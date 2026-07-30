# -*- coding: utf-8 -*-
"""NAI 작업실의 localhost HTTP transport."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MAX_REQUEST_BODY = 128 * 1024 * 1024
STATIC_ASSETS = {
    "/ui/base.css": ("base.css", "text/css; charset=utf-8"),
    "/ui/studio.css": ("studio.css", "text/css; charset=utf-8"),
    "/ui/studio-core.js": ("studio-core.js", "text/javascript; charset=utf-8"),
    "/ui/studio-generation.js": (
        "studio-generation.js",
        "text/javascript; charset=utf-8",
    ),
    "/ui/studio-settings.js": (
        "studio-settings.js",
        "text/javascript; charset=utf-8",
    ),
    "/ui/studio-library.js": (
        "studio-library.js",
        "text/javascript; charset=utf-8",
    ),
    "/ui/studio-builder.js": (
        "studio-builder.js",
        "text/javascript; charset=utf-8",
    ),
    "/ui/studio-admin.js": (
        "studio-admin.js",
        "text/javascript; charset=utf-8",
    ),
    "/ui/studio-bootstrap.js": (
        "studio-bootstrap.js",
        "text/javascript; charset=utf-8",
    ),
    "/ui/studio.js": ("studio.js", "text/javascript; charset=utf-8"),
}


# arca.live browser relay만 받는 교차 출처 예외. 최소·명시적으로 유지한다 —
# 이 경로는 라우트에서 pairing code를 다시 검증한다.
RELAY_POST_PATHS = ("/api/public_collection_relay",)
RELAY_ALLOWED_ORIGIN = "https://arca.live"


class ConfigRequestHandler(BaseHTTPRequestHandler):
    """기능 라우트가 공유하는 localhost 보안·응답 계약."""

    def log_message(self, *args: Any) -> None:
        pass

    def _relay_request(self) -> bool:
        return (
            self.path.startswith(RELAY_POST_PATHS)
            and self.headers.get("Origin") == RELAY_ALLOWED_ORIGIN
        )

    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if self._relay_request():
            # 브라우저의 relay 스크립트가 응답을 읽을 수 있어야 한다.
            self.send_header(
                "Access-Control-Allow-Origin", RELAY_ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler 규약
        """relay 경로의 CORS·Private Network Access preflight만 허용한다."""
        if not self._relay_request():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header(
            "Access-Control-Allow-Origin", RELAY_ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, X-Pairing-Code")
        requested = (
            self.headers.get("Access-Control-Request-Private-Network") or ""
        ).lower()
        if requested == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def _trusted_post(self) -> bool:
        """다른 웹사이트가 localhost API를 대신 호출하지 못하게 한다."""
        allowed = {"127.0.0.1", "localhost", "::1"}
        try:
            host = urlparse("http://" + (self.headers.get("Host") or ""))
            if host.hostname not in allowed or host.port != self.server.server_port:
                return False
            if self.path.startswith(RELAY_POST_PATHS):
                # 유일한 교차 출처 예외 — pairing code 검증은 라우트의 몫이다.
                return self.headers.get("Origin") == RELAY_ALLOWED_ORIGIN
            origin = self.headers.get("Origin")
            if origin:
                source = urlparse(origin)
                if (
                    source.scheme != "http"
                    or source.hostname not in allowed
                    or source.port != self.server.server_port
                ):
                    return False
            fetch_site = (self.headers.get("Sec-Fetch-Site") or "").lower()
            return not fetch_site or fetch_site == "same-origin"
        except (TypeError, ValueError):
            return False

    def _read_post_body(self) -> bytes | None:
        if not self._trusted_post():
            self._json(
                {"ok": False, "error": "허용되지 않은 요청 출처입니다."},
                status=403,
            )
            return None
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._json(
                {"ok": False, "error": "잘못된 Content-Length입니다."},
                status=400,
            )
            return None
        if length < 0 or length > MAX_REQUEST_BODY:
            self._json({"ok": False, "error": "요청 본문이 너무 큽니다."}, status=413)
            return None
        return self.rfile.read(length) if length else b""

    def _serve_static(self, root: str | Path) -> bool:
        asset = STATIC_ASSETS.get(self.path)
        if asset is None:
            return False
        filename, content_type = asset
        path = Path(root) / filename
        if not path.is_file():
            self.send_response(404)
            self.end_headers()
            return True
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Windows에서 이미 사용 중인 포트의 중복 바인딩을 막는다."""

    allow_reuse_address = False


def start_http_server(
    application: Any,
    handler: type[BaseHTTPRequestHandler],
    *,
    port_range: range,
    open_browser: bool,
    browser_open: Any,
    logger: Any,
) -> tuple[ThreadingHTTPServer | None, str | None]:
    """포트를 하나만 점유하고 기존 ConfigServer 상태에 연결해 실행한다."""
    for port in port_range:
        try:
            httpd = ExclusiveThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            continue
        httpd.application = application
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/"
        logger.info(f"🖼  설정 / 실시간 미리보기: {url}")
        if open_browser:
            try:
                browser_open(url)
            except Exception:
                pass
        return httpd, url
    logger.error("서버용 포트를 찾지 못했습니다 (8787~8796 모두 사용 중).")
    return None, None


__all__ = [
    "ConfigRequestHandler",
    "MAX_REQUEST_BODY",
    "STATIC_ASSETS",
    "start_http_server",
]
