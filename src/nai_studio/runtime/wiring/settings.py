# -*- coding: utf-8 -*-
"""세팅 계열(세팅 저장·씬·캐스트·프로젝트·캐릭터 파일) Operations 조립.

`app`은 레거시 호환면의 globals()다 — 호출 시점 조회로 monkeypatch 계약을
보존한다. 조립만 있고 기능 알고리즘은 없다.
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any, Mapping

from src.nai_studio.services import character_storage as _character_storage
from src.nai_studio.services import setting_runtime as _setting_runtime
from src.nai_studio.services import setting_store as _setting_store
from src.nai_studio.services import settings_handlers as _settings_handlers


def setting_store_paths(app: Mapping[str, Any]):
    """세팅 서비스가 현재 프로필 경로를 호출 시점에 읽게 한다."""
    return _setting_store.SettingStorePaths(
        settings_dir=app["SETTINGS_DIR"],
        schema_dir=app["SCHEMA_DIR"],
        preset_dir=app["SCENESET_DIR"],
    )


def setting_store_operations(app: Mapping[str, Any]):
    """원자 저장·잠금·컴파일 규칙을 세팅 저장소에 연결한다."""
    return _setting_store.SettingStoreOperations(
        transaction=app["_setting_transaction"],
        load_json=app["load_json_recover"],
        atomic_write_json=app["atomic_write_json"],
        recoverable_remove=app["recoverable_remove"],
        safe_name=app["_safe_name"],
        derive_catalog=app["derive_setting_catalog"],
        axis_specs=app["axis_specs"],
        ensure_schema_split=app["ensure_schema_split"],
        warning=app["log"].warning,
        info=app["log"].info,
    )


def setting_transaction(app: Mapping[str, Any]):
    """기존 세팅 파일의 프로세스·스레드 잠금을 같은 순서로 묶는다."""
    stack = ExitStack()
    stack.enter_context(
        app["shared_data_transaction"](app["SETTINGS_DIR"].parent)
    )
    stack.enter_context(app["_SETTING_TX_LOCK"])
    return stack


def settings_handler_operations(app: Mapping[str, Any]):
    """프로젝트·설정·씬 저장 의존성을 호출 시점에 연결한다."""
    return _settings_handlers.SettingsHandlerOperations(
        config_transaction=lambda: app["shared_data_transaction"](
            app["CHAR_DIR"].parent
        ),
        setting_transaction=app["_setting_transaction"],
        default_config=app["DEFAULT_CONFIG"],
        normalize_projects=app["normalize_projects"],
        normalize_link=app["normalize_link"],
        project_by_id=app["project_by_id"],
        generation_blueprint=app["generation_blueprint"],
        blueprint_common=app["blueprint_common"],
        fingerprint_blueprint=app["fingerprint_blueprint"],
        resolve_inheritance=app["resolve_inheritance"],
        materialize_blueprint=app["materialize_blueprint_into_config"],
        save_config=app["save_config"],
        validate_config_value=app["validate_config_value"],
        sync_chars_to_files=app["sync_chars_to_files"],
        sync_blueprint_overrides=app["sync_blueprint_local_overrides"],
        delete_char_files=app["delete_char_files"],
        setting_path=app["setting_path"],
        load_json=app["load_json_recover"],
        setting_revision=app["setting_content_revision"],
        normalize_resolution=app["normalize_resolution"],
        normalize_centers=app["normalize_scene_centers"],
        normalize_reference_ids=app["normalize_scene_reference_ids"],
        atomic_write_json=app["atomic_write_json"],
        warning=app["log"].warning,
        info=app["log"].info,
    )


def setting_runtime_operations(app: Mapping[str, Any]):
    """현재 세팅·캐릭터·이름 경계를 호출 때 주입해 APP patch를 보존한다."""
    return _setting_runtime.SettingRuntimeOperations(
        comparison_characters=app["comparison_characters"],
        derive_catalog=app["derive_setting_catalog"],
        safe_name=app["_safe_name"],
        setting_state=app["setting_state"],
    )


def character_storage_paths(app: Mapping[str, Any]):
    return _character_storage.CharacterStoragePaths(
        legacy_settings_file=app["LEGACY_SETTINGS_FILE"],
        settings_file=app["SETTINGS_FILE"],
        character_dir=app["CHAR_DIR"],
    )


def character_storage_operations(app: Mapping[str, Any]):
    """현재 파일·복구·ID 경계를 호출 때 주입해 기존 patch와 저장 순서를 보존한다."""
    return _character_storage.CharacterStorageOperations(
        read_legacy_settings=app["_read_legacy_txt"],
        setting_path=app["setting_path"],
        load_json=app["load_json_recover"],
        atomic_write_json=app["atomic_write_json"],
        recoverable_remove=app["recoverable_remove"],
        random_id=app["_character_random_id"],
        log_info=app["log"].info,
        log_warning=app["log"].warning,
    )


__all__ = [
    "character_storage_operations",
    "character_storage_paths",
    "setting_runtime_operations",
    "setting_store_operations",
    "setting_store_paths",
    "setting_transaction",
    "settings_handler_operations",
]
