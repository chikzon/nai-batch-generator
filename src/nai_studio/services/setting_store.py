# -*- coding: utf-8 -*-
"""세팅 파일의 저장·복제·카탈로그 조립을 담당한다."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class SettingStorePaths:
    """사용자별 세팅과 구버전 변환 원본의 실제 경로."""

    settings_dir: Path
    schema_dir: Path
    preset_dir: Path


@dataclass(frozen=True)
class SettingStoreOperations:
    """저장소가 기존 원자 저장·잠금·카탈로그 규칙을 재사용하게 한다."""

    transaction: Callable[[], Any]
    load_json: Callable[[Path], Any]
    atomic_write_json: Callable[..., Any]
    recoverable_remove: Callable[..., Path]
    safe_name: Callable[[Any], str]
    derive_catalog: Callable[[dict], list[dict]]
    axis_specs: Callable[[dict], dict]
    ensure_schema_split: Callable[[], Any]
    warning: Callable[..., Any]
    info: Callable[..., Any]


BUILDER_MODES = ("단독", "남녀", "백합")
SCENESET_KEYS = ("setting_state",)
_META_KEYS = (
    "방식",
    "단계명",
    "계열이름",
    "옵션규격",
    "옵션",
    "상대역",
)
_ROLE_KEYS = ("외형", "착의", "네거티브", "의상")


def ensure_migration(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
) -> None:
    """구버전 씬규격을 현재 세팅 파일로 한 번만 옮긴다."""
    with operations.transaction():
        if paths.settings_dir.exists():
            return
        operations.ensure_schema_split()
        if not paths.schema_dir.exists():
            return
        paths.settings_dir.mkdir()
        mapping = {
            "체위": ("남녀 체위", "남녀"),
            "표정": ("표정", "단독"),
            "백합": ("백합", "백합"),
        }
        for kind, (name, mode) in mapping.items():
            source = paths.schema_dir / kind / "기본.json"
            if not source.exists():
                continue
            try:
                data = operations.load_json(source)
            except Exception as error:
                operations.warning("%s 변환 실패: %s", kind, error)
                continue
            output = {
                "이름": name,
                "방식": mode,
                "씬": data.get("씬", {}),
                "옵션": data.get("옵션", {}),
                "상대역": {
                    "외형": "",
                    "착의": "",
                    "네거티브": "",
                    "의상": "",
                },
            }
            operations.atomic_write_json(
                paths.settings_dir / f"{name}.json",
                output,
                keep_backup=False,
            )
        operations.info("세팅/ 폴더 생성 완료 (씬규격에서 변환)")


def list_settings(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
) -> list[dict]:
    """파일을 넣고 빼는 즉시 반영되는 세팅 목록."""
    ensure_migration(paths, operations)
    result = []
    if not paths.settings_dir.exists():
        return result
    for path in sorted(paths.settings_dir.glob("*.json")):
        try:
            data = operations.load_json(path)
            if isinstance(data, dict) and data.get("씬"):
                result.append({
                    "file": path.name,
                    "name": data.get("이름") or path.stem,
                    "mode": data.get("방식", "단독"),
                    "data": data,
                })
        except Exception as error:
            operations.warning("세팅 파일 손상(%s): %s", path.name, error)
    return result


def setting_path(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
) -> Path | None:
    """파일명과 내부 이름이 다를 수 있는 기존 세팅을 내부 이름으로 찾는다."""
    candidates = (
        paths.settings_dir.glob("*.json")
        if paths.settings_dir.exists()
        else ()
    )
    for path in candidates:
        try:
            data = operations.load_json(path)
            if (data.get("이름") or path.stem) == name:
                return path
        except Exception:
            continue
    return None


def used_scene_nums(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    skip: str | None = None,
) -> dict[int, str]:
    """모든 세팅이 함께 쓰는 전역 씬 번호와 소유 세팅."""
    used = {}
    for setting in list_settings(paths, operations):
        if skip and setting["name"] == skip:
            continue
        for key in setting["data"].get("씬", {}):
            if str(key).isdigit():
                used[int(key)] = setting["name"]
    return used


def free_scene_block(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    count: int,
    skip: str | None = None,
    step: int = 100,
) -> int:
    """눈에 띄는 100 단위 구간에서 연속된 빈 씬 번호를 찾는다."""
    used = set(used_scene_nums(paths, operations, skip))
    start = step
    while True:
        if not any(
            start + index in used
            for index in range(max(1, count))
        ):
            return start
        start += step


def scene_num_clashes(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
) -> dict[int, list[str]]:
    """둘 이상의 세팅이 사용해 덮어쓰기 위험이 있는 씬 번호."""
    seen = {}
    clashes = {}
    for setting in list_settings(paths, operations):
        for key in setting["data"].get("씬", {}):
            if not str(key).isdigit():
                continue
            number = int(key)
            if number in seen:
                clashes.setdefault(number, [seen[number]]).append(
                    setting["name"]
                )
            else:
                seen[number] = setting["name"]
    return clashes


def content_revision(data: Any) -> str:
    """되돌리기 전에 사용자 수정 여부를 비교하는 안정 해시."""
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def duplicate_group(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    group_id: int,
) -> dict:
    """세트의 모든 단계를 같은 파일 안의 새 번호로 복제한다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅 파일을 찾을 수 없습니다."}
        data = operations.load_json(path)
        scenes = data.get("씬", {})
        group = next(
            (
                item
                for item in operations.derive_catalog(scenes)
                if item["id"] == int(group_id)
            ),
            None,
        )
        if not group:
            return {"ok": False, "error": "그 세트를 찾을 수 없습니다."}
        used = {
            int(key)
            for key in scenes
            if str(key).isdigit()
        }
        span = len(group["ids"])
        start = max(used) + 1
        while any(start + index in used for index in range(span)):
            start += 1
        for index, source_id in enumerate(group["ids"]):
            scene = dict(scenes[str(source_id)])
            source_name = scenes[str(source_id)].get("name", "")
            head, _, tail = source_name.rpartition(" ")
            scene["name"] = (
                f"{head} 사본 {tail}"
                if head
                else f"{source_name} 사본"
            )
            scenes[str(start + index)] = scene
        data["씬"] = scenes
        operations.atomic_write_json(path, data, indent=1)
        return {"ok": True, "new_id": start, "count": span}


