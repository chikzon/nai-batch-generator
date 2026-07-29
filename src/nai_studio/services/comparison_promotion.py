# -*- coding: utf-8 -*-
"""비교 결과의 원문 레시피·엄격 계보·지식 자산 승격 조립 경계."""

from __future__ import annotations

import copy
import hashlib
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ComparisonPromotionPaths:
    """현재 프로필의 그림체·캐릭터·설정 저장 위치."""

    base_dir: Path
    style_dir: Path
    character_dir: Path
    settings_file: Path


@dataclass(frozen=True)
class ComparisonPromotionOperations:
    """비교 실행 조회와 기존 blueprint·자산 저장 계약을 늦게 연결한다."""

    transaction: Callable[[Path], AbstractContextManager[Any]]
    comparison_result_context: Callable[[dict, Any], dict[str, Any]]
    default_config: Mapping[str, Any]
    comparison_style_config: Callable[[dict, Any, dict], dict[str, Any]]
    recipe_setting_keys: tuple[str, ...]
    slot_prompt: Callable[[Any], str]
    comparison_result_evaluation: Callable[..., dict[str, Any]]
    build_result_promotion: Callable[..., dict[str, Any]]
    style_bundle_signature: Callable[[dict[str, Any]], str]
    character_bundle_signature: Callable[[dict[str, Any]], str]
    list_styles: Callable[[Any], list[dict[str, Any]]]
    load_spec: Callable[[], Any]
    load_combos: Callable[[], list[Any]]
    unique_library_name: Callable[..., str]
    save_style_file: Callable[..., Any]
    safe_name: Callable[[Any], str]
    record_import_batch: Callable[[dict[str, Any]], Any]
    sync_characters_to_files: Callable[[dict], Any]
    save_config: Callable[[dict], Any]
    random_character_id: Callable[[], str]
    recipe_for_output: Callable[[dict, Any], dict[str, Any]] | None = None


class LegacyPromotionLineageUnavailable(ValueError):
    """엄격 실행 식별자가 전혀 없는 구형 비교 결과."""


def _find_record_by_id(
    rows: list[Any],
    wanted: Any,
) -> dict[str, Any] | None:
    if wanted is None:
        return None
    return next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("id")) == str(wanted)
        ),
        None,
    )


