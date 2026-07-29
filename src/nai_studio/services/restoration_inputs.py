# -*- coding: utf-8 -*-
"""레거시 임포트 입력을 안전한 설계도 복원 후보로 투영한다.

이 모듈은 파일을 읽거나 저장하지 않는다. 단건 이미지, 게시글 수집, 자료팩,
보유 폴더가 이미 만들어 낸 메모리 레코드를 같은 복원 큐 계약으로 바꿀 뿐이다.
원본 메타데이터와 생성값은 보존하지만 토큰, 절대경로, 이미지 바이트는 계약
JSON의 경계를 넘기지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.nai_studio.domain.evidence import canonical_evidence
from src.nai_studio.domain.restoration import (
    canonical_restore_queue,
    enqueue_restore_items,
    resume_restore_queue,
)


RESTORATION_INPUT_SCHEMA = "nai-restoration-input/v1"

_BINARY_KEYS = frozenset({
    "binary",
    "blob",
    "body",
    "bytes_data",
    "data_base64",
    "file_bytes",
    "image_base64",
    "image_bytes",
    "raw_bytes",
})
_SECRET_QUERY_KEYS = frozenset({
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "key",
    "secret",
    "sig",
    "signature",
    "token",
})
_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:pst-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._~+/-]{12,})"
)
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\r\n\t\"'<>|]+|"
    r"\\\\[^\\/\s]+[\\/][^\r\n\t\"'<>|]+)"
)
_POSIX_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9:])/(?:home|Users|var|tmp|opt|root|mnt|srv|private)"
    r"(?:/[^\s\r\n\t\"'<>|]+)+"
)


def _record(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _is_absolute_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text or "://" in text:
        return False
    return (
        PureWindowsPath(text).is_absolute()
        or PurePosixPath(text).is_absolute()
        or text.startswith("\\\\")
    )


def _safe_locator(value: Any) -> str:
    """절대경로를 노출하지 않으면서 동일 파일 위치의 계보 키를 만든다."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not _is_absolute_path(text):
        return text.replace("\\", "/")
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    return f"path-sha256:{digest}"


def _safe_filename(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1] if text else ""


def _safe_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return _TOKEN_PATTERN.sub("[secret]", text)
    if parts.scheme not in ("http", "https"):
        return _TOKEN_PATTERN.sub("[secret]", text)
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None:
        netloc += f":{port}"
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _SECRET_QUERY_KEYS
    ]
    return urlunsplit((
        parts.scheme,
        netloc,
        parts.path,
        urlencode(query, doseq=True),
        "",
    ))


def _safe_string(value: str) -> str:
    text = _TOKEN_PATTERN.sub("[secret]", value)
    if _is_absolute_path(text):
        return "[absolute-path]"
    text = _WINDOWS_PATH_PATTERN.sub("[absolute-path]", text)
    return _POSIX_PATH_PATTERN.sub("[absolute-path]", text)


def _is_secret_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value or "").casefold())
    return (
        normalized in {
            "authorization", "apikey", "apitoken", "accesstoken",
            "naitoken", "persistenttoken", "cookie", "password",
            "secret", "setcookie", "refreshtoken",
        }
        or normalized.endswith("token")
    )


def _safe_json(value: Any, *, key: str = "") -> Any:
    """JSON 호환 사본을 만들며 비밀값·바이너리·절대경로만 제거한다."""
    folded = str(key or "").casefold()
    if _is_secret_key(key) or folded in _BINARY_KEYS:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, Mapping):
        result = {}
        for raw_key, raw_item in value.items():
            item_key = str(raw_key)
            if _is_secret_key(item_key) or item_key.casefold() in _BINARY_KEYS:
                continue
            safe = _safe_json(raw_item, key=item_key)
            if safe is not None:
                result[item_key] = safe
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            safe = _safe_json(item, key=key)
            if safe is not None:
                result.append(safe)
        return result
    if isinstance(value, str):
        if folded.endswith("url") or folded in {"url", "post_url", "source_url"}:
            return _safe_url(value)
        if "path" in folded or folded in {"cwd", "root"}:
            return _safe_locator(value)
        return _safe_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return deepcopy(value)
    return _safe_string(str(value))


