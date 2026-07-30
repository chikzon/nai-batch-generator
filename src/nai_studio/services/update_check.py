# -*- coding: utf-8 -*-
"""공식 GitHub Release만 확인하는 제품 갱신 검사·다운로드·설치 안내.

- `update_status`: 새 버전·현재 버전·변경 요약·다운로드 크기를 먼저 보여 준다.
- `update_download`: `SHA256SUMS.txt`와 asset hash가 일치할 때만 완료로
  처리한다 (다운로드 자체는 기존 archive_download가 Range 재개·HTTPS 검증까지
  맡는다). 실패·불일치·오프라인이면 현재 버전이 그대로 남는다.
- `update_install`: 내용을 다시 확인한 뒤 installer UI를 띄운다 —
  무서명 상태에서 자동·무인 설치는 하지 않는다 (조용한 설치 플래그 금지).
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

RELEASE_API = (
    "https://api.github.com/repos/chikzon/nai-batch-generator"
    "/releases/latest"
)
# 빌드의 tools.build.app.APP_VERSION과 계약 시험으로 묶여 있다.
CURRENT_VERSION = "1.2.0"
SUMS_ASSET_NAME = "SHA256SUMS.txt"
_SETUP_SUFFIX = "-setup.exe"


@dataclass(frozen=True)
class UpdateCheckOperations:
    http_get_json: Callable[[str], Any]
    http_get_text: Callable[[str], str]
    download: Callable[..., dict]
    destination_root: Callable[[], Path]
    open_installer: Callable[[Path], Any]
    info: Callable[[str], Any] = lambda *_: None
    warning: Callable[[str], Any] = lambda *_: None


def version_tuple(text: Any) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(part) for part in parts[:4]) or (0,)


def parse_sha256sums(text: str) -> dict[str, str]:
    """`<64hex>  <파일명>` 줄들을 파일명 → 해시로 읽는다."""
    result: dict[str, str] = {}
    for line in str(text or "").splitlines():
        match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line.strip())
        if match:
            result[Path(match.group(2)).name] = match.group(1).lower()
    return result


def _release_payload(release: Any) -> dict:
    release = release if isinstance(release, dict) else {}
    assets = [
        {
            "name": str(item.get("name") or ""),
            "size": int(item.get("size") or 0),
            "url": str(item.get("browser_download_url") or ""),
        }
        for item in (release.get("assets") or [])
        if isinstance(item, dict)
    ]
    setup = next(
        (item for item in assets if item["name"].endswith(_SETUP_SUFFIX)),
        None,
    )
    sums = next(
        (item for item in assets if item["name"] == SUMS_ASSET_NAME),
        None,
    )
    latest = str(release.get("tag_name") or release.get("name") or "")
    return {
        "latest": latest.lstrip("vV"),
        "notes": str(release.get("body") or "")[:1000],
        "published_at": str(release.get("published_at") or ""),
        "page": str(release.get("html_url") or ""),
        "assets": assets,
        "setup": setup,
        "sums": sums,
        "download_size": (setup or {}).get("size", 0),
    }


class UpdateManager:
    """갱신 검사·다운로드 상태를 한 곳에 든다. 다운로드는 한 번에 하나."""

    # 다운로드 진행 중 status 폴링이 GitHub API를 연타하지 않게 잠깐 캐시한다.
    CACHE_SECONDS = 60.0

    def __init__(
        self,
        operations_factory: Callable[[], UpdateCheckOperations],
    ) -> None:
        self._operations_factory = operations_factory
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cached: tuple[float, dict] | None = None
        self._state: dict = {
            "downloading": False,
            "download_result": None,
            "downloaded": None,
        }

    def _fetch(self, operations: UpdateCheckOperations) -> dict:
        with self._lock:
            cached = self._cached
        if cached and time.monotonic() - cached[0] < self.CACHE_SECONDS:
            return dict(cached[1])
        payload = _release_payload(operations.http_get_json(RELEASE_API))
        payload["ok"] = True
        payload["current"] = CURRENT_VERSION
        payload["update_available"] = (
            version_tuple(payload["latest"]) > version_tuple(CURRENT_VERSION)
        )
        with self._lock:
            self._cached = (time.monotonic(), dict(payload))
        return payload

    def status(self) -> dict:
        operations = self._operations_factory()
        with self._lock:
            download_state = {
                "downloading": self._state["downloading"],
                "download_result": self._state["download_result"],
                "downloaded": self._state["downloaded"],
            }
        try:
            payload = self._fetch(operations)
        except Exception as exc:
            # 오프라인·API 실패 — 현재 버전은 그대로다.
            payload = {
                "ok": False,
                "current": CURRENT_VERSION,
                "error": f"갱신 정보를 확인하지 못했습니다: {exc}",
            }
        payload.update(download_state)
        return payload

    def _expected_sha(
        self,
        operations: UpdateCheckOperations,
        payload: dict,
    ) -> str:
        if not payload.get("sums"):
            raise ValueError("Release에 SHA256SUMS.txt가 없습니다.")
        sums = parse_sha256sums(
            operations.http_get_text(payload["sums"]["url"]))
        expected = sums.get(payload["setup"]["name"], "")
        if not expected:
            raise ValueError(
                "SHA256SUMS.txt에 설치본 항목이 없어 내려받지 않습니다.")
        return expected

    def download(self) -> dict:
        operations = self._operations_factory()
        with self._lock:
            if self._state["downloading"]:
                return {"ok": False, "error": "이미 내려받는 중입니다."}
        # 네트워크 확인은 잠금 밖에서 — status 조회를 막지 않는다.
        try:
            payload = self._fetch(operations)
            if not payload.get("setup"):
                return {"ok": False, "error": "Release에 설치본이 없습니다."}
            if not payload.get("update_available"):
                return {
                    "ok": False,
                    "error": "이미 최신 버전입니다.",
                    "current": CURRENT_VERSION,
                }
            expected = self._expected_sha(operations, payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        destination = (
            Path(operations.destination_root())
            / payload["setup"]["name"]
        )
        if destination.is_file():
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest == expected:
                record = {
                    "version": payload["latest"],
                    "path": str(destination),
                    "sha256": expected,
                }
                with self._lock:
                    self._state["downloaded"] = record
                    self._state["download_result"] = {
                        "ok": True, "reused": True, **record}
                return {"ok": True, "reused": True, **record}
        with self._lock:
            if self._state["downloading"]:
                return {"ok": False, "error": "이미 내려받는 중입니다."}
            self._state["downloading"] = True
            self._state["download_result"] = None
            self._thread = threading.Thread(
                target=self._run_download,
                args=(payload, expected, destination),
                daemon=True,
            )
            self._thread.start()
        return {
            "ok": True,
            "started": True,
            "destination": str(destination),
            "expected_sha256": expected,
        }

    def _run_download(
        self,
        payload: dict,
        expected: str,
        destination: Path,
    ) -> None:
        operations = self._operations_factory()
        try:
            result = operations.download(
                payload["setup"]["url"],
                destination,
                expected_sha256=expected,
            )
        except Exception as exc:
            result = {"ok": False, "error": f"내려받기 실패: {exc}"}
        with self._lock:
            self._state["downloading"] = False
            self._state["download_result"] = result
            if result.get("ok"):
                self._state["downloaded"] = {
                    "version": payload["latest"],
                    "path": str(destination),
                    "sha256": expected,
                }
                operations.info(
                    f"갱신 설치본 준비 완료: {destination.name}")

    def install(self) -> dict:
        operations = self._operations_factory()
        with self._lock:
            record = dict(self._state["downloaded"] or {})
        if not record.get("path"):
            return {
                "ok": False,
                "error": "먼저 새 버전을 내려받아 검사해야 합니다.",
            }
        path = Path(record["path"])
        root = Path(operations.destination_root()).resolve()
        if not path.is_file() or root not in path.resolve().parents:
            return {"ok": False, "error": "설치본 파일을 찾지 못했습니다."}
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record.get("sha256"):
            return {
                "ok": False,
                "error": "설치본 내용이 검사값과 달라 실행하지 않습니다.",
            }
        # installer UI를 띄울 뿐이다 — 무인 설치 플래그는 어디에도 없다.
        operations.open_installer(path)
        return {"ok": True, "started": True, "path": str(path)}


__all__ = [
    "CURRENT_VERSION",
    "RELEASE_API",
    "SUMS_ASSET_NAME",
    "UpdateCheckOperations",
    "UpdateManager",
    "parse_sha256sums",
    "version_tuple",
]
