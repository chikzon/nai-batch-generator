# -*- coding: utf-8 -*-
"""한 장의 NAI 호출에 속도 제한과 오류별 3회 재시도를 적용한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.nai_studio.runtime.errors import FatalStopError
from src.nai_studio.services.nai_client import (
    APIError,
    AccountBannedError,
    AuthError,
    RateLimitError,
)


@dataclass(frozen=True)
class GenerationRetryOperations:
    pace_gate: Callable[[dict, Any, str], tuple[bool, str]]
    pace_complete: Callable[[], Any]
    call_nai_api: Callable[..., Any]
    warning: Callable[[str], Any]
    error: Callable[[str], Any]
    critical: Callable[[str], Any]


def generate_with_retry(
    operations: GenerationRetryOperations,
    config: dict,
    live: Any,
    step: dict,
    *,
    token: str,
    failed_count: int = 0,
    prepare_attempt: Callable[[], dict] | None = None,
    on_success: Callable[[Any, dict], Any] | None = None,
    on_fatal_stop: Callable[[], Any] | None = None,
) -> Any | None:
    """현재 호출 순서와 대기 정책으로 한 장을 만들고 저장 전 이미지만 돌려준다."""
    for attempt in range(3):
        if live.stop_req:
            break
        allowed, reason = operations.pace_gate(config, live, "배치")
        if not allowed:
            live.update(status_text=reason)
            break
        try:
            current_step = prepare_attempt() if prepare_attempt else step
            try:
                image = operations.call_nai_api(
                    token,
                    current_step["base_prompt"],
                    current_step["negative_prompt"],
                    current_step["width"],
                    current_step["height"],
                    chars=current_step["people"],
                    scale=current_step["scale"],
                    cfg_rescale=current_step["cfg_rescale"],
                    steps=current_step["steps"],
                    sampler=current_step["sampler"],
                    scheduler=current_step["scheduler"],
                    uc_preset=current_step["uc_preset"],
                    seed=current_step["seed"],
                    variety=current_step["variety"],
                    params=current_step["params"],
                )
            finally:
                operations.pace_complete()
            return (
                on_success(image, current_step)
                if on_success
                else image
            )
        except RateLimitError as error:
            wait = error.retry_after
            operations.warning(
                f"  429 — 서버 지시대로 {wait:g}초 대기 후 재시도"
            )
            if attempt >= 2:
                break
            live.note_retry(error)
            live.update(status_text=f"429 — {wait:g}초 대기 중...")
            if live.wait_cancelable(wait):
                break
        except (AccountBannedError, AuthError) as error:
            operations.critical(f"  {error}")
            live.update(
                status_text=f"중단됨: {error}",
                failed=max(1, failed_count),
                last_error=str(error),
                phase="failed",
                can_retry=True,
            )
            if on_fatal_stop:
                on_fatal_stop()
            raise FatalStopError(str(error)) from error
        except APIError as error:
            operations.error(f"  시도 {attempt + 1} 실패: {error}")
            if not error.retryable:
                live.update(
                    status_text=f"재시도하지 않는 요청 오류: {error}",
                    last_error=str(error),
                )
                break
            if attempt >= 2:
                break
            wait = min(5 * (2 ** attempt), 30)
            live.note_retry(error)
            live.update(
                status_text=(
                    f"서버 오류 — {wait}초 뒤 재시도 "
                    f"({attempt + 1}/3)"
                )
            )
            if live.wait_cancelable(wait):
                break
        except Exception as error:
            operations.error(f"  시도 {attempt + 1} 실패: {error}")
            if attempt < 2:
                live.note_retry(error)
                live.update(
                    status_text=f"재시도 중... ({attempt + 1}/3)",
                    last_error=str(error),
                )
            if attempt < 2 and live.wait_cancelable(30):
                break
    return None


__all__ = [
    "GenerationRetryOperations",
    "generate_with_retry",
]
