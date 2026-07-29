# -*- coding: utf-8 -*-
"""성공한 생성 이미지의 저장·계보·재개 장부를 순서대로 확정한다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GenerationCommitOperations:
    save_image: Callable[..., Path]
    output_format: Callable[[dict], str]
    output_clean_args: Callable[[dict], tuple[bool, int]]
    output_clean: Callable[[dict], tuple[bool, int, int]]
    task_fingerprint: Callable[[str, dict, str, int, int], str]
    record_job_result: Callable[..., Any]
    output_root: Callable[[dict], Path]
    make_progress_record: Callable[..., dict]
    progress_item_key: Callable[[Any], tuple | None]
    bump_daily: Callable[[dict], Any]
    daily_count: Callable[[dict], int]
    save_state: Callable[[dict], Any]
    warning: Callable[..., Any]


def save_generation_result(
    operations: GenerationCommitOperations,
    config: dict,
    live: Any,
    step: dict,
    image: Any,
    *,
    seed_key: str,
    context_fingerprint: str,
    lineage_failures: int,
) -> dict:
    frozen = live.frozen_blueprint()
    image.nai_blueprint_fingerprint = str(
        (frozen or {}).get("fingerprint") or ""
    )
    clean, max_side = operations.output_clean_args(config)
    quality = operations.output_clean(config)[2]
    saved_path = operations.save_image(
        image,
        step["output_path"],
        fmt=operations.output_format(config),
        clean=clean,
        max_side=max_side,
        quality=quality,
    )

    character = step["character"]
    character_id = step["character_id"]
    scene_number = step["scene_number"]
    copy_number = step["copy_number"]
    fingerprint = operations.task_fingerprint(
        context_fingerprint,
        character,
        character_id,
        scene_number,
        copy_number,
    )
    try:
        operations.record_job_result(
            live.job_id,
            saved_path,
            artifact=saved_path.resolve().relative_to(
                operations.output_root(config).resolve()
            ).as_posix(),
            result_id=(
                "result-setting-"
                + hashlib.sha256(
                    f"{seed_key}\0{character_id}\0{scene_number}\0"
                    f"{copy_number}\0{fingerprint}".encode("utf-8")
                ).hexdigest()[:24]
            ),
        )
    except Exception as error:
        lineage_failures += 1
        operations.warning(
            "세팅 결과는 저장했지만 Job 계보 연결에 실패: %s",
            error,
        )
    live.set_image(image)
    return {
        "saved_path": saved_path,
        "fingerprint": fingerprint,
        "lineage_failures": lineage_failures,
    }


def commit_generation_progress(
    operations: GenerationCommitOperations,
    config: dict,
    state: dict,
    live: Any,
    step: dict,
    saved_path: Path,
    fingerprint: str,
    *,
    seed_key: str,
    done_this_run: dict,
    skip_set: set,
    completed: int,
    lineage_failures: int,
) -> dict:
    character_id = step["character_id"]
    scene_number = step["scene_number"]
    copy_number = step["copy_number"]
    done_this_run.setdefault(character_id, set()).add((
        scene_number,
        copy_number,
    ))
    record = operations.make_progress_record(
        config,
        scene_number,
        copy_number,
        saved_path,
        fingerprint,
    )
    progress = (
        state["progress"]
        .setdefault(seed_key, {})
        .setdefault(character_id, [])
    )
    progress[:] = [
        item
        for item in progress
        if operations.progress_item_key(item) != (scene_number, copy_number)
    ]
    progress.append(record)
    operations.bump_daily(state)
    completed += 1
    live.update(
        daily=operations.daily_count(state),
        completed=completed,
        failed=len(skip_set),
    )
    try:
        operations.save_state(state)
    except Exception as error:
        lineage_failures += 1
        operations.warning(
            "세팅 결과는 저장했지만 재개 장부 저장에 실패: %s",
            error,
        )
    return {
        "progress_record": record,
        "completed": completed,
        "lineage_failures": lineage_failures,
    }


def commit_generation_result(
    operations: GenerationCommitOperations,
    config: dict,
    state: dict,
    live: Any,
    step: dict,
    image: Any,
    *,
    seed_key: str,
    context_fingerprint: str,
    done_this_run: dict,
    skip_set: set,
    completed: int,
    lineage_failures: int,
) -> dict:
    """저장 성공 뒤 계보와 재개 상태를 갱신하고 부분 실패 수를 돌려준다."""
    saved = save_generation_result(
        operations,
        config,
        live,
        step,
        image,
        seed_key=seed_key,
        context_fingerprint=context_fingerprint,
        lineage_failures=lineage_failures,
    )
    progress = commit_generation_progress(
        operations,
        config,
        state,
        live,
        step,
        saved["saved_path"],
        saved["fingerprint"],
        seed_key=seed_key,
        done_this_run=done_this_run,
        skip_set=skip_set,
        completed=completed,
        lineage_failures=saved["lineage_failures"],
    )
    return {
        **saved,
        **progress,
    }


__all__ = [
    "GenerationCommitOperations",
    "commit_generation_progress",
    "commit_generation_result",
    "save_generation_result",
]
