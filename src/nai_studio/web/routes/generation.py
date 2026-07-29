# -*- coding: utf-8 -*-
"""비교 실행과 실시간 생성 상태 GET 라우트."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GenerationGetOperations:
    comparison_catalog: Any
    comparison_runs: Any
    comparison_progress: Any


def _comparison(
    request: Any,
    application: Any,
    operations: GenerationGetOperations,
) -> bool:
    routes = (
        (
            "/api/compare_catalog",
            lambda: operations.comparison_catalog(
                application.cfg, application.spec
            ),
        ),
        ("/api/compare_runs", lambda: operations.comparison_runs(application.cfg)),
        (
            "/api/compare_progress",
            lambda: operations.comparison_progress(application.cfg),
        ),
    )
    for prefix, operation in routes:
        if request.path.startswith(prefix):
            try:
                request._json(operation())
            except Exception as exc:
                request._json({"ok": False, "error": str(exc)})
            return True
    return False


def handle_generation_get(
    request: Any,
    application: Any,
    operations: GenerationGetOperations,
) -> bool:
    if _comparison(request, application, operations):
        return True
    if request.path.startswith("/status.json"):
        request._json(application.live.snapshot())
        return True
    if not request.path.startswith("/latest.webp"):
        return False
    body = application.live.image()
    if body is None:
        request.send_response(404)
        request.end_headers()
        return True
    request.send_response(200)
    request.send_header("Content-Type", "image/webp")
    request.send_header("Cache-Control", "no-store")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)
    return True


__all__ = ["GenerationGetOperations", "handle_generation_get"]
