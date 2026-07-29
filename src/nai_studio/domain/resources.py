# -*- coding: utf-8 -*-
"""Vibe·Character Reference의 무손실 자원과 교환 문서 계약."""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence


RESOURCE_SCHEMA = "nai-resource/v1"
RESOURCE_BUNDLE_SCHEMA = "nai-resource-bundle/v1"
RESOURCE_KINDS = ("vibe", "character-reference")
RESOURCE_VALUE_MIN = -1.0
RESOURCE_VALUE_MAX = 2.0

_PRIVATE_KEYS = {
    "token", "api_token", "access_token", "authorization",
    "path", "file_path", "local_path", "absolute_path", "original_path",
}
_CONTENT_EXCLUDED = {
    "schema", "id", "fingerprint", "name", "strength",
    "information_extracted", "fidelity", "ref_type", "source",
    "source_refs", "evidence_refs", "locked_fields", "created_at",
    "updated_at", "runtime", "setting_variants", "sources",
}
_ENCODED_KEYS = ("encoded", "encoding", "encoded_vibe", "encodedVibe")
_IE_KEYS = (
    "information_extracted", "informationExtracted", "info_extracted",
    "infoExtracted", "ie",
)


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _refs(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain non-empty string refs")
        if item not in result:
            result.append(item)
    return result


def _value(value: Any, field: str, default: float | None) -> int | float | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field} must be finite")
    if not RESOURCE_VALUE_MIN <= numeric <= RESOURCE_VALUE_MAX:
        raise ValueError(
            f"{field} must be between {RESOURCE_VALUE_MIN} "
            f"and {RESOURCE_VALUE_MAX}"
        )
    return deepcopy(value)


def _first(raw: Mapping[str, Any], names: Sequence[str], default: Any = None) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return default


def _public_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if (
                lowered in _PRIVATE_KEYS
                or lowered.endswith("_token")
                or lowered.endswith("_path")
            ):
                continue
            if lowered == "uri" and isinstance(item, str):
                if item.lower().startswith("file://") or re.match(
                    r"^[a-zA-Z]:[\\/]", item
                ):
                    continue
            output[str(key)] = _public_copy(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_public_copy(item) for item in value]
    return deepcopy(value)


