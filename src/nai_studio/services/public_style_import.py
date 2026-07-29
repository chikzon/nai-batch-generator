# -*- coding: utf-8 -*-
"""공개 이미지의 NAI 메타데이터를 그림체 저장 레코드로 변환한다."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PublicStyleImportOperations:
    extract_metadata: Callable[[bytes, str], dict]
    model_id: Callable[[Any, str], str]
    split_uc_preset: Callable[[str, str], tuple[Any, str]]
    restore_quality_prompt: Callable[[str, str, dict], tuple[str, Any]]
    parse_artist_combo: Callable[[str], tuple[list, list]]


def style_record_from_public_image(
    operations: PublicStyleImportOperations,
    data: bytes,
    content_type: str,
    article: dict,
) -> dict | None:
    """공개 이미지의 원문·설정·캐릭터를 손실 없이 그림체 묶음으로 옮긴다."""
    metadata = operations.extract_metadata(data, content_type)
    if metadata["metadata_status"] != "ok":
        return None

    params = dict(metadata.get("params") or {})
    source_model = operations.model_id(
        params.get("model"),
        "nai-diffusion-4-5-full",
    )
    uc_preset, user_negative = operations.split_uc_preset(
        metadata.get("negative") or "",
        source_model,
    )
    if "uc_preset" not in params and uc_preset is not None:
        params["uc_preset"] = uc_preset
        params["uc_preset_guessed"] = True

    base_prompt, quality_toggle = operations.restore_quality_prompt(
        metadata.get("base") or "",
        source_model,
        params,
    )
    if "quality_toggle" not in params:
        params["quality_toggle"] = quality_toggle
        params["quality_toggle_guessed"] = True

    artists, rest = operations.parse_artist_combo(base_prompt)
    article_id = str(article.get("article_id") or "")
    image_digest = hashlib.sha256(data).hexdigest()
    return {
        "id": f"arca-{article_id}-{image_digest[:12]}",
        "title": str(
            article.get("title") or f"아카라이브 {article_id}"
        )[:160],
        "source": "아카라이브",
        "tab": str(article.get("board_tab") or ""),
        "posted_at": str(article.get("posted_at") or ""),
        "recommend": article.get("recommend"),
        "views": article.get("views"),
        "url": str(article.get("source_url") or ""),
        "count": len(artists),
        "combo": ", ".join(
            f"{weight:g}::artist:{name}::"
            if weight is not None
            else f"artist:{name}"
            for weight, name in artists
        ),
        "artists": [name for _, name in artists],
        "weights": {
            name: weight if weight is not None else 1.0
            for weight, name in artists
        },
        "base": base_prompt,
        "rest": ", ".join(rest),
        "negative": (
            user_negative
            if uc_preset is not None
            else metadata.get("negative") or ""
        ),
        "negative_full": metadata.get("negative") or "",
        "characters": copy.deepcopy(metadata.get("characters") or []),
        "metadata_raw": copy.deepcopy(metadata.get("raw") or {}),
        "params": params,
        "images": [],
    }


__all__ = [
    "PublicStyleImportOperations",
    "style_record_from_public_image",
]
