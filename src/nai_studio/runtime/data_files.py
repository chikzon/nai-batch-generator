# -*- coding: utf-8 -*-
"""사용자 자료의 프로세스 잠금·원자 저장·손상 복구 경계."""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .diagnostics import redact_diagnostic_text


_LOG = logging.getLogger("gen")
_JSON_IO_LOCK = threading.RLock()
_SHARED_DATA_THREAD_LOCK = threading.RLock()
_SHARED_DATA_LOCAL = threading.local()


@contextmanager
def shared_data_transaction(root: str | Path, timeout: float = 15.0):
    """프로필·실행본이 같은 사용자 자료를 고칠 때 한 트랜잭션씩 직렬화."""
    root = Path(root).resolve()
    lock_home = Path(tempfile.gettempdir()) / "nais-data-locks"
    lock_path = lock_home / (
        hashlib.sha256(
            os.path.normcase(str(root)).encode("utf-8")
        ).hexdigest() + ".lock"
    )
    with _SHARED_DATA_THREAD_LOCK:
        held = getattr(_SHARED_DATA_LOCAL, "held", {})
        key = str(lock_path)
        if key in held:
            held[key] += 1
            try:
                yield
            finally:
                held[key] -= 1
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        acquired = False
        deadline = time.monotonic() + max(0.1, float(timeout))
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(
                            handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "다른 실행본이 사용자 자료를 저장 중입니다. "
                            "잠시 후 다시 시도하세요."
                        )
                    time.sleep(0.05)
            held[key] = 1
            _SHARED_DATA_LOCAL.held = held
            try:
                yield
            finally:
                held.pop(key, None)
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()


def serialized_data_write(root_getter: Callable[[], str | Path]):
    """공유 자료를 고치는 공개 진입점을 프로세스 간 직렬화."""
    def decorate(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            with shared_data_transaction(root_getter()):
                return func(*args, **kwargs)
        return wrapped
    return decorate


def _atomic_write_bytes(
    path: str | Path,
    payload: bytes,
    keep_backup: bool = True,
) -> None:
    """같은 폴더 임시 파일을 fsync한 뒤 교체하고 기존 정상본을 백업."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _JSON_IO_LOCK:
        if keep_backup and path.exists():
            try:
                old = path.read_bytes()
                backup = path.with_name(path.name + ".bak")
                backup_temp = backup.with_name(
                    f".{backup.name}.{os.getpid()}."
                    f"{threading.get_ident()}.tmp"
                )
                with open(backup_temp, "wb") as stream:
                    stream.write(old)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(backup_temp, backup)
            except OSError as exc:
                _LOG.warning("JSON 백업 저장 실패(%s): %s", path.name, exc)
        temp = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with open(temp, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(
    path: str | Path,
    data: Any,
    indent: int | None = 2,
    keep_backup: bool = True,
) -> None:
    raw = json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8")
    _atomic_write_bytes(path, raw, keep_backup=keep_backup)


def atomic_write_text(
    path: str | Path,
    text: Any,
    encoding: str = "utf-8",
    keep_backup: bool = True,
) -> None:
    _atomic_write_bytes(
        path, str(text).encode(encoding), keep_backup=keep_backup)


def recoverable_remove(path: str | Path, label: str = "삭제") -> Path:
    """사용자 자료를 즉시 지우지 않고 같은 폴더의 목록 밖 백업으로 이동."""
    path = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{label}-{stamp}.bak")
    serial = 2
    while backup.exists():
        backup = path.with_name(
            f"{path.name}.{label}-{stamp}-{serial}.bak")
        serial += 1
    os.replace(path, backup)
    return backup


def load_json_recover(path: str | Path) -> Any:
    """주 JSON이 잘렸으면 마지막 정상 .bak으로 주 파일까지 복구."""
    path = Path(path)
    with _JSON_IO_LOCK:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as first:
            backup = path.with_name(path.name + ".bak")
            try:
                data = json.loads(backup.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raise first
            _LOG.error(
                "손상된 %s 대신 백업을 복구했습니다: %s", path.name, first)
            atomic_write_json(path, data, keep_backup=False)
            return data


def load_settings_recover(path: str | Path) -> dict[str, Any]:
    """설정은 JSON 객체만 정상으로 인정하고 정상 백업으로만 자동 복구."""
    path = Path(path)

    def read_dict(candidate: Path) -> dict[str, Any]:
        data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(
                f"{candidate.name}의 최상위 값은 JSON 객체여야 합니다.")
        return data

    with _JSON_IO_LOCK:
        try:
            return read_dict(path)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as first:
            backup = path.with_name(path.name + ".bak")
            try:
                data = read_dict(backup)
            except FileNotFoundError:
                raise first
            except OSError:
                raise
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise first
            _LOG.error(
                "손상된 %s 대신 객체형 백업을 복구했습니다: %s",
                path.name,
                first,
            )
            atomic_write_json(path, data, keep_backup=False)
            return data


def quarantine_corrupt_settings(
    path: str | Path,
    reason: Any,
) -> dict[str, Any]:
    """읽을 수 없는 설정과 백업을 삭제하지 않고 복구보관 폴더로 이동."""
    path = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    recovery_root = path.parent / "복구보관"
    batch = recovery_root / stamp
    serial = 2
    while batch.exists():
        batch = recovery_root / f"{stamp}-{serial}"
        serial += 1
    batch.mkdir(parents=True, exist_ok=False)
    kept = []
    for source in (path, path.with_name(path.name + ".bak")):
        if not source.is_file():
            continue
        target = batch / source.name
        os.replace(source, target)
        kept.append(target.name)
    notice = {
        "schema": "nais-startup-recovery/v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reason": redact_diagnostic_text(reason),
        "folder": str(batch),
        "files": kept,
    }
    atomic_write_json(batch / "복구기록.json", notice, keep_backup=False)
    return notice


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "load_json_recover",
    "load_settings_recover",
    "quarantine_corrupt_settings",
    "recoverable_remove",
    "serialized_data_write",
    "shared_data_transaction",
]
