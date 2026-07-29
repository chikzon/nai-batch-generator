# -*- coding: utf-8 -*-
"""세팅 자료와 캐릭터 원문을 한 장의 NAI 프롬프트로 조립한다.

저장·HTTP·실행 상태에는 의존하지 않는 순수 컴파일 경계다. 생성, 비교,
미리보기는 같은 함수를 써서 화면과 실제 payload의 해석 차이를 막는다.
"""

from __future__ import annotations

import re
from typing import Any

from src.nai_studio.domain.image_metadata import strip_comment_lines
from src.nai_studio.domain.positioning import (
    normalize_scene_centers,
    position_mode_uses_coords,
    spread_centers,
)

AXIS_TARGETS = ("base", "여자", "남자", "네거티브")
AXIS_SHAPES = ("고정", "계열별", "단계별")
LEGACY_AXES = {
    "장소테마": ("base", "계열별"),
    "시간대": ("base", "고정"),
    "표정진행": ("여자", "단계별"),
}


def clean_char_prompt(raw: Any) -> str:
    """주석 줄을 제외하고 캐릭터 원문을 쉼표 프롬프트로 만든다."""
    return ", ".join(
        tag.strip()
        for tag in (raw or "").replace("\n", ",").split(",")
        if tag.strip() and not tag.strip().startswith("#")
    )


def setting_state(config: dict, name: str) -> dict:
    """설정에 저장된 한 세팅의 선택 상태를 돌려준다."""
    return (config.get("setting_state") or {}).get(name, {})


def load_asset_config(
    config: dict,
    *,
    list_settings: Any,
    derive_catalog: Any,
    warn: Any,
) -> dict:
    """세팅 파일을 실행용 장면·옵션 축 사전으로 병합한다."""
    style = (config.get("base_prompt") or "").strip()
    asset_config = {
        "base": {
            "nsfw_base_prompt": "1girl, 1boy"
            + (f", {style}" if style else ""),
            "yuri_base_prompt": "2girls, yuri"
            + (f", {style}" if style else ""),
            "base_prompt": "1girl" + (f", {style}" if style else ""),
            "nsfw_negative_prompt": config.get("negative_prompt", ""),
            "negative_prompt": config.get("negative_prompt", ""),
            "cfg_scale": config.get("cfg_scale", 5.5),
            "cfg_rescale": config.get("cfg_rescale", 0.56),
            "sampler": config.get(
                "sampler", "k_euler_ancestral"
            ),
            "scheduler": config.get("scheduler", "karras"),
            "uc_preset": 3,
        },
        "scenes": {},
        "_settings": {},
    }
    for setting in list_settings():
        name = setting["name"]
        mode = setting["mode"]
        data = setting["data"]
        state = setting_state(config, name)
        chosen = state.get("opts", {})
        options = data.get("옵션", {})
        role = data.get("상대역", {})
        specs = axis_specs(data)
        asset_config["_settings"][name] = {
            "mode": mode,
            "options": options,
            "role": role,
            "opts": chosen,
            "file": setting["file"],
            "specs": specs,
        }
        stage_of, stages_of = {}, {}
        for group in derive_catalog(data.get("씬", {})):
            for index, scene_number in enumerate(group["ids"]):
                stage_of[scene_number] = index
                stages_of[scene_number] = len(group["ids"])
        for key, raw_scene in data.get("씬", {}).items():
            if not str(key).isdigit():
                continue
            if str(key) in asset_config["scenes"]:
                warn(
                    f"씬 번호 {key}가 겹칩니다 "
                    f"({asset_config['scenes'][str(key)].get('_setting')} ↔ {name}) — "
                    "뒤에 읽힌 쪽이 이깁니다. 세팅 빌더의 "
                    "'번호 다시 매기기'를 쓰세요."
                )
            scene = dict(raw_scene)
            scene["_setting"] = name
            scene["_mode"] = mode
            scene["_num"] = int(key)
            scene["_stage"] = stage_of.get(int(key), 0)
            scene["_stages"] = stages_of.get(int(key), 1)
            location = apply_axes(
                specs, options, chosen, scene, "base"
            )
            if location:
                scene["location"] = location
            asset_config["scenes"][str(key)] = scene
    return asset_config


