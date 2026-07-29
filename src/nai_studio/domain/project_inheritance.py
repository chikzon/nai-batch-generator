# -*- coding: utf-8 -*-
"""프로젝트 공통 설계도를 현재 생성 흐름에 안전하게 연결하는 순수 계약.

프로젝트 원본을 실행 때마다 따라가지 않는다. 사용자가 승인한 설계도 사본을
고정하고, 세팅·실험과 승인 뒤 바꾼 현재 값만 우선순위 레이어로 합친다.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .blueprint import (
    canonical_generation_plan,
    fingerprint_blueprint,
    resolve_blueprint_layers,
    summarize_blueprint,
)


INHERITANCE_SCHEMA = "nai-blueprint-inheritance/v1"
_COMPUTED_KEYS = {"fingerprint", "summary", "provenance"}
_CHILD_KEYS = {"setting", "experiment"}


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def blueprint_common(value: Mapping[str, Any] | None) -> dict:
    """프로젝트에서 공유할 실행 공통값만 돌려준다."""
    plan = canonical_generation_plan(value)
    for key in ("schema", "source", *_CHILD_KEYS, *_COMPUTED_KEYS):
        plan.pop(key, None)
    return plan


def blueprint_child(value: Mapping[str, Any] | None) -> dict:
    """세팅·실험은 프로젝트 공통값보다 높은 별도 레이어다."""
    plan = canonical_generation_plan(value)
    return {
        key: deepcopy(plan.get(key))
        for key in _CHILD_KEYS
        if key in plan
    }


def _diff_mapping(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict:
    """현재에 실제로 존재하며 부모와 다른 값만 partial blueprint로 만든다.

    배열과 빈 값은 의도 있는 원자값이다. 부모에만 있고 현재 화면이 모르는 미래
    필드는 지우지 않고 상속한다.
    """
    result = {}
    for key, value in current.items():
        if key in _COMPUTED_KEYS or key in ("schema", "source"):
            continue
        old = baseline.get(key, object())
        if isinstance(value, Mapping) and isinstance(old, Mapping):
            nested = _diff_mapping(value, old)
            if nested:
                result[str(key)] = nested
        elif value != old:
            result[str(key)] = deepcopy(value)
    return result


def local_overrides(
    current: Mapping[str, Any] | None,
    accepted_parent: Mapping[str, Any] | None,
) -> dict:
    """승인된 부모 뒤 사용자가 바꾼 현재 공통값만 추린다."""
    return _diff_mapping(
        blueprint_common(current),
        blueprint_common(accepted_parent),
    )


def normalize_projects(value: Any) -> list[dict]:
    """저장 가능한 프로젝트 목록을 작고 결정적인 구조로 정리한다."""
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("프로젝트는 최대 100개까지 저장할 수 있습니다.")
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("프로젝트 항목 형식이 올바르지 않습니다.")
        project_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if (
            not project_id
            or len(project_id) > 120
            or not name
            or len(name) > 120
            or project_id in seen
        ):
            raise ValueError("프로젝트 id 또는 이름이 올바르지 않습니다.")
        common = blueprint_common(_mapping(raw.get("blueprint")))
        result.append({
            "id": project_id,
            "name": name,
            "blueprint": common,
            "fingerprint": fingerprint_blueprint(common),
            "updated_at": str(raw.get("updated_at") or ""),
        })
        seen.add(project_id)
    return result


def normalize_link(value: Any) -> dict:
    if not value:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("프로젝트 연결 형식이 올바르지 않습니다.")
    project_id = str(value.get("project_id") or "").strip()
    if not project_id:
        return {}
    accepted = blueprint_common(_mapping(value.get("accepted_blueprint")))
    accepted_fingerprint = str(
        value.get("accepted_fingerprint") or fingerprint_blueprint(accepted)
    )
    overrides = _mapping(value.get("local_overrides"))
    return {
        "schema": INHERITANCE_SCHEMA,
        "project_id": project_id,
        "accepted_fingerprint": accepted_fingerprint,
        "accepted_blueprint": accepted,
        "local_overrides": overrides,
    }


def project_by_id(
    projects: Sequence[Mapping[str, Any]] | None,
    project_id: str,
) -> dict | None:
    return next(
        (
            deepcopy(dict(item))
            for item in (projects or ())
            if isinstance(item, Mapping)
            and str(item.get("id") or "") == str(project_id or "")
        ),
        None,
    )


def resolve_inheritance(
    current_blueprint: Mapping[str, Any],
    projects: Sequence[Mapping[str, Any]] | None,
    link: Mapping[str, Any] | None,
    *,
    runtime: Mapping[str, Any] | None = None,
) -> dict:
    """프로젝트 10 → 세팅·실험 20 → 현재 변경 30 → 실행값 40."""
    current = canonical_generation_plan(current_blueprint)
    normalized_link = normalize_link(link)
    if not normalized_link:
        return {
            "blueprint": deepcopy(current_blueprint),
            "provenance": {},
            "conflicts": [],
            "fingerprint": str(
                current_blueprint.get("fingerprint")
                or fingerprint_blueprint(current)
            ),
            "project": {
                "active": False,
                "parent_changed": False,
                "inherited_paths": 0,
                "override_paths": 0,
            },
        }

    project = project_by_id(projects, normalized_link["project_id"])
    accepted = normalized_link["accepted_blueprint"]
    current_project_fingerprint = str(
        (project or {}).get("fingerprint") or ""
    )
    parent_changed = bool(
        project
        and current_project_fingerprint
        != normalized_link["accepted_fingerprint"]
    )
    layers = [
        {
            "source": {
                "kind": "project",
                "id": normalized_link["project_id"],
                "name": str((project or {}).get("name") or ""),
                "accepted_fingerprint": normalized_link["accepted_fingerprint"],
            },
            "priority": 10,
            "blueprint": accepted,
        },
        {
            "source": {"kind": "setting-experiment"},
            "priority": 20,
            "blueprint": blueprint_child(current),
        },
        {
            "source": {"kind": "current-overrides"},
            "priority": 30,
            "blueprint": normalized_link["local_overrides"],
        },
    ]
    if runtime:
        layers.append({
            "source": {"kind": "runtime"},
            "priority": 40,
            "blueprint": _mapping(runtime),
        })
    result = resolve_blueprint_layers(layers)
    result["blueprint"]["source"] = {
        "kind": "project-inheritance",
        "project_id": normalized_link["project_id"],
        "accepted_fingerprint": normalized_link["accepted_fingerprint"],
        "operation": deepcopy(current.get("source") or {}),
    }
    result["blueprint"]["fingerprint"] = fingerprint_blueprint(
        result["blueprint"])
    result["blueprint"]["summary"] = summarize_blueprint(result["blueprint"])
    result["fingerprint"] = result["blueprint"]["fingerprint"]
    result["project"] = {
        "active": True,
        "id": normalized_link["project_id"],
        "name": str((project or {}).get("name") or ""),
        "missing": project is None,
        "parent_changed": parent_changed,
        "accepted_fingerprint": normalized_link["accepted_fingerprint"],
        "current_fingerprint": current_project_fingerprint,
        "inherited_paths": sum(
            1 for item in result["provenance"].values()
            if (item.get("source") or {}).get("kind") == "project"
        ),
        "override_paths": sum(
            1 for item in result["provenance"].values()
            if (item.get("source") or {}).get("kind")
            in ("current-overrides", "setting-experiment", "runtime")
        ),
    }
    return result
