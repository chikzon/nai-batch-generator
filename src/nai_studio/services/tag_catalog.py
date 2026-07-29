# -*- coding: utf-8 -*-
"""태그 CSV의 슬롯 분류·검색·자동완성 색인을 소유한다."""

from __future__ import annotations

import csv
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable


@dataclass(frozen=True)
class TagCatalogPaths:
    tag_dir: Path
    cache_file: Path


@dataclass
class TagCatalogState:
    cache: dict
    lock: RLock
    cache_version: int = 3


@dataclass(frozen=True)
class TagCatalogOperations:
    renamed_tag: Callable[[Any], str | None]
    info: Callable[..., Any]
    warning: Callable[..., Any]


def slot_of_tag(
    tag: str,
    category: int,
    character_rules: list,
    style_rules: list,
) -> tuple[str | None, str]:
    """규격 키워드와 CSV 카테고리로 빌더 슬롯을 고른다."""
    if category == 1:
        return "작가", "style"
    if category == 3:
        return "원작/장르", "style"
    if category == 4:
        return "기본", "char"
    core = tag.replace("_", " ").lower()
    best, best_length, kind = None, 0, "char"
    for rules, candidate_kind in (
        (character_rules, "char"),
        (style_rules, "style"),
    ):
        for group in rules:
            for keyword in group.get("키워드", []):
                lowered = keyword.lower()
                if len(lowered) > best_length and lowered in core:
                    best = group["이름"]
                    best_length = len(lowered)
                    kind = candidate_kind
    return best, kind


def load_tag_dict(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
    spec: dict,
) -> dict:
    """CSV 사전을 한 번만 읽고 슬롯별 빈도 목록을 만든다."""
    if state.cache["loaded"]:
        return state.cache
    with state.lock:
        if state.cache["loaded"]:
            return state.cache
        rows, by_slot = [], {}
        if paths.tag_dir.exists():
            character_rules = spec.get("캐릭터_그룹", [])
            style_rules = spec.get("그림체_그룹", [])
            for path in sorted(paths.tag_dir.glob("*.csv")):
                _read_tag_file(
                    path,
                    character_rules,
                    style_rules,
                    rows,
                    by_slot,
                    operations,
                )
        for key in by_slot:
            by_slot[key].sort(key=lambda item: -item[1])
        state.cache.update({
            "loaded": True,
            "rows": rows,
            "by_slot": by_slot,
        })
        operations.info(
            "태그 사전 로드: %s개 (슬롯 분류 %s종)",
            f"{len(rows):,}",
            len(by_slot),
        )
        return state.cache


def _read_tag_file(
    path: Path,
    character_rules: list,
    style_rules: list,
    rows: list,
    by_slot: dict,
    operations: TagCatalogOperations,
) -> None:
    try:
        with open(
            path,
            encoding="utf-8",
            errors="ignore",
            newline="",
        ) as stream:
            for row in csv.reader(stream):
                if len(row) < 3 or not row[0].strip():
                    continue
                tag = row[0].strip()
                try:
                    category = int(row[1]) if row[1].strip() else 0
                    count = int(row[2]) if row[2].strip() else 0
                except ValueError:
                    continue
                slot, kind = slot_of_tag(
                    tag,
                    category,
                    character_rules,
                    style_rules,
                )
                display = tag.replace("_", " ")
                aliases = [
                    item.strip().replace("_", " ")
                    for item in (
                        row[3] if len(row) > 3 else ""
                    ).split(",")
                ]
                rows.append((
                    display,
                    count,
                    slot or "",
                    kind,
                    [item for item in aliases if item],
                ))
                if slot:
                    by_slot.setdefault(
                        (kind, slot),
                        [],
                    ).append((display, count))
    except Exception as error:
        operations.warning(
            "태그 CSV 읽기 실패(%s): %s",
            path.name,
            error,
        )


def autocomplete_tags(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
    spec: dict,
    query: str,
    limit: int = 12,
    *,
    index: dict | None = None,
) -> list[dict]:
    """앞부분 일치와 포함 일치를 빈도순으로 돌려준다."""
    query = (query or "").strip().lower().replace("_", " ")
    if len(query) < 2:
        return []
    if index is None:
        index = autocomplete_index(
            paths,
            state,
            operations,
            spec,
        )
    bare = re.sub(r"^artists?:", "", query)
    seen, output = set(), []
    for key in {query[:2], bare[:2]}:
        for tag, count, lowered in index["buckets"].get(key, []):
            if tag in seen:
                continue
            if (
                lowered.startswith(query)
                or re.sub(r"^artists?:", "", lowered).startswith(bare)
            ):
                seen.add(tag)
                output.append((tag, count))
                if len(output) >= limit * 2:
                    break
    output.sort(key=lambda item: -item[1])
    if len(output) < limit:
        for tag, count, lowered in index["flat"]:
            if tag in seen or query not in lowered:
                continue
            seen.add(tag)
            output.append((tag, count))
            if len(output) >= limit:
                break
    return [
        {"tag": tag, "count": count}
        for tag, count in output[:limit]
    ]


def search_tags(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
    spec: dict,
    kind: str,
    slot: str,
    query: str,
    limit: int = 60,
) -> list[dict]:
    catalog = load_tag_dict(paths, state, operations, spec)
    query = (query or "").strip().lower().replace("_", " ")
    if slot:
        pool = catalog["by_slot"].get((kind, slot), [])
        if query:
            hits = [
                item
                for item in pool
                if query in item[0].lower()
            ]
            if hits:
                return [
                    {"tag": tag, "count": count}
                    for tag, count in hits[:limit]
                ]
        else:
            return [
                {"tag": tag, "count": count}
                for tag, count in pool[:limit]
            ]
    if not query:
        return []
    output = [
        (row[0], row[1])
        for row in catalog["rows"]
        if query in row[0].lower()
    ]
    output.sort(key=lambda item: -item[1])
    return [
        {"tag": tag, "count": count}
        for tag, count in output[:limit]
    ]


