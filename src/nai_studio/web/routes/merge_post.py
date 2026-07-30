# -*- coding: utf-8 -*-
"""백업·자료팩 공통 병합 검토 POST 라우트.

새 Operations 묶음을 만들지 않는다 — 백업은 recovery 세트, 자료팩은
collection 세트를 그대로 받아 기존 workflow에 위임하고, merge_workflow가
행 모양만 통일한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MergePostOperations:
    """자료실 증거·캐릭터 병합 경계 — compat/studio_wiring이 조립한다."""

    evidence_compare: Any
    evidence_merge: Any
    character_compare: Any
    character_merge: Any
    character_dupes: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _bad_source(request: Any) -> None:
    request._json({
        "ok": False,
        "error": "source는 backup·datapack·library 중 하나여야 합니다.",
    })


def _merge_preview(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    merge_operations: Any,
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
    elif source == "library":
        # 자료실 중복 후보 나란히 비교 — 쓰기 없음
        request._json(merge_operations.evidence_compare(
            _json_body(body).get("ids") or []))
        return
    elif source == "characters":
        data = _json_body(body)
        ids = data.get("ids") or []
        if ids:
            request._json(merge_operations.character_compare(
                application.cfg, ids))
        else:
            # ids 없이 부르면 중복 묶음 목록을 준다
            request._json(merge_operations.character_dupes(application.cfg))
        return
    else:
        _bad_source(request)
        return
    request._json(merge_preview_response(source, detail, rows))


def _merge_apply(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    merge_operations: Any,
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
    elif source == "library":
        result = merge_operations.evidence_merge(
            data.get("representative"), data.get("others") or [])
    elif source == "characters":
        result = merge_operations.character_merge(
            application, data.get("representative"), data.get("others") or [])
    else:
        _bad_source(request)
        return
    request._json(merge_apply_response(source, result))


def _merge_undo(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    merge_operations: Any,
    body: bytes,
) -> None:
    data = _json_body(body)
    source = str(data.get("source") or "").strip().lower()
    if source == "backup":
        result = rollback_backup_workflow(
            application, recovery_operations, data.get("id"))
    elif source in ("datapack", "library"):
        # 증거 병합도 자료팩과 같은 Undo 장부(list_updates)를 쓴다.
        result = undo_pack_workflow(
            application, collection_operations, data.get("id"))
    elif source == "characters":
        result = {
            "ok": False,
            "error": "캐릭터 병합은 대표에 더하기만 해 되돌릴 항목이 "
                     "없습니다. 원본 캐릭터는 그대로 남아 있습니다.",
        }
    else:
        _bad_source(request)
        return
    request._json(merge_undo_response(source, result))


def handle_merge_post(
    request: Any,
    application: Any,
    recovery_operations: Any,
    collection_operations: Any,
    merge_operations: Any,
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
                    merge_operations,
                    body,
                )
            except Exception as exc:
                request._json({"ok": False, "error": str(exc)})
            return True
    return False


__all__ = ["MergePostOperations", "handle_merge_post"]
