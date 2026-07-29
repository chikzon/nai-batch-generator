# -*- coding: utf-8 -*-
"""메타데이터 감사 장부의 검증된 한 건을 복원 후보와 그림체로 연결한다."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .metadata_audit_adapter import MetadataAuditAdapter


@dataclass(frozen=True)
class MetadataCandidatePaths:
    """후보가 읽힐 감사 장부의 프로필 경계."""

    base_dir: Path
    ledger_path: Path | None = None


@dataclass(frozen=True)
class MetadataCandidateOperations:
    """기존 감사·복원·그림체 저장 계약을 호출 시점에 연결한다."""

    adapter_for_paths: Callable[
        [MetadataCandidatePaths], MetadataAuditAdapter
    ]
    extract_nai_metadata: Callable[[bytes, str], dict[str, Any]]
    nai_json_metadata: Callable[[Any], dict[str, Any] | None]
    prompt_parts: Callable[[dict[str, Any]], tuple[Any, Any, Any]]
    param_keys: tuple[str, ...]
    image_inspect_queue: Callable[..., dict[str, Any]]
    redact_diagnostic_text: Callable[[Any], str]
    parse_artist_combo: Callable[[str], tuple[list[Any], list[str]]]
    style_asset_from_record: Callable[..., dict[str, Any]]
    add_style: Callable[..., dict[str, Any]]


def _metadata_from_payload(
    operations: MetadataCandidateOperations,
    relative_path: str,
    payload: bytes,
) -> dict[str, Any]:
    suffix = Path(relative_path).suffix.casefold()
    if suffix in (".png", ".webp"):
        mime = "image/png" if suffix == ".png" else "image/webp"
        return operations.extract_nai_metadata(payload, mime)
    if suffix != ".json":
        raise ValueError("PNG, WebP, JSON 후보만 열 수 있습니다.")
    value = json.loads(payload.decode("utf-8-sig"))
    raw = operations.nai_json_metadata(value)
    if raw is None:
        raise ValueError(
            "선택한 JSON에서 NAI 생성 메타데이터를 찾지 못했습니다."
        )
    base, negative, characters = operations.prompt_parts(raw)
    params = {
        key: raw[key]
        for key in operations.param_keys
        if raw.get(key) is not None
    }
    return {
        "metadata_status": "ok",
        "base": base,
        "negative": negative,
        "characters": characters,
        "params": params,
        "raw": raw,
    }


def _evidence_candidate(
    operations: MetadataCandidateOperations,
    relative_path: str,
    style: dict[str, Any],
) -> dict[str, Any]:
    queue = operations.image_inspect_queue(
        {"ok": True, "style": style},
        filename=operations.redact_diagnostic_text(
            Path(relative_path).name
        ),
    )
    return copy.deepcopy(
        queue["items"][0]["result"]["evidence_candidate"]
    )


def _candidate_from_metadata(
    operations: MetadataCandidateOperations,
    relative_path: str,
    metadata: dict[str, Any],
    *,
    include_raw: bool,
) -> dict[str, Any]:
    candidate = {
        "base": str(metadata.get("base") or ""),
        "negative": str(metadata.get("negative") or ""),
        "negative_full": str(metadata.get("negative") or ""),
        "characters": copy.deepcopy(metadata.get("characters") or []),
        "params": copy.deepcopy(metadata.get("params") or {}),
    }
    evidence = _evidence_candidate(
        operations,
        relative_path,
        {
            **candidate,
            "metadata_raw": copy.deepcopy(metadata.get("raw") or {}),
        },
    )
    actual = evidence.get("actual_generation") or {}
    candidate.update({
        "base": str(actual.get("base") or ""),
        "negative": str(actual.get("negative") or ""),
        "negative_full": str(actual.get("negative") or ""),
        "characters": copy.deepcopy(actual.get("characters") or []),
        "params": copy.deepcopy(actual.get("settings") or {}),
    })
    if include_raw:
        candidate["metadata_raw"] = copy.deepcopy(
            metadata.get("raw") or {}
        )
    return candidate


def metadata_audit_candidate(
    paths: MetadataCandidatePaths,
    operations: MetadataCandidateOperations,
    body: bytes | str,
    *,
    include_raw: bool = False,
) -> dict[str, Any]:
    """감사 장부의 SHA와 현재 파일을 다시 대조해 저장 없는 후보를 반환한다."""
    data = json.loads(body or b"{}")
    relative_path = str(data.get("path") or "")
    digest = str(data.get("sha256") or "")
    payload = operations.adapter_for_paths(paths).read_verified(
        relative_path, digest
    )
    metadata = _metadata_from_payload(
        operations, relative_path, payload
    )
    if metadata.get("metadata_status") != "ok":
        raise ValueError(
            "선택한 파일의 NAI 생성 메타데이터가 더 이상 유효하지 않습니다."
        )
    return {
        "ok": True,
        "path": relative_path,
        "sha256": digest.lower(),
        "candidate": _candidate_from_metadata(
            operations,
            relative_path,
            metadata,
            include_raw=include_raw,
        ),
    }


def _artist_fields(
    operations: MetadataCandidateOperations,
    base: str,
) -> dict[str, Any]:
    artists, rest = operations.parse_artist_combo(base)
    return {
        "count": len(artists),
        "combo": ", ".join(
            (
                f"{weight:g}::artist:{name}::"
                if weight is not None
                else f"artist:{name}"
            )
            for weight, name in artists
        ),
        "artists": [name for _, name in artists],
        "weights": {
            name: weight if weight is not None else 1.0
            for weight, name in artists
        },
        "rest": ", ".join(rest),
    }


def _candidate_record(
    operations: MetadataCandidateOperations,
    candidate: dict[str, Any],
    digest: str,
) -> dict[str, Any]:
    base = str(candidate.get("base") or "")
    artist_fields = _artist_fields(operations, base)
    return {
        "id": f"audit-{digest[:20]}",
        "content_sha256": digest,
        "title": f"복원 후보 {digest[:12]}",
        "source": "보유 자료 감사",
        "tab": "",
        "posted_at": "",
        "recommend": None,
        "views": None,
        "url": "",
        **artist_fields,
        "base": base,
        "negative": str(candidate.get("negative") or ""),
        "negative_full": str(candidate.get("negative_full") or ""),
        "characters": copy.deepcopy(candidate.get("characters") or []),
        "metadata_raw": copy.deepcopy(
            candidate.get("metadata_raw") or {}
        ),
        "params": copy.deepcopy(candidate.get("params") or {}),
        "images": [],
    }


def _record_with_evidence(
    operations: MetadataCandidateOperations,
    relative_path: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    evidence = _evidence_candidate(
        operations, relative_path, record
    )
    actual = evidence.get("actual_generation") or {}
    record.update({
        "base": str(actual.get("base") or ""),
        "negative": str(actual.get("negative") or ""),
        "characters": copy.deepcopy(actual.get("characters") or []),
        "params": copy.deepcopy(actual.get("settings") or {}),
    })
    record["negative_full"] = record["negative"]
    record.update(_artist_fields(operations, record["base"]))
    record["metadata_raw"] = copy.deepcopy(
        evidence.get("raw_metadata") or {}
    )
    record["evidence_records"] = [evidence]
    record["knowledge_asset"] = operations.style_asset_from_record(
        record,
        evidence_refs=[evidence["id"]],
        lifecycle="candidate",
    )
    return record


def metadata_audit_save_candidate(
    paths: MetadataCandidatePaths,
    operations: MetadataCandidateOperations,
    body: bytes | str,
) -> dict[str, Any]:
    """검증·정제한 후보를 기존 그림체 충돌 처리와 원자 저장 경계로 보낸다."""
    result = metadata_audit_candidate(
        paths, operations, body, include_raw=True
    )
    digest = result["sha256"]
    record = _candidate_record(
        operations, result["candidate"], digest
    )
    record = _record_with_evidence(
        operations, result["path"], record
    )
    saved = operations.add_style(
        record,
        import_info={
            "kind": "metadata-audit",
            "file": f"자료색인 후보 {digest[:12]}",
        },
        return_detail=True,
    )
    return {
        "ok": True,
        "sha256": digest,
        "import": {
            key: saved.get(key)
            for key in (
                "action",
                "total",
                "batch",
                "changed",
                "id",
            )
        },
    }
