# -*- coding: utf-8 -*-
"""세팅 캐스트를 장면별 실행 작업으로 펼치는 순수 실행 계산."""

from __future__ import annotations

import copy
import zlib
from dataclasses import dataclass
from typing import Any, Callable

from src.nai_studio.services.character_runtime import (
    character_run_from_group,
    slot_bundle_identity,
    slot_prompt,
)
@dataclass(frozen=True)
class SettingRuntimeOperations:
    comparison_characters: Callable[[dict], list[dict]]
    derive_catalog: Callable[[dict], list[dict]]
    safe_name: Callable[[Any], str]
    setting_state: Callable[[dict, str], dict]


def setting_cast_members(
    operations: SettingRuntimeOperations,
    config: dict,
    state: Any,
) -> list[dict]:
    """저장 캐스트와 전체 캐릭터 순회를 같은 실행 슬롯 모양으로 돌려준다."""
    state = state or {}
    if state.get("cast_source") == "all_characters":
        return [{
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "prompt": item.get("female", ""),
            "outfit": item.get("clothed", ""),
            "negative": item.get("negative", ""),
            "variant": copy.deepcopy(item.get("variant") or {}),
            "variants": copy.deepcopy(item.get("variants") or []),
            "selected_variant_id": item.get("selected_variant_id", ""),
            "reference_ids": copy.deepcopy(item.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(item.get("vibe_ids") or []),
            "enabled": True,
        } for item in operations.comparison_characters(config)]
    return [
        item
        for item in (state.get("cast") or [])
        if isinstance(item, dict)
    ]


def _scene_numbers(
    operations: SettingRuntimeOperations,
    config: dict,
    asset_config: dict,
) -> list[int]:
    allowed: set[int] = set()
    for name in asset_config.get("_settings", {}):
        state = operations.setting_state(config, name)
        if state.get("use") is False:
            continue
        selected = set(state.get("selected", []))
        if not selected:
            continue
        scenes = {
            key: scene
            for key, scene in asset_config["scenes"].items()
            if scene.get("_setting") == name
        }
        stages = {
            int(value)
            for value in (state.get("stages") or [])
            if str(value).isdigit()
        }
        for group in operations.derive_catalog(scenes):
            if group["id"] not in selected:
                continue
            if stages:
                allowed.update(
                    scene_number
                    for index, scene_number in enumerate(group["ids"], 1)
                    if index in stages
                )
            else:
                allowed.update(group["ids"])
    return sorted(
        number
        for number in (
            int(value)
            for value in asset_config.get("scenes", {})
            if str(value).isdigit()
        )
        if number in allowed
    )


def _reserve_counts(
    operations: SettingRuntimeOperations,
    config: dict,
    asset_config: dict,
) -> dict[int, int]:
    reserve = {}
    for name in asset_config.get("_settings", {}):
        requested = operations.setting_state(config, name).get("reserve") or {}
        if not requested:
            continue
        scenes = {
            key: scene
            for key, scene in asset_config["scenes"].items()
            if scene.get("_setting") == name
        }
        for group in operations.derive_catalog(scenes):
            count = int(
                requested.get(
                    str(group["id"]),
                    requested.get(group["id"], 1),
                )
                or 1
            )
            if count > 1:
                for scene_number in group["ids"]:
                    reserve[scene_number] = count
    return reserve


def _scene_runs(
    operations: SettingRuntimeOperations,
    config: dict,
    state: dict,
    setting_name: str,
    fallback_slots: list[dict],
) -> list[tuple[list[dict], str | None]]:
    cast = [
        member
        for member in setting_cast_members(operations, config, state)
        if slot_prompt(member).strip()
    ]
    if not cast:
        return [(fallback_slots, None)] if fallback_slots else []
    if state.get("cast_mode") == "together":
        identity = "\0".join(slot_bundle_identity(member) for member in cast)
        return [(cast, f"{setting_name}\0together\0{identity}")]
    return [
        (
            [member],
            f"{setting_name}\0sequence\0{index}\0"
            f"{slot_bundle_identity(member)}",
        )
        for index, member in enumerate(cast)
    ]


def _append_scene_runs(
    operations: SettingRuntimeOperations,
    pending: list,
    config: dict,
    state: dict,
    setting_name: str,
    fallback_slots: list[dict],
    scene_number: int,
    copies: int,
    done_this_run: dict,
    skip_set: set,
) -> None:
    runs = _scene_runs(
        operations,
        config,
        state,
        setting_name,
        fallback_slots,
    )
    for index, (group, identity) in enumerate(runs):
        character = character_run_from_group(
            group,
            index,
            state.get("position_mode"),
        )
        character_id = (
            operations.safe_name(character["name"]).lower()
            or f"char{index + 1}"
        )
        if identity is not None:
            digest = zlib.crc32(identity.encode("utf-8")) & 0xFFFFFFFF
            character_id = f"{character_id[:30]}-{digest:08x}"
        completed = done_this_run.get(character_id, set())
        for copy_number in range(1, max(1, int(copies)) + 1):
            if (
                (scene_number, copy_number) in completed
                or (character_id, scene_number, copy_number) in skip_set
            ):
                continue
            pending.append((
                character,
                character_id,
                scene_number,
                copy_number,
            ))


def compute_pending(
    operations: SettingRuntimeOperations,
    config: dict,
    asset_config: dict,
    done_this_run: dict,
    skip_set: set,
) -> list[tuple]:
    """세팅 선택·단계·캐스트·예약·재개 상태를 장면 실행 순서로 계산한다."""
    scene_numbers = _scene_numbers(operations, config, asset_config)
    fallback_slots = [
        slot
        for slot in config.get("char_slots", [])
        if slot_prompt(slot).strip() and slot.get("enabled") is not False
    ]
    reserve = _reserve_counts(operations, config, asset_config)
    pending = []
    for scene_number in scene_numbers:
        scene = asset_config["scenes"][str(scene_number)]
        setting_name = scene.get("_setting", "")
        state = operations.setting_state(config, setting_name)
        _append_scene_runs(
            operations,
            pending,
            config,
            state,
            setting_name,
            fallback_slots,
            scene_number,
            reserve.get(scene_number, 1),
            done_this_run,
            skip_set,
        )
    if config.get("per_char_order", True):
        order = {}
        for item in pending:
            order.setdefault(item[1], len(order))
        pending.sort(key=lambda item: (order[item[1]], item[2], item[3]))
    return pending


__all__ = [
    "SettingRuntimeOperations",
    "compute_pending",
    "setting_cast_members",
]
