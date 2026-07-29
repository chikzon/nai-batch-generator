# -*- coding: utf-8 -*-
"""세팅 작업 한 장의 경로·프롬프트·인물·시드를 순수 계산한다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GenerationStepOperations:
    character_resource_config: Callable[[dict, dict], dict]
    setting_reference_config: Callable[[dict, dict], tuple]
    build_scene: Callable[[dict, dict, dict, int], tuple]
    seed_for: Callable[[dict, int, int], int]
    join_tags: Callable[..., str]
    setting_scene_people: Callable[..., tuple]
    with_position_mode: Callable[[dict, Any, bool], dict]
    with_centers: Callable[[dict, list], dict]


def generation_reference_config(
    operations: GenerationStepOperations,
    config: dict,
    scene: dict,
    character: dict,
) -> dict:
    """실행 coordinator가 Vibe·Reference를 준비하기 전의 요청 설정을 만든다."""
    cast_config = operations.character_resource_config(config, character)
    reference_config, _, _ = operations.setting_reference_config(
        cast_config,
        scene,
    )
    return reference_config


def prepare_generation_step(
    operations: GenerationStepOperations,
    config: dict,
    asset_config: dict,
    item: tuple,
    *,
    base_seed: int,
    seed_key: str,
    output_base: Path,
) -> dict:
    """재시도 밖에서 한 번만 계산할 장면·경로·시드 재료를 만든다."""
    character, character_id, scene_number, copy_number = item
    scene = asset_config["scenes"][str(scene_number)]
    (
        base_prompt,
        female_prompt,
        male_prompt,
        character_negative,
        male_negative,
        width,
        height,
    ) = operations.build_scene(
        asset_config,
        character,
        config,
        scene_number,
    )

    base_negative = asset_config["base"].get(
        "nsfw_negative_prompt",
        asset_config["base"]["negative_prompt"],
    )
    seed = operations.seed_for(
        config,
        base_seed,
        scene_number + (copy_number - 1) * 100003,
    )
    suffix = "" if copy_number == 1 else f"_{copy_number}벌"
    filename = (
        f"{scene_number:03d}_"
        f"{scene['name'].replace(' ', '_').replace('/', '_')}"
        f"{suffix}.webp"
    )
    output_dir = Path(output_base) / f"seed_{seed_key}" / character_id
    call_options = {
        "scale": asset_config["base"].get(
            "cfg_scale",
            config.get("cfg_scale", 5.5),
        ),
        "cfg_rescale": asset_config["base"].get(
            "cfg_rescale",
            config.get("cfg_rescale", 0.56),
        ),
        "steps": int(config.get(
            "steps",
            asset_config["base"].get("steps", 28),
        )),
        "sampler": asset_config["base"].get(
            "sampler",
            config.get("sampler", "k_euler_ancestral"),
        ),
        "scheduler": asset_config["base"].get(
            "scheduler",
            config.get("scheduler", "karras"),
        ),
        "uc_preset": int(config.get(
            "uc_preset",
            asset_config["base"].get("uc_preset", 3),
        )),
        "variety": config.get("variety", False),
    }
    return {
        "character": character,
        "character_id": character_id,
        "character_label": character.get("name") or character_id,
        "scene": scene,
        "scene_number": scene_number,
        "copy_number": copy_number,
        "output_dir": output_dir,
        "output_path": output_dir / filename,
        "filename": filename,
        "base_prompt": base_prompt,
        "base_negative": base_negative,
        "female_prompt": female_prompt,
        "male_prompt": male_prompt,
        "character_negative": character_negative,
        "male_negative": male_negative,
        "seed": seed,
        "width": width,
        "height": height,
        **call_options,
    }


def prepare_generation_attempt(
    operations: GenerationStepOperations,
    config: dict,
    step: dict,
    runtime_params: dict,
) -> dict:
    """재시도마다 기존 순서로 인물·좌표와 씬 네거티브를 다시 계산한다."""
    scene = step["scene"]
    scene_negative = (scene.get("negative") or "").strip()
    negative_prompt = (
        operations.join_tags(step["base_negative"], scene_negative)
        if scene_negative
        else step["base_negative"]
    )
    people, centers, use_positions = operations.setting_scene_people(
        scene,
        step["female_prompt"],
        step["male_prompt"],
        step["character_negative"],
        step["male_negative"],
        step["character"],
        config,
    )
    params = operations.with_position_mode(
        runtime_params,
        step["character"].get("position_mode"),
        use_positions,
    )
    if use_positions:
        params = operations.with_centers(params, centers)
    return {
        **step,
        "negative_prompt": negative_prompt,
        "people": people,
        "centers": centers,
        "use_positions": use_positions,
        "params": params,
    }


__all__ = [
    "GenerationStepOperations",
    "generation_reference_config",
    "prepare_generation_attempt",
    "prepare_generation_step",
]
