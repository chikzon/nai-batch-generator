# -*- coding: utf-8 -*-
"""HTTP 라우트가 사용할 기능별 작업 묶음을 주입값으로 조립한다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from src.nai_studio.web.routes.assets import AssetGetOperations
from src.nai_studio.web.routes.catalog import CatalogGetOperations
from src.nai_studio.web.routes.catalog_post import CatalogPostOperations
from src.nai_studio.web.routes.collection_post import CollectionPostOperations
from src.nai_studio.web.routes.evaluation_post import EvaluationPostOperations
from src.nai_studio.web.routes.fragments_post import FragmentPostOperations
from src.nai_studio.web.routes.generation import GenerationGetOperations
from src.nai_studio.web.routes.generation_post import GenerationPostOperations
from src.nai_studio.web.routes.recovery import RecoveryGetOperations
from src.nai_studio.web.routes.recovery_post import RecoveryPostOperations
from src.nai_studio.web.routes.runtime_post import RuntimePostOperations
from src.nai_studio.web.routes.settings_post import SettingsPostOperations


_OPERATION_TYPES = {
    "catalog_get": CatalogGetOperations,
    "generation_get": GenerationGetOperations,
    "asset_get": AssetGetOperations,
    "recovery_get": RecoveryGetOperations,
    "recovery_post": RecoveryPostOperations,
    "collection_post": CollectionPostOperations,
    "catalog_post": CatalogPostOperations,
    "evaluation_post": EvaluationPostOperations,
    "fragment_post": FragmentPostOperations,
    "settings_post": SettingsPostOperations,
    "generation_post": GenerationPostOperations,
    "runtime_post": RuntimePostOperations,
}

# 서버 인스턴스의 상태나 잠금에 직접 연결되는 작업만 여기서 결합한다.
# 나머지 작업은 호출자가 late-bound callable로 넣어 전역 monkeypatch 의미를 보존한다.
_SERVER_MEMBERS = {
    "collection_post": {
        "resource_import": "handle_resource_import",
        "reference_add": "handle_ref_add",
        "reference_save": "handle_ref_save",
    },
    "catalog_post": {
        "style_save": "handle_style_save",
        "normalization_save": "handle_norm_save",
    },
    "generation_post": {
        "compare_rerun": "handle_compare_rerun",
        "compare_promote": "handle_compare_promote",
        "compare_preview": "handle_compare_preview",
        "compare_run": "handle_compare_run",
        "start": "handle_start",
        "generate_one": "handle_generate_one",
        "request_stop": "live.request_stop",
        "job_command": "handle_job_command",
        "image_to_image": "handle_i2i",
        "variation_save": "handle_character_variation_save",
        "regenerate": "handle_regen",
        "scene_run": "handle_scene_run",
        "director": "handle_director",
        "inspect_image": "handle_inspect",
    },
    "settings_post": {
        "scene_save": "handle_scene_save",
        "option_item": "handle_option_item",
        "role_save": "handle_role_save",
        "sceneset_save": "handle_sceneset_save",
    },
    "runtime_post": {
        "blueprint_project": "handle_blueprint_project",
        "save_config": "handle_save",
    },
}


def _member(root: Any, path: str) -> Any:
    value = root
    for name in path.split("."):
        value = getattr(value, name)
    return value


def _build_operation(
    group: str,
    operation_type: type,
    bindings: Mapping[str, Any],
    server: Any,
) -> Any:
    server_members = _SERVER_MEMBERS.get(group, {})
    values = {}
    for field in fields(operation_type):
        if field.name in server_members:
            values[field.name] = _member(server, server_members[field.name])
            continue
        try:
            values[field.name] = bindings[field.name]
        except KeyError as exc:
            raise KeyError(
                f"missing route binding: {group}.{field.name}"
            ) from exc
    return operation_type(**values)


def build_route_operation_sets(
    bindings: Mapping[str, Any],
    server: Any,
) -> dict[str, Any]:
    """기존 Operations dataclass 12개를 라우트 기능군 이름으로 반환한다."""
    return {
        group: _build_operation(group, operation_type, bindings, server)
        for group, operation_type in _OPERATION_TYPES.items()
    }


__all__ = ["build_route_operation_sets"]
