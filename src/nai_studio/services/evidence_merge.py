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

from src.nai_studio.domain.evaluation import merge_evaluations
from src.nai_studio.domain.resources import canonical_resource
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


def _character_text(record: dict, *names: str) -> str:
    for name in names:
        value = record.get(name)
        if value:
            return str(value)
    return ""


def character_text_key(record: dict) -> str:
    """중복 후보 판정 키 — 원문(외형·착의·네거티브)만 본다.

    변형·참조·증거는 일부러 뺀다: 그 차이를 합치는 것이 병합의 목적이라,
    지문에 넣으면 정작 합칠 쌍을 못 잡는다.
    """
    return "\n".join((
        _character_text(record, "female", "prompt", "외형").strip(),
        _character_text(record, "clothed", "outfit", "착의").strip(),
        _character_text(record, "negative", "네거티브").strip(),
    ))


def find_character_dupes(
    characters: list,
    *,
    bundle_signature: Callable[[dict], str],
) -> dict:
    """원문이 같은 캐릭터를 묶는다 (변형·참조가 달라도 같은 후보)."""
    del bundle_signature  # 표시용 비교 payload에서만 쓴다
    groups: dict[str, list[dict]] = {}
    for record in characters or []:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        groups.setdefault(character_text_key(record), []).append(record)
    duplicates = [
        {
            "건수": len(rows),
            "항목": [
                {"id": row.get("id"), "name": row.get("name")}
                for row in rows
            ],
        }
        for rows in groups.values()
        if len(rows) >= 2
    ]
    duplicates.sort(key=lambda group: -group["건수"])
    return {
        "ok": True,
        "묶음": len(duplicates),
        "전체": len(characters or []),
        "목록": duplicates[:300],
    }


def character_compare_payload(
    characters: list,
    ids: Any,
    *,
    bundle_signature: Callable[[dict], str],
) -> dict:
    """캐릭터 중복 후보를 원문·변형·참조·증거까지 나란히 투영한다 (쓰기 없음)."""
    wanted = [str(value) for value in (ids or []) if str(value)]
    if len(wanted) < 2:
        return {"ok": False, "error": "비교할 캐릭터를 두 개 이상 골라 주세요."}
    by_id = {
        str(row.get("id")): row
        for row in characters or []
        if isinstance(row, dict) and row.get("id")
    }
    missing = [value for value in wanted if value not in by_id]
    if missing:
        return {
            "ok": False,
            "error": "찾을 수 없는 캐릭터가 있습니다: " + ", ".join(missing),
        }
    records = [by_id[value] for value in wanted]
    rows = [{
        "id": record.get("id"),
        "name": record.get("name"),
        "prompt": _character_text(record, "female", "prompt", "외형"),
        "outfit": _character_text(record, "clothed", "outfit", "착의"),
        "negative": _character_text(record, "negative", "네거티브"),
        "variants": copy.deepcopy(record.get("variants") or []),
        "reference_ids": list(record.get("reference_ids") or []),
        "vibe_ids": list(record.get("vibe_ids") or []),
        "evidence_records": len(record.get("evidence_records") or []),
        "bundle_signature": bundle_signature(record),
    } for record in records]
    first, second = records[0], records[1]
    return {
        "ok": True,
        "source": "characters",
        "rows": rows,
        "prompt_diff": prompt_segment_diff(
            _character_text(first, "female", "prompt", "외형"),
            _character_text(second, "female", "prompt", "외형"),
        ),
        "negative_diff": prompt_segment_diff(
            _character_text(first, "negative", "네거티브"),
            _character_text(second, "negative", "네거티브"),
        ),
        "recoverable": False,
    }


def _union_records(base: list, extra: list, key: str = "id") -> list:
    merged = list(base or [])
    known = {
        str(item.get(key)) if isinstance(item, dict) else repr(item)
        for item in merged
    }
    for item in extra or []:
        marker = (
            str(item.get(key)) if isinstance(item, dict) else repr(item)
        )
        if marker not in known:
            merged.append(copy.deepcopy(item))
            known.add(marker)
    return merged


