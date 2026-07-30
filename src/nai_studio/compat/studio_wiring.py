# -*- coding: utf-8 -*-
"""legacy_surface의 줄 예산을 지키기 위한 추가 배선 모음.

`legacy_surface.py`는 모듈 경계 시험이 5,500줄로 고정한다. 잔여 계획의 새
기능(3-way 병합, 수집, 갱신)의 조립은 여기에 두고, legacy에는 import와
전개 한 줄만 남긴다. 서비스는 여전히 순수하고, 여기는 경로·공통 경계를
연결만 한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.nai_studio.runtime.data_files import (
    atomic_write_json,
    load_json_recover,
)
from src.nai_studio.services import merge_plan as _merge_plan


def user_backup_baseline_fields(profile_dir: Path) -> dict[str, Callable]:
    """UserBackupOperations에 얹을 3-way 기준값 배선.

    장부: `<프로필>/.nai-studio/merge-baseline.json`.
    내보내기는 `baseline_lookup`으로 읽고, 복원 적용은 `record_baseline`으로
    갱신한다.
    """
    path = _merge_plan.baseline_path(Path(profile_dir))

    def baseline_lookup(logical: str) -> dict | None:
        return _merge_plan.baseline_entry(
            _merge_plan.load_baseline(path, load_json_recover), logical)

    def record_baseline(applied: dict[str, bytes]) -> Any:
        return _merge_plan.record_applied_baseline(
            path, load_json_recover, atomic_write_json, applied)

    return {
        "baseline_lookup": baseline_lookup,
        "record_baseline": record_baseline,
    }


__all__ = ["user_backup_baseline_fields"]
