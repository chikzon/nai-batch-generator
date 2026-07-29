# -*- coding: utf-8 -*-
"""NAI 모델 식별과 Quality·UC 프리셋의 순수 문자열 변환.

NovelAI 메타데이터 복원과 최종 프롬프트 조립이 같은 표를 사용해야 하므로 도메인
경계에 둔다. 파일·설정·HTTP에는 접근하지 않으며 입력 문자열을 자르지 않는다.
"""
from __future__ import annotations

import re


MODELS = [
    ("nai-diffusion-4-5-full", "V4.5 Full (기본)"),
    ("nai-diffusion-4-5-curated", "V4.5 Curated"),
    ("nai-diffusion-4-full", "V4 Full"),
    ("nai-diffusion-4-curated-preview", "V4 Curated"),
    ("nai-diffusion-3", "V3 (Anime)"),
    ("nai-diffusion-furry-3", "V3 Furry"),
]
UC_PRESETS = [(0, "Heavy"), (1, "Light"), (3, "Human Focus"), (4, "None")]


def model_id_from_metadata(value, fallback="nai-diffusion-4-5-full"):
    """NAI PNG의 표시명·Source 문자열을 지원하는 API 모델 ID로 바꾼다."""
    supported = {model_id for model_id, _label in MODELS}
    fallback = fallback if fallback in supported else "nai-diffusion-4-5-full"
    text = str(value or "").strip()
    if text in supported:
        return text
    low = text.casefold()
    curated = "curated" in low
    if re.search(r"\bv?4(?:[._ -]?5)\b", low):
        return "nai-diffusion-4-5-curated" if curated else "nai-diffusion-4-5-full"
    if "furry" in low and re.search(r"\bv?3\b", low):
        return "nai-diffusion-furry-3"
    if re.search(r"\bv?4\b", low):
        return "nai-diffusion-4-curated-preview" if curated else "nai-diffusion-4-full"
    if re.search(r"\bv?3\b", low) or low.startswith("stable diffusion xl"):
        return "nai-diffusion-3"
    return fallback


# NovelAI 공식 Quality Tags 문구. UI와 메타데이터 복원이 함께 쓰는 값이다.
QUALITY_SUFFIX_TEXT = {
    "nai-diffusion-4-5-full":
        "very aesthetic, masterpiece, no text",
    "nai-diffusion-4-5-curated":
        "masterpiece, no text, -0.8::feet::, rating:general",
    "nai-diffusion-4-full":
        "no text, best quality, very aesthetic, absurdres",
    "nai-diffusion-4-curated-preview":
        "rating:general, amazing quality, very aesthetic, absurdres",
    "nai-diffusion-3":
        "best quality, amazing quality, very aesthetic, absurdres",
    "nai-diffusion-furry-3":
        "{best quality}, {amazing quality}",
}
# 기존 테스트·외부 호출 호환용 이름.
QUALITY_SUFFIX = ", " + QUALITY_SUFFIX_TEXT["nai-diffusion-4-5-full"]


def quality_suffix_text(model):
    return QUALITY_SUFFIX_TEXT.get(str(model or ""), "")


def merge_quality_suffix(prompt, model):
    text = quality_suffix_text(model)
    raw = str(prompt or "").rstrip().rstrip(",")
    if not text or raw.endswith(text):
        return raw
    return f"{raw}, {text}" if raw else text


def split_quality_suffix(prompt, model=None):
    """공식 퀄리티 문구를 떼어 ``(사용자 프롬프트, 켜짐)``으로 반환."""
    raw = str(prompt or "").strip().rstrip(",")
    candidates = []
    if model and quality_suffix_text(model):
        candidates.append(quality_suffix_text(model))
    else:
        candidates.extend(QUALITY_SUFFIX_TEXT.values())
    # 이전 배포본이 넣던 잘못된 location 포함 문구는 가져오기에서만 제거한다.
    candidates.extend([
        "location, very aesthetic, masterpiece, no text",
        "location, masterpiece, no text, -0.8::feet::, rating:general",
    ])
    for text in sorted(set(candidates), key=len, reverse=True):
        if raw == text:
            return "", True
        if raw.endswith(", " + text):
            return raw[:-(len(text) + 2)].rstrip().rstrip(","), True
        if raw.startswith(text + ", "):
            return raw[len(text) + 2:].lstrip().lstrip(","), True
        marker = ", " + text + ", "
        if marker in raw:
            left, right = raw.split(marker, 1)
            joined = ", ".join(
                item for item in (left.rstrip(" ,"), right.lstrip(" ,")) if item
            )
            return joined, True
    return raw, False


def restore_quality_prompt(prompt, model, params):
    """명시된 메타데이터 상태를 우선하고 구형 파일만 문구로 추정."""
    if "quality_toggle" in params:
        enabled = bool(params["quality_toggle"])
        if not enabled:
            return str(prompt or "").strip().rstrip(","), False
        base, _ = split_quality_suffix(prompt, model)
        return base, True
    return split_quality_suffix(prompt, model)


