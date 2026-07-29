# -*- coding: utf-8 -*-
"""Canonical experiment cells projected into pure legacy execution material.

This module does not call NAI and does not mutate the live configuration.  It
only prepares the values that the comparison/settings executors already know
how to consume.  Runtime credentials deliberately remain outside this
boundary.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .experiment_bridge import regeneration_identity_for_legacy_cell


_SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "api_token",
    "authorization",
    "nai_token",
    "persistent_token",
    "secret",
    "token",
}
_STYLE_PARAMETER_MAP = {
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
    "model": "model",
    "width": "width",
    "height": "height",
}


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _is_secret_key(value: Any) -> bool:
    key = str(value).casefold()
    return key in _SECRET_KEYS or key.endswith("_token")


def _without_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_secrets(item)
            for key, item in value.items()
            if not _is_secret_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_without_secrets(item) for item in value]
    return deepcopy(value)


def _source_name(value: Any, fallback: str) -> str:
    if isinstance(value, Mapping):
        for key in ("_compare_name", "name", "title", "id", "_compare_id"):
            if value.get(key) not in (None, ""):
                return str(value.get(key))
    return fallback


def _character_prompt(value: Mapping[str, Any]) -> str:
    for key in ("female", "appearance", "prompt"):
        if value.get(key) is not None:
            return str(value.get(key))
    return ""


def _character_outfit(value: Mapping[str, Any]) -> str:
    for key in ("clothed", "outfit"):
        if value.get(key) is not None:
            return str(value.get(key))
    return ""


def _character_slot(value: Mapping[str, Any]) -> tuple[dict, dict]:
    safe = _mapping(_without_secrets(value))
    slot = {
        "id": safe.get("id") or safe.get("_compare_id"),
        "name": _source_name(safe, "character"),
        "prompt": _character_prompt(safe),
        "outfit": _character_outfit(safe),
        "negative": str(safe.get("negative") or ""),
        "enabled": safe.get("enabled") is not False,
    }
    for key in (
        "variants", "variant", "references", "character_references", "vibes",
        "source", "evidence_ids",
    ):
        if key in safe:
            slot[key] = deepcopy(safe[key])
    position = safe.get("position")
    center = (
        _mapping(position)
        if isinstance(position, Mapping)
        else {"x": 0.5, "y": 0.5}
    )
    return slot, center


def _current_slots(cfg: Mapping[str, Any]) -> tuple[list, list]:
    slots, centers = [], []
    raw_centers = _list(cfg.get("char_centers"))
    for index, raw in enumerate(_list(cfg.get("char_slots"))):
        if not isinstance(raw, Mapping) or raw.get("enabled") is False:
            continue
        safe = _mapping(_without_secrets(raw))
        slots.append(safe)
        center = raw_centers[index] if index < len(raw_centers) else None
        centers.append(
            _mapping(_without_secrets(center))
            if isinstance(center, Mapping)
            else {"x": 0.5, "y": 0.5}
        )
    return slots, centers


def _style_overrides(
    cfg: Mapping[str, Any],
    style: Mapping[str, Any] | None,
) -> dict:
    if not isinstance(style, Mapping):
        return {
            "base_prompt": str(cfg.get("base_prompt") or ""),
            "negative_prompt": str(cfg.get("negative_prompt") or ""),
            "style_name": str(cfg.get("style_name") or ""),
        }
    safe = _mapping(_without_secrets(style))
    result = {
        "base_prompt": str(
            safe.get("base")
            if safe.get("base") is not None
            else safe.get("combo")
            if safe.get("combo") is not None
            else cfg.get("base_prompt") or ""
        ),
        "negative_prompt": str(
            safe.get("negative")
            if safe.get("negative") is not None
            else cfg.get("negative_prompt") or ""
        ),
        "style_name": _source_name(safe, str(cfg.get("style_name") or "")),
    }
    params = _mapping(safe.get("params"))
    for source, target in _STYLE_PARAMETER_MAP.items():
        if params.get(source) is not None:
            result[target] = deepcopy(params[source])
    return result


def _path_is_safe(path: str) -> bool:
    return all(not _is_secret_key(part) for part in path.split(".") if part)


def _assign_path(target: dict, path: str, value: Any) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts or not _path_is_safe(path):
        return
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = _without_secrets(value)


def _apply_generation_path(
    config_overrides: dict,
    payload_overrides: dict,
    path: str,
    value: Any,
) -> None:
    if not _path_is_safe(path):
        return
    if path.startswith("payload."):
        _assign_path(payload_overrides, path[len("payload."):], value)
        return
    if not path.startswith("generation."):
        return
    relative = path[len("generation."):]
    if relative.startswith("resolution."):
        relative = relative[len("resolution."):]
    if relative.startswith("settings."):
        relative = relative[len("settings."):]
    if relative and "." not in relative:
        config_overrides[relative] = _without_secrets(value)
    else:
        _assign_path(payload_overrides, relative, value)


def _selected_setting(value: Any) -> dict:
    if not isinstance(value, Mapping):
        return {}
    safe = _mapping(_without_secrets(value))
    # The state key is an identity, not a display label.  Existing setting
    # records commonly use the same value for both, while imported records may
    # rename their label without changing the stable id.
    name = str(
        safe.get("id")
        or safe.get("_compare_id")
        or safe.get("name")
        or safe.get("_compare_name")
        or "setting"
    )
    state = safe.get("state")
    if isinstance(state, Mapping):
        selected = _mapping(state)
    else:
        selected = {
            key: deepcopy(item)
            for key, item in safe.items()
            if key not in ("id", "name", "_compare_id", "_compare_name")
        }
    selected["use"] = selected.get("use") is not False
    return {name if name else "setting": selected}


def _resolve_seed(
    cell: Mapping[str, Any],
    runtime_base_seed: int | None,
) -> int | None:
    material = _mapping(cell.get("seed_material"))
    resolved = material.get("resolved_seed")
    if resolved not in (None, ""):
        return int(resolved)
    if runtime_base_seed in (None, ""):
        return None
    seed = (int(runtime_base_seed) + int(material.get("offset") or 0)) & 0xffffffff
    return seed or 1


def legacy_execution_material(
    cell: Mapping[str, Any],
    cfg: Mapping[str, Any],
    *,
    runtime_base_seed: int | None = None,
    attempt: int = 1,
) -> dict:
    """Return immutable, secret-free input for one legacy execution cell."""
    raw_cell = _mapping(cell)
    safe_cfg = _mapping(_without_secrets(cfg))
    legacy = _mapping(raw_cell.get("legacy_material"))
    assignments = _mapping(raw_cell.get("assignments"))
    style = legacy.get("style")
    character = legacy.get("character")
    setting = legacy.get("setting")

    config_overrides = _style_overrides(
        safe_cfg, style if isinstance(style, Mapping) else None
    )
    payload_overrides: dict = {}
    selected_axes = _mapping(legacy.get("selected_axes"))
    for path, value in selected_axes.items():
        _apply_generation_path(
            config_overrides, payload_overrides, str(path), value
        )

    experiment = _mapping(_mapping(raw_cell.get("blueprint")).get("experiment"))
    for path, value in _mapping(experiment.get("fixed")).items():
        _apply_generation_path(
            config_overrides, payload_overrides, str(path), value
        )

    if isinstance(character, Mapping):
        slot, center = _character_slot(character)
        char_slots, char_centers = [slot], [center]
    else:
        char_slots, char_centers = _current_slots(safe_cfg)

    seed_material = _mapping(raw_cell.get("seed_material"))
    seed_index = int(seed_material.get("seed_index") or 0)
    resume_key = str(
        raw_cell.get("legacy_resume_key")
        or raw_cell.get("legacy_job_key")
        or raw_cell.get("id")
        or ""
    )
    retry = regeneration_identity_for_legacy_cell(raw_cell, attempt)
    legacy_mode = str(
        _mapping(_mapping(raw_cell.get("blueprint")).get("experiment")).get(
            "mode"
        )
        or ""
    )
    job_key = str(raw_cell.get("legacy_job_key") or resume_key)
    job = {
        "key": job_key,
        "style": _without_secrets(style),
        "character": _without_secrets(character),
        "setting": _without_secrets(setting),
        "style_name": _source_name(style, "current style"),
        "char_name": _source_name(character, "current characters"),
        "setting_name": _source_name(setting, ""),
        "seed_index": seed_index,
        "mode": legacy_mode,
    }
    return {
        "cell_id": str(raw_cell.get("id") or ""),
        "resume_key": resume_key,
        "legacy_job_key": (
            str(raw_cell.get("legacy_job_key"))
            if raw_cell.get("legacy_job_key") is not None else None
        ),
        "request_id": retry["request_id"],
        "attempt": max(1, int(attempt)),
        "job": job,
        "config_overrides": _without_secrets(config_overrides),
        "payload_overrides": _without_secrets(payload_overrides),
        "char_slots": _without_secrets(char_slots),
        "char_centers": _without_secrets(char_centers),
        "setting_state": _selected_setting(setting),
        "selected_axes": _without_secrets(selected_axes),
        "seed": _resolve_seed(raw_cell, runtime_base_seed),
        "seed_material": _without_secrets(seed_material),
        "include_references": bool(legacy.get("include_references")),
    }


def regenerate_legacy_execution_material(
    cell: Mapping[str, Any],
    cfg: Mapping[str, Any],
    *,
    attempt: int = 1,
    runtime_base_seed: int | None = None,
) -> dict:
    """Rebuild one cell with the same content identity and a new request id."""
    result = legacy_execution_material(
        cell,
        cfg,
        runtime_base_seed=runtime_base_seed,
        attempt=attempt,
    )
    result["rerun_of"] = result["resume_key"]
    return result


def legacy_execution_queue(
    expanded: Mapping[str, Any],
    cfg: Mapping[str, Any],
    *,
    completed_keys: Sequence[str] | None = None,
    rerun_keys: Sequence[str] | None = None,
    runtime_base_seed: int | None = None,
) -> dict:
    """Materialize pending cells while honoring old and canonical resume keys."""
    completed = {str(item) for item in (completed_keys or ())}
    reruns = {str(item) for item in (rerun_keys or ())}
    items, skipped = [], 0
    for raw in _list((expanded or {}).get("cells")):
        if not isinstance(raw, Mapping):
            continue
        identities = {
            str(raw.get("id") or ""),
            str(raw.get("legacy_resume_key") or ""),
            str(raw.get("legacy_job_key") or ""),
        }
        force = bool(identities & reruns)
        already_done = (
            str(raw.get("status") or "") == "completed"
            or bool(identities & completed)
        )
        if already_done and not force:
            skipped += 1
            continue
        items.append(
            regenerate_legacy_execution_material(
                raw,
                cfg,
                attempt=2 if force else 1,
                runtime_base_seed=runtime_base_seed,
            )
            if force
            else legacy_execution_material(
                raw, cfg, runtime_base_seed=runtime_base_seed
            )
        )
    return {
        "experiment_id": str((expanded or {}).get("id") or ""),
        "total_cells": len(_list((expanded or {}).get("cells"))),
        "items": items,
        "pending": len(items),
        "skipped_completed": skipped,
    }
