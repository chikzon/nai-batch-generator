# -*- coding: utf-8 -*-
"""설계도·설정 저장·비용·토큰 계산 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.nai_studio.services.generation_runtime import (
    anlas_response,
    token_response,
)


@dataclass(frozen=True)
class RuntimePostOperations:
    blueprint_project: Any
    save_config: Any
    fetch_balance: Any
    vibe_paths: Any
    load_asset_config: Any
    compute_pending: Any
    estimate_anlas: Any
    finalize_tokens: Any
    token_count: Any
    tokens_exact: Any
    update_status: Any
    update_download: Any
    update_install: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def handle_runtime_post(
    request: Any,
    application: Any,
    operations: RuntimePostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/blueprint_project"):
            result = operations.blueprint_project(body)
        elif request.path.startswith("/api/save"):
            result = operations.save_config(body)
        elif request.path.startswith("/api/anlas"):
            result = anlas_response(application, operations, _json_body(body))
        elif request.path.startswith("/api/tokens"):
            result = token_response(application, operations, _json_body(body))
        elif request.path.startswith("/api/update_status"):
            result = operations.update_status()
        elif request.path.startswith("/api/update_download"):
            result = operations.update_download()
        elif request.path.startswith("/api/update_install"):
            result = operations.update_install()
        else:
            return False
        request._json(result)
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["RuntimePostOperations", "handle_runtime_post"]