def autocomplete_index(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
    spec: dict,
    *,
    cache_loader: Callable[[], dict | None] | None = None,
    cache_saver: Callable[[list, dict, list], None] | None = None,
) -> dict:
    if state.cache.get("ac"):
        return state.cache["ac"]
    with state.lock:
        if state.cache.get("ac"):
            return state.cache["ac"]
        cached = (
            cache_loader()
            if cache_loader is not None
            else cache_load(paths, state, operations)
        )
        if cached:
            state.cache["rows"] = cached["rows"]
            state.cache["loaded"] = True
            state.cache["ac"] = {
                "buckets": cached["buckets"],
                "flat": cached["flat"],
            }
            operations.info(
                "자동완성 색인(캐시): 앞2글자 %s종",
                f"{len(cached['buckets']):,}",
            )
            return state.cache["ac"]
        catalog = load_tag_dict(paths, state, operations, spec)
        return build_index(
            paths,
            state,
            operations,
            catalog,
            cache_loader=cache_loader,
            cache_saver=cache_saver,
        )


def build_index(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
    catalog: dict,
    *,
    cache_loader: Callable[[], dict | None] | None = None,
    cache_saver: Callable[[list, dict, list], None] | None = None,
) -> dict:
    cached = (
        cache_loader()
        if cache_loader is not None
        else cache_load(paths, state, operations)
    )
    if cached:
        catalog["rows"] = cached["rows"]
        catalog["ac"] = {
            "buckets": cached["buckets"],
            "flat": cached["flat"],
        }
        operations.info(
            "자동완성 색인(캐시): 앞2글자 %s종",
            f"{len(cached['buckets']):,}",
        )
        return catalog["ac"]
    buckets, flat = {}, []
    for row in catalog["rows"]:
        tag, count = row[0], row[1]
        aliases = row[4] if len(row) > 4 else []
        lowered = tag.lower()
        suggested = operations.renamed_tag(tag) or tag
        suggested_lower = suggested.lower()
        flat.append((suggested, count, suggested_lower))
        if suggested_lower != lowered:
            flat.append((suggested, count, lowered))
        keys = {lowered[:2], suggested_lower[:2]}
        bare = re.sub(r"^artists?:", "", lowered)
        if bare is not lowered:
            keys.add(bare[:2])
        for alias in aliases[:6]:
            alias_lower = alias.lower()
            if alias_lower and alias_lower != lowered:
                flat.append((suggested, count, alias_lower))
                if len(alias_lower) >= 2:
                    keys.add(alias_lower[:2])
                    buckets.setdefault(alias_lower[:2], []).append(
                        (suggested, count, alias_lower)
                    )
        for key in keys:
            if len(key) == 2:
                buckets.setdefault(key, []).append((
                    suggested,
                    count,
                    suggested_lower
                    if key == suggested_lower[:2]
                    else lowered,
                ))
    for key in buckets:
        buckets[key].sort(key=lambda item: -item[1])
    flat.sort(key=lambda item: -item[1])
    catalog["ac"] = {"buckets": buckets, "flat": flat}
    operations.info(
        "자동완성 색인: 앞2글자 %s종",
        f"{len(buckets):,}",
    )
    if cache_saver is not None:
        cache_saver(catalog["rows"], buckets, flat)
    else:
        cache_save(
            paths,
            state,
            operations,
            catalog["rows"],
            buckets,
            flat,
        )
    return catalog["ac"]


def tag_fingerprint(paths: TagCatalogPaths) -> tuple:
    if not paths.tag_dir.exists():
        return ()
    return tuple(sorted(
        (
            path.name,
            path.stat().st_size,
            int(path.stat().st_mtime),
        )
        for path in paths.tag_dir.glob("*.csv")
    ))


def cache_load(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
) -> dict | None:
    try:
        if not paths.cache_file.exists():
            return None
        with open(paths.cache_file, "rb") as stream:
            cached = pickle.load(stream)
        if cached.get("fp") != tag_fingerprint(paths):
            operations.info(
                "태그 사전이 바뀌어 색인 캐시를 버립니다"
            )
            return None
        if cached.get("ver") != state.cache_version:
            operations.info(
                "색인 형식이 바뀌어 캐시를 다시 만듭니다"
            )
            return None
        return cached
    except Exception as error:
        operations.info("색인 캐시 읽기 건너뜀: %s", error)
        return None


def cache_save(
    paths: TagCatalogPaths,
    state: TagCatalogState,
    operations: TagCatalogOperations,
    rows: list,
    buckets: dict,
    flat: list,
) -> None:
    try:
        paths.cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = paths.cache_file.with_suffix(".tmp")
        with open(temporary, "wb") as stream:
            pickle.dump(
                {
                    "fp": tag_fingerprint(paths),
                    "ver": state.cache_version,
                    "rows": rows,
                    "buckets": buckets,
                    "flat": flat,
                },
                stream,
                protocol=4,
            )
        temporary.replace(paths.cache_file)
        operations.info(
            "색인 캐시 저장: %sMB",
            paths.cache_file.stat().st_size // 1024 // 1024,
        )
    except Exception as error:
        operations.info("색인 캐시 저장 건너뜀: %s", error)


__all__ = [
    "TagCatalogOperations",
    "TagCatalogPaths",
    "TagCatalogState",
    "autocomplete_index",
    "autocomplete_tags",
    "build_index",
    "cache_load",
    "cache_save",
    "load_tag_dict",
    "search_tags",
    "slot_of_tag",
    "tag_fingerprint",
]
