# -*- coding: utf-8 -*-
"""세팅·장면 편집과 실제 전송값 미리보기 POST 라우트."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from typing import Any

from src.nai_studio.services.scene_preview import scene_preview_payload


@dataclass(frozen=True)
class SettingsPostOperations:
    duplicate_scene_undo: Any
    duplicate_scene: Any
    scene_save: Any
    option_item: Any
    role_save: Any
    sceneset_save: Any
    load_asset_config: Any
    setting_state: Any
    cast_members: Any
    slot_prompt: Any
    character_run: Any
    build_scene: Any
    reference_config: Any
    scene_people: Any
    seed_for: Any
    load_state: Any
    normalize_prompt: Any
    join_tags: Any
    token_count: Any
    save_scenes: Any
    new_setting: Any
    add_set: Any
    save_meta: Any
    renumber: Any
    delete_setting: Any
    duplicate_group: Any
    log_warning: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _scene_edit(
    request: Any,
    operations: SettingsPostOperations,
    body: bytes,
) -> bool:
    data = _json_body(body)
    if request.path.startswith("/api/scene_duplicate_undo"):
        result = operations.duplicate_scene_undo(
            data.get("setting", ""), data.get("id", ""),
            data.get("scene_sha256", ""), data.get("expect_revision", ""),
        )
    elif request.path.startswith("/api/scene_duplicate"):
        result = operations.duplicate_scene(
            data.get("setting", ""), data.get("id", ""),
            data.get("expect_revision", ""),
        )
    elif request.path.startswith("/api/scene_save"):
        result = operations.scene_save(body)
    elif request.path.startswith("/api/option_item"):
        result = operations.option_item(body)
    elif request.path.startswith("/api/role_save"):
        result = operations.role_save(body)
    elif request.path.startswith("/api/sceneset_save"):
        result = operations.sceneset_save(body)
    else:
        return False
    request._json(result)
    return True


def _setting_builder(
    request: Any,
    operations: SettingsPostOperations,
    body: bytes,
) -> bool:
    data = _json_body(body)
    if request.path.startswith("/api/sb_new"):
        result = operations.new_setting(
            data.get("name", ""), data.get("mode", "단독"), data.get("stages")
        )
    elif request.path.startswith("/api/sb_addset"):
        result = operations.add_set(
            data.get("name", ""), data.get("label", ""),
            data.get("category", ""), int(data.get("width") or 832),
            int(data.get("height") or 1216), data.get("stages"),
        )
    elif request.path.startswith("/api/sb_meta"):
        result = operations.save_meta(
            data.get("name", ""), data.get("patch") or {}
        )
    elif request.path.startswith("/api/sb_renumber"):
        result = operations.renumber(data.get("name", ""), data.get("start"))
    elif request.path.startswith("/api/sb_del"):
        result = operations.delete_setting(data.get("name", ""))
    else:
        return False
    request._json(result)
    return True


def _setting_duplicate(
    request: Any,
    operations: SettingsPostOperations,
    body: bytes,
) -> None:
    data = _json_body(body)
    try:
        scene_id = int(data.get("id"))
    except (TypeError, ValueError):
        request._json({
            "ok": False,
            "error": "복제할 세트의 씬 번호(id)가 필요합니다.",
        })
        return
    request._json(operations.duplicate_group(data.get("name", ""), scene_id))


def handle_settings_post(
    request: Any,
    application: Any,
    operations: SettingsPostOperations,
    body: bytes,
) -> bool:
    try:
        if _scene_edit(request, operations, body):
            pass
        elif request.path.startswith("/api/scene_preview"):
            request._json(scene_preview_payload(
                application, operations, int(_json_body(body).get("num"))
            ))
        elif request.path.startswith("/api/scenes_save"):
            request._json({
                "ok": True,
                "scenes": operations.save_scenes(
                    _json_body(body).get("scenes") or []
                ),
            })
        elif _setting_builder(request, operations, body):
            pass
        elif request.path.startswith("/api/setting_dup"):
            _setting_duplicate(request, operations, body)
        else:
            return False
    except Exception as exc:
        if request.path.startswith("/api/scene_preview"):
            operations.log_warning(f"씬 미리보기 실패: {traceback.format_exc()}")
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["SettingsPostOperations", "handle_settings_post"]
