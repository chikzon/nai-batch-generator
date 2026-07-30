# -*- coding: utf-8 -*-
"""비교 manifest 시작·재개와 선택 셀 재실행의 런타임 조립 경계."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ComparisonRuntimeOperations:
    """기존 비교 계획·Job·결과 저장 helper를 현재 실행 환경에 연결한다."""

    output_root: Callable[[dict], Path]
    comparison_signature: Callable[..., str]
    load_progress: Callable[[], dict[str, Any]]
    load_json: Callable[[Path], Any]
    path_is_inside: Callable[[Any, Any], bool]
    output_file_for_preview: Callable[[dict, Any], Path | None]
    output_subdir: Callable[[dict, str], Path]
    now: Callable[[], Any]
    random_bytes: Callable[[int], bytes]
    now_text: Callable[[], str]
    random_seed: Callable[[int, int], int]
    comparison_recipe_context: Callable[..., dict[str, Any]]
    save_progress: Callable[[dict[str, Any], Path], Any]
    info: Callable[..., Any]
    warning: Callable[..., Any]
    selected_comparison_record: Callable[..., tuple[Any, ...]]
    regenerate_execution_material: Callable[..., dict[str, Any]]
    selected_config: Callable[[dict, dict], dict]
    load_asset_config: Callable[[dict], dict]
    compute_pending: Callable[..., Any]
    selected_job_values: Callable[..., tuple[Any, ...]]
    generation_blueprint: Callable[..., dict[str, Any]]
    pace_gate: Callable[..., tuple[bool, str]]
    runtime_generation_params: Callable[..., dict[str, Any]]
    call_nai_api: Callable[..., Any]
    with_centers: Callable[[dict, list], dict]
    pace_complete: Callable[[], Any]
    output_format: Callable[[dict], str]
    available_output_path: Callable[[Path, str], Path]
    output_clean_args: Callable[[dict], tuple[Any, Any, Any]]
    save_with_meta: Callable[..., Path]
    record_job_result: Callable[..., Any]
    uuid4: Callable[[], Any]
    comparison_job_recipe_snapshot: Callable[..., dict[str, Any]]
    load_state: Callable[[], dict]
    bump_daily: Callable[[dict], Any]
    save_state: Callable[[dict], Any]
    # 재개용 진행 파일만 갱신한다 (manifest는 손대지 않는다 — save_progress와 다름).
    save_resume_progress: Callable[[dict[str, Any]], Any] | None = None


def activate_comparison_run(
    operations: ComparisonRuntimeOperations,
    config: dict,
    folder: Any,
) -> dict[str, Any]:
    """선택한 미완료 manifest를 현재 재개 대상으로 안전하게 활성화한다."""
    root = operations.output_root(config).resolve()
    runs_root = (root / "비교생성").resolve()
    rel = str(folder or "").strip().replace("\\", "/").strip("/")
    candidate = (root / rel).resolve()
    if (not rel or not operations.path_is_inside(candidate, runs_root)
            or not candidate.is_dir()):
        raise ValueError("선택한 비교 실험 폴더를 찾지 못했습니다.")
    manifest_path = candidate / "manifest.json"
    progress = operations.load_json(manifest_path)
    if not isinstance(progress, dict):
        raise ValueError("비교 실험 기록 형식이 올바르지 않습니다.")
    plan = progress.get("plan") if isinstance(progress.get("plan"), dict) else {}
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    completed = progress.get("completed")
    resumable = bool(
        progress.get("status") != "complete"
        and progress.get("signature")
        and isinstance(completed, dict)
    )
    if resumable:
        operations.save_resume_progress(progress)
    return {
        "ok": True,
        "folder": candidate.relative_to(root).as_posix(),
        "status": str(progress.get("status") or ""),
        "completed": len(completed) if isinstance(completed, dict) else 0,
        "total": int(plan.get("count") or 0),
        "resumable": resumable,
        "options": options,
    }


def comparison_result_context(
    operations: ComparisonRuntimeOperations,
    config: dict,
    rel: Any,
) -> dict[str, Any]:
    """비교 결과 한 장의 파일·manifest·정확한 작업 레코드를 함께 찾는다."""
    image_path = operations.output_file_for_preview(config, rel)
    if image_path is None:
        raise ValueError("선택한 비교 결과 파일을 찾지 못했습니다.")
    root = operations.output_root(config).resolve()
    runs_root = (root / "비교생성").resolve()
    folder = image_path.parent.resolve()
    if not operations.path_is_inside(folder, runs_root):
        raise ValueError("비교 생성 결과만 현재 생성에 적용할 수 있습니다.")
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("이 결과의 비교 manifest를 찾지 못했습니다.")
    manifest = operations.load_json(manifest_path)
    wanted = image_path.relative_to(root).as_posix()
    for section in ("completed", "reruns"):
        rows = manifest.get(section)
        if not isinstance(rows, dict):
            continue
        for key, record in rows.items():
            if (isinstance(record, dict)
                    and str(record.get("file") or "").replace("\\", "/")
                    == wanted):
                effective = manifest
                if section == "reruns":
                    effective = copy.deepcopy(manifest)
                    effective["completed"] = {str(key): copy.deepcopy(record)}
                return {
                    "image_path": image_path,
                    "file": wanted,
                    "folder": folder,
                    "manifest": effective,
                    "record": copy.deepcopy(record),
                    "job_key": str(key),
                    "section": section,
                }
    raise ValueError("manifest에서 선택한 결과의 생성 기록을 찾지 못했습니다.")


def comparison_runs(
    operations: ComparisonRuntimeOperations,
    config: dict,
    limit: Any = 50,
) -> dict[str, Any]:
    """손상된 manifest는 건너뛰고 최근 비교 실행을 수정 시각순으로 반환한다."""
    root = operations.output_root(config).resolve()
    runs_root = (root / "비교생성").resolve()
    if not runs_root.is_dir():
        return {"ok": True, "runs": []}
    found = []
    for folder in runs_root.iterdir():
        if (
            not folder.is_dir()
            or not operations.path_is_inside(folder, runs_root)
        ):
            continue
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            progress = operations.load_json(manifest_path)
        except Exception as error:
            operations.warning(
                "비교 실험 기록을 읽지 못했습니다(%s): %s",
                folder.name,
                error,
            )
            continue
        if not isinstance(progress, dict):
            continue
        plan = (
            progress.get("plan")
            if isinstance(progress.get("plan"), dict)
            else {}
        )
        options = (
            plan.get("options")
            if isinstance(plan.get("options"), dict)
            else {}
        )
        completed = progress.get("completed")
        completed_count = (
            len(completed) if isinstance(completed, dict) else 0
        )
        status = str(progress.get("status") or "")
        try:
            modified = manifest_path.stat().st_mtime
        except OSError:
            modified = 0
        found.append({
            "folder": folder.relative_to(root).as_posix(),
            "name": folder.name,
            "status": status,
            "mode_label": str(
                progress.get("mode_label") or ""
            ),
            "completed": completed_count,
            "total": int(
                plan.get("count") or completed_count
            ),
            "updated_at": str(
                progress.get("updated_at")
                or progress.get("created_at")
                or ""
            ),
            "resumable": bool(
                status != "complete"
                and progress.get("signature")
                and isinstance(completed, dict)
            ),
            "options": options,
            "_mtime": modified,
        })
    found.sort(
        key=lambda item: (item["_mtime"], item["name"]),
        reverse=True,
    )
    for item in found:
        item.pop("_mtime", None)
    count = max(1, min(int(limit or 50), 200))
    return {"ok": True, "runs": found[:count]}


def _valid_completed_result(
    operations: ComparisonRuntimeOperations,
    config: dict,
    record: Any,
) -> bool:
    relative = record.get("file") if isinstance(record, dict) else record
    path = operations.output_file_for_preview(config, relative)
    valid = (
        path is not None
        and path.is_file()
        and path.stat().st_size > 0
    )
    expected_hash = (
        str(record.get("content_sha256") or "")
        if isinstance(record, dict)
        else ""
    )
    if valid and expected_hash:
        try:
            valid = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                == expected_hash
            )
        except OSError:
            valid = False
    return valid


def _resumable_folder(
    operations: ComparisonRuntimeOperations,
    config: dict,
    root: Path,
    old: dict[str, Any],
    signature: str,
) -> Path | None:
    if (
        old.get("signature") != signature
        or not isinstance(old.get("completed"), dict)
    ):
        return None
    candidate = (root / str(old.get("folder") or "")).resolve()
    if (
        not operations.path_is_inside(candidate, root)
        or not candidate.is_dir()
    ):
        return None
    invalid = any(
        not _valid_completed_result(operations, config, record)
        for record in old["completed"].values()
    )
    if old.get("status") == "complete" and not invalid:
        return None
    return candidate


def _new_comparison_progress(
    operations: ComparisonRuntimeOperations,
    config: dict,
    plan: dict,
    styles: list,
    characters: list,
    root: Path,
    signature: str,
) -> tuple[dict[str, Any], Path]:
    run_id = (
        operations.now().strftime("%Y%m%d-%H%M%S")
        + "-"
        + operations.random_bytes(3).hex()
    )
    folder = operations.output_subdir(
        config, "비교생성"
    ) / run_id
    folder.mkdir(parents=True, exist_ok=True)
    progress = {
        "version": 1,
        "signature": signature,
        "status": "running",
        "created_at": operations.now_text(),
        "updated_at": operations.now_text(),
        "folder": folder.relative_to(root).as_posix(),
        "mode": plan["options"]["mode"],
        "mode_label": plan["mode_label"],
        "plan": {
            key: value
            for key, value in plan.items()
            if key not in ("sample_styles", "sample_characters")
        },
        "base_seed": (
            int(plan["options"].get("seed") or 0)
            or operations.random_seed(1, 2**32 - 1)
        ),
        "recipe_context": operations.comparison_recipe_context(
            config, plan, styles, characters
        ),
        "completed": {},
        "errors": {},
    }
    return progress, folder


def _resume_comparison_progress(
    operations: ComparisonRuntimeOperations,
    config: dict,
    plan: dict,
    styles: list,
    characters: list,
    old: dict[str, Any],
    folder: Path,
) -> dict[str, Any]:
    progress = old
    progress["status"] = "running"
    progress["updated_at"] = operations.now_text()
    if not isinstance(progress.get("recipe_context"), dict):
        progress["recipe_context"] = (
            operations.comparison_recipe_context(
                config, plan, styles, characters
            )
        )
    operations.info(
        "중단된 자료 비교 생성을 이어서 합니다: %s", folder
    )
    return progress


def _drop_invalid_completed(
    operations: ComparisonRuntimeOperations,
    config: dict,
    progress: dict[str, Any],
) -> None:
    completed = progress.setdefault("completed", {})
    for key, record in list(completed.items()):
        if not _valid_completed_result(
            operations, config, record
        ):
            completed.pop(key, None)


def comparison_progress_start(
    operations: ComparisonRuntimeOperations,
    config: dict,
    plan: dict,
    styles: list,
    characters: list,
) -> tuple[dict[str, Any], Path]:
    """같은 계획의 유효 결과만 유지해 재개하거나 새 manifest를 시작한다."""
    root = operations.output_root(config).resolve()
    signature = operations.comparison_signature(
        config, plan, styles, characters
    )
    old = operations.load_progress()
    folder = _resumable_folder(
        operations, config, root, old, signature
    )
    if folder is None:
        progress, folder = _new_comparison_progress(
            operations,
            config,
            plan,
            styles,
            characters,
            root,
            signature,
        )
    else:
        progress = _resume_comparison_progress(
            operations,
            config,
            plan,
            styles,
            characters,
            old,
            folder,
        )
    _drop_invalid_completed(operations, config, progress)
    operations.save_progress(progress, folder)
    return progress, folder


def _rerun_job(
    operations: ComparisonRuntimeOperations,
    config: dict,
    progress: dict[str, Any],
    source_key: str,
    source: dict[str, Any],
    cell: dict[str, Any],
    attempt: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    material = operations.regenerate_execution_material(
        cell,
        config,
        attempt=attempt,
        runtime_base_seed=int(
            progress.get("base_seed")
            or source.get("seed")
            or 1
        ),
    )
    scratch = operations.selected_config(config, material)
    material_job = material.get("job") or {}
    job = {
        "index": int(source.get("index") or 1),
        "key": source_key,
        "cell_id": material.get("cell_id"),
        "cell_resume_key": material.get("resume_key"),
        "canonical_cell": cell,
        "material": material,
        "scratch_cfg": scratch,
        "style": material_job.get("style"),
        "character": material_job.get("character"),
        "setting": material_job.get("setting"),
        "style_name": source.get("style") or "현재 그림체",
        "char_name": source.get("character") or "현재 캐릭터",
        "setting_name": source.get("setting") or "",
        "seed_index": int(source.get("seed_index") or 0),
        "seed": int(
            source.get("seed") or material.get("seed") or 1
        ),
        "cid": str(
            source.get("cid") or source.get("cast_id") or ""
        ),
        "scene_num": int(source.get("scene") or 0),
        "copy": int(source.get("copy") or 1),
    }
    _restore_setting_leaf(operations, scratch, job)
    return material, job


def _restore_setting_leaf(
    operations: ComparisonRuntimeOperations,
    scratch: dict,
    job: dict[str, Any],
) -> None:
    if not isinstance(job["setting"], dict) or not job["scene_num"]:
        return
    asset_config = operations.load_asset_config(scratch)
    matches = [
        (derived, str(character_id))
        for derived, character_id, scene_num, copy_num
        in operations.compute_pending(
            scratch, asset_config, {}, set()
        )
        if (
            int(scene_num) == job["scene_num"]
            and int(copy_num) == job["copy"]
            and (
                not job["cid"]
                or str(character_id) == job["cid"]
            )
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            "선택했던 세팅 씬을 현재 자료에서 찾지 못했습니다."
        )
    job["asset_config"] = asset_config
    job["scene_character"] = copy.deepcopy(matches[0][0])
    job["cid"] = matches[0][1]


def _execution_blueprint(
    operations: ComparisonRuntimeOperations,
    config: dict,
    plan: dict,
    job: dict[str, Any],
    source_key: str,
    attempt: int,
) -> tuple[Any, str, str, list, list, dict[str, Any]]:
    used, base, negative, people, centers = (
        operations.selected_job_values(config, plan, job)
    )
    execution_config = copy.deepcopy(used)
    execution_config.update({
        "base_prompt": base,
        "negative_prompt": negative,
        "char_slots": [
            {
                "prompt": str(person.get("prompt") or ""),
                "negative": str(person.get("negative") or ""),
                "enabled": True,
            }
            for person in people
            if isinstance(person, dict)
        ],
        "char_centers": copy.deepcopy(centers),
        "nai_seed": job["seed"],
    })
    blueprint = operations.generation_blueprint(
        execution_config,
        source={
            "kind": "comparison-rerun",
            "cell": source_key,
            "attempt": attempt,
        },
        experiment={"mode": "selected_groups"},
    )
    return used, base, negative, people, centers, blueprint


def _generate_rerun(
    operations: ComparisonRuntimeOperations,
    server: Any,
    config: dict,
    plan: dict,
    job: dict[str, Any],
    used: dict,
    base: str,
    negative: str,
    people: list,
    centers: list,
) -> Any:
    token = config["token"]
    allowed, reason = operations.pace_gate(
        config, server.live, "비교 한 셀 재실행"
    )
    if not allowed:
        raise ValueError(reason)
    params = operations.runtime_generation_params(
        used,
        token,
        include_refs=plan["options"].get(
            "include_refs", False
        ),
    )
    try:
        return operations.call_nai_api(
            token,
            base,
            negative,
            int(used.get("width", 832)),
            int(used.get("height", 1216)),
            chars=people,
            scale=used.get("cfg_scale", 5.5),
            cfg_rescale=used.get("cfg_rescale", 0.56),
            steps=int(used.get("steps", 28)),
            sampler=used.get(
                "sampler", "k_euler_ancestral"
            ),
            scheduler=used.get("scheduler", "karras"),
            variety=used.get("variety", False),
            uc_preset=int(used.get("uc_preset", 4)),
            seed=job["seed"],
            params=operations.with_centers(params, centers),
        )
    finally:
        operations.pace_complete()


def _save_rerun_image(
    operations: ComparisonRuntimeOperations,
    server: Any,
    config: dict,
    folder: Path,
    source: dict[str, Any],
    source_key: str,
    job: dict[str, Any],
    attempt: int,
    image: Any,
    blueprint: dict[str, Any],
) -> tuple[Path, str]:
    source_path = operations.output_file_for_preview(
        config, source["file"]
    )
    stem = (
        source_path.stem
        if source_path is not None
        else f"{job['index']:06d}_selected"
    )
    output_format = operations.output_format(config)
    target = operations.available_output_path(
        folder / f"{stem}_rerun{attempt}.webp",
        output_format,
    )
    image.nai_blueprint_fingerprint = blueprint["fingerprint"]
    clean, max_side, quality = operations.output_clean_args(
        config
    )
    saved = operations.save_with_meta(
        image,
        target,
        fmt=output_format,
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
    operations.record_job_result(
        server.live.job_id,
        saved,
        artifact=relative,
        source_result_ids=[source_key],
    )
    return saved, relative


def _record_rerun(
    operations: ComparisonRuntimeOperations,
    progress: dict[str, Any],
    folder: Path,
    config: dict,
    plan: dict,
    job: dict[str, Any],
    source_key: str,
    source: dict[str, Any],
    attempt: int,
    saved: Path,
    relative_saved: str,
    image: Any,
    blueprint: dict[str, Any],
    recipe_values: tuple[Any, ...],
) -> None:
    used, base, negative, people, centers = recipe_values
    rerun_key = (
        f"{source_key}:rerun:{attempt}:"
        f"{operations.uuid4().hex[:8]}"
    )
    record = copy.deepcopy(source)
    record.update({
        "file": relative_saved,
        "rerun_of": source_key,
        "rerun_attempt": attempt,
        "content_sha256": hashlib.sha256(
            saved.read_bytes()
        ).hexdigest(),
        "request_id": str(
            getattr(image, "nai_request_id", "") or ""
        ),
        "payload_hash": str(
            getattr(image, "nai_payload_hash", "") or ""
        ),
        "blueprint_fingerprint": blueprint["fingerprint"],
        "seed": job["seed"],
        "recipe": operations.comparison_job_recipe_snapshot(
            config,
            plan,
            job,
            used,
            base,
            negative,
            people,
            centers,
            job["seed"],
        ),
    })
    progress.setdefault("reruns", {})[rerun_key] = record
    progress["updated_at"] = operations.now_text()
    operations.save_progress(progress, folder)


def rerun_selected_comparison(
    operations: ComparisonRuntimeOperations,
    server: Any,
    config: dict,
    relative_path: Any,
) -> None:
    """저장된 canonical 셀을 같은 seed로 실행해 새 계보 결과로 추가한다."""
    progress, folder, source_key, source = (
        operations.selected_comparison_record(
            config, relative_path
        )
    )
    cell = source.get("canonical_cell")
    if not isinstance(cell, dict):
        raise ValueError(
            "이 결과에는 한 셀 재실행 정보가 없습니다."
        )
    plan = progress.get("plan")
    if not isinstance(plan, dict):
        raise ValueError(
            "이 결과의 선택 실험 계획을 읽지 못했습니다."
        )
    attempt = max(
        2, int(source.get("rerun_attempt") or 1) + 1
    )
    _, job = _rerun_job(
        operations,
        config,
        progress,
        source_key,
        source,
        cell,
        attempt,
    )
    recipe_values = _execution_blueprint(
        operations,
        config,
        plan,
        job,
        source_key,
        attempt,
    )
    used, base, negative, people, centers, blueprint = (
        recipe_values
    )
    image = _generate_rerun(
        operations,
        server,
        config,
        plan,
        job,
        used,
        base,
        negative,
        people,
        centers,
    )
    saved, relative_saved = _save_rerun_image(
        operations,
        server,
        config,
        folder,
        source,
        source_key,
        job,
        attempt,
        image,
        blueprint,
    )
    _record_rerun(
        operations,
        progress,
        folder,
        config,
        plan,
        job,
        source_key,
        source,
        attempt,
        saved,
        relative_saved,
        image,
        blueprint,
        (used, base, negative, people, centers),
    )
    state = operations.load_state()
    operations.bump_daily(state)
    operations.save_state(state)
    server.live.update(
        index=1,
        total=1,
        completed=1,
        failed=0,
        filename=saved.name,
        seed=job["seed"],
        status_text=(
            f"선택 실험 한 셀 재실행 완료 · {saved.name}"
        ),
        phase="completed",
        can_retry=False,
    )
