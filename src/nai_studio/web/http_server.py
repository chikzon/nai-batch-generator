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
    "/ui/studio.js": ("studio.js", "text/javascript; charset=utf-8"),
}


class ConfigRequestHandler(BaseHTTPRequestHandler):
    """기능 라우트가 공유하는 localhost 보안·응답 계약."""

    def log_message(self, *args: Any) -> None:
        pass

    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _trusted_post(self) -> bool:
        """다른 웹사이트가 localhost API를 대신 호출하지 못하게 한다."""
        allowed = {"127.0.0.1", "localhost", "::1"}
        try:
            host = urlparse("http://" + (self.headers.get("Host") or ""))
            if host.hostname not in allowed or host.port != self.server.server_port:
                return False
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
