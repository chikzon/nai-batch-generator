# -*- coding: utf-8 -*-
"""캐릭터 이미지 시험 작업대의 순수 이미지·저장 변환."""
from __future__ import annotations

import copy
import io
import json
from typing import Any, Mapping

from PIL import Image


def reference_inset_canvas(source_bytes: bytes, width: int, height: int) -> dict:
    """원본을 왼쪽에 보존하고 오른쪽만 다시 그릴 infill 재료를 만든다."""
    width, height = int(width), int(height)
    if not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise ValueError("Reference inset 해상도는 256~2048px여야 합니다.")
    if width % 64 or height % 64:
        raise ValueError("Reference inset 해상도는 64px 단위여야 합니다.")
    reference_width = max(
        128, min(width - 128, round(width * 0.48 / 64) * 64))
    with Image.open(io.BytesIO(source_bytes)) as source:
        source = source.convert("RGB")
        ratio = min(reference_width / source.width, height / source.height)
        resized = source.resize((
            max(1, round(source.width * ratio)),
            max(1, round(source.height * ratio)),
        ), Image.LANCZOS)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(
        resized,
        ((reference_width - resized.width) // 2,
         (height - resized.height) // 2),
    )
    mask = Image.new("L", (width, height), 0)
    mask.paste(255, (max(0, reference_width - 8), 0, width, height))
    image_buf, mask_buf = io.BytesIO(), io.BytesIO()
    canvas.save(image_buf, "PNG")
    mask.save(mask_buf, "PNG")
    return {
        "image": image_buf.getvalue(),
        "mask": mask_buf.getvalue(),
        "width": width,
        "height": height,
        "reference_width": reference_width,
    }


def apply_character_variation_candidates(
    legacy_character: Mapping[str, Any],
    candidates: Mapping[str, Any],
    *,
    local_ref: str,
    save_as: str,
) -> dict:
    """승인 후보를 기존 캐릭터 사본에 append-only로 적용한다."""
    if save_as not in ("representative", "evidence", "variation"):
        raise ValueError("대표·근거·variation 중 저장 위치를 골라주세요.")
    character = copy.deepcopy(dict(legacy_character))

    def append_unique(field: str, value: Any) -> None:
        rows = character.setdefault(field, [])
        signature = json.dumps(
            value, ensure_ascii=False, sort_keys=True, default=str)
        if not any(
            json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            == signature
            for item in rows
        ):
            rows.append(copy.deepcopy(value))

    append_unique("images", local_ref)
    evidence = copy.deepcopy(dict(candidates["evidence_candidate"]))
    evidence["image_ref"] = local_ref
    evidence["status"] = "approved"
    evidence.pop("domain_proposal", None)
    append_unique("evidence_images", local_ref)
    append_unique("evidence", evidence)
    if save_as == "representative":
        previous = character.get(
            "representative", character.get("representative_image"))
        if previous and previous != local_ref:
            append_unique("evidence_images", previous)
            append_unique("images", previous)
        character["representative"] = local_ref
    elif save_as == "variation":
        variant = copy.deepcopy(dict(candidates["variant_candidate"]))
        variant["image_ref"] = local_ref
        variant["status"] = "approved"
        variant.pop("domain_proposal", None)
        append_unique("variation_images", local_ref)
        if not any(
            str(item.get("id") or "") == str(variant.get("id") or "")
            for item in (character.get("variants") or [])
            if isinstance(item, Mapping)
        ):
            character.setdefault("variants", []).append(variant)
    return character
