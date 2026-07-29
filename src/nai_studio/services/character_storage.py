# -*- coding: utf-8 -*-
"""구 설정 이전과 캐릭터 독립 JSON 동기화의 저장 경계."""

from __future__ import annotations

import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


GROUP_ORDER = (
    "기본",
    "상황",
    "행동",
    "외모",
    "의상",
    "장신구",
    "마무리",
)

CHARACTER_ASSET_OPTIONAL_FIELDS = (
    "variant",
    "variants",
    "selected_variant_id",
    "reference_ids",
    "vibe_ids",
    "representative",
    "representative_image",
    "images",
    "evidence",
    "evidence_refs",
    "evidence_images",
    "variation_images",
    "reference_inset",
    "temporary_generation_overrides",
    "lineage",
)


@dataclass(frozen=True)
class CharacterStoragePaths:
    """현재 프로필의 옛 설정과 캐릭터 저장 위치."""

    legacy_settings_file: Path
    settings_file: Path
    character_dir: Path


@dataclass(frozen=True)
class CharacterStorageOperations:
    """현재 앱의 경로 해석·원자 저장·복구·ID 생성을 호출 시점에 연결한다."""

    read_legacy_settings: Callable[[], dict]
    setting_path: Callable[[str], Path | None]
    load_json: Callable[[Path], Any]
    atomic_write_json: Callable[..., None]
    recoverable_remove: Callable[..., Path]
    random_id: Callable[[], str]
    log_info: Callable[..., Any]
    log_warning: Callable[..., Any]


def safe_name(name: Any) -> str:
    """Windows 파일명 금지 문자를 제거하되 기존 빈 이름 대체값을 유지한다."""
    invalid = '<>:"/\\|?*'
    result = "".join(
        character
        for character in (name or "")
        if character not in invalid
    ).strip()
    return result or "이름없음"


def compose_from_groups(groups: Any) -> str:
    """구 캐릭터 그룹을 기존 고정 순서의 전체 외형 프롬프트로 결합한다."""
    parts = []
    for group in GROUP_ORDER:
        value = (groups or {}).get(group, "").strip().rstrip(",")
        if value:
            parts.append(value)
    return ", ".join(parts)


def folder_by_name(
    config: dict,
    operations: CharacterStorageOperations,
    name: str,
    parent_id: str | None = None,
) -> dict:
    """표시 폴더를 이름·부모 조합으로 재사용하고 없을 때만 기존 형식으로 만든다."""
    for folder in config.get("character_folders", []):
        if (
            folder.get("name") == name
            and folder.get("parent_id") == parent_id
        ):
            return folder
    folder = {
        "id": operations.random_id(),
        "name": name,
        "parent_id": parent_id,
    }
    config.setdefault("character_folders", []).append(folder)
    return folder


