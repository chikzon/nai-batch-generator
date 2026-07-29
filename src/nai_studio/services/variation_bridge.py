# -*- coding: utf-8 -*-
"""기존 캐릭터 저장 구조와 이미지 변형 도메인 사이의 순수 어댑터.

파일을 읽거나 저장하지 않는다. 모든 반환값은 사본이며 승인 결과도 기존 레코드에
적용할 patch가 아니라 추가 가능한 후보 레코드다.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.nai_studio.domain.variations import (
    accept_variation,
    canonical_character_asset,
    plan_character_variation,
)


def _mapping(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _first(raw: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw:
            return deepcopy(raw.get(key))
    return deepcopy(default)


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _index_by_id(records: Sequence[Mapping[str, Any]] | None) -> dict[str, dict]:
    return {
        str(record.get("id")): deepcopy(dict(record))
        for record in (records or ())
        if isinstance(record, Mapping) and record.get("id") not in (None, "")
    }


def _selected_records(
    identifiers: Sequence[Any],
    records: Sequence[Mapping[str, Any]] | None,
) -> list[dict]:
    indexed = _index_by_id(records)
    selected = []
    for identifier in identifiers or ():
        key = str(identifier)
        record = indexed.get(key)
        if record is None:
            # 참조 파일이 아직 로드되지 않았어도 사용자의 연결 id는 버리지 않는다.
            record = {"id": key, "missing": True}
        selected.append(record)
    return selected


def character_asset_from_legacy_record(
    value: Mapping[str, Any],
    *,
    char_refs: Sequence[Mapping[str, Any]] | None = None,
    vibes: Sequence[Mapping[str, Any]] | None = None,
    origin: str = "characters",
) -> dict:
    """기존 ``characters`` 또는 ``char_slots`` 한 건을 자산 사본으로 투영한다."""
    record = _mapping(value)
    reference_ids = _list(record.get("reference_ids"))
    vibe_ids = _list(record.get("vibe_ids"))
    selected_refs = _selected_records(reference_ids, char_refs)
    selected_vibes = _selected_records(vibe_ids, vibes)
    primary_ref = selected_refs[0] if selected_refs else {}

    images = _list(_first(record, "evidence_images", "images", default=[]))
    representative = _first(
        record, "representative", "representative_image", "image", default=None
    )
    if representative is None and images:
        representative = deepcopy(images[0])
    references = {
        "c1": _mapping(record.get("c1")),
        "character_reference": ({
            "ref": {"id": str(primary_ref.get("id"))},
            "enabled": True,
            "strength": primary_ref.get("strength", 1.0),
            "fidelity": primary_ref.get("fidelity", 0.6),
            "ref_type": str(
                primary_ref.get("ref_type") or "character&style"
            ),
        } if primary_ref else {}),
        "reference_inset": _mapping(
            _first(record, "reference_inset", "inset", default={})
        ),
    }
    vibe_refs = [{
        "ref": {"id": str(item.get("id"))},
        "strength": item.get("strength", 0.6),
        "fidelity": item.get("info_extracted", item.get("fidelity", 0.7)),
        "legacy": deepcopy(item),
    } for item in selected_vibes]
    asset = canonical_character_asset({
        "id": str(record.get("id") or ""),
        "name": str(record.get("name") or ""),
        "appearance": str(
            _first(record, "appearance", "prompt", "female", default="") or ""
        ),
        "outfit": str(
            _first(record, "outfit", "clothed", default="") or ""
        ),
        "negative": str(record.get("negative") or ""),
        "variant": _mapping(record.get("variant")),
        "representative": representative,
        "evidence_images": images,
        "variation_images": _list(record.get("variation_images")),
        "references": references,
        "vibe_refs": vibe_refs,
        "random_pools": _mapping(record.get("random_pools")),
        "temporary_generation_overrides": _mapping(
            record.get("temporary_generation_overrides")
        ),
        "lineage": _list(record.get("lineage")),
        "legacy_origin": str(origin),
        "legacy_record": deepcopy(record),
        "legacy_reference_records": selected_refs,
        "legacy_vibe_records": selected_vibes,
    })
    # 빈 legacy id를 명시 id로 취급해 빈 문자열이 되지 않게 canonical id를 복구한다.
    if not asset["id"]:
        without_id = deepcopy(asset)
        without_id.pop("id", None)
        asset = canonical_character_asset(without_id)
    return asset


def character_assets_from_legacy_config(
    value: Mapping[str, Any],
    *,
    include_slots: bool = True,
) -> list[dict]:
    """현재 설정의 저장 캐릭터와 실행 슬롯을 순서 그대로 모두 투영한다."""
    cfg = _mapping(value)
    refs = [
        item for item in _list(cfg.get("char_refs"))
        if isinstance(item, Mapping)
    ]
    vibes = [
        item for item in _list(cfg.get("vibes"))
        if isinstance(item, Mapping)
    ]
    output = [
        character_asset_from_legacy_record(
            item, char_refs=refs, vibes=vibes, origin="characters"
        )
        for item in _list(cfg.get("characters"))
        if isinstance(item, Mapping)
    ]
    if include_slots:
        output.extend(
            character_asset_from_legacy_record(
                item, char_refs=refs, vibes=vibes, origin="char_slots"
            )
            for item in _list(cfg.get("char_slots"))
            if isinstance(item, Mapping)
        )
    return output


def _bounded_float(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 값이 숫자가 아닙니다.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} 값은 {minimum:g}~{maximum:g} 범위여야 합니다.")
    return number


def _ref_material(reference: Any, *, strength: float, fidelity: float) -> dict:
    reference_id = ""
    if isinstance(reference, Mapping):
        reference_id = str(reference.get("id") or "")
    elif isinstance(reference, str) and ":" not in reference and "/" not in reference:
        reference_id = reference
    return {
        "id": reference_id or _stable_id("variation-ref", reference),
        "name": "변형 계획 Character Reference",
        "enabled": True,
        "ref_type": "character&style",
        "strength": strength,
        "fidelity": fidelity,
        # 실제 legacy runtime이 파일/bytes로 해석해야 하는 원본 참조.
        "image_ref": deepcopy(reference),
    }


def variation_plan_to_legacy_payload_material(
    asset: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict:
    """변형 계획을 기존 생성 함수에 연결할 손실 없는 Payload 재료로 바꾼다."""
    character = canonical_character_asset(asset)
    prepared = plan_character_variation(character, plan)
    temporary = _mapping(prepared.get("temporary_settings"))
    overrides = _mapping(prepared.get("prompt_overrides"))

    def character_value(canonical: str, alias: str) -> str:
        if canonical in overrides:
            return str(overrides.get(canonical) or "")
        if alias in overrides:
            return str(overrides.get(alias) or "")
        return str(character.get(canonical) or "")

    slot = {
        "id": character["id"],
        "name": str(character.get("name") or ""),
        "prompt": character_value("appearance", "prompt"),
        "outfit": character_value("outfit", "clothed"),
        "negative": character_value("negative", "negative"),
        "variant": deepcopy(character.get("variant") or {}),
        "enabled": True,
    }
    legacy_record = _mapping(character.get("legacy_record"))
    slot["reference_ids"] = _list(legacy_record.get("reference_ids"))
    slot["vibe_ids"] = _list(legacy_record.get("vibe_ids"))

    reference_cfg = _mapping(
        _mapping(character.get("references")).get("character_reference")
    )
    reference_strength = _bounded_float(
        temporary.get(
            "reference_strength", reference_cfg.get("strength", 1.0)
        ),
        name="Character Reference strength",
        minimum=-1,
        maximum=2,
    )
    reference_fidelity = _bounded_float(
        temporary.get(
            "reference_fidelity", reference_cfg.get("fidelity", 0.6)
        ),
        name="Character Reference fidelity",
        minimum=-1,
        maximum=2,
    )
    char_refs = deepcopy(character.get("legacy_reference_records") or [])
    if prepared["mode"] == "character-reference":
        planned_ref = _ref_material(
            prepared["reference"],
            strength=reference_strength,
            fidelity=reference_fidelity,
        )
        char_refs = [planned_ref, *char_refs]

    i2i = None
    action = "generate"
    if prepared["mode"] in ("img2img", "inpaint"):
        action = "infill" if prepared["mode"] == "inpaint" else "img2img"
        cap = 1.0 if action == "infill" else 0.99
        strength = _bounded_float(
            temporary.get("strength", 0.7),
            name=f"{prepared['mode']} strength",
            minimum=0.01,
            maximum=cap,
        )
        noise = _bounded_float(
            temporary.get("noise", 0.0),
            name=f"{prepared['mode']} noise",
            minimum=0.0,
            maximum=1.0,
        )
        i2i = {
            "image_ref": deepcopy(prepared["source_image"]),
            "mask_ref": deepcopy(prepared["mask"]),
            "strength": strength,
            "noise": noise,
            "seed": prepared.get("seed"),
        }

    generation = {
        key: deepcopy(value)
        for key, value in temporary.items()
        if key not in (
            "strength", "noise", "reference_strength", "reference_fidelity"
        )
    }
    generation["seed"] = deepcopy(prepared.get("seed"))
    generation["resolution"] = deepcopy(prepared.get("resolution") or {})
    unresolved = [deepcopy(prepared["source_image"])]
    if prepared.get("mask") is not None:
        unresolved.append(deepcopy(prepared["mask"]))
    if prepared.get("reference") is not None:
        unresolved.append(deepcopy(prepared["reference"]))
    if prepared.get("inset") is not None:
        unresolved.append(deepcopy(prepared["inset"]))
    return {
        "schema": "nai-legacy-variation-payload-material/v1",
        "action": action,
        "mode": prepared["mode"],
        "char_slots": [slot],
        "char_refs": char_refs,
        "vibes": deepcopy(character.get("legacy_vibe_records") or []),
        "i2i": i2i,
        "reference_inset": deepcopy(prepared.get("inset")),
        "generation": generation,
        "unresolved_image_refs": unresolved,
        "variation_plan": deepcopy(prepared),
    }


def approved_proposal_to_legacy_candidates(
    legacy_character: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    approved: bool,
) -> dict:
    """명시 승인된 제안만 기존 저장 형식에 추가 가능한 후보로 변환한다."""
    if approved is not True:
        raise PermissionError("캐릭터 변형 제안은 명시적으로 승인해야 합니다.")
    record = _mapping(legacy_character)
    domain = _mapping(proposal)
    if domain.get("action") != "proposal-only":
        raise ValueError("자동 덮어쓰기 없는 변형 제안 형식이 아닙니다.")
    variant = _mapping(domain.get("variant"))
    evidence = _mapping(domain.get("evidence"))
    if variant.get("status") != "proposed" or evidence.get("status") != "proposed":
        raise ValueError("승인할 proposed Variant와 증거가 모두 필요합니다.")

    asset = character_asset_from_legacy_record(record)
    if str(domain.get("asset_id") or "") != asset["id"]:
        raise ValueError("제안이 다른 캐릭터 레코드를 가리킵니다.")
    legacy_variant = {
        "id": str(variant.get("id") or ""),
        "name": str(variant.get("name") or ""),
        "female": str(variant.get("appearance") or ""),
        "clothed": str(variant.get("outfit") or ""),
        "negative": str(variant.get("negative") or ""),
        "image_ref": deepcopy(variant.get("image_ref")),
        "lineage": deepcopy(variant.get("lineage") or {}),
        "status": "approved-candidate",
        "domain_proposal": deepcopy(variant),
    }
    legacy_evidence = {
        "id": str(evidence.get("id") or ""),
        "image_ref": deepcopy(evidence.get("image_ref")),
        "metadata": deepcopy(evidence.get("metadata") or {}),
        "lineage": deepcopy(evidence.get("lineage") or {}),
        "status": "approved-candidate",
        "domain_proposal": deepcopy(evidence),
    }
    return {
        "schema": "nai-legacy-character-addition-candidates/v1",
        "character_id": str(record.get("id") or asset["id"]),
        "base_record_fingerprint": asset["fingerprint"],
        "variant_candidate": legacy_variant,
        "evidence_candidate": legacy_evidence,
        "apply": "append-only",
        "original_record": deepcopy(record),
    }
