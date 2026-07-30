# -*- coding: utf-8 -*-
"""GET/POST 라우트 Operations 바인딩 조립.

`app`은 레거시 호환면의 globals()다. `late_bound`는 이름을 호출 순간에
찾으므로 라우트가 살아 있는 동안의 monkeypatch도 그대로 반영된다.
endpoint 문자열은 여기 없다 — web/routes 밖으로 내보내지 않는다.
"""
from __future__ import annotations

from typing import Any, Mapping


def late_bound(app: Mapping[str, Any], name: str):
    return lambda *args, **kwargs: app[name](*args, **kwargs)


def catalog_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "booru": late_bound(app, "search_booru"),
        "style_duplicates": late_bound(app, "find_style_dupes"),
        "library": late_bound(app, "search_library"),
        "combos": late_bound(app, "search_combos"),
        "recipes": late_bound(app, "search_recipes"),
        "prewarm": late_bound(app, "prewarm_images"),
        "autocomplete": late_bound(app, "autocomplete_tags"),
        "tags": late_bound(app, "search_tags"),
        "scenes": lambda cfg, ids, setting: app["scene_catalog"](
            cfg,
            ids,
            setting,
            setting_path=app["setting_path"],
            load_json=app["load_json_recover"],
            load_asset_config=app["load_asset_config"],
            content_revision=app["setting_content_revision"],
            normalize_refs=app["normalize_scene_reference_ids"],
            normalize_centers=app["normalize_scene_centers"],
        ),
        "comparison_catalog": late_bound(app, "comparison_catalog"),
        "comparison_runs": late_bound(app, "comparison_runs"),
        "comparison_progress": late_bound(app, "comparison_progress_summary"),
    }


def asset_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "vibe_dir": lambda: app["VIBE_DIR"],
        "mime": lambda: app["MIME"],
        "output_preview": late_bound(app, "output_file_for_preview"),
        "output_list": late_bound(app, "list_output"),
        "setting_thumbs": late_bound(app, "setting_thumbs"),
        "resource_export": lambda cfg: app["export_legacy_resources"](
            cfg,
            file_index=app["resource_file_index"](cfg),
        ),
        "backup_export": late_bound(app, "export_user_backup"),
        "fragments_export": late_bound(app, "export_fragments_zip"),
        "settings_export": late_bound(app, "export_settings_zip"),
        "cached_image": late_bound(app, "fetch_cached_image"),
        "diagnostics": lambda limit, errors_only: app["diagnostic_snapshot"](
            app["LOG_FILE"],
            limit=limit,
            errors_only=errors_only,
        ),
        "render_page": late_bound(app, "render_page"),
    }


def recovery_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "metadata_audit": lambda offset, limit: app["metadata_audit_status"](
            found_offset=offset,
            found_limit=limit,
        ),
        "folder_inventory": late_bound(app, "folder_inventory_page"),
        "trash": late_bound(app, "list_trash_batches"),
        "pack_log": lambda: {
            "ok": True,
            "log": app["pack_log_brief"](),
        },
        "public_restoration": lambda: app[
            "PUBLIC_COLLECTION"
        ].restoration_snapshot(),
        "public_collection": lambda: app["PUBLIC_COLLECTION"].snapshot(),
        "data_storage": late_bound(app, "data_storage_status"),
        "image_origins": late_bound(app, "image_origin_stats"),
        "local_integrity": late_bound(app, "local_image_integrity"),
        "preview_backup": late_bound(app, "preview_user_backup"),
        "restore_backup": late_bound(app, "restore_user_backup"),
        "rollback_backup": late_bound(app, "rollback_user_backup"),
        "load_settings": lambda: app["load_settings_recover"](
            app["SETTINGS_FILE"]
        ),
        "default_config": lambda: app["DEFAULT_CONFIG"],
        "migrate_selections": late_bound(app, "migrate_legacy_selections"),
        "migrate_slots": late_bound(app, "migrate_char_slots"),
        "load_spec": late_bound(app, "load_spec"),
        "options": lambda: app["OPTIONS"],
        "load_options": late_bound(app, "load_options"),
        "normalize_local_images": late_bound(
            app, "normalize_local_image_refs"),
        "rollback_local_images": late_bound(
            app, "rollback_local_image_normalize"),
        "rebuild_data_index": late_bound(app, "rebuild_data_index"),
        "metadata_control": late_bound(app, "metadata_audit_control"),
        "metadata_candidate": late_bound(app, "metadata_audit_candidate"),
        "metadata_save": late_bound(app, "metadata_audit_save_candidate"),
        "image_batch_queue": late_bound(app, "image_batch_queue"),
        "summarize_queue": late_bound(app, "summarize_restore_queue"),
    }


