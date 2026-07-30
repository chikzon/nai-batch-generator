# -*- coding: utf-8 -*-
"""여러 파일을 staging→검증→교체로 반영하는 재시작 안전 트랜잭션 경계.

다중 파일 교체에 완전한 원자성은 없다. 대신 journal에 단계·대상 경로·전후
SHA-256·백업 위치·완료 여부를 남겨, 어느 지점에서 중단돼도 다음 기동에서
'이어서 완료' 또는 '전체 되돌리기' 중 하나로 수렴하게 만든다.

- 자료팩·백업·병합처럼 여러 파일을 함께 바꾸는 서비스가 이 경계를 공유한다.
- `runtime/data_files.py`의 원자 저장·프로세스 잠금을 주입받아 재사용한다.
- 대상 경로는 데이터 루트 기준 상대경로만 기록한다. 토큰·쿠키는 다루지 않는다.
- 사용자 원본은 백업 없이 덮지 않고, 적용 뒤 바뀐 파일은 되돌리지 않고
  conflict로 기록해 보존한다.
"""
from __future__ import annotations

import hashlib
import os
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

TRANSACTION_SCHEMA = "nais-file-transaction/v1"
JOURNAL_DIR_PARTS = (".nai-studio", "transactions")
_FINAL_STATUSES = ("committed", "rolled-back", "abandoned", "undone")


class FileTransactionError(RuntimeError):
    """staging 검증 실패처럼 트랜잭션을 계속할 수 없는 오류."""


@dataclass(frozen=True)
class FileTransactionPaths:
    """journal·staging·백업이 데이터 루트와 같은 볼륨에 있도록 고정한다."""

    root: Path

    @property
    def journal_root(self) -> Path:
        return Path(self.root).joinpath(*JOURNAL_DIR_PARTS)


@dataclass(frozen=True)
class FileTransactionOperations:
    """기존 원자 저장·프로세스 잠금 경계를 주입받는다. `replace`는 실패 주입
    시험을 위해 os.replace를 감쌀 수 있다."""

    transaction: Callable[[Path], AbstractContextManager[Any]]
    atomic_write_bytes: Callable[..., None]
    atomic_write_json: Callable[..., None]
    load_json: Callable[[Path], Any]
    replace: Callable[[Any, Any], None]
    info: Callable[[str], Any]
    warning: Callable[[str], Any]


def _relative_target(raw: Any) -> str:
    """루트 탈출·절대경로·드라이브 지정을 거부한 상대 POSIX 경로."""
    text = str(raw).replace("\\", "/").strip()
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts) or ":" in parts[0]:
        raise FileTransactionError(f"트랜잭션 대상 경로가 올바르지 않습니다: {raw!r}")
    if text.startswith("/"):
        raise FileTransactionError(f"트랜잭션 대상은 상대경로여야 합니다: {raw!r}")
    return "/".join(parts)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _txn_dir(paths: FileTransactionPaths, journal: dict) -> Path:
    return paths.journal_root / journal["id"]


def _journal_path(paths: FileTransactionPaths, journal: dict) -> Path:
    return _txn_dir(paths, journal) / "journal.json"


def _save_journal(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
) -> None:
    journal["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    operations.atomic_write_json(
        _journal_path(paths, journal), journal, keep_backup=False)


def begin_file_transaction(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    label: str,
) -> dict:
    """staging 상태의 새 journal을 만든다. 아직 사용자 자료는 건드리지 않는다."""
    journal = {
        "schema": TRANSACTION_SCHEMA,
        "id": f"{int(time.time())}-{os.urandom(4).hex()}",
        "label": str(label or "파일 작업"),
        "status": "staging",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": [],
    }
    _save_journal(paths, operations, journal)
    return journal


def stage_file_bytes(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
    target: Any,
    payload: bytes,
) -> dict:
    """새 내용을 staging에 준비하고 journal에 SHA-256과 함께 기록한다."""
    if journal.get("status") != "staging":
        raise FileTransactionError(
            f"staging 단계가 아닌 트랜잭션입니다: {journal.get('status')}")
    relative = _relative_target(target)
    staged_rel = f"staging/{relative}"
    operations.atomic_write_bytes(
        _txn_dir(paths, journal) / staged_rel, bytes(payload),
        keep_backup=False)
    entry = {
        "target": relative,
        "staged": staged_rel,
        "new_sha256": _sha256(bytes(payload)),
        "new_size": len(payload),
        "prior_sha256": None,
        "prior_missing": None,
        "backup": None,
        "applied": False,
    }
    journal["entries"].append(entry)
    _save_journal(paths, operations, journal)
    return entry


