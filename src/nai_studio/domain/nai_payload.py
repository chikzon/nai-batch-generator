# -*- coding: utf-8 -*-
"""NAI 생성 파라미터와 API payload 조립.

HTTP·파일·토큰을 소유하지 않는다. 생성 화면과 배치 실행이 같은 NAI 계약을
사용하도록, 이미 해석된 프롬프트와 인물 목록을 요청 JSON으로 바꾸는 책임만 가진다.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from .positioning import normalize_position_mode, position_mode_uses_coords


MAX_CHARACTERS = 6
SAMPLERS = [
    "k_euler_ancestral",
    "k_euler",
    "k_dpmpp_2s_ancestral",
    "k_dpmpp_2m",
    "k_dpmpp_2m_sde",
    "k_dpmpp_sde",
]
NOISE_SCHEDULES = ["karras", "native", "exponential", "polyexponential"]
RESOLUTIONS = [
    (832, 1216, "세로"),
    (1216, 832, "가로"),
    (1024, 1024, "정사각"),
    (1024, 1536, "세로 대형"),
    (1536, 1024, "가로 대형"),
    (1472, 1472, "정사각 대형"),
    (1920, 1088, "와이드"),
    (1088, 1920, "세로 와이드"),
    (512, 768, "세로 작게"),
    (768, 512, "가로 작게"),
    (640, 640, "정사각 작게"),
]

# V3 전용 설정은 V4 요청에서 중립값이어야 한다. UI 저장값은 보존하고 요청 사본만
# 바꾸므로 모델을 오갈 때 사용자의 설정이 사라지지 않는다.
V3_ONLY = {
    "smea": ("sm", False),
    "smea_dyn": ("sm_dyn", False),
    "dynamic_thresholding": ("dynamic_thresholding", False),
    "uncond_scale": ("uncond_scale", 0.0),
    "controlnet_strength": ("controlnet_strength", 1.0),
    "legacy_v3_extend": ("legacy_v3_extend", False),
}
V4_ONLY = (
    "variety",
    "use_coords",
    "deliberate_euler_ancestral_bug",
    "prefer_brownian",
)


def reference_fields(params: Mapping[str, Any]) -> dict[str, Any]:
    """Vibe와 Character Reference를 NAI가 받는 서로 다른 필드로 변환."""
    out: dict[str, Any] = {}
    vibes = params.get("_vibes") or {}
    encoded = vibes.get("encoded") or []
    strengths = vibes.get("strengths") or []
    if encoded:
        extracted = vibes.get("ies") or [0.7] * len(encoded)
        out["reference_image_multiple"] = encoded
        out["reference_strength_multiple"] = strengths
        out["reference_information_extracted_multiple"] = extracted

    refs = params.get("_char_refs") or {}
    images = refs.get("images") or []
    if images and encoded:
        raise ValueError(
            "NAI에서는 바이브와 캐릭터 레퍼런스를 동시에 사용할 수 없습니다. "
            "둘 중 하나를 꺼주세요."
        )
    if images:
        out["director_reference_images"] = images
        out["director_reference_descriptions"] = [
            {
                "caption": {"base_caption": text, "char_captions": []},
                "use_coords": False,
                "use_order": False,
                "legacy_uc": False,
            }
            for text in (refs.get("types") or [])
        ]
        out["director_reference_information_extracted"] = [1.0] * len(images)
        out["director_reference_strength_values"] = refs.get("strengths") or []
        out["director_reference_secondary_strength_values"] = [
            1 - value for value in (refs.get("fidelities") or [])
        ]
    return out


def fixed_seed(cfg: Mapping[str, Any]) -> int | None:
    try:
        value = int(cfg.get("nai_seed") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def seed_for(cfg: Mapping[str, Any], base_seed: int, index: int) -> int:
    value = fixed_seed(cfg)
    if value:
        return value
    return (int(base_seed) + int(index)) % (2 ** 32)


def annotate_nai_comment(
    comment: Any,
    quality_toggle: bool,
    uc_preset: int,
    *,
    request_id: str = "",
    payload_hash: str = "",
    blueprint_fingerprint: str = "",
) -> Any:
    """NAI Comment JSON에 UI 토글과 결과 계보 식별값을 보존."""
    try:
        data = json.loads(str(comment or ""))
        if not isinstance(data, dict):
            return comment
        data["qualityToggle"] = bool(quality_toggle)
        data["ucPreset"] = int(uc_preset)
        if request_id:
            data["requestId"] = str(request_id)
        if payload_hash:
            data["payloadHash"] = str(payload_hash)
        if blueprint_fingerprint:
            data["blueprintFingerprint"] = str(blueprint_fingerprint)
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return comment


def is_v4_model(model: Any) -> bool:
    return str(model or "").startswith("nai-diffusion-4")


def variety_sigma(model: Any) -> float:
    """V4.5는 58.0, 그 외 모델은 19.0 기준 시그마를 사용."""
    return 58.0 if "4-5" in str(model or "") else 19.0


def variety_sigma_value(
    model: Any,
    width: int,
    height: int,
    variety: bool,
    params: Mapping[str, Any],
    *,
    warn: Callable[[str], None] | None = None,
) -> float | None:
    if not variety:
        return None
    if (params.get("_char_refs") or {}).get("images") and warn is not None:
        warn(
            "Variety+와 캐릭터 레퍼런스를 함께 보냅니다 — 다른 앱 두 곳은 결과 이상을 "
            "피하려 이 조합을 막습니다. 문제가 생기면 둘 중 하나를 꺼 보세요 "
            "(SDS-B 조건부)"
        )
    return variety_sigma(model) * ((width * height) / (832 * 1216)) ** 0.5


def image_to_image_fields(
    image_to_image: Mapping[str, Any],
    action: str,
    seed: int,
) -> dict[str, Any]:
    """img2img·인페인트에만 필요한 원본·강도·마스크 필드를 만든다."""
    if action == "generate" or not image_to_image.get("image"):
        return {}
    cap = 1.0 if action == "infill" else 0.99
    strength = min(
        cap, max(0.01, float(image_to_image.get("strength", 0.7))))
    out = {
        "image": image_to_image["image"],
        "strength": strength,
        "noise": float(image_to_image.get("noise", 0.0)),
        "extra_noise_seed": (
            int(image_to_image.get("seed") or seed) - 1
        ) % (2 ** 32),
        "color_correct": False,
    }
    if action == "infill":
        out["mask"] = image_to_image["mask"]
        out["add_original_image"] = True
        out["inpaintImg2ImgStrength"] = strength
    return {key: value for key, value in out.items() if value is not None}


def build_nai_payload(
    *,
    base_prompt: str,
    negative_prompt: str,
    people: Sequence[tuple[str, str]],
    width: int,
    height: int,
    scale: float,
    cfg_rescale: float,
    steps: int,
    sampler: str,
    scheduler: str,
    uc_preset: int,
    seed: int,
    variety: bool,
    params: Mapping[str, Any],
    warn: Callable[[str], None] | None = None,
    info: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """해석이 끝난 생성 설계도를 NAI 요청 payload로 조립.

    반환의 두 번째 값은 실제 모델·action·좌표 사용 여부다. 전송 계층이 응답
    메타데이터를 기록할 때 같은 결정을 재계산하지 않도록 함께 돌려준다.
    """
    prepared = dict(params or {})
    model = prepared.get("model") or "nai-diffusion-4-5-full"
    if is_v4_model(model):
        for key, (_, neutral) in V3_ONLY.items():
            if prepared.get(key) not in (None, neutral) and info is not None:
                info(
                    f"{key} 은(는) V3 전용이라 이 모델에서는 무시합니다 "
                    f"(중립값 {neutral})"
                )
            prepared[key] = neutral

    position_mode = normalize_position_mode(
        prepared.get("position_mode"), prepared.get("use_coords", False))
    use_coords = position_mode_uses_coords(
        position_mode, prepared.get("use_coords", False))
    centers = prepared.get("char_centers") or []

    def center(index: int) -> list[dict[str, float]]:
        if not use_coords:
            return [{"x": 0.5, "y": 0.5}]
        item = (
            centers[index]
            if index < len(centers) and isinstance(centers[index], dict)
            else {}
        )
        return [{
            "x": float(item.get("x", 0.5)),
            "y": float(item.get("y", 0.5)),
        }]

    limited_people = list(people[:MAX_CHARACTERS])
    char_captions = [
        {"char_caption": prompt, "centers": center(index)}
        for index, (prompt, _) in enumerate(limited_people)
    ]
    negative_char_captions = [
        {"char_caption": negative, "centers": center(index)}
        for index, (_, negative) in enumerate(limited_people)
    ]

    image_to_image = prepared.get("_i2i") or {}
    action = "generate"
    if image_to_image.get("image"):
        action = "infill" if image_to_image.get("mask") else "img2img"
        if action == "infill" and not model.endswith("-inpainting"):
            model += "-inpainting"

    parameters = {
        "width": width,
        "height": height,
        "n_samples": 1,
        "steps": steps,
        "scale": scale,
        "uncond_scale": float(prepared.get("uncond_scale", 0.0)),
        "cfg_rescale": cfg_rescale,
        "sampler": sampler,
        "noise_schedule": scheduler,
        "seed": seed,
        "negative_prompt": negative_prompt,
        "params_version": 3,
        "legacy": False,
        "image_format": "png",
        "version": 1,
        "legacy_v3_extend": bool(prepared.get("legacy_v3_extend", False)),
        "add_original_image": True,
        "prefer_brownian": bool(prepared.get("prefer_brownian", True)),
        "deliberate_euler_ancestral_bug": bool(
            prepared.get("deliberate_euler_ancestral_bug", False)),
        "dynamic_thresholding": bool(
            prepared.get("dynamic_thresholding", False)),
        "dynamic_thresholding_percentile": 0.999,
        "dynamic_thresholding_mimic_scale": 10.0,
        "sm": bool(prepared.get("smea", False)),
        "sm_dyn": bool(prepared.get("smea_dyn", False)),
        "skip_cfg_above_sigma": variety_sigma_value(
            model, width, height, variety, prepared, warn=warn),
        "skip_cfg_below_sigma": 0.0,
        "ucPreset": uc_preset,
        "use_coords": use_coords,
        "cfg_sched_eligibility": "enable_for_post_summer_samplers",
        "explike_fine_detail": False,
        "minimize_sigma_inf": False,
        "uncond_per_vibe": True,
        "wonky_vibe_correlation": True,
        "controlnet_strength": float(
            prepared.get("controlnet_strength", 1)),
        "controlnet_model": None,
        "lora_unet_weights": None,
        "lora_clip_weights": None,
        "reference_information_extracted_multiple": [],
        "reference_strength_multiple": [],
        "normalize_reference_strength_multiple": True,
        **reference_fields(prepared),
        **image_to_image_fields(image_to_image, action, seed),
        "characterPrompts": [
            {
                "prompt": prompt,
                "uc": negative,
                "center": center(index)[0],
                "enabled": True,
            }
            for index, (prompt, negative) in enumerate(limited_people)
        ],
        "v4_prompt": {
            "caption": {
                "base_caption": base_prompt,
                "char_captions": char_captions,
            },
            "use_coords": use_coords,
            "use_order": True,
            "legacy_uc": False,
        },
        "v4_negative_prompt": {
            "caption": {
                "base_caption": negative_prompt,
                "char_captions": negative_char_captions,
            },
            "use_coords": use_coords,
            "use_order": False,
            "legacy_uc": False,
        },
        "request_type": "PromptGenerateRequest",
    }
    return {
        "input": base_prompt,
        "model": model,
        "action": action,
        "parameters": parameters,
    }, {
        "model": model,
        "action": action,
        "use_coords": use_coords,
        "params": prepared,
    }


__all__ = [
    "MAX_CHARACTERS",
    "NOISE_SCHEDULES",
    "RESOLUTIONS",
    "SAMPLERS",
    "V3_ONLY",
    "V4_ONLY",
    "annotate_nai_comment",
    "build_nai_payload",
    "fixed_seed",
    "image_to_image_fields",
    "is_v4_model",
    "reference_fields",
    "seed_for",
    "variety_sigma",
    "variety_sigma_value",
]
