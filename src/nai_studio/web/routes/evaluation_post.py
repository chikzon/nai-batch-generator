# -*- coding: utf-8 -*-
"""작가 평가·결과 선별·이미지 정리 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from src.nai_studio.services.evaluation_workflow import (
    delete_outputs_workflow,
    save_mosaic_workflow,
    save_picks_workflow,
    strip_metadata_workflow,
)


@dataclass(frozen=True)
class EvaluationPostOperations:
    artist_workspace: Any
    load_ratings: Any
    rate_artist: Any
    apply_evaluation: Any
    picks_lock: Any
    load_picks: Any
    save_picks: Any
    trash_outputs: Any
    restore_trash: Any
    output_subdir: Any
    atomic_write: Any
    strip_and_save: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _too_large(request: Any, body: bytes, limit: int) -> bool:
    if len(body or b"") <= limit:
        return False
    request._json({"ok": False, "error": "요청이 너무 큽니다."})
    return True


def _artist_workspace(
    request: Any, operations: EvaluationPostOperations, body: bytes
) -> None:
    if not _too_large(request, body, 128 * 1024):
        request._json(operations.artist_workspace(_json_body(body)))


def _rate(
    request: Any, operations: EvaluationPostOperations, body: bytes
) -> None:
    if _too_large(request, body, 64 * 1024):
        return
    data = json.loads(body or b"{}")
    if not isinstance(data, dict):
        request._json({"ok": False, "error": "잘못된 형식"})
        return
    artist = str(data.get("artist", ""))
    if not data.get("list") and len(artist) > 200:
        request._json({"ok": False, "error": "작가 이름이 너무 깁니다."})
        return
    if data.get("list"):
        request._json({"ok": True, "ratings": operations.load_ratings()})
        return
    rating = operations.rate_artist(
        artist,
        **{
            key: data[key]
            for key in ("score", "fav", "block", "memo")
            if key in data
        },
    )
    request._json({"ok": True, "artist": artist.lower(), "rating": rating})


def _evaluation(
    request: Any, operations: EvaluationPostOperations, body: bytes
) -> None:
    if not _too_large(request, body, 4 * 1024 * 1024):
        request._json(operations.apply_evaluation(_json_body(body)))


def handle_evaluation_post(
    request: Any,
    application: Any,
    operations: EvaluationPostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/artist_workspace"):
            _artist_workspace(request, operations, body)
        elif request.path.startswith("/api/rate"):
            _rate(request, operations, body)
        elif request.path.startswith("/api/evaluation_action"):
            _evaluation(request, operations, body)
        elif request.path.startswith("/api/picks_save"):
            request._json(save_picks_workflow(operations, _json_body(body)))
        elif request.path.startswith("/api/picks_del"):
            request._json(delete_outputs_workflow(
                application, operations, _json_body(body)
            ))
        elif request.path.startswith("/api/picks_restore"):
            result = operations.restore_trash(
                application.cfg, _json_body(body).get("batch_id")
            )
            request._json({"ok": True, **result})
        elif request.path.startswith("/api/mosaic_save"):
            request._json(save_mosaic_workflow(
                application, operations, body
            ))
        elif request.path.startswith("/api/strip_meta"):
            request._json(strip_metadata_workflow(
                application,
                operations,
                body,
                filename=unquote(
                    request.headers.get("X-Filename", "image.png")
                ),
                max_side=int(request.headers.get("X-MaxSide", "0") or 0),
                quality=int(request.headers.get("X-Quality", "95") or 95),
                force_webp=request.headers.get("X-ForceWebp") == "1",
            ))
        else:
            return False
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["EvaluationPostOperations", "handle_evaluation_post"]
