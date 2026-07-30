# -*- coding: utf-8 -*-
"""생성 계열(NAI 호출·payload·진행·재시도·결과 저장·이미지 도구) Operations 조립.

`app`은 레거시 호환면의 globals()다 — 호출 시점 조회로 기존 monkeypatch
(patch.object(APP, "call_nai_api", …) 등) 계약을 보존한다. 여기에는 조립만
있고 기능 알고리즘·경로 상수·상태는 없다.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.nai_studio.services import collection_handlers as _collection_handlers
from src.nai_studio.services import generation_commit as _generation_commit
from src.nai_studio.services import (
    generation_execution as _generation_execution,
)
from src.nai_studio.services import generation_handlers as _generation_handlers
from src.nai_studio.services import generation_pacing as _generation_pacing
from src.nai_studio.services import generation_retry as _generation_retry
from src.nai_studio.services import generation_step as _generation_step
from src.nai_studio.services import image_tool_handlers as _image_tool_handlers
from src.nai_studio.services import nai_auxiliary as _nai_auxiliary
from src.nai_studio.services import (
    reference_preparation as _reference_preparation,
)


def reference_operations(app: Mapping[str, Any]):
    """현재 프로필 파일·HTTP·원자 저장을 Reference 서비스에 연결한다."""
    return _reference_preparation.ReferenceOperations(
        vibe_dir=app["VIBE_DIR"],
        settings_file=app["SETTINGS_FILE"],
        default_config=app["DEFAULT_CONFIG"],
        vibe_paths=app["vibe_paths"],
        encode_vibe=app["encode_vibe"],
        atomic_write_text=app["atomic_write_text"],
        transaction=app["shared_data_transaction"],
        load_json=app["load_json_recover"],
        save_config=app["save_config"],
        http_post=app["requests"].post,
        warning=app["log"].warning,
        info=app["log"].info,
    )


def auxiliary_operations(app: Mapping[str, Any]):
    """보조 NAI 호출의 HTTP·이미지 변환·로그를 늦게 연결한다."""
    return _nai_auxiliary.AuxiliaryOperations(
        http_post=app["requests"].post,
        http_get=app["requests"].get,
        image_png_base64=app["_b64_png"],
        info=app["log"].info,
        warning=app["log"].warning,
    )


def pacing_operations(app: Mapping[str, Any]):
    """현재 상태 장부와 patch 가능한 시계를 호출 간격 서비스에 연결한다."""
    return _generation_pacing.PacingOperations(
        load_state=app["load_state"],
        daily_count=app["daily_count"],
        random_uniform=app["random"].uniform,
        now=app["time"].time,
        sleep=app["time"].sleep,
        last_call=app["_LAST_CALL"],
    )


def generation_step_operations(app: Mapping[str, Any]):
    return _generation_step.GenerationStepOperations(
        character_resource_config=app["character_resource_config"],
        setting_reference_config=app["setting_reference_config"],
        build_scene=app["build_scene"],
        seed_for=app["seed_for"],
        join_tags=app["_join_tags"],
        setting_scene_people=app["setting_scene_people"],
        with_position_mode=app["with_position_mode"],
        with_centers=app["with_centers"],
    )


def generation_retry_operations(app: Mapping[str, Any]):
    return _generation_retry.GenerationRetryOperations(
        pace_gate=app["pace_gate"],
        pace_complete=app["pace_complete"],
        call_nai_api=app["call_nai_api"],
        warning=app["log"].warning,
        error=app["log"].error,
        critical=app["log"].critical,
    )


def generation_commit_operations(app: Mapping[str, Any]):
    return _generation_commit.GenerationCommitOperations(
        save_image=app["save_with_meta"],
        output_format=app["out_format"],
        output_clean_args=app["_ocargs"],
        output_clean=app["out_clean"],
        task_fingerprint=app["generation_task_fingerprint"],
        record_job_result=app["record_job_result"],
        output_root=app["out_root"],
        make_progress_record=app["make_progress_record"],
        progress_item_key=app["progress_item_key"],
        bump_daily=app["bump_daily"],
        daily_count=app["daily_count"],
        save_state=app["save_state"],
        warning=app["log"].warning,
    )


def generation_execution_operations(app: Mapping[str, Any]):
    """세팅 생성의 계산·재시도·저장 의존성을 호출 시점에 연결한다."""
    return _generation_execution.GenerationExecutionOperations(
        step=app["_generation_step_operations"](),
        retry=app["_generation_retry_operations"](),
        commit=app["_generation_commit_operations"](),
        load_state=app["load_state"],
        save_state=app["save_state"],
        fixed_seed=app["fixed_seed"],
        daily_count=app["daily_count"],
        daily_cap=app["DAILY_CAP"],
        load_asset_config=app["load_asset_config"],
        context_fingerprint=app["generation_context_fingerprint"],
        compute_pending=app["compute_pending"],
        progress_record_valid=app["progress_record_valid"],
        progress_record_path=app["progress_record_path"],
        pace=app["pace"],
        output_sub=app["out_sub"],
        runtime_params=app["runtime_generation_params"],
        random_seed=lambda: app["random"].randint(0, 2**32 - 1),
        random_uniform=app["random"].uniform,
        info=app["log"].info,
        warning=app["log"].warning,
        error=app["log"].error,
    )


def generation_handler_run_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "common_job_store": app["common_job_store"],
        "make_job_command": app["make_job_command"],
        "transition_job": app["transition_job"],
        "activate_comparison_run": app["activate_comparison_run"],
        "retry_job": app["retry_job"],
        "reconcile_job": app["reconcile_job"],
        "inherited_blueprint": app["inherited_blueprint"],
        "single_generation_material": app[
            "single_generation_legacy_material"],
        "characters_resource_config": app["characters_resource_config"],
        "start_daemon": lambda target: app["threading"].Thread(
            target=target, daemon=True).start(),
        "error": app["log"].error,
        "warning": app["log"].warning,
    }


def generation_handler_nai_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "pace_gate": app["pace_gate"],
        "runtime_generation_params": app["runtime_generation_params"],
        "load_state": app["load_state"],
        "call_nai_api": app["call_nai_api"],
        "with_centers": app["with_centers"],
        "pace_complete": app["pace_complete"],
        "output_subdir": app["out_sub"],
        "output_format": app["out_format"],
        "output_clean_args": app["out_clean"],
        "save_with_meta": app["save_with_meta"],
        "output_root": app["out_root"],
        "record_job_result": app["record_job_result"],
        "bump_daily": app["bump_daily"],
        "save_state": app["save_state"],
        "daily_count": app["daily_count"],
        "available_output_path": app["available_output_path"],
    }


def generation_handler_image_bindings(app: Mapping[str, Any]) -> dict:
    return {
        "random_seed": app["random"].randint,
        "reference_inset_canvas": app["reference_inset_canvas"],
        "character_asset_from_record": app[
            "character_asset_from_legacy_record"],
        "variation_plan_material": app[
            "variation_plan_to_legacy_payload_material"],
        "slot_prompt": app["slot_prompt"],
        "active_people": app["active_people"],
        "now": lambda: app["datetime"].now(),
        "extract_metadata": app["extract_nai_metadata"],
        "model_id_from_metadata": app["model_id_from_metadata"],
        "normalize_position_mode": app["normalize_position_mode"],
        "scene_mode_pending": app["scene_mode_pending"],
        "safe_name": app["_safe_name"],
        "progress_record_path": app["progress_record_path"],
        "join_tags": app["_join_tags"],
        "seed_for": app["seed_for"],
    }


def generation_handler_operations(app: Mapping[str, Any]):
    """생성 HTTP handler의 의존성을 기능 묶음별로 늦게 연결한다."""
    return _generation_handlers.GenerationHandlerOperations(
        **app["_generation_handler_run_bindings"](),
        **app["_generation_handler_nai_bindings"](),
        **app["_generation_handler_image_bindings"](),
    )


def image_tool_operations(app: Mapping[str, Any]):
    """이미지 도구의 저장·NAI·계보 의존성을 호출 시점에 연결한다."""
    return _image_tool_handlers.ImageToolOperations(
        vibe_dir=app["VIBE_DIR"],
        shared_data_transaction=app["shared_data_transaction"],
        vibe_paths=app["vibe_paths"],
        save_config=app["save_config"],
        prepare_vibes=app["prepare_vibes"],
        recoverable_remove=app["recoverable_remove"],
        director_tools=app["DIRECTOR_TOOLS"],
        call_upscale=app["call_upscale"],
        call_director=app["call_director"],
        inherited_blueprint=app["inherited_blueprint"],
        output_sub=app["out_sub"],
        record_job_result=app["record_job_result"],
        output_root=app["out_root"],
        info=app["log"].info,
        warning=app["log"].warning,
    )


def collection_handler_operations(app: Mapping[str, Any]):
    """단건 복원·변형 저장의 기존 데이터 경계를 호출 시점에 연결한다."""
    return _collection_handlers.CollectionHandlerOperations(
        output_root=app["out_root"],
        character_asset_from_legacy_record=app[
            "character_asset_from_legacy_record"
        ],
        accept_variation=app["accept_variation"],
        approved_variation_candidates=app[
            "approved_proposal_to_legacy_candidates"
        ],
        apply_variation_candidates=app[
            "apply_character_variation_candidates"
        ],
        local_import_image=app["_local_import_image"],
        sync_chars_to_files=app["sync_chars_to_files"],
        save_config=app["save_config"],
        extract_nai_metadata=app["extract_nai_metadata"],
        parse_artist_combo=app["parse_artist_combo"],
        model_id_from_metadata=app["model_id_from_metadata"],
        split_uc_preset=app["split_uc_preset"],
        restore_quality_prompt=app["restore_quality_prompt"],
        image_cache=app["IMG_CACHE"],
        atomic_write_bytes=app["_atomic_write_bytes"],
        evidence_from_image_record=app["evidence_from_image_record"],
        style_asset_from_record=app["style_asset_from_record"],
        add_style=app["add_style"],
        image_inspect_queue=app["image_inspect_queue"],
        summarize_restore_queue=app["summarize_restore_queue"],
        warning=app["log"].warning,
    )


__all__ = [
    "auxiliary_operations",
    "collection_handler_operations",
    "generation_commit_operations",
    "generation_execution_operations",
    "generation_handler_image_bindings",
    "generation_handler_nai_bindings",
    "generation_handler_operations",
    "generation_handler_run_bindings",
    "generation_retry_operations",
    "generation_step_operations",
    "image_tool_operations",
    "pacing_operations",
    "reference_operations",
]
