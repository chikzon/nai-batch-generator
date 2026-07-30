# -*- coding: utf-8 -*-
"""관리·비교 계열(비교 계획·실행권 핸들러) Operations 조립.

`app`은 레거시 호환면의 globals()다 — 호출 시점 조회로 monkeypatch 계약을
보존한다. 조립만 있고 기능 알고리즘은 없다.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.nai_studio.services import comparison_handlers as _comparison_handlers
from src.nai_studio.services import comparison_planning as _comparison_planning


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


__all__ = [
    "comparison_handler_operations",
    "comparison_planning_operations",
]
