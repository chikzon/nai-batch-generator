# -*- coding: utf-8 -*-
"""그림체 묶음의 비파괴 병합·저장·Undo 장부 연결 경계."""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.nai_studio.services.datapack_store import row_key


STYLE_SETTING_KEYS = (
    "model",
    "width",
    "height",
    "cfg_scale",
    "cfg_rescale",
    "steps",
    "sampler",
    "scheduler",
    "variety",
    "uc_preset",
    "quality_toggle",
    "smea",
    "smea_dyn",
    "dynamic_thresholding",
    "uncond_scale",
    "controlnet_strength",
    "prefer_brownian",
    "deliberate_euler_ancestral_bug",
    "legacy_v3_extend",
    "use_coords",
    "position_mode",
)
_SETTING_ALIASES = {
    "cfg_scale": ("cfg_scale", "scale"),
    "scheduler": ("scheduler", "noise_schedule"),
    "variety": ("variety", "variety_plus", "skip_cfg_above_sigma"),
    "smea": ("smea", "sm"),
    "smea_dyn": ("smea_dyn", "sm_dyn"),
}
_INT_SETTINGS = {"width", "height", "steps", "uc_preset"}
_FLOAT_SETTINGS = {
    "cfg_scale",
    "cfg_rescale",
    "uncond_scale",
    "controlnet_strength",
}
_BOOL_SETTINGS = {
    "variety",
    "quality_toggle",
    "smea",
    "smea_dyn",
    "dynamic_thresholding",
    "prefer_brownian",
    "deliberate_euler_ancestral_bug",
    "legacy_v3_extend",
    "use_coords",
}


@dataclass(frozen=True)
class StyleStorePaths:
    style_file: Path
    transaction_root: Path


@dataclass(frozen=True)
class StyleStoreOperations:
    transaction: Callable[[Path], AbstractContextManager[Any]]
    lock: Any
    load_rows: Callable[[], list]
    atomic_write_json: Callable[..., None]
    normalize_model: Callable[[Any, str], Any]
    forget_caches: Callable[[], Any]
    record_import_batch: Callable[[dict], str | None]


def _value(record: dict, *names: str) -> Any:
    for name in names:
        if record.get(name) is not None:
            return record.get(name)
    return None


def canonical_style_settings(
    operations: StyleStoreOperations,
    record: Any,
) -> dict:
    record = record if isinstance(record, dict) else {}
    raw = _value(record, "settings", "설정", "params") or {}
    raw = raw if isinstance(raw, dict) else {}
    result = {}
    for key in STYLE_SETTING_KEYS:
        names = _SETTING_ALIASES.get(key, (key,))
        value = next((
            raw[name]
            for name in names
            if name in raw and raw[name] is not None
        ), None)
        if value is None:
            continue
        try:
            if key in _INT_SETTINGS:
                value = int(value)
            elif key in _FLOAT_SETTINGS:
                value = float(value)
            elif key in _BOOL_SETTINGS:
                value = (
                    value.strip().lower() in ("1", "true", "yes", "on")
                    if isinstance(value, str)
                    else bool(value)
                )
            elif key == "model":
                value = operations.normalize_model(
                    value,
                    str(value or "nai-diffusion-4-5-full"),
                )
            else:
                value = str(value)
        except (TypeError, ValueError, OverflowError):
            value = str(value)
        result[key] = value
    return result