# NAI 요청의 ucPreset 숫자는 화면 상태이고 실제 UC 문구 조립은 클라이언트 책임이다.
_V45_FULL_HEAVY = (
    "lowres, artistic error, film grain, scan artifacts, worst quality, "
    "bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, "
    "halftone, screentone, multiple views, logo, too many watermarks, negative space, "
    "blank page"
)
UC_PRESET_TEXT = {
    "nai-diffusion-4-5-full": {
        0: _V45_FULL_HEAVY,
        1: ("lowres, artistic error, scan artifacts, worst quality, bad quality, "
            "jpeg artifacts, multiple views, very displeasing, too many watermarks, "
            "negative space, blank page"),
        3: _V45_FULL_HEAVY + ", @_@, mismatched pupils, glowing eyes, bad anatomy",
        4: "",
    },
    "nai-diffusion-4-5-curated": {
        0: ("blurry, lowres, upscaled, artistic error, film grain, scan artifacts, "
            "worst quality, bad quality, jpeg artifacts, very displeasing, chromatic "
            "aberration, halftone, multiple views, logo, too many watermarks, negative "
            "space, blank page"),
        1: ("blurry, lowres, upscaled, artistic error, scan artifacts, jpeg artifacts, "
            "logo, too many watermarks, negative space, blank page"),
        3: ("blurry, lowres, upscaled, artistic error, film grain, scan artifacts, "
            "bad anatomy, bad hands, worst quality, bad quality, jpeg artifacts, very "
            "displeasing, chromatic aberration, halftone, multiple views, logo, too "
            "many watermarks, @_@, mismatched pupils, glowing eyes, negative space, "
            "blank page"),
        4: "",
    },
    "nai-diffusion-4-full": {
        0: ("blurry, lowres, error, film grain, scan artifacts, worst quality, bad "
            "quality, jpeg artifacts, very displeasing, chromatic aberration, multiple "
            "views, logo, too many watermarks"),
        1: ("blurry, lowres, error, worst quality, bad quality, jpeg artifacts, very "
            "displeasing"),
        4: "",
    },
    "nai-diffusion-4-curated-preview": {
        0: ("blurry, lowres, error, film grain, scan artifacts, worst quality, bad "
            "quality, jpeg artifacts, very displeasing, chromatic aberration, logo, "
            "dated, signature, multiple views, gigantic breasts"),
        1: ("blurry, lowres, error, worst quality, bad quality, jpeg artifacts, very "
            "displeasing, logo, dated, signature"),
        4: "",
    },
    "nai-diffusion-3": {
        0: ("lowres, {bad}, error, fewer, extra, missing, worst quality, jpeg "
            "artifacts, bad quality, watermark, unfinished, displeasing, chromatic "
            "aberration, signature, extra digits, artistic error, username, scan, "
            "[abstract],"),
        1: "lowres, jpeg artifacts, worst quality, watermark, blurry, very displeasing,",
        3: ("lowres, {bad}, error, fewer, extra, missing, worst quality, jpeg "
            "artifacts, bad quality, watermark, unfinished, displeasing, chromatic "
            "aberration, signature, extra digits, artistic error, username, scan, "
            "[abstract], bad anatomy, bad hands, @_@, mismatched pupils, heart-shaped "
            "pupils, glowing eyes,"),
        4: "",
    },
    "nai-diffusion-furry-3": {
        0: ("{{worst quality}}, [displeasing], {unusual pupils}, guide lines, "
            "{{unfinished}}, {bad}, url, artist name, {{tall image}}, mosaic, {sketch "
            "page}, comic panel, impact (font), [dated], {logo}, ych, {what}, {where is "
            "your god now}, {distorted text}, repeated text, {floating head}, {1994}, "
            "{widescreen}, absolutely everyone, sequence, {compression artifacts}, "
            "hard translated, {cropped}, {commissioner name}, unknown text, high "
            "contrast,"),
        1: ("{worst quality}, guide lines, unfinished, bad, url, tall image, "
            "widescreen, compression artifacts, unknown text,"),
        4: "",
    },
}


def uc_preset_text(model, preset):
    """이 모델에서 이 프리셋의 공식 문구."""
    return UC_PRESET_TEXT.get(str(model or ""), {}).get(
        int(preset or 0), ""
    ).strip().rstrip(",")


def merge_uc_preset(negative, model, preset):
    """UC 문구를 네거티브 앞에 중복 없이 붙인다."""
    text = uc_preset_text(model, preset)
    if not text:
        return negative or ""
    negative = (negative or "").strip()
    if negative == text or text in negative:
        return negative
    return f"{text}, {negative}" if negative else text


def split_uc_preset(negative, model=None):
    """UC 문구를 떼어 ``(프리셋 번호, 사용자 네거티브)``로 반환."""
    negative = (negative or "").strip()
    table = UC_PRESET_TEXT.get(str(model or ""), {})
    candidates = list(table.items()) if table else [
        item
        for preset_table in UC_PRESET_TEXT.values()
        for item in preset_table.items()
    ]
    candidates = [
        (number, text.strip().rstrip(","))
        for number, text in candidates
    ]
    for number, text in sorted(candidates, key=lambda item: -len(item[1])):
        if not text:
            continue
        position = negative.find(text)
        if position < 0:
            continue
        before = negative[:position].strip().strip(",").strip()
        after = negative[position + len(text):].strip().strip(",").strip()
        user_text = ", ".join(part for part in (before, after) if part)
        return number, user_text
    return None, negative


__all__ = [
    "MODELS",
    "QUALITY_SUFFIX",
    "QUALITY_SUFFIX_TEXT",
    "UC_PRESETS",
    "UC_PRESET_TEXT",
    "merge_quality_suffix",
    "merge_uc_preset",
    "model_id_from_metadata",
    "quality_suffix_text",
    "restore_quality_prompt",
    "split_quality_suffix",
    "split_uc_preset",
    "uc_preset_text",
]
