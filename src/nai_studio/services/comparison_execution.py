# -*- coding: utf-8 -*-
"""비교 작업 순서·재시도·진행 기록을 기존 실행 helper로 조립한다."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ComparisonExecutionOperations:
    """비교 runtime·planning·Job·NAI·result 경계를 호출 시점에 연결한다."""

    progress_start: Callable[..., tuple[dict[str, Any], Path]]
    save_progress: Callable[[dict[str, Any], Path], Any]
    link_job_ancestor: Callable[[str, str], Any]
    record_job_result: Callable[..., Any]
    output_file_for_preview: Callable[[dict, Any], Path | None]
    redact_diagnostic_text: Callable[[Any], str]
    warning: Callable[..., Any]
    info: Callable[..., Any]
    error: Callable[..., Any]
    iter_character_setting_jobs: Callable[..., Any]
    iter_selected_jobs: Callable[..., Any]
    iter_comparison_jobs: Callable[..., Any]
    comparison_job_values: Callable[..., tuple[Any, ...]]
    comparison_job_recipe_snapshot: Callable[..., dict[str, Any]]
    generation_blueprint: Callable[..., dict[str, Any]]
    safe_name: Callable[[Any], str]
    available_output_path: Callable[[Path, str], Path]
    output_format: Callable[[dict], str]
    output_root: Callable[[dict], Path]
    output_clean_args: Callable[[dict], tuple[Any, Any, Any]]
    pace: Callable[[dict], dict[str, Any]]
    pace_gate: Callable[..., tuple[bool, str]]
    pace_complete: Callable[[], Any]
    runtime_generation_params: Callable[..., dict[str, Any]]
    call_nai_api: Callable[..., Any]
    with_centers: Callable[[dict, list], dict]
    save_with_meta: Callable[..., Path]
    load_state: Callable[[], dict]
    daily_count: Callable[[dict], int]
    bump_daily: Callable[[dict], Any]
    save_state: Callable[[dict], Any]
    now_text: Callable[[], str]
    rate_limit_error: type[BaseException]
    account_errors: tuple[type[BaseException], ...]
    api_error: type[BaseException]


def _result_id(key: Any, blueprint_fingerprint: Any) -> str:
    digest = hashlib.sha256(
        f"{key}\0{blueprint_fingerprint or ''}".encode("utf-8")
    ).hexdigest()[:24]
    return "result-comparison-" + digest


def _bind_manifest_job(
    operations: ComparisonExecutionOperations,
    server: Any,
    progress: dict[str, Any],
    folder: Path,
) -> None:
    previous = str(progress.get("job_id") or "")
    current = str(server.live.job_id or "")
    if not current or progress.get("job_id") == current:
        return
    if previous:
        try:
            operations.link_job_ancestor(current, previous)
        except Exception as error:
            operations.warning(
                "이전 비교 Job 계보 연결 실패: %s", error
            )
    attempts = progress.setdefault("attempt_job_ids", [])
    for identifier in (previous, current):
        if identifier and identifier not in attempts:
            attempts.append(identifier)
    progress["job_id"] = current
    progress["request_id"] = current
    operations.save_progress(progress, folder)


def _reconnect_completed_results(
    operations: ComparisonExecutionOperations,
    server: Any,
    config: dict,
    progress: dict[str, Any],
) -> dict[str, Any]:
    errors = progress.setdefault("lineage_errors", {})
    if not server.live.job_id:
        return errors
    for key, record in progress["completed"].items():
        if not isinstance(record, dict):
            continue
        path = operations.output_file_for_preview(
            config, record.get("file")
        )
        if path is None:
            continue
        try:
            operations.record_job_result(
                server.live.job_id,
                path,
                artifact=str(record.get("file") or ""),
                result_id=_result_id(
                    key, record.get("blueprint_fingerprint")
                ),
            )
            errors.pop(str(key), None)
        except Exception as error:
            operations.warning(
                "검증된 비교 결과의 Job 계보 연결 실패: %s",
                error,
            )
            errors[str(key)] = operations.redact_diagnostic_text(
                error
            )
    return errors


def _comparison_jobs(
    operations: ComparisonExecutionOperations,
    config: dict,
    plan: dict,
    styles: list,
    characters: list,
    base_seed: int,
) -> Any:
    mode = plan["options"].get("mode")
    if mode == "character_setting":
        return operations.iter_character_setting_jobs(
            config, plan, characters
        )
    if mode == "selected":
        return operations.iter_selected_jobs(
            config,
            plan,
            styles,
            characters,
            runtime_base_seed=base_seed,
        )
    return operations.iter_comparison_jobs(
        config, plan, styles, characters
    )


def _job_seed(
    options: dict[str, Any],
    job: dict[str, Any],
    base_seed: int,
) -> tuple[int, int]:
    seed_index = int(job.get("seed_index") or 0)
    if options.get("mode") == "selected":
        seed = int(job.get("seed") or 0)
    elif options["same_seed"]:
        seed = (
            base_seed + seed_index * 100003
        ) & 0xFFFFFFFF
    else:
        seed = (
            base_seed + (job["index"] - 1) * 100003
        ) & 0xFFFFFFFF
    return seed_index, seed or 1


def _job_execution(
    operations: ComparisonExecutionOperations,
    config: dict,
    plan: dict,
    job: dict[str, Any],
    base_seed: int,
    folder: Path,
) -> dict[str, Any]:
    used, base, negative, people, centers = (
        operations.comparison_job_values(config, plan, job)
    )
    options = plan["options"]
    seed_index, seed = _job_seed(
        options, job, base_seed
    )
    execution_config = copy.deepcopy(used)
    execution_config.update({
        "base_prompt": base,
        "negative_prompt": negative,
        "char_slots": [
            {
                "name": f"비교 인물 {index + 1}",
                "prompt": str(person.get("prompt") or ""),
                "outfit": "",
                "negative": str(person.get("negative") or ""),
                "enabled": True,
            }
            for index, person in enumerate(people)
            if isinstance(person, dict)
        ],
        "char_centers": copy.deepcopy(centers),
        "nai_seed": seed,
    })
    blueprint = operations.generation_blueprint(
        execution_config,
        source={
            "kind": "comparison",
            "mode": options.get("mode"),
            "cell": str(job.get("key") or ""),
        },
        experiment={
            "mode": options.get("mode") or "comparison"
        },
    )
    style_label = job["style_name"]
    character_label = job["char_name"]
    suffix = (
        f"_S{seed_index + 1}"
        if int(options.get("seed_count") or 1) > 1
        else ""
    )
    stem = (
        f"{job['index']:06d}_"
        f"{operations.safe_name(style_label)[:38]}__"
        f"{operations.safe_name(character_label)[:32]}"
        f"{suffix}"
    )
    target = operations.available_output_path(
        folder / f"{stem}.webp",
        operations.output_format(config),
    )
    return {
        "used": used,
        "base": base,
        "negative": negative,
        "people": people,
        "centers": centers,
        "seed_index": seed_index,
        "seed": seed,
        "blueprint": blueprint,
        "style_label": style_label,
        "character_label": character_label,
        "target": target,
    }


def _announce_job(
    operations: ComparisonExecutionOperations,
    server: Any,
    plan: dict,
    execution: dict[str, Any],
    done_count: int,
) -> None:
    server.live.update(
        index=done_count + 1,
        total=plan["count"],
        filename=execution["target"].name,
        char_name=(
            f"{execution['style_label']} × "
            f"{execution['character_label']}"
        ),
        status_text=(
            "자료 비교 생성 중 — "
            f"{done_count + 1:,}/{plan['count']:,}"
        ),
        seed=execution["seed"],
    )
    operations.info(
        "[비교 %d/%d] %s × %s · %dx%d · 시드 %d",
        done_count + 1,
        plan["count"],
        execution["style_label"],
        execution["character_label"],
        execution["used"]["width"],
        execution["used"]["height"],
        execution["seed"],
    )


def _call_comparison_api(
    operations: ComparisonExecutionOperations,
    config: dict,
    options: dict[str, Any],
    token: str,
    execution: dict[str, Any],
) -> Any:
    used = execution["used"]
    params = operations.runtime_generation_params(
        used,
        token,
        include_refs=options["include_refs"],
    )
    try:
        return operations.call_nai_api(
            token,
            execution["base"],
            execution["negative"],
            int(used.get("width", 832)),
            int(used.get("height", 1216)),
            chars=execution["people"],
            scale=used.get("cfg_scale", 5.5),
            cfg_rescale=used.get("cfg_rescale", 0.56),
            steps=int(used.get("steps", 28)),
            sampler=used.get(
                "sampler", "k_euler_ancestral"
            ),
            scheduler=used.get("scheduler", "karras"),
            variety=used.get("variety", False),
            uc_preset=int(used.get("uc_preset", 4)),
            seed=execution["seed"],
            params=operations.with_centers(
                params, execution["centers"]
            ),
        )
    finally:
        operations.pace_complete()


def _save_generated_image(
    operations: ComparisonExecutionOperations,
    server: Any,
    config: dict,
    execution: dict[str, Any],
    image: Any,
) -> tuple[Path, str]:
    fingerprint = execution["blueprint"]["fingerprint"]
    image.nai_blueprint_fingerprint = fingerprint
    clean, max_side, quality = operations.output_clean_args(
        config
    )
    saved = operations.save_with_meta(
        image,
        execution["target"],
        fmt=operations.output_format(config),
        clean=clean,
        max_side=max_side,
        quality=quality,
    )
    server.live.set_image(image)
    relative = (
        saved.resolve()
        .relative_to(operations.output_root(config).resolve())
        .as_posix()
    )
    return saved, relative


def _link_new_result(
    operations: ComparisonExecutionOperations,
    server: Any,
    key: Any,
    saved: Path,
    relative: str,
    fingerprint: str,
    lineage_errors: dict[str, Any],
) -> None:
    try:
        operations.record_job_result(
            server.live.job_id,
            saved,
            artifact=relative,
            result_id=_result_id(key, fingerprint),
        )
        lineage_errors.pop(str(key), None)
    except Exception as error:
        lineage_errors[str(key)] = (
            operations.redact_diagnostic_text(error)
        )
        operations.warning(
            "비교 결과는 저장했지만 Job 계보 연결에 실패: %s",
            error,
        )


def _completed_record(
    operations: ComparisonExecutionOperations,
    config: dict,
    plan: dict,
    job: dict[str, Any],
    execution: dict[str, Any],
    saved: Path,
    relative: str,
    image: Any,
) -> dict[str, Any]:
    record = {
        "index": job["index"],
        "file": relative,
        "style": execution["style_label"],
        "character": execution["character_label"],
        "style_id": (
            (job.get("style") or {}).get("_compare_id")
        ),
        "character_id": (
            (job.get("character") or {}).get("_compare_id")
        ),
        "seed_index": execution["seed_index"],
        "seed": execution["seed"],
        "width": int(execution["used"]["width"]),
        "height": int(execution["used"]["height"]),
        "content_sha256": hashlib.sha256(
            saved.read_bytes()
        ).hexdigest(),
        "request_id": str(
            getattr(image, "nai_request_id", "") or ""
        ),
        "payload_hash": str(
            getattr(image, "nai_payload_hash", "") or ""
        ),
        "blueprint_fingerprint": execution[
            "blueprint"
        ]["fingerprint"],
    }
    mode = plan["options"].get("mode")
    if mode in ("character_setting", "selected"):
        record.update({
            "cell_id": job.get("cell_id"),
            "cell_resume_key": job.get("cell_resume_key"),
            "setting": job.get("setting_name"),
            "setting_id": (
                (job.get("setting") or {}).get("id")
                or (job.get("setting") or {}).get("name")
            ),
            "scene": int(job.get("scene_num") or 0),
            "copy": int(job.get("copy") or 1),
            "recipe": operations.comparison_job_recipe_snapshot(
                config,
                plan,
                job,
                execution["used"],
                execution["base"],
                execution["negative"],
                execution["people"],
                execution["centers"],
                execution["seed"],
            ),
        })
    if mode == "selected":
        _add_canonical_cell(record, job)
    return record


def _add_canonical_cell(
    record: dict[str, Any],
    job: dict[str, Any],
) -> None:
    cell = job.get("canonical_cell") or {}
    record["cid"] = str(job.get("cid") or "")
    record["cast_id"] = str(job.get("cid") or "")
    record["canonical_cell"] = {
        name: copy.deepcopy(cell.get(name))
        for name in (
            "id",
            "legacy_resume_key",
            "legacy_job_key",
            "seed_material",
            "legacy_material",
        )
        if cell.get(name) is not None
    }
    record["canonical_cell"]["blueprint"] = {
        "experiment": {"mode": "selected_groups"}
    }


def _record_success(
    operations: ComparisonExecutionOperations,
    server: Any,
    config: dict,
    plan: dict,
    progress: dict[str, Any],
    folder: Path,
    state: dict,
    completed: dict,
    errors: dict,
    run_failed: set,
    lineage_errors: dict,
    job: dict[str, Any],
    execution: dict[str, Any],
    image: Any,
) -> None:
    key = job["key"]
    saved, relative = _save_generated_image(
        operations, server, config, execution, image
    )
    _link_new_result(
        operations,
        server,
        key,
        saved,
        relative,
        execution["blueprint"]["fingerprint"],
        lineage_errors,
    )
    completed[key] = _completed_record(
        operations,
        config,
        plan,
        job,
        execution,
        saved,
        relative,
        image,
    )
    errors.pop(key, None)
    operations.bump_daily(state)
    try:
        operations.save_state(state)
    except Exception as error:
        lineage_errors[str(key)] = (
            operations.redact_diagnostic_text(error)
        )
        operations.warning(
            "비교 결과는 저장했지만 생성량 장부 저장에 실패: %s",
            error,
        )
    progress["updated_at"] = operations.now_text()
    try:
        operations.save_progress(progress, folder)
    except Exception as error:
        lineage_errors[str(key)] = (
            operations.redact_diagnostic_text(error)
        )
        operations.warning(
            "비교 결과는 저장했지만 재개 manifest 저장에 실패: %s",
            error,
        )
    server.live.update(
        daily=operations.daily_count(state),
        completed=len(completed),
        failed=len(run_failed),
        index=len(completed) + len(run_failed),
    )


def _attempt_job(
    operations: ComparisonExecutionOperations,
    server: Any,
    config: dict,
    plan: dict,
    progress: dict[str, Any],
    folder: Path,
    state: dict,
    completed: dict,
    errors: dict,
    run_failed: set,
    lineage_errors: dict,
    job: dict[str, Any],
    execution: dict[str, Any],
    final_status: str,
) -> tuple[bool, str, str, bool]:
    last_error = ""
    fatal = False
    for attempt in range(3):
        if server.live.stop_req:
            final_status = "stopped"
            break
        allowed, reason = operations.pace_gate(
            config, server.live, "자료 비교"
        )
        if not allowed:
            last_error = reason
            if "일일 상한" in reason:
                final_status = "daily_limit"
            break
        try:
            image = _call_comparison_api(
                operations,
                config,
                plan["options"],
                config["token"],
                execution,
            )
            _record_success(
                operations,
                server,
                config,
                plan,
                progress,
                folder,
                state,
                completed,
                errors,
                run_failed,
                lineage_errors,
                job,
                execution,
                image,
            )
            return True, "", final_status, fatal
        except operations.rate_limit_error as error:
            last_error = str(error)
            if attempt >= 2:
                break
            server.live.note_retry(error)
            server.live.update(
                status_text=(
                    f"429 — {error.retry_after:g}초 뒤 재시도"
                )
            )
            if server.live.wait_cancelable(error.retry_after):
                final_status = "stopped"
                break
        except operations.account_errors as error:
            last_error = str(error)
            server.live.update(
                status_text=f"즉시 중단: {error}"
            )
            final_status, fatal = "fatal", True
            break
        except operations.api_error as error:
            last_error = str(error)
            if not error.retryable or attempt >= 2:
                break
            wait = min(5 * (2**attempt), 30)
            server.live.note_retry(error)
            server.live.update(
                status_text=(
                    f"서버 오류 — {wait}초 뒤 재시도"
                )
            )
            if server.live.wait_cancelable(wait):
                final_status = "stopped"
                break
        except Exception as error:
            last_error = str(error)
            operations.error(
                "자료 비교 %s 실패(%d/3): %s",
                execution["target"].name,
                attempt + 1,
                error,
            )
            if attempt < 2:
                server.live.note_retry(error)
            if (
                attempt < 2
                and server.live.wait_cancelable(30)
            ):
                final_status = "stopped"
                break
    return False, last_error, final_status, fatal


def _record_failure(
    operations: ComparisonExecutionOperations,
    server: Any,
    progress: dict[str, Any],
    folder: Path,
    completed: dict,
    errors: dict,
    run_failed: set,
    job: dict[str, Any],
    execution: dict[str, Any],
    last_error: str,
) -> None:
    key = job["key"]
    errors[key] = {
        "index": job["index"],
        "style": execution["style_label"],
        "character": execution["character_label"],
        "error": last_error or "중지됨",
    }
    run_failed.add(key)
    server.live.update(
        index=len(completed) + len(run_failed),
        failed=len(run_failed),
        last_error=last_error or "중지됨",
        can_retry=True,
    )
    progress["updated_at"] = operations.now_text()
    operations.save_progress(progress, folder)


def _final_status(
    current: str,
    completed: dict,
    errors: dict,
    lineage_errors: dict,
    count: int,
) -> str:
    if current == "complete" and lineage_errors:
        return "partial"
    if current == "complete" and len(completed) < count:
        return "partial" if errors else "stopped"
    return current


def _finish_execution(
    operations: ComparisonExecutionOperations,
    server: Any,
    config: dict,
    plan: dict,
    progress: dict[str, Any],
    folder: Path,
    completed: dict,
    errors: dict,
    final_status: str,
) -> None:
    progress["status"] = final_status
    progress["updated_at"] = operations.now_text()
    progress["completed_count"] = len(completed)
    operations.save_progress(progress, folder)
    relative_folder = (
        folder.resolve()
        .relative_to(operations.output_root(config).resolve())
        .as_posix()
    )
    if final_status == "complete":
        text = (
            f"자료 비교 완료 — {len(completed):,}장 · "
            f"{relative_folder}"
        )
    elif final_status == "partial":
        text = (
            f"자료 비교 부분 완료 — 성공 {len(completed):,}장 · "
            f"실패 {len(errors):,}장 (같은 계획으로 실패분 재시도)"
        )
    elif final_status == "stopped":
        text = (
            f"자료 비교 중지 — {len(completed):,}/"
            f"{plan['count']:,}장 (같은 계획으로 이어짐)"
        )
    elif final_status == "daily_limit":
        text = (
            f"일일 상한 도달 — {len(completed):,}/"
            f"{plan['count']:,}장 (내일 이어짐)"
        )
    else:
        text = (
            f"자료 비교 중단 — {len(completed):,}/"
            f"{plan['count']:,}장"
        )
    phase = {
        "complete": "completed",
        "partial": "partial",
        "stopped": "stopped",
        "daily_limit": "stopped",
        "fatal": "failed",
    }.get(final_status, "failed")
    server.live.update(
        index=len(completed),
        total=plan["count"],
        status_text=text,
        completed=len(completed),
        failed=len(errors),
        phase=phase,
        last_error=(
            next(reversed(errors.values())).get("error", "")
            if errors
            else ""
        ),
        can_retry=final_status != "complete",
    )
    operations.info(text)


def run_comparison(
    operations: ComparisonExecutionOperations,
    server: Any,
    config: dict,
    plan: dict,
    styles: list,
    characters: list,
) -> None:
    """직렬 비교 작업을 manifest 상태 규칙과 최대 3회 재시도로 실행한다."""
    progress, folder = operations.progress_start(
        config, plan, styles, characters
    )
    _bind_manifest_job(operations, server, progress, folder)
    completed = progress["completed"]
    lineage_errors = _reconnect_completed_results(
        operations, server, config, progress
    )
    errors = progress.setdefault("errors", {})
    base_seed = int(progress["base_seed"])
    state = operations.load_state()
    jobs = _comparison_jobs(
        operations,
        config,
        plan,
        styles,
        characters,
        base_seed,
    )
    run_failed: set[Any] = set()
    server.live.update(
        index=len(completed),
        total=plan["count"],
        char_name=plan["mode_label"],
        filename="",
        status_text=(
            f"자료 비교 생성 준비 중 — "
            f"{len(completed):,}/{plan['count']:,}"
        ),
        daily=operations.daily_count(state),
        daily_cap=operations.pace(config)["daily_cap"],
        completed=len(completed),
        eta_base_completed=len(completed),
    )
    final_status = "complete"
    for job in jobs:
        key = job["key"]
        if key in completed:
            continue
        if server.live.stop_req:
            final_status = "stopped"
            break
        if (
            operations.daily_count(state)
            >= operations.pace(config)["daily_cap"]
        ):
            final_status = "daily_limit"
            server.live.update(
                status_text=(
                    "일일 상한 도달 — 내일 같은 계획을 누르면 이어집니다."
                )
            )
            break
        execution = _job_execution(
            operations,
            config,
            plan,
            job,
            base_seed,
            folder,
        )
        done_count = len(completed) + len(run_failed)
        _announce_job(
            operations,
            server,
            plan,
            execution,
            done_count,
        )
        ok, last_error, final_status, fatal = _attempt_job(
            operations,
            server,
            config,
            plan,
            progress,
            folder,
            state,
            completed,
            errors,
            run_failed,
            lineage_errors,
            job,
            execution,
            final_status,
        )
        if not ok:
            _record_failure(
                operations,
                server,
                progress,
                folder,
                completed,
                errors,
                run_failed,
                job,
                execution,
                last_error,
            )
            if (
                fatal
                or final_status in ("stopped", "daily_limit")
            ):
                break
    final_status = _final_status(
        final_status,
        completed,
        errors,
        lineage_errors,
        plan["count"],
    )
    _finish_execution(
        operations,
        server,
        config,
        plan,
        progress,
        folder,
        completed,
        errors,
        final_status,
    )
