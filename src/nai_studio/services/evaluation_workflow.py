# -*- coding: utf-8 -*-
"""평가 장부와 생성 결과 파일을 함께 갱신하는 응용 workflow."""

from __future__ import annotations

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
    "delete_outputs_workflow",
    "save_mosaic_workflow",
    "save_picks_workflow",
    "strip_metadata_workflow",
]
