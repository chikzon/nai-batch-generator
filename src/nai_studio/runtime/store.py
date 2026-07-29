# -*- coding: utf-8 -*-
"""공통 Job 계약의 파일 기반 durable 저장소.

실행 스레드나 NAI 호출을 소유하지 않는다. 한 Job을 한 JSON 파일로 원자 저장하고,
재시작 뒤 불확실한 실행 상태를 회수하는 책임만 가진다.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from .jobs import (
    reconcile_job,
    recover_job,
    snapshot_from_json,
    snapshot_to_json,
    validate_job,
)


INDEX_SCHEMA = "nai-runtime-job-index/v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_FORBIDDEN_SNAPSHOT_KEYS = frozenset((
    "access-token",
    "access_token",
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "blueprint",
    "cookie",
    "negative_prompt",
    "password",
    "payload",
    "prompt",
    "raw_payload",
    "refresh-token",
    "refresh_token",
    "secret",
    "token",
))


class JobStoreError(RuntimeError):
    """Job 저장소를 안전하게 사용할 수 없을 때의 기본 오류."""


class JobNotFoundError(JobStoreError):
    """요청한 Job 파일이 없을 때."""


class JobStoreCorruptionError(JobStoreError):
    """주 파일과 백업 어느 쪽에서도 정상 스냅샷을 읽지 못할 때."""


def _normalized_key(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "")


def _assert_no_raw_inputs(value: Any, path: str = "job") -> None:
    """방어 계층: 실행 장부에 토큰·프롬프트·원문 payload를 넣지 않는다."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in _FORBIDDEN_SNAPSHOT_KEYS:
                raise JobStoreError(
                    f"Job 스냅샷에 저장할 수 없는 원문 필드입니다: {path}.{key}")
            _assert_no_raw_inputs(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_raw_inputs(item, f"{path}[{index}]")


def _validate_index(value: Any) -> dict:
    if not isinstance(value, Mapping) or value.get("schema") != INDEX_SCHEMA:
        raise ValueError("Job 인덱스 형식이 올바르지 않습니다.")
    raw_ids = value.get("job_ids")
    if not isinstance(raw_ids, list):
        raise ValueError("Job 인덱스의 job_ids가 배열이 아닙니다.")
    ids = []
    seen = set()
    for item in raw_ids:
        identifier = str(item or "")
        if not _SAFE_ID.fullmatch(identifier):
            raise ValueError("Job 인덱스에 안전하지 않은 id가 있습니다.")
        if identifier not in seen:
            seen.add(identifier)
            ids.append(identifier)
    return {"schema": INDEX_SCHEMA, "job_ids": ids}


class JobStore:
    """프로세스 내 동시 접근을 직렬화하는 Job JSON 저장소."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise JobStoreError("Job 저장 경로가 폴더가 아닙니다.")
        self.index_path = self.root / "index.json"
        self._lock = threading.RLock()

    def _job_path(self, job_id: str) -> Path:
        identifier = str(job_id or "")
        if not _SAFE_ID.fullmatch(identifier):
            raise JobStoreError("안전하지 않은 Job id입니다.")
        candidate = (self.root / f"{identifier}.json").resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise JobStoreError("Job 경로가 저장소 밖을 가리킵니다.") from exc
        return candidate

    @staticmethod
    def _backup_path(path: Path) -> Path:
        return path.with_name(path.name + ".bak")

    @staticmethod
    def _decode_json(raw: bytes) -> Any:
        return json.loads(raw.decode("utf-8-sig"))

    def _read_candidate(
        self,
        path: Path,
        validator: Callable[[Any], dict],
    ) -> tuple[dict, bytes]:
        raw = path.read_bytes()
        return validator(self._decode_json(raw)), raw

    def _fsync_directory(self) -> None:
        """지원하는 OS에서는 이름 교체까지 디스크에 밀어낸다."""
        flags = getattr(os, "O_RDONLY", 0)
        try:
            descriptor = os.open(str(self.root), flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    def _replace_bytes(self, path: Path, payload: bytes) -> None:
        temp = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}."
            f"{uuid.uuid4().hex}.tmp")
        try:
            with open(temp, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            self._fsync_directory()
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _atomic_write(
        self,
        path: Path,
        payload: bytes,
        validator: Callable[[Any], dict],
    ) -> None:
        """기존 정상본만 .bak으로 보존한 뒤 최종 파일을 교체한다."""
        if path.exists():
            try:
                _, old = self._read_candidate(path, validator)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise JobStoreCorruptionError(
                    f"손상된 기존 파일을 덮어쓰지 않았습니다: {path.name}") from exc
            self._replace_bytes(self._backup_path(path), old)
        self._replace_bytes(path, payload)

    def _read_with_recovery(
        self,
        path: Path,
        validator: Callable[[Any], dict],
    ) -> dict:
        if not path.is_file():
            raise JobNotFoundError(f"Job 파일을 찾을 수 없습니다: {path.name}")
        try:
            value, _ = self._read_candidate(path, validator)
            return value
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as primary:
            backup = self._backup_path(path)
            try:
                value, raw = self._read_candidate(backup, validator)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as secondary:
                # 어느 쪽도 정상인지 확정할 수 없으므로 두 원본을 그대로 둔다.
                raise JobStoreCorruptionError(
                    f"{path.name}과 백업을 모두 읽지 못했습니다. "
                    "두 파일을 보존했습니다.") from secondary
            # 정상 백업이 확인된 경우에만 손상 주 파일을 교체한다. 이때 손상본을
            # 백업 위에 쓰지 않는다.
            try:
                self._replace_bytes(path, raw)
            except OSError as exc:
                raise JobStoreCorruptionError(
                    f"정상 백업을 확인했지만 {path.name} 복구에 실패했습니다.") from exc
            return value

    def _load_index(self) -> dict:
        if not self.index_path.exists():
            return {"schema": INDEX_SCHEMA, "job_ids": []}
        return self._read_with_recovery(self.index_path, _validate_index)

    def _save_index(self, value: Mapping[str, Any]) -> None:
        clean = _validate_index(value)
        payload = json.dumps(
            clean, ensure_ascii=False, sort_keys=True, indent=2,
        ).encode("utf-8")
        self._atomic_write(self.index_path, payload, _validate_index)

    def save(self, job: Mapping[str, Any]) -> dict:
        """검증된 Job 스냅샷과 인덱스를 원자 저장."""
        with self._lock:
            clean = validate_job(job)
            _assert_no_raw_inputs(clean)
            # 인덱스가 주 파일·백업 모두 손상된 경우에는 Job만 먼저 바꾸지 않는다.
            # 정상 인덱스를 확인한 다음 각각의 원자 교체를 시작한다.
            index = self._load_index()
            path = self._job_path(clean["id"])
            payload = snapshot_to_json(clean, indent=2).encode("utf-8")
            self._atomic_write(path, payload, snapshot_from_json)

            identifiers = [
                item for item in index["job_ids"] if item != clean["id"]
            ]
            identifiers.append(clean["id"])
            self._save_index({"schema": INDEX_SCHEMA, "job_ids": identifiers})
            return clean

    def get(self, job_id: str) -> dict:
        """한 Job을 읽고, 주 파일이 손상됐으면 정상 백업으로만 복구."""
        with self._lock:
            value = self._read_with_recovery(
                self._job_path(job_id), snapshot_from_json)
            _assert_no_raw_inputs(value)
            return value

    def list(self) -> list[dict]:
        """인덱스 순서로 Job을 반환하고 인덱스 누락 파일도 잃지 않는다."""
        with self._lock:
            index = self._load_index()
            identifiers = list(index["job_ids"])
            known = set(identifiers)
            for path in sorted(self.root.glob("*.json")):
                if path == self.index_path:
                    continue
                identifier = path.name[:-5]
                if _SAFE_ID.fullmatch(identifier) and identifier not in known:
                    identifiers.append(identifier)
                    known.add(identifier)

            jobs = [self.get(identifier) for identifier in identifiers]
            repaired_ids = [job["id"] for job in jobs]
            if repaired_ids != index["job_ids"]:
                self._save_index({
                    "schema": INDEX_SCHEMA,
                    "job_ids": repaired_ids,
                })
            return jobs

    def recover_all(self) -> list[dict]:
        """재시작 뒤 실행 중이던 모든 Job을 paused로 회수해 다시 저장."""
        with self._lock:
            recovered = []
            for job in self.list():
                changed = recover_job(job)
                if changed != job:
                    self.save(changed)
                recovered.append(changed)
            return recovered

    def reconcile(self, job_id: str, observation: Mapping[str, Any]) -> dict:
        """외부에서 확인한 결과·비용·진행 사실을 Job에 합쳐 저장."""
        with self._lock:
            changed = reconcile_job(self.get(job_id), observation)
            return self.save(changed)
