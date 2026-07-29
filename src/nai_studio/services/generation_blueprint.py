# -*- coding: utf-8 -*-
"""현재 사용자 상태를 저장 변경 없이 하나의 생성 설계도로 투영한다."""

from __future__ import annotations

import copy
from typing import Any

from src.nai_studio.domain.blueprint import (
    canonical_generation_plan,
    fingerprint_blueprint,
    summarize_blueprint,
)
from src.nai_studio.domain.experiment import canonical_experiment_rule
from src.nai_studio.domain.positioning import (
    normalize_position_mode,
    position_mode_uses_coords,
)
from src.nai_studio.services.character_runtime import slot_prompt
from src.nai_studio.services.variation_bridge import selected_variation_values


BLUEPRINT_GENERATION_KEYS = (
    "model",
    "width",
    "height",
    "nai_seed",
    "steps",
    "cfg_scale",
    "cfg_rescale",
    "sampler",
    "scheduler",
    "uc_preset",
    "quality_toggle",
    "variety",
    "smea",
    "smea_dyn",
    "dynamic_thresholding",
    "uncond_scale",
    "controlnet_strength",
    "prefer_brownian",
    "deliberate_euler_ancestral_bug",
    "use_coords",
    "position_mode",
)


def generation_blueprint(
    config: dict | None,
    *,
    source: Any = None,
    setting: Any = None,
    experiment: Any = None,
) -> dict:
    """현재 설정·캐릭터·자료·출력을 실행 가능한 단일 설계도로 해석한다."""
    config = config or {}
    slots = config.get("char_slots") or []
    centers = config.get("char_centers") or []
    characters = []
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict):
            continue
        effective = selected_variation_values(slot)
        selected = effective["selected_variant"]
        center = (
            centers[index]
            if index < len(centers) and isinstance(centers[index], dict)
            else {"x": 0.5, "y": 0.5}
        )
        characters.append({
            "id": str(slot.get("id") or ""),
            "name": str(slot.get("name") or ""),
            "enabled": slot.get("enabled") is not False,
            "appearance": effective["prompt"],
            "clothed": effective["outfit"],
            "negative": effective["negative"],
            "resolved_prompt": slot_prompt(slot),
            "position": {
                "x": center.get("x", 0.5),
                "y": center.get("y", 0.5),
                "mode": normalize_position_mode(
                    config.get("position_mode"), config.get("use_coords")
                ),
                "enabled": position_mode_uses_coords(
                    config.get("position_mode"), config.get("use_coords")
                ),
            },
            "variant": copy.deepcopy(slot.get("variant") or {}),
            "variants": copy.deepcopy(slot.get("variants") or []),
            "selected_variant_id": effective["selected_variant_id"],
            "reference_ids": copy.deepcopy(
                (
                    selected.get("reference_ids")
                    if "reference_ids" in selected
                    else slot.get("reference_ids")
                )
                or []
            ),
            "vibe_ids": copy.deepcopy(
                (
                    selected.get("vibe_ids")
                    if "vibe_ids" in selected
                    else slot.get("vibe_ids")
                )
                or []
            ),
        })

    active_settings = {
        str(name): copy.deepcopy(state)
        for name, state in (config.get("setting_state") or {}).items()
        if isinstance(state, dict) and state.get("use")
    }

    generation = {
        key: copy.deepcopy(config.get(key))
        for key in BLUEPRINT_GENERATION_KEYS
    }
    generation["seed"] = generation.pop(
        "nai_seed", config.get("nai_seed", 0)
    )
    generation["resolution"] = {
        "width": generation.get("width"),
        "height": generation.get("height"),
    }
    generation["settings"] = {
        key: copy.deepcopy(generation.get(key))
        for key in BLUEPRINT_GENERATION_KEYS
        if key not in ("width", "height", "nai_seed")
    }
    generation["final"] = {
        "base_prompt": str(config.get("base_prompt") or ""),
        "negative_prompt": str(config.get("negative_prompt") or ""),
        "character_prompts": [
            {
                "prompt": item["resolved_prompt"],
                "negative": item["negative"],
                "position": copy.deepcopy(item["position"]),
            }
            for item in characters
            if item.get("enabled")
        ],
    }
    style_settings = {
        key: copy.deepcopy(config.get(key))
        for key in BLUEPRINT_GENERATION_KEYS
        if key not in ("nai_seed", "use_coords", "position_mode")
    }
    blueprint = canonical_generation_plan({
        "source": copy.deepcopy(source or {"kind": "current-config"}),
        "style": {
            "name": str(config.get("style_name") or ""),
            "base": str(config.get("base_prompt") or ""),
            "negative": str(config.get("negative_prompt") or ""),
            "generation_settings": style_settings,
            "parts": {
                "fixed": str(config.get("base_fixed") or ""),
                "variable": str(config.get("base_var") or ""),
                "detail": str(config.get("base_detail") or ""),
            },
        },
        "characters": characters,
        "resources": {
            "vibes": copy.deepcopy(config.get("vibes") or []),
            "character_references": copy.deepcopy(
                config.get("char_refs") or []
            ),
        },
        "setting": copy.deepcopy(
            setting
            or {
                "name": next(iter(active_settings), ""),
                "active": active_settings,
                "cast_presets": copy.deepcopy(
                    config.get("cast_presets") or []
                ),
            }
        ),
        "experiment": canonical_experiment_rule(
            copy.deepcopy(experiment or {"mode": "single"})
        ),
        "generation": generation,
        "output": {
            "format": str(config.get("save_format") or "webp"),
            "quality": config.get("save_quality", 92),
            "clean_metadata": bool(config.get("save_clean")),
            "max_side": config.get("save_max_side", 0),
            "directory": str(config.get("out_dir") or ""),
            "by_date": bool(config.get("out_by_date")),
        },
    })
    blueprint["fingerprint"] = fingerprint_blueprint(blueprint)
    blueprint["summary"] = summarize_blueprint(blueprint)
    return blueprint


__all__ = ["BLUEPRINT_GENERATION_KEYS", "generation_blueprint"]
