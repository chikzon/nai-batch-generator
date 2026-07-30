# -*- coding: utf-8 -*-
"""대형 archive의 HTTP Range 재개 다운로드.

`.part` 파일과 versioned sidecar 상태로 중단 지점을 기록한다. 이어받기는
URL·ETag/Last-Modified·받은 크기·부분 SHA-256이 전부 일치할 때만 하고,
하나라도 어긋나면 처음부터 다시 받는다 — 반쯤 섞인 파일을 만들지 않는다.

- HTTPS만 허용하고 loopback·사설망·링크로컬 주소와 그런 곳으로 가는
  redirect를 차단한다.
- sidecar는 download state 계약(`nais-archive-download/v1`)만 담는다.
  쿠키·토큰은 다루지 않는다.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

DOWNLOAD_STATE_SCHEMA = "nais-archive-download/v1"
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class ArchiveDownloadError(RuntimeError):
    """주소 검증 실패·크기 초과처럼 계속할 수 없는 다운로드 오류."""


@dataclass(frozen=True)
class ArchiveDownloadOperations:
    """스트림·이름 풀이·원자 저장을 주입받는다 (시험은 가짜 스트림을 넣는다)."""

    open_stream: Callable[[str, dict], Any]
    resolve_host: Callable[[str], list[str]]
    atomic_write_json: Callable[..., None]
    load_json: Callable[[Path], Any]
    replace: Callable[[Any, Any], None] = os.replace
    should_stop: Callable[[], bool] = field(default=lambda: False)
    info: Callable[[str], Any] = field(default=lambda *_: None)
    warning: Callable[[str], Any] = field(default=lambda *_: None)


def validate_archive_url(
    url: str,
    resolve_host: Callable[[str], list[str]],
) -> str:
    """HTTPS·공인 주소만 허용한다. redirect 각 단계에도 다시 적용된다."""
    parts = urlsplit(str(url or ""))
    if parts.scheme != "https":
        raise ArchiveDownloadError("HTTPS 주소만 받을 수 있습니다.")
    host = parts.hostname or ""
    if not host:
        raise ArchiveDownloadError("주소에 호스트가 없습니다.")
    try:
        literal = [str(ipaddress.ip_address(host))]
    except ValueError:
        literal = None
    try:
        addresses = literal or [str(item) for item in resolve_host(host)]
    except ArchiveDownloadError:
        raise
    except Exception as exc:
        raise ArchiveDownloadError(f"주소를 풀 수 없습니다: {host} ({exc})")
    if not addresses:
        raise ArchiveDownloadError(f"주소를 풀 수 없습니다: {host}")
    for address in addresses:
        value = ipaddress.ip_address(address)
        if (
            value.is_loopback
            or value.is_private
            or value.is_link_local
            or value.is_reserved
            or value.is_multicast
            or value.is_unspecified
        ):
            raise ArchiveDownloadError(
                f"내부망 주소로는 받지 않습니다: {host} → {address}")
    return str(url)


def _paths_for(destination: Path) -> tuple[Path, Path]:
    part = destination.with_name(destination.name + ".part")
    sidecar = destination.with_name(destination.name + ".download.json")
    return part, sidecar


def _load_state(
    operations: ArchiveDownloadOperations,
    sidecar: Path,
    url: str,
) -> dict | None:
    if not sidecar.is_file():
        return None
    try:
        state = operations.load_json(sidecar)
    except Exception:
        return None
    if (
        not isinstance(state, dict)
        or state.get("schema") != DOWNLOAD_STATE_SCHEMA
        or state.get("url") != url
    ):
        return None
    return state


def _resume_hasher(
    operations: ArchiveDownloadOperations,
    part: Path,
    state: dict | None,
) -> tuple[Any, int]:
    """checkpoint까지의 .part를 재해시해 이어받을 지점과 해시 상태를 만든다.

    checkpoint보다 긴 .part는 기록 지점까지 잘라 살리고, 부분 해시가
    어긋나면 처음부터 다시 받는다.
    """
    hasher = hashlib.sha256()
    if state is None or not part.is_file():
        return hasher, 0
    received = int(state.get("received") or 0)
    if received <= 0 or part.stat().st_size < received:
        return hashlib.sha256(), 0
    if part.stat().st_size > received:
        with open(part, "r+b") as stream:
            stream.truncate(received)
    with open(part, "rb") as stream:
        remaining = received
        while remaining > 0:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            hasher.update(chunk)
            remaining -= len(chunk)
    if remaining or hasher.hexdigest() != state.get("partial_sha256"):
        operations.warning("받다 만 파일이 기록과 달라 처음부터 다시 받습니다.")
        return hashlib.sha256(), 0
    return hasher, received


def _open_with_redirects(
    operations: ArchiveDownloadOperations,
    url: str,
    headers: dict,
    max_redirects: int,
) -> tuple[Any, str]:
    current = url
    for _ in range(max_redirects + 1):
        validate_archive_url(current, operations.resolve_host)
        response = operations.open_stream(current, dict(headers))
        status = int(getattr(response, "status_code", 0))
        if status in _REDIRECT_STATUSES:
            location = (getattr(response, "headers", {}) or {}).get("Location")
            close = getattr(response, "close", None)
            if close:
                close()
            if not location:
                raise ArchiveDownloadError("redirect에 목적지가 없습니다.")
            current = urljoin(current, str(location))
            continue
        return response, current
    raise ArchiveDownloadError("redirect가 너무 많습니다.")


def _validators_match(state: dict, headers: Any) -> bool:
    etag = str(headers.get("ETag") or "")
    last_modified = str(headers.get("Last-Modified") or "")
    known_etag = str(state.get("etag") or "")
    known_modified = str(state.get("last_modified") or "")
    if known_etag and etag:
        return known_etag == etag
    if known_modified and last_modified:
        return known_modified == last_modified
    return False


def _save_state(
    operations: ArchiveDownloadOperations,
    sidecar: Path,
    url: str,
    headers: Any,
    expected_size: int,
    received: int,
    hasher: Any,
) -> None:
    operations.atomic_write_json(sidecar, {
        "schema": DOWNLOAD_STATE_SCHEMA,
        "url": url,
        "etag": str(headers.get("ETag") or ""),
        "last_modified": str(headers.get("Last-Modified") or ""),
        "expected_size": expected_size,
        "received": received,
        "partial_sha256": hasher.hexdigest(),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, keep_backup=False)


def download_archive(
    operations: ArchiveDownloadOperations,
    url: str,
    destination: str | Path,
    *,
    expected_sha256: str = "",
    max_bytes: int = 8 * 1024 ** 3,
    chunk_size: int = 1024 * 1024,
    checkpoint_bytes: int = 8 * 1024 * 1024,
    max_redirects: int = 5,
) -> dict:
    """archive 하나를 재개 가능하게 받는다.

    반환: {ok, path, bytes, sha256, resumed} 또는
    {ok: False, error, resumable(중단·재시도 가능 여부)}.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part, sidecar = _paths_for(destination)
    state = _load_state(operations, sidecar, str(url))
    hasher, resume_from = _resume_hasher(operations, part, state)

    headers: dict = {}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"
    response, final_url = _open_with_redirects(
        operations, str(url), headers, max_redirects)
    try:
        status = int(getattr(response, "status_code", 0))
        response_headers = getattr(response, "headers", {}) or {}
        resumed = False
        if resume_from > 0 and status == 206 and state is not None:
            content_range = str(response_headers.get("Content-Range") or "")
            if (
                _validators_match(state, response_headers)
                and content_range.startswith(f"bytes {resume_from}-")
            ):
                resumed = True
            else:
                operations.warning(
                    "서버 내용이 바뀌어 처음부터 다시 받습니다.")
        if not resumed:
            if status == 206:
                # 검증에 실패한 206은 신뢰하지 않는다 — 전체를 다시 요청한다.
                close = getattr(response, "close", None)
                if close:
                    close()
                response, final_url = _open_with_redirects(
                    operations, str(url), {}, max_redirects)
                status = int(getattr(response, "status_code", 0))
                response_headers = getattr(response, "headers", {}) or {}
            if status != 200:
                return {
                    "ok": False,
                    "resumable": status in (429, 500, 502, 503, 504),
                    "error": f"다운로드 응답이 올바르지 않습니다: {status}",
                }
            hasher, resume_from = hashlib.sha256(), 0

        length = response_headers.get("Content-Length")
        expected_size = (
            resume_from + int(length)
            if str(length or "").isdigit()
            else int((state or {}).get("expected_size") or 0)
        )
        if expected_size and expected_size > max_bytes:
            return {
                "ok": False,
                "resumable": False,
                "error": f"허용 크기를 넘습니다: {expected_size:,}바이트",
            }

        received = resume_from
        last_checkpoint = received
        mode = "ab" if resumed else "wb"
        with open(part, mode) as stream:
            for chunk in response.iter_content(chunk_size):
                if operations.should_stop():
                    stream.flush()
                    os.fsync(stream.fileno())
                    _save_state(
                        operations, sidecar, str(url), response_headers,
                        expected_size, received, hasher)
                    return {
                        "ok": False,
                        "resumable": True,
                        "error": "중지 요청으로 멈췄습니다. 이어받을 수 있습니다.",
                        "received": received,
                    }
                if not chunk:
                    continue
                received += len(chunk)
                if received > max_bytes:
                    return {
                        "ok": False,
                        "resumable": False,
                        "error": f"허용 크기를 넘습니다: {received:,}바이트+",
                    }
                stream.write(chunk)
                hasher.update(chunk)
                if received - last_checkpoint >= checkpoint_bytes:
                    stream.flush()
                    os.fsync(stream.fileno())
                    _save_state(
                        operations, sidecar, str(url), response_headers,
                        expected_size, received, hasher)
                    last_checkpoint = received
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        close = getattr(response, "close", None)
        if close:
            close()

    if expected_size and received != expected_size:
        _save_state(
            operations, sidecar, str(url), response_headers,
            expected_size, received, hasher)
        return {
            "ok": False,
            "resumable": True,
            "error": (
                f"받은 크기가 예상과 다릅니다: {received:,}"
                f"/{expected_size:,}바이트"
            ),
            "received": received,
        }
    digest = hasher.hexdigest()
    if expected_sha256 and digest != str(expected_sha256).lower():
        part.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        return {
            "ok": False,
            "resumable": False,
            "error": "내용 SHA-256이 기대값과 다릅니다. 파일을 버렸습니다.",
        }
    operations.replace(part, destination)
    sidecar.unlink(missing_ok=True)
    operations.info(
        f"archive 다운로드 완료: {destination.name} · {received:,}바이트")
    return {
        "ok": True,
        "path": str(destination),
        "bytes": received,
        "sha256": digest,
        "resumed": resumed,
        "final_url": final_url,
    }


