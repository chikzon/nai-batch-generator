# -*- coding: utf-8 -*-
"""정적 작업실 템플릿에 제품 선택지와 프로필 표지만 주입한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class PageRenderModel:
    """템플릿이 표시하는 값만 모아 설정·저장 계층과 렌더러를 분리한다."""

    profile: str
    models: Iterable[tuple[Any, str]]
    samplers: Iterable[str]
    schedules: Iterable[str]
    uc_presets: Iterable[tuple[Any, str]]
    resolutions: Iterable[tuple[int, int, str]]
    director_tools: Iterable[tuple[str, str, Any]]
    emotions: Iterable[str]
    boorus: dict[str, dict[str, Any]]


def _options(
    pairs: Iterable[tuple[Any, Any]],
    escape_html: Callable[[Any], str],
) -> str:
    return "".join(
        f'<option value="{value}">{escape_html(label)}</option>'
        for value, label in pairs
    )


def render_page(
    template: str,
    model: PageRenderModel,
    escape_html: Callable[[Any], str],
) -> str:
    """표시 모델을 HTML placeholder에 한 번씩 치환해 완성된 페이지를 돌려준다."""
    resolutions = list(model.resolutions)
    profile = escape_html(model.profile)
    values = {
        "__MODELS__": _options(model.models, escape_html),
        "__SAMPLERS__": _options(
            ((value, value.replace("k_", "")) for value in model.samplers),
            escape_html,
        ),
        "__SCHEDS__": _options(
            ((value, value) for value in model.schedules),
            escape_html,
        ),
        "__UCP__": _options(
            ((str(value), f"{value} · {label}") for value, label in model.uc_presets),
            escape_html,
        ),
        "__RES__": _options(
            (
                (f"{width}x{height}", f"{label} {width}×{height}")
                for width, height, label in resolutions
            ),
            escape_html,
        ),
        "__RESJSON__": json.dumps(
            [
                {"w": width, "h": height, "label": label}
                for width, height, label in resolutions
            ],
            ensure_ascii=False,
        ),
        "__DIRTOOLS__": _options(
            ((tool, label) for tool, label, _ in model.director_tools),
            escape_html,
        ),
        "__EMOTIONS__": _options(
            ((emotion, emotion) for emotion in model.emotions),
            escape_html,
        ),
        "__BOORUS__": _options(
            (
                (key, value["name"] + value.get("note", ""))
                for key, value in model.boorus.items()
            ),
            escape_html,
        ),
        "__PROFNOW__": (
            f"프로필 「{profile}」" if profile else "기본 (첫째 계정)"
        ),
        "__PROFTITLE__": f" — {profile}" if profile else "",
        "__PROFBADGE__": (
            f'<span class="badge" style="margin-left:7px;">프로필 {profile}</span>'
            if profile else ""
        ),
    }
    rendered = template
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


__all__ = ["PageRenderModel", "render_page"]
