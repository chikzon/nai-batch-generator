# -*- coding: utf-8 -*-
"""옛 프로그램 폴더의 허용된 사용자 자료를 새 데이터 폴더로 안전 복사한다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ProgramDataMigrationPaths:
    """이전·현재 자료 뿌리와 기존 복사 허용 목록."""

    program_dir: Path
    data_dir: Path
    user_files: tuple[str, ...]
    user_dirs: tuple[str, ...]
    receipt_name: str = "이전자료-복사기록.json"
    receipt_schema: str = "nais-data-migration/v1"


@dataclass(frozen=True)
class ProgramDataMigrationOperations:
    """파일 메타데이터 복사와 영수증 원자 교체 의존성."""

    copy_file: Callable[[Any, Any], Any]
    replace_file: Callable[[Any, Any], Any]
    process_id: Callable[[], int]
    thread_id: Callable[[], int]
    now: Callable[[], Any]


def _empty_result(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "copied": 0,
        "skipped": 0,
        "conflicts": 0,
    }


def _load_receipt(receipt: Path) -> Any:
    try:
        return json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_receipt(
    operations: ProgramDataMigrationOperations,
    receipt: Path,
    result: dict[str, Any],
) -> None:
    temporary = receipt.with_name(
        f".{receipt.name}.{operations.process_id()}."
        f"{operations.thread_id()}.tmp"
    )
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    operations.replace_file(temporary, receipt)


def _same_file(source: Path, target: Path) -> bool:
    return (
        target.is_file()
        and source.is_file()
        and hashlib.sha256(target.read_bytes()).digest()
        == hashlib.sha256(source.read_bytes()).digest()
    )


def _copy_one(
    operations: ProgramDataMigrationOperations,
    result: dict[str, Any],
    source: Path,
    target: Path,
) -> None:
    if source.is_symlink():
        result["skipped"] += 1
        return
    try:
        if target.exists():
            if _same_file(source, target):
                result["skipped"] += 1
            else:
                result["conflicts"] += 1
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        operations.copy_file(source, target)
        result["copied"] += 1
    except OSError as error:
        result["errors"].append(f"{source.name}: {error}")


def _copy_allowlisted_files(
    paths: ProgramDataMigrationPaths,
    operations: ProgramDataMigrationOperations,
    result: dict[str, Any],
    source: Path,
    target: Path,
) -> None:
    for name in paths.user_files:
        candidate = source / name
        if candidate.is_file():
            _copy_one(
                operations,
                result,
                candidate,
                target / name,
            )
    for name in paths.user_dirs:
        root = source / name
        if not root.is_dir() or root.is_symlink():
            continue
        for candidate in sorted(root.rglob("*")):
            if candidate.is_file():
                _copy_one(
                    operations,
                    result,
                    candidate,
                    target / name / candidate.relative_to(root),
                )


def migrate_legacy_program_data(
    paths: ProgramDataMigrationPaths,
    operations: ProgramDataMigrationOperations,
) -> dict[str, Any]:
    """원본과 새 위치의 기존 파일을 보존하며 없는 허용 자료만 이어 복사한다."""
    source = paths.program_dir.resolve()
    target = paths.data_dir.resolve()
    if source == target:
        return _empty_result("same")
    receipt = target / paths.receipt_name
    old_receipt = _load_receipt(receipt)
    if old_receipt.get("status") == "complete":
        return old_receipt
    names = paths.user_files + paths.user_dirs
    if not any((source / name).exists() for name in names):
        return _empty_result("none")
    destination_has_data = any(
        (target / name).exists() for name in names
    )
    if (
        old_receipt.get("status") not in ("copying", "partial")
        and destination_has_data
    ):
        return _empty_result("destination-not-empty")

    target.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schema": paths.receipt_schema,
        "status": "copying",
        "source": str(source),
        "target": str(target),
        "copied": 0,
        "skipped": 0,
        "conflicts": 0,
        "errors": [],
    }
    _save_receipt(operations, receipt, result)
    _copy_allowlisted_files(
        paths, operations, result, source, target
    )
    result["status"] = (
        "complete" if not result["errors"] else "partial"
    )
    result["completed_at"] = operations.now().isoformat(
        timespec="seconds"
    )
    _save_receipt(operations, receipt, result)
    return result
