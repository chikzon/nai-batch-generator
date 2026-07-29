# -*- coding: utf-8 -*-
"""이미지 기반 캐릭터 자산과 비파괴 변형 계획 계약."""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Mapping


CHARACTER_ASSET_SCHEMA = "nai-character-asset/v1"
VARIATION_PLAN_SCHEMA = "nai-character-variation-plan/v1"
VARIATION_MODES = ("character-reference", "inpaint", "img2img")
REFERENCE_KINDS = ("c1", "character_reference", "reference_inset")


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _present(raw: Mapping[str, Any], key: str, *aliases: str) -> Any:
    if key in raw:
        return raw.get(key)
    for alias in aliases:
        if alias in raw:
            return raw.get(alias)
    return None


def _stable_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{hashlib.sha256(_stable_json(value)).hexdigest()[:24]}"


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _number(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
    default: float,
) -> float:
    if value in (None, ""):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 값이 숫자가 아닙니다.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} 값은 {minimum:g}~{maximum:g} 범위여야 합니다.")
    return number


def _validate_ref(value: Any, *, name: str, required: bool = False) -> Any:
    if value in (None, ""):
        if required:
            raise ValueError(f"{name} 참조가 필요합니다.")
        return None
    if isinstance(value, str):
        if not value.strip():
            if required:
                raise ValueError(f"{name} 참조가 필요합니다.")
            return None
        return value
    if isinstance(value, Mapping):
        result = deepcopy(dict(value))
        if not any(
            result.get(key) not in (None, "")
            for key in ("id", "path", "url", "content_hash", "image_ref")
        ):
            raise ValueError(
                f"{name} 참조에는 id, path, url, content_hash, image_ref 중 하나가 필요합니다."
            )
        return result
    raise TypeError(f"{name} 참조는 문자열 또는 참조 객체여야 합니다.")


def _canonical_reference(value: Any, *, kind: str) -> dict:
    raw = _mapping(value)
    ref = _present(raw, "ref", "image_ref", "image", "id")
    enabled = bool(raw.get("enabled", ref not in (None, "")))
    ref = _validate_ref(ref, name=kind, required=enabled)
    result = deepcopy(raw)
    result.update({
        "kind": kind,
        "enabled": enabled,
        "ref": ref,
        # 앱과 실제 API가 허용하는 확장 범위. 0~1로 조용히 자르지 않는다.
        "strength": _number(
            raw.get("strength"),
            name=f"{kind} strength",
            minimum=-1,
            maximum=2,
            default=1.0,
        ),
        "fidelity": _number(
            raw.get("fidelity"),
            name=f"{kind} fidelity",
            minimum=-1,
            maximum=2,
            default=0.6,
        ),
    })
    return result


def _canonical_vibe(value: Any, index: int) -> dict:
    if isinstance(value, str):
        raw = {"ref": value}
    else:
        raw = _mapping(value)
    ref = _validate_ref(
        _present(raw, "ref", "image_ref", "id"),
        name=f"vibe {index + 1}",
        required=True,
    )
    result = deepcopy(raw)
    result.update({
        "ref": ref,
        "strength": _number(
            raw.get("strength"),
            name=f"vibe {index + 1} strength",
            minimum=-1,
            maximum=2,
            default=0.6,
        ),
        "fidelity": _number(
            _present(raw, "fidelity", "info_extracted"),
            name=f"vibe {index + 1} fidelity",
            minimum=-1,
            maximum=2,
            default=0.7,
        ),
    })
    return result


def fingerprint_character_asset(value: Mapping[str, Any] | None) -> str:
    data = canonical_character_asset(value)
    for key in ("fingerprint", "created_at", "updated_at", "runtime"):
        data.pop(key, None)
    return hashlib.sha256(_stable_json(data)).hexdigest()


