# -*- coding: utf-8 -*-
"""통합 자료실 검색과 비파괴 검토 장부 경계."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class LibraryCatalogPaths:
    """현재 프로필의 자료 정리 장부 위치와 공개 계약."""

    review_file: Path
    review_schema: str = "nais-library-review/v1"
    review_statuses: frozenset[str] = frozenset({
        "pending",
        "reviewed",
        "hold",
    })


@dataclass(frozen=True)
class LibraryCatalogState:
    """기존 그림체 검색 캐시와 정렬 함수를 같은 객체로 공유한다."""

    combo_cache: dict[str, Any]
    style_sorts: dict[str, Callable[[dict], Any]]


@dataclass(frozen=True)
class LibraryCatalogOperations:
    """조회·저장 함수를 호출 시점에 연결해 legacy monkeypatch와 캐시를 보존한다."""

    load_combos: Callable[[], list]
    load_ratings: Callable[[], dict]
    style_rating: Callable[[dict, dict], dict]
    list_settings: Callable[[], list]
    list_styles: Callable[[dict], list]
    load_recipes: Callable[[], list]
    comparison_runs: Callable[..., dict]
    load_json: Callable[[Path], Any]
    atomic_write_json: Callable[..., None]
    now: Callable[[], Any]
    review_lock: Any
    warning: Callable[..., Any]


def _combo_texts(
    rows: list[dict],
    state: LibraryCatalogState,
) -> list[str]:
    cached = (
        (state.combo_cache.get("search") or [])
        if rows is state.combo_cache.get("rows") else []
    )
    if len(cached) == len(rows):
        return cached
    return [
        " ".join(str(row.get(key) or "") for key in (
            "combo", "title", "source", "rest", "negative"
        )).casefold()
        for row in rows
    ]


def _filter_combos(
    rows: list[dict],
    state: LibraryCatalogState,
    *,
    query: str,
    tab: str,
    source: str,
    seeded: Any,
) -> list[dict]:
    query = (query or "").strip().casefold()
    matched = rows
    if query:
        terms = [term for term in query.split() if term]
        cached = _combo_texts(rows, state)
        matched = [
            row
            for row, text in zip(rows, cached)
            if all(term in text for term in terms)
        ]
    if tab and tab != "all":
        matched = [
            row
            for row in matched
            if (row.get("tab") or "") == tab
        ]
    if source and source != "all":
        matched = [
            row
            for row in matched
            if (row.get("source") or "") == source
        ]
    if seeded in ("1", "true", True):
        matched = [
            row
            for row in matched
            if (row.get("params") or {}).get("seed")
        ]
    return matched


def _rating_accessor(
    operations: LibraryCatalogOperations,
    ratings: dict,
) -> Callable[[dict], dict]:
    cache: dict[int, dict] = {}

    def rating_for(row: dict) -> dict:
        key = id(row)
        if key not in cache:
            cache[key] = operations.style_rating(row, ratings)
        return cache[key]

    return rating_for


def _filter_combo_ratings(
    matched: list[dict],
    rating: str,
    rating_for: Callable[[dict], dict],
) -> list[dict]:
    if rating:
        if rating == "fav":
            return [row for row in matched if rating_for(row)["fav"]]
        elif rating == "rated":
            return [row for row in matched if rating_for(row)["score"]]
        elif rating == "hideblock":
            return [row for row in matched if not rating_for(row)["block"]]
    return matched


def _combo_tally(
    rows: list[dict],
    state: LibraryCatalogState,
    key: str,
    default: str = "",
) -> dict[str, int]:
    if rows is state.combo_cache.get("rows"):
        cached = state.combo_cache.get(
            "sources" if key == "source" else "tabs" if key == "tab" else ""
        )
        if cached is not None:
            return dict(cached)
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or default
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _combo_cards(
    page: list[dict],
    rating_for: Callable[[dict], dict],
) -> list[dict]:
    card_fields = (
        "id",
        "title",
        "source",
        "tab",
        "posted_at",
        "recommend",
        "views",
        "url",
        "count",
        "combo",
        "artists",
        "base",
        "negative",
        "negative_full",
        "params",
        "images",
    )
    items = []
    for row in page:
        item = {
            key: row[key] for key in card_fields if key in row
        }
        if isinstance(item.get("images"), list):
            item["images"] = item["images"][:1]
        item["_rate"] = rating_for(row)
        items.append(item)
    return items


def search_combos(
    state: LibraryCatalogState,
    operations: LibraryCatalogOperations,
    query: str = "",
    limit: int = 40,
    offset: int = 0,
    tab: str = "",
    source: str = "",
    sort: str = "",
    seeded: Any = "",
    rating: str = "",
) -> dict[str, Any]:
    """그림체 묶음을 검색·필터·정렬하고 카드에 필요한 필드만 반환한다."""
    rows = operations.load_combos()
    rating_for = _rating_accessor(operations, operations.load_ratings())
    matched = _filter_combos(
        rows, state, query=query, tab=tab, source=source, seeded=seeded
    )
    matched = _filter_combo_ratings(matched, rating, rating_for)
    if sort in state.style_sorts and sort != "default":
        matched = sorted(
            matched,
            key=state.style_sorts[sort],
            reverse=sort == "newest",
        )
    items = _combo_cards(matched[offset:offset + limit], rating_for)
    seeded_total = (
        int(state.combo_cache.get("seeded") or 0)
        if rows is state.combo_cache.get("rows")
        else sum(
            1
            for row in rows
            if (row.get("params") or {}).get("seed")
        )
    )
    return {
        "total": len(rows),
        "matched": len(matched),
        "sources": _combo_tally(rows, state, "source", "도랑"),
        "tabs": _combo_tally(rows, state, "tab"),
        "seeded": seeded_total,
        "items": items,
        "offset": offset,
    }


def load_library_review(
    paths: LibraryCatalogPaths,
    operations: LibraryCatalogOperations,
    strict: bool = False,
) -> dict[str, Any]:
    """손상 장부는 읽기 화면에서 격리하고 저장 요청에서는 덮어쓰지 않는다."""
    if not paths.review_file.is_file():
        return {"schema": paths.review_schema, "items": {}}
    try:
        data = operations.load_json(paths.review_file)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("items"), dict)
        ):
            raise ValueError(
                "자료 정리 장부 형식이 올바르지 않습니다."
            )
        return data
    except Exception as error:
        operations.warning(
            f"자료 정리 장부를 읽지 못했습니다: {error}"
        )
        if strict:
            raise ValueError(
                "자료 정리 장부가 손상되어 저장을 멈췄습니다. "
                "자료정리.json과 .bak을 확인하세요."
            ) from error
        return {"schema": paths.review_schema, "items": {}}


def library_review_revision(data: Any) -> str:
    """장부 전체의 안정 JSON 지문을 낙관적 동시성 revision으로 쓴다."""
    raw = json.dumps(
        data or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_library_labels(value: Any) -> list[str]:
    """이름표를 NFKC 정규화하고 순서를 지킨 채 중복·상한을 적용한다."""
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(
            "자료 이름표는 문자열 또는 목록이어야 합니다."
        )
    labels: list[str] = []
    for raw in value:
        label = unicodedata.normalize(
            "NFKC",
            str(raw or ""),
        ).strip()
        if not label:
            continue
        if len(label) > 40:
            raise ValueError("자료 이름표는 40자 이하여야 합니다.")
        if label not in labels:
            labels.append(label)
        if len(labels) >= 20:
            break
    return labels


def organize_library_items(
    paths: LibraryCatalogPaths,
    operations: LibraryCatalogOperations,
    request: Any,
) -> dict[str, Any]:
    """원본 자산은 건드리지 않고 검토 상태와 이름표 장부만 원자 저장한다."""
    if not isinstance(request, dict):
        raise ValueError("자료 정리 요청 형식이 올바르지 않습니다.")
    identifiers = request.get("ids") or []
    if not isinstance(identifiers, list):
        raise ValueError("정리할 자료 id는 목록이어야 합니다.")
    identifiers = list(dict.fromkeys(
        str(value or "").strip() for value in identifiers
    ))
    identifiers = [
        value for value in identifiers if value
    ]
    if not identifiers:
        raise ValueError("정리할 자료를 먼저 고르세요.")
    if len(identifiers) > 500:
        raise ValueError(
            "한 번에 정리할 자료는 500개까지입니다."
        )
    if any(
        len(value) > 240 or ":" not in value
        for value in identifiers
    ):
        raise ValueError("자료 id 형식이 올바르지 않습니다.")
    action = str(request.get("action") or "apply")
    with operations.review_lock:
        data = load_library_review(
            paths,
            operations,
            strict=True,
        )
        revision = library_review_revision(data)
        expected = str(request.get("expect_revision") or "")
        if expected and expected != revision:
            return {
                "ok": False,
                "conflict": True,
                "revision": revision,
                "error": (
                    "다른 화면에서 자료 정리가 먼저 바뀌었습니다. "
                    "목록을 새로 불러와 다시 적용하세요."
                ),
            }
        items = data.setdefault("items", {})
        before = {
            item_id: copy.deepcopy(items.get(item_id))
            for item_id in identifiers
        }
        if action == "restore":
            restore = request.get("records")
            if not isinstance(restore, dict):
                raise ValueError(
                    "되돌릴 자료 정리 기록이 없습니다."
                )
            for item_id in identifiers:
                old = restore.get(item_id)
                if isinstance(old, dict):
                    items[item_id] = copy.deepcopy(old)
                else:
                    items.pop(item_id, None)
        elif action == "apply":
            raw_status = request.get("status")
            status = str(raw_status or "").strip()
            if (
                status
                and status not in paths.review_statuses
            ):
                raise ValueError("알 수 없는 검토 상태입니다.")
            labels = normalize_library_labels(
                request.get("labels")
            )
            label_mode = str(
                request.get("label_mode") or "add"
            )
            if label_mode not in {"add", "replace", "clear"}:
                raise ValueError(
                    "알 수 없는 이름표 적용 방식입니다."
                )
            for item_id in identifiers:
                record = copy.deepcopy(items.get(item_id) or {})
                if status:
                    record["status"] = status
                if label_mode == "clear":
                    record["labels"] = []
                elif label_mode == "replace":
                    record["labels"] = labels
                elif labels:
                    record["labels"] = normalize_library_labels(
                        list(record.get("labels") or []) + labels
                    )
                record["updated_at"] = operations.now().isoformat(
                    timespec="seconds"
                )
                if (
                    record.get("status", "pending") == "pending"
                    and not record.get("labels")
                ):
                    items.pop(item_id, None)
                else:
                    items[item_id] = record
        else:
            raise ValueError("알 수 없는 자료 정리 동작입니다.")
        data["schema"] = paths.review_schema
        data["updated_at"] = operations.now().isoformat(
            timespec="seconds"
        )
        operations.atomic_write_json(paths.review_file, data)
        return {
            "ok": True,
            "changed": len(identifiers),
            "before": before,
            "revision": library_review_revision(data),
        }


def _character_rows(config: dict | None) -> list[dict[str, Any]]:
    rows = []
    for character in (config or {}).get("characters", []):
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "(무명)")
        images: list[str] = []
        for image_ref in [
            character.get("representative"),
            character.get("representative_image"),
            *(
                character.get("images")
                if isinstance(character.get("images"), list)
                else []
            ),
            *(
                character.get("evidence_images")
                if isinstance(
                    character.get("evidence_images"),
                    list,
                )
                else []
            ),
            *(
                character.get("variation_images")
                if isinstance(
                    character.get("variation_images"),
                    list,
                )
                else []
            ),
        ]:
            if (
                isinstance(image_ref, str)
                and image_ref
                and image_ref not in images
            ):
                images.append(image_ref)
        rows.append({
            "id": (
                "character:"
                + str(character.get("id") or name)
            ),
            "kind": "캐릭터",
            "store": "character",
            "name": name,
            "prompt": str(character.get("female") or ""),
            "negative": str(character.get("negative") or ""),
            "outfit": str(character.get("clothed") or ""),
            "source": str(
                character.get("source") or "내 캐릭터"
            ),
            "groups": (
                character.get("groups")
                if isinstance(character.get("groups"), dict)
                else {}
            ),
            "images": images,
            "evidence": (
                copy.deepcopy(character.get("evidence"))
                if "evidence" in character
                else None
            ),
            "ref": {
                key: copy.deepcopy(character.get(key))
                for key in (
                    "id",
                    "name",
                    "female",
                    "clothed",
                    "negative",
                    "groups",
                    "source",
                    "folder_id",
                    "subfolder_id",
                    "variant",
                    "variants",
                    "reference_ids",
                    "vibe_ids",
                    "selected_variant_id",
                    "representative",
                    "images",
                    "evidence",
                    "evidence_ids",
                    "evidence_refs",
                    "evidence_images",
                    "variation_images",
                )
                if key in character
            },
        })
    return rows


def _preset_rows(
    operations: LibraryCatalogOperations,
    spec: dict | None,
) -> list[dict[str, Any]]:
    rows = []
    for index, style in enumerate(
        operations.list_styles(spec or {})
    ):
        name = str(
            style.get("name") or f"그림체 {index + 1}"
        )
        rows.append({
            "id": "preset:" + name,
            "kind": "그림체",
            "store": "preset",
            "name": name,
            "prompt": str(style.get("prompt") or ""),
            "negative": str(style.get("negative") or ""),
            "source": "내 프리셋",
            "settings": copy.deepcopy(
                style.get("settings") or {}
            ),
            "images": [],
            "ref": copy.deepcopy(style),
        })
    return rows


def _collected_style_rows(
    operations: LibraryCatalogOperations,
) -> list[dict[str, Any]]:
    rows = []
    card_fields = (
        "id",
        "title",
        "source",
        "tab",
        "posted_at",
        "recommend",
        "views",
        "url",
        "count",
        "combo",
        "artists",
        "base",
        "negative",
        "negative_full",
        "params",
        "images",
    )
    for index, style in enumerate(operations.load_combos()):
        if not isinstance(style, dict):
            continue
        compact = {
            key: copy.deepcopy(style[key])
            for key in card_fields
            if key in style
        }
        if isinstance(compact.get("images"), list):
            compact["images"] = compact["images"][:1]
        name = str(
            style.get("title")
            or style.get("combo")
            or f"수집 그림체 {index + 1}"
        )
        fallback_id = hashlib.sha256(
            json.dumps(
                compact,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:20]
        rows.append({
            "id": (
                "collected:"
                + str(style.get("id") or fallback_id)
            ),
            "kind": "그림체",
            "store": "collected",
            "name": name,
            "prompt": str(
                style.get("base") or style.get("combo") or ""
            ),
            "negative": str(style.get("negative") or ""),
            "source": str(
                style.get("source") or "수집 자료"
            ),
            "settings": copy.deepcopy(
                style.get("params") or {}
            ),
            "images": list(style.get("images") or [])[:1],
            "ref": compact,
        })
    return rows


def _recipe_rows(
    operations: LibraryCatalogOperations,
) -> list[dict[str, Any]]:
    rows = []
    for index, recipe in enumerate(operations.load_recipes()):
        if not isinstance(recipe, dict):
            continue
        compact = {
            key: copy.deepcopy(recipe[key])
            for key in (
                "id",
                "title",
                "axis",
                "concept",
                "concept_ko",
                "domain",
                "tags",
                "positive",
                "negative",
                "url",
                "images",
            )
            if key in recipe
        }
        if isinstance(compact.get("images"), list):
            compact["images"] = compact["images"][:2]
        fallback_id = hashlib.sha256(
            json.dumps(
                compact,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:20]
        rows.append({
            "id": (
                "recipe:"
                + str(recipe.get("id") or fallback_id)
            ),
            "kind": "레시피",
            "store": "recipe",
            "name": str(
                recipe.get("title")
                or recipe.get("concept_ko")
                or f"레시피 {index + 1}"
            ),
            "prompt": str(recipe.get("positive") or ""),
            "negative": str(recipe.get("negative") or ""),
            "source": "공유 레시피",
            "images": list(recipe.get("images") or [])[:1],
            "ref": compact,
        })
    return rows


def _setting_rows(
    operations: LibraryCatalogOperations,
) -> list[dict[str, Any]]:
    rows = []
    for setting in operations.list_settings():
        data = (
            setting.get("data")
            if isinstance(setting.get("data"), dict)
            else {}
        )
        scenes = (
            data.get("씬")
            if isinstance(data.get("씬"), dict)
            else {}
        )
        scene_names = [
            str(scene.get("name") or scene.get("이름") or "")
            for scene in scenes.values()
            if isinstance(scene, dict)
        ]
        rows.append({
            "id": (
                "setting:"
                + str(
                    setting.get("file")
                    or setting.get("name")
                )
            ),
            "kind": "세팅",
            "store": "setting",
            "name": str(
                setting.get("name") or "(이름 없는 세팅)"
            ),
            "prompt": ", ".join(scene_names),
            "negative": str(data.get("네거티브") or ""),
            "source": "내 세팅",
            "meta": {
                "mode": str(setting.get("mode") or "단독"),
                "scenes": len(scenes),
                "stages": list(data.get("단계명") or []),
                "options": (
                    list((data.get("옵션") or {}).keys())
                    if isinstance(data.get("옵션"), dict)
                    else []
                ),
            },
            "ref": {
                "name": str(setting.get("name") or ""),
                "file": str(setting.get("file") or ""),
            },
        })
    return rows


def _generation_rows(
    operations: LibraryCatalogOperations,
    config: dict | None,
) -> list[dict[str, Any]]:
    rows = []
    for run in operations.comparison_runs(
        config,
        limit=200,
    ).get("runs", []):
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "상태 미확인")
        completed = int(run.get("completed") or 0)
        total = int(run.get("total") or completed)
        rows.append({
            "id": (
                "generation:"
                + str(run.get("folder") or run.get("name"))
            ),
            "kind": "생성 기록",
            "store": "generation",
            "name": str(
                run.get("mode_label")
                or run.get("name")
                or "비교 생성"
            ),
            "prompt": f"{status} · {completed}/{total}장",
            "negative": "",
            "source": "비교 생성",
            "meta": {
                "status": status,
                "completed": completed,
                "total": total,
                "updated_at": str(
                    run.get("updated_at") or ""
                ),
                "resumable": bool(run.get("resumable")),
            },
            "ref": copy.deepcopy(run),
        })
    return rows


def _apply_library_review(
    rows: list[dict[str, Any]],
    paths: LibraryCatalogPaths,
    operations: LibraryCatalogOperations,
) -> tuple[dict, dict[str, int], dict[str, int]]:
    review_data = load_library_review(paths, operations)
    review_items = review_data.get("items") or {}
    review_counts = {
        "pending": 0,
        "reviewed": 0,
        "hold": 0,
    }
    all_labels: dict[str, int] = {}
    for row in rows:
        record = review_items.get(row["id"])
        if not isinstance(record, dict):
            record = {}
        status = str(record.get("status") or "pending")
        if status not in paths.review_statuses:
            status = "pending"
        try:
            labels = normalize_library_labels(
                record.get("labels")
            )
        except ValueError:
            labels = []
        row["review_status"] = status
        row["labels"] = labels
        review_counts[status] += 1
        for value in labels:
            all_labels[value] = all_labels.get(value, 0) + 1
    return review_data, review_counts, all_labels


def _library_facets(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    all_sources: dict[str, int] = {}
    all_kinds: dict[str, int] = {}
    for row in rows:
        all_sources[row["source"]] = (
            all_sources.get(row["source"], 0) + 1
        )
        all_kinds[row["kind"]] = (
            all_kinds.get(row["kind"], 0) + 1
        )
    return all_sources, all_kinds


def _library_terms(query: str) -> list[str]:
    return [
        part
        for part in re.split(
            r"\s+",
            unicodedata.normalize(
                "NFKC",
                str(query or ""),
            ).strip().casefold(),
        )
        if part
    ]


def _library_row_matches(
    row: dict[str, Any],
    terms: list[str],
    kind: str,
    source: str,
    review: str,
    label: str,
) -> bool:
    if kind and kind not in {"all", row["kind"]}:
        return False
    if source and source not in {"all", row["source"]}:
        return False
    if review and review not in {"all", row["review_status"]}:
        return False
    if label and label not in row["labels"]:
        return False
    if not terms:
        return True
    haystack = unicodedata.normalize(
        "NFKC",
        " ".join([
            row.get("name", ""),
            row.get("prompt", ""),
            row.get("negative", ""),
            row.get("outfit", ""),
            row.get("source", ""),
            " ".join(row.get("labels") or []),
            row.get("review_status", ""),
            json.dumps(
                row.get("meta") or {},
                ensure_ascii=False,
            ),
        ]),
    ).casefold()
    return all(term in haystack for term in terms)


def search_library(
    paths: LibraryCatalogPaths,
    operations: LibraryCatalogOperations,
    config: dict | None,
    spec: dict | None,
    query: str = "",
    kind: str = "",
    source: str = "",
    limit: int = 100,
    offset: int = 0,
    review: str = "",
    label: str = "",
) -> dict[str, Any]:
    """각 저장소 투영을 합친 뒤 검토 상태·검색·페이징을 한 번 적용한다."""
    try:
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit, offset = 100, 0
    rows = [
        *_character_rows(config),
        *_preset_rows(operations, spec),
        *_collected_style_rows(operations),
        *_recipe_rows(operations),
        *_setting_rows(operations),
        *_generation_rows(operations, config),
    ]
    review_data, review_counts, all_labels = _apply_library_review(
        rows, paths, operations
    )
    all_sources, all_kinds = _library_facets(rows)
    query_terms = _library_terms(query)
    matched = [
        row
        for row in rows
        if _library_row_matches(
            row, query_terms, kind, source, review, label
        )
    ]
    page = matched[offset:offset + limit]
    return {
        "ok": True,
        "total": len(rows),
        "matched": len(matched),
        "offset": offset,
        "items": page,
        "sources": all_sources,
        "kinds": all_kinds,
        "review_counts": review_counts,
        "labels": all_labels,
        "revision": library_review_revision(review_data),
    }


__all__ = [
    "LibraryCatalogOperations",
    "LibraryCatalogPaths",
    "LibraryCatalogState",
    "library_review_revision",
    "load_library_review",
    "normalize_library_labels",
    "organize_library_items",
    "search_combos",
    "search_library",
]