def _json_copy(value: Any) -> Any:
    safe = _safe_json(value)
    # 서비스 경계에서 JSON 직렬화 가능 여부를 즉시 검증한다.
    json.dumps(safe, ensure_ascii=False, allow_nan=False)
    return safe


def _content_hash(record: Mapping[str, Any]) -> str:
    for key in (
        "content_sha256",
        "archive_sha256",
        "content_hash",
        "sha256",
        "digest",
        "hash",
    ):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def _image_refs(record: Mapping[str, Any]) -> list[str]:
    raw = record.get("images")
    if raw is None:
        raw = record.get("image_refs")
    if raw is None and record.get("image_ref") is not None:
        raw = [record.get("image_ref")]
    if isinstance(raw, (str, Mapping)):
        raw = [raw]
    refs = []
    for item in raw or []:
        if isinstance(item, Mapping):
            value = (
                item.get("uri")
                or item.get("url")
                or item.get("source_url")
                or item.get("path")
            )
        else:
            value = item
        text = str(value or "").strip()
        if not text:
            continue
        if text.startswith(("http://", "https://")):
            ref = _safe_url(text)
        elif text.startswith("local:"):
            local_value = text[6:]
            if _is_absolute_path(local_value):
                digest = hashlib.sha256(
                    local_value.encode("utf-8", "surrogatepass")
                ).hexdigest()[:20]
                ref = f"local-file:{_safe_filename(local_value)}:{digest}"
            else:
                ref = text
        elif _is_absolute_path(text):
            digest = hashlib.sha256(
                text.encode("utf-8", "surrogatepass")
            ).hexdigest()[:20]
            ref = f"local-file:{_safe_filename(text)}:{digest}"
        else:
            ref = text.replace("\\", "/")
        if ref not in refs:
            refs.append(ref)
    return refs


def _generation_values(record: Mapping[str, Any]) -> dict:
    params = record.get("params")
    if not isinstance(params, Mapping):
        params = record.get("settings")
    if not isinstance(params, Mapping):
        params = record.get("generation_settings")
    return _json_copy({
        "base": record.get("base", record.get("prompt", "")),
        "negative": record.get(
            "negative_full",
            record.get("negative", record.get("negative_prompt", "")),
        ),
        "characters": record.get("characters") or [],
        "settings": params or {},
    })


def _evidence_candidate(
    record: Mapping[str, Any],
    *,
    source_kind: str,
    source_url: str = "",
    filename: str = "",
) -> dict:
    metadata = record.get("metadata_raw")
    if metadata is None:
        metadata = record.get("raw_metadata")
    if metadata is None:
        metadata = record.get("metadata")
    evidence = canonical_evidence({
        "kind": "generation-record",
        "image": {
            "refs": _image_refs(record),
            "content_sha256": _content_hash(record),
            "filename": _safe_filename(
                filename
                or record.get("filename")
                or record.get("title")
                or record.get("name")
            ),
        },
        "source": {
            "kind": str(source_kind or "unknown"),
            "url": _safe_url(
                source_url
                or record.get("source_url")
                or record.get("url")
                or record.get("post_url")
            ),
            "posted_at": _json_copy(
                record.get("posted_at") or record.get("date") or ""
            ),
        },
        "raw_metadata": _json_copy(metadata),
        "actual_generation": _generation_values(record),
        "evaluation": _json_copy(record.get("evaluation") or {}),
    })
    return evidence


