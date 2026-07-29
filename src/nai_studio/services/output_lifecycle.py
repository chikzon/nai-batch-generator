# -*- coding: utf-8 -*-
"""생성 결과 탐색·휴지통·복원·비교 계보의 파일 생명주기 경계."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class OutputLifecyclePaths:
    """출력 저장소가 해석하는 파일 종류와 내부 휴지통 계약."""

    trash_dir_name: str = ".NAI-휴지통"
    image_extensions: tuple[str, ...] = (
        ".webp",
        ".png",
        ".jpg",
        ".jpeg",
    )
    trash_schema: str = "nais-output-trash/v2"
    directory_count_ttl: float = 30.0


@dataclass(frozen=True)
class OutputLifecycleOperations:
    """현재 프로필의 저장·평가·시간 의존성을 호출 시점에 연결한다.

    legacy 전역을 모듈 import 때 붙잡지 않아 사용자 출력 경로와 시험용 패치가 그대로
    적용된다. 파일 이동 전 manifest, 이름표 잠금, 평가 투영은 기존 공통 경계를 쓴다.
    """

    output_root: Callable[[dict | None], Path]
    atomic_write_json: Callable[..., None]
    load_json: Callable[[Path], Any]
    load_picks: Callable[[], dict]
    save_picks: Callable[[dict], dict]
    picks_lock: Any
    project_evaluations: Callable[..., dict]
    move_file: Callable[[str, str], Any]
    now: Callable[[], Any]
    uuid4: Callable[[], Any]
    clock: Callable[[], float]
    directory_count_cache: dict[str, tuple[int, float]]
    warning: Callable[..., Any]


def path_is_inside(path: Any, root: Any) -> bool:
    """해결된 경로가 지정 뿌리 안인지 현재 플랫폼의 표준 경로 규칙으로 판정한다."""
    candidate = Path(path).resolve()
    boundary = Path(root).resolve()
    try:
        return candidate.is_relative_to(boundary)
    except AttributeError:
        return os.path.commonpath(
            (str(candidate), str(boundary))
        ) == str(boundary)


def output_file_for_preview(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    config: dict | None,
    relative: Any,
) -> Path | None:
    """정상 출력 루트 안의 실제 파일만 미리보기 대상으로 반환한다."""
    relative = str(relative or "").replace("\\", "/")
    if (
        not relative
        or paths.trash_dir_name.casefold()
        in {part.casefold() for part in Path(relative).parts}
    ):
        return None
    root = operations.output_root(config).resolve()
    trash_root = (root / paths.trash_dir_name).resolve()
    candidate = (root / relative).resolve()
    if (
        not path_is_inside(candidate, root)
        or path_is_inside(candidate, trash_root)
        or not candidate.is_file()
    ):
        return None
    return candidate


def trash_output_files(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    config: dict | None,
    targets: Any,
    keep: Any = (),
) -> dict[str, Any]:
    """출력물을 먼저 기록한 복구 묶음으로 이동하고 실제 이동 경로만 반환한다."""
    root = operations.output_root(config).resolve()
    trash_root = (root / paths.trash_dir_name).resolve()
    kept = set(keep or ())
    planned: list[dict[str, str]] = []
    seen: set[str] = set()
    for relative in targets or ():
        relative = str(relative or "").replace("\\", "/").lstrip("/")
        if (
            not relative
            or relative in seen
            or relative in kept
            or relative.startswith(paths.trash_dir_name + "/")
        ):
            continue
        source = (root / relative).resolve()
        if not path_is_inside(source, root) or not source.is_file():
            continue
        planned.append({"original": relative})
        seen.add(relative)
    if not planned:
        return {"deleted": 0, "batch_id": None, "paths": []}

    trash_root.mkdir(parents=True, exist_ok=True)
    for _attempt in range(8):
        batch_id = (
            operations.now().strftime("%Y%m%d-%H%M%S")
            + "-"
            + operations.uuid4().hex[:12]
        )
        batch_dir = trash_root / batch_id
        try:
            batch_dir.mkdir(parents=False, exist_ok=False)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(
            "고유한 휴지통 묶음 폴더를 만들지 못했습니다."
        )

    for item in planned:
        destination = (batch_dir / item["original"]).resolve()
        if not path_is_inside(destination, batch_dir):
            raise ValueError(
                "휴지통 밖을 가리키는 경로가 포함되어 있습니다."
            )
        item["trashed"] = destination.relative_to(root).as_posix()

    picks = operations.load_picks()
    labels: dict[str, dict[str, Any]] = {}
    for item in planned:
        relative = item["original"]
        record: dict[str, Any] = {}
        if relative in picks.get("picked", []):
            record["picked"] = True
        if relative in picks.get("fav", []):
            record["fav"] = True
        folders = [
            name
            for name, values in picks.get("folders", {}).items()
            if relative in values
        ]
        if folders:
            record["folders"] = folders
        for key in (
            "ranks",
            "ratings",
            "elo",
            "elo_matches",
            "tags",
        ):
            if relative in picks.get(key, {}):
                record[key] = picks[key][relative]
        if record:
            labels[relative] = record

    manifest_path = batch_dir / "manifest.json"
    manifest: dict[str, Any] = {
        "schema": paths.trash_schema,
        "batch_id": batch_id,
        "created_at": operations.now().isoformat(timespec="seconds"),
        "status": "moving",
        "items": planned,
        "labels": labels,
    }
    operations.atomic_write_json(manifest_path, manifest, indent=2)
    moved: list[dict[str, str]] = []
    for item in planned:
        source = (root / item["original"]).resolve()
        destination = (root / item["trashed"]).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        operations.move_file(str(source), str(destination))
        moved.append(item)
    manifest["status"] = "ready"
    manifest["moved"] = len(moved)
    operations.atomic_write_json(manifest_path, manifest, indent=2)
    return {
        "deleted": len(moved),
        "batch_id": batch_id,
        "paths": [item["original"] for item in moved],
    }


def _trash_restore_manifest(
    operations: OutputLifecycleOperations,
    batch: Path,
) -> tuple[Path, dict, list[dict]]:
    manifest_path = batch / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("복원할 휴지통 묶음을 찾을 수 없습니다.")
    manifest = operations.load_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
        raise ValueError("휴지통 장부 형식이 올바르지 않습니다.")
    return (
        manifest_path,
        manifest,
        [item for item in manifest["items"] if isinstance(item, dict)],
    )


def _unused_restore_target(
    root: Path,
    trash_root: Path,
    original: str,
) -> Path | None:
    target = (root / original).resolve()
    if not path_is_inside(target, root) or path_is_inside(target, trash_root):
        return None
    stem, suffix, serial = target.stem, target.suffix, 2
    while target.exists():
        target = target.with_name(f"{stem}_{serial}{suffix}")
        serial += 1
    return target


def _plan_trash_restore(
    operations: OutputLifecycleOperations,
    root: Path,
    trash_root: Path,
    batch: Path,
    manifest_path: Path,
    manifest: dict,
    items: list[dict],
) -> dict[str, str]:
    plan = manifest.get("restore_plan")
    plan = dict(plan) if isinstance(plan, dict) else {}
    changed = False
    for item in items:
        original = str(item.get("original") or "").replace("\\", "/").lstrip("/")
        source = (root / str(item.get("trashed") or "")).resolve()
        if not original or not path_is_inside(source, batch):
            continue
        relative = str(plan.get(original) or "").replace("\\", "/").lstrip("/")
        planned = (root / relative).resolve() if relative else None
        if planned is not None and (
            not path_is_inside(planned, root)
            or path_is_inside(planned, trash_root)
        ):
            planned = None
        if planned is None and source.is_file():
            planned = _unused_restore_target(root, trash_root, original)
            if planned is not None:
                plan[original] = planned.relative_to(root).as_posix()
                changed = True
    if changed or manifest.get("restore_plan") != plan:
        manifest["restore_plan"] = plan
        manifest["restore_status"] = "moving"
        operations.atomic_write_json(manifest_path, manifest, indent=2)
    return plan


def _move_trash_items(
    operations: OutputLifecycleOperations,
    root: Path,
    trash_root: Path,
    batch: Path,
    manifest_path: Path,
    manifest: dict,
    items: list[dict],
    plan: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    restored: list[str] = []
    restored_map: dict[str, str] = {}
    for item in items:
        original = str(item.get("original") or "").replace("\\", "/").lstrip("/")
        planned_relative = str(plan.get(original) or "").replace("\\", "/").lstrip("/")
        if not original or not planned_relative:
            continue
        source = (root / str(item.get("trashed") or "")).resolve()
        target = (root / planned_relative).resolve()
        if (
            not path_is_inside(source, batch)
            or not path_is_inside(target, root)
            or path_is_inside(target, trash_root)
        ):
            continue
        if source.is_file() and target.exists():
            target = _unused_restore_target(root, trash_root, original)
            if target is None:
                continue
            planned_relative = target.relative_to(root).as_posix()
            plan[original] = planned_relative
            manifest["restore_plan"] = plan
            operations.atomic_write_json(manifest_path, manifest, indent=2)
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            operations.move_file(str(source), str(target))
        elif not target.is_file():
            continue
        restored.append(planned_relative)
        restored_map[original] = planned_relative
    return restored, restored_map


def _restore_trash_labels(
    operations: OutputLifecycleOperations,
    labels: dict,
    restored_map: dict[str, str],
) -> None:
    if not restored_map or not isinstance(labels, dict):
        return
    keyed = ("ranks", "ratings", "elo", "elo_matches", "tags")
    with operations.picks_lock:
        picks = operations.load_picks()
        for original, restored_relative in restored_map.items():
            record = labels.get(original) or {}
            record = record if isinstance(record, dict) else {}
            picks["picked"][:] = [
                value for value in picks["picked"] if value != original
            ]
            picks["fav"][:] = [
                value for value in picks["fav"] if value != original
            ]
            for values in picks["folders"].values():
                values[:] = [value for value in values if value != original]
            for key in keyed:
                picks[key].pop(original, None)
            if record.get("picked") and restored_relative not in picks["picked"]:
                picks["picked"].append(restored_relative)
            if record.get("fav") and restored_relative not in picks["fav"]:
                picks["fav"].append(restored_relative)
            for name in record.get("folders") or []:
                values = picks["folders"].setdefault(str(name)[:40], [])
                if restored_relative not in values:
                    values.append(restored_relative)
            for key in keyed:
                if key in record:
                    picks[key][restored_relative] = record[key]
        operations.save_picks(picks)


def restore_trash_batch(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    config: dict | None,
    batch_id: Any,
) -> dict[str, Any]:
    """휴지통 묶음을 충돌 없는 원래 계열 경로로 복원하고 가상 이름표를 되붙인다."""
    root = operations.output_root(config).resolve()
    trash_root = (root / paths.trash_dir_name).resolve()
    batch = (trash_root / str(batch_id or "")).resolve()
    if not path_is_inside(batch, trash_root):
        raise ValueError("잘못된 휴지통 묶음입니다.")
    manifest_path, manifest, items = _trash_restore_manifest(operations, batch)
    plan = _plan_trash_restore(
        operations, root, trash_root, batch, manifest_path, manifest, items
    )
    restored, restored_map = _move_trash_items(
        operations, root, trash_root, batch, manifest_path, manifest, items, plan
    )
    _restore_trash_labels(
        operations, manifest.get("labels") or {}, restored_map
    )
    manifest["restored_at"] = operations.now().isoformat(
        timespec="seconds"
    )
    manifest["restored"] = restored
    manifest["restore_status"] = "complete"
    operations.atomic_write_json(manifest_path, manifest, indent=2)
    return {"restored": len(restored), "paths": restored}


def list_trash_batches(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    config: dict | None,
) -> dict[str, Any]:
    """재시작 뒤에도 남은 휴지통 묶음과 복원 가능한 파일 크기를 집계한다."""
    root = operations.output_root(config).resolve()
    trash_root = (root / paths.trash_dir_name).resolve()
    if not trash_root.is_dir():
        return {
            "ok": True,
            "batches": [],
            "total_files": 0,
            "total_bytes": 0,
        }
    rows: list[dict[str, Any]] = []
    for batch in sorted(trash_root.iterdir(), reverse=True):
        manifest_path = batch / "manifest.json"
        if not batch.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = operations.load_json(manifest_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest.get("items"), list)
        ):
            continue
        items = [
            item
            for item in manifest["items"]
            if isinstance(item, dict)
        ]
        available, size = 0, 0
        for item in items:
            path = (
                root / str(item.get("trashed") or "")
            ).resolve()
            if path_is_inside(path, batch) and path.is_file():
                available += 1
                try:
                    size += path.stat().st_size
                except OSError:
                    pass
        rows.append({
            "batch_id": str(
                manifest.get("batch_id") or batch.name
            ),
            "created_at": str(manifest.get("created_at") or ""),
            "available": available,
            "total": len(items),
            "bytes": size,
            "status": str(
                manifest.get("restore_status")
                or manifest.get("status")
                or ""
            ),
        })
    return {
        "ok": True,
        "batches": rows,
        "total_files": sum(row["available"] for row in rows),
        "total_bytes": sum(row["bytes"] for row in rows),
    }


def dir_image_count(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    directory: Path,
) -> int:
    """재귀 이미지 수를 짧게 캐시해 탐색기 왕복의 전체 트리 재탐색을 줄인다."""
    now = operations.clock()
    key = str(directory)
    hit = operations.directory_count_cache.get(key)
    if hit and now - hit[1] < paths.directory_count_ttl:
        return hit[0]
    count = sum(
        1
        for file in directory.rglob("*")
        if file.suffix.lower() in paths.image_extensions
    )
    operations.directory_count_cache[key] = (count, now)
    return count


def comparison_manifests_for_output_dir(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    config: dict | None,
    subdirectory: Any,
) -> list[dict[str, Any]]:
    """현재 출력 폴더를 직접 감싸는 첫 비교 manifest만 안전하게 복사한다."""
    del paths
    root = operations.output_root(config).resolve()
    current = (root / str(subdirectory or "")).resolve()
    if not path_is_inside(current, root):
        return []
    manifests: list[dict[str, Any]] = []
    while current != root:
        path = current / "manifest.json"
        if path.is_file():
            try:
                value = operations.load_json(path)
                if isinstance(value, dict):
                    value = copy.deepcopy(value)
                    value.setdefault(
                        "folder",
                        current.relative_to(root).as_posix(),
                    )
                    manifests.append(value)
            except Exception as error:
                operations.warning(
                    "비교 결과 계보를 읽지 못했습니다(%s): %s",
                    path.name,
                    error,
                )
            break
        current = current.parent
    return manifests


def list_output(
    paths: OutputLifecyclePaths,
    operations: OutputLifecycleOperations,
    subdirectory: str = "",
    config: dict | None = None,
    limit: int = 0,
    offset: int = 0,
    only_pick: bool = False,
    only_fav: bool = False,
) -> dict[str, Any]:
    """출력 폴더 한 단계와 필터 뒤 이미지 페이지·평가 계보를 함께 반환한다."""
    root = operations.output_root(config).resolve()
    base = (
        (root / subdirectory).resolve()
        if subdirectory
        else root
    )
    trash_root = (root / paths.trash_dir_name).resolve()
    try:
        inside = base.is_relative_to(root)
    except AttributeError:
        inside = str(base).startswith(str(root))
    if (
        not (inside and base.is_dir())
        or base == trash_root
        or path_is_inside(base, trash_root)
    ):
        return {"ok": False, "error": "그런 폴더가 없습니다."}

    directories: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for path in sorted(base.iterdir()):
        if path.name == paths.trash_dir_name:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        if path.is_dir():
            directories.append({
                "name": path.name,
                "path": relative,
                "count": dir_image_count(paths, operations, path),
            })
        elif path.suffix.lower() in paths.image_extensions:
            stat = path.stat()
            files.append({
                "name": path.name,
                "path": relative,
                "bytes": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
    files.sort(key=lambda item: -item["mtime"])
    picks = operations.load_picks()
    if only_pick:
        chosen = set(picks["picked"])
        files = [
            item for item in files if item["path"] in chosen
        ]
    if only_fav:
        chosen = set(picks["fav"])
        files = [
            item for item in files if item["path"] in chosen
        ]
    total = len(files)
    offset = max(0, int(offset or 0))
    limit = max(0, min(500, int(limit or 0)))
    if limit:
        files = files[offset:offset + limit]
    else:
        offset = 0
    evaluation_projection = operations.project_evaluations(
        picks,
        comparison_manifests=comparison_manifests_for_output_dir(
            paths,
            operations,
            config,
            subdirectory,
        ),
        result_records=[
            {"path": item["path"]} for item in files
        ],
    )
    return {
        "ok": True,
        "dir": subdirectory,
        "dirs": directories,
        "files": files,
        "total": total,
        "offset": offset,
        "has_more": bool(
            limit and offset + len(files) < total
        ),
        "picked": picks["picked"],
        "fav": picks["fav"],
        "folders": picks["folders"],
        "ranks": picks.get("ranks", {}),
        "ratings": picks.get("ratings", {}),
        "elo": picks.get("elo", {}),
        "elo_matches": picks.get("elo_matches", {}),
        "tags": picks.get("tags", {}),
        "memos": picks.get("memos", {}),
        "review_states": picks.get("review_states", {}),
        "evaluations": evaluation_projection["evaluations"],
        "evaluation_issues": evaluation_projection["issues"],
        "up": (
            str(Path(subdirectory).parent).replace("\\", "/")
            if subdirectory and subdirectory != "."
            else ""
        ),
    }


__all__ = [
    "OutputLifecycleOperations",
    "OutputLifecyclePaths",
    "comparison_manifests_for_output_dir",
    "dir_image_count",
    "list_output",
    "list_trash_batches",
    "output_file_for_preview",
    "path_is_inside",
    "restore_trash_batch",
    "trash_output_files",
]
