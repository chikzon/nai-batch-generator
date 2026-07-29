# -*- coding: utf-8 -*-
"""모든 NAI 실행 경로가 공유할 수 있는 순수 Job 계약.

이 모듈은 파일을 쓰거나 스레드를 만들거나 NAI를 호출하지 않는다. 현재
``legacy_app``의 생성·세팅·비교 장부를 한 번에 바꾸지 않고도 각 실행 경로가
동일한 스냅샷을 점진적으로 채택할 수 있게 하는 데이터 모델과 순수 함수만 둔다.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..domain import fingerprint_blueprint


JOB_SCHEMA = "nai-runtime-job/v1"
JOB_KINDS = (
    "single",
    "setting",
    "comparison",
    "img2img",
    "inpaint",
    "director",
    "vibe_encoding",
)
JOB_PHASES = (
    "queued",
    "preparing",
    "sending",
    "receiving",
    "saving",
    "completed",
    "failed",
    "cancelled",
    "paused",
)
TERMINAL_PHASES = frozenset(("completed", "cancelled"))
NAI_RESOURCE_KEY = "novelai-generation-api"

_ACTIVE_PHASES = frozenset(("preparing", "sending", "receiving", "saving"))
_HASH_LENGTH = 64
_SECRET_KEYS = frozenset((
    "access-token",
    "access_token",
    "authorization",
    "api-key",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "password",
    "refresh-token",
    "refresh_token",
    "secret",
    "token",
))
_ALLOWED_TRANSITIONS = {
    "queued": frozenset(("preparing", "paused", "cancelled", "failed")),
    "preparing": frozenset(("sending", "paused", "cancelled", "failed")),
    "sending": frozenset(("receiving", "paused", "cancelled", "failed")),
    "receiving": frozenset(("saving", "paused", "cancelled", "failed")),
    # 저장은 원자 저장 경계다. 반쪽 결과를 막기 위해 시작한 저장을 pause/cancel로
    # 끊지 않고 성공 또는 실패로만 닫는다.
    "saving": frozenset(("completed", "failed")),
    "failed": frozenset(("queued", "cancelled")),
    "paused": frozenset(("queued", "cancelled")),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


class JobContractError(ValueError):
    """Job 스냅샷 또는 상태 전이가 계약을 어겼을 때 발생."""


def _now(value: str | None = None) -> str:
    return str(value) if value else datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _nonnegative_int(value: Any, name: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise JobContractError(f"{name}은 0 이상의 정수여야 합니다.") from exc
    if parsed < 0:
        raise JobContractError(f"{name}은 0 이상의 정수여야 합니다.")
    return parsed


def _nonnegative_number(value: Any, name: str) -> int | float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise JobContractError(f"{name}은 0 이상의 숫자여야 합니다.") from exc
    if parsed < 0:
        raise JobContractError(f"{name}은 0 이상의 숫자여야 합니다.")
    return int(parsed) if parsed.is_integer() else parsed


def _is_hash(value: Any) -> bool:
    text = str(value or "")
    return len(text) == _HASH_LENGTH and all(
        char in "0123456789abcdef" for char in text)


def _without_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace(" ", "")
            if normalized in _SECRET_KEYS:
                continue
            clean[str(key)] = _without_secrets(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_without_secrets(item) for item in value]
    return value


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_payload(payload: Mapping[str, Any] | None) -> str:
    """비밀값을 제외한 실제 NAI 요청 내용의 안정적인 SHA-256 지문."""
    return _stable_hash(_without_secrets(_mapping(payload)))


def _default_retry_policy(value: Mapping[str, Any] | None = None) -> dict:
    raw = _mapping(value)
    maximum = _nonnegative_int(raw.get("max_attempts", 3), "max_attempts")
    if maximum < 1:
        raise JobContractError("max_attempts는 1 이상이어야 합니다.")
    backoff = raw.get("backoff_seconds", (1, 3, 10))
    if not isinstance(backoff, (list, tuple)):
        raise JobContractError("backoff_seconds는 숫자 배열이어야 합니다.")
    return {
        "max_attempts": maximum,
        "backoff_seconds": [
            _nonnegative_number(item, "backoff_seconds") for item in backoff
        ],
        "retryable_codes": [
            str(item) for item in _list(raw.get("retryable_codes")) if str(item)
        ],
    }


def _progress(value: Mapping[str, Any] | None = None) -> dict:
    raw = _mapping(value)
    completed = _nonnegative_int(raw.get("completed"), "progress.completed")
    failed = _nonnegative_int(raw.get("failed"), "progress.failed")
    total = _nonnegative_int(raw.get("total"), "progress.total")
    if total and completed + failed > total:
        raise JobContractError("완료와 실패 수의 합이 전체 작업 수보다 큽니다.")
    denominator = total or max(1, completed + failed)
    return {
        "completed": completed,
        "failed": failed,
        "total": total,
        "ratio": min(1.0, (completed + failed) / denominator),
        "message": str(raw.get("message") or ""),
    }


def new_job(
    kind: str,
    *,
    blueprint: Mapping[str, Any] | None = None,
    blueprint_fingerprint: str = "",
    payload: Mapping[str, Any] | None = None,
    payload_hash: str = "",
    request_id: str = "",
    job_id: str = "",
    total: int = 1,
    cost_preview: int | float = 0,
    retry_policy: Mapping[str, Any] | None = None,
    source_job_ids: Iterable[str] = (),
    source_result_ids: Iterable[str] = (),
    metadata: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> dict:
    """실행 종류와 무관하게 같은 queued 스냅샷을 만든다.

    원문 설계도와 payload는 스냅샷에 저장하지 않는다. 각각의 지문만 남겨 토큰이나
    프롬프트가 실행 장부를 통해 복제되는 일을 막는다.
    """
    kind = str(kind or "")
    if kind not in JOB_KINDS:
        raise JobContractError(f"지원하지 않는 작업 종류입니다: {kind}")
    created_at = _now(now)
    blueprint_digest = str(blueprint_fingerprint or "")
    if blueprint is not None:
        blueprint_digest = fingerprint_blueprint(blueprint)
    payload_digest = str(payload_hash or "")
    if payload is not None:
        payload_digest = fingerprint_payload(payload)
    if not _is_hash(blueprint_digest):
        raise JobContractError("blueprint_fingerprint는 SHA-256이어야 합니다.")
    if not _is_hash(payload_digest):
        raise JobContractError("payload_hash는 SHA-256이어야 합니다.")
    stable_request_id = str(request_id or f"req-{uuid.uuid4().hex}")
    record = {
        "schema": JOB_SCHEMA,
        "id": str(job_id or f"job-{uuid.uuid4().hex}"),
        "request_id": stable_request_id,
        "kind": kind,
        "phase": "queued",
        "blueprint_fingerprint": blueprint_digest,
        "payload_hash": payload_digest,
        "cost": {
            "unit": "anlas",
            "preview": _nonnegative_number(cost_preview, "cost.preview"),
            "actual": None,
        },
        "retry": {
            "count": 0,
            "policy": _default_retry_policy(retry_policy),
        },
        "progress": _progress({"total": total}),
        "resource": {
            "key": NAI_RESOURCE_KEY,
            "mode": "exclusive",
            "lease": None,
        },
        "lineage": {
            "source_job_ids": [str(item) for item in source_job_ids if str(item)],
            "source_result_ids": [
                str(item) for item in source_result_ids if str(item)
            ],
            "result_ids": [],
        },
        "results": [],
        "error": None,
        "metadata": _mapping(metadata),
        "created_at": created_at,
        "updated_at": created_at,
        "phase_history": [{"phase": "queued", "at": created_at}],
    }
    return validate_job(record)


def canonical_job(value: Mapping[str, Any]) -> dict:
    """현재 스키마를 정규화하고 모르는 확장 필드는 보존한다."""
    raw = _mapping(value)
    if raw.get("schema") != JOB_SCHEMA:
        raise JobContractError("지원하지 않는 Job 스냅샷 버전입니다.")
    result = {
        "schema": JOB_SCHEMA,
        "id": str(raw.get("id") or ""),
        "request_id": str(raw.get("request_id") or ""),
        "kind": str(raw.get("kind") or ""),
        "phase": str(raw.get("phase") or ""),
        "blueprint_fingerprint": str(raw.get("blueprint_fingerprint") or ""),
        "payload_hash": str(raw.get("payload_hash") or ""),
        "cost": _mapping(raw.get("cost")),
        "retry": _mapping(raw.get("retry")),
        "progress": _progress(raw.get("progress")),
        "resource": _mapping(raw.get("resource")),
        "lineage": _mapping(raw.get("lineage")),
        "results": _list(raw.get("results")),
        "error": deepcopy(raw.get("error")),
        "metadata": _mapping(raw.get("metadata")),
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "phase_history": _list(raw.get("phase_history")),
    }
    for key, item in raw.items():
        if key not in result:
            result[key] = deepcopy(item)
    return result


def validate_job(value: Mapping[str, Any]) -> dict:
    """스냅샷을 검증하고 입력을 건드리지 않은 정규화 사본을 반환."""
    job = canonical_job(value)
    if not job["id"] or not job["request_id"]:
        raise JobContractError("Job id와 request id가 필요합니다.")
    if job["kind"] not in JOB_KINDS:
        raise JobContractError(f"지원하지 않는 작업 종류입니다: {job['kind']}")
    if job["phase"] not in JOB_PHASES:
        raise JobContractError(f"지원하지 않는 작업 단계입니다: {job['phase']}")
    if not _is_hash(job["blueprint_fingerprint"]):
        raise JobContractError("blueprint_fingerprint는 SHA-256이어야 합니다.")
    if not _is_hash(job["payload_hash"]):
        raise JobContractError("payload_hash는 SHA-256이어야 합니다.")

    cost = job["cost"]
    if str(cost.get("unit") or "") != "anlas":
        raise JobContractError("비용 단위는 anlas여야 합니다.")
    cost["preview"] = _nonnegative_number(cost.get("preview"), "cost.preview")
    if cost.get("actual") is not None:
        cost["actual"] = _nonnegative_number(cost["actual"], "cost.actual")

    retry = job["retry"]
    retry["count"] = _nonnegative_int(retry.get("count"), "retry.count")
    retry["policy"] = _default_retry_policy(retry.get("policy"))
    if retry["count"] >= retry["policy"]["max_attempts"]:
        # count는 이미 수행한 재시도 수이고 최초 시도는 1회다.
        raise JobContractError("retry.count가 허용 재시도 범위를 벗어났습니다.")

    resource = job["resource"]
    if resource.get("key") != NAI_RESOURCE_KEY or resource.get("mode") != "exclusive":
        raise JobContractError("NAI 호출은 공통 exclusive resource를 사용해야 합니다.")
    lease = resource.get("lease")
    if lease is not None:
        if not isinstance(lease, Mapping):
            raise JobContractError("resource.lease 형식이 올바르지 않습니다.")
        lease = _mapping(lease)
        if not lease.get("id") or not lease.get("owner_id"):
            raise JobContractError("lease id와 owner id가 필요합니다.")
        resource["lease"] = lease
        if job["phase"] not in _ACTIVE_PHASES:
            raise JobContractError("활성 단계가 아닌 Job은 NAI lease를 가질 수 없습니다.")

    lineage = job["lineage"]
    for key in ("source_job_ids", "source_result_ids", "result_ids"):
        lineage[key] = [str(item) for item in _list(lineage.get(key)) if str(item)]
    result_ids = [
        str(item.get("id")) for item in job["results"]
        if isinstance(item, Mapping) and item.get("id")
    ]
    if result_ids != lineage["result_ids"]:
        raise JobContractError("results와 lineage.result_ids가 일치하지 않습니다.")
    if not job["created_at"] or not job["updated_at"]:
        raise JobContractError("created_at과 updated_at이 필요합니다.")
    if not job["phase_history"]:
        raise JobContractError("phase_history가 비어 있습니다.")
    if str(job["phase_history"][-1].get("phase") or "") != job["phase"]:
        raise JobContractError("phase_history의 마지막 단계가 현재 단계와 다릅니다.")
    return job


def transition_job(
    value: Mapping[str, Any],
    phase: str,
    *,
    error: Mapping[str, Any] | None = None,
    message: str | None = None,
    now: str | None = None,
) -> dict:
    """허용된 상태 전이만 적용한 새 스냅샷을 반환."""
    job = validate_job(value)
    target = str(phase or "")
    if target not in _ALLOWED_TRANSITIONS[job["phase"]]:
        raise JobContractError(
            f"허용되지 않는 단계 전이입니다: {job['phase']} -> {target}")
    if target == "failed" and not isinstance(error, Mapping):
        raise JobContractError("실패 단계에는 error가 필요합니다.")
    changed_at = _now(now)
    job["phase"] = target
    job["updated_at"] = changed_at
    job["phase_history"].append({"phase": target, "at": changed_at})
    job["error"] = _mapping(error) if target == "failed" else None
    if message is not None:
        job["progress"]["message"] = str(message)
    if target not in _ACTIVE_PHASES:
        job["resource"]["lease"] = None
    return validate_job(job)


def update_progress(
    value: Mapping[str, Any],
    *,
    completed: int | None = None,
    failed: int | None = None,
    total: int | None = None,
    message: str | None = None,
    now: str | None = None,
) -> dict:
    job = validate_job(value)
    raw = dict(job["progress"])
    if completed is not None:
        raw["completed"] = completed
    if failed is not None:
        raw["failed"] = failed
    if total is not None:
        raw["total"] = total
    if message is not None:
        raw["message"] = str(message)
    job["progress"] = _progress(raw)
    job["updated_at"] = _now(now)
    return validate_job(job)


def update_cost(
    value: Mapping[str, Any],
    *,
    preview: int | float | None = None,
    actual: int | float | None = None,
    now: str | None = None,
) -> dict:
    job = validate_job(value)
    if preview is not None:
        job["cost"]["preview"] = _nonnegative_number(preview, "cost.preview")
    if actual is not None:
        job["cost"]["actual"] = _nonnegative_number(actual, "cost.actual")
    job["updated_at"] = _now(now)
    return validate_job(job)


def acquire_lease(
    value: Mapping[str, Any],
    owner_id: str,
    *,
    lease_id: str = "",
    acquired_at: str | None = None,
    expires_at: str = "",
) -> dict:
    """현재 Job에 공통 NAI exclusive lease를 표시한다.

    서로 다른 Job 사이의 실제 상호 배제는 후속 실행 엔진이 같은 resource key를
    기준으로 수행한다.
    """
    job = validate_job(value)
    if job["phase"] not in _ACTIVE_PHASES:
        raise JobContractError("NAI lease는 활성 실행 단계에서만 얻을 수 있습니다.")
    if job["resource"].get("lease") is not None:
        raise JobContractError("Job이 이미 NAI lease를 가지고 있습니다.")
    owner = str(owner_id or "")
    if not owner:
        raise JobContractError("lease owner id가 필요합니다.")
    job["resource"]["lease"] = {
        "id": str(lease_id or f"lease-{uuid.uuid4().hex}"),
        "owner_id": owner,
        "acquired_at": _now(acquired_at),
        "expires_at": str(expires_at or ""),
    }
    job["updated_at"] = job["resource"]["lease"]["acquired_at"]
    return validate_job(job)


def release_lease(
    value: Mapping[str, Any],
    lease_id: str,
    *,
    now: str | None = None,
) -> dict:
    job = validate_job(value)
    lease = job["resource"].get("lease")
    if not isinstance(lease, Mapping) or lease.get("id") != str(lease_id or ""):
        raise JobContractError("현재 소유한 lease와 id가 일치하지 않습니다.")
    job["resource"]["lease"] = None
    job["updated_at"] = _now(now)
    return validate_job(job)


def lease_expired(value: Mapping[str, Any], *, now: str | None = None) -> bool:
    job = validate_job(value)
    lease = job["resource"].get("lease")
    if not isinstance(lease, Mapping) or not lease.get("expires_at"):
        return False
    try:
        expires = datetime.fromisoformat(
            str(lease["expires_at"]).replace("Z", "+00:00"))
        current = datetime.fromisoformat(_now(now).replace("Z", "+00:00"))
    except ValueError as exc:
        raise JobContractError("lease 시각 형식이 올바르지 않습니다.") from exc
    return expires <= current


def retry_job(
    value: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict:
    """실패한 논리 Job의 request id를 유지한 채 다음 시도를 queued로 만든다."""
    job = validate_job(value)
    if job["phase"] != "failed":
        raise JobContractError("실패한 Job만 재시도할 수 있습니다.")
    error = job.get("error") if isinstance(job.get("error"), Mapping) else {}
    if not error.get("retryable"):
        raise JobContractError("재시도할 수 없는 실패입니다.")
    policy = job["retry"]["policy"]
    next_count = job["retry"]["count"] + 1
    if next_count >= policy["max_attempts"]:
        raise JobContractError("허용된 최대 시도 횟수를 모두 사용했습니다.")
    job["retry"]["count"] = next_count
    changed_at = _now(now)
    job["phase"] = "queued"
    job["updated_at"] = changed_at
    job["phase_history"].append({"phase": "queued", "at": changed_at})
    job["error"] = None
    job["resource"]["lease"] = None
    return validate_job(job)


def add_result(
    value: Mapping[str, Any],
    result_id: str,
    *,
    artifact: str = "",
    content_hash: str = "",
    source_result_ids: Iterable[str] = (),
    now: str | None = None,
) -> dict:
    job = validate_job(value)
    identifier = str(result_id or "")
    if not identifier:
        raise JobContractError("result id가 필요합니다.")
    if identifier in job["lineage"]["result_ids"]:
        return job
    if content_hash and not _is_hash(content_hash):
        raise JobContractError("result content_hash는 SHA-256이어야 합니다.")
    record = {
        "id": identifier,
        "artifact": str(artifact or ""),
        "content_hash": str(content_hash or ""),
        "source_result_ids": [
            str(item) for item in source_result_ids if str(item)
        ],
    }
    job["results"].append(record)
    job["lineage"]["result_ids"].append(identifier)
    job["updated_at"] = _now(now)
    return validate_job(job)


def snapshot_to_json(value: Mapping[str, Any], *, indent: int | None = 2) -> str:
    """원자 저장 도우미에 넘길 수 있는 UTF-8 JSON 문자열."""
    return json.dumps(
        validate_job(value), ensure_ascii=False, sort_keys=True, indent=indent)


def snapshot_from_json(value: str | bytes | Mapping[str, Any]) -> dict:
    if isinstance(value, Mapping):
        raw = value
    else:
        try:
            raw = json.loads(value.decode("utf-8-sig") if isinstance(value, bytes)
                             else value)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JobContractError("Job 스냅샷 JSON을 읽을 수 없습니다.") from exc
    if not isinstance(raw, Mapping):
        raise JobContractError("Job 스냅샷 최상위 값은 객체여야 합니다.")
    return validate_job(raw)


def recover_job(
    value: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict:
    """프로세스 재시작 시 불확실한 실행을 paused로 회수한다.

    queued와 종결 Job은 그대로 유지한다. sending/receiving 중 실제 서버가 작업을
    끝냈을 가능성은 ``reconcile_job``에 관찰 결과를 넣어 판정한다.
    """
    job = validate_job(value)
    if job["phase"] not in _ACTIVE_PHASES:
        return job
    changed_at = _now(now)
    interrupted = job["phase"]
    job["phase"] = "paused"
    job["resource"]["lease"] = None
    job["updated_at"] = changed_at
    job["phase_history"].append({"phase": "paused", "at": changed_at})
    job["error"] = {
        "code": "runtime-interrupted",
        "message": f"{interrupted} 단계에서 앱이 종료되어 결과 확인이 필요합니다.",
        "retryable": True,
    }
    return validate_job(job)


def reconcile_job(
    value: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict:
    """스테이징/결과 스캔처럼 외부에서 확인한 사실을 스냅샷에 합친다.

    파일 탐색 자체는 하지 않는다. 호출자가 검증한 result 목록과 비용·진행 수만
    전달하므로 함수는 테스트와 재시작 복구에서 결정적으로 동작한다.
    """
    job = recover_job(value, now=now)
    seen = set(job["lineage"]["result_ids"])
    for item in _list(observation.get("results")):
        if not isinstance(item, Mapping) or not item.get("id"):
            raise JobContractError("reconcile results에는 id가 필요합니다.")
        identifier = str(item["id"])
        if identifier in seen:
            continue
        job = add_result(
            job,
            identifier,
            artifact=str(item.get("artifact") or ""),
            content_hash=str(item.get("content_hash") or ""),
            source_result_ids=item.get("source_result_ids") or (),
            now=now,
        )
        seen.add(identifier)

    progress = _mapping(observation.get("progress"))
    if progress:
        job = update_progress(
            job,
            completed=progress.get("completed"),
            failed=progress.get("failed"),
            total=progress.get("total"),
            message=progress.get("message"),
            now=now,
        )
    if observation.get("actual_cost") is not None:
        job = update_cost(job, actual=observation["actual_cost"], now=now)

    artifacts_intact = observation.get("artifacts_intact")
    confirmed_complete = bool(observation.get("confirmed_complete"))
    total = job["progress"]["total"]
    completed = job["progress"]["completed"]
    failed = job["progress"]["failed"]
    if confirmed_complete and artifacts_intact is not False:
        if total and completed + failed < total:
            raise JobContractError("완료 확인과 진행 수치가 일치하지 않습니다.")
        # reconcile은 paused/failed 스냅샷도 확정 결과로 닫을 수 있다.
        changed_at = _now(now)
        job["phase"] = "completed"
        job["error"] = None
        job["updated_at"] = changed_at
        job["phase_history"].append({"phase": "completed", "at": changed_at})
    elif artifacts_intact is False:
        changed_at = _now(now)
        if job["phase"] == "completed":
            # 완료 기록보다 실제 결과 보존을 우선한다.
            job["phase"] = "paused"
            job["phase_history"].append({"phase": "paused", "at": changed_at})
        job["error"] = {
            "code": "artifact-missing",
            "message": "기록된 결과 일부를 찾지 못해 재조정이 필요합니다.",
            "retryable": True,
        }
        job["updated_at"] = changed_at
    return validate_job(job)


def _legacy_hash(value: Mapping[str, Any], label: str) -> str:
    return _stable_hash({"legacy": label, "value": _without_secrets(value)})


def from_legacy_job_record(
    value: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict:
    """현재 ``작업대기열.json`` 한 행을 공통 계약으로 읽는 호환 어댑터."""
    raw = _mapping(value)
    legacy_kind = str(raw.get("kind") or "preview")
    kind = {
        "preview": "single",
        "library": "single",
        "generation": "setting",
        "settings": "setting",
        "comparison": "comparison",
        "img2img": "img2img",
        "inpaint": "inpaint",
        "director": "director",
        "vibe_encoding": "vibe_encoding",
    }.get(legacy_kind, "single")
    status = str(raw.get("status") or "interrupted")
    phase = {
        "running": "paused",
        "stopping": "paused",
        "interrupted": "paused",
        "stopped": "paused",
        "partial": "paused",
        "completed": "completed",
        "complete": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(status, "queued")
    created = str(raw.get("created_at") or _now(now))
    updated = str(raw.get("updated_at") or created)
    completed = _nonnegative_int(raw.get("completed"), "completed")
    failed = _nonnegative_int(raw.get("failed"), "failed")
    job = new_job(
        kind,
        blueprint_fingerprint=_legacy_hash(raw, "blueprint"),
        payload_hash=_legacy_hash(raw, "payload"),
        request_id=str(raw.get("request_id") or raw.get("id") or ""),
        job_id=str(raw.get("id") or ""),
        total=completed + failed,
        metadata={
            "legacy_schema": "nais-job-ledger/v1",
            "legacy_kind": legacy_kind,
            "operation": str(raw.get("operation") or ""),
            "can_resume": bool(raw.get("can_resume")),
        },
        now=created,
    )
    job = update_progress(
        job, completed=completed, failed=failed,
        message=str(raw.get("message") or ""), now=updated)
    if phase != "queued":
        job["phase"] = phase
        job["updated_at"] = updated
        job["phase_history"].append({"phase": phase, "at": updated})
        if phase == "failed":
            job["error"] = {
                "code": "legacy-failure",
                "message": str(raw.get("message") or "기존 작업 실패"),
                "retryable": bool(raw.get("can_resume")),
            }
    return validate_job(job)


def from_comparison_progress(
    value: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict:
    """현재 비교 ``manifest.json``을 공통 Job으로 읽는 호환 어댑터."""
    raw = _mapping(value)
    plan = _mapping(raw.get("plan"))
    completed_rows = _mapping(raw.get("completed"))
    error_rows = _mapping(raw.get("errors"))
    signature = str(raw.get("signature") or "")
    blueprint_digest = signature if _is_hash(signature) else _legacy_hash(
        {"plan": plan, "recipe_context": raw.get("recipe_context")},
        "comparison-blueprint",
    )
    created = str(raw.get("created_at") or _now(now))
    updated = str(raw.get("updated_at") or created)
    job = new_job(
        "comparison",
        blueprint_fingerprint=blueprint_digest,
        payload_hash=_legacy_hash(plan, "comparison-payload"),
        request_id=str(raw.get("request_id") or ""),
        job_id=str(raw.get("job_id") or ""),
        total=_nonnegative_int(plan.get("count"), "plan.count")
              or len(completed_rows) + len(error_rows),
        metadata={
            "legacy_schema": "comparison-progress/v1",
            "folder": str(raw.get("folder") or ""),
            "mode": str(raw.get("mode") or ""),
            "mode_label": str(raw.get("mode_label") or ""),
        },
        now=created,
    )
    for key, item in completed_rows.items():
        record = item if isinstance(item, Mapping) else {"file": item}
        job = add_result(
            job, str(key), artifact=str(record.get("file") or ""), now=updated)
    job = update_progress(
        job,
        completed=len(completed_rows),
        failed=len(error_rows),
        message=str(raw.get("status") or ""),
        now=updated,
    )
    phase = {
        "running": "paused",
        "partial": "paused",
        "stopped": "paused",
        "failed": "failed",
        "complete": "completed",
        "completed": "completed",
    }.get(str(raw.get("status") or ""), "queued")
    if phase != "queued":
        job["phase"] = phase
        job["updated_at"] = updated
        job["phase_history"].append({"phase": phase, "at": updated})
        if phase == "failed":
            job["error"] = {
                "code": "comparison-failure",
                "message": "비교 생성 일부 또는 전체가 실패했습니다.",
                "retryable": True,
            }
    return validate_job(job)