def canonical_character_asset(value: Mapping[str, Any] | None) -> dict:
    """대표·증거·변형 이미지와 캐릭터 원문을 한 자산으로 정규화한다."""
    raw = _mapping(value)
    representative = _validate_ref(
        _present(raw, "representative", "representative_image", "image"),
        name="대표 이미지",
    )
    evidence = [
        _validate_ref(item, name=f"증거 이미지 {index + 1}", required=True)
        for index, item in enumerate(
            _list(_present(raw, "evidence_images", "evidence"))
        )
    ]
    variation_images = [
        _validate_ref(item, name=f"변형 이미지 {index + 1}", required=True)
        for index, item in enumerate(
            _list(_present(raw, "variation_images", "variations"))
        )
    ]
    references_raw = _mapping(raw.get("references"))
    references = {}
    aliases = {
        "c1": ("c1",),
        "character_reference": ("character_reference", "character_ref"),
        "reference_inset": ("reference_inset", "inset"),
    }
    for kind, candidates in aliases.items():
        selected = references_raw.get(kind)
        if selected is None:
            selected = _present(raw, candidates[0], *candidates[1:])
        references[kind] = _canonical_reference(selected, kind=kind)

    result = deepcopy(raw)
    result["schema"] = CHARACTER_ASSET_SCHEMA
    result["name"] = _text(raw.get("name"))
    result["appearance"] = _text(
        _present(raw, "appearance", "prompt", "female")
    )
    result["outfit"] = _text(_present(raw, "outfit", "clothed"))
    result["negative"] = _text(raw.get("negative"))
    result["variant"] = _mapping(raw.get("variant"))
    result["representative"] = representative
    result["evidence_images"] = evidence
    result["variation_images"] = variation_images
    result["references"] = references
    result["vibe_refs"] = [
        _canonical_vibe(item, index)
        for index, item in enumerate(_list(raw.get("vibe_refs")))
    ]
    pools = _mapping(raw.get("random_pools"))
    result["random_pools"] = {
        **pools,
        "appearance": _list(
            _present(pools, "appearance", "appearances")
            if pools else _present(raw, "appearance_pool", "random_appearances")
        ),
        "outfit": _list(
            _present(pools, "outfit", "outfits")
            if pools else _present(raw, "outfit_pool", "random_outfits")
        ),
    }
    result["temporary_generation_overrides"] = _mapping(
        _present(raw, "temporary_generation_overrides", "temporary_settings")
    )
    result["lineage"] = deepcopy(
        raw.get("lineage") if raw.get("lineage") is not None else []
    )
    identity = {
        "name": result["name"],
        "appearance": result["appearance"],
        "outfit": result["outfit"],
        "negative": result["negative"],
        "representative": representative,
    }
    result["id"] = str(raw.get("id") or _stable_id("character", identity))
    fingerprint_data = deepcopy(result)
    fingerprint_data.pop("fingerprint", None)
    for key in ("created_at", "updated_at", "runtime"):
        fingerprint_data.pop(key, None)
    result["fingerprint"] = hashlib.sha256(_stable_json(fingerprint_data)).hexdigest()
    return result


def _canonical_resolution(value: Any) -> dict:
    raw = _mapping(value)
    result = deepcopy(raw)
    for key in ("width", "height"):
        if raw.get(key) in (None, ""):
            continue
        try:
            number = int(raw.get(key))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{key} 값이 정수가 아닙니다.") from exc
        if not 64 <= number <= 8192:
            raise ValueError(f"{key} 값은 64~8192 범위여야 합니다.")
        result[key] = number
    return result


