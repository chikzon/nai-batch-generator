# -*- coding: utf-8 -*-
"""백업·로컬 자료 복구·메타데이터 감사 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.nai_studio.services.user_backup_workflow import (
    data_index_response,
    preview_backup_workflow,
    restoration_batch_response,
    restore_backup_workflow,
    rollback_backup_workflow,
)


@dataclass(frozen=True)
class RecoveryPostOperations:
    preview_backup: Any
    restore_backup: Any
    rollback_backup: Any
    load_settings: Any
    default_config: Any
    migrate_selections: Any
    migrate_slots: Any
    load_spec: Any
    options: Any
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


def handle_recovery_post(
    request: Any,
    application: Any,
    operations: RecoveryPostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/backup_preview"):
            result = preview_backup_workflow(application, operations, body)
        elif request.path.startswith("/api/backup_restore"):
            selected = (
                "application/json"
                in request.headers.get("Content-Type", "")
            )
            value = _json_body(body) if selected else body
            result = restore_backup_workflow(
                application,
                operations,
                value,
                selected_request=selected,
                backup_sha256=request.headers.get("X-Backup-SHA256", ""),
            )
        elif request.path.startswith("/api/backup_rollback"):
            result = rollback_backup_workflow(
                application, operations, _json_body(body).get("id")
            )
        elif request.path.startswith("/api/data_index_rebuild"):
            result = data_index_response(operations)
        elif request.path.startswith("/api/restoration_batch"):
            result = restoration_batch_response(
                operations, _json_body(body)
            )
        elif not _simple_recovery(request, operations, body):
            return False
        else:
            return True
        request._json(result)
    except Exception as exc:
        _error(request, exc)
    return True


__all__ = ["RecoveryPostOperations", "handle_recovery_post"]
