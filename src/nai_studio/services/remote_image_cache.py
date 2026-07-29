# -*- coding: utf-8 -*-
"""원격 예시 이미지 캐시·출처 장부·미리 받기 경계."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class RemoteImageCachePaths:
    """로컬 이미지와 원격 캐시를 분리한 기존 파일 위치 계약."""

    image_cache: Path
    remote_cache: Path
    origin_file: Path
    cap_mb: int
    mime: Mapping[str, str]


@dataclass(frozen=True)
class RemoteImageCacheOperations:
    """HTTP·원자 저장·로그·잠금을 실행 환경에 늦게 연결한다."""

    http_get: Callable[..., Any]
    load_json: Callable[[Path], Any]
    atomic_write_bytes: Callable[..., None]
    atomic_write_json: Callable[..., None]
    warning: Callable[[str], Any]
    info: Callable[[str], Any]
    origin_lock: Any


def trim_remote_cache(
    paths: RemoteImageCachePaths,
    operations: RemoteImageCacheOperations,
) -> None:
    """상한을 넘긴 원격 캐시만 오래된 순서로 80%까지 줄인다."""
    try:
        files = [
            (path.stat().st_mtime, path.stat().st_size, path)
            for path in paths.remote_cache.glob("*")
            if path.is_file()
        ]
    except Exception:
        return
    total = sum(size for _, size, _ in files)
    cap = paths.cap_mb * 1024 * 1024
    if total <= cap:
        return
    for _, size, path in sorted(files):
        try:
            path.unlink()
            total -= size
        except Exception:
            pass
        if total <= cap * 0.8:
            break
    operations.info(f"예시 이미지 캐시 정리 → {total/1024/1024:.0f}MB")


def headers_for(
    url: str,
    host_headers: Mapping[str, Mapping[str, str]],
    default_headers: Mapping[str, str],
) -> Mapping[str, str]:
    """호스트별 CDN 계약을 우선하고 그 밖에는 브라우저 헤더를 쓴다."""
    host = (urlparse(url).hostname or "").lower()
    for expected, headers in host_headers.items():
        if host == expected or host.endswith("." + expected):
            return headers
    return default_headers


def _remote_cache_path(paths: RemoteImageCachePaths, url: str) -> Path:
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix not in paths.mime:
        suffix = ".webp"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return paths.remote_cache / (digest + suffix)


def fetch_cached_image(
    paths: RemoteImageCachePaths,
    operations: RemoteImageCacheOperations,
    url: Any,
    host_headers: Mapping[str, Mapping[str, str]],
    default_headers: Mapping[str, str],
    note_origin: Callable[[str, bytes], Any],
) -> tuple[bytes | None, str | None]:
    """local:은 직접 읽고 HTTP 이미지는 원자 저장 뒤 출처를 연결한다."""
    text = (url or "").strip()
    if not text:
        return None, None
    paths.image_cache.mkdir(parents=True, exist_ok=True)
    if text.startswith("local:"):
        path = paths.image_cache / Path(text[6:]).name
        if path.exists() and path.is_file():
            return (
                path.read_bytes(),
                paths.mime.get(path.suffix.lower(), "image/png"),
            )
        operations.warning(f"로컬 이미지 없음: {path.name}")
        return None, None
    if not text.startswith(("http://", "https://")):
        return None, None
    return _fetch_remote(
        paths,
        operations,
        text,
        host_headers,
        default_headers,
        note_origin,
    )


def _fetch_remote(
    paths: RemoteImageCachePaths,
    operations: RemoteImageCacheOperations,
    url: str,
    host_headers: Mapping[str, Mapping[str, str]],
    default_headers: Mapping[str, str],
    note_origin: Callable[[str, bytes], Any],
) -> tuple[bytes | None, str | None]:
    paths.remote_cache.mkdir(parents=True, exist_ok=True)
    path = _remote_cache_path(paths, url)
    if path.exists():
        return path.read_bytes(), paths.mime.get(path.suffix.lower(), "image/webp")
    try:
        response = operations.http_get(
            url,
            timeout=25,
            headers=headers_for(url, host_headers, default_headers),
        )
        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and content_type.startswith("image/"):
            operations.atomic_write_bytes(
                path,
                response.content,
                keep_backup=False,
            )
            note_origin(url, response.content)
            return response.content, content_type
        operations.warning(
            f"이미지 응답 이상 [{response.status_code} {content_type}]: "
            f"{url[:80]}"
        )
    except Exception as exc:
        operations.warning(f"이미지 가져오기 실패: {exc}")
    return None, None


def load_image_origins(
    paths: RemoteImageCachePaths,
    operations: RemoteImageCacheOperations,
) -> dict:
    """복구 가능한 기존 JSON 장부만 사전으로 반환한다."""
    if not paths.origin_file.exists():
        return {}
    try:
        data = operations.load_json(paths.origin_file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def note_image_origin(
    paths: RemoteImageCachePaths,
    operations: RemoteImageCacheOperations,
    url: Any,
    data: Any,
    pack: str = "",
) -> str | None:
    """원본 주소와 내용 SHA-256을 기존 출처 장부 schema로 원자 저장한다."""
    if not url or not data:
        return None
    digest = hashlib.sha256(data).hexdigest()
    try:
        with operations.origin_lock:
            book = load_image_origins(paths, operations)
            row = book.get(digest) or {
                "sha256": digest,
                "urls": [],
                "pack": pack,
            }
            if url not in row["urls"]:
                row["urls"].append(url)
            if pack and not row.get("pack"):
                row["pack"] = pack
            row["size"] = len(data)
            book[digest] = row
            paths.origin_file.parent.mkdir(parents=True, exist_ok=True)
            operations.atomic_write_json(
                paths.origin_file,
                book,
                indent=None,
            )
    except Exception as exc:
        operations.warning(f"출처 기록 실패: {exc}")
    return digest


def image_origin_stats(
    paths: RemoteImageCachePaths,
    operations: RemoteImageCacheOperations,
) -> dict:
    """주소가 여러 개인 동일 이미지와 중복 주소 수를 기존 응답으로 요약한다."""
    book = load_image_origins(paths, operations)
    duplicates = {
        key: value
        for key, value in book.items()
        if len(value.get("urls") or []) > 1
    }
    return {
        "ok": True,
        "그림": len(book),
        "주소여럿": len(duplicates),
        "낭비주소": sum(
            len(value["urls"]) - 1 for value in duplicates.values()
        ),
        "예시": [
            {"sha256": key[:16], "urls": value["urls"][:4]}
            for key, value in list(duplicates.items())[:20]
        ],
    }


def prewarm_images(
    items: Any,
    n: int,
    *,
    seen: set,
    pool: Any,
    lock: Any,
    executor_factory: Callable[..., Any],
    fetch_image: Callable[[str], Any],
    trim_cache: Callable[[], Any],
) -> Any:
    """목록 첫 이미지만 중복 없이 백그라운드 캐시에 넣고 pool을 반환한다."""
    urls = _prewarm_urls(items, n)
    if not urls:
        return pool
    with lock:
        todo = [url for url in urls if url not in seen]
        seen.update(todo)
        if pool is None:
            pool = executor_factory(
                max_workers=8,
                thread_name_prefix="imgwarm",
            )
    for url in todo:
        try:
            pool.submit(fetch_image, url)
        except Exception:
            break
    if len(seen) % 600 < len(todo):
        try:
            pool.submit(trim_cache)
        except Exception:
            pass
    return pool


def _prewarm_urls(items: Any, n: int) -> list[str]:
    urls: list[str] = []
    for item in (items or [])[:n]:
        for url in (item.get("images") or [])[:1]:
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.append(url)
    return urls


__all__ = [
    "RemoteImageCacheOperations",
    "RemoteImageCachePaths",
    "fetch_cached_image",
    "headers_for",
    "image_origin_stats",
    "load_image_origins",
    "note_image_origin",
    "prewarm_images",
    "trim_remote_cache",
]