def collection_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "preview_pack": late_bound(app, "preview_datapack_bytes"),
        "import_pack": late_bound(app, "import_datapack_bytes"),
        "pack_queue": late_bound(app, "pack_import_queue"),
        "summarize_queue": late_bound(app, "summarize_restore_queue"),
        "forget_caches": late_bound(app, "forget_collection_caches"),
        "public_start": lambda payload: app["PUBLIC_COLLECTION"].start(
            payload),
        "public_retry": lambda payload: app["PUBLIC_COLLECTION"].retry_failed(
            payload),
        "public_control": lambda action: app["PUBLIC_COLLECTION"].control(
            action),
        "undo_pack": late_bound(app, "undo_datapack"),
        "import_settings": late_bound(app, "import_settings_bytes"),
        "verify_tags": late_bound(app, "verify_tags"),
        "organize_library": late_bound(app, "organize_library_items"),
        "delete_styles": late_bound(app, "delete_styles"),
        "restore_styles": late_bound(app, "restore_styles"),
    }


def evaluation_fragment_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "artist_workspace": late_bound(app, "artist_workspace_request"),
        "load_ratings": late_bound(app, "load_ratings"),
        "rate_artist": late_bound(app, "rate_artist"),
        "apply_evaluation": late_bound(app, "apply_evaluation_action"),
        "picks_lock": app["_JSON_IO_LOCK"],
        "load_picks": late_bound(app, "load_picks"),
        "save_picks": late_bound(app, "save_picks"),
        "trash_outputs": late_bound(app, "trash_output_files"),
        "restore_trash": late_bound(app, "restore_trash_batch"),
        "output_subdir": late_bound(app, "out_sub"),
        "atomic_write": late_bound(app, "_atomic_write_bytes"),
        "strip_and_save": late_bound(app, "strip_and_save"),
        "fragment_dir": lambda: app["FRAG_DIR"],
        "save_fragment": late_bound(app, "save_fragment"),
        "list_fragments": late_bound(app, "list_fragments"),
        "recoverable_remove": late_bound(app, "recoverable_remove"),
        "load_state": late_bound(app, "load_state"),
        "save_state": late_bound(app, "save_state"),
        "import_fragments": late_bound(app, "import_fragments_bytes"),
        "reroll_components": late_bound(app, "reroll_legacy_components"),
        "resolve_prompt": late_bound(app, "resolve_legacy_prompt"),
        "sequence_text": late_bound(app, "legacy_sequence_text"),
        "resolve_fragments": late_bound(app, "resolve_fragments"),
        "random_factory": app["random"].Random,
    }


def settings_runtime_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "duplicate_scene_undo": late_bound(
            app, "undo_duplicate_setting_scene"),
        "duplicate_scene": late_bound(app, "duplicate_setting_scene"),
        "load_asset_config": late_bound(app, "load_asset_config"),
        "setting_state": late_bound(app, "setting_state"),
        "cast_members": late_bound(app, "setting_cast_members"),
        "slot_prompt": late_bound(app, "slot_prompt"),
        "character_run": late_bound(app, "character_run_from_group"),
        "build_scene": late_bound(app, "build_scene"),
        "reference_config": late_bound(app, "setting_reference_config"),
        "scene_people": late_bound(app, "setting_scene_people"),
        "seed_for": late_bound(app, "seed_for"),
        "normalize_prompt": late_bound(app, "normalize_prompt"),
        "join_tags": late_bound(app, "_join_tags"),
        "token_count": late_bound(app, "nai_tokens"),
        "save_scenes": late_bound(app, "save_scenes"),
        "new_setting": late_bound(app, "new_setting"),
        "add_set": late_bound(app, "setting_add_set"),
        "save_meta": late_bound(app, "setting_meta_save"),
        "renumber": late_bound(app, "setting_renumber"),
        "delete_setting": late_bound(app, "setting_delete"),
        "duplicate_group": late_bound(app, "duplicate_setting_group"),
        "log_warning": app["log"].warning,
        "activate_comparison": late_bound(app, "activate_comparison_run"),
        "comparison_recipe": late_bound(app, "comparison_recipe_for_output"),
        "fetch_balance": late_bound(app, "fetch_anlas_balance"),
        "vibe_paths": late_bound(app, "vibe_paths"),
        "compute_pending": late_bound(app, "compute_pending"),
        "estimate_anlas": late_bound(app, "anlas_estimate"),
        "finalize_tokens": late_bound(app, "finalized_token_texts"),
        "tokens_exact": late_bound(app, "tokens_exact"),
    }


def route_bindings(app: Mapping[str, Any]) -> dict:
    """라우트 Operations 의존성을 기능 범주별로 합친다."""
    groups = (
        catalog_bindings(app),
        asset_bindings(app),
        recovery_bindings(app),
        collection_bindings(app),
        evaluation_fragment_bindings(app),
        settings_runtime_bindings(app),
        app["_studio_wiring"].extra_route_bindings(app),
    )
    return {key: value for group in groups for key, value in group.items()}


__all__ = [
    "asset_bindings",
    "catalog_bindings",
    "collection_bindings",
    "evaluation_fragment_bindings",
    "late_bound",
    "recovery_bindings",
    "route_bindings",
    "settings_runtime_bindings",
]
