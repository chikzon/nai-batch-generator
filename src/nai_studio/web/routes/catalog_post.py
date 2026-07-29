# -*- coding: utf-8 -*-
"""자료실·그림체 정리 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CatalogPostOperations:
    style_save: Any
    normalization_save: Any
    verify_tags: Any
    organize_library: Any
    delete_styles: Any
    restore_styles: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def handle_catalog_post(
    request: Any,
    operations: CatalogPostOperations,
    body: bytes,
) -> bool:
    try:
        data = _json_body(body)
        if request.path.startswith("/api/style_save"):
            result = operations.style_save(body)
        elif request.path.startswith("/api/norm_save"):
            result = operations.normalization_save(body)
        elif request.path.startswith("/api/verify_tags"):
            result = operations.verify_tags(data.get("text") or "")
        elif request.path.startswith("/api/library_organize"):
            result = operations.organize_library(data)
        elif request.path.startswith("/api/style_del"):
            result = operations.delete_styles(data.get("ids"))
        elif request.path.startswith("/api/style_restore"):
            result = operations.restore_styles(data.get("ids"))
        else:
            return False
        request._json(result)
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["CatalogPostOperations", "handle_catalog_post"]
