# -*- coding: utf-8 -*-
"""평가 장부와 생성 결과 파일을 함께 갱신하는 응용 workflow."""

from __future__ import annotations

import math
from typing import Any


PICK_FIELDS = (
    "picked",
    "fav",
    "folders",
    "ranks",
    "ratings",
    "elo",
    "elo_matches",
    "tags",
    "memos",
    "review_states",
)


def normalize_picks(data: dict) -> dict:
    """선별 장부 값을 작고 유한한 JSON 값으로 정규화한다."""
    data = dict(data or {})
    for key in ("picked", "fav"):
        data[key] = list(dict.fromkeys(
            str(path).replace("\\", "/")
            for path in (data.get(key) or [])
            if str(path).strip()
        ))
    folders = {}
    for name, paths in (data.get("folders") or {}).items():
        clean_name = str(name).strip()[:40]
        if not clean_name or not isinstance(paths, list):
            continue
        folders[clean_name] = list(dict.fromkeys([
            *folders.get(clean_name, []),
            *(
                str(path).replace("\\", "/")
                for path in paths
                if str(path).strip()
            ),
        ]))
    data["folders"] = folders
    data["ranks"] = {
        str(path).replace("\\", "/"): max(1, int(rank))
        for path, rank in (data.get("ranks") or {}).items()
        if str(path).strip() and str(rank).lstrip("-").isdigit()
    }
    data["ratings"] = {
        str(path).replace("\\", "/"): max(1, min(5, int(score)))
        for path, score in (data.get("ratings") or {}).items()
        if (
            str(path).strip()
            and str(score).isdigit()
            and int(score) > 0
        )
    }
    elo = {}
    for path, score in (data.get("elo") or {}).items():
        try:
            number = float(score)
        except (TypeError, ValueError, OverflowError):
            continue
        if str(path).strip() and math.isfinite(number):
            elo[str(path).replace("\\", "/")] = round(
                max(0.0, min(3000.0, number)), 1
            )
    data["elo"] = elo
    data["elo_matches"] = {
        str(path).replace("\\", "/"): max(
            0, min(1_000_000, int(count))
        )
        for path, count in (data.get("elo_matches") or {}).items()
        if str(path).strip() and str(count).isdigit()
    }
    tags = {}
    for path, values in (data.get("tags") or {}).items():
        if not str(path).strip() or not isinstance(values, list):
            continue
        cleaned = list(dict.fromkeys(
            str(tag).strip()[:40]
            for tag in values
            if str(tag).strip()
        ))[:12]
        if cleaned:
            tags[str(path).replace("\\", "/")] = cleaned
    data["tags"] = tags
    data["memos"] = {
        str(path).replace("\\", "/"): str(memo)
        for path, memo in (data.get("memos") or {}).items()
        if str(path).strip() and isinstance(memo, str) and memo
    }
    allowed_states = {"candidate", "confirmed", "shared", "archived"}
    data["review_states"] = {
        str(path).replace("\\", "/"): str(state)
        for path, state in (data.get("review_states") or {}).items()
        if str(path).strip() and str(state) in allowed_states
    }
    return data


