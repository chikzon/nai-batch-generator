# -*- coding: utf-8 -*-
"""백업·자료팩 공통 병합 검토 POST 라우트.

새 Operations 묶음을 만들지 않는다 — 백업은 recovery 세트, 자료팩은
collection 세트를 그대로 받아 기존 workflow에 위임하고, merge_workflow가
행 모양만 통일한다.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from src.nai_studio.services.datapack_workflow import (
    import_pack_workflow,
    preview_pack_workflow,
    undo_pack_workflow,
)
from src.nai_studio.services.merge_workflow import (
    MERGE_SOURCES,
    merge_apply_response,
    merge_preview_response,
    merge_rows_from_backup,
    merge_rows_from_datapack,
    merge_undo_response,
)
from src.nai_studio.services.user_backup_workflow import (
    preview_backup_workflow,
    restore_backup_workflow,
    rollback_backup_workflow,
)


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _bad_source(request: Any) -> None:
    request._json({
        "ok": False,
        "error": "source는 backup 또는 datapack이어야 합니다.",
    })


def _merge_preview(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    body: bytes,
) -> None:
    source = str(request.headers.get("X-Source") or "").strip().lower()
    if source == "backup":
        detail = preview_backup_workflow(
            application, recovery_operations, body)
        rows = merge_rows_from_backup(detail)
    elif source == "datapack":
        detail = preview_pack_workflow(
            application,
            collection_operations,
            body,
            unquote(request.headers.get("X-Filename", "")),
        )
        rows = merge_rows_from_datapack(detail)
    else:
        _bad_source(request)
        return
    request._json(merge_preview_response(source, detail, rows))


def _merge_apply(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    body: bytes,
) -> None:
    data = _json_body(body)
    source = str(data.get("source") or "").strip().lower()
    if source == "backup":
        result = restore_backup_workflow(
            application,
            recovery_operations,
            data,
            selected_request=True,
        )
    elif source == "datapack":
        result = import_pack_workflow(
            application,
            collection_operations,
            data,
            filename=str(data.get("filename") or ""),
            selected_request=True,
            overwrite=False,
            request_bytes=body,
        )
    else:
        _bad_source(request)
        return
    request._json(merge_apply_response(source, result))


def _merge_undo(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    body: bytes,
) -> None:
    data = _json_body(body)
    source = str(data.get("source") or "").strip().lower()
    if source == "backup":
        result = rollback_backup_workflow(
            application, recovery_operations, data.get("id"))
    elif source == "datapack":
        result = undo_pack_workflow(
            application, collection_operations, data.get("id"))
    else:
        _bad_source(request)
        return
    request._json(merge_undo_response(source, result))


def handle_merge_post(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    body: bytes,
) -> bool:
    routes = (
        ("/api/merge_preview", _merge_preview),
        ("/api/merge_apply", _merge_apply),
        ("/api/merge_undo", _merge_undo),
    )
    for prefix, handler in routes:
        if request.path.startswith(prefix):
            try:
                handler(
                    request,
                    application,
                    recovery_operations,
                    collection_operations,
                    body,
                )
            except Exception as exc:
                request._json({"ok": False, "error": str(exc)})
            return True
    return False


__all__ = ["handle_merge_post"]
