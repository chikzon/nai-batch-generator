# -*- coding: utf-8 -*-
"""기존 자료 비교·세팅 상태를 공통 실험 셀로 투영하는 순수 어댑터."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.nai_studio.domain.blueprint import canonical_generation_plan
from src.nai_studio.domain.experiment import (
    canonical_experiment_rule,
    expand_experiment,
    regeneration_identity,
)


_GENERATION_KEYS = (
    "model", "width", "height", "nai_seed", "steps", "cfg_scale",
    "cfg_rescale", "sampler", "scheduler", "uc_preset", "quality_toggle",
    "variety", "smea", "smea_dyn", "dynamic_thresholding",
    "uncond_scale", "controlnet_strength", "prefer_brownian",
    "deliberate_euler_ancestral_bug", "use_coords",
)
_SECRET_KEYS = {
    "token", "api_token", "authorization", "nai_token", "secret",
    "access_token", "persistent_token", "api_key", "apikey",
}


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _without_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_secrets(item)
            for key, item in value.items()
            if (
                str(key).casefold() not in _SECRET_KEYS
                and not str(key).casefold().endswith("_token")
            )
        }
    if isinstance(value, list):
        return [_without_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_without_secrets(item) for item in value]
    return deepcopy(value)


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _legacy_comparison_id(prefix: str, *parts: Any) -> str:
    """legacy_app._comparison_id와 바이트 단위로 같은 재개 key."""
    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _strip_comment_lines(value: Any) -> str:
    lines = str(value or "").splitlines(keepends=True)
    return "".join(line for line in lines if not line.lstrip(" \t").startswith("#"))


def _legacy_slot_prompt(value: Mapping[str, Any]) -> str:
    parts = []
    for key in ("prompt", "outfit"):
        item = _strip_comment_lines(value.get(key)).strip().strip(",").strip()
        if item:
            parts.append(item)
    return ", ".join(parts)


def _legacy_job_key(
    cfg: Mapping[str, Any],
    legacy_mode: str,
    assignments: Mapping[str, Any],
    seed_index: int,
) -> str | None:
    style = assignments.get("style")
    character = assignments.get("character")
    if legacy_mode == "styles" and isinstance(style, Mapping):
        slot_key = []
        for raw in _list(cfg.get("char_slots")):
            if not isinstance(raw, Mapping) or raw.get("enabled") is False:
                continue
            prompt = _legacy_slot_prompt(raw)
            if prompt:
                slot_key.append([prompt, raw.get("negative", "")])
        key = [_source_id(style), slot_key]
    elif legacy_mode == "characters" and isinstance(character, Mapping):
        key = ["current", _source_id(character)]
    elif (
        legacy_mode == "both"
        and isinstance(style, Mapping)
        and isinstance(character, Mapping)
    ):
        key = [_source_id(style), _source_id(character)]
    else:
        return None
    return _legacy_comparison_id("job", legacy_mode, key, int(seed_index))


def _source_id(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("_compare_id", "id", "name", "_compare_name"):
            if value.get(key) not in (None, ""):
                return str(value.get(key))
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, default=str
        ).encode("utf-8")
    ).hexdigest()


def _filter_selected(values: Sequence[Any], selected: Any) -> list:
    items = _without_secrets(_list(values))
    if selected in (None, (), [], {}):
        return items
    wanted = {
        str(item) for item in (
            selected.keys() if isinstance(selected, Mapping) else selected
        )
    }
    return [item for item in items if _source_id(item) in wanted]


def _setting_sources(
    cfg: Mapping[str, Any],
    explicit: Sequence[Mapping[str, Any]] | None,
) -> list[dict]:
    if explicit is not None:
        return [
            _without_secrets(item)
            for item in explicit if isinstance(item, Mapping)
        ]
    output = []
    for name, raw_state in _mapping(cfg.get("setting_state")).items():
        if not isinstance(raw_state, Mapping):
            continue
        state = _without_secrets(raw_state)
        if state.get("use") is False:
            continue
        output.append({
            "id": str(name),
            "name": str(name),
            "state": state,
            "selected": _list(state.get("selected")),
            "stages": _list(state.get("stages")),
            "options": _mapping(state.get("opts")),
            "cast": _list(state.get("cast")),
        })
    return output


def legacy_blueprint_from_config(value: Mapping[str, Any]) -> dict:
    """토큰·실행 상태 없이 현재 비교 기준을 생성 설계도 사본으로 만든다."""
    cfg = _mapping(value)
    slots = []
    centers = _list(cfg.get("char_centers"))
    for index, raw in enumerate(_list(cfg.get("char_slots"))):
        if not isinstance(raw, Mapping):
            continue
        slot = _without_secrets(raw)
        center = (
            centers[index] if index < len(centers)
            and isinstance(centers[index], Mapping) else {}
        )
        slots.append({
            **slot,
            "appearance": str(
                slot.get("prompt") or slot.get("female") or ""
            ),
            "clothed": str(
                slot.get("outfit") or slot.get("clothed") or ""
            ),
            "negative": str(slot.get("negative") or ""),
            "position": _without_secrets(center),
        })
    generation = {
        key: _without_secrets(cfg.get(key))
        for key in _GENERATION_KEYS if key in cfg
    }
    generation["seed"] = generation.pop(
        "nai_seed", _without_secrets(cfg.get("seed"))
    )
    return canonical_generation_plan({
        "source": {"kind": "legacy-comparison-config"},
        "style": {
            "name": str(cfg.get("style_name") or ""),
            "base": str(cfg.get("base_prompt") or ""),
            "negative": str(cfg.get("negative_prompt") or ""),
        },
        "characters": slots,
        "resources": {
            "vibes": _without_secrets(_list(cfg.get("vibes"))),
            "character_references": _without_secrets(
                _list(cfg.get("char_refs"))
            ),
        },
        "setting": {
            "name": "",
            "active": _without_secrets(_mapping(cfg.get("setting_state"))),
        },
        "experiment": {"mode": "single"},
        "generation": generation,
    })


def experiment_rule_from_legacy(
    cfg: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    styles: Sequence[Mapping[str, Any]] | None = None,
    characters: Sequence[Mapping[str, Any]] | None = None,
    settings: Sequence[Mapping[str, Any]] | None = None,
    selected: Mapping[str, Any] | None = None,
) -> dict:
    """기존 comparison options와 수동 선택을 공통 실험 규칙으로 바꾼다."""
    safe_cfg = _mapping(_without_secrets(cfg))
    safe_plan = _mapping(_without_secrets(plan))
    options = _mapping(safe_plan.get("options"))
    selection = _mapping(_without_secrets(selected))
    mode = str(options.get("mode") or safe_plan.get("mode") or "styles")
    mode_aliases = {
        "styles": "all_styles",
        "characters": "all_characters",
        "both": "style_character_cross",
        "character_setting": "character_setting_cross",
        "selected": "selected_groups",
    }
    canonical_mode = mode_aliases.get(mode, mode)
    style_values = _filter_selected(
        styles or safe_plan.get("styles_source") or [],
        selection.get("styles"),
    )
    character_values = _filter_selected(
        characters or safe_plan.get("characters_source") or [],
        selection.get("characters"),
    )
    setting_values = _filter_selected(
        _setting_sources(safe_cfg, settings),
        selection.get("settings"),
    )
    seed_count = max(1, int(options.get("seed_count") or 1))
    # 기존 iter_comparison_jobs 순서(style → character → seed)를 유지한다.
    # 순서가 바뀌면 same_seed=False의 시드와 중단 재개 키가 달라진다.
    axes = []
    if canonical_mode in ("all_styles", "style_character_cross"):
        axes.append({"name": "style", "values": style_values})
    if canonical_mode in (
        "all_characters", "style_character_cross",
        "character_setting_cross",
    ):
        axes.append({"name": "character", "values": character_values})
    if canonical_mode == "character_setting_cross":
        axes.append({"name": "setting", "values": setting_values})
    if canonical_mode == "selected_groups":
        if style_values:
            axes.append({"name": "style", "values": style_values})
        if character_values:
            axes.append({"name": "character", "values": character_values})
        if setting_values:
            axes.append({"name": "setting", "values": setting_values})
        for name, values in sorted(_mapping(selection.get("axes")).items()):
            axes.append({
                "name": str(name),
                "values": _without_secrets(_list(values)),
            })
    axes.append({
        "name": "experiment.seed_index",
        "values": list(range(seed_count)),
    })
    fixed = {
        "experiment.seed_policy": {
            "same_seed": bool(options.get("same_seed", True)),
            "base_seed": int(options.get("seed") or 0),
            "stride": 100003,
        },
    }
    if options.get("fixed_size"):
        if options.get("width") is not None:
            fixed["generation.width"] = deepcopy(options.get("width"))
        if options.get("height") is not None:
            fixed["generation.height"] = deepcopy(options.get("height"))

    rule = {
        "mode": canonical_mode,
        "styles": style_values,
        "characters": character_values,
        "settings": setting_values,
        "axes": axes,
        "fixed": fixed,
        "limit": int(options.get("limit") or safe_plan.get("count") or 0),
        "metadata": {
            "legacy_mode": mode,
            "legacy_options": options,
            "include_references": bool(options.get("include_refs")),
        },
    }
    if canonical_mode == "selected_groups":
        selected_axes = _mapping(selection.get("axes"))
        groups = {
            str(name): _without_secrets(_list(values))
            for name, values in selected_axes.items()
        }
        if style_values:
            groups["style"] = style_values
        if character_values:
            groups["character"] = character_values
        if setting_values:
            groups["setting"] = setting_values
        rule["selected_groups"] = groups
    return canonical_experiment_rule(rule)


def _seed_material(
    cell_index: int,
    seed_index: int,
    policy: Mapping[str, Any],
) -> dict:
    base_seed = int(policy.get("base_seed") or 0)
    stride = int(policy.get("stride") or 100003)
    same_seed = bool(policy.get("same_seed", True))
    offset_index = seed_index if same_seed else cell_index
    offset = offset_index * stride
    return {
        "same_seed": same_seed,
        "base_seed": base_seed or None,
        "seed_index": seed_index,
        "offset": offset,
        "resolved_seed": ((base_seed + offset) & 0xffffffff) or 1
        if base_seed else None,
        "requires_runtime_base_seed": not bool(base_seed),
    }


def expand_legacy_experiment_cells(
    cfg: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    styles: Sequence[Mapping[str, Any]] | None = None,
    characters: Sequence[Mapping[str, Any]] | None = None,
    settings: Sequence[Mapping[str, Any]] | None = None,
    selected: Mapping[str, Any] | None = None,
    completed_keys: Sequence[str] | None = None,
) -> dict:
    """기존 모드와 새 축을 실행기가 소비할 결정적 셀 재료로 확장한다."""
    base = legacy_blueprint_from_config(cfg)
    rule = experiment_rule_from_legacy(
        cfg,
        plan,
        styles=styles,
        characters=characters,
        settings=settings,
        selected=selected,
    )
    expanded = expand_experiment(base, rule)
    completed = {str(item) for item in (completed_keys or ())}
    policy = _mapping(rule.get("fixed")).get("experiment.seed_policy") or {}
    cells = []
    for index, raw_cell in enumerate(expanded["cells"]):
        cell = deepcopy(raw_cell)
        assignments = _mapping(cell.get("assignments"))
        seed_index = int(assignments.get("experiment.seed_index") or 0)
        identity = {
            key: _source_id(value)
            for key, value in assignments.items()
            if key != "experiment.seed_index"
        }
        identity["seed_index"] = seed_index
        identity["mode"] = rule["metadata"].get("legacy_mode")
        legacy_job_key = _legacy_job_key(
            cfg,
            str(rule["metadata"].get("legacy_mode") or ""),
            assignments,
            seed_index,
        )
        resume_key = legacy_job_key or _stable_id("legacy-cell", identity)
        cell["legacy_resume_key"] = resume_key
        cell["legacy_job_key"] = legacy_job_key
        cell["seed_material"] = _seed_material(index, seed_index, policy)
        cell["legacy_material"] = {
            "style": deepcopy(assignments.get("style")),
            "character": deepcopy(assignments.get("character")),
            "setting": deepcopy(assignments.get("setting")),
            "selected_axes": {
                key: deepcopy(value)
                for key, value in assignments.items()
                if key not in (
                    "style", "character", "setting",
                    "experiment.seed_index",
                )
            },
            "include_references": bool(
                rule["metadata"].get("include_references")
            ),
            "seed": deepcopy(cell["seed_material"]),
        }
        if (
            cell["id"] in completed
            or resume_key in completed
            or (legacy_job_key is not None and legacy_job_key in completed)
        ):
            cell["status"] = "completed"
        cell["regeneration"] = regeneration_identity(cell, 1)
        cells.append(cell)
    result = deepcopy(expanded)
    result["cells"] = cells
    result["completed"] = sum(
        item["status"] == "completed" for item in cells
    )
    result["pending"] = len(cells) - result["completed"]
    result["legacy_mode"] = rule["metadata"].get("legacy_mode")
    return result


def regeneration_identity_for_legacy_cell(
    cell: Mapping[str, Any],
    attempt: int = 1,
) -> dict:
    """기존 재개 키와 공통 셀 id를 함께 보존한 한 칸 재생성 식별자."""
    identity = regeneration_identity(cell, attempt)
    identity["legacy_resume_key"] = str(
        (cell or {}).get("legacy_resume_key") or ""
    )
    return identity
