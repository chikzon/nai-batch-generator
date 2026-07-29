# -*- coding: utf-8 -*-
"""기존 선별/비교 결과를 공통 평가와 append-only 이벤트로 잇는다.

현재 ``선별.json``에는 picked·fav·folders·ranks·ratings·elo·elo_matches·tags가
있다. 메모·생명주기·승격 이력은 없으므로 기존 map을 추측해 덮지 않고, 기존
정규화가 보존하는 ``evaluation_events`` 배열에만 새 의사결정을 덧붙인다.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.nai_studio.domain.evaluation import (
    REVIEW_STATES,
    canonical_evaluation,
    promote_result,
    record_blind_match,
)


EVALUATION_EVENT_SCHEMA = "nai-evaluation-event/v1"
_STATE_ORDER = {name: index for index, name in enumerate(REVIEW_STATES)}


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _rows(value: Any, field: str) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [deepcopy(dict(value))]
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a mapping or list")
    if any(not isinstance(item, Mapping) for item in value):
        raise TypeError(f"{field} must contain mappings")
    return [deepcopy(dict(item)) for item in value]


def _path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def _stable_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("evaluation bridge values must be JSON-compatible") from exc
    return hashlib.sha256(encoded).hexdigest()


def _union(*groups: Sequence[Any]) -> list:
    output = []
    for group in groups:
        for item in group or ():
            if item not in output:
                output.append(deepcopy(item))
    return output


def _memo_entries(
    path: str,
    picks: Mapping[str, Any],
    result: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
) -> list[dict]:
    entries = []
    for source, value in (
        ("picks.memos", (picks.get("memos") or {}).get(path)),
        ("picks.notes", (picks.get("notes") or {}).get(path)),
        ("result", result.get("memo", result.get("note"))),
        ("comparison-manifest", manifest_record.get(
            "memo", manifest_record.get("note")
        )),
    ):
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise TypeError(f"{source} memo must be a string")
        entry = {"source": source, "memo": value}
        if entry not in entries:
            entries.append(entry)
    return entries


def _manifest_records(
    manifests: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict], list[dict]]:
    by_path = {}
    issues = []
    for manifest_index, manifest in enumerate(manifests):
        completed = manifest.get("completed")
        if not isinstance(completed, Mapping):
            continue
        for job_key, raw in completed.items():
            if not isinstance(raw, Mapping):
                continue
            path = _path(raw.get("file"))
            if not path:
                continue
            record = deepcopy(dict(raw))
            record["_lineage"] = {
                "kind": "comparison",
                "manifest_index": manifest_index,
                "manifest_signature": str(manifest.get("signature") or ""),
                "manifest_folder": _path(manifest.get("folder")),
                "job_key": str(job_key),
                "mode": str(manifest.get("mode") or ""),
                "style_id": deepcopy(raw.get("style_id")),
                "character_id": deepcopy(raw.get("character_id")),
                "seed": deepcopy(raw.get("seed")),
                "seed_index": deepcopy(raw.get("seed_index")),
                "width": deepcopy(raw.get("width")),
                "height": deepcopy(raw.get("height")),
            }
            if path in by_path and by_path[path] != record:
                issues.append({
                    "code": "duplicate-result-manifest",
                    "path": path,
                    "kept": deepcopy(by_path[path].get("_lineage")),
                    "other": deepcopy(record.get("_lineage")),
                })
                continue
            by_path[path] = record
    return by_path, issues


def _evaluation_paths(
    source: Mapping[str, Any],
    result_by_path: Mapping[str, Any],
    manifest_by_path: Mapping[str, Any],
) -> list[str]:
    paths = []
    for key in ("picked", "fav"):
        paths.extend(_path(item) for item in (source.get(key) or []))
    for key in (
        "ranks", "ratings", "elo", "elo_matches", "tags", "memos", "notes",
        "review_states",
    ):
        paths.extend(_path(item) for item in (source.get(key) or {}))
    for members in (source.get("folders") or {}).values():
        paths.extend(_path(item) for item in (members or []))
    return list(dict.fromkeys(
        item for item in [*paths, *result_by_path, *manifest_by_path] if item
    ))


def _rating_for_evaluation(
    path: str,
    source: Mapping[str, Any],
    result: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    issues: list,
) -> tuple[Any, list[dict]]:
    entries = []
    for value_source, value in (
        ("picks.ratings", (source.get("ratings") or {}).get(path)),
        ("result", result.get("rating")),
        ("comparison-manifest", manifest_record.get("rating")),
    ):
        if value is not None:
            entries.append({"source": value_source, "rating": deepcopy(value)})
    values = list(dict.fromkeys(entry["rating"] for entry in entries))
    if len(values) > 1:
        issues.append({
            "code": "rating-conflict", "path": path, "values": deepcopy(entries)
        })
    return (entries[0]["rating"] if entries else None), entries


def _review_state_for_evaluation(
    path: str,
    source: Mapping[str, Any],
    result: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    issues: list,
) -> tuple[str, list[dict]]:
    states = []
    for state_source, state in (
        ("picks.review_states", (source.get("review_states") or {}).get(path)),
        ("result", result.get("review_state")),
        ("comparison-manifest", manifest_record.get("review_state")),
    ):
        if state is None:
            continue
        if state not in REVIEW_STATES:
            raise ValueError(f"invalid review state for {path}: {state}")
        states.append({"source": state_source, "state": state})
    values = list(dict.fromkeys(item["state"] for item in states))
    if len(values) > 1:
        issues.append({
            "code": "review-state-conflict", "path": path,
            "values": deepcopy(states),
        })
    return (max(values, key=_STATE_ORDER.get) if values else "candidate"), states


def _project_evaluation(
    path: str,
    source: Mapping[str, Any],
    result: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    folders: Mapping[str, set[str]],
    picked: set[str],
    favorites: set[str],
    issues: list,
) -> dict:
    memos = _memo_entries(path, source, result, manifest_record)
    tags = _union(
        (source.get("tags") or {}).get(path) or [],
        result.get("tags") or [], manifest_record.get("tags") or [],
    )
    boards = [name for name, members in folders.items() if path in members]
    rating, rating_entries = _rating_for_evaluation(
        path, source, result, manifest_record, issues
    )
    review_state, states = _review_state_for_evaluation(
        path, source, result, manifest_record, issues
    )
    elo_map = source.get("elo") or {}
    matches_map = source.get("elo_matches") or {}
    return canonical_evaluation({
        "subject": {"kind": "generation-result", "path": path},
        "favorite": path in favorites, "rating": rating,
        "memo": memos[0]["memo"] if memos else "",
        "memo_entries": memos, "rating_entries": rating_entries,
        "tags": tags, "review_state": review_state,
        "review_state_entries": states,
        "fixed_board": {"member": path in picked or bool(boards), "boards": boards},
        "blind": {
            "enabled": path in elo_map or path in matches_map,
            "revealed": True, "matches": int(matches_map.get(path) or 0),
        },
        "elo": {
            "rating": float(elo_map.get(path, 1000.0)),
            "matches": int(matches_map.get(path) or 0), "wins": 0, "losses": 0,
        },
        "evidence_refs": _union(
            result.get("evidence_refs") or [],
            manifest_record.get("evidence_refs") or [],
        ),
        "result_refs": [f"result:{path}"],
        "asset_refs": _union(
            result.get("asset_refs") or [], manifest_record.get("asset_refs") or []
        ),
        "comparison_lineage": deepcopy(manifest_record.get("_lineage") or {}),
        "result_record": deepcopy(result),
        "legacy_rank": deepcopy((source.get("ranks") or {}).get(path)),
    })


def project_legacy_evaluations(
    picks: Mapping[str, Any],
    *,
    comparison_manifests: Sequence[Mapping[str, Any]] = (),
    result_records: Sequence[Mapping[str, Any]] = (),
) -> dict:
    """선별 장부·비교 manifest·결과 레코드를 경로별 공통 평가로 투영."""
    source = _mapping(picks, "picks")
    manifest_by_path, issues = _manifest_records(
        _rows(comparison_manifests, "comparison_manifests")
    )
    result_by_path = {}
    for record in _rows(result_records, "result_records"):
        path = _path(record.get("path", record.get("file")))
        if path:
            result_by_path[path] = record
    picked = {_path(item) for item in (source.get("picked") or [])}
    favorites = {_path(item) for item in (source.get("fav") or [])}
    folders = {
        str(name): {_path(item) for item in (members or [])}
        for name, members in (source.get("folders") or {}).items()
    }
    evaluations = [
        _project_evaluation(
            path, source, result_by_path.get(path, {}),
            manifest_by_path.get(path, {}), folders, picked, favorites, issues,
        )
        for path in _evaluation_paths(source, result_by_path, manifest_by_path)
    ]
    return {"evaluations": evaluations, "issues": issues}


def _single_result_ref(evaluation: Mapping[str, Any]) -> str:
    refs = canonical_evaluation(evaluation)["result_refs"]
    if len(refs) != 1 or not refs[0].startswith("result:"):
        raise ValueError("evaluation must have exactly one legacy result ref")
    return refs[0]


def present_blind_pair(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    excluded_pairs: Sequence[Sequence[str]] = (),
) -> dict:
    """판수가 가장 적고 ELO가 가까운 두 결과를 이름/평가 없이 제시."""
    values = [canonical_evaluation(item) for item in evaluations]
    if len({item["id"] for item in values}) < 2:
        raise ValueError("blind comparison requires two different evaluations")
    excluded = {
        frozenset(str(value) for value in pair)
        for pair in excluded_pairs
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    }
    ordered = sorted(
        values,
        key=lambda item: (
            item["blind"]["matches"],
            item["elo"]["rating"],
            item["id"],
        ),
    )
    first = ordered[0]
    opponents = sorted(
        (
            item for item in ordered[1:]
            if frozenset((first["id"], item["id"])) not in excluded
        ),
        key=lambda item: (
            abs(item["elo"]["rating"] - first["elo"]["rating"]),
            item["blind"]["matches"],
            item["id"],
        ),
    )
    if not opponents:
        raise ValueError("no blind pair remains after exclusions")
    second = opponents[0]
    return {
        "blind": True,
        "hidden_fields": [
            "name", "filename", "source", "favorite", "rating", "tags",
            "review_state", "elo",
        ],
        "a": {
            "evaluation_id": first["id"],
            "result_ref": _single_result_ref(first),
        },
        "b": {
            "evaluation_id": second["id"],
            "result_ref": _single_result_ref(second),
        },
    }


def _event(kind: str, payload: Mapping[str, Any]) -> dict:
    data = {
        "schema": EVALUATION_EVENT_SCHEMA,
        "kind": kind,
        "payload": deepcopy(dict(payload)),
    }
    data["id"] = "evaluation-event:" + _stable_hash(data)[:32]
    return data


def blind_match_event(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    k_factor: int | float = 24,
    outcome: str = "first",
) -> dict:
    """기존 ELO K=24와 승/패/무승부를 기록한 append-only 이벤트."""
    if outcome not in ("first", "second", "tie"):
        raise ValueError("outcome must be first, second, or tie")
    if (
        isinstance(k_factor, bool)
        or not isinstance(k_factor, (int, float))
        or not math.isfinite(float(k_factor))
        or float(k_factor) <= 0
    ):
        raise ValueError("k_factor must be a positive finite number")
    if outcome == "first":
        result = record_blind_match(first, second, k_factor=k_factor)
        first_value, second_value = result["winner"], result["loser"]
        match = result["match"]
    elif outcome == "second":
        result = record_blind_match(second, first, k_factor=k_factor)
        first_value, second_value = result["loser"], result["winner"]
        match = result["match"]
    else:
        first_value = canonical_evaluation(first)
        second_value = canonical_evaluation(second)
        if first_value["id"] == second_value["id"]:
            raise ValueError("blind match subjects must be different")
        first_before = first_value["elo"]["rating"]
        second_before = second_value["elo"]["rating"]
        expected_first = 1 / (
            1 + 10 ** ((second_before - first_before) / 400)
        )
        delta = float(k_factor) * (0.5 - expected_first)
        first_value["elo"]["rating"] = round(first_before + delta, 6)
        second_value["elo"]["rating"] = round(second_before - delta, 6)
        for value in (first_value, second_value):
            value["elo"]["matches"] += 1
            value["blind"]["enabled"] = True
            value["blind"]["matches"] += 1
        first_value = canonical_evaluation(first_value)
        second_value = canonical_evaluation(second_value)
        match = {
            "id": "blind-match:" + _stable_hash({
                "first": first_value["id"],
                "second": second_value["id"],
                "first_match": first_value["elo"]["matches"],
                "second_match": second_value["elo"]["matches"],
                "outcome": "tie",
            })[:32],
            "first_id": first_value["id"],
            "second_id": second_value["id"],
            "outcome": "tie",
            "k_factor": float(k_factor),
            "before": {"first": first_before, "second": second_before},
            "after": {
                "first": first_value["elo"]["rating"],
                "second": second_value["elo"]["rating"],
            },
        }
    first_ref = _single_result_ref(first_value)
    second_ref = _single_result_ref(second_value)
    return _event("blind-match", {
        "first_id": first_value["id"],
        "second_id": second_value["id"],
        "first_result_ref": first_ref,
        "second_result_ref": second_ref,
        "outcome": outcome,
        "k_factor": float(k_factor),
        "match": deepcopy(match),
        "legacy_projection": {
            first_ref.removeprefix("result:"): {
                "elo": first_value["elo"]["rating"],
                "elo_matches": first_value["elo"]["matches"],
            },
            second_ref.removeprefix("result:"): {
                "elo": second_value["elo"]["rating"],
                "elo_matches": second_value["elo"]["matches"],
            },
        },
    })


def fixed_board_event(
    evaluation: Mapping[str, Any],
    board: str,
    *,
    member: bool = True,
) -> dict:
    value = canonical_evaluation(evaluation)
    board = str(board or "").strip()
    if not board:
        raise ValueError("board name is required")
    return _event("fixed-board", {
        "evaluation_id": value["id"],
        "result_ref": _single_result_ref(value),
        "board": board,
        "member": bool(member),
        "base_fingerprint": value["fingerprint"],
    })


def lifecycle_event(
    evaluation: Mapping[str, Any],
    state: str,
) -> dict:
    value = canonical_evaluation(evaluation)
    if state not in REVIEW_STATES:
        raise ValueError(
            "lifecycle state must be one of: " + ", ".join(REVIEW_STATES)
        )
    return _event("lifecycle", {
        "evaluation_id": value["id"],
        "result_ref": _single_result_ref(value),
        "from": value["review_state"],
        "to": state,
        "base_fingerprint": value["fingerprint"],
    })


def promotion_event(
    evaluation: Mapping[str, Any],
    target: str,
) -> dict:
    value = canonical_evaluation(evaluation)
    decision = promote_result(
        value,
        target,
        result_ref=_single_result_ref(value),
    )
    return _event("promotion-proposed", {
        "evaluation_id": value["id"],
        "decision": decision,
        "base_fingerprint": value["fingerprint"],
    })


def append_evaluation_events(
    picks: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> dict:
    """기존 선별 map은 그대로 두고 event 배열 뒤에 새 ID만 덧붙인다."""
    result = _mapping(picks, "picks")
    current = result.get("evaluation_events")
    if current is None:
        current = []
    if not isinstance(current, list):
        raise TypeError("evaluation_events must be a list")
    output = deepcopy(current)
    seen = {
        str(item.get("id"))
        for item in output
        if isinstance(item, Mapping) and item.get("id")
    }
    appended = []
    duplicates = []
    for event in events:
        if not isinstance(event, Mapping):
            raise TypeError("each evaluation event must be a mapping")
        item = deepcopy(dict(event))
        if (
            item.get("schema") != EVALUATION_EVENT_SCHEMA
            or not item.get("id")
            or not item.get("kind")
            or not isinstance(item.get("payload"), Mapping)
        ):
            raise ValueError("invalid evaluation event")
        event_id = str(item["id"])
        if event_id in seen:
            duplicates.append(event_id)
            continue
        seen.add(event_id)
        output.append(item)
        appended.append(event_id)
    result["evaluation_events"] = output
    return {
        "picks": result,
        "appended": appended,
        "duplicates": duplicates,
        "append_only": True,
    }
