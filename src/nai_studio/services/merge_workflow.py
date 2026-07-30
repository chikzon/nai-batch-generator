# -*- coding: utf-8 -*-
"""백업·자료팩 충돌을 한 가지 행 모양으로 투영하는 병합 검토 표면.

적용·되돌리기는 기존 백업·자료팩 workflow가 그대로 수행한다. 이 모듈은
검토 화면이 소스와 무관하게 쓸 공통 행({id, source, kind, label, decision,
base/current/incoming, recoverable})과 응답 조립만 맡는다 — 순수 함수뿐이다.
"""
from __future__ import annotations

from typing import Any

MERGE_ROW_SCHEMA = "nais-merge-row/v1"
MERGE_SOURCES = ("backup", "datapack")


def classify_merge_kind(logical: Any) -> str:
    """행 분류 — 그림체·캐릭터는 묶음(프롬프트+네거티브+설정)째 검토한다."""
    text = str(logical or "")
    if "그림체" in text or "작가조합" in text:
        return "그림체"
    if "캐릭터" in text:
        return "캐릭터"
    if "세팅" in text or "씬" in text:
        return "세팅"
    if "이미지캐시" in text:
        return "이미지"
    if text.endswith("설정.json"):
        return "설정"
    return "기타"


def merge_rows_from_backup(preview: dict) -> list[dict]:
    """백업 검사 결과의 change들을 공통 행으로 투영한다 (3-way 판정 포함)."""
    rows = []
    for change in preview.get("changes") or []:
        pointer = str(change.get("pointer") or "/")
        rows.append({
            "schema": MERGE_ROW_SCHEMA,
            "id": change.get("id"),
            "source": "backup",
            "kind": classify_merge_kind(change.get("logical")),
            "label": str(change.get("logical") or "")
            + ("" if pointer == "/" else f" · {pointer}"),
            "action": change.get("action"),
            "decision": change.get("decision", "no-base"),
            "base_found": bool(change.get("base_found")),
            "base": change.get("base"),
            "current": change.get("current"),
            "incoming": change.get("incoming"),
            "recoverable": True,
        })
    return rows


def merge_rows_from_datapack(preview: dict) -> list[dict]:
    """자료팩 검사 결과의 충돌을 공통 행으로 투영한다 (아직 2-way)."""
    rows = []
    for conflict in preview.get("conflicts") or []:
        rows.append({
            "schema": MERGE_ROW_SCHEMA,
            "id": conflict.get("id"),
            "source": "datapack",
            "kind": classify_merge_kind(conflict.get("logical")),
            "label": str(conflict.get("logical") or "")
            + (
                f" · {conflict.get('key')}"
                if conflict.get("key")
                and conflict.get("key") != conflict.get("logical")
                else ""
            ),
            "action": "변경",
            "decision": "no-base",
            "base_found": False,
            "base": None,
            "current": conflict.get("current"),
            "incoming": conflict.get("incoming"),
            "recoverable": True,
        })
    return rows


def merge_preview_response(
    source: str,
    detail: dict,
    rows: list[dict],
) -> dict:
    decisions: dict[str, int] = {}
    for row in rows:
        decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1
    return {
        "ok": bool(detail.get("ok")),
        "source": source,
        "rows": rows,
        "count": len(rows),
        "decisions": decisions,
        "sha256": str(detail.get("sha256") or ""),
        "diff_fingerprint": str(detail.get("diff_fingerprint") or ""),
        "recoverable": True,
        "detail": detail,
    }


def merge_apply_response(source: str, result: dict) -> dict:
    undo_id = str(result.get("batch") or "")
    return {
        "ok": bool(result.get("ok")),
        "source": source,
        "undo": (
            {"source": source, "id": undo_id}
            if result.get("ok") and undo_id
            else None
        ),
        "detail": result,
    }


def merge_undo_response(source: str, result: dict) -> dict:
    return {"ok": bool(result.get("ok")), "source": source, "detail": result}


__all__ = [
    "MERGE_ROW_SCHEMA",
    "MERGE_SOURCES",
    "classify_merge_kind",
    "merge_apply_response",
    "merge_preview_response",
    "merge_rows_from_backup",
    "merge_rows_from_datapack",
    "merge_undo_response",
]
