# -*- coding: utf-8 -*-
"""재개할 생성 결과가 같은 계획의 온전한 파일인지 검증한다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


_FINGERPRINT_IGNORED = {"token", "booru_keys", "ui"}


def context_fingerprint(config: dict, assets: dict) -> str:
    """비밀값·표시 설정·런타임 키를 제외한 배치 입력의 안정 해시."""
    clean_config = {
        key: value
        for key, value in (config or {}).items()
        if (
            not str(key).startswith("_")
            and key not in _FINGERPRINT_IGNORED
        )
    }
    return _stable_hash({
        "config": clean_config,
        "assets": assets,
    })


def task_fingerprint(
    context: str,
    character: Any,
    character_id: Any,
    scene: Any,
    copy_number: Any,
) -> str:
    """배치 계획 안의 장면·인물·사본 한 칸을 식별한다."""
    return _stable_hash({
        "context": context,
        "char": character,
        "cid": character_id,
        "scene": int(scene),
        "copy": int(copy_number),
    })


def make_record(
    config: dict,
    scene: Any,
    copy_number: Any,
    saved_path: Any,
    fingerprint: str,
    output_root: Callable[[dict], Path],
) -> dict:
    """저장 위치와 실제 바이트 수를 재개 장부에 기록한다."""
    root = output_root(config).resolve()
    path = Path(saved_path).resolve()
    try:
        stored = path.relative_to(root).as_posix()
    except ValueError:
        stored = str(path)
    return {
        "scene": int(scene),
        "copy": int(copy_number),
        "path": stored,
        "bytes": path.stat().st_size,
        "fingerprint": fingerprint,
    }


def item_key(item: Any) -> tuple[int, int] | None:
    """구형 숫자·쌍 기록과 현재 객체 기록을 같은 키로 읽는다."""
    try:
        if isinstance(item, dict):
            return int(item["scene"]), int(item.get("copy", 1))
        if isinstance(item, (list, tuple)) and len(item) == 2:
            return int(item[0]), int(item[1])
        return int(item), 1
    except (KeyError, TypeError, ValueError):
        return None


def record_path(
    record: Any,
    config: dict,
    output_root: Callable[[dict], Path],
) -> Path | None:
    """상대 경로 기록은 현재 출력 루트 아래에서만 해석한다."""
    value = record.get("path") if isinstance(record, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return (
        path
        if path.is_absolute()
        else output_root(config).resolve() / path
    )


def record_valid(
    record: Any,
    config: dict,
    expected_fingerprint: str,
    output_root: Callable[[dict], Path],
) -> bool:
    """계획 해시·존재·비어 있지 않음·바이트 수가 모두 맞을 때만 재개한다."""
    if not isinstance(record, dict):
        return False
    if record.get("fingerprint") != expected_fingerprint:
        return False
    path = record_path(record, config, output_root)
    if path is None:
        return False
    try:
        size = path.stat().st_size
        return (
            path.is_file()
            and size > 0
            and size == int(record.get("bytes", -1))
        )
    except (OSError, TypeError, ValueError):
        return False


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "context_fingerprint",
    "item_key",
    "make_record",
    "record_path",
    "record_valid",
    "task_fingerprint",
]