def duplicate_scene(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    scene_id: Any,
    expect_revision: str = "",
) -> dict:
    """장면의 알려진 필드와 미래 필드를 모두 깊은 복사한다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅 파일을 찾을 수 없습니다."}
        pack = operations.load_json(path)
        revision = content_revision(pack)
        if expect_revision and str(expect_revision) != revision:
            return {
                "ok": False,
                "conflict": True,
                "error": (
                    "다른 저장이 먼저 반영되어 장면을 복제하지 않았습니다. "
                    "다시 열어 확인해주세요."
                ),
            }
        scenes = pack.get("씬") or {}
        scene_id = str(scene_id)
        source = scenes.get(scene_id)
        if not isinstance(source, dict):
            return {
                "ok": False,
                "error": f"{scene_id}번 장면을 찾을 수 없습니다.",
            }
        used = set(used_scene_nums(paths, operations))
        try:
            candidate = int(scene_id) + 1
        except ValueError:
            candidate = max(used, default=99) + 1
        while candidate in used:
            candidate += 1
        clone = copy.deepcopy(source)
        root = str(clone.get("name") or "장면").strip() + " 사본"
        names = {
            str(scene.get("name") or "").casefold()
            for scene in scenes.values()
            if isinstance(scene, dict)
        }
        clone_name = root
        serial = 2
        while clone_name.casefold() in names:
            clone_name = f"{root} {serial}"
            serial += 1
        clone["name"] = clone_name
        new_id = str(candidate)
        scenes[new_id] = clone
        pack["씬"] = scenes
        operations.atomic_write_json(path, pack, indent=1)
        return {
            "ok": True,
            "setting": name,
            "new_id": new_id,
            "name": clone_name,
            "scene_sha256": content_revision(clone),
            "revision": content_revision(pack),
        }


def undo_duplicate_scene(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    scene_id: Any,
    scene_sha256: str,
    expect_revision: str = "",
) -> dict:
    """복제 뒤 바뀌지 않은 장면만 안전하게 되돌린다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅 파일을 찾을 수 없습니다."}
        pack = operations.load_json(path)
        revision = content_revision(pack)
        if expect_revision and str(expect_revision) != revision:
            return {
                "ok": False,
                "conflict": True,
                "error": (
                    "복제 뒤 다른 저장이 반영되어 "
                    "자동으로 취소하지 않았습니다."
                ),
            }
        scene_id = str(scene_id)
        scene = (pack.get("씬") or {}).get(scene_id)
        if not isinstance(scene, dict):
            return {
                "ok": False,
                "error": "취소할 복제 장면을 찾을 수 없습니다.",
            }
        if (
            not scene_sha256
            or content_revision(scene) != str(scene_sha256)
        ):
            return {
                "ok": False,
                "conflict": True,
                "error": (
                    "복제한 장면이 이미 수정되어 "
                    "자동으로 지우지 않았습니다."
                ),
            }
        pack["씬"].pop(scene_id, None)
        operations.atomic_write_json(path, pack, indent=1)
        return {
            "ok": True,
            "setting": name,
            "removed_id": scene_id,
            "revision": content_revision(pack),
        }


