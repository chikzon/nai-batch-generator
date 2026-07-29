# -*- coding: utf-8 -*-
"""모든 NAI 생성 경로가 공유하는 호출 간격과 일일 상한."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PacingOperations:
    """상태 저장과 시계를 주입해 기존 patch·가상 시계 계약을 보존한다."""

    load_state: Callable[[], dict]
    daily_count: Callable[[dict], int]
    random_uniform: Callable[[float, float], float]
    now: Callable[[], float]
    sleep: Callable[[float], Any]
    last_call: dict[str, float]


def normalize_pace(config: dict, defaults: dict) -> dict:
    """잘못된 사용자 값을 기본값으로 되돌리고 지연 범위를 정렬한다."""
    pace = dict(defaults)
    for key, value in (config.get("pace") or {}).items():
        if key not in pace:
            continue
        try:
            pace[key] = (
                float(value)
                if key.startswith("delay")
                else int(value)
            )
        except (TypeError, ValueError):
            pass
    if pace["delay_max"] < pace["delay_min"]:
        pace["delay_max"] = pace["delay_min"]
    return pace


def wait_for_slot(
    operations: PacingOperations,
    config: dict,
    defaults: dict,
    live: Any = None,
) -> tuple[bool, str]:
    """마지막 요청 완료 시각부터 설정된 간격이 지날 때까지 기다린다."""
    pace = normalize_pace(config, defaults)
    state = operations.load_state()
    if operations.daily_count(state) >= pace["daily_cap"]:
        return (
            False,
            f"일일 상한 {pace['daily_cap']}장에 도달했습니다 — 내일 이어서 하세요.",
        )
    gap = operations.random_uniform(
        pace["delay_min"],
        pace["delay_max"],
    )
    while True:
        wait = operations.last_call["t"] + gap - operations.now()
        if wait <= 0:
            return True, ""
        if live is not None and getattr(live, "stop_req", False):
            return False, "중지되었습니다."
        operations.sleep(min(0.5, wait))


def mark_complete(operations: PacingOperations) -> None:
    """요청 성공 여부와 무관하게 다음 호출 간격의 기준 시각을 기록한다."""
    operations.last_call["t"] = operations.now()


__all__ = [
    "PacingOperations",
    "mark_complete",
    "normalize_pace",
    "wait_for_slot",
]
