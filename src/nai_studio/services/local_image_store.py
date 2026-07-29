# -*- coding: utf-8 -*-
"""자료 JSON의 local: 이미지 참조를 감사·정규화·복원하는 저장 경계."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .datapack_store import content_image_name, rewrite_local_image_refs


@dataclass(frozen=True)
class LocalImagePaths:
    """프로필별 자료와 이미지 캐시 위치 및 기존 장부 계약."""

    base_dir: Path
    image_cache: Path
    image_suffixes: tuple[str, ...] = (
        ".webp",
        ".png",
        ".jpg",
        ".jpeg",
    )
    record_dir_name: str = "이미지무결성기록"
    journal_schema: str = "nais-local-image-normalize/v1"

    @property
    def collection_dir(self) -> Path:
        return self.base_dir / "수집"


@dataclass(frozen=True)
class LocalImageOperations:
    """원자 저장·직렬화·시간 의존성을 현재 실행 환경에 늦게 연결한다."""

    transaction: Callable[[Path], AbstractContextManager[Any]]
    lock: Any
    atomic_write_bytes: Callable[..., None]
    atomic_write_json: Callable[..., None]
    forget_caches: Callable[[], Any]
    now: Callable[[], Any]
    unix_time: Callable[[], float]
    random_bytes: Callable[[int], bytes]
    replace_file: Callable[[Any, Any], Any]


def collect_local_refs(value: Any, found: list[str]) -> None:
    """JSON 어느 깊이에 있든 local: 참조의 안전한 파일명만 모은다."""
    if isinstance(value, str) and value.startswith("local:"):
        found.append(Path(value[6:]).name)
    elif isinstance(value, list):
        for item in value:
            collect_local_refs(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            collect_local_refs(item, found)


def local_image_record_dir(paths: LocalImagePaths, batch: Any) -> Path:
    """외부 입력을 파일명 하나로 제한해 기존 이미지 무결성 장부 위치를 만든다."""
    return (
        paths.collection_dir
        / paths.record_dir_name
        / Path(str(batch)).name
    )


def _read_documents(
    paths: LocalImagePaths,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    documents: list[dict[str, Any]] = []
    refs: list[str] = []
    invalid_json: list[dict[str, str]] = []
    candidates = (
        sorted(paths.collection_dir.glob("*.json"))
        if paths.collection_dir.is_dir()
        else []
    )
    for path in candidates:
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8-sig"))
            names: list[str] = []
            collect_local_refs(value, names)
            documents.append({
                "path": path,
                "raw": raw,
                "value": value,
                "refs": names,
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            refs.extend(names)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            invalid_json.append({"file": path.name, "error": str(exc)})
    return documents, refs, invalid_json


def _read_image_files(
    paths: LocalImagePaths,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[str]],
    list[dict[str, str]],
    int,
]:
    files: dict[str, dict[str, Any]] = {}
    by_hash: dict[str, list[str]] = {}
    unreadable: list[dict[str, str]] = []
    total_bytes = 0
    if not paths.image_cache.is_dir():
        return files, by_hash, unreadable, total_bytes
    for path in sorted(paths.image_cache.iterdir()):
        if (
            not path.is_file()
            or path.suffix.lower() not in paths.image_suffixes
        ):
            continue
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            canonical = content_image_name(path.name, raw)
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            valid = True
        except Exception as exc:
            raw = b""
            digest = ""
            canonical = ""
            valid = False
            unreadable.append({"file": path.name, "error": str(exc)})
        size = path.stat().st_size
        total_bytes += size
        files[path.name] = {
            "path": path,
            "raw": raw,
            "sha256": digest,
            "canonical": canonical,
            "valid": valid,
            "size": size,
        }
        if digest:
            by_hash.setdefault(digest, []).append(path.name)
    return files, by_hash, unreadable, total_bytes


def _normalization_analysis(
    documents: list[dict[str, Any]],
    refs: list[str],
    files: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], dict[str, str], list[str], int, int]:
    unique_refs = sorted(set(refs))
    missing = [name for name in unique_refs if name not in files]
    unreadable_refs = [
        name
        for name in unique_refs
        if name in files and not files[name]["valid"]
    ]
    mapping = {
        name: files[name]["canonical"]
        for name in unique_refs
        if (
            name in files
            and files[name]["valid"]
            and name != files[name]["canonical"]
        )
    }
    copy_names = sorted({
        canonical
        for canonical in mapping.values()
        if canonical not in files
    })
    copy_bytes = sum(
        next(
            files[old]["size"]
            for old, canonical_name in mapping.items()
            if canonical_name == canonical
        )
        for canonical in copy_names
    )
    changed_documents = sum(
        any(name in mapping for name in document["refs"])
        for document in documents
    )
    return (
        missing,
        unreadable_refs,
        mapping,
        copy_names,
        copy_bytes,
        changed_documents,
    )


def _audit_fingerprint(
    documents: list[dict[str, Any]],
    files: dict[str, dict[str, Any]],
) -> str:
    rows = (
        [
            f"json:{document['path'].name}:{document['sha256']}"
            for document in documents
        ]
        + [
            f"img:{name}:{info['sha256']}:{info['size']}"
            for name, info in sorted(files.items())
        ]
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _local_image_audit(
    paths: LocalImagePaths,
    include_private: bool = False,
) -> dict[str, Any]:
    """자료 JSON 참조와 로컬 이미지 바이트를 대조하고 쓰기 전 상태를 고정한다."""
    documents, refs, invalid_json = _read_documents(paths)
    files, by_hash, unreadable, total_bytes = _read_image_files(paths)
    (
        missing,
        unreadable_refs,
        mapping,
        copy_names,
        copy_bytes,
        changed_documents,
    ) = _normalization_analysis(documents, refs, files)
    unique_refs = sorted(set(refs))
    unreferenced = sorted(set(files) - set(unique_refs))
    legacy_names = sorted(
        name
        for name, info in files.items()
        if info["valid"] and name != info["canonical"]
    )
    duplicate_groups = [
        names for names in by_hash.values() if len(names) > 1
    ]
    result: dict[str, Any] = {
        "ok": not invalid_json,
        "files": len(files),
        "bytes": total_bytes,
        "references": len(refs),
        "unique_references": len(unique_refs),
        "missing": len(missing),
        "unreadable": len(unreadable),
        "unreadable_references": len(unreadable_refs),
        "legacy_names": len(legacy_names),
        "referenced_legacy_names": len(mapping),
        "unreferenced": len(unreferenced),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_extra_files": sum(
            len(group) - 1 for group in duplicate_groups
        ),
        "invalid_json": invalid_json,
        "normalization": {
            "references_to_change": sum(
                refs.count(name) for name in mapping
            ),
            "files_to_copy": len(copy_names),
            "copy_bytes": copy_bytes,
            "documents_to_change": changed_documents,
            "blocked": bool(
                invalid_json or missing or unreadable_refs
            ),
        },
        "samples": {
            "missing": missing[:12],
            "unreadable": unreadable[:12],
            "legacy_names": legacy_names[:12],
            "unreferenced": unreferenced[:12],
        },
        "fingerprint": _audit_fingerprint(documents, files),
    }
    if include_private:
        result.update(
            _documents=documents,
            _files=files,
            _mapping=mapping,
            _copy_names=copy_names,
        )
    return result


def local_image_integrity(paths: LocalImagePaths) -> dict[str, Any]:
    """UI/API 요약에 미사용 파일이 자동 삭제 대상이 아님을 함께 알린다."""
    result = _local_image_audit(paths)
    result["note"] = (
        "과거 이름은 변환 전 해시일 수 있어 손상으로 세지 않습니다. "
        "미사용 후보도 다른 자료팩에서 쓸 수 있으므로 자동 삭제하지 않습니다."
    )
    return result


def _document_plans(
    audit: dict[str, Any],
    before_dir: Path,
    operations: LocalImageOperations,
) -> tuple[list[dict[str, str]], list[tuple[Path, bytes]]]:
    records: list[dict[str, str]] = []
    plans: list[tuple[Path, bytes]] = []
    for document in audit["_documents"]:
        rewritten = rewrite_local_image_refs(
            document["value"], audit["_mapping"]
        )
        if rewritten == document["value"]:
            continue
        after = json.dumps(
            rewritten,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        operations.atomic_write_bytes(
            before_dir / document["path"].name,
            document["raw"],
            keep_backup=False,
        )
        records.append({
            "file": document["path"].name,
            "before_sha256": document["sha256"],
            "after_sha256": hashlib.sha256(after).hexdigest(),
        })
        plans.append((document["path"], after))
    return records, plans


def _created_image_records(audit: dict[str, Any]) -> list[dict[str, str]]:
    created: list[dict[str, str]] = []
    for canonical in audit["_copy_names"]:
        source_name = next(
            name
            for name, new_name in audit["_mapping"].items()
            if new_name == canonical
        )
        created.append({
            "name": canonical,
            "sha256": audit["_files"][source_name]["sha256"],
            "source": source_name,
        })
    return created


def _apply_created_images(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    audit: dict[str, Any],
    created: list[dict[str, str]],
) -> None:
    for item in created:
        source = audit["_files"][item["source"]]
        target = paths.image_cache / item["name"]
        if target.exists():
            if target.read_bytes() != source["raw"]:
                raise ValueError(f"내용 주소 충돌: {item['name']}")
            continue
        operations.atomic_write_bytes(
            target, source["raw"], keep_backup=False
        )


def _recover_failed_normalization(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    record_dir: Path,
    records: list[dict[str, str]],
    created: list[dict[str, str]],
) -> None:
    before_dir = record_dir / "before"
    for record in records:
        backup = before_dir / record["file"]
        target = paths.collection_dir / record["file"]
        if backup.exists():
            operations.atomic_write_bytes(target, backup.read_bytes())
    failed_dir = record_dir / "적용실패-복사본"
    failed_dir.mkdir(parents=True, exist_ok=True)
    for item in created:
        target = paths.image_cache / item["name"]
        if target.exists():
            operations.replace_file(target, failed_dir / item["name"])


def _normalization_batch_id(
    operations: LocalImageOperations,
) -> str:
    return (
        f"{int(operations.unix_time())}-"
        f"{operations.random_bytes(4).hex()}"
    )


def _normalize_locked(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    expected_fingerprint: str,
) -> dict[str, Any]:
    audit = _local_image_audit(paths, include_private=True)
    if (
        expected_fingerprint
        and expected_fingerprint != audit["fingerprint"]
    ):
        return {
            "ok": False,
            "error": "검사 뒤 자료가 바뀌었습니다. 다시 검사해 주세요.",
        }
    if audit["normalization"]["blocked"]:
        return {
            "ok": False,
            "error": "누락·읽기 실패·잘못된 JSON이 있어 자동 정리를 중단했습니다.",
            "audit": local_image_integrity(paths),
        }
    if not audit["_mapping"]:
        return {
            "ok": True,
            "batch": "",
            "changed_references": 0,
            "changed_documents": 0,
            "created_files": 0,
        }
    return _write_normalization(paths, operations, audit)


def _write_normalization(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    audit: dict[str, Any],
) -> dict[str, Any]:
    batch = _normalization_batch_id(operations)
    record_dir = local_image_record_dir(paths, batch)
    before_dir = record_dir / "before"
    before_dir.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, str]] = []
    created: list[dict[str, str]] = []
    try:
        records, plans = _document_plans(
            audit, before_dir, operations
        )
        created = _created_image_records(audit)
        journal = {
            "schema": paths.journal_schema,
            "id": batch,
            "at": operations.now().isoformat(timespec="seconds"),
            "status": "preparing",
            "records": records,
            "created": created,
            "mapping": audit["_mapping"],
        }
        journal_path = record_dir / "journal.json"
        operations.atomic_write_json(
            journal_path, journal, indent=1, keep_backup=False
        )
        _apply_created_images(paths, operations, audit, created)
        for path, after in plans:
            operations.atomic_write_bytes(path, after)
        journal["status"] = "complete"
        operations.atomic_write_json(journal_path, journal, indent=1)
    except Exception:
        _recover_failed_normalization(
            paths, operations, record_dir, records, created
        )
        raise
    operations.forget_caches()
    return {
        "ok": True,
        "batch": batch,
        "changed_references": audit["normalization"][
            "references_to_change"
        ],
        "changed_documents": len(records),
        "created_files": len(created),
        "kept_legacy_files": len(audit["_mapping"]),
    }


def normalize_local_image_refs(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    expected_fingerprint: str = "",
) -> dict[str, Any]:
    """손상 없는 감사 결과만 원본 선기록 뒤 내용 주소 참조로 바꾼다."""
    with operations.transaction(paths.base_dir):
        with operations.lock:
            return _normalize_locked(
                paths, operations, expected_fingerprint
            )


def _restore_documents(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    record_dir: Path,
    journal: dict[str, Any],
) -> tuple[int, int]:
    restored = 0
    skipped = 0
    for record in journal.get("records") or []:
        name = Path(record.get("file", "")).name
        target = paths.collection_dir / name
        backup = record_dir / "before" / name
        try:
            current = target.read_bytes()
            if (
                hashlib.sha256(current).hexdigest()
                != record.get("after_sha256")
            ):
                skipped += 1
                continue
            operations.atomic_write_bytes(target, backup.read_bytes())
            restored += 1
        except OSError:
            skipped += 1
    return restored, skipped


def _live_local_refs(paths: LocalImagePaths) -> tuple[set[str], bool]:
    refs: list[str] = []
    complete = True
    for path in paths.collection_dir.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            collect_local_refs(value, refs)
        except Exception:
            complete = False
    return set(refs), complete


def _hold_unreferenced_created(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    record_dir: Path,
    journal: dict[str, Any],
) -> int:
    live_refs, refs_complete = _live_local_refs(paths)
    held_dir = record_dir / "되돌린-새이름"
    held = 0
    for item in journal.get("created") or []:
        name = Path(item.get("name", "")).name
        target = paths.image_cache / name
        if (
            not refs_complete
            or name in live_refs
            or not target.is_file()
        ):
            continue
        try:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != item.get("sha256"):
                continue
            held_dir.mkdir(parents=True, exist_ok=True)
            operations.replace_file(target, held_dir / name)
            held += 1
        except OSError:
            pass
    return held


def _rollback_locked(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    batch: Any,
) -> dict[str, Any]:
    record_dir = local_image_record_dir(paths, batch)
    journal_path = record_dir / "journal.json"
    if not journal_path.is_file():
        return {
            "ok": False,
            "error": "되돌릴 이미지 정리 기록을 찾지 못했습니다.",
        }
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("schema") != paths.journal_schema:
        return {"ok": False, "error": "알 수 없는 이미지 정리 기록입니다."}
    if journal.get("status") == "undone":
        return {
            "ok": True,
            "restored": 0,
            "skipped": 0,
            "already": True,
        }
    restored, skipped = _restore_documents(
        paths, operations, record_dir, journal
    )
    held = _hold_unreferenced_created(
        paths, operations, record_dir, journal
    )
    journal.update(
        status="undone",
        undone_at=operations.now().isoformat(timespec="seconds"),
        restored=restored,
        skipped=skipped,
        held_created=held,
    )
    operations.atomic_write_json(journal_path, journal, indent=1)
    operations.forget_caches()
    return {
        "ok": True,
        "restored": restored,
        "skipped": skipped,
        "held_created": held,
    }


def rollback_local_image_normalize(
    paths: LocalImagePaths,
    operations: LocalImageOperations,
    batch: Any,
) -> dict[str, Any]:
    """사용자가 정규화 뒤 편집한 JSON은 건너뛰고 안전한 원본만 복원한다."""
    with operations.transaction(paths.base_dir):
        with operations.lock:
            return _rollback_locked(paths, operations, batch)
