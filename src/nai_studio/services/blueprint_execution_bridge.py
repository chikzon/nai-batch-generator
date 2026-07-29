# -*- coding: utf-8 -*-
"""Canonical generation blueprint to one legacy single-generation material.

The adapter is deliberately pure.  It neither reads runtime configuration nor
accepts credentials.  The returned values are the prompt, character, resource,
generation and output inputs that the existing single-image executor already
understands.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from src.nai_studio.domain.blueprint import canonical_generation_plan

from .experiment_execution_bridge import (
    _character_slot,
    _mapping,
    _without_secrets,
)


MATERIAL_SCHEMA = "nai-legacy-single-execution-material/v1"
_KNOWN_BLUEPRINT_FIELDS = {
    "schema",
    "source",
    "style",
    "characters",
    "resources",
    "setting",
    "experiment",
    "generation",
    "output",
    "provenance",
    "fingerprint",
    "summary",
}
_OUTPUT_TO_LEGACY = {
    "format": "save_format",
    "quality": "save_quality",
    "clean_metadata": "save_clean",
    "max_side": "save_max_side",
    "directory": "out_dir",
    "by_date": "out_by_date",
}
_DIRECT_GENERATION_FIELDS = {
    "model",
    "width",
    "height",
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
}
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(?:access|api|auth|bearer|persistent|refresh|secret)?"
    r"(?:token|key|password|cookie)(?:$|[_-])",
    re.IGNORECASE,
)
_PST_TOKEN = re.compile(r"pst-[A-Za-z0-9_-]+")


def _secret_free(value: Any) -> Any:
    """Reuse the experiment boundary, then cover camelCase and token values."""
    value = _without_secrets(value)
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            folded = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).casefold()
            if _SECRET_KEY.search(folded):
                continue
            result[str(key)] = _secret_free(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_secret_free(item) for item in value]
    if isinstance(value, str):
        return _PST_TOKEN.sub("[credential removed]", value)
    return deepcopy(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _join_prompt_parts(*parts: Any) -> str:
    """Match the legacy executor's comma joining without changing the source."""
    clean = []
    for part in parts:
        text = _text(part)
        normalized = text.strip().strip(",").strip()
        if normalized:
            clean.append(normalized)
    return ", ".join(clean)


def _value(mapping: Mapping[str, Any], key: str, fallback: Any = None) -> Any:
    return mapping[key] if key in mapping else fallback


def _generation_settings(plan: Mapping[str, Any]) -> dict:
    style = _mapping(plan.get("style"))
    generation = _mapping(plan.get("generation"))
    settings = _mapping(style.get("generation_settings"))
    settings.update(_mapping(generation.get("settings")))
    for key, item in generation.items():
        if key in _DIRECT_GENERATION_FIELDS:
            settings[key] = deepcopy(item)
    return _secret_free(settings)


def _output_material(value: Mapping[str, Any]) -> tuple[dict, dict]:
    output = _mapping(value)
    legacy = {
        legacy_key: deepcopy(output[key])
        for key, legacy_key in _OUTPUT_TO_LEGACY.items()
        if key in output
    }
    passthrough = {
        key: deepcopy(item)
        for key, item in output.items()
        if key not in _OUTPUT_TO_LEGACY
    }
    return _secret_free(legacy), _secret_free(passthrough)


