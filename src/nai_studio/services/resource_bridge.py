# -*- coding: utf-8 -*-
"""기존 VIBE_DIR 저장 구조와 canonical 자원을 잇는 순수 어댑터.

현재 저장 구조에는 별도 VIBE_INDEX 파일이 없다. 설정의 ``vibes``·``char_refs``
목록이 색인이고, 파일은 ``<id>.png``·``<id>.vibe``·``<id>.ref.png``로 연결된다.
이 모듈은 파일을 읽거나 쓰지 않고 호출자가 넘긴 file_index로 투영·쓰기 계획만
만든다. 기존 사용자 설정과 파일은 자동 변환하지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.nai_studio.domain.resources import (
    canonical_resource,
    export_resource_document,
    parse_resource_document,
)


LEGACY_IMPORT_PLAN_SCHEMA = "nai-legacy-resource-import-plan/v1"


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _rows(value: Any, field: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise TypeError(f"{field} must contain mappings")
    return [deepcopy(dict(item)) for item in value]


def _encoded_from_index(file_index: Mapping[str, Any], filename: str) -> str | None:
    value = file_index.get(filename)
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{filename} must contain ASCII encoded vibe data") from exc
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        encoded = value.get("encoded", value.get("text"))
        if encoded is None:
            return None
        if not isinstance(encoded, str):
            raise TypeError(f"{filename} encoded value must be a string")
        return encoded
    raise TypeError(f"{filename} file index value has unsupported type")


def _image_from_index(file_index: Mapping[str, Any], filename: str) -> dict:
    value = file_index.get(filename)
    if value is None:
        return {}
    if isinstance(value, bytes):
        return {
            "filename": filename,
            "content_sha256": hashlib.sha256(value).hexdigest(),
            "size": len(value),
            # 경로나 별도 파일에 의존하지 않는 교환 문서가 되게 한다.
            "data_base64": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, str):
        return {"filename": filename, "uri": value}
    if isinstance(value, Mapping):
        result = deepcopy(dict(value))
        # index에 실제 경로가 있어도 canonical/export 경계로 넘기지 않는다.
        for key in list(result):
            lowered = str(key).lower()
            if lowered == "path" or lowered.endswith("_path"):
                result.pop(key, None)
        result.setdefault("filename", filename)
        return result
    raise TypeError(f"{filename} file index value has unsupported type")


def _binding_record(
    item: Mapping[str, Any],
    resource: Mapping[str, Any],
    *,
    kind: str,
) -> dict:
    record = {
        "legacy_id": str(item.get("id") or ""),
        "resource_id": str(resource["id"]),
        "kind": kind,
        "enabled": item.get("enabled") is not False,
        "strength": deepcopy(item.get(
            "strength",
            0.6 if kind == "vibe" else 1.0,
        )),
    }
    if kind == "vibe":
        record["information_extracted"] = deepcopy(
            item.get("info_extracted", 0.7)
        )
        record["encoded_ie"] = deepcopy(item.get("encoded_ie"))
    else:
        record["fidelity"] = deepcopy(item.get("fidelity", 0.6))
        record["ref_type"] = str(
            item.get("ref_type") or "character&style"
        )
    return record


def _character_bindings(
    config: Mapping[str, Any],
    resource_ids: Mapping[str, str],
) -> tuple[list[dict], list[dict]]:
    output = []
    issues = []

    def add(source: str, item: Mapping[str, Any]) -> None:
        vibe_ids = [
            str(value) for value in (
                item.get("vibe_ids") or item.get("vibe_refs") or []
            ) if value
        ]
        reference_ids = [
            str(value) for value in (
                item.get("reference_ids")
                or item.get("character_reference_refs")
                or []
            ) if value
        ]
        missing = [
            value for value in vibe_ids + reference_ids
            if value not in resource_ids
        ]
        output.append({
            "source": source,
            "character_id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "vibe_refs": [
                resource_ids[value] for value in vibe_ids
                if value in resource_ids
            ],
            "character_reference_refs": [
                resource_ids[value] for value in reference_ids
                if value in resource_ids
            ],
            "missing_legacy_ids": missing,
        })
        for value in missing:
            issues.append({
                "code": "missing-resource-binding",
                "source": source,
                "legacy_id": value,
            })

    for index, item in enumerate(config.get("characters") or []):
        if isinstance(item, Mapping):
            add(f"characters[{index}]", item)
    for index, item in enumerate(config.get("char_slots") or []):
        if isinstance(item, Mapping):
            add(f"char_slots[{index}]", item)
    for preset_index, preset in enumerate(config.get("cast_presets") or []):
        if not isinstance(preset, Mapping):
            continue
        for member_index, item in enumerate(preset.get("members") or []):
            if isinstance(item, Mapping):
                add(
                    f"cast_presets[{preset_index}].members[{member_index}]",
                    item,
                )
    for setting_name, state in (config.get("setting_state") or {}).items():
        if not isinstance(state, Mapping):
            continue
        for index, item in enumerate(state.get("cast") or []):
            if isinstance(item, Mapping):
                add(f"setting_state.{setting_name}.cast[{index}]", item)
    return output, issues


def project_legacy_resources(
    config: Mapping[str, Any],
    *,
    file_index: Mapping[str, Any] | None = None,
) -> dict:
    """현재 설정 목록과 VIBE_DIR 파일 색인을 canonical 자원 사본으로 투영."""
    cfg = _mapping(config, "config")
    files = _mapping(file_index, "file_index")
    resources = []
    vibe_bindings = []
    reference_bindings = []
    resource_ids = {}
    issues = []
    model = str(cfg.get("model") or "")

    for item in _rows(cfg.get("vibes"), "vibes"):
        legacy_id = str(item.get("id") or "")
        if not legacy_id:
            issues.append({"code": "missing-legacy-id", "kind": "vibe"})
            continue
        image_name = f"{legacy_id}.png"
        encoded_name = f"{legacy_id}.vibe"
        image_ref = _image_from_index(files, image_name)
        encoded = _encoded_from_index(files, encoded_name)
        desired_ie = item.get("info_extracted", 0.7)
        encoded_ie = item.get("encoded_ie")
        actual_ie = (
            encoded_ie
            if encoded is not None and encoded_ie is not None
            else desired_ie
        )
        resource = canonical_resource({
            "kind": "vibe",
            "name": str(item.get("name") or legacy_id),
            "image_ref": image_ref,
            "encoded": encoded,
            "model": str(item.get("model") or model),
            "strength": item.get("strength", 0.6),
            "information_extracted": actual_ie,
            "source": {
                "kind": "legacy-vibe-dir",
                "legacy_id": legacy_id,
                "image_file": image_name,
                "encoded_file": encoded_name,
            },
            "source_refs": [f"legacy:vibe:{legacy_id}"],
            "evidence_refs": deepcopy(item.get("evidence_refs") or []),
            "requested_information_extracted": deepcopy(desired_ie),
            "encoded_at_information_extracted": deepcopy(encoded_ie),
        })
        resources.append(resource)
        resource_ids[legacy_id] = resource["id"]
        vibe_bindings.append(_binding_record(item, resource, kind="vibe"))
        if not image_ref and encoded is None:
            issues.append({
                "code": "missing-vibe-files",
                "legacy_id": legacy_id,
            })
        if (
            encoded is not None
            and encoded_ie is not None
            and float(encoded_ie) != float(desired_ie)
        ):
            issues.append({
                "code": "stale-vibe-encoding",
                "legacy_id": legacy_id,
                "encoded_ie": deepcopy(encoded_ie),
                "requested_ie": deepcopy(desired_ie),
                "can_reencode": bool(image_ref),
            })

    for item in _rows(cfg.get("char_refs"), "char_refs"):
        legacy_id = str(item.get("id") or "")
        if not legacy_id:
            issues.append({
                "code": "missing-legacy-id",
                "kind": "character-reference",
            })
            continue
        image_name = f"{legacy_id}.ref.png"
        image_ref = _image_from_index(files, image_name)
        resource = canonical_resource({
            "kind": "character-reference",
            "name": str(item.get("name") or legacy_id),
            "image_ref": image_ref,
            "model": str(item.get("model") or model),
            "strength": item.get("strength", 0.6),
            "information_extracted": 1.0,
            "fidelity": item.get("fidelity", 0.6),
            "ref_type": str(
                item.get("ref_type") or "character&style"
            ),
            "source": {
                "kind": "legacy-vibe-dir",
                "legacy_id": legacy_id,
                "image_file": image_name,
            },
            "source_refs": [f"legacy:character-reference:{legacy_id}"],
            "evidence_refs": deepcopy(item.get("evidence_refs") or []),
        })
        resources.append(resource)
        resource_ids[legacy_id] = resource["id"]
        reference_bindings.append(
            _binding_record(item, resource, kind="character-reference")
        )
        if not image_ref:
            issues.append({
                "code": "missing-character-reference-file",
                "legacy_id": legacy_id,
            })

    character_bindings, binding_issues = _character_bindings(
        cfg,
        resource_ids,
    )
    issues.extend(binding_issues)
    return {
        "resources": resources,
        "bindings": {
            "vibes": vibe_bindings,
            "character_references": reference_bindings,
            "characters": character_bindings,
        },
        "issues": issues,
    }


def export_legacy_resources(
    config: Mapping[str, Any],
    *,
    file_index: Mapping[str, Any] | None = None,
    bundle: bool = True,
) -> bytes:
    """기존 저장값을 토큰·절대경로 없는 canonical 교환 문서로 내보낸다."""
    projected = project_legacy_resources(config, file_index=file_index)
    return export_resource_document(projected["resources"], bundle=bundle)


def _legacy_id(resource: Mapping[str, Any], used: set[str]) -> str:
    prefix = "vibe" if resource["kind"] == "vibe" else "cref"
    base = f"{prefix}_{resource['fingerprint'][:16]}"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _embedded_image(image_ref: Mapping[str, Any]) -> bytes | None:
    encoded = image_ref.get(
        "data_base64",
        image_ref.get("bytes_base64"),
    )
    if encoded is None:
        return None
    if not isinstance(encoded, str):
        raise TypeError("embedded image must be a base64 string")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("embedded image is not valid base64") from exc


def legacy_resource_import_plan(
    document: bytes | str | Mapping[str, Any],
    *,
    filename: str = "",
    existing_config: Mapping[str, Any] | None = None,
) -> dict:
    """교환 문서를 기존 설정/파일 구조에 넣기 위한 비파괴 계획만 만든다."""
    cfg = _mapping(existing_config, "existing_config")
    parsed = parse_resource_document(document, filename=filename)
    used = {
        str(item.get("id"))
        for key in ("vibes", "char_refs")
        for item in (cfg.get(key) or [])
        if isinstance(item, Mapping) and item.get("id")
    }
    known_fingerprints = {
        str(item.get("resource_fingerprint"))
        for key in ("vibes", "char_refs")
        for item in (cfg.get(key) or [])
        if isinstance(item, Mapping) and item.get("resource_fingerprint")
    }
    seen_fingerprints = set(known_fingerprints)
    additions = {"vibes": [], "char_refs": []}
    writes = []
    skipped = []
    issues = []
    current_model = str(cfg.get("model") or "")

    for resource in parsed["resources"]:
        if resource["fingerprint"] in seen_fingerprints:
            skipped.append({
                "resource_id": resource["id"],
                "reason": "already-imported",
            })
            continue
        if (
            resource["kind"] == "vibe"
            and resource["encoded"]
            and resource["model"]
            and current_model
            and resource["model"] != current_model
        ):
            skipped.append({
                "resource_id": resource["id"],
                "reason": "model-mismatch",
                "resource_model": resource["model"],
                "current_model": current_model,
            })
            continue

        legacy_id = _legacy_id(resource, used)
        embedded = _embedded_image(resource["image_ref"])
        if resource["kind"] == "vibe":
            if not resource["encoded"] and embedded is None:
                skipped.append({
                    "resource_id": resource["id"],
                    "reason": "vibe-has-no-materializable-data",
                })
                continue
            item = {
                "id": legacy_id,
                "name": str(resource.get("name") or "가져온 바이브"),
                # 가져오기만으로 다음 생성에 영향을 주지 않는다.
                "enabled": False,
                "strength": deepcopy(resource["strength"]),
                "info_extracted": deepcopy(
                    resource["information_extracted"]
                ),
                "encoded_ie": (
                    deepcopy(resource["information_extracted"])
                    if resource["encoded"] else None
                ),
                "resource_fingerprint": resource["fingerprint"],
            }
            additions["vibes"].append(item)
            seen_fingerprints.add(resource["fingerprint"])
            if embedded is not None:
                writes.append({
                    "filename": f"{legacy_id}.png",
                    "kind": "binary",
                    "content": embedded,
                })
            if resource["encoded"] is not None:
                writes.append({
                    "filename": f"{legacy_id}.vibe",
                    "kind": "text",
                    "encoding": "ascii",
                    "content": resource["encoded"],
                })
        else:
            if embedded is None:
                skipped.append({
                    "resource_id": resource["id"],
                    "reason": "character-reference-requires-embedded-image",
                })
                continue
            item = {
                "id": legacy_id,
                "name": str(
                    resource.get("name") or "가져온 캐릭터 레퍼런스"
                ),
                "enabled": False,
                "ref_type": deepcopy(resource["ref_type"]),
                "strength": deepcopy(resource["strength"]),
                "fidelity": deepcopy(resource["fidelity"]),
                "resource_fingerprint": resource["fingerprint"],
            }
            additions["char_refs"].append(item)
            seen_fingerprints.add(resource["fingerprint"])
            writes.append({
                "filename": f"{legacy_id}.ref.png",
                "kind": "binary",
                "content": embedded,
            })

    return {
        "schema": LEGACY_IMPORT_PLAN_SCHEMA,
        "source_format": parsed["source_format"],
        "additions": additions,
        "writes": writes,
        "skipped": skipped,
        "issues": issues,
        "applied": False,
    }
