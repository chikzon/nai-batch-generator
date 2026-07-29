# -*- coding: utf-8 -*-
"""세팅 생성의 초기화·재개·준비·재시도·저장 경계를 조정한다."""

from __future__ import annotations

import copy
import hashlib
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.nai_studio.services.generation_commit import (
    GenerationCommitOperations,
    commit_generation_progress,
    save_generation_result,
)
from src.nai_studio.services.generation_retry import (
    GenerationRetryOperations,
    generate_with_retry,
)
from src.nai_studio.services.generation_step import (
    GenerationStepOperations,
    generation_reference_config,
    prepare_generation_attempt,
    prepare_generation_step,
)


@dataclass(frozen=True)
class GenerationExecutionOperations:
    step: GenerationStepOperations
    retry: GenerationRetryOperations
    commit: GenerationCommitOperations
    load_state: Callable[[], dict]
    save_state: Callable[[dict], Any]
    fixed_seed: Callable[[dict], int]
    daily_count: Callable[[dict], int]
    daily_cap: int
    load_asset_config: Callable[[dict], dict]
    context_fingerprint: Callable[[dict, dict], str]
    compute_pending: Callable[[dict, dict, dict, set], list]
    progress_record_valid: Callable[[dict, dict, str], bool]
    progress_record_path: Callable[[dict, dict], Path]
    pace: Callable[[dict], dict]
    output_sub: Callable[[dict, str], Path]
    runtime_params: Callable[[dict, str], dict]
    random_seed: Callable[[], int]
    random_uniform: Callable[[float, float], float]
    info: Callable[..., Any]
    warning: Callable[..., Any]
    error: Callable[..., Any]


def _initialize_run(
    operations: GenerationExecutionOperations,
    server: Any,
    config_snapshot: Any,
) -> dict:
    config = copy.deepcopy(
        config_snapshot
        if isinstance(config_snapshot, dict)
        else server.cfg
    )
    seed_index = int(config.get("seed", 1) or 1)
    seed_key = f"{seed_index:02d}"
    state = operations.load_state()
    if seed_key not in state["seeds"]:
        state["seeds"][seed_key] = operations.random_seed()
        operations.save_state(state)
    base_seed = state["seeds"][seed_key]
    state.setdefault("frag_seq", {})
    config["_frag_counters"] = state["frag_seq"]
    server.live.update(seed_key=seed_key)
    fixed = operations.fixed_seed(config)
    if fixed:
        operations.info(
            f"═══ 회차 {seed_key} — NAI 시드 고정 {fixed} "
            f"(모든 장이 같은 시드) ═══"
        )
    else:
        operations.info(
            f"═══ 회차 {seed_key} (기준 시드 {base_seed}) — "
            "장마다 '기준+씬번호' 시드. 같은 회차를 다시 돌리면 같은 결과 ═══"
        )
    operations.info(
        f"오늘 생성량: {operations.daily_count(state)}/{operations.daily_cap}"
    )
    characters = config.get("characters", [])
    enabled = [item for item in characters if item.get("enabled", True)]
    selection = " · ".join(
        f"{name} {len(value.get('selected', []))}세트"
        for name, value in (config.get("setting_state") or {}).items()
        if value.get("use") is not False and value.get("selected")
    )
    operations.info(
        f"캐릭터 {len(enabled)}명 켜짐 (전체 {len(characters)}명) · "
        f"선택: {selection or '없음'}"
    )
    if not enabled:
        operations.warning(
            "⚠ 켜진 캐릭터가 없습니다. "
            "브라우저에서 캐릭터를 추가하거나 켜주세요."
        )
    return {
        "config": config,
        "state": state,
        "seed_key": seed_key,
        "base_seed": base_seed,
    }


