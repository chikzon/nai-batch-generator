# -*- coding: utf-8 -*-
"""Vibe·Character Reference 파일을 NAI 전송 배열로 준비한다."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from PIL import Image

from src.nai_studio.services.nai_client import (
    APIError,
    AuthError,
    RateLimitError,
)


REFERENCE_CANVASES = (
    (1024, 1536),
    (1536, 1024),
    (1472, 1472),
)


@dataclass(frozen=True)
class ReferenceOperations:
    """파일·설정 저장과 HTTP를 주입해 사용자 캐시 경계를 유지한다."""

    vibe_dir: Path
    settings_file: Path
    default_config: Mapping[str, Any]
    vibe_paths: Callable[[str], tuple[Path, Path]]
    encode_vibe: Callable[..., str]
    atomic_write_text: Callable[..., Any]
    transaction: Callable[[Path], Any]
    load_json: Callable[[Path], Any]
    save_config: Callable[[dict], Any]
    http_post: Callable[..., Any]
    warning: Callable[..., Any]
    info: Callable[..., Any]


def image_png_base64(image_bytes_or_image: Any) -> tuple[str, int, int]:
    """이미 PNG면 원본을 보존하고 아니면 같은 크기의 PNG로 바꾼다."""
    if isinstance(image_bytes_or_image, (bytes, bytearray)):
        raw = bytes(image_bytes_or_image)
        try:
            image = Image.open(io.BytesIO(raw))
            if (image.format or "").upper() == "PNG":
                return (
                    base64.b64encode(raw).decode("ascii"),
                    image.width,
                    image.height,
                )
        except Exception:
            pass
        image = Image.open(io.BytesIO(raw))
    else:
        image = image_bytes_or_image
    buffer = io.BytesIO()
    image.convert(
        "RGBA" if image.mode == "RGBA" else "RGB"
    ).save(buffer, "PNG")
    return (
        base64.b64encode(buffer.getvalue()).decode("ascii"),
        image.width,
        image.height,
    )


def encode_vibe(
    operations: ReferenceOperations,
    endpoint: str,
    token: str,
    image_bytes: bytes,
    information_extracted: float = 0.7,
    model: str = "nai-diffusion-4-5-full",
) -> str:
    """Vibe 인코딩 응답 바이트를 재사용 가능한 base64 캐시로 만든다."""
    image, _, _ = image_png_base64(image_bytes)
    response = operations.http_post(
        endpoint,
        timeout=180,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "image": image,
            "information_extracted": float(information_extracted),
            "model": model,
        },
    )
    if response.status_code == 401:
        raise AuthError("401 — 토큰을 확인하세요.")
    if response.status_code == 429:
        raise RateLimitError("429 Too Many Requests")
    if response.status_code != 200:
        raise APIError(
            "바이브 인코딩 실패 "
            f"HTTP {response.status_code}: {response.text[:200]}"
        )
    return base64.b64encode(response.content).decode("ascii")


def prepare_vibes(
    operations: ReferenceOperations,
    config: dict,
    token: str,
) -> tuple[list[str], list[float], list[float], int]:
    """켜진 Vibe를 필요할 때만 인코딩하고 캐시 상태만 최신 설정에 병합한다."""
    encoded = []
    strengths = []
    information = []
    newly_encoded = 0
    changed = False
    for vibe in config.get("vibes", []):
        if not vibe.get("enabled"):
            continue
        image_path, encoded_path = operations.vibe_paths(
            vibe.get("id", "")
        )
        extracted = float(vibe.get("info_extracted", 0.7))
        needs_encoding = (
            not encoded_path.exists()
            or abs(
                float(vibe.get("encoded_ie", -1)) - extracted
            ) > 1e-9
        )
        if needs_encoding:
            if not image_path.exists():
                operations.warning(
                    "바이브 원본이 없습니다: %s",
                    image_path.name,
                )
                continue
            value = operations.encode_vibe(
                token,
                image_path.read_bytes(),
                extracted,
                config.get("model")
                or "nai-diffusion-4-5-full",
            )
            operations.atomic_write_text(
                encoded_path,
                value,
                encoding="ascii",
                keep_backup=False,
            )
            vibe["encoded_ie"] = extracted
            newly_encoded += 1
            changed = True
            operations.info(
                "바이브 인코딩: %s (정보추출 %s) — 2 Anlas",
                vibe.get("name"),
                extracted,
            )
        encoded.append(encoded_path.read_text(encoding="ascii"))
        strengths.append(float(vibe.get("strength", 0.6)))
        information.append(extracted)
    if changed:
        _save_encoded_state(operations, config)
    return encoded, strengths, information, newly_encoded


def _save_encoded_state(
    operations: ReferenceOperations,
    config: dict,
) -> None:
    """긴 인코딩 중 다른 실행본이 저장한 설정 위에 캐시 필드만 병합한다."""
    with operations.transaction(operations.vibe_dir.parent.parent):
        latest = dict(operations.default_config)
        if operations.settings_file.is_file():
            loaded = operations.load_json(operations.settings_file)
            if isinstance(loaded, dict):
                latest.update(loaded)
        encoded_information = {
            item.get("id"): item.get("encoded_ie")
            for item in config.get("vibes", [])
            if (
                item.get("id")
                and item.get("encoded_ie") is not None
            )
        }
        for item in latest.get("vibes", []):
            if item.get("id") in encoded_information:
                item["encoded_ie"] = encoded_information[item.get("id")]
        operations.save_config(latest)


def reference_canvas(
    width: int,
    height: int,
) -> tuple[int, int]:
    """원본 비율에 가장 가까운 NAI 허용 캔버스를 고른다."""
    aspect = width / height if height else 1.0
    return min(
        REFERENCE_CANVASES,
        key=lambda canvas: abs(canvas[0] / canvas[1] - aspect),
    )


def letterbox_reference(raw: bytes) -> tuple[str, tuple[int, int]]:
    """비율을 보존한 검은 레터박스로 NAI 허용 PNG 캔버스를 만든다."""
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        canvas_width, canvas_height = reference_canvas(
            image.width,
            image.height,
        )
        ratio = min(
            canvas_width / image.width,
            canvas_height / image.height,
        )
        width = max(1, round(image.width * ratio))
        height = max(1, round(image.height * ratio))
        output = Image.new(
            "RGB",
            (canvas_width, canvas_height),
            (0, 0, 0),
        )
        output.paste(
            image.resize((width, height), Image.LANCZOS),
            (
                (canvas_width - width) // 2,
                (canvas_height - height) // 2,
            ),
        )
    buffer = io.BytesIO()
    output.save(buffer, "PNG")
    return (
        base64.b64encode(buffer.getvalue()).decode("ascii"),
        (canvas_width, canvas_height),
    )


def prepare_character_references(
    operations: ReferenceOperations,
    config: dict,
    letterbox: Callable[
        [bytes], tuple[str, tuple[int, int]]
    ] = letterbox_reference,
) -> tuple[list[str], list[str], list[float], list[float]]:
    """켜진 Character Reference를 정렬된 네 배열로 준비한다."""
    images = []
    types = []
    strengths = []
    fidelities = []
    for reference in config.get("char_refs", []):
        if not reference.get("enabled"):
            continue
        raw = reference.get("_image_bytes")
        path = (
            operations.vibe_dir
            / f"{reference.get('id', '')}.ref.png"
        )
        if raw is None:
            if not path.exists():
                if reference.get("_required"):
                    raise ValueError(
                        "시험용 Character Reference 원본을 찾지 못했습니다."
                    )
                continue
            raw = path.read_bytes()
        try:
            encoded, canvas = letterbox(raw)
        except Exception as error:
            if reference.get("_required"):
                raise ValueError(
                    "시험용 Character Reference를 준비하지 못했습니다: "
                    f"{error}"
                ) from error
            operations.warning(
                "캐릭터 레퍼런스 준비 실패(%s): %s",
                path.name,
                error,
            )
            continue
        operations.info(
            "캐릭터 레퍼런스 %s → %s×%s 로 맞춤",
            path.stem,
            canvas[0],
            canvas[1],
        )
        images.append(encoded)
        types.append(
            reference.get("ref_type") or "character&style"
        )
        strengths.append(float(reference.get("strength", 0.6)))
        fidelities.append(float(reference.get("fidelity", 0.6)))
    return images, types, strengths, fidelities


__all__ = [
    "REFERENCE_CANVASES",
    "ReferenceOperations",
    "encode_vibe",
    "image_png_base64",
    "letterbox_reference",
    "prepare_character_references",
    "prepare_vibes",
    "reference_canvas",
]
