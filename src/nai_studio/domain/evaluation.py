# -*- coding: utf-8 -*-
"""생성 결과와 지식 자산의 평가·생명주기 공통 계약.

평가는 원 결과나 자산을 직접 변경하지 않는다. 승격은 의사결정 기록만 만들고,
서로 다른 평가를 합칠 때는 원본 snapshot과 실제 충돌을 함께 반환한다.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Mapping, Sequence


EVALUATION_SCHEMA = "nai-evaluation/v1"
PROMOTION_SCHEMA = "nai-promotion-decision/v1"
REVIEW_STATES = ("candidate", "confirmed", "shared", "archived")
PROMOTION_TARGETS = ("style", "character", "reference", "vibe")

_STATE_ORDER = {name: index for index, name in enumerate(REVIEW_STATES)}
_FINGERPRINT_IGNORED = {
    "schema", "id", "fingerprint", "created_at", "updated_at", "runtime",
}


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _refs(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain non-empty string refs")
        if item not in result:
            result.append(item)
    return result


def _tags(value: Any) -> list[str]:
    return _refs(value, "tags")


def _rating(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("rating must be a number from 0 to 5 or null")
    if not math.isfinite(float(value)) or not 0 <= value <= 5:
        raise ValueError("rating must be between 0 and 5")
    return deepcopy(value)


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return result


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field} must be a non-negative integer") from exc
    if result < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return result


def _stable_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("evaluation must contain JSON-compatible values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _fixed_board(value: Any) -> dict:
    raw = _mapping(value, "fixed_board")
    boards = _refs(raw.get("boards"), "fixed_board.boards")
    result = deepcopy(raw)
    result["boards"] = boards
    result["member"] = bool(raw.get("member", bool(boards)))
    return result


def _blind(value: Any) -> dict:
    raw = _mapping(value, "blind")
    result = deepcopy(raw)
    result["enabled"] = bool(raw.get("enabled", False))
    result["revealed"] = bool(raw.get("revealed", False))
    result["matches"] = _nonnegative_int(raw.get("matches", 0), "blind.matches")
    return result


def _elo(value: Any) -> dict:
    raw = _mapping(value, "elo")
    result = deepcopy(raw)
    result["rating"] = _number(raw.get("rating", 1500.0), "elo.rating")
    result["matches"] = _nonnegative_int(raw.get("matches", 0), "elo.matches")
    result["wins"] = _nonnegative_int(raw.get("wins", 0), "elo.wins")
    result["losses"] = _nonnegative_int(raw.get("losses", 0), "elo.losses")
    return result


def _canonical_without_identity(value: Mapping[str, Any] | None) -> dict:
    raw = _mapping(value, "evaluation")
    review_state = raw.get("review_state", "candidate")
    if review_state not in REVIEW_STATES:
        raise ValueError(
            "review_state must be one of: " + ", ".join(REVIEW_STATES)
        )
    memo = raw.get("memo", "")
    if not isinstance(memo, str):
        raise TypeError("memo must be a string")

    result = {
        "schema": EVALUATION_SCHEMA,
        "favorite": bool(raw.get("favorite", False)),
        "rating": _rating(raw.get("rating")),
        "memo": memo,
        "tags": _tags(raw.get("tags")),
        "review_state": review_state,
        "fixed_board": _fixed_board(raw.get("fixed_board")),
        "blind": _blind(raw.get("blind")),
        "elo": _elo(raw.get("elo")),
        "evidence_refs": _refs(raw.get("evidence_refs"), "evidence_refs"),
        "result_refs": _refs(raw.get("result_refs"), "result_refs"),
        "asset_refs": _refs(raw.get("asset_refs"), "asset_refs"),
    }
    for key, item in raw.items():
        if key not in result and key not in {"id", "fingerprint"}:
            result[key] = deepcopy(item)
    return result


def _identity_content(value: Mapping[str, Any]) -> dict:
    raw = _mapping(value, "evaluation")
    return {
        "evidence_refs": sorted(_refs(
            raw.get("evidence_refs"),
            "evidence_refs",
        )),
        "result_refs": sorted(_refs(raw.get("result_refs"), "result_refs")),
        "asset_refs": sorted(_refs(raw.get("asset_refs"), "asset_refs")),
        "subject": deepcopy(raw.get("subject")),
    }


def evaluation_id(value: Mapping[str, Any] | None) -> str:
    raw = _mapping(value, "evaluation")
    if raw.get("id") not in (None, ""):
        return str(raw["id"])
    return "evaluation:" + _stable_hash(_identity_content(raw))[:32]


def fingerprint_evaluation(value: Mapping[str, Any] | None) -> str:
    data = _canonical_without_identity(value)
    return _stable_hash({
        key: item
        for key, item in data.items()
        if key not in _FINGERPRINT_IGNORED
    })


def canonical_evaluation(value: Mapping[str, Any] | None) -> dict:
    """평가값, 참조, blind/ELO 상태와 미래 필드를 보존한 공통 레코드."""
    result = _canonical_without_identity(value)
    result["id"] = evaluation_id(value)
    result["fingerprint"] = fingerprint_evaluation(result)
    return result


def record_rating(
    value: Mapping[str, Any],
    rating: int | float,
) -> dict:
    """평가 사본에 별점을 기록하고 이전 값을 이력에 보존."""
    result = canonical_evaluation(value)
    normalized = _rating(rating)
    history = deepcopy(result.get("rating_history") or [])
    if not isinstance(history, list):
        raise TypeError("rating_history must be a list")
    history.append({
        "rating": normalized,
        "previous": deepcopy(result.get("rating")),
    })
    result["rating"] = normalized
    result["rating_history"] = history
    return canonical_evaluation(result)


def record_blind_match(
    winner: Mapping[str, Any],
    loser: Mapping[str, Any],
    k_factor: int | float = 32,
) -> dict:
    """두 평가 사본의 ELO와 match 수를 한 번의 blind 결과로 갱신."""
    winning = canonical_evaluation(winner)
    losing = canonical_evaluation(loser)
    if winning["id"] == losing["id"]:
        raise ValueError("winner and loser must be different evaluation subjects")
    k = _number(k_factor, "k_factor", minimum=0.0000001)
    winner_before = winning["elo"]["rating"]
    loser_before = losing["elo"]["rating"]
    expected_winner = 1 / (1 + 10 ** ((loser_before - winner_before) / 400))
    delta = k * (1 - expected_winner)

    winning["elo"]["rating"] = round(winner_before + delta, 6)
    losing["elo"]["rating"] = round(loser_before - delta, 6)
    for item in (winning, losing):
        item["elo"]["matches"] += 1
        item["blind"]["enabled"] = True
        item["blind"]["matches"] += 1
    winning["elo"]["wins"] += 1
    losing["elo"]["losses"] += 1
    winning = canonical_evaluation(winning)
    losing = canonical_evaluation(losing)
    match = {
        "id": "blind-match:" + _stable_hash({
            "winner": winning["id"],
            "loser": losing["id"],
            "winner_match": winning["elo"]["matches"],
            "loser_match": losing["elo"]["matches"],
        })[:32],
        "winner_id": winning["id"],
        "loser_id": losing["id"],
        "k_factor": k,
        "before": {
            "winner": winner_before,
            "loser": loser_before,
        },
        "after": {
            "winner": winning["elo"]["rating"],
            "loser": losing["elo"]["rating"],
        },
    }
    return {"winner": winning, "loser": losing, "match": match}


def promote_result(
    value: Mapping[str, Any],
    target: str,
    *,
    result_ref: str | None = None,
) -> dict:
    """자동 반영 없이 결과→자산 승격 제안과 원 결과 계보만 만든다."""
    evaluation = canonical_evaluation(value)
    if target not in PROMOTION_TARGETS:
        raise ValueError(
            "promotion target must be one of: " + ", ".join(PROMOTION_TARGETS)
        )
    available = evaluation["result_refs"]
    if result_ref is None:
        if len(available) != 1:
            raise ValueError(
                "result_ref is required unless evaluation has exactly one result"
            )
        result_ref = available[0]
    if not isinstance(result_ref, str) or not result_ref.strip():
        raise ValueError("result_ref must be a non-empty string")
    if result_ref not in available:
        raise ValueError("result_ref must belong to the evaluation")

    lineage = {
        "evaluation_id": evaluation["id"],
        "evaluation_fingerprint": evaluation["fingerprint"],
        "source_result_ref": result_ref,
        "evidence_refs": deepcopy(evaluation["evidence_refs"]),
        "asset_refs": deepcopy(evaluation["asset_refs"]),
    }
    identity = {"target": target, "lineage": lineage}
    return {
        "schema": PROMOTION_SCHEMA,
        "id": "promotion:" + _stable_hash(identity)[:32],
        "target": target,
        "status": "proposed",
        "automatic": False,
        "lineage": lineage,
    }


def _union(values: Sequence[Sequence[str]]) -> list[str]:
    result = []
    for group in values:
        for item in group:
            if item not in result:
                result.append(deepcopy(item))
    return result


def _conflict(path: str, sources: Sequence[dict], field: str) -> dict | None:
    entries = [
        {
            "evaluation_id": item["id"],
            "fingerprint": item["fingerprint"],
            "value": deepcopy(item.get(field)),
        }
        for item in sources
    ]
    distinct = {
        json.dumps(entry["value"], ensure_ascii=False, sort_keys=True)
        for entry in entries
    }
    if len(distinct) < 2:
        return None
    return {"path": path, "values": entries}


def merge_evaluations(*values: Mapping[str, Any]) -> dict:
    """평가들을 합치되 모든 원본 snapshot과 실제 값 충돌을 반환."""
    if not values:
        raise ValueError("at least one evaluation is required")
    sources = [canonical_evaluation(value) for value in values]
    merged = deepcopy(sources[0])
    merged["favorite"] = any(item["favorite"] for item in sources)
    merged["tags"] = _union([item["tags"] for item in sources])
    merged["evidence_refs"] = _union([
        item["evidence_refs"] for item in sources
    ])
    merged["result_refs"] = _union([item["result_refs"] for item in sources])
    merged["asset_refs"] = _union([item["asset_refs"] for item in sources])
    merged["fixed_board"] = deepcopy(sources[0]["fixed_board"])
    merged["fixed_board"]["boards"] = _union([
        item["fixed_board"]["boards"] for item in sources
    ])
    merged["fixed_board"]["member"] = any(
        item["fixed_board"]["member"] for item in sources
    )
    merged["review_state"] = max(
        (item["review_state"] for item in sources),
        key=_STATE_ORDER.get,
    )
    merged["memo_entries"] = [
        {
            "evaluation_id": item["id"],
            "fingerprint": item["fingerprint"],
            "memo": item["memo"],
        }
        for item in sources
        if item["memo"]
    ]
    merged["rating_entries"] = [
        {
            "evaluation_id": item["id"],
            "fingerprint": item["fingerprint"],
            "rating": item["rating"],
        }
        for item in sources
        if item["rating"] is not None
    ]
    merged["merged_sources"] = deepcopy(sources)

    conflicts = []
    for field in (
        "favorite", "rating", "memo", "review_state", "blind", "elo",
        "fixed_board",
    ):
        conflict = _conflict(field, sources, field)
        if conflict:
            conflicts.append(conflict)
    # 동일 평가 대상의 ID를 유지하고, 서로 다른 대상을 합친 경우에는 합성 대상
    # ID를 만든다. 원본 ID는 merged_sources에 모두 남는다.
    source_ids = {item["id"] for item in sources}
    if len(source_ids) > 1:
        merged["id"] = "evaluation:merged:" + _stable_hash(
            sorted(source_ids)
        )[:24]
    merged = canonical_evaluation(merged)
    return {"evaluation": merged, "conflicts": conflicts}