def plan_character_variation(
    asset: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict:
    """기존 자산을 바꾸지 않고 한 번의 이미지 변형 실행 계획을 만든다."""
    character = canonical_character_asset(asset)
    raw = _mapping(request)
    mode = str(raw.get("mode") or "")
    if mode not in VARIATION_MODES:
        raise ValueError(
            "변형 mode는 character-reference, inpaint, img2img 중 하나여야 합니다."
        )
    source_image = _validate_ref(
        _present(raw, "source_image", "source", "image_ref")
        or character.get("representative"),
        name="원본 이미지",
        required=True,
    )
    reference = _validate_ref(
        _present(raw, "reference", "reference_image"),
        name="캐릭터 레퍼런스",
        required=False,
    )
    if mode == "character-reference" and reference is None:
        reference = source_image
    mask = _validate_ref(raw.get("mask"), name="인페인트 마스크")
    if mode == "inpaint" and mask is None:
        raise ValueError("inpaint 변형에는 마스크 참조가 필요합니다.")
    inset = _validate_ref(
        _present(raw, "inset", "reference_inset"),
        name="Reference inset",
    )
    seed = raw.get("seed")
    if seed not in (None, ""):
        try:
            seed = int(seed)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("seed 값이 정수가 아닙니다.") from exc
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("seed 값은 0~4294967295 범위여야 합니다.")
    else:
        seed = None

    temporary = deepcopy(character["temporary_generation_overrides"])
    temporary.update(_mapping(
        _present(raw, "temporary_settings", "temporary_generation_overrides")
    ))
    result = deepcopy(raw)
    result.update({
        "schema": VARIATION_PLAN_SCHEMA,
        "character_asset_id": character["id"],
        "character_asset_fingerprint": character["fingerprint"],
        "mode": mode,
        "source_image": source_image,
        "reference": reference,
        "mask": mask,
        "inset": inset,
        "prompt_overrides": _mapping(raw.get("prompt_overrides")),
        "seed": seed,
        "resolution": _canonical_resolution(raw.get("resolution")),
        "temporary_settings": temporary,
        "lineage": {
            "parent_asset_id": character["id"],
            "parent_asset_fingerprint": character["fingerprint"],
        },
    })
    identity = deepcopy(result)
    identity.pop("id", None)
    identity.pop("fingerprint", None)
    result["fingerprint"] = hashlib.sha256(_stable_json(identity)).hexdigest()
    result["id"] = str(
        raw.get("id")
        or _stable_id("variation-plan", {
            "asset": character["id"],
            "fingerprint": result["fingerprint"],
        })
    )
    return result


def accept_variation(
    asset: Mapping[str, Any],
    plan: Mapping[str, Any],
    generated: Mapping[str, Any],
) -> dict:
    """생성 결과를 자동 덮어쓰지 않고 증거·Variant 제안으로만 돌려준다."""
    character = canonical_character_asset(asset)
    recorded_asset_id = str((plan or {}).get("character_asset_id") or "")
    if recorded_asset_id and recorded_asset_id != character["id"]:
        raise ValueError("변형 계획이 다른 캐릭터 자산을 가리킵니다.")
    recorded_fingerprint = str(
        (plan or {}).get("character_asset_fingerprint") or ""
    )
    if recorded_fingerprint and recorded_fingerprint != character["fingerprint"]:
        raise ValueError("변형 계획 이후 캐릭터 자산이 변경되었습니다.")
    planned = plan_character_variation(character, plan)
    raw = _mapping(generated)
    image_ref = _validate_ref(
        _present(raw, "image_ref", "image", "artifact"),
        name="생성 결과 이미지",
        required=True,
    )
    prompt_overrides = _mapping(planned.get("prompt_overrides"))
    lineage = {
        "character_asset_id": character["id"],
        "character_asset_fingerprint": character["fingerprint"],
        "variation_plan_id": planned["id"],
        "variation_plan_fingerprint": planned["fingerprint"],
    }
    evidence = {
        "id": _stable_id("evidence-proposal", {
            "lineage": lineage,
            "image_ref": image_ref,
        }),
        "status": "proposed",
        "image_ref": deepcopy(image_ref),
        "metadata": _mapping(raw.get("metadata")),
        "lineage": deepcopy(lineage),
    }
    appearance = (
        _present(prompt_overrides, "appearance", "prompt")
        if any(key in prompt_overrides for key in ("appearance", "prompt"))
        else character["appearance"]
    )
    outfit = (
        _present(prompt_overrides, "outfit", "clothed")
        if any(key in prompt_overrides for key in ("outfit", "clothed"))
        else character["outfit"]
    )
    variant = {
        "id": _stable_id("variant-proposal", {
            "lineage": lineage,
            "image_ref": image_ref,
            "prompt_overrides": prompt_overrides,
        }),
        "status": "proposed",
        "name": _text(raw.get("name") or prompt_overrides.get("name")),
        "appearance": _text(appearance),
        "outfit": _text(outfit),
        "negative": _text(
            prompt_overrides.get("negative")
            if "negative" in prompt_overrides else character["negative"]
        ),
        "image_ref": deepcopy(image_ref),
        "lineage": deepcopy(lineage),
    }
    return {
        "schema": "nai-character-variation-proposal/v1",
        "asset_id": character["id"],
        "action": "proposal-only",
        "evidence": evidence,
        "variant": variant,
        "generated": deepcopy(raw),
    }