def _hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("resource must contain JSON-compatible values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _image_ref(value: Any) -> dict:
    if isinstance(value, str):
        return {"uri": value}
    return _mapping(value, "image_ref")


def _canonical_without_identity(
    value: Mapping[str, Any] | None,
    *,
    kind: str | None = None,
) -> dict:
    raw = _mapping(value, "resource")
    raw_kind = raw.get("kind")
    if kind is not None and raw_kind not in (None, kind):
        raise ValueError("explicit kind conflicts with resource kind")
    kind = kind or raw_kind
    if kind not in RESOURCE_KINDS:
        raise ValueError(
            "resource kind must be one of: " + ", ".join(RESOURCE_KINDS)
        )

    encoded = _first(raw, _ENCODED_KEYS)
    if encoded is not None and not isinstance(encoded, str):
        raise TypeError("encoded must be a string or null")
    image_ref = _image_ref(
        raw.get("image_ref", raw.get("image"))
    )
    default_strength = 0.6 if kind == "vibe" else 1.0
    default_ie = 0.7 if kind == "vibe" else 1.0
    default_fidelity = None if kind == "vibe" else 0.6
    ref_type = raw.get(
        "ref_type",
        raw.get("referenceType", "vibe" if kind == "vibe" else "character&style"),
    )
    if not isinstance(ref_type, str) or not ref_type.strip():
        raise ValueError("ref_type must be a non-empty string")

    locked_fields = _refs(raw.get("locked_fields"), "locked_fields")
    if encoded and not image_ref and "information_extracted" not in locked_fields:
        locked_fields.append("information_extracted")
    result = {
        "schema": RESOURCE_SCHEMA,
        "kind": kind,
        "name": deepcopy(raw.get("name", "")),
        "image_ref": image_ref,
        "encoded": encoded,
        "model": deepcopy(raw.get("model", "")),
        "strength": _value(
            raw.get("strength"),
            "strength",
            default_strength,
        ),
        "information_extracted": _value(
            _first(raw, _IE_KEYS),
            "information_extracted",
            default_ie,
        ),
        "fidelity": _value(
            raw.get("fidelity"),
            "fidelity",
            default_fidelity,
        ),
        "ref_type": ref_type,
        "source": _mapping(raw.get("source"), "source"),
        "source_refs": _refs(raw.get("source_refs"), "source_refs"),
        "evidence_refs": _refs(raw.get("evidence_refs"), "evidence_refs"),
        "locked_fields": locked_fields,
    }
    aliases = set(_ENCODED_KEYS) | set(_IE_KEYS) | {
        "image", "referenceType",
    }
    for key, item in raw.items():
        if (
            key not in result
            and key not in {"id", "fingerprint"}
            and key not in aliases
        ):
            result[key] = deepcopy(item)
    return result


def fingerprint_resource(
    value: Mapping[str, Any] | None,
    *,
    kind: str | None = None,
) -> str:
    """사용 강도·출처와 무관한 이미지/encoding 내용 지문."""
    data = _canonical_without_identity(value, kind=kind)
    if data["encoded"]:
        image_identity = {}
    else:
        image_identity = _public_copy(data["image_ref"])
    identity = {
        key: _public_copy(item)
        for key, item in data.items()
        if key not in _CONTENT_EXCLUDED and key != "image_ref"
    }
    identity["image_ref"] = image_identity
    return _hash(identity)


def canonical_resource(
    value: Mapping[str, Any] | None = None,
    *,
    kind: str | None = None,
) -> dict:
    """Vibe 또는 Character Reference 한 건의 canonical 자원."""
    result = _canonical_without_identity(value, kind=kind)
    result["fingerprint"] = fingerprint_resource(result)
    result["id"] = f"resource:{result['kind']}:{result['fingerprint'][:32]}"
    return result


def _decode_document(value: bytes | str | Mapping[str, Any]) -> Any:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("resource document must be UTF-8 JSON") from exc
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("resource document must be valid JSON") from exc
    raise TypeError("resource document must be bytes, str, or mapping")


def _official_vibe_items(raw: Mapping[str, Any]) -> list[dict]:
    encodings = raw.get("encodings")
    if not isinstance(encodings, Mapping):
        data = raw.get("data")
        if isinstance(data, Mapping) and all(
            isinstance(item, (str, Mapping)) for item in data.values()
        ):
            encodings = data
    if isinstance(encodings, Mapping):
        base = {
            key: deepcopy(item)
            for key, item in raw.items()
            if key not in {"encodings", "data", "resources", "vibes", "items"}
        }
        output = []
        for model, item in encodings.items():
            row = deepcopy(base)
            row["kind"] = "vibe"
            row["model"] = str(model)
            if isinstance(item, str):
                row["encoded"] = item
            elif isinstance(item, Mapping):
                row.update(deepcopy(dict(item)))
                row.setdefault("model", str(model))
            else:
                raise ValueError("vibe encoding must be a string or mapping")
            output.append(row)
        return output
    return []


def _resource_item(value: Mapping[str, Any], default_kind: str | None) -> dict:
    raw = deepcopy(dict(value))
    kind = raw.get("kind", default_kind)
    aliases = {
        "cref": "character-reference",
        "character_reference": "character-reference",
        "characterReference": "character-reference",
    }
    kind = aliases.get(kind, kind)
    if kind is None and any(key in raw for key in _ENCODED_KEYS):
        kind = "vibe"
    return canonical_resource(raw, kind=kind)


def parse_resource_document(
    value: bytes | str | Mapping[str, Any],
    filename: str = "",
) -> dict:
    """NAI V4 vibe 파일과 우리 단일/묶음 JSON을 자동 판별."""
    raw = _decode_document(value)
    suffix = str(filename).lower()
    resources = []
    source_format = ""

    if isinstance(raw, list):
        resources = [_resource_item(item, None) for item in raw]
        source_format = "resource-list"
    elif not isinstance(raw, Mapping):
        raise ValueError("unknown resource document format")
    elif raw.get("schema") == RESOURCE_SCHEMA:
        resources = [_resource_item(raw, raw.get("kind"))]
        source_format = "nai-resource"
    elif raw.get("schema") == RESOURCE_BUNDLE_SCHEMA:
        items = raw.get("resources")
        if not isinstance(items, list):
            raise ValueError("resource bundle requires resources list")
        resources = [_resource_item(item, None) for item in items]
        source_format = "nai-resource-bundle"
    else:
        official = _official_vibe_items(raw)
        if official:
            resources = [_resource_item(item, "vibe") for item in official]
            source_format = "naiv4vibebundle"
        else:
            items = _first(raw, ("resources", "vibes", "items"))
            if isinstance(items, list):
                resources = [_resource_item(item, "vibe") for item in items]
                source_format = "naiv4vibebundle"
            else:
                identifier = str(
                    raw.get("identifier", raw.get("type", ""))
                ).lower()
                vibe_signal = (
                    suffix.endswith(".naiv4vibe")
                    or "vibe" in identifier
                    or any(key in raw for key in _ENCODED_KEYS)
                )
                if vibe_signal:
                    resources = [_resource_item(raw, "vibe")]
                    source_format = "naiv4vibe"
                else:
                    raise ValueError("unknown resource document format")
    if not resources:
        raise ValueError("resource document contains no resources")
    return {
        "schema": RESOURCE_BUNDLE_SCHEMA,
        "source_format": source_format,
        "resources": resources,
    }


def export_resource_document(
    resources: Sequence[Mapping[str, Any]],
    bundle: bool = True,
) -> bytes:
    """인증정보·로컬 경로를 제외한 UTF-8 JSON 교환 문서."""
    if not isinstance(resources, (list, tuple)):
        raise TypeError("resources must be a list")
    canonical = [
        _public_copy(canonical_resource(item))
        for item in resources
    ]
    if not canonical:
        raise ValueError("at least one resource is required")
    if bundle:
        document: Any = {
            "schema": RESOURCE_BUNDLE_SCHEMA,
            "resources": canonical,
        }
    else:
        if len(canonical) != 1:
            raise ValueError("single resource export requires exactly one item")
        document = canonical[0]
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _conflicts(group: Sequence[dict]) -> list[dict]:
    output = []
    for field in ("strength", "information_extracted", "fidelity", "ref_type"):
        values = []
        seen = set()
        for item in group:
            encoded = json.dumps(item.get(field), ensure_ascii=False, sort_keys=True)
            if encoded in seen:
                continue
            seen.add(encoded)
            values.append({
                "resource_id": item["id"],
                "source_refs": deepcopy(item["source_refs"]),
                "value": deepcopy(item.get(field)),
            })
        if len(values) > 1:
            output.append({
                "fingerprint": group[0]["fingerprint"],
                "path": field,
                "values": values,
            })
    return output


def merge_resources(*values: Mapping[str, Any]) -> dict:
    """동일 내용 자원은 계보를 합치고 설정 차이는 충돌로 돌려준다."""
    if len(values) == 1 and isinstance(values[0], (list, tuple)):
        values = tuple(values[0])
    if not values:
        raise ValueError("at least one resource is required")
    canonical = [canonical_resource(item) for item in values]
    groups: dict[str, list[dict]] = {}
    order = []
    for item in canonical:
        fingerprint = item["fingerprint"]
        if fingerprint not in groups:
            groups[fingerprint] = []
            order.append(fingerprint)
        groups[fingerprint].append(item)

    merged = []
    conflicts = []
    for fingerprint in order:
        group = groups[fingerprint]
        result = deepcopy(group[0])
        result["evidence_refs"] = []
        result["source_refs"] = []
        sources = []
        variants = []
        for item in group:
            for field in ("evidence_refs", "source_refs"):
                for ref in item[field]:
                    if ref not in result[field]:
                        result[field].append(ref)
            if item["source"] and item["source"] not in sources:
                sources.append(deepcopy(item["source"]))
            variant = {
                "strength": deepcopy(item["strength"]),
                "information_extracted": deepcopy(
                    item["information_extracted"]
                ),
                "fidelity": deepcopy(item["fidelity"]),
                "ref_type": deepcopy(item["ref_type"]),
                "source_refs": deepcopy(item["source_refs"]),
            }
            if variant not in variants:
                variants.append(variant)
        result["sources"] = sources
        result["setting_variants"] = variants
        # content fingerprint와 ID는 계보 병합으로 바뀌지 않는다.
        result["fingerprint"] = fingerprint
        result["id"] = f"resource:{result['kind']}:{fingerprint[:32]}"
        merged.append(result)
        conflicts.extend(_conflicts(group))
    return {"resources": merged, "conflicts": conflicts}
