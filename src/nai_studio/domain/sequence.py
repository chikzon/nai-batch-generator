# -*- coding: utf-8 -*-
"""세팅(생성 계획)에 붙는 순서 실행 계약.

Storyteller·Sequence를 별도 저장 기능으로 복제하지 않고, 생성 설계도의 단계별
명시값과 진행 규칙으로 표현한다. 모든 함수는 사본만 만들며 prompt를 분해하거나
기존 사용자 자료를 변환하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


SEQUENCE_SCHEMA = "nai-sequence-plan/v1"
SEQUENCE_PROGRESSIONS = ("cycle", "manual", "once")
SEQUENCE_DIRECTIONS = ("forward", "backward")
SEED_POLICY_MODES = ("inherit", "fixed", "random", "sequence")
VIBE_CONTINUITY_SOURCES = ("none", "first", "previous", "last")

_IDENTITY_IGNORED = {
    "schema", "id", "fingerprint", "created_at", "updated_at", "runtime",
}


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _list(value: Any, field: str) -> list:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list")
    return deepcopy(list(value))


def _hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("sequence plan must contain JSON-compatible values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _positive_repeat(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        repeat = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if repeat < 1:
        raise ValueError(f"{field} must be a positive integer")
    return repeat


def _seed_policy(value: Any) -> dict:
    result = _mapping(value, "seed_policy")
    mode = result.get("mode", "inherit")
    if mode not in SEED_POLICY_MODES:
        raise ValueError(
            "seed policy mode must be one of: " + ", ".join(SEED_POLICY_MODES)
        )
    result["mode"] = mode
    if mode == "fixed" and "seed" not in result:
        raise ValueError("fixed seed policy requires seed")
    return result


def _vibe_continuity(value: Any) -> dict:
    result = _mapping(value, "vibe_continuity")
    source = result.get("source", "none")
    if source not in VIBE_CONTINUITY_SOURCES:
        raise ValueError(
            "vibe continuity source must be one of: "
            + ", ".join(VIBE_CONTINUITY_SOURCES)
        )
    result["source"] = source
    return result


def _step_body(value: Mapping[str, Any]) -> dict:
    raw = _mapping(value, "sequence step")
    result = {
        "name": deepcopy(raw.get("name", "")),
        # 문자열·배열 어느 형식이든 원문 그대로 둔다.
        "include": deepcopy(raw.get("include")),
        "exclude": deepcopy(raw.get("exclude")),
        "rating": deepcopy(raw.get("rating")),
        "resolution": _mapping(raw.get("resolution"), "resolution"),
        "seed_policy": _seed_policy(raw.get("seed_policy")),
        "character_overrides": _mapping(
            raw.get("character_overrides"),
            "character_overrides",
        ),
        "style_overrides": _mapping(
            raw.get("style_overrides"),
            "style_overrides",
        ),
        "background": deepcopy(raw.get("background")),
        "outfit": deepcopy(raw.get("outfit")),
        "carry": {
            **_mapping(raw.get("carry"), "carry"),
            "background": bool(
                _mapping(raw.get("carry"), "carry").get("background", False)
            ),
            "outfit": bool(
                _mapping(raw.get("carry"), "carry").get("outfit", False)
            ),
        },
        "vibe_continuity": _vibe_continuity(raw.get("vibe_continuity")),
        "repeat": _positive_repeat(raw.get("repeat", 1), "step repeat"),
    }
    for key, item in raw.items():
        if key not in result and key not in {"id", "fingerprint"}:
            result[key] = deepcopy(item)
    return result


def fingerprint_sequence_step(value: Mapping[str, Any]) -> str:
    """표시 시각·명시 ID와 무관한 단계 내용 지문."""
    data = _step_body(value)
    return _hash({
        key: item
        for key, item in data.items()
        if key not in _IDENTITY_IGNORED
    })


def sequence_step_id(value: Mapping[str, Any], occurrence: int = 0) -> str:
    """ID 없는 동일 단계도 순서 안에서 안정적으로 구분하는 내용 ID."""
    raw = _mapping(value, "sequence step")
    if raw.get("id") not in (None, ""):
        return str(raw["id"])
    occurrence = max(0, int(occurrence))
    return (
        f"sequence-step:{fingerprint_sequence_step(raw)[:24]}:"
        f"{occurrence + 1}"
    )


def _canonical_step(value: Mapping[str, Any], occurrence: int) -> dict:
    result = _step_body(value)
    result["fingerprint"] = fingerprint_sequence_step(result)
    result["id"] = sequence_step_id(value, occurrence)
    return result


def canonical_sequence_plan(value: Mapping[str, Any] | None) -> dict:
    """단계, 진행, 고정, 반복과 순서를 하나의 무손실 실행 계획으로 정리."""
    raw = _mapping(value, "sequence plan")
    progression = raw.get("progression", raw.get("mode", "once"))
    if progression not in SEQUENCE_PROGRESSIONS:
        raise ValueError(
            "sequence progression must be one of: "
            + ", ".join(SEQUENCE_PROGRESSIONS)
        )

    steps = []
    generated_occurrences: dict[str, int] = {}
    explicit_ids = set()
    for item in _list(raw.get("steps"), "steps"):
        if not isinstance(item, Mapping):
            raise TypeError("each sequence step must be a mapping")
        explicit = item.get("id")
        if explicit not in (None, ""):
            explicit = str(explicit)
            if explicit in explicit_ids:
                raise ValueError(f"duplicate sequence step id: {explicit}")
            explicit_ids.add(explicit)
            occurrence = 0
        else:
            fingerprint = fingerprint_sequence_step(item)
            occurrence = generated_occurrences.get(fingerprint, 0)
            generated_occurrences[fingerprint] = occurrence + 1
        steps.append(_canonical_step(item, occurrence))

    ids = [step["id"] for step in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("sequence step IDs must be unique")

    raw_order = raw.get("order")
    if raw_order in (None, "forward"):
        order = list(ids)
    elif raw_order == "reverse":
        order = list(reversed(ids))
    else:
        order = _list(raw_order, "order")
        if any(not isinstance(item, str) for item in order):
            raise TypeError("order must contain step ID strings")
        unknown = [item for item in order if item not in set(ids)]
        if unknown:
            raise ValueError("order refers to unknown step: " + str(unknown[0]))
        if len(order) != len(set(order)):
            raise ValueError("order must not repeat a step reference")

    freeze = _mapping(raw.get("freeze"), "freeze")
    freeze = {
        **freeze,
        "style": bool(freeze.get("style", False)),
        "characters": bool(freeze.get("characters", False)),
        "wildcards": bool(freeze.get("wildcards", False)),
    }
    result = {
        "schema": SEQUENCE_SCHEMA,
        "name": deepcopy(raw.get("name", "")),
        "progression": progression,
        "freeze": freeze,
        "repeat": _positive_repeat(raw.get("repeat", 1), "sequence repeat"),
        "order": order,
        "steps": steps,
    }
    for key, item in raw.items():
        if key not in result and key not in {
            "id", "fingerprint", "mode",
        }:
            result[key] = deepcopy(item)

    identity = {
        key: item
        for key, item in result.items()
        if key not in _IDENTITY_IGNORED
    }
    result["fingerprint"] = _hash(identity)
    result["id"] = (
        str(raw["id"]) if raw.get("id") not in (None, "")
        else f"sequence:{result['fingerprint'][:24]}"
    )
    return result


def fingerprint_sequence_plan(value: Mapping[str, Any] | None) -> str:
    return canonical_sequence_plan(value)["fingerprint"]


def sequence_plan_id(value: Mapping[str, Any] | None) -> str:
    return canonical_sequence_plan(value)["id"]


def next_sequence_step(
    plan: Mapping[str, Any],
    current_id: str | None = None,
    direction: str = "forward",
) -> dict | None:
    """명시 방향으로 다음 단계를 반환한다. once/manual은 경계에서 멈춘다."""
    if direction not in SEQUENCE_DIRECTIONS:
        raise ValueError(
            "direction must be one of: " + ", ".join(SEQUENCE_DIRECTIONS)
        )
    canonical = canonical_sequence_plan(plan)
    order = canonical["order"]
    if not order:
        return None
    if current_id is None:
        target = order[0] if direction == "forward" else order[-1]
    else:
        if current_id not in order:
            raise ValueError(f"unknown current sequence step: {current_id}")
        offset = 1 if direction == "forward" else -1
        index = order.index(current_id) + offset
        if 0 <= index < len(order):
            target = order[index]
        elif canonical["progression"] == "cycle":
            target = order[index % len(order)]
        else:
            return None
    return deepcopy(next(step for step in canonical["steps"] if step["id"] == target))


def _deep_merge(target: dict, override: Mapping[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            child = deepcopy(dict(target[key]))
            _deep_merge(child, value)
            target[key] = child
        else:
            target[key] = deepcopy(value)


def _previous_source(previous_result: Any, source: str) -> dict | None:
    if not isinstance(previous_result, Mapping):
        return None
    if isinstance(previous_result.get(source), Mapping):
        return deepcopy(dict(previous_result[source]))
    return deepcopy(dict(previous_result))


def _source_blueprint(source: Mapping[str, Any] | None) -> dict:
    if not isinstance(source, Mapping):
        return {}
    for key in ("blueprint", "resolved_blueprint", "plan"):
        if isinstance(source.get(key), Mapping):
            return deepcopy(dict(source[key]))
    return deepcopy(dict(source))


def _result_vibe_reference(source: Mapping[str, Any] | None) -> Any:
    if not isinstance(source, Mapping):
        return None
    for key in ("vibe", "vibe_ref", "image", "artifact", "result_ref"):
        if source.get(key) is not None:
            return deepcopy(source[key])
    artifacts = source.get("artifacts")
    if isinstance(artifacts, (list, tuple)) and artifacts:
        return deepcopy(artifacts[0])
    return None


def _apply_step_style(resolved: dict, step: dict, applied: list[str]) -> None:
    style = deepcopy(dict(resolved["style"]))
    _deep_merge(style, step["style_overrides"])
    if step["style_overrides"]:
        applied.append("style")
    resolved["style"] = style


def _apply_step_characters(
    resolved: dict,
    step: dict,
    previous: dict,
    applied: list[str],
    carried: dict,
) -> None:
    characters = deepcopy(resolved["characters"])
    by_id = {
        str(item.get("id")): item
        for item in characters
        if isinstance(item, Mapping) and item.get("id") not in (None, "")
    }
    for character_id, override in step["character_overrides"].items():
        if str(character_id) not in by_id:
            raise ValueError(
                f"character override refers to unknown character: {character_id}"
            )
        if not isinstance(override, Mapping):
            raise TypeError("character override must be a mapping")
        _deep_merge(by_id[str(character_id)], override)
        applied.append(f"characters:{character_id}")
    previous_characters = {
        str(item.get("id")): item
        for item in (previous.get("characters") or [])
        if isinstance(item, Mapping) and item.get("id") not in (None, "")
    }
    outfit = step["outfit"]
    if isinstance(outfit, Mapping):
        for character_id, value in outfit.items():
            if str(character_id) not in by_id:
                raise ValueError(
                    f"outfit refers to unknown character: {character_id}"
                )
            by_id[str(character_id)]["clothed"] = deepcopy(value)
            applied.append(f"characters:{character_id}:clothed")
    elif outfit is not None:
        if len(characters) != 1:
            raise ValueError("scalar outfit requires exactly one blueprint character")
        characters[0]["clothed"] = deepcopy(outfit)
        applied.append("characters:0:clothed")
    elif step["carry"]["outfit"] and previous_characters:
        for character_id, current in by_id.items():
            prior = previous_characters.get(character_id)
            if isinstance(prior, Mapping) and "clothed" in prior:
                current["clothed"] = deepcopy(prior["clothed"])
                carried[f"characters:{character_id}:clothed"] = "previous-result"
    resolved["characters"] = characters


def _apply_step_setting(
    resolved: dict,
    step: dict,
    previous: dict,
    applied: list[str],
    carried: dict,
) -> None:
    setting = deepcopy(dict(resolved["setting"]))
    scene = _mapping(setting.get("scene_values"), "setting.scene_values")
    for field in ("include", "exclude", "rating"):
        if step[field] is not None:
            scene[field] = deepcopy(step[field])
            applied.append(f"setting.scene_values.{field}")
    if step["background"] is not None:
        scene["background"] = deepcopy(step["background"])
        applied.append("setting.scene_values.background")
    elif step["carry"]["background"]:
        prior_scene = (
            (previous.get("setting") or {}).get("scene_values")
            if isinstance(previous.get("setting"), Mapping) else None
        )
        if isinstance(prior_scene, Mapping) and "background" in prior_scene:
            scene["background"] = deepcopy(prior_scene["background"])
            carried["setting.scene_values.background"] = "previous-result"
    setting["scene_values"] = scene
    resolved["setting"] = setting


def _apply_step_generation(
    resolved: dict,
    step: dict,
    applied: list[str],
) -> None:
    generation = deepcopy(dict(resolved["generation"]))
    resolution = _mapping(generation.get("resolution"), "generation.resolution")
    _deep_merge(resolution, step["resolution"])
    if step["resolution"]:
        applied.append("generation.resolution")
    generation["resolution"] = resolution
    schedule = _mapping(generation.get("schedule"), "generation.schedule")
    if step["seed_policy"]["mode"] != "inherit" or len(step["seed_policy"]) > 1:
        schedule["seed_policy"] = deepcopy(step["seed_policy"])
        applied.append("generation.schedule.seed_policy")
    generation["schedule"] = schedule
    resolved["generation"] = generation


def _apply_step_vibe(
    resolved: dict,
    step: dict,
    previous_result: Mapping[str, Any] | None,
) -> tuple[dict, str]:
    continuity = deepcopy(step["vibe_continuity"])
    source_name = continuity["source"]
    status = "disabled"
    if source_name != "none":
        source = _previous_source(previous_result, source_name)
        reference = _result_vibe_reference(source)
        if reference is None:
            status = "unavailable"
        else:
            resources = deepcopy(dict(resolved["resources"]))
            vibes = _list(resources.get("vibes"), "resources.vibes")
            vibes.append({
                "source": source_name,
                "reference": reference,
                "sequence_step_id": step["id"],
            })
            resources["vibes"] = vibes
            resolved["resources"] = resources
            status = "applied"
    return continuity, status


def resolve_sequence_step(
    base_blueprint: Mapping[str, Any],
    plan: Mapping[str, Any],
    step_id: str,
    previous_result: Mapping[str, Any] | None = None,
) -> dict:
    """기본 설계도 사본에 선택 단계가 명시한 값과 carry만 적용한다."""
    if not isinstance(base_blueprint, Mapping):
        raise TypeError("base_blueprint must be a mapping")
    canonical = canonical_sequence_plan(plan)
    try:
        step = next(
            item for item in canonical["steps"] if item["id"] == step_id
        )
    except StopIteration as exc:
        raise ValueError(f"unknown sequence step: {step_id}") from exc

    resolved = deepcopy(dict(base_blueprint))
    resolved.setdefault("style", {})
    resolved.setdefault("characters", [])
    resolved.setdefault("resources", {})
    resolved.setdefault("setting", {})
    resolved.setdefault("generation", {})
    if not isinstance(resolved["style"], Mapping):
        raise TypeError("blueprint style must be a mapping")
    if not isinstance(resolved["characters"], list):
        raise TypeError("blueprint characters must be a list")

    applied = []
    carried = {}
    previous = _source_blueprint(_previous_source(previous_result, "previous"))
    _apply_step_style(resolved, step, applied)
    _apply_step_characters(resolved, step, previous, applied, carried)
    _apply_step_setting(resolved, step, previous, applied, carried)
    _apply_step_generation(resolved, step, applied)
    continuity, continuity_status = _apply_step_vibe(
        resolved, step, previous_result
    )

    resolved["sequence"] = {
        "schema": SEQUENCE_SCHEMA,
        "plan_id": canonical["id"],
        "plan_fingerprint": canonical["fingerprint"],
        "step_id": step["id"],
        "step_fingerprint": step["fingerprint"],
        "progression": canonical["progression"],
        "repeat": step["repeat"],
        "freeze": deepcopy(canonical["freeze"]),
        "applied": applied,
        "carried": carried,
        "vibe_continuity": {
            **continuity,
            "status": continuity_status,
        },
    }
    return resolved
