# -*- coding: utf-8 -*-
"""그림체 묶음의 비파괴 병합·저장·Undo 장부 연결 경계."""

from __future__ import annotations

import copy
import hashlib
import json
import re
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
    trash_file: Path


@dataclass(frozen=True)
class StyleStoreOperations:
    transaction: Callable[[Path], AbstractContextManager[Any]]
    lock: Any
    load_rows: Callable[[], list]
    atomic_write_json: Callable[..., None]
    normalize_model: Callable[[Any, str], Any]
    forget_caches: Callable[[], Any]
    record_import_batch: Callable[[dict], str | None]
    load_json: Callable[[Path], Any]
    deletion_stamp: Callable[[], str]


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


def load_styles(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
) -> list:
    """현재 그림체 원본을 복구 로더로 읽고 잘못된 최상위 값은 비운다."""
    if not paths.style_file.exists():
        return []
    try:
        rows = operations.load_json(paths.style_file)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def write_styles(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    rows: list,
) -> None:
    paths.style_file.parent.mkdir(parents=True, exist_ok=True)
    operations.atomic_write_json(paths.style_file, rows, indent=None)
    operations.forget_caches()


def delete_styles(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    ids: Any,
) -> dict:
    """선택 그림체를 원본에서 빼고 최대 5천 건 휴지통에 보존한다."""
    with operations.transaction(paths.transaction_root):
        with operations.lock:
            return _delete_styles(paths, operations, ids)


def _delete_styles(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    ids: Any,
) -> dict:
    wanted = {str(value) for value in (ids or []) if str(value)}
    if not wanted:
        return {"ok": False, "error": "고른 것이 없습니다."}
    rows = load_styles(paths, operations)
    kept = [row for row in rows if str(row.get("id")) not in wanted]
    removed = [row for row in rows if str(row.get("id")) in wanted]
    if not removed:
        return {"ok": False, "error": "그 그림체를 못 찾았습니다."}
    trash = _load_trash(paths, operations)
    stamp = operations.deletion_stamp()
    trash.extend({**row, "_지운때": stamp} for row in removed)
    paths.trash_file.parent.mkdir(parents=True, exist_ok=True)
    operations.atomic_write_json(paths.trash_file, trash[-5000:], indent=None)
    write_styles(paths, operations, kept)
    return {
        "ok": True,
        "지움": len(removed),
        "남음": len(kept),
        "되살릴수있음": len(trash),
    }


def _load_trash(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
) -> list:
    if not paths.trash_file.exists():
        return []
    try:
        rows = operations.load_json(paths.trash_file)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def restore_styles(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    ids: Any = None,
) -> dict:
    """선택 항목 또는 마지막 삭제 묶음을 현재 자료와 충돌 없이 복원한다."""
    with operations.transaction(paths.transaction_root):
        with operations.lock:
            return _restore_styles(paths, operations, ids)


def _restore_styles(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
    ids: Any,
) -> dict:
    if not paths.trash_file.exists():
        return {"ok": False, "error": "지운 그림체가 없습니다."}
    try:
        trash = operations.load_json(paths.trash_file)
    except Exception:
        return {"ok": False, "error": "지운 목록을 읽지 못했습니다."}
    if not isinstance(trash, list) or not trash:
        return {"ok": False, "error": "지운 그림체가 없습니다."}
    wanted = _restore_ids(trash, ids)
    if not any(str(row.get("id")) in wanted for row in trash):
        return {"ok": False, "error": "되살릴 것을 못 찾았습니다."}
    rows = load_styles(paths, operations)
    rows, remaining, added, conflicts = _merge_restored(rows, trash, wanted)
    write_styles(paths, operations, rows)
    operations.atomic_write_json(paths.trash_file, remaining, indent=None)
    return {
        "ok": True,
        "되살림": added,
        "충돌": conflicts,
        "남은휴지통": len(remaining),
    }


def _restore_ids(trash: list, ids: Any) -> set[str]:
    if ids:
        return {str(value) for value in ids}
    stamp = trash[-1].get("_지운때")
    return {
        str(row.get("id"))
        for row in trash
        if row.get("_지운때") == stamp
    }


def _merge_restored(
    rows: list,
    trash: list,
    wanted: set[str],
) -> tuple[list, list, int, int]:
    existing = {str(row.get("id")) for row in rows}
    remaining, added, conflicts = [], 0, 0
    for row in trash:
        row_id = str(row.get("id"))
        if row_id not in wanted:
            remaining.append(row)
        elif row_id in existing:
            remaining.append(row)
            conflicts += 1
        else:
            rows.insert(0, {
                key: value for key, value in row.items() if key != "_지운때"
            })
            existing.add(row_id)
            added += 1
    return rows, remaining, added, conflicts


def combo_fingerprint(row: dict) -> str:
    """작가 이름 집합을 순서·가중치·자료별 id와 무관한 지문으로 만든다."""
    artists = row.get("artists")
    if artists:
        return " ".join(sorted(
            (str(artist) or "").strip().lower()
            for artist in artists
            if artist
        ))
    combo = (row.get("combo") or "").lower()
    names = re.findall(r"artist:([^,:]+)", combo)
    if names:
        return " ".join(sorted(name.strip() for name in names))
    return re.sub(r"\s+", "", combo)


def find_style_dupes(
    paths: StyleStorePaths,
    operations: StyleStoreOperations,
) -> dict:
    """동일 작가 지문을 묶고 설정 근거가 풍부한 항목부터 보여 준다."""
    groups: dict[str, list] = {}
    rows = load_styles(paths, operations)
    for row in rows:
        fingerprint = combo_fingerprint(row)
        if fingerprint:
            groups.setdefault(fingerprint, []).append(row)
    duplicates = [
        _duplicate_group(fingerprint, group)
        for fingerprint, group in groups.items()
        if len(group) >= 2
    ]
    duplicates.sort(key=lambda group: -group["건수"])
    return {
        "ok": True,
        "묶음": len(duplicates),
        "겹친항목": sum(group["건수"] for group in duplicates),
        "전체": len(rows),
        "목록": duplicates[:300],
    }


def _duplicate_group(fingerprint: str, rows: list) -> dict:
    ordered = sorted(rows, key=lambda row: (
        0 if (row.get("params") or {}).get("seed") else 1,
        -len(json.dumps(row, ensure_ascii=False)),
    ))
    return {
        "지문": fingerprint[:120],
        "건수": len(ordered),
        "항목": [
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "source": row.get("source"),
                "설정값": bool((row.get("params") or {}).get("seed")),
                "작가수": row.get("count") or len(row.get("artists") or []),
            }
            for row in ordered
        ],
    }


__all__ = [
    "STYLE_SETTING_KEYS",
    "StyleStoreOperations",
    "StyleStorePaths",
    "add_style",
    "canonical_style_settings",
    "combo_fingerprint",
    "delete_styles",
    "find_style_dupes",
    "load_styles",
    "merge_style_evidence",
    "restore_styles",
    "style_bundle_signature",
    "write_styles",
]
