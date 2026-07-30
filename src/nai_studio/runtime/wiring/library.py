# -*- coding: utf-8 -*-
"""자료 계열(자료팩·백업·로컬이미지·데이터 색인·메타 후보) Operations 조립.

`app`은 레거시 호환면의 globals()다. 이름을 호출 시점에 찾으므로 기존
monkeypatch(patch.object(APP, "이름", …))가 그대로 동작한다. 서비스 모듈
자체는 patch 대상이 아니므로 직접 import한다.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.nai_studio.services import data_inventory as _data_inventory
from src.nai_studio.services import datapack_store as _datapack_store
from src.nai_studio.services import local_image_store as _local_image_store
from src.nai_studio.services import (
    metadata_candidate_store as _metadata_candidate_store,
)
from src.nai_studio.services import user_backup_store as _user_backup_store


def datapack_paths(app: Mapping[str, Any]):
    """자료팩 서비스가 쓸 현재 프로필 경로를 호출 시점에 조립한다."""
    return _datapack_store.DatapackPaths(
        base_dir=app["BASE_DIR"],
        style_file=app["STYLE_FILE"],
        recipe_file=app["RECIPE_FILE"],
        combo_file=app["COMBO_FILE"],
        image_cache=app["IMG_CACHE"],
        tag_dir=app["TAG_DIR"],
        builder_file=app["BUILDER_FILE"],
        spec_file=app["SPEC_FILE"],
        options_file=app["OPTIONS_FILE"],
        settings_dir=app["SETTINGS_DIR"],
        character_dir=app["CHAR_DIR"],
    )


def datapack_operations(app: Mapping[str, Any]):
    """원자 저장과 캐릭터 동기화를 현재 전역 구현에 늦게 연결한다."""
    return _datapack_store.DatapackOperations(
        transaction=app["shared_data_transaction"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        atomic_write_json=app["atomic_write_json"],
        load_json=app["load_json_recover"],
        recoverable_remove=app["recoverable_remove"],
        row_digest=app["_style_row_digest"],
        character_signature=app["character_bundle_signature"],
        delete_character_files=app["delete_char_files"],
        sync_character_files=app["sync_chars_to_files"],
        save_config=app["save_config"],
        forget_caches=app["forget_collection_caches"],
        pack_queue=app["pack_import_queue"],
        summarize_queue=app["summarize_restore_queue"],
        warning=app["log"].warning,
    )


def local_image_paths(app: Mapping[str, Any]):
    return _local_image_store.LocalImagePaths(
        base_dir=app["BASE_DIR"],
        image_cache=app["IMG_CACHE"],
        image_suffixes=tuple(sorted(app["_LOCAL_IMAGE_SUFFIXES"])),
        record_dir_name="이미지무결성기록",
        journal_schema="nais-local-image-normalize/v1",
    )


def local_image_operations(app: Mapping[str, Any]):
    """현재 원자 저장·트랜잭션·시간 함수를 주입해 기존 patch 계약을 보존한다."""
    return _local_image_store.LocalImageOperations(
        transaction=app["shared_data_transaction"],
        lock=app["_LOCAL_IMAGE_LOCK"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        atomic_write_json=app["atomic_write_json"],
        forget_caches=app["forget_collection_caches"],
        now=app["datetime"].now,
        unix_time=app["time"].time,
        random_bytes=app["os"].urandom,
        replace_file=app["os"].replace,
    )


def data_inventory_paths(app: Mapping[str, Any]):
    return _data_inventory.DataInventoryPaths(
        base_dir=app["BASE_DIR"],
        program_dir=app["PROGRAM_DIR"],
        index_file=app["_data_index_path"](),
        schema=app["DATA_INDEX_SCHEMA"],
        profile=app["PROFILE"],
    )


def data_inventory_operations(app: Mapping[str, Any]):
    return _data_inventory.DataInventoryOperations(
        load_json=app["load_json_recover"],
        atomic_write_json=app["atomic_write_json"],
        now=app["datetime"].now,
        redact=app["redact_diagnostic_text"],
        folder_queue=app["folder_inventory_queue"],
        folder_summary=app["folder_inventory_summary"],
        summarize_queue=app["summarize_restore_queue"],
    )


def metadata_candidate_paths(app: Mapping[str, Any]):
    return _metadata_candidate_store.MetadataCandidatePaths(
        base_dir=app["BASE_DIR"],
    )


def metadata_candidate_operations(app: Mapping[str, Any]):
    """현재 감사 singleton과 복원·그림체 저장 경계를 호출 때 주입해 patch를 보존한다."""
    return _metadata_candidate_store.MetadataCandidateOperations(
        adapter_for_paths=lambda _paths: app["metadata_audit_adapter"](),
        extract_nai_metadata=app["extract_nai_metadata"],
        nai_json_metadata=app["_nai_json_metadata"],
        prompt_parts=app["_prompt_parts"],
        param_keys=tuple(app["PARAM_KEYS"]),
        image_inspect_queue=app["image_inspect_queue"],
        redact_diagnostic_text=app["redact_diagnostic_text"],
        parse_artist_combo=app["parse_artist_combo"],
        style_asset_from_record=app["style_asset_from_record"],
        add_style=app["add_style"],
    )


def user_backup_paths(app: Mapping[str, Any]):
    return _user_backup_store.UserBackupPaths(
        base_dir=app["BASE_DIR"],
        profile_dir=app["PROFILE_DIR"],
        sources=_user_backup_store.UserBackupSourcePaths(
            settings_file=app["SETTINGS_FILE"],
            builder_file=app["BUILDER_FILE"],
            spec_file=app["SPEC_FILE"],
            options_file=app["OPTIONS_FILE"],
            tag_dir=app["TAG_DIR"],
            settings_dir=app["SETTINGS_DIR"],
            schema_dir=app["SCHEMA_DIR"],
            sceneset_dir=app["SCENESET_DIR"],
            style_dir=app["STYLE_DIR"],
            character_dir=app["CHAR_DIR"],
            fragment_dir=app["FRAG_DIR"],
            vibe_dir=app["VIBE_DIR"],
            picks_file=app["PICKS_FILE"],
            scenes_file=app["SCENES_FILE"],
        ),
        profile_name=app["PROFILE"],
        schema=app["BACKUP_SCHEMA"],
        journal_schema="nais-restore-journal/v1",
        journal_dir_name="복원기록",
    )


def user_backup_operations(app: Mapping[str, Any]):
    """현재 복원·원자 저장 경계를 호출 때 주입해 기존 patch와 롤백 순서를 보존한다."""
    return _user_backup_store.UserBackupOperations(
        transaction=app["shared_data_transaction"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        atomic_write_json=app["atomic_write_json"],
        load_settings=app["load_settings_recover"],
        rollback=app["rollback_user_backup"],
        after_restore=app["forget_collection_caches"],
        now=app["datetime"].now,
        random_bytes=app["os"].urandom,
        warning=app["log"].warning,
        recoverable_remove=app["recoverable_remove"],
        **app["_studio_wiring"].user_backup_baseline_fields(
            app["PROFILE_DIR"]),
    )


__all__ = [
    "data_inventory_operations",
    "data_inventory_paths",
    "datapack_operations",
    "datapack_paths",
    "local_image_operations",
    "local_image_paths",
    "metadata_candidate_operations",
    "metadata_candidate_paths",
    "user_backup_operations",
    "user_backup_paths",
]
