# -*- coding: utf-8 -*-
"""자료팩의 검사·선택 적용·Undo와 실행 중 캐시 갱신 workflow."""

from __future__ import annotations

import hashlib
from typing import Any


def reset_pack_preview(application: Any) -> None:
    application.pack_preview_blob = None
    application.pack_preview_sha256 = ""
    application.pack_preview_filename = ""


def _with_restore_queue(
    operations: Any,
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


def preview_pack_workflow(
    application: Any,
    operations: Any,
    body: bytes,
    filename: str,
) -> dict:
    result = operations.preview_pack(body, filename)
    if result.get("ok"):
        application.pack_preview_blob = bytes(body)
        application.pack_preview_sha256 = str(result.get("sha256") or "")
        application.pack_preview_filename = filename
    else:
        reset_pack_preview(application)
    return result


def _selected_pack_import(
    application: Any,
    operations: Any,
    data: dict,
) -> tuple[dict, str]:
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


def import_pack_workflow(
    application: Any,
    operations: Any,
    body: bytes | dict,
    *,
    filename: str,
    selected_request: bool,
    overwrite: bool,
    request_bytes: bytes = b"",
) -> dict:
    """preview와 같은 원문만 적용하고 성공한 뒤에만 캐시·spec을 새로 읽는다."""
    try:
        if selected_request:
            result, archive_sha = _selected_pack_import(
                application,
                operations,
                body if isinstance(body, dict) else {},
            )
        else:
            raw = body if isinstance(body, bytes) else b""
            result = operations.import_pack(
                raw, filename, overwrite=overwrite
            )
            archive_sha = hashlib.sha256(raw).hexdigest()
    except Exception as exc:
        raw = request_bytes or (body if isinstance(body, bytes) else b"")
        result = {"ok": False, "error": str(exc)}
        archive_sha = hashlib.sha256(raw).hexdigest()
    _with_restore_queue(
        operations,
        result,
        archive_sha256=archive_sha,
        filename=filename,
    )
    if result.get("ok"):
        reset_pack_preview(application)
        operations.forget_caches()
        application.spec = operations.load_spec()
        options = operations.options()
        options.clear()
        options.update(operations.load_options())
    return result


def undo_pack_workflow(
    application: Any,
    operations: Any,
    pack_id: Any,
) -> dict:
    """Undo와 설정 revision 갱신을 같은 config 잠금 안에서 처리한다."""
    with application.config_lock:
        application.use_latest_config()
        result = operations.undo_pack(pack_id, application.cfg)
        if result.get("changed_config"):
            application.config_revision += 1
        result["revision"] = application.config_revision
    if result.get("ok"):
        application.spec = operations.load_spec()
        options = operations.options()
        options.clear()
        options.update(operations.load_options())
    return result


__all__ = [
    "import_pack_workflow",
    "preview_pack_workflow",
    "reset_pack_preview",
    "undo_pack_workflow",
]
