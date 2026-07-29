# -*- coding: utf-8 -*-
"""자료 색인과 메타데이터 감사 서비스를 잇는 파일 시스템 어댑터.

판독 규칙은 호출자가 주입하고, 이 모듈은 ``BASE_DIR`` 안의 색인 파일을 읽는
일과 안전한 감사 장부를 원자적으로 교체하는 일만 담당한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from .metadata_audit import (
    MAX_AUDIT_CHUNK,
    METADATA_AUDIT_SCHEMA,
    MetadataInspector,
    canonical_metadata_audit,
    metadata_audit_bundle,
    metadata_audit_failures,
    metadata_audit_summary,
    new_metadata_audit,
    pause_metadata_audit,
    resume_metadata_audit,
    retry_metadata_failures,
    run_metadata_audit_chunk,
)


DATA_INDEX_SCHEMA = "nais-data-index/v1"
DEFAULT_LEDGER_PARTS = (".nai-studio", "metadata-audit.json")


class MetadataAuditAdapterError(RuntimeError):
    """메타데이터 감사 앱 경계의 기본 오류."""


class MetadataAuditPathError(MetadataAuditAdapterError):
    """읽기 또는 저장 경로가 ``BASE_DIR`` 밖을 가리킬 때 발생한다."""


class MetadataAuditLedgerError(MetadataAuditAdapterError):
    """감사 장부가 없거나 올바른 JSON 계약이 아닐 때 발생한다."""


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate != root


class MetadataAuditAdapter:
    """기존 자료 색인을 최대 500개 단위의 안전한 감사 실행으로 연결한다."""

    def __init__(
        self,
        base_dir: Path | str,
        *,
        metadata_inspector: MetadataInspector,
        ledger_path: Path | str | None = None,
    ):
        self.base_dir = Path(base_dir).resolve()
        if not self.base_dir.is_dir():
            raise MetadataAuditPathError("BASE_DIR가 존재하는 폴더가 아닙니다.")
        if not callable(metadata_inspector):
            raise TypeError("metadata_inspector는 호출 가능해야 합니다.")
        self.metadata_inspector = metadata_inspector
        raw_ledger = (
            Path(ledger_path)
            if ledger_path is not None
            else self.base_dir.joinpath(*DEFAULT_LEDGER_PARTS)
        )
        if not raw_ledger.is_absolute():
            raw_ledger = self.base_dir / raw_ledger
        self.ledger_path = raw_ledger.resolve()
        if not _inside(self.base_dir, self.ledger_path):
            raise MetadataAuditPathError(
                "감사 장부는 BASE_DIR 안에 있어야 합니다."
            )
        self._lock = threading.RLock()

    def _owned_path(self, relative_path: str) -> Path:
        """색인의 POSIX 상대 경로를 BASE_DIR 안의 실제 파일로 제한한다."""
        text = str(relative_path or "").strip().replace("\\", "/")
        pure = PurePosixPath(text)
        if (
            not text
            or pure.is_absolute()
            or ".." in pure.parts
            or "://" in text
        ):
            raise MetadataAuditPathError("안전한 상대 경로가 아닙니다.")
        candidate = self.base_dir.joinpath(*pure.parts).resolve()
        if not _inside(self.base_dir, candidate):
            raise MetadataAuditPathError(
                "색인 항목이 BASE_DIR 밖을 가리킵니다."
            )
        return candidate

    def _reader(self, entry: Mapping[str, str]) -> bytes:
        path = self._owned_path(str(entry.get("path") or ""))
        return path.read_bytes()

    def _fsync_directory(self) -> None:
        flags = getattr(os, "O_RDONLY", 0)
        try:
            descriptor = os.open(str(self.ledger_path.parent), flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    def _atomic_save(self, state: Mapping[str, Any]) -> dict:
        """검증·정제한 장부만 같은 폴더의 임시 파일에서 원자 교체한다."""
        clean = canonical_metadata_audit(state)
        payload = json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.ledger_path.with_name(
            f".{self.ledger_path.name}.{os.getpid()}."
            f"{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with open(temp, "xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.ledger_path)
            self._fsync_directory()
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return clean

    def _load_unlocked(self) -> dict:
        if not self.ledger_path.is_file():
            raise MetadataAuditLedgerError("메타데이터 감사 장부가 없습니다.")
        try:
            raw = self.ledger_path.read_bytes()
            value = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MetadataAuditLedgerError(
                "메타데이터 감사 장부를 읽을 수 없습니다."
            ) from error
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != METADATA_AUDIT_SCHEMA
            or not isinstance(value.get("items"), list)
        ):
            raise MetadataAuditLedgerError(
                "메타데이터 감사 장부 계약이 올바르지 않습니다."
            )
        return canonical_metadata_audit(value)

    def load(self) -> dict:
        with self._lock:
            return self._load_unlocked()

    @staticmethod
    def _light_bundle(
        state: Mapping[str, Any],
        *,
        failure_limit: int = 50,
        found_offset: int = 0,
        found_limit: int = 50,
    ) -> dict:
        """HTTP/UI용 경량 상태.

        전체 ``items``와 전체 복원 큐를 매 조회마다 직렬화하지 않는다. 수만 개
        자료에서도 화면에는 수치와 현재 쪽의 상대 경로·SHA만 보낸다.
        """
        clean = canonical_metadata_audit(state)
        failure_limit = max(0, min(500, int(failure_limit or 0)))
        found_offset = max(0, int(found_offset or 0))
        found_limit = max(0, min(500, int(found_limit or 0)))
        found = [
            {"path": item["path"], "sha256": item["sha256"]}
            for item in clean["items"]
            if item["status"] == "found"
        ]
        return {
            "summary": metadata_audit_summary(clean),
            "failures": metadata_audit_failures(clean)[:failure_limit],
            "found": found[found_offset:found_offset + found_limit],
            "found_offset": found_offset,
            "found_more": found_offset + found_limit < len(found),
        }

    def status_light(
        self,
        *,
        failure_limit: int = 50,
        found_offset: int = 0,
        found_limit: int = 50,
    ) -> dict:
        with self._lock:
            return self._light_bundle(
                self._load_unlocked(),
                failure_limit=failure_limit,
                found_offset=found_offset,
                found_limit=found_limit,
            )

    def start(
        self,
        data_index: Mapping[str, Any],
        *,
        chunk_size: int = MAX_AUDIT_CHUNK,
    ) -> dict:
        """기존 자료 색인 항목을 원문 없는 감사 대기열로 바꾸고 저장한다."""
        if (
            not isinstance(data_index, Mapping)
            or data_index.get("schema") != DATA_INDEX_SCHEMA
            or not isinstance(data_index.get("entries"), list)
        ):
            raise MetadataAuditAdapterError(
                "기존 자료 색인 계약이 올바르지 않습니다."
            )
        try:
            ledger_relative = self.ledger_path.relative_to(
                self.base_dir
            ).as_posix()
        except ValueError as error:  # 생성자 경계의 방어적 재확인
            raise MetadataAuditPathError(
                "감사 장부는 BASE_DIR 안에 있어야 합니다."
            ) from error
        entries = [
            entry
            for entry in data_index["entries"]
            if not (
                isinstance(entry, Mapping)
                and str(entry.get("path") or "").replace("\\", "/")
                == ledger_relative
            )
        ]
        with self._lock:
            state = new_metadata_audit(entries, chunk_size=chunk_size)
            clean = self._atomic_save(state)
            return metadata_audit_bundle(clean)

    def start_light(
        self,
        data_index: Mapping[str, Any],
        *,
        chunk_size: int = MAX_AUDIT_CHUNK,
    ) -> dict:
        if (
            not isinstance(data_index, Mapping)
            or data_index.get("schema") != DATA_INDEX_SCHEMA
            or not isinstance(data_index.get("entries"), list)
        ):
            raise MetadataAuditAdapterError(
                "기존 자료 색인 계약이 올바르지 않습니다."
            )
        ledger_relative = self.ledger_path.relative_to(
            self.base_dir).as_posix()
        entries = [
            entry
            for entry in data_index["entries"]
            if not (
                isinstance(entry, Mapping)
                and str(entry.get("path") or "").replace("\\", "/")
                == ledger_relative
            )
        ]
        with self._lock:
            clean = self._atomic_save(new_metadata_audit(
                entries,
                chunk_size=chunk_size,
            ))
            return self._light_bundle(clean)

    def status(self) -> dict:
        with self._lock:
            return metadata_audit_bundle(self._load_unlocked())

    def run_chunk(self) -> dict:
        """대기 상태에서 한 묶음을 실행한다. 일시 정지 상태는 그대로 둔다."""
        with self._lock:
            state = run_metadata_audit_chunk(
                self._load_unlocked(),
                reader=self._reader,
                metadata_inspector=self.metadata_inspector,
            )
            clean = self._atomic_save(state)
            return metadata_audit_bundle(clean)

    def run_chunk_light(self) -> dict:
        with self._lock:
            state = run_metadata_audit_chunk(
                self._load_unlocked(),
                reader=self._reader,
                metadata_inspector=self.metadata_inspector,
            )
            clean = self._atomic_save(state)
            return self._light_bundle(clean)

    def pause(self) -> dict:
        with self._lock:
            state = pause_metadata_audit(self._load_unlocked())
            clean = self._atomic_save(state)
            return metadata_audit_bundle(clean)

    def pause_light(self) -> dict:
        with self._lock:
            clean = self._atomic_save(
                pause_metadata_audit(self._load_unlocked()))
            return self._light_bundle(clean)

    def resume(self) -> dict:
        """정지 지점에서 다음 묶음 하나를 실행하고 결과를 저장한다."""
        with self._lock:
            state = resume_metadata_audit(
                self._load_unlocked(),
                reader=self._reader,
                metadata_inspector=self.metadata_inspector,
            )
            clean = self._atomic_save(state)
            return metadata_audit_bundle(clean)

    def resume_light(self) -> dict:
        with self._lock:
            state = resume_metadata_audit(
                self._load_unlocked(),
                reader=self._reader,
                metadata_inspector=self.metadata_inspector,
            )
            clean = self._atomic_save(state)
            return self._light_bundle(clean)

    def retry(self, *, paths: Iterable[str] | None = None) -> dict:
        """전체 또는 선택 실패 항목을 같은 색인 SHA로 다시 읽어 저장한다."""
        with self._lock:
            state = retry_metadata_failures(
                self._load_unlocked(),
                reader=self._reader,
                metadata_inspector=self.metadata_inspector,
                paths=paths,
            )
            clean = self._atomic_save(state)
            return metadata_audit_bundle(clean)

    def retry_light(self, *, paths: Iterable[str] | None = None) -> dict:
        with self._lock:
            state = retry_metadata_failures(
                self._load_unlocked(),
                reader=self._reader,
                metadata_inspector=self.metadata_inspector,
                paths=paths,
            )
            clean = self._atomic_save(state)
            return self._light_bundle(clean)

    def read_verified(self, relative_path: str, sha256: str) -> bytes:
        """사용자가 고른 후보 한 건만 현재 색인 SHA와 대조해 읽는다."""
        request = {"path": str(relative_path or ""), "sha256": str(sha256 or "")}
        payload = self._reader(request)
        if hashlib.sha256(payload).hexdigest() != request["sha256"].lower():
            raise MetadataAuditAdapterError(
                "색인 뒤 파일 내용이 바뀌었습니다. 색인을 다시 만드세요."
            )
        return payload


__all__ = [
    "DATA_INDEX_SCHEMA",
    "DEFAULT_LEDGER_PARTS",
    "MetadataAuditAdapter",
    "MetadataAuditAdapterError",
    "MetadataAuditLedgerError",
    "MetadataAuditPathError",
]
