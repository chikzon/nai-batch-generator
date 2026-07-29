# -*- coding: utf-8 -*-
"""Director와 Vibe·Reference 요청을 기존 서버 상태 경계에 연결한다."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from PIL import Image

from src.nai_studio.services.character_storage import safe_name
from src.nai_studio.services.result_store import atomic_save_image


@dataclass(frozen=True)
class ImageToolOperations:
    """기존 저장·NAI·계보 함수만 주입해 핸들러를 독립시킨다."""

    vibe_dir: Path
    shared_data_transaction: Callable[[Path], Any]
    vibe_paths: Callable[[str], tuple[Path, Path]]
    save_config: Callable[[dict], Any]
    prepare_vibes: Callable[[dict, str], Any]
    recoverable_remove: Callable[[Path], Any]
    director_tools: tuple | list
    call_upscale: Callable[[str, bytes, int], bytes]
    call_director: Callable[..., bytes]
    inherited_blueprint: Callable[..., dict]
    output_sub: Callable[[dict, str], Path]
    record_job_result: Callable[..., Any]
    output_root: Callable[[dict], Path]
    info: Callable[..., Any]
    warning: Callable[..., Any]


def handle_ref_add(
    server: Any,
    data: dict,
    operations: ImageToolOperations,
) -> dict:
    """업로드 이미지를 Vibe 또는 Character Reference로 등록한다."""
    body = data.get("body") or b""
    kind = data.get("kind")
    filename = data.get("filename", "")
    try:
        if not body:
            return {"ok": False, "error": "이미지가 비어 있습니다."}
        name = Path(unquote(filename or "")).stem[:40] or "레퍼런스"
        operations.vibe_dir.mkdir(parents=True, exist_ok=True)
        reference_id = (
            f"{kind}_{int(time.time() * 1000) % 10**10}-"
            f"{os.urandom(3).hex()}"
        )
        image = Image.open(io.BytesIO(body))
        if kind == "vibe":
            return _add_vibe(
                server,
                operations,
                image,
                reference_id,
                name,
            )
        return _add_character_reference(
            server,
            operations,
            image,
            reference_id,
            name,
        )
    except Exception as error:
        operations.warning(
            "레퍼런스 추가 실패: %s",
            traceback.format_exc(),
        )
        return {"ok": False, "error": str(error)}


def _add_vibe(
    server: Any,
    operations: ImageToolOperations,
    image: Image.Image,
    reference_id: str,
    name: str,
) -> dict:
    with operations.shared_data_transaction(
        operations.vibe_dir.parent.parent
    ):
        with server.config_lock:
            server.use_latest_config()
            path, _ = operations.vibe_paths(reference_id)
            converted = image.convert("RGB")
            atomic_save_image(
                path,
                lambda temporary: converted.save(temporary, "PNG"),
            )
            item = {
                "id": reference_id,
                "name": name,
                "enabled": True,
                "strength": 0.6,
                "info_extracted": 0.7,
                "encoded_ie": None,
            }
            server.cfg.setdefault("vibes", []).append(item)
            operations.save_config(server.cfg)
            server.config_revision += 1
    token = (server.cfg.get("token") or "").strip()
    if token:
        try:
            operations.prepare_vibes(server.cfg, token)
            item["encoded"] = True
        except Exception as error:
            return {
                "ok": True,
                "item": item,
                "vibes": server.cfg["vibes"],
                "warn": f"등록은 됐지만 인코딩 실패: {error}",
                "revision": server.config_revision,
            }
    return {
        "ok": True,
        "item": item,
        "vibes": server.cfg["vibes"],
        "revision": server.config_revision,
    }


def _add_character_reference(
    server: Any,
    operations: ImageToolOperations,
    image: Image.Image,
    reference_id: str,
    name: str,
) -> dict:
    with operations.shared_data_transaction(
        operations.vibe_dir.parent.parent
    ):
        with server.config_lock:
            server.use_latest_config()
            path = operations.vibe_dir / f"{reference_id}.ref.png"
            converted = image.convert("RGB")
            atomic_save_image(
                path,
                lambda temporary: converted.save(temporary, "PNG"),
            )
            item = {
                "id": reference_id,
                "name": name,
                "enabled": True,
                "ref_type": "character&style",
                "strength": 0.6,
                "fidelity": 0.6,
            }
            server.cfg.setdefault("char_refs", []).append(item)
            operations.save_config(server.cfg)
            server.config_revision += 1
    return {
        "ok": True,
        "item": item,
        "char_refs": server.cfg["char_refs"],
        "revision": server.config_revision,
    }


def handle_ref_save(
    server: Any,
    data: dict,
    operations: ImageToolOperations,
) -> dict:
    """강도·정보 추출·활성 상태와 삭제를 충돌 검사 후 저장한다."""
    with operations.shared_data_transaction(
        operations.vibe_dir.parent.parent
    ):
        return _save_references(
            server,
            data.get("body") or b"",
            operations,
        )


def _save_references(
    server: Any,
    body: bytes,
    operations: ImageToolOperations,
) -> dict:
    try:
        changes = json.loads(body or b"{}")
        revision = changes.pop("_revision", None)
        base_values = changes.pop("_base", {})
        if not isinstance(base_values, dict):
            base_values = {}
        with server.config_lock:
            if _stale_revision(server, revision):
                return {
                    "ok": False,
                    "conflict": True,
                    "revision": server.config_revision,
                    "error": (
                        "다른 화면에서 참조 설정이 먼저 변경됐습니다. "
                        "새로고침 후 다시 시도하세요."
                    ),
                }
            merged = server.latest_config_from_disk()
            conflicts = [
                key
                for key in ("vibes", "char_refs")
                if key in changes
                and key in base_values
                and merged.get(key) != base_values.get(key)
                and changes.get(key) != merged.get(key)
            ]
            if conflicts:
                server.cfg.clear()
                server.cfg.update(merged)
                server.config_revision += 1
                return {
                    "ok": False,
                    "conflict": True,
                    "conflict_keys": conflicts,
                    "revision": server.config_revision,
                    "error": (
                        "다른 실행본이 같은 참조 목록을 먼저 변경했습니다. "
                        "새로고침 후 다시 시도하세요."
                    ),
                }
            server.cfg.clear()
            server.cfg.update(merged)
            _merge_reference_changes(
                server.cfg,
                changes,
                operations,
            )
            operations.save_config(server.cfg)
            server.config_revision += 1
            return {
                "ok": True,
                "vibes": server.cfg.get("vibes", []),
                "char_refs": server.cfg.get("char_refs", []),
                "revision": server.config_revision,
            }
    except Exception as error:
        return {"ok": False, "error": str(error)}


def _stale_revision(server: Any, revision: Any) -> bool:
    if revision is None:
        return False
    try:
        return int(revision) != server.config_revision
    except (TypeError, ValueError):
        return True


def _merge_reference_changes(
    config: dict,
    changes: dict,
    operations: ImageToolOperations,
) -> None:
    for key in ("vibes", "char_refs"):
        if key not in changes:
            continue
        old = {
            item.get("id"): item
            for item in config.get(key, [])
        }
        new = changes[key]
        for gone in set(old) - {
            item.get("id") for item in new
        }:
            for path in (
                operations.vibe_dir / f"{gone}.png",
                operations.vibe_dir / f"{gone}.vibe",
                operations.vibe_dir / f"{gone}.ref.png",
            ):
                if path.exists():
                    operations.recoverable_remove(path)
        for item in new:
            previous = old.get(item.get("id"))
            if (
                previous
                and abs(
                    float(item.get("info_extracted", 0.7))
                    - float(previous.get("info_extracted", 0.7))
                )
                > 1e-9
            ):
                item["encoded_ie"] = None
        config[key] = new


def handle_director(
    server: Any,
    data: dict,
    operations: ImageToolOperations,
) -> dict:
    """Director 또는 Upscale 호출 결과를 저장하고 실행 상태에 연결한다."""
    body = data.get("body") or b""
    tool = data.get("tool")
    token_claim = None
    try:
        validation_error = _director_validation(
            server,
            operations,
            body,
            tool,
        )
        if validation_error:
            return validation_error
        token = (server.cfg.get("token") or "").strip()
        token_claim = server.live.try_claim(
            f"디렉터 · {tool}",
            "director",
            blueprint=operations.inherited_blueprint(
                server.cfg,
                source={"kind": "director", "tool": tool},
            ),
            payload_identity={
                "kind": "director",
                "tool": tool,
                "input_sha256": hashlib.sha256(body).hexdigest(),
            },
        )
        if token_claim is None:
            return {
                "ok": False,
                "error": "이미 다른 NAI 작업이 실행 중입니다.",
            }
        server.live.update(
            status_text=f"디렉터 · {tool} 처리 중...",
            char_name=f"디렉터 · {tool}",
            index=1,
            total=1,
        )
        output = _call_image_tool(
            operations,
            token,
            body,
            tool,
            data,
        )
        return _save_director_result(
            server,
            operations,
            output,
            tool,
            data.get("filename", ""),
        )
    except Exception as error:
        operations.warning(
            "디렉터 툴 실패: %s",
            traceback.format_exc(),
        )
        if token_claim is not None:
            server.live.update(
                status_text=f"디렉터 툴 실패: {error}",
                failed=1,
                last_error=str(error),
                can_retry=True,
                phase="failed",
            )
        return {"ok": False, "error": str(error)}
    finally:
        if token_claim is not None:
            server.live.release(token_claim)


def _director_validation(
    server: Any,
    operations: ImageToolOperations,
    body: bytes,
    tool: Any,
) -> dict | None:
    if not body:
        return {"ok": False, "error": "이미지가 비어 있습니다."}
    if not (server.cfg.get("token") or "").strip():
        return {
            "ok": False,
            "error": "시스템에서 NAI 토큰을 먼저 넣어주세요.",
        }
    names = {
        name for name, _, _ in operations.director_tools
    } | {"upscale"}
    if tool not in names:
        return {
            "ok": False,
            "error": f"알 수 없는 도구: {tool}",
        }
    return None


def _call_image_tool(
    operations: ImageToolOperations,
    token: str,
    body: bytes,
    tool: str,
    data: dict,
) -> bytes:
    if tool == "upscale":
        return operations.call_upscale(
            token,
            body,
            int(data.get("scale", "4") or 4),
        )
    needs_prompt = next(
        needs
        for name, _, needs in operations.director_tools
        if name == tool
    )
    prompt = data.get("prompt", "")
    return operations.call_director(
        token,
        body,
        tool,
        prompt=(prompt or "") if needs_prompt else None,
        defry=data.get("defry", "0"),
    )


def _save_director_result(
    server: Any,
    operations: ImageToolOperations,
    output: bytes,
    tool: str,
    filename: str,
) -> dict:
    image = Image.open(io.BytesIO(output))
    keep_alpha = tool == "bg-removal"
    directory = operations.output_sub(server.cfg, "디렉터")
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_name(Path(filename or "결과").stem)[:40] or "결과"
    extension = "png" if keep_alpha else "webp"
    path = _available_director_path(
        directory / f"{stem}_{tool}.{extension}"
    )
    if keep_alpha:
        converted = image.convert("RGBA")
        atomic_save_image(
            path,
            lambda temporary: converted.save(temporary, "PNG"),
        )
    else:
        converted = image.convert("RGB")
        atomic_save_image(
            path,
            lambda temporary: converted.save(
                temporary,
                "WEBP",
                quality=95,
            ),
        )
    operations.record_job_result(
        server.live.job_id,
        path,
        artifact=path.resolve().relative_to(
            operations.output_root(server.cfg).resolve()
        ).as_posix(),
    )
    server.live.set_image(image.convert("RGB"))
    server.live.update(
        filename=path.name,
        char_name=f"디렉터 · {tool}",
        status_text="디렉터 툴 완료",
        completed=1,
        phase="completed",
    )
    operations.info(
        "디렉터 %s → %s (%s×%s)",
        tool,
        path.name,
        image.width,
        image.height,
    )
    return {
        "ok": True,
        "tool": tool,
        "file": path.name,
        "path": str(path),
        "width": image.width,
        "height": image.height,
    }


def _available_director_path(path: Path) -> Path:
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(
            f"{path.stem}_{number}{path.suffix}"
        )
        if not candidate.exists():
            return candidate
        number += 1


__all__ = [
    "ImageToolOperations",
    "handle_director",
    "handle_ref_add",
    "handle_ref_save",
]