def _character_recipe_parts(
    context: dict[str, Any],
    record: dict[str, Any],
    character: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if character is not None:
        return (
            [{
                "name": (
                    character.get("name")
                    or record.get("character")
                    or "캐릭터"
                ),
                "prompt": character.get("female") or "",
                "outfit": character.get("clothed") or "",
                "negative": character.get("negative") or "",
                "variant": copy.deepcopy(
                    character.get("variant") or {}
                ),
                "variants": copy.deepcopy(
                    character.get("variants") or []
                ),
                "reference_ids": copy.deepcopy(
                    character.get("reference_ids") or []
                ),
                "vibe_ids": copy.deepcopy(
                    character.get("vibe_ids") or []
                ),
                "enabled": True,
            }],
            [{"x": 0.5, "y": 0.5}],
        )
    slots = [
        dict(slot)
        for slot in (context.get("char_slots") or [])
        if isinstance(slot, dict)
    ]
    centers = [
        dict(center)
        for center in (context.get("char_centers") or [])
        if isinstance(center, dict)
    ]
    return slots, centers


def _legacy_recipe_from_context(
    operations: ComparisonPromotionOperations,
    context_result: dict[str, Any],
) -> dict[str, Any]:
    progress = context_result["manifest"]
    record = context_result["record"]
    context = progress.get("recipe_context")
    if not isinstance(context, dict):
        raise ValueError(
            "이 결과는 원문 레시피 기록 기능 이전에 만들어져 자동 적용할 수 없습니다."
        )
    config = dict(operations.default_config)
    if isinstance(context.get("config"), dict):
        config.update(context["config"])
    options = context.get("options")
    if not isinstance(options, dict):
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
    styles = (
        context.get("styles")
        if isinstance(context.get("styles"), list)
        else []
    )
    characters = (
        context.get("characters")
        if isinstance(context.get("characters"), list)
        else []
    )
    style = _find_record_by_id(styles, record.get("style_id"))
    character = _find_record_by_id(
        characters, record.get("character_id")
    )
    used = operations.comparison_style_config(
        config, style, options
    )
    slots, centers = _character_recipe_parts(
        context, record, character
    )
    include_refs = bool(options.get("include_refs"))
    return {
        "version": 1,
        "mode": str(
            progress.get("mode") or options.get("mode") or ""
        ),
        "base_prompt": (
            (style or {}).get("base")
            or config.get("base_prompt")
            or "1girl"
        ).strip(),
        "negative_prompt": (
            (
                (style or {}).get("negative")
                if style is not None
                else config.get("negative_prompt", "")
            )
            or ""
        ),
        "style_name": (
            (style or {}).get("name")
            or config.get("style_name")
            or record.get("style")
            or ""
        ),
        "settings": {
            key: used.get(key)
            for key in operations.recipe_setting_keys
        },
        "char_slots": slots,
        "char_centers": centers,
        "nai_seed": int(record.get("seed") or 0),
        "include_refs": include_refs,
        "vibes": (
            config.get("vibes") or []
            if include_refs
            else []
        ),
        "char_refs": (
            config.get("char_refs") or []
            if include_refs
            else []
        ),
        "source": {
            "style": style or {},
            "character": character or {},
        },
    }


def _recipe_for_context(
    operations: ComparisonPromotionOperations,
    context_result: dict[str, Any],
) -> dict[str, Any]:
    progress = context_result["manifest"]
    if not isinstance(progress.get("completed"), dict):
        raise ValueError("비교 결과 기록 형식이 올바르지 않습니다.")
    record = context_result["record"]
    if isinstance(record.get("recipe"), dict):
        recipe = copy.deepcopy(record["recipe"])
        recipe["nai_seed"] = int(
            record.get("seed") or recipe.get("nai_seed") or 0
        )
        return recipe
    return _legacy_recipe_from_context(operations, context_result)


def comparison_recipe_for_output(
    operations: ComparisonPromotionOperations,
    config: dict,
    relative_path: Any,
) -> dict[str, Any]:
    """비교 manifest의 실제 원문·설정·캐릭터 묶음을 결과 한 장에 복원한다."""
    context = operations.comparison_result_context(
        config, relative_path
    )
    return {
        "ok": True,
        "file": context["file"],
        "recipe": _recipe_for_context(operations, context),
    }


def _restored_recipe(
    operations: ComparisonPromotionOperations,
    config: dict,
    relative_path: Any,
) -> dict[str, Any]:
    if operations.recipe_for_output is not None:
        return operations.recipe_for_output(config, relative_path)
    return comparison_recipe_for_output(
        operations, config, relative_path
    )


def _verified_result(
    context: dict[str, Any],
) -> dict[str, Any]:
    record = context["record"]
    strict_keys = (
        "content_sha256",
        "request_id",
        "payload_hash",
        "blueprint_fingerprint",
    )
    if not any(key in record for key in strict_keys):
        raise LegacyPromotionLineageUnavailable(
            "이 비교 결과에는 엄격 실행 식별자가 없습니다."
        )
    missing = [key for key in strict_keys if not record.get(key)]
    if missing:
        raise ValueError(
            "비교 결과의 엄격 실행 식별자가 일부 빠졌습니다: "
            + ", ".join(missing)
        )
    actual_sha = hashlib.sha256(
        context["image_path"].read_bytes()
    ).hexdigest()
    if actual_sha != str(
        record.get("content_sha256") or ""
    ).lower():
        raise ValueError(
            "저장된 비교 이미지가 manifest 기록 뒤 바뀌어 엄격한 계보로 승격할 수 없습니다."
        )
    return {
        "path": context["file"],
        "content_sha256": actual_sha,
        "request_id": record.get("request_id"),
        "payload_hash": record.get("payload_hash"),
        "blueprint_fingerprint": record.get(
            "blueprint_fingerprint"
        ),
    }


def _style_settings(
    operations: ComparisonPromotionOperations,
    recipe: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in (recipe.get("settings") or {}).items()
        if (
            key in operations.recipe_setting_keys
            and value is not None
        )
    }


def _style_promotion_record(
    operations: ComparisonPromotionOperations,
    result: dict[str, Any],
    context: dict[str, Any],
    evaluation: dict[str, Any],
    recipe: dict[str, Any],
    name: str,
    resolved_names: list[str] | None,
) -> list[dict[str, Any]]:
    resolved = (
        (resolved_names or [""])[0] if resolved_names else ""
    )
    return [operations.build_result_promotion(
        result,
        context["manifest"],
        evaluation,
        target="style",
        name=str(
            resolved or name or recipe.get("style_name") or ""
        ),
        content={
            "base": str(recipe.get("base_prompt") or ""),
            "negative": str(
                recipe.get("negative_prompt") or ""
            ),
            "generation_settings": _style_settings(
                operations, recipe
            ),
        },
    )]


def _character_promotion_records(
    operations: ComparisonPromotionOperations,
    result: dict[str, Any],
    context: dict[str, Any],
    evaluation: dict[str, Any],
    recipe: dict[str, Any],
    resolved_names: list[str] | None,
) -> list[dict[str, Any]]:
    output = []
    slots = [
        slot
        for slot in (recipe.get("char_slots") or [])
        if (
            isinstance(slot, dict)
            and operations.slot_prompt(slot).strip()
        )
    ]
    for index, slot in enumerate(slots, 1):
        variants = copy.deepcopy(slot.get("variants") or [])
        variant = copy.deepcopy(slot.get("variant") or {})
        if variant and variant not in variants:
            variants.insert(0, variant)
        resolved = (
            resolved_names[index - 1]
            if resolved_names and index <= len(resolved_names)
            else ""
        )
        output.append(operations.build_result_promotion(
            result,
            context["manifest"],
            evaluation,
            target="character",
            name=str(
                resolved
                or slot.get("name")
                or f"비교 결과 캐릭터 {index}"
            ),
            content={
                "prompt": operations.slot_prompt(slot),
                "appearance": str(
                    slot.get("prompt")
                    or slot.get("female")
                    or ""
                ),
                "clothed": str(
                    slot.get("outfit")
                    or slot.get("clothed")
                    or ""
                ),
                "negative": str(slot.get("negative") or ""),
                "variants": variants,
                "reference_refs": list(
                    slot.get("reference_ids") or []
                ),
                "vibe_refs": list(slot.get("vibe_ids") or []),
            },
        ))
    if not output:
        raise ValueError(
            "이 비교 결과에는 승격할 캐릭터가 없습니다."
        )
    return output


def result_promotion_records(
    operations: ComparisonPromotionOperations,
    config: dict,
    relative_path: Any,
    kind: Any,
    name: str = "",
    resolved_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """검증된 실행 식별자와 원문 자산 묶음을 장부용 승격 레코드로 만든다."""
    context = operations.comparison_result_context(
        config, relative_path
    )
    recipe = _restored_recipe(
        operations, config, relative_path
    )["recipe"]
    result = _verified_result(context)
    evaluation = operations.comparison_result_evaluation(
        context["file"],
        context["manifest"],
        context["job_key"],
    )
    target = str(kind or "").strip().casefold()
    if target == "style":
        return _style_promotion_record(
            operations,
            result,
            context,
            evaluation,
            recipe,
            name,
            resolved_names,
        )
    if target != "characters":
        raise ValueError("승격할 자료 종류가 올바르지 않습니다.")
    return _character_promotion_records(
        operations,
        result,
        context,
        evaluation,
        recipe,
        resolved_names,
    )


def _style_signature(
    operations: ComparisonPromotionOperations,
    prompt: Any,
    negative: Any,
    settings: Any,
) -> str:
    return operations.style_bundle_signature({
        "prompt": prompt,
        "negative": negative,
        "settings": settings,
    })


def _inside_base(path: Path, base_dir: Path) -> str:
    try:
        return (
            path.resolve()
            .relative_to(base_dir.resolve())
            .as_posix()
        )
    except (OSError, ValueError):
        return ""


def _promote_style(
    paths: ComparisonPromotionPaths,
    operations: ComparisonPromotionOperations,
    recipe: dict[str, Any],
    source_file: str,
    name: str,
    spec: Any,
) -> dict[str, Any]:
    prompt = recipe.get("base_prompt") or ""
    negative = recipe.get("negative_prompt") or ""
    settings = _style_settings(operations, recipe)
    wanted = _style_signature(
        operations, prompt, negative, settings
    )
    resolved_spec = spec or operations.load_spec()
    styles = operations.list_styles(resolved_spec)
    same = next(
        (
            item
            for item in styles
            if _style_signature(
                operations,
                item.get("prompt"),
                item.get("negative"),
                item.get("settings"),
            ) == wanted
        ),
        None,
    )
    if same is not None:
        return {
            "ok": True,
            "kind": "style",
            "saved": 0,
            "existing": 1,
            "names": [same.get("name") or "기존 그림체"],
            "styles": styles,
            "changed_config": False,
        }
    collected = next(
        (
            item
            for item in operations.load_combos()
            if (
                isinstance(item, dict)
                and operations.style_bundle_signature(item)
                == wanted
            )
        ),
        None,
    )
    if collected is not None:
        return {
            "ok": True,
            "kind": "style",
            "saved": 0,
            "existing": 1,
            "names": [
                collected.get("title")
                or collected.get("id")
                or "기존 그림체"
            ],
            "styles": styles,
            "changed_config": False,
            "existing_store": "수집/그림체.json",
        }
    return _save_promoted_style(
        paths,
        operations,
        recipe,
        source_file,
        name,
        resolved_spec,
        styles,
        prompt,
        negative,
        settings,
    )


def _save_promoted_style(
    paths: ComparisonPromotionPaths,
    operations: ComparisonPromotionOperations,
    recipe: dict[str, Any],
    source_file: str,
    name: str,
    resolved_spec: Any,
    styles: list[dict[str, Any]],
    prompt: str,
    negative: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    final_name = operations.unique_library_name(
        paths.style_dir,
        name or recipe.get("style_name"),
        "비교 결과 그림체",
        (item.get("name") for item in styles),
    )
    operations.save_style_file(
        final_name,
        prompt=prompt,
        negative=negative,
        settings=settings,
    )
    saved_path = (
        paths.style_dir
        / f"{operations.safe_name(final_name)}.json"
    )
    relative = _inside_base(saved_path, paths.base_dir)
    batch_id = None
    if relative and saved_path.is_file():
        batch_id = operations.record_import_batch({
            "kind": "comparison",
            "file": source_file,
            "installed": [{
                "path": relative,
                "sha256": hashlib.sha256(
                    saved_path.read_bytes()
                ).hexdigest(),
            }],
            "요약": "비교 결과: 그림체 묶음 1건 승격",
        })
    return {
        "ok": True,
        "kind": "style",
        "saved": 1,
        "existing": 0,
        "names": [final_name],
        "styles": operations.list_styles(resolved_spec),
        "changed_config": False,
        "batch": batch_id,
    }


def _new_character(
    operations: ComparisonPromotionOperations,
    slot: dict[str, Any],
    final_name: str,
    source_file: str,
) -> dict[str, Any]:
    return {
        "id": operations.random_character_id(),
        "name": final_name,
        "female": str(slot.get("prompt") or ""),
        "clothed": str(slot.get("outfit") or ""),
        "negative": str(slot.get("negative") or ""),
        "variant": copy.deepcopy(slot.get("variant") or {}),
        "variants": copy.deepcopy(slot.get("variants") or []),
        "reference_ids": copy.deepcopy(
            slot.get("reference_ids") or []
        ),
        "vibe_ids": copy.deepcopy(slot.get("vibe_ids") or []),
        "enabled": True,
        "folder_id": None,
        "subfolder_id": None,
        "source": f"비교 결과: {source_file}",
    }


def _promote_characters(
    paths: ComparisonPromotionPaths,
    operations: ComparisonPromotionOperations,
    config: dict,
    recipe: dict[str, Any],
    source_file: str,
    name: str,
) -> dict[str, Any]:
    slots = [
        slot
        for slot in (recipe.get("char_slots") or [])
        if (
            isinstance(slot, dict)
            and operations.slot_prompt(slot).strip()
        )
    ]
    if not slots:
        return {
            "ok": False,
            "error": "이 비교 결과에는 저장할 캐릭터가 없습니다.",
        }
    characters = config.setdefault("characters", [])
    names: list[str] = []
    saved_records: list[dict[str, Any]] = []
    existing = 0
    for index, slot in enumerate(slots, 1):
        signature = operations.character_bundle_signature({
            "female": str(slot.get("prompt") or ""),
            "clothed": str(slot.get("outfit") or ""),
            "negative": str(slot.get("negative") or ""),
            "variant": copy.deepcopy(slot.get("variant") or {}),
            "variants": copy.deepcopy(
                slot.get("variants") or []
            ),
            "reference_ids": copy.deepcopy(
                slot.get("reference_ids") or []
            ),
            "vibe_ids": copy.deepcopy(
                slot.get("vibe_ids") or []
            ),
        })
        same = next(
            (
                item
                for item in characters
                if operations.character_bundle_signature(item)
                == signature
            ),
            None,
        )
        if same is not None:
            names.append(
                same.get("name") or f"기존 캐릭터 {index}"
            )
            existing += 1
            continue
        requested = slot.get("name") or (
            f"{name} {index}"
            if name and len(slots) > 1
            else name
        )
        final_name = operations.unique_library_name(
            paths.character_dir,
            requested,
            f"비교 결과 캐릭터 {index}",
            (item.get("name") for item in characters),
        )
        created = _new_character(
            operations, slot, final_name, source_file
        )
        characters.append(created)
        saved_records.append(created)
        names.append(final_name)
    return _finish_character_promotion(
        paths,
        operations,
        config,
        source_file,
        characters,
        names,
        saved_records,
        existing,
    )


def _finish_character_promotion(
    paths: ComparisonPromotionPaths,
    operations: ComparisonPromotionOperations,
    config: dict,
    source_file: str,
    characters: list[dict[str, Any]],
    names: list[str],
    saved_records: list[dict[str, Any]],
    existing: int,
) -> dict[str, Any]:
    if saved_records:
        operations.sync_characters_to_files(config)
        operations.save_config(config)
    batch_id = None
    settings_inside = bool(
        _inside_base(paths.settings_file, paths.base_dir)
    )
    if saved_records and settings_inside:
        records = [{
            "id": item.get("id"),
            "after_signature": (
                operations.character_bundle_signature(item)
            ),
        } for item in saved_records]
        batch_id = operations.record_import_batch({
            "kind": "comparison",
            "file": source_file,
            "characters": records,
            "요약": (
                f"비교 결과: 캐릭터 묶음 {len(records)}건 승격"
            ),
        })
    return {
        "ok": True,
        "kind": "characters",
        "saved": len(saved_records),
        "existing": existing,
        "names": names,
        "characters": characters,
        "changed_config": bool(saved_records),
        "batch": batch_id,
    }


def _promote_locked(
    paths: ComparisonPromotionPaths,
    operations: ComparisonPromotionOperations,
    config: dict,
    relative_path: Any,
    kind: Any,
    name: str,
    spec: Any,
) -> dict[str, Any]:
    restored = _restored_recipe(
        operations, config, relative_path
    )
    recipe = restored["recipe"]
    target = str(kind or "").strip().lower()
    if target == "setting":
        return {
            "ok": False,
            "error": (
                "이 비교 결과에는 세팅 선택 상태가 없습니다. "
                "그림만 보고 세팅을 추정해 저장하지 않습니다."
            ),
        }
    if target == "style":
        return _promote_style(
            paths,
            operations,
            recipe,
            restored["file"],
            name,
            spec,
        )
    if target != "characters":
        return {
            "ok": False,
            "error": "저장할 자료 종류가 올바르지 않습니다.",
        }
    return _promote_characters(
        paths,
        operations,
        config,
        recipe,
        restored["file"],
        name,
    )


def promote_comparison_recipe_assets(
    paths: ComparisonPromotionPaths,
    operations: ComparisonPromotionOperations,
    config: dict,
    relative_path: Any,
    kind: Any,
    name: str = "",
    spec: Any = None,
) -> dict[str, Any]:
    """명시적으로 선택한 결과만 중복·덮어쓰기 없이 기존 자산에 저장한다."""
    with operations.transaction(paths.base_dir):
        return _promote_locked(
            paths,
            operations,
            config,
            relative_path,
            kind,
            name,
            spec,
        )
