# -*- coding: utf-8 -*-
"""생성 결과를 증거와 명시적 지식 자산으로 승격하는 순수 경계.

결과나 메타데이터에서 지식 내용을 추측하지 않는다. 사용자가 ``target``과
완전한 ``content``를 직접 제공한 경우에만 기존 evidence·knowledge 계약과
평가 승격 이벤트를 연결한다.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from src.nai_studio.domain.evaluation import (
    PROMOTION_SCHEMA,
    canonical_evaluation,
)
from src.nai_studio.domain.evidence import canonical_evidence
from src.nai_studio.domain.knowledge import canonical_knowledge_asset
from src.nai_studio.services.evaluation_bridge import (
    EVALUATION_EVENT_SCHEMA,
    promotion_event as evaluation_promotion_event,
)


RESULT_PROMOTION_SCHEMA = "nai-result-promotion/v1"
PROMOTION_LEDGER_SCHEMA = "nai-result-promotion-ledger/v1"
PROMOTION_TARGETS = ("style", "character")

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:pst-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._~+/-]{12,})"
)
_FORBIDDEN_KEYS = frozenset({
    "accesstoken",
    "apikey",
    "apitoken",
    "authorization",
    "binary",
    "body",
    "bytesdata",
    "cookie",
    "filebytes",
    "imagebase64",
    "imagebytes",
    "metadataraw",
    "password",
    "payload",
    "rawbytes",
    "rawmetadata",
    "rawpayload",
    "refreshtoken",
    "requestbody",
    "secret",
    "token",
})
_LINEAGE_FIELDS = (
    "manifest_index",
    "manifest_signature",
    "manifest_folder",
    "job_key",
    "mode",
    "style_id",
    "character_id",
    "seed",
    "seed_index",
    "width",
    "height",
)


def _mapping(value: Any, field: str) -> dict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return deepcopy(dict(value))


def _stable_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("promotion values must be JSON-compatible") from error
    return hashlib.sha256(encoded).hexdigest()


def _is_absolute_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (
        PureWindowsPath(text).is_absolute()
        or bool(PureWindowsPath(text).drive)
        or PurePosixPath(text).is_absolute()
        or text.startswith("\\\\")
    )


def _relative_path(value: Any, field: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or "://" in text
        or _is_absolute_path(text)
        or ".." in pure.parts
    ):
        raise ValueError(f"{field} must be a safe relative path")
    parts = [part for part in pure.parts if part not in ("", ".")]
    if not parts:
        raise ValueError(f"{field} must be a safe relative path")
    return "/".join(parts)


def _optional_relative_path(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return _relative_path(value, "comparison folder")
    except ValueError:
        return ""


def _sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _safe_text(value: Any, field: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if required and not value.strip():
        raise ValueError(f"{field} is required")
    if _TOKEN_PATTERN.search(value):
        raise ValueError(f"{field} must not contain an access token")
    if _is_absolute_path(value):
        raise ValueError(f"{field} must not contain an absolute path")
    return value


def _assert_safe_json(
    value: Any,
    field: str,
    *,
    allow_event_payload: bool = False,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(
                r"[\s_-]+",
                "",
                str(key).strip().casefold(),
            )
            event_payload = allow_event_payload and normalized == "payload"
            if (
                normalized in _FORBIDDEN_KEYS
                and not event_payload
                and item not in (None, "", [], {})
            ):
                raise ValueError(f"{field}.{key} is not allowed")
            _assert_safe_json(item, f"{field}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe_json(item, f"{field}[{index}]")
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{field} must not contain binary data")
    if isinstance(value, str):
        _safe_text(value, field)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must contain finite numbers")
    if value is not None and not isinstance(value, (bool, int, float)):
        raise TypeError(f"{field} contains a non-JSON value")


def _refs(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list")
    result = []
    for index, item in enumerate(value):
        text = _safe_text(item, f"{field}[{index}]", required=True)
        if text not in result:
            result.append(text)
    return result


def _content(target: str, value: Any) -> dict:
    raw = _mapping(value, "content")
    required = {
        "style": ("base", "negative", "generation_settings"),
        "character": (
            "prompt",
            "negative",
            "variants",
            "reference_refs",
            "vibe_refs",
        ),
    }[target]
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(
            f"{target} content is missing required fields: "
            + ", ".join(missing)
        )
    prompt_fields = ("base", "negative") if target == "style" else (
        "prompt",
        "negative",
    )
    for key in prompt_fields:
        if not isinstance(raw[key], str):
            raise TypeError(f"content.{key} must be a string")
    if target == "style":
        if not isinstance(raw["generation_settings"], Mapping):
            raise TypeError("content.generation_settings must be a mapping")
    else:
        if not isinstance(raw["variants"], list):
            raise TypeError("content.variants must be a list")
        raw["reference_refs"] = _refs(
            raw["reference_refs"],
            "content.reference_refs",
        )
        raw["vibe_refs"] = _refs(raw["vibe_refs"], "content.vibe_refs")
    _assert_safe_json(raw, "content")
    # 필수 묶음과 미래의 명시 필드를 그대로 보존하고 자동 결합·분해하지 않는다.
    return deepcopy(raw)


def _manifest_match(
    comparison_manifest: Mapping[str, Any],
    result_path: str,
) -> tuple[dict, str]:
    manifest = _mapping(comparison_manifest, "comparison_manifest")
    completed = manifest.get("completed")
    matches = []
    if isinstance(completed, Mapping):
        for job_key, value in completed.items():
            if not isinstance(value, Mapping):
                continue
            raw_path = value.get("file", value.get("path"))
            try:
                candidate = _relative_path(raw_path, "comparison result path")
            except ValueError:
                continue
            if candidate == result_path:
                matches.append((deepcopy(dict(value)), str(job_key)))
    elif any(key in manifest for key in ("file", "path")):
        candidate = _relative_path(
            manifest.get("file", manifest.get("path")),
            "comparison result path",
        )
        if candidate == result_path:
            matches.append((deepcopy(manifest), str(manifest.get("job_key") or "")))
    if len(matches) != 1:
        raise ValueError(
            "comparison_manifest must contain exactly one matching result"
        )
    return matches[0]


def _optional_scalar(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return deepcopy(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return deepcopy(value)
    if isinstance(value, str):
        try:
            return _safe_text(value, field)
        except ValueError:
            return ""
    return None


def _comparison_lineage(
    manifest: Mapping[str, Any],
    record: Mapping[str, Any],
    job_key: str,
    evaluation: Mapping[str, Any],
) -> dict:
    root = dict(manifest)
    evaluation_lineage = evaluation.get("comparison_lineage")
    if not isinstance(evaluation_lineage, Mapping):
        evaluation_lineage = {}
    result = {
        "kind": "comparison",
        "manifest_signature": _optional_scalar(
            root.get("signature"),
            "comparison_manifest.signature",
        ),
        "manifest_folder": _optional_relative_path(root.get("folder")),
        "job_key": _safe_text(
            job_key or str(record.get("job_key") or ""),
            "comparison job key",
        ),
        "mode": _optional_scalar(
            root.get("mode", record.get("mode")),
            "comparison mode",
        ),
    }
    for key in _LINEAGE_FIELDS:
        if key in result:
            continue
        value = (
            record.get(key)
            if record.get(key) is not None
            else evaluation_lineage.get(key)
        )
        result[key] = _optional_scalar(value, f"comparison lineage {key}")
    return result


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _execution_values(
    source: Mapping[str, Any],
    field: str,
    normalizer,
    source_name: str,
) -> list[Any]:
    values = []
    nested = source.get("execution")
    candidates = [source.get(field)]
    if isinstance(nested, Mapping):
        candidates.append(nested.get(field))
    for raw in candidates:
        if raw in (None, ""):
            continue
        value = normalizer(raw, f"{source_name}.{field}")
        if value not in values:
            values.append(value)
    if len(values) > 1:
        raise ValueError(
            f"{source_name} contains conflicting {field} values"
        )
    return values


def _execution_lineage(
    result: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict:
    specs = {
        "request_id": lambda value, field: _safe_text(
            value,
            field,
            required=True,
        ),
        "payload_hash": _sha256,
        "blueprint_fingerprint": _sha256,
    }
    output = {}
    verified_fields = []
    for field, normalizer in specs.items():
        caller = _execution_values(
            result,
            field,
            normalizer,
            "result_record",
        )
        record = _execution_values(
            manifest_record,
            field,
            normalizer,
            "comparison_manifest.completed",
        )
        root = _execution_values(
            manifest,
            field,
            normalizer,
            "comparison_manifest",
        )
        manifest_values = []
        for value in (*record, *root):
            if value not in manifest_values:
                manifest_values.append(value)
        if len(manifest_values) > 1:
            raise ValueError(
                f"comparison manifest contains conflicting {field} values"
            )
        if caller and manifest_values and caller[0] != manifest_values[0]:
            raise ValueError(
                f"result_record {field} does not match comparison manifest"
            )
        value = _first(
            caller[0] if caller else None,
            manifest_values[0] if manifest_values else None,
        )
        if value in (None, ""):
            raise ValueError(f"{field} is required")
        output[field] = value
        if manifest_values:
            verified_fields.append(field)
    output["manifest_verified"] = len(verified_fields) == len(specs)
    return output


def _canonical_promotion_decision(
    value: Mapping[str, Any],
    target: str,
) -> dict:
    raw = _mapping(value, "promotion decision")
    lineage = _mapping(raw.get("lineage"), "promotion decision lineage")
    if raw.get("schema") != PROMOTION_SCHEMA:
        raise ValueError("invalid promotion decision schema")
    if raw.get("target") != target:
        raise ValueError("promotion decision target does not match")
    if raw.get("status") != "proposed" or raw.get("automatic") is not False:
        raise ValueError("promotion decision must be an explicit proposal")
    expected = {
        "schema": PROMOTION_SCHEMA,
        "id": "promotion:" + _stable_hash({
            "target": target,
            "lineage": lineage,
        })[:32],
        "target": target,
        "status": "proposed",
        "automatic": False,
        "lineage": lineage,
    }
    if raw != expected:
        if raw.get("id") != expected["id"]:
            raise ValueError("promotion decision id does not match its content")
        raise ValueError("promotion decision is not canonical")
    return expected


def _canonical_promotion_event(
    value: Mapping[str, Any],
    target: str,
) -> dict:
    raw = _mapping(value, "promotion_event")
    payload = _mapping(raw.get("payload"), "promotion_event.payload")
    decision = _canonical_promotion_decision(
        payload.get("decision"),
        target,
    )
    decision_lineage = decision["lineage"]
    evaluation_id = _safe_text(
        payload.get("evaluation_id"),
        "promotion_event.payload.evaluation_id",
        required=True,
    )
    base_fingerprint = _sha256(
        payload.get("base_fingerprint"),
        "promotion_event.payload.base_fingerprint",
    )
    if decision_lineage.get("evaluation_id") != evaluation_id:
        raise ValueError(
            "promotion decision evaluation does not match event payload"
        )
    if decision_lineage.get("evaluation_fingerprint") != base_fingerprint:
        raise ValueError(
            "promotion decision fingerprint does not match event payload"
        )
    canonical_payload = {
        "evaluation_id": evaluation_id,
        "decision": decision,
        "base_fingerprint": base_fingerprint,
    }
    expected = {
        "schema": EVALUATION_EVENT_SCHEMA,
        "kind": "promotion-proposed",
        "payload": canonical_payload,
    }
    expected["id"] = "evaluation-event:" + _stable_hash(expected)[:32]
    if raw != expected:
        if raw.get("id") != expected["id"]:
            raise ValueError("promotion event id does not match its content")
        raise ValueError("promotion event is not canonical")
    return expected


def _evaluation_summary(value: Mapping[str, Any]) -> dict:
    evaluation = canonical_evaluation(value)
    memo = _safe_text(evaluation["memo"], "evaluation.memo")
    tags = _refs(evaluation["tags"], "evaluation.tags")
    evidence_refs = _refs(
        evaluation["evidence_refs"],
        "evaluation.evidence_refs",
    )
    return {
        "canonical": evaluation,
        "public": {
            "id": evaluation["id"],
            "fingerprint": evaluation["fingerprint"],
            "rating": deepcopy(evaluation["rating"]),
            "memo": memo,
            "tags": tags,
        },
        "evidence_refs": evidence_refs,
    }


def build_result_promotion(
    result_record: Mapping[str, Any],
    comparison_manifest: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    *,
    target: str,
    content: Mapping[str, Any],
    name: str = "",
) -> dict:
    """명시된 결과 하나를 증거 하나와 style/character 자산 하나로 만든다."""
    if target not in PROMOTION_TARGETS:
        raise ValueError("target must be style or character")
    result = _mapping(result_record, "result_record")
    manifest = _mapping(comparison_manifest, "comparison_manifest")
    image = result.get("image")
    if not isinstance(image, Mapping):
        image = {}
    result_path = _relative_path(
        _first(result.get("path"), result.get("file"), image.get("path")),
        "result image path",
    )
    image_sha = _sha256(
        _first(
            result.get("content_sha256"),
            result.get("image_sha256"),
            result.get("sha256"),
            image.get("content_sha256"),
            image.get("sha256"),
        ),
        "result image SHA",
    )
    manifest_record, job_key = _manifest_match(manifest, result_path)
    execution = _execution_lineage(result, manifest_record, manifest)
    evaluation_data = _evaluation_summary(evaluation)
    canonical_eval = evaluation_data["canonical"]
    expected_ref = f"result:{result_path}"
    if canonical_eval["result_refs"] != [expected_ref]:
        raise ValueError(
            "evaluation must refer to exactly the promoted result path"
        )
    explicit_content = _content(target, content)
    asset_name = _safe_text(name, "name")
    comparison = _comparison_lineage(
        manifest,
        manifest_record,
        job_key,
        canonical_eval,
    )
    decision_event = evaluation_promotion_event(canonical_eval, target)
    decision = decision_event["payload"]["decision"]
    lineage = {
        "source_result_ref": expected_ref,
        "result_image": {
            "path": result_path,
            "content_sha256": image_sha,
        },
        "execution": execution,
        "comparison": comparison,
        "evaluation": evaluation_data["public"],
        "promotion_decision_id": decision["id"],
        "promotion_event_id": decision_event["id"],
    }
    evidence = canonical_evidence({
        "kind": "generation-record",
        "image": {
            "path": result_path,
            "content_sha256": image_sha,
        },
        "source": {
            "kind": "generation-result",
            "result_ref": expected_ref,
        },
        "raw_metadata": None,
        "actual_generation": {},
        "evaluation": evaluation_data["public"],
        "execution": execution,
        "comparison_lineage": comparison,
        "lineage": lineage,
    })
    evidence_refs = [evidence["id"]]
    for ref in evaluation_data["evidence_refs"]:
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    asset = canonical_knowledge_asset({
        "kind": target,
        "lifecycle": "candidate",
        "name": asset_name,
        "evidence_refs": evidence_refs,
        "content": explicit_content,
        "lineage": lineage,
    })
    record = {
        "schema": RESULT_PROMOTION_SCHEMA,
        "kind": "result-to-knowledge",
        "target": target,
        "promotion_event": decision_event,
        "evidence": evidence,
        "knowledge_asset": asset,
        "lineage": lineage,
    }
    record["id"] = "result-promotion:" + _stable_hash({
        "target": target,
        "promotion_event_id": decision_event["id"],
        "evidence_id": evidence["id"],
        "knowledge_asset_id": asset["id"],
        "lineage": lineage,
    })[:40]
    return record


def _canonical_promotion(value: Mapping[str, Any]) -> dict:
    raw = _mapping(value, "promotion")
    if raw.get("schema") != RESULT_PROMOTION_SCHEMA:
        raise ValueError("invalid result promotion schema")
    target = raw.get("target")
    if target not in PROMOTION_TARGETS:
        raise ValueError("promotion target must be style or character")
    promotion = _canonical_promotion_event(
        raw.get("promotion_event"),
        target,
    )
    decision = promotion["payload"]["decision"]
    evidence = canonical_evidence(_mapping(raw.get("evidence"), "evidence"))
    if evidence["raw_metadata"] not in (None, {}):
        raise ValueError("promotion evidence must not contain raw metadata")
    if evidence["actual_generation"]:
        raise ValueError("promotion evidence must not contain a raw payload")
    evidence_path = _relative_path(
        evidence["image"].get("path"),
        "promotion evidence image path",
    )
    _sha256(
        evidence["image"].get("content_sha256"),
        "promotion evidence image SHA",
    )
    raw_asset = _mapping(raw.get("knowledge_asset"), "knowledge_asset")
    raw_asset["content"] = _content(target, raw_asset.get("content"))
    asset = canonical_knowledge_asset(raw_asset)
    if asset["kind"] != target:
        raise ValueError("knowledge asset target does not match")
    if evidence["id"] not in asset["evidence_refs"]:
        raise ValueError("knowledge asset must reference promotion evidence")
    lineage = _mapping(raw.get("lineage"), "lineage")
    if evidence.get("lineage") != lineage or asset.get("lineage") != lineage:
        raise ValueError("promotion lineage must match evidence and asset")
    execution_lineage = lineage.get("execution")
    if (
        not isinstance(execution_lineage, Mapping)
        or not isinstance(execution_lineage.get("manifest_verified"), bool)
    ):
        raise ValueError(
            "promotion execution lineage must state manifest verification"
        )
    if lineage.get("source_result_ref") != f"result:{evidence_path}":
        raise ValueError("promotion result lineage does not match image path")
    evaluation_lineage = lineage.get("evaluation")
    if not isinstance(evaluation_lineage, Mapping):
        raise ValueError("promotion evaluation lineage is required")
    decision_lineage = decision["lineage"]
    if (
        evaluation_lineage.get("id") != decision_lineage.get("evaluation_id")
        or evaluation_lineage.get("fingerprint")
        != decision_lineage.get("evaluation_fingerprint")
        or lineage.get("source_result_ref")
        != decision_lineage.get("source_result_ref")
    ):
        raise ValueError("promotion decision lineage does not match record")
    if lineage.get("promotion_decision_id") != decision["id"]:
        raise ValueError("promotion decision lineage id does not match")
    if lineage.get("promotion_event_id") != promotion["id"]:
        raise ValueError("promotion event lineage id does not match")
    _assert_safe_json(
        promotion,
        "promotion_event",
        allow_event_payload=True,
    )
    _assert_safe_json(evidence, "evidence")
    _assert_safe_json(lineage, "lineage")
    _assert_safe_json(asset, "knowledge_asset")
    result = {
        "schema": RESULT_PROMOTION_SCHEMA,
        "kind": "result-to-knowledge",
        "target": target,
        "promotion_event": deepcopy(promotion),
        "evidence": evidence,
        "knowledge_asset": asset,
        "lineage": lineage,
    }
    result["id"] = "result-promotion:" + _stable_hash({
        "target": target,
        "promotion_event_id": promotion["id"],
        "evidence_id": evidence["id"],
        "knowledge_asset_id": asset["id"],
        "lineage": lineage,
    })[:40]
    return result


def new_promotion_ledger() -> dict:
    return {"schema": PROMOTION_LEDGER_SCHEMA, "events": []}


def append_promotion_events(
    ledger: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
) -> dict:
    """기존 순서를 보존하고 같은 결정 ID는 한 번만 붙이는 순수 append."""
    source = new_promotion_ledger() if ledger is None else _mapping(
        ledger,
        "ledger",
    )
    if (
        source.get("schema") != PROMOTION_LEDGER_SCHEMA
        or not isinstance(source.get("events"), list)
    ):
        raise ValueError("invalid promotion ledger")
    output = [_canonical_promotion(item) for item in source["events"]]
    seen = {item["id"] for item in output}
    appended = []
    duplicates = []
    for event in events:
        item = _canonical_promotion(event)
        if item["id"] in seen:
            duplicates.append(item["id"])
            continue
        seen.add(item["id"])
        output.append(item)
        appended.append(item["id"])
    return {
        "ledger": {
            "schema": PROMOTION_LEDGER_SCHEMA,
            "events": output,
        },
        "appended": appended,
        "duplicates": duplicates,
    }


__all__ = [
    "PROMOTION_LEDGER_SCHEMA",
    "PROMOTION_TARGETS",
    "RESULT_PROMOTION_SCHEMA",
    "append_promotion_events",
    "build_result_promotion",
    "new_promotion_ledger",
]
