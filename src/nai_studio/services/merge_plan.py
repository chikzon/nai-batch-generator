# -*- coding: utf-8 -*-
"""3-way 병합의 공통 기준값 계약.

백업(앞으로 자료팩·병합 화면도)이 공유하는 `기준 / 현재 / 들어오는 값` 판정을
한 곳에 둔다. 기준값 장부는 프로필의 `.nai-studio/merge-baseline.json`에 있고,
백업을 적용할 때 갱신되며, 새 백업을 내보낼 때 ZIP에 함께 실린다.

- JSON 파일은 값 자체를 보존해 항목(포인터) 단위 3-way를 제공한다.
- 이미지 등 바이너리는 내용 SHA-256만 보존한다 — 바이트를 중복 저장하지 않는다.
- 기준값이 없으면 판정은 `no-base`(기존 2-way)로 남는다. 자동 변환은 없다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

BASELINE_SCHEMA = "nais-merge-baseline/v1"
BASELINE_FILE_PARTS = (".nai-studio", "merge-baseline.json")

_MISSING = object()


def baseline_path(profile_dir: Path) -> Path:
    return Path(profile_dir).joinpath(*BASELINE_FILE_PARTS)


def load_baseline(path: Path, load_json: Callable[[Path], Any]) -> dict:
    """기준값 장부. 없거나 깨졌으면 빈 장부 — 판정만 no-base가 될 뿐이다."""
    try:
        data = load_json(Path(path))
    except Exception:
        return {"schema": BASELINE_SCHEMA, "files": {}}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"schema": BASELINE_SCHEMA, "files": {}}
    return data


def baseline_entry(baseline: dict, logical: str) -> dict | None:
    entry = (baseline.get("files") or {}).get(str(logical))
    return entry if isinstance(entry, dict) else None


def record_applied_baseline(
    path: Path,
    load_json: Callable[[Path], Any],
    atomic_write_json: Callable[..., None],
    applied: dict[str, bytes],
) -> dict:
    """적용이 끝난 파일들의 내용을 새 기준값으로 기록한다.

    JSON으로 읽히면 값을 보존하고, 아니면 해시만 남긴다.
    """
    baseline = load_baseline(path, load_json)
    files = baseline.setdefault("files", {})
    for logical, raw in sorted(applied.items()):
        entry = {"sha256": hashlib.sha256(raw).hexdigest(), "value": None}
        try:
            entry["value"] = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            pass
        files[str(logical)] = entry
    baseline["schema"] = BASELINE_SCHEMA
    atomic_write_json(path, baseline, keep_backup=False)
    return baseline


def baseline_export_payload(entry: dict | None) -> tuple[bytes | None, str]:
    """내보내기에 실을 기준값 바이트와 base_sha256.

    JSON 값이 있으면 그 바이트를 `baseline/<logical>`로 동봉하고,
    바이너리는 해시만 manifest에 적는다.
    """
    if not entry or not entry.get("sha256"):
        return None, ""
    if entry.get("value") is None:
        # 바이너리 — 원본 바이트의 해시만 싣는다 (현재/들어오는 파일 해시와 비교).
        return None, str(entry["sha256"])
    raw = json.dumps(
        entry["value"], ensure_ascii=False, indent=1).encode("utf-8")
    # JSON — 동봉 바이트 자체를 검증할 수 있도록 동봉본의 해시를 적는다.
    return raw, hashlib.sha256(raw).hexdigest()


def resolve_pointer(base: Any, tokens: tuple) -> tuple[bool, Any]:
    """`_collect_changes`의 토큰 경로를 기준값 위에서 따라간다.

    토큰: ("key", 키) · ("item", 필드, 값문자열) — user_backup_store와 같은 모양.
    """
    value = base
    for token in tokens:
        if token[0] == "key":
            if not isinstance(value, dict) or token[1] not in value:
                return False, None
            value = value[token[1]]
            continue
        field, wanted = token[1], str(token[2])
        if not isinstance(value, list):
            return False, None
        match = next(
            (
                item
                for item in value
                if isinstance(item, dict)
                and str(item.get(field, "")) == wanted
            ),
            None,
        )
        if match is None:
            return False, None
        value = match
    return True, value


def three_way_decision(
    base_found: bool,
    base: Any,
    current_exists: bool,
    current: Any,
    incoming_exists: bool,
    incoming: Any,
) -> str:
    """항목 하나의 병합 판정. 값이 같은 항목은 애초에 plan에 오르지 않는다.

    - take-incoming: 내 쪽이 기준값 그대로 → 들어오는 쪽만 바뀜
    - keep-current: 들어오는 쪽이 기준값 그대로 → 내 쪽만 바뀜
    - both-changed: 양쪽 다 기준값에서 벗어남 → 사용자가 고른다
    - no-base: 기준값이 없어 2-way — 사용자가 고른다
    """
    if not base_found:
        return "no-base"
    if current_exists and current == base:
        return "take-incoming"
    if incoming_exists and incoming == base:
        return "keep-current"
    return "both-changed"


def decision_for_hashes(
    base_sha256: str,
    current_sha256: str,
    incoming_sha256: str,
) -> str:
    """바이너리 파일의 파일 단위 3-way — 내용 해시로만 비교한다."""
    if not base_sha256:
        return "no-base"
    if current_sha256 == base_sha256:
        return "take-incoming"
    if incoming_sha256 == base_sha256:
        return "keep-current"
    return "both-changed"


__all__ = [
    "BASELINE_FILE_PARTS",
    "BASELINE_SCHEMA",
    "baseline_entry",
    "baseline_export_payload",
    "baseline_path",
    "decision_for_hashes",
    "load_baseline",
    "record_applied_baseline",
    "resolve_pointer",
    "three_way_decision",
]
