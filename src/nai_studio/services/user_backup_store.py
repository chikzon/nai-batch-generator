# -*- coding: utf-8 -*-
"""사용자 백업 검증·차이 계산·원자 복원의 저장 경계."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_MISSING = object()
_SECRET_KEYS = frozenset({"token", "booru_keys", "out_dir"})
_PROFILE_FILES = frozenset({"설정.json", "선별.json", "씬.json"})
_COMMON_FILES = frozenset({"후보사전.json", "규격.json", "옵션.json"})
_COMMON_DIRS = frozenset({
    "태그",
    "세팅",
    "씬규격",
    "씬프리셋",
    "그림체",
    "캐릭터",
    "조각",
    "수집",
})


@dataclass(frozen=True)
class UserBackupPaths:
    base_dir: Path
    profile_dir: Path
    sources: "UserBackupSourcePaths"
    profile_name: str = ""
    schema: str = "nais-user-backup/v1"
    journal_schema: str = "nais-restore-journal/v1"
    journal_dir_name: str = "복원기록"


@dataclass(frozen=True)
class UserBackupOperations:
    transaction: Callable[[Path], AbstractContextManager[Any]]
    atomic_write_bytes: Callable[..., None]
    atomic_write_json: Callable[..., None]
    load_settings: Callable[[Path], Any]
    rollback: Callable[[str], Any]
    after_restore: Callable[[], Any]
    now: Callable[[], Any]
    random_bytes: Callable[[int], bytes]
    warning: Callable[..., Any]
    recoverable_remove: Callable[..., Any]


@dataclass(frozen=True)
class UserBackupSourcePaths:
    """백업에 포함할 사용자 원본의 기존 파일·폴더 위치 계약."""

    settings_file: Path
    builder_file: Path
    spec_file: Path
    options_file: Path
    tag_dir: Path
    settings_dir: Path
    schema_dir: Path
    sceneset_dir: Path
    style_dir: Path
    character_dir: Path
    fragment_dir: Path
    vibe_dir: Path
    picks_file: Path
    scenes_file: Path


def _clean_settings(raw: Any) -> bytes:
    data = dict(raw or {}) if isinstance(raw, dict) else {}
    for key in _SECRET_KEYS:
        data.pop(key, None)
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def clean_settings(raw: Any) -> bytes:
    """API 토큰·로컬 출력 위치를 제외한 설정 JSON 바이트를 만든다."""
    return _clean_settings(raw)


def _safe_logical(value: Any) -> str | None:
    value = str(value or "").replace("\\", "/").strip("/")
    parts = value.split("/") if value else []
    if (
        len(parts) < 2
        or parts[0] not in ("common", "profile")
        or any(part in ("", ".", "..") or ":" in part for part in parts)
    ):
        return None
    return "/".join(parts)


def safe_logical(value: Any) -> str | None:
    return _safe_logical(value)


def _read_backup(
    paths: UserBackupPaths,
    blob: bytes,
) -> tuple[dict, dict[str, bytes], str]:
    if not blob.startswith(b"PK"):
        raise ValueError("NAI 사용자 백업 ZIP이 아닙니다.")
    archive_sha = hashlib.sha256(blob).hexdigest()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if len(infos) > 50000 or sum(item.file_size for item in infos) > 1024 ** 3:
            raise ValueError("백업의 파일 수나 압축 해제 크기가 비정상적입니다.")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except Exception as exc:
            raise ValueError(f"manifest.json을 읽지 못했습니다: {exc}") from exc
        if manifest.get("schema") != paths.schema:
            raise ValueError("지원하지 않는 백업 형식입니다.")
        payloads: dict[str, bytes] = {}
        seen: set[str] = set()
        for entry in manifest.get("files") or []:
            logical = _safe_logical(entry.get("path"))
            if not logical or logical in seen:
                raise ValueError(
                    "백업 manifest에 위험하거나 중복된 경로가 있습니다."
                )
            seen.add(logical)
            try:
                raw = archive.read("data/" + logical)
            except KeyError as exc:
                raise ValueError(f"백업 내용이 빠졌습니다: {logical}") from exc
            if (
                len(raw) != int(entry.get("size", -1))
                or hashlib.sha256(raw).hexdigest() != entry.get("sha256")
            ):
                raise ValueError(f"백업 내용 검사가 실패했습니다: {logical}")
            payloads[logical] = raw
    return manifest, payloads, archive_sha


def _destination(paths: UserBackupPaths, logical: Any) -> Path:
    safe = _safe_logical(logical)
    if not safe:
        raise ValueError("위험한 백업 경로입니다.")
    scope, relative = safe.split("/", 1)
    if scope == "profile":
        if relative not in _PROFILE_FILES:
            raise ValueError(f"허용하지 않는 프로필 자료입니다: {relative}")
        root = paths.profile_dir.resolve()
    else:
        if (
            relative not in _COMMON_FILES
            and relative.split("/", 1)[0] not in _COMMON_DIRS
        ):
            raise ValueError(f"허용하지 않는 공용 자료입니다: {relative}")
        root = paths.base_dir.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError("백업 경로가 앱 자료 폴더를 벗어납니다.")
    return target


def destination(paths: UserBackupPaths, logical: Any) -> Path:
    return _destination(paths, logical)


def _merge_secrets(
    operations: UserBackupOperations,
    logical: str,
    raw: bytes,
    target: Path,
) -> bytes:
    if logical != "profile/설정.json":
        return raw
    incoming = json.loads(raw.decode("utf-8"))
    if not isinstance(incoming, dict):
        raise ValueError("복원할 설정의 최상위 값은 JSON 객체여야 합니다.")
    current = operations.load_settings(target) if target.is_file() else {}
    for key in _SECRET_KEYS:
        if key in current:
            incoming[key] = current[key]
    return json.dumps(incoming, ensure_ascii=False, indent=1).encode("utf-8")


def merge_secrets(
    operations: UserBackupOperations,
    logical: str,
    raw: bytes,
    target: Path,
) -> bytes:
    return _merge_secrets(operations, logical, raw, target)


def backup_sources(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    config: Any,
) -> dict[str, bytes]:
    """토큰·생성물·재생성 캐시를 제외하고 사용자 원본만 모은다."""
    files: dict[str, bytes] = {}
    source = paths.sources
    for name, path in (
        ("후보사전.json", source.builder_file),
        ("규격.json", source.spec_file),
        ("옵션.json", source.options_file),
    ):
        _put_source(files, operations, f"common/{name}", path)
    for prefix, root in (
        ("태그", source.tag_dir),
        ("세팅", source.settings_dir),
        ("씬규격", source.schema_dir),
        ("씬프리셋", source.sceneset_dir),
        ("그림체", source.style_dir),
        ("캐릭터", source.character_dir),
        ("조각", source.fragment_dir),
        ("수집/바이브", source.vibe_dir),
    ):
        _put_tree(files, operations, prefix, root)
    _put_collection_sources(paths, operations, files)
    files["profile/설정.json"] = _clean_settings(config)
    for name, path in (
        ("선별.json", source.picks_file),
        ("씬.json", source.scenes_file),
    ):
        _put_source(files, operations, f"profile/{name}", path)
    return files


def _put_source(
    files: dict[str, bytes],
    operations: UserBackupOperations,
    logical: str,
    path: Path,
) -> None:
    try:
        if path.is_file() and not path.name.endswith((".bak", ".tmp")):
            files[logical] = path.read_bytes()
    except OSError as exc:
        operations.warning("백업에서 건너뜀 %s: %s", path, exc)


def _put_tree(
    files: dict[str, bytes],
    operations: UserBackupOperations,
    prefix: str,
    root: Path,
    skip: tuple[str, ...] = (),
) -> None:
    if not root.is_dir():
        return
    resolved = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.endswith((".bak", ".tmp")):
            continue
        relative = path.relative_to(root)
        if any(part in skip for part in relative.parts):
            continue
        try:
            if resolved not in path.resolve().parents:
                continue
        except OSError:
            continue
        _put_source(
            files,
            operations,
            f"common/{prefix}/{relative.as_posix()}",
            path,
        )


def _put_collection_sources(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    files: dict[str, bytes],
) -> None:
    collection = paths.base_dir / "수집"
    if not collection.is_dir():
        return
    for path in sorted(collection.glob("*.json")):
        _put_source(files, operations, f"common/수집/{path.name}", path)
    _put_tree(
        files,
        operations,
        "수집/이미지캐시",
        collection / "이미지캐시",
        skip=("원격",),
    )


def export_user_backup(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    config: Any,
) -> bytes:
    """사용자 원본과 비밀값 제외 내역을 기존 ZIP schema로 내보낸다."""
    payloads = backup_sources(paths, operations, config)
    manifest = {
        "schema": paths.schema,
        "created_at": operations.now().isoformat(timespec="seconds"),
        "profile": paths.profile_name or "기본",
        "files": [
            {
                "path": logical,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            for logical, raw in sorted(payloads.items())
        ],
        "excluded": [
            "API 토큰",
            "생성 결과(output)",
            "로그·진행상태",
            "태그 검색 색인",
            "다운로드한 원격 이미지 캐시",
            "자료팩 되돌리기 임시백업",
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=1,
            ).encode("utf-8"),
        )
        for logical, raw in sorted(payloads.items()):
            archive.writestr("data/" + logical, raw)
    return output.getvalue()


def _list_key(current: Any, incoming: Any) -> str:
    lists = [value for value in (current, incoming) if isinstance(value, list)]
    rows = [item for value in lists for item in value]
    if not rows or not all(isinstance(item, dict) for item in rows):
        return ""
    for key in ("id", "이름", "name", "title", "seed"):
        values_by_list = [
            [str(item.get(key, "")).strip() for item in value]
            for value in lists
        ]
        if all(
            all(values) and len(values) == len(set(values))
            for values in values_by_list
        ):
            return key
    return ""


def _pointer(tokens: tuple) -> str:
    parts = []
    for token in tokens:
        if token[0] == "key":
            parts.append(str(token[1]).replace("~", "~0").replace("/", "~1"))
        else:
            value = str(token[2]).replace("~", "~0").replace("/", "~1")
            parts.append(f"@{token[1]}={value}")
    return "/" + "/".join(parts) if parts else "/"


def _collect_changes(
    current: Any,
    incoming: Any,
    tokens: tuple = (),
) -> list[dict]:
    if current is not _MISSING and incoming is not _MISSING:
        if current == incoming:
            return []
        if isinstance(current, dict) and isinstance(incoming, dict):
            changes = []
            for key in sorted(set(current) | set(incoming), key=str):
                changes.extend(_collect_changes(
                    current.get(key, _MISSING),
                    incoming.get(key, _MISSING),
                    tokens + (("key", key),),
                ))
            return changes
        if isinstance(current, list) and isinstance(incoming, list):
            key = _list_key(current, incoming)
            if key:
                before = {str(item[key]): item for item in current}
                after = {str(item[key]): item for item in incoming}
                changes = []
                for value in sorted(set(before) | set(after)):
                    changes.extend(_collect_changes(
                        before.get(value, _MISSING),
                        after.get(value, _MISSING),
                        tokens + (("item", key, value),),
                    ))
                return changes
    return [{
        "tokens": tokens,
        "current_exists": current is not _MISSING,
        "incoming_exists": incoming is not _MISSING,
        "current": None if current is _MISSING else copy.deepcopy(current),
        "incoming": None if incoming is _MISSING else copy.deepcopy(incoming),
    }]


def _apply_change(value: Any, change: dict, depth: int = 0) -> Any:
    tokens = change["tokens"]
    incoming = copy.deepcopy(change["incoming"])
    if depth >= len(tokens):
        return incoming if change["incoming_exists"] else _MISSING
    token = tokens[depth]
    if token[0] == "key":
        result = copy.deepcopy(value) if isinstance(value, dict) else {}
        key = token[1]
        replaced = _apply_change(
            result.get(key, _MISSING), change, depth + 1
        )
        if replaced is _MISSING:
            result.pop(key, None)
        else:
            result[key] = replaced
        return result
    rows = copy.deepcopy(value) if isinstance(value, list) else []
    field, wanted = token[1], str(token[2])
    index = next((
        row_index
        for row_index, item in enumerate(rows)
        if isinstance(item, dict) and str(item.get(field, "")) == wanted
    ), None)
    child = rows[index] if index is not None else _MISSING
    replaced = _apply_change(child, change, depth + 1)
    if replaced is _MISSING:
        if index is not None:
            rows.pop(index)
    elif index is None:
        rows.append(replaced)
    else:
        rows[index] = replaced
    return rows


def backup_diff_plan(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    blob: bytes,
) -> tuple[dict, dict[str, bytes], str, list[dict], dict, int, str]:
    manifest, payloads, archive_sha = _read_backup(paths, blob)
    declared = {
        str(item.get("path") or ""): item
        for item in (manifest.get("files") or [])
    }
    plans = []
    counts = {"새 파일": 0, "바뀔 파일": 0, "같은 파일": 0}
    total = 0
    for logical, raw in sorted(payloads.items()):
        target = _destination(paths, logical)
        wanted = _merge_secrets(operations, logical, raw, target)
        current_raw = target.read_bytes() if target.is_file() else None
        total += len(wanted)
        if current_raw == wanted:
            counts["같은 파일"] += 1
            continue
        status = "새 파일" if current_raw is None else "바뀔 파일"
        counts[status] += 1
        incoming_value = current_value = _MISSING
        json_mode = False
        try:
            incoming_value = json.loads(wanted.decode("utf-8"))
            current_value = (
                json.loads(current_raw.decode("utf-8"))
                if current_raw is not None
                else _MISSING
            )
            json_mode = True
        except (UnicodeError, json.JSONDecodeError, AttributeError):
            pass
        changes = (
            _collect_changes(current_value, incoming_value)
            if json_mode and current_raw is not None
            else [{
                "tokens": (),
                "current_exists": current_raw is not None,
                "incoming_exists": True,
                "current": ({
                    "bytes": len(current_raw),
                    "sha256": hashlib.sha256(current_raw).hexdigest(),
                } if current_raw is not None else None),
                "incoming": {
                    "bytes": len(wanted),
                    "sha256": hashlib.sha256(wanted).hexdigest(),
                },
            }]
        )
        current_sha = hashlib.sha256(current_raw or b"").hexdigest()
        incoming_sha = hashlib.sha256(wanted).hexdigest()
        base_sha = str((declared.get(logical) or {}).get("base_sha256") or "")
        for change in changes:
            pointer = _pointer(change["tokens"])
            change_id = hashlib.sha256(
                f"{archive_sha}\0{logical}\0{pointer}\0"
                f"{current_sha}\0{incoming_sha}".encode("utf-8")
            ).hexdigest()
            plans.append({
                **change,
                "id": change_id,
                "logical": logical,
                "pointer": pointer,
                "file_status": status,
                "json": json_mode,
                "current_sha256": current_sha,
                "incoming_sha256": incoming_sha,
                "base_sha256": base_sha,
                "target": target,
                "wanted_raw": wanted,
                "current_raw": current_raw,
            })
    fingerprint = hashlib.sha256(
        "\n".join(item["id"] for item in plans).encode("ascii")
    ).hexdigest()
    return manifest, payloads, archive_sha, plans, counts, total, fingerprint


def backup_change_public(change: Mapping[str, Any]) -> dict:
    """내부 대상 경로·원문 바이트를 제외한 선택 복원 항목만 공개한다."""
    if change["current_exists"] and change["incoming_exists"]:
        action = "변경"
    elif change["incoming_exists"]:
        action = "추가"
    else:
        action = "제거"
    return {
        key: copy.deepcopy(change[key])
        for key in (
            "id",
            "logical",
            "pointer",
            "file_status",
            "json",
            "current_exists",
            "incoming_exists",
            "current",
            "incoming",
            "current_sha256",
            "incoming_sha256",
            "base_sha256",
        )
    } | {
        "action": action,
        "base_available": bool(change.get("base_sha256")),
    }


def preview_user_backup(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    blob: bytes,
) -> dict:
    """백업을 쓰지 않고 검증해 기존 미리보기 응답과 변경 지문을 만든다."""
    (
        manifest,
        payloads,
        archive_sha,
        plans,
        counts,
        total,
        fingerprint,
    ) = backup_diff_plan(paths, operations, blob)
    return {
        "ok": True,
        "sha256": archive_sha,
        "files": len(payloads),
        "bytes": total,
        "counts": counts,
        "created_at": manifest.get("created_at"),
        "profile": manifest.get("profile"),
        "excluded": manifest.get("excluded") or [],
        "diff_fingerprint": fingerprint,
        "changes": [backup_change_public(change) for change in plans],
    }


def restore_user_backup(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    blob: bytes,
    expected_sha: str = "",
    selected: Any = None,
    expected_diff: str = "",
) -> dict:
    with operations.transaction(paths.base_dir):
        return _restore_user_backup(
            paths,
            operations,
            blob,
            expected_sha,
            selected,
            expected_diff,
        )


def _restore_user_backup(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    blob: bytes,
    expected_sha: str,
    selected: Any,
    expected_diff: str,
) -> dict:
    (
        _manifest,
        payloads,
        archive_sha,
        plans,
        _counts,
        _total,
        diff_fingerprint,
    ) = backup_diff_plan(paths, operations, blob)
    if expected_sha and expected_sha != archive_sha:
        return {
            "ok": False,
            "error": "미리보기한 백업과 복원할 백업이 다릅니다.",
        }
    if expected_diff and expected_diff != diff_fingerprint:
        return {
            "ok": False,
            "conflict": True,
            "error": "검사 뒤 현재 자료가 바뀌었습니다. 백업을 다시 검사해 주세요.",
        }
    selected_ids = None if selected is None else set(map(str, selected))
    by_id = {item["id"]: item for item in plans}
    if selected_ids is not None:
        unknown = selected_ids - set(by_id)
        if unknown:
            return {
                "ok": False,
                "conflict": True,
                "error": "검사 뒤 충돌 항목이 바뀌었습니다. 백업을 다시 검사해 주세요.",
            }
        if not selected_ids:
            return {
                "ok": True,
                "batch": "",
                "changed": 0,
                "files": len(payloads),
                "selected": 0,
            }
    chosen = (
        plans
        if selected_ids is None
        else [by_id[item_id] for item_id in selected_ids]
    )
    grouped: dict[str, list[dict]] = {}
    for change in chosen:
        grouped.setdefault(change["logical"], []).append(change)

    now = operations.now()
    batch = now.strftime("%Y%m%d-%H%M%S") + "-" + operations.random_bytes(3).hex()
    journal = paths.profile_dir / paths.journal_dir_name / batch
    pending = []
    for logical, changes in sorted(grouped.items()):
        target = _destination(paths, logical)
        old = target.read_bytes() if target.is_file() else None
        if len(changes) == 1 and not changes[0]["tokens"]:
            wanted = changes[0]["wanted_raw"]
        else:
            try:
                value = json.loads(old.decode("utf-8")) if old is not None else {}
            except (UnicodeError, json.JSONDecodeError) as exc:
                return {
                    "ok": False,
                    "error": f"{logical} 현재 JSON을 읽지 못했습니다: {exc}",
                }
            for change in sorted(changes, key=lambda item: item["pointer"]):
                value = _apply_change(value, change)
            if value is _MISSING:
                continue
            wanted = json.dumps(
                value, ensure_ascii=False, indent=1
            ).encode("utf-8")
        if old == wanted:
            continue
        item = {
            "path": logical,
            "new": old is None,
            "applied_sha256": hashlib.sha256(wanted).hexdigest(),
        }
        if old is not None:
            saved = (
                _clean_settings(json.loads(old))
                if logical == "profile/설정.json"
                else old
            )
            operations.atomic_write_bytes(
                journal / "before" / logical,
                saved,
                keep_backup=False,
            )
        pending.append((item, target, wanted))

    record = {
        "schema": paths.journal_schema,
        "id": batch,
        "backup_sha256": archive_sha,
        "status": "ready",
        "operations": [item[0] for item in pending],
        "completed": [],
    }
    journal_file = journal / "journal.json"
    operations.atomic_write_json(
        journal_file, record, indent=1, keep_backup=False
    )
    try:
        record["status"] = "applying"
        operations.atomic_write_json(
            journal_file, record, indent=1, keep_backup=False
        )
        for item, target, wanted in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            operations.atomic_write_bytes(target, wanted)
            record["completed"].append(item["path"])
            operations.atomic_write_json(
                journal_file, record, indent=1, keep_backup=False
            )
    except Exception:
        operations.rollback(batch)
        raise
    record.update(
        status="complete",
        completed_at=operations.now().isoformat(timespec="seconds"),
    )
    operations.atomic_write_json(
        journal_file, record, indent=1, keep_backup=False
    )
    operations.after_restore()
    return {
        "ok": True,
        "batch": batch,
        "changed": len(pending),
        "files": len(payloads),
        "selected": len(chosen),
    }


def rollback_user_backup(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    batch_id: Any,
) -> dict:
    """복원 뒤 수정되지 않은 파일만 이전 상태로 안전하게 되돌린다."""
    with operations.transaction(paths.base_dir):
        return _rollback_user_backup(paths, operations, batch_id)


def _rollback_user_backup(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    batch_id: Any,
) -> dict:
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", str(batch_id or "")):
        return {"ok": False, "error": "복원 기록 번호가 올바르지 않습니다."}
    root = (paths.profile_dir / paths.journal_dir_name).resolve()
    journal = (root / str(batch_id)).resolve()
    journal_file = journal / "journal.json"
    if root not in journal.parents or not journal_file.is_file():
        return {"ok": False, "error": "복원 기록을 찾지 못했습니다."}
    record = operations.load_settings(journal_file)
    if record.get("status") == "rolled_back":
        return {"ok": False, "error": "이미 되돌린 복원입니다."}
    restored, skipped = _rollback_operations(
        paths,
        operations,
        journal,
        record,
    )
    record.update(
        status="rolled_back",
        rolled_back_at=operations.now().isoformat(timespec="seconds"),
    )
    operations.atomic_write_json(journal_file, record, indent=1)
    operations.after_restore()
    return {"ok": True, "restored": restored, "skipped": skipped}


def _rollback_operations(
    paths: UserBackupPaths,
    operations: UserBackupOperations,
    journal: Path,
    record: dict,
) -> tuple[int, int]:
    completed = set(record.get("completed") or [])
    restored = skipped = 0
    for item in reversed(record.get("operations") or []):
        logical = item.get("path")
        if logical not in completed:
            continue
        target = _destination(paths, logical)
        if not _matches_applied(target, item):
            skipped += 1
        elif item.get("new"):
            operations.recoverable_remove(target, label="복원취소")
            restored += 1
        else:
            saved = journal / "before" / logical
            if saved.is_file():
                raw = _merge_secrets(
                    operations,
                    logical,
                    saved.read_bytes(),
                    target,
                )
                operations.atomic_write_bytes(target, raw)
                restored += 1
    return restored, skipped


def _matches_applied(target: Path, operation: Mapping[str, Any]) -> bool:
    return (
        target.is_file()
        and hashlib.sha256(target.read_bytes()).hexdigest()
        == operation.get("applied_sha256")
    )


__all__ = [
    "UserBackupOperations",
    "UserBackupPaths",
    "UserBackupSourcePaths",
    "backup_change_public",
    "backup_diff_plan",
    "backup_sources",
    "clean_settings",
    "destination",
    "export_user_backup",
    "merge_secrets",
    "preview_user_backup",
    "restore_user_backup",
    "rollback_user_backup",
    "safe_logical",
]
