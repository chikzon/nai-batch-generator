# -*- coding: utf-8 -*-
"""자료팩 검증·병합·장부·되돌리기의 저장 경계.

이 모듈은 애플리케이션 전역 경로와 설정 객체를 직접 참조하지 않는다. 프로필별 경로와
안전 저장 함수는 호출자가 매번 주입한다. 따라서 기존 HTTP workflow는 미리보기 캐시와
화면 갱신만 맡고, 이 모듈은 동일한 자료 결과를 만드는 파일 작업만 맡는다.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import io
import json
import os
import time
import zipfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from src.nai_studio.runtime import file_transaction as file_txn


_BACKUP_MISSING = object()


@dataclass(frozen=True)
class DatapackPaths:
    """현재 프로필의 자료 위치 계약.

    legacy 전역을 import 시점에 붙잡지 않고 공개 호출마다 이 값을 새로 만들면, 프로필
    전환과 임시 경로 테스트가 같은 서비스 구현을 안전하게 공유한다.
    """

    base_dir: Path
    style_file: Path
    recipe_file: Path
    combo_file: Path
    image_cache: Path
    tag_dir: Path
    builder_file: Path
    spec_file: Path
    options_file: Path
    settings_dir: Path
    character_dir: Path


@dataclass(frozen=True)
class DatapackOperations:
    """자료팩 저장이 연결하는 기존 공통 경계.

    원자 저장·프로세스 잠금·캐릭터 파일 동기화·복원 큐를 주입받아 기존 구현의 결과와
    테스트 패치 가능성을 유지한다. 새 저장 형식이나 별도 journal은 이 경계에 포함하지
    않는다.
    """

    transaction: Callable[[Path], AbstractContextManager[Any]]
    atomic_write_bytes: Callable[..., None]
    atomic_write_json: Callable[..., None]
    load_json: Callable[[Path], Any]
    recoverable_remove: Callable[..., Path]
    row_digest: Callable[[Any], str]
    character_signature: Callable[[dict], str]
    delete_character_files: Callable[[dict, set[str]], Any]
    sync_character_files: Callable[[dict], Any]
    save_config: Callable[[dict], Any]
    forget_caches: Callable[[], Any]
    pack_queue: Callable[..., Any]
    summarize_queue: Callable[[Any], Any]
    warning: Callable[[str], Any]
    # 파일별 교체 지점. 실패 주입 시험을 위해 갈아끼울 수 있다.
    replace: Callable[[Any, Any], None] = os.replace


def datapack_lists(paths: DatapackPaths) -> dict[str, tuple[Path, str]]:
    """목록 자료 이름을 현재 프로필 파일과 중복 식별 키로 연결한다."""
    return {
        "그림체.json": (paths.style_file, "id"),
        "레시피.json": (paths.recipe_file, "id"),
        "작가조합.json": (paths.combo_file, "id"),
        "작가통계.json": (
            paths.base_dir / "수집" / "작가통계.json",
            "tag",
        ),
    }


def datapack_dirs(
    paths: DatapackPaths,
) -> dict[str, tuple[Path, tuple[str, ...]]]:
    """디렉터리 자료 이름을 저장 위치와 허용 확장자로 연결한다."""
    return {
        "수집/이미지캐시": (
            paths.image_cache,
            (".webp", ".png", ".jpg", ".jpeg"),
        ),
        "태그": (paths.tag_dir, (".csv",)),
    }


def datapack_whole_files(paths: DatapackPaths) -> dict[str, Path]:
    """목록 병합 없이 JSON 객체 하나를 통째로 설치하는 기본 자료."""
    return {
        "후보사전.json": paths.builder_file,
        "규격.json": paths.spec_file,
        "옵션.json": paths.options_file,
    }


def pack_rel(name: Any) -> str | None:
    """ZIP 경로를 앱 기준 상대경로로 바꾸고 탈출·드라이브 지정을 거부한다."""
    parts = [
        part
        for part in str(name).replace("\\", "/").split("/")
        if part not in ("", ".")
    ]
    if any(part == ".." for part in parts) or (
        parts and ":" in parts[0]
    ):
        return None
    for index, part in enumerate(parts):
        if part in ("수집", "태그", "세팅", "캐릭터"):
            return "/".join(parts[index:])
    return "/".join(parts)


def read_rows(raw: bytes) -> tuple[list[Any] | None, str]:
    """UTF-8·CP949의 목록, 감싼 목록, NDJSON을 기존 규칙대로 읽는다."""
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        try:
            text = raw.decode("cp949")
        except Exception:
            return None, "글자를 못 읽었습니다 (UTF-8·CP949 둘 다 아님)"
    text = text.strip()
    if not text:
        return None, "빈 파일입니다"
    try:
        data = json.loads(text)
    except Exception:
        rows, bad = [], 0
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
        if rows and bad == 0:
            return rows, "줄마다 한 건(NDJSON)"
        return None, "JSON 으로 못 읽었습니다"
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        best, best_key = None, ""
        for key, value in data.items():
            if isinstance(value, list) and (
                best is None or len(value) > len(best)
            ):
                best, best_key = value, key
        if best is not None:
            return best, f"'{best_key}' 안의 목록을 꺼냄"
        return None, "목록이 들어 있지 않습니다"
    return None, "목록이 아닙니다"


def row_key(item: dict, key: str) -> tuple[str, bool]:
    """주 식별자가 없을 때 내용 해시를 써서 버리지 않는 기존 키 규칙."""
    value = item.get(key)
    if value not in (None, ""):
        return str(value), False
    blob = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return (
        "가져옴-" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12],
        True,
    )


def datapack_match_key(item: dict, primary: str) -> str:
    """충돌 비교는 id/tag, 사람이 보는 이름, 마지막으로 내용 해시 순서다."""
    value = item.get(primary)
    if value not in (None, ""):
        return str(value)
    for field in ("id", "이름", "name", "title", "tag"):
        value = item.get(field)
        if value not in (None, ""):
            return f"{field}={value}"
    return row_key(item, primary)[0]


def merge_list_json(
    operations: DatapackOperations,
    path: Path,
    incoming: list[Any],
    key: str,
    overwrite: bool = False,
    replace_keys: Any = None,
) -> tuple[dict[str, int], list[str], list[dict[str, Any]]]:
    """목록 자료를 비파괴 병합하고 Undo에 필요한 추가·교체 기록을 반환한다."""
    old: list[Any] = []
    if path.exists():
        try:
            loaded = operations.load_json(path)
            if not isinstance(loaded, list):
                raise ValueError(
                    f"{path.name}이 목록이 아니라 가져오기를 중단했습니다."
                )
            old = loaded
        except Exception as exc:
            raise ValueError(
                f"{path.name}과 백업을 읽지 못해 가져오기를 중단했습니다."
            ) from exc
    index: dict[str, int] = {}
    for position, item in enumerate(old):
        if isinstance(item, dict):
            index.setdefault(datapack_match_key(item, key), position)
    counts = {
        "새로": 0,
        "같음": 0,
        "다름": 0,
        "열쇠없음": 0,
        "항목아님": 0,
        "덮어씀": 0,
    }
    added_keys: list[str] = []
    updates: list[dict[str, Any]] = []
    replacements = set(map(str, replace_keys or ()))
    for item in incoming:
        if not isinstance(item, dict):
            counts["항목아님"] += 1
            continue
        raw_key, made = row_key(item, key)
        match_key = datapack_match_key(item, key)
        made = made and match_key.startswith("가져옴-")
        if made:
            counts["열쇠없음"] += 1
        if match_key in index:
            same = old[index[match_key]] == item
            if same:
                counts["같음"] += 1
            elif overwrite or match_key in replacements:
                before = copy.deepcopy(old[index[match_key]])
                old[index[match_key]] = item
                counts["덮어씀"] += 1
                updates.append({
                    "key": match_key,
                    "match_key": True,
                    "before": before,
                    "after_sha256": operations.row_digest(item),
                })
            else:
                counts["다름"] += 1
            continue
        index[match_key] = len(old)
        old.append(item)
        added_keys.append(raw_key)
        counts["새로"] += 1
    if counts["새로"] + counts["덮어씀"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        operations.atomic_write_json(path, old, indent=None)
    return counts, added_keys, updates


def say_counts(counts: dict[str, int]) -> str:
    """자료 병합 수치를 기존 화면 문장으로 바꾼다."""
    order = [
        ("새로", "새로 {}건"),
        ("덮어씀", "덮어씀 {}건"),
        ("같음", "이미 있음 {}건"),
        ("다름", "같은 이름인데 내용이 달라 그대로 둠 {}건"),
        ("열쇠없음", "이름표가 없어 내용으로 넣음 {}건"),
        ("항목아님", "모양이 아니라 건너뜀 {}건"),
    ]
    parts = [
        template.format(counts[key])
        for key, template in order
        if counts.get(key)
    ]
    return " · ".join(parts) or "들어온 것 없음"


def content_image_name(name: Any, raw: bytes) -> str:
    """그림 파일명을 실제 바이트 SHA-256과 확인된 이미지 형식으로 만든다."""
    suffix = Path(str(name)).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in (".webp", ".png", ".jpg"):
        suffix = ".webp"
    try:
        with Image.open(io.BytesIO(raw)) as image:
            suffix = {
                "WEBP": ".webp",
                "PNG": ".png",
                "JPEG": ".jpg",
            }.get((image.format or "").upper(), suffix)
            image.verify()
    except Exception:
        pass
    return hashlib.sha256(raw).hexdigest() + suffix


def rewrite_local_image_refs(value: Any, renamed: dict[str, str]) -> Any:
    """JSON 내부의 local: 파일명을 내용 주소로 재귀 치환한다."""
    if isinstance(value, str) and value.startswith("local:"):
        old = Path(value[6:]).name
        return "local:" + renamed.get(old, old)
    if isinstance(value, list):
        return [rewrite_local_image_refs(item, renamed) for item in value]
    if isinstance(value, dict):
        return {
            key: rewrite_local_image_refs(item, renamed)
            for key, item in value.items()
        }
    return value


def pack_log_path(paths: DatapackPaths) -> Path:
    return paths.base_dir / "수집" / "가져온기록.json"


def load_pack_log(
    paths: DatapackPaths,
    operations: DatapackOperations,
) -> list[dict[str, Any]]:
    path = pack_log_path(paths)
    if path.exists():
        try:
            data = operations.load_json(path)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def save_pack_log(
    paths: DatapackPaths,
    operations: DatapackOperations,
    rows: list[dict[str, Any]],
) -> None:
    path = pack_log_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    operations.atomic_write_json(path, rows[-50:], indent=1)


def _record_import_batch(
    paths: DatapackPaths,
    operations: DatapackOperations,
    batch: Any,
) -> str | None:
    record = copy.deepcopy(batch) if isinstance(batch, dict) else {}
    changed = any(record.get(key) for key in (
        "lists",
        "files",
        "installed",
        "list_updates",
        "characters",
    ))
    if not changed:
        return None
    record.setdefault("id", f"{int(time.time())}-{os.urandom(4).hex()}")
    record.setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
    record.setdefault("file", "자료")
    record.setdefault("kind", "datapack")
    record.setdefault("lists", {})
    record.setdefault("files", {})
    record.setdefault("installed", [])
    record.setdefault("list_updates", [])
    record.setdefault("characters", [])
    record.setdefault(
        "새로",
        sum(len(value) for value in record["lists"].values())
        + sum(len(value) for value in record["files"].values())
        + len(record["installed"])
        + len(record["characters"]),
    )
    rows = load_pack_log(paths, operations)
    rows.append(record)
    save_pack_log(paths, operations, rows)
    return str(record["id"])


def record_import_batch(
    paths: DatapackPaths,
    operations: DatapackOperations,
    batch: Any,
) -> str | None:
    """단건·비교 승격도 자료팩과 같은 Undo 장부에 직렬화해 기록한다."""
    with operations.transaction(paths.base_dir):
        return _record_import_batch(paths, operations, batch)


def validate_datapack_manifest(
    paths: DatapackPaths,
    archive: zipfile.ZipFile,
    schema: str = "nais-datapack/v1",
) -> dict[str, Any] | None:
    """v1 manifest의 경로·크기·개별/전체 해시를 실제 쓰기 전에 검증한다."""
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > 100_000:
        raise ValueError("자료팩 파일 수가 비정상적으로 많습니다.")
    if any(info.file_size > 512 * 1024 * 1024 for info in infos):
        raise ValueError("자료팩의 낱개 파일이 512MB를 넘습니다.")
    if sum(info.file_size for info in infos) > 2 * 1024 * 1024 * 1024:
        raise ValueError("자료팩을 풀었을 때 크기가 2GB를 넘습니다.")

    members: dict[str, str] = {}
    manifest_name = None
    for info in infos:
        relative = pack_rel(info.filename)
        if relative is None:
            raise ValueError(
                "자료팩에 앱 폴더 밖을 가리키는 경로가 있습니다."
            )
        if relative in members:
            raise ValueError(
                f"자료팩에 같은 경로가 두 번 있습니다: {relative}"
            )
        members[relative] = info.filename
        if Path(relative).name == "manifest.json" and "/" not in relative:
            manifest_name = info.filename
    if not manifest_name:
        return None
    try:
        manifest = json.loads(
            archive.read(manifest_name).decode("utf-8-sig")
        )
    except Exception as exc:
        raise ValueError(
            f"자료팩 manifest.json을 읽지 못했습니다: {exc}"
        ) from exc
    if manifest.get("schema") != schema:
        return None

    declared: set[str] = set()
    fingerprint_rows: list[str] = []
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("자료팩 manifest의 files가 목록이 아닙니다.")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(
                "자료팩 manifest의 파일 항목 모양이 잘못됐습니다."
            )
        relative = pack_rel(entry.get("path", ""))
        if (
            not relative
            or relative == "manifest.json"
            or relative in declared
        ):
            raise ValueError(
                "자료팩 manifest에 위험하거나 중복된 경로가 있습니다."
            )
        member = members.get(relative)
        if not member:
            raise ValueError(f"자료팩 내용이 빠졌습니다: {relative}")
        raw = archive.read(member)
        digest = hashlib.sha256(raw).hexdigest()
        if (
            len(raw) != int(entry.get("size", -1))
            or digest != entry.get("sha256")
        ):
            raise ValueError(
                f"자료팩 내용 검사가 실패했습니다: {relative}"
            )
        declared.add(relative)
        fingerprint_rows.append(
            f"{relative}\t{len(raw)}\t{digest}"
        )
    fingerprint = hashlib.sha256(
        "\n".join(sorted(fingerprint_rows)).encode("utf-8")
    ).hexdigest()
    if manifest.get("content_sha256") != fingerprint:
        raise ValueError(
            "자료팩 전체 내용 지문이 manifest와 다릅니다."
        )

    known_lists = set(datapack_lists(paths))
    known_whole = set(datapack_whole_files(paths))
    for relative in members:
        stem = Path(relative).name
        is_data = (
            stem in known_lists
            or stem in known_whole
            or relative.startswith((
                "세팅/",
                "캐릭터/",
                "태그/",
                "수집/이미지캐시/",
            ))
        )
        if is_data and relative not in declared:
            raise ValueError(
                f"manifest에 기록되지 않은 자료가 들어 있습니다: {relative}"
            )
    return {
        "id": str(manifest.get("id") or ""),
        "name": str(manifest.get("name") or ""),
        "version": str(manifest.get("version") or ""),
        "content_sha256": fingerprint,
        "files": len(declared),
    }


def datapack_conflict_id(
    operations: DatapackOperations,
    archive_sha: str,
    logical: str,
    key: str,
    current: Any,
    incoming: Any,
) -> tuple[str, str, str]:
    current_sha = operations.row_digest(current)
    incoming_sha = operations.row_digest(incoming)
    value = (
        f"{archive_sha}\0{logical}\0{key}\0"
        f"{current_sha}\0{incoming_sha}"
    )
    return (
        hashlib.sha256(value.encode("utf-8")).hexdigest(),
        current_sha,
        incoming_sha,
    )


def datapack_character_destination(
    paths: DatapackPaths,
    operations: DatapackOperations,
    raw: bytes,
    fallback: Path,
) -> Path:
    """파일명이 달라도 안정적인 캐릭터 id가 같으면 기존 파일을 갱신한다."""
    try:
        incoming = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return fallback
    character_id = (
        str(incoming.get("id") or "")
        if isinstance(incoming, dict)
        else ""
    )
    if not character_id or not paths.character_dir.is_dir():
        return fallback
    for path in paths.character_dir.rglob("*.json"):
        try:
            current = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if (
            isinstance(current, dict)
            and str(current.get("id") or "") == character_id
        ):
            return path
    return fallback


@dataclass
class _DatapackPreviewState:
    paths: DatapackPaths
    operations: DatapackOperations
    archive_sha: str
    lists: dict[str, tuple[Path, str]]
    whole: dict[str, Path]
    conflicts: list[dict[str, Any]]
    recognized: int = 0


def _add_preview_conflict(
    state: _DatapackPreviewState,
    logical: str,
    key: str,
    current: Any,
    incoming: Any,
    kind: str,
) -> None:
    conflict_id, current_sha, incoming_sha = datapack_conflict_id(
        state.operations,
        state.archive_sha,
        logical,
        key,
        current,
        incoming,
    )
    state.conflicts.append({
        "id": conflict_id,
        "logical": logical,
        "key": str(key),
        "kind": kind,
        "current": copy.deepcopy(current),
        "incoming": copy.deepcopy(incoming),
        "current_sha256": current_sha,
        "incoming_sha256": incoming_sha,
    })


def _preview_list_asset(
    state: _DatapackPreviewState,
    stem: str,
    raw: bytes,
    renamed: dict[str, str] | None = None,
) -> bool:
    spot = state.lists.get(stem)
    if not spot:
        return False
    state.recognized += 1
    destination, key = spot
    rows, _how = read_rows(raw)
    if rows is None:
        return True
    if renamed:
        rows = rewrite_local_image_refs(rows, renamed)
    current = _preview_current_list(destination)
    by_key: dict[str, dict] = {}
    for item in current:
        if isinstance(item, dict):
            by_key.setdefault(datapack_match_key(item, key), item)
    for item in rows:
        if not isinstance(item, dict):
            continue
        item_key = datapack_match_key(item, key)
        before = by_key.get(item_key, _BACKUP_MISSING)
        if before is not _BACKUP_MISSING and before != item:
            _add_preview_conflict(
                state,
                stem,
                item_key,
                before,
                item,
                "목록 자산",
            )
    return True


def _preview_current_list(destination: Path) -> list[Any]:
    if not destination.is_file():
        return []
    try:
        loaded = json.loads(destination.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(
            f"{destination.name}을 읽지 못해 자료팩을 비교할 수 없습니다: {exc}"
        ) from exc
    if not isinstance(loaded, list):
        raise ValueError(
            f"{destination.name}이 목록이 아니라 자료팩을 비교할 수 없습니다."
        )
    return loaded


def _preview_whole_asset(
    state: _DatapackPreviewState,
    logical: str,
    raw: bytes,
    destination: Path,
    kind: str,
) -> None:
    state.recognized += 1
    try:
        incoming = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return
    if not isinstance(incoming, dict) or not destination.is_file():
        return
    try:
        current = json.loads(destination.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(
            f"{destination.name}을 읽지 못해 자료팩을 비교할 수 없습니다: {exc}"
        ) from exc
    if current != incoming:
        _add_preview_conflict(
            state,
            logical,
            logical,
            current,
            incoming,
            kind,
        )


def _preview_image_renames(
    state: _DatapackPreviewState,
    archive: zipfile.ZipFile,
) -> dict[str, str]:
    renamed: dict[str, str] = {}
    extensions = datapack_dirs(state.paths)["수집/이미지캐시"][1]
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        relative = pack_rel(name)
        if relative and relative.startswith("수집/이미지캐시/"):
            stem = Path(relative).name
            if Path(stem).suffix.lower() in extensions:
                renamed[stem] = content_image_name(
                    stem,
                    archive.read(name),
                )
    return renamed


def _preview_archive_members(
    state: _DatapackPreviewState,
    archive: zipfile.ZipFile,
    renamed: dict[str, str],
) -> None:
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        relative = pack_rel(name)
        if not relative:
            continue
        stem = Path(relative).name
        raw = archive.read(name)
        if _preview_list_asset(state, stem, raw, renamed):
            continue
        if stem in state.whole and not relative.startswith("세팅/"):
            _preview_whole_asset(
                state, stem, raw, state.whole[stem], "기본 자료"
            )
        elif relative.startswith("세팅/") and stem.lower().endswith(".json"):
            _preview_whole_asset(
                state,
                relative,
                raw,
                state.paths.settings_dir / stem,
                "세팅",
            )
        elif relative.startswith("캐릭터/") and stem.lower().endswith(".json"):
            destination = datapack_character_destination(
                state.paths,
                state.operations,
                raw,
                state.paths.character_dir
                / Path(relative).relative_to("캐릭터"),
            )
            _preview_whole_asset(
                state,
                relative,
                raw,
                destination,
                "캐릭터",
            )


def _preview_datapack_archive(
    state: _DatapackPreviewState,
    data: bytes,
    filename: str,
    schema: str,
) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = validate_datapack_manifest(
            state.paths,
            archive,
            schema=schema,
        )
        renamed = _preview_image_renames(state, archive)
        _preview_archive_members(state, archive, renamed)
    return (
        (manifest or {}).get("name")
        or (manifest or {}).get("id")
        or Path(filename).name
        or "자료팩"
    )


def _preview_single_datapack(
    state: _DatapackPreviewState,
    data: bytes,
    filename: str,
) -> str | dict[str, Any]:
    stem = Path(filename).name
    if _preview_list_asset(state, stem, data):
        return stem
    if stem in state.whole:
        _preview_whole_asset(
            state,
            stem,
            data,
            state.whole[stem],
            "기본 자료",
        )
        return stem
    return {"ok": False, "error": f"'{stem}' 은(는) 자료팩이 아닙니다."}


def preview_datapack_bytes(
    paths: DatapackPaths,
    operations: DatapackOperations,
    data: bytes,
    filename: str = "",
    *,
    schema: str = "nais-datapack/v1",
) -> dict[str, Any]:
    """쓰기 전에 같은 식별자지만 다른 자산만 안정적인 충돌 목록으로 만든다."""
    archive_sha = hashlib.sha256(data).hexdigest()
    state = _DatapackPreviewState(
        paths=paths,
        operations=operations,
        archive_sha=archive_sha,
        lists=datapack_lists(paths),
        whole=datapack_whole_files(paths),
        conflicts=[],
    )
    if data[:2] == b"PK":
        pack_name = _preview_datapack_archive(
            state,
            data,
            filename,
            schema,
        )
    else:
        pack_name = _preview_single_datapack(state, data, filename)
        if isinstance(pack_name, dict):
            return pack_name

    if not state.recognized:
        return {
            "ok": False,
            "error": "자료팩에서 알아볼 수 있는 자료를 못 찾았습니다.",
        }
    state.conflicts.sort(key=lambda item: (item["logical"], item["key"]))
    fingerprint = hashlib.sha256(
        "\n".join(item["id"] for item in state.conflicts).encode("ascii")
    ).hexdigest()
    return {
        "ok": True,
        "name": pack_name,
        "sha256": archive_sha,
        "diff_fingerprint": fingerprint,
        "conflicts": state.conflicts,
        "conflict_count": len(state.conflicts),
    }


@dataclass
class _DatapackImportState:
    paths: DatapackPaths
    operations: DatapackOperations
    lists: dict[str, tuple[Path, str]]
    dirs: dict[str, tuple[Path, tuple[str, ...]]]
    whole: dict[str, Path]
    overwrite: bool
    selected_list_keys: dict[str, set[str]]
    selected_whole: set[str]
    report: list[str]
    batch: dict[str, Any]
    local_image_renames: dict[str, str]
    files: int = 0


def _selected_import_conflicts(
    paths: DatapackPaths,
    operations: DatapackOperations,
    data: bytes,
    filename: str,
    selected_conflicts: Any,
    expected_diff: str,
    schema: str,
) -> tuple[dict[str, set[str]], set[str], dict[str, Any] | None]:
    selected_lists: dict[str, set[str]] = {}
    selected_whole: set[str] = set()
    if selected_conflicts is None:
        return selected_lists, selected_whole, None
    preview = preview_datapack_bytes(
        paths,
        operations,
        data,
        filename,
        schema=schema,
    )
    if not preview.get("ok"):
        return selected_lists, selected_whole, preview
    if expected_diff and expected_diff != preview["diff_fingerprint"]:
        return selected_lists, selected_whole, {
            "ok": False,
            "conflict": True,
            "error": "검사 뒤 현재 자료가 바뀌었습니다. 자료팩을 다시 검사해 주세요.",
        }
    by_id = {item["id"]: item for item in preview["conflicts"]}
    wanted_ids = set(map(str, selected_conflicts))
    if wanted_ids - set(by_id):
        return selected_lists, selected_whole, {
            "ok": False,
            "conflict": True,
            "error": "검사 뒤 충돌 항목이 바뀌었습니다. 자료팩을 다시 검사해 주세요.",
        }
    for item_id in wanted_ids:
        item = by_id[item_id]
        if item["kind"] == "목록 자산":
            selected_lists.setdefault(item["logical"], set()).add(item["key"])
        else:
            selected_whole.add(item["logical"])
    return selected_lists, selected_whole, None


def _new_import_state(
    paths: DatapackPaths,
    operations: DatapackOperations,
    data: bytes,
    filename: str,
    overwrite: bool,
    selected_lists: dict[str, set[str]],
    selected_whole: set[str],
) -> _DatapackImportState:
    batch_id = f"{int(time.time())}-{os.urandom(4).hex()}"
    return _DatapackImportState(
        paths=paths,
        operations=operations,
        lists=datapack_lists(paths),
        dirs=datapack_dirs(paths),
        whole=datapack_whole_files(paths),
        overwrite=overwrite,
        selected_list_keys=selected_lists,
        selected_whole=selected_whole,
        report=[],
        batch={
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "file": Path(filename).name or "자료팩",
            "id": batch_id,
            "lists": {},
            "files": {},
            "installed": [],
            "archive_sha256": hashlib.sha256(data).hexdigest(),
        },
        local_image_renames={},
    )


def _take_whole_import(
    state: _DatapackImportState,
    label: str,
    raw: bytes,
    destination: Path,
) -> bool:
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        state.report.append(f"{label}: JSON으로 읽지 못해 건너뜀")
        return True
    if not isinstance(parsed, dict):
        state.report.append(f"{label}: JSON 객체가 아니라 건너뜀")
        return True
    canonical = json.dumps(parsed, ensure_ascii=False, indent=1).encode("utf-8")
    relative = destination.relative_to(state.paths.base_dir).as_posix()
    digest = hashlib.sha256(canonical).hexdigest()
    if destination.exists():
        if _same_whole_asset(state, destination, parsed):
            state.report.append(f"{label}: 이미 같은 자료가 있음")
            return True
        if not state.overwrite and label not in state.selected_whole:
            state.report.append(f"{label}: 기존 자료가 달라 그대로 둠")
            return True
        _replace_whole_asset(state, label, destination, canonical, relative, digest)
    else:
        state.operations.atomic_write_bytes(
            destination,
            canonical,
            keep_backup=False,
        )
        state.batch["installed"].append({"path": relative, "sha256": digest})
        state.report.append(f"{label}: 새로 넣음")
    state.files += 1
    return True


def _same_whole_asset(
    state: _DatapackImportState,
    destination: Path,
    parsed: dict,
) -> bool:
    try:
        return state.operations.load_json(destination) == parsed
    except Exception:
        return False


def _replace_whole_asset(
    state: _DatapackImportState,
    label: str,
    destination: Path,
    canonical: bytes,
    relative: str,
    digest: str,
) -> None:
    backup = (
        state.paths.base_dir
        / "수집"
        / "가져온백업"
        / state.batch["id"]
        / relative
    )
    state.operations.atomic_write_bytes(
        backup,
        destination.read_bytes(),
        keep_backup=False,
    )
    state.operations.atomic_write_bytes(destination, canonical)
    state.batch["installed"].append({
        "path": relative,
        "backup": backup.relative_to(state.paths.base_dir).as_posix(),
        "sha256": digest,
    })
    state.report.append(f"{label}: 기존 자료를 백업하고 새 것으로 바꿈")


def _take_list_import(
    state: _DatapackImportState,
    stem: str,
    raw: bytes,
) -> bool:
    spot = state.lists.get(stem)
    if not spot:
        return False
    destination, key = spot
    rows, how = read_rows(raw)
    if rows is None:
        state.report.append(f"{stem}: {how}")
        return True
    if state.local_image_renames:
        rows = rewrite_local_image_refs(rows, state.local_image_renames)
    counts, keys, updates = merge_list_json(
        state.operations,
        destination,
        rows,
        key,
        state.overwrite,
        replace_keys=state.selected_list_keys.get(stem),
    )
    state.report.append(
        f"{stem}: {say_counts(counts)}" + (f" ({how})" if how else "")
    )
    if keys:
        state.batch["lists"][stem] = keys
    for update in updates:
        state.batch.setdefault("list_updates", []).append({
            "stem": stem,
            **update,
        })
    state.files += counts["새로"] + counts["덮어씀"]
    return True


def _archive_image_payloads(
    state: _DatapackImportState,
    archive: zipfile.ZipFile,
) -> dict[str, tuple[bytes, str]]:
    payloads: dict[str, tuple[bytes, str]] = {}
    extensions = state.dirs["수집/이미지캐시"][1]
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        relative = pack_rel(name)
        if relative is None or not relative.startswith("수집/이미지캐시/"):
            continue
        stem = Path(relative).name
        if Path(stem).suffix.lower() not in extensions:
            continue
        raw = archive.read(name)
        correct = content_image_name(stem, raw)
        state.local_image_renames[stem] = correct
        payloads[name] = (raw, correct)
    return payloads


def _install_directory_asset(
    state: _DatapackImportState,
    directory: str,
    root: Path,
    stem: str,
    raw: bytes,
    saved_name: str,
    copied: dict[str, int],
    skipped: dict[str, int],
) -> None:
    destination = root / saved_name
    if destination.exists() and destination.read_bytes() == raw:
        skipped[directory] = skipped.get(directory, 0) + 1
    elif destination.exists():
        _replace_directory_asset(
            state,
            directory,
            destination,
            raw,
            copied,
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        state.operations.atomic_write_bytes(
            destination,
            raw,
            keep_backup=False,
        )
        copied[directory] = copied.get(directory, 0) + 1
        state.batch["files"].setdefault(directory, []).append(saved_name)


def _replace_directory_asset(
    state: _DatapackImportState,
    directory: str,
    destination: Path,
    raw: bytes,
    copied: dict[str, int],
) -> None:
    relative = destination.relative_to(state.paths.base_dir).as_posix()
    backup = (
        state.paths.base_dir
        / "수집"
        / "가져온백업"
        / state.batch["id"]
        / relative
    )
    state.operations.atomic_write_bytes(
        backup,
        destination.read_bytes(),
        keep_backup=False,
    )
    state.operations.atomic_write_bytes(
        destination,
        raw,
        keep_backup=False,
    )
    copied[directory] = copied.get(directory, 0) + 1
    state.batch["installed"].append({
        "path": relative,
        "backup": backup.relative_to(state.paths.base_dir).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    })


def _install_archive_member(
    state: _DatapackImportState,
    archive: zipfile.ZipFile,
    name: str,
    image_payloads: dict[str, tuple[bytes, str]],
    copied: dict[str, int],
    skipped: dict[str, int],
) -> int:
    relative = pack_rel(name)
    if relative is None:
        return 0
    stem = Path(relative).name
    if _take_list_import(state, stem, archive.read(name)):
        return 0
    if stem in state.whole and not relative.startswith("세팅/"):
        _take_whole_import(state, stem, archive.read(name), state.whole[stem])
        return 0
    if relative.startswith("세팅/") and stem.lower().endswith(".json"):
        _take_whole_import(
            state, relative, archive.read(name), state.paths.settings_dir / stem
        )
        return 0
    if relative.startswith("캐릭터/") and stem.lower().endswith(".json"):
        raw = archive.read(name)
        destination = datapack_character_destination(
            state.paths,
            state.operations,
            raw,
            state.paths.character_dir
            / Path(relative).relative_to("캐릭터"),
        )
        _take_whole_import(state, relative, raw, destination)
        return 0
    for directory, (root, extensions) in state.dirs.items():
        if relative.startswith(directory + "/") and stem.lower().endswith(extensions):
            raw, saved_name = image_payloads.get(
                name,
                (archive.read(name), stem),
            )
            _install_directory_asset(
                state,
                directory,
                root,
                stem,
                raw,
                saved_name,
                copied,
                skipped,
            )
            return int(
                directory == "수집/이미지캐시" and saved_name != stem
            )
    return 0


def _append_directory_report(
    state: _DatapackImportState,
    copied: dict[str, int],
    skipped: dict[str, int],
    renamed: int,
) -> None:
    for directory in state.dirs:
        copied_count = copied.get(directory, 0)
        skipped_count = skipped.get(directory, 0)
        if copied_count or skipped_count:
            state.files += copied_count
            state.report.append(
                f"{directory}: 새로 {copied_count}개"
                + (
                    f" · 이미 있음 {skipped_count}개"
                    if skipped_count
                    else ""
                )
            )
    if renamed:
        state.report.append(
            f"이미지 내용 주소: 이름이 달랐던 {renamed}개를 바로잡음"
        )


def _import_datapack_archive(
    state: _DatapackImportState,
    data: bytes,
    schema: str,
) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = validate_datapack_manifest(
            state.paths,
            archive,
            schema=schema,
        )
        if manifest:
            state.batch["manifest"] = manifest
            state.report.append(
                f"자료팩 확인: "
                f"{manifest['name'] or manifest['id'] or '이름 없음'}"
                f" · 파일 {manifest['files']}개 · SHA-256 "
                f"{manifest['content_sha256'][:12]}"
            )
        image_payloads = _archive_image_payloads(state, archive)
        copied: dict[str, int] = {}
        skipped: dict[str, int] = {}
        renamed = 0
        for name in archive.namelist():
            if not name.endswith("/"):
                renamed += _install_archive_member(
                    state,
                    archive,
                    name,
                    image_payloads,
                    copied,
                    skipped,
                )
        _append_directory_report(state, copied, skipped, renamed)


def _import_single_datapack(
    state: _DatapackImportState,
    data: bytes,
    filename: str,
) -> dict[str, Any] | None:
    stem = Path(filename).name
    if stem in state.whole:
        _take_whole_import(state, stem, data, state.whole[stem])
        return None
    if _take_list_import(state, stem, data):
        return None
    return {
        "ok": False,
        "error": (
            f"'{stem}' 은(는) 자료팩이 아닙니다. 자료팩.zip 이나 "
            f"{' · '.join(list(state.lists) + list(state.whole))} 를 넣어 주세요."
        ),
    }


def _finalize_datapack_import(
    state: _DatapackImportState,
    filename: str,
) -> dict[str, Any]:
    if not state.report:
        return {
            "ok": False,
            "error": "자료팩에서 알아볼 수 있는 자료를 못 찾았습니다.",
        }
    if (
        state.batch["lists"]
        or state.batch["files"]
        or state.batch["installed"]
        or state.batch.get("list_updates")
    ):
        state.batch["새로"] = state.files
        state.batch["요약"] = " · ".join(state.report)
        rows = load_pack_log(state.paths, state.operations)
        rows.append(state.batch)
        save_pack_log(state.paths, state.operations, rows)
    result = {
        "ok": True,
        "added": state.files,
        "report": state.report,
        "batch": state.batch.get("id"),
        "archive_sha256": state.batch.get("archive_sha256"),
        "log": pack_log_brief(state.paths, state.operations),
    }
    queue = state.operations.pack_queue(
        {**result, "batch_record": copy.deepcopy(state.batch)},
        filename=filename,
    )
    result["restoration"] = state.operations.summarize_queue(queue)
    result["restoration_queue"] = queue
    return result


def _transaction_boundary(
    paths: DatapackPaths,
    operations: DatapackOperations,
) -> tuple[file_txn.FileTransactionPaths, file_txn.FileTransactionOperations]:
    """설치가 쓸 파일 트랜잭션 경계를 주입된 공통 경계로 조립한다."""
    txn_paths = file_txn.FileTransactionPaths(root=paths.base_dir)
    txn_ops = file_txn.FileTransactionOperations(
        transaction=operations.transaction,
        atomic_write_bytes=operations.atomic_write_bytes,
        atomic_write_json=operations.atomic_write_json,
        load_json=operations.load_json,
        replace=operations.replace,
        info=lambda *_: None,
        warning=operations.warning,
    )
    return txn_paths, txn_ops


def _stage_rel(paths: DatapackPaths, path: Any) -> str | None:
    """staging 대상 판정. base_dir 밖·가져온백업·journal은 즉시 쓴다."""
    try:
        relative = Path(path).resolve().relative_to(
            Path(paths.base_dir).resolve())
    except (OSError, ValueError):
        return None
    posix = relative.as_posix()
    if posix.startswith("수집/가져온백업/") or posix.startswith(".nai-studio/"):
        return None
    return posix


def _staged_operations(
    paths: DatapackPaths,
    operations: DatapackOperations,
    txn_paths: file_txn.FileTransactionPaths,
    txn_ops: file_txn.FileTransactionOperations,
    journal: dict,
    staged: dict[str, bytes],
) -> DatapackOperations:
    """설치 중 대상 파일 쓰기를 staging으로 돌린 operations 사본.

    방금 stage한 파일의 재읽기는 staged 내용을 돌려준다.
    ponytail: 디스크에 없는 파일을 한 ZIP에서 같은 이름으로 두 번 넣는
    기형 자료팩은 뒤의 내용이 이긴다 — 정상 자료팩에는 없는 모양이다.
    """

    def write_bytes(path, payload, keep_backup=True, **kwargs):
        relative = _stage_rel(paths, path)
        if relative is None:
            operations.atomic_write_bytes(
                path, payload, keep_backup=keep_backup, **kwargs)
            return
        file_txn.stage_file_bytes(
            txn_paths, txn_ops, journal, relative, bytes(payload))
        staged[relative] = bytes(payload)

    def write_json(path, data, indent=2, keep_backup=True, **kwargs):
        raw = json.dumps(
            data, ensure_ascii=False, indent=indent).encode("utf-8")
        write_bytes(path, raw, keep_backup=keep_backup)

    def load_json(path):
        relative = _stage_rel(paths, path)
        if relative is not None and relative in staged:
            return json.loads(staged[relative].decode("utf-8"))
        return operations.load_json(path)

    return dataclasses.replace(
        operations,
        atomic_write_bytes=write_bytes,
        atomic_write_json=write_json,
        load_json=load_json,
    )


def _import_datapack_bytes(
    paths: DatapackPaths,
    operations: DatapackOperations,
    data: bytes,
    filename: str,
    overwrite: bool,
    selected_conflicts: Any,
    expected_diff: str,
    schema: str,
) -> dict[str, Any]:
    selected_lists, selected_whole, error = _selected_import_conflicts(
        paths,
        operations,
        data,
        filename,
        selected_conflicts,
        expected_diff,
        schema,
    )
    if error:
        return error
    state = _new_import_state(
        paths,
        operations,
        data,
        filename,
        overwrite,
        selected_lists,
        selected_whole,
    )
    # 설치 전체를 staging에 준비하고 journal과 함께 파일별 교체로 반영한다.
    # 여기서 중단되면 기동 복구가 이어서 완료하거나 전체 되돌린다.
    txn_paths, txn_ops = _transaction_boundary(paths, operations)
    journal = file_txn.begin_file_transaction(
        txn_paths, txn_ops, f"자료팩 적용: {state.batch['file']}")
    staged: dict[str, bytes] = {}
    state.operations = _staged_operations(
        paths, operations, txn_paths, txn_ops, journal, staged)
    if data[:2] == b"PK":
        _import_datapack_archive(state, data, schema)
    else:
        error = _import_single_datapack(state, data, filename)
        if error:
            return error
    state.batch["transaction"] = journal["id"]
    file_txn.commit_file_transaction(txn_paths, txn_ops, journal)
    state.operations = operations
    return _finalize_datapack_import(state, filename)


def import_datapack_bytes(
    paths: DatapackPaths,
    operations: DatapackOperations,
    data: bytes,
    filename: str = "",
    overwrite: bool = False,
    selected_conflicts: Any = None,
    expected_diff: str = "",
    *,
    schema: str = "nais-datapack/v1",
) -> dict[str, Any]:
    """현재 자료 뿌리를 잠근 뒤 ZIP·낱개 JSON을 기존 규칙대로 장착한다."""
    with operations.transaction(paths.base_dir):
        return _import_datapack_bytes(
            paths,
            operations,
            data,
            filename,
            overwrite,
            selected_conflicts,
            expected_diff,
            schema,
        )


def pack_log_brief(
    paths: DatapackPaths,
    operations: DatapackOperations,
) -> list[dict[str, Any]]:
    """화면에는 큰 Undo 원장 대신 판별 가능한 요약만 반환한다."""
    return [
        {
            "id": batch.get("id"),
            "at": batch.get("at"),
            "file": batch.get("file"),
            "kind": batch.get("kind", "datapack"),
            "새로": batch.get("새로", 0),
            "요약": batch.get("요약", ""),
            "pack_id": (batch.get("manifest") or {}).get("id", ""),
            "pack_name": (batch.get("manifest") or {}).get("name", ""),
            "content_sha256": (batch.get("manifest") or {}).get(
                "content_sha256",
                batch.get("archive_sha256", ""),
            ),
        }
        for batch in reversed(load_pack_log(paths, operations))
    ]


@dataclass
class _DatapackUndoState:
    paths: DatapackPaths
    operations: DatapackOperations
    rows: list[dict[str, Any]]
    hit: dict[str, Any]
    lists: dict[str, tuple[Path, str]]
    dirs: dict[str, tuple[Path, tuple[str, ...]]]
    report: list[str]
    failures: list[str]
    changed_config: bool = False


def _undo_list_updates(state: _DatapackUndoState) -> None:
    for update in reversed(state.hit.get("list_updates") or []):
        stem = str(update.get("stem") or "")
        spot = state.lists.get(stem)
        before = update.get("before")
        if not spot or not isinstance(before, dict):
            continue
        path, key = spot
        if not path.is_file():
            continue
        try:
            current_rows = state.operations.load_json(path)
            wanted_key = str(update.get("key") or "")
            index = next(
                (
                    position
                    for position, item in enumerate(current_rows)
                    if isinstance(item, dict)
                    and (
                        datapack_match_key(item, key)
                        if update.get("match_key")
                        else row_key(item, key)[0]
                    )
                    == wanted_key
                ),
                None,
            )
            if index is None:
                state.report.append(f"{stem}: 바뀐 묶음을 찾지 못해 그대로 둠")
                continue
            if (
                state.operations.row_digest(current_rows[index])
                != update.get("after_sha256")
            ):
                state.report.append(f"{stem}: 가져온 뒤 수정되어 그대로 둠")
                continue
            current_rows[index] = before
            state.operations.atomic_write_json(path, current_rows, indent=None)
            state.report.append(f"{stem}: 임포트 전 묶음으로 복구")
        except Exception as exc:
            state.operations.warning(f"임포트 목록 갱신 되돌리기 실패: {exc}")
            state.failures.append(f"{stem}: 목록 갱신 복구 실패")


def _undo_list_additions(state: _DatapackUndoState) -> None:
    for stem, keys in (state.hit.get("lists") or {}).items():
        spot = state.lists.get(stem)
        if not spot or not keys:
            continue
        path, key = spot
        if not path.exists():
            continue
        try:
            old = state.operations.load_json(path)
        except Exception as exc:
            state.operations.warning(f"임포트 목록 삭제 되돌리기 실패: {exc}")
            state.failures.append(f"{stem}: 목록 삭제 실패")
            continue
        drop = set(map(str, keys))
        kept = [
            item
            for item in old
            if not (
                isinstance(item, dict)
                and row_key(item, key)[0] in drop
            )
        ]
        removed = len(old) - len(kept)
        if removed:
            state.operations.atomic_write_json(path, kept, indent=None)
            state.report.append(f"{stem}: {removed}건 뺌")


def _undo_directory_files(state: _DatapackUndoState) -> None:
    for directory, names in (state.hit.get("files") or {}).items():
        root = state.dirs.get(directory, (None, ()))[0]
        if not root:
            continue
        removed = 0
        for name in names:
            path = root / name
            try:
                if path.exists():
                    state.operations.recoverable_remove(
                        path,
                        label="자료팩되돌리기",
                    )
                    removed += 1
            except Exception as exc:
                state.operations.warning(f"자료팩 파일 되돌리기 실패: {exc}")
                state.failures.append(f"{directory}/{name}: 파일 이동 실패")
        if removed:
            state.report.append(f"{directory}: {removed}개 지움")


def _undo_installed_asset(
    state: _DatapackUndoState,
    item: dict[str, Any],
) -> None:
    relative = Path(item.get("path", ""))
    destination = (state.paths.base_dir / relative).resolve()
    if state.paths.base_dir.resolve() not in destination.parents:
        return
    if not destination.exists():
        return
    current = hashlib.sha256(destination.read_bytes()).hexdigest()
    if current != item.get("sha256"):
        state.report.append(
            f"{relative.as_posix()}: 가져온 뒤 수정되어 그대로 둠"
        )
        return
    backup_relative = item.get("backup")
    if not backup_relative:
        state.operations.recoverable_remove(
            destination,
            label="자료팩되돌리기",
        )
        state.report.append(f"{relative.as_posix()}: 가져온 파일 뺌")
        return
    backup = (state.paths.base_dir / backup_relative).resolve()
    if (
        backup.exists()
        and state.paths.base_dir.resolve() in backup.parents
    ):
        state.operations.atomic_write_bytes(destination, backup.read_bytes())
        backup.unlink()
        state.report.append(f"{relative.as_posix()}: 이전 자료 복구")
    else:
        state.failures.append(f"{relative.as_posix()}: 이전 자료 백업 없음")


def _undo_installed_assets(state: _DatapackUndoState) -> None:
    for item in reversed(state.hit.get("installed") or []):
        try:
            _undo_installed_asset(state, item)
        except Exception as exc:
            state.operations.warning(f"자료팩 전체파일 되돌리기 실패: {exc}")
            state.failures.append(
                f"{Path(item.get('path', '')).as_posix()}: 전체파일 복구 실패"
            )


def _undo_imported_characters(
    state: _DatapackUndoState,
    config: dict | None,
) -> None:
    character_records = state.hit.get("characters") or []
    if config is None or not character_records:
        return
    wanted = {
        str(item.get("id")): str(item.get("after_signature") or "")
        for item in character_records
        if isinstance(item, dict) and item.get("id")
    }
    removed_ids: set[str] = set()
    kept = []
    for character in config.get("characters") or []:
        character_id = str(character.get("id") or "")
        if character_id not in wanted:
            kept.append(character)
            continue
        if (
            wanted[character_id]
            and state.operations.character_signature(character)
            != wanted[character_id]
        ):
            kept.append(character)
            state.report.append(
                f"캐릭터 {character.get('name') or character_id}: "
                "가져온 뒤 수정되어 그대로 둠"
            )
            continue
        removed_ids.add(character_id)
    if not removed_ids:
        return
    config["characters"] = kept
    state.operations.delete_character_files(config, removed_ids)
    state.operations.sync_character_files(config)
    state.operations.save_config(config)
    state.changed_config = True
    state.report.append(f"캐릭터: {len(removed_ids)}건 뺌")


def _finalize_datapack_undo(
    state: _DatapackUndoState,
) -> dict[str, Any]:
    state.operations.forget_caches()
    if state.failures:
        return {
            "ok": False,
            "partial": bool(state.report),
            "error": (
                "일부 항목을 되돌리지 못했습니다. "
                "같은 기록으로 다시 시도할 수 있습니다."
            ),
            "report": state.report + state.failures,
            "log": pack_log_brief(state.paths, state.operations),
            "changed_config": state.changed_config,
        }
    save_pack_log(
        state.paths,
        state.operations,
        [batch for batch in state.rows if batch is not state.hit],
    )
    return {
        "ok": True,
        "report": state.report or ["되돌릴 것이 없었습니다"],
        "log": pack_log_brief(state.paths, state.operations),
        "changed_config": state.changed_config,
    }


def _undo_datapack(
    paths: DatapackPaths,
    operations: DatapackOperations,
    batch_id: Any,
    config: dict | None,
) -> dict[str, Any]:
    rows = load_pack_log(paths, operations)
    hit = next(
        (
            batch
            for batch in rows
            if str(batch.get("id")) == str(batch_id)
        ),
        None,
    )
    if not hit:
        return {"ok": False, "error": "그 기록을 못 찾았습니다."}
    state = _DatapackUndoState(
        paths,
        operations,
        rows,
        hit,
        datapack_lists(paths),
        datapack_dirs(paths),
        [],
        [],
    )
    _undo_list_updates(state)
    _undo_list_additions(state)
    _undo_directory_files(state)
    _undo_installed_assets(state)
    _undo_imported_characters(state, config)
    return _finalize_datapack_undo(state)


def undo_datapack(
    paths: DatapackPaths,
    operations: DatapackOperations,
    batch_id: Any,
    config: dict | None = None,
) -> dict[str, Any]:
    """장부에 기록된 한 판만 잠금 안에서 조건부 복구한다."""
    with operations.transaction(paths.base_dir):
        return _undo_datapack(
            paths,
            operations,
            batch_id,
            config,
        )


__all__ = [
    "DatapackOperations",
    "DatapackPaths",
    "content_image_name",
    "datapack_character_destination",
    "datapack_conflict_id",
    "datapack_dirs",
    "datapack_lists",
    "datapack_match_key",
    "datapack_whole_files",
    "import_datapack_bytes",
    "load_pack_log",
    "merge_list_json",
    "pack_log_brief",
    "pack_log_path",
    "pack_rel",
    "preview_datapack_bytes",
    "read_rows",
    "record_import_batch",
    "rewrite_local_image_refs",
    "row_key",
    "save_pack_log",
    "say_counts",
    "undo_datapack",
    "validate_datapack_manifest",
]