def single_generation_legacy_material(
    blueprint: Mapping[str, Any],
) -> dict:
    """Return token-free material for one existing single-generation call.

    ``call`` contains the values already passed to ``call_nai_api``.
    ``config_overrides`` contains the equivalent legacy configuration fields.
    Unknown fields remain under ``passthrough`` instead of being guessed or
    discarded.
    """
    raw = _mapping(_secret_free(blueprint))
    plan = canonical_generation_plan(raw)
    style = _mapping(plan.get("style"))
    generation = _mapping(plan.get("generation"))
    final = _mapping(generation.get("final"))
    resources = _mapping(plan.get("resources"))

    base_prompt = _text(
        _value(final, "base_prompt", style.get("base"))
    )
    negative_prompt = _text(
        _value(final, "negative_prompt", style.get("negative"))
    )
    settings = _generation_settings(plan)
    resolution = _mapping(generation.get("resolution"))
    width = _value(resolution, "width", generation.get("width"))
    height = _value(resolution, "height", generation.get("height"))
    seed = generation.get("seed") if "seed" in generation else None
    use_coords = bool(
        _value(settings, "use_coords", generation.get("use_coords", False))
    )

    final_characters = final.get("character_prompts")
    final_characters = (
        list(final_characters)
        if isinstance(final_characters, (list, tuple))
        else []
    )
    char_slots = []
    char_centers = []
    call_characters = []
    call_centers = []
    positions = []
    enabled_index = 0
    for character in plan.get("characters") or []:
        if not isinstance(character, Mapping) or character.get("enabled") is False:
            continue
        legacy_slot, _unused_center = _character_slot(character)
        # The shared experiment projection knows the legacy aliases.  Begin
        # with the complete canonical character so fields from a newer schema
        # are not lost, then overlay those normalized legacy names.
        slot = _mapping(_secret_free(character))
        slot.update(legacy_slot)
        final_character = (
            _mapping(final_characters[enabled_index])
            if enabled_index < len(final_characters)
            and isinstance(final_characters[enabled_index], Mapping)
            else {}
        )
        enabled_index += 1

        resolved_prompt = _text(
            _value(
                final_character,
                "prompt",
                character.get("resolved_prompt")
                if character.get("resolved_prompt") is not None
                else _join_prompt_parts(
                    character.get("appearance"), character.get("clothed")
                ),
            )
        )
        character_negative = _text(
            _value(final_character, "negative", character.get("negative"))
        )
        position = _mapping(
            _value(final_character, "position", character.get("position"))
        )
        position_enabled = bool(
            _value(position, "enabled", use_coords)
        )
        center = {
            key: deepcopy(position[key])
            for key in ("x", "y")
            if key in position
        }

        # Keep the source split for editing, and the resolved value for the
        # exact legacy call.  Unknown character fields survive in ``slot``.
        slot["prompt"] = _text(character.get("appearance"))
        slot["outfit"] = _text(character.get("clothed"))
        slot["negative"] = character_negative
        slot["enabled"] = True
        slot["position"] = _secret_free(position)
        char_slots.append(_secret_free(slot))
        char_centers.append(_secret_free(center))
        if resolved_prompt.strip():
            call_characters.append({
                "prompt": resolved_prompt,
                "negative": character_negative,
            })
            call_centers.append(_secret_free(center))
            positions.append({
                "enabled": position_enabled,
                **_secret_free(center),
            })

    output, output_passthrough = _output_material(
        _mapping(plan.get("output"))
    )
    vibes = _secret_free(resources.get("vibes") or [])
    char_refs = _secret_free(resources.get("character_references") or [])
    config_overrides = {
        "base_prompt": base_prompt,
        "negative_prompt": negative_prompt,
        "style_name": _text(style.get("name")),
        "char_slots": deepcopy(char_slots),
        "char_centers": deepcopy(char_centers),
        "vibes": deepcopy(vibes),
        "char_refs": deepcopy(char_refs),
        "use_coords": use_coords,
        **deepcopy(settings),
        **deepcopy(output),
    }
    if width is not None:
        config_overrides["width"] = deepcopy(width)
    if height is not None:
        config_overrides["height"] = deepcopy(height)
    if seed is not None:
        config_overrides["nai_seed"] = deepcopy(seed)

    top_passthrough = {
        key: deepcopy(item)
        for key, item in raw.items()
        if key not in _KNOWN_BLUEPRINT_FIELDS
    }
    generation_passthrough = {
        key: deepcopy(item)
        for key, item in generation.items()
        if key not in {
            "resolution",
            "settings",
            "final",
            "schedule",
            "provenance",
            "seed",
            *_DIRECT_GENERATION_FIELDS,
        }
    }
    result = {
        "schema": MATERIAL_SCHEMA,
        "config_overrides": _secret_free(config_overrides),
        "call": {
            "base_prompt": base_prompt,
            "negative_prompt": negative_prompt,
            "characters": _secret_free(call_characters[:6]),
            "char_centers": _secret_free(call_centers[:6]),
            "positions": _secret_free(positions[:6]),
            "width": deepcopy(width),
            "height": deepcopy(height),
            "seed": deepcopy(seed),
            "generation_settings": deepcopy(settings),
            "resources": {
                "vibes": deepcopy(vibes),
                "character_references": deepcopy(char_refs),
            },
        },
        "output": deepcopy(output),
        "passthrough": _secret_free({
            "blueprint": top_passthrough,
            "source": plan.get("source"),
            "style": {
                key: deepcopy(item)
                for key, item in style.items()
                if key not in {
                    "id",
                    "name",
                    "base",
                    "negative",
                    "parts",
                    "generation_settings",
                    "evidence",
                    "provenance",
                }
            },
            "generation": generation_passthrough,
            "output": output_passthrough,
            "setting": plan.get("setting"),
            "experiment": plan.get("experiment"),
            "provenance": plan.get("provenance"),
        }),
    }
    return _secret_free(result)
