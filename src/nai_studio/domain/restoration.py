# -*- coding: utf-8 -*-
"""이미지·게시글·자료팩·폴더를 같은 설계도 복원 후보로 다루는 순수 계약.

이 모듈은 파일을 읽거나 네트워크에 접속하지 않는다. 원본 자료를 지식으로 자동
승격하지도 않는다. 수집기가 건넨 사실을 손실 없이 정규화하고 배치의 중단·재개,
중복·변경 계보와 판독 결과만 기록한다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping, Sequence


RESTORE_ITEM_SCHEMA = "nai-restore-item/v1"
RESTORE_QUEUE_SCHEMA = "nai-restore-queue/v1"
RESTORE_STATUSES = ("pending", "recognized", "unrecognized", "failed")


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _stable_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_stable_json(value)).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _present(raw: Mapping[str, Any], key: str, *aliases: str) -> Any:
    """빈 문자열·빈 목록도 명시값이므로 별칭보다 먼저 보존한다."""
    if key in raw:
        return raw.get(key)
    for alias in aliases:
        if alias in raw:
            return raw.get(alias)
    return None


def _canonical_source(raw: Mapping[str, Any]) -> dict:
    source = _mapping(raw.get("source"))
    aliases = {
        "url": ("source_url", "url"),
        "path": ("source_path", "path"),
        "post_url": ("post_url",),
        "kind": ("source_kind", "kind"),
    }
    for key, candidates in aliases.items():
        if key in source:
            continue
        for candidate in candidates:
            if candidate in raw:
                source[key] = deepcopy(raw.get(candidate))
                break
    return source


def _canonical_images(raw: Mapping[str, Any]) -> list:
    value = _present(raw, "images", "image_refs")
    if value is None and "image_ref" in raw:
        value = [raw.get("image_ref")]
    if isinstance(value, (str, bytes, Mapping)):
        return [deepcopy(value)]
    return _list(value)


def _item_identity(raw: Mapping[str, Any], source: dict, images: list) -> dict:
    content_hash = _present(raw, "content_hash", "hash", "sha256")
    identity = {
        "source": source,
        "images": images,
        "content_hash": "" if content_hash is None else str(content_hash),
    }
    # 주소·경로·해시가 전혀 없는 메모리 입력도 같은 원문이면 같은 후보가 된다.
    if not source and not images and not identity["content_hash"]:
        identity["raw_metadata"] = deepcopy(
            _present(raw, "raw_metadata", "metadata")
        )
    return identity


def canonical_restore_item(value: Mapping[str, Any] | None) -> dict:
    """한 복원 후보를 원문과 미래 필드를 버리지 않고 정규화한다."""
    raw = _mapping(value)
    source = _canonical_source(raw)
    images = _canonical_images(raw)
    content_hash = _present(raw, "content_hash", "hash", "sha256")
    recognition = _mapping(raw.get("recognition"))
    status = str(
        recognition.get("status")
        or raw.get("recognition_status")
        or raw.get("status")
        or "pending"
    )
    result = deepcopy(raw)
    result["schema"] = RESTORE_ITEM_SCHEMA
    result["source"] = source
    result["images"] = images
    result["content_hash"] = "" if content_hash is None else str(content_hash)
    result["raw_metadata"] = deepcopy(
        _present(raw, "raw_metadata", "metadata")
    )
    result["detected_fields"] = _mapping(
        _present(raw, "detected_fields", "nai_fields")
    )
    recognition["status"] = status
    recognition["attempts"] = _nonnegative_int(
        recognition.get("attempts", raw.get("attempts"))
    )
    recognition["history"] = _list(recognition.get("history"))
    result["recognition"] = recognition
    relations = _mapping(raw.get("relations"))
    if "duplicate_of" not in relations and raw.get("duplicate_of"):
        relations["duplicate_of"] = str(raw.get("duplicate_of"))
    if "change_from" not in relations and raw.get("change_from"):
        relations["change_from"] = str(raw.get("change_from"))
    result["relations"] = relations
    result["cursor"] = deepcopy(raw.get("cursor"))
    result["date"] = deepcopy(raw.get("date"))
    result["result"] = _mapping(raw.get("result"))
    result["id"] = str(
        raw.get("id")
        or _stable_id("restore-item", _item_identity(raw, source, images))
    )
    return result


def canonical_restore_queue(value: Mapping[str, Any] | None) -> dict:
    """배치 범위와 커서를 유지한 복원 큐의 부작용 없는 정규형."""
    raw = _mapping(value)
    items = [
        canonical_restore_item(item)
        if isinstance(item, Mapping)
        else deepcopy(item)
        for item in _list(raw.get("items"))
    ]
    result = deepcopy(raw)
    result["schema"] = RESTORE_QUEUE_SCHEMA
    result["source"] = _mapping(raw.get("source"))
    result["date_range"] = _mapping(raw.get("date_range"))
    result["cursor"] = deepcopy(raw.get("cursor"))
    result["status"] = str(raw.get("status") or "pending")
    result["items"] = items
    result["metadata"] = _mapping(raw.get("metadata"))
    identity = {
        "source": result["source"],
        "date_range": result["date_range"],
        "scope": deepcopy(raw.get("scope")),
        "initial_items": [
            item.get("id") for item in items if isinstance(item, Mapping)
        ],
    }
    result["id"] = str(raw.get("id") or _stable_id("restore-queue", identity))
    return result


def _source_locator(item: Mapping[str, Any]) -> bytes:
    source = _mapping(item.get("source"))
    # 날짜·커서는 수집 위치이지 원본의 주소가 아니므로 변경 판정에서 제외한다.
    locator = {
        key: source.get(key)
        for key in ("kind", "url", "path", "post_url", "source_id")
        if source.get(key) not in (None, "")
    }
    if not locator:
        locator["images"] = _list(item.get("images"))
    return _stable_json(locator)


def enqueue_restore_items(
    queue: Mapping[str, Any] | None,
    items: Sequence[Mapping[str, Any]],
) -> dict:
    """후보를 추가하고 같은 내용·바뀐 원본 관계를 기록한다.

    같은 내용이어도 항목을 버리지 않는다. 완전히 같은 후보가 다시 들어온 경우도
    큐 안의 발생 순서를 포함한 새 id를 주고 최초 항목을 ``duplicate_of``로 잇는다.
    """
    result = canonical_restore_queue(queue)
    existing = [
        item for item in result["items"] if isinstance(item, Mapping)
    ]
    hash_first: dict[str, str] = {}
    locator_latest: dict[bytes, dict] = {}
    base_counts: dict[str, int] = {}
    for item in existing:
        digest = str(item.get("content_hash") or "")
        if digest:
            hash_first.setdefault(digest, str(item.get("id") or ""))
        locator_latest[_source_locator(item)] = item
        base_id = str(item.get("origin_id") or item.get("id") or "")
        base_counts[base_id] = base_counts.get(base_id, 0) + 1

    for raw in items or ():
        if not isinstance(raw, Mapping):
            continue
        item = canonical_restore_item(raw)
        base_id = item["id"]
        occurrence = base_counts.get(base_id, 0)
        if occurrence:
            item["origin_id"] = base_id
            item["id"] = _stable_id("restore-item", {
                "queue_id": result["id"],
                "origin_id": base_id,
                "occurrence": occurrence,
            })
        base_counts[base_id] = occurrence + 1

        digest = str(item.get("content_hash") or "")
        relations = _mapping(item.get("relations"))
        if digest and digest in hash_first and not relations.get("duplicate_of"):
            relations["duplicate_of"] = hash_first[digest]
        locator = _source_locator(item)
        previous = locator_latest.get(locator)
        if (
            previous
            and digest
            and previous.get("content_hash")
            and digest != previous.get("content_hash")
            and not relations.get("change_from")
        ):
            relations["change_from"] = str(previous.get("id") or "")
        item["relations"] = relations
        result["items"].append(item)
        existing.append(item)
        if digest:
            hash_first.setdefault(digest, item["id"])
        locator_latest[locator] = item
    return result


def mark_restore_result(
    queue: Mapping[str, Any],
    item_id: str,
    status: str,
    *,
    evidence_ref: Any = None,
    blueprint_candidate: Mapping[str, Any] | None = None,
    error: Any = None,
) -> dict:
    """한 후보의 판독 결과를 기록하고 원문 입력은 그대로 둔다."""
    if status not in ("recognized", "unrecognized", "failed"):
        raise ValueError("복원 결과는 recognized, unrecognized, failed 중 하나여야 합니다.")
    result = canonical_restore_queue(queue)
    found = False
    for index, raw_item in enumerate(result["items"]):
        if not isinstance(raw_item, Mapping) or str(raw_item.get("id")) != str(item_id):
            continue
        item = canonical_restore_item(raw_item)
        recognition = _mapping(item.get("recognition"))
        attempts = _nonnegative_int(recognition.get("attempts")) + 1
        history = _list(recognition.get("history"))
        history.append({
            "attempt": attempts,
            "status": status,
            "error": deepcopy(error),
        })
        recognition.update({
            "status": status,
            "attempts": attempts,
            "history": history,
        })
        if status == "failed":
            recognition["error"] = deepcopy(error)
        else:
            recognition.pop("error", None)
        item["recognition"] = recognition
        item_result = _mapping(item.get("result"))
        if evidence_ref is not None:
            item_result["evidence_ref"] = deepcopy(evidence_ref)
        if blueprint_candidate is not None:
            item_result["blueprint_candidate"] = deepcopy(
                dict(blueprint_candidate)
            )
        item["result"] = item_result
        result["items"][index] = item
        found = True
        break
    if not found:
        raise KeyError(f"복원 후보를 찾을 수 없습니다: {item_id}")
    return result


def resume_restore_queue(
    queue: Mapping[str, Any],
    *,
    cursor: Any = None,
    retry_failed: bool = True,
) -> dict:
    """멈춘 배치를 재개하고 선택적으로 실패 항목만 대기 상태로 돌린다."""
    result = canonical_restore_queue(queue)
    result["status"] = "running"
    if cursor is not None:
        result["cursor"] = deepcopy(cursor)
    if retry_failed:
        for index, raw_item in enumerate(result["items"]):
            if not isinstance(raw_item, Mapping):
                continue
            item = canonical_restore_item(raw_item)
            recognition = _mapping(item.get("recognition"))
            if recognition.get("status") != "failed":
                continue
            recognition["status"] = "pending"
            # 실패 원인과 시도 이력은 재개 뒤에도 감사할 수 있게 보존한다.
            item["recognition"] = recognition
            result["items"][index] = item
    return result


def summarize_restore_queue(queue: Mapping[str, Any] | None) -> dict:
    """진행 화면과 로그가 공유할 작은 복원 배치 요약."""
    data = canonical_restore_queue(queue)
    counts = {status: 0 for status in RESTORE_STATUSES}
    other = 0
    images = duplicates = changes = 0
    for item in data["items"]:
        if not isinstance(item, Mapping):
            other += 1
            continue
        status = str(_mapping(item.get("recognition")).get("status") or "pending")
        if status in counts:
            counts[status] += 1
        else:
            other += 1
        images += len(_list(item.get("images")))
        relations = _mapping(item.get("relations"))
        duplicates += bool(relations.get("duplicate_of"))
        changes += bool(relations.get("change_from"))
    return {
        "schema": RESTORE_QUEUE_SCHEMA,
        "id": data["id"],
        "status": data["status"],
        "total": len(data["items"]),
        "images": images,
        **counts,
        "other": other,
        "duplicates": duplicates,
        "changes": changes,
        "cursor": deepcopy(data.get("cursor")),
        "date_range": deepcopy(data.get("date_range")),
    }
