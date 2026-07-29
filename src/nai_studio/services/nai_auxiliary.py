# -*- coding: utf-8 -*-
"""Director·업스케일·구독 잔액의 보조 NAI HTTP 호출."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Any, Callable

from src.nai_studio.services.nai_client import (
    APIError,
    AuthError,
    RateLimitError,
)


SUBSCRIPTION_URL = "https://image.novelai.net/user/subscription"


@dataclass(frozen=True)
class AuxiliaryOperations:
    """HTTP와 PNG 변환을 주입해 외부 호출을 mock 가능한 경계로 둔다."""

    http_post: Callable[..., Any]
    http_get: Callable[..., Any]
    image_png_base64: Callable[[Any], tuple[str, int, int]]
    info: Callable[..., Any]
    warning: Callable[..., Any]


def last_zip_item(content: bytes) -> bytes:
    """NAI 보조 API ZIP의 마지막 결과 파일을 읽는다."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
        ]
        if not names:
            raise APIError("응답 zip 이 비어 있습니다.")
        return archive.read(names[-1])


def call_director(
    operations: AuxiliaryOperations,
    endpoint: str,
    token: str,
    image_bytes: bytes,
    method: str,
    prompt: str | None = None,
    defry: int = 0,
) -> bytes:
    """Director augment-image 요청의 기존 payload와 응답을 유지한다."""
    image, width, height = operations.image_png_base64(image_bytes)
    body = {
        "req_type": method,
        "image": image,
        "width": width,
        "height": height,
    }
    if prompt is not None:
        body["prompt"] = prompt
        body["defry"] = int(defry or 0)
    response = operations.http_post(
        endpoint,
        json=body,
        timeout=180,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/x-zip-compressed",
        },
    )
    if response.status_code == 429:
        raise RateLimitError("429 Too Many Requests")
    if response.status_code == 401:
        raise AuthError("401 — 토큰을 확인하세요.")
    if response.status_code != 200:
        raise APIError(
            f"HTTP {response.status_code}: {response.text[:200]}"
        )
    return last_zip_item(response.content)


def call_upscale(
    operations: AuxiliaryOperations,
    endpoints: tuple[str, ...],
    token: str,
    image_bytes: bytes,
    scale: int = 4,
) -> bytes:
    """첫 업스케일 호스트 실패 시 기존 순서로 다음 호스트를 시도한다."""
    image, width, height = operations.image_png_base64(image_bytes)
    body = {
        "image": image,
        "width": width,
        "height": height,
        "scale": int(scale),
    }
    last_error = ""
    for endpoint in endpoints:
        response = operations.http_post(
            endpoint,
            json=body,
            timeout=180,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/x-zip-compressed",
            },
        )
        if response.status_code == 200:
            return last_zip_item(response.content)
        if response.status_code == 401:
            raise AuthError("401 — 토큰을 확인하세요.")
        last_error = (
            f"HTTP {response.status_code}: {response.text[:160]}"
        )
        operations.info(
            "업스케일 %s → %s",
            endpoint,
            last_error,
        )
    raise APIError(last_error or "업스케일 실패")


def fetch_anlas_balance(
    operations: AuxiliaryOperations,
    token: str,
    endpoint: str = SUBSCRIPTION_URL,
) -> dict | None:
    """구독 응답을 기존 잔액·등급·활성 상태 스키마로 축약한다."""
    if not token:
        return None
    try:
        response = operations.http_get(
            endpoint,
            timeout=15,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            return None
        data = response.json()
        training = data.get("trainingStepsLeft") or {}
        fixed = int(training.get("fixedTrainingStepsLeft") or 0)
        purchased = int(
            training.get("purchasedTrainingSteps") or 0
        )
        tier = data.get("tier")
        return {
            "fixed": fixed,
            "purchased": purchased,
            "total": fixed + purchased,
            "tier": tier,
            "opus": tier == 3,
            "active": bool(data.get("active")),
        }
    except Exception as error:
        operations.warning("Anlas 조회 실패: %s", error)
        return None


__all__ = [
    "AuxiliaryOperations",
    "SUBSCRIPTION_URL",
    "call_director",
    "call_upscale",
    "fetch_anlas_balance",
    "last_zip_item",
]