def _restore_item(
    record: Mapping[str, Any],
    *,
    source_kind: str,
    source_url: str = "",
    filename: str = "",
    source_id: str = "",
    status: str | None = None,
    attempts: int = 0,
    error: Any = None,
) -> dict:
    data = _record(record)
    url = _safe_url(
        source_url
        or data.get("source_url")
        or data.get("url")
        or data.get("post_url")
    )
    candidate = _evidence_candidate(
        data,
        source_kind=source_kind,
        source_url=url,
        filename=filename,
    )
    if status is None:
        if data.get("ok") is False:
            status = (
                "unrecognized"
                if str(data.get("metadata_status") or "").casefold()
                in {"missing", "none", "unrecognized"}
                else "failed"
            )
        elif (
            data.get("ok") is True
            or data.get("metadata_status") == "ok"
            or data.get("style")
        ):
            status = "recognized"
        else:
            status = "pending"
    recognition = {
        "status": status,
        "attempts": max(0, int(attempts or 0)),
        "history": _json_copy(data.get("history") or []),
    }
    if error not in (None, ""):
        recognition["error"] = _json_copy(error)
    locator = source_id or data.get("source_id") or data.get("path")
    source = {
        "kind": source_kind,
        "url": url,
        "post_url": _safe_url(data.get("post_url") or url),
        "source_id": _safe_locator(locator),
        "filename": _safe_filename(
            filename
            or data.get("filename")
            or data.get("title")
            or data.get("name")
            or data.get("path")
        ),
    }
    return {
        "source": source,
        "images": _image_refs(data),
        "content_hash": _content_hash(data),
        "raw_metadata": candidate["raw_metadata"],
        "detected_fields": candidate["actual_generation"],
        "recognition": recognition,
        "cursor": _json_copy(data.get("cursor")),
        "date": _json_copy(
            data.get("date")
            or data.get("posted_at")
            or data.get("updated_at")
        ),
        "relations": _json_copy(data.get("relations") or {}),
        "result": {
            "evidence_candidate": candidate,
            "blueprint_candidate": _json_copy(
                data.get("blueprint_candidate") or {}
            ),
        },
    }


