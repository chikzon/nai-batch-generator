# -*- coding: utf-8 -*-
"""프로젝트 상속·전체 설정·장면 편집 저장 요청을 조정한다."""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class SettingsHandlerOperations:
    """기존 project·config·setting 저장 서비스를 주입한다."""

    config_transaction: Callable[[], Any]
    setting_transaction: Callable[[], Any]
    default_config: Mapping[str, Any]
    normalize_projects: Callable[[Any], list]
    normalize_link: Callable[[Any], dict]
    project_by_id: Callable[[list, str], dict | None]
    generation_blueprint: Callable[[dict], dict]
    blueprint_common: Callable[[dict], dict]
    fingerprint_blueprint: Callable[[dict], str]
    resolve_inheritance: Callable[[dict, list, dict], dict]
    materialize_blueprint: Callable[[dict, dict], dict]
    save_config: Callable[[dict], Any]
    validate_config_value: Callable[[str, Any, Any], tuple]
    sync_chars_to_files: Callable[[dict], Any]
    sync_blueprint_overrides: Callable[[dict], Any]
    delete_char_files: Callable[[dict, set], Any]
    setting_path: Callable[[str], Path | None]
    load_json: Callable[[Path], dict]
    setting_revision: Callable[[dict], str]
    normalize_resolution: Callable[[Any], int]
    normalize_centers: Callable[[Any], list]
    normalize_reference_ids: Callable[[Any], list]
    atomic_write_json: Callable[[Path, dict], Any]
    warning: Callable[..., Any]
    info: Callable[..., Any]


def handle_blueprint_project(
    server: Any,
    data: dict,
    operations: SettingsHandlerOperations,
) -> dict:
    """프로젝트 공통값 생성·갱신·연결·수락·연결 해제를 저장한다."""
    with operations.config_transaction():
        try:
            request = json.loads(data.get("body") or b"{}")
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "잘못된 프로젝트 요청입니다.",
            }
        action = str(request.get("action") or "").strip().lower()
        if action not in (
            "create",
            "update",
            "activate",
            "accept",
            "disconnect",
        ):
            return {
                "ok": False,
                "error": "알 수 없는 프로젝트 작업입니다.",
            }
        with server.config_lock:
            config = server.latest_config_from_disk()
            projects = operations.normalize_projects(
                config.get("blueprint_projects") or []
            )
            link = operations.normalize_link(
                config.get("blueprint_inheritance") or {}
            )
            project_id = str(
                request.get("id")
                or link.get("project_id")
                or ""
            )
            current = operations.generation_blueprint(config)
            result = _apply_project_action(
                operations,
                action,
                request,
                config,
                projects,
                link,
                project_id,
                current,
            )
            if isinstance(result, dict) and result.get("ok") is False:
                return result
            config, project_id = result
            operations.save_config(config)
            server.cfg.clear()
            server.cfg.update(config)
            server.config_revision += 1
            snapshot = server.snapshot_blueprint()
            snapshot.update({
                "revision": server.config_revision,
                "project_id": project_id,
            })
            return snapshot


def _apply_project_action(
    operations: SettingsHandlerOperations,
    action: str,
    request: dict,
    config: dict,
    projects: list,
    link: dict,
    project_id: str,
    current: dict,
) -> tuple[dict, str] | dict:
    if action in ("create", "update"):
        return _store_project(
            operations,
            action,
            request,
            config,
            projects,
            project_id,
            current,
        )
    if action == "activate":
        return _activate_project(
            operations,
            config,
            projects,
            project_id,
            current,
        )
    if action == "accept":
        return _accept_project(
            operations,
            request,
            config,
            projects,
            link,
            project_id,
            current,
        )
    config["blueprint_inheritance"] = {}
    return config, project_id