def _guess_shape(items: Any) -> str:
    """옵션 값의 모양으로 기존 자료의 적용 방식을 복원한다."""
    for value in (items or {}).values():
        if isinstance(value, list):
            return "단계별"
        if isinstance(value, dict):
            return "계열별"
        return "고정"
    return "고정"


def axis_specs(data: dict) -> dict:
    """세팅 파일의 선언 또는 기존 값 모양에서 옵션 축 규격을 만든다."""
    declared = data.get("옵션규격") or {}
    result = {}
    for axis, items in (data.get("옵션") or {}).items():
        spec = declared.get(axis) or {}
        target = spec.get("적용")
        shape = spec.get("방식")
        if target not in AXIS_TARGETS or shape not in AXIS_SHAPES:
            legacy_target, legacy_shape = LEGACY_AXES.get(axis, (None, None))
            target = (
                target if target in AXIS_TARGETS else (legacy_target or "base")
            )
            shape = (
                shape if shape in AXIS_SHAPES else (legacy_shape or _guess_shape(items))
            )
        result[axis] = (target, shape)
    return result


def apply_axes(
    specs: dict,
    options: dict,
    chosen: dict,
    scene: dict,
    target: str,
) -> str:
    """현재 장면의 대상 칸에 적용할 옵션 태그만 순서대로 조립한다."""
    parts = []
    for axis, (axis_target, shape) in (specs or {}).items():
        if axis_target != target:
            continue
        pick = chosen.get(axis, "")
        if not pick:
            continue
        value = (options.get(axis) or {}).get(pick)
        if not value:
            continue
        if shape == "계열별" and isinstance(value, dict):
            selected = value.get(scene.get("category", ""))
            if selected:
                parts.append(selected)
        elif shape == "단계별" and isinstance(value, (list, tuple)):
            index = int(scene.get("_stage", 0))
            if 0 <= index < len(value) and value[index]:
                parts.append(value[index])
        elif isinstance(value, str):
            parts.append(value)
    return ", ".join(part for part in parts if part)


def _setting_ctx(asset_config: dict, scene: dict) -> dict:
    return asset_config.get("_settings", {}).get(scene.get("_setting", ""), {})


def remove_prompt_tags(text: str, removals: Any) -> str:
    """쉼표 단위 프롬프트에서 장면이 제외한 태그를 제거한다."""
    if isinstance(removals, str):
        removals = re.split(r"[,\n]", removals)
    needles = [
        str(value).strip().lower()
        for value in (removals or [])
        if str(value).strip()
    ]
    if not needles:
        return text
    parts = [tag.strip() for tag in (text or "").split(",") if tag.strip()]
    return ", ".join(
        tag
        for tag in parts
        if not any(needle in tag.lower() for needle in needles)
    )


def join_tags(*parts: str) -> str:
    """빈 조각과 고립 쉼표를 만들지 않고 프롬프트 원문 조각을 잇는다."""
    return ", ".join(
        part.strip().strip(",").strip()
        for part in parts
        if part and part.strip().strip(",").strip()
    )


def strip_subject_prefix(text: str) -> str:
    """기존 인원수 접두사 뒤의 화풍 태그만 돌려준다."""
    text = text or ""
    for prefix in ("1girl, 1boy, ", "1girl,1boy,", "1girl, "):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def build_scene(
    asset_config: dict,
    character: dict,
    config: dict,
    scene_number: int,
) -> tuple:
    """방식에 맞는 Base·인물·Negative·해상도 한 묶음을 만든다."""
    scene = asset_config["scenes"][str(scene_number)]
    mode = scene.get("_mode", "단독")
    if mode == "백합":
        return build_yuri(asset_config, character, scene)
    return build_standard(asset_config, character, scene, mode)