def _new_queue(
    source_kind: str,
    *,
    status: str = "pending",
    cursor: Any = None,
    date_range: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict:
    return canonical_restore_queue({
        "source": {"kind": source_kind},
        "status": str(status or "pending"),
        "cursor": _json_copy(cursor),
        "date_range": _json_copy(date_range or {}),
        "metadata": {
            "schema": RESTORATION_INPUT_SCHEMA,
            **_json_copy(metadata or {}),
        },
        "items": [],
    })


def image_inspect_queue(
    value: Mapping[str, Any],
    *,
    filename: str = "",
    source_url: str = "",
) -> dict:
    """단건 `/api/inspect` 응답을 복원 후보 한 건으로 투영한다."""
    raw = _record(value)
    record = raw.get("style") if isinstance(raw.get("style"), Mapping) else raw
    item = _restore_item(
        record,
        source_kind="image",
        source_url=source_url,
        filename=filename,
        status=(
            "recognized"
            if raw.get("ok") is True
            else "failed" if raw.get("error") else None
        ),
        attempts=1 if raw.get("ok") is not None else 0,
        error=raw.get("error"),
    )
    return enqueue_restore_items(
        _new_queue("image", status="completed" if raw.get("ok") else "failed"),
        [item],
    )


def image_batch_queue(
    values: Sequence[Mapping[str, Any]],
    *,
    cursor: Any = None,
    status: str = "pending",
) -> dict:
    """여러 이미지의 추출 결과를 순서·실패를 잃지 않는 한 큐로 만든다."""
    queue = _new_queue("image-batch", status=status, cursor=cursor)
    items = []
    for index, value in enumerate(values or ()):
        raw = _record(value)
        record = raw.get("style") if isinstance(raw.get("style"), Mapping) else raw
        merged = {**record, "cursor": raw.get("cursor", index)}
        items.append(_restore_item(
            merged,
            source_kind="image",
            filename=str(
                raw.get("filename")
                or record.get("filename")
                or record.get("title")
                or ""
            ),
            status=(
                "recognized"
                if raw.get("ok") is True
                else "failed" if raw.get("error") else None
            ),
            attempts=int(raw.get("attempts") or (1 if "ok" in raw else 0)),
            error=raw.get("error"),
        ))
    return enqueue_restore_items(queue, items)


def public_collection_queue(value: Mapping[str, Any]) -> dict:
    """게시글 수집 상태를 날짜·cursor·중단/재개·실패 이력과 함께 투영한다."""
    state = _record(value)
    articles = (
        state.get("articles")
        if isinstance(state.get("articles"), Mapping)
        else {}
    )
    failures = (
        state.get("failures")
        if isinstance(state.get("failures"), Mapping)
        else {}
    )
    queue = _new_queue(
        "public-collection",
        status=str(state.get("status") or "idle"),
        cursor=state.get("cursor"),
        date_range=state.get("date_range") or {
            "from": state.get("date_from"),
            "to": state.get("date_to"),
        },
        metadata={
            "legacy_schema": state.get("schema"),
            "stage": state.get("stage"),
            "keyword": state.get("keyword"),
        },
    )
    items = []
    urls = list(dict.fromkeys([
        *list(state.get("queue") or []),
        *[str(url) for url in articles],
        *[str(url) for url in failures],
    ]))
    for index, raw_url in enumerate(urls):
        url = str(raw_url or "")
        article = _record(articles.get(url))
        failure = _record(failures.get(url))
        source_record = article or failure
        source_record = {
            **source_record,
            "cursor": source_record.get("cursor", index),
            "post_url": url,
            "source_url": url,
            "images": (
                source_record.get("images")
                or source_record.get("image_urls")
                or []
            ),
            "relations": {
                **_record(source_record.get("relations")),
                "evidence_refs": _json_copy(
                    source_record.get("evidence_refs") or []
                ),
            },
        }
        if failure:
            status = "failed"
            attempts = int(failure.get("attempts") or 0)
        elif article:
            status = (
                "recognized"
                if int(article.get("metadata_images") or 0) > 0
                else "unrecognized"
            )
            attempts = max(1, int(article.get("attempts") or 1))
        else:
            status = "pending"
            attempts = 0
        items.append(_restore_item(
            source_record,
            source_kind="public-post",
            source_url=url,
            source_id=url,
            status=status,
            attempts=attempts,
            error=failure.get("error"),
        ))
    return enqueue_restore_items(queue, items)


def pack_import_queue(
    value: Mapping[str, Any],
    *,
    filename: str = "",
) -> dict:
    """자료팩 가져오기 결과와 manifest 지문을 복원 후보로 투영한다."""
    result = _record(value)
    log = _record(result.get("batch_record") or result.get("batch_log"))
    if not log and isinstance(result.get("log"), list):
        batch_id = str(result.get("batch") or "")
        log = next((
            _record(item)
            for item in result["log"]
            if isinstance(item, Mapping)
            and (not batch_id or str(item.get("id") or "") == batch_id)
        ), {})
    manifest = _record(result.get("manifest") or log.get("manifest"))
    if not manifest and any(
        log.get(key) for key in ("pack_id", "pack_name", "content_sha256")
    ):
        manifest = {
            "id": log.get("pack_id"),
            "name": log.get("pack_name"),
            "content_sha256": log.get("content_sha256"),
        }
    content_hash = (
        manifest.get("content_sha256")
        or result.get("content_sha256")
        or result.get("archive_sha256")
        or log.get("archive_sha256")
        or ""
    )
    record = {
        "filename": filename or result.get("filename") or log.get("file"),
        "source_id": (
            manifest.get("id")
            or result.get("batch")
            or log.get("id")
            or filename
        ),
        "content_hash": content_hash,
        "metadata": {
            "manifest": manifest,
            "report": result.get("report") or [],
            "added": result.get("added"),
            "batch": result.get("batch") or log.get("id"),
            "installed": log.get("installed") or [],
            "lists": log.get("lists") or {},
            "files": log.get("files") or {},
        },
        "blueprint_candidate": result.get("blueprint_candidate") or {},
        "ok": result.get("ok"),
        "error": result.get("error"),
    }
    status = (
        "recognized"
        if result.get("ok") is True
        else "failed" if result.get("error") else "pending"
    )
    item = _restore_item(
        record,
        source_kind="data-pack",
        filename=str(record["filename"] or ""),
        source_id=str(record["source_id"] or ""),
        status=status,
        attempts=1 if result.get("ok") is not None else 0,
        error=result.get("error"),
    )
    return enqueue_restore_items(
        _new_queue(
            "data-pack",
            status="completed" if status == "recognized" else status,
            metadata={"batch": result.get("batch")},
        ),
        [item],
    )


def folder_inventory_queue(
    values: Sequence[Mapping[str, Any]],
    *,
    folder_label: str = "",
    cursor: Any = None,
    status: str = "pending",
) -> dict:
    """보유 폴더의 파일 인벤토리를 이미지 바이트 없이 복원 큐로 만든다."""
    queue = _new_queue(
        "folder",
        status=status,
        cursor=cursor,
        metadata={"folder_label": _safe_string(str(folder_label or ""))},
    )
    items = []
    for index, value in enumerate(values or ()):
        record = (
            _record(value)
            if isinstance(value, Mapping)
            else {"path": str(value or "")}
        )
        path = record.get("path") or record.get("source_path") or ""
        record["cursor"] = record.get("cursor", index)
        items.append(_restore_item(
            record,
            source_kind="folder-item",
            source_id=_safe_locator(path),
            filename=_safe_filename(
                record.get("filename") or path or record.get("name")
            ),
            status=str(record.get("status") or "pending"),
            attempts=int(record.get("attempts") or 0),
            error=record.get("error"),
        ))
    return enqueue_restore_items(queue, items)


def restoration_queue_from_input(
    kind: str,
    value: Any,
    **options: Any,
) -> dict:
    """모든 지원 입력을 한 진입점에서 공통 복원 큐로 투영한다."""
    normalized = str(kind or "").strip().casefold().replace("_", "-")
    if normalized in {"image", "image-inspect", "single-image"}:
        return image_inspect_queue(_record(value), **options)
    if normalized in {"images", "image-batch", "multi-image"}:
        return image_batch_queue(_sequence(value), **options)
    if normalized in {"post", "posts", "public-collection", "collection"}:
        return public_collection_queue(_record(value))
    if normalized in {"pack", "data-pack", "pack-import"}:
        return pack_import_queue(_record(value), **options)
    if normalized in {"folder", "folder-inventory"}:
        return folder_inventory_queue(_sequence(value), **options)
    raise ValueError(f"지원하지 않는 복원 입력 종류입니다: {kind}")


def retry_restoration_inputs(
    queue: Mapping[str, Any],
    *,
    item_ids: Iterable[str] | None = None,
    cursor: Any = None,
) -> dict:
    """선택한 실패 항목만 대기 상태로 돌리고 기존 실패 이력은 보존한다."""
    selected = {str(item) for item in (item_ids or ()) if str(item)}
    result = resume_restore_queue(queue, cursor=cursor, retry_failed=False)
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        recognition = item.get("recognition")
        if not isinstance(recognition, dict):
            continue
        if recognition.get("status") != "failed":
            continue
        if selected and str(item.get("id") or "") not in selected:
            continue
        recognition["status"] = "pending"
    return result


__all__ = [
    "RESTORATION_INPUT_SCHEMA",
    "folder_inventory_queue",
    "image_batch_queue",
    "image_inspect_queue",
    "pack_import_queue",
    "public_collection_queue",
    "restoration_queue_from_input",
    "retry_restoration_inputs",
]
