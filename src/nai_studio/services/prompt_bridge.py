# -*- coding: utf-8 -*-
"""기존 조각 형식과 canonical prompt resolver를 잇는 무상태 어댑터.

``{a|b}``와 ``<이름>``은 canonical resolver가 처리한다. 배치 전체의 counter가
필요한 기존 ``<*이름>``은 텍스트에 그대로 남겨 ``legacy_app.resolve_fragments``
경로가 이어서 처리하게 한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.nai_studio.domain.prompt_resolution import (
    RESULT_SCHEMA,
    PromptResolutionError,
    reroll_components,
    resolve_prompt,
)


BRIDGE_SCHEMA = "nai-prompt-legacy-bridge/v1"
UI_STATE_SCHEMA = "nai-prompt-ui-state/v1"
_SEQUENTIAL = re.compile(r"<\*([^<>]+)>")


class PromptBridgeError(ValueError):
    """canonical 결과를 기존 조각 경로에 안전하게 투영할 수 없을 때."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sequential_references(text: str) -> list[dict]:
    """최종 canonical 문자열에 남은 기존 counter 조각 위치."""
    found = []
    for match in _SEQUENTIAL.finditer(text):
        name = match.group(1).strip()
        if not name:
            continue
        expression = match.group(0)
        stable = _sha256(
            f"legacy-sequence\0{name}\0{match.start()}\0{match.end()}")
        found.append({
            "id": f"legacy-sequence-{stable[:24]}",
            "name": name,
            "expression": expression,
            "range": {"start": match.start(), "end": match.end()},
            "handler": "legacy-counter",
        })
    return found


def _canonical_from_result(value: Mapping[str, Any]) -> dict:
    if not isinstance(value, Mapping):
        raise PromptBridgeError("프롬프트 해석 결과는 객체여야 합니다.")
    if value.get("schema") == RESULT_SCHEMA:
        return deepcopy(dict(value))
    if value.get("schema") == BRIDGE_SCHEMA and isinstance(
            value.get("canonical"), Mapping):
        canonical = deepcopy(dict(value["canonical"]))
        if canonical.get("schema") == RESULT_SCHEMA:
            return canonical
    raise PromptBridgeError("지원하지 않는 프롬프트 해석 결과입니다.")


def prompt_ui_state(value: Mapping[str, Any]) -> dict:
    """설정 UI에 JSON으로 저장할 수 있는 비밀 없는 고정·trace 사본.

    원문 template과 조각 사전은 기존 설정·조각 파일이 계속 소유한다. UI 상태에는
    이를 중복 저장하지 않고 해시와 선택 결과만 둔다.
    """
    canonical = _canonical_from_result(value)
    text = str(canonical.get("text") or "")
    sequential = _sequential_references(text)
    freeze = canonical.get("freeze")
    if not isinstance(freeze, Mapping):
        raise PromptBridgeError("canonical 결과에 freeze가 없습니다.")
    state = {
        "schema": UI_STATE_SCHEMA,
        "resolved_text": text,
        "resolved_text_hash": _sha256(text),
        "components": deepcopy(canonical.get("components") or []),
        "trace": deepcopy(canonical.get("trace") or []),
        "freeze": deepcopy(dict(freeze)),
        "legacy_sequence": {
            "pending": bool(sequential),
            "references": sequential,
        },
    }
    # 설정 JSON에 들어갈 계약이므로 bytes/set/사용자 객체가 섞이지 않았음을 즉시 확인.
    try:
        json.dumps(state, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise PromptBridgeError("UI 프롬프트 상태를 JSON으로 저장할 수 없습니다.") from exc
    return state


def _bridge_result(canonical: Mapping[str, Any]) -> dict:
    canonical_copy = _canonical_from_result(canonical)
    text = str(canonical_copy.get("text") or "")
    sequential = _sequential_references(text)
    bridge = {
        "schema": BRIDGE_SCHEMA,
        "text": text,
        "canonical": canonical_copy,
        "legacy_sequence": {
            "pending": bool(sequential),
            "references": sequential,
            # True면 기존 resolve_fragments가 이 문자열을 받아 counter를 갱신한다.
            "pass_to_legacy": bool(sequential),
        },
    }
    bridge["ui_state"] = prompt_ui_state(canonical_copy)
    return bridge


def resolve_legacy_prompt(
    template: str,
    fragments: Mapping[str, Any] | None,
    seed: Any,
    frozen: Mapping[str, Any] | None = None,
) -> dict:
    """기존 프롬프트를 canonical 선택과 legacy 순차 선택의 경계로 해석."""
    try:
        canonical = resolve_prompt(template, fragments, seed, frozen=frozen)
    except PromptResolutionError:
        raise
    return _bridge_result(canonical)


def reroll_legacy_components(
    result: Mapping[str, Any],
    component_ids: Sequence[str],
    seed: Any,
) -> dict:
    """canonical component 일부만 다시 뽑고 legacy counter 표기는 보존."""
    canonical = _canonical_from_result(result)
    try:
        rerolled = reroll_components(canonical, component_ids, seed)
    except PromptResolutionError:
        raise
    return _bridge_result(rerolled)


def legacy_sequence_text(value: Mapping[str, Any]) -> str:
    """기존 counter resolver에 넘길 canonical 해석 문자열."""
    if not isinstance(value, Mapping) or value.get("schema") != BRIDGE_SCHEMA:
        raise PromptBridgeError("legacy bridge 결과가 아닙니다.")
    return str(value.get("text") or "")

