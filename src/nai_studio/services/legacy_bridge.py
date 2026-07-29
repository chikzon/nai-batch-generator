# -*- coding: utf-8 -*-
"""기존 사용자 자료를 바꾸지 않고 공통 도메인 계약으로 해석한다.

이 모듈은 마이그레이션 도구가 아니다. 현재 설정·그림체·캐릭터·세팅 레코드의
사본을 증거와 지식 자산으로 투영한다. 따라서 옛 파일을 자동 저장하거나, prompt를
분해·요약하거나, 모르는 필드를 버리지 않는다.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from src.nai_studio.domain.evidence import canonical_evidence
from src.nai_studio.domain.evaluation import canonical_evaluation
from src.nai_studio.domain.knowledge import canonical_knowledge_asset
from src.nai_studio.domain.restoration import (
    canonical_restore_queue,
    enqueue_restore_items,
)
from src.nai_studio.domain.sequence import canonical_sequence_plan


_STYLE_SETTING_KEYS = (
    "model",
    "cfg_scale",
    "cfg_rescale",
    "steps",
    "sampler",
    "scheduler",
    "variety",
    "width",
    "height",
    "uc_preset",
    "quality_toggle",
    "smea",
    "smea_dyn",
    "dynamic_thresholding",
    "uncond_scale",
    "controlnet_strength",
    "prefer_brownian",
    "deliberate_euler_ancestral_bug",
    "legacy_v3_extend",
)


def _record(value: Any) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _first(record: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return deepcopy(record[key])
    return deepcopy(default)


def _style_settings(record: Mapping[str, Any]) -> dict:
    raw = _first(record, "generation_settings", "settings", "params", default={})
    settings = _record(raw)
    # 현재 설정 화면의 평평한 키도 읽되 기존 params/settings를 덮지 않는다.
    for key in _STYLE_SETTING_KEYS:
        if key not in settings and key in record:
            settings[key] = deepcopy(record[key])
    return settings


def evidence_from_image_record(
    value: Mapping[str, Any],
    *,
    evaluation: Mapping[str, Any] | None = None,
) -> dict:
    """단건 이미지·수집 결과·생성 결과를 같은 증거 레코드로 투영한다."""
    record = _record(value)
    images = deepcopy(record.get("images") or [])
    image = {
        "refs": images,
        "content_sha256": str(record.get("content_sha256") or ""),
        "filename": str(
            record.get("filename")
            or record.get("title")
            or record.get("name")
            or ""
        ),
    }
    source = {
        "label": str(record.get("source") or ""),
        "url": str(record.get("url") or ""),
        "posted_at": str(record.get("posted_at") or ""),
    }
    actual_generation = {
        "base": str(_first(record, "base", "prompt", "프롬프트")),
        "negative": str(
            _first(record, "negative_full", "negative", "네거티브")
        ),
        "characters": deepcopy(record.get("characters") or []),
        "settings": _style_settings(record),
    }
    return canonical_evidence({
        "kind": "generation-record",
        "image": image,
        "source": source,
        "raw_metadata": deepcopy(
            _first(record, "metadata_raw", "raw_metadata", default=None)
        ),
        "actual_generation": actual_generation,
        "evaluation": _record(evaluation or record.get("evaluation")),
    })


def style_asset_from_record(
    value: Mapping[str, Any],
    *,
    evidence_refs: Iterable[str] = (),
    lifecycle: str = "candidate",
) -> dict:
    """베이스·네거티브·생성 설정을 나누지 않는 그림체 자산."""
    record = _record(value)
    refs = list(evidence_refs)
    refs.extend(
        ref for ref in (record.get("evidence_refs") or [])
        if isinstance(ref, str) and ref not in refs
    )
    return canonical_knowledge_asset({
        "kind": "style",
        "lifecycle": lifecycle,
        "name": str(_first(record, "name", "title", "이름")),
        "evidence_refs": refs,
        "content": {
            "base": str(
                _first(record, "base", "prompt", "프롬프트", "combo")
            ),
            "negative": str(
                _first(record, "negative", "네거티브")
            ),
            "generation_settings": _style_settings(record),
        },
    })


def character_asset_from_record(
    value: Mapping[str, Any],
    *,
    evidence_refs: Iterable[str] = (),
    lifecycle: str = "candidate",
) -> dict:
    """캐릭터 원문과 네거티브·변형·Reference·Vibe를 한 자산으로 보존한다."""
    record = _record(value)
    refs = list(evidence_refs)
    refs.extend(
        ref for ref in (record.get("evidence_refs") or [])
        if isinstance(ref, str) and ref not in refs
    )
    return canonical_knowledge_asset({
        "kind": "character",
        "lifecycle": lifecycle,
        "name": str(_first(record, "name", "이름")),
        "evidence_refs": refs,
        "content": {
            "prompt": str(
                _first(record, "prompt", "female", "appearance", "외형")
            ),
            "clothed": str(
                _first(record, "clothed", "outfit", "착의")
            ),
            "negative": str(_first(record, "negative", "네거티브")),
            "variants": deepcopy(
                record.get("variants")
                if isinstance(record.get("variants"), list)
                else ([record["variant"]] if record.get("variant") else [])
            ),
            "reference_refs": deepcopy(
                _first(record, "reference_refs", "reference_ids", default=[])
            ),
            "vibe_refs": deepcopy(
                _first(record, "vibe_refs", "vibe_ids", default=[])
            ),
        },
    })


def setting_asset_from_record(
    value: Mapping[str, Any],
    *,
    evidence_refs: Iterable[str] = (),
    lifecycle: str = "candidate",
) -> dict:
    """기존 세팅 파일을 장면·관계·위치·옵션 지식으로 읽는다."""
    record = _record(value)
    scene_map = _first(record, "scenes", "씬", default={})
    scenes = (
        deepcopy(list(scene_map.values()))
        if isinstance(scene_map, Mapping)
        else deepcopy(scene_map if isinstance(scene_map, list) else [])
    )
    content = {
        "scenes": scenes,
        "relationships": deepcopy(
            _first(record, "relationships", "관계", default=[])
        ),
        "positions": deepcopy(
            _first(record, "positions", "위치", "char_centers", default=[])
        ),
        "options": _record(
            _first(record, "options", "옵션", default={})
        ),
        "steps": deepcopy(
            _first(record, "steps", "단계", default=[])
        ),
        "families": deepcopy(
            _first(record, "families", "계열", default=[])
        ),
    }
    return canonical_knowledge_asset({
        "kind": "setting-material",
        "lifecycle": lifecycle,
        "name": str(_first(record, "name", "이름")),
        "evidence_refs": list(evidence_refs),
        "content": content,
    })


def knowledge_assets_from_config(value: Mapping[str, Any]) -> list[dict]:
    """현재 화면값에서 즉시 생성에 쓰이는 그림체·캐릭터 자산 사본을 만든다."""
    cfg = _record(value)
    assets = []
    style_record = {
        "name": cfg.get("style_name") or "현재 그림체",
        "base": cfg.get("base_prompt") or "",
        "negative": cfg.get("negative_prompt") or "",
        "settings": {
            key: deepcopy(cfg[key])
            for key in _STYLE_SETTING_KEYS
            if key in cfg
        },
    }
    if style_record["base"] or style_record["negative"] or style_record["settings"]:
        assets.append(style_asset_from_record(
            style_record,
            lifecycle="confirmed",
        ))
    for character in cfg.get("characters") or []:
        if isinstance(character, Mapping):
            assets.append(character_asset_from_record(
                character,
                lifecycle="confirmed",
            ))
    return assets


def evaluations_from_picks(
    value: Mapping[str, Any],
    *,
    paths: Iterable[str] | None = None,
) -> list[dict]:
    """기존 선별·별점·ELO 장부를 결과별 공통 평가 사본으로 읽는다."""
    picks = _record(value)
    wanted = (
        [str(path).replace("\\", "/") for path in paths]
        if paths is not None
        else []
    )
    if not wanted:
        all_paths = []
        for key in ("picked", "fav"):
            all_paths.extend(str(path).replace("\\", "/")
                             for path in (picks.get(key) or []))
        for key in ("ranks", "ratings", "elo", "elo_matches", "tags"):
            all_paths.extend(str(path).replace("\\", "/")
                             for path in (picks.get(key) or {}))
        for group in (picks.get("folders") or {}).values():
            all_paths.extend(str(path).replace("\\", "/")
                             for path in (group or []))
        wanted = list(dict.fromkeys(path for path in all_paths if path))
    picked = set(picks.get("picked") or [])
    favorites = set(picks.get("fav") or [])
    folders = {
        str(name): {str(path).replace("\\", "/") for path in (members or [])}
        for name, members in (picks.get("folders") or {}).items()
    }
    ratings = picks.get("ratings") or {}
    elo = picks.get("elo") or {}
    matches = picks.get("elo_matches") or {}
    tags = picks.get("tags") or {}
    evaluations = []
    for path in dict.fromkeys(wanted):
        boards = [name for name, members in folders.items() if path in members]
        evaluations.append(canonical_evaluation({
            "subject": {"kind": "generation-result", "path": path},
            "favorite": path in favorites,
            "rating": ratings.get(path),
            "tags": deepcopy(tags.get(path) or []),
            "fixed_board": {
                "member": path in picked or bool(boards),
                "boards": boards,
            },
            "blind": {
                "enabled": path in elo or path in matches,
                "revealed": True,
                "matches": int(matches.get(path) or 0),
            },
            "elo": {
                "rating": float(elo.get(path, 1500.0)),
                "matches": int(matches.get(path) or 0),
                # 옛 장부에는 승/패 분리가 없다. 추측하지 않고 0으로 둔다.
                "wins": 0,
                "losses": 0,
            },
            "result_refs": [f"result:{path}"],
        }))
    return evaluations


def restoration_queue_from_collection(value: Mapping[str, Any]) -> dict:
    """기존 공개자료 수집 진행 장부를 공통 설계도 복원 큐로 해석한다."""
    state = _record(value)
    articles = state.get("articles") if isinstance(
        state.get("articles"), Mapping) else {}
    failures = state.get("failures") if isinstance(
        state.get("failures"), Mapping) else {}
    queue = canonical_restore_queue({
        "source": {
            "kind": "public-collection",
            "keyword": str(state.get("keyword") or ""),
        },
        "cursor": deepcopy(state.get("cursor")),
        "status": str(state.get("status") or "idle"),
        "date_range": _record(state.get("date_range")),
        "metadata": {
            "legacy_schema": str(state.get("schema") or ""),
            "stage": str(state.get("stage") or ""),
        },
        "items": [],
    })
    items = []
    for index, url in enumerate(state.get("queue") or []):
        url = str(url or "")
        article = articles.get(url) if isinstance(articles.get(url), Mapping) else {}
        failure = failures.get(url) if isinstance(failures.get(url), Mapping) else {}
        if failure:
            recognition = {
                "status": "failed",
                "attempts": int(failure.get("attempts") or 0),
                "error": str(failure.get("error") or ""),
                "history": deepcopy(failure.get("history") or []),
            }
        elif article:
            recognition = {
                "status": (
                    "recognized"
                    if int(article.get("metadata_images") or 0) > 0
                    else "unrecognized"
                ),
                "attempts": max(1, int(article.get("attempts") or 1)),
                "history": [],
            }
        else:
            recognition = {"status": "pending", "attempts": 0, "history": []}
        items.append({
            "source": {
                "kind": "public-post",
                "url": url,
                "post_url": url,
                "title": str(
                    article.get("title") or failure.get("title") or ""),
            },
            "images": deepcopy(article.get("image_urls") or []),
            "content_hash": str(
                article.get("digest") or article.get("content_hash") or ""),
            "cursor": index,
            "date": deepcopy(
                article.get("posted_at") or article.get("updated_at")),
            "recognition": recognition,
            "result": {
                "evidence_refs": deepcopy(article.get("evidence_refs") or []),
            },
        })
    return enqueue_restore_items(queue, items)


def sequence_plan_from_setting(value: Mapping[str, Any]) -> dict:
    """현재 세팅의 장면 순서를 Storyteller/Sequence 공통 계획으로 투영한다."""
    wrapper = _record(value)
    data = _record(wrapper.get("data") or wrapper)
    scenes = data.get("씬") if isinstance(data.get("씬"), Mapping) else {}

    def scene_order(item):
        key = str(item[0])
        return (0, int(key)) if key.isdigit() else (1, key)

    steps = []
    for scene_id, raw_scene in sorted(scenes.items(), key=scene_order):
        scene = _record(raw_scene)
        resolution = {}
        if scene.get("width") is not None:
            resolution["width"] = deepcopy(scene["width"])
        if scene.get("height") is not None:
            resolution["height"] = deepcopy(scene["height"])
        steps.append({
            "id": f"scene-{scene_id}",
            "name": str(scene.get("name") or scene_id),
            "include": {
                key: deepcopy(scene[key])
                for key in (
                    "prompt", "female_prompt", "male_prompt",
                    "character_prompt", "tags",
                )
                if key in scene
            },
            "exclude": deepcopy(
                _first(scene, "negative", "negative_prompt", default=None)
            ),
            "rating": deepcopy(scene.get("rating")),
            "resolution": resolution,
            "seed_policy": _record(scene.get("seed_policy")) or {
                "mode": "inherit"
            },
            "character_overrides": _record(
                _first(scene, "character_overrides", "캐릭터", default={})
            ),
            "style_overrides": _record(scene.get("style_overrides")),
            "background": deepcopy(scene.get("background")),
            "outfit": deepcopy(scene.get("outfit")),
            "carry": _record(scene.get("carry")),
            "vibe_continuity": _record(
                scene.get("vibe_continuity")) or {"source": "none"},
            "repeat": int(scene.get("repeat") or 1),
            "legacy_scene": scene,
        })
    options = _record(data.get("옵션"))
    return canonical_sequence_plan({
        "name": str(
            data.get("이름") or wrapper.get("name") or "세팅 순서"),
        "progression": str(options.get("progression") or "once"),
        "freeze": {
            "style": bool(options.get("freeze_style")),
            "characters": bool(options.get("freeze_characters")),
            "wildcards": bool(options.get("freeze_wildcards")),
        },
        "repeat": int(options.get("sequence_repeat") or 1),
        "steps": steps,
        "legacy_mode": deepcopy(data.get("방식")),
        "stage_names": deepcopy(data.get("단계명") or []),
        "families": deepcopy(data.get("계열이름") or []),
    })
