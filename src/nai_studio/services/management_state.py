# -*- coding: utf-8 -*-
"""관리 화면의 legacy 작업 장부와 실행 상태 투영 경계."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.nai_studio.runtime import (
    add_result,
    fingerprint_payload,
    from_legacy_job_record,
    new_job,
    reconcile_job,
    transition_job,
    update_progress,
)
from src.nai_studio.domain.blueprint import fingerprint_blueprint


LEDGER_SCHEMA = "nais-job-ledger/v1"
RUNTIME_SCHEMA = "nai-runtime-job/v1"


@dataclass(frozen=True)
class JobLedgerPaths:
    ledger_file: Path

    @property
    def durable_root(self) -> Path:
        return (self.ledger_file.parent / "작업기록").resolve()


@dataclass(frozen=True)
class JobLedgerOperations:
    lock: Any
    load_json: Callable[[Path], Any]
    atomic_write_json: Callable[..., Any]
    common_job_store: Callable[[], Any]
    now: Callable[[], str]
    uuid_hex: Callable[[], str]
    redact: Callable[[Any], str]
    log_error: Callable[..., Any]


@dataclass(frozen=True)
class ConfigProjectionOperations:
    load_settings: Callable[[Path], dict]
    migrate_selections: Callable[[dict], Any]
    migrate_char_slots: Callable[[dict], Any]
    job_summary: Callable[[], dict]
    runtime_kind: Callable[[Any, Any], str]
    inherited_blueprint: Callable[..., dict]
    project_live_state: Callable[..., dict]
    comparison_progress: Callable[[], dict]
    project_comparison_progress: Callable[[dict], dict]
    redact: Callable[[Any], str]


def resolve_common_job_store(
    paths: JobLedgerPaths,
    current_store: Any,
    current_root: Path | None,
    factory: Callable[[Path], Any],
) -> tuple[Any, Path]:
    """프로필 경로가 바뀐 경우에만 durable 저장소를 다시 연다."""
    root = paths.durable_root
    if current_store is None or current_root != root:
        current_store = factory(root)
        current_root = root
    return current_store, current_root


def runtime_kind(operation: Any, legacy_kind: Any) -> str:
    text = f"{operation} {legacy_kind}".casefold()
    if "비교" in text or "comparison" in text:
        return "comparison"
    if "img2img" in text:
        return "img2img"
    if "인페인트" in text or "inpaint" in text:
        return "inpaint"
    if "director" in text or "디렉터" in text:
        return "director"
    if "vibe" in text or "바이브" in text:
        return "vibe_encoding"
    if (
        legacy_kind in ("settings", "generation")
        or "씬" in text
        or "세팅" in text
    ):
        return "setting"
    return "single"


def load_job_ledger(
    paths: JobLedgerPaths,
    operations: JobLedgerOperations,
) -> dict:
    if not paths.ledger_file.is_file():
        return {"schema": LEDGER_SCHEMA, "jobs": []}
    data = operations.load_json(paths.ledger_file)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("작업대기열 기록 형식이 올바르지 않습니다.")
    jobs = [
        dict(item)
        for item in data["jobs"][-200:]
        if isinstance(item, dict) and item.get("id")
    ]
    return {"schema": LEDGER_SCHEMA, "jobs": jobs}


def save_job_ledger(
    paths: JobLedgerPaths,
    operations: JobLedgerOperations,
    data: dict,
) -> dict:
    clean = {
        "schema": LEDGER_SCHEMA,
        "jobs": list(data.get("jobs") or [])[-200:],
    }
    operations.atomic_write_json(
        paths.ledger_file,
        clean,
        indent=1,
    )
    return clean


def recover_job_ledger(
    paths: JobLedgerPaths,
    operations: JobLedgerOperations,
) -> dict:
    """중단된 legacy 기록과 durable lease를 함께 복구한다."""
    with operations.lock:
        data = load_job_ledger(paths, operations)
        changed = False
        now = operations.now()
        for job in data["jobs"]:
            if job.get("status") not in ("running", "stopping"):
                continue
            job["status"] = "interrupted"
            job["updated_at"] = now
            job["can_resume"] = job.get("kind") in (
                "settings",
                "comparison",
                "collection",
                "recovery",
            )
            changed = True
        if changed:
            data = save_job_ledger(paths, operations, data)
        try:
            operations.common_job_store().recover_all()
        except Exception as error:
            operations.log_error(
                "공통 작업 장부 복구 실패: %s",
                error,
            )
        return data


def start_job_record(
    paths: JobLedgerPaths,
    operations: JobLedgerOperations,
    operation: Any,
    kind: Any,
    *,
    blueprint: dict | None = None,
    payload_identity: dict | None = None,
) -> str:
    with operations.lock:
        data = recover_job_ledger(paths, operations)
        now = operations.now()
        record = {
            "id": f"job-{operations.uuid_hex()}",
            "operation": str(operation or "생성")[:120],
            "kind": str(kind or "preview")[:40],
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "completed": 0,
            "failed": 0,
            "can_resume": False,
        }
        data["jobs"].append(record)
        save_job_ledger(paths, operations, data)
        blueprint_digest = fingerprint_blueprint(
            blueprint or {
                "source": {"kind": str(kind or "preview")},
            }
        )
        payload_digest = fingerprint_payload(
            payload_identity or {
                "operation": str(operation or "생성"),
                "kind": str(kind or "preview"),
                "blueprint_fingerprint": blueprint_digest,
            }
        )
        durable = new_job(
            runtime_kind(operation, kind),
            blueprint_fingerprint=blueprint_digest,
            payload_hash=payload_digest,
            request_id=record["id"],
            job_id=record["id"],
            metadata={
                "legacy_kind": str(kind or "preview"),
                "operation": str(operation or "생성"),
            },
            now=now,
        )
        durable = transition_job(durable, "preparing", now=now)
        operations.common_job_store().save(durable)
        return record["id"]


def finish_durable_job(existing: Any, projected: dict) -> dict:
    """관찰값만 합치고 시작할 때 확정한 지문·계보·결과를 보존한다."""
    if not isinstance(existing, dict):
        return projected
    if (
        existing.get("phase") == "cancelled"
        and projected.get("phase") != "cancelled"
    ):
        return existing
    target = str(projected.get("phase") or "")
    progress = copy.deepcopy(projected.get("progress") or {})
    now = str(projected.get("updated_at") or "")
    if target == "completed":
        verified = bool(existing.get("results"))
        return reconcile_job(
            existing,
            {
                "progress": progress,
                "confirmed_complete": verified,
                "artifacts_intact": verified,
            },
            now=now,
        )
    merged = update_progress(
        existing,
        completed=progress.get("completed"),
        failed=progress.get("failed"),
        total=progress.get("total"),
        message=progress.get("message"),
        now=now,
    )
    if (
        target in ("paused", "failed", "cancelled")
        and merged.get("phase") != target
    ):
        merged = transition_job(
            merged,
            target,
            error=(
                copy.deepcopy(projected.get("error"))
                if target == "failed"
                else None
            ),
            now=now,
        )
    return merged


def finish_job_record(
    paths: JobLedgerPaths,
    operations: JobLedgerOperations,
    job_id: str,
    *,
    status: Any,
    completed: Any = 0,
    failed: Any = 0,
    can_resume: Any = False,
    message: Any = "",
) -> None:
    if not job_id:
        return
    with operations.lock:
        data = load_job_ledger(paths, operations)
        for job in reversed(data["jobs"]):
            if job.get("id") != job_id:
                continue
            job.update({
                "status": str(status or "completed"),
                "updated_at": operations.now(),
                "completed": max(0, int(completed or 0)),
                "failed": max(0, int(failed or 0)),
                "can_resume": bool(can_resume),
                "message": str(message or "")[:500],
            })
            projected = from_legacy_job_record(job)
            try:
                existing = operations.common_job_store().get(job_id)
            except Exception:
                existing = None
            operations.common_job_store().save(
                finish_durable_job(existing, projected)
            )
            break
        save_job_ledger(paths, operations, data)


def record_job_result(
    operations: JobLedgerOperations,
    job_id: str,
    path: str | Path,
    *,
    artifact: Any = "",
    source_result_ids: Any = (),
    result_id: Any = "",
) -> dict | None:
    if not job_id:
        return None
    result_path = Path(path)
    if not result_path.is_file():
        raise ValueError(
            "결과 파일을 확인할 수 없어 Job에 완료로 기록하지 않았습니다."
        )
    content_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
    safe_artifact = str(artifact or result_path.name).replace("\\", "/")
    if (
        Path(safe_artifact).is_absolute()
        or ".." in Path(safe_artifact).parts
    ):
        safe_artifact = result_path.name
    stable_result_id = str(result_id or "").strip()
    if not stable_result_id:
        stable_result_id = "result-" + hashlib.sha256(
            f"{job_id}\0{safe_artifact}\0{content_hash}".encode("utf-8")
        ).hexdigest()[:32]
    store = operations.common_job_store()
    changed = add_result(
        store.get(job_id),
        stable_result_id,
        artifact=safe_artifact,
        content_hash=content_hash,
        source_result_ids=source_result_ids,
    )
    store.save(changed)
    return next(
        item
        for item in changed["results"]
        if item.get("id") == stable_result_id
    )


def link_job_ancestor(
    operations: JobLedgerOperations,
    job_id: Any,
    source_job_id: Any,
) -> dict | None:
    current = str(job_id or "")
    source = str(source_job_id or "")
    if not current or not source or current == source:
        return None
    store = operations.common_job_store()
    job = store.get(current)
    ancestry = job.setdefault("lineage", {}).setdefault(
        "source_job_ids",
        [],
    )
    if source not in ancestry:
        ancestry.append(source)
        store.save(job)
    return job


def job_ledger_summary(
    paths: JobLedgerPaths,
    operations: JobLedgerOperations,
) -> dict:
    data = load_job_ledger(paths, operations)
    jobs = list(reversed(data["jobs"]))
    try:
        durable = operations.common_job_store().list()
        durable_by_id = {
            str(item.get("id") or ""): item
            for item in durable
        }
        durable_error = ""
    except Exception as error:
        durable = []
        durable_by_id = {}
        durable_error = operations.redact(error)
    contracts = []
    for item in jobs:
        stored = durable_by_id.get(str(item.get("id") or ""))
        if stored:
            contracts.append(stored)
            continue
        try:
            contracts.append(from_legacy_job_record(item))
        except Exception as error:
            contracts.append({
                "schema": RUNTIME_SCHEMA,
                "id": str(item.get("id") or ""),
                "phase": "invalid",
                "error": operations.redact(error),
            })
    return {
        "ok": True,
        **data,
        "jobs": jobs,
        "contracts": contracts,
        "durable_jobs": list(reversed(durable)),
        "durable_error": durable_error,
    }


def latest_config_from_disk(
    current: dict,
    settings_file: Path,
    defaults: dict,
    operations: ConfigProjectionOperations,
) -> dict:
    """디스크 공용값과 메모리의 `_` 런타임 값만 합친다."""
    runtime = {
        key: value
        for key, value in current.items()
        if str(key).startswith("_")
    }
    latest = {
        key: value
        for key, value in current.items()
        if not str(key).startswith("_")
    }
    if settings_file.is_file():
        latest = operations.load_settings(settings_file)
    merged = dict(defaults)
    merged.update(latest)
    merged.update(runtime)
    operations.migrate_selections(merged)
    operations.migrate_char_slots(merged)
    return merged


def snapshot_jobs(
    server: Any,
    operations: ConfigProjectionOperations,
) -> dict:
    """legacy·durable·현재 실행·비교 manifest를 한 읽기 응답으로 투영한다."""
    summary = operations.job_summary()
    active_contracts = []
    issues = []
    live = server.live.snapshot()
    if live.get("running") or live.get("phase") not in ("", "idle"):
        try:
            frozen = server.live.frozen_blueprint()
            active_contracts.append(operations.project_live_state(
                live,
                kind=operations.runtime_kind(
                    live.get("operation"),
                    live.get("retry_mode"),
                ),
                job_id=live.get("job_id") or "",
                blueprint=(
                    frozen
                    or operations.inherited_blueprint(
                        server.cfg,
                        source={
                            "kind": "live-state-projection-fallback",
                        },
                    )
                ),
                payload_identity={
                    "operation": live.get("operation"),
                    "seed_key": live.get("seed_key"),
                    "total": live.get("total"),
                },
            ))
        except Exception as error:
            issues.append({
                "source": "live-state",
                "error": operations.redact(error),
            })
    progress = operations.comparison_progress()
    live_is_current_comparison = (
        bool(live.get("running"))
        and "비교" in str(live.get("operation") or "")
    )
    if progress.get("signature") and not live_is_current_comparison:
        try:
            active_contracts.append(
                operations.project_comparison_progress(progress)
            )
        except Exception as error:
            issues.append({
                "source": "comparison-progress",
                "error": operations.redact(error),
            })
    summary["active_contracts"] = active_contracts
    summary["projection_issues"] = issues
    return summary


__all__ = [
    "ConfigProjectionOperations",
    "JobLedgerOperations",
    "JobLedgerPaths",
    "finish_durable_job",
    "finish_job_record",
    "job_ledger_summary",
    "latest_config_from_disk",
    "link_job_ancestor",
    "load_job_ledger",
    "record_job_result",
    "recover_job_ledger",
    "resolve_common_job_store",
    "runtime_kind",
    "save_job_ledger",
    "snapshot_jobs",
    "start_job_record",
]
