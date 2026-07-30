# -*- coding: utf-8 -*-
"""캐릭터 자산을 생성·세팅·비교가 공유하는 실행 입력으로 투영한다."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from src.nai_studio.domain.image_metadata import strip_comment_lines
from src.nai_studio.domain.positioning import normalize_position_mode
from src.nai_studio.services.setting_compiler import join_tags
from src.nai_studio.services.variation_bridge import selected_variation_values


log = logging.getLogger(__name__)
NAI_CHARACTER_LIMIT = 6


def slot_prompt(slot: Any) -> str:
    """캐릭터 칸의 선택 Variant 외형과 착의를 손실 없이 전송값으로 잇는다."""
    if not isinstance(slot, dict):
        return ""
    effective = selected_variation_values(slot)
    return join_tags(
        strip_comment_lines(effective["prompt"]),
        strip_comment_lines(effective["outfit"]),
    )


def slot_bundle_identity(slot: Any) -> str:
    """재개·중복 판정에 쓰는 캐릭터 원문·Variant·자료·위치의 안정된 값."""
    if not isinstance(slot, dict):
        return ""
    effective = selected_variation_values(slot)
    selected = effective["selected_variant"]
    bundle = {
        "id": slot.get("id", ""),
        "prompt": effective["prompt"],
        "outfit": effective["outfit"],
        "negative": effective["negative"],
        "variant": slot.get("variant") or {},
        "variants": slot.get("variants") or [],
        "selected_variant_id": effective["selected_variant_id"],
        "reference_ids": (
            selected.get("reference_ids")
            if "reference_ids" in selected
            else slot.get("reference_ids")
        )
        or [],
        "vibe_ids": (
            selected.get("vibe_ids")
            if "vibe_ids" in selected
            else slot.get("vibe_ids")
        )
        or [],
        "position": slot.get("position") or {},
    }
    return json.dumps(
        bundle,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def character_run_from_group(
    group: Any,
    fallback_index: int = 0,
    position_mode: Any = None,
) -> dict:
    """캐릭터 슬롯·캐스트를 한 장의 세팅용 인물 묶음으로 만든다."""
    members = [
        item
        for item in (group or [])
        if isinstance(item, dict) and slot_prompt(item).strip()
    ]
    if not members:
        return {}
    primary = members[0]
    partner = members[1] if len(members) > 1 else {}
    primary_effective = selected_variation_values(primary)
    partner_effective = selected_variation_values(partner)
    names = [
        str(item.get("name") or "").strip()
        for item in members
        if str(item.get("name") or "").strip()
    ]
    centers = []
    for item in members:
        center = item.get("position") or item.get("center")
        centers.append(
            copy.deepcopy(center)
            if isinstance(center, dict) and center.get("x") is not None
            else None
        )
    return {
        "name": " + ".join(names) or f"인물{fallback_index + 1}",
        "female": slot_prompt(primary),
        "negative": primary_effective["negative"],
        "male_prompt_base": slot_prompt(partner),
        "partner_negative": partner_effective["negative"],
        "extras": [
            {
                "prompt": slot_prompt(item),
                "negative": selected_variation_values(item)["negative"],
                "center": copy.deepcopy(
                    item.get("position") or item.get("center")
                ),
            }
            for item in members[2:]
        ],
        "centers": centers,
        "position_mode": (
            normalize_position_mode(
                position_mode, bool([center for center in centers if center])
            )
            if position_mode not in (None, "")
            else ""
        ),
        "reference_ids": list(
            dict.fromkeys(
                str(resource_id)
                for item in members
                for resource_id in (item.get("reference_ids") or [])
                if resource_id
            )
        ),
        "vibe_ids": list(
            dict.fromkeys(
                str(resource_id)
                for item in members
                for resource_id in (item.get("vibe_ids") or [])
                if resource_id
            )
        ),
    }


def active_people(
    slots: Any,
    centers: Any = None,
    extra: Any = None,
    *,
    limit: int = NAI_CHARACTER_LIMIT,
) -> tuple[list[dict], list[dict]]:
    """켠 캐릭터와 같은 인덱스의 좌표를 NAI 인물 상한까지 함께 고른다."""
    centers = centers or []
    people, selected_centers = [], []
    for index, slot in enumerate(slots or []):
        if not isinstance(slot, dict) or slot.get("enabled") is False:
            continue
        prompt = slot_prompt(slot)
        if not prompt.strip():
            continue
        effective = selected_variation_values(slot)
        people.append({
            "prompt": prompt,
            "negative": effective["negative"],
        })
        center = (
            centers[index]
            if index < len(centers) and isinstance(centers[index], dict)
            else None
        )
        selected_centers.append(center or {"x": 0.5, "y": 0.5})
    for item in (extra or []):
        prompt = strip_comment_lines(item.get("prompt") or "")
        if prompt.strip():
            people.append({
                "prompt": prompt,
                "negative": strip_comment_lines(item.get("negative") or ""),
            })
            selected_centers.append(
                item.get("center") or {"x": 0.5, "y": 0.5}
            )
    if len(people) > limit:
        log.warning(
            "켠 인물이 %s명입니다 — NAI 상한 %s명까지만 보냅니다 "
            "(칸은 그대로 남습니다).",
            len(people),
            limit,
        )
        people = people[:limit]
        selected_centers = selected_centers[:limit]
    return people, selected_centers


def scene_reference_config(cfg, scene, *, normalize_reference_ids):
    """씬 전용 Reference 선택을 현재 설정 위에 안전하게 얹는다.

    `use_character_refs`가 꺼져 있으면 전역 활성 목록을 그대로 쓴다. 켜져 있으면
    인물 순서대로 고른 id만 활성화한다. 같은 id를 여러 인물에 골라도 NAI에는 한 번만
    보내며, 삭제되어 찾을 수 없는 id는 건너뛰고 이름 목록에는 근거를 남긴다.
    """
    if not scene.get("use_character_refs"):
        active = [r.get("name") or r.get("id") or "무제"
                  for r in (cfg.get("char_refs") or []) if r.get("enabled")]
        return cfg, False, active
    chosen = normalize_reference_ids(scene.get("character_refs"))
    by_id = {
        str(item.get("id") or ""): item
        for item in (cfg.get("char_refs") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    scoped = dict(cfg)
    selected, names, seen = [], [], set()
    for rid in chosen:
        if not rid:
            names.append("참조 안 함")
            continue
        item = by_id.get(rid)
        if item is None:
            names.append(f"없어진 참조({rid})")
            continue
        names.append(item.get("name") or rid)
        if rid not in seen:
            selected.append(dict(item, enabled=True))
            seen.add(rid)
    scoped["char_refs"] = selected
    return scoped, True, names


def cast_resource_config(cfg, character):
    """저장 캐스트가 가리키는 Vibe·Reference만 이 작업에 활성화한다.

    id 목록이 비어 있으면 기존 전역 선택을 그대로 쓴다. 따라서 과거 캐스트와 설정은
    동작이 바뀌지 않고, 새 출연 구성에서 자료 id를 명시했을 때만 범위를 좁힌다.
    """
    scoped = dict(cfg)
    selected = selected_variation_values(character).get("selected_variant") or {}
    for key, id_key in (("char_refs", "reference_ids"), ("vibes", "vibe_ids")):
        source_ids = (
            selected.get(id_key)
            if id_key in selected else character.get(id_key)
        )
        wanted = [str(value) for value in (source_ids or []) if value]
        if not wanted:
            continue
        by_id = {
            str(item.get("id") or ""): item
            for item in (cfg.get(key) or [])
            if isinstance(item, dict) and item.get("id")
        }
        scoped[key] = [
            dict(by_id[resource_id], enabled=True)
            for resource_id in dict.fromkeys(wanted)
            if resource_id in by_id
        ]
    return scoped


__all__ = [
    "NAI_CHARACTER_LIMIT",
    "active_people",
    "cast_resource_config",
    "character_run_from_group",
    "scene_reference_config",
    "slot_bundle_identity",
    "slot_prompt",
]
