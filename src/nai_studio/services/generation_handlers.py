# -*- coding: utf-8 -*-
"""Job 센터 명령과 단독 생성 handler의 서비스 조립 경계."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image


@dataclass(frozen=True)
class GenerationHandlerOperations:
    """기존 Job·blueprint·NAI·결과 저장 helper를 호출 시점에 연결한다."""

    common_job_store: Callable[[], Any]
    make_job_command: Callable[..., dict[str, Any]]
    transition_job: Callable[[dict, str], dict[str, Any]]
    activate_comparison_run: Callable[[dict, Any], dict[str, Any]]
    retry_job: Callable[[dict], dict[str, Any]]
    reconcile_job: Callable[[dict, dict], dict[str, Any]]
    inherited_blueprint: Callable[..., dict[str, Any]]
    single_generation_material: Callable[
        [dict[str, Any]], dict[str, Any]
    ]
    characters_resource_config: Callable[
        [dict, list], dict
    ]
    pace_gate: Callable[..., tuple[bool, str]]
    runtime_generation_params: Callable[..., dict[str, Any]]
    load_state: Callable[[], dict]
    call_nai_api: Callable[..., Any]
    with_centers: Callable[[dict, list], dict]
    pace_complete: Callable[[], Any]
    output_subdir: Callable[[dict, str], Path]
    output_format: Callable[[dict], str]
    output_clean_args: Callable[[dict], tuple[Any, Any, Any]]
    save_with_meta: Callable[..., Path]
    output_root: Callable[[dict], Path]
    record_job_result: Callable[..., Any]
    bump_daily: Callable[[dict], Any]
    save_state: Callable[[dict], Any]
    start_daemon: Callable[[Callable[[], None]], Any]
    error: Callable[..., Any]
    random_seed: Callable[[int, int], int]
    reference_inset_canvas: Callable[[bytes, int, int], dict[str, Any]]
    character_asset_from_record: Callable[..., dict[str, Any]]
    variation_plan_material: Callable[..., dict[str, Any]]
    slot_prompt: Callable[[Any], str]
    active_people: Callable[..., tuple[list, list]]
    now: Callable[[], Any]
    extract_metadata: Callable[[bytes, str], dict[str, Any] | None]
    model_id_from_metadata: Callable[[Any, str], str]
    normalize_position_mode: Callable[[Any, bool], str]
    scene_mode_pending: Callable[[dict], list]
    daily_count: Callable[[dict], int]
    safe_name: Callable[[str], str]
    progress_record_path: Callable[[dict, dict], Path | None]
    join_tags: Callable[..., str]
    seed_for: Callable[[dict, int, int], int]
    available_output_path: Callable[[Path, str], Path]
    warning: Callable[..., Any]


def handle_job_command(
    server: Any,
    data: dict[str, Any],
    operations: GenerationHandlerOperations,
) -> dict[str, Any]:
    """검증된 Job 명령을 현재 Live 실행권 또는 재개 화면에 연결한다."""
    job_id = str(data.get("job_id") or "")
    action = str(data.get("action") or "")
    if not job_id or action not in (
        "pause",
        "cancel",
        "retry",
        "resume",
        "reconcile",
    ):
        raise ValueError("작업과 명령을 올바르게 골라주세요.")
    store = operations.common_job_store()
    job = store.get(job_id)
    command = operations.make_job_command(
        job,
        action,
        observation=data.get("observation"),
    )
    handler = command.get("handler") or {}
    handled = False
    navigation = ""
    message = ""
    if action in ("pause", "cancel"):
        live = server.live.snapshot()
        if (
            not live.get("running")
            or str(live.get("job_id") or "") != job_id
        ):
            raise ValueError(
                "이 기록은 현재 NAI 실행권을 가진 작업이 아닙니다. "
                "무관한 현재 작업은 멈추지 않았습니다."
            )
        handled = server.live.request_stop()
        updated = operations.transition_job(
            job, command["next_phase"]
        )
    elif action in ("retry", "resume"):
        (
            handled,
            navigation,
            message,
            updated,
        ) = _retry_or_resume(
            server,
            operations,
            job,
            action,
            command,
            handler,
        )
    else:
        updated = operations.reconcile_job(
            job, command.get("observation") or {}
        )
        handled = True
        message = (
            "디스크의 실제 결과와 작업 기록을 대조했습니다."
        )
    store.save(updated)
    return {
        "ok": True,
        "handled": handled,
        "command": command,
        "job": updated,
        "navigation": navigation,
        "message": message,
    }


def _retry_or_resume(
    server: Any,
    operations: GenerationHandlerOperations,
    job: dict[str, Any],
    action: str,
    command: dict[str, Any],
    handler: dict[str, Any],
) -> tuple[bool, str, str, dict[str, Any]]:
    if handler.get("target") == "comparison":
        activated = operations.activate_comparison_run(
            server.cfg, handler.get("folder")
        )
        if not activated.get("resumable"):
            raise ValueError(
                "이 비교 기록은 완료됐거나 재개 근거가 없습니다."
            )
        updated = (
            operations.retry_job(job)
            if action == "retry"
            else operations.transition_job(
                job, command["next_phase"]
            )
        )
        return (
            True,
            "compare",
            "중단 지점을 활성화했습니다. 장수와 비용을 확인한 뒤 실행하세요.",
            updated,
        )
    navigation = (
        "settings" if job.get("kind") == "setting" else "preview"
    )
    return (
        False,
        navigation,
        (
            "원래 작업 화면으로 이동합니다. 현재 입력과 비용을 확인해 "
            "실제로 다시 실행할 때까지 작업 상태는 바꾸지 않았습니다."
        ),
        job,
    )


def _single_generation_snapshot(
    config: dict,
    operations: GenerationHandlerOperations,
) -> tuple[dict, dict, dict]:
    blueprint = operations.inherited_blueprint(
        config, source={"kind": "single-generate"}
    )
    material = operations.single_generation_material(blueprint)
    job_config = copy.deepcopy(config)
    job_config.update(material.get("config_overrides") or {})
    job_config = operations.characters_resource_config(
        job_config, blueprint.get("characters") or []
    )
    return blueprint, material, job_config


def _call_single_generation(
    operations: GenerationHandlerOperations,
    config: dict,
    job_config: dict,
    call: dict[str, Any],
) -> tuple[Any, dict]:
    base = str(call.get("base_prompt") or "").strip() or "1girl"
    people = copy.deepcopy(call.get("characters") or [])
    centers = copy.deepcopy(call.get("char_centers") or [])
    params = operations.runtime_generation_params(
        job_config, config["token"]
    )
    state = operations.load_state()
    try:
        image = operations.call_nai_api(
            config["token"],
            base,
            call.get("negative_prompt", ""),
            int(call.get("width") or 832),
            int(call.get("height") or 1216),
            chars=people,
            scale=job_config.get("cfg_scale", 5.5),
            cfg_rescale=job_config.get("cfg_rescale", 0.56),
            steps=int(job_config.get("steps", 28)),
            sampler=job_config.get(
                "sampler", "k_euler_ancestral"
            ),
            scheduler=job_config.get("scheduler", "karras"),
            variety=job_config.get("variety", False),
            uc_preset=int(job_config.get("uc_preset", 3)),
            seed=call.get("seed") or None,
            params=operations.with_centers(params, centers),
        )
    finally:
        operations.pace_complete()
    return image, state


def _save_single_generation(
    server: Any,
    operations: GenerationHandlerOperations,
    job_config: dict,
    blueprint: dict[str, Any],
    image: Any,
) -> str:
    image.nai_blueprint_fingerprint = blueprint["fingerprint"]
    output_dir = operations.output_subdir(job_config, "단독")
    number = len([
        path
        for path in output_dir.iterdir()
        if path.suffix.lower() in (".webp", ".png")
    ]) + 1
    clean, max_side, quality = operations.output_clean_args(
        job_config
    )
    saved = operations.save_with_meta(
        image,
        output_dir / f"{number:04d}.webp",
        fmt=operations.output_format(job_config),
        clean=clean,
        max_side=max_side,
        quality=quality,
    )
    relative = (
        saved.resolve()
        .relative_to(
            operations.output_root(job_config).resolve()
        )
        .as_posix()
    )
    operations.record_job_result(
        server.live.job_id,
        saved,
        artifact=relative,
    )
    server.live.set_image(image)
    return relative


def _run_generate_one(
    server: Any,
    operations: GenerationHandlerOperations,
    token: Any,
    config: dict,
    blueprint: dict[str, Any],
    material: dict[str, Any],
    job_config: dict,
) -> None:
    server.live.update(
        status_text="단독 생성 중...",
        char_name="단독 생성",
        filename="",
        index=1,
        total=1,
    )
    try:
        allowed, reason = operations.pace_gate(
            job_config, server.live, "단독"
        )
        if not allowed:
            server.live.update(
                status_text=reason,
                phase="stopped",
                can_retry=True,
            )
            return
        image, state = _call_single_generation(
            operations,
            config,
            job_config,
            material["call"],
        )
        relative = _save_single_generation(
            server,
            operations,
            job_config,
            blueprint,
            image,
        )
        operations.bump_daily(state)
        operations.save_state(state)
        server.live.update(
            status_text=f"단독 생성 완료 ✓ ({relative})",
            completed=1,
            phase="completed",
        )
    except Exception as error:
        operations.error("단독 생성 실패: %s", error)
        server.live.update(
            status_text=f"단독 생성 실패: {error}",
            failed=1,
            last_error=str(error),
            can_retry=True,
            phase="failed",
        )
    finally:
        server.live.release(token)


def handle_generate_one(
    server: Any,
    data: Any,
    operations: GenerationHandlerOperations,
) -> dict[str, Any]:
    """클릭 순간의 설계도를 고정하고 단독 생성 worker를 비동기로 시작한다."""
    del data
    if server.live.running:
        return {"ok": False, "error": "이미 생성 중입니다."}
    with server.config_lock:
        config = copy.deepcopy(server.cfg)
    if not config.get("token", "").startswith("pst-"):
        return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
    blueprint, material, job_config = (
        _single_generation_snapshot(config, operations)
    )
    token = server.live.try_claim(
        "단독 생성",
        "preview",
        blueprint=blueprint,
        payload_identity={
            "kind": "single",
            "output": "one-image",
        },
    )
    if token is None:
        return {"ok": False, "error": "이미 생성 중입니다."}
    operations.start_daemon(
        lambda: _run_generate_one(
            server,
            operations,
            token,
            config,
            blueprint,
            material,
            job_config,
        )
    )
    return {"ok": True}


def _i2i_dimensions(
    data: dict[str, Any],
    config: dict,
    variation_mode: str,
    image_bytes: bytes,
    image_b64: str,
    mask_b64: str | None,
) -> tuple[int, int, bytes, str, str | None] | dict[str, Any]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
        if mask_b64:
            mask_bytes = base64.b64decode(mask_b64)
            with Image.open(io.BytesIO(mask_bytes)) as mask:
                if mask.size != (width, height):
                    return {
                        "ok": False,
                        "error": "원본과 마스크 크기가 다릅니다.",
                    }
    except Exception as error:
        return {
            "ok": False,
            "error": f"그림을 못 읽었습니다: {error}",
        }
    if variation_mode not in (
        "character-reference",
        "reference-inset",
    ):
        return width, height, image_bytes, image_b64, mask_b64
    try:
        trial_width = int(
            data.get("trial_width")
            or config.get("width")
            or width
        )
        trial_height = int(
            data.get("trial_height")
            or config.get("height")
            or height
        )
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "시험 해상도가 올바르지 않습니다.",
        }
    trial_width = max(
        64, min(2048, trial_width // 64 * 64)
    )
    trial_height = max(
        64, min(2048, trial_height // 64 * 64)
    )
    if variation_mode == "character-reference":
        return (
            trial_width,
            trial_height,
            image_bytes,
            image_b64,
            None,
        )
    return trial_width, trial_height, image_bytes, image_b64, mask_b64


def _reference_inset(
    operations: GenerationHandlerOperations,
    variation_mode: str,
    dimensions: tuple[int, int, bytes, str, str | None],
) -> tuple[int, int, bytes, str, str | None] | dict[str, Any]:
    width, height, image_bytes, image_b64, mask_b64 = dimensions
    if variation_mode != "reference-inset":
        return dimensions
    try:
        inset = operations.reference_inset_canvas(
            image_bytes, width, height
        )
    except Exception as error:
        return {"ok": False, "error": str(error)}
    return (
        inset["width"],
        inset["height"],
        inset["image"],
        base64.b64encode(inset["image"]).decode("ascii"),
        base64.b64encode(inset["mask"]).decode("ascii"),
    )


def _variation_material(
    operations: GenerationHandlerOperations,
    config: dict,
    data: dict[str, Any],
    variation_mode: str,
    variation_id: str,
    image_bytes: bytes,
    original_source: bytes,
    mask_b64: str | None,
    source_hash: str,
    seed: int,
    width: int,
    height: int,
) -> tuple[dict, str, dict, bytes | None] | dict[str, Any]:
    record = next(
        (
            item
            for item in config.get("characters", [])
            if str(item.get("id") or "") == variation_id
        ),
        None,
    )
    if record is None:
        return {
            "ok": False,
            "error": "변형할 캐릭터 자산을 찾지 못했습니다.",
        }
    try:
        asset = operations.character_asset_from_record(
            record,
            char_refs=config.get("char_refs") or [],
            vibes=config.get("vibes") or [],
        )
        planned_mode = (
            variation_mode
            if variation_mode != "reference-inset"
            else "inpaint"
        )
        prompt_overrides = {
            target: str(data.get(source_key) or "")
            for target, source_key in (
                ("appearance", "trial_appearance"),
                ("outfit", "trial_outfit"),
                ("negative", "trial_negative"),
            )
            if source_key in data
        }
        temporary_settings = {
            "strength": (
                1.0
                if variation_mode == "reference-inset"
                else float(data.get("strength", 0.7))
            ),
            "noise": (
                0.0
                if variation_mode == "reference-inset"
                else float(data.get("noise", 0.0))
            ),
            "reference_strength": float(
                data.get("reference_strength", 1.0)
            ),
            "reference_fidelity": float(
                data.get("reference_fidelity", 0.6)
            ),
        }
        plan = operations.variation_plan_material(
            asset,
            {
                "mode": planned_mode,
                "source_image": {
                    "content_hash": hashlib.sha256(
                        image_bytes
                    ).hexdigest()
                },
                "reference": (
                    {"content_hash": source_hash}
                    if variation_mode == "character-reference"
                    else None
                ),
                "mask": (
                    {
                        "content_hash": hashlib.sha256(
                            base64.b64decode(mask_b64)
                        ).hexdigest()
                    }
                    if mask_b64
                    else None
                ),
                "inset": (
                    {"content_hash": source_hash}
                    if variation_mode == "reference-inset"
                    else None
                ),
                "prompt_overrides": prompt_overrides,
                "seed": seed,
                "resolution": {
                    "width": width,
                    "height": height,
                },
                "temporary_settings": temporary_settings,
            },
        )
    except Exception as error:
        return {
            "ok": False,
            "error": (
                f"캐릭터 변형 계획을 만들지 못했습니다: {error}"
            ),
        }
    job_config = copy.deepcopy(config)
    job_config["char_slots"] = plan["char_slots"]
    transient = None
    if variation_mode == "character-reference":
        job_config["char_refs"] = [
            copy.deepcopy(plan["char_refs"][0])
        ]
        job_config["vibes"] = []
        transient = original_source
    else:
        job_config["char_refs"] = plan["char_refs"]
        job_config["vibes"] = plan["vibes"]
    if "trial_scene_prompt" in data:
        job_config["base_prompt"] = str(
            data.get("trial_scene_prompt") or ""
        )
    if "trial_base_negative" in data:
        job_config["negative_prompt"] = str(
            data.get("trial_base_negative") or ""
        )
    job_config["width"], job_config["height"] = width, height
    return (
        job_config,
        str(record.get("name") or variation_id),
        plan,
        transient,
    )


def _i2i_call(
    operations: GenerationHandlerOperations,
    job_config: dict,
    data: dict[str, Any],
    variation_mode: str,
    image_b64: str,
    mask_b64: str | None,
    seed: int,
    width: int,
    height: int,
) -> Any:
    slots = [
        slot
        for slot in job_config.get("char_slots", [])
        if (
            operations.slot_prompt(slot).strip()
            and slot.get("enabled") is not False
        )
    ]
    params = operations.runtime_generation_params(
        job_config, job_config["token"]
    )
    if variation_mode != "character-reference":
        params["_i2i"] = {
            "image": image_b64,
            "mask": mask_b64,
            "strength": (
                1.0
                if variation_mode == "reference-inset"
                else float(data.get("strength", 0.7))
            ),
            "noise": (
                0.0
                if variation_mode == "reference-inset"
                else float(data.get("noise", 0.0))
            ),
            "seed": seed,
        }
    people, centers = operations.active_people(
        slots, job_config.get("char_centers")
    )
    try:
        return operations.call_nai_api(
            job_config["token"],
            job_config.get("base_prompt", "") or "1girl",
            job_config.get("negative_prompt", ""),
            width,
            height,
            chars=people,
            scale=job_config.get("cfg_scale", 5.5),
            cfg_rescale=job_config.get("cfg_rescale", 0.56),
            steps=int(job_config.get("steps", 28)),
            sampler=job_config.get(
                "sampler", "k_euler_ancestral"
            ),
            scheduler=job_config.get("scheduler", "karras"),
            variety=job_config.get("variety", False),
            uc_preset=int(job_config.get("uc_preset", 3)),
            seed=seed,
            params=operations.with_centers(params, centers),
        )
    finally:
        operations.pace_complete()


def _save_i2i_result(
    server: Any,
    operations: GenerationHandlerOperations,
    job_config: dict,
    mode: str,
    variation_id: str,
    image: Any,
) -> tuple[Path, Path]:
    output_dir = operations.output_subdir(
        job_config,
        "캐릭터 변형" if variation_id else mode,
    )
    number = len([
        path
        for path in output_dir.iterdir()
        if path.suffix.lower() in (".webp", ".png")
    ]) + 1
    frozen = server.live.frozen_blueprint()
    image.nai_blueprint_fingerprint = str(
        (frozen or {}).get("fingerprint") or ""
    )
    clean, max_side, quality = operations.output_clean_args(
        job_config
    )
    saved = operations.save_with_meta(
        image,
        output_dir / f"{number:04d}.webp",
        fmt=operations.output_format(job_config),
        clean=clean,
        max_side=max_side,
        quality=quality,
    )
    operations.record_job_result(
        server.live.job_id,
        saved,
        artifact=(
            saved.resolve()
            .relative_to(
                operations.output_root(job_config).resolve()
            )
            .as_posix()
        ),
    )
    return output_dir, saved


def _finish_pending_variation(
    server: Any,
    operations: GenerationHandlerOperations,
    variation_id: str,
    saved: Path,
    seed: int,
    width: int,
    height: int,
) -> None:
    if not variation_id:
        return
    with server.config_lock:
        pending = server.pending_variation
        if (
            isinstance(pending, dict)
            and pending.get("character_id") == variation_id
            and pending.get("job_id") == server.live.job_id
        ):
            pending.update({
                "result_path": str(saved.resolve()),
                "result_hash": hashlib.sha256(
                    saved.read_bytes()
                ).hexdigest(),
                "seed": seed,
                "width": width,
                "height": height,
                "completed_at": operations.now().isoformat(
                    timespec="seconds"
                ),
            })


def _run_i2i(
    server: Any,
    operations: GenerationHandlerOperations,
    token: Any,
    context: dict[str, Any],
) -> None:
    mode = context["mode"]
    variation_name = context["variation_name"]
    label = (
        f"{variation_name} 변형" if variation_name else mode
    )
    server.live.update(
        status_text=f"{label} 생성 중...",
        char_name=label,
        index=1,
        total=1,
    )
    try:
        allowed, reason = operations.pace_gate(
            context["job_config"], server.live, mode
        )
        if not allowed:
            server.live.update(
                status_text=reason,
                phase="stopped",
                can_retry=True,
            )
            return
        image = _i2i_call(
            operations,
            context["job_config"],
            context["data"],
            context["variation_mode"],
            context["image_b64"],
            context["mask_b64"],
            context["seed"],
            context["width"],
            context["height"],
        )
        output_dir, saved = _save_i2i_result(
            server,
            operations,
            context["job_config"],
            mode,
            context["variation_id"],
            image,
        )
        _finish_pending_variation(
            server,
            operations,
            context["variation_id"],
            saved,
            context["seed"],
            context["width"],
            context["height"],
        )
        server.live.set_image(image)
        state = operations.load_state()
        operations.bump_daily(state)
        operations.save_state(state)
        server.live.update(
            status_text=(
                f"{label} 완료 ✓ "
                f"(output/{output_dir.name}/{saved.name} · "
                f"시드 {context['seed']})"
            ),
            seed=context["seed"],
            completed=1,
            phase="completed",
        )
    except Exception as error:
        operations.error("%s 실패: %s", mode, error)
        server.live.update(
            status_text=f"{mode} 실패: {error}",
            failed=1,
            last_error=str(error),
            can_retry=True,
            phase="failed",
        )
    finally:
        server.live.release(token)


def _expansion(data: dict[str, Any]) -> dict[str, int] | dict[str, Any]:
    expansion = {}
    for key in ("left", "right", "top", "bottom"):
        try:
            value = int((data.get("expansion") or {}).get(key, 0))
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": f"Outpaint {key} 확장값이 올바르지 않습니다.",
            }
        if value < 0 or value > 1536 or value % 64:
            return {
                "ok": False,
                "error": (
                    "Outpaint 확장값은 0~1536의 "
                    "64px 단위여야 합니다."
                ),
            }
        expansion[key] = value
    return expansion


def _i2i_request(
    data: dict[str, Any],
) -> tuple[str, str, str, str | None, str, dict[str, int]] | dict[str, Any]:
    """화면 입력을 편집 종류·이미지·확장 계약으로만 정규화한다."""
    variation_mode = str(
        data.get("variation_mode") or "img2img"
    ).strip().lower()
    if variation_mode not in (
        "img2img",
        "inpaint",
        "character-reference",
        "reference-inset",
    ):
        return {"ok": False, "error": "알 수 없는 캐릭터 시험 방식입니다."}
    operation = str(data.get("operation") or "edit").strip().lower()
    if operation not in ("edit", "outpaint"):
        return {"ok": False, "error": "알 수 없는 이미지 편집 작업입니다."}
    image_b64 = (data.get("image") or "").split(",", 1)[-1]
    if not image_b64:
        return {"ok": False, "error": "원본 그림이 없습니다."}
    mask_b64 = (data.get("mask") or "").split(",", 1)[-1] or None
    if operation == "outpaint" and not mask_b64:
        return {"ok": False, "error": "Outpaint 확장 영역 마스크가 없습니다."}
    mode = (
        "Outpaint" if operation == "outpaint"
        else "Character Reference" if variation_mode == "character-reference"
        else "Reference inset" if variation_mode == "reference-inset"
        else "인페인트" if mask_b64 else "img2img"
    )
    expansion = _expansion(data)
    if expansion.get("ok") is False:
        return expansion
    if operation == "outpaint" and not any(expansion.values()):
        return {"ok": False, "error": "Outpaint 확장 방향과 크기가 없습니다."}
    return variation_mode, operation, image_b64, mask_b64, mode, expansion


def _i2i_source(
    data: dict[str, Any],
    config: dict[str, Any],
    operations: GenerationHandlerOperations,
    variation_mode: str,
    image_b64: str,
    mask_b64: str | None,
) -> tuple[int, int, bytes, str, str | None, bytes, str, dict] | dict:
    """원본과 NAI 입력 캔버스를 읽고 크기·원본 지문을 함께 고정한다."""
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as error:
        return {"ok": False, "error": f"그림을 못 읽었습니다: {error}"}
    original_source = image_bytes
    dimensions = _i2i_dimensions(
        data, config, variation_mode, image_bytes, image_b64, mask_b64
    )
    if isinstance(dimensions, dict):
        return dimensions
    dimensions = _reference_inset(operations, variation_mode, dimensions)
    if isinstance(dimensions, dict):
        return dimensions
    width, height, image_bytes, image_b64, mask_b64 = dimensions
    width, height = max(64, width // 64 * 64), max(64, height // 64 * 64)
    if width > 2048 or height > 2048:
        return {
            "ok": False,
            "error": "최종 크기는 가로·세로 2048px를 넘을 수 없습니다.",
        }
    original_b64 = (data.get("original") or "").split(",", 1)[-1] or None
    try:
        source_raw = (
            base64.b64decode(original_b64) if original_b64 else original_source
        )
        with Image.open(io.BytesIO(source_raw)) as source:
            source_size = {"width": source.width, "height": source.height}
    except Exception as error:
        return {"ok": False, "error": f"Outpaint 원본을 못 읽었습니다: {error}"}
    return (
        width,
        height,
        image_bytes,
        image_b64,
        mask_b64,
        original_source,
        hashlib.sha256(source_raw).hexdigest(),
        source_size,
    )


def _i2i_variation(
    operations: GenerationHandlerOperations,
    config: dict[str, Any],
    data: dict[str, Any],
    variation_mode: str,
    image_bytes: bytes,
    original_source: bytes,
    mask_b64: str | None,
    source_hash: str,
    seed: int,
    width: int,
    height: int,
) -> tuple[dict, str, dict | None, bytes | None, dict | None] | dict:
    """선택된 캐릭터 시험만 별도 계획으로 투영하고 일반 편집은 원 설정을 쓴다."""
    variation_id = str(data.get("variation_character_id") or "").strip()
    if not variation_id:
        return config, "", None, None, None
    planned = _variation_material(
        operations,
        config,
        data,
        variation_mode,
        variation_id,
        image_bytes,
        original_source,
        mask_b64,
        source_hash,
        seed,
        width,
        height,
    )
    if isinstance(planned, dict):
        return planned
    job_config, variation_name, plan, transient_reference = planned
    return (
        job_config,
        variation_name,
        plan,
        transient_reference,
        copy.deepcopy(plan["variation_plan"]),
    )


def _store_pending_variation(
    server: Any,
    operations: GenerationHandlerOperations,
    variation_id: str,
    variation_name: str,
    variation_mode: str,
    variation_plan: dict | None,
) -> None:
    """임시 변형 저장 버튼이 같은 실행 결과만 가리키도록 시작 계획을 보관한다."""
    with server.config_lock:
        server.pending_variation = (
            {
                "character_id": variation_id,
                "character_name": variation_name,
                "asset_fingerprint": (
                    variation_plan.get("character_asset_fingerprint")
                    if variation_plan else ""
                ),
                "plan": copy.deepcopy(variation_plan),
                "mode": variation_mode,
                "started_at": operations.now().isoformat(timespec="seconds"),
                "result_path": "",
                "job_id": server.live.job_id,
            }
            if variation_id else None
        )


def _i2i_started(
    operation: str,
    mode: str,
    variation_mode: str,
    variation_id: str,
    variation_name: str,
    plan: dict | None,
    width: int,
    height: int,
    mask_b64: str | None,
    source_hash: str,
    expansion: dict[str, int],
) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": mode,
        "width": width,
        "height": height,
        "source_hash": source_hash,
        "expansion": expansion if operation == "outpaint" else None,
        "variation_character": variation_name,
        "variation_mode": variation_mode if variation_id else "",
        "temporary": bool(variation_id),
        "vibe_suppressed": bool(
            variation_id
            and variation_mode == "character-reference"
            and plan.get("vibes")
        ),
    }


def handle_i2i(
    server: Any,
    data: dict[str, Any],
    operations: GenerationHandlerOperations,
) -> dict[str, Any]:
    """img2img·Inpaint·Outpaint와 임시 캐릭터 변형 worker를 시작한다."""
    if server.live.running:
        return {"ok": False, "error": "이미 생성 중입니다."}
    with server.config_lock:
        config = copy.deepcopy(server.cfg)
    if not config.get("token", "").startswith("pst-"):
        return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
    request = _i2i_request(data)
    if isinstance(request, dict):
        return request
    variation_mode, operation, image_b64, mask_b64, mode, expansion = request
    source = _i2i_source(
        data, config, operations, variation_mode, image_b64, mask_b64
    )
    if isinstance(source, dict):
        return source
    (
        width,
        height,
        image_bytes,
        image_b64,
        mask_b64,
        original_source,
        source_hash,
        source_size,
    ) = source
    seed = int(data.get("seed") or 0) or operations.random_seed(
        0, 2**32 - 1
    )
    variation_id = str(data.get("variation_character_id") or "").strip()
    variation = _i2i_variation(
        operations, config, data, variation_mode, image_bytes,
        original_source, mask_b64, source_hash, seed, width, height,
    )
    if isinstance(variation, dict):
        return variation
    job_config, variation_name, plan, transient_reference, variation_plan = (
        variation
    )
    blueprint = operations.inherited_blueprint(
        job_config,
        source={
            "kind": (
                "character-variation"
                if variation_id
                else "outpaint"
                if operation == "outpaint"
                else "image-edit"
            ),
            "mode": mode,
            "character_id": variation_id,
            "content_hash": source_hash,
            "source_size": source_size,
            "expansion": (
                expansion if operation == "outpaint" else None
            ),
        },
    )
    token = server.live.try_claim(
        mode,
        "preview",
        blueprint=blueprint,
        payload_identity={
            "kind": (
                operation
                if operation == "outpaint"
                else "inpaint"
                if mask_b64
                else "img2img"
            ),
            "width": width,
            "height": height,
            "has_mask": bool(mask_b64),
            "source_hash": source_hash,
            "expansion": (
                expansion if operation == "outpaint" else None
            ),
            "character_id": variation_id,
        },
    )
    if token is None:
        return {"ok": False, "error": "이미 생성 중입니다."}
    if transient_reference is not None:
        job_config["char_refs"][0][
            "_image_bytes"
        ] = transient_reference
        job_config["char_refs"][0]["_required"] = True
    _store_pending_variation(
        server, operations, variation_id, variation_name,
        variation_mode, variation_plan,
    )
    context = {
        "data": data,
        "mode": mode,
        "variation_mode": variation_mode,
        "variation_id": variation_id,
        "variation_name": variation_name,
        "job_config": job_config,
        "image_b64": image_b64,
        "mask_b64": mask_b64,
        "seed": seed,
        "width": width,
        "height": height,
    }
    operations.start_daemon(
        lambda: _run_i2i(
            server, operations, token, context
        )
    )
    return _i2i_started(
        operation, mode, variation_mode, variation_id, variation_name,
        plan, width, height, mask_b64, source_hash, expansion,
    )


def _path_is_inside(path: Path, root: Path) -> bool:
    """Keep metadata recovery inside the configured output root."""
    try:
        return path.is_relative_to(root)
    except AttributeError:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def _collect_regen_jobs(
    data: dict[str, Any],
    config: dict,
    operations: GenerationHandlerOperations,
) -> list[tuple[Path, dict, Any]]:
    """Resolve selected output files and retain only recoverable NAI metadata."""
    root = operations.output_root(config).resolve()
    jobs = []
    for relative in data.get("paths") or []:
        path = (root / relative).resolve()
        if not (_path_is_inside(path, root) and path.is_file()):
            continue
        content_type = (
            "image/png"
            if path.suffix.lower() == ".png"
            else "image/webp"
        )
        metadata = operations.extract_metadata(
            path.read_bytes(), content_type
        )
        raw = (metadata or {}).get("raw") or {}
        if not raw:
            continue
        model = ((metadata or {}).get("params") or {}).get("model")
        jobs.append((path, raw, model))
    return jobs


def _regen_prompts(raw: dict) -> tuple[str, str, list, list]:
    """Restore base, negative, characters, and coordinates from NAI metadata."""
    v4_prompt = raw.get("v4_prompt") or {}
    caption = v4_prompt.get("caption") or {}
    base = caption.get("base_caption") or raw.get("prompt") or ""
    negative_caption = (
        (raw.get("v4_negative_prompt") or {}).get("caption") or {}
    )
    negative = (
        negative_caption.get("base_caption") or raw.get("uc") or ""
    )
    characters = [
        {"prompt": item.get("char_caption", ""), "negative": ""}
        for item in caption.get("char_captions") or []
    ]
    for index, item in enumerate(
        negative_caption.get("char_captions") or []
    ):
        if index < len(characters):
            characters[index]["negative"] = item.get(
                "char_caption", ""
            )
    centers = [
        (item.get("centers") or [{}])[0]
        for item in caption.get("char_captions") or []
    ]
    return base, negative, characters, centers


def _regen_parameters(
    path: Path,
    raw: dict,
    model: Any,
    mode: str,
    strength: float,
    config: dict,
    operations: GenerationHandlerOperations,
) -> tuple[dict, int, int]:
    """Build request-only restored settings without mutating user config."""
    v4_prompt = raw.get("v4_prompt") or {}
    params = operations.runtime_generation_params(
        config, config["token"], include_refs=False
    )
    params.update({
        "model": operations.model_id_from_metadata(
            model,
            config.get("model") or "nai-diffusion-4-5-full",
        ),
        "use_coords": bool(v4_prompt.get("use_coords")),
        "position_mode": operations.normalize_position_mode(
            "", bool(v4_prompt.get("use_coords"))
        ),
        "char_centers": [
            {
                "x": float(center.get("x", 0.5)),
                "y": float(center.get("y", 0.5)),
            }
            for center in (
                (item.get("centers") or [{}])[0]
                for item in (
                    (v4_prompt.get("caption") or {}).get(
                        "char_captions"
                    )
                    or []
                )
            )
        ],
        "smea": bool(raw.get("sm")),
        "smea_dyn": bool(raw.get("sm_dyn")),
        "prefer_brownian": bool(
            raw.get("prefer_brownian", True)
        ),
        "variety": raw.get("skip_cfg_above_sigma") is not None,
    })
    width = int(raw.get("width") or config.get("width", 832))
    height = int(raw.get("height") or config.get("height", 1216))
    if mode == "img2img":
        with Image.open(path) as image:
            width = max(64, image.width // 64 * 64)
            height = max(64, image.height // 64 * 64)
            buffer = io.BytesIO()
            image.convert("RGB").resize((width, height)).save(
                buffer, "PNG"
            )
        params["_i2i"] = {
            "image": base64.b64encode(buffer.getvalue()).decode(),
            "mask": None,
            "strength": strength,
            "noise": 0.0,
        }
    return params, width, height


def _call_regen(
    operations: GenerationHandlerOperations,
    config: dict,
    path: Path,
    raw: dict,
    model: Any,
    mode: str,
    strength: float,
    seed: int,
) -> Any:
    base, negative, characters, _ = _regen_prompts(raw)
    params, width, height = _regen_parameters(
        path,
        raw,
        model,
        mode,
        strength,
        config,
        operations,
    )
    try:
        return operations.call_nai_api(
            config["token"],
            base,
            negative,
            width,
            height,
            scale=float(
                raw.get("scale") or config.get("cfg_scale", 5.5)
            ),
            cfg_rescale=float(raw.get("cfg_rescale") or 0.0),
            steps=int(raw.get("steps") or 28),
            sampler=raw.get("sampler") or "k_euler_ancestral",
            scheduler=raw.get("noise_schedule") or "karras",
            uc_preset=int(
                raw.get("ucPreset", config.get("uc_preset", 3))
            ),
            seed=seed,
            params=params,
            chars=characters,
        )
    finally:
        operations.pace_complete()


def _save_regen(
    server: Any,
    operations: GenerationHandlerOperations,
    config: dict,
    output_dir: Path,
    path: Path,
    mode: str,
    image: Any,
) -> Path:
    frozen = server.live.frozen_blueprint()
    image.nai_blueprint_fingerprint = str(
        (frozen or {}).get("fingerprint") or ""
    )
    suffix = "_i2i" if mode == "img2img" else ""
    clean, max_side, quality = operations.output_clean_args(config)
    saved = operations.save_with_meta(
        image,
        output_dir / f"{path.stem}{suffix}.webp",
        fmt=operations.output_format(config),
        clean=clean,
        max_side=max_side,
        quality=quality,
    )
    relative = (
        saved.resolve()
        .relative_to(operations.output_root(config).resolve())
        .as_posix()
    )
    operations.record_job_result(
        server.live.job_id, saved, artifact=relative
    )
    return saved


def _regen_final_status(
    server: Any,
    done: int,
    failed: int,
    total: int,
    blocked: bool,
) -> None:
    if server.live.stop_req:
        phase = "stopped"
        text = f"그림값 복구 중지 — {done}/{total}장 (다시 실행 가능)"
    elif blocked:
        phase = "stopped"
        text = server.live.status_text
    elif failed:
        phase = "partial"
        text = f"그림값 복구 일부 완료 — 성공 {done} · 실패 {failed}"
    else:
        phase = "completed"
        text = f"그림값 복구 완료 — {done}/{total}장 (output/복구/)"
    server.live.update(
        status_text=text,
        completed=done,
        failed=failed,
        phase=phase,
        can_retry=bool(failed or blocked or server.live.stop_req),
    )


def _run_regen(
    server: Any,
    operations: GenerationHandlerOperations,
    token: Any,
    config: dict,
    jobs: list[tuple[Path, dict, Any]],
    mode: str,
    strength: float,
) -> None:
    output_dir = operations.output_subdir(config, "복구")
    state = operations.load_state()
    done = failed = 0
    blocked = False
    server.live.update(
        total=len(jobs), index=0, char_name="그림값 복구"
    )
    try:
        for index, (path, raw, model) in enumerate(jobs, 1):
            if server.live.stop_req:
                break
            server.live.update(
                index=index,
                filename=path.name,
                status_text="복구 중...",
            )
            seed = int(raw.get("seed") or 0) or operations.random_seed(
                0, 2**32 - 1
            )
            allowed, reason = operations.pace_gate(
                config, server.live, "복구"
            )
            if not allowed:
                server.live.update(status_text=reason)
                blocked = True
                break
            try:
                image = _call_regen(
                    operations,
                    config,
                    path,
                    raw,
                    model,
                    mode,
                    strength,
                    seed,
                )
            except Exception as error:
                operations.error("복구 실패 %s: %s", path.name, error)
                failed += 1
                server.live.update(
                    status_text=f"{path.name} 실패: {error}",
                    failed=failed,
                    last_error=str(error),
                )
                continue
            saved = _save_regen(
                server,
                operations,
                config,
                output_dir,
                path,
                mode,
                image,
            )
            server.live.set_image(image)
            operations.bump_daily(state)
            operations.save_state(state)
            done += 1
            server.live.update(
                completed=done,
                index=index,
                filename=saved.name,
                daily=operations.daily_count(state),
            )
        _regen_final_status(
            server, done, failed, len(jobs), blocked
        )
    finally:
        server.live.release(token)


def handle_regen(
    server: Any,
    data: dict[str, Any],
    operations: GenerationHandlerOperations,
) -> dict[str, Any]:
    """Recover metadata-backed outputs through a service-owned worker."""
    if server.live.running:
        return {"ok": False, "error": "이미 생성 중입니다."}
    config = server.cfg
    if not config.get("token", "").startswith("pst-"):
        return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
    mode = data.get("mode") or "generate"
    strength = float(data.get("strength", 0.5))
    jobs = _collect_regen_jobs(data, config, operations)
    if not jobs:
        return {
            "ok": False,
            "error": (
                "메타데이터가 있는 그림이 없습니다. "
                "(카톡·디스코드를 거친 그림은 정보가 지워집니다)"
            ),
        }
    blueprint = operations.inherited_blueprint(
        config,
        source={"kind": "metadata-recovery", "items": len(jobs)},
    )
    token = server.live.try_claim(
        "그림값 복구",
        "library",
        blueprint=blueprint,
        payload_identity={
            "kind": "recovery",
            "items": len(jobs),
            "mode": mode,
        },
    )
    if token is None:
        return {"ok": False, "error": "이미 생성 중입니다."}
    operations.start_daemon(
        lambda: _run_regen(
            server,
            operations,
            token,
            config,
            jobs,
            mode,
            strength,
        )
    )
    return {"ok": True, "count": len(jobs), "mode": mode}


def _scene_fingerprints(
    blueprint: dict[str, Any], base_seed: int
) -> str:
    return hashlib.sha256(
        f"{blueprint['fingerprint']}\0{base_seed}".encode("utf-8")
    ).hexdigest()


def _scene_cell_identity(
    operations: GenerationHandlerOperations,
    run_fingerprint: str,
    scene: dict,
    copy_number: int,
    index: int,
) -> tuple[str, str, str]:
    scene_id = operations.safe_name(
        str(scene.get("id") or f"scene-{index}")
    )
    fingerprint = hashlib.sha256(
        (
            f"{run_fingerprint}\0{scene_id}\0{copy_number}"
        ).encode("utf-8")
    ).hexdigest()
    return scene_id, f"{scene_id}:{int(copy_number)}", fingerprint


def _valid_scene_record(
    operations: GenerationHandlerOperations,
    record: Any,
    config: dict,
    fingerprint: str,
) -> tuple[dict, Path] | None:
    if not isinstance(record, dict):
        return None
    path = operations.progress_record_path(record, config)
    try:
        valid = (
            record.get("fingerprint") == fingerprint
            and path is not None
            and path.is_file()
            and path.stat().st_size == int(record.get("bytes", -1))
            and hashlib.sha256(path.read_bytes()).hexdigest()
            == str(record.get("content_sha256") or "")
        )
    except (OSError, TypeError, ValueError):
        valid = False
    return (record, path) if valid else None


def _resume_scene_cells(
    server: Any,
    operations: GenerationHandlerOperations,
    config: dict,
    jobs: list,
    run_fingerprint: str,
    progress: dict,
) -> tuple[dict[str, dict], int]:
    valid_cells = {}
    lineage_failures = 0
    for index, (scene, copy_number) in enumerate(jobs, 1):
        _, cell_id, fingerprint = _scene_cell_identity(
            operations,
            run_fingerprint,
            scene,
            copy_number,
            index,
        )
        valid = _valid_scene_record(
            operations,
            progress.get(cell_id),
            config,
            fingerprint,
        )
        if valid is None:
            continue
        record, path = valid
        valid_cells[cell_id] = record
        try:
            operations.record_job_result(
                server.live.job_id,
                path,
                artifact=str(record.get("path") or ""),
                result_id="result-scene-" + fingerprint[:24],
            )
        except Exception as error:
            operations.warning(
                "검증된 씬 결과의 Job 계보 연결 실패: %s", error
            )
            lineage_failures += 1
    return valid_cells, lineage_failures


def _scene_seed_state(
    operations: GenerationHandlerOperations,
    config: dict,
    state: dict,
) -> int:
    seed_key = f"{int(config.get('seed', 1)):02d}"
    seeds = state.setdefault("seeds", {})
    if seed_key not in seeds:
        seeds[seed_key] = operations.random_seed(0, 2**32 - 1)
        operations.save_state(state)
    return seeds[seed_key]


def _scene_request(
    operations: GenerationHandlerOperations,
    config: dict,
    params: dict,
    slots: list,
    scene: dict,
    seed: int,
) -> Any:
    base = operations.join_tags(
        (config.get("base_prompt") or "").strip(),
        scene.get("prompt", ""),
    )
    negative = operations.join_tags(
        config.get("negative_prompt", ""),
        scene.get("negative", ""),
    )
    extra = [
        {
            "prompt": scene[key],
            "negative": scene.get(key + "_neg", ""),
        }
        for key in ("char1", "char2")
        if (scene.get(key) or "").strip()
    ]
    people, centers = operations.active_people(
        slots, config.get("char_centers"), extra
    )
    try:
        return operations.call_nai_api(
            config["token"],
            base,
            negative,
            int(scene.get("width", 832)),
            int(scene.get("height", 1216)),
            chars=people,
            scale=config.get("cfg_scale", 5.5),
            cfg_rescale=config.get("cfg_rescale", 0.56),
            steps=int(config.get("steps", 28)),
            sampler=config.get(
                "sampler", "k_euler_ancestral"
            ),
            scheduler=config.get("scheduler", "karras"),
            variety=config.get("variety", False),
            uc_preset=int(config.get("uc_preset", 3)),
            seed=seed,
            params=operations.with_centers(params, centers),
        )
    finally:
        operations.pace_complete()


def _scene_target(
    operations: GenerationHandlerOperations,
    output_dir: Path,
    config: dict,
    scene: dict,
    scene_id: str,
    copy_number: int,
    seed: int,
) -> Path:
    suffix = "" if copy_number == 1 else f"_{copy_number}번"
    stem = (
        f"{scene_id}_{operations.safe_name(scene['name'])}"
        f"_seed{seed}{suffix}"
    )
    return operations.available_output_path(
        output_dir / f"{stem}.webp",
        operations.output_format(config),
    )


def _save_scene_result(
    server: Any,
    operations: GenerationHandlerOperations,
    config: dict,
    state: dict,
    progress: dict,
    cell_id: str,
    scene_id: str,
    copy_number: int,
    fingerprint: str,
    target: Path,
    image: Any,
) -> tuple[Path, int]:
    frozen = server.live.frozen_blueprint()
    image.nai_blueprint_fingerprint = str(
        (frozen or {}).get("fingerprint") or ""
    )
    clean, max_side, quality = operations.output_clean_args(config)
    saved = operations.save_with_meta(
        image,
        target,
        fmt=operations.output_format(config),
        clean=clean,
        max_side=max_side,
        quality=quality,
    )
    server.live.set_image(image)
    operations.bump_daily(state)
    relative = (
        saved.resolve()
        .relative_to(operations.output_root(config).resolve())
        .as_posix()
    )
    progress[cell_id] = {
        "scene": scene_id,
        "copy": int(copy_number),
        "path": relative,
        "bytes": saved.stat().st_size,
        "content_sha256": hashlib.sha256(
            saved.read_bytes()
        ).hexdigest(),
        "fingerprint": fingerprint,
    }
    lineage_failures = 0
    try:
        operations.save_state(state)
    except Exception as error:
        operations.warning(
            "씬 결과 저장 후 재개 장부 저장 실패: %s", error
        )
        lineage_failures += 1
    try:
        operations.record_job_result(
            server.live.job_id,
            saved,
            artifact=relative,
            result_id="result-scene-" + fingerprint[:24],
        )
    except Exception as error:
        operations.warning(
            "씬 결과 저장 후 Job 계보 연결 실패: %s", error
        )
        lineage_failures += 1
    return saved, lineage_failures


def _scene_final_status(
    server: Any,
    done: int,
    failed: int,
    lineage_failures: int,
    total: int,
    blocked: bool,
) -> None:
    if server.live.stop_req:
        phase = "stopped"
        text = f"씬 모드 중지 — {done}/{total}장 (다시 실행 가능)"
    elif blocked:
        phase = "stopped"
        text = server.live.status_text
    elif failed:
        phase = "partial"
        text = f"씬 모드 일부 완료 — 성공 {done} · 실패 {failed}"
    elif lineage_failures:
        phase = "partial"
        text = (
            "씬 이미지는 저장했지만 작업 계보·재개 장부 "
            f"{lineage_failures}건을 확인해야 합니다."
        )
    else:
        phase = "completed"
        text = f"씬 모드 완료 — {done}/{total}장 (output/씬/)"
    server.live.update(
        status_text=text,
        completed=done,
        failed=max(failed, lineage_failures),
        phase=phase,
        can_retry=bool(
            failed
            or lineage_failures
            or blocked
            or server.live.stop_req
        ),
    )


def _scene_run_context(
    server: Any,
    operations: GenerationHandlerOperations,
    config: dict,
    jobs: list,
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    state = operations.load_state()
    state.setdefault("frag_seq", {})
    config["_frag_counters"] = state["frag_seq"]
    params = operations.runtime_generation_params(
        config, config["token"]
    )
    output_dir = operations.output_subdir(config, "씬")
    base_seed = _scene_seed_state(operations, config, state)
    run_fingerprint = _scene_fingerprints(blueprint, base_seed)
    progress = state.setdefault("scene_progress", {}).setdefault(
        run_fingerprint, {}
    )
    valid_cells, lineage_failures = _resume_scene_cells(
        server,
        operations,
        config,
        jobs,
        run_fingerprint,
        progress,
    )
    slots = [
        slot
        for slot in config.get("char_slots", [])
        if (
            operations.slot_prompt(slot).strip()
            and slot.get("enabled") is not False
        )
    ]
    return {
        "state": state,
        "params": params,
        "output_dir": output_dir,
        "base_seed": base_seed,
        "run_fingerprint": run_fingerprint,
        "progress": progress,
        "valid_cells": valid_cells,
        "lineage_failures": lineage_failures,
        "slots": slots,
    }


def _run_scene_cell(
    server: Any,
    operations: GenerationHandlerOperations,
    config: dict,
    context: dict[str, Any],
    scene: dict,
    copy_number: int,
    index: int,
    failed: int,
) -> tuple[str, int, int]:
    scene_id, cell_id, fingerprint = _scene_cell_identity(
        operations,
        context["run_fingerprint"],
        scene,
        copy_number,
        index,
    )
    if cell_id in context["valid_cells"]:
        server.live.update(
            index=index,
            filename=Path(
                str(
                    context["valid_cells"][cell_id].get("path")
                    or ""
                )
            ).name,
            status_text="확인된 완료 장면 건너뜀",
        )
        return "skip", 0, 0
    allowed, reason = operations.pace_gate(
        config, server.live, "씬"
    )
    if not allowed:
        server.live.update(status_text=reason)
        return "blocked", 0, 0
    seed = operations.seed_for(
        config,
        context["base_seed"],
        index + (copy_number - 1) * 100003,
    )
    target = _scene_target(
        operations,
        context["output_dir"],
        config,
        scene,
        scene_id,
        copy_number,
        seed,
    )
    server.live.update(
        index=index,
        filename=target.name,
        status_text="생성 중...",
        seed=seed,
    )
    try:
        image = _scene_request(
            operations,
            config,
            context["params"],
            context["slots"],
            scene,
            seed,
        )
    except Exception as error:
        operations.error("씬 '%s' 실패: %s", scene["name"], error)
        server.live.update(
            status_text=f"'{scene['name']}' 실패: {error}",
            failed=failed + 1,
            last_error=str(error),
        )
        return "failed", 0, 0
    saved, lineage_delta = _save_scene_result(
        server,
        operations,
        config,
        context["state"],
        context["progress"],
        cell_id,
        scene_id,
        copy_number,
        fingerprint,
        target,
        image,
    )
    server.live.update(
        index=index,
        filename=saved.name,
        daily=operations.daily_count(context["state"]),
    )
    return "done", 1, lineage_delta


def _execute_scene_jobs(
    server: Any,
    operations: GenerationHandlerOperations,
    config: dict,
    jobs: list,
    context: dict[str, Any],
) -> tuple[int, int, int, bool]:
    done = len(context["valid_cells"])
    failed = 0
    lineage_failures = context["lineage_failures"]
    server.live.update(
        total=len(jobs),
        index=done,
        completed=done,
        eta_base_completed=done,
        char_name="씬 모드",
    )
    blocked = False
    for index, (scene, copy_number) in enumerate(jobs, 1):
        if server.live.stop_req:
            break
        status, done_delta, lineage_delta = _run_scene_cell(
            server,
            operations,
            config,
            context,
            scene,
            copy_number,
            index,
            failed,
        )
        if status == "blocked":
            blocked = True
            break
        if status == "failed":
            failed += 1
            continue
        if status == "done":
            done += done_delta
            lineage_failures += lineage_delta
            server.live.update(completed=done)
    return done, failed, lineage_failures, blocked


def _run_scene(
    server: Any,
    operations: GenerationHandlerOperations,
    token: Any,
    config: dict,
    jobs: list,
    blueprint: dict[str, Any],
) -> None:
    try:
        context = _scene_run_context(
            server, operations, config, jobs, blueprint
        )
        done, failed, lineage_failures, blocked = (
            _execute_scene_jobs(
                server, operations, config, jobs, context
            )
        )
        _scene_final_status(
            server,
            done,
            failed,
            lineage_failures,
            len(jobs),
            blocked,
        )
    finally:
        config.pop("_frag_counters", None)
        server.live.release(token)


def handle_scene_run(
    server: Any,
    data: Any,
    operations: GenerationHandlerOperations,
) -> dict[str, Any]:
    """Run reserved scene/cast/step/options cells without mutating settings."""
    del data
    if server.live.running:
        return {"ok": False, "error": "이미 생성 중입니다."}
    with server.config_lock:
        config = copy.deepcopy(server.cfg)
    if not config.get("token", "").startswith("pst-"):
        return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
    jobs = operations.scene_mode_pending(config)
    if not jobs:
        return {
            "ok": False,
            "error": "예약 매수를 1 이상으로 건 씬이 없습니다.",
        }
    blueprint = operations.inherited_blueprint(
        config,
        source={"kind": "scene-run"},
        setting={
            "name": "씬 모드",
            "steps": copy.deepcopy(jobs),
        },
    )
    token = server.live.try_claim(
        "씬 모드",
        "settings",
        blueprint=blueprint,
        payload_identity={"kind": "setting", "jobs": len(jobs)},
    )
    if token is None:
        return {"ok": False, "error": "이미 생성 중입니다."}
    operations.start_daemon(
        lambda: _run_scene(
            server,
            operations,
            token,
            config,
            jobs,
            blueprint,
        )
    )
    return {"ok": True, "count": len(jobs)}
