# -*- coding: utf-8 -*-
"""개인 자료 색인·저장 현황·대형 폴더 페이지 경계."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping


@dataclass(frozen=True)
class DataInventoryPaths:
    """자료 루트와 재생성 가능한 색인 파일의 기존 위치 계약."""

    base_dir: Path
    program_dir: Path
    index_file: Path
    schema: str
    profile: str


@dataclass(frozen=True)
class DataInventoryOperations:
    """복구 로더·원자 저장·복원 큐·민감정보 제거를 실행 환경에 연결한다."""

    load_json: Callable[[Path], Any]
    atomic_write_json: Callable[..., None]
    now: Callable[[], Any]
    redact: Callable[[Any], str]
    folder_queue: Callable[..., dict]
    folder_summary: Callable[[Mapping[str, Any]], dict]
    summarize_queue: Callable[[Any], dict]


def load_data_index_cached(
    paths: DataInventoryPaths,
    operations: DataInventoryOperations,
    cache: dict,
) -> Any:
    """파일 수정시각이 같을 때만 큰 색인 역직렬화 결과를 재사용한다."""
    if not paths.index_file.is_file():
        return None
    stamp = paths.index_file.stat().st_mtime_ns
    key = str(paths.index_file.resolve())
    if (
        cache.get("path") == key
        and cache.get("mtime_ns") == stamp
        and isinstance(cache.get("value"), dict)
    ):
        return cache["value"]
    value = operations.load_json(paths.index_file)
    cache.update(path=key, mtime_ns=stamp, value=value)
    return value


def iter_indexed_data_files(
    paths: DataInventoryPaths,
) -> Iterator[tuple[Path, str]]:
    """사용자 원본만 순회하고 캐시·장부·임시 파일·링크는 제외한다."""
    roots = [
        paths.base_dir / name
        for name in (
            "후보사전.json",
            "규격.json",
            "옵션.json",
            "태그",
            "세팅",
            "캐릭터",
            "그림체",
            "씬규격",
            "씬프리셋",
            "조각",
            "수집",
        )
    ]
    blocked_parts = {
        "원격",
        "가져온백업",
        "이미지무결성기록",
        "사용자복원기록",
        "__pycache__",
        ".NAI-휴지통",
    }
    blocked_names = {"자료색인.json", "가져온기록.json", "태그색인.pickle"}
    yield from _walk_roots(paths, roots, blocked_parts, blocked_names)


def _walk_roots(
    paths: DataInventoryPaths,
    roots: list[Path],
    blocked_parts: set[str],
    blocked_names: set[str],
) -> Iterator[tuple[Path, str]]:
    seen: set[str] = set()
    base = paths.base_dir.resolve()
    for root in roots:
        candidates = (
            [root]
            if root.is_file()
            else sorted(root.rglob("*")) if root.is_dir() else []
        )
        for path in candidates:
            if not _indexable(path, base, blocked_parts, blocked_names):
                continue
            relative = path.relative_to(paths.base_dir).as_posix()
            if relative not in seen:
                seen.add(relative)
                yield path, relative


def _indexable(
    path: Path,
    base: Path,
    blocked_parts: set[str],
    blocked_names: set[str],
) -> bool:
    if not path.is_file() or path.is_symlink() or path.name in blocked_names:
        return False
    try:
        if base not in path.resolve().parents:
            return False
    except OSError:
        return False
    if any(part in blocked_parts for part in path.parts):
        return False
    return path.suffix.lower() not in (
        ".bak",
        ".tmp",
        ".log",
        ".pyc",
        ".pickle",
    )


def rebuild_data_index(
    paths: DataInventoryPaths,
    operations: DataInventoryOperations,
    cache: dict,
) -> dict:
    """자료 원본의 크기·SHA-256을 다시 계산하고 파생 색인을 원자 저장한다."""
    entries, by_root, total = _index_entries(paths)
    fingerprint = hashlib.sha256(
        "\n".join(
            f"{item['path']}\t{item['size']}\t{item['sha256']}"
            for item in entries
        ).encode("utf-8")
    ).hexdigest()
    index = {
        "schema": paths.schema,
        "generated_at": operations.now().isoformat(timespec="seconds"),
        "data_dir": str(paths.base_dir),
        "files": len(entries),
        "bytes": total,
        "by_root": by_root,
        "fingerprint": fingerprint,
        "entries": entries,
    }
    operations.atomic_write_json(
        paths.index_file,
        index,
        indent=1,
        keep_backup=False,
    )
    cache.update(
        path=str(paths.index_file.resolve()),
        mtime_ns=paths.index_file.stat().st_mtime_ns,
        value=index,
    )
    return index


def _index_entries(
    paths: DataInventoryPaths,
) -> tuple[list[dict], dict, int]:
    entries: list[dict] = []
    by_root: dict[str, dict[str, int]] = {}
    total = 0
    for path, relative in iter_indexed_data_files(paths):
        if len(entries) >= 250_000:
            raise ValueError("자료 파일이 250,000개를 넘어 색인 생성을 중단했습니다.")
        raw = path.read_bytes()
        size = len(raw)
        top = relative.split("/", 1)[0]
        stat = by_root.setdefault(top, {"files": 0, "bytes": 0})
        stat["files"] += 1
        stat["bytes"] += size
        total += size
        entries.append({
            "path": relative,
            "size": size,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return entries, by_root, total


def data_storage_status(
    paths: DataInventoryPaths,
    operations: DataInventoryOperations,
    cache: dict,
    migration: Mapping[str, Any],
) -> dict:
    """저장 위치와 마지막 색인의 공개 요약만 반환한다."""
    index, restoration = None, None
    if paths.index_file.is_file():
        try:
            loaded = load_data_index_cached(paths, operations, cache)
            if isinstance(loaded, dict) and loaded.get("schema") == paths.schema:
                restoration = operations.folder_summary(loaded)
                index = {
                    key: loaded.get(key)
                    for key in (
                        "generated_at",
                        "files",
                        "bytes",
                        "by_root",
                        "fingerprint",
                    )
                }
        except Exception:
            pass
    return {
        "ok": True,
        "program_dir": str(paths.program_dir),
        "data_dir": str(paths.base_dir),
        "separated": paths.program_dir.resolve() != paths.base_dir.resolve(),
        "profile": paths.profile or "기본",
        "migration": {
            key: migration.get(key)
            for key in ("status", "copied", "skipped", "conflicts")
        },
        "index": index,
        "restoration": restoration,
    }


def folder_inventory_page(
    paths: DataInventoryPaths,
    operations: DataInventoryOperations,
    cache: dict,
    offset: Any = 0,
    limit: Any = 50,
) -> dict:
    """색인을 최대 100건씩 비식별 복원 큐와 화면 항목으로 투영한다."""
    index = load_data_index_cached(paths, operations, cache)
    if not isinstance(index, dict) or index.get("schema") != paths.schema:
        return {"ok": True, "empty": True, "items": [], "total": 0}
    entries = index.get("entries") if isinstance(index.get("entries"), list) else []
    start = max(0, int(offset or 0))
    page_size = max(1, min(100, int(limit or 50)))
    page = [
        item
        for item in entries[start:start + page_size]
        if isinstance(item, dict)
    ]
    safe_rows = _inventory_rows(operations, page, start)
    queue = operations.folder_queue(
        safe_rows,
        folder_label="개인 자료",
        cursor=start + len(page),
        status="indexed",
    )
    return _inventory_response(
        operations,
        entries,
        page,
        safe_rows,
        queue,
        start,
        page_size,
    )


def _inventory_rows(
    operations: DataInventoryOperations,
    page: list[dict],
    start: int,
) -> list[dict]:
    return [
        {
            "path": f"index-item:{str(item.get('sha256') or '')}",
            "filename": operations.redact(
                Path(str(item.get("path") or "")).name
            ),
            "content_sha256": item.get("sha256"),
            "size": item.get("size"),
            "cursor": start + index,
            "status": "pending",
        }
        for index, item in enumerate(page)
    ]


def _inventory_response(
    operations: DataInventoryOperations,
    entries: list,
    page: list[dict],
    safe_rows: list[dict],
    queue: dict,
    start: int,
    page_size: int,
) -> dict:
    next_offset = min(start + page_size, len(entries))
    return {
        "ok": True,
        "empty": not entries,
        "total": len(entries),
        "offset": start,
        "more": next_offset < len(entries),
        "next_offset": next_offset,
        "restoration_queue": queue,
        "restoration": operations.summarize_queue(queue),
        "items": [
            {
                "name": safe_rows[index]["filename"],
                "size": int(item.get("size") or 0),
                "cursor": start + index,
            }
            for index, item in enumerate(page)
        ],
    }


__all__ = [
    "DataInventoryOperations",
    "DataInventoryPaths",
    "data_storage_status",
    "folder_inventory_page",
    "iter_indexed_data_files",
    "load_data_index_cached",
    "rebuild_data_index",
]
