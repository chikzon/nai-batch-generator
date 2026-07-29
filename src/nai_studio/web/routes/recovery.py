# -*- coding: utf-8 -*-
"""자료 복구·보존 상태를 읽는 GET 라우트."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class RecoveryGetOperations:
    metadata_audit: Any
    folder_inventory: Any
    trash: Any
    pack_log: Any
    public_restoration: Any
    public_collection: Any
    data_storage: Any
    image_origins: Any
    local_integrity: Any


def _respond(request: Any, operation: Any) -> None:
    try:
        request._json(operation())
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})


def handle_recovery_get(
    request: Any,
    application: Any,
    operations: RecoveryGetOperations,
) -> bool:
    path = request.path
    if path.startswith("/api/metadata_audit_status"):
        query = parse_qs(urlparse(path).query)
        _respond(
            request,
            lambda: operations.metadata_audit(
                int(query.get("offset", ["0"])[0]),
                int(query.get("limit", ["50"])[0]),
            ),
        )
        return True
    if path.startswith("/api/folder_inventory"):
        query = parse_qs(urlparse(path).query)
        _respond(
            request,
            lambda: operations.folder_inventory(
                query.get("offset", ["0"])[0],
                query.get("limit", ["50"])[0],
            ),
        )
        return True
    routes = (
        ("/api/trash", lambda: operations.trash(application.cfg)),
        ("/api/pack_log", operations.pack_log),
        ("/api/public_collection_restoration", operations.public_restoration),
        ("/api/public_collection", operations.public_collection),
        ("/api/data_storage", operations.data_storage),
        ("/api/img_origins", operations.image_origins),
        ("/api/local_image_integrity", operations.local_integrity),
    )
    for prefix, operation in routes:
        if path.startswith(prefix):
            _respond(request, operation)
            return True
    return False


__all__ = ["RecoveryGetOperations", "handle_recovery_get"]
