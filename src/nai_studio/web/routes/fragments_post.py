# -*- coding: utf-8 -*-
"""프롬프트 조각 저장·임포트·미리보기 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote


@dataclass(frozen=True)
class FragmentPostOperations:
    fragment_dir: Path
    save_fragment: Any
    list_fragments: Any
    recoverable_remove: Any
    load_state: Any
    save_state: Any
    import_fragments: Any
    reroll_components: Any
    resolve_prompt: Any
    sequence_text: Any
    resolve_fragments: Any
    random_factory: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _save(
    request: Any, operations: FragmentPostOperations, body: bytes
) -> None:
    data = _json_body(body)
    old_name = (data.get("old") or "").strip()
    name = operations.save_fragment(
        data.get("name", ""), data.get("lines") or []
    )
    if old_name and old_name != name:
        old_path = operations.fragment_dir / f"{old_name}.txt"
        if old_path.exists():
            operations.recoverable_remove(old_path, label="이름변경")
    request._json({
        "ok": True,
        "name": name,
        "fragments": operations.list_fragments(),
    })


def _delete(
    request: Any, operations: FragmentPostOperations, body: bytes
) -> None:
    name = Path(_json_body(body).get("name", "")).name
    path = operations.fragment_dir / f"{name}.txt"
    if path.exists():
        operations.recoverable_remove(path)
    request._json({"ok": True, "fragments": operations.list_fragments()})


def _reset(
    request: Any,
    application: Any,
    operations: FragmentPostOperations,
) -> None:
    state = operations.load_state()
    state["frag_seq"] = {}
    operations.save_state(state)
    application.cfg["_frag_counters"] = state["frag_seq"]
    request._json({"ok": True})


def _preview(
    request: Any, operations: FragmentPostOperations, body: bytes
) -> None:
    data = _json_body(body)
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
    request._json({
        "ok": True,
        "text": outputs[0],
        "result": result,
        "ui_state": result["ui_state"],
    })


def handle_fragment_post(
    request: Any,
    application: Any,
    operations: FragmentPostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/frag_save"):
            _save(request, operations, body)
        elif request.path.startswith("/api/frag_del"):
            _delete(request, operations, body)
        elif request.path.startswith("/api/frag_reset"):
            _reset(request, application, operations)
        elif request.path.startswith("/api/frag_import"):
            request._json(operations.import_fragments(
                body, unquote(request.headers.get("X-Filename", ""))
            ))
        elif request.path.startswith("/api/frag_try"):
            _preview(request, operations, body)
        else:
            return False
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["FragmentPostOperations", "handle_fragment_post"]
