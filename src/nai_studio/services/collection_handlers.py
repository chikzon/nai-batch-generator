# -*- coding: utf-8 -*-
"""단건 메타데이터 복원과 캐릭터 변형 결과 승격 요청을 조정한다."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from PIL import Image


@dataclass(frozen=True)
class CollectionHandlerOperations:
    """기존 metadata·restoration·variation 서비스 경계를 주입한다."""

    output_root: Callable[[dict], Path]
    character_asset_from_legacy_record: Callable[..., Any]
    accept_variation: Callable[..., Any]
    approved_variation_candidates: Callable[..., Any]
    apply_variation_candidates: Callable[..., dict]
    local_import_image: Callable[..., tuple]
    sync_chars_to_files: Callable[[dict], Any]
    save_config: Callable[[dict], Any]
    extract_nai_metadata: Callable[[bytes, str], dict]
    parse_artist_combo: Callable[[str], tuple]
    model_id_from_metadata: Callable[[Any, str], str]
    split_uc_preset: Callable[[str, str], tuple]
    restore_quality_prompt: Callable[[str, str, dict], tuple]
    image_cache: Path
    atomic_write_bytes: Callable[..., Any]
    evidence_from_image_record: Callable[[dict], dict]
    style_asset_from_record: Callable[..., dict]
    add_style: Callable[..., Any]
    image_inspect_queue: Callable[..., dict]
    summarize_restore_queue: Callable[[dict], dict]
    warning: Callable[..., Any]


def handle_character_variation_save(
    server: Any,
    data: dict,
    operations: CollectionHandlerOperations,
) -> dict:
    """완료된 고정 결과를 명시한 캐릭터 자산 항목으로 승격한다."""
    try:
        request = json.loads(data.get("body") or b"{}")
    except Exception as error:
        return {"ok": False, "error": str(error)}
    save_as = str(request.get("save_as") or "").strip()
    if save_as not in ("representative", "evidence", "variation"):
        return {
            "ok": False,
            "error": "대표·근거·variation 중 저장 위치를 골라주세요.",
        }
    with server.config_lock:
        pending = copy.deepcopy(server.pending_variation)
        if not isinstance(pending, dict) or not pending.get("result_path"):
            return {
                "ok": False,
                "error": "저장할 완료 결과가 없습니다.",
            }
        result_path = Path(str(pending["result_path"])).resolve()
        latest = server.latest_config_from_disk()
        validation_error, actual_hash = _variation_validation(
            pending,
            result_path,
            latest,
            operations,
        )
        if validation_error:
            return validation_error
        character = next(
            (
                item
                for item in (latest.get("characters") or [])
                if str(item.get("id") or "")
                == str(pending.get("character_id") or "")
            ),
            None,
        )
        if character is None:
            return {
                "ok": False,
                "error": "대상 캐릭터가 없어졌습니다.",
            }
        try:
            candidates = _variation_candidates(
                character,
                latest,
                pending,
                request,
                actual_hash,
                operations,
            )
        except Exception as error:
            return {
                "ok": False,
                "conflict": True,
                "error": str(error),
            }
        content_type = (
            "image/png"
            if result_path.suffix.lower() == ".png"
            else "image/webp"
        )
        local_ref, _ = operations.local_import_image(
            result_path.read_bytes(),
            content_type,
        )
        updated_character = operations.apply_variation_candidates(
            character,
            candidates,
            local_ref=local_ref,
            save_as=save_as,
        )
        character.clear()
        character.update(updated_character)
        server.cfg.clear()
        server.cfg.update(latest)
        operations.sync_chars_to_files(server.cfg)
        operations.save_config(server.cfg)
        server.config_revision += 1
        return {
            "ok": True,
            "save_as": save_as,
            "character": copy.deepcopy(character),
            "revision": server.config_revision,
            "local_ref": local_ref,
        }


def _variation_validation(
    pending: dict,
    result_path: Path,
    latest: dict,
    operations: CollectionHandlerOperations,
) -> tuple[dict | None, str]:
    root = operations.output_root(latest).resolve()
    try:
        inside = result_path.is_relative_to(root)
    except AttributeError:
        inside = str(result_path).startswith(str(root))
    if not inside or not result_path.is_file():
        return (
            {
                "ok": False,
                "error": "고정된 생성 결과 파일을 확인할 수 없습니다.",
            },
            "",
        )
    actual_hash = hashlib.sha256(
        result_path.read_bytes()
    ).hexdigest()
    if actual_hash != str(pending.get("result_hash") or ""):
        return (
            {
                "ok": False,
                "error": "생성 뒤 결과 파일이 바뀌어 저장하지 않았습니다.",
            },
            "",
        )
    return None, actual_hash


def _variation_candidates(
    character: dict,
    latest: dict,
    pending: dict,
    request: dict,
    actual_hash: str,
    operations: CollectionHandlerOperations,
) -> Any:
    asset = operations.character_asset_from_legacy_record(
        character,
        char_refs=latest.get("char_refs") or [],
        vibes=latest.get("vibes") or [],
    )
    proposal = operations.accept_variation(
        asset,
        pending.get("plan") or {},
        {
            "image_ref": {"content_hash": actual_hash},
            "name": str(request.get("name") or "").strip(),
            "metadata": {
                key: copy.deepcopy(pending.get(key))
                for key in (
                    "mode",
                    "job_id",
                    "seed",
                    "width",
                    "height",
                    "started_at",
                    "completed_at",
                )
            },
        },
    )
    return operations.approved_variation_candidates(
        character,
        proposal,
        approved=True,
    )


def handle_inspect(
    server: Any,
    data: dict,
    operations: CollectionHandlerOperations,
) -> dict:
    """이미지의 NAI 메타데이터를 복원해 그림체 후보와 복원 큐를 만든다."""
    body = data.get("body") or b""
    filename = data.get("filename", "")
    save_flag = data.get("save_flag", "")
    try:
        name = (
            Path(unquote(filename or "")).name
            or "붙여넣은 이미지"
        )
        if not body:
            return _inspect_failure(
                operations,
                "이미지가 비어 있습니다.",
                name,
            )
        content_type = (
            "image/webp"
            if body[:4] == b"RIFF"
            else "image/png"
        )
        metadata = operations.extract_nai_metadata(
            body,
            content_type,
        )
        if metadata["metadata_status"] != "ok":
            return _inspect_failure(
                operations,
                (
                    "이 이미지에는 NAI 생성 정보가 없습니다. "
                    "(카톡·디스코드 등을 거치면 지워집니다 — "
                    "원본 파일을 넣어주세요)"
                ),
                name,
            )
        record = _metadata_style_record(
            server,
            operations,
            metadata,
            body,
            name,
        )
        thumbnail = _inspect_thumbnail(
            operations,
            record,
            body,
        )
        evidence = operations.evidence_from_image_record(record)
        knowledge = operations.style_asset_from_record(
            record,
            evidence_refs=[evidence["id"]],
            lifecycle="candidate",
        )
        record["evidence_records"] = [evidence]
        record["knowledge_asset"] = knowledge
        saved = _save_inspected_style(
            operations,
            record,
            name,
            save_flag,
            thumbnail,
        )
        result = {
            "ok": True,
            "style": record,
            "saved": saved.get("total") if saved else None,
            "import": saved,
        }
        return _with_restore_queue(operations, result, name)
    except Exception as error:
        operations.warning(
            "메타데이터 추출 실패: %s",
            traceback.format_exc(),
        )
        result = {"ok": False, "error": str(error)}
        return _with_restore_queue(
            operations,
            result,
            Path(str(filename or "")).name,
        )


def _inspect_failure(
    operations: CollectionHandlerOperations,
    error: str,
    filename: str,
) -> dict:
    return _with_restore_queue(
        operations,
        {"ok": False, "error": error},
        filename,
    )


def _with_restore_queue(
    operations: CollectionHandlerOperations,
    result: dict,
    filename: str,
) -> dict:
    queue = operations.image_inspect_queue(
        result,
        filename=filename,
    )
    result["restoration"] = operations.summarize_restore_queue(queue)
    result["restoration_queue"] = queue
    return result


def _metadata_style_record(
    server: Any,
    operations: CollectionHandlerOperations,
    metadata: dict,
    body: bytes,
    name: str,
) -> dict:
    artists, rest = operations.parse_artist_combo(metadata["base"])
    params = dict(metadata["params"] or {})
    source_model = operations.model_id_from_metadata(
        params.get("model"),
        server.cfg.get("model") or "nai-diffusion-4-5-full",
    )
    uc_preset, user_negative = operations.split_uc_preset(
        metadata["negative"],
        source_model,
    )
    if "uc_preset" not in params and uc_preset is not None:
        params["uc_preset"] = uc_preset
        params["uc_preset_guessed"] = True
    base_text, quality_toggle = operations.restore_quality_prompt(
        metadata["base"],
        source_model,
        params,
    )
    if "quality_toggle" not in params:
        params["quality_toggle"] = quality_toggle
        params["quality_toggle_guessed"] = True
    content_hash = hashlib.sha256(body).hexdigest()
    return {
        "id": f"file-{content_hash[:20]}",
        "content_sha256": content_hash,
        "title": Path(name).stem[:80],
        "source": "내 이미지",
        "tab": "",
        "posted_at": "",
        "recommend": None,
        "views": None,
        "url": "",
        "count": len(artists),
        "combo": ", ".join(
            (
                f"{weight:g}::artist:{artist}::"
                if weight is not None
                else f"artist:{artist}"
            )
            for weight, artist in artists
        ),
        "artists": [artist for _, artist in artists],
        "weights": {
            artist: weight if weight is not None else 1.0
            for weight, artist in artists
        },
        "base": base_text,
        "rest": ", ".join(rest),
        "negative": (
            user_negative
            if uc_preset is not None
            else metadata["negative"]
        ),
        "negative_full": metadata["negative"],
        "characters": metadata["characters"],
        "metadata_raw": metadata["raw"],
        "params": params,
        "images": [],
    }


def _inspect_thumbnail(
    operations: CollectionHandlerOperations,
    record: dict,
    body: bytes,
) -> dict:
    created = False
    key = ""
    try:
        output = io.BytesIO()
        with Image.open(io.BytesIO(body)) as image:
            image = image.convert("RGB")
            image.thumbnail((512, 512), Image.LANCZOS)
            image.save(output, "WEBP", quality=74, method=4)
        thumbnail = output.getvalue()
        key = hashlib.sha256(thumbnail).hexdigest() + ".webp"
        path = operations.image_cache / key
        if not path.exists():
            operations.atomic_write_bytes(
                path,
                thumbnail,
                keep_backup=False,
            )
            created = True
        record["images"] = [f"local:{key}"]
    except Exception as error:
        operations.warning("추출 썸네일 실패: %s", error)
    return {"created": created, "key": key}


def _save_inspected_style(
    operations: CollectionHandlerOperations,
    record: dict,
    name: str,
    save_flag: Any,
    thumbnail: dict,
) -> Any:
    if save_flag not in ("1", "true"):
        return None
    files = (
        {"수집/이미지캐시": [thumbnail["key"]]}
        if thumbnail["created"] and thumbnail["key"]
        else {}
    )
    return operations.add_style(
        record,
        import_info={
            "kind": "image",
            "file": name,
            "files": files,
        },
        return_detail=True,
    )


__all__ = [
    "CollectionHandlerOperations",
    "handle_character_variation_save",
    "handle_inspect",
]
