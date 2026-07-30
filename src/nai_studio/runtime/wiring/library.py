# -*- coding: utf-8 -*-
"""자료 계열(자료팩·백업·로컬이미지·데이터 색인·메타 후보) Operations 조립.

`app`은 레거시 호환면의 globals()다. 이름을 호출 시점에 찾으므로 기존
monkeypatch(patch.object(APP, "이름", …))가 그대로 동작한다. 서비스 모듈
자체는 patch 대상이 아니므로 직접 import한다.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.nai_studio.services import artist_rating_store as _artist_rating_store
from src.nai_studio.services import artist_workspace as _artist_workspace
from src.nai_studio.services import builder_handlers as _builder_handlers
from src.nai_studio.services import catalog_search as _catalog_search
from src.nai_studio.services import data_inventory as _data_inventory
from src.nai_studio.services import datapack_store as _datapack_store
from src.nai_studio.services import fragment_workflow as _fragment_workflow
from src.nai_studio.services import library_catalog as _library_catalog
from src.nai_studio.services import local_image_store as _local_image_store
from src.nai_studio.services import (
    metadata_candidate_store as _metadata_candidate_store,
)
from src.nai_studio.services import (
    public_style_import as _public_style_import,
)
from src.nai_studio.services import (
    remote_image_cache as _remote_image_cache,
)
from src.nai_studio.services import resource_bridge as _resource_bridge
from src.nai_studio.services import style_store as _style_store
from src.nai_studio.runtime import file_transaction as _file_transaction
from src.nai_studio.services import tag_catalog as _tag_catalog
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


def resource_import_paths(app: Mapping[str, Any]):
    return _resource_bridge.LegacyResourceImportPaths(
        vibe_dir=app["VIBE_DIR"],
        transaction_root=app["VIBE_DIR"].parent.parent,
    )


def resource_import_operations(app: Mapping[str, Any]):
    return _resource_bridge.LegacyResourceImportOperations(
        transaction=app["shared_data_transaction"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        save_config=app["save_config"],
    )


def file_transaction_paths(app: Mapping[str, Any]):
    return _file_transaction.FileTransactionPaths(root=app["BASE_DIR"])


def file_transaction_operations(app: Mapping[str, Any]):
    return _file_transaction.FileTransactionOperations(
        transaction=app["shared_data_transaction"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        atomic_write_json=app["atomic_write_json"],
        load_json=app["load_json_recover"],
        replace=app["os"].replace,
        info=app["log"].info,
        warning=app["log"].warning,
    )


def catalog_search_paths(app: Mapping[str, Any]):
    return _catalog_search.CatalogSearchPaths(
        settings_file=app["SETTINGS_FILE"])


def catalog_search_state(app: Mapping[str, Any]):
    return _catalog_search.CatalogSearchState(
        booru_keys=app["_BOORU_KEYS"],
        booru_last=app["_BOORU_LAST"],
        booru_lock=app["_BOORU_LOCK"],
        tag_cache=app["_TAGV_CACHE"],
    )


def catalog_search_operations(app: Mapping[str, Any]):
    """현재 HTTP·시간·로그 객체를 주입해 기존 APP monkeypatch 계약을 보존한다."""
    return _catalog_search.CatalogSearchOperations(
        request_get=app["requests"].get,
        request_errors=(app["requests"].exceptions.RequestException,),
        clock=app["time"].time,
        sleep=app["time"].sleep,
        log_info=app["log"].info,
        log_warning=app["log"].warning,
        user_agent=app["BOORU_UA"],
    )


def remote_image_cache_paths(app: Mapping[str, Any]):
    return _remote_image_cache.RemoteImageCachePaths(
        image_cache=app["IMG_CACHE"],
        remote_cache=app["REMOTE_CACHE"],
        origin_file=app["_img_origin_path"](),
        cap_mb=app["REMOTE_CAP_MB"],
        mime=app["MIME"],
    )


def remote_image_cache_operations(app: Mapping[str, Any]):
    return _remote_image_cache.RemoteImageCacheOperations(
        http_get=app["requests"].get,
        load_json=app["load_json_recover"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        atomic_write_json=app["atomic_write_json"],
        warning=app["log"].warning,
        info=app["log"].info,
        origin_lock=app["_ORIGIN_LOCK"],
    )


def style_store_paths(app: Mapping[str, Any]):
    return _style_store.StyleStorePaths(
        style_file=app["STYLE_FILE"],
        transaction_root=app["STYLE_FILE"].parent.parent,
        trash_file=app["_trashed_style_path"](),
    )


def style_store_operations(app: Mapping[str, Any]):
    """현재 저장·모델·Undo 경계를 호출 때 주입해 기존 patch 계약을 보존한다."""
    return _style_store.StyleStoreOperations(
        transaction=app["shared_data_transaction"],
        lock=app["_STYLE_TX_LOCK"],
        load_rows=app["load_combos"],
        atomic_write_json=app["atomic_write_json"],
        normalize_model=app["model_id_from_metadata"],
        forget_caches=app["forget_collection_caches"],
        record_import_batch=app["record_import_batch"],
        load_json=app["load_json_recover"],
        deletion_stamp=lambda: app["time"].strftime("%Y-%m-%d %H:%M:%S"),
    )


def artist_workspace_operations(app: Mapping[str, Any]):
    """현재 난수·태그 결합 함수를 주입해 seed와 APP patch 계약을 보존한다."""
    return _artist_workspace.ArtistWorkspaceOperations(
        seeded_random=app["random"].Random,
        system_random=app["random"].SystemRandom,
        join_tags=app["_join_tags"],
    )


def style_catalog_paths(app: Mapping[str, Any]):
    return _library_catalog.StyleCatalogPaths(
        style_file=app["STYLE_FILE"],
        combo_file=app["COMBO_FILE"],
    )


def style_catalog_operations(app: Mapping[str, Any]):
    return _library_catalog.StyleCatalogOperations(
        load_json=app["load_json_recover"],
        info=app["log"].info,
        warning=app["log"].warning,
        lock=app["_COMBOS_LOCK"],
    )


def artist_rating_paths(app: Mapping[str, Any]):
    return _artist_rating_store.ArtistRatingPaths(
        ratings_file=app["RATINGS_FILE"],
    )


def artist_rating_state(app: Mapping[str, Any]):
    return _artist_rating_store.ArtistRatingState(
        cache=app["_RATINGS"],
        lock=app["_RATINGS_LOCK"],
    )


def artist_rating_operations(app: Mapping[str, Any]):
    """현재 저장 경계와 patch 가능한 조회·저장 함수를 서비스에 늦게 연결한다."""
    return _artist_rating_store.ArtistRatingOperations(
        transaction=app["shared_data_transaction"],
        load_json=app["load_json_recover"],
        atomic_write_json=app["atomic_write_json"],
        parse_artist_combo=app["parse_artist_combo"],
        warning=app["log"].warning,
        current_loader=lambda: app["load_ratings"](),
        current_saver=lambda data: app["save_ratings"](data),
    )


def library_catalog_paths(app: Mapping[str, Any]):
    return _library_catalog.LibraryCatalogPaths(
        review_file=app["LIBRARY_REVIEW_FILE"],
        review_schema="nais-library-review/v1",
        review_statuses=frozenset(app["LIBRARY_REVIEW_STATUSES"]),
    )


def library_catalog_state(app: Mapping[str, Any]):
    return _library_catalog.LibraryCatalogState(
        combo_cache=app["_COMBOS"],
        style_sorts=app["STYLE_SORTS"],
    )


def library_catalog_operations(app: Mapping[str, Any]):
    """현재 자료 공급자와 저장 경계를 호출 때 주입해 기존 patch 계약을 보존한다."""
    return _library_catalog.LibraryCatalogOperations(
        load_combos=app["load_combos"],
        load_ratings=app["load_ratings"],
        style_rating=app["style_rating"],
        list_settings=app["list_settings"],
        list_styles=app["list_styles"],
        load_recipes=app["load_recipes"],
        comparison_runs=app["comparison_runs"],
        load_json=app["load_json_recover"],
        atomic_write_json=app["atomic_write_json"],
        now=app["datetime"].now,
        review_lock=app["_LIBRARY_REVIEW_LOCK"],
        warning=app["log"].warning,
    )


def tag_catalog_paths(app: Mapping[str, Any]):
    return _tag_catalog.TagCatalogPaths(
        tag_dir=app["TAG_DIR"],
        cache_file=app["AC_CACHE_FILE"],
    )


def tag_catalog_state(app: Mapping[str, Any]):
    return _tag_catalog.TagCatalogState(
        cache=app["_TAG_CACHE"],
        lock=app["_TAG_LOCK"],
        cache_version=app["AC_CACHE_VER"],
    )


def tag_catalog_operations(app: Mapping[str, Any]):
    return _tag_catalog.TagCatalogOperations(
        renamed_tag=app["nai_renamed_tag"],
        info=app["log"].info,
        warning=app["log"].warning,
    )


def builder_handler_paths(app: Mapping[str, Any]):
    return _builder_handlers.BuilderHandlerPaths(
        builder_file=app["BUILDER_FILE"],
        transaction_root=app["CHAR_DIR"].parent,
    )


def builder_handler_operations(app: Mapping[str, Any]):
    """빌더 저장이 쓰는 기존 저장·잠금·파일 동기화 경계를 늦게 연결한다."""
    return _builder_handlers.BuilderHandlerOperations(
        load_json=app["load_json_recover"],
        transaction=app["shared_data_transaction"],
        compose_ordered=app["_compose_ordered"],
        save_style_file=app["save_style_file"],
        list_styles=app["list_styles"],
        random_character_id=lambda: "".join(app["random"].choices(
            app["string"].ascii_lowercase + app["string"].digits,
            k=8,
        )),
        sync_chars_to_files=app["sync_chars_to_files"],
        save_config=app["save_config"],
        warning=app["log"].warning,
    )


def fragment_import_operations(app: Mapping[str, Any]):
    return _fragment_workflow.FragmentImportOperations(
        fragment_dir=lambda: app["FRAG_DIR"],
        safe_name=app["_safe_name"],
        atomic_write_text=app["atomic_write_text"],
        list_fragments=app["list_fragments"],
    )


def public_style_import_operations(app: Mapping[str, Any]):
    """현재 메타·모델·UC·품질·작가 파서를 호출 때 주입해 APP patch를 보존한다."""
    return _public_style_import.PublicStyleImportOperations(
        extract_metadata=app["extract_nai_metadata"],
        model_id=app["model_id_from_metadata"],
        split_uc_preset=app["split_uc_preset"],
        restore_quality_prompt=app["restore_quality_prompt"],
        parse_artist_combo=app["parse_artist_combo"],
    )


__all__ = [
    "artist_rating_operations",
    "artist_rating_paths",
    "artist_rating_state",
    "artist_workspace_operations",
    "builder_handler_operations",
    "builder_handler_paths",
    "catalog_search_operations",
    "catalog_search_paths",
    "catalog_search_state",
    "data_inventory_operations",
    "data_inventory_paths",
    "datapack_operations",
    "datapack_paths",
    "fragment_import_operations",
    "library_catalog_operations",
    "library_catalog_paths",
    "library_catalog_state",
    "local_image_operations",
    "local_image_paths",
    "metadata_candidate_operations",
    "metadata_candidate_paths",
    "public_style_import_operations",
    "remote_image_cache_operations",
    "remote_image_cache_paths",
    "style_catalog_operations",
    "style_catalog_paths",
    "style_store_operations",
    "style_store_paths",
    "tag_catalog_operations",
    "tag_catalog_paths",
    "tag_catalog_state",
    "user_backup_operations",
    "user_backup_paths",
]
