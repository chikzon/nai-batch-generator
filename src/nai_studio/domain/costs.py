# -*- coding: utf-8 -*-
"""NAI 생성 비용과 Opus 무료 조건 계산."""
from __future__ import annotations

import math
from typing import Any, Mapping


# NAIS3의 공개 계산식과 NAI의 Opus 조건을 한곳에 둔다. 생성·비교·UI 미리보기는
# 같은 함수를 써야 장당 비용과 총액이 서로 어긋나지 않는다.
ANLAS_A = 2.951823174884865e-6
ANLAS_B = 5.753298233447344e-7
OPUS_FREE_PX = 1024 * 1024
OPUS_FREE_STEPS = 28


def anlas_per_image(
    width: int,
    height: int,
    steps: int,
    strength: float = 1.0,
    char_refs: int = 0,
) -> int:
    px = max(int(width) * int(height), 65536)
    base = math.ceil(
        (ANLAS_A * px + ANLAS_B * px * int(steps)) * float(strength))
    return max(base, 2) + 5 * int(char_refs)


def anlas_estimate(
    cfg: Mapping[str, Any],
    count: int = 1,
    width: int | None = None,
    height: int | None = None,
    opus: bool = False,
    char_refs: int = 0,
    mode: str = "t2i",
    strength: float = 1.0,
) -> dict[str, Any]:
    """장당·총액과 무료 여부를 같은 계약으로 계산한다."""
    w = int(width or cfg.get("width", 832))
    h = int(height or cfg.get("height", 1216))
    steps = int(cfg.get("steps", 28))
    px = max(w * h, 65536)
    uses_base = mode in ("img2img", "infill")
    free_eligible = (
        px <= OPUS_FREE_PX
        and steps <= OPUS_FREE_STEPS
        and not uses_base
    )
    generation_free = bool(opus) and free_eligible
    base_per = anlas_per_image(
        w, h, steps, strength if uses_base else 1.0, char_refs=0)
    ref_fee = 5 * max(int(char_refs), 0)
    per = (0 if generation_free else base_per) + ref_fee
    total_free = per == 0
    if generation_free and ref_fee:
        why = (
            f"Opus 무료 생성 + 캐릭터 레퍼런스 {int(char_refs)}개 "
            f"장당 {ref_fee} Anlas"
        )
    elif total_free:
        why = "Opus 무료 (1024² 이하 · 28스텝 이하)"
    elif uses_base:
        why = "원본 그림을 쓰는 작업은 Opus 무료가 아닙니다 (img2img·인페인트)"
    elif not opus and px <= OPUS_FREE_PX and steps <= OPUS_FREE_STEPS:
        why = "무료 크기·스텝 범위지만 Opus 적용 여부가 확인되지 않았습니다"
    else:
        why = (
            f"무료 조건 초과 — {w}×{h}·{steps}스텝 "
            f"(무료는 1024² 이하·28스텝 이하)"
        )
    return {
        "per_image": per,
        "per_image_paid": base_per + ref_fee,
        "total": per * max(int(count), 0),
        "count": int(count),
        "free": total_free,
        "free_eligible": free_eligible,
        "generation_free": generation_free,
        "char_ref_fee": ref_fee,
        "mode": mode,
        "width": w,
        "height": h,
        "steps": steps,
        "why": why,
    }


__all__ = [
    "ANLAS_A",
    "ANLAS_B",
    "OPUS_FREE_PX",
    "OPUS_FREE_STEPS",
    "anlas_estimate",
    "anlas_per_image",
]
