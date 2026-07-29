# -*- coding: utf-8 -*-
"""자료팩·공개자료·Reference 임포트 POST 라우트."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote


@dataclass(frozen=True)
class CollectionPostOperations:
    preview_pack: Any
    import_pack: Any
    pack_queue: Any
    summarize_queue: Any
    forget_caches: Any
    load_spec: Any
    options: dict
    load_options: Any
    public_start: Any
    public_retry: Any
    public_control: Any
    undo_pack: Any
    import_settings: Any
    resource_import: Any
    reference_add: Any
    reference_save: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _error(request: Any, exc: Exception) -> None:
    request._json({"ok": False, "error": str(exc)})


def _reset_preview(application: Any) -> None:
    application.pack_preview_blob = None
    application.pack_preview_sha256 = ""
    application.pack_preview_filename = ""


def _pack_queue(
    operations: CollectionPostOperations,
    result: dict,
    *,
    archive_sha256: str,
    filename: str,
) -> dict:
    if "restoration_queue" in result:
        return result
    queue = operations.pack_queue(
        {**result, "archive_sha256": archive_sha256},
        filename=filename,
    )
    result["restoration"] = operations.summarize_queue(queue)
    result["restoration_queue"] = queue
    return result


def _pack_preview(
    request: Any,
    application: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> None:
    filename = unquote(request.headers.get("X-Filename", ""))
    result = operations.preview_pack(body, filename)
    if result.get("ok"):
        application.pack_preview_blob = bytes(body)
        application.pack_preview_sha256 = str(result.get("sha256") or "")
        application.pack_preview_filename = filename
    else:
        _reset_preview(application)
    request._json(result)


def _selected_pack_import(
    application: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> tuple[dict, str]:
    data = _json_body(body)
    expected_sha = str(data.get("sha256") or "")
    if (
        not application.pack_preview_blob
        or expected_sha != application.pack_preview_sha256
    ):
        return {
            "ok": False,
            "error": "검사한 자료팩 원문이 메모리에 없습니다. 다시 골라 주세요.",
        }, expected_sha
    return operations.import_pack(
        application.pack_preview_blob,
        application.pack_preview_filename,
        selected_conflicts=data.get("selected") or [],
        expected_diff=str(data.get("diff_fingerprint") or ""),
    ), expected_sha


def _pack_import(
    request: Any,
    application: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> None:
    filename = unquote(request.headers.get("X-Filename", ""))
    selected = "application/json" in request.headers.get("Content-Type", "")
    if selected:
        result, archive_sha = _selected_pack_import(application, operations, body)
    else:
        result = operations.import_pack(
            body, filename, overwrite="overwrite=1" in request.path
        )
        archive_sha = hashlib.sha256(body).hexdigest()
    _pack_queue(
        operations,
        result,
        archive_sha256=archive_sha,
        filename=filename,
    )
    if result.get("ok"):
        _reset_preview(application)
        operations.forget_caches()
        application.spec = operations.load_spec()
        operations.options.clear()
        operations.options.update(operations.load_options())
    request._json(result)


def _pack_import_error(
    request: Any,
    operations: CollectionPostOperations,
    body: bytes,
    exc: Exception,
) -> None:
    result = {"ok": False, "error": str(exc)}
    _pack_queue(
        operations,
        result,
        archive_sha256=hashlib.sha256(body).hexdigest(),
        filename=unquote(request.headers.get("X-Filename", "")),
    )
    request._json(result)


def _pack_undo(
    request: Any,
    application: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> None:
    data = _json_body(body)
    with application.config_lock:
        application.use_latest_config()
        result = operations.undo_pack(data.get("id"), application.cfg)
        if result.get("changed_config"):
            application.config_revision += 1
        result["revision"] = application.config_revision
    if result.get("ok"):
        application.spec = operations.load_spec()
        operations.options.clear()
        operations.options.update(operations.load_options())
    request._json(result)


def _public_collection(
    request: Any,
    operations: CollectionPostOperations,
    body: bytes,
) -> bool:
    data = _json_body(body)
    routes = (
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
            _reset_preview(application)
            request._json({"ok": True})
        elif request.path.startswith("/api/pack_preview"):
            _pack_preview(request, application, operations, body)
        elif request.path.startswith("/api/pack_import"):
            try:
                _pack_import(request, application, operations, body)
            except Exception as exc:
                _pack_import_error(request, operations, body, exc)
        elif request.path.startswith("/api/pack_undo"):
            _pack_undo(request, application, operations, body)
        elif request.path.startswith("/api/setting_import"):
            request._json(operations.import_settings(
                body, unquote(request.headers.get("X-Filename", ""))
            ))
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
