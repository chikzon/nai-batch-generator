# -*- coding: utf-8 -*-
"""프롬프트 조각·인라인 와일드카드의 결정적 해석 계약.

지원 문법:

* ``{a|b|c}``: 해당 위치의 선택지 하나
* ``<이름>``: ``fragments["이름"]``의 문자열 하나

문법 밖 문자열은 그대로 둔다. 특히 NAI 가중치와 prompt mixing 표기에는 손대지
않는다. 범위는 원문 Python 문자열의 0 기반 ``[start, end)`` 문자 위치다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


FREEZE_SCHEMA = "nai-prompt-freeze/v1"
RESULT_SCHEMA = "nai-prompt-resolution/v1"
MAX_DEPTH = 16
MAX_OUTPUT_LENGTH = 1_000_000


class PromptResolutionError(ValueError):
    """프롬프트를 손실 없이 해석할 수 없을 때."""


class MissingFragmentError(PromptResolutionError):
    """참조한 조각이 없거나 선택지가 비어 있을 때."""


class CyclicFragmentError(PromptResolutionError):
    """조각 참조가 순환할 때."""


class PromptDepthError(PromptResolutionError):
    """중첩 상한을 넘어 해석 결과를 확정할 수 없을 때."""


class PromptOutputLimitError(PromptResolutionError):
    """출력을 자르지 않고 명시적으로 거절해야 할 때."""


class FrozenChoiceError(PromptResolutionError):
    """고정 스냅샷이 현재 원문·조각과 맞지 않을 때."""


@dataclass(frozen=True)
class _Expansion:
    text: str
    components: tuple[dict, ...]


def _stable_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_fragments(value: Mapping[str, Any] | None) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PromptResolutionError("fragments는 이름별 문자열 배열이어야 합니다.")
    result = {}
    for raw_name, raw_choices in value.items():
        name = str(raw_name).strip()
        if not name:
            raise PromptResolutionError("조각 이름은 비어 있을 수 없습니다.")
        if isinstance(raw_choices, str):
            choices = [raw_choices]
        elif isinstance(raw_choices, Sequence) and not isinstance(
                raw_choices, (bytes, bytearray)):
            choices = [str(item) for item in raw_choices]
        else:
            raise PromptResolutionError(
                f"조각 '{name}'의 선택지는 문자열 배열이어야 합니다.")
        if not choices or any(choice == "" for choice in choices):
            raise MissingFragmentError(f"조각 '{name}'에 사용할 문자열이 없습니다.")
        result[name] = choices
    return result


def _split_inline(content: str) -> list[str] | None:
    """중첩 중괄호 밖의 |만 나누고 실제 {|_|} 계열 태그는 보존."""
    parts = []
    start = 0
    depth = 0
    for index, char in enumerate(content):
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "|" and depth == 0:
            parts.append(content[start:index].strip())
            start = index + 1
    if not parts:
        return None
    parts.append(content[start:].strip())
    if len(parts) < 2 or any(part == "" for part in parts):
        return None
    return parts


def _closing_brace(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _component_id(
    kind: str,
    path: str,
    source_kind: str,
    source_name: str,
    start: int,
    end: int,
    expression: str,
) -> str:
    digest = _stable_json_hash({
        "kind": kind,
        "path": path,
        "source_kind": source_kind,
        "source_name": source_name,
        "start": start,
        "end": end,
        "expression": expression,
    })
    return f"component-{digest[:24]}"


class _Resolver:
    def __init__(
        self,
        template: str,
        fragments: Mapping[str, list[str]],
        seed: Any,
        frozen: Mapping[str, Any] | None,
        avoid: Mapping[str, int] | None = None,
    ):
        self.template = template
        self.fragments = deepcopy(dict(fragments))
        self.seed = str(seed)
        self.template_hash = _text_hash(template)
        self.fragments_hash = _stable_json_hash(self.fragments)
        self.frozen = self._load_frozen(frozen)
        self.avoid = dict(avoid or {})
        self.trace: list[dict] = []
        self.freeze_choices: dict[str, dict] = {}

    def _load_frozen(self, value: Mapping[str, Any] | None) -> dict[str, dict]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise FrozenChoiceError("freeze 스냅샷은 객체여야 합니다.")
        if value.get("schema") == FREEZE_SCHEMA:
            if value.get("template_hash") != self.template_hash:
                raise FrozenChoiceError("freeze의 프롬프트 원문이 현재 원문과 다릅니다.")
            if value.get("fragments_hash") != self.fragments_hash:
                raise FrozenChoiceError("freeze의 조각 자료가 현재 자료와 다릅니다.")
            choices = value.get("choices")
        else:
            choices = value.get("choices", value)
        if not isinstance(choices, Mapping):
            raise FrozenChoiceError("freeze choices가 객체가 아닙니다.")
        return {
            str(key): deepcopy(dict(item))
            for key, item in choices.items()
            if isinstance(item, Mapping)
        }

    def _pick(
        self,
        component_id: str,
        expression: str,
        choices: Sequence[str],
    ) -> tuple[int, str, bool]:
        expression_hash = _text_hash(expression)
        frozen = self.frozen.get(component_id)
        if frozen is not None:
            if frozen.get("expression_hash") != expression_hash:
                raise FrozenChoiceError(
                    f"{component_id}의 고정 표현식이 현재 원문과 다릅니다.")
            try:
                index = int(frozen.get("choice_index"))
            except (TypeError, ValueError) as exc:
                raise FrozenChoiceError(
                    f"{component_id}의 고정 선택 번호가 잘못됐습니다.") from exc
            if not 0 <= index < len(choices):
                raise FrozenChoiceError(
                    f"{component_id}의 고정 선택 번호가 범위를 벗어났습니다.")
            if str(frozen.get("choice")) != choices[index]:
                raise FrozenChoiceError(
                    f"{component_id}의 고정 선택 원문이 현재 자료와 다릅니다.")
            choice = choices[index]
            was_frozen = True
        else:
            digest = hashlib.sha256(
                f"{self.seed}\0{component_id}".encode("utf-8")).digest()
            number = int.from_bytes(digest, "big")
            index = number % len(choices)
            avoided = self.avoid.get(component_id)
            if len(choices) > 1 and avoided is not None and index == avoided:
                # 재추첨은 선택지가 둘 이상이면 이전과 다른 값으로 결정한다.
                index = (index + 1 + ((number // len(choices))
                                     % (len(choices) - 1))) % len(choices)
                if index == avoided:
                    index = (index + 1) % len(choices)
            choice = choices[index]
            was_frozen = False
        self.freeze_choices[component_id] = {
            "expression_hash": expression_hash,
            "choice_index": index,
            "choice": choice,
        }
        return index, choice, was_frozen

    @staticmethod
    def _shift(components: Sequence[dict], offset: int) -> list[dict]:
        shifted = []
        for item in components:
            record = deepcopy(item)
            output_range = record["output_range"]
            record["output_range"] = {
                "start": output_range["start"] + offset,
                "end": output_range["end"] + offset,
            }
            shifted.append(record)
        return shifted

    def _ensure_length(self, size: int) -> None:
        if size > MAX_OUTPUT_LENGTH:
            raise PromptOutputLimitError(
                f"해석 결과가 {MAX_OUTPUT_LENGTH:,}자를 넘습니다. 원문을 자르지 않았습니다.")

    def expand(
        self,
        text: str,
        *,
        source_kind: str,
        source_name: str,
        path: str,
        depth: int,
        fragment_stack: tuple[str, ...],
        parent_id: str = "",
    ) -> _Expansion:
        if depth > MAX_DEPTH:
            raise PromptDepthError(
                f"조각·와일드카드 중첩이 {MAX_DEPTH}단계를 넘습니다.")
        output: list[str] = []
        output_length = 0
        components: list[dict] = []
        index = 0

        def append_literal(value: str) -> None:
            nonlocal output_length
            output.append(value)
            output_length += len(value)
            self._ensure_length(output_length)

        while index < len(text):
            if text[index] == "<":
                closing = text.find(">", index + 1)
                if closing >= 0:
                    expression = text[index:closing + 1]
                    name = text[index + 1:closing].strip()
                    # NAI prompt mixing 구분자 <|>는 조각 참조가 아니다.
                    # 기존 <*이름> 순차 조각은 별도 counter 상태 계약이다. 이
                    # seed/freeze resolver가 의미를 바꾸지 않고 원문으로 넘긴다.
                    if name and not name.startswith("*") and set(name) != {"|"}:
                        if name not in self.fragments:
                            raise MissingFragmentError(
                                f"없는 조각을 참조했습니다: <{name}>")
                        if name in fragment_stack:
                            chain = " → ".join(fragment_stack + (name,))
                            raise CyclicFragmentError(f"조각 순환 참조: {chain}")
                        choices = self.fragments[name]
                        component_id = _component_id(
                            "fragment", path, source_kind, source_name,
                            index, closing + 1, expression)
                        chosen_index, choice, was_frozen = self._pick(
                            component_id, expression, choices)
                        child = self.expand(
                            choice,
                            source_kind="fragment",
                            source_name=name,
                            path=f"{path}/{component_id}/choice-{chosen_index}",
                            depth=depth + 1,
                            fragment_stack=fragment_stack + (name,),
                            parent_id=component_id,
                        )
                        start_out = output_length
                        append_literal(child.text)
                        end_out = output_length
                        source = {
                            "kind": source_kind,
                            "name": source_name,
                        }
                        record = {
                            "id": component_id,
                            "kind": "fragment",
                            "source": source,
                            "range": {"start": index, "end": closing + 1},
                            "expression": expression,
                            "fragment": name,
                            "choice": {
                                "index": chosen_index,
                                "value": choice,
                                "frozen": was_frozen,
                            },
                            "output_range": {
                                "start": start_out,
                                "end": end_out,
                            },
                            "depth": depth,
                            "parent_id": parent_id,
                        }
                        components.append(record)
                        components.extend(self._shift(child.components, start_out))
                        self.trace.append({
                            "component_id": component_id,
                            "kind": "fragment",
                            "source": deepcopy(source),
                            "range": deepcopy(record["range"]),
                            "choice_index": chosen_index,
                            "choice": choice,
                            "output_range": deepcopy(record["output_range"]),
                            "depth": depth,
                            "frozen": was_frozen,
                        })
                        index = closing + 1
                        continue

            if text[index] == "{":
                closing = _closing_brace(text, index)
                if closing >= 0:
                    expression = text[index:closing + 1]
                    choices = _split_inline(text[index + 1:closing])
                    if choices is not None:
                        component_id = _component_id(
                            "inline", path, source_kind, source_name,
                            index, closing + 1, expression)
                        chosen_index, choice, was_frozen = self._pick(
                            component_id, expression, choices)
                        child = self.expand(
                            choice,
                            source_kind="inline",
                            source_name=component_id,
                            path=f"{path}/{component_id}/choice-{chosen_index}",
                            depth=depth + 1,
                            fragment_stack=fragment_stack,
                            parent_id=component_id,
                        )
                        start_out = output_length
                        append_literal(child.text)
                        end_out = output_length
                        source = {
                            "kind": source_kind,
                            "name": source_name,
                        }
                        record = {
                            "id": component_id,
                            "kind": "inline",
                            "source": source,
                            "range": {"start": index, "end": closing + 1},
                            "expression": expression,
                            "choice": {
                                "index": chosen_index,
                                "value": choice,
                                "frozen": was_frozen,
                            },
                            "output_range": {
                                "start": start_out,
                                "end": end_out,
                            },
                            "depth": depth,
                            "parent_id": parent_id,
                        }
                        components.append(record)
                        components.extend(self._shift(child.components, start_out))
                        self.trace.append({
                            "component_id": component_id,
                            "kind": "inline",
                            "source": deepcopy(source),
                            "range": deepcopy(record["range"]),
                            "choice_index": chosen_index,
                            "choice": choice,
                            "output_range": deepcopy(record["output_range"]),
                            "depth": depth,
                            "frozen": was_frozen,
                        })
                        index = closing + 1
                        continue

            append_literal(text[index])
            index += 1

        return _Expansion("".join(output), tuple(components))

    def result(self) -> dict:
        expanded = self.expand(
            self.template,
            source_kind="template",
            source_name="",
            path="template",
            depth=0,
            fragment_stack=(),
        )
        freeze = {
            "schema": FREEZE_SCHEMA,
            "template_hash": self.template_hash,
            "fragments_hash": self.fragments_hash,
            "choices": deepcopy(self.freeze_choices),
        }
        return {
            "schema": RESULT_SCHEMA,
            "text": expanded.text,
            "components": list(expanded.components),
            "trace": deepcopy(self.trace),
            "freeze": freeze,
            # 부분 재추첨은 외부 파일이나 전역 상태를 다시 읽지 않고 이 입력 복제본만
            # 사용한다. resolve_prompt 호출자의 객체는 수정하지 않는다.
            "inputs": {
                "template": self.template,
                "fragments": deepcopy(self.fragments),
            },
            "seed": self.seed,
        }


def resolve_prompt(
    template: str,
    fragments: Mapping[str, Any] | None,
    seed: Any,
    frozen: Mapping[str, Any] | None = None,
) -> dict:
    """프롬프트를 결정적으로 해석하고 추적·고정 스냅샷을 반환."""
    if not isinstance(template, str):
        raise PromptResolutionError("template은 문자열이어야 합니다.")
    normalized = _normalize_fragments(fragments)
    return _Resolver(template, normalized, seed, frozen).result()


def reroll_components(
    result: Mapping[str, Any],
    component_ids: Sequence[str],
    seed: Any,
) -> dict:
    """지정한 component와 그 하위 선택만 다시 뽑는다.

    지정하지 않은 component는 기존 freeze를 그대로 적용하므로 그 선택 원문은
    byte-identical하게 유지된다.
    """
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise PromptResolutionError("부분 재추첨 결과 형식이 올바르지 않습니다.")
    inputs = result.get("inputs")
    components = result.get("components")
    freeze = result.get("freeze")
    if not isinstance(inputs, Mapping) or not isinstance(components, list):
        raise PromptResolutionError("부분 재추첨에 필요한 입력·component가 없습니다.")
    by_id = {
        str(item.get("id")): item
        for item in components
        if isinstance(item, Mapping) and item.get("id")
    }
    selected = {str(item) for item in component_ids}
    if not selected:
        raise PromptResolutionError("재추첨할 component id가 없습니다.")
    missing = sorted(selected - set(by_id))
    if missing:
        raise PromptResolutionError(
            "현재 결과에 없는 component id입니다: " + ", ".join(missing))

    descendants = set(selected)
    changed = True
    while changed:
        changed = False
        for identifier, item in by_id.items():
            if item.get("parent_id") in descendants and identifier not in descendants:
                descendants.add(identifier)
                changed = True

    old_choices = freeze.get("choices") if isinstance(freeze, Mapping) else None
    if not isinstance(old_choices, Mapping):
        raise PromptResolutionError("부분 재추첨에 필요한 freeze가 없습니다.")
    kept = {
        identifier: deepcopy(dict(item))
        for identifier, item in old_choices.items()
        if identifier not in descendants and isinstance(item, Mapping)
    }
    next_freeze = {
        "schema": FREEZE_SCHEMA,
        "template_hash": freeze.get("template_hash"),
        "fragments_hash": freeze.get("fragments_hash"),
        "choices": kept,
    }
    avoid = {
        identifier: int(old_choices[identifier]["choice_index"])
        for identifier in selected
        if identifier in old_choices
    }
    template = inputs.get("template")
    fragments = inputs.get("fragments")
    if not isinstance(template, str) or not isinstance(fragments, Mapping):
        raise PromptResolutionError("부분 재추첨 입력 원문이 올바르지 않습니다.")
    normalized = _normalize_fragments(fragments)
    return _Resolver(
        template, normalized, seed, next_freeze, avoid=avoid).result()
