# -*- coding: utf-8 -*-
"""보유 폴더 색인을 원본 수정 없이 작은 묶음으로 감사한다.

이 모듈은 파일 시스템을 직접 열거나 쓰지 않는다. 호출자가 주입한 ``reader``와
``metadata_inspector``만 사용하고, 감사 장부에는 상대 경로·내용 SHA-256과
운영 상태만 남긴다. 이미지 바이트와 추출된 메타데이터는 즉시 버린다.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence

from .restoration_inputs import image_batch_queue


METADATA_AUDIT_SCHEMA = "nai-metadata-audit/v1"
MAX_AUDIT_CHUNK = 500

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_SUPPORTED_KINDS = {
    ".png": "png",
    ".webp": "webp",
    ".json": "json",
}
_FINAL_STATUSES = frozenset({"found", "none", "error"})
_AUDIT_STATUSES = frozenset({
    "pending",
    "running",
    "paused",
    "completed",
    "partial",
})

Reader = Callable[[Mapping[str, str]], bytes]
MetadataInspector = Callable[[bytes, str, str], Any]


def nai_json_metadata(value: Any) -> dict | None:
    """일반 앱 자료 JSON과 NAI 생성 메타데이터 JSON을 좁게 구분한다."""
    if not isinstance(value, dict):
        return None
    candidates = [value]
    for key in ("Comment", "comment", "Description", "description", "metadata"):
        nested = value.get(key)
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        source = " ".join(str(candidate.get(key) or "")
                          for key in ("source", "software", "model")).casefold()
        has_prompt = bool(
            candidate.get("v4_prompt")
            or candidate.get("prompt")
            or candidate.get("description")
        )
        has_generation = (
            any(candidate.get(key) is not None
                for key in ("seed", "steps", "sampler", "scale",
                            "noise_schedule", "ucPreset"))
            and ("novelai" in source or isinstance(candidate.get("v4_prompt"), dict))
        )
        if has_prompt and has_generation:
            return candidate
    return None


def _relative_path(value: Any) -> str:
    """안전한 상대 경로만 반환하고 절대·상위 이동 경로는 버린다."""
    text = str(value or "").strip().replace("\\", "/")
    if not text or "://" in text:
        return ""
    windows_path = PureWindowsPath(text)
    posix_path = PurePosixPath(text)
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or text.startswith("//")
        or ".." in posix_path.parts
    ):
        return ""
    parts = [part for part in posix_path.parts if part not in ("", ".")]
    return "/".join(parts)


def _sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA256_PATTERN.fullmatch(text) else ""


def _kind(path: str) -> str:
    suffix = PurePosixPath(path).suffix.casefold()
    return _SUPPORTED_KINDS.get(suffix, "unsupported")


def _entry(value: Any) -> dict:
    source = dict(value) if isinstance(value, Mapping) else {}
    path = _relative_path(
        source.get("path")
        or source.get("relative_path")
        or source.get("name")
    )
    digest = _sha256(
        source.get("sha256")
        or source.get("content_sha256")
        or source.get("digest")
    )
    if not path:
        error_code = "invalid-relative-path"
    elif not digest:
        error_code = "invalid-sha256"
    else:
        error_code = ""
    return {
        "path": path,
        "sha256": digest,
        "kind": _kind(path),
        "status": "error" if error_code else "pending",
        "attempts": 0,
        "error_code": error_code,
    }


def _canonical_item(value: Any) -> dict:
    source = dict(value) if isinstance(value, Mapping) else {}
    item = _entry(source)
    status = str(source.get("status") or item["status"]).casefold()
    if status not in _FINAL_STATUSES | {"pending"}:
        status = item["status"]
    if item["error_code"]:
        status = "error"
    item["status"] = status
    try:
        item["attempts"] = max(0, int(source.get("attempts") or 0))
    except (TypeError, ValueError):
        item["attempts"] = 0
    error_code = str(source.get("error_code") or "")
    if item["status"] == "error":
        item["error_code"] = error_code or item["error_code"] or "audit-error"
    else:
        item["error_code"] = ""
    return item


def _chunk_size(value: Any) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = MAX_AUDIT_CHUNK
    return max(1, min(MAX_AUDIT_CHUNK, size))


def new_metadata_audit(
    entries: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    chunk_size: int = MAX_AUDIT_CHUNK,
) -> dict:
    """색인 항목을 바이트와 원문 메타데이터가 없는 감사 장부로 만든다."""
    items = [_entry(value) for value in list(entries or ())]
    return {
        "schema": METADATA_AUDIT_SCHEMA,
        "status": "pending" if items else _completion_status(items),
        "cursor": 0,
        "total": len(items),
        "chunk_size": _chunk_size(chunk_size),
        "items": items,
    }


def canonical_metadata_audit(value: Mapping[str, Any] | None) -> dict:
    """외부 상태에서 허용된 장부 필드만 다시 구성한다."""
    source = dict(value) if isinstance(value, Mapping) else {}
    items = [_canonical_item(item) for item in source.get("items") or ()]
    try:
        cursor = int(source.get("cursor") or 0)
    except (TypeError, ValueError):
        cursor = 0
    cursor = max(0, min(len(items), cursor))
    status = str(source.get("status") or "pending").casefold()
    if status not in _AUDIT_STATUSES:
        status = "pending"
    return {
        "schema": METADATA_AUDIT_SCHEMA,
        "status": status,
        "cursor": cursor,
        "total": len(items),
        "chunk_size": _chunk_size(source.get("chunk_size")),
        "items": items,
    }


def _completion_status(items: Sequence[Mapping[str, Any]]) -> str:
    return (
        "partial"
        if any(item.get("status") == "error" for item in items)
        else "completed"
    )


def _inspection_found(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, Mapping):
        if "found" in value:
            return bool(value.get("found"))
        status = str(
            value.get("status")
            or value.get("metadata_status")
            or ""
        ).casefold()
        if status:
            return status in {"found", "ok", "recognized", "present"}
        return bool(value)
    return bool(value)


def _error_code(prefix: str, error: BaseException) -> str:
    """예외 메시지 대신 안정적인 형식 이름만 기록한다."""
    name = type(error).__name__
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "", name)[:80] or "Error"
    return f"{prefix}-{safe_name}"


def _audit_item(
    item: Mapping[str, Any],
    *,
    reader: Reader,
    metadata_inspector: MetadataInspector,
) -> dict:
    result = _canonical_item(item)
    result["attempts"] += 1
    if not result["path"]:
        result["status"] = "error"
        result["error_code"] = "invalid-relative-path"
        return result
    if not result["sha256"]:
        result["status"] = "error"
        result["error_code"] = "invalid-sha256"
        return result
    if result["kind"] == "unsupported":
        result["status"] = "none"
        result["error_code"] = ""
        return result
    read_request = {
        "path": result["path"],
        "sha256": result["sha256"],
    }
    try:
        payload = reader(deepcopy(read_request))
    except Exception as error:  # 호출자 어댑터의 실패를 장부 상태로 격리한다.
        result["status"] = "error"
        result["error_code"] = _error_code("read", error)
        return result
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        result["status"] = "error"
        result["error_code"] = "read-non-bytes"
        return result
    payload_bytes = bytes(payload)
    actual_sha = hashlib.sha256(payload_bytes).hexdigest()
    if actual_sha != result["sha256"]:
        result["status"] = "error"
        result["error_code"] = "content-changed"
        return result
    try:
        inspection = metadata_inspector(
            payload_bytes,
            result["kind"],
            result["path"],
        )
        found = _inspection_found(inspection)
    except Exception as error:  # 원문·경로가 섞일 수 있는 메시지는 보존하지 않는다.
        result["status"] = "error"
        result["error_code"] = _error_code("inspect", error)
        return result
    finally:
        # 바이트와 검사 결과는 이 함수 밖 장부로 절대 전달하지 않는다.
        payload_bytes = b""
    result["status"] = "found" if found else "none"
    result["error_code"] = ""
    return result


def run_metadata_audit_chunk(
    state: Mapping[str, Any],
    *,
    reader: Reader,
    metadata_inspector: MetadataInspector,
) -> dict:
    """현재 cursor에서 최대 500개를 감사하고 다음 묶음 앞에서 멈춘다."""
    audit = canonical_metadata_audit(state)
    if audit["status"] == "paused":
        return audit
    if audit["cursor"] >= audit["total"]:
        audit["status"] = _completion_status(audit["items"])
        return audit

    audit["status"] = "running"
    visited = 0
    cursor = audit["cursor"]
    while cursor < audit["total"] and visited < audit["chunk_size"]:
        item = audit["items"][cursor]
        if item["status"] == "pending":
            audit["items"][cursor] = _audit_item(
                item,
                reader=reader,
                metadata_inspector=metadata_inspector,
            )
        cursor += 1
        visited += 1
    audit["cursor"] = cursor
    audit["status"] = (
        _completion_status(audit["items"])
        if cursor >= audit["total"]
        else "paused"
    )
    return audit


def pause_metadata_audit(state: Mapping[str, Any]) -> dict:
    """완료 전 장부를 읽기 작업 없이 일시 정지한다."""
    audit = canonical_metadata_audit(state)
    if audit["cursor"] < audit["total"]:
        audit["status"] = "paused"
    return audit


def resume_metadata_audit(
    state: Mapping[str, Any],
    *,
    reader: Reader,
    metadata_inspector: MetadataInspector,
) -> dict:
    """일시 정지된 장부에서 다음 묶음 하나를 실행한다."""
    audit = canonical_metadata_audit(state)
    if audit["cursor"] >= audit["total"]:
        audit["status"] = _completion_status(audit["items"])
        return audit
    audit["status"] = "running"
    return run_metadata_audit_chunk(
        audit,
        reader=reader,
        metadata_inspector=metadata_inspector,
    )


def retry_metadata_failures(
    state: Mapping[str, Any],
    *,
    reader: Reader,
    metadata_inspector: MetadataInspector,
    paths: Iterable[str] | None = None,
) -> dict:
    """실패 항목 전체 또는 선택한 상대 경로만 같은 SHA로 다시 검사한다."""
    audit = canonical_metadata_audit(state)
    selected = None
    if paths is not None:
        selected = {
            path
            for path in (_relative_path(value) for value in paths)
            if path
        }
    retried = 0
    for index, item in enumerate(audit["items"]):
        if item["status"] != "error":
            continue
        if selected is not None and item["path"] not in selected:
            continue
        if retried >= audit["chunk_size"]:
            break
        audit["items"][index] = _audit_item(
            item,
            reader=reader,
            metadata_inspector=metadata_inspector,
        )
        retried += 1
    audit["status"] = (
        "paused"
        if audit["cursor"] < audit["total"]
        else _completion_status(audit["items"])
    )
    return audit


def metadata_audit_summary(state: Mapping[str, Any]) -> dict:
    """경로·원문 없이 화면과 작업 큐가 사용할 수치만 반환한다."""
    audit = canonical_metadata_audit(state)
    status_counts = {
        name: sum(item["status"] == name for item in audit["items"])
        for name in ("pending", "found", "none", "error")
    }
    kind_counts = {
        name: sum(item["kind"] == name for item in audit["items"])
        for name in ("png", "webp", "json", "unsupported")
    }
    return {
        "schema": METADATA_AUDIT_SCHEMA,
        "status": audit["status"],
        "cursor": audit["cursor"],
        "total": audit["total"],
        "remaining": max(0, audit["total"] - audit["cursor"]),
        "status_counts": status_counts,
        "kind_counts": kind_counts,
    }


def metadata_audit_failures(state: Mapping[str, Any]) -> list[dict]:
    """재시도 화면에 필요한 실패 상대 경로·SHA·상태만 반환한다."""
    audit = canonical_metadata_audit(state)
    return [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "attempts": item["attempts"],
            "error_code": item["error_code"],
        }
        for item in audit["items"]
        if item["status"] == "error"
    ]


def metadata_audit_restoration_queue(state: Mapping[str, Any]) -> dict:
    """메타데이터가 확인된 항목을 원문 없이 기존 복원 큐 계약에 연결한다."""
    audit = canonical_metadata_audit(state)
    values = [
        {
            "ok": True,
            "filename": item["path"],
            "path": item["path"],
            "content_sha256": item["sha256"],
            "metadata_status": "ok",
            "cursor": index,
        }
        for index, item in enumerate(audit["items"])
        if item["status"] == "found"
    ]
    queue_status = {
        "completed": "completed",
        "partial": "partial",
        "paused": "paused",
    }.get(audit["status"], "pending")
    return image_batch_queue(
        values,
        cursor={"audit_cursor": audit["cursor"]},
        status=queue_status,
    )


def metadata_audit_bundle(state: Mapping[str, Any]) -> dict:
    """저장 가능한 장부와 안전한 요약·재시도 목록·복원 큐를 함께 반환한다."""
    audit = canonical_metadata_audit(state)
    result = {
        "audit": audit,
        "summary": metadata_audit_summary(audit),
        "failures": metadata_audit_failures(audit),
        "restoration_queue": metadata_audit_restoration_queue(audit),
    }
    # 공개 경계가 JSON이며 바이트를 포함하지 않는다는 계약을 즉시 확인한다.
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result


__all__ = [
    "MAX_AUDIT_CHUNK",
    "METADATA_AUDIT_SCHEMA",
    "canonical_metadata_audit",
    "metadata_audit_bundle",
    "metadata_audit_failures",
    "metadata_audit_restoration_queue",
    "metadata_audit_summary",
    "new_metadata_audit",
    "pause_metadata_audit",
    "resume_metadata_audit",
    "retry_metadata_failures",
    "run_metadata_audit_chunk",
]
