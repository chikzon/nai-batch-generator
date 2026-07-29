# -*- coding: utf-8 -*-
"""브라우저·HTTP·손상 설정이 공유하는 저장 전 값 검증."""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from src.nai_studio.domain.project_inheritance import (
    normalize_link,
    normalize_projects,
)


NUMERIC_RULES = {
    "steps": (1, 50, True),
    "cfg_scale": (1.0, 10.0, False),
    "cfg_rescale": (0.0, 1.0, False),
    "save_quality": (40, 100, True),
    "seed": (1, 999999999, True),
    "nai_seed": (0, 2**32 - 1, True),
    "uncond_scale": (0.0, 1.5, False),
    "controlnet_strength": (0.0, 2.0, False),
}
PACE_RULES = {
    "delay_min": (0.0, 120.0, False),
    "delay_max": (0.0, 300.0, False),
    "daily_cap": (1, 100000, True),
    "soft_every": (0, 100000, True),
    "soft_seconds": (1, 3600, True),
    "cool_every": (0, 100000, True),
    "cool_seconds": (1, 7200, True),
}


def bounded_number(
    value: Any,
    low: float,
    high: float,
    integer: bool = False,
) -> int | float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("number must be finite")
    if integer:
        number = int(number)
    used = max(low, min(high, number))
    return int(used) if integer else float(used)


def normalize_resolution(value: Any) -> int:
    """NAI 해상도를 64배수인 64..2048 범위로 맞춘다."""
    raw = bounded_number(value, 64, 2048, True)
    return max(64, min(2048, raw // 64 * 64))


def normalize_cast_presets(value: Any) -> list[dict]:
    """캐스트 구조를 검증하되 프롬프트 원문 길이와 내용은 바꾸지 않는다."""
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError(
            "cast presets must be a list with at most 200 items"
        )
    result, seen_ids, seen_names = [], set(), set()
    for preset in value:
        if not isinstance(preset, dict):
            raise ValueError("cast preset must be an object")
        preset_id = preset.get("id")
        name = preset.get("name")
        mode = preset.get("mode", "sequence")
        position_mode = preset.get("position_mode", "")
        members = preset.get("members")
        if (
            not isinstance(preset_id, str)
            or not preset_id
            or len(preset_id) > 120
            or not re.fullmatch(r"[A-Za-z0-9._:-]+", preset_id)
        ):
            raise ValueError("invalid cast preset id")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 120
        ):
            raise ValueError("invalid cast preset name")
        folded_name = name.strip().casefold()
        if preset_id in seen_ids or folded_name in seen_names:
            raise ValueError("duplicate cast preset")
        if mode not in ("sequence", "together"):
            raise ValueError("invalid cast preset mode")
        if position_mode not in ("", "ai", "grid", "coordinate"):
            raise ValueError("invalid cast preset position mode")
        if (
            not isinstance(members, list)
            or not members
            or len(members) > 64
        ):
            raise ValueError(
                "cast preset must contain 1 to 64 members"
            )
        clean_members = []
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("cast member must be an object")
            required_text = ("name", "prompt", "negative")
            optional_text = ("id", "outfit", "source_id")
            list_fields = ("reference_ids", "vibe_ids")
            object_fields = ("variant", "position")
            allowed = set(
                required_text
                + optional_text
                + list_fields
                + object_fields
            )
            if set(member) - allowed:
                raise ValueError("unknown cast member fields")
            cleaned = {}
            for field in required_text:
                text = member.get(field, "")
                if not isinstance(text, str):
                    raise ValueError(
                        "cast member fields must be strings"
                    )
                cleaned[field] = text
            for field in optional_text:
                if field not in member:
                    continue
                text = member[field]
                if not isinstance(text, str):
                    raise ValueError(
                        "cast member fields must be strings"
                    )
                cleaned[field] = text
            for field in list_fields:
                if field not in member:
                    continue
                items = member[field]
                if not isinstance(items, list) or len(items) > 64:
                    raise ValueError(
                        "cast member references must be lists"
                    )
                if any(not isinstance(item, str) for item in items):
                    raise ValueError(
                        "cast member reference ids must be strings"
                    )
                cleaned[field] = list(items)
            for field in object_fields:
                if field not in member:
                    continue
                item = member[field]
                if not isinstance(item, dict):
                    raise ValueError(
                        "cast member variant and position must be objects"
                    )
                cleaned[field] = copy.deepcopy(item)
            clean_members.append(cleaned)
        clean_preset = {
            "id": preset_id,
            "name": name.strip(),
            "members": clean_members,
        }
        if "mode" in preset:
            clean_preset["mode"] = mode
        if "position_mode" in preset:
            clean_preset["position_mode"] = position_mode
        result.append(clean_preset)
        seen_ids.add(preset_id)
        seen_names.add(folded_name)
    return result


def validate_config_value(
    key: str,
    value: Any,
    current: Any,
    *,
    pace_default: dict,
) -> tuple[bool, Any, dict]:
    """한 설정 값을 검증하고 서버가 보정한 값의 근거를 함께 돌려준다."""
    corrections = {}
    try:
        if key in ("width", "height"):
            used = normalize_resolution(value)
        elif key in NUMERIC_RULES:
            used = bounded_number(value, *NUMERIC_RULES[key])
        elif key == "save_max_side":
            used = int(value)
            if used not in (0, 768, 1024, 1536):
                raise ValueError("unsupported save size")
        elif key == "uc_preset":
            used = int(value)
            if used not in (0, 1, 3, 4):
                raise ValueError("unsupported UC preset")
        elif key == "pace":
            if not isinstance(value, dict):
                raise ValueError("pace must be an object")
            used = (
                dict(current)
                if isinstance(current, dict)
                else dict(pace_default)
            )
            for pace_key, rule in PACE_RULES.items():
                if pace_key not in value:
                    continue
                selected = bounded_number(value[pace_key], *rule)
                used[pace_key] = selected
                if selected != value[pace_key]:
                    corrections[f"pace.{pace_key}"] = {
                        "sent": value[pace_key],
                        "used": selected,
                    }
            unknown = set(value) - set(PACE_RULES)
            if unknown:
                raise ValueError(
                    f"unknown pace fields: {sorted(unknown)}"
                )
            if used.get("delay_max", 0) < used.get("delay_min", 0):
                sent = used["delay_max"]
                used["delay_max"] = used["delay_min"]
                corrections["pace.delay_max"] = {
                    "sent": sent,
                    "used": used["delay_max"],
                }
        elif key == "cast_presets":
            used = normalize_cast_presets(value)
        elif key == "blueprint_projects":
            used = normalize_projects(value)
        elif key == "blueprint_inheritance":
            used = normalize_link(value)
        elif key == "position_mode":
            used = str(value or "").strip().lower()
            if used not in ("", "ai", "grid", "coordinate"):
                raise ValueError("unsupported position mode")
        else:
            return True, value, corrections
    except (TypeError, ValueError, OverflowError):
        return False, current, corrections
    if used != value:
        corrections[key] = {"sent": value, "used": used}
    return True, used, corrections


__all__ = [
    "NUMERIC_RULES",
    "PACE_RULES",
    "bounded_number",
    "normalize_cast_presets",
    "normalize_resolution",
    "validate_config_value",
]
