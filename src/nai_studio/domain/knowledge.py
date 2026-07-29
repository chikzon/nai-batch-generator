# -*- coding: utf-8 -*-
"""증거에서 정제해 실제 생성에 재사용하는 지식 자산 계약.

자산은 원문 prompt를 자동 분해·요약하지 않는다. 그림체와 캐릭터의 불가분 값,
작가·조각·레시피·세팅 재료를 명시적인 종류로 구분하고 증거 ID를 참조한다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


KNOWLEDGE_SCHEMA = "nai-knowledge-asset/v1"
KNOWLEDGE_KINDS = (
    "style",
    "character",
    "artist",
    "fragment",
    "recipe",
    "setting-material",
)
KNOWLEDGE_LIFECYCLES = (
    "candidate",
    "confirmed",
    "shared",
    "archived",
)

_CONTENT_DEFAULTS = {
    "style": {
        "base": "",
        "negative": "",
        "generation_settings": {},
    },
    "character": {
        "prompt": "",
        "negative": "",
        "variants": [],
        "reference_refs": [],
        "vibe_refs": [],
    },
    "artist": {
        "prompt": "",
        "ratings": [],
        "weight": None,
        "combinations": [],
    },
    "fragment": {
        "prompt": "",
        "selection": {},
    },
    "recipe": {
        "blueprint": {},
        "components": [],
    },
    "setting-material": {
        "scenes": [],
        "relationships": [],
        "positions": [],
        "options": {},
    },
}

_IDENTITY_IGNORED = frozenset({
    "schema",
    "id",
    "fingerprint",
    "lifecycle",
    "created_at",
    "updated_at",
    "imported_at",
    "runtime",
})


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _refs(value: Any, field: str) -> list:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list")
    copied = deepcopy(list(value))
    if any(not isinstance(item, str) for item in copied):
        raise TypeError(f"{field} must contain string IDs")
    return copied


def _stable_hash(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("knowledge asset must contain JSON-compatible values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _content(kind: str, value: Any) -> dict:
    raw = _mapping(value, "content")
    result = {}
    for key, default in _CONTENT_DEFAULTS[kind].items():
        result[key] = deepcopy(raw[key] if key in raw else default)
    # 후속 버전의 값을 현재 버전이 모른다는 이유로 잃지 않는다.
    for key, item in raw.items():
        if key not in result:
            result[key] = deepcopy(item)
    return result


def _canonical_without_identity(value: Mapping[str, Any]) -> dict:
    raw = _mapping(value, "knowledge asset")
    kind = raw.get("kind")
    if kind not in KNOWLEDGE_KINDS:
        raise ValueError(
            "knowledge kind must be one of: " + ", ".join(KNOWLEDGE_KINDS)
        )
    lifecycle = raw.get("lifecycle", "candidate")
    if lifecycle not in KNOWLEDGE_LIFECYCLES:
        raise ValueError(
            "lifecycle must be one of: " + ", ".join(KNOWLEDGE_LIFECYCLES)
        )

    result = {
        "schema": KNOWLEDGE_SCHEMA,
        "kind": kind,
        "lifecycle": lifecycle,
        "name": deepcopy(raw.get("name", "")),
        "evidence_refs": _refs(raw.get("evidence_refs"), "evidence_refs"),
        "content": _content(kind, raw.get("content")),
    }
    for key, item in raw.items():
        if key not in result and key not in {"id", "fingerprint"}:
            result[key] = deepcopy(item)
    return result


def fingerprint_knowledge_asset(value: Mapping[str, Any]) -> str:
    """검토 단계·수정 시각과 무관한 지식 내용의 SHA-256 지문."""
    data = _canonical_without_identity(value)
    content = {
        key: item
        for key, item in data.items()
        if key not in _IDENTITY_IGNORED
    }
    return _stable_hash(content)


def knowledge_asset_id(value: Mapping[str, Any]) -> str:
    """종류와 내용 지문으로 만든 안정 자산 ID."""
    data = _canonical_without_identity(value)
    return (
        f"knowledge:{data['kind']}:"
        f"{fingerprint_knowledge_asset(data)}"
    )


def canonical_knowledge_asset(value: Mapping[str, Any]) -> dict:
    """종류별 필수 영역과 생명주기, 안정 ID를 갖춘 지식 자산."""
    result = _canonical_without_identity(value)
    result["fingerprint"] = fingerprint_knowledge_asset(result)
    result["id"] = (
        f"knowledge:{result['kind']}:{result['fingerprint']}"
    )
    return result


def knowledge_fields() -> tuple[str, ...]:
    """저장·검색·후속 UI가 공유할 고정 영역."""
    return (
        "schema",
        "id",
        "fingerprint",
        "kind",
        "lifecycle",
        "name",
        "evidence_refs",
        "content",
    )