def create_setting(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    mode: str = "단독",
    stages: list | None = None,
) -> dict:
    """사용자 단계명을 가진 빈 세팅 파일을 만든다."""
    with operations.transaction():
        safe = operations.safe_name(name) or "새 세팅"
        if mode not in BUILDER_MODES:
            mode = "단독"
        paths.settings_dir.mkdir(exist_ok=True)
        target = paths.settings_dir / f"{safe}.json"
        serial = 2
        while target.exists():
            target = paths.settings_dir / f"{safe} ({serial}).json"
            serial += 1
        data = {
            "이름": target.stem,
            "방식": mode,
            "단계명": [
                item
                for item in (stages or ["시작", "중간", "끝"])
                if str(item).strip()
            ],
            "계열이름": {},
            "옵션규격": {},
            "옵션": {},
            "씬": {},
            "상대역": {},
        }
        operations.atomic_write_json(
            target,
            data,
            indent=1,
            keep_backup=False,
        )
        return {
            "ok": True,
            "name": target.stem,
            "file": target.name,
        }


def add_set(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    label: str,
    category: str = "",
    width: int = 832,
    height: int = 1216,
    stages: list | None = None,
) -> dict:
    """단계명마다 하나씩 씬을 만들어 한 세트를 추가한다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        data = operations.load_json(path)
        stages = [
            item
            for item in (
                stages
                or data.get("단계명")
                or ["시작", "중간", "끝"]
            )
            if str(item).strip()
        ]
        label = (label or "새 세트").strip()
        scenes = data.setdefault("씬", {})
        own_numbers = {
            int(key)
            for key in scenes
            if str(key).isdigit()
        }
        other_numbers = set(
            used_scene_nums(paths, operations, skip=name)
        )
        start = (
            max(own_numbers) + 1
            if own_numbers
            else free_scene_block(
                paths,
                operations,
                len(stages),
                skip=name,
            )
        )
        while any(
            start + index in other_numbers
            or start + index in own_numbers
            for index in range(len(stages))
        ):
            start += 1
        for index, stage in enumerate(stages):
            scenes[str(start + index)] = {
                "name": f"{label} {stage}".strip(),
                "female_prompt": "",
                "male_prompt": "",
                "width": int(width),
                "height": int(height),
                "category": category or "",
            }
        operations.atomic_write_json(path, data, indent=1)
        return {"ok": True, "start": start, "count": len(stages)}


def save_meta(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    patch: dict,
) -> dict:
    """세팅 머리 정보와 안전한 파일명 변경을 한 트랜잭션으로 저장한다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        data = operations.load_json(path)
        for key in _META_KEYS:
            if key in patch:
                data[key] = patch[key]
        if data.get("방식") not in BUILDER_MODES:
            data["방식"] = "단독"
        new_name = (patch.get("이름") or "").strip()
        if new_name and new_name != data.get("이름"):
            safe = operations.safe_name(new_name) or data["이름"]
            target = paths.settings_dir / f"{safe}.json"
            if target.exists() and target != path:
                return {
                    "ok": False,
                    "error": f"'{safe}' 이름이 이미 있습니다.",
                }
            data["이름"] = safe
            operations.atomic_write_json(
                target,
                data,
                indent=1,
                keep_backup=False,
            )
            operations.recoverable_remove(path, label="이름변경")
            return {"ok": True, "name": safe, "renamed": True}
        data["이름"] = data.get("이름") or path.stem
        operations.atomic_write_json(path, data, indent=1)
        return {"ok": True, "name": data["이름"]}


