# -*- coding: utf-8 -*-
"""arca.live browser relay의 pairing과 전달 자료 검증.

로그인 자료는 쿠키·비밀번호를 앱에 저장하지 않는다 — 사용자가 브라우저에서
고른 게시물의 HTML·이미지 바이트만 localhost로 전달받는다. 전달 요청은
매 실행 발급되는 pairing code와 허용 Origin(arca.live), 크기 제한을 통과해야
하고, 통과한 자료는 기존 공개자료 수집 계약(relay_article)으로만 들어간다 —
별도 저장 체계는 없다.
"""
from __future__ import annotations

import base64
import hmac
import secrets
import threading
from typing import Any

from src.nai_studio.collection.arca import PublicImportError

RELAY_ALLOWED_ORIGIN = "https://arca.live"
RELAY_MAX_HTML_BYTES = 4 * 1024 * 1024
RELAY_MAX_IMAGE_BYTES = 64 * 1024 * 1024
RELAY_MAX_IMAGES = 40

# content-type ↔ 파일 머리(magic)가 서로 맞아야 받는다.
_IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


class RelayPairing:
    """매 실행 새로 발급하는 pairing code. 재발급하면 이전 code는 무효다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._code: str | None = None

    def issue(self) -> dict:
        with self._lock:
            self._code = "-".join(
                secrets.token_hex(2).upper() for _ in range(2))
            return {
                "ok": True,
                "code": self._code,
                "origin": RELAY_ALLOWED_ORIGIN,
            }

    def verify(self, code: Any) -> bool:
        with self._lock:
            issued = self._code
        if not issued or not code:
            return False
        return hmac.compare_digest(str(code).strip().upper(), issued)


def _decoded_images(raw_images: Any) -> tuple[list[tuple[bytes, str]], list[str]]:
    images: list[tuple[bytes, str]] = []
    errors: list[str] = []
    rows = raw_images if isinstance(raw_images, list) else []
    if len(rows) > RELAY_MAX_IMAGES:
        errors.append(
            f"이미지가 너무 많습니다: {len(rows)}개 (최대 {RELAY_MAX_IMAGES})")
        rows = rows[:RELAY_MAX_IMAGES]
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append(f"이미지 {index}: 모양이 잘못됐습니다")
            continue
        content_type = str(row.get("type") or "").split(";", 1)[0].lower()
        magic = _IMAGE_MAGIC.get(content_type)
        if not magic:
            errors.append(f"이미지 {index}: PNG/WebP/JPEG만 받습니다")
            continue
        try:
            data = base64.b64decode(str(row.get("data") or ""), validate=True)
        except Exception:
            errors.append(f"이미지 {index}: base64를 읽지 못했습니다")
            continue
        if not data or len(data) > RELAY_MAX_IMAGE_BYTES:
            errors.append(
                f"이미지 {index}: 비었거나 {RELAY_MAX_IMAGE_BYTES // (1024**2)}"
                "MB를 넘습니다")
            continue
        if not any(data.startswith(item) for item in magic):
            errors.append(f"이미지 {index}: 내용이 형식과 다릅니다")
            continue
        images.append((data, content_type))
    return images, errors


def handle_relay_payload(
    manager: Any,
    pairing: RelayPairing,
    data: Any,
    *,
    origin: str,
    pairing_code: str,
) -> dict:
    """pairing·Origin·크기 검증을 통과한 자료만 기존 수집 계약으로 넘긴다."""
    if origin != RELAY_ALLOWED_ORIGIN:
        return {"ok": False, "error": "허용되지 않은 출처입니다."}
    if not pairing.verify(pairing_code):
        return {
            "ok": False,
            "error": "pairing code가 없거나 틀립니다. 앱에서 새로 발급하세요.",
        }
    data = data if isinstance(data, dict) else {}
    html_text = str(data.get("html") or "")
    if len(html_text.encode("utf-8", "ignore")) > RELAY_MAX_HTML_BYTES:
        return {"ok": False, "error": "게시물 HTML이 너무 큽니다."}
    images, image_errors = _decoded_images(data.get("images"))
    if not html_text.strip():
        return {"ok": False, "error": "게시물 HTML이 비어 있습니다."}
    try:
        result = manager.relay_article(
            str(data.get("url") or ""), html_text, images)
    except PublicImportError as exc:
        return {"ok": False, "error": str(exc)}
    result.setdefault("errors", [])
    result["errors"] = list(image_errors) + list(result["errors"])
    if image_errors:
        result["ok"] = False
    return result


__all__ = [
    "RELAY_ALLOWED_ORIGIN",
    "RELAY_MAX_HTML_BYTES",
    "RELAY_MAX_IMAGE_BYTES",
    "RELAY_MAX_IMAGES",
    "RelayPairing",
    "handle_relay_payload",
]
