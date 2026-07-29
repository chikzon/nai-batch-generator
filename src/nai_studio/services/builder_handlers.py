# -*- coding: utf-8 -*-
"""후보사전 로드와 그림체·캐릭터 빌더 저장 요청."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class BuilderHandlerPaths:
    builder_file: Path
    transaction_root: Path


@dataclass(frozen=True)
class BuilderHandlerOperations:
    load_json: Callable[[Path], Any]
    transaction: Callable[[Path], Any]
    compose_ordered: Callable[[dict, list], str]
    save_style_file: Callable[..., Any]
    list_styles: Callable[[dict], list]
    random_character_id: Callable[[], str]
    sync_chars_to_files: Callable[[dict], Any]
    save_config: Callable[[dict], Any]
    warning: Callable[..., Any]


def load_builder(
    paths: BuilderHandlerPaths,
    operations: BuilderHandlerOperations,
) -> dict:
    """사용자 후보사전을 보존하며 대상별 화면 단계만 정리한다."""
    if paths.builder_file.exists():
        try:
            data = operations.load_json(paths.builder_file)
            if isinstance(data, dict):
                characters = list(
                    data.get("캐릭터단계") or []
                )
                base = []
                for step in list(data.get("베이스단계") or []):
                    if (
                        isinstance(step, dict)
                        and step.get("대상") == "캐릭터"
                    ):
                        characters.append(step)
                    else:
                        base.append(step)
                _mark_artist_combo_slots(base)
                data["캐릭터단계"] = characters
                data["베이스단계"] = base
                return data
        except Exception as error:
            operations.warning(
                "후보사전.json 손상: %s",
                error,
            )
    return {"슬롯": [], "풀": {}, "한글": {}}


def _mark_artist_combo_slots(base_steps: list) -> None:
    for step in base_steps:
        slots = (
            step.get("슬롯") or []
            if isinstance(step, dict)
            else []
        )
        for slot in slots:
            if (
                slot.get("라벨") == "작가 조합"
                and not (slot.get("후보") or [])
            ):
                slot.setdefault("조합전용", True)


def handle_style_save(
    server: Any,
    data: dict,
    operations: BuilderHandlerOperations,
) -> dict:
    try:
        request = json.loads(data.get("body"))
        name = (request.get("name") or "").strip()
        if not name:
            return {
                "ok": False,
                "error": "그림체 이름을 입력해주세요.",
            }
        operations.save_style_file(
            name,
            prompt=request.get("prompt", ""),
            groups=request.get("groups"),
            settings=request.get("settings"),
            negative=request.get("negative", ""),
        )
        return {
            "ok": True,
            "styles": operations.list_styles(server.spec),
        }
    except Exception as error:
        return {"ok": False, "error": str(error)}


def handle_norm_save(
    server: Any,
    data: dict,
    paths: BuilderHandlerPaths,
    operations: BuilderHandlerOperations,
) -> dict:
    """규격화 결과를 그림체 또는 캐릭터 자산으로 저장한다."""
    with operations.transaction(paths.transaction_root):
        try:
            request = json.loads(data.get("body"))
            name = (request.get("name") or "").strip()
            groups = request.get("groups") or {}
            if not name:
                return {
                    "ok": False,
                    "error": "이름을 입력해주세요.",
                }
            if request.get("type") == "style":
                return _save_normalized_style(
                    server,
                    operations,
                    request,
                    groups,
                    name,
                )
            return _save_normalized_character(
                server,
                operations,
                request,
                groups,
                name,
            )
        except Exception as error:
            return {"ok": False, "error": str(error)}


def _save_normalized_style(
    server: Any,
    operations: BuilderHandlerOperations,
    request: dict,
    groups: dict,
    name: str,
) -> dict:
    order = [
        group["이름"]
        for group in server.spec.get("그림체_그룹", [])
    ]
    prompt = operations.compose_ordered(groups, order)
    if not prompt:
        return {"ok": False, "error": "내용이 비어 있습니다."}
    operations.save_style_file(name, groups=groups)
    return {
        "ok": True,
        "styles": operations.list_styles(server.spec),
    }


def _save_normalized_character(
    server: Any,
    operations: BuilderHandlerOperations,
    request: dict,
    groups: dict,
    name: str,
) -> dict:
    order = [
        group["이름"]
        for group in server.spec.get("캐릭터_그룹", [])
    ]
    prompt = operations.compose_ordered(groups, order)
    if not prompt:
        prompt = ", ".join(
            value.strip().rstrip(",")
            for value in groups.values()
            if isinstance(value, str) and value.strip()
        )
    if not prompt:
        return {"ok": False, "error": "내용이 비어 있습니다."}
    with server.config_lock:
        server.use_latest_config()
        character = {
            "id": operations.random_character_id(),
            "name": name,
            "female": prompt,
            "clothed": "",
            "negative": request.get("negative", ""),
            "groups": request.get("builder_groups") or groups,
            "enabled": True,
            "folder_id": request.get("folder_id") or None,
            "subfolder_id": request.get("subfolder_id") or None,
        }
        server.cfg.setdefault("characters", []).append(character)
        operations.sync_chars_to_files(server.cfg)
        operations.save_config(server.cfg)
        server.config_revision += 1
        return {
            "ok": True,
            "characters": server.cfg["characters"],
            "revision": server.config_revision,
        }


__all__ = [
    "BuilderHandlerOperations",
    "BuilderHandlerPaths",
    "handle_norm_save",
    "handle_style_save",
    "load_builder",
]