def apply_evaluation_action_workflow(
    data: dict,
    *,
    lock: Any,
    load_picks: Any,
    save_picks: Any,
    project_evaluations: Any,
    blind_event: Any,
    fixed_board_event: Any,
    lifecycle_event: Any,
    promotion_event: Any,
    append_events: Any,
) -> dict:
    """평가 결정을 선별 장부와 append-only 사건에 한 번에 기록한다."""
    data = data if isinstance(data, dict) else {}
    action = str(data.get("action") or "")
    with lock:
        picks = load_picks()
        decision_id = str(data.get("decision_id") or "").strip()
        prior_decisions = picks.get("evaluation_decision_ids")
        if not isinstance(prior_decisions, list):
            prior_decisions = []
        if action == "blind-match" and not decision_id:
            raise ValueError("블라인드 비교 결정 식별자가 필요합니다.")
        if action == "blind-match" and decision_id in prior_decisions:
            return {
                "ok": True,
                "duplicate": True,
                "appended": [],
                "picks": {
                    "elo": picks.get("elo", {}),
                    "elo_matches": picks.get("elo_matches", {}),
                    "folders": picks.get("folders", {}),
                    "review_states": picks.get("review_states", {}),
                },
            }
        paths = [
            str(value or "").replace("\\", "/")
            for value in (data.get("paths") or [])
            if str(value or "").strip()
        ]
        projection = project_evaluations(
            picks,
            result_records=[{"path": path} for path in paths],
        )
        by_path = {
            str((item.get("subject") or {}).get("path") or ""): item
            for item in projection["evaluations"]
        }
        events = []
        if action == "blind-match":
            if len(paths) != 2 or paths[0] == paths[1]:
                raise ValueError(
                    "블라인드 비교에는 서로 다른 결과 두 개가 필요합니다."
                )
            events.append(blind_event(
                by_path[paths[0]],
                by_path[paths[1]],
                outcome=str(data.get("outcome") or "first"),
                k_factor=24,
            ))
            for path, values in (
                events[0].get("payload", {}).get(
                    "legacy_projection"
                )
                or {}
            ).items():
                picks.setdefault("elo", {})[path] = values["elo"]
                picks.setdefault("elo_matches", {})[path] = values[
                    "elo_matches"
                ]
        elif action == "fixed-board":
            if not paths:
                raise ValueError("고정 비교판에는 결과가 필요합니다.")
            board = str(data.get("board") or "").strip()[:40]
            member = bool(data.get("member", True))
            events = [
                fixed_board_event(by_path[path], board, member=member)
                for path in paths
            ]
            members = picks.setdefault("folders", {}).setdefault(
                board, []
            )
            if member:
                members[:] = list(dict.fromkeys([*members, *paths]))
            else:
                picks["folders"][board] = [
                    item for item in members if item not in set(paths)
                ]
        elif action == "lifecycle":
            if len(paths) != 1:
                raise ValueError("생명주기 변경에는 결과 한 개가 필요합니다.")
            state = str(data.get("state") or "")
            events.append(lifecycle_event(by_path[paths[0]], state))
            picks.setdefault("review_states", {})[paths[0]] = state
        elif action == "promotion":
            if len(paths) != 1:
                raise ValueError("승격 제안에는 결과 한 개가 필요합니다.")
            events.append(
                promotion_event(
                    by_path[paths[0]], str(data.get("target") or "")
                )
            )
        else:
            raise ValueError("지원하지 않는 평가 작업입니다.")
        if action == "blind-match" and decision_id:
            picks["evaluation_decision_ids"] = [
                *prior_decisions,
                decision_id,
            ]
        appended = append_events(picks, events)
        saved = save_picks(appended["picks"])
    return {
        "ok": True,
        "event": events[0] if len(events) == 1 else None,
        "events": events,
        "appended": appended["appended"],
        "duplicate": bool(appended["duplicates"]),
        "picks": {
            "elo": saved.get("elo", {}),
            "elo_matches": saved.get("elo_matches", {}),
            "folders": saved.get("folders", {}),
            "review_states": saved.get("review_states", {}),
        },
    }


def save_picks_workflow(operations: Any, data: dict) -> dict:
    """전달된 장부 필드만 병합해 다른 화면의 최신 선별 상태를 보존한다."""
    with operations.picks_lock:
        current = operations.load_picks()
        for key in PICK_FIELDS:
            if key in data:
                current[key] = data[key]
        saved = operations.save_picks(current)
    return {"ok": True, "picks": saved}


def _remove_paths_from_picks(picks: dict, gone: set[str]) -> None:
    for key in ("picked", "fav"):
        picks[key] = [
            item for item in picks.get(key, []) if item not in gone
        ]
    for key in (
        "ranks",
        "ratings",
        "elo",
        "elo_matches",
        "tags",
        "memos",
        "review_states",
    ):
        picks[key] = {
            item: value
            for item, value in picks.get(key, {}).items()
            if item not in gone
        }
    picks["folders"] = {
        name: [item for item in paths if item not in gone]
        for name, paths in picks.get("folders", {}).items()
    }


def delete_outputs_workflow(
    application: Any,
    operations: Any,
    data: dict,
) -> dict:
    """파일을 휴지통에 옮긴 뒤 성공한 경로만 평가 장부에서 제거한다."""
    keep = set(data.get("keep") or [])
    targets = [
        str(item)
        for item in (data.get("targets") or [])
        if str(item) not in keep
    ]
    result = operations.trash_outputs(application.cfg, targets, keep)
    if result["deleted"]:
        gone = set(result.get("paths") or [])
        with operations.picks_lock:
            picks = operations.load_picks()
            _remove_paths_from_picks(picks, gone)
            operations.save_picks(picks)
    return {"ok": True, **result}


def save_mosaic_workflow(
    application: Any,
    operations: Any,
    body: bytes,
) -> dict:
    directory = operations.output_subdir(application.cfg, "모자이크")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{len(list(directory.glob('*.png'))) + 1:04d}.png"
    operations.atomic_write(path, body, keep_backup=False)
    return {"ok": True, "file": path.name, "bytes": len(body)}


def strip_metadata_workflow(
    application: Any,
    operations: Any,
    body: bytes,
    *,
    filename: str,
    max_side: int,
    quality: int,
    force_webp: bool,
) -> dict:
    return operations.strip_and_save(
        body,
        filename,
        max_side=max_side,
        quality=quality,
        force_webp=force_webp,
        cfg=application.cfg,
    )


__all__ = [
    "apply_evaluation_action_workflow",
    "delete_outputs_workflow",
    "normalize_picks",
    "save_mosaic_workflow",
    "save_picks_workflow",
    "strip_metadata_workflow",
]