def _apply_entry(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
    entry: dict,
) -> None:
    txn_dir = _txn_dir(paths, journal)
    staged = txn_dir / entry["staged"]
    try:
        staged_bytes = staged.read_bytes()
    except OSError as exc:
        raise FileTransactionError(
            f"staging 파일을 읽을 수 없습니다: {entry['target']} ({exc})")
    if _sha256(staged_bytes) != entry["new_sha256"]:
        raise FileTransactionError(
            f"staging 내용이 journal과 다릅니다: {entry['target']}")
    target = Path(paths.root) / entry["target"]
    if target.exists():
        prior = target.read_bytes()
        if entry.get("prior_sha256") is None:
            backup_rel = f"backup/{entry['target']}"
            operations.atomic_write_bytes(
                txn_dir / backup_rel, prior, keep_backup=False)
            entry["prior_sha256"] = _sha256(prior)
            entry["prior_missing"] = False
            entry["backup"] = backup_rel
    elif entry.get("prior_missing") is None:
        entry["prior_missing"] = True
    _save_journal(paths, operations, journal)
    target.parent.mkdir(parents=True, exist_ok=True)
    operations.replace(staged, target)
    entry["applied"] = True
    _save_journal(paths, operations, journal)


def commit_file_transaction(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
) -> dict:
    """staged 내용을 검증한 뒤 파일별 교체로 반영한다. 중단돼도 journal이
    남으므로 다음 기동에서 이어서 완료하거나 되돌릴 수 있다."""
    if journal.get("status") not in ("staging", "applying"):
        raise FileTransactionError(
            f"반영할 수 없는 상태입니다: {journal.get('status')}")
    with operations.transaction(paths.root):
        journal["status"] = "applying"
        _save_journal(paths, operations, journal)
        for entry in journal["entries"]:
            if not entry.get("applied"):
                _apply_entry(paths, operations, journal, entry)
        journal["status"] = "committed"
        _save_journal(paths, operations, journal)
    applied = sum(1 for entry in journal["entries"] if entry.get("applied"))
    operations.info(
        f"파일 트랜잭션 반영 완료: {journal['label']} · {applied}개")
    return {"ok": True, "id": journal["id"], "applied": applied}


def _revert_entry(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
    entry: dict,
) -> str:
    """적용된 항목 하나를 원상으로. 적용 뒤 사용자가 바꾼 파일은 건드리지 않는다."""
    target = Path(paths.root) / entry["target"]
    current = target.read_bytes() if target.exists() else None
    current_sha = _sha256(current) if current is not None else None
    if entry.get("prior_missing"):
        if current is None or current_sha == entry.get("prior_sha256"):
            return "restored"
        if current_sha != entry["new_sha256"]:
            return "conflict"
        removed_rel = f"backup/새파일보관/{entry['target']}"
        operations.atomic_write_bytes(
            _txn_dir(paths, journal) / removed_rel, current,
            keep_backup=False)
        target.unlink()
        return "restored"
    backup = _txn_dir(paths, journal) / str(entry.get("backup"))
    try:
        prior = backup.read_bytes()
    except OSError:
        return "conflict"
    if _sha256(prior) != entry.get("prior_sha256"):
        return "conflict"
    if current_sha == entry.get("prior_sha256"):
        return "restored"
    if current is not None and current_sha != entry["new_sha256"]:
        return "conflict"
    operations.atomic_write_bytes(target, prior, keep_backup=False)
    return "restored"


def _rollback(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
    final_status: str,
) -> dict:
    restored, conflicts = [], []
    # 중단돼도 방향이 남도록 되돌리기 진행 상태를 먼저 기록한다.
    journal["status"] = "rolling-back"
    journal["final_status"] = final_status
    _save_journal(paths, operations, journal)
    for entry in reversed(journal["entries"]):
        if not entry.get("applied"):
            continue
        outcome = _revert_entry(paths, operations, journal, entry)
        (restored if outcome == "restored" else conflicts).append(
            entry["target"])
        if outcome == "restored":
            entry["applied"] = False
            _save_journal(paths, operations, journal)
    journal["status"] = final_status
    journal.pop("final_status", None)
    journal["conflicts"] = conflicts
    _save_journal(paths, operations, journal)
    if conflicts:
        operations.warning(
            "파일 트랜잭션 되돌리기 중 사용자 수정 파일을 보존했습니다: "
            + ", ".join(conflicts))
    return {
        "ok": not conflicts,
        "id": journal["id"],
        "restored": restored,
        "conflicts": conflicts,
    }