def _saved_progress(state: dict, seed_key: str) -> tuple[dict, int]:
    records = {}
    legacy_records = 0
    for character_id, items in (
        state.get("progress", {}).get(seed_key) or {}
    ).items():
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                legacy_records += 1
                continue
            try:
                key = (
                    str(character_id),
                    int(item["scene"]),
                    int(item.get("copy", 1)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            records[key] = item
    return records, legacy_records


def _restore_completed(
    operations: GenerationExecutionOperations,
    server: Any,
    config: dict,
    state: dict,
    seed_key: str,
) -> dict:
    asset_config = operations.load_asset_config(config)
    context = operations.context_fingerprint(config, asset_config)
    records, legacy_records = _saved_progress(state, seed_key)
    done = {}
    verified = []
    invalid_records = 0
    candidates = operations.compute_pending(config, asset_config, {}, set())
    for character, character_id, scene_number, copy_number in candidates:
        record = records.get((character_id, scene_number, copy_number))
        if record is None:
            continue
        fingerprint = operations.commit.task_fingerprint(
            context,
            character,
            character_id,
            scene_number,
            copy_number,
        )
        if operations.progress_record_valid(record, config, fingerprint):
            done.setdefault(character_id, set()).add((
                scene_number,
                copy_number,
            ))
            verified.append((
                str(character_id),
                int(scene_number),
                int(copy_number),
                record,
                fingerprint,
            ))
        else:
            invalid_records += 1
    completed = sum(len(value) for value in done.values())
    lineage_failures = _link_verified(
        operations,
        server,
        config,
        seed_key,
        completed,
        verified,
    )
    if legacy_records or invalid_records:
        operations.warning(
            "재개 기록 중 파일 또는 설정 근거가 없는 %d건은 다시 생성합니다.",
            legacy_records + invalid_records,
        )
    server.live.update(
        completed=completed,
        eta_base_completed=completed,
        total=max(len(candidates), completed),
    )
    return {
        "done": done,
        "completed": completed,
        "lineage_failures": lineage_failures,
    }


def _link_verified(
    operations: GenerationExecutionOperations,
    server: Any,
    config: dict,
    seed_key: str,
    completed: int,
    verified: list,
) -> int:
    if not completed:
        return 0
    operations.info(
        f"회차 {seed_key}의 파일·설정이 일치하는 완료 "
        f"{completed}장을 건너뜁니다."
    )
    failures = 0
    for character_id, scene_number, copy_number, record, fingerprint in verified:
        try:
            operations.commit.record_job_result(
                server.live.job_id,
                operations.progress_record_path(record, config),
                artifact=str(record.get("path") or ""),
                result_id=(
                    "result-setting-"
                    + hashlib.sha256(
                        f"{seed_key}\0{character_id}\0{scene_number}\0"
                        f"{copy_number}\0{fingerprint}".encode("utf-8")
                    ).hexdigest()[:24]
                ),
            )
        except Exception as error:
            operations.warning(
                "검증된 세팅 결과의 Job 계보 연결 실패: %s",
                error,
            )
            failures += 1
    return failures


def _pause_before_next(
    operations: GenerationExecutionOperations,
    server: Any,
    config: dict,
    state: dict,
    completed: int,
) -> bool:
    policy = operations.pace(config)
    if (
        policy["cool_every"]
        and completed > 0
        and completed % policy["cool_every"] == 0
    ):
        operations.info(
            f"⏸ {policy['cool_every']}장 완료 — "
            f"{policy['cool_seconds']}초 쿨다운"
        )
        server.live.update(
            status_text=f"쿨다운 {policy['cool_seconds']}초..."
        )
        operations.save_state(state)
        return server.live.wait_cancelable(policy["cool_seconds"])
    if (
        policy["soft_every"]
        and completed > 0
        and completed % policy["soft_every"] == 0
    ):
        pause = max(
            1.0,
            policy["soft_seconds"] + operations.random_uniform(-5, 10),
        )
        operations.info(f"⏸ 소프트 휴식 {pause:.0f}초")
        server.live.update(status_text=f"소프트 휴식 {pause:.0f}초...")
        operations.save_state(state)
        return server.live.wait_cancelable(pause)
    return False


def _prepare_step(
    operations: GenerationExecutionOperations,
    config: dict,
    asset_config: dict,
    item: tuple,
    *,
    base_seed: int,
    seed_key: str,
) -> tuple[dict, dict]:
    character, character_id, _, _ = item
    output_base = operations.output_sub(config, "nsfw_seed")
    output_dir = output_base / f"seed_{seed_key}" / character_id
    output_dir.mkdir(parents=True, exist_ok=True)
    scene = asset_config["scenes"][str(item[2])]
    reference_config = generation_reference_config(
        operations.step,
        config,
        scene,
        character,
    )
    params = operations.runtime_params(reference_config, config["token"])
    material = prepare_generation_step(
        operations.step,
        config,
        asset_config,
        item,
        base_seed=base_seed,
        seed_key=seed_key,
        output_base=output_base,
    )
    return material, params


def _execute_step(
    operations: GenerationExecutionOperations,
    server: Any,
    config: dict,
    state: dict,
    material: dict,
    runtime_params: dict,
    *,
    seed_key: str,
    context_fingerprint: str,
    done_this_run: dict,
    skip_set: set,
    completed: int,
    lineage_failures: int,
) -> dict | None:
    saved = {}

    def prepare_attempt() -> dict:
        return prepare_generation_attempt(
            operations.step,
            config,
            material,
            runtime_params,
        )

    def save_inside_attempt(image: Any, step: dict) -> Any:
        saved.update(save_generation_result(
            operations.commit,
            config,
            server.live,
            step,
            image,
            seed_key=seed_key,
            context_fingerprint=context_fingerprint,
            lineage_failures=lineage_failures,
        ))
        saved["step"] = step
        return image

    image = generate_with_retry(
        operations.retry,
        config,
        server.live,
        material,
        token=config["token"],
        failed_count=len(skip_set),
        prepare_attempt=prepare_attempt,
        on_success=save_inside_attempt,
        on_fatal_stop=lambda: operations.save_state(state),
    )
    if image is None:
        return None
    progress = commit_generation_progress(
        operations.commit,
        config,
        state,
        server.live,
        saved["step"],
        saved["saved_path"],
        saved["fingerprint"],
        seed_key=seed_key,
        done_this_run=done_this_run,
        skip_set=skip_set,
        completed=completed,
        lineage_failures=saved["lineage_failures"],
    )
    return {**saved, **progress}


def _stop_for_daily_limit(
    operations: GenerationExecutionOperations,
    server: Any,
    config: dict,
    state: dict,
) -> bool:
    if operations.daily_count(state) < operations.pace(config)["daily_cap"]:
        return False
    cap = operations.pace(config)["daily_cap"]
    operations.warning(
        f"일일 {cap}장 한도 도달. 내일 다시 실행하면 이어서 합니다."
    )
    server.live.update(
        status_text="일일 한도 도달 — 내일 다시 실행하면 이어집니다.",
        phase="stopped",
        can_retry=True,
    )
    operations.save_state(state)
    return True


def run_generation(
    operations: GenerationExecutionOperations,
    server: Any,
    config_snapshot: Any = None,
) -> None:
    """기존 세팅 생성 loop를 분리된 준비·재시도·저장 경계로 실행한다."""
    run = _initialize_run(operations, server, config_snapshot)
    config, state = run["config"], run["state"]
    seed_key, base_seed = run["seed_key"], run["base_seed"]
    restored = _restore_completed(
        operations,
        server,
        config,
        state,
        seed_key,
    )
    done_this_run = restored["done"]
    completed = restored["completed"]
    lineage_failures = restored["lineage_failures"]
    skip_set = set()

    while True:
        if server.live.stop_req:
            operations.info(
                "■ 중지되었습니다 — '생성 시작'을 다시 누르면 이어서 합니다."
            )
            server.live.update(
                status_text=(
                    "중지됨 — '생성 시작'을 누르면 이어서 합니다."
                ),
                phase="stopped",
                can_retry=True,
            )
            operations.save_state(state)
            return
        asset_config = operations.load_asset_config(config)
        context = operations.context_fingerprint(config, asset_config)
        pending = operations.compute_pending(
            config,
            asset_config,
            done_this_run,
            skip_set,
        )
        if not pending:
            break
        if _stop_for_daily_limit(
            operations, server, config, state
        ):
            return
        if _pause_before_next(
            operations, server, config, state, completed
        ):
            continue
        item = pending[0]
        total = completed + len(skip_set) + len(pending)
        try:
            step, runtime_params = _prepare_step(
                operations,
                config,
                asset_config,
                item,
                base_seed=base_seed,
                seed_key=seed_key,
            )
        except Exception as error:
            _skip_preparation_error(
                operations,
                server,
                item,
                completed,
                total,
                skip_set,
                error,
            )
            if server.live.wait_cancelable(1):
                return
            continue
        operations.info(
            f"[{completed + 1}/{total}] "
            f"({step['character_label']}) {step['filename']} "
            f"시드 {step['seed']} "
            f"(오늘 {operations.daily_count(state) + 1}/"
            f"{operations.daily_cap})"
        )
        server.live.update(
            index=completed + 1,
            total=total,
            filename=step["filename"],
            char_name=step["character_label"],
            status_text="생성 중...",
            seed=step["seed"],
        )
        result = _execute_step(
            operations,
            server,
            config,
            state,
            step,
            runtime_params,
            seed_key=seed_key,
            context_fingerprint=context,
            done_this_run=done_this_run,
            skip_set=skip_set,
            completed=completed,
            lineage_failures=lineage_failures,
        )
        if result is not None:
            completed = result["completed"]
            lineage_failures = result["lineage_failures"]
        else:
            skip_set.add((item[1], item[2], item[3]))
            server.live.update(
                status_text=f"실패 — 건너뜀: {step['filename']}",
                failed=len(skip_set),
                can_retry=True,
            )

    if lineage_failures:
        server.live.update(
            failed=max(server.live.failed, lineage_failures),
            status_text=(
                "이미지는 저장했지만 작업 계보·재개 장부 일부를 "
                "확인해야 합니다."
            ),
            phase="partial",
            can_retry=True,
        )


def _skip_preparation_error(
    operations: GenerationExecutionOperations,
    server: Any,
    item: tuple,
    completed: int,
    total: int,
    skip_set: set,
    error: Exception,
) -> None:
    operations.error(
        f"[{completed + 1}/{total}] "
        f"프롬프트/폴더 준비 중 오류로 이 컷 건너뜀: {error}"
    )
    operations.error(traceback.format_exc())
    skip_set.add((item[1], item[2], item[3]))
    server.live.update(
        status_text=f"오류(건너뜀): {error}",
        failed=len(skip_set),
        last_error=str(error),
        can_retry=True,
    )


__all__ = [
    "GenerationExecutionOperations",
    "run_generation",
]