def renumber(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
    start: int | None = None,
) -> dict:
    """세트·단계 순서를 보존하면서 씬 번호 충돌을 없앤다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        data = operations.load_json(path)
        scenes = data.get("씬", {})
        order = []
        for group in operations.derive_catalog(scenes):
            order.extend(group["ids"])
        for key in sorted(
            int(item)
            for item in scenes
            if str(item).isdigit()
        ):
            if key not in order:
                order.append(key)
        if start is None:
            start = free_scene_block(
                paths,
                operations,
                len(order),
                skip=name,
            )
        data["씬"] = {
            str(start + index): scenes[str(old)]
            for index, old in enumerate(order)
        }
        operations.atomic_write_json(path, data, indent=1)
        return {
            "ok": True,
            "start": start,
            "count": len(data["씬"]),
            "clashes": scene_num_clashes(paths, operations),
        }


def delete_setting(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    name: str,
) -> dict:
    """세팅 파일을 복구 가능한 백업 이름으로 옮긴다."""
    with operations.transaction():
        path = setting_path(paths, operations, name)
        if not path:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        backup = operations.recoverable_remove(path)
        return {"ok": True, "backup": backup.name}


def export_settings(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    names: list[str] | None = None,
) -> bytes:
    """선택한 세팅을 기존 ZIP 내부 경로 그대로 내보낸다."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for setting in list_settings(paths, operations):
            if names and setting["name"] not in names:
                continue
            path = paths.settings_dir / setting["file"]
            archive.write(path, path.name)
    return buffer.getvalue()


def import_settings(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    data: bytes,
    filename: str = "",
) -> dict:
    """ZIP 또는 JSON을 기존 자료를 덮지 않는 새 이름으로 가져온다."""
    with operations.transaction():
        paths.settings_dir.mkdir(exist_ok=True)
        added = []
        skipped = []

        def put(stem: str, raw: bytes) -> None:
            try:
                item = json.loads(raw.decode("utf-8"))
            except Exception:
                skipped.append(f"{stem}: JSON 이 아닙니다")
                return
            if not (isinstance(item, dict) and item.get("씬")):
                skipped.append(
                    f"{stem}: 세팅 파일이 아닙니다 ('씬' 이 없음)"
                )
                return
            base = operations.safe_name(
                item.get("이름") or stem
            ) or "세팅"
            target = paths.settings_dir / f"{base}.json"
            serial = 2
            while target.exists():
                target = paths.settings_dir / f"{base} ({serial}).json"
                serial += 1
            if target.stem != base:
                item["이름"] = target.stem
            operations.atomic_write_json(
                target,
                item,
                indent=1,
                keep_backup=False,
            )
            added.append(target.stem)

        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    if (
                        name.lower().endswith(".json")
                        and not name.endswith("/")
                    ):
                        put(Path(name).stem, archive.read(name))
        else:
            put(Path(filename).stem or "세팅", data)
        return {
            "ok": bool(added),
            "added": added,
            "skipped": skipped,
        }


def list_presets(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
) -> list[dict]:
    """세팅 상태 프리셋을 파일 순서대로 읽는다."""
    presets = []
    if not paths.preset_dir.exists():
        return presets
    for path in sorted(paths.preset_dir.glob("*.json")):
        try:
            data = operations.load_json(path)
            if isinstance(data, dict):
                presets.append({"name": path.stem, "data": data})
        except Exception:
            continue
    return presets


