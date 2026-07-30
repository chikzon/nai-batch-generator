# -*- coding: utf-8 -*-
"""HTTP handler and localhost server orchestration.

Route operation dataclasses remain owned by their route modules and are built
through :mod:`app_wiring`.  This module only preserves dispatch order and the
localhost transport lifecycle formerly assembled inside ``ConfigServer``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src.nai_studio.web.app_wiring import build_route_operation_sets
from src.nai_studio.web.http_server import (
    ConfigRequestHandler,
    start_http_server,
)
from src.nai_studio.web.routes.assets import handle_asset_get
from src.nai_studio.web.routes.catalog import handle_catalog_get
from src.nai_studio.web.routes.catalog_post import handle_catalog_post
from src.nai_studio.web.routes.collection_post import (
    handle_collection_post,
)
from src.nai_studio.web.routes.evaluation_post import (
    handle_evaluation_post,
)
from src.nai_studio.web.routes.fragments_post import (
    handle_fragment_post,
)
from src.nai_studio.web.routes.generation import (
    handle_generation_get,
)
from src.nai_studio.web.routes.generation_post import (
    handle_generation_post,
)
from src.nai_studio.web.routes.merge_post import handle_merge_post
from src.nai_studio.web.routes.recovery import handle_recovery_get
from src.nai_studio.web.routes.recovery_post import (
    handle_recovery_post,
)
from src.nai_studio.web.routes.runtime import handle_runtime_get
from src.nai_studio.web.routes.runtime_post import handle_runtime_post
from src.nai_studio.web.routes.settings_post import (
    handle_settings_post,
)


@dataclass(frozen=True)
class ServerRuntimePaths:
    """Static asset root and exclusive localhost port candidates."""

    static_dir: Path
    port_range: range


@dataclass(frozen=True)
class ServerRuntimeOperations:
    """Replaceable transport edges; route behavior stays in route modules."""

    build_operation_sets: Callable[
        [Mapping[str, Any], Any], dict[str, Any]
    ] = build_route_operation_sets
    request_handler: type = ConfigRequestHandler
    start_http: Callable[..., tuple[Any, str | None]] = (
        start_http_server
    )
    browser_open: Callable[[str], Any] | None = None
    logger: Any = None


def _dispatch_get(
    request: Any,
    application: Any,
    operation_sets: Mapping[str, Any],
) -> bool:
    """Run GET route groups in the legacy first-match order."""
    return (
        handle_runtime_get(request, application)
        or handle_recovery_get(
            request, application, operation_sets["recovery_get"]
        )
        or handle_catalog_get(
            request, application, operation_sets["catalog_get"]
        )
        or handle_generation_get(
            request, application, operation_sets["generation_get"]
        )
        or handle_asset_get(
            request, application, operation_sets["asset_get"]
        )
    )


def _dispatch_post(
    request: Any,
    application: Any,
    operation_sets: Mapping[str, Any],
    body: bytes,
) -> bool:
    """Run POST route groups in the legacy first-match order."""
    return (
        handle_merge_post(
            request,
            application,
            operation_sets["recovery_post"],
            operation_sets["collection_post"],
            body,
        )
        or handle_recovery_post(
            request,
            application,
            operation_sets["recovery_post"],
            body,
        )
        or handle_collection_post(
            request,
            application,
            operation_sets["collection_post"],
            body,
        )
        or handle_catalog_post(
            request, operation_sets["catalog_post"], body
        )
        or handle_evaluation_post(
            request,
            application,
            operation_sets["evaluation_post"],
            body,
        )
        or handle_fragment_post(
            request,
            application,
            operation_sets["fragment_post"],
            body,
        )
        or handle_settings_post(
            request,
            application,
            operation_sets["settings_post"],
            body,
        )
        or handle_generation_post(
            request,
            application,
            operation_sets["generation_post"],
            body,
        )
        or handle_runtime_post(
            request,
            application,
            operation_sets["runtime_post"],
            body,
        )
    )


def build_request_handler(
    application: Any,
    operation_sets: Mapping[str, Any],
    paths: ServerRuntimePaths,
    operations: ServerRuntimeOperations,
) -> type:
    """Bind one ConfigServer and its route operations to an HTTP handler."""
    base_handler = operations.request_handler
    static_dir = paths.static_dir

    class Handler(base_handler):

        def do_GET(self) -> None:
            if self._serve_static(static_dir):
                return
            if _dispatch_get(self, application, operation_sets):
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            body = self._read_post_body()
            if body is None:
                return
            if _dispatch_post(
                self, application, operation_sets, body
            ):
                return
            self.send_response(404)
            self.end_headers()

    return Handler


def start_server_runtime(
    application: Any,
    bindings: Mapping[str, Any],
    paths: ServerRuntimePaths,
    operations: ServerRuntimeOperations,
    *,
    open_browser: bool = True,
) -> str | None:
    """Build routes, scan localhost ports, and attach transport to the app."""
    operation_sets = operations.build_operation_sets(
        bindings, application
    )
    handler = build_request_handler(
        application, operation_sets, paths, operations
    )
    httpd, url = operations.start_http(
        application,
        handler,
        port_range=paths.port_range,
        open_browser=open_browser,
        browser_open=operations.browser_open,
        logger=operations.logger,
    )
    application.httpd = httpd
    application.url = url
    return url


__all__ = [
    "ServerRuntimeOperations",
    "ServerRuntimePaths",
    "build_request_handler",
    "start_server_runtime",
]
