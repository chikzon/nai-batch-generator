# -*- coding: utf-8 -*-
"""이미지·내보내기·진단·HTML GET 응답."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


@dataclass(frozen=True)
class AssetGetOperations:
    vibe_dir: Path
    mime: dict
    output_preview: Any
    output_list: Any
    setting_thumbs: Any
    resource_export: Any
    backup_export: Any
    fragments_export: Any
    settings_export: Any
    cached_image: Any
    diagnostics: Any
    render_page: Any


def _one(query: dict, name: str, default: str = "") -> str:
    return query.get(name, [default])[0]


def _send(
    request: Any,
    body: bytes,
    content_type: str,
    *,
    cache: str | None = None,
    disposition: str | None = None,
) -> None:
    request.send_response(200)
    request.send_header("Content-Type", content_type)
    if cache:
        request.send_header("Cache-Control", cache)
    if disposition:
        request.send_header("Content-Disposition", disposition)
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)


def _not_found(request: Any) -> None:
    request.send_response(404)
    request.end_headers()


def _reference_image(
    request: Any, operations: AssetGetOperations, query: dict
) -> None:
    resource_id = Path(_one(query, "id")).name
    suffix = ".ref.png" if _one(query, "kind", "vibe") == "cref" else ".png"
    path = operations.vibe_dir / f"{resource_id}{suffix}"
    if not resource_id or not path.is_file():
        _not_found(request)
        return
    _send(request, path.read_bytes(), "image/png", cache="max-age=3600")


def _output_image(
    request: Any,
    application: Any,
    operations: AssetGetOperations,
    query: dict,
) -> None:
    path = operations.output_preview(application.cfg, unquote(_one(query, "p")))
    if path is None:
        _not_found(request)
        return
    _send(
        request,
        path.read_bytes(),
        operations.mime.get(path.suffix.lower(), "image/webp"),
        cache="max-age=60",
    )


def _cached_image(
    request: Any, operations: AssetGetOperations, query: dict
) -> None:
    body, content_type = operations.cached_image(unquote(_one(query, "u")))
    if not body:
        _not_found(request)
        return
    _send(
        request,
        body,
        content_type or "image/webp",
        cache="max-age=86400",
    )


def _json_route(
    request: Any,
    application: Any,
    operations: AssetGetOperations,
    query: dict,
) -> bool:
    if request.path.startswith("/api/out_list"):
        operation = lambda: operations.output_list(
            unquote(_one(query, "dir")),
            application.cfg,
            limit=int(_one(query, "limit", "0")),
            offset=int(_one(query, "offset", "0")),
            only_pick=_one(query, "only_pick") in ("1", "true"),
            only_fav=_one(query, "only_fav") in ("1", "true"),
        )
    elif request.path.startswith("/api/setting_thumbs"):
        operation = lambda: {
            "ok": True,
            "thumbs": operations.setting_thumbs(
                unquote(_one(query, "name")), application.cfg
            ),
        }
    elif request.path.startswith("/api/diag"):
        try:
            limit = max(10, min(2000, int(_one(query, "n", "300"))))
        except (TypeError, ValueError):
            limit = 300
        operation = lambda: operations.diagnostics(
            limit, _one(query, "err") in ("1", "true")
        )
    else:
        return False
    try:
        request._json(operation())
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


def _export_route(
    request: Any,
    application: Any,
    operations: AssetGetOperations,
    query: dict,
) -> bool:
    routes = (
        (
            "/api/ref_bundle_export",
            lambda: operations.resource_export(application.cfg),
            "application/json; charset=utf-8",
            'attachment; filename="nai-resources.naiv4vibebundle"',
        ),
        (
            "/api/backup_export",
            lambda: operations.backup_export(application.cfg),
            "application/zip",
            'attachment; filename="nais-user-backup.zip"',
        ),
        (
            "/api/frag_export",
            operations.fragments_export,
            "application/zip",
            'attachment; filename="fragments.zip"',
        ),
        (
            "/api/setting_export",
            lambda: operations.settings_export(
                [
                    name
                    for name in (unquote(value) for value in query.get("name", []))
                    if name
                ]
                or None
            ),
            "application/zip",
            'attachment; filename="settings.zip"',
        ),
    )
    for prefix, operation, content_type, disposition in routes:
        if not request.path.startswith(prefix):
            continue
        try:
            body = operation()
        except Exception as exc:
            request._json({"ok": False, "error": str(exc)})
            return True
        _send(request, body, content_type, disposition=disposition)
        return True
    return False


def handle_asset_get(
    request: Any,
    application: Any,
    operations: AssetGetOperations,
) -> bool:
    query = parse_qs(urlparse(request.path).query)
    if request.path.startswith("/refimg"):
        _reference_image(request, operations, query)
    elif request.path.startswith("/setout"):
        _output_image(request, application, operations, query)
    elif request.path.startswith("/img"):
        _cached_image(request, operations, query)
    elif _json_route(request, application, operations, query):
        pass
    elif _export_route(request, application, operations, query):
        pass
    elif request.path == "/" or request.path.startswith("/?"):
        _send(
            request,
            operations.render_page().encode("utf-8"),
            "text/html; charset=utf-8",
        )
    else:
        return False
    return True


__all__ = ["AssetGetOperations", "handle_asset_get"]
