# -*- coding: utf-8 -*-
"""자료실 중복 후보의 나란히 비교와 증거 병합 (순수).

- 중복 그림체(find_style_dupes 묶음)의 항목을 원본 이미지·출처·메타데이터·
  생성 설정·평가까지 한 응답으로 투영한다.
- 병합은 `merge_style_evidence`(비파괴, 증거만 추가)를 대표 자산에 반복 적용
  한다. 다른 원본 자산은 삭제하지 않는다 — 삭제는 기존 휴지통 경로의 몫이다.
- weighted prompt는 원문을 그대로 두고 구간(공통·좌측 전용·우측 전용)만
  비교한다. 자동 의미 병합·재작성은 하지 않는다.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

from src.nai_studio.services.style_store import merge_style_evidence

# 가중치 그룹 시작: `1.7::` `.9::` `-0.5::` — `::`로 닫힌다.
_WEIGHT_OPEN = re.compile(r"(?<![\w:])-?(?:\d+\.?\d*|\.\d+)\s*::")


def prompt_segments(text: Any) -> list[str]:
    """프롬프트를 구간으로 나눈다. 가중치 그룹 안의 콤마는 구분자가 아니다.

    원문 보존이 목적이라 구간 내부는 공백만 다듬고 그대로 돌려준다.
    """
    raw = str(text or "")
    segments: list[str] = []
    buffer: list[str] = []
    index, depth = 0, 0
    while index < len(raw):
        match = _WEIGHT_OPEN.match(raw, index)
        if match:
            buffer.append(match.group(0))
            index = match.end()
            depth += 1
            continue
        if depth and raw.startswith("::", index):
            buffer.append("::")
            index += 2
            depth -= 1
            continue
        char = raw[index]
        if char == "," and depth == 0:
            segment = "".join(buffer).strip()
            if segment:
                segments.append(segment)
            buffer = []
        else:
            buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        segments.append(tail)
    return segments


def _segment_key(segment: str) -> str:
    return re.sub(r"\s+", " ", segment).strip().lower()


def prompt_segment_diff(left: Any, right: Any) -> dict:
    """두 프롬프트의 공통·좌측 전용·우측 전용 구간 (원문·순서 보존).

    구간 동일성은 공백 정규화한 원문 기준이다 — 가중치가 다르면 다른 구간으로
    본다 (원문을 해석하거나 고치지 않는다).
    """
    left_segments = prompt_segments(left)
    right_segments = prompt_segments(right)
    right_counts: dict[str, int] = {}
    for segment in right_segments:
        key = _segment_key(segment)
        right_counts[key] = right_counts.get(key, 0) + 1
    common: list[str] = []
    left_only: list[str] = []
    used: dict[str, int] = {}
    for segment in left_segments:
        key = _segment_key(segment)
        if used.get(key, 0) < right_counts.get(key, 0):
            used[key] = used.get(key, 0) + 1
            common.append(segment)
        else:
            left_only.append(segment)
    consumed: dict[str, int] = {}
    right_only: list[str] = []
    for segment in right_segments:
        key = _segment_key(segment)
        if consumed.get(key, 0) < used.get(key, 0):
            consumed[key] = consumed.get(key, 0) + 1
        else:
            right_only.append(segment)
    return {
        "common": common,
        "left_only": left_only,
        "right_only": right_only,
    }


def _compare_row(
    record: dict,
    *,
    canonical_settings: Callable[[dict], dict],
    rating_for: Callable[[dict], Any],
) -> dict:
    return {
        "id": record.get("id"),
        "title": record.get("title") or record.get("이름"),
        "prompt": record.get("prompt") or record.get("combo") or "",
        "negative": record.get("negative") or "",
        "settings": canonical_settings(record),
        "model": record.get("model"),
        "images": list(record.get("images") or []),
        "source": record.get("source"),
        "url": record.get("url"),
        "posted_at": record.get("posted_at"),
        "evidence": list(record.get("evidence") or []),
        "evidence_records": len(record.get("evidence_records") or []),
        "rating": rating_for(record),
        "raw_metadata_present": bool(
            record.get("raw") or record.get("raw_metadata")
        ),
    }


def dupe_compare_payload(
    rows: list,
    ids: Any,
    *,
    canonical_settings: Callable[[dict], dict],
    rating_for: Callable[[dict], Any],
) -> dict:
    """중복 후보 id들을 나란히 비교할 한 응답으로 투영한다 (쓰기 없음)."""
    wanted = [str(value) for value in (ids or []) if str(value)]
    if len(wanted) < 2:
        return {"ok": False, "error": "비교할 항목을 두 개 이상 골라 주세요."}
    by_id = {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }
    missing = [value for value in wanted if value not in by_id]
    if missing:
        return {
            "ok": False,
            "error": "찾을 수 없는 항목이 있습니다: " + ", ".join(missing),
        }
    records = [by_id[value] for value in wanted]
    compared = [
        _compare_row(
            record,
            canonical_settings=canonical_settings,
            rating_for=rating_for,
        )
        for record in records
    ]
    first, second = records[0], records[1]
    return {
        "ok": True,
        "source": "library",
        "rows": compared,
        "prompt_diff": prompt_segment_diff(
            first.get("prompt") or first.get("combo"),
            second.get("prompt") or second.get("combo"),
        ),
        "negative_diff": prompt_segment_diff(
            first.get("negative"), second.get("negative")),
        "recoverable": True,
    }


def merge_evidence_rows(
    rows: list,
    representative_id: Any,
    other_ids: Any,
    *,
    row_digest: Callable[[Any], str],
) -> dict:
    """대표 자산에 나머지 항목의 증거만 비파괴로 합친 새 rows를 만든다.

    원본 자산 행은 그대로 남는다. 되돌리기는 반환된 batch(list_updates)를
    기존 자료팩 Undo 장부에 실어 해결한다.
    """
    representative_id = str(representative_id or "")
    wanted = [
        str(value)
        for value in (other_ids or [])
        if str(value) and str(value) != representative_id
    ]
    if not representative_id or not wanted:
        return {"ok": False, "error": "대표와 합칠 항목을 골라 주세요."}
    index_by_id = {
        str(row.get("id")): position
        for position, row in enumerate(rows)
        if isinstance(row, dict) and row.get("id")
    }
    if representative_id not in index_by_id:
        return {"ok": False, "error": "대표 항목을 찾지 못했습니다."}
    missing = [value for value in wanted if value not in index_by_id]
    if missing:
        return {
            "ok": False,
            "error": "합칠 항목을 찾지 못했습니다: " + ", ".join(missing),
        }
    new_rows = list(rows)
    position = index_by_id[representative_id]
    before = copy.deepcopy(new_rows[position])
    merged = before
    for value in wanted:
        merged = merge_style_evidence(merged, new_rows[index_by_id[value]])
    changed = merged != before
    if changed:
        new_rows[position] = merged
    batch = {
        "kind": "evidence-merge",
        "file": "증거 병합",
        "list_updates": [{
            "stem": "그림체.json",
            "key": representative_id,
            "match_key": True,
            "before": before,
            "after_sha256": row_digest(merged),
        }],
    } if changed else None
    return {
        "ok": True,
        "changed": changed,
        "rows": new_rows,
        "batch": batch,
        "merged_from": wanted,
        "representative": representative_id,
    }


__all__ = [
    "dupe_compare_payload",
    "merge_evidence_rows",
    "prompt_segment_diff",
    "prompt_segments",
]
