# -*- coding: utf-8 -*-
"""저장된 세팅과 캐스트를 실제 생성 직전 값으로 조립하는 미리보기 서비스."""

from __future__ import annotations

from typing import Any


def _scene_cast(
    application: Any,
    operations: Any,
    scene: dict,
) -> tuple[dict, dict]:
    config = application.cfg
    state = operations.setting_state(config, scene.get("_setting", ""))
    members = [
        member
        for member in operations.cast_members(config, state)
        if operations.slot_prompt(member).strip()
    ]
    if members:
        used = members if state.get("cast_mode") == "together" else members[:1]
        return operations.character_run(
            used, position_mode=state.get("position_mode")
        ), state
    slots = [
        slot
        for slot in (config.get("char_slots") or [])
        if operations.slot_prompt(slot).strip()
    ]
    if slots:
        return operations.character_run(
            slots, position_mode=config.get("position_mode")
        ), state
    return {"name": "(캐릭터 없음)", "female": "", "negative": ""}, state


def _preview_response(operations: Any, values: dict) -> dict:
    normalize = operations.normalize_prompt
    scene = values["scene"]
    return {
        "ok": True,
        "num": values["number"],
        "name": scene.get("name", ""),
        "setting": scene.get("_setting", ""),
        "mode": scene.get("_mode", ""),
        "cast": values["cast"]["name"],
        "relationship_name": scene.get(
            "relationship_name", scene.get("pair", "")
        ),
        "base": normalize(values["base"]),
        "female": normalize(values["female"]),
        "male": normalize(values["male"]),
        "negative": normalize(values["negative"]),
        "char_negative": normalize(values["char_negative"]),
        "male_negative": normalize(values["male_negative"]),
        "people": len(values["people"]),
        "use_positions": values["use_positions"],
        "char_centers": values["centers"],
        "scene_reference_override": values["reference_override"],
        "reference_names": values["reference_names"],
        "width": values["width"],
        "height": values["height"],
        "seed": values["seed"],
        "tokens": {
            "base": operations.token_count(values["base"]),
            "female": operations.token_count(values["female"]),
            "male": operations.token_count(values["male"]),
        },
    }


def scene_preview_payload(
    application: Any,
    operations: Any,
    number: int,
) -> dict:
    """선택 씬·캐스트·좌표·Reference를 저장 변경 없이 최종값으로 투영한다."""
    config = application.cfg
    asset_config = operations.load_asset_config(config)
    scene = asset_config["scenes"].get(str(number))
    if not scene:
        return {"ok": False, "error": f"{number}번 씬이 없습니다."}
    cast, _ = _scene_cast(application, operations, scene)
    base, female, male, char_neg, male_neg, width, height = (
        operations.build_scene(asset_config, cast, config, number)
    )
    _, ref_override, ref_names = operations.reference_config(config, scene)
    people, centers, use_positions = operations.scene_people(
        scene, female, male, char_neg, male_neg, cast, config
    )
    seed = operations.seed_for(
        config,
        operations.load_state()["seeds"].get(
            f"{int(config.get('seed', 1) or 1):02d}", 0
        ),
        number,
    )
    negative = operations.join_tags(
        asset_config["base"].get(
            "nsfw_negative_prompt", asset_config["base"]["negative_prompt"]
        ),
        (scene.get("negative") or "").strip(),
    )
    return _preview_response(
        operations,
        {
            "scene": scene,
            "cast": cast,
            "number": number,
            "base": base,
            "female": female,
            "male": male,
            "char_negative": char_neg,
            "male_negative": male_neg,
            "people": people,
            "centers": centers,
            "use_positions": use_positions,
            "reference_override": ref_override,
            "reference_names": ref_names,
            "width": width,
            "height": height,
            "seed": seed,
            "negative": negative,
        },
    )


__all__ = ["scene_preview_payload"]
