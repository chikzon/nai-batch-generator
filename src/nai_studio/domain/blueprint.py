# -*- coding: utf-8 -*-
"""생성 화면·세팅·비교·챗봇 계약이 공유하는 생성 설계도.

설계도는 새 사용자 저장소가 아니다. 기존 설정·그림체·캐릭터·세팅을 실행 직전에
한 번 해석한 파생값이며, 원본 데이터를 자동 변환하거나 덮어쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence


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


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _present(raw: Mapping[str, Any], key: str, *aliases: str) -> Any:
    """빈 문자열·빈 목록도 사용자의 명시값이므로 별칭보다 먼저 보존한다."""
    if key in raw:
        return raw.get(key)
    for alias in aliases:
        if alias in raw:
            return raw.get(alias)
    return None


def _canonical_character(value: Any) -> dict:
    """캐릭터 한 명을 실행 경로와 무관한 손실 없는 구조로 정리한다."""
    raw = _mapping(value)
    result = deepcopy(raw)
    result.setdefault("id", _text(raw.get("id")))
    result.setdefault("name", _text(raw.get("name")))
    result.setdefault("enabled", raw.get("enabled") is not False)
    result.setdefault(
        "appearance",
        _text(_present(raw, "appearance", "prompt", "female")),
    )
    result.setdefault(
        "clothed",
        _text(_present(raw, "clothed", "outfit")),
    )
    result.setdefault("negative", _text(raw.get("negative")))
    result["variant"] = _mapping(raw.get("variant"))
    result["reference_ids"] = _list(_present(raw, "reference_ids", "references"))
    result["vibe_ids"] = _list(_present(raw, "vibe_ids", "vibes"))
    result["include"] = _list(_present(raw, "include", "include_tags"))
    result["exclude"] = _list(_present(raw, "exclude", "exclude_tags"))
    result["position"] = _mapping(raw.get("position"))
    result["relations"] = _list(raw.get("relations"))
    result["provenance"] = _list(raw.get("provenance"))
    return result


def _canonical_style(value: Any) -> dict:
    raw = _mapping(value)
    result = deepcopy(raw)
    result.setdefault("id", _text(raw.get("id")))
    result.setdefault("name", _text(raw.get("name")))
    result.setdefault("base", _text(_present(raw, "base", "prompt")))
    result.setdefault("negative", _text(raw.get("negative")))
    result["parts"] = _mapping(raw.get("parts"))
    result["generation_settings"] = _mapping(
        _present(raw, "generation_settings", "params")
    )
    result["evidence"] = _list(raw.get("evidence"))
    result["provenance"] = _list(raw.get("provenance"))
    return result


def _canonical_setting(value: Any) -> dict:
    raw = _mapping(value)
    result = deepcopy(raw)
    result.setdefault("id", _text(raw.get("id")))
    result.setdefault("name", _text(raw.get("name")))
    result["scene_values"] = _mapping(_present(raw, "scene_values", "scene"))
    result["character_values"] = _mapping(
        _present(raw, "character_values", "per_character")
    )
    result["relations"] = _list(raw.get("relations"))
    result["steps"] = _list(raw.get("steps"))
    result["families"] = _list(raw.get("families"))
    result["options"] = _mapping(raw.get("options"))
    result["cast"] = [
        (_canonical_character(item) if isinstance(item, Mapping) else deepcopy(item))
        for item in _list(raw.get("cast"))
    ]
    result["repeat"] = deepcopy(raw.get("repeat"))
    result["order"] = deepcopy(raw.get("order"))
    result["reservation"] = _mapping(raw.get("reservation"))
    result["provenance"] = _list(raw.get("provenance"))
    return result


def _canonical_generation(value: Any) -> dict:
    raw = _mapping(value)
    result = deepcopy(raw)
    resolution = _mapping(raw.get("resolution"))
    if "width" not in resolution and raw.get("width") is not None:
        resolution["width"] = deepcopy(raw.get("width"))
    if "height" not in resolution and raw.get("height") is not None:
        resolution["height"] = deepcopy(raw.get("height"))
    result["resolution"] = resolution
    result["settings"] = _mapping(raw.get("settings"))
    result["final"] = _mapping(raw.get("final"))
    result["schedule"] = _mapping(raw.get("schedule"))
    result["provenance"] = _list(raw.get("provenance"))
    return result


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


def canonical_generation_plan(value: Mapping[str, Any] | None) -> dict:
    """여러 화면의 값을 하나의 실행 전 설계도로 정규화한다.

    기존 필드와 아직 모르는 미래 필드는 그대로 보존한다. 이 함수는 파생 사본만
    만들며 기존 설정·캐릭터·자료 파일을 바꾸지 않는다.
    """
    result = canonical_blueprint(value)
    result["style"] = _canonical_style(result["style"])
    result["characters"] = [
        (_canonical_character(item) if isinstance(item, Mapping) else deepcopy(item))
        for item in result["characters"]
    ]
    result["resources"] = _mapping(result["resources"])
    result["resources"]["vibes"] = _list(result["resources"].get("vibes"))
    result["resources"]["character_references"] = _list(
        _present(result["resources"], "character_references", "references")
    )
    result["setting"] = _canonical_setting(result["setting"])
    result["experiment"] = _mapping(result["experiment"])
    result["generation"] = _canonical_generation(result["generation"])
    result["output"] = _mapping(result["output"])
    result["provenance"] = _list(result.get("provenance"))
    return result


def _pointer(parts: Sequence[str]) -> str:
    if not parts:
        return "/"
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _leaf_values(value: Any, parts: tuple[str, ...] = ()) -> Iterable[tuple]:
    if isinstance(value, Mapping):
        if not value:
            yield parts, {}
        else:
            for key, item in value.items():
                yield from _leaf_values(item, parts + (str(key),))
        return
    # 배열은 순서와 캐릭터-좌표 짝이 의미를 가지므로 원자 값으로 취급한다.
    yield parts, deepcopy(value)


def _assign_path(target: dict, parts: Sequence[str], value: Any) -> None:
    if not parts:
        if isinstance(value, Mapping):
            target.clear()
            target.update(deepcopy(dict(value)))
        return
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = deepcopy(value)


def resolve_blueprint_layers(
    layers: Sequence[Mapping[str, Any]],
    *,
    base: Mapping[str, Any] | None = None,
) -> dict:
    """우선순위가 있는 설계도 조각을 합치고 선택 근거와 충돌을 함께 돌려준다.

    레이어 형식은 ``{"source": {...}, "priority": 10, "blueprint": {...}}``다.
    높은 우선순위가 이기며 같은 우선순위는 뒤 레이어가 이긴다. 값이 다른 모든
    경쟁은 ``conflicts``에 남으므로 조용한 덮어쓰기가 없다.
    """
    candidates: dict[tuple[str, ...], list[dict]] = {}
    ordered_layers: list[tuple[int, int, dict, dict]] = []
    if base is not None:
        ordered_layers.append((-10**9, -1, {"kind": "base"}, _mapping(base)))
    for order, layer in enumerate(layers or ()):
        if not isinstance(layer, Mapping):
            continue
        try:
            priority = int(layer.get("priority", 0))
        except (TypeError, ValueError, OverflowError):
            priority = 0
        source = _mapping(layer.get("source"))
        if not source:
            source = {"kind": "layer", "id": str(order)}
        payload = layer.get("blueprint")
        if payload is None:
            payload = layer.get("values")
        ordered_layers.append((priority, order, source, _mapping(payload)))

    for priority, order, source, payload in ordered_layers:
        for parts, item in _leaf_values(payload):
            candidates.setdefault(parts, []).append({
                "priority": priority,
                "order": order,
                "source": deepcopy(source),
                "value": deepcopy(item),
            })

    resolved: dict = {}
    provenance: dict[str, dict] = {}
    conflicts: list[dict] = []
    for parts in sorted(candidates):
        choices = candidates[parts]
        winner = max(choices, key=lambda item: (item["priority"], item["order"]))
        _assign_path(resolved, parts, winner["value"])
        pointer = _pointer(parts)
        provenance[pointer] = {
            "source": deepcopy(winner["source"]),
            "priority": winner["priority"],
        }
        distinct = {
            json.dumps(item["value"], ensure_ascii=False, sort_keys=True, default=str)
            for item in choices
        }
        if len(distinct) > 1:
            conflicts.append({
                "path": pointer,
                "winner": {
                    "source": deepcopy(winner["source"]),
                    "priority": winner["priority"],
                    "value": deepcopy(winner["value"]),
                },
                "candidates": deepcopy(choices),
                "rule": (
                    "higher-priority"
                    if len({item["priority"] for item in choices}) > 1
                    else "later-layer"
                ),
            })

    plan = canonical_generation_plan(resolved)
    plan["provenance"] = deepcopy(plan.get("provenance") or [])
    return {
        "blueprint": plan,
        "provenance": provenance,
        "conflicts": conflicts,
        "fingerprint": fingerprint_blueprint(plan),
    }


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
