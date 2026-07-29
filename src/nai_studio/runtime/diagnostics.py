# -*- coding: utf-8 -*-
"""진단 로그를 안전한 구조화 사건으로 바꾸는 순수 변환 계층."""
from __future__ import annotations

import re
from datetime import datetime


_DIAG_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"\[(?P<level>[A-Z]+)\] (?P<message>.*)$"
)
_DIAG_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(pst-)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*"
            r"(?:bearer\s+|basic\s+)?[^\s,;]+"
        ),
        r"\1: [REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|"
            r"token|secret|signature|credential)\s*[:=]\s*[^\s,;&]+"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)([?&](?:api[-_]?key|access[-_]?token|refresh[-_]?token|"
            r"token|key|secret|signature|credential|x-amz-[^=&#\s]+)=)"
            r"[^&#\s]+"
        ),
        r"\1[REDACTED]",
    ),
)
_DIAG_USER_PATH_PATTERNS = (
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/\s]+"), r"\1<user>"),
    (re.compile(r"(?i)(/Users/)[^/\s]+"), r"\1<user>"),
    (re.compile(r"(?i)(/home/)[^/\s]+"), r"\1<user>"),
)


def redact_diagnostic_text(value):
    """진단 화면/API에 내보내기 전에 토큰·서명·사용자 홈 경로를 지운다."""
    text = str(value or "")
    for pattern, replacement in _DIAG_SECRET_PATTERNS + _DIAG_USER_PATH_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def diagnostic_category(message):
    """기계적인 키워드 분류다. 원문 의미를 추측해 심각도를 바꾸지는 않는다."""
    text = message.casefold()
    categories = (
        ("security", ("authorization", "token", "secret", "credential", "인증")),
        ("metadata", ("metadata", "png", "exif", "메타데이터")),
        ("pacing", ("pace", "delay", "retry", "backoff", "cancel", "중지", "재시도")),
        ("generation", ("generate", "generation", "anlas", "생성", "seed")),
        ("network", ("http", "request", "connection", "timeout", "network", "서버")),
        ("storage", ("save", "saved", "output", "file", "folder", "저장", "파일", "폴더")),
    )
    for category, needles in categories:
        if any(needle in text for needle in needles):
            return category
    return "system"


def parse_diagnostic_lines(lines):
    """기본 로그 형식의 각 줄을 비밀값이 제거된 구조화 사건으로 변환한다."""
    events = []
    previous_at = None
    for raw in lines:
        match = _DIAG_LINE_RE.match(str(raw))
        if not match and events:
            events[-1]["message"] += "\n" + redact_diagnostic_text(raw)
            continue
        if match:
            timestamp = match.group("time")
            level = match.group("level")
            message = match.group("message")
            try:
                at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S,%f")
            except ValueError:
                at = None
        else:
            timestamp = ""
            level = "INFO"
            message = str(raw)
            at = None
        since_previous_ms = None
        if at is not None and previous_at is not None:
            since_previous_ms = max(0, round((at - previous_at).total_seconds() * 1000))
        if at is not None:
            previous_at = at
        safe_message = redact_diagnostic_text(message)
        events.append({
            "time": timestamp,
            "level": level,
            "category": diagnostic_category(safe_message),
            "message": safe_message,
            "since_previous_ms": since_previous_ms,
        })
    return events


def diagnostic_event_line(event):
    """사람이 복사하기 쉬운 한 줄 표기."""
    elapsed = event.get("since_previous_ms")
    delta = "" if elapsed is None else f" +{elapsed}ms"
    stamp = event.get("time") or "시간 미상"
    return (
        f"{stamp}{delta} [{event.get('level', 'INFO')}]"
        f"[{event.get('category', 'system')}] {event.get('message', '')}"
    )


__all__ = [
    "diagnostic_category",
    "diagnostic_event_line",
    "parse_diagnostic_lines",
    "redact_diagnostic_text",
]
