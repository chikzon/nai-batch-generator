# -*- coding: utf-8 -*-
"""작가 별점·즐겨찾기·차단·메모의 원자 저장소."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable


@dataclass(frozen=True)
class ArtistRatingPaths:
    ratings_file: Path


@dataclass
class ArtistRatingState:
    cache: dict
    lock: RLock


@dataclass(frozen=True)
class ArtistRatingOperations:
    transaction: Callable[[Path], Any]
    load_json: Callable[[Path], Any]
    atomic_write_json: Callable[[Path, Any], Any]
    parse_artist_combo: Callable[[str], tuple]
    warning: Callable[..., Any]
    current_loader: Callable[[], dict] | None = None
    current_saver: Callable[[dict], dict] | None = None


def artist_key(name: Any) -> str:
    """저장·검색·차단 판정이 공유하는 작가 이름 표준형."""
    return re.sub(
        r"\s+",
        " ",
        str(name or ""),
    ).strip().casefold()


def load_ratings(
    paths: ArtistRatingPaths,
    state: ArtistRatingState,
    operations: ArtistRatingOperations,
) -> dict:
    """파일 수정 시각이 바뀌면 안전한 마지막 값으로 다시 읽는다."""
    with state.lock:
        try:
            modified = (
                paths.ratings_file.stat().st_mtime_ns
                if paths.ratings_file.exists()
                else 0
            )
        except OSError:
            modified = 0
        if modified != state.cache["mtime"]:
            data = {}
            if paths.ratings_file.exists():
                try:
                    data = (
                        operations.load_json(paths.ratings_file)
                        or {}
                    )
                except Exception as error:
                    operations.warning(
                        "작가평가.json 읽기 실패: %s",
                        error,
                    )
                    return state.cache["data"]
            state.cache.update({
                "mtime": modified,
                "data": data if isinstance(data, dict) else {},
            })
        return state.cache["data"]


def save_ratings(
    paths: ArtistRatingPaths,
    state: ArtistRatingState,
    operations: ArtistRatingOperations,
    data: dict,
) -> dict:
    """평가 사본을 원자 저장하고 메모리 캐시를 갱신한다."""
    with state.lock:
        paths.ratings_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        operations.atomic_write_json(paths.ratings_file, data)
        try:
            state.cache.update({
                "mtime": paths.ratings_file.stat().st_mtime,
                "data": data,
            })
        except OSError:
            state.cache.update({"mtime": -1, "data": data})
        return data


def rate_artist(
    paths: ArtistRatingPaths,
    state: ArtistRatingState,
    operations: ArtistRatingOperations,
    name: Any,
    **fields: Any,
) -> dict:
    """작가 한 명의 허용된 평가 필드만 최신 디스크 값에 병합한다."""
    with operations.transaction(paths.ratings_file.parent.parent):
        key = artist_key(name)
        if not key:
            return {}
        with state.lock:
            state.cache["mtime"] = -1
            data = dict(
                operations.current_loader()
                if operations.current_loader is not None
                else load_ratings(paths, state, operations)
            )
            current = dict(data.get(key) or {})
            _apply_rating_fields(current, fields)
            if not any((
                current.get("score"),
                current.get("fav"),
                current.get("block"),
                current.get("memo"),
            )):
                data.pop(key, None)
            else:
                data[key] = current
            if operations.current_saver is not None:
                operations.current_saver(data)
            else:
                save_ratings(paths, state, operations, data)
            return current


def _apply_rating_fields(
    current: dict,
    fields: dict,
) -> None:
    for key in ("score", "fav", "block", "memo"):
        if key not in fields:
            continue
        if key == "score":
            try:
                current[key] = max(
                    0,
                    min(5, int(fields[key] or 0)),
                )
            except (TypeError, ValueError):
                current[key] = 0
        elif key == "memo":
            current[key] = str(fields[key] or "")
        else:
            value = fields[key]
            current[key] = (
                value
                if isinstance(value, bool)
                else str(value).strip().lower()
                in ("1", "true", "yes", "on")
            )


def blocked_artists_in(
    paths: ArtistRatingPaths,
    state: ArtistRatingState,
    operations: ArtistRatingOperations,
    text: str,
) -> list[str]:
    ratings = load_ratings(paths, state, operations)
    blocked = {
        key
        for key, value in ratings.items()
        if value.get("block")
    }
    if not blocked:
        return []
    names = {
        artist_key(artist)
        for _, artist in operations.parse_artist_combo(
            text or ""
        )[0]
    }
    return sorted(blocked & names)


def style_rating(
    paths: ArtistRatingPaths,
    state: ArtistRatingState,
    operations: ArtistRatingOperations,
    record: dict,
    ratings: dict | None = None,
) -> dict:
    data = (
        load_ratings(paths, state, operations)
        if ratings is None
        else ratings
    )
    artists = [
        artist_key(artist)
        for artist in (record.get("artists") or [])
    ]
    values = [
        data.get(artist)
        for artist in artists
        if data.get(artist)
    ]
    scores = [
        value["score"]
        for value in values
        if value.get("score")
    ]
    return {
        "score": (
            round(sum(scores) / len(scores), 1)
            if scores
            else 0
        ),
        "fav": any(value.get("fav") for value in values),
        "block": any(value.get("block") for value in values),
        "rated": len(values),
    }


__all__ = [
    "ArtistRatingOperations",
    "ArtistRatingPaths",
    "ArtistRatingState",
    "artist_key",
    "blocked_artists_in",
    "load_ratings",
    "rate_artist",
    "save_ratings",
    "style_rating",
]
