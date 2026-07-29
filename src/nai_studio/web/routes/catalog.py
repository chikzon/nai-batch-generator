# -*- coding: utf-8 -*-
"""자료실·빌더 검색 GET 라우트."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


@dataclass(frozen=True)
class CatalogGetOperations:
    booru: Any
    style_duplicates: Any
    library: Any
    combos: Any
    recipes: Any
    prewarm: Any
    autocomplete: Any
    tags: Any
    scenes: Any


def _one(query: dict, name: str, default: str = "") -> str:
    return query.get(name, [default])[0]


def _library(application: Any, operations: CatalogGetOperations, query: dict) -> dict:
    return operations.library(
        application.cfg,
        application.spec,
        q=_one(query, "q"),
        kind=_one(query, "kind"),
        source=_one(query, "source"),
        review=_one(query, "review"),
        label=_one(query, "label"),
        limit=int(_one(query, "limit", "100")),
        offset=int(_one(query, "offset", "0")),
    )


def _combos(operations: CatalogGetOperations, query: dict) -> dict:
    result = operations.combos(
        _one(query, "q"),
        int(_one(query, "limit", "40")),
        int(_one(query, "offset", "0")),
        tab=_one(query, "tab"),
        source=_one(query, "source"),
        sort=_one(query, "sort"),
        seeded=_one(query, "seeded"),
        rating=_one(query, "rating"),
    )
    return {"ok": True, **result}


def _recipes(operations: CatalogGetOperations, query: dict) -> dict:
    result = operations.recipes(
        _one(query, "q"),
        _one(query, "axis"),
        int(_one(query, "limit", "60")),
        int(_one(query, "offset", "0")),
    )
    operations.prewarm(result.get("items"), n=60)
    return {"ok": True, **result}


def _scenes(
    application: Any,
    operations: CatalogGetOperations,
    query: dict,
) -> dict:
    scene_ids = [
        value
        for value in _one(query, "ids").split(",")
        if value.strip().isdigit()
    ]
    return operations.scenes(
        application.cfg,
        scene_ids,
        _one(query, "setting").strip(),
    )


def _payload(
    path: str,
    application: Any,
    operations: CatalogGetOperations,
    query: dict,
) -> dict | None:
    if path.startswith("/api/booru"):
        return operations.booru(
            _one(query, "site", "danbooru"),
            unquote(_one(query, "q")),
            int(_one(query, "page", "1")),
            int(_one(query, "limit", "40")),
        )
    if path.startswith("/api/style_dupes"):
        return operations.style_duplicates()
    if path.startswith("/api/library"):
        return _library(application, operations, query)
    if path.startswith("/api/combos"):
        return _combos(operations, query)
    if path.startswith("/api/recipes"):
        return _recipes(operations, query)
    if path.startswith("/api/ac"):
        return {
            "ok": True,
            "items": operations.autocomplete(
                application.spec,
                unquote(_one(query, "q")),
                int(_one(query, "limit", "12")),
            ),
        }
    if path.startswith("/api/tags"):
        return {
            "ok": True,
            "tags": operations.tags(
                application.spec,
                _one(query, "kind", "char"),
                _one(query, "slot"),
                _one(query, "q"),
                int(_one(query, "limit", "60")),
            ),
        }
    if path.startswith("/api/scenes"):
        return _scenes(application, operations, query)
    return None


def handle_catalog_get(
    request: Any,
    application: Any,
    operations: CatalogGetOperations,
) -> bool:
    prefixes = (
        "/api/booru",
        "/api/style_dupes",
        "/api/library",
        "/api/combos",
        "/api/recipes",
        "/api/ac",
        "/api/tags",
        "/api/scenes",
    )
    if not request.path.startswith(prefixes):
        return False
    query = parse_qs(urlparse(request.path).query)
    if request.path.startswith("/api/booru"):
        request._json(_payload(request.path, application, operations, query))
        return True
    try:
        request._json(_payload(request.path, application, operations, query))
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["CatalogGetOperations", "handle_catalog_get"]
