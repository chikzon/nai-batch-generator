# -*- coding: utf-8 -*-
"""관리·비교 계열(비교 계획·실행권 핸들러) Operations 조립.

`app`은 레거시 호환면의 globals()다 — 호출 시점 조회로 monkeypatch 계약을
보존한다. 조립만 있고 기능 알고리즘은 없다.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.nai_studio.services import comparison_execution as _comparison_execution
from src.nai_studio.services import comparison_handlers as _comparison_handlers
from src.nai_studio.services import comparison_planning as _comparison_planning
from src.nai_studio.services import (
    comparison_promotion as _comparison_promotion,
)
from src.nai_studio.services import comparison_runtime as _comparison_runtime
from src.nai_studio.services import management_state as _management_state
from src.nai_studio.services import output_lifecycle as _output_lifecycle
from src.nai_studio.services import (
    program_data_migration as _program_data_migration,
)
from src.nai_studio.runtime import program_entry as _program_entry


def comparison_planning_operations(app: Mapping[str, Any]):
    """비교 계획이 쓰는 저장·세팅 경계를 호출 시점의 구현에 연결한다."""
    return _comparison_planning.ComparisonPlanningOperations(
        load_combos=app["load_combos"],
        load_spec=app["load_spec"],
        list_styles=app["list_styles"],
        style_bundle_signature=app["style_bundle_signature"],
        load_asset_config=app["load_asset_config"],
        compute_pending=app["compute_pending"],
        setting_reference_config=app["setting_reference_config"],
        character_resource_config=app["character_resource_config"],
        characters_resource_config=app["characters_resource_config"],
        inherited_blueprint=app["inherited_blueprint"],
        recipe_setting_keys=app["COMPARE_RECIPE_SETTING_KEYS"],
        max_characters=app["MAX_CHARS"],
    )


def comparison_handler_operations(app: Mapping[str, Any]):
    """비교 실행·승격의 기존 계획·계보·worker 의존성을 연결한다."""
    return _comparison_handlers.ComparisonHandlerOperations(
        result_promotion_records=app["_result_promotion_records"],
        legacy_lineage_unavailable=app["LegacyPromotionLineageUnavailable"],
        promote_assets=app["promote_comparison_recipe_assets"],
        append_promotion_ledger=app["_append_result_promotion_ledger"],
        redact_diagnostic_text=app["redact_diagnostic_text"],
        comparison_plan=app["comparison_plan"],
        inherited_blueprint=app["inherited_blueprint"],
        comparison_characters=app["comparison_characters"],
        comparison_sources=app["comparison_sources"],
        run_comparison=app["_run_comparison"],
        selected_comparison_record=app["_selected_comparison_record"],
        rerun_selected_comparison=app["_rerun_selected_comparison"],
        start_daemon=lambda target: app["threading"].Thread(
            target=target,
            daemon=True,
        ).start(),
        error=app["log"].error,
    )


def config_initialization_operations(app: Mapping[str, Any]):
    """설정 복구와 캐릭터 동기화의 기존 patch 경계를 늦게 연결한다."""
    return _management_state.ConfigInitializationOperations(
        load_settings=app["load_settings_recover"],
        quarantine_corrupt=app["quarantine_corrupt_settings"],
        migrate_legacy=app["_migrate_legacy"],
        ensure_settings_migration=app["ensure_settings_migration"],
        migrate_selections=app["migrate_legacy_selections"],
        migrate_char_slots=app["migrate_char_slots"],
        import_char_files=app["import_char_files"],
        sync_chars_to_files=app["sync_chars_to_files"],
        save_config=app["save_config"],
        log_critical=app["log"].critical,
    )


def output_lifecycle_paths(app: Mapping[str, Any]):
    """레거시 상수와 서비스의 파일·휴지통 계약을 한곳에서 연결한다."""
    return _output_lifecycle.OutputLifecyclePaths(
        trash_dir_name=app["TRASH_DIR_NAME"],
        image_extensions=app["IMG_EXT"],
        trash_schema="nais-output-trash/v2",
        directory_count_ttl=30.0,
    )


def output_lifecycle_operations(app: Mapping[str, Any]):
    """호출 시점의 저장·시간 의존성을 주입해 기존 monkeypatch 계약을 보존한다."""
    return _output_lifecycle.OutputLifecycleOperations(
        output_root=app["out_root"],
        atomic_write_json=app["atomic_write_json"],
        load_json=app["load_json_recover"],
        load_picks=app["load_picks"],
        save_picks=app["save_picks"],
        picks_lock=app["_JSON_IO_LOCK"],
        project_evaluations=app["project_legacy_evaluations"],
        move_file=app["shutil"].move,
        now=app["datetime"].now,
        uuid4=app["uuid"].uuid4,
        clock=app["time"].time,
        directory_count_cache=app["_DIR_COUNT_CACHE"],
        warning=app["log"].warning,
    )


def job_ledger_paths(app: Mapping[str, Any]):
    return _management_state.JobLedgerPaths(
        ledger_file=app["JOB_LEDGER_FILE"],
    )


def job_ledger_operations(app: Mapping[str, Any]):
    """현재 프로필 저장소와 patch 가능한 장부 의존성을 늦게 연결한다."""
    return _management_state.JobLedgerOperations(
        lock=app["_JSON_IO_LOCK"],
        load_json=app["load_json_recover"],
        atomic_write_json=app["atomic_write_json"],
        common_job_store=lambda: app["common_job_store"](),
        now=lambda: app["datetime"].now().isoformat(timespec="seconds"),
        uuid_hex=lambda: app["uuid"].uuid4().hex,
        redact=app["redact_diagnostic_text"],
        log_error=app["log"].error,
    )


def config_projection_operations(app: Mapping[str, Any]):
    """ConfigServer의 읽기 전용 설정·Job 투영 의존성을 늦게 연결한다."""
    return _management_state.ConfigProjectionOperations(
        load_settings=app["load_settings_recover"],
        migrate_selections=app["migrate_legacy_selections"],
        migrate_char_slots=app["migrate_char_slots"],
        job_summary=lambda: app["job_ledger_summary"](),
        runtime_kind=app["_runtime_kind"],
        inherited_blueprint=app["inherited_blueprint"],
        project_live_state=app["project_live_state"],
        comparison_progress=lambda: app["_comparison_progress_load"](),
        project_comparison_progress=app["project_comparison_progress"],
        redact=app["redact_diagnostic_text"],
    )


def comparison_runtime_operations(app: Mapping[str, Any]):
    """비교 manifest·재실행 의존성을 호출 시점의 APP 경계에 연결한다."""
    return _comparison_runtime.ComparisonRuntimeOperations(
        output_root=app["out_root"],
        comparison_signature=app["comparison_signature"],
        load_progress=app["_comparison_progress_load"],
        load_json=app["load_json_recover"],
        path_is_inside=app["_path_is_inside"],
        output_file_for_preview=app["output_file_for_preview"],
        output_subdir=app["out_sub"],
        now=lambda: app["datetime"].now(),
        random_bytes=app["os"].urandom,
        now_text=lambda: app["time"].strftime("%Y-%m-%d %H:%M:%S"),
        random_seed=app["random"].randint,
        comparison_recipe_context=app["comparison_recipe_context"],
        save_progress=app["_comparison_progress_save"],
        info=app["log"].info,
        warning=app["log"].warning,
        selected_comparison_record=app["_selected_comparison_record"],
        regenerate_execution_material=app[
            "regenerate_legacy_execution_material"
        ],
        selected_config=app["_comparison_selected_cfg"],
        load_asset_config=app["load_asset_config"],
        compute_pending=app["compute_pending"],
        selected_job_values=app["comparison_selected_job_values"],
        generation_blueprint=app["generation_blueprint"],
        pace_gate=app["pace_gate"],
        runtime_generation_params=app["runtime_generation_params"],
        call_nai_api=app["call_nai_api"],
        with_centers=app["with_centers"],
        pace_complete=app["pace_complete"],
        output_format=app["out_format"],
        available_output_path=app["available_output_path"],
        output_clean_args=app["out_clean"],
        save_with_meta=app["save_with_meta"],
        record_job_result=app["record_job_result"],
        uuid4=app["uuid"].uuid4,
        comparison_job_recipe_snapshot=app["comparison_job_recipe_snapshot"],
        load_state=app["load_state"],
        bump_daily=app["bump_daily"],
        save_state=app["save_state"],
        # COMPARE_PROGRESS_FILE을 호출 시점에 읽어야 monkeypatch가 보인다.
        save_resume_progress=lambda progress: app["atomic_write_json"](
            app["COMPARE_PROGRESS_FILE"], progress, indent=1),
    )


def comparison_execution_operations(app: Mapping[str, Any]):
    """비교 큐·NAI·결과 저장 의존성을 호출 시점의 APP 경계에 연결한다."""
    return _comparison_execution.ComparisonExecutionOperations(
        progress_start=app["_comparison_progress_start"],
        save_progress=app["_comparison_progress_save"],
        link_job_ancestor=app["link_job_ancestor"],
        record_job_result=app["record_job_result"],
        output_file_for_preview=app["output_file_for_preview"],
        redact_diagnostic_text=app["redact_diagnostic_text"],
        warning=app["log"].warning,
        info=app["log"].info,
        error=app["log"].error,
        iter_character_setting_jobs=app["iter_character_setting_jobs"],
        iter_selected_jobs=app["iter_selected_comparison_jobs"],
        iter_comparison_jobs=app["iter_comparison_jobs"],
        comparison_job_values=app["comparison_job_values"],
        comparison_job_recipe_snapshot=app["comparison_job_recipe_snapshot"],
        generation_blueprint=app["generation_blueprint"],
        safe_name=app["_safe_name"],
        available_output_path=app["available_output_path"],
        output_format=app["out_format"],
        output_root=app["out_root"],
        output_clean_args=app["out_clean"],
        pace=app["pace"],
        pace_gate=app["pace_gate"],
        pace_complete=app["pace_complete"],
        runtime_generation_params=app["runtime_generation_params"],
        call_nai_api=app["call_nai_api"],
        with_centers=app["with_centers"],
        save_with_meta=app["save_with_meta"],
        load_state=app["load_state"],
        daily_count=app["daily_count"],
        bump_daily=app["bump_daily"],
        save_state=app["save_state"],
        now_text=lambda: app["time"].strftime("%Y-%m-%d %H:%M:%S"),
        rate_limit_error=app["RateLimitError"],
        account_errors=(
            app["AccountBannedError"],
            app["AuthError"],
        ),
        api_error=app["APIError"],
    )


def comparison_promotion_paths(app: Mapping[str, Any]):
    """현재 프로필의 승격 저장 경로를 호출 시점에 조립한다."""
    return _comparison_promotion.ComparisonPromotionPaths(
        base_dir=app["BASE_DIR"],
        style_dir=app["STYLE_DIR"],
        character_dir=app["CHAR_DIR"],
        settings_file=app["SETTINGS_FILE"],
    )


def comparison_promotion_operations(
    app: Mapping[str, Any],
    include_recipe_adapter: bool = False,
):
    """현재 비교·평가·저장 경계를 늦게 주입해 APP patch를 보존한다."""
    return _comparison_promotion.ComparisonPromotionOperations(
        transaction=app["shared_data_transaction"],
        comparison_result_context=app["_comparison_result_context"],
        default_config=app["DEFAULT_CONFIG"],
        comparison_style_config=app["comparison_style_config"],
        recipe_setting_keys=app["COMPARE_RECIPE_SETTING_KEYS"],
        slot_prompt=app["slot_prompt"],
        comparison_result_evaluation=app["_comparison_result_evaluation"],
        build_result_promotion=app["build_result_promotion"],
        style_bundle_signature=app["style_bundle_signature"],
        character_bundle_signature=app["character_bundle_signature"],
        list_styles=app["list_styles"],
        load_spec=app["load_spec"],
        load_combos=app["load_combos"],
        unique_library_name=app["_unique_library_name"],
        save_style_file=app["save_style_file"],
        safe_name=app["_safe_name"],
        record_import_batch=app["record_import_batch"],
        sync_characters_to_files=app["sync_chars_to_files"],
        save_config=app["save_config"],
        random_character_id=lambda: "".join(app["random"].choices(
            app["string"].ascii_lowercase + app["string"].digits, k=8)),
        recipe_for_output=(
            app["comparison_recipe_for_output"]
            if include_recipe_adapter
            else None
        ),
    )


def program_data_migration_paths(app: Mapping[str, Any], program_dir, data_dir):
    return _program_data_migration.ProgramDataMigrationPaths(
        program_dir=program_dir,
        data_dir=data_dir,
        user_files=app["_LEGACY_USER_FILES"],
        user_dirs=app["_LEGACY_USER_DIRS"],
    )


def program_data_migration_operations(app: Mapping[str, Any]):
    return _program_data_migration.ProgramDataMigrationOperations(
        copy_file=app["shutil"].copy2,
        replace_file=app["os"].replace,
        process_id=app["os"].getpid,
        thread_id=app["threading"].get_ident,
        now=lambda: app["datetime"].now(),
    )


def program_entry_operations(app: Mapping[str, Any]):
    """기존 main의 초기화·서버·batch 경계를 호출 시점에 연결한다."""
    return _program_entry.ProgramEntryOperations(
        prepare_profile=lambda profile: profile,
        initialize_logging=lambda _context: app["log"],
        acquire_single_instance=lambda _context: True,
        release_single_instance=lambda _instance: None,
        migrate_program_data=lambda _context: app["_DATA_MIGRATION"],
        load_config=lambda _context: app["load_or_init_config"](),
        load_options=lambda _context: app["OPTIONS"],
        load_spec=lambda _context: app["load_spec"](),
        recover_jobs=lambda _context: app["recover_job_ledger"](),
        create_server=lambda config, _options, spec, _context: app[
            "ConfigServer"
        ](
            config,
            persist_jobs=True,
            spec=spec,
        ),
        start_server=lambda server, open_browser: server.start(
            open_browser=open_browser
        ),
        cleanup_server=lambda _server: None,
        close_logging=lambda _logger: None,
        # 태그 색인과 그림체 카탈로그를 함께 예열해 첫 열기를 웜 경로로 만든다.
        warm_index=lambda server: (
            app["_ac_index"](server.spec),
            app["load_combos"](),
        ),
        start_daemon=lambda target: app["threading"].Thread(
            target=target,
            daemon=True,
        ).start(),
        run_generation=lambda server, config: app["_run_generation"](
            server,
            config,
        ),
        inherited_blueprint=app["inherited_blueprint"],
        fatal_stop_errors=(app["FatalStopError"],),
        log_info=app["log"].info,
        log_critical=app["log"].critical,
        format_traceback=app["traceback"].format_exc,
        read_input=lambda prompt: input(prompt),
        write_line=lambda line: print(line),
    )


__all__ = [
    "comparison_execution_operations",
    "comparison_handler_operations",
    "comparison_planning_operations",
    "comparison_promotion_operations",
    "comparison_promotion_paths",
    "comparison_runtime_operations",
    "config_initialization_operations",
    "config_projection_operations",
    "job_ledger_operations",
    "job_ledger_paths",
    "output_lifecycle_operations",
    "output_lifecycle_paths",
    "program_entry_operations",
]