def _store_project(
    operations: SettingsHandlerOperations,
    action: str,
    request: dict,
    config: dict,
    projects: list,
    project_id: str,
    current: dict,
) -> tuple[dict, str] | dict:
    name = str(request.get("name") or "").strip()
    if not name or len(name) > 120:
        return {
            "ok": False,
            "error": "프로젝트 이름을 1~120자로 적어주세요.",
        }
    if action == "create":
        project_id = f"project-{uuid.uuid4().hex}"
    existing = operations.project_by_id(projects, project_id)
    if action == "update" and existing is None:
        return {
            "ok": False,
            "error": "갱신할 프로젝트를 찾지 못했습니다.",
        }
    common = operations.blueprint_common(current)
    record = {
        "id": project_id,
        "name": name,
        "blueprint": common,
        "fingerprint": operations.fingerprint_blueprint(common),
        "updated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    }
    projects = [
        item
        for item in projects
        if item.get("id") != project_id
    ] + [record]
    config["blueprint_projects"] = operations.normalize_projects(
        projects
    )
    return config, project_id


def _activate_project(
    operations: SettingsHandlerOperations,
    config: dict,
    projects: list,
    project_id: str,
    current: dict,
) -> tuple[dict, str] | dict:
    project = operations.project_by_id(projects, project_id)
    if project is None:
        return {
            "ok": False,
            "error": "연결할 프로젝트를 찾지 못했습니다.",
        }
    accepted = operations.blueprint_common(project["blueprint"])
    link = {
        "schema": "nai-blueprint-inheritance/v1",
        "project_id": project_id,
        "accepted_fingerprint": project["fingerprint"],
        "accepted_blueprint": accepted,
        "local_overrides": {},
    }
    resolution = operations.resolve_inheritance(
        current,
        projects,
        link,
    )
    config = operations.materialize_blueprint(
        config,
        resolution["blueprint"],
    )
    config["blueprint_projects"] = projects
    config["blueprint_inheritance"] = operations.normalize_link(link)
    return config, project_id


def _accept_project(
    operations: SettingsHandlerOperations,
    request: dict,
    config: dict,
    projects: list,
    link: dict,
    project_id: str,
    current: dict,
) -> tuple[dict, str] | dict:
    if not link:
        return {
            "ok": False,
            "error": "연결된 프로젝트가 없습니다.",
        }
    project = operations.project_by_id(
        projects,
        link["project_id"],
    )
    if project is None:
        return {
            "ok": False,
            "error": "프로젝트 원본을 찾지 못했습니다.",
        }
    expected = str(request.get("fingerprint") or "")
    if (
        expected
        and expected != str(project.get("fingerprint") or "")
    ):
        return {
            "ok": False,
            "conflict": True,
            "error": (
                "확인 뒤 프로젝트 공통값이 다시 바뀌었습니다. "
                "내용을 다시 확인해 주세요."
            ),
        }
    new_link = copy.deepcopy(link)
    new_link["accepted_blueprint"] = operations.blueprint_common(
        project["blueprint"]
    )
    new_link["accepted_fingerprint"] = project["fingerprint"]
    resolution = operations.resolve_inheritance(
        current,
        projects,
        new_link,
    )
    config = operations.materialize_blueprint(
        config,
        resolution["blueprint"],
    )
    config["blueprint_projects"] = projects
    config["blueprint_inheritance"] = operations.normalize_link(
        new_link
    )
    return config, project_id


def handle_save(
    server: Any,
    data: dict,
    operations: SettingsHandlerOperations,
) -> dict:
    """허용된 설정만 검증해 디스크 최신판 위에 병합한다."""
    with operations.config_transaction():
        try:
            changes = json.loads(data.get("body"))
        except json.JSONDecodeError:
            return {"ok": False, "error": "잘못된 데이터"}
        revision = changes.pop("_revision", None)
        base_values = changes.pop("_base", {})
        if not isinstance(base_values, dict):
            base_values = {}
        with server.config_lock:
            if _stale_revision(server, revision):
                return {
                    "ok": False,
                    "conflict": True,
                    "revision": server.config_revision,
                    "error": (
                        "다른 화면에서 설정이 먼저 변경됐습니다. "
                        "새로고침 후 다시 시도하세요."
                    ),
                }
            local_before = dict(server.cfg)
            merged = server.latest_config_from_disk()
            allowed = {
                key
                for key in operations.default_config
                if not key.startswith("_")
            }
            allowed |= {"booru_keys"}
            allowed -= {"male_prompt"}
            external_changes = sorted(
                key
                for key in allowed
                if key not in changes
                and local_before.get(key) != merged.get(key)
            )
            conflicts = _config_conflicts(
                changes,
                base_values,
                merged,
                allowed,
            )
            if conflicts:
                server.cfg.clear()
                server.cfg.update(merged)
                server.config_revision += 1
                return {
                    "ok": False,
                    "conflict": True,
                    "conflict_keys": conflicts,
                    "revision": server.config_revision,
                    "error": (
                        "다른 실행본이 같은 설정을 먼저 변경했습니다. "
                        "새로고침 후 값을 확인하고 다시 시도하세요."
                    ),
                }
            server.cfg.clear()
            server.cfg.update(merged)
            old_ids = {
                character.get("id")
                for character in server.cfg.get("characters", [])
            }
            accepted, rejected, fixed_values = _apply_config_changes(
                operations,
                server.cfg,
                changes,
                allowed,
            )
            new_ids = {
                character.get("id")
                for character in server.cfg.get("characters", [])
            }
            operations.sync_chars_to_files(server.cfg)
            operations.sync_blueprint_overrides(server.cfg)
            operations.save_config(server.cfg)
            operations.delete_char_files(
                server.cfg,
                old_ids - new_ids,
            )
            server.config_revision += 1
            _log_config_adjustments(
                operations,
                rejected,
                fixed_values,
            )
            return {
                "ok": True,
                "accepted": accepted,
                "rejected": rejected,
                "fixed": fixed_values,
                "revision": server.config_revision,
                "external_changes": external_changes,
            }


def _stale_revision(server: Any, revision: Any) -> bool:
    if revision is None:
        return False
    try:
        return int(revision) != server.config_revision
    except (TypeError, ValueError):
        return True


def _config_conflicts(
    changes: dict,
    base_values: dict,
    merged: dict,
    allowed: set,
) -> list:
    return sorted(
        key
        for key, incoming in changes.items()
        if key in allowed
        and key in base_values
        and merged.get(key) != base_values.get(key)
        and incoming != merged.get(key)
    )


def _apply_config_changes(
    operations: SettingsHandlerOperations,
    config: dict,
    changes: dict,
    allowed: set,
) -> tuple[list, list, dict]:
    accepted = []
    rejected = []
    fixed_values = {}
    for key, value in changes.items():
        if key not in allowed:
            if not key.startswith("_"):
                rejected.append(key)
            continue
        valid, used, fixes = operations.validate_config_value(
            key,
            value,
            config.get(key),
        )
        fixed_values.update(fixes)
        if not valid:
            rejected.append(key)
            continue
        config[key] = used
        accepted.append(key)
    return accepted, rejected, fixed_values


def _log_config_adjustments(
    operations: SettingsHandlerOperations,
    rejected: list,
    fixed_values: dict,
) -> None:
    if rejected:
        operations.warning(
            "설정 저장에서 잘못된 키/값을 거절함: %s",
            ", ".join(sorted(rejected)),
        )
    if fixed_values:
        operations.info(
            "설정값을 허용 범위로 맞췄습니다: %s",
            fixed_values,
        )


def handle_scene_save(
    server: Any,
    data: dict,
    operations: SettingsHandlerOperations,
) -> dict:
    """한 세팅의 씬 내부 값과 되돌리기용 이전 값을 원자 저장한다."""
    with operations.setting_transaction():
        try:
            request = json.loads(data.get("body"))
            setting = str(request.get("setting") or "").strip()
            if not setting:
                return {
                    "ok": False,
                    "error": "수정할 세팅 이름이 없습니다.",
                }
            path = operations.setting_path(setting)
            if not path:
                return {
                    "ok": False,
                    "error": f"'{setting}' 세팅을 찾을 수 없습니다.",
                }
            updates = request.get("updates") or {}
            if not isinstance(updates, dict):
                return {
                    "ok": False,
                    "error": "씬 수정 내용의 형식이 잘못되었습니다.",
                }
            pack = operations.load_json(path)
            revision = operations.setting_revision(pack)
            expected = str(request.get("expect_revision") or "")
            if expected and expected != revision:
                return {
                    "ok": False,
                    "conflict": True,
                    "error": (
                        "다른 저장이 먼저 반영되어 되돌리지 않았습니다. "
                        "다시 열어 확인해주세요."
                    ),
                }
            prepared, before = _prepare_scene_updates(
                server,
                operations,
                pack,
                updates,
            )
            changed_scenes, changed_fields = _apply_scene_updates(
                pack,
                prepared,
            )
            if changed_fields:
                operations.atomic_write_json(path, pack)
            after_revision = operations.setting_revision(pack)
            return {
                "ok": True,
                "updated": changed_scenes,
                "fields": changed_fields,
                "setting": setting,
                "before": before,
                "revision": after_revision,
            }
        except Exception as error:
            return {"ok": False, "error": str(error)}


_SCENE_FIELDS = (
    "female_prompt",
    "male_prompt",
    "partner_prompt",
    "base_tags",
    "relationship_name",
    "relationship_tags",
    "female_negative",
    "male_negative",
    "partner_negative",
    "remove_char_tags",
    "remove_male_tags",
    "remove_partner_tags",
    "negative",
    "width",
    "height",
    "char_centers",
    "use_character_refs",
    "character_refs",
)
_TAG_LIST_FIELDS = (
    "remove_char_tags",
    "remove_male_tags",
    "remove_partner_tags",
)


def _prepare_scene_updates(
    server: Any,
    operations: SettingsHandlerOperations,
    pack: dict,
    updates: dict,
) -> tuple[dict, dict]:
    valid_reference_ids = {
        str(reference.get("id") or "")
        for reference in (server.cfg.get("char_refs") or [])
        if isinstance(reference, dict) and reference.get("id")
    }
    scenes = pack.get("씬") or {}
    prepared = {}
    before = {}
    for scene_id, fields in updates.items():
        scene_id = str(scene_id)
        scene = scenes.get(scene_id)
        if not isinstance(scene, dict) or not isinstance(fields, dict):
            continue
        clean, old = _prepare_scene_fields(
            operations,
            scene,
            fields,
            valid_reference_ids,
        )
        if clean:
            prepared[scene_id] = clean
            before[scene_id] = old
    return prepared, before


def _prepare_scene_fields(
    operations: SettingsHandlerOperations,
    scene: dict,
    fields: dict,
    valid_reference_ids: set,
) -> tuple[dict, dict]:
    clean = {}
    old = {}
    for key in _SCENE_FIELDS:
        if key not in fields:
            continue
        value = _normalize_scene_value(
            operations,
            key,
            fields[key],
            valid_reference_ids,
        )
        clean[key] = value
        old[key] = _previous_scene_value(
            operations,
            scene,
            key,
            value,
        )
    return clean, old


def _normalize_scene_value(
    operations: SettingsHandlerOperations,
    key: str,
    value: Any,
    valid_reference_ids: set,
) -> Any:
    if key in ("width", "height"):
        return operations.normalize_resolution(value)
    if key == "char_centers":
        return operations.normalize_centers(value)
    if key == "character_refs":
        references = operations.normalize_reference_ids(value)
        unknown = [
            reference
            for reference in references
            if reference and reference not in valid_reference_ids
        ]
        if unknown:
            raise ValueError(
                f"찾을 수 없는 캐릭터 레퍼런스입니다: {unknown[0]}"
            )
        return references
    if key == "use_character_refs":
        if not isinstance(value, bool):
            raise ValueError(
                "씬 Reference 사용 여부는 true/false여야 합니다."
            )
        return value
    if key in _TAG_LIST_FIELDS:
        if isinstance(value, str):
            return [
                item.strip()
                for item in re.split(r"[,\n]", value)
                if item.strip()
            ]
        if isinstance(value, list):
            return [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]
        raise ValueError(f"{key} 값은 문자열 또는 목록이어야 합니다.")
    if not isinstance(value, str):
        raise ValueError(f"{key} 값은 문자열이어야 합니다.")
    return value


def _previous_scene_value(
    operations: SettingsHandlerOperations,
    scene: dict,
    key: str,
    value: Any,
) -> Any:
    if key == "char_centers":
        return operations.normalize_centers(scene.get(key))
    if key == "character_refs":
        return operations.normalize_reference_ids(
            scene.get("character_refs")
        )
    if key == "use_character_refs":
        return bool(scene.get(key, False))
    if key in _TAG_LIST_FIELDS:
        previous = scene.get(key) or []
        if isinstance(previous, str):
            return [
                item.strip()
                for item in re.split(r"[,\n]", previous)
                if item.strip()
            ]
        return [
            str(item).strip()
            for item in previous
            if str(item).strip()
        ]
    return scene.get(
        key,
        "" if key not in ("width", "height") else value,
    )


def _apply_scene_updates(
    pack: dict,
    prepared: dict,
) -> tuple[int, int]:
    scenes = pack.get("씬") or {}
    changed_scenes = 0
    changed_fields = 0
    for scene_id, fields in prepared.items():
        scene_changed = False
        for key, value in fields.items():
            empty = (
                []
                if key in ("char_centers", "character_refs")
                or key in _TAG_LIST_FIELDS
                else False if key == "use_character_refs" else ""
            )
            if scenes[scene_id].get(key, empty) != value:
                scenes[scene_id][key] = value
                changed_fields += 1
                scene_changed = True
        changed_scenes += int(scene_changed)
    return changed_scenes, changed_fields


def normalize_scene_rows(scenes: Any, *, safe_name: Callable[[Any], str]) -> list:
    """씬 모드 저장 목록을 id 충돌 없이 저장 형태로 정규화한다."""
    out, used_ids = [], set()
    for s in scenes or []:
        root_id = safe_name(str(s.get("id") or s.get("name") or f"scene{len(out)+1}"))
        sid, serial = root_id, 2
        while sid.casefold() in used_ids:
            sid = f"{root_id}-{serial}"
            serial += 1
        used_ids.add(sid.casefold())
        out.append({
            "id": sid,
            "name": (s.get("name") or "").strip() or "이름 없음",
            "prompt": s.get("prompt", ""),
            # 씬이 **인물별 프롬프트**도 가질 수 있다 (배경·구도는 prompt, 인물은 여기).
            # 씬 프롬프트에 인물 묘사를 적으면 base 로 들어가 왼쪽 캐릭터와 뭉개진다 —
            # NAIS3 에서 "씬에 여자 프롬을 넣었더니 베이스의 여자와 합쳐졌다" 는 그 문제다.
            "char1": s.get("char1", ""),
            "char2": s.get("char2", ""),
            "char1_neg": s.get("char1_neg", ""),
            "char2_neg": s.get("char2_neg", ""),
            "negative": s.get("negative", ""),
            "width": int(s.get("width") or 832),
            "height": int(s.get("height") or 1216),
            "reserve": max(0, int(s.get("reserve") or 0)),   # 0 = 안 뽑음
            # 해상도를 직접 입력으로 두겠다는 표시 (프리셋과 값이 같아도 칸을 보여 준다)
            "custom_res": bool(s.get("custom_res")),
        })
    return out


__all__ = [
    "SettingsHandlerOperations",
    "handle_blueprint_project",
    "handle_save",
    "handle_scene_save",
    "normalize_scene_rows",
]