def rollback_file_transaction(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    journal: dict,
) -> dict:
    """미완 트랜잭션을 백업으로 전체 되돌린다."""
    with operations.transaction(paths.root):
        return _rollback(paths, operations, journal, "rolled-back")


def undo_file_transaction(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
    transaction_id: str,
) -> dict:
    """반영이 끝난 트랜잭션 한 판을 백업으로 되돌린다 (한 판 Undo)."""
    journal_path = (
        paths.journal_root / str(transaction_id) / "journal.json")
    if not journal_path.is_file():
        return {"ok": False, "error": "되돌릴 작업 기록이 없습니다."}
    journal = operations.load_json(journal_path)
    if journal.get("status") != "committed":
        return {
            "ok": False,
            "error": f"되돌릴 수 없는 상태입니다: {journal.get('status')}",
        }
    with operations.transaction(paths.root):
        return _rollback(paths, operations, journal, "undone")


def _staged_all_valid(paths: FileTransactionPaths, journal: dict) -> bool:
    txn_dir = _txn_dir(paths, journal)
    for entry in journal["entries"]:
        if entry.get("applied"):
            continue
        staged = txn_dir / entry["staged"]
        try:
            if _sha256(staged.read_bytes()) != entry["new_sha256"]:
                return False
        except OSError:
            return False
    return True


def _recovery_notice(journal: dict, action: str, result: dict) -> dict:
    """기존 시작 복구 배너(STARTUP_RECOVERY_NOTICE)가 그대로 보여줄 수 있는 모양."""
    return {
        "schema": "nais-startup-recovery/v1",
        "kind": "file-transaction",
        "action": action,
        "id": journal["id"],
        "label": journal.get("label", ""),
        "files": [entry["target"] for entry in journal["entries"]],
        "folder": journal.get("_folder", ""),
        "conflicts": result.get("conflicts", []),
    }


def recover_file_transactions(
    paths: FileTransactionPaths,
    operations: FileTransactionOperations,
) -> list[dict]:
    """기동 시 미완 journal을 수렴시킨다. staged가 전부 검증되면 이어서 완료,
    아니면 백업으로 전체 되돌린다. 반환된 알림은 시작 배너로 전달된다."""
    journal_root = paths.journal_root
    if not journal_root.is_dir():
        return []
    notices: list[dict] = []
    with operations.transaction(paths.root):
        for journal_path in sorted(journal_root.glob("*/journal.json")):
            try:
                journal = operations.load_json(journal_path)
            except Exception as exc:
                operations.warning(
                    f"트랜잭션 journal을 읽지 못했습니다: {journal_path} ({exc})")
                continue
            status = journal.get("status")
            if status in _FINAL_STATUSES:
                continue
            journal["_folder"] = str(journal_path.parent)
            if status == "staging":
                journal["status"] = "abandoned"
                journal.pop("_folder", None)
                _save_journal(paths, operations, journal)
                continue
            if status == "rolling-back":
                # 되돌리던 중 중단 — 같은 방향으로 끝까지 되돌린다.
                folder = journal.pop("_folder", "")
                final = journal.get("final_status", "rolled-back")
                result = _rollback(paths, operations, journal, final)
                journal["_folder"] = folder
                notices.append(
                    _recovery_notice(journal, "rolled-back", result))
                continue
            if status != "applying":
                operations.warning(
                    f"알 수 없는 트랜잭션 상태를 건너뜁니다: {status}")
                continue
            if _staged_all_valid(paths, journal):
                folder = journal.pop("_folder", "")
                for entry in journal["entries"]:
                    if not entry.get("applied"):
                        _apply_entry(paths, operations, journal, entry)
                journal["status"] = "committed"
                _save_journal(paths, operations, journal)
                journal["_folder"] = folder
                notices.append(_recovery_notice(
                    journal, "resumed", {"conflicts": []}))
                operations.info(
                    f"중단된 파일 트랜잭션을 이어서 완료했습니다: "
                    f"{journal['label']}")
            else:
                folder = journal.pop("_folder", "")
                result = _rollback(paths, operations, journal, "rolled-back")
                journal["_folder"] = folder
                notices.append(_recovery_notice(journal, "rolled-back", result))
                operations.info(
                    f"중단된 파일 트랜잭션을 되돌렸습니다: {journal['label']}")
    return notices


__all__ = [
    "TRANSACTION_SCHEMA",
    "FileTransactionError",
    "FileTransactionOperations",
    "FileTransactionPaths",
    "begin_file_transaction",
    "commit_file_transaction",
    "recover_file_transactions",
    "rollback_file_transaction",
    "stage_file_bytes",
    "undo_file_transaction",
]
