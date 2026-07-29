# -*- coding: utf-8 -*-
"""설계도·순서·작업 상태를 읽는 runtime 라우트."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse


def _respond(request: Any, operation: Any) -> None:
    try:
        request._json(operation())
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})


def handle_runtime_get(request: Any, application: Any) -> bool:
    """기존 prefix 순서를 유지하고 처리한 요청만 True로 반환한다."""
    if request.path.startswith("/api/blueprint"):
        _respond(request, application.snapshot_blueprint)
        return True
    if request.path.startswith("/api/setting_sequence"):
        query = parse_qs(urlparse(request.path).query)
        _respond(
            request,
            lambda: application.snapshot_sequence(query.get("name", [""])[0]),
        )
        return True
    if request.path.startswith("/api/jobs"):
        _respond(request, application.snapshot_jobs)
        return True
    if request.path.startswith("/api/config"):
        request._json(application.snapshot_config())
        return True
    return False


__all__ = ["handle_runtime_get"]
