# -*- coding: utf-8 -*-
"""생성·비교·이미지 도구 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote


@dataclass(frozen=True)
class GenerationPostOperations:
    activate_comparison: Any
    compare_rerun: Any
    comparison_recipe: Any
    compare_promote: Any
    compare_preview: Any
    compare_run: Any
    start: Any
    generate_one: Any
    request_stop: Any
    job_command: Any
    image_to_image: Any
    variation_save: Any
    regenerate: Any
    scene_run: Any
    director: Any
    inspect_image: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _comparison(
    request: Any,
    application: Any,
    operations: GenerationPostOperations,
    body: bytes,
) -> bool:
    data = _json_body(body)
    if request.path.startswith("/api/compare_activate"):
        result = operations.activate_comparison(
            application.cfg, data.get("folder")
        )
    elif request.path.startswith("/api/compare_rerun"):
        result = operations.compare_rerun(body)
    elif request.path.startswith("/api/compare_recipe"):
        result = operations.comparison_recipe(
            application.cfg, data.get("path")
        )
    elif request.path.startswith("/api/compare_promote"):
        result = operations.compare_promote(body)
    elif request.path.startswith("/api/compare_preview"):
        result = operations.compare_preview(body)
    elif request.path.startswith("/api/compare_run"):
        result = operations.compare_run(body)
    else:
        return False
    request._json(result)
    return True


def _image_tool(
    request: Any,
    operations: GenerationPostOperations,
    body: bytes,
) -> bool:
    if request.path.startswith("/api/i2i"):
        result = operations.image_to_image(body)
    elif request.path.startswith("/api/character_variation_save"):
        result = operations.variation_save(body)
    elif request.path.startswith("/api/director"):
        result = operations.director(
            body,
            request.headers.get("X-Tool", ""),
            unquote(request.headers.get("X-Prompt", "") or ""),
            request.headers.get("X-Defry", "0"),
            request.headers.get("X-Scale", "4"),
            unquote(request.headers.get("X-Filename", "") or ""),
        )
    elif request.path.startswith("/api/inspect"):
        result = operations.inspect_image(
            body,
            request.headers.get("X-Filename", ""),
            request.headers.get("X-Save", ""),
        )
    else:
        return False
    request._json(result)
    return True


def handle_generation_post(
    request: Any,
    application: Any,
    operations: GenerationPostOperations,
    body: bytes,
) -> bool:
    try:
        if _comparison(request, application, operations, body):
            pass
        elif request.path.startswith("/api/start"):
            request._json(operations.start())
        elif request.path.startswith("/api/generate_one"):
            request._json(operations.generate_one())
        elif request.path.startswith("/api/stop"):
            request._json({"ok": operations.request_stop()})
        elif request.path.startswith("/api/job_command"):
            if len(body or b"") > 128 * 1024:
                request._json({"ok": False, "error": "요청이 너무 큽니다."})
            else:
                request._json(operations.job_command(body))
        elif request.path.startswith("/api/regen"):
            request._json(operations.regenerate(body))
        elif request.path.startswith("/api/scenes_run"):
            request._json(operations.scene_run())
        elif _image_tool(request, operations, body):
            pass
        else:
            return False
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["GenerationPostOperations", "handle_generation_post"]
