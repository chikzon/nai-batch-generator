# -*- coding: utf-8 -*-
"""생성 설계도에 붙는 결정적 실험 규칙.

전수 비교·교차 비교·다중 시드·파라미터 비교를 별도 저장 기능으로 만들지 않고
같은 설계도를 여러 실행 셀로 확장한다.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .blueprint import canonical_generation_plan, fingerprint_blueprint


EXPERIMENT_SCHEMA = "nai-experiment-rule/v1"


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _stable_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _digest(kind: str, value: Any) -> str:
    return f"{kind}-{hashlib.sha256(_stable_json(value)).hexdigest()[:24]}"


def _value_identity(value: Any) -> str:
    if isinstance(value, Mapping):
        known = value.get("id") or value.get("_compare_id") or value.get("name")
        if known not in (None, ""):
            return str(known)
    return hashlib.sha256(_stable_json(value)).hexdigest()


def _dedupe(values: Sequence[Any]) -> list:
    output, seen = [], set()
    for value in values:
        identity = _value_identity(value)
        if identity in seen:
            continue
        seen.add(identity)
        output.append(deepcopy(value))
    return output


def canonical_experiment_rule(
    value: Mapping[str, Any] | None,
    *,
    catalogs: Mapping[str, Any] | None = None,
) -> dict:
    """축약 모드와 명시 축을 하나의 실험 규칙으로 정리한다."""
    raw = _mapping(value)
    catalogs = _mapping(catalogs)
    mode = str(raw.get("mode") or "single")
    aliases = {
        "both": "style_character_cross",
        "cross": "style_character_cross",
        "styles": "all_styles",
        "characters": "all_characters",
        "character×setting": "character_setting_cross",
    }
    mode = aliases.get(mode, mode)

    axes = []
    for axis in _list(raw.get("axes")):
        if not isinstance(axis, Mapping):
            continue
        name = str(axis.get("name") or axis.get("path") or "").strip()
        if not name:
            continue
        values = _dedupe(_list(axis.get("values")))
        axes.append({
            **deepcopy(dict(axis)),
            "name": name,
            "values": values,
        })

    names = {axis["name"] for axis in axes}

    def add_axis(name: str, sources: Sequence[str]) -> None:
        if name in names:
            return
        values = []
        for source in sources:
            if raw.get(source) is not None:
                values = _list(raw.get(source))
                break
            if catalogs.get(source) is not None:
                values = _list(catalogs.get(source))
                break
        axes.append({"name": name, "values": _dedupe(values)})
        names.add(name)

    if mode in ("all_styles", "style_character_cross"):
        add_axis("style", ("styles",))
    if mode in (
        "all_characters", "style_character_cross", "character_setting_cross",
    ):
        add_axis("character", ("characters",))
    if mode == "character_setting_cross":
        add_axis("setting", ("settings",))
    if mode == "selected_groups":
        groups = raw.get("selected_groups") or catalogs.get("selected_groups") or {}
        if isinstance(groups, Mapping):
            for name in sorted(groups):
                axis_name = str(name)
                if axis_name in names:
                    # 명시 axes가 축약 selected_groups보다 구체적이므로 유지한다.
                    continue
                axes.append({
                    "name": axis_name,
                    "values": _dedupe(_list(groups.get(name))),
                })
                names.add(axis_name)

    seeds = _list(raw.get("seeds"))
    if not seeds and raw.get("seed_count") not in (None, ""):
        try:
            count = max(1, int(raw.get("seed_count")))
        except (TypeError, ValueError, OverflowError):
            count = 1
        try:
            start = int(raw.get("seed") or 0)
        except (TypeError, ValueError, OverflowError):
            start = 0
        seeds = [start + index for index in range(count)]
    if seeds and "generation.seed" not in names:
        axes.append({"name": "generation.seed", "values": _dedupe(seeds)})

    try:
        limit = max(0, int(raw.get("limit") or 0))
    except (TypeError, ValueError, OverflowError):
        limit = 0
    return {
        "schema": EXPERIMENT_SCHEMA,
        "mode": mode,
        "fixed": _mapping(raw.get("fixed")),
        "axes": axes,
        "order": str(raw.get("order") or "product"),
        "limit": limit,
        "metadata": _mapping(raw.get("metadata")),
    }


def _set_path(target: dict, path: str, value: Any) -> None:
    if path == "style":
        target["style"] = deepcopy(value)
        return
    if path in ("character", "characters"):
        target["characters"] = (
            deepcopy(value) if isinstance(value, list) else [deepcopy(value)]
        )
        return
    if path == "setting":
        target["setting"] = deepcopy(value)
        return
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = deepcopy(value)


def cell_identity(
    blueprint: Mapping[str, Any],
    assignments: Mapping[str, Any],
) -> str:
    """목록 순서·진행 상태와 무관한 셀 식별자."""
    return _digest("cell", {
        "blueprint": fingerprint_blueprint(blueprint),
        "assignments": _mapping(assignments),
    })


def expand_experiment(
    blueprint: Mapping[str, Any],
    rule: Mapping[str, Any] | None,
    *,
    catalogs: Mapping[str, Any] | None = None,
    completed_ids: Sequence[str] | None = None,
) -> dict:
    """실험 규칙을 재현 가능한 실행 셀 목록으로 확장한다."""
    base = canonical_generation_plan(blueprint)
    spec = canonical_experiment_rule(rule, catalogs=catalogs)
    completed = {str(item) for item in (completed_ids or ())}
    fixed = spec["fixed"]
    axes = spec["axes"]
    values = [axis["values"] for axis in axes]
    combinations = itertools.product(*values) if values else [()]
    cells = []
    for combination in combinations:
        assignments = {
            axis["name"]: deepcopy(item)
            for axis, item in zip(axes, combination)
        }
        plan = deepcopy(base)
        for path, item in sorted(fixed.items()):
            _set_path(plan, str(path), item)
        for path, item in assignments.items():
            _set_path(plan, path, item)
        plan["experiment"] = {
            **deepcopy(plan.get("experiment") or {}),
            "schema": EXPERIMENT_SCHEMA,
            "mode": spec["mode"],
            "fixed": deepcopy(fixed),
            "selection": deepcopy(assignments),
        }
        plan = canonical_generation_plan(plan)
        identity_base = deepcopy(base)
        for path, item in sorted(fixed.items()):
            _set_path(identity_base, str(path), item)
        identity = cell_identity(identity_base, assignments)
        cells.append({
            "id": identity,
            "fingerprint": fingerprint_blueprint(plan),
            "assignments": assignments,
            "blueprint": plan,
            "status": "completed" if identity in completed else "pending",
        })
        if spec["limit"] and len(cells) >= spec["limit"]:
            break

    plan_identity = _digest("experiment", {
        "blueprint": fingerprint_blueprint(base),
        "rule": spec,
    })
    return {
        "id": plan_identity,
        "schema": EXPERIMENT_SCHEMA,
        "rule": spec,
        "total": len(cells),
        "pending": sum(cell["status"] != "completed" for cell in cells),
        "completed": sum(cell["status"] == "completed" for cell in cells),
        "cells": cells,
    }


def regeneration_identity(cell: Mapping[str, Any], attempt: int = 1) -> dict:
    """한 칸 재생성 요청을 원래 셀과 연결하되 시도별 id를 만든다."""
    cell_id = str((cell or {}).get("id") or "")
    attempt = max(1, int(attempt))
    return {
        "cell_id": cell_id,
        "attempt": attempt,
        "request_id": _digest("retry", {
            "cell_id": cell_id,
            "attempt": attempt,
        }),
    }
