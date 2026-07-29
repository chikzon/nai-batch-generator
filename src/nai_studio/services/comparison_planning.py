# -*- coding: utf-8 -*-
"""자료 비교의 목록·계획·실행 leaf·재현 사본을 조립하는 서비스."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.nai_studio.domain.costs import anlas_estimate
from src.nai_studio.domain.model_presets import model_id_from_metadata
from src.nai_studio.domain.positioning import with_position_mode
from src.nai_studio.runtime.diagnostics import redact_diagnostic_text
from src.nai_studio.services.character_runtime import active_people, slot_prompt
from src.nai_studio.services.config_validation import normalize_resolution
from src.nai_studio.services.experiment_bridge import (
    expand_legacy_experiment_cells,
    legacy_comparison_id,
)
from src.nai_studio.services.experiment_execution_bridge import (
    legacy_execution_material,
)
from src.nai_studio.services.setting_compiler import (
    _join_tags,
    build_scene,
    setting_scene_people,
)
from src.nai_studio.services.variation_bridge import selected_variation_values


COMPARE_MODE_LABELS = {
    "styles": "그림체 전체",
    "characters": "캐릭터 전체",
    "both": "그림체 × 캐릭터",
    "character_setting": "캐릭터 × 선택 세팅",
    "selected": "선택 자료·축",
}
COMPARE_MAX_JOBS = 2_000_000
COMPARE_SELECTED_AXES = {
    "generation.cfg_scale": ("float", -10.0, 10.0),
    "generation.cfg_rescale": ("float", 0.0, 1.0),
    "generation.steps": ("int", 1, 50),
    "generation.sampler": ("text", None, None),
    "generation.scheduler": ("text", None, None),
    "generation.variety": ("bool", None, None),
}


@dataclass(frozen=True)
class ComparisonPlanningOperations:
    """저장소·세팅 compiler와 비교 계획 사이의 늦은 결합 지점."""

    load_combos: Any
    load_spec: Any
    list_styles: Any
    style_bundle_signature: Any
    load_asset_config: Any
    compute_pending: Any
    setting_reference_config: Any
    character_resource_config: Any
    characters_resource_config: Any
    inherited_blueprint: Any
    recipe_setting_keys: tuple[str, ...]
    max_characters: int


def comparison_styles(
    operations: ComparisonPlanningOperations,
    spec: dict | None = None,
) -> list[dict]:
    """수집 그림체와 사용자가 저장한 그림체 프리셋을 같은 실행 목록으로 합친다."""
    out, seen, bundle_seen = [], set(), set()
    for index, raw in enumerate(operations.load_combos()):
        if not isinstance(raw, dict):
            continue
        base = (raw.get("base") or raw.get("combo") or "").strip()
        if not base:
            continue
        item = dict(raw)
        identifier = str(
            item.get("id")
            or legacy_comparison_id(
                "style",
                item.get("title"),
                base,
                item.get("negative"),
                item.get("params"),
                index,
            )
        )
        if identifier in seen:
            identifier = legacy_comparison_id(
                "style", identifier, base, item.get("params"), index
            )
        seen.add(identifier)
        item["_compare_id"] = identifier
        item["_compare_name"] = (
            item.get("title") or item.get("combo") or f"그림체 {index + 1}"
        ).strip()
        item["_compare_kind"] = "수집"
        out.append(item)
        bundle_seen.add(operations.style_bundle_signature(item))

    for index, saved in enumerate(
        operations.list_styles(spec or operations.load_spec())
    ):
        if not isinstance(saved, dict) or not (
            saved.get("prompt") or ""
        ).strip():
            continue
        bundle_signature = operations.style_bundle_signature(saved)
        if bundle_signature in bundle_seen:
            continue
        settings = dict(saved.get("settings") or {})
        params = {
            "scale": settings.get("cfg_scale"),
            "cfg_rescale": settings.get("cfg_rescale"),
            "steps": settings.get("steps"),
            "sampler": settings.get("sampler"),
            "noise_schedule": settings.get("scheduler"),
            "variety_plus": settings.get("variety"),
            "model": settings.get("model"),
            "width": settings.get("width"),
            "height": settings.get("height"),
            "uc_preset": settings.get("uc_preset"),
            "quality_toggle": settings.get("quality_toggle"),
        }
        params = {key: value for key, value in params.items() if value is not None}
        identifier = legacy_comparison_id(
            "preset",
            saved.get("name"),
            saved.get("prompt"),
            saved.get("negative"),
            params,
            index,
        )
        if identifier in seen:
            continue
        seen.add(identifier)
        out.append(
            {
                "id": identifier,
                "_compare_id": identifier,
                "_compare_name": saved.get("name")
                or f"내 프리셋 {index + 1}",
                "_compare_kind": "내 프리셋",
                "base": saved.get("prompt", ""),
                "negative": saved.get("negative", ""),
                "params": params,
            }
        )
        bundle_seen.add(bundle_signature)
    return out


def _comparison_character_prompt(item: dict | None) -> str:
    """저장 캐릭터도 일반 캐릭터 칸과 같은 `외형 + 착의` 한 덩어리로 보낸다."""
    return slot_prompt(
        {
            "prompt": (item or {}).get("female", ""),
            "outfit": (item or {}).get("clothed", ""),
            "negative": (item or {}).get("negative", ""),
            "variants": copy.deepcopy((item or {}).get("variants") or []),
            "selected_variant_id": (item or {}).get("selected_variant_id", ""),
        }
    )


def comparison_characters(cfg: dict) -> list[dict]:
    """라이브러리에서 비교에 사용할 캐릭터와 활성 변형을 고른다."""
    grouped, standalone = {}, []
    for index, raw in enumerate((cfg or {}).get("characters") or []):
        if not isinstance(raw, dict):
            continue
        prompt = _comparison_character_prompt(raw)
        if not prompt:
            continue
        item = dict(raw)
        effective = selected_variation_values(item)
        item["female"] = effective["prompt"]
        item["clothed"] = effective["outfit"]
        item["negative"] = effective["negative"]
        item["selected_variant_id"] = effective["selected_variant_id"]
        item["_compare_id"] = str(
            item.get("id")
            or legacy_comparison_id(
                "char",
                item.get("name"),
                prompt,
                item.get("negative"),
                index,
            )
        )
        item["_compare_name"] = (
            item.get("name") or f"캐릭터 {index + 1}"
        ).strip()
        variant = (
            item.get("variant")
            if isinstance(item.get("variant"), dict)
            else {}
        )
        group = str(variant.get("group") or "").strip()
        if group:
            grouped.setdefault(group, []).append(item)
        else:
            standalone.append(item)
    out = list(standalone)
    for members in grouped.values():
        active = [
            item
            for item in members
            if (item.get("variant") or {}).get("enabled") is not False
        ]
        out.extend(active or members[:1])
    return out


def _compare_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def normalize_comparison_selection(value: Any) -> dict:
    """선택 실험 입력을 허용된 자료 id와 생성 설정 축으로만 줄인다."""
    raw = value if isinstance(value, dict) else {}

    def identifiers(key: str) -> list[str]:
        values = raw.get(key)
        values = values if isinstance(values, list) else []
        out, seen = [], set()
        for item in values[:20_000]:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    axes = {}
    raw_axes = raw.get("axes") if isinstance(raw.get("axes"), dict) else {}
    for path, spec in COMPARE_SELECTED_AXES.items():
        values = raw_axes.get(path)
        if not isinstance(values, list):
            continue
        kind, lower, upper = spec
        normalized, seen = [], set()
        for item in values[:50]:
            try:
                if kind == "int":
                    parsed = max(int(lower), min(int(upper), int(item)))
                elif kind == "float":
                    parsed = max(float(lower), min(float(upper), float(item)))
                elif kind == "bool":
                    parsed = _compare_bool(item)
                else:
                    parsed = str(item or "").strip()[:80]
                    if not parsed:
                        continue
            except (TypeError, ValueError, OverflowError):
                continue
            marker = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(parsed)
        if normalized:
            axes[path] = normalized
    return {
        "styles": identifiers("styles"),
        "characters": identifiers("characters"),
        "settings": identifiers("settings"),
        "axes": axes,
    }


def normalize_comparison_options(raw: Any, cfg: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("mode") or "styles")
    if mode not in COMPARE_MODE_LABELS:
        mode = "styles"
    try:
        limit = max(
            0, min(int(raw.get("limit") or 0), COMPARE_MAX_JOBS)
        )
    except (TypeError, ValueError, OverflowError):
        limit = 0
    try:
        seed = max(0, min(int(raw.get("seed") or 0), 2**32 - 1))
    except (TypeError, ValueError, OverflowError):
        seed = 0
    try:
        seed_count = max(1, min(int(raw.get("seed_count") or 1), 4))
    except (TypeError, ValueError, OverflowError):
        seed_count = 1
    try:
        width = normalize_resolution(raw.get("width", cfg.get("width", 832)))
        height = normalize_resolution(
            raw.get("height", cfg.get("height", 1216))
        )
    except (TypeError, ValueError, OverflowError):
        width = normalize_resolution(cfg.get("width", 832))
        height = normalize_resolution(cfg.get("height", 1216))
    return {
        "mode": mode,
        "fixed_size": _compare_bool(raw.get("fixed_size"), True),
        "width": width,
        "height": height,
        "same_seed": _compare_bool(raw.get("same_seed"), True),
        "seed": seed,
        "seed_count": seed_count,
        "limit": limit,
        "include_refs": _compare_bool(raw.get("include_refs"), False),
        "selection": normalize_comparison_selection(raw.get("selection")),
    }


def comparison_style_config(
    cfg: dict,
    style: dict | None,
    options: dict,
) -> dict:
    """그림체 한 건의 설정 묶음을 실행용 cfg 사본에 적용한다."""
    used = dict(cfg or {})
    params = (style or {}).get("params") or {}
    mapping = {
        "scale": "cfg_scale",
        "cfg_rescale": "cfg_rescale",
        "steps": "steps",
        "sampler": "sampler",
        "noise_schedule": "scheduler",
        "variety_plus": "variety",
        "uc_preset": "uc_preset",
        "quality_toggle": "quality_toggle",
        "sm": "smea",
        "sm_dyn": "smea_dyn",
        "dynamic_thresholding": "dynamic_thresholding",
        "uncond_scale": "uncond_scale",
        "controlnet_strength": "controlnet_strength",
        "prefer_brownian": "prefer_brownian",
        "deliberate_euler_ancestral_bug": "deliberate_euler_ancestral_bug",
    }
    for source, target in mapping.items():
        if params.get(source) is not None:
            used[target] = params[source]
    if params.get("model"):
        used["model"] = model_id_from_metadata(
            params.get("model"),
            used.get("model") or "nai-diffusion-4-5-full",
        )
    if params.get("width"):
        used["width"] = normalize_resolution(params["width"])
    if params.get("height"):
        used["height"] = normalize_resolution(params["height"])
    if options.get("fixed_size"):
        used["width"], used["height"] = options["width"], options["height"]
    return used


def comparison_sources(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    spec: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    return comparison_styles(operations, spec), comparison_characters(cfg)


def comparison_settings(cfg: dict) -> list[dict]:
    """현재 켠 세팅 중 실제 세트가 선택된 것만 실행용 사본으로 돌려준다."""
    rows = []
    for name, raw in (cfg.get("setting_state") or {}).items():
        if not isinstance(raw, dict):
            continue
        state = copy.deepcopy(raw)
        if state.get("use") is False or not state.get("selected"):
            continue
        rows.append({"id": str(name), "name": str(name), "state": state})
    return rows


def comparison_catalog(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    spec: dict | None = None,
) -> dict:
    """선택 실험 UI가 쓰는 가벼운 자료 목록."""
    styles = comparison_styles(operations, spec)
    characters = comparison_characters(cfg)
    settings = comparison_settings(cfg)
    return {
        "ok": True,
        "styles": [
            {"id": item["_compare_id"], "name": item["_compare_name"]}
            for item in styles
        ],
        "characters": [
            {"id": item["_compare_id"], "name": item["_compare_name"]}
            for item in characters
        ],
        "settings": [
            {"id": item["id"], "name": item["name"]} for item in settings
        ],
    }


def _comparison_selected_sources(
    styles: list[dict],
    characters: list[dict],
    settings: list[dict],
    selection: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    wanted_styles = set(selection.get("styles") or [])
    wanted_characters = set(selection.get("characters") or [])
    wanted_settings = set(selection.get("settings") or [])
    return (
        [
            item
            for item in styles
            if str(item.get("_compare_id") or "") in wanted_styles
        ],
        [
            item
            for item in characters
            if str(item.get("_compare_id") or "") in wanted_characters
        ],
        [
            item
            for item in settings
            if str(item.get("id") or "") in wanted_settings
        ],
    )


def _comparison_selected_cfg(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    material: dict,
) -> dict:
    """canonical 셀 재료를 사용자 설정을 건드리지 않는 실행 사본으로 바꾼다."""
    scratch = copy.deepcopy(cfg or {})
    scratch.update(copy.deepcopy(material.get("config_overrides") or {}))
    slots = copy.deepcopy(material.get("char_slots") or [])
    centers = copy.deepcopy(material.get("char_centers") or [])
    scratch["char_slots"] = slots
    scratch["char_centers"] = centers
    if material.get("setting_state"):
        scratch["setting_state"] = copy.deepcopy(material["setting_state"])

    selected_character = (material.get("job") or {}).get("character")
    if isinstance(selected_character, dict) and material.get("setting_state"):
        cast = _comparison_character_setting_slot(selected_character)
        for state in scratch["setting_state"].values():
            if not isinstance(state, dict):
                continue
            state["cast_source"] = "manual"
            state["cast_mode"] = "sequence"
            state["cast"] = [cast]

    if material.get("include_references") and isinstance(
        selected_character, dict
    ):
        scratch = operations.character_resource_config(
            scratch,
            _comparison_character_setting_scene_character(
                selected_character
            ),
        )
    return scratch


def _selected_comparison_leaf_seed(
    options: dict,
    runtime_base_seed: int | None,
    seed_index: int,
    leaf_index: int,
    canonical_seed: int | None,
) -> int | None:
    """선택 실험의 실제 실행 leaf마다 비교 가능한 결정적 seed를 만든다."""
    if runtime_base_seed is None:
        return canonical_seed
    offset = (
        int(seed_index)
        if options.get("same_seed", True)
        else max(0, int(leaf_index) - 1)
    )
    seed = (int(runtime_base_seed) + offset * 100003) & 0xFFFFFFFF
    return seed or 1


def iter_selected_comparison_jobs(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    styles: list[dict],
    chars: list[dict],
    settings: list[dict] | None = None,
    runtime_base_seed: int | None = None,
):
    """선택 자료·축 canonical 셀을 실제 비교/세팅 leaf 작업으로 펼친다."""
    selection = plan.get("selection") or plan["options"].get("selection") or {}
    settings = comparison_settings(cfg) if settings is None else list(settings)
    selected_styles, selected_chars, selected_settings = (
        _comparison_selected_sources(
            styles, chars, settings, selection
        )
    )
    expanded = expand_legacy_experiment_cells(
        cfg,
        {"options": dict(plan["options"], limit=0), "count": 0},
        styles=selected_styles,
        characters=selected_chars,
        settings=selected_settings,
        selected=selection,
    )
    limit = max(0, int(plan.get("count") or 0))
    made = 0
    for cell in expanded.get("cells") or []:
        material = legacy_execution_material(
            cell, cfg, runtime_base_seed=runtime_base_seed
        )
        scratch = _comparison_selected_cfg(operations, cfg, material)
        source = material.get("job") or {}
        style = source.get("style")
        character = source.get("character")
        setting = source.get("setting")
        style_name = source.get("style_name") or "현재 그림체"
        char_name = source.get("char_name") or "현재 캐릭터"
        setting_name = source.get("setting_name") or ""
        common = {
            "cell_id": material.get("cell_id"),
            "cell_resume_key": material.get("resume_key"),
            "canonical_cell": copy.deepcopy(cell),
            "material": material,
            "scratch_cfg": scratch,
            "style": style,
            "character": character,
            "setting": setting,
            "style_name": style_name,
            "char_name": char_name,
            "setting_name": setting_name,
            "seed_index": int(
                (material.get("seed_material") or {}).get("seed_index") or 0
            ),
            "seed": material.get("seed"),
        }
        if isinstance(setting, dict):
            asset_config = operations.load_asset_config(scratch)
            for derived, cast_id, scene_num, copy_num in (
                operations.compute_pending(scratch, asset_config, {}, set())
            ):
                if limit and made >= limit:
                    return
                made += 1
                yield dict(
                    common,
                    index=made,
                    seed=_selected_comparison_leaf_seed(
                        plan["options"],
                        runtime_base_seed,
                        common["seed_index"],
                        made,
                        common.get("seed"),
                    ),
                    key=legacy_comparison_id(
                        "job",
                        "selected",
                        material.get("resume_key"),
                        str(cast_id),
                        int(scene_num),
                        int(copy_num),
                    ),
                    cid=str(cast_id),
                    asset_config=asset_config,
                    scene_character=copy.deepcopy(derived),
                    scene_num=int(scene_num),
                    copy=int(copy_num),
                )
        else:
            if limit and made >= limit:
                return
            made += 1
            yield dict(
                common,
                index=made,
                seed=_selected_comparison_leaf_seed(
                    plan["options"],
                    runtime_base_seed,
                    common["seed_index"],
                    made,
                    common.get("seed"),
                ),
                key=str(
                    material.get("resume_key") or cell.get("id") or ""
                ),
            )


def comparison_selected_job_values(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    job: dict,
) -> tuple[dict, str, str, list, list]:
    scratch = job["scratch_cfg"]
    material = job["material"]
    if job.get("asset_config") is not None:
        asset_config = job["asset_config"]
        scene = asset_config["scenes"][str(job["scene_num"])]
        character = copy.deepcopy(job["scene_character"])
        (
            base,
            female,
            male,
            char_negative,
            male_negative,
            _width,
            _height,
        ) = build_scene(
            asset_config, character, scratch, int(job["scene_num"])
        )
        negative = asset_config["base"].get(
            "nsfw_negative_prompt",
            asset_config["base"].get("negative_prompt", ""),
        )
        if scene.get("negative"):
            negative = _join_tags(negative, scene["negative"])
        people, centers, use_positions = setting_scene_people(
            scene,
            female,
            male,
            char_negative,
            male_negative,
            character,
            scratch,
        )
        used = scratch
        if plan["options"].get("include_refs"):
            used, _, _ = operations.setting_reference_config(used, scene)
        used = with_position_mode(
            used, character.get("position_mode"), use_positions
        )
    else:
        used = scratch
        base = str(used.get("base_prompt") or "1girl")
        negative = str(used.get("negative_prompt") or "")
        people, centers = active_people(
            material.get("char_slots") or [],
            material.get("char_centers") or [],
        )
        selected_character = (material.get("job") or {}).get("character")
        if isinstance(selected_character, dict) and (
            selected_character.get("position")
            or selected_character.get("center")
        ):
            used = with_position_mode(used, "coordinate", True)
    if plan["options"].get("fixed_size"):
        used["width"] = plan["options"]["width"]
        used["height"] = plan["options"]["height"]
    return used, base, negative, people, centers


def comparison_selected_plan(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    options: dict,
    styles: list[dict],
    chars: list[dict],
    settings: list[dict],
    opus: bool | None = None,
    *,
    job_values: Any = None,
) -> dict:
    selection = options.get("selection") or {}
    chosen_styles, chosen_chars, chosen_settings = (
        _comparison_selected_sources(
            styles, chars, settings, selection
        )
    )
    errors = []
    if len(chosen_styles) != len(selection.get("styles") or []):
        errors.append(
            "선택한 그림체 중 현재 찾을 수 없는 항목이 있습니다."
        )
    if len(chosen_chars) != len(selection.get("characters") or []):
        errors.append(
            "선택한 캐릭터 중 현재 찾을 수 없는 항목이 있습니다."
        )
    if len(chosen_settings) != len(selection.get("settings") or []):
        errors.append(
            "선택한 세팅 중 현재 찾을 수 없는 항목이 있습니다."
        )
    if not any(
        (
            chosen_styles,
            chosen_chars,
            chosen_settings,
            selection.get("axes"),
        )
    ):
        errors.append(
            "그림체·캐릭터·세팅 또는 바꿀 생성 설정 축을 하나 이상 선택해주세요."
        )

    probe = {
        "options": options,
        "selection": selection,
        "count": COMPARE_MAX_JOBS + 1,
    }
    value_builder = job_values or (
        lambda used_cfg, used_plan, job: comparison_selected_job_values(
            operations, used_cfg, used_plan, job
        )
    )
    total = paid_total = opus_total = eligible = 0
    cost_cap = int(options.get("limit") or 0) or COMPARE_MAX_JOBS
    if not errors:
        for job in iter_selected_comparison_jobs(
            operations,
            cfg,
            probe,
            styles,
            chars,
            settings=settings,
        ):
            total += 1
            if total <= cost_cap:
                used, _, _, _, _ = value_builder(cfg, probe, job)
                refs = (
                    sum(
                        1
                        for item in (used.get("char_refs") or [])
                        if item.get("enabled")
                    )
                    if options.get("include_refs")
                    else 0
                )
                paid = anlas_estimate(
                    used, 1, opus=False, char_refs=refs
                )
                free = anlas_estimate(
                    used, 1, opus=True, char_refs=refs
                )
                paid_total += paid["per_image"]
                opus_total += free["per_image"]
                eligible += int(bool(free["free_eligible"]))
            if total > COMPARE_MAX_JOBS:
                break
    count = min(total, int(options.get("limit") or total))
    if count > COMPARE_MAX_JOBS:
        errors.append(
            f"한 계획은 최대 {COMPARE_MAX_JOBS:,}장까지 만들 수 있습니다."
        )
    result = {
        "ok": not errors,
        "errors": errors,
        "options": options,
        "selection": selection,
        "mode_label": COMPARE_MODE_LABELS["selected"],
        "styles": len(chosen_styles),
        "characters": len(chosen_chars),
        "settings": len(chosen_settings),
        "axes": len(selection.get("axes") or {}),
        "current_slots": len(
            [
                slot
                for slot in (cfg.get("char_slots") or [])
                if isinstance(slot, dict)
                and slot_prompt(slot).strip()
                and slot.get("enabled") is not False
            ]
        ),
        "combinations": total // max(1, options["seed_count"]),
        "seed_count": options["seed_count"],
        "total": total,
        "count": count,
        "limited": count < total,
        "free_eligible": min(eligible, count),
        "paid_anlas_max": paid_total,
        "opus_anlas": opus_total,
        "expected_anlas": (
            opus_total
            if opus is True
            else paid_total
            if opus is False
            else None
        ),
        "subscription_known": opus is not None,
        "sample_styles": [
            item["_compare_name"] for item in chosen_styles[:3]
        ],
        "sample_characters": [
            item["_compare_name"] for item in chosen_chars[:3]
        ],
        "sample_settings": [item["name"] for item in chosen_settings[:3]],
    }
    if not errors:
        experiment = expand_legacy_experiment_cells(
            cfg,
            {"options": dict(options, limit=0), "count": 0},
            styles=chosen_styles,
            characters=chosen_chars,
            settings=chosen_settings,
            selected=selection,
        )
        result["experiment"] = {
            "schema": experiment.get("schema"),
            "id": experiment.get("id"),
            "mode": experiment.get("legacy_mode"),
            "cells": experiment.get("total", 0),
            "total": total,
            "pending": total,
            "completed": 0,
            "cell_ids": [
                {
                    "id": cell.get("id"),
                    "resume_key": cell.get("legacy_resume_key"),
                }
                for cell in (experiment.get("cells") or [])[:10]
            ],
        }
    return result


def _comparison_character_setting_slot(character: dict | None) -> dict:
    """라이브러리 캐릭터를 세팅 캐스트 한 명의 무손실 사본으로 바꾼다."""
    item = character if isinstance(character, dict) else {}
    return {
        "id": item.get("id") or item.get("_compare_id") or "",
        "name": item.get("name")
        or item.get("_compare_name")
        or "캐릭터",
        "prompt": item.get("female", ""),
        "outfit": item.get("clothed", ""),
        "negative": item.get("negative", ""),
        "variant": copy.deepcopy(item.get("variant") or {}),
        "reference_ids": copy.deepcopy(item.get("reference_ids") or []),
        "vibe_ids": copy.deepcopy(item.get("vibe_ids") or []),
        "position": copy.deepcopy(
            item.get("position") or item.get("center") or {}
        ),
        "enabled": True,
    }


def _comparison_character_setting_cfg(
    cfg: dict,
    setting: dict | None,
    character: dict | None,
) -> dict:
    """한 캐릭터×세팅 셀만 보이게 만든 비영구 scratch 설정."""
    scratch = copy.deepcopy(cfg or {})
    states = {}
    setting_id = str(
        (setting or {}).get("id") or (setting or {}).get("name") or ""
    )
    for name, raw in (scratch.get("setting_state") or {}).items():
        state = copy.deepcopy(raw) if isinstance(raw, dict) else {}
        state["use"] = False
        states[str(name)] = state
    chosen = copy.deepcopy((setting or {}).get("state") or {})
    chosen["use"] = True
    chosen["cast_source"] = "manual"
    chosen["cast_mode"] = "sequence"
    chosen["cast"] = [_comparison_character_setting_slot(character)]
    states[setting_id] = chosen
    scratch["setting_state"] = states
    return scratch


def _comparison_character_setting_scene_character(
    character: dict | None,
) -> dict:
    """build_scene이 외형·착의를 단계별로 고를 수 있는 원형 캐릭터."""
    slot = _comparison_character_setting_slot(character)
    center = (
        slot.get("position")
        if isinstance(slot.get("position"), dict)
        else {}
    )
    return {
        "name": slot["name"],
        "female": slot["prompt"],
        "clothed": slot["outfit"],
        "negative": slot["negative"],
        "male_prompt_base": "",
        "partner_negative": "",
        "extras": [],
        "centers": [copy.deepcopy(center) if center else None],
        "reference_ids": copy.deepcopy(slot["reference_ids"]),
        "vibe_ids": copy.deepcopy(slot["vibe_ids"]),
    }


def iter_character_setting_jobs(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    chars: list[dict],
    settings: list[dict] | None = None,
):
    """캐릭터×세팅 셀을 선택 씬·단계·예약 매수까지 실제 한 장 단위로 펼친다."""
    options = plan["options"]
    limit = max(0, int(plan.get("count") or 0))
    made = 0
    settings = comparison_settings(cfg) if settings is None else list(settings)
    cell_plan = {"options": dict(options, limit=0), "count": 0}
    expanded = expand_legacy_experiment_cells(
        cfg,
        cell_plan,
        characters=chars,
        settings=settings,
    )
    cells = {}
    for cell in expanded.get("cells") or []:
        material = cell.get("legacy_material") or {}
        character = material.get("character") or {}
        setting = material.get("setting") or {}
        seed_index = int(
            (cell.get("seed_material") or {}).get("seed_index") or 0
        )
        cells[
            (
                str(
                    character.get("_compare_id")
                    or character.get("id")
                    or ""
                ),
                str(setting.get("id") or setting.get("name") or ""),
                seed_index,
            )
        ] = cell

    for character in chars:
        character_id = str(
            character.get("_compare_id") or character.get("id") or ""
        )
        for setting in settings:
            setting_id = str(
                setting.get("id") or setting.get("name") or ""
            )
            scratch = _comparison_character_setting_cfg(
                cfg, setting, character
            )
            asset_config = operations.load_asset_config(scratch)
            pending = operations.compute_pending(
                scratch, asset_config, {}, set()
            )
            scene_character = (
                _comparison_character_setting_scene_character(character)
            )
            for _derived, cast_id, scene_num, copy_num in pending:
                for seed_index in range(options["seed_count"]):
                    if limit and made >= limit:
                        return
                    cell = cells.get(
                        (character_id, setting_id, seed_index)
                    )
                    if cell is None:
                        continue
                    parent_key = str(
                        cell.get("legacy_resume_key")
                        or cell.get("id")
                        or ""
                    )
                    made += 1
                    yield {
                        "index": made,
                        "key": legacy_comparison_id(
                            "job",
                            "character_setting",
                            (
                                parent_key,
                                cast_id,
                                int(scene_num),
                                int(copy_num),
                            ),
                            int(seed_index),
                        ),
                        "cell_id": cell.get("id"),
                        "cell_resume_key": parent_key,
                        "style": None,
                        "character": character,
                        "setting": setting,
                        "style_name": (
                            str(cfg.get("style_name") or "").strip()
                            or "현재 그림체"
                        ),
                        "char_name": (
                            f"{character.get('_compare_name') or character.get('name') or '캐릭터'}"
                            f" × {setting.get('name') or setting_id}"
                        ),
                        "setting_name": setting.get("name") or setting_id,
                        "seed_index": int(seed_index),
                        "scene_num": int(scene_num),
                        "copy": int(copy_num),
                        "scratch_cfg": scratch,
                        "asset_config": asset_config,
                        "scene_character": scene_character,
                    }


def comparison_character_setting_job_values(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    job: dict,
) -> tuple[dict, str, str, list, list]:
    """세팅 배치의 장면 해석을 그대로 써 한 비교 leaf의 NAI 입력을 만든다."""
    scratch = job["scratch_cfg"]
    asset_config = job["asset_config"]
    scene_num = int(job["scene_num"])
    scene = asset_config["scenes"][str(scene_num)]
    character = copy.deepcopy(job["scene_character"])
    if scene.get("_mode") != "백합":
        character["female"] = _join_tags(
            character.get("female", ""), character.get("clothed", "")
        )
    (
        base,
        female,
        male,
        char_negative,
        male_negative,
        width,
        height,
    ) = build_scene(asset_config, character, scratch, scene_num)
    negative = asset_config["base"].get(
        "nsfw_negative_prompt",
        asset_config["base"].get("negative_prompt", ""),
    )
    scene_negative = scene.get("negative") or ""
    if scene_negative:
        negative = _join_tags(negative, scene_negative)
    people, centers, use_positions = setting_scene_people(
        scene,
        female,
        male,
        char_negative,
        male_negative,
        character,
        scratch,
    )
    if plan["options"].get("include_refs"):
        used = operations.character_resource_config(scratch, character)
        used, _, _ = operations.setting_reference_config(used, scene)
    else:
        used = dict(scratch)
    if plan["options"].get("fixed_size"):
        width = plan["options"]["width"]
        height = plan["options"]["height"]
    used["width"], used["height"] = int(width), int(height)
    used = with_position_mode(
        used, character.get("position_mode"), use_positions
    )
    return used, base, negative, people, centers


def comparison_character_setting_plan(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    options: dict,
    chars: list[dict],
    opus: bool | None = None,
    *,
    job_values: Any = None,
) -> dict:
    """캐릭터×선택 세팅의 실제 leaf 장수와 비용을 API 없이 계산한다."""
    settings = comparison_settings(cfg)
    errors = []
    if not chars:
        errors.append(
            "비교할 캐릭터가 없습니다. 캐릭터 라이브러리에 먼저 저장해주세요."
        )
    if not settings:
        errors.append("선택한 세트가 있는 켜진 세팅이 없습니다.")
    probe = {"options": options, "count": COMPARE_MAX_JOBS + 1}
    value_builder = job_values or (
        lambda used_cfg, used_plan, job: (
            comparison_character_setting_job_values(
                operations, used_cfg, used_plan, job
            )
        )
    )
    total = paid_total = opus_total = eligible = 0
    cost_cap = int(options.get("limit") or 0) or COMPARE_MAX_JOBS
    if not errors:
        for job in iter_character_setting_jobs(
            operations, cfg, probe, chars, settings=settings
        ):
            total += 1
            if total <= cost_cap:
                used, _, _, _, _ = value_builder(cfg, probe, job)
                refs = (
                    sum(
                        1
                        for item in (used.get("char_refs") or [])
                        if item.get("enabled")
                    )
                    if options.get("include_refs")
                    else 0
                )
                paid = anlas_estimate(
                    used, 1, opus=False, char_refs=refs
                )
                free = anlas_estimate(
                    used, 1, opus=True, char_refs=refs
                )
                paid_total += paid["per_image"]
                opus_total += free["per_image"]
                eligible += int(bool(free["free_eligible"]))
            if total > COMPARE_MAX_JOBS:
                break
    count = min(total, int(options.get("limit") or total))
    if count > COMPARE_MAX_JOBS:
        errors.append(
            f"한 계획은 최대 {COMPARE_MAX_JOBS:,}장까지 만들 수 있습니다."
        )
    result = {
        "ok": not errors,
        "errors": errors,
        "options": options,
        "mode_label": COMPARE_MODE_LABELS["character_setting"],
        "styles": 1,
        "characters": len(chars),
        "settings": len(settings),
        "current_slots": 0,
        "combinations": len(chars) * len(settings),
        "seed_count": options["seed_count"],
        "total": total,
        "count": count,
        "limited": count < total,
        "free_eligible": min(eligible, count),
        "paid_anlas_max": paid_total,
        "opus_anlas": opus_total,
        "expected_anlas": (
            opus_total
            if opus is True
            else paid_total
            if opus is False
            else None
        ),
        "subscription_known": opus is not None,
        "sample_styles": [
            str(cfg.get("style_name") or "현재 그림체")
        ],
        "sample_characters": [
            item["_compare_name"] for item in chars[:3]
        ],
        "sample_settings": [item["name"] for item in settings[:3]],
    }
    try:
        cell_plan = {
            "options": dict(options, limit=0),
            "count": 0,
        }
        experiment = expand_legacy_experiment_cells(
            cfg,
            cell_plan,
            characters=chars,
            settings=settings,
        )
        result["experiment"] = {
            "schema": experiment.get("schema"),
            "id": experiment.get("id"),
            "mode": experiment.get("legacy_mode"),
            "cells": experiment.get("total", 0),
            "total": total,
            "pending": total,
            "completed": 0,
            "cell_ids": [
                {
                    "id": cell.get("id"),
                    "resume_key": cell.get("legacy_resume_key"),
                }
                for cell in (experiment.get("cells") or [])[:10]
            ],
        }
    except Exception as error:
        result["experiment"] = {
            "ok": False,
            "error": redact_diagnostic_text(error),
        }
    return result


def _comparison_base_counts(
    cfg: dict,
    mode: str,
    options: dict,
    styles: list[dict],
    chars: list[dict],
) -> tuple[int, int, int, list[str]]:
    combinations = (
        len(styles) if mode == "styles"
        else len(chars) if mode == "characters"
        else len(styles) * len(chars)
    )
    total = combinations * options["seed_count"]
    count = min(total, options["limit"]) if options["limit"] else total
    errors = []
    if mode in ("styles", "both") and not styles:
        errors.append(
            "비교할 그림체가 없습니다. 자료팩이나 그림체 자료를 먼저 넣어주세요."
        )
    if mode in ("characters", "both") and not chars:
        errors.append(
            "비교할 캐릭터가 없습니다. 캐릭터 라이브러리에 먼저 저장해주세요."
        )
    if count > COMPARE_MAX_JOBS:
        errors.append(
            f"한 계획은 최대 {COMPARE_MAX_JOBS:,}장까지 만들 수 있습니다."
        )
    return combinations, total, count, errors


def _comparison_costs(
    cfg: dict,
    mode: str,
    options: dict,
    styles: list[dict],
    chars: list[dict],
    count: int,
) -> tuple[int, int, int]:
    refs = (
        sum(1 for reference in cfg.get("char_refs", []) if reference.get("enabled"))
        if options["include_refs"] else 0
    )
    paid_total = opus_total = eligible = 0
    remain = count

    def add(job_cfg: dict, multiplier: int) -> None:
        nonlocal paid_total, opus_total, eligible, remain
        number = max(0, min(int(multiplier), remain))
        if not number:
            return
        paid = anlas_estimate(job_cfg, 1, opus=False, char_refs=refs)
        free = anlas_estimate(job_cfg, 1, opus=True, char_refs=refs)
        paid_total += paid["per_image"] * number
        opus_total += free["per_image"] * number
        eligible += number if free["free_eligible"] else 0
        remain -= number

    if mode == "characters":
        add(comparison_style_config(cfg, None, options), count)
    else:
        multiplier = (
            options["seed_count"]
            if mode == "styles"
            else len(chars) * options["seed_count"]
        )
        for style in styles:
            if remain <= 0:
                break
            add(comparison_style_config(cfg, style, options), multiplier)
    return paid_total, opus_total, eligible


def _attach_experiment(
    cfg: dict,
    result: dict,
    styles: list[dict],
    chars: list[dict],
) -> None:
    """실행 전 계획에 공통 실험 셀 식별자를 붙이되 실패는 진단으로만 남긴다."""
    try:
        experiment = expand_legacy_experiment_cells(
            cfg, result, styles=styles, characters=chars
        )
        result["experiment"] = {
            "schema": experiment.get("schema"),
            "id": experiment.get("id"),
            "mode": experiment.get("legacy_mode"),
            "total": experiment.get("total", 0),
            "pending": experiment.get("pending", 0),
            "completed": experiment.get("completed", 0),
            "cell_ids": [
                {"id": cell.get("id"), "resume_key": cell.get("legacy_resume_key")}
                for cell in (experiment.get("cells") or [])[:10]
            ],
        }
    except Exception as error:
        result["experiment"] = {
            "ok": False,
            "error": redact_diagnostic_text(error),
        }


def comparison_plan(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    raw: dict,
    spec: dict | None = None,
    opus: bool | None = None,
    *,
    selected_job_values: Any = None,
    character_setting_job_values: Any = None,
) -> dict:
    """실행 전에 장수와 과금 범위를 계산한다. API 호출은 하지 않는다."""
    options = normalize_comparison_options(raw, cfg)
    mode = options["mode"]
    styles, chars = (
        ([], comparison_characters(cfg))
        if mode == "character_setting"
        else comparison_sources(operations, cfg, spec)
    )
    if mode == "selected":
        return comparison_selected_plan(
            operations, cfg, options, styles, chars, comparison_settings(cfg),
            opus=opus, job_values=selected_job_values,
        )
    if mode == "character_setting":
        return comparison_character_setting_plan(
            operations, cfg, options, chars, opus=opus,
            job_values=character_setting_job_values,
        )
    current_slots = [
        slot
        for slot in (cfg.get("char_slots") or [])
        if slot_prompt(slot).strip()
        and slot.get("enabled") is not False
    ]
    combinations, total, count, errors = _comparison_base_counts(
        cfg, mode, options, styles, chars
    )
    paid_total, opus_total, eligible = _comparison_costs(
        cfg, mode, options, styles, chars, count
    )
    expected = None
    if opus is True:
        expected = opus_total
    elif opus is False:
        expected = paid_total
    result = {
        "ok": not errors,
        "errors": errors,
        "options": options,
        "mode_label": COMPARE_MODE_LABELS[mode],
        "styles": len(styles),
        "characters": len(chars),
        "current_slots": len(current_slots),
        "combinations": combinations,
        "seed_count": options["seed_count"],
        "total": total,
        "count": count,
        "limited": count < total,
        "free_eligible": eligible,
        "paid_anlas_max": paid_total,
        "opus_anlas": opus_total,
        "expected_anlas": expected,
        "subscription_known": opus is not None,
        "sample_styles": [
            item["_compare_name"] for item in styles[:3]
        ],
        "sample_characters": [
            item["_compare_name"] for item in chars[:3]
        ],
    }
    _attach_experiment(cfg, result, styles, chars)
    return result


def comparison_signature(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    styles: list[dict],
    chars: list[dict],
) -> str:
    options = plan["options"]
    selected_settings = comparison_settings(cfg)
    if options["mode"] == "selected":
        selected_styles, selected_chars, selected_settings = (
            _comparison_selected_sources(
                styles,
                chars,
                selected_settings,
                plan.get("selection")
                or options.get("selection")
                or {},
            )
        )
    else:
        selected_styles, selected_chars = styles, chars
    relevant_cfg = {
        key: cfg.get(key)
        for key in (
            "base_prompt",
            "negative_prompt",
            "cfg_scale",
            "cfg_rescale",
            "steps",
            "sampler",
            "scheduler",
            "variety",
            "model",
            "uc_preset",
            "quality_toggle",
            "smea",
            "smea_dyn",
            "dynamic_thresholding",
            "uncond_scale",
            "controlnet_strength",
            "prefer_brownian",
            "deliberate_euler_ancestral_bug",
            "use_coords",
            "position_mode",
            "char_slots",
            "char_centers",
            "vibes",
            "char_refs",
            "out_dir",
            "out_by_date",
        )
    }
    raw = {
        "options": options,
        "selection": (
            plan.get("selection")
            or options.get("selection")
            or {}
            if options["mode"] == "selected"
            else {}
        ),
        "config": relevant_cfg,
        "styles": [
            (
                item["_compare_id"],
                item.get("base"),
                item.get("combo"),
                item.get("negative"),
                item.get("params"),
            )
            for item in styles
        ]
        if options["mode"] in ("styles", "both")
        else [
            (
                item["_compare_id"],
                item.get("base"),
                item.get("combo"),
                item.get("negative"),
                item.get("params"),
            )
            for item in selected_styles
        ]
        if options["mode"] == "selected"
        else [],
        "characters": [
            (
                item["_compare_id"],
                item.get("female"),
                item.get("clothed"),
                item.get("negative"),
            )
            for item in chars
        ]
        if options["mode"]
        in ("characters", "both", "character_setting")
        else [
            (
                item["_compare_id"],
                item.get("female"),
                item.get("clothed"),
                item.get("negative"),
                item.get("position"),
                item.get("reference_ids"),
                item.get("vibe_ids"),
            )
            for item in selected_chars
        ]
        if options["mode"] == "selected"
        else [],
        "settings": selected_settings
        if options["mode"] in ("character_setting", "selected")
        else [],
    }
    return hashlib.sha256(
        json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def iter_comparison_jobs(
    cfg: dict,
    plan: dict,
    styles: list[dict],
    chars: list[dict],
):
    """큰 직교곱도 목록 전체를 메모리에 만들지 않고 한 건씩 낸다."""
    options, made = plan["options"], 0
    limit = plan["count"]

    def emit(
        style: dict | None,
        char: dict | None,
        style_name: str,
        char_name: str,
        key: Any,
        seed_index: int,
    ) -> dict | None:
        nonlocal made
        if made >= limit:
            return None
        made += 1
        return {
            "index": made,
            "key": legacy_comparison_id(
                "job", options["mode"], key, int(seed_index)
            ),
            "style": style,
            "character": char,
            "style_name": style_name,
            "char_name": char_name,
            "seed_index": int(seed_index),
        }

    if options["mode"] == "styles":
        slots = [
            slot
            for slot in (cfg.get("char_slots") or [])
            if slot_prompt(slot).strip()
            and slot.get("enabled") is not False
        ]
        char_name = (
            f"현재 캐릭터 {len(slots)}명" if slots else "캐릭터 없음"
        )
        slot_key = [
            (slot_prompt(slot), slot.get("negative", ""))
            for slot in slots
        ]
        for style in styles:
            for seed_index in range(options["seed_count"]):
                job = emit(
                    style,
                    None,
                    style["_compare_name"],
                    char_name,
                    (style["_compare_id"], slot_key),
                    seed_index,
                )
                if job is None:
                    return
                yield job
    elif options["mode"] == "characters":
        for char in chars:
            for seed_index in range(options["seed_count"]):
                job = emit(
                    None,
                    char,
                    "현재 그림체",
                    char["_compare_name"],
                    ("current", char["_compare_id"]),
                    seed_index,
                )
                if job is None:
                    return
                yield job
    else:
        for style in styles:
            for char in chars:
                for seed_index in range(options["seed_count"]):
                    job = emit(
                        style,
                        char,
                        style["_compare_name"],
                        char["_compare_name"],
                        (style["_compare_id"], char["_compare_id"]),
                        seed_index,
                    )
                    if job is None:
                        return
                    yield job


def comparison_job_values(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    job: dict,
    *,
    selected_job_values: Any = None,
    character_setting_job_values: Any = None,
) -> tuple[dict, str, str, list, list]:
    if plan["options"].get("mode") == "character_setting":
        if character_setting_job_values is not None:
            return character_setting_job_values(cfg, plan, job)
        return comparison_character_setting_job_values(
            operations, cfg, plan, job
        )
    if plan["options"].get("mode") == "selected":
        if selected_job_values is not None:
            return selected_job_values(cfg, plan, job)
        return comparison_selected_job_values(
            operations, cfg, plan, job
        )
    options = plan["options"]
    style = job.get("style")
    used = comparison_style_config(cfg, style, options)
    base = (
        (style or {}).get("base")
        or (style or {}).get("combo")
        or cfg.get("base_prompt")
        or "1girl"
    ).strip()
    negative = (
        (style or {}).get("negative")
        if style is not None
        else cfg.get("negative_prompt", "")
    )
    negative = negative or ""
    char = job.get("character")
    if char is not None:
        used = operations.character_resource_config(used, char)
        people = [
            {
                "prompt": _comparison_character_prompt(char),
                "negative": char.get("negative", "") or "",
            }
        ]
        centers = [{"x": 0.5, "y": 0.5}]
    else:
        used = operations.characters_resource_config(
            used, cfg.get("char_slots") or []
        )
        people, centers = active_people(
            cfg.get("char_slots") or [],
            cfg.get("char_centers"),
        )
    return used, base, negative, people, centers


def comparison_job_recipe_snapshot(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    job: dict,
    used: dict,
    base: str,
    negative: str,
    people: list,
    centers: list,
    seed: int,
) -> dict:
    """현재 자료가 나중에 바뀌어도 한 결과를 복원할 수 있는 비밀값 없는 사본."""
    character = job.get("character") or {}
    setting = job.get("setting") or {}
    style = job.get("style") or {}
    mode = plan["options"].get("mode")
    if mode == "character_setting":
        slots = [
            {
                "id": character.get("id")
                or character.get("_compare_id")
                or "",
                "name": character.get("name")
                or character.get("_compare_name")
                or "",
                "prompt": character.get("female", ""),
                "outfit": character.get("clothed", ""),
                "negative": character.get("negative", ""),
                "variant": copy.deepcopy(character.get("variant") or {}),
                "variants": copy.deepcopy(
                    character.get("variants") or []
                ),
                "reference_ids": copy.deepcopy(
                    character.get("reference_ids") or []
                ),
                "vibe_ids": copy.deepcopy(
                    character.get("vibe_ids") or []
                ),
                "enabled": True,
            }
        ]
        position = (
            character.get("position") or character.get("center") or {}
        )
        char_centers = [copy.deepcopy(position)] if position else []
        source_setting = {
            "id": setting.get("id") or setting.get("name") or "",
            "name": setting.get("name") or setting.get("id") or "",
            "state": copy.deepcopy(setting.get("state") or {}),
            "scene": int(job.get("scene_num") or 0),
            "copy": int(job.get("copy") or 1),
        }
    elif mode == "selected":
        material = job.get("material") or {}
        slots = copy.deepcopy(material.get("char_slots") or [])
        char_centers = copy.deepcopy(
            material.get("char_centers") or []
        )
        source_setting = (
            {
                "id": setting.get("id") or setting.get("name") or "",
                "name": setting.get("name") or setting.get("id") or "",
                "state": copy.deepcopy(setting.get("state") or {}),
                "cid": str(job.get("cid") or ""),
                "scene": int(job.get("scene_num") or 0),
                "copy": int(job.get("copy") or 1),
            }
            if setting
            else {}
        )
    elif character:
        slots = [
            {
                "id": character.get("id")
                or character.get("_compare_id")
                or "",
                "name": character.get("name")
                or character.get("_compare_name")
                or "",
                "prompt": character.get("female", ""),
                "outfit": character.get("clothed", ""),
                "negative": character.get("negative", ""),
                "variant": copy.deepcopy(character.get("variant") or {}),
                "variants": copy.deepcopy(
                    character.get("variants") or []
                ),
                "reference_ids": copy.deepcopy(
                    character.get("reference_ids") or []
                ),
                "vibe_ids": copy.deepcopy(
                    character.get("vibe_ids") or []
                ),
                "enabled": True,
            }
        ]
        char_centers = [{"x": 0.5, "y": 0.5}]
        source_setting = {}
    else:
        slots = [
            copy.deepcopy(slot)
            for slot in (cfg.get("char_slots") or [])
            if isinstance(slot, dict)
            and slot.get("enabled") is not False
            and slot_prompt(slot).strip()
        ][: operations.max_characters]
        _, char_centers = active_people(
            cfg.get("char_slots") or [],
            cfg.get("char_centers"),
        )
        source_setting = {}
    include_refs = bool(plan["options"].get("include_refs"))
    wanted_vibes = {
        str(value)
        for slot in slots
        if isinstance(slot, dict)
        for value in (slot.get("vibe_ids") or [])
        if value
    }
    wanted_refs = {
        str(value)
        for slot in slots
        if isinstance(slot, dict)
        for value in (slot.get("reference_ids") or [])
        if value
    }
    saved_vibes = [
        copy.deepcopy(item)
        for item in (used.get("vibes") or [])
        if include_refs
        and isinstance(item, dict)
        and (
            str(item.get("id") or "") in wanted_vibes
            or (not wanted_vibes and item.get("enabled"))
        )
    ]
    saved_refs = [
        copy.deepcopy(item)
        for item in (used.get("char_refs") or [])
        if include_refs
        and isinstance(item, dict)
        and (
            str(item.get("id") or "") in wanted_refs
            or (not wanted_refs and item.get("enabled"))
        )
    ]
    return {
        "version": 2,
        "mode": plan["options"].get("mode") or "",
        "base_prompt": base,
        "negative_prompt": negative,
        "style_name": (
            style.get("name")
            or style.get("title")
            or style.get("_compare_name")
            or cfg.get("style_name", "")
        ),
        "settings": {
            key: used.get(key)
            for key in operations.recipe_setting_keys
        },
        "char_slots": slots,
        "char_centers": char_centers,
        "nai_seed": int(seed),
        "include_refs": include_refs,
        "vibes": saved_vibes,
        "char_refs": saved_refs,
        "source": {
            "style": {
                key: copy.deepcopy(style.get(key))
                for key in (
                    "id",
                    "_compare_id",
                    "title",
                    "name",
                    "_compare_name",
                    "base",
                    "combo",
                    "negative",
                    "params",
                )
                if style.get(key) is not None
            },
            "character": {
                key: copy.deepcopy(character.get(key))
                for key in (
                    "id",
                    "_compare_id",
                    "name",
                    "_compare_name",
                    "female",
                    "clothed",
                    "negative",
                    "variant",
                    "variants",
                    "reference_ids",
                    "vibe_ids",
                    "position",
                )
                if character.get(key) is not None
            },
            "setting": source_setting,
            "axes": copy.deepcopy(
                (job.get("material") or {}).get("selected_axes") or {}
            ),
        },
        "resolved": {
            "base_prompt": base,
            "negative_prompt": negative,
            "characters": copy.deepcopy(people),
            "char_centers": copy.deepcopy(centers),
        },
    }


def comparison_recipe_context(
    operations: ComparisonPlanningOperations,
    cfg: dict,
    plan: dict,
    styles: list[dict],
    chars: list[dict],
) -> dict:
    """비교 결과가 현재 자료 변경 뒤에도 재현되도록 원문을 한 번만 스냅샷한다."""
    options = plan.get("options") or {}
    context_settings = comparison_settings(cfg)
    if options.get("mode") == "selected":
        styles, chars, context_settings = _comparison_selected_sources(
            styles,
            chars,
            context_settings,
            plan.get("selection") or options.get("selection") or {},
        )
    all_slots = cfg.get("char_slots") or []
    active_slots = [
        dict(slot)
        for slot in all_slots
        if isinstance(slot, dict)
        and slot_prompt(slot).strip()
        and slot.get("enabled") is not False
    ][: operations.max_characters]
    _, active_centers = active_people(
        all_slots,
        cfg.get("char_centers"),
    )
    config = {
        key: cfg.get(key)
        for key in (
            "base_prompt",
            "negative_prompt",
            "style_name",
            *operations.recipe_setting_keys,
        )
    }
    if options.get("include_refs"):
        config["vibes"] = cfg.get("vibes") or []
        config["char_refs"] = cfg.get("char_refs") or []
    context = {
        "version": 1,
        "options": options,
        "config": config,
        "char_slots": active_slots,
        "char_centers": active_centers,
        "styles": [
            {
                "id": item.get("_compare_id"),
                "name": item.get("_compare_name"),
                "kind": item.get("_compare_kind"),
                "base": item.get("base") or item.get("combo") or "",
                "negative": item.get("negative") or "",
                "params": item.get("params") or {},
            }
            for item in styles
            if options.get("mode") in ("styles", "both", "selected")
        ],
        "characters": [
            {
                "id": item.get("_compare_id"),
                "name": item.get("_compare_name"),
                "female": item.get("female") or "",
                "clothed": item.get("clothed") or "",
                "negative": item.get("negative") or "",
                "source": item.get("source") or "",
            }
            for item in chars
            if options.get("mode")
            in ("characters", "both", "character_setting", "selected")
        ],
        "settings": context_settings
        if options.get("mode") in ("character_setting", "selected")
        else [],
        "selection": copy.deepcopy(
            plan.get("selection") or options.get("selection") or {}
        ),
    }
    context["blueprint"] = operations.inherited_blueprint(
        cfg,
        source={"kind": "comparison-plan"},
        experiment={
            "mode": options.get("mode") or "single",
            "fixed_size": bool(options.get("fixed_size")),
            "width": options.get("width"),
            "height": options.get("height"),
            "same_seed": bool(options.get("same_seed")),
            "seed": options.get("seed"),
            "seed_count": options.get("seed_count"),
            "limit": options.get("limit"),
            "include_references": bool(options.get("include_refs")),
        },
    )
    return context


__all__ = [
    "COMPARE_MAX_JOBS",
    "COMPARE_MODE_LABELS",
    "COMPARE_SELECTED_AXES",
    "ComparisonPlanningOperations",
    "_comparison_character_prompt",
    "_comparison_character_setting_cfg",
    "_comparison_character_setting_scene_character",
    "_comparison_character_setting_slot",
    "_comparison_selected_cfg",
    "comparison_catalog",
    "comparison_character_setting_job_values",
    "comparison_character_setting_plan",
    "comparison_characters",
    "comparison_job_recipe_snapshot",
    "comparison_job_values",
    "comparison_plan",
    "comparison_recipe_context",
    "comparison_selected_job_values",
    "comparison_selected_plan",
    "comparison_settings",
    "comparison_signature",
    "comparison_sources",
    "comparison_style_config",
    "comparison_styles",
    "iter_character_setting_jobs",
    "iter_comparison_jobs",
    "iter_selected_comparison_jobs",
    "normalize_comparison_options",
    "normalize_comparison_selection",
]