def read_character_documents(
    operations: CharacterStorageOperations,
    paths: Any,
) -> list[tuple[Path, Any, Exception | None]]:
    """독립 JSON을 병렬로 읽고 깨진 파일만 기존 .bak 복구 경계로 다시 읽는다."""
    documents = list(paths)

    def read_one(
        path: Path,
    ) -> tuple[Path, Any, Exception | None]:
        try:
            return (
                path,
                json.loads(path.read_text(encoding="utf-8-sig")),
                None,
            )
        except Exception as first:
            try:
                return path, operations.load_json(path), None
            except Exception:
                return path, None, first

    if len(documents) < 32:
        return [read_one(path) for path in documents]
    workers = min(16, max(4, (os.cpu_count() or 4) * 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(read_one, documents))


def migrate_legacy_selections(
    config: dict,
    operations: CharacterStorageOperations,
) -> None:
    """구 선택·테마·상대역 키를 현재 세팅 구조로 기존 한 번만 이전한다."""
    if config.get("_settings_migrated"):
        config.pop("male_prompt", None)
        config.pop("male_outfit", None)
        return
    setting_state = config.setdefault("setting_state", {})
    if config.get("selected_positions") is not None:
        setting_state.setdefault("남녀 체위", {})["selected"] = (
            config.pop("selected_positions", [])
        )
        setting_state["남녀 체위"].setdefault("opts", {})
        for old, new in (
            ("location_theme", "장소테마"),
            ("time_of_day", "시간대"),
            ("expression_arc", "표정진행"),
            ("male_wear", "남자옷"),
        ):
            if config.get(old):
                setting_state["남녀 체위"]["opts"][new] = (
                    config.pop(old)
                )
            else:
                config.pop(old, None)
    if config.get("selected_expressions") is not None:
        setting_state.setdefault("표정", {})["selected"] = config.pop(
            "selected_expressions",
            [],
        )
    if config.get("selected_yuri") is not None:
        setting_state.setdefault("백합", {})["selected"] = config.pop(
            "selected_yuri",
            [],
        )
        setting_state["백합"].setdefault("opts", {})
        if config.get("yuri_undress"):
            setting_state["백합"]["opts"]["옷진행"] = config.pop(
                "yuri_undress"
            )

    def put_role(
        name: str,
        role_updates: dict[str, Any],
    ) -> None:
        path = operations.setting_path(name)
        if not path:
            return
        try:
            pack = operations.load_json(path)
            role = pack.setdefault("상대역", {})
            for key, value in role_updates.items():
                if value and not role.get(key):
                    role[key] = value
            operations.atomic_write_json(path, pack)
        except Exception as error:
            operations.log_warning(
                f"상대역 이전 실패({name}): {error}"
            )

    legacy_male = config.pop("male_prompt", "")
    legacy_male_outfit = config.pop("male_outfit", "")
    if legacy_male:
        put_role(
            "남녀 체위",
            {
                "외형": legacy_male,
                "의상": legacy_male_outfit,
            },
        )
    if config.get("partner_prompt"):
        put_role(
            "백합",
            {
                "외형": config.pop("partner_prompt", ""),
                "착의": config.pop("partner_clothed", ""),
                "네거티브": config.pop("partner_negative", ""),
            },
        )
    config.pop("pack_pos", None)
    config.pop("pack_expr", None)
    config.pop("pack_yuri", None)
    config["_settings_migrated"] = True


def migrate_legacy(
    paths: CharacterStoragePaths,
    operations: CharacterStorageOperations,
    config: dict,
    *,
    light_preset: Any,
    positions: Any,
) -> dict:
    """설정.txt의 기존 필드와 캐릭터 섹션을 현재 키로 원래 범위만 이전한다."""
    old = operations.read_legacy_settings()
    if not old:
        return config
    operations.log_info(
        "설정.txt 발견 — 설정.json 으로 1회 이전합니다."
    )
    config["token"] = old.get("토큰", config["token"])
    if old.get("시드", "").isdigit():
        config["seed"] = int(old["시드"])
    config["base_prompt"] = old.get(
        "그림체",
        config["base_prompt"],
    )
    config["negative_prompt"] = old.get(
        "네거티브",
        config["negative_prompt"],
    )
    config["male_prompt"] = old.get(
        "남자",
        config["male_prompt"],
    )
    for key, cast, target in (
        ("CFG", float, "cfg_scale"),
        ("리스케일", float, "cfg_rescale"),
        ("스텝", int, "steps"),
    ):
        value = old.get(key, "")
        if value:
            try:
                config[target] = cast(value)
            except ValueError:
                pass
    if old.get("샘플러"):
        config["sampler"] = old["샘플러"]
    if old.get("노이즈"):
        config["scheduler"] = old["노이즈"]
    if old.get("버라이어티"):
        config["variety"] = (
            old["버라이어티"].lower()
            in ("켬", "on", "true", "1", "yes")
        )

    if old.get("여자"):
        config["characters"].append({
            "id": "char1",
            "name": "캐릭터 1",
            "female": old["여자"],
            "negative": "",
            "enabled": True,
            "folder_id": None,
            "subfolder_id": None,
        })

    current = None
    sections: dict[tuple[str, str], dict[str, str]] = {}
    try:
        with open(
            paths.legacy_settings_file,
            encoding="utf-8",
        ) as stream:
            for line in stream:
                line = line.strip().lstrip("﻿")
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    heading = line[1:-1].strip()
                    parts = heading.split(None, 1)
                    if (
                        len(parts) == 2
                        and parts[0] in ("여자", "남자")
                    ):
                        current = (parts[0], parts[1].strip())
                        sections[current] = {}
                    else:
                        current = None
                elif "=" in line and current:
                    key, value = line.split("=", 1)
                    sections[current][key.strip()] = value.strip()
    except OSError:
        pass
    for (
        character_type,
        character_name,
    ), fields in sections.items():
        if (
            character_type == "여자"
            and fields.get("외형")
        ):
            if any(
                character.get("name") == character_name
                for character in config["characters"]
            ):
                continue
            config["characters"].append({
                "id": operations.random_id(),
                "name": character_name,
                "female": fields.get("외형", ""),
                "clothed": fields.get("착의", ""),
                "negative": fields.get("네거티브", ""),
                "enabled": True,
                "folder_id": None,
                "subfolder_id": None,
            })
        elif (
            character_type == "남자"
            and fields.get("외형")
            and not config.get("male_prompt")
        ):
            config["male_prompt"] = fields["외형"]

    selected = old.get("선택체위", "").strip()
    if selected:
        config["selected_positions"] = [
            int(value)
            for value in selected.split(",")
            if value.strip().isdigit()
        ]
    else:
        preset_name = old.get("세트", "전체")
        if preset_name == "가벼움":
            config["selected_positions"] = list(light_preset)
        else:
            config["selected_positions"] = [
                position["id"] for position in positions
            ]
    return config


def import_char_files(
    paths: CharacterStoragePaths,
    operations: CharacterStorageOperations,
    config: dict,
) -> None:
    """새 파일과 설정보다 더 최근에 외부 편집된 같은 id 파일만 설정에 반영한다."""
    if not paths.character_dir.exists():
        return
    known = {
        character.get("id"): character
        for character in config.get("characters", [])
        if character.get("id")
    }
    try:
        settings_mtime = paths.settings_file.stat().st_mtime_ns
    except OSError:
        settings_mtime = -1
    registered: list[str] = []
    refreshed: list[str] = []
    documents = read_character_documents(
        operations,
        sorted(paths.character_dir.rglob("*.json")),
    )
    for path, data, error in documents:
        if error is not None:
            operations.log_warning(
                f"캐릭터 파일 손상(건너뜀): {path.name}"
            )
            continue
        if not isinstance(data, dict):
            continue
        character_id = data.get("id")
        appearance = (
            (data.get("외형") or "").strip()
            or compose_from_groups(data.get("그룹"))
        )
        clothed = data.get("착의", "")
        if not (
            appearance or str(clothed or "").strip()
        ):
            continue
        relative = path.relative_to(
            paths.character_dir
        ).parts[:-1]
        folder_id = subfolder_id = None
        if len(relative) >= 1:
            folder = folder_by_name(
                config,
                operations,
                relative[0],
            )
            folder_id = folder["id"]
        if len(relative) >= 2:
            subfolder = folder_by_name(
                config,
                operations,
                relative[1],
                parent_id=folder_id,
            )
            subfolder_id = subfolder["id"]
        if character_id and character_id in known:
            try:
                externally_newer = (
                    path.stat().st_mtime_ns > settings_mtime
                )
            except OSError:
                externally_newer = False
            if not externally_newer:
                continue
            current = known[character_id]
            current.update({
                "name": data.get("이름") or path.stem,
                "female": appearance,
                "clothed": clothed,
                "negative": data.get("네거티브", ""),
                "source": data.get("출처", ""),
                "folder_id": folder_id,
                "subfolder_id": subfolder_id,
            })
            for field in CHARACTER_ASSET_OPTIONAL_FIELDS:
                if field in data:
                    current[field] = copy.deepcopy(data[field])
            if data.get("그룹"):
                current["groups"] = data["그룹"]
            else:
                current.pop("groups", None)
            refreshed.append(
                str(path.relative_to(paths.character_dir))
            )
            continue
        new_id = character_id or operations.random_id()
        new_character = {
            "id": new_id,
            "name": data.get("이름") or path.stem,
            "female": appearance,
            "clothed": clothed,
            "negative": data.get("네거티브", ""),
            "source": data.get("출처", ""),
            "enabled": True,
            "folder_id": folder_id,
            "subfolder_id": subfolder_id,
        }
        for field in CHARACTER_ASSET_OPTIONAL_FIELDS:
            if field in data:
                new_character[field] = copy.deepcopy(data[field])
        if data.get("그룹"):
            new_character["groups"] = data["그룹"]
        config.setdefault("characters", []).append(new_character)
        known[new_id] = new_character
        registered.append(
            str(path.relative_to(paths.character_dir))
        )
    if registered:
        sample = ", ".join(registered[:3])
        operations.log_info(
            f"캐릭터 파일 등록: {len(registered):,}개"
            + (f" (예: {sample})" if sample else "")
        )
    if refreshed:
        sample = ", ".join(refreshed[:3])
        operations.log_info(
            f"외부에서 더 새로 편집한 캐릭터 반영: "
            f"{len(refreshed):,}개"
            + (f" (예: {sample})" if sample else "")
        )


def sync_chars_to_files(
    paths: CharacterStoragePaths,
    operations: CharacterStorageOperations,
    config: dict,
) -> None:
    """설정 캐릭터를 알려지지 않은 필드와 파일명을 보존하며 독립 JSON에 동기화한다."""
    paths.character_dir.mkdir(exist_ok=True)
    folders = {
        folder["id"]: folder
        for folder in config.get("character_folders", [])
    }
    existing_by_id: dict[str, list[tuple[Path, dict]]] = {}
    existing_by_path: dict[Path, dict] = {}
    documents = read_character_documents(
        operations,
        paths.character_dir.rglob("*.json"),
    )
    for old_path, old_data, error in documents:
        if error is not None:
            continue
        if (
            not isinstance(old_data, dict)
            or not old_data.get("id")
        ):
            continue
        existing_by_id.setdefault(
            str(old_data["id"]),
            [],
        ).append((old_path, old_data))
        existing_by_path[old_path.resolve()] = old_data

    keep: set[Path] = set()
    for character in config.get("characters", []):
        parts = []
        folder = folders.get(character.get("folder_id"))
        if folder:
            parts.append(safe_name(folder["name"]))
        subfolder = folders.get(
            character.get("subfolder_id")
        )
        if subfolder:
            parts.append(safe_name(subfolder["name"]))
        directory = (
            paths.character_dir.joinpath(*parts)
            if parts
            else paths.character_dir
        )
        directory.mkdir(parents=True, exist_ok=True)
        desired = directory / (
            f"{safe_name(character.get('name') or character['id'])}"
            ".json"
        )
        candidates = existing_by_id.get(
            str(character["id"]),
            [],
        )
        stable = next(
            (
                old_path
                for old_path, old_data in candidates
                if old_path.parent.resolve() == directory.resolve()
                and str(old_data.get("이름") or old_path.stem)
                == str(character.get("name") or "")
            ),
            None,
        )
        path = stable or desired
        if stable is None:
            serial = 2
            while path.exists():
                occupant = existing_by_path.get(path.resolve())
                if (
                    isinstance(occupant, dict)
                    and str(occupant.get("id"))
                    == str(character["id"])
                ):
                    break
                path = directory / (
                    f"{safe_name(character.get('name') or character['id'])}"
                    f" ({serial}).json"
                )
                serial += 1
        prior = existing_by_path.get(path.resolve())
        if prior is None and candidates:
            prior = candidates[0][1]
        data = dict(prior) if isinstance(prior, dict) else {}
        data.update({
            "id": character["id"],
            "이름": character.get("name", ""),
            "외형": character.get("female", ""),
            "착의": character.get("clothed", ""),
            "네거티브": character.get("negative", ""),
        })
        for field in CHARACTER_ASSET_OPTIONAL_FIELDS:
            if field in character:
                data[field] = copy.deepcopy(character[field])
        if character.get("groups"):
            data["그룹"] = character["groups"]
        else:
            data.pop("그룹", None)
        if character.get("source"):
            data["출처"] = character["source"]
        else:
            data.pop("출처", None)
        try:
            if not (
                path.is_file()
                and existing_by_path.get(path.resolve()) == data
            ):
                operations.atomic_write_json(path, data)
            keep.add(path.resolve())
        except OSError as error:
            operations.log_warning(
                f"캐릭터 파일 저장 실패({path.name}): {error}"
            )

    identifiers = {
        character["id"]
        for character in config.get("characters", [])
    }
    for path, data in (
        (old_path, old_data)
        for rows in existing_by_id.values()
        for old_path, old_data in rows
    ):
        if path.resolve() in keep:
            continue
        if (
            isinstance(data, dict)
            and data.get("id")
            and data["id"] in identifiers
        ):
            operations.recoverable_remove(
                path,
                label="옛위치",
            )


__all__ = [
    "CHARACTER_ASSET_OPTIONAL_FIELDS",
    "CharacterStorageOperations",
    "CharacterStoragePaths",
    "GROUP_ORDER",
    "compose_from_groups",
    "folder_by_name",
    "import_char_files",
    "migrate_legacy",
    "migrate_legacy_selections",
    "read_character_documents",
    "safe_name",
    "sync_chars_to_files",
]
