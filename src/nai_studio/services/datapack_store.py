# -*- coding: utf-8 -*-
"""자료팩 검증·병합·장부·되돌리기의 저장 경계.

이 모듈은 애플리케이션 전역 경로와 설정 객체를 직접 참조하지 않는다. 프로필별 경로와
안전 저장 함수는 호출자가 매번 주입한다. 따라서 기존 HTTP workflow는 미리보기 캐시와
화면 갱신만 맡고, 이 모듈은 동일한 자료 결과를 만드는 파일 작업만 맡는다.
"""

from __future__ import annotations

import copy
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


def preview_datapack_bytes(
    paths: DatapackPaths,
    operations: DatapackOperations,
    data: bytes,
    filename: str = "",
    *,
    schema: str = "nais-datapack/v1",
) -> dict[str, Any]:
    """쓰기 전에 같은 식별자지만 다른 자산만 안정적인 충돌 목록으로 만든다."""
    lists = datapack_lists(paths)
    whole = datapack_whole_files(paths)
    archive_sha = hashlib.sha256(data).hexdigest()
    conflicts: list[dict[str, Any]] = []
    recognized = 0

    def add_conflict(
        logical: str,
        key: str,
        current: Any,
        incoming: Any,
        kind: str,
    ) -> None:
        conflict_id, current_sha, incoming_sha = datapack_conflict_id(
            operations,
            archive_sha,
            logical,
            key,
            current,
            incoming,
        )
        conflicts.append({
            "id": conflict_id,
            "logical": logical,
            "key": str(key),
            "kind": kind,
            "current": copy.deepcopy(current),
            "incoming": copy.deepcopy(incoming),
            "current_sha256": current_sha,
            "incoming_sha256": incoming_sha,
        })

    def inspect_list(
        stem: str,
        raw: bytes,
        renamed: dict[str, str] | None = None,
    ) -> bool:
        nonlocal recognized
        spot = lists.get(stem)
        if not spot:
            return False
        recognized += 1
        destination, key = spot
        rows, _how = read_rows(raw)
        if rows is None:
            return True
        if renamed:
            rows = rewrite_local_image_refs(rows, renamed)
        current: list[Any] = []
        if destination.is_file():
            try:
                loaded = json.loads(
                    destination.read_text(encoding="utf-8-sig")
                )
            except Exception as exc:
                raise ValueError(
                    f"{destination.name}을 읽지 못해 자료팩을 비교할 수 "
                    f"없습니다: {exc}"
                ) from exc
            if not isinstance(loaded, list):
                raise ValueError(
                    f"{destination.name}이 목록이 아니라 자료팩을 비교할 수 "
                    "없습니다."
                )
            current = loaded
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
                add_conflict(
                    stem,
                    item_key,
                    before,
                    item,
                    "목록 자산",
                )
        return True

    def inspect_whole(
        logical: str,
        raw: bytes,
        destination: Path,
        kind: str,
    ) -> None:
        nonlocal recognized
        recognized += 1
        try:
            incoming = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            return
        if not isinstance(incoming, dict) or not destination.is_file():
            return
        try:
            current = json.loads(
                destination.read_text(encoding="utf-8-sig")
            )
        except Exception as exc:
            raise ValueError(
                f"{destination.name}을 읽지 못해 자료팩을 비교할 수 "
                f"없습니다: {exc}"
            ) from exc
        if current != incoming:
            add_conflict(logical, logical, current, incoming, kind)

    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = validate_datapack_manifest(
                paths,
                archive,
                schema=schema,
            )
            renamed: dict[str, str] = {}
            image_extensions = datapack_dirs(paths)[
                "수집/이미지캐시"
            ][1]
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                relative = pack_rel(name)
                if (
                    relative
                    and relative.startswith("수집/이미지캐시/")
                ):
                    stem = Path(relative).name
                    if Path(stem).suffix.lower() in image_extensions:
                        renamed[stem] = content_image_name(
                            stem,
                            archive.read(name),
                        )
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                relative = pack_rel(name)
                if not relative:
                    continue
                stem = Path(relative).name
                raw = archive.read(name)
                if stem in lists:
                    inspect_list(stem, raw, renamed)
                elif stem in whole and not relative.startswith("세팅/"):
                    inspect_whole(
                        stem,
                        raw,
                        whole[stem],
                        "기본 자료",
                    )
                elif (
                    relative.startswith("세팅/")
                    and stem.lower().endswith(".json")
                ):
                    inspect_whole(
                        relative,
                        raw,
                        paths.settings_dir / stem,
                        "세팅",
                    )
                elif (
                    relative.startswith("캐릭터/")
                    and stem.lower().endswith(".json")
                ):
                    inspect_whole(
                        relative,
                        raw,
                        datapack_character_destination(
                            paths,
                            operations,
                            raw,
                            paths.character_dir
                            / Path(relative).relative_to("캐릭터"),
                        ),
                        "캐릭터",
                    )
            pack_name = (
                (manifest or {}).get("name")
                or (manifest or {}).get("id")
                or Path(filename).name
                or "자료팩"
            )
    else:
        stem = Path(filename).name
        if stem in lists:
            inspect_list(stem, data)
        elif stem in whole:
            inspect_whole(stem, data, whole[stem], "기본 자료")
        else:
            return {
                "ok": False,
                "error": f"'{stem}' 은(는) 자료팩이 아닙니다.",
            }
        pack_name = stem

    if not recognized:
        return {
            "ok": False,
            "error": "자료팩에서 알아볼 수 있는 자료를 못 찾았습니다.",
        }
    conflicts.sort(key=lambda item: (item["logical"], item["key"]))
    fingerprint = hashlib.sha256(
        "\n".join(item["id"] for item in conflicts).encode("ascii")
    ).hexdigest()
    return {
        "ok": True,
        "name": pack_name,
        "sha256": archive_sha,
        "diff_fingerprint": fingerprint,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
    }


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
    lists = datapack_lists(paths)
    dirs = datapack_dirs(paths)
    whole = datapack_whole_files(paths)
    selected_list_keys: dict[str, set[str]] = {}
    selected_whole: set[str] = set()
    if selected_conflicts is not None:
        preview = preview_datapack_bytes(
            paths,
            operations,
            data,
            filename,
            schema=schema,
        )
        if not preview.get("ok"):
            return preview
        if expected_diff and expected_diff != preview["diff_fingerprint"]:
            return {
                "ok": False,
                "conflict": True,
                "error": (
                    "검사 뒤 현재 자료가 바뀌었습니다. "
                    "자료팩을 다시 검사해 주세요."
                ),
            }
        by_id = {item["id"]: item for item in preview["conflicts"]}
        wanted_ids = set(map(str, selected_conflicts))
        if wanted_ids - set(by_id):
            return {
                "ok": False,
                "conflict": True,
                "error": (
                    "검사 뒤 충돌 항목이 바뀌었습니다. "
                    "자료팩을 다시 검사해 주세요."
                ),
            }
        for item_id in wanted_ids:
            item = by_id[item_id]
            if item["kind"] == "목록 자산":
                selected_list_keys.setdefault(
                    item["logical"],
                    set(),
                ).add(item["key"])
            else:
                selected_whole.add(item["logical"])

    report: list[str] = []
    files = 0
    batch_id = f"{int(time.time())}-{os.urandom(4).hex()}"
    batch: dict[str, Any] = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file": Path(filename).name or "자료팩",
        "id": batch_id,
        "lists": {},
        "files": {},
        "installed": [],
        "archive_sha256": hashlib.sha256(data).hexdigest(),
    }

    def take_whole(label: str, raw: bytes, destination: Path) -> bool:
        nonlocal files
        try:
            parsed = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            report.append(f"{label}: JSON으로 읽지 못해 건너뜀")
            return True
        if not isinstance(parsed, dict):
            report.append(f"{label}: JSON 객체가 아니라 건너뜀")
            return True
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            indent=1,
        ).encode("utf-8")
        relative = destination.relative_to(paths.base_dir).as_posix()
        digest = hashlib.sha256(canonical).hexdigest()
        if destination.exists():
            try:
                same = operations.load_json(destination) == parsed
            except Exception:
                same = False
            if same:
                report.append(f"{label}: 이미 같은 자료가 있음")
                return True
            if not overwrite and label not in selected_whole:
                report.append(f"{label}: 기존 자료가 달라 그대로 둠")
                return True
            backup = (
                paths.base_dir
                / "수집"
                / "가져온백업"
                / batch_id
                / relative
            )
            operations.atomic_write_bytes(
                backup,
                destination.read_bytes(),
                keep_backup=False,
            )
            operations.atomic_write_bytes(destination, canonical)
            batch["installed"].append({
                "path": relative,
                "backup": backup.relative_to(
                    paths.base_dir
                ).as_posix(),
                "sha256": digest,
            })
            report.append(
                f"{label}: 기존 자료를 백업하고 새 것으로 바꿈"
            )
        else:
            operations.atomic_write_bytes(
                destination,
                canonical,
                keep_backup=False,
            )
            batch["installed"].append({
                "path": relative,
                "sha256": digest,
            })
            report.append(f"{label}: 새로 넣음")
        files += 1
        return True

    local_image_renames: dict[str, str] = {}

    def take_list(stem: str, raw: bytes) -> bool:
        nonlocal files
        spot = lists.get(stem)
        if not spot:
            return False
        destination, key = spot
        rows, how = read_rows(raw)
        if rows is None:
            report.append(f"{stem}: {how}")
            return True
        if local_image_renames:
            rows = rewrite_local_image_refs(rows, local_image_renames)
        counts, keys, updates = merge_list_json(
            operations,
            destination,
            rows,
            key,
            overwrite,
            replace_keys=selected_list_keys.get(stem),
        )
        report.append(
            f"{stem}: {say_counts(counts)}"
            + (f" ({how})" if how else "")
        )
        if keys:
            batch["lists"][stem] = keys
        for update in updates:
            batch.setdefault("list_updates", []).append({
                "stem": stem,
                **update,
            })
        files += counts["새로"] + counts["덮어씀"]
        return True

    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = validate_datapack_manifest(
                paths,
                archive,
                schema=schema,
            )
            if manifest:
                batch["manifest"] = manifest
                report.append(
                    f"자료팩 확인: "
                    f"{manifest['name'] or manifest['id'] or '이름 없음'}"
                    f" · 파일 {manifest['files']}개 · SHA-256 "
                    f"{manifest['content_sha256'][:12]}"
                )
            image_payloads: dict[str, tuple[bytes, str]] = {}
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                relative = pack_rel(name)
                if (
                    relative is None
                    or not relative.startswith("수집/이미지캐시/")
                ):
                    continue
                stem = Path(relative).name
                if (
                    Path(stem).suffix.lower()
                    not in dirs["수집/이미지캐시"][1]
                ):
                    continue
                raw = archive.read(name)
                correct = content_image_name(stem, raw)
                local_image_renames[stem] = correct
                image_payloads[name] = (raw, correct)

            copied: dict[str, int] = {}
            skipped: dict[str, int] = {}
            renamed = 0
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                relative = pack_rel(name)
                if relative is None:
                    continue
                stem = Path(relative).name
                if stem in lists:
                    take_list(stem, archive.read(name))
                    continue
                if stem in whole and not relative.startswith("세팅/"):
                    take_whole(stem, archive.read(name), whole[stem])
                    continue
                if (
                    relative.startswith("세팅/")
                    and stem.lower().endswith(".json")
                ):
                    take_whole(
                        relative,
                        archive.read(name),
                        paths.settings_dir / stem,
                    )
                    continue
                if (
                    relative.startswith("캐릭터/")
                    and stem.lower().endswith(".json")
                ):
                    raw = archive.read(name)
                    take_whole(
                        relative,
                        raw,
                        datapack_character_destination(
                            paths,
                            operations,
                            raw,
                            paths.character_dir
                            / Path(relative).relative_to("캐릭터"),
                        ),
                    )
                    continue
                for directory, (root, extensions) in dirs.items():
                    if (
                        relative.startswith(directory + "/")
                        and stem.lower().endswith(extensions)
                    ):
                        raw, saved_name = image_payloads.get(
                            name,
                            (archive.read(name), stem),
                        )
                        if (
                            directory == "수집/이미지캐시"
                            and saved_name != stem
                        ):
                            renamed += 1
                        destination = root / saved_name
                        if (
                            destination.exists()
                            and destination.read_bytes() == raw
                        ):
                            skipped[directory] = (
                                skipped.get(directory, 0) + 1
                            )
                        elif destination.exists():
                            relative_destination = destination.relative_to(
                                paths.base_dir
                            ).as_posix()
                            backup = (
                                paths.base_dir
                                / "수집"
                                / "가져온백업"
                                / batch_id
                                / relative_destination
                            )
                            operations.atomic_write_bytes(
                                backup,
                                destination.read_bytes(),
                                keep_backup=False,
                            )
                            operations.atomic_write_bytes(
                                destination,
                                raw,
                                keep_backup=False,
                            )
                            copied[directory] = (
                                copied.get(directory, 0) + 1
                            )
                            batch["installed"].append({
                                "path": relative_destination,
                                "backup": backup.relative_to(
                                    paths.base_dir
                                ).as_posix(),
                                "sha256": hashlib.sha256(
                                    raw
                                ).hexdigest(),
                            })
                        else:
                            destination.parent.mkdir(
                                parents=True,
                                exist_ok=True,
                            )
                            operations.atomic_write_bytes(
                                destination,
                                raw,
                                keep_backup=False,
                            )
                            copied[directory] = (
                                copied.get(directory, 0) + 1
                            )
                            batch["files"].setdefault(
                                directory,
                                [],
                            ).append(saved_name)
                        break
            for directory in dirs:
                copied_count = copied.get(directory, 0)
                skipped_count = skipped.get(directory, 0)
                if copied_count or skipped_count:
                    files += copied_count
                    report.append(
                        f"{directory}: 새로 {copied_count}개"
                        + (
                            f" · 이미 있음 {skipped_count}개"
                            if skipped_count
                            else ""
                        )
                    )
            if renamed:
                report.append(
                    f"이미지 내용 주소: 이름이 달랐던 "
                    f"{renamed}개를 바로잡음"
                )
    else:
        stem = Path(filename).name
        if stem in whole:
            take_whole(stem, data, whole[stem])
        elif not take_list(stem, data):
            return {
                "ok": False,
                "error": (
                    f"'{stem}' 은(는) 자료팩이 아닙니다. "
                    f"자료팩.zip 이나 "
                    f"{' · '.join(list(lists) + list(whole))} 를 넣어 주세요."
                ),
            }

    if not report:
        return {
            "ok": False,
            "error": "자료팩에서 알아볼 수 있는 자료를 못 찾았습니다.",
        }
    if (
        batch["lists"]
        or batch["files"]
        or batch["installed"]
        or batch.get("list_updates")
    ):
        batch["새로"] = files
        batch["요약"] = " · ".join(report)
        rows = load_pack_log(paths, operations)
        rows.append(batch)
        save_pack_log(paths, operations, rows)
    result = {
        "ok": True,
        "added": files,
        "report": report,
        "batch": batch.get("id"),
        "archive_sha256": batch.get("archive_sha256"),
        "log": pack_log_brief(paths, operations),
    }
    queue = operations.pack_queue(
        {**result, "batch_record": copy.deepcopy(batch)},
        filename=filename,
    )
    result["restoration"] = operations.summarize_queue(queue)
    result["restoration_queue"] = queue
    return result


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
    lists = datapack_lists(paths)
    dirs = datapack_dirs(paths)
    report: list[str] = []
    failures: list[str] = []

    for update in reversed(hit.get("list_updates") or []):
        stem = str(update.get("stem") or "")
        spot = lists.get(stem)
        before = update.get("before")
        if not spot or not isinstance(before, dict):
            continue
        path, key = spot
        if not path.is_file():
            continue
        try:
            current_rows = operations.load_json(path)
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
                report.append(f"{stem}: 바뀐 묶음을 찾지 못해 그대로 둠")
                continue
            if (
                operations.row_digest(current_rows[index])
                != update.get("after_sha256")
            ):
                report.append(f"{stem}: 가져온 뒤 수정되어 그대로 둠")
                continue
            current_rows[index] = before
            operations.atomic_write_json(path, current_rows, indent=None)
            report.append(f"{stem}: 임포트 전 묶음으로 복구")
        except Exception as exc:
            operations.warning(f"임포트 목록 갱신 되돌리기 실패: {exc}")
            failures.append(f"{stem}: 목록 갱신 복구 실패")

    for stem, keys in (hit.get("lists") or {}).items():
        spot = lists.get(stem)
        if not spot or not keys:
            continue
        path, key = spot
        if not path.exists():
            continue
        try:
            old = operations.load_json(path)
        except Exception as exc:
            operations.warning(f"임포트 목록 삭제 되돌리기 실패: {exc}")
            failures.append(f"{stem}: 목록 삭제 실패")
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
            operations.atomic_write_json(path, kept, indent=None)
            report.append(f"{stem}: {removed}건 뺌")

    for directory, names in (hit.get("files") or {}).items():
        root = dirs.get(directory, (None, ()))[0]
        if not root:
            continue
        removed = 0
        for name in names:
            path = root / name
            try:
                if path.exists():
                    operations.recoverable_remove(
                        path,
                        label="자료팩되돌리기",
                    )
                    removed += 1
            except Exception as exc:
                operations.warning(
                    f"자료팩 파일 되돌리기 실패: {exc}"
                )
                failures.append(
                    f"{directory}/{name}: 파일 이동 실패"
                )
        if removed:
            report.append(f"{directory}: {removed}개 지움")

    for item in reversed(hit.get("installed") or []):
        try:
            relative = Path(item.get("path", ""))
            destination = (paths.base_dir / relative).resolve()
            if paths.base_dir.resolve() not in destination.parents:
                continue
            if not destination.exists():
                continue
            current = hashlib.sha256(
                destination.read_bytes()
            ).hexdigest()
            if current != item.get("sha256"):
                report.append(
                    f"{relative.as_posix()}: 가져온 뒤 수정되어 그대로 둠"
                )
                continue
            backup_relative = item.get("backup")
            if backup_relative:
                backup = (
                    paths.base_dir / backup_relative
                ).resolve()
                if (
                    backup.exists()
                    and paths.base_dir.resolve() in backup.parents
                ):
                    operations.atomic_write_bytes(
                        destination,
                        backup.read_bytes(),
                    )
                    backup.unlink()
                    report.append(
                        f"{relative.as_posix()}: 이전 자료 복구"
                    )
                else:
                    failures.append(
                        f"{relative.as_posix()}: 이전 자료 백업 없음"
                    )
            else:
                operations.recoverable_remove(
                    destination,
                    label="자료팩되돌리기",
                )
                report.append(
                    f"{relative.as_posix()}: 가져온 파일 뺌"
                )
        except Exception as exc:
            operations.warning(
                f"자료팩 전체파일 되돌리기 실패: {exc}"
            )
            failures.append(
                f"{Path(item.get('path', '')).as_posix()}: "
                "전체파일 복구 실패"
            )

    changed_config = False
    character_records = hit.get("characters") or []
    if config is not None and character_records:
        wanted = {
            str(item.get("id")): str(
                item.get("after_signature") or ""
            )
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
                and operations.character_signature(character)
                != wanted[character_id]
            ):
                kept.append(character)
                report.append(
                    f"캐릭터 "
                    f"{character.get('name') or character_id}: "
                    "가져온 뒤 수정되어 그대로 둠"
                )
                continue
            removed_ids.add(character_id)
        if removed_ids:
            config["characters"] = kept
            operations.delete_character_files(config, removed_ids)
            operations.sync_character_files(config)
            operations.save_config(config)
            changed_config = True
            report.append(f"캐릭터: {len(removed_ids)}건 뺌")

    operations.forget_caches()
    if failures:
        return {
            "ok": False,
            "partial": bool(report),
            "error": (
                "일부 항목을 되돌리지 못했습니다. "
                "같은 기록으로 다시 시도할 수 있습니다."
            ),
            "report": report + failures,
            "log": pack_log_brief(paths, operations),
            "changed_config": changed_config,
        }
    save_pack_log(
        paths,
        operations,
        [batch for batch in rows if batch is not hit],
    )
    return {
        "ok": True,
        "report": report or ["되돌릴 것이 없었습니다"],
        "log": pack_log_brief(paths, operations),
        "changed_config": changed_config,
    }


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
