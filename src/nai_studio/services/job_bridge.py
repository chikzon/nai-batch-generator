# -*- coding: utf-8 -*-
"""기존 실행 상태와 durable Job 계약 사이의 순수 어댑터.

파일 저장과 핸들러 호출은 하지 않는다. 기존 상태에서 prompt·token 원문을 빼고
지문·진행·계보만 Job으로 투영하며, legacy 실행기가 소비할 명령 dict를 만든다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping

from src.nai_studio.domain import fingerprint_blueprint
from src.nai_studio.runtime.jobs import (
    NAI_RESOURCE_KEY,
    JobContractError,
    add_result,
    fingerprint_payload,
    from_comparison_progress,
    new_job,
    reconcile_job,
    retry_job,
    transition_job,
    update_cost,
    update_progress,
    validate_job,
)


COMMAND_SCHEMA = "nai-legacy-job-command/v1"


class JobBridgeError(ValueError):
    """기존 상태를 안전한 Job 또는 command로 투영할 수 없을 때."""


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _stable_id(*parts: Any) -> str:
    raw = json.dumps(
        parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_identifier(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _fingerprints(
    *,
    blueprint: Mapping[str, Any] | None,
    payload_identity: Mapping[str, Any] | None,
    fallback: Mapping[str, Any],
) -> tuple[str, str]:
    blueprint_value = (
        blueprint if isinstance(blueprint, Mapping)
        else {"source": deepcopy(dict(fallback))}
    )
    payload_value = (
        payload_identity if isinstance(payload_identity, Mapping)
        else deepcopy(dict(fallback))
    )
    return (
        fingerprint_blueprint(blueprint_value),
        fingerprint_payload(payload_value),
    )


def _set_observed_phase(
    job: Mapping[str, Any],
    phase: str,
    *,
    retryable: bool = False,
    at: str = "",
) -> dict:
    """legacy snapshot은 사건 관찰값이므로 중간 전이를 꾸며내지 않는다."""
    clean = validate_job(job)
    if phase == "queued":
        return clean
    clean["phase"] = phase
    clean["updated_at"] = str(at or clean["updated_at"])
    clean["phase_history"].append({
        "phase": phase,
        "at": clean["updated_at"],
        "source": "legacy-projection",
    })
    if phase == "failed":
        clean["error"] = {
            "code": "legacy-failure",
            "message": "기존 실행 상태가 실패로 기록됐습니다.",
            "retryable": bool(retryable),
        }
    elif phase == "paused":
        clean["error"] = {
            "code": "legacy-paused",
            "message": "기존 실행을 중지한 지점에서 이어갈 수 있습니다.",
            "retryable": True,
        }
    else:
        clean["error"] = None
    return validate_job(clean)


def _lineage(
    job: Mapping[str, Any],
    *,
    source_job_ids: Iterable[str] = (),
    source_result_ids: Iterable[str] = (),
) -> dict:
    clean = validate_job(job)
    for key, values in (
        ("source_job_ids", source_job_ids),
        ("source_result_ids", source_result_ids),
    ):
        current = list(clean["lineage"][key])
        for value in values:
            text = str(value or "")
            if text and text not in current:
                current.append(text)
        clean["lineage"][key] = current
    return validate_job(clean)


def project_live_state(
    snapshot: Mapping[str, Any],
    *,
    kind: str,
    job_id: str = "",
    request_id: str = "",
    blueprint: Mapping[str, Any] | None = None,
    payload_identity: Mapping[str, Any] | None = None,
    source_job_ids: Iterable[str] = (),
    source_result_ids: Iterable[str] = (),
) -> dict:
    """``LiveState.snapshot()``을 prompt 없는 durable Job으로 투영."""
    live = _mapping(snapshot)
    operation = str(live.get("operation") or kind or "generation")[:120]
    started = str(live.get("started_at") or "")
    stable = _stable_id("live", kind, operation, started)
    identifier = _safe_identifier(
        job_id or live.get("job_id"), f"job-live-{stable[:24]}")
    request = _safe_identifier(request_id, identifier)
    fallback = {
        "kind": str(kind),
        "operation": operation,
        "started_at": started,
        "seed_key": str(live.get("seed_key") or ""),
    }
    blueprint_hash, payload_hash = _fingerprints(
        blueprint=blueprint,
        payload_identity=payload_identity,
        fallback=fallback,
    )
    retry_count = max(0, int(live.get("retry_count") or 0))
    job = new_job(
        str(kind),
        blueprint_fingerprint=blueprint_hash,
        payload_hash=payload_hash,
        request_id=request,
        job_id=identifier,
        total=max(0, int(live.get("total") or 0)),
        cost_preview=max(0, float(live.get("cost_preview") or 0)),
        retry_policy={"max_attempts": max(3, retry_count + 2)},
        metadata={
            "legacy_source": "LiveState",
            "operation": operation,
            "retry_mode": str(live.get("retry_mode") or ""),
            "seed_key": str(live.get("seed_key") or ""),
            "can_retry": bool(live.get("can_retry")),
        },
        now=str(live.get("created_at") or live.get("updated_at") or "") or None,
    )
    job = update_progress(
        job,
        completed=max(0, int(live.get("completed") or 0)),
        failed=max(0, int(live.get("failed") or 0)),
        total=max(0, int(live.get("total") or 0)),
    )
    job["retry"]["count"] = retry_count
    if live.get("cost_actual") is not None:
        job = update_cost(job, actual=max(0, float(live["cost_actual"])))
    legacy_phase = str(live.get("phase") or "idle")
    phase = {
        "idle": "queued",
        "running": "preparing",
        "stopping": "paused",
        "stopped": "paused",
        "partial": "paused",
        "completed": "completed",
        "complete": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(legacy_phase, "queued")
    job = _set_observed_phase(
        job,
        phase,
        retryable=bool(live.get("can_retry")),
        at=str(live.get("updated_at") or ""),
    )
    return _lineage(
        job,
        source_job_ids=source_job_ids,
        source_result_ids=source_result_ids,
    )


def project_comparison_progress(
    progress: Mapping[str, Any],
    *,
    blueprint: Mapping[str, Any] | None = None,
    payload_identity: Mapping[str, Any] | None = None,
    source_job_ids: Iterable[str] = (),
    source_result_ids: Iterable[str] = (),
) -> dict:
    """비교 progress/manifest를 안정 ID와 원래 계획 지문을 가진 Job으로 투영."""
    raw = _mapping(progress)
    plan = _mapping(raw.get("plan"))
    signature = str(raw.get("signature") or "")
    stable = _stable_id(
        "comparison", signature, raw.get("folder"), raw.get("created_at"))
    raw["job_id"] = _safe_identifier(
        raw.get("job_id"), f"job-comparison-{stable[:24]}")
    raw["request_id"] = _safe_identifier(raw.get("request_id"), raw["job_id"])
    job = from_comparison_progress(raw)
    if blueprint is not None:
        job["blueprint_fingerprint"] = fingerprint_blueprint(blueprint)
    if payload_identity is not None:
        job["payload_hash"] = fingerprint_payload(payload_identity)
    job["metadata"]["plan"] = {
        "kind": "comparison",
        "fingerprint": (
            signature if len(signature) == 64
            else _stable_id("comparison-plan", plan)
        ),
        "folder": str(raw.get("folder") or ""),
    }
    return _lineage(
        job,
        source_job_ids=source_job_ids,
        source_result_ids=source_result_ids,
    )


def project_settings_batch_state(
    state: Mapping[str, Any],
    *,
    seed_key: str,
    live: Mapping[str, Any] | None = None,
    expected_total: int | None = None,
    blueprint: Mapping[str, Any] | None = None,
    payload_identity: Mapping[str, Any] | None = None,
    job_id: str = "",
    request_id: str = "",
    source_job_ids: Iterable[str] = (),
    source_result_ids: Iterable[str] = (),
) -> dict:
    """``nsfw_seed_state.json``의 한 회차를 설정/씬 batch Job으로 투영."""
    raw = _mapping(state)
    key = str(seed_key or "")
    source_jobs = tuple(str(item) for item in source_job_ids if str(item))
    source_results = tuple(str(item) for item in source_result_ids if str(item))
    progress_root = (
        raw.get("progress") if isinstance(raw.get("progress"), Mapping) else {}
    )
    batch = (
        progress_root.get(key)
        if isinstance(progress_root.get(key), Mapping) else {}
    )
    records = []
    for character_id in sorted(batch, key=str):
        items = batch.get(character_id)
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, Mapping):
                continue
            records.append((str(character_id), deepcopy(dict(item))))
    live_state = _mapping(live)
    failed = max(0, int(live_state.get("failed") or 0))
    completed = len(records)
    total = max(
        completed + failed,
        int(expected_total) if expected_total is not None else 0,
    )
    stable = _stable_id("settings", key, raw.get("seeds", {}).get(key))
    identifier = _safe_identifier(
        job_id or live_state.get("job_id"), f"job-setting-{stable[:24]}")
    request = _safe_identifier(request_id, identifier)
    fallback = {
        "kind": "setting",
        "seed_key": key,
        "base_seed": (
            raw.get("seeds", {}).get(key)
            if isinstance(raw.get("seeds"), Mapping) else None
        ),
        "task_fingerprints": [
            str(item.get("fingerprint") or "") for _, item in records
        ],
    }
    blueprint_hash, payload_hash = _fingerprints(
        blueprint=blueprint,
        payload_identity=payload_identity,
        fallback=fallback,
    )
    job = new_job(
        "setting",
        blueprint_fingerprint=blueprint_hash,
        payload_hash=payload_hash,
        request_id=request,
        job_id=identifier,
        total=total,
        metadata={
            "legacy_source": "nsfw_seed_state",
            "seed_key": key,
            "base_seed": fallback["base_seed"],
            "plan": {
                "kind": "setting",
                "fingerprint": blueprint_hash,
            },
        },
    )
    for character_id, item in records:
        result_id = "result-setting-" + _stable_id(
            key, character_id, item.get("scene"), item.get("copy"),
            item.get("fingerprint"))[:24]
        job = add_result(
            job,
            result_id,
            artifact=str(item.get("path") or ""),
            source_result_ids=source_results,
        )
    job = update_progress(
        job, completed=completed, failed=failed, total=total)
    legacy_phase = str(live_state.get("phase") or "")
    if legacy_phase in ("completed", "complete"):
        phase = "completed"
    elif legacy_phase == "failed":
        phase = "failed"
    elif legacy_phase == "cancelled":
        phase = "cancelled"
    elif legacy_phase == "running":
        phase = "preparing"
    elif legacy_phase in ("stopped", "stopping", "partial"):
        phase = "paused"
    elif expected_total is not None and total > 0 and completed >= total and not failed:
        phase = "completed"
    else:
        # 디스크 진행 기록만으로 계획 전체 완료를 추측하지 않는다.
        phase = "paused" if completed or failed else "queued"
    job = _set_observed_phase(
        job,
        phase,
        retryable=bool(live_state.get("can_retry", True)),
        at=str(live_state.get("updated_at") or ""),
    )
    return _lineage(
        job,
        source_job_ids=source_jobs,
        source_result_ids=source_results,
    )


def _safe_observation(value: Mapping[str, Any] | None) -> dict:
    raw = _mapping(value)
    results = []
    for item in _list(raw.get("results")):
        if not isinstance(item, Mapping) or not item.get("id"):
            raise JobBridgeError("reconcile result에는 id가 필요합니다.")
        results.append({
            "id": str(item["id"]),
            "artifact": str(item.get("artifact") or ""),
            "content_hash": str(item.get("content_hash") or ""),
            "source_result_ids": [
                str(value) for value in _list(item.get("source_result_ids"))
                if str(value)
            ],
        })
    progress = _mapping(raw.get("progress"))
    safe = {
        "results": results,
        "progress": {
            key: max(0, int(progress.get(key) or 0))
            for key in ("completed", "failed", "total")
        } if progress else {},
        "actual_cost": (
            max(0, float(raw["actual_cost"]))
            if raw.get("actual_cost") is not None else None
        ),
        "artifacts_intact": (
            bool(raw["artifacts_intact"])
            if raw.get("artifacts_intact") is not None else None
        ),
        "confirmed_complete": bool(raw.get("confirmed_complete")),
    }
    return safe


def _handler(kind: str, action: str, metadata: Mapping[str, Any]) -> dict:
    if action in ("pause", "cancel"):
        return {"target": "live_state", "operation": "request_stop"}
    if action in ("retry", "resume"):
        if kind == "comparison":
            return {
                "target": "comparison",
                "operation": "resume",
                "folder": str(
                    (_mapping(metadata.get("plan"))).get("folder") or ""),
            }
        if kind == "setting":
            return {
                "target": "generation",
                "operation": "resume",
                "seed_key": str(metadata.get("seed_key") or ""),
            }
        return {
            "target": "live_state",
            "operation": "retry",
            "retry_mode": str(metadata.get("retry_mode") or ""),
        }
    return {"target": "job_store", "operation": "reconcile"}


def make_job_command(
    job: Mapping[str, Any],
    action: str,
    *,
    observation: Mapping[str, Any] | None = None,
) -> dict:
    """pause/cancel/retry/resume/reconcile을 안전한 legacy 명령으로 변환."""
    clean = validate_job(job)
    action = str(action or "")
    current = clean["phase"]
    try:
        if action == "pause":
            projected = transition_job(clean, "paused")
            safe_observation = None
        elif action == "cancel":
            projected = transition_job(clean, "cancelled")
            safe_observation = None
        elif action == "retry":
            projected = retry_job(clean)
            safe_observation = None
        elif action == "resume":
            if current != "paused":
                raise JobBridgeError("paused Job만 resume할 수 있습니다.")
            projected = transition_job(clean, "queued")
            safe_observation = None
        elif action == "reconcile":
            safe_observation = _safe_observation(observation)
            projected = reconcile_job(clean, safe_observation)
        else:
            raise JobBridgeError(f"지원하지 않는 Job 명령입니다: {action}")
    except JobContractError as exc:
        raise JobBridgeError(str(exc)) from exc

    command = {
        "schema": COMMAND_SCHEMA,
        "action": action,
        "job_id": clean["id"],
        "request_id": clean["request_id"],
        "kind": clean["kind"],
        "expected_phase": current,
        "next_phase": projected["phase"],
        "resource": {
            "key": NAI_RESOURCE_KEY,
            "mode": "exclusive",
            "requires_idle": action in ("retry", "resume"),
        },
        "handler": _handler(clean["kind"], action, clean["metadata"]),
        "identity": {
            "blueprint_fingerprint": clean["blueprint_fingerprint"],
            "payload_hash": clean["payload_hash"],
            "source_job_ids": list(clean["lineage"]["source_job_ids"]),
            "source_result_ids": list(clean["lineage"]["source_result_ids"]),
        },
        "update": {
            "phase": projected["phase"],
            "retry_count": projected["retry"]["count"],
            "completed": projected["progress"]["completed"],
            "failed": projected["progress"]["failed"],
            "actual_cost": projected["cost"]["actual"],
            "result_ids": list(projected["lineage"]["result_ids"]),
        },
    }
    if safe_observation is not None:
        command["observation"] = safe_observation
    # 선택 필드만 조립하므로 원문 prompt/payload/token은 들어올 자리가 없다.
    json.dumps(command, ensure_ascii=False, sort_keys=True)
    return command
