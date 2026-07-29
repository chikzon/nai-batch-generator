# -*- coding: utf-8 -*-
"""비교 실행 시작과 결과 자산 승격 요청을 기존 서비스에 연결한다."""

from __future__ import annotations

import copy
import json
import traceback
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ComparisonHandlerOperations:
    """planning·execution·promotion 서비스와 진단 경계를 주입한다."""

    result_promotion_records: Callable[..., list]
    legacy_lineage_unavailable: type[BaseException]
    promote_assets: Callable[..., dict]
    append_promotion_ledger: Callable[[list], dict]
    redact_diagnostic_text: Callable[[Any], str]
    comparison_plan: Callable[..., dict]
    inherited_blueprint: Callable[..., dict]
    comparison_characters: Callable[[dict], list]
    comparison_sources: Callable[[dict, Any], tuple[list, list]]
    run_comparison: Callable[..., Any]
    start_daemon: Callable[[Callable[[], Any]], Any]
    error: Callable[..., Any]


def handle_compare_promote(
    server: Any,
    data: dict,
    operations: ComparisonHandlerOperations,
) -> dict:
    """선택한 비교 결과를 그림체 또는 캐릭터 자산으로 승격한다."""
    try:
        request = json.loads(data.get("body") or b"{}")
        with server.config_lock:
            server.use_latest_config()
            promotions = _promotion_records(
                server,
                request,
                operations,
            )
            result = operations.promote_assets(
                server.cfg,
                request.get("path"),
                request.get("kind"),
                name=request.get("name"),
                spec=server.spec,
            )
            if result.get("changed_config"):
                server.config_revision += 1
            result["revision"] = server.config_revision
            _attach_promotion_lineage(
                server,
                request,
                result,
                promotions,
                operations,
            )
            return result
    except Exception as error:
        return {"ok": False, "error": str(error)}


def _promotion_records(
    server: Any,
    request: dict,
    operations: ComparisonHandlerOperations,
) -> list | None:
    try:
        return operations.result_promotion_records(
            server.cfg,
            request.get("path"),
            request.get("kind"),
            name=request.get("name"),
        )
    except operations.legacy_lineage_unavailable:
        return None


def _attach_promotion_lineage(
    server: Any,
    request: dict,
    result: dict,
    promotions: list | None,
    operations: ComparisonHandlerOperations,
) -> None:
    if not result.get("ok"):
        return
    if promotions is None:
        result["lineage"] = {
            "verified": False,
            "warning": (
                "자산은 저장했지만 이 구형 결과에는 엄격한 실행 계보가 "
                "없어 승격 장부에는 넣지 않았습니다."
            ),
        }
        return
    try:
        resolved = operations.result_promotion_records(
            server.cfg,
            request.get("path"),
            request.get("kind"),
            name=request.get("name"),
            resolved_names=list(result.get("names") or []),
        )
        result["lineage"] = operations.append_promotion_ledger(
            resolved
        )
        result["lineage"]["verified"] = all(
            item.get("lineage", {})
            .get("execution", {})
            .get("manifest_verified")
            is True
            for item in resolved
        )
    except Exception as error:
        result["lineage"] = {
            "error": operations.redact_diagnostic_text(error),
            "verified": False,
        }


def handle_compare_run(
    server: Any,
    data: dict,
    operations: ComparisonHandlerOperations,
) -> dict:
    """확인된 비교 계획의 실행권을 잡고 기존 worker를 시작한다."""
    if server.live.running:
        return {"ok": False, "error": "이미 생성 중입니다."}
    try:
        request = json.loads(data.get("body") or b"{}")
    except Exception as error:
        return {
            "ok": False,
            "error": f"잘못된 요청입니다: {error}",
        }
    with server.config_lock:
        run_config = copy.deepcopy(server.cfg)
    if not run_config.get("token", "").startswith("pst-"):
        return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
    opus = None
    if server.anlas_balance_cache is not None:
        opus = bool(server.anlas_balance_cache.get("opus"))
    plan = operations.comparison_plan(
        run_config,
        request,
        server.spec,
        opus=opus,
    )
    if not plan["ok"] or not plan["count"]:
        return {
            "ok": False,
            "error": (
                " ".join(plan.get("errors") or [])
                or "생성할 항목이 없습니다."
            ),
        }
    confirmation_error = _comparison_confirmation(
        request,
        plan,
    )
    if confirmation_error:
        return confirmation_error
    token = server.live.try_claim(
        "자료 비교 생성",
        "library",
        blueprint=operations.inherited_blueprint(
            run_config,
            source={"kind": "comparison-plan"},
            experiment={
                **copy.deepcopy(plan.get("options") or {}),
                "selection": copy.deepcopy(
                    plan.get("selection")
                    or (plan.get("options") or {}).get("selection")
                    or {}
                ),
            },
        ),
        payload_identity={
            "kind": "comparison",
            "count": plan["count"],
            "mode": (plan.get("options") or {}).get("mode"),
        },
    )
    if token is None:
        return {"ok": False, "error": "이미 생성 중입니다."}
    styles, characters = _comparison_materials(
        operations,
        run_config,
        server.spec,
        plan,
    )
    operations.start_daemon(
        lambda: _comparison_worker(
            operations,
            server,
            run_config,
            plan,
            styles,
            characters,
            token,
        )
    )
    return {"ok": True, "plan": plan}


def _comparison_confirmation(
    request: dict,
    plan: dict,
) -> dict | None:
    try:
        confirmed_count = int(request.get("confirmed_count"))
    except (TypeError, ValueError):
        confirmed_count = -1
    if (
        request.get("confirmed")
        and confirmed_count == plan["count"]
    ):
        return None
    return {
        "ok": False,
        "error": (
            "실행 직전 장수 확인이 필요합니다. "
            f"현재 계획은 {plan['count']:,}장입니다."
        ),
        "plan": plan,
    }


def _comparison_materials(
    operations: ComparisonHandlerOperations,
    config: dict,
    spec: Any,
    plan: dict,
) -> tuple[list, list]:
    if plan["options"].get("mode") == "character_setting":
        return [], operations.comparison_characters(config)
    return operations.comparison_sources(config, spec)


def _comparison_worker(
    operations: ComparisonHandlerOperations,
    server: Any,
    config: dict,
    plan: dict,
    styles: list,
    characters: list,
    token: Any,
) -> None:
    try:
        operations.run_comparison(
            server,
            config,
            plan,
            styles,
            characters,
        )
    except Exception as error:
        operations.error("자료 비교 생성 실패: %s", error)
        operations.error(traceback.format_exc())
        server.live.update(
            status_text=f"자료 비교 생성 실패: {error}",
            failed=max(1, server.live.failed),
            last_error=str(error),
            can_retry=True,
            phase="failed",
        )
    finally:
        server.live.release(token)


__all__ = [
    "ComparisonHandlerOperations",
    "handle_compare_promote",
    "handle_compare_run",
]