def build_standard(
    asset_config: dict,
    character: dict,
    scene: dict,
    mode: str,
) -> tuple:
    """남녀 또는 단독 장면을 컴파일한다."""
    variant = "clothed" if mode == "단독" else "nude"
    base = (
        asset_config["base"]["nsfw_base_prompt"]
        if variant == "nude"
        else asset_config["base"]["base_prompt"]
    )
    context = _setting_ctx(asset_config, scene)
    cleaned_character = clean_char_prompt(character.get("female", ""))
    character_negative = character.get("negative", "")

    location = scene.get("location", "")
    if location:
        base = f"{base}, {location}"
    if scene.get("base_tags"):
        base = join_tags(base, scene.get("base_tags"))
    if scene.get("relationship_tags"):
        base = join_tags(base, scene.get("relationship_tags"))

    cleaned_character = remove_prompt_tags(
        cleaned_character, scene.get("remove_char_tags", [])
    )
    character_negative = join_tags(
        character_negative, scene.get("female_negative", "")
    )
    female_caption = join_tags(
        cleaned_character, scene.get("female_prompt", "")
    )
    male_caption = scene.get("male_prompt", "")

    stage = int(
        scene.get("_stage", (scene.get("_num", 0) - 1) % 5)
    )
    role = context.get("role", {})
    chosen = context.get("opts", {})
    specs = context.get("specs") or {}
    options = context.get("options", {})

    female_axis = apply_axes(specs, options, chosen, scene, "여자")
    if female_axis:
        female_caption = join_tags(female_caption, female_axis)

    if mode == "남녀":
        cast_partner = character.get("male_prompt_base", "")
        male_base = clean_char_prompt(cast_partner or role.get("외형", ""))
        male_base = remove_prompt_tags(
            male_base, scene.get("remove_male_tags", [])
        )
        outfit = role.get("의상", "")
        wear = ""
        if not cast_partner:
            wear_mode = chosen.get("남자옷", "나체")
            if wear_mode == "착의":
                wear = f"{outfit}, clothed male, clothed sex, open pants"
            elif wear_mode == "탈의진행":
                if stage <= 1:
                    wear = f"{outfit}, clothed male, clothed sex, open pants"
                elif stage == 2:
                    wear = "topless male, open pants, clothed sex"
        male_axis = apply_axes(specs, options, chosen, scene, "남자")
        male_caption = ", ".join(
            value
            for value in (male_base, wear, male_caption, male_axis)
            if value
        )
        male_negative = join_tags(
            character.get("partner_negative", "") or role.get("네거티브", ""),
            scene.get("male_negative", ""),
        )
    else:
        male_caption = apply_axes(specs, options, chosen, scene, "남자")
        male_negative = ""

    negative_axis = apply_axes(specs, options, chosen, scene, "네거티브")
    if negative_axis:
        character_negative = join_tags(character_negative, negative_axis)

    return (
        base,
        female_caption,
        male_caption,
        character_negative,
        male_negative,
        scene["width"],
        scene["height"],
    )


def build_yuri(asset_config: dict, character: dict, scene: dict) -> tuple:
    """백합 장면의 두 캐릭터와 탈의 단계 원문을 컴파일한다."""
    context = _setting_ctx(asset_config, scene)
    role = context.get("role", {})
    chosen = context.get("opts", {})
    undress_tags = context.get("options", {}).get("탈의단계", {})

    base = asset_config["base"].get("yuri_base_prompt", "2girls, yuri")
    if scene.get("base_tags"):
        base = f"{base}, {scene['base_tags']}"
    if scene.get("relationship_tags"):
        base = join_tags(base, scene.get("relationship_tags"))
    if scene.get("location"):
        base = f"{base}, {scene['location']}"

    first_level = scene.get("undress1", 4)
    second_level = scene.get("undress2", 4)
    if chosen.get("옷진행", "진행") == "나체":
        first_level = second_level = 4

    def girl_text(nude_raw: str, clothed_raw: str, level: int) -> str:
        raw = nude_raw if level >= 4 or not clothed_raw else clothed_raw
        text = clean_char_prompt(raw)
        extra = undress_tags.get(str(level), "")
        return f"{text}, {extra}" if extra else text

    female_text = remove_prompt_tags(
        girl_text(
            character.get("female", ""),
            character.get("clothed", ""),
            first_level,
        ),
        scene.get("remove_char_tags", []),
    )
    cast_partner = character.get("male_prompt_base", "")
    partner_text = remove_prompt_tags(
        (
            clean_char_prompt(cast_partner)
            if cast_partner
            else girl_text(
                role.get("외형", ""),
                role.get("착의", ""),
                second_level,
            )
        ),
        scene.get("remove_partner_tags", []),
    )

    return (
        base,
        join_tags(female_text, scene.get("female_prompt", "")),
        join_tags(partner_text, scene.get("partner_prompt", "")),
        join_tags(
            character.get("negative", ""),
            scene.get("female_negative", ""),
        ),
        join_tags(
            character.get("partner_negative", "") or role.get("네거티브", ""),
            scene.get("partner_negative", ""),
        ),
        scene["width"],
        scene["height"],
    )


