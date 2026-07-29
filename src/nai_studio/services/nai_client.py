# -*- coding: utf-8 -*-
"""NovelAI 이미지 요청의 payload 전처리·HTTP·응답 해석 경계."""

from __future__ import annotations

import io
import logging
import random
import uuid
import zipfile
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import requests
from PIL import Image

from src.nai_studio.domain.image_metadata import (
    normalize_prompt,
    png_text_chunks,
    strip_comment_lines,
)
from src.nai_studio.domain.model_presets import (
    merge_quality_suffix,
    merge_uc_preset,
)
from src.nai_studio.domain.nai_payload import (
    annotate_nai_comment,
    build_nai_payload,
)
from src.nai_studio.runtime import fingerprint_payload


log = logging.getLogger(__name__)
DEFAULT_NAI_API_URL = "https://image.novelai.net/ai/generate-image"


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after: float = 60):
        super().__init__(message)
        self.retry_after = max(
            1.0, min(float(retry_after or 60), 600.0)
        )


class AccountBannedError(Exception):
    pass


class AuthError(Exception):
    pass


class APIError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = bool(retryable)


def retry_after_seconds(value: Any, default: float = 60) -> float:
    """Retry-After의 초·HTTP-date를 1..600초의 재시도 간격으로 읽는다."""
    text = str(value or "").strip()
    if not text:
        return float(default)
    try:
        return max(1.0, min(float(text), 600.0))
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
            now = (
                datetime.now(when.tzinfo)
                if when.tzinfo
                else datetime.now()
            )
            return max(
                1.0, min((when - now).total_seconds(), 600.0)
            )
        except (TypeError, ValueError, OverflowError):
            return float(default)


def _character_pairs(chars: Any) -> list[list[str]]:
    pairs = []
    for character in chars or []:
        if isinstance(character, dict):
            pairs.append([
                character.get("prompt", ""),
                character.get("negative", ""),
            ])
        else:
            pair = (list(character) + ["", ""])[:2]
            pairs.append([pair[0], pair[1]])
    return pairs


def _resolve_prompts(
    base_prompt: str,
    negative: str,
    characters: list[list[str]],
    params: dict,
    fragment_resolver: Callable[..., tuple],
) -> tuple[str, str, list[list[str]]]:
    """모든 칸을 한 호출로 주석 제거→조각 해석→NAI 정규화한다."""
    fixed = [
        strip_comment_lines(value)
        for value in (base_prompt, negative)
    ]
    flat_characters = [
        strip_comment_lines(value)
        for pair in characters
        for value in pair
    ]
    if params.get("use_fragments", True):
        resolved, counters = fragment_resolver(
            fixed + flat_characters,
            counters=params.get("_frag_counters"),
        )
        fixed = list(resolved[:2])
        flat_characters = list(resolved[2:])
        if params.get("_frag_counters") is not None:
            params["_frag_counters"].update(counters)
    base_prompt, negative = [
        normalize_prompt(value) for value in fixed
    ]
    flat_characters = [
        normalize_prompt(value) for value in flat_characters
    ]
    for index in range(len(characters)):
        characters[index] = [
            flat_characters[index * 2],
            flat_characters[index * 2 + 1],
        ]
    return base_prompt, negative, characters


def request_nai_image(
    token: str,
    base_prompt: str,
    negative: str,
    width: int,
    height: int,
    *,
    scale: float = 5.5,
    cfg_rescale: float = 0.56,
    steps: int = 28,
    sampler: str = "k_euler_ancestral",
    scheduler: str = "karras",
    uc_preset: int = 3,
    seed: int | None = None,
    variety: bool = False,
    params: dict | None = None,
    chars: Any = None,
    fragment_resolver: Callable[..., tuple],
    blocked_artist_finder: Callable[[str], list] | None = None,
    endpoint: str = DEFAULT_NAI_API_URL,
    max_characters: int = 6,
) -> Image.Image:
    """한 생성 요청을 보내고 추적 메타가 붙은 RGB 이미지를 돌려준다."""
    request_params = dict(params or {})
    characters = _character_pairs(chars)
    base_prompt, negative, characters = _resolve_prompts(
        base_prompt,
        negative,
        characters,
        request_params,
        fragment_resolver,
    )
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    model = request_params.get("model") or "nai-diffusion-4-5-full"
    if request_params.get("quality_toggle"):
        base_prompt = merge_quality_suffix(base_prompt, model)
    negative = merge_uc_preset(
        negative, model, request_params.get("uc_preset")
    )

    if blocked_artist_finder is not None:
        try:
            blocked = blocked_artist_finder(base_prompt)
            if blocked:
                log.warning(
                    "차단해 둔 작가가 프롬프트에 있습니다: %s",
                    ", ".join(blocked),
                )
        except Exception:
            # 차단 목록은 보조 경고이며 사용자 생성 자체를 막지 않는다.
            pass

    people = [
        (caption, character_negative or "")
        for caption, character_negative in characters
        if caption.strip()
    ]
    if len(people) > max_characters:
        log.warning(
            "인물이 %s명인데 NAI는 %s명까지입니다 — 뒤쪽 %s명은 보내지 않습니다.",
            len(people),
            max_characters,
            len(people) - max_characters,
        )
        people = people[:max_characters]
    payload, _ = build_nai_payload(
        base_prompt=base_prompt,
        negative_prompt=negative,
        people=people,
        width=width,
        height=height,
        scale=scale,
        cfg_rescale=cfg_rescale,
        steps=steps,
        sampler=sampler,
        scheduler=scheduler,
        uc_preset=uc_preset,
        seed=seed,
        variety=variety,
        params=request_params,
        warn=log.warning,
        info=log.info,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/x-zip-compressed",
    }
    request_id = f"nai-request-{uuid.uuid4().hex}"
    payload_hash = fingerprint_payload(payload)
    response = requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=120,
    )
    if response.status_code == 429:
        wait = retry_after_seconds(
            response.headers.get("Retry-After"), 60
        )
        raise RateLimitError(
            f"429 Too Many Requests — {wait:g}초 뒤 재시도", wait
        )
    if response.status_code == 403:
        raise AccountBannedError(
            "403 Forbidden — 계정 보호를 위해 즉시 중단합니다."
        )
    if response.status_code == 401:
        raise AuthError("401 — 토큰이 만료되었거나 잘못되었습니다.")
    if response.status_code != 200:
        raise APIError(
            f"HTTP {response.status_code}: {response.text[:200]}",
            status_code=response.status_code,
            retryable=(
                response.status_code == 408
                or response.status_code >= 500
            ),
        )

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        raw = archive.read(archive.namelist()[0])
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    chunks = png_text_chunks(raw)
    image.nai_seed = seed
    image.nai_request_id = request_id
    image.nai_payload_hash = payload_hash
    image.nai_comment = annotate_nai_comment(
        next(
            (
                chunks[key]
                for key in chunks
                if key.lower() == "comment"
            ),
            "",
        ),
        request_params.get("quality_toggle", False),
        uc_preset,
        request_id=request_id,
        payload_hash=payload_hash,
    )
    return image


__all__ = [
    "APIError",
    "AccountBannedError",
    "AuthError",
    "DEFAULT_NAI_API_URL",
    "RateLimitError",
    "request_nai_image",
    "retry_after_seconds",
]
