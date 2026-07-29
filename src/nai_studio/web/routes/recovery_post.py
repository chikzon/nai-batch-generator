# -*- coding: utf-8 -*-
"""백업·로컬 자료 복구·메타데이터 감사 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecoveryPostOperations:
    preview_backup: Any
    restore_backup: Any
    rollback_backup: Any
    load_settings: Any
    default_config: dict
    migrate_selections: Any
    migrate_slots: Any
    load_spec: Any
    options: dict
    load_options: Any
    normalize_local_images: Any
    rollback_local_images: Any
    rebuild_data_index: Any
    metadata_control: Any
    metadata_candidate: Any
    metadata_save: Any
    image_batch_queue: Any
    summarize_queue: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _error(request: Any, exc: Exception) -> None:
    request._json({"ok": False, "error": str(exc)})


def _refresh_restored_state(
    application: Any, operations: RecoveryPostOperations
) -> None:
    fresh = operations.load_settings()
    merged = dict(operations.default_config)
    merged.update(fresh if isinstance(fresh, dict) else {})
    operations.migrate_selections(merged)
    operations.migrate_slots(merged)
    application.cfg.clear()
    application.cfg.update(merged)
    application.spec = operations.load_spec()
    operations.options.clear()
    operations.options.update(operations.load_options())
    application.config_revision += 1


def _backup_preview(
    request: Any,
    application: Any,
    operations: RecoveryPostOperations,
    body: bytes,
) -> None:
    result = operations.preview_backup(body)
    if result.get("ok"):
        application.backup_preview_blob = bytes(body)
        application.backup_preview_sha256 = str(result.get("sha256") or "")
    request._json(result)


def _backup_restore(
    request: Any,
    application: Any,
    operations: RecoveryPostOperations,
    body: bytes,
) -> None:
    if "application/json" in request.headers.get("Content-Type", ""):
        data = _json_body(body)
        expected_sha = str(data.get("sha256") or "")
        if (
            not application.backup_preview_blob
            or expected_sha != application.backup_preview_sha256
        ):
            request._json({
                "ok": False,
                "error": "검사한 백업 원문이 메모리에 없습니다. 다시 검사해 주세요.",
            })
            return
        result = operations.restore_backup(
            application.backup_preview_blob,
            expected_sha,
            selected=data.get("selected") or [],
            expected_diff=str(data.get("diff_fingerprint") or ""),
        )
    else:
        result = operations.restore_backup(
            body, request.headers.get("X-Backup-SHA256", "")
        )
    if result.get("ok"):
        application.backup_preview_blob = None
        application.backup_preview_sha256 = ""
        _refresh_restored_state(application, operations)
    request._json(result)


def _backup_rollback(
    request: Any,
    application: Any,
    operations: RecoveryPostOperations,
    body: bytes,
) -> None:
    result = operations.rollback_backup(_json_body(body).get("id"))
    if result.get("ok"):
        _refresh_restored_state(application, operations)
    request._json(result)


def _simple_recovery(
    request: Any,
    operations: RecoveryPostOperations,
    body: bytes,
) -> bool:
    data = _json_body(body)
    routes = (
        ("/api/local_image_normalize", lambda: operations.normalize_local_images(
            data.get("fingerprint", "")
        )),
        ("/api/local_image_rollback", lambda: operations.rollback_local_images(
            data.get("id", "")
        )),
        ("/api/metadata_audit_control", lambda: operations.metadata_control(body)),
        ("/api/metadata_audit_candidate", lambda: operations.metadata_candidate(body)),
        ("/api/metadata_audit_save", lambda: operations.metadata_save(body)),
    )
    for prefix, operation in routes:
        if request.path.startswith(prefix):
            request._json(operation())
            return True
    return False


def _data_index(
    request: Any, operations: RecoveryPostOperations
) -> None:
    index = operations.rebuild_data_index()
    request._json({
        "ok": True,
        "files": index["files"],
        "bytes": index["bytes"],
        "fingerprint": index["fingerprint"],
    })


def _restoration_batch(
    request: Any, operations: RecoveryPostOperations, body: bytes
) -> None:
    data = _json_body(body)
    queue = operations.image_batch_queue(
        data.get("items") or [],
        cursor=data.get("cursor"),
        status=data.get("status") or "completed",
    )
    request._json({
        "ok": True,
        "restoration": operations.summarize_queue(queue),
        "restoration_queue": queue,
    })


def handle_recovery_post(
    request: Any,
    application: Any,
    operations: RecoveryPostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/backup_preview"):
            _backup_preview(request, application, operations, body)
        elif request.path.startswith("/api/backup_restore"):
            _backup_restore(request, application, operations, body)
        elif request.path.startswith("/api/backup_rollback"):
            _backup_rollback(request, application, operations, body)
        elif request.path.startswith("/api/data_index_rebuild"):
            _data_index(request, operations)
        elif request.path.startswith("/api/restoration_batch"):
            _restoration_batch(request, operations, body)
        elif not _simple_recovery(request, operations, body):
            return False
    except Exception as exc:
        _error(request, exc)
    return True


__all__ = ["RecoveryPostOperations", "handle_recovery_post"]
