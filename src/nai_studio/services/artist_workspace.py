# -*- coding: utf-8 -*-
"""작가 태그 파싱과 조합 가중치 계산의 순수 작업 경계."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable


_COMBO_NUMBER = r"-?(?:\d+\.\d*|\.\d+|\d+)"
_COMBO_OPEN = re.compile(
    rf"^\s*\{{*\s*({_COMBO_NUMBER})\s*::\s*"
)
_COMBO_ARTIST = re.compile(
    r"^\s*artists?\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_COMBO_GLUE = re.compile(
    rf"::\s+(?=(?:{_COMBO_NUMBER}\s*::\s*)?artists?\s*:)",
    re.IGNORECASE,
)
_NOT_ARTIST = {
    "artist collaboration",
    "artist name",
    "artist request",
    "artist logo",
    "artist signature",
    "artist self-insert",
    "multiple artists",
    "style parody",
}


@dataclass(frozen=True)
class ArtistWorkspaceOperations:
    """무작위 생성과 프롬프트 결합을 현재 애플리케이션 경계에서 주입한다."""

    seeded_random: Callable[[str], Any]
    system_random: Callable[[], Any]
    join_tags: Callable[..., str]


def parse_artist_combo(
    text: str,
) -> tuple[list[tuple[float | None, str]], list[str]]:
    """프롬프트에서 순서·가중치를 보존한 작가와 나머지 원문 토큰을 나눈다."""
    artists: list[tuple[float | None, str]] = []
    rest: list[str] = []
    weight: float | None = None
    prepared = _COMBO_GLUE.sub(
        ":: , ",
        text or "",
    ).replace("\n", ",")
    for token in prepared.split(","):
        raw = token
        normalized = token.strip()
        if not normalized:
            continue
        opening = _COMBO_OPEN.match(normalized)
        if opening:
            weight = float(opening.group(1))
            normalized = normalized[opening.end():].strip()
        closing = (
            normalized.endswith("::")
            or normalized.endswith("}}")
        )
        normalized = (
            normalized.rstrip("}")
            .rstrip(":")
            .rstrip()
            .rstrip("{")
            .strip()
        )
        if normalized:
            artist_match = _COMBO_ARTIST.match(normalized)
            if artist_match:
                name = re.sub(
                    r"\s+",
                    " ",
                    artist_match.group(1),
                ).strip(" _:")
                if name.count(")") > name.count("("):
                    name = name.rstrip(")").strip()
                if (
                    name
                    and len(name) <= 60
                    and "::" not in name
                    and name.lower() not in _NOT_ARTIST
                ):
                    artists.append((weight, name))
            else:
                rest.append(raw.strip())
        if closing:
            weight = None
    return artists, rest


def finite_number(value: Any, fallback: Any = 1.0) -> float:
    """빈 값은 fallback으로 바꾸되 NaN·무한대는 가중치로 허용하지 않는다."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(fallback)
    if not math.isfinite(result):
        raise ValueError("가중치는 유한한 숫자여야 합니다.")
    return result


def artist_weight_text(value: float) -> str:
    """가중치를 세 자리 이하로 유지하며 음의 0을 사용자 문자열에서 제거한다."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def compose_artist_workspace(
    operations: ArtistWorkspaceOperations,
    rows: Any,
    mode: str = "custom",
    curve_start: Any = 1.2,
    curve_end: Any = 0.8,
    seed: Any = "",
) -> dict[str, Any]:
    """행 순서와 잠금을 지키며 고정·균일·곡선·무작위 작가 조합을 만든다."""
    if not isinstance(rows, list):
        raise ValueError("작가 목록 형식이 올바르지 않습니다.")
    mode = str(mode or "custom").strip().lower()
    if mode not in {"custom", "balanced", "curve", "random"}:
        raise ValueError("알 수 없는 가중치 방식입니다.")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows[:20]:
        if not isinstance(raw, dict):
            continue
        name = re.sub(
            r"\s+",
            " ",
            str(raw.get("name") or ""),
        ).strip()
        if not name:
            continue
        if (
            len(name) > 60
            or any(
                marker in name
                for marker in (",", "\n", "\r", "::")
            )
        ):
            raise ValueError(
                f"작가 이름 형식이 올바르지 않습니다: {name[:30]}"
            )
        key = name.casefold()
        if key in seen:
            raise ValueError(
                f"같은 작가가 두 번 들어 있습니다: {name}"
            )
        seen.add(key)
        weight = finite_number(raw.get("weight"), 1.0)
        minimum = finite_number(raw.get("min"), weight)
        maximum = finite_number(raw.get("max"), weight)
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        cleaned.append({
            "name": name,
            "weight": weight,
            "min": minimum,
            "max": maximum,
            "locked": bool(raw.get("locked")),
        })
    if not cleaned:
        return {"rows": [], "combo": ""}

    unlocked = [
        row for row in cleaned if not row["locked"]
    ]
    if mode == "balanced":
        for row in unlocked:
            row["weight"] = 1.0
    elif mode == "curve":
        start = finite_number(curve_start, 1.2)
        end = finite_number(curve_end, 0.8)
        for index, row in enumerate(unlocked):
            ratio = index / max(1, len(unlocked) - 1)
            row["weight"] = start + (end - start) * ratio
    elif mode == "random":
        randomizer = (
            operations.seeded_random(str(seed))
            if str(seed)
            else operations.system_random()
        )
        for row in unlocked:
            row["weight"] = randomizer.uniform(
                row["min"],
                row["max"],
            )

    combo = ", ".join(
        f"{artist_weight_text(row['weight'])}::"
        f"artist:{row['name']}::"
        for row in cleaned
    )
    return {"rows": cleaned, "combo": combo}


def artist_workspace_request(
    operations: ArtistWorkspaceOperations,
    data: Any,
) -> dict[str, Any]:
    """UI의 parse·compose 요청을 같은 파서와 가중치 규칙으로 처리한다."""
    if not isinstance(data, dict):
        raise ValueError("잘못된 요청 형식입니다.")
    action = str(data.get("action") or "compose")
    base = str(data.get("base") or "")
    if action == "parse":
        artists, _rest = parse_artist_combo(base)
        rows = [{
            "name": name,
            "weight": (
                weight if weight is not None else 1.0
            ),
            "min": (
                weight if weight is not None else 0.7
            ),
            "max": (
                weight if weight is not None else 1.3
            ),
            "locked": False,
        } for weight, name in artists]
        return {"ok": True, "rows": rows}
    result = compose_artist_workspace(
        operations,
        data.get("rows") or [],
        mode=data.get("mode"),
        curve_start=data.get("curve_start"),
        curve_end=data.get("curve_end"),
        seed=data.get("seed"),
    )
    _artists, rest = parse_artist_combo(base)
    prompt = operations.join_tags(
        result["combo"],
        ", ".join(rest),
    )
    return {"ok": True, **result, "prompt": prompt}


__all__ = [
    "ArtistWorkspaceOperations",
    "artist_weight_text",
    "artist_workspace_request",
    "compose_artist_workspace",
    "finite_number",
    "parse_artist_combo",
]
