# -*- coding: utf-8 -*-
"""생성 화면·세팅·비교·챗봇 계약이 공유하는 생성 설계도.

설계도는 새 사용자 저장소가 아니다. 기존 설정·그림체·캐릭터·세팅을 실행 직전에
한 번 해석한 파생값이며, 원본 데이터를 자동 변환하거나 덮어쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


BLUEPRINT_SCHEMA = "nai-generation-blueprint/v1"

_TOP_LEVEL = (
    "schema",
    "source",
    "style",
    "characters",
    "resources",
    "setting",
    "experiment",
    "generation",
    "output",
)


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def canonical_blueprint(value: Mapping[str, Any] | None) -> dict:
    """누락된 영역을 빈 구조로 채우되 문자열·배열 원문은 그대로 보존."""
    raw = _mapping(value)
    result = {
        "schema": BLUEPRINT_SCHEMA,
        "source": _mapping(raw.get("source")),
        "style": _mapping(raw.get("style")),
        "characters": _list(raw.get("characters")),
        "resources": _mapping(raw.get("resources")),
        "setting": _mapping(raw.get("setting")),
        "experiment": _mapping(raw.get("experiment")),
        "generation": _mapping(raw.get("generation")),
        "output": _mapping(raw.get("output")),
    }
    # 미래 버전이 추가한 필드도 버리지 않는다. 현재 화면이 모른다는 이유로
    # 챗봇·자료팩·후속 버전의 정보를 잃지 않게 한다.
    for key, item in raw.items():
        if key not in result:
            result[key] = deepcopy(item)
    return result


def fingerprint_blueprint(value: Mapping[str, Any] | None) -> str:
    """표시 시각·진행률과 무관한 설계 내용 지문."""
    data = canonical_blueprint(value)
    for key in (
        "created_at", "updated_at", "progress", "runtime", "fingerprint",
        "summary",
    ):
        data.pop(key, None)
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def summarize_blueprint(value: Mapping[str, Any] | None) -> dict:
    """UI·계약·로그가 같은 기준으로 쓰는 짧은 설계 요약."""
    data = canonical_blueprint(value)
    characters = [
        item for item in data["characters"]
        if isinstance(item, Mapping) and item.get("enabled", True)
    ]
    resources = data["resources"]
    experiment = data["experiment"]
    generation = data["generation"]
    return {
        "schema": BLUEPRINT_SCHEMA,
        "fingerprint": fingerprint_blueprint(data),
        "style_name": str(data["style"].get("name") or ""),
        "characters": len(characters),
        "vibes": len(resources.get("vibes") or []),
        "references": len(resources.get("character_references") or []),
        "setting_name": str(data["setting"].get("name") or ""),
        "experiment_mode": str(experiment.get("mode") or "single"),
        "model": str(generation.get("model") or ""),
        "width": generation.get("width"),
        "height": generation.get("height"),
        "seed": generation.get("seed"),
        "output_format": str(data["output"].get("format") or ""),
    }


def blueprint_fields() -> tuple[str, ...]:
    """계약 문서·진단용 고정 최상위 영역."""
    return _TOP_LEVEL
