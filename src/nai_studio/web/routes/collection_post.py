# -*- coding: utf-8 -*-
"""자료팩·공개자료·Reference 임포트 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from src.nai_studio.services.datapack_workflow import (
    import_pack_workflow,
    preview_pack_workflow,
    reset_pack_preview,
    undo_pack_workflow,
)


@dataclass(frozen=True)
class CollectionPostOperations:
    preview_pack: Any
    import_pack: Any
    pack_queue: Any
    summarize_queue: Any
    forget_caches: Any
    load_spec: Any
    options: Any
    load_options: Any
    public_start: Any
    public_retry: Any
    public_control: Any
    undo_pack: Any
    import_settings: Any
    resource_import: Any
    reference_add: Any
    reference_save: Any
    archive_download_control: Any
    public_pairing: Any
    public_relay: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _error(request: Any, exc: Exception) -> None:
    request._json({"ok": False, "error": str(exc)})


def _public_collection(
    request: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> bool:
    data = _json_body(body)
    routes = (
        # ⚠ pairing·relay가 start/retry/control보다 먼저 와야 하는 것은
        # 아니지만, 접두가 서로 겹치지 않는지 늘 확인할 것.
        ("/api/public_collection_pairing", lambda: operations.public_pairing()),
        ("/api/public_collection_relay", lambda: operations.public_relay(
            request.headers.get("Origin", ""),
            request.headers.get("X-Pairing-Code", ""),
            data,
        )),
        ("/api/public_collection_start", lambda: operations.public_start(data)),
        ("/api/public_collection_retry", lambda: operations.public_retry(data)),
        ("/api/public_collection_control", lambda: operations.public_control(
            data.get("action")
        )),
    )
    for prefix, operation in routes:
        if request.path.startswith(prefix):
            request._json(operation())
            return True
    return False


def _reference_import(
    request: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> bool:
    if request.path.startswith("/api/ref_bundle_import"):
        result = operations.resource_import(
            body, request.headers.get("X-Filename", "")
        )
    elif request.path.startswith("/api/ref_add"):
        result = operations.reference_add(
            body,
            request.headers.get("X-Kind", "vibe"),
            request.headers.get("X-Filename", ""),
        )
    elif request.path.startswith("/api/ref_save"):
        result = operations.reference_save(body)
    else:
        return False
    request._json(result)
    return True


def handle_collection_post(
    request: Any,
    application: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/pack_preview_cancel"):
            reset_pack_preview(application)
            request._json({"ok": True})
        elif request.path.startswith("/api/pack_preview"):
            request._json(preview_pack_workflow(
                application,
                operations,
                body,
                unquote(request.headers.get("X-Filename", "")),
            ))
        elif request.path.startswith("/api/pack_import"):
            selected = (
                "application/json"
                in request.headers.get("Content-Type", "")
            )
            request._json(import_pack_workflow(
                application,
                operations,
                _json_body(body) if selected else body,
                filename=unquote(request.headers.get("X-Filename", "")),
                selected_request=selected,
                overwrite="overwrite=1" in request.path,
                request_bytes=body,
            ))
        elif request.path.startswith("/api/pack_undo"):
            request._json(undo_pack_workflow(
                application, operations, _json_body(body).get("id")
            ))
        elif request.path.startswith("/api/setting_import"):
            request._json(operations.import_settings(
                body, unquote(request.headers.get("X-Filename", ""))
            ))
        elif request.path.startswith("/api/archive_download_control"):
            request._json(
                operations.archive_download_control(_json_body(body)))
        elif _public_collection(request, operations, body):
            pass
        elif _reference_import(request, operations, body):
            pass
        else:
            return False
    except Exception as exc:
        _error(request, exc)
    return True


__all__ = ["CollectionPostOperations", "handle_collection_post"]
