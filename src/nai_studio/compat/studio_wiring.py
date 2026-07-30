# -*- coding: utf-8 -*-
"""legacy_surface의 줄 예산을 지키기 위한 추가 배선 모음.

`legacy_surface.py`는 모듈 경계 시험이 5,500줄로 고정한다. 잔여 계획의 새
기능(3-way 병합, 수집, 갱신)의 조립은 여기에 두고, legacy에는 import와
전개 한 줄만 남긴다. 서비스는 여전히 순수하고, 여기는 경로·공통 경계를
연결만 한다.
"""
from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Callable

from src.nai_studio.runtime.data_files import (
    atomic_write_json,
    load_json_recover,
)
from src.nai_studio.services import archive_download as _archive_download
from src.nai_studio.services import collection_relay as _collection_relay
from src.nai_studio.services import evidence_merge as _evidence_merge
from src.nai_studio.services import merge_plan as _merge_plan
from src.nai_studio.services import style_store as _style_store
from src.nai_studio.services.character_storage import safe_name as _safe_name

_ARCHIVE_MANAGER: Any = None
_RELAY_PAIRING = _collection_relay.RelayPairing()


def user_backup_baseline_fields(profile_dir: Path) -> dict[str, Callable]:
    """UserBackupOperations에 얹을 3-way 기준값 배선.

    장부: `<프로필>/.nai-studio/merge-baseline.json`.
    내보내기는 `baseline_lookup`으로 읽고, 복원 적용은 `record_baseline`으로
    갱신한다.
    """
    path = _merge_plan.baseline_path(Path(profile_dir))

    def baseline_lookup(logical: str) -> dict | None:
        return _merge_plan.baseline_entry(
            _merge_plan.load_baseline(path, load_json_recover), logical)

    def record_baseline(applied: dict[str, bytes]) -> Any:
        return _merge_plan.record_applied_baseline(
            path, load_json_recover, atomic_write_json, applied)

    return {
        "baseline_lookup": baseline_lookup,
        "record_baseline": record_baseline,
    }


def extra_route_bindings(app: dict) -> dict:
    """legacy `_route_bindings()`에 합쳐지는 추가 바인딩.

    `app`은 legacy_surface의 globals()다 — 호출 시점에 읽어 기존 monkeypatch
    관행(patch.object(APP, …))이 그대로 통한다.
    """

    def evidence_compare(ids):
        paths = app["_style_store_paths"]()
        operations = app["_style_store_operations"]()
        rows = _style_store.load_styles(paths, operations)
        return _evidence_merge.dupe_compare_payload(
            rows,
            ids,
            canonical_settings=lambda record:
                _style_store.canonical_style_settings(operations, record),
            rating_for=app["style_rating"],
        )

    def evidence_merge(representative, others):
        paths = app["_style_store_paths"]()
        operations = app["_style_store_operations"]()
        with operations.transaction(paths.transaction_root):
            with operations.lock:
                rows = _style_store.load_styles(paths, operations)
                result = _evidence_merge.merge_evidence_rows(
                    rows,
                    representative,
                    others,
                    row_digest=app["_style_row_digest"],
                )
                if not result.get("ok") or not result.get("changed"):
                    result.pop("rows", None)
                    result.pop("batch", None)
                    return result
                _style_store.write_styles(
                    paths, operations, result.pop("rows"))
                result["batch"] = app["record_import_batch"](
                    result.pop("batch"))
        return result

    def archive_manager():
        """프로세스에 하나뿐인 archive 다운로드 작업. app 전역은 호출 때 읽는다."""
        global _ARCHIVE_MANAGER
        if _ARCHIVE_MANAGER is None:
            def resolve_host(host):
                return sorted({
                    item[4][0] for item in socket.getaddrinfo(host, 443)
                })

            def operations_factory(should_stop):
                return _archive_download.ArchiveDownloadOperations(
                    open_stream=lambda url, headers: app["requests"].get(
                        url,
                        headers=headers,
                        stream=True,
                        timeout=(10, 60),
                        allow_redirects=False,
                    ),
                    resolve_host=resolve_host,
                    atomic_write_json=app["atomic_write_json"],
                    load_json=app["load_json_recover"],
                    should_stop=should_stop,
                    info=app["log"].info,
                    warning=app["log"].warning,
                )

            _ARCHIVE_MANAGER = _archive_download.ArchiveDownloadManager(
                destination_root=lambda: (
                    Path(app["BASE_DIR"]) / "수집" / "받기"),
                operations_factory=operations_factory,
                safe_name=_safe_name,
            )
        return _ARCHIVE_MANAGER

    return {
        "evidence_compare": evidence_compare,
        "evidence_merge": evidence_merge,
        "archive_download_control": (
            lambda data: archive_manager().control(data)),
        "public_pairing": _RELAY_PAIRING.issue,
        "public_relay": lambda origin, code, data: (
            _collection_relay.handle_relay_payload(
                app["PUBLIC_COLLECTION"],
                _RELAY_PAIRING,
                data,
                origin=origin,
                pairing_code=code,
            )),
    }


__all__ = ["extra_route_bindings", "user_backup_baseline_fields"]
