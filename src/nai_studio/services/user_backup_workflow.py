# -*- coding: utf-8 -*-
"""전체 백업의 검사·선택 복원·rollback과 복원 큐 workflow."""

from __future__ import annotations

from typing import Any


def _refresh_restored_state(application: Any, operations: Any) -> None:
    """디스크 복원이 끝난 뒤에만 메모리 설정·spec·options를 같은 판으로 맞춘다."""
    fresh = operations.load_settings()
    merged = dict(operations.default_config())
    merged.update(fresh if isinstance(fresh, dict) else {})
    operations.migrate_selections(merged)
    operations.migrate_slots(merged)
    application.cfg.clear()
    application.cfg.update(merged)
    application.spec = operations.load_spec()
    options = operations.options()
    options.clear()
    options.update(operations.load_options())
    application.config_revision += 1


def preview_backup_workflow(
    application: Any,
    operations: Any,
    body: bytes,
) -> dict:
    result = operations.preview_backup(body)
    if result.get("ok"):
        application.backup_preview_blob = bytes(body)
        application.backup_preview_sha256 = str(result.get("sha256") or "")
    return result


def restore_backup_workflow(
    application: Any,
    operations: Any,
    body: Any,
    *,
    selected_request: bool,
    backup_sha256: str = "",
) -> dict:
    """선택 복원은 직전에 검사한 동일 원문만 허용해 preview/commit 간 교체를 막는다."""
    if selected_request:
        data = body if isinstance(body, dict) else {}
        expected_sha = str(data.get("sha256") or "")
        if (
            not application.backup_preview_blob
            or expected_sha != application.backup_preview_sha256
        ):
            return {
                "ok": False,
                "error": "검사한 백업 원문이 메모리에 없습니다. 다시 검사해 주세요.",
            }
        result = operations.restore_backup(
            application.backup_preview_blob,
            expected_sha,
            selected=data.get("selected") or [],
            expected_diff=str(data.get("diff_fingerprint") or ""),
        )
    else:
        result = operations.restore_backup(body, backup_sha256)
    if result.get("ok"):
        application.backup_preview_blob = None
        application.backup_preview_sha256 = ""
        _refresh_restored_state(application, operations)
    return result


def rollback_backup_workflow(
    application: Any,
    operations: Any,
    rollback_id: Any,
) -> dict:
    result = operations.rollback_backup(rollback_id)
    if result.get("ok"):
        _refresh_restored_state(application, operations)
    return result


def data_index_response(operations: Any) -> dict:
    index = operations.rebuild_data_index()
    return {
        "ok": True,
        "files": index["files"],
        "bytes": index["bytes"],
        "fingerprint": index["fingerprint"],
    }


def restoration_batch_response(operations: Any, data: dict) -> dict:
    queue = operations.image_batch_queue(
        data.get("items") or [],
        cursor=data.get("cursor"),
        status=data.get("status") or "completed",
    )
    return {
        "ok": True,
        "restoration": operations.summarize_queue(queue),
        "restoration_queue": queue,
    }


__all__ = [
    "data_index_response",
    "preview_backup_workflow",
    "restoration_batch_response",
    "restore_backup_workflow",
    "rollback_backup_workflow",
]
