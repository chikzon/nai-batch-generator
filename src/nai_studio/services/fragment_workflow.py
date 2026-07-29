# -*- coding: utf-8 -*-
"""프롬프트 조각의 저장·복구·결정적 미리보기 workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def save_fragment_workflow(operations: Any, data: dict) -> dict:
    """새 이름 저장이 성공한 뒤에만 이전 이름을 복구 가능 삭제한다."""
    old_name = (data.get("old") or "").strip()
    name = operations.save_fragment(
        data.get("name", ""), data.get("lines") or []
    )
    if old_name and old_name != name:
        old_path = operations.fragment_dir() / f"{old_name}.txt"
        if old_path.exists():
            operations.recoverable_remove(old_path, label="이름변경")
    return {
        "ok": True,
        "name": name,
        "fragments": operations.list_fragments(),
    }


def delete_fragment_workflow(operations: Any, data: dict) -> dict:
    name = Path(data.get("name", "")).name
    path = operations.fragment_dir() / f"{name}.txt"
    if path.exists():
        operations.recoverable_remove(path)
    return {"ok": True, "fragments": operations.list_fragments()}


def reset_fragment_sequence(application: Any, operations: Any) -> dict:
    """순차 조각 counter를 상태 파일과 현재 설정에서 함께 초기화한다."""
    state = operations.load_state()
    state["frag_seq"] = {}
    operations.save_state(state)
    application.cfg["_frag_counters"] = state["frag_seq"]
    return {"ok": True}


def preview_fragment_workflow(operations: Any, data: dict) -> dict:
    """저장 counter를 소비하지 않는 복사본으로 조각 결과를 미리 계산한다."""
    seed = data.get("seed", 0)
    if data.get("previous") and data.get("reroll_ids"):
        result = operations.reroll_components(
            data["previous"], data["reroll_ids"], seed
        )
    else:
        result = operations.resolve_prompt(
            data.get("text", ""), operations.list_fragments(), seed
        )
    outputs, _ = operations.resolve_fragments(
        [operations.sequence_text(result)],
        counters=dict(operations.load_state().get("frag_seq", {})),
        rng=operations.random_factory(str(seed)),
    )
    return {
        "ok": True,
        "text": outputs[0],
        "result": result,
        "ui_state": result["ui_state"],
    }


__all__ = [
    "delete_fragment_workflow",
    "preview_fragment_workflow",
    "reset_fragment_sequence",
    "save_fragment_workflow",
]