def save_preset(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    body: bytes | str,
    config: Mapping[str, Any],
) -> dict:
    """현재 세팅 선택 상태만 이름 있는 프리셋으로 저장한다."""
    try:
        data = json.loads(body)
        name = (data.get("name") or "").strip()
        if not name:
            return {
                "ok": False,
                "error": "프리셋 이름을 입력해주세요.",
            }
        paths.preset_dir.mkdir(exist_ok=True)
        preset = {key: config.get(key) for key in SCENESET_KEYS}
        operations.atomic_write_json(
            paths.preset_dir / f"{operations.safe_name(name)}.json",
            preset,
        )
        return {
            "ok": True,
            "scene_presets": list_presets(paths, operations),
        }
    except Exception as error:
        return {"ok": False, "error": str(error)}


def save_role(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    body: bytes | str,
) -> dict:
    """세팅 상대역의 기존 네 필드만 원문 그대로 갱신한다."""
    try:
        data = json.loads(body)
        path = setting_path(
            paths,
            operations,
            data.get("setting", ""),
        )
        if not path:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        pack = operations.load_json(path)
        role = pack.setdefault("상대역", {})
        incoming = data.get("role") or {}
        for key in _ROLE_KEYS:
            if key in incoming:
                role[key] = incoming[key]
        operations.atomic_write_json(path, pack)
        return {"ok": True}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def update_option(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    body: bytes | str,
    snapshot: Callable[[], dict],
) -> dict:
    """세팅 옵션 한 항목을 직렬화해 수정하고 최신 화면 상태를 돌려준다."""
    with operations.transaction():
        try:
            data = json.loads(body)
            option = (data.get("option") or "").strip()
            name = (data.get("name") or "").strip()
            operation = data.get("op")
            path = setting_path(
                paths,
                operations,
                data.get("setting", ""),
            )
            if (
                not path
                or not option
                or not name
                or operation not in ("set", "del")
            ):
                return {"ok": False, "error": "잘못된 요청입니다."}
            pack = operations.load_json(path)
            options = pack.setdefault("옵션", {}).setdefault(
                option,
                {},
            )
            if operation == "del":
                options.pop(name, None)
            else:
                options[name] = data.get("value")
            operations.atomic_write_json(path, pack)
            return {"ok": True, "snapshot": snapshot()}
        except Exception as error:
            return {"ok": False, "error": str(error)}


def setting_catalog(
    paths: SettingStorePaths,
    operations: SettingStoreOperations,
    category_meta: Mapping[str, Mapping[str, Any]],
) -> list[dict]:
    """세팅 파일을 UI 스냅샷의 기존 카탈로그 스키마로 조립한다."""
    output = []
    for setting in list_settings(paths, operations):
        scenes = setting["data"].get("씬", {})
        groups = operations.derive_catalog(scenes)
        category_counts = {}
        for group in groups:
            category = group["cat"]
            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )
        labels = setting["data"].get("계열이름") or {}
        metadata = {
            category: {
                "name": (
                    labels.get(category)
                    or category_meta.get(category, {}).get("name")
                    or (f"{category} 계열" if category else "전체")
                ),
                "sub": f"{count}종",
            }
            for category, count in category_counts.items()
        }
        output.append({
            "file": setting["file"],
            "name": setting["name"],
            "mode": setting["mode"],
            "groups": groups,
            "category_meta": metadata,
            "options": setting["data"].get("옵션", {}),
            "role": setting["data"].get("상대역", {}),
            "stages": setting["data"].get("단계명") or [],
            "axis_specs": {
                key: {"적용": target, "방식": shape}
                for key, (target, shape) in operations.axis_specs(
                    setting["data"]
                ).items()
            },
            "cat_names": setting["data"].get("계열이름") or {},
            "nums": sorted(
                int(key)
                for key in setting["data"].get("씬", {})
                if str(key).isdigit()
            ),
        })
    return output


__all__ = [
    "BUILDER_MODES",
    "SCENESET_KEYS",
    "SettingStoreOperations",
    "SettingStorePaths",
    "add_set",
    "content_revision",
    "create_setting",
    "delete_setting",
    "duplicate_group",
    "duplicate_scene",
    "ensure_migration",
    "export_settings",
    "free_scene_block",
    "import_settings",
    "list_presets",
    "list_settings",
    "renumber",
    "save_meta",
    "save_preset",
    "save_role",
    "scene_num_clashes",
    "setting_catalog",
    "setting_path",
    "undo_duplicate_scene",
    "update_option",
    "used_scene_nums",
]
