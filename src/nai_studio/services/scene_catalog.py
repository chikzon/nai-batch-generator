# -*- coding: utf-8 -*-
"""세팅 장면을 UI 조회용 기록으로 투영한다."""

from __future__ import annotations

from typing import Any


def _list_text(value: Any) -> str:
    return ", ".join(value) if isinstance(value, list) else str(value or "")


def _scene_record(
    scene_id: str,
    scene: dict,
    *,
    setting_name: str,
    mode: str,
    normalize_refs: Any,
    normalize_centers: Any,
) -> dict:
    return {
        "id": int(scene_id),
        "name": scene.get("name", ""),
        "setting": setting_name or scene.get("_setting", ""),
        "mode": mode or scene.get("_mode", ""),
        "female_prompt": scene.get("female_prompt", ""),
        "male_prompt": scene.get("male_prompt", ""),
        "partner_prompt": scene.get("partner_prompt", ""),
        "base_tags": scene.get("base_tags", ""),
        "relationship_name": scene.get("relationship_name", scene.get("pair", "")),
        "relationship_tags": scene.get("relationship_tags", ""),
        "female_negative": scene.get("female_negative", ""),
        "male_negative": scene.get("male_negative", ""),
        "partner_negative": scene.get("partner_negative", ""),
        "remove_char_tags": _list_text(scene.get("remove_char_tags")),
        "remove_male_tags": _list_text(scene.get("remove_male_tags")),
        "remove_partner_tags": _list_text(scene.get("remove_partner_tags")),
        "pair": scene.get("pair", ""),
        "negative": scene.get("negative", ""),
        "width": scene.get("width", 832),
        "height": scene.get("height", 1216),
        "use_character_refs": bool(scene.get("use_character_refs", False)),
        "character_refs": normalize_refs(scene.get("character_refs")),
        "char_centers": normalize_centers(scene.get("char_centers")),
    }


def _source(
    cfg: dict,
    setting_name: str,
    *,
    setting_path: Any,
    load_json: Any,
    load_asset_config: Any,
    content_revision: Any,
) -> tuple[dict, str, str]:
    if not setting_name:
        return load_asset_config(cfg)["scenes"], "", ""
    path = setting_path(setting_name)
    if not path:
        raise ValueError(f"'{setting_name}' 세팅을 찾을 수 없습니다.")
    pack = load_json(path)
    return (
        pack.get("씬") or {},
        pack.get("방식", "단독"),
        content_revision(pack),
    )


def scene_catalog(
    cfg: dict,
    scene_ids: list[str],
    setting_name: str,
    *,
    setting_path: Any,
    load_json: Any,
    load_asset_config: Any,
    content_revision: Any,
    normalize_refs: Any,
    normalize_centers: Any,
) -> dict:
    scenes, mode, revision = _source(
        cfg,
        setting_name,
        setting_path=setting_path,
        load_json=load_json,
        load_asset_config=load_asset_config,
        content_revision=content_revision,
    )
    selected = [
        _scene_record(
            scene_id,
            scenes[scene_id],
            setting_name=setting_name,
            mode=mode,
            normalize_refs=normalize_refs,
            normalize_centers=normalize_centers,
        )
        for scene_id in scene_ids
        if scene_id in scenes
    ]
    char_refs = [
        {
            "id": str(ref.get("id") or ""),
            "name": str(ref.get("name") or ref.get("id") or "무제"),
        }
        for ref in (cfg.get("char_refs") or [])
        if isinstance(ref, dict) and ref.get("id")
    ]
    return {
        "ok": True,
        "scenes": selected,
        "revision": revision,
        "char_refs": char_refs,
    }


__all__ = ["scene_catalog"]