class ArchiveDownloadManager:
    """archive를 한 번에 하나씩 받는 백그라운드 작업.

    진행 상태의 진실은 sidecar다 — 조회는 sidecar를 읽고, 재시작 후에도
    같은 URL이면 이어받는다. 쿠키·토큰은 저장하지 않는다.
    """

    def __init__(
        self,
        destination_root: Callable[[], Path],
        operations_factory: Callable[
            [Callable[[], bool]], ArchiveDownloadOperations],
        *,
        download: Callable[..., dict] = download_archive,
        safe_name: Callable[[str], str] | None = None,
    ) -> None:
        self._destination_root = destination_root
        self._operations_factory = operations_factory
        self._download = download
        self._safe_name = safe_name or (lambda value: value)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state: dict = {
            "running": False,
            "url": "",
            "destination": "",
            "result": None,
        }

    def _destination_for(self, url: str, filename: str) -> Path:
        name = self._safe_name(
            str(filename or "").strip()
            or Path(urlsplit(str(url)).path).name
            or "archive.zip"
        )
        root = Path(self._destination_root())
        target = (root / name).resolve()
        if root.resolve() != target.parent:
            raise ArchiveDownloadError("받을 파일 이름이 올바르지 않습니다.")
        return target

    def start(
        self,
        url: Any,
        filename: str = "",
        expected_sha256: str = "",
        max_bytes: Any = None,
    ) -> dict:
        with self._lock:
            if self._state["running"]:
                return {
                    "ok": False,
                    "error": "이미 받는 중입니다. 멈추거나 끝난 뒤 시작하세요.",
                }
            operations = self._operations_factory(self._stop.is_set)
            try:
                validate_archive_url(str(url or ""), operations.resolve_host)
                destination = self._destination_for(str(url), filename)
            except ArchiveDownloadError as exc:
                return {"ok": False, "error": str(exc)}
            self._stop.clear()
            self._state.update(
                running=True,
                url=str(url),
                destination=str(destination),
                result=None,
            )
            extra = {}
            if max_bytes is not None:
                extra["max_bytes"] = int(max_bytes)
            self._thread = threading.Thread(
                target=self._run,
                args=(str(url), destination, str(expected_sha256 or ""), extra),
                daemon=True,
            )
            self._thread.start()
            return {"ok": True, "destination": str(destination)}

    def _run(
        self,
        url: str,
        destination: Path,
        expected_sha256: str,
        extra: dict,
    ) -> None:
        operations = self._operations_factory(self._stop.is_set)
        try:
            result = self._download(
                operations,
                url,
                destination,
                expected_sha256=expected_sha256,
                **extra,
            )
        except ArchiveDownloadError as exc:
            result = {"ok": False, "resumable": False, "error": str(exc)}
        except Exception as exc:
            # 네트워크 단절 — checkpoint까지는 sidecar에 있으니 이어받는다.
            result = {
                "ok": False,
                "resumable": True,
                "error": f"연결이 끊겼습니다: {exc}",
            }
        with self._lock:
            self._state.update(running=False, result=result)

    def snapshot(self) -> dict:
        with self._lock:
            state = dict(self._state)
        destination = state.get("destination") or ""
        if destination:
            sidecar = Path(destination).with_name(
                Path(destination).name + ".download.json")
            if sidecar.is_file():
                try:
                    operations = self._operations_factory(lambda: False)
                    saved = operations.load_json(sidecar)
                    state["received"] = int(saved.get("received") or 0)
                    state["expected_size"] = int(
                        saved.get("expected_size") or 0)
                except Exception:
                    pass
        state["ok"] = True
        return state

    def control(self, data: Any) -> dict:
        data = data if isinstance(data, dict) else {}
        action = str(data.get("action") or "status").strip().lower()
        if action == "start":
            return self.start(
                data.get("url"),
                filename=str(data.get("filename") or ""),
                expected_sha256=str(data.get("sha256") or ""),
                max_bytes=data.get("max_bytes"),
            )
        if action == "stop":
            self._stop.set()
            return {"ok": True, "stopping": True}
        if action == "status":
            return self.snapshot()
        return {"ok": False, "error": f"모르는 동작입니다: {action}"}


__all__ = [
    "ArchiveDownloadError",
    "ArchiveDownloadManager",
    "ArchiveDownloadOperations",
    "DOWNLOAD_STATE_SCHEMA",
    "download_archive",
    "validate_archive_url",
]
