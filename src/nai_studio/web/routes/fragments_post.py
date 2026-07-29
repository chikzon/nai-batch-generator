# -*- coding: utf-8 -*-
"""프롬프트 조각 저장·임포트·미리보기 POST 라우트."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from src.nai_studio.services.fragment_workflow import (
    delete_fragment_workflow,
    preview_fragment_workflow,
    reset_fragment_sequence,
    save_fragment_workflow,
)


@dataclass(frozen=True)
class FragmentPostOperations:
    fragment_dir: Any
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


def handle_fragment_post(
    request: Any,
    application: Any,
    operations: FragmentPostOperations,
    body: bytes,
) -> bool:
    try:
        data = _json_body(body)
        if request.path.startswith("/api/frag_save"):
            result = save_fragment_workflow(operations, data)
        elif request.path.startswith("/api/frag_del"):
            result = delete_fragment_workflow(operations, data)
        elif request.path.startswith("/api/frag_reset"):
            result = reset_fragment_sequence(application, operations)
        elif request.path.startswith("/api/frag_import"):
            result = operations.import_fragments(
                body, unquote(request.headers.get("X-Filename", ""))
            )
        elif request.path.startswith("/api/frag_try"):
            result = preview_fragment_workflow(operations, data)
        else:
            return False
        request._json(result)
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["FragmentPostOperations", "handle_fragment_post"]