def _resource_duplicate_groups(
    resource_records: list,
    wanted_ids: set[str],
) -> list[list[str]]:
    """병합된 캐릭터가 가리키는 자원 중 내용이 같은 것들을 알려만 준다.

    자원 자체는 자동 통합하지 않는다 — 도메인 canonical_resource의
    내용 지문(강도·출처 무관)으로 같은 자원인지 판정만 한다.
    """
    by_fingerprint: dict[str, list[str]] = {}
    for record in resource_records or []:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or "")
        if record_id not in wanted_ids:
            continue
        try:
            fingerprint = canonical_resource(record)["fingerprint"]
        except Exception:
            continue
        by_fingerprint.setdefault(fingerprint, []).append(record_id)
    return [ids for ids in by_fingerprint.values() if len(ids) >= 2]


def merge_character_assets(
    characters: list,
    representative_id: Any,
    other_ids: Any,
    *,
    bundle_signature: Callable[[dict], str],
    resource_records: list | None = None,
) -> dict:
    """대표 캐릭터에 다른 캐릭터의 변형·참조·증거를 **더하기만** 한다.

    원문(외형·착의·네거티브)은 대표 것을 그대로 두고, 원본 캐릭터도
    삭제하지 않는다. 평가 레코드가 양쪽에 있으면 도메인 merge_evaluations로
    합치고, 내용이 같은 자원 참조는 통합하지 않고 목록으로 알려 준다.
    """
    representative_id = str(representative_id or "")
    wanted = [
        str(value) for value in (other_ids or [])
        if str(value) and str(value) != representative_id
    ]
    if not representative_id or not wanted:
        return {"ok": False, "error": "대표와 합칠 캐릭터를 골라 주세요."}
    index_by_id = {
        str(row.get("id")): position
        for position, row in enumerate(characters or [])
        if isinstance(row, dict) and row.get("id")
    }
    if representative_id not in index_by_id:
        return {"ok": False, "error": "대표 캐릭터를 찾지 못했습니다."}
    missing = [value for value in wanted if value not in index_by_id]
    if missing:
        return {
            "ok": False,
            "error": "합칠 캐릭터를 찾지 못했습니다: " + ", ".join(missing),
        }
    new_rows = [copy.deepcopy(row) for row in characters]
    merged = new_rows[index_by_id[representative_id]]
    before = copy.deepcopy(merged)
    evaluations = [merged["evaluation"]] if isinstance(
        merged.get("evaluation"), dict) else []
    for value in wanted:
        other = new_rows[index_by_id[value]]
        merged["variants"] = _union_records(
            merged.get("variants"), other.get("variants"))
        for field in ("reference_ids", "vibe_ids", "evidence_refs"):
            merged[field] = _union_records(
                merged.get(field), other.get(field))
            if not merged[field]:
                merged.pop(field, None)
        merged["evidence_records"] = _union_records(
            merged.get("evidence_records"), other.get("evidence_records"))
        if not merged["evidence_records"]:
            merged.pop("evidence_records", None)
        if isinstance(other.get("evaluation"), dict):
            evaluations.append(other["evaluation"])
    evaluation_conflicts: list = []
    if len(evaluations) >= 2:
        try:
            outcome = merge_evaluations(*evaluations)
            merged["evaluation"] = outcome["evaluation"]
            evaluation_conflicts = list(outcome.get("conflicts") or [])
        except Exception:
            pass
    changed = merged != before
    resource_ids = {
        str(item) for item in
        list(merged.get("reference_ids") or [])
        + list(merged.get("vibe_ids") or [])
    }
    return {
        "ok": True,
        "changed": changed,
        "rows": new_rows,
        "representative": representative_id,
        "merged_from": wanted,
        "evaluation_conflicts": evaluation_conflicts,
        "resource_duplicates": _resource_duplicate_groups(
            resource_records or [], resource_ids),
    }


__all__ = [
    "character_compare_payload",
    "character_text_key",
    "dupe_compare_payload",
    "find_character_dupes",
    "merge_character_assets",
    "merge_evidence_rows",
    "prompt_segment_diff",
    "prompt_segments",
]
