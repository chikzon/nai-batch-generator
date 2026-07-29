# -*- coding: utf-8 -*-
"""생성 결과의 포맷 선택·원자 저장·NAI 메타데이터 보존."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from PIL import Image


log = logging.getLogger(__name__)


def out_format(config: dict | None) -> str:
    """사용자 설정의 결과 포맷을 PNG 또는 WebP로 제한한다."""
    value = str((config or {}).get("save_format", "webp")).lower()
    return "png" if value == "png" else "webp"


def out_clean(config: dict | None) -> tuple[bool, int, int]:
    """메타 제거, 긴 변 상한, 저장 품질을 한 저장 정책으로 읽는다."""
    config = config or {}
    quality = int(config.get("save_quality", 92) or 92)
    if not config.get("save_clean"):
        return False, 0, quality
    return (
        True,
        int(config.get("save_max_side", 0) or 0),
        quality,
    )


def output_clean_args(config: dict | None) -> tuple[bool, int]:
    """기존 저장 호출부가 쓰는 clean·max_side 두 값."""
    clean, max_side, _ = out_clean(config)
    return clean, max_side


def atomic_save_image(path: Any, writer: Callable[[Path], None]) -> Path:
    """완전히 인코딩·fsync한 결과만 최종 파일명으로 노출한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        writer(temporary)
        with open(temporary, "rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def _lineage_comment(image: Image.Image, blueprint_fingerprint: str) -> str:
    comment = getattr(image, "nai_comment", "")
    try:
        decoded = json.loads(str(comment or ""))
        if isinstance(decoded, dict):
            request_id = str(
                getattr(image, "nai_request_id", "") or ""
            )
            payload_hash = str(
                getattr(image, "nai_payload_hash", "") or ""
            )
            blueprint_id = str(
                blueprint_fingerprint
                or getattr(image, "nai_blueprint_fingerprint", "")
                or ""
            )
            if request_id:
                decoded["requestId"] = request_id
            if payload_hash:
                decoded["payloadHash"] = payload_hash
            if blueprint_id:
                decoded["blueprintFingerprint"] = blueprint_id
            return json.dumps(
                decoded,
                ensure_ascii=False,
                separators=(",", ":"),
            )
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return comment


def _clean_copy(
    image: Image.Image,
    path: Path,
    *,
    quality: int,
    fmt: str,
    max_side: int,
) -> Path:
    if max_side and max(image.size) > max_side:
        ratio = max_side / max(image.size)
        image = image.resize(
            (
                max(1, round(image.width * ratio)),
                max(1, round(image.height * ratio)),
            ),
            Image.LANCZOS,
        )
    flat = Image.new("RGB", image.size)
    flat.putdata(list(image.convert("RGB").getdata()))
    if fmt == "png":
        path = path.with_suffix(".png")
        return atomic_save_image(
            path, lambda temporary: flat.save(temporary, "PNG")
        )
    path = path.with_suffix(".webp")
    return atomic_save_image(
        path,
        lambda temporary: flat.save(
            temporary, "WEBP", quality=quality
        ),
    )


def save_with_meta(
    image: Image.Image,
    path: Any,
    quality: int = 92,
    fmt: str = "webp",
    clean: bool = False,
    max_side: int = 0,
    blueprint_fingerprint: str = "",
) -> Path:
    """결과를 원자 저장하고 선택에 따라 NAI 복원 메타·계보를 보존한다."""
    path = Path(path)
    if clean:
        return _clean_copy(
            image,
            path,
            quality=quality,
            fmt=fmt,
            max_side=max_side,
        )
    if fmt == "png" and path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    elif fmt == "webp" and path.suffix.lower() != ".webp":
        path = path.with_suffix(".webp")

    comment = _lineage_comment(image, blueprint_fingerprint)
    exif_bytes = None
    try:
        if comment:
            exif = Image.Exif()
            exif[270] = comment
            exif[305] = "NovelAI"
            exif_bytes = exif.tobytes()
    except Exception as error:
        log.warning("EXIF 준비 실패(그림은 그대로 저장): %s", error)

    if fmt == "png":
        def save_png(temporary: Path) -> None:
            try:
                from PIL import PngImagePlugin

                info = PngImagePlugin.PngInfo()
                if comment:
                    info.add_text("Comment", comment)
                    info.add_text("Software", "NovelAI")
                image.save(temporary, "PNG", pnginfo=info)
            except Exception as error:
                log.warning(
                    "PNG 메타 심기 실패(그림은 그대로 저장): %s",
                    error,
                )
                image.save(temporary, "PNG")

        return atomic_save_image(path, save_png)

    def save_webp(temporary: Path) -> None:
        try:
            if exif_bytes:
                image.save(
                    temporary,
                    "WEBP",
                    quality=quality,
                    exif=exif_bytes,
                )
            else:
                image.save(temporary, "WEBP", quality=quality)
        except Exception:
            image.save(temporary, "WEBP", quality=quality)

    return atomic_save_image(path, save_webp)


def available_output_path(path: Any, fmt: str = "webp") -> Path:
    """기존 결과를 덮지 않는 첫 파일명을 고른다."""
    path = Path(path).with_suffix(".png" if fmt == "png" else ".webp")
    if not path.exists():
        return path
    stem, suffix, number = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem}_{number}{suffix}")
        if not candidate.exists():
            return candidate
        number += 1


_atomic_save_image = atomic_save_image
_ocargs = output_clean_args


__all__ = [
    "_atomic_save_image",
    "_ocargs",
    "atomic_save_image",
    "available_output_path",
    "out_clean",
    "out_format",
    "output_clean_args",
    "save_with_meta",
]
