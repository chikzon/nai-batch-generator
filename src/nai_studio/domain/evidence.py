# -*- coding: utf-8 -*-
"""수집 경로와 무관하게 원본과 재현 조건을 함께 보존하는 증거 계약.

증거는 이미지를 자동으로 그림체·캐릭터 조각으로 분해하지 않는다. 이미지 한 장,
게시글, 자료팩, 생성 결과가 어느 입력 경로에서 왔든 같은 JSON 계약으로 기록하고,
지식 자산은 이 기록의 ID만 참조한다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


EVIDENCE_SCHEMA = "nai-evidence/v1"
EVIDENCE_KINDS = (
    "generation-record",
    "style",
    "character",
    "setting",
)

_IDENTITY_IGNORED = frozenset({
    "schema",
    "id",
    "fingerprint",
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


def _stable_hash(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("evidence must contain JSON-compatible values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _canonical_without_identity(value: Mapping[str, Any]) -> dict:
    raw = _mapping(value, "evidence")
    kind = raw.get("kind")
    if kind not in EVIDENCE_KINDS:
        raise ValueError(
            "evidence kind must be one of: " + ", ".join(EVIDENCE_KINDS)
        )

    result = {
        "schema": EVIDENCE_SCHEMA,
        "kind": kind,
        "image": _mapping(raw.get("image"), "image"),
        "source": _mapping(raw.get("source"), "source"),
        # 메타데이터는 dict, JSON 문자열, 원문 text chunk 중 무엇이든 원형을
        # 유지한다. 여기서 해석하거나 prompt를 분해하지 않는다.
        "raw_metadata": deepcopy(raw.get("raw_metadata")),
        "actual_generation": _mapping(
            raw.get("actual_generation"),
            "actual_generation",
        ),
        "evaluation": _mapping(raw.get("evaluation"), "evaluation"),
    }
    for key, item in raw.items():
        if key not in result and key not in {"id", "fingerprint"}:
            result[key] = deepcopy(item)
    return result


def fingerprint_evidence(value: Mapping[str, Any]) -> str:
    """가져온 시각·실행 상태와 무관한 증거 내용의 SHA-256 지문."""
    data = _canonical_without_identity(value)
    content = {
        key: item
        for key, item in data.items()
        if key not in _IDENTITY_IGNORED
    }
    return _stable_hash(content)


def evidence_id(value: Mapping[str, Any]) -> str:
    """동일한 증거 내용이면 입력 경로와 키 순서가 달라도 같은 안정 ID."""
    data = _canonical_without_identity(value)
    return f"evidence:{data['kind']}:{fingerprint_evidence(data)}"


def canonical_evidence(value: Mapping[str, Any]) -> dict:
    """필수 영역을 채우고 안정 ID를 붙인 무손실 증거 레코드."""
    result = _canonical_without_identity(value)
    result["fingerprint"] = fingerprint_evidence(result)
    result["id"] = f"evidence:{result['kind']}:{result['fingerprint']}"
    return result


def evidence_fields() -> tuple[str, ...]:
    """저장·진단·후속 UI가 공유할 고정 영역."""
    return (
        "schema",
        "id",
        "fingerprint",
        "kind",
        "image",
        "source",
        "raw_metadata",
        "actual_generation",
        "evaluation",
    )