def setting_scene_people(
    scene: dict,
    female: str,
    male: str,
    character_negative: str,
    male_negative: str,
    character: dict,
    config: dict,
    *,
    limit: int = 6,
) -> tuple[list[dict], list[dict], bool]:
    """한 세팅 장면의 인물과 같은 순서의 좌표를 함께 만든다."""
    people = [{
        "prompt": female,
        "negative": character_negative,
    }]
    if male:
        people.append({
            "prompt": male,
            "negative": male_negative,
        })
    extras = [
        item
        for item in (character.get("extras") or [])
        if isinstance(item, dict)
    ]
    for extra in extras:
        prompt = strip_comment_lines(extra.get("prompt") or "")
        if prompt.strip():
            people.append({
                "prompt": prompt,
                "negative": strip_comment_lines(
                    extra.get("negative") or ""
                ),
            })
    people = people[:limit]

    explicit = normalize_scene_centers(
        scene.get("char_centers"), limit=limit
    )
    raw_cast_centers = character.get("centers") or []
    has_cast_centers = any(
        isinstance(center, dict) and center.get("x") is not None
        for center in raw_cast_centers
    )
    cast_mode = str(
        character.get("position_mode") or ""
    ).strip().lower()
    config_mode = str(
        config.get("position_mode") or ""
    ).strip().lower()
    if cast_mode in ("ai", "grid", "coordinate"):
        use_positions = position_mode_uses_coords(cast_mode)
    elif config_mode in ("ai", "grid", "coordinate"):
        use_positions = position_mode_uses_coords(config_mode)
    else:
        use_positions = (
            bool(explicit)
            or has_cast_centers
            or position_mode_uses_coords(
                None, config.get("use_coords")
            )
        )
    if not use_positions:
        return people, [], False

    defaults = spread_centers(len(people))
    cast_centers = []
    if has_cast_centers:
        for index in range(len(people)):
            center = (
                raw_cast_centers[index]
                if index < len(raw_cast_centers)
                else None
            )
            try:
                cast_centers.append(
                    normalize_scene_centers(
                        [center], limit=limit
                    )[0]
                    if center
                    else defaults[index]
                )
            except (ValueError, TypeError, IndexError):
                cast_centers.append(defaults[index])
    if explicit:
        centers = list(explicit)
    elif cast_centers:
        centers = list(cast_centers)
    else:
        centers = normalize_scene_centers(
            config.get("char_centers") or [], limit=limit
        )
    for index in range(len(centers), len(people)):
        extra_index = index - (2 if male else 1)
        extra_center = (
            extras[extra_index].get("center")
            if 0 <= extra_index < len(extras)
            else None
        )
        try:
            center = (
                normalize_scene_centers(
                    [extra_center], limit=limit
                )[0]
                if extra_center
                else defaults[index]
            )
        except ValueError:
            center = defaults[index]
        centers.append(center)
    return people, centers[:len(people)], True


# 기존 import·테스트 patch 위치를 보존하는 호환 이름.
_build_std = build_standard
_build_yuri = build_yuri
_join_tags = join_tags
_strip_subject_prefix = strip_subject_prefix


__all__ = [
    "AXIS_SHAPES",
    "AXIS_TARGETS",
    "LEGACY_AXES",
    "_build_std",
    "_build_yuri",
    "_guess_shape",
    "_join_tags",
    "_strip_subject_prefix",
    "apply_axes",
    "axis_specs",
    "build_scene",
    "clean_char_prompt",
    "join_tags",
    "load_asset_config",
    "remove_prompt_tags",
    "setting_scene_people",
    "setting_state",
]