def style_bundle_signature(
    operations: StyleStoreOperations,
    record: Any,
) -> str:
    record = record if isinstance(record, dict) else {}
    prompt = _value(record, "base", "prompt", "프롬프트")
    if prompt in (None, ""):
        prompt = record.get("combo") or ""
    negative = _value(record, "negative", "네거티브") or ""
    settings = canonical_style_settings(operations, record)
    if not (str(prompt or "") or str(negative or "") or settings):
        params = record.get("params") or {}
        fallback = {
            "artists": record.get("artists") or [],
            "combo": record.get("combo") or "",
            "seed": params.get("seed") if isinstance(params, dict) else None,
        }
        return json.dumps(
            {"legacy": fallback},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return json.dumps(
        {
            "prompt": str(prompt or ""),
            "negative": str(negative or ""),
            "settings": settings,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _row_digest(row: Any) -> str:
    payload = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def merge_style_evidence(existing: dict, incoming: dict) -> dict:
    """기존 원문·설정은 유지하고 같은 묶음의 새 이미지·출처만 더한다."""
    merged = copy.deepcopy(existing)
    images = list(merged.get("images") or [])
    for image in incoming.get("images") or []:
        if image not in images:
            images.append(image)
    if images:
        merged["images"] = images

    evidence = list(merged.get("evidence") or [])
    item = {
        key: copy.deepcopy(incoming.get(key))
        for key in ("title", "source", "url", "posted_at", "images")
        if incoming.get(key) not in (None, "", [])
    }
    if item:
        marker = json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        known = {
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for value in evidence
            if isinstance(value, dict)
        }
        if marker not in known:
            evidence.append(item)
    if evidence:
        merged["evidence"] = evidence

    records = list(merged.get("evidence_records") or [])
    known_ids = {
        str(item.get("id") or "")
        for item in records
        if isinstance(item, dict)
    }
    for record in incoming.get("evidence_records") or []:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or "")
        if record_id and record_id not in known_ids:
            records.append(copy.deepcopy(record))
            known_ids.add(record_id)
    if records:
        merged["evidence_records"] = records
    return merged


def add_style(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    record: dict,
    import_info: Any = None,
    return_detail: bool = False,
) -> dict | int:
    """동시 저장을 직렬화하고 기존 그림체 묶음에 근거만 비파괴 병합한다."""
    with operations.transaction(paths.transaction_root):
        with operations.lock:
            return _add_style(
                paths,
                operations,
                record,
                import_info,
                return_detail,
            )


def _add_style(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    record: dict,
    import_info: Any,
    return_detail: bool,
) -> dict | int:
    operations.forget_caches()
    rows = list(operations.load_rows())
    signature = style_bundle_signature(operations, record)
    action, changed, before, record_key = "added", True, None, ""
    saved_record = record
    for index, existing in enumerate(rows):
        if (
            not isinstance(existing, dict)
            or style_bundle_signature(operations, existing) != signature
        ):
            continue
        before = copy.deepcopy(existing)
        merged = merge_style_evidence(existing, record)
        changed = merged != existing
        if changed:
            rows[index] = merged
            action = "updated"
        else:
            action = "existing"
        record_key, _ = row_key(existing, "id")
        saved_record = rows[index]
        break
    else:
        saved_record = copy.deepcopy(record)
        if not saved_record.get("id"):
            digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
            saved_record["id"] = "style-" + digest[:20]
        record_key, _ = row_key(saved_record, "id")
        rows.insert(0, saved_record)

    if changed:
        paths.style_file.parent.mkdir(parents=True, exist_ok=True)
        operations.atomic_write_json(paths.style_file, rows, indent=None)

    batch_id = None
    if changed and isinstance(import_info, dict):
        batch = {
            "kind": str(import_info.get("kind") or "import"),
            "file": str(import_info.get("file") or "자료"),
            "lists": {},
            "files": copy.deepcopy(import_info.get("files") or {}),
            "installed": [],
            "list_updates": [],
            "요약": "",
        }
        if before is None:
            batch["lists"] = {"그림체.json": [record_key]}
            batch["요약"] = "그림체: 새 묶음 1건"
        else:
            batch["list_updates"] = [{
                "stem": "그림체.json",
                "key": record_key,
                "before": before,
                "after_sha256": _row_digest(saved_record),
            }]
            batch["요약"] = "그림체: 같은 묶음에 새 근거를 더함"
        batch_id = operations.record_import_batch(batch)

    if changed:
        operations.forget_caches()
    detail = {
        "total": len(rows),
        "action": action,
        "changed": changed,
        "id": saved_record.get("id"),
        "batch": batch_id,
    }
    return detail if return_detail else len(rows)


__all__ = [
    "STYLE_SETTING_KEYS",
    "StyleStoreOperations",
    "StyleStorePaths",
    "add_style",
    "canonical_style_settings",
    "merge_style_evidence",
    "style_bundle_signature",
]
