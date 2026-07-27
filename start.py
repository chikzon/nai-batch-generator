# -*- coding: utf-8 -*-
# NAI 배치 생성기 — Copyright (C) 2026 ninesdead
# GPL-3.0-or-later. 이 프로그램은 어떠한 보증도 없이 제공됩니다.
# 자세한 조건은 함께 배포되는 LICENSE 파일을 보십시오.
"""NAI 시드 배치 생성기 (단일 파일판, 브라우저 UI 내장)

실행.bat -> start.py 를 실행하면:
  1) 로컬 웹서버가 뜨고 브라우저가 자동으로 열립니다.
  2) 그 화면에서 API 토큰 / 캐릭터(여러 명 추가·삭제) / 기본 프롬프트 /
     네거티브 프롬프트 / 체위 113종 체크박스를 고릅니다.
     -> 값을 바꿀 때마다 설정.json 에 실시간으로 저장됩니다 (자동 저장).
  3) '생성 시작'을 누르면 그 순간부터 실제 생성이 시작되고,
     같은 화면에서 생성되는 이미지를 실시간으로 볼 수 있습니다.

이전 버전의 설정.txt 가 있다면 최초 1회 자동으로 설정.json 으로 옮겨옵니다.
"""
import gzip
import hashlib
import base64
import functools
import io
import json
import logging
import math
import os
import random
import re
import shutil
import string
import struct
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
import zipfile
import zlib
from contextlib import contextmanager
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

# 프로그램 파일과 사용자 자료는 생명주기가 다르다. 설치 프로그램을 제거해도 설정·
# 캐릭터·세팅·수집물·생성물이 함께 사라지면 안 된다. 묶인 실행본은 기본적으로
# %LOCALAPPDATA%\NAI배치생성기\데이터 를 쓰고, 코드·CSS·토크나이저는 exe 옆에서 읽는다.
# 소스 실행은 개발 중인 기존 자료 위치를 바꾸지 않도록 예전처럼 소스 폴더를 쓴다.
PROGRAM_DIR = (Path(sys.executable).parent if getattr(sys, "frozen", False)
               else Path(__file__).parent)


def resolve_data_dir(program_dir=None, frozen=None, argv=None, local_app_data=None):
    """사용자 자료 뿌리를 부작용 없이 결정한다.

    `--data-dir <경로>`는 대용량 개인 자료를 다른 드라이브에 둘 때 쓴다.
    `--portable`은 명시적으로 프로그램 옆에 자료를 두는 호환 모드다.
    """
    program_dir = Path(program_dir or PROGRAM_DIR).resolve()
    frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    argv = list(sys.argv[1:] if argv is None else argv)
    for index, arg in enumerate(argv):
        if str(arg).startswith("--data-dir="):
            value = str(arg).split("=", 1)[1].strip()
            if value:
                return Path(value).expanduser().resolve()
        if arg == "--data-dir" and index + 1 < len(argv):
            value = str(argv[index + 1]).strip()
            if value:
                return Path(value).expanduser().resolve()
    if "--portable" in argv or not frozen:
        return program_dir
    local_root = local_app_data or os.environ.get("LOCALAPPDATA")
    if not local_root:
        # LOCALAPPDATA가 없는 특수 환경에서도 임시 해제 폴더가 아니라 exe 옆에 남긴다.
        return program_dir
    return (Path(local_root) / "NAI배치생성기" / "데이터").resolve()


BASE_DIR = resolve_data_dir()

_LEGACY_USER_FILES = (
    "설정.json", "설정.json.bak", "설정.txt", "asset_config.json",
    "후보사전.json", "규격.json", "옵션.json", "씬.json", "선별.json",
    "nsfw_seed_state.json", "비교생성-진행.json",
)
_LEGACY_USER_DIRS = (
    "프로필", "output", "수집", "캐릭터", "그림체", "태그", "세팅",
    "씬규격", "씬프리셋", "조각",
)


def migrate_legacy_program_data(program_dir, data_dir):
    """옛 설치본의 프로그램 옆 자료를 새 사용자 폴더로 **복사만** 한다.

    원본은 지우지 않고, 대상에 다른 내용이 있으면 덮지 않는다. 중간에 종료돼도 다음
    실행에서 없는 파일만 이어 복사할 수 있도록 완료 기록은 맨 마지막에 쓴다.
    """
    source, target = Path(program_dir).resolve(), Path(data_dir).resolve()
    if source == target:
        return {"status": "same", "copied": 0, "skipped": 0, "conflicts": 0}
    receipt = target / "이전자료-복사기록.json"
    old_receipt = {}
    try:
        old_receipt = json.loads(receipt.read_text(encoding="utf-8"))
        if old_receipt.get("status") == "complete":
            return old_receipt
    except (OSError, json.JSONDecodeError):
        pass
    evidence = [source / name for name in _LEGACY_USER_FILES + _LEGACY_USER_DIRS]
    if not any(path.exists() for path in evidence):
        return {"status": "none", "copied": 0, "skipped": 0, "conflicts": 0}

    # 사용자가 이미 새 위치에 자료를 만든 경우 두 저장소를 자동 병합하지 않는다.
    destination_evidence = [
        target / name for name in _LEGACY_USER_FILES + _LEGACY_USER_DIRS
    ]
    if (old_receipt.get("status") not in ("copying", "partial")
            and any(path.exists() for path in destination_evidence)):
        return {"status": "destination-not-empty", "copied": 0,
                "skipped": 0, "conflicts": 0}

    target.mkdir(parents=True, exist_ok=True)
    result = {"schema": "nais-data-migration/v1", "status": "copying",
              "source": str(source), "target": str(target),
              "copied": 0, "skipped": 0, "conflicts": 0, "errors": []}

    def save_receipt():
        tmp = receipt.with_name(
            f".{receipt.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, receipt)

    save_receipt()

    def copy_one(src, dst):
        if src.is_symlink():
            result["skipped"] += 1
            return
        try:
            if dst.exists():
                if (dst.is_file() and src.is_file()
                        and hashlib.sha256(dst.read_bytes()).digest()
                        == hashlib.sha256(src.read_bytes()).digest()):
                    result["skipped"] += 1
                else:
                    result["conflicts"] += 1
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            result["copied"] += 1
        except OSError as e:
            result["errors"].append(f"{src.name}: {e}")

    for name in _LEGACY_USER_FILES:
        src = source / name
        if src.is_file():
            copy_one(src, target / name)
    for name in _LEGACY_USER_DIRS:
        root = source / name
        if not root.is_dir() or root.is_symlink():
            continue
        for src in sorted(root.rglob("*")):
            if src.is_file():
                copy_one(src, target / name / src.relative_to(root))
    result["status"] = "complete" if not result["errors"] else "partial"
    result["completed_at"] = datetime.now().isoformat(timespec="seconds")
    save_receipt()
    return result


if getattr(sys, "frozen", False) and BASE_DIR.resolve() != PROGRAM_DIR.resolve():
    _DATA_MIGRATION = migrate_legacy_program_data(PROGRAM_DIR, BASE_DIR)
else:
    _DATA_MIGRATION = {"status": "not-needed", "copied": 0,
                       "skipped": 0, "conflicts": 0}

# ── 프로필 (계정 여러 개를 한 폴더에서) ───────────────────────────────
#   실행.bat 이나 명령줄에 `--profile 둘째` 를 주면 그 프로필의
#   설정·상태·생성물만 따로 쓴다. 그림체·태그·후보사전 같은 **공용 자산은 그대로 쓴다.**
#   토큰이 프로필별로 갈리므로 계정 2개를 나란히 돌릴 수 있다.
#   ⚠ 같은 계정으로 두 개를 동시에 돌리지는 말 것 (요청이 겹쳐 밴 위험이 커진다).
def _profile_from_argv():
    for i, a in enumerate(sys.argv[1:]):
        if a.startswith("--profile="):
            return a.split("=", 1)[1].strip()
        if a == "--profile" and i + 2 <= len(sys.argv) - 1:
            return sys.argv[i + 2].strip()
    return ""


PROFILE = _profile_from_argv()
PROFILE_DIR = (BASE_DIR / "프로필" / PROFILE) if PROFILE else BASE_DIR
UI_DIR = PROGRAM_DIR / "ui"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

LEGACY_SETTINGS_FILE = BASE_DIR / "설정.txt"          # 원본 대조본은 공용
SETTINGS_FILE = PROFILE_DIR / "설정.json"
CONFIG_FILE = BASE_DIR / "asset_config.json"
STATE_FILE = PROFILE_DIR / "nsfw_seed_state.json"
COMPARE_PROGRESS_FILE = PROFILE_DIR / "비교생성-진행.json"
OUTPUT_BASE = PROFILE_DIR / "output"
LOG_FILE = PROFILE_DIR / "생성.log"
# 시작 때 설정과 자동 백업이 모두 손상되면 아래에 복구 사실을 남긴다.
# 화면은 이 값을 한 번 읽어 사용자가 기본값으로 바뀐 이유와 원본 보관 위치를 알 수 있다.
STARTUP_RECOVERY_NOTICE = None


def out_root(cfg=None):
    """생성물이 실제로 쌓일 뿌리. 설정의 `out_dir` 이 있으면 거기로 (NAIS3-Custom 참고).
    잘못된 경로면 조용히 무시하고 기본값을 쓴다 — 생성이 실패하면 안 된다.
    ⚠ 탐색기·선별의 경로 이름표는 이 뿌리 기준이라, 뿌리를 바꾸면 옛 목록은 안 보인다."""
    d = ((cfg or {}).get("out_dir") or "").strip()
    if d:
        try:
            p = Path(d).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            return p.resolve()
        except (OSError, ValueError) as e:
            log.warning(f"저장 폴더 '{d}' 를 쓸 수 없어 기본 폴더에 저장합니다: {e}")
    return OUTPUT_BASE


def out_sub(cfg, name):
    """모드별 하위 폴더(단독·씬·복구…). 날짜별 정리를 켜면 그 아래 YYYY-MM-DD 로 나눈다."""
    p = out_root(cfg) / name
    if (cfg or {}).get("out_by_date"):
        p = p / date.today().isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p

NAI_API_URL = "https://image.novelai.net/ai/generate-image"
MAX_CHARS = 6            # NAI 가 한 그림에 받는 인물 수 상한

# 밴 예방 기본값. 전부 설정.json 의 `pace` 로 덮어쓸 수 있다 (기타 탭에서 조절).
DELAY_NORMAL = 8          # 장당 기본 딜레이(초) — 실제로는 ±랜덤 변동
SOFT_REST_EVERY = 350     # N장마다 소프트 휴식
SOFT_REST_SECONDS = 30    # 소프트 휴식 길이
COOLDOWN_EVERY = 3000     # N장마다 5분 쿨다운
COOLDOWN_SECONDS = 300
DAILY_CAP = 7000          # 하루 생성 상한
PACE_DEFAULT = {"delay_min": 5.5, "delay_max": 11.5,
                "soft_every": SOFT_REST_EVERY, "soft_seconds": SOFT_REST_SECONDS,
                "cool_every": COOLDOWN_EVERY, "cool_seconds": COOLDOWN_SECONDS,
                "daily_cap": DAILY_CAP}


def pace(cfg):
    """밴 예방 설정 — 없는 값은 기본값으로 채운다."""
    p = dict(PACE_DEFAULT)
    for k, v in (cfg.get("pace") or {}).items():
        if k in p:
            try:
                p[k] = float(v) if k.startswith("delay") else int(v)
            except (TypeError, ValueError):
                pass
    if p["delay_max"] < p["delay_min"]:
        p["delay_max"] = p["delay_min"]
    return p
PREVIEW_PORT_RANGE = range(8787, 8797)   # 설정 UI / 실시간 미리보기 서버 포트 후보

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("gen")


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
    """logging 기본 형식의 각 줄을 redacted 구조화 이벤트로 변환한다.

    traceback처럼 timestamp 없이 이어지는 줄은 직전 사건의 본문이다. 별도 INFO 사건으로
    만들면 "오류만" 필터에서 원인 스택이 사라지므로 직전 사건에 안전하게 합친다.
    """
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
    """사람이 복사하기 쉬운 한 줄 표기. 모든 값은 이미 redaction을 거친다."""
    elapsed = event.get("since_previous_ms")
    delta = "" if elapsed is None else f" +{elapsed}ms"
    stamp = event.get("time") or "시간 미상"
    return (
        f"{stamp}{delta} [{event.get('level', 'INFO')}]"
        f"[{event.get('category', 'system')}] {event.get('message', '')}"
    )


# JSON 설정/재개 상태는 자동저장과 생성 worker가 동시에 만질 수 있다.
# 같은 디렉터리의 임시 파일을 fsync한 뒤 os.replace해야 중간 종료에도 반쪽 JSON이 남지 않는다.
_JSON_IO_LOCK = threading.RLock()
_SHARED_DATA_THREAD_LOCK = threading.RLock()
_SHARED_DATA_LOCAL = threading.local()


@contextmanager
def shared_data_transaction(root, timeout=15.0):
    """프로필·실행본 둘이 같은 사용자 자료를 고칠 때 한 판씩 처리한다.

    원자 교체만으로는 두 프로세스가 같은 옛 파일을 읽고 각자 쓴 뒤 한쪽 변경을
    잃는 read-modify-write 경쟁을 막지 못한다. 사용자 자료 경로의 지문으로 TEMP에
    1바이트 잠금 파일을 두고, 자료를 다시 읽는 시점부터 기록까지를 한 트랜잭션으로
    묶는다. 같은 스레드의 중첩 호출은 재진입시킨다.
    """
    root = Path(root).resolve()
    # 잠금은 사용자 자료도 프로그램 본체도 아니다. 자료 폴더 안에 두면 개발 트리에
    # 보이거나 자료팩 인벤토리에 섞이므로, 경로 지문으로 TEMP의 공용 잠금만 가리킨다.
    lock_home = Path(tempfile.gettempdir()) / "nais-data-locks"
    lock_path = lock_home / (
        hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
        + ".lock")
    with _SHARED_DATA_THREAD_LOCK:
        held = getattr(_SHARED_DATA_LOCAL, "held", {})
        key = str(lock_path)
        if key in held:
            held[key] += 1
            try:
                yield
            finally:
                held[key] -= 1
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        acquired = False
        deadline = time.monotonic() + max(0.1, float(timeout))
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "다른 실행본이 사용자 자료를 저장 중입니다. 잠시 후 다시 시도하세요.")
                    time.sleep(0.05)
            held[key] = 1
            _SHARED_DATA_LOCAL.held = held
            try:
                yield
            finally:
                held.pop(key, None)
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()


def serialized_data_write(root_getter):
    """공유 자료를 고치는 공개 진입점을 프로세스 간 직렬화한다."""
    def decorate(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            with shared_data_transaction(root_getter()):
                return func(*args, **kwargs)
        return wrapped
    return decorate


def _atomic_write_bytes(path, payload, keep_backup=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _JSON_IO_LOCK:
        if keep_backup and path.exists():
            try:
                old = path.read_bytes()
                bak = path.with_name(path.name + ".bak")
                bak_tmp = bak.with_name(f".{bak.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                with open(bak_tmp, "wb") as f:
                    f.write(old); f.flush(); os.fsync(f.fileno())
                os.replace(bak_tmp, bak)
            except OSError as e:
                log.warning(f"JSON 백업 저장 실패({path.name}): {e}")
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(payload); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(path, data, indent=2, keep_backup=True):
    raw = json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8")
    _atomic_write_bytes(path, raw, keep_backup=keep_backup)


def atomic_write_text(path, text, encoding="utf-8", keep_backup=True):
    """조각처럼 JSON이 아닌 사용자 자료도 반쪽 파일이 남지 않게 저장한다."""
    _atomic_write_bytes(
        path, str(text).encode(encoding), keep_backup=keep_backup)


def recoverable_remove(path, label="삭제"):
    """사용자 자료를 즉시 지우지 않고 같은 폴더의 목록 밖 백업으로 옮긴다."""
    path = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{label}-{stamp}.bak")
    serial = 2
    while backup.exists():
        backup = path.with_name(
            f"{path.name}.{label}-{stamp}-{serial}.bak")
        serial += 1
    os.replace(path, backup)
    return backup


def load_json_recover(path):
    """주 파일이 잘렸으면 마지막 정상 .bak을 읽고 주 파일도 복구한다."""
    path = Path(path)
    with _JSON_IO_LOCK:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as first:
            bak = path.with_name(path.name + ".bak")
            try:
                data = json.loads(bak.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                raise first
            log.error(f"손상된 {path.name} 대신 백업을 복구했습니다: {first}")
            atomic_write_json(path, data, keep_backup=False)
            return data


def quarantine_corrupt_settings(path, reason):
    """읽을 수 없는 설정과 자동 백업을 삭제하지 않고 복구보관 폴더로 옮긴다.

    두 JSON이 함께 깨지면 예전에는 웹 화면 자체가 뜨지 않았다. 이 함수는 원본 바이트를
    보존한 채 시작만 정상화한다. 권한 오류 같은 JSON 손상 이외의 실패에는 호출하지 않는다.
    """
    path = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    recovery_root = path.parent / "복구보관"
    batch = recovery_root / stamp
    serial = 2
    while batch.exists():
        batch = recovery_root / f"{stamp}-{serial}"
        serial += 1
    batch.mkdir(parents=True, exist_ok=False)
    kept = []
    for source in (path, path.with_name(path.name + ".bak")):
        if not source.is_file():
            continue
        target = batch / source.name
        os.replace(source, target)
        kept.append(target.name)
    notice = {
        "schema": "nais-startup-recovery/v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reason": redact_diagnostic_text(reason),
        "folder": str(batch),
        "files": kept,
    }
    atomic_write_json(batch / "복구기록.json", notice, keep_backup=False)
    return notice

# 체위 목록 (asset_config.json 의 nude 씬을 5장 단위로 그룹핑한 것) — 브라우저 체크박스용
POSITIONS = [{"id": 101, "cat": "A", "label": "A01 핸드잡"}, {"id": 106, "cat": "A", "label": "A02 펠라치오"}, {"id": 111, "cat": "A", "label": "A03 파이즈리"}, {"id": 116, "cat": "A", "label": "A04 69"}, {"id": 121, "cat": "A", "label": "A05 허벅지"}, {"id": 126, "cat": "A", "label": "A06 스탠딩69"}, {"id": 131, "cat": "A", "label": "A07 피드백"}, {"id": 136, "cat": "A", "label": "A08 플레시라이트"}, {"id": 141, "cat": "A", "label": "A09 라잉블로우"}, {"id": 146, "cat": "A", "label": "A10 노스폴"}, {"id": 151, "cat": "A", "label": "A11 너싱핑거링"}, {"id": 156, "cat": "A", "label": "A12 너싱핸드잡"}, {"id": 161, "cat": "A", "label": "A13 온사이드핑거링"}, {"id": 166, "cat": "A", "label": "A14 온사이드핸드잡"}, {"id": 171, "cat": "A", "label": "A15 우로보로스"}, {"id": 176, "cat": "A", "label": "A16 싯앤블로우"}, {"id": 181, "cat": "A", "label": "A17 사우스폴"}, {"id": 186, "cat": "A", "label": "A18 스탠드앤블로우"}, {"id": 191, "cat": "A", "label": "A19 스로트스와빙"}, {"id": 201, "cat": "B", "label": "B01 정상위"}, {"id": 206, "cat": "B", "label": "B02 메이팅 프레스"}, {"id": 211, "cat": "B", "label": "B03 레그락정상위"}, {"id": 216, "cat": "B", "label": "B04 다리어깨"}, {"id": 221, "cat": "B", "label": "B05 테이블"}, {"id": 226, "cat": "B", "label": "B06 데크체어"}, {"id": 231, "cat": "B", "label": "B07 이글"}, {"id": 236, "cat": "B", "label": "B08 가드"}, {"id": 241, "cat": "B", "label": "B09 플랫폼미셔너리"}, {"id": 246, "cat": "B", "label": "B10 리버스앤빌"}, {"id": 251, "cat": "B", "label": "B11 시저드데크체어"}, {"id": 256, "cat": "B", "label": "B12 사이드웨이미셔너리"}, {"id": 261, "cat": "B", "label": "B13 티스퀘어"}, {"id": 266, "cat": "B", "label": "B14 빅토리"}, {"id": 301, "cat": "C", "label": "C01 후배위"}, {"id": 306, "cat": "C", "label": "C02 측위"}, {"id": 311, "cat": "C", "label": "C03 프론본"}, {"id": 316, "cat": "C", "label": "C04 립프로그"}, {"id": 321, "cat": "C", "label": "C05 크라우칭타이거"}, {"id": 326, "cat": "C", "label": "C06 백파이프"}, {"id": 331, "cat": "C", "label": "C07 벤트스푼"}, {"id": 336, "cat": "C", "label": "C08 댕글링도기"}, {"id": 341, "cat": "C", "label": "C09 자키"}, {"id": 346, "cat": "C", "label": "C10 라잉버틀러"}, {"id": 351, "cat": "C", "label": "C11 머메이드"}, {"id": 356, "cat": "C", "label": "C12 마운팅"}, {"id": 361, "cat": "C", "label": "C13 사이드바이사이드"}, {"id": 366, "cat": "C", "label": "C14 스피드범프"}, {"id": 371, "cat": "C", "label": "C15 트라이앵글"}, {"id": 376, "cat": "C", "label": "C16 트위스티드스푼"}, {"id": 401, "cat": "D", "label": "D01 기승위"}, {"id": 406, "cat": "D", "label": "D02 역기승위"}, {"id": 411, "cat": "D", "label": "D03 아마존"}, {"id": 416, "cat": "D", "label": "D04 마스터리"}, {"id": 421, "cat": "D", "label": "D05 리버스아마존"}, {"id": 426, "cat": "D", "label": "D06 리버스메이팅프레스"}, {"id": 431, "cat": "D", "label": "D07 리버스미셔너리"}, {"id": 436, "cat": "D", "label": "D08 스쿼트"}, {"id": 501, "cat": "E", "label": "E01 대면좌위"}, {"id": 506, "cat": "E", "label": "E02 배면좌위"}, {"id": 511, "cat": "E", "label": "E03 사이드새들"}, {"id": 516, "cat": "E", "label": "E04 바스켓"}, {"id": 521, "cat": "E", "label": "E05 체어"}, {"id": 526, "cat": "E", "label": "E06 크레이들"}, {"id": 531, "cat": "E", "label": "E07 프롬비하인드"}, {"id": 536, "cat": "E", "label": "E08 프롬프론트"}, {"id": 541, "cat": "E", "label": "E09 닐링바디가드"}, {"id": 546, "cat": "E", "label": "E10 퍼칭"}, {"id": 551, "cat": "E", "label": "E11 리클라인드테이블로터스"}, {"id": 556, "cat": "E", "label": "E12 리버스퍼칭"}, {"id": 561, "cat": "E", "label": "E13 리버스세인트"}, {"id": 566, "cat": "E", "label": "E14 리버스테이블로터스"}, {"id": 571, "cat": "E", "label": "E15 세인트"}, {"id": 576, "cat": "E", "label": "E16 시티드캐리"}, {"id": 581, "cat": "E", "label": "E17 시팅테이블로터스"}, {"id": 586, "cat": "E", "label": "E18 스튜던츠"}, {"id": 591, "cat": "E", "label": "E19 테이블로터스"}, {"id": 596, "cat": "E", "label": "E20 트위스티드체어"}, {"id": 601, "cat": "F", "label": "F01 들박"}, {"id": 606, "cat": "F", "label": "F02 역들박"}, {"id": 611, "cat": "F", "label": "F03 풀넬슨"}, {"id": 616, "cat": "F", "label": "F04 스탠딩백"}, {"id": 621, "cat": "F", "label": "F05 스탠딩대면"}, {"id": 626, "cat": "F", "label": "F06 바디가드"}, {"id": 631, "cat": "F", "label": "F07 발레리나"}, {"id": 636, "cat": "F", "label": "F08 브라이덜캐리"}, {"id": 641, "cat": "F", "label": "F09 버틀러"}, {"id": 646, "cat": "F", "label": "F10 케이블카"}, {"id": 651, "cat": "F", "label": "F11 댄서"}, {"id": 656, "cat": "F", "label": "F12 페어리"}, {"id": 661, "cat": "F", "label": "F13 플랫폼캐리"}, {"id": 666, "cat": "F", "label": "F14 플랫폼스탠딩도기"}, {"id": 671, "cat": "F", "label": "F15 프리즌가드"}, {"id": 676, "cat": "F", "label": "F16 리어애드미럴"}, {"id": 681, "cat": "F", "label": "F17 리버스댄서"}, {"id": 686, "cat": "F", "label": "F18 스텝"}, {"id": 691, "cat": "F", "label": "F19 서스펜디드로터스"}, {"id": 701, "cat": "G", "label": "G01 파일드라이버"}, {"id": 706, "cat": "G", "label": "G02 서스펜션브릿지"}, {"id": 711, "cat": "G", "label": "G03 크랩"}, {"id": 716, "cat": "G", "label": "G04 레그글라이더"}, {"id": 721, "cat": "G", "label": "G05 휠배로우"}, {"id": 726, "cat": "G", "label": "G06 잭해머"}, {"id": 731, "cat": "G", "label": "G07 아치"}, {"id": 736, "cat": "G", "label": "G08 플로어브릿지"}, {"id": 741, "cat": "G", "label": "G09 플랫폼레그글라이더"}, {"id": 746, "cat": "G", "label": "G10 리버스잭해머"}, {"id": 751, "cat": "G", "label": "G11 리버스파일드라이버"}, {"id": 756, "cat": "G", "label": "G12 리버스서스펜션브릿지"}, {"id": 761, "cat": "G", "label": "G13 리버스휠배로우"}, {"id": 766, "cat": "G", "label": "G14 시저드레그글라이더"}, {"id": 771, "cat": "G", "label": "G15 스윙잉"}, {"id": 776, "cat": "G", "label": "G16 트라피즈"}, {"id": 781, "cat": "G", "label": "G17 언유주얼"}]
CATEGORY_META = {"A": {"name": "오럴 · 핸드 계열", "sub": "19종"}, "B": {"name": "미셔너리 계열", "sub": "14종"}, "C": {"name": "후배위 계열", "sub": "16종"}, "D": {"name": "기승위 계열", "sub": "8종"}, "E": {"name": "좌위 계열", "sub": "20종"}, "F": {"name": "입위 · 캐리 계열", "sub": "19종"}, "G": {"name": "공중 · 특수 계열", "sub": "17종"}}
LIGHT_PRESET = [101, 106, 111, 116, 121, 201, 211, 216, 301, 306, 311, 401, 406, 501, 506, 616, 621, 626]
EXPR_POSITIONS = [{"id": 0, "label": "기본"}, {"id": 1, "label": "진지"}, {"id": 2, "label": "고민"}, {"id": 3, "label": "호기심"}, {"id": 4, "label": "기록"}, {"id": 5, "label": "두리번"}, {"id": 6, "label": "미소"}, {"id": 7, "label": "웃음"}, {"id": 8, "label": "감탄"}, {"id": 9, "label": "흥분"}, {"id": 10, "label": "유레카"}, {"id": 11, "label": "당황"}, {"id": 12, "label": "부끄러움"}, {"id": 13, "label": "수줍음"}, {"id": 14, "label": "딴청"}, {"id": 15, "label": "엣헴"}, {"id": 16, "label": "놀람"}, {"id": 17, "label": "충격"}, {"id": 18, "label": "멍함"}, {"id": 19, "label": "공포"}, {"id": 20, "label": "긴장"}, {"id": 21, "label": "슬픔"}, {"id": 22, "label": "오열"}, {"id": 23, "label": "좌절"}, {"id": 24, "label": "우울"}, {"id": 25, "label": "체념"}, {"id": 26, "label": "화남"}, {"id": 27, "label": "분노"}, {"id": 28, "label": "삐짐"}, {"id": 29, "label": "경멸"}, {"id": 30, "label": "짜증"}, {"id": 31, "label": "지루함"}, {"id": 32, "label": "피곤"}, {"id": 33, "label": "졸림"}, {"id": 34, "label": "배부름"}, {"id": 35, "label": "취함"}, {"id": 36, "label": "애교"}, {"id": 37, "label": "데헷"}, {"id": 38, "label": "떼쓰기"}, {"id": 39, "label": "유혹"}, {"id": 40, "label": "윙크"}, {"id": 41, "label": "손가락 하트"}, {"id": 42, "label": "팔 하트"}, {"id": 43, "label": "안아줘"}, {"id": 44, "label": "키스"}, {"id": 45, "label": "볼만지기"}]
YURI_POSITIONS = [{"id": 801, "label": "Y01 마주보기", "mood": "가벼움"}, {"id": 802, "label": "Y02 손등터치", "mood": "가벼움"}, {"id": 803, "label": "Y03 손잡기", "mood": "가벼움"}, {"id": 804, "label": "Y04 이마맞대기", "mood": "가벼움"}, {"id": 805, "label": "Y05 볼쓰다듬기", "mood": "가벼움"}, {"id": 806, "label": "Y06 키스", "mood": "가벼움"}, {"id": 807, "label": "Y07 키스심화", "mood": "가벼움"}, {"id": 808, "label": "Y08 프렌치키스", "mood": "가벼움"}, {"id": 809, "label": "Y09 딥키스포옹", "mood": "가벼움"}, {"id": 810, "label": "Y10 귀깨물기", "mood": "가벼움"}, {"id": 811, "label": "Y11 목덜미키스", "mood": "가벼움"}, {"id": 812, "label": "Y12 셔츠벗기기", "mood": "진함"}, {"id": 813, "label": "Y13 옷벗기기", "mood": "진함"}, {"id": 814, "label": "Y14 목키스", "mood": "진함"}, {"id": 815, "label": "Y15 백허그속삭임", "mood": "진함"}, {"id": 816, "label": "Y16 백허그가슴", "mood": "진함"}, {"id": 817, "label": "Y17 상의벗기기", "mood": "진함"}, {"id": 818, "label": "Y18 가슴애무", "mood": "진함"}, {"id": 819, "label": "Y19 가슴빨기", "mood": "진함"}, {"id": 820, "label": "Y20 올라타기", "mood": "진함"}, {"id": 821, "label": "Y21 배키스", "mood": "진함"}, {"id": 822, "label": "Y22 마지막옷", "mood": "진함"}, {"id": 823, "label": "Y23 허벅지키스", "mood": "진함"}, {"id": 824, "label": "Y24 허벅지핥기", "mood": "진함"}, {"id": 825, "label": "Y25 손가락애무", "mood": "진함"}, {"id": 826, "label": "Y26 손가락심화", "mood": "진함"}, {"id": 827, "label": "Y27 커닐링구스", "mood": "진함"}, {"id": 828, "label": "Y28 커닐심화", "mood": "진함"}, {"id": 829, "label": "Y29 관찰", "mood": "진함"}, {"id": 830, "label": "Y30 절정직전", "mood": "진함"}, {"id": 831, "label": "Y31 위치바꾸기", "mood": "진함"}, {"id": 832, "label": "Y32 상호자위", "mood": "진함"}, {"id": 833, "label": "Y33 여성69", "mood": "진함"}, {"id": 834, "label": "Y34 트라이버딤", "mood": "진함"}, {"id": 835, "label": "Y35 손깍지", "mood": "진함"}, {"id": 836, "label": "Y36 트라이버딤심화", "mood": "진함"}, {"id": 837, "label": "Y37 손깍지눈맞춤", "mood": "진함"}, {"id": 838, "label": "Y38 눈맞춤", "mood": "진함"}, {"id": 839, "label": "Y39 동시절정", "mood": "진함"}, {"id": 840, "label": "Y40 사후포옹", "mood": "가벼움"}, {"id": 841, "label": "Y41 가슴베개", "mood": "가벼움"}, {"id": 842, "label": "Y42 얼굴쓰다듬기", "mood": "가벼움"}, {"id": 843, "label": "Y43 이불속", "mood": "가벼움"}, {"id": 844, "label": "Y44 머리쓰다듬기", "mood": "가벼움"}, {"id": 845, "label": "Y45 이불덮기", "mood": "가벼움"}, {"id": 846, "label": "Y46 껴안고잠", "mood": "가벼움"}, {"id": 847, "label": "Y47 잠든손깍지", "mood": "가벼움"}, {"id": 848, "label": "Y48 새벽", "mood": "가벼움"}, {"id": 849, "label": "Y49 이마키스", "mood": "가벼움"}, {"id": 850, "label": "Y50 아침맞이", "mood": "가벼움"}, {"id": 851, "label": "Y51 무릎베개", "mood": "가벼움"}, {"id": 852, "label": "Y52 머리빗기", "mood": "가벼움"}, {"id": 853, "label": "Y53 벽쿵키스", "mood": "가벼움"}, {"id": 854, "label": "Y54 백허그창가", "mood": "가벼움"}, {"id": 855, "label": "Y55 손등키스", "mood": "가벼움"}, {"id": 856, "label": "Y56 볼키스", "mood": "가벼움"}, {"id": 857, "label": "Y57 무릎앉기", "mood": "가벼움"}, {"id": 858, "label": "Y58 간지럽히기", "mood": "가벼움"}, {"id": 859, "label": "Y59 춤추기", "mood": "가벼움"}, {"id": 860, "label": "Y60 이불김밥", "mood": "가벼움"}, {"id": 861, "label": "Y61 가슴맞대기", "mood": "진함"}, {"id": 862, "label": "Y62 스푼손가락", "mood": "진함"}, {"id": 863, "label": "Y63 뒤에서가슴", "mood": "진함"}, {"id": 864, "label": "Y64 허벅지그라인딩", "mood": "진함"}, {"id": 865, "label": "Y65 페이스시팅", "mood": "진함"}, {"id": 866, "label": "Y66 페이스시팅절정", "mood": "진함"}, {"id": 867, "label": "Y67 서서커닐", "mood": "진함"}, {"id": 868, "label": "Y68 기승손가락", "mood": "진함"}, {"id": 869, "label": "Y69 측면트라이버딤", "mood": "진함"}, {"id": 870, "label": "Y70 스트랩온장착", "mood": "진함"}, {"id": 871, "label": "Y71 스트랩온정상위", "mood": "진함"}, {"id": 872, "label": "Y72 스트랩온후배위", "mood": "진함"}, {"id": 873, "label": "Y73 스트랩온절정", "mood": "진함"}, {"id": 874, "label": "Y74 마무리트라이버딤", "mood": "진함"}, {"id": 875, "label": "Y75 여운쓰다듬기", "mood": "진함"}]

DEFAULT_CONFIG = {
    "token": "",
    "seed": 1,                # 배치 회차 번호 (시드 1·2·3…)
    "nai_seed": 0,            # NAI 시드 고정 (0이면 매 장 랜덤)
    "base_prompt": "",       # 그림체
    "negative_prompt": "",
    "male_prompt": "",        # (레거시 — 세팅 파일 상대역으로 1회 이전됨)
    "cfg_scale": 5.5,
    "cfg_rescale": 0.56,
    "steps": 28,
    "sampler": "k_euler_ancestral",
    "scheduler": "karras",
    "variety": False,
    "style_name": "",
    # ── 생성 파라미터 (기본값 = 지금까지의 동작 그대로) ──
    "model": "nai-diffusion-4-5-full",
    "width": 832,             # 단독 생성용. 세팅 씬은 씬별 해상도를 쓴다
    "height": 1216,
    # 4 None = NAI가 네거티브에 아무것도 더하지 않음. 내 네거티브만 그대로 쓴다.
    "uc_preset": 4,           # 0 Heavy · 1 Light · 3 Human Focus · 4 None
    "quality_toggle": False,  # 켜면 선택한 모델의 공식 퀄리티 태그 자동 추가
    "smea": False,
    "smea_dyn": False,
    "dynamic_thresholding": False,
    "uncond_scale": 0.0,
    "controlnet_strength": 1.0,
    "prefer_brownian": True,
    "deliberate_euler_ancestral_bug": False,
    "use_coords": False,
    "legacy_v3_extend": False,
    "characters": [],        # 라이브러리(DB): [{id, name, female, clothed, negative, ...}]
    "character_folders": [],  # [{id, name, parent_id}]
    "vibes": [],             # 바이브 트랜스퍼 [{id,name,enabled,strength,info_extracted}]
    "char_refs": [],         # 캐릭터 레퍼런스 [{id,name,enabled,ref_type,strength,fidelity}]
    "char_centers": [],      # 인물별 화면 위치 [{x,y}] (use_coords 켤 때 쓰임)
    "base_fixed": "", "base_var": "", "base_detail": "",   # 프롬프트 3분할 (켤 때만 씀)
    "pace": {},                 # 밴 예방 (비면 PACE_DEFAULT)
    "save_format": "webp",      # 저장 포맷 (webp | png) — 공홈과 같은 선택
    "save_clean": False,        # 저장할 때 메타를 아예 안 넣기 (공유용)
    "save_max_side": 0,         # 저장할 때 긴 변 줄이기 (0 = 그대로)
    "save_quality": 92,         # WebP 품질
    "per_char_order": True,     # 캐스트가 여럿이면 한 사람씩 몰아서 생성
    "out_dir": "",              # 생성물 저장 폴더 (비면 profile/output)
    "out_by_date": False,       # 켜면 모드 폴더 아래 날짜(YYYY-MM-DD)로 또 나눈다
    "char_slots": [],        # ① 설정의 캐릭터 칸들 (한 그림에 함께 들어갈 인물): [{name, prompt, negative}]
    "setting_state": {},        # 세팅 이름 → {use, selected, opts, cast: [{name, prompt, negative}]}
    "ui": {},                   # 화면 설정 {theme, accent, fs, radius}
}


def migrate_char_slots(cfg):
    """구버전 '켜진 캐릭터 = 각자 주인공' → ① 설정 캐릭터 슬롯으로 1회 이전"""
    if cfg.get("_slots_migrated"):
        return
    if not cfg.get("char_slots"):
        for c in cfg.get("characters", []):
            if c.get("enabled", True) and c.get("female"):
                cfg.setdefault("char_slots", []).append(
                    {"name": c.get("name", ""), "prompt": c.get("female", ""),
                     "negative": c.get("negative", "")})
    cfg["_slots_migrated"] = True


def migrate_legacy_selections(cfg):
    """구 cfg 키(selected_*/테마/남자·파트너 역)를 세팅 구조로 1회 이전"""
    if cfg.get("_settings_migrated"):
        # DEFAULT_CONFIG에 이전용 키가 남아 있어 병합할 때마다 빈 male_prompt가
        # 되살아났다. 화면은 이 폐기 키를 저장하려다 모든 모달에 경고를 띄웠다.
        cfg.pop("male_prompt", None)
        cfg.pop("male_outfit", None)
        return
    ss = cfg.setdefault("setting_state", {})
    if cfg.get("selected_positions") is not None:
        ss.setdefault("남녀 체위", {})["selected"] = cfg.pop("selected_positions", [])
        ss["남녀 체위"].setdefault("opts", {})
        for old, new in (("location_theme", "장소테마"), ("time_of_day", "시간대"),
                         ("expression_arc", "표정진행"), ("male_wear", "남자옷")):
            if cfg.get(old):
                ss["남녀 체위"]["opts"][new] = cfg.pop(old)
            else:
                cfg.pop(old, None)
    if cfg.get("selected_expressions") is not None:
        ss.setdefault("표정", {})["selected"] = cfg.pop("selected_expressions", [])
    if cfg.get("selected_yuri") is not None:
        ss.setdefault("백합", {})["selected"] = cfg.pop("selected_yuri", [])
        ss["백합"].setdefault("opts", {})
        if cfg.get("yuri_undress"):
            ss["백합"]["opts"]["옷진행"] = cfg.pop("yuri_undress")
    # 상대역 → 세팅 파일로
    def put_role(name, role_updates):
        p = setting_path(name)
        if not p:
            return
        try:
            pack = load_json_recover(p)
            role = pack.setdefault("상대역", {})
            for k, v in role_updates.items():
                if v and not role.get(k):
                    role[k] = v
            atomic_write_json(p, pack)
        except Exception as e:
            log.warning(f"상대역 이전 실패({name}): {e}")
    legacy_male = cfg.pop("male_prompt", "")
    legacy_male_outfit = cfg.pop("male_outfit", "")
    if legacy_male:
        put_role("남녀 체위", {"외형": legacy_male,
                              "의상": legacy_male_outfit})
    if cfg.get("partner_prompt"):
        put_role("백합", {"외형": cfg.pop("partner_prompt", ""),
                         "착의": cfg.pop("partner_clothed", ""),
                         "네거티브": cfg.pop("partner_negative", "")})
    cfg.pop("pack_pos", None); cfg.pop("pack_expr", None); cfg.pop("pack_yuri", None)
    cfg["_settings_migrated"] = True

# ── 장소 테마 (카테고리 A~G별 배경. 시간 표현은 시간대에서 결합) ──
LOCATION_THEMES = {
    "호텔": {"A": "luxury hotel room, bedside, carpet", "B": "luxury hotel room, on hotel bed, white sheets, large window", "C": "luxury hotel room, on hotel bed, white sheets, large window", "D": "luxury hotel room, on hotel bed, white sheets, large window", "E": "luxury hotel suite, on sofa, large window", "F": "luxury hotel room, against wall, floor-to-ceiling window", "G": "luxury hotel room, spacious floor, soft carpet"},
    "온천여관": {"A": "japanese ryokan room, tatami, futon, warm lantern light", "B": "japanese ryokan room, on futon, tatami, warm lantern light, shoji", "C": "japanese ryokan room, on futon, tatami, warm lantern light, shoji", "D": "japanese ryokan room, on futon, tatami, warm lantern light", "E": "japanese ryokan room, tatami, low table, warm lantern light", "F": "onsen, outdoor bath, steam, stone floor, lanterns, wet", "G": "japanese ryokan room, tatami, futon, warm lantern light"},
    "저택": {"A": "luxury mansion bedroom, bedside, carpet, candlelight", "B": "luxury mansion bedroom, canopy bed, silk sheets, candlelight", "C": "luxury mansion bedroom, canopy bed, silk sheets, candlelight", "D": "luxury mansion bedroom, canopy bed, silk sheets, candlelight", "E": "mansion study, leather sofa, fireplace lighting, bookshelf", "F": "mansion hallway, against wall, tall window", "G": "mansion floor, fireplace lighting, luxurious rug"},
    "원룸": {"A": "small apartment room, bedside, dim lamp light", "B": "small apartment, on bed, messy sheets, dim lamp light, window", "C": "small apartment, on bed, messy sheets, dim lamp light", "D": "small apartment, on bed, messy sheets, dim lamp light", "E": "small apartment, on couch, tv light", "F": "small apartment, against wall, dim lamp light", "G": "small apartment floor, rug, dim lamp light"},
    "사무실": {"A": "office, desk lamp, window blinds", "B": "office, lying on office desk, scattered papers, desk lamp", "C": "office, lying on office desk, scattered papers, desk lamp", "D": "office chair, window blinds", "E": "office chair, window blinds, desk lamp", "F": "office, against glass window, city view", "G": "office floor, carpet, desk lamp"},
    "야외": {"A": "forest clearing, grass", "B": "on blanket, forest clearing, fireflies", "C": "on blanket, forest clearing, fireflies", "D": "on blanket, grass field", "E": "sitting on blanket, forest clearing", "F": "against tree, forest", "G": "grass field, flowers"},
    "해변": {"A": "beach, sand, beach mat", "B": "lying on beach mat, sand, ocean, waves", "C": "lying on beach mat, sand, ocean, waves", "D": "on beach mat, sand, ocean", "E": "sitting on beach mat, sand, ocean", "F": "standing in shallow water, ocean, wet", "G": "sand, beach, ocean"},
    "욕실": {"A": "bathroom, tiles, steam, wet", "B": "large bathtub, water, steam, wet", "C": "bathroom floor, wet tiles, steam", "D": "in bathtub, water, steam, wet", "E": "bathtub edge, steam, wet", "F": "bathroom, against tile wall, shower, water stream, wet", "G": "bathroom floor, wet tiles, steam"},
    "판타지성": {"A": "fantasy castle chamber, stone walls, candlelight", "B": "fantasy castle bedroom, canopy bed, torchlight, stone walls", "C": "fantasy castle bedroom, canopy bed, torchlight, stone walls", "D": "fantasy castle bedroom, canopy bed, torchlight", "E": "fantasy throne room, on throne, torchlight", "F": "castle corridor, against stone wall, torchlight", "G": "castle chamber, fur rug, candlelight"},
    "러브호텔": {"A": "love hotel room, neon mood lighting, bedside", "B": "love hotel, heart-shaped bed, pink sheets, neon mood lighting, mirror ceiling", "C": "love hotel, heart-shaped bed, pink sheets, neon mood lighting, mirror ceiling", "D": "love hotel, heart-shaped bed, pink sheets, neon mood lighting", "E": "love hotel, sofa, neon mood lighting", "F": "love hotel, against mirror wall, neon mood lighting", "G": "love hotel floor, carpet, neon mood lighting"},
}
TIME_TAGS = {
    "아침": "morning, soft sunlight, sunlight through window",
    "낮": "daytime, bright sunlight",
    "노을": "sunset, dusk, golden hour lighting, orange light",
    "밤": "night, dim warm lighting",
}
EXP_PRESETS = {
    "참교육": ["seductive smile, smug, half-closed eyes, licking lips, eye contact, looking at viewer", "smug, smirk, teasing smile, half-closed eyes, light blush, eye contact", "wavy mouth, trembling, sweat, heavy blush, tearing up, forced smile", "ahegao, rolling eyes, stick out tongue, heart shaped pupils, crying, streaming tears, heavy blush", "dazed, exhausted, teary eyes, drooling, twitching, heavy breathing"],
    "수줍음": ["embarrassed, shy, averting eyes, biting lip, deep blush", "embarrassed, blush, looking away, covering own face, trembling", "tearful, trembling, heavy blush, hand over own mouth, wavy mouth", "crying, tightly closed eyes, tears, open mouth, heavy blush", "exhausted, teary eyes, embarrassed smile, heavy breathing, blush"],
    "도발": ["seductive smile, smug, half-closed eyes, licking lips, eye contact, looking at viewer", "smirk, teasing smile, eye contact, half-closed eyes, light blush", "confident smile, sweat, blush, half-closed eyes, eye contact", "grin, heart shaped pupils, eye contact, blush, open mouth", "satisfied smug smile, licking lips, half-closed eyes, heavy breathing"],
    "순애": ["loving gaze, gentle smile, blush, eye contact", "happy, smile, blush, eye contact, trembling", "happy, deep blush, trembling, half-closed eyes, smile", "happy tears, smile, heart shaped pupils, deep blush", "satisfied smile, teary eyes, heavy breathing, blush"],
}
UNDRESS_STAGES = {
    1: "open clothes, unbuttoned, clothes pull",
    2: "underwear only, bra, panties",
    3: "topless",
}

# ══ 생성 옵션 데이터화: 옵션.json (테마/시간/표정진행/탈의단계 — 내용을 마음대로 수정·추가) ══
OPTIONS_FILE = BASE_DIR / "옵션.json"
DEFAULT_OPTIONS = {
    "_설명": "생성 옵션의 실제 내용입니다. 항목 추가/삭제/수정 자유 — UI 선택지에 바로 반영됩니다. UI의 [옵션 내용 편집]에서도 고칠 수 있습니다.",
    "장소테마": LOCATION_THEMES,
    "시간대": TIME_TAGS,
    "표정진행": EXP_PRESETS,
    "탈의단계": {"1": UNDRESS_STAGES[1], "2": UNDRESS_STAGES[2], "3": UNDRESS_STAGES[3]},
}


def load_options():
    if OPTIONS_FILE.exists():
        try:
            data = load_json_recover(OPTIONS_FILE)
            if isinstance(data, dict):
                return data
        except Exception as e:
            log.warning(f"옵션.json 손상 — 기본 옵션 사용: {e}")
        return json.loads(json.dumps(DEFAULT_OPTIONS))
    # 본체와 자료를 분리한 빈 배포에서는 파일을 자동으로 만들지 않는다.
    # 기본값은 코드에서 쓸 수 있고, 사용자가 편집하거나 자료팩을 넣을 때만 생긴다.
    return json.loads(json.dumps(DEFAULT_OPTIONS))


OPTIONS = load_options()

# ══ 씬 프리셋: 현재 선택(체위/표정/백합/옵션) 조합을 이름 붙여 저장 ══
SCENESET_DIR = BASE_DIR / "씬프리셋"
SCENESET_KEYS = ("setting_state",)


def list_scene_presets():
    presets = []
    if not SCENESET_DIR.exists():
        return presets
    for p in sorted(SCENESET_DIR.glob("*.json")):
        try:
            data = load_json_recover(p)
            if isinstance(data, dict):
                presets.append({"name": p.stem, "data": data})
        except Exception:
            continue
    return presets


# ══ 레시피 라이브러리 (수집/레시피.json — 도랑위키 등에서 모은 남들의 조합) ══
RECIPE_FILE = BASE_DIR / "수집" / "레시피.json"
_RECIPES = {"loaded": False, "rows": []}


def load_recipes():
    if _RECIPES["loaded"]:
        return _RECIPES["rows"]
    rows = []
    if RECIPE_FILE.exists():
        try:
            rows = load_json_recover(RECIPE_FILE)
            log.info(f"레시피 라이브러리 로드: {len(rows):,}건")
        except Exception as e:
            log.warning(f"레시피 로드 실패: {e}")
    _RECIPES.update({"loaded": True, "rows": rows})
    return rows


def search_recipes(q="", axis="", limit=60, offset=0):
    rows = load_recipes()
    q = (q or "").strip().lower()
    hit = []
    for r in rows:
        if axis and r.get("axis") != axis:
            continue
        if q:
            hay = (r.get("title", "") + " " + r.get("concept_ko", "") + " " +
                   " ".join(r.get("tags", [])) + " " + r.get("positive", "")).lower()
            if q not in hay:
                continue
        hit.append(r)
    axes = {}
    for r in rows:
        axes[r.get("axis", "?")] = axes.get(r.get("axis", "?"), 0) + 1
    return {"total": len(rows), "matched": len(hit), "axes": axes,
            "items": hit[offset:offset + limit], "offset": offset}



# ══════════════════════════════════════════════════════════════════════
#  NAI 메타데이터 추출 — novelai.net/inspect 가 하는 일을 로컬에서
#  PNG tEXt/zTXt/iTXt + 스텔스(알파 채널 LSB) + WebP EXIF.
#  아카 이미지는 업로드 과정에서 텍스트 청크가 지워지는 경우가 많아
#  (표본 150장 중 111장) 스텔스 판독이 필수다. Pillow 없이도 동작한다.
# ══════════════════════════════════════════════════════════════════════
# `1.2::artist:foo74::` 처럼 숫자로 끝나는 태그가 `::`에 붙으면 NAI가 가중치로 오해한다.
# 닫는 `::` 앞에 공백을 넣어 원래 의도대로 읽히게 정규화한다.
_W_GROUP = re.compile(r"([+-]?\d+(?:\.\d+)?)::([\s\S]*?)::")
_ARTIST_CLOSER = re.compile(r"(artist\s*:[^,\n]*?\d)\s*::", re.I)

# `#` 로 **시작하는 줄**은 메모다 — 전송·미리보기·토큰 계산에서 뺀다
# (NAIS3-Custom 의 프롬프트 주석 참고). 줄 중간의 # 는 건드리지 않는다.
_COMMENT_LINE = re.compile(r"^[ \t]*#[^\n]*\n?", re.M)


def strip_comment_lines(text):
    t = str(text or "")
    return _COMMENT_LINE.sub("", t) if "#" in t else t


def normalize_prompt(prompt):
    prompt = strip_comment_lines(prompt)   # 주석 줄은 애초에 프롬프트가 아니다
    def fix(m):
        body = m.group(2).rstrip()
        if body[-1:].isdigit():
            body += " "
        return f"{m.group(1)}::{body}::"
    return _ARTIST_CLOSER.sub(lambda m: f"{m.group(1)} ::", _W_GROUP.sub(fix, str(prompt or "")))

GENERATION_KEYS = {"seed", "sampler", "steps", "scale", "noise_schedule",
                   "model", "width", "height"}
TEXT_KEYS = {"comment", "description", "software", "source", "parameters", "prompt", "uc"}


# ────────────────────────── PNG: 텍스트 청크 ──────────────────────────
def png_text_chunks(data):
    """tEXt / zTXt / iTXt 청크를 {키: 값} 으로."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {}
    pos, out = 8, {}
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if kind == b"tEXt":
                k, v = payload.split(b"\0", 1)
                out[k.decode("latin1")] = v.decode("utf-8", "replace")
            elif kind == b"zTXt":
                k, rest = payload.split(b"\0", 1)
                out[k.decode("latin1")] = zlib.decompress(rest[1:]).decode("utf-8", "replace")
            elif kind == b"iTXt":
                k, rest = payload.split(b"\0", 1)
                compressed = rest[0]
                rest = rest[2:]
                _, rest = rest.split(b"\0", 1)     # language tag
                _, v = rest.split(b"\0", 1)        # translated keyword
                out[k.decode("latin1")] = (zlib.decompress(v) if compressed else v).decode("utf-8", "replace")
        except (ValueError, IndexError, zlib.error):
            pass
        if kind == b"IEND":
            break
    return out


# ─────────────────── PNG: 알파 채널만 뽑는 최소 디코더 ───────────────────
def _alpha_via_pillow(data):
    """Pillow가 있으면 알파 추출을 맡긴다 (순수 파이썬 디코더보다 10배 이상 빠름)."""
    try:
        import io
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.mode != "RGBA":
                return None
            return im.size[0], im.size[1], im.getchannel("A").tobytes()
    except Exception:
        return None


def _png_alpha_channel(data):
    """비인터레이스 RGBA/GA 8·16비트 PNG에서 (width, height, alpha bytes) 반환.
    Pillow 없이 스텔스 정보를 읽기 위한 최소 구현."""
    fast = _alpha_via_pillow(data)
    if fast:
        return fast
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, ihdr = 8, [], None
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat.append(payload)
        elif kind == b"IEND":
            break
    if not ihdr or not idat:
        return None
    width, height, depth, color, comp, filt, interlace = ihdr
    # 알파가 있는 형식만 (4=회색+알파, 6=트루컬러+알파)
    if color not in (4, 6) or depth not in (8, 16) or comp or filt or interlace:
        return None
    channels = 2 if color == 4 else 4
    bpp = channels * depth // 8               # 픽셀당 바이트
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    if len(raw) < height * (stride + 1):
        return None

    prev = bytearray(stride)
    alpha = bytearray(width * height)
    step = depth // 8
    off = 0
    for y in range(height):
        ftype = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        if ftype == 1:                                  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:                                # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:                                # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:                                # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            return None
        # 알파는 픽셀의 마지막 채널 — 16비트면 상위 바이트만 쓰면 되지만
        # 스텔스는 8비트 저장이므로 최하위 바이트를 취한다.
        base = (channels - 1) * step + (step - 1)
        row = y * width
        for x in range(width):
            alpha[row + x] = line[x * bpp + base]
        prev = line
    return width, height, bytes(alpha)


def read_stealth_info(data, alpha=None):
    """알파 채널 LSB에 숨겨진 stealth_pnginfo / stealth_pngcomp 페이로드."""
    if alpha is None:
        alpha = _png_alpha_channel(data)
    if not alpha:
        return None
    width, height, buf = alpha

    def bit(i):
        x, y = divmod(i, height)
        if x >= width:
            raise ValueError("stealth payload exceeds image bounds")
        return str(buf[y * width + x] & 1)

    try:
        sig_bits = "".join(bit(i) for i in range(120))
        sig = bytes(int(sig_bits[i:i + 8], 2) for i in range(0, 120, 8)).decode("utf-8", "ignore")
        if sig not in {"stealth_pngcomp", "stealth_pnginfo"}:
            return None
        n = int("".join(bit(i) for i in range(120, 152)), 2)
        if n <= 0 or n % 8 or 152 + n > width * height:
            return None
        bits = "".join(bit(i) for i in range(152, 152 + n))
        payload = bytes(int(bits[i:i + 8], 2) for i in range(0, n, 8))
        if sig == "stealth_pngcomp":
            payload = gzip.decompress(payload)
        return payload.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError, zlib.error):
        return None


# ───────────────────────── 값 병합 / 파싱 ─────────────────────────
def _merge(values, raw, allow_plain_prompt=True):
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            by = {str(k).casefold(): v for k, v in parsed.items()}
            comment = by.get("comment")
            if isinstance(comment, str):
                try:
                    nested = json.loads(comment)
                    if isinstance(nested, dict):
                        parsed = nested
                except json.JSONDecodeError:
                    pass
            desc = str(by.get("description") or "").strip()
            src = str(by.get("source") or "").strip()
            soft = str(by.get("software") or "").strip()
            if desc:
                parsed.setdefault("prompt", desc)
            if src:
                parsed.setdefault("source", src)
                if src.casefold().startswith("novelai diffusion"):
                    parsed.setdefault("model", src)
            if soft:
                parsed.setdefault("software", soft)
            values.update(parsed)
            return
    except (json.JSONDecodeError, TypeError):
        pass
    text = str(raw).split("Negative prompt:", 1)[0].strip()
    if allow_plain_prompt and text:
        values.setdefault("prompt", text)


def _webp_values(data):
    """WebP는 Pillow가 있어야 EXIF를 읽을 수 있다. 없으면 빈 dict."""
    try:
        import io
        from PIL import Image
    except ImportError:
        return {}
    values = {}
    try:
        with Image.open(io.BytesIO(data)) as im:
            if str(im.format or "").upper() != "WEBP":
                return {}
            by = {str(k).casefold(): v for k, v in im.info.items()}
            for key in ("parameters", "comment", "description", "prompt", "uc"):
                raw = by.get(key)
                if raw in (None, b"", ""):
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "ignore")
                if key == "uc":
                    values.setdefault("uc", str(raw))
                else:
                    _merge(values, raw)
            exif = im.getexif() if hasattr(im, "getexif") else None
            if not exif:
                return values
            uc = exif.get(37510)
            if uc in (None, b"", "") and hasattr(exif, "get_ifd"):
                try:
                    uc = exif.get_ifd(34665).get(37510)
                except (KeyError, TypeError, ValueError):
                    uc = None
            if uc not in (None, b"", ""):
                if isinstance(uc, bytes):
                    if uc.startswith(b"UNICODE\x00"):
                        for enc in ("utf-16-be", "utf-16-le", "utf-16"):
                            try:
                                uc = uc[8:].decode(enc); break
                            except UnicodeDecodeError:
                                continue
                        else:
                            uc = uc[8:].decode("utf-8", "ignore")
                    elif uc.startswith(b"ASCII\x00\x00\x00"):
                        uc = uc[8:].decode("utf-8", "ignore")
                    else:
                        uc = uc.decode("utf-8", "ignore")
                uc = str(uc).replace("\x00", "").strip()
                if uc:
                    _merge(values, uc)
            for tag, key in ((270, None), (305, "software")):
                v = exif.get(tag)
                if v in (None, b"", ""):
                    continue
                if isinstance(v, bytes):
                    v = v.decode("utf-8", "ignore")
                if key:
                    values.setdefault(key, str(v).strip())
                else:
                    _merge(values, v)
    except Exception:
        return {}
    return values


def _is_nai(values):
    if not isinstance(values, dict):
        return False
    if isinstance(values.get("v4_prompt"), dict):
        return True
    soft = str(values.get("software") or "").casefold()
    src = str(values.get("source") or "").casefold()
    if values.get("prompt") and (soft.startswith("novelai") or src.startswith("novelai diffusion")):
        return True
    return bool(values.get("prompt")) and len(GENERATION_KEYS & set(values)) >= 2


def _prompt_parts(values):
    v4 = values.get("v4_prompt") if isinstance(values.get("v4_prompt"), dict) else {}
    cap = v4.get("caption") if isinstance(v4.get("caption"), dict) else {}
    base = normalize_prompt(cap.get("base_caption") or values.get("prompt")
                            or values.get("prompts") or "")
    chars = []
    for e in (cap.get("char_captions") or []) if isinstance(cap.get("char_captions"), list) else []:
        if isinstance(e, dict) and e.get("char_caption"):
            chars.append({"prompt": normalize_prompt(e["char_caption"]),
                          "negative": "",
                          "centers": e.get("centers") if isinstance(e.get("centers"), list) else []})
    v4n = values.get("v4_negative_prompt") if isinstance(values.get("v4_negative_prompt"), dict) else {}
    ncap = v4n.get("caption") if isinstance(v4n.get("caption"), dict) else {}
    neg_chars = (ncap.get("char_captions") or []) if isinstance(
        ncap.get("char_captions"), list) else []
    # 캐릭터 1·2는 세부 태그로 다시 쪼개지 않고, 메타데이터에 든 각 캐릭터의
    # 전체 프롬프트와 전용 네거티브를 같은 순서로 그대로 묶어 둔다.
    for i, e in enumerate(neg_chars):
        if not isinstance(e, dict):
            continue
        while len(chars) <= i:
            chars.append({"prompt": "", "negative": "", "centers": []})
        chars[i]["negative"] = normalize_prompt(e.get("char_caption") or "")
    neg = normalize_prompt(ncap.get("base_caption") or values.get("uc")
                           or values.get("negative_prompt")
                           or values.get("undesired_content") or "")
    return str(base), str(neg), chars


PARAM_KEYS = ("seed", "sampler", "steps", "scale", "cfg_rescale", "noise_schedule",
              "width", "height", "uncond_scale", "dynamic_thresholding",
              "controlnet_strength", "deliberate_euler_ancestral_bug",
              "prefer_brownian", "skip_cfg_above_sigma", "sm", "sm_dyn")


def extract_nai_metadata(data, content_type=""):
    out = {"metadata_status": "no_metadata", "base": "", "negative": "",
           "characters": [], "params": {}, "raw": {}}
    if not isinstance(data, (bytes, bytearray)) or len(data) < 12:
        return out
    data = bytes(data)
    ct = (content_type or "").lower()
    is_png = data.startswith(b"\x89PNG") or "png" in ct
    is_webp = (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or "webp" in ct
    if not (is_png or is_webp):
        return out

    values = _webp_values(data) if is_webp else {}
    if is_png:
        for key, raw in png_text_chunks(data).items():
            k = key.lower()
            if k not in TEXT_KEYS:
                continue
            if k == "uc":
                values["uc"] = raw
            elif k == "source":
                s = str(raw or "").strip()
                if s:
                    values.setdefault("source", s)
                    if s.casefold().startswith("novelai diffusion"):
                        values.setdefault("model", s)
            else:
                _merge(values, raw, allow_plain_prompt=k not in {"software", "source"})
        if not _is_nai(values):                       # 텍스트 청크가 지워졌으면 스텔스
            stealth = read_stealth_info(data)
            if stealth:
                _merge(values, stealth)

    if not _is_nai(values):
        return out
    base, neg, chars = _prompt_parts(values)
    if not base and not neg:
        return out

    params = {k: values[k] for k in PARAM_KEYS if values.get(k) is not None}
    if "seed" in params:
        params["seed"] = str(params["seed"])
    if "skip_cfg_above_sigma" in values:
        params["variety_plus"] = bool(values.get("skip_cfg_above_sigma"))
    if values.get("ucPreset") is not None:
        try:
            params["uc_preset"] = int(values["ucPreset"])
        except (TypeError, ValueError):
            pass
    if values.get("qualityToggle") is not None:
        params["quality_toggle"] = bool(values["qualityToggle"])
    model = values.get("model") or values.get("source") or ""
    if model:
        params["model"] = str(model)
    out.update({"metadata_status": "ok", "base": base, "negative": neg,
                "characters": chars, "params": params, "raw": values})
    return out


IMG_CACHE = BASE_DIR / "수집" / "이미지캐시"


# ══════════════════════════════════════════════════════════════════════
#  NAI V4/V4.5 토큰 수 — T5 Unigram + Viterbi (의존성 없음)
#  NAI 는 프롬프트를 T5 인코더에 넣는다. 정확한 토큰 수를 알려면 NAI 가 쓰는
#  같은 vocab(t5_tokenizer.json, 32,100개)으로 같은 방식으로 쪼개야 한다.
#  가중치 표기(`1.4::` `::`)와 {}[] 강조는 NAI 가 파싱해서 걷어내므로 세지 않는다.
#  → 태그 텍스트 506개 표본에서 표준 구현과 100% 일치 확인.
# ══════════════════════════════════════════════════════════════════════
METASPACE = "▁"
_STATE = {"loaded": False, "vocab": {}, "maxlen": 1, "unk": -1e3}

# 가중치·강조 표기 제거 (텍스트가 아니라 문법이므로 토큰에 안 들어간다)
_WEIGHT = re.compile(r"[+-]?\d*\.?\d+\s*::|::")
_BRACKET = re.compile(r"[{}\[\]]")


def load_vocab(path):
    if _STATE["loaded"]:
        return _STATE
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        pieces = d["model"]["vocab"]
        vocab = {}
        maxlen = 1
        for item in pieces:
            piece, score = item[0], float(item[1])
            vocab[piece] = score
            if len(piece) > maxlen:
                maxlen = len(piece)
        # unk 점수: 가장 낮은 점수보다 더 낮게 (모르는 글자 1개 = 1토큰)
        worst = min(vocab.values()) if vocab else -20.0
        _STATE.update(loaded=True, vocab=vocab, maxlen=min(maxlen, 32),
                      unk=worst - 10.0)
    except Exception:
        _STATE["loaded"] = True          # 실패해도 다시 시도하지 않음
    return _STATE


def _viterbi(piece):
    """한 조각을 vocab 조각들로 나눌 때 로그확률 합이 최대가 되는 분할의 개수"""
    vocab = _STATE["vocab"]
    if not vocab:
        return max(1, len(piece) // 4)   # vocab 없으면 대략치
    n = len(piece)
    best = [(-1e18, 0)] * (n + 1)        # (점수, 토큰수)
    best[0] = (0.0, 0)
    maxlen = _STATE["maxlen"]
    unk = _STATE["unk"]
    for i in range(1, n + 1):
        top = (-1e18, 0)
        lo = max(0, i - maxlen)
        for j in range(lo, i):
            prev = best[j]
            if prev[0] <= -1e17:
                continue
            sub = piece[j:i]
            sc = vocab.get(sub)
            if sc is None:
                # 표준 Unigram 과 같이 미등록 구간은 글자 하나씩 <unk> 로 센다.
                # (길이 무제한으로 묶으면 긴 미등록 구간이 1토큰이 되어 크게 어긋난다)
                if i - j != 1:
                    continue
                sc = unk
            cand = (prev[0] + sc, prev[1] + 1)
            if cand[0] > top[0]:
                top = cand
        best[i] = top
    return best[n][1] if best[n][0] > -1e17 else max(1, n)


def count_tokens(text, vocab_path=None):
    """프롬프트의 NAI 토큰 수 (</s> 포함)"""
    if vocab_path:
        load_vocab(vocab_path)
    t = _BRACKET.sub("", _WEIGHT.sub(" ", str(text or "")))
    total = 0
    for piece in t.split():
        total += _viterbi(METASPACE + piece)
    return total + 1                     # </s>


TOKENIZER_FILE = PROGRAM_DIR / "t5_tokenizer.json"


# ══════════════════════════════════════════════════════════════════════
#  Anlas 비용 — NAIS3 src/shared/anlas.ts 의 공식 그대로
#  Opus 무료 생성 조건: 1024² 이하 · 28스텝 이하 · 베이스 이미지 없음.
#  캐릭터 레퍼런스는 무료 생성을 깨지 않고 참조 1개당 장당 5 Anlas만 별도 과금된다.
# ══════════════════════════════════════════════════════════════════════
ANLAS_A = 2.951823174884865e-6
ANLAS_B = 5.753298233447344e-7
OPUS_FREE_PX = 1024 * 1024
OPUS_FREE_STEPS = 28


def anlas_per_image(width, height, steps, strength=1.0, char_refs=0):
    px = max(int(width) * int(height), 65536)
    base = math.ceil((ANLAS_A * px + ANLAS_B * px * int(steps)) * float(strength))
    return max(base, 2) + 5 * int(char_refs)


def anlas_estimate(cfg, count=1, width=None, height=None, opus=False, char_refs=0,
                   mode="t2i", strength=1.0):
    """장당·총액과 무료 여부. count=한 회차에 뽑을 장수.
    mode: t2i | img2img | infill — **베이스 이미지를 쓰면 Opus 무료가 아니다**
    (공식 조건: 한 번에 1장 · 베이스 이미지 미사용 · 1024² 이하 · 28스텝 이하). CQA-008"""
    w = int(width or cfg.get("width", 832))
    h = int(height or cfg.get("height", 1216))
    steps = int(cfg.get("steps", 28))
    px = max(w * h, 65536)
    uses_base = mode in ("img2img", "infill")
    free_eligible = (px <= OPUS_FREE_PX
                     and steps <= OPUS_FREE_STEPS and not uses_base)
    generation_free = bool(opus) and free_eligible
    base_per = anlas_per_image(
        w, h, steps, strength if uses_base else 1.0, char_refs=0)
    ref_fee = 5 * max(int(char_refs), 0)
    per = (0 if generation_free else base_per) + ref_fee
    total_free = per == 0
    if generation_free and ref_fee:
        why = (f"Opus 무료 생성 + 캐릭터 레퍼런스 {int(char_refs)}개 "
               f"장당 {ref_fee} Anlas")
    elif total_free:
        why = "Opus 무료 (1024² 이하 · 28스텝 이하)"
    elif uses_base:
        why = "원본 그림을 쓰는 작업은 Opus 무료가 아닙니다 (img2img·인페인트)"
    elif not opus and px <= OPUS_FREE_PX and steps <= OPUS_FREE_STEPS:
        why = "무료 크기·스텝 범위지만 Opus 적용 여부가 확인되지 않았습니다"
    else:
        why = (f"무료 조건 초과 — {w}×{h}·{steps}스텝 "
               f"(무료는 1024² 이하·28스텝 이하)")
    return {
        "per_image": per,
        "per_image_paid": base_per + ref_fee,
        "total": per * max(int(count), 0),
        "count": int(count),
        "free": total_free,
        "free_eligible": free_eligible,
        "generation_free": generation_free,
        "char_ref_fee": ref_fee,
        "mode": mode,
        "width": w, "height": h, "steps": steps,
        "why": why,
    }


# ══════════════════════════════════════════════════════════════════════
#  바이브 트랜스퍼 / 캐릭터 레퍼런스
#   바이브   : 그림의 '분위기'를 옮긴다. encode-vibe 로 한 번 인코딩(2 Anlas)해
#              캐시해 두면 그 뒤로는 공짜로 계속 쓴다 → 배치 생성에 딱 맞다.
#   캐릭레퍼 : 캐릭터 생김새를 참조한다. 무료 생성은 유지되고 참조당 장당 5 Anlas가 붙는다.
#  (NAIS3 구현과 같은 필드·같은 캐시 무효화 규칙)
# ══════════════════════════════════════════════════════════════════════
ENCODE_VIBE_URL = "https://image.novelai.net/ai/encode-vibe"
VIBE_DIR = BASE_DIR / "수집" / "바이브"
REF_TYPES = [("character&style", "생김새 + 화풍"), ("character", "생김새만"),
             ("style", "화풍만")]


def vibe_paths(vid):
    return VIBE_DIR / f"{vid}.png", VIBE_DIR / f"{vid}.vibe"


def encode_vibe(token, image_bytes, information_extracted=0.7,
                model="nai-diffusion-4-5-full"):
    """그림 → 인코딩된 바이브(base64). 2 Anlas 소모. 결과는 캐시해서 재사용한다."""
    import base64
    b64, _, _ = _b64_png(image_bytes)
    r = requests.post(ENCODE_VIBE_URL, timeout=180, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"image": b64, "information_extracted": float(information_extracted),
              "model": model})
    if r.status_code == 401:
        raise AuthError("401 — 토큰을 확인하세요.")
    if r.status_code == 429:
        raise RateLimitError("429 Too Many Requests")
    if r.status_code != 200:
        raise APIError(f"바이브 인코딩 실패 HTTP {r.status_code}: {r.text[:200]}")
    return base64.b64encode(r.content).decode("ascii")


def prepare_vibes(cfg, token):
    """켜진 바이브들을 준비. 인코딩이 없거나 information_extracted 가 바뀌면 다시 인코딩.
    반환: ([encoded base64...], [strength...], [information_extracted...], 새로 인코딩한 개수)"""
    encoded, strengths, ies, newly = [], [], [], 0
    changed = False
    for v in cfg.get("vibes", []):
        if not v.get("enabled"):
            continue
        img_p, enc_p = vibe_paths(v.get("id", ""))
        ie = float(v.get("info_extracted", 0.7))
        need = (not enc_p.exists()) or abs(float(v.get("encoded_ie", -1)) - ie) > 1e-9
        if need:
            if not img_p.exists():
                log.warning(f"바이브 원본이 없습니다: {img_p.name}")
                continue
            enc = encode_vibe(token, img_p.read_bytes(), ie,
                              cfg.get("model") or "nai-diffusion-4-5-full")
            atomic_write_text(
                enc_p, enc, encoding="ascii", keep_backup=False)
            v["encoded_ie"] = ie
            newly += 1
            changed = True
            log.info(f"바이브 인코딩: {v.get('name')} (정보추출 {ie}) — 2 Anlas")
        encoded.append(enc_p.read_text(encoding="ascii"))
        strengths.append(float(v.get("strength", 0.6)))
        ies.append(ie)
    if changed:
        with shared_data_transaction(VIBE_DIR.parent.parent):
            # 인코딩은 최대 180초가 걸린다. 그 사이 다른 실행본이 저장한 설정을
            # 시작 시점의 cfg 전체로 덮지 않고, 같은 id의 캐시 상태만 최신판에 합친다.
            latest = dict(DEFAULT_CONFIG)
            if SETTINGS_FILE.is_file():
                loaded = load_json_recover(SETTINGS_FILE)
                if isinstance(loaded, dict):
                    latest.update(loaded)
            encoded_ie = {
                item.get("id"): item.get("encoded_ie")
                for item in cfg.get("vibes", [])
                if item.get("id") and item.get("encoded_ie") is not None
            }
            for item in latest.get("vibes", []):
                if item.get("id") in encoded_ie:
                    item["encoded_ie"] = encoded_ie[item.get("id")]
            save_config(latest)      # 캐시 상태를 남겨 다음엔 공짜로 쓴다
    return encoded, strengths, ies, newly


# ★ 캐릭터 레퍼런스 참조 이미지는 **이 세 캔버스 중 하나**여야 한다.
#   다른 크기를 보내면 NAI 가 400 "Error encoding v4 director references" 를 준다.
#   (512·832×1216·1024² 전부 실패했고 이 셋만 통과했다 — 실측)
#   비율을 지켜 넣고 남는 곳은 검게 채운다(레터박스).
CR_CANVAS = ((1024, 1536), (1536, 1024), (1472, 1472))


def _cr_canvas_for(w, h):
    """비율이 가장 가까운 캔버스를 고른다."""
    ar = (w / h) if h else 1.0
    return min(CR_CANVAS, key=lambda c: abs((c[0] / c[1]) - ar))


def letterbox_ref(raw):
    """참조 이미지를 허용 캔버스에 레터박스로 넣어 PNG base64 로."""
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        cw, ch = _cr_canvas_for(im.width, im.height)
        r = min(cw / im.width, ch / im.height)
        nw, nh = max(1, round(im.width * r)), max(1, round(im.height * r))
        out = Image.new("RGB", (cw, ch), (0, 0, 0))
        out.paste(im.resize((nw, nh), Image.LANCZOS), ((cw - nw) // 2, (ch - nh) // 2))
    b = io.BytesIO()
    out.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode("ascii"), (cw, ch)


def prepare_char_refs(cfg):
    """켜진 캐릭터 레퍼런스. 반환: (images b64, types, strengths, fidelities)"""
    imgs, types, strengths, fids = [], [], [], []
    for r in cfg.get("char_refs", []):
        if not r.get("enabled"):
            continue
        p = VIBE_DIR / f"{r.get('id','')}.ref.png"
        if not p.exists():
            continue
        try:
            b64, cv = letterbox_ref(p.read_bytes())
        except Exception as e:
            log.warning(f"캐릭터 레퍼런스 준비 실패({p.name}): {e}")
            continue
        log.info(f"캐릭터 레퍼런스 {p.stem} → {cv[0]}×{cv[1]} 로 맞춤")
        imgs.append(b64)
        types.append(r.get("ref_type") or "character&style")
        strengths.append(float(r.get("strength", 0.6)))
        fids.append(float(r.get("fidelity", 0.6)))
    return imgs, types, strengths, fids


def runtime_generation_params(cfg, token, include_refs=True):
    """현재 설정에서 한 호출에만 쓸 레퍼런스 파라미터를 만든다.

    `_vibes`/`_char_refs`는 영구 설정이 아니라 전송 직전 계산값이다. 공유 cfg에
    남기면 앞 배치의 레퍼런스가 단독·씬·복구 호출로 새므로 항상 제거한 복사본에서
    시작한다. 메타데이터 복구는 원본에 없는 현재 레퍼런스를 덧붙이지 않는다.
    """
    params = dict(cfg or {})
    params.pop("_vibes", None)
    params.pop("_char_refs", None)
    if not include_refs:
        return params
    try:
        encoded, strengths, ies, newly = prepare_vibes(cfg, token)
        images, types, ref_strengths, fidelities = prepare_char_refs(cfg)
        params["_vibes"] = {
            "encoded": encoded,
            "strengths": strengths,
            "ies": ies,
        }
        params["_char_refs"] = {
            "images": images,
            "types": types,
            "strengths": ref_strengths,
            "fidelities": fidelities,
        }
        if newly:
            log.info(f"바이브 {newly}개를 새로 인코딩했습니다.")
    except Exception as e:
        log.warning(f"레퍼런스 준비 실패 — 레퍼런스 없이 계속합니다: {e}")
        params["_vibes"] = {}
        params["_char_refs"] = {}
    return params


# ══════════════════════════════════════════════════════════════════════
#  디렉터 툴 — NAI 가 그림을 다시 손봐 주는 기능
#   augment-image : 배경 제거 · 라인아트 · 스케치 · 색칠 · 표정 변경 · 정리
#   upscale       : 해상도 올리기 (호스트가 다르다)
#  응답은 zip 이고 **마지막 항목**이 결과물이다 (배경 제거는 3장이 들어온다).
# ══════════════════════════════════════════════════════════════════════
AUGMENT_URL = "https://image.novelai.net/ai/augment-image"
UPSCALE_URLS = ("https://api.novelai.net/ai/upscale",
                "https://image.novelai.net/ai/upscale")   # 호스트가 옮겨질 수 있어 둘 다 시도

DIRECTOR_TOOLS = [
    ("bg-removal", "배경 제거", False),
    ("lineart", "라인아트", False),
    ("sketch", "스케치", False),
    ("colorize", "색칠", True),        # prompt·defry 를 받는다
    ("emotion", "표정 변경", True),
    ("declutter", "정리 (말풍선 등 지우기)", False),
]
# 표정 변경에서 쓸 수 있는 감정 (prompt 맨 앞에 붙인다)
EMOTIONS = ["neutral", "happy", "sad", "angry", "scared", "surprised", "tired",
            "excited", "nervous", "thinking", "confused", "shy", "disgusted",
            "smug", "bored", "laughing", "irritated", "aroused", "embarrassed",
            "worried", "love", "determined", "hurt", "playful"]


# ══════════════════════════════════════════════════════════════════════
#  단부루/겔부루 검색 — 태그로 실제 그림을 찾아 태그·그림체를 가져온다
#  NAIS3 는 Electron <webview> 로 사이트를 통째로 띄우지만 우리는 브라우저 앱이라
#  iframe 이 막힌다. 대신 각 사이트의 JSON API 를 서버가 불러 우리 그리드에 그린다.
#  (원본 사이트로 새 창 열기도 함께 제공)
# ══════════════════════════════════════════════════════════════════════
BOORUS = {
    "danbooru": {"name": "단부루", "url": "https://danbooru.donmai.us/posts.json",
                 "page": "https://danbooru.donmai.us/posts"},
    # 겔부루는 2024 년부터 API 키(&api_key=&user_id=)가 없으면 401,
    # e621 은 한국에서 451(지역 차단)이다. 목록에는 남기되 미리 알려 준다.
    "gelbooru": {"name": "겔부루", "note": " (API 키 필요)", "auth": "gel",
                 "url": "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1",
                 "page": "https://gelbooru.com/index.php?page=post&s=list"},
    "e621": {"name": "e621", "note": " (지역 차단)", "auth": "basic",
             "url": "https://e621.net/posts.json",
             "page": "https://e621.net/posts"},
}
BOORUS["danbooru"]["auth"] = "basic"

# 단부루 미러 도메인 — 같은 데이터베이스를 다른 호스트 이름으로 서비스한다.
# 본 도메인이 연결을 끊을 때(반복 호출·ISP·지역) 미러는 대개 응답한다.
#   실측: danbooru 가 ConnectionError 인 상태에서 hijiribe·sonohara 는 HTTP 200.
# ⚠ safebooru 는 전연령만 걸러 보여 주므로 결과가 달라진다 — 마지막에 두고 알려 준다.
# ⚠ 태그 2개 제한은 미러에서도 똑같다(422 TagLimitError). 미러는 차단만 우회한다.
DANBOORU_MIRRORS = ["danbooru.donmai.us", "hijiribe.donmai.us", "sonohara.donmai.us"]
DANBOORU_SFW_MIRROR = "safebooru.donmai.us"

# 부루 계정은 사이트마다 방식이 다르다
#   단부루 · e621 → HTTP Basic (아이디 + API 키). e621 은 User-Agent 도 요구한다.
#   겔부루      → 쿼리 파라미터 (&user_id=&api_key=)
# 넣지 않아도 단부루는 비로그인으로 검색되고, 겔부루만 반드시 필요하다.
BOORU_AUTH_HELP = {
    "danbooru": "danbooru.donmai.us → My Account → API Key. "
                "골드 이상이면 태그 제한이 2개에서 6개로 풀린다.",
    "gelbooru": "gelbooru.com → My Account → Options 맨 아래 API Access Credentials "
                "(user_id 와 api_key 가 함께 나온다).",
    "e621": "e621.net → Account → Manage API Access. 지역 차단이면 키가 있어도 451 이다.",
}


# search_booru 는 모듈 함수라 서버의 cfg 를 못 본다. 저장할 때 여기 심어 둔다.
_BOORU_KEYS = {}


def booru_creds(site):
    """설정에 저장된 부루 계정 (없으면 빈 값). 검색은 1초에 한 번이라 파일을 읽어도 된다."""
    keys = _BOORU_KEYS.get(site)
    if keys is None:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                keys = (json.load(f).get("booru_keys") or {}).get(site) or {}
        except (OSError, ValueError):
            keys = {}
    return str(keys.get("user") or "").strip(), str(keys.get("key") or "").strip()


_BOORU_LAST = [0.0]
_BOORU_LOCK = threading.Lock()


def _booru_throttle(gap=1.0):
    """검색 요청 간 최소 간격. 몰아치면 Cloudflare 가 IP 를 잠시 막는다."""
    with _BOORU_LOCK:
        wait = gap - (time.time() - _BOORU_LAST[0])
        if wait > 0:
            time.sleep(wait)
        _BOORU_LAST[0] = time.time()


def search_booru(site="danbooru", tags="", page=1, limit=40):
    """태그로 검색해 [{id,tags,thumb,full,url,rating,score}] 반환."""
    cfg = BOORUS.get(site) or BOORUS["danbooru"]
    # 태그는 **공백으로 구분**한다. 공백을 _ 로 바꾸면 태그 하나로 뭉쳐 0건이 된다.
    # 태그 안의 공백은 사용자가 _ 로 적어 넣는다 (단부루 표기 그대로).
    # 우리 그림체 데이터는 `artist:wanke` 형태인데 단부루 검색은 태그 이름만 받는다.
    # 그대로 붙여넣어도 찾아지도록 접두사를 떼어 준다.
    parts = [re.sub(r"^artists?:", "", t, flags=re.I).replace(" ", "_")
             for t in (tags or "").split() if t]
    # 단부루는 비로그인 검색이 태그 2개까지다 (초과하면 422 TagLimitError).
    note = ""
    if site == "danbooru" and len(parts) > 2:
        # 비로그인 2개 · 로그인(골드 이상) 6개. 키를 넣어 두면 6개까지 보내 본다.
        cap = 6 if all(booru_creds("danbooru")) else 2
        if len(parts) > cap:
            note = (f"단부루는 태그 {cap}개까지만 검색됩니다 — 앞 {cap}개만 씁니다: "
                    f"{' '.join(parts[:cap])}"
                    + ("" if cap > 2 else " (기타 → API 에 단부루 계정을 넣으면 6개까지)"))
            parts = parts[:cap]
    tags = " ".join(parts)[:200]
    headers = {"User-Agent": BOORU_UA}
    params = ({"tags": tags, "limit": limit, "pid": max(0, page - 1)} if site == "gelbooru"
              else {"tags": tags, "limit": limit, "page": page})
    # 저장된 계정이 있으면 붙인다 (겔부루는 이게 없으면 아예 JSON 을 주지 않는다)
    auth = None
    cuser, ckey = booru_creds(site)
    if cuser and ckey:
        if cfg.get("auth") == "gel":
            params["user_id"], params["api_key"] = cuser, ckey
        else:
            auth = (cuser, ckey)
    elif site == "gelbooru":
        return {"ok": False,
                "error": "겔부루는 API 키가 있어야 검색됩니다. "
                         "기타 → API 의 '부루 계정' 에 user_id 와 api_key 를 넣어 주세요."}
    try:
        # 단부루는 본 도메인이 막히면 미러를 차례로 시도한다.
        urls = [cfg["url"]]
        if site == "danbooru":
            urls = [cfg["url"].replace(DANBOORU_MIRRORS[0], h) for h in DANBOORU_MIRRORS]
        r, used, last_err = None, urls[0], None
        for ui, u in enumerate(urls):
            for attempt in range(2 if len(urls) > 1 else 3):
                _booru_throttle()
                try:
                    r = requests.get(u, timeout=25, headers=headers,
                                     params=params, auth=auth)
                    used = u
                    break
                except requests.exceptions.RequestException as e:
                    # 연달아 검색하면 Cloudflare 가 연결을 끊는다(ConnectionReset).
                    # 잠깐 쉬고 다시 시도하면 대개 풀리고, 그래도 안 되면 미러로 넘어간다.
                    last_err, r = e, None
                    time.sleep(1.0 * (attempt + 1))
            if r is not None:
                if ui > 0:
                    host = used.split("/")[2]
                    note = (note + " · " if note else "") + f"본 도메인이 막혀 미러({host})로 검색했습니다"
                    log.info(f"단부루 미러 사용: {host}")
                break
        if r is None:
            log.warning(f"{site} 검색 연결 실패: {last_err}")
            extra = (" 미러(hijiribe·sonohara)도 응답하지 않았습니다."
                     if site == "danbooru" else "")
            return {"ok": False,
                    "error": f"{cfg['name']} 이 연결을 끊었습니다 — 검색을 너무 "
                             f"자주 보내면 잠시 막습니다. 1~2분 뒤 다시 해 보세요.{extra}"}
        if r.status_code == 429:
            return {"ok": False,
                    "error": f"{cfg['name']} 요청 제한(429) — 잠시 뒤 다시 해 보세요."}
        if r.status_code == 451:
            return {"ok": False, "error": f"{cfg['name']} 은 이 지역에서 막혀 있습니다 (451)."}
        if r.status_code in (401, 403):
            return {"ok": False,
                    "error": f"{cfg['name']} 인증 실패({r.status_code}) — 기타 → API 의 "
                             f"'부루 계정' 을 확인해 주세요. {BOORU_AUTH_HELP.get(site, '')}"}
        if r.status_code == 422 and "TagLimit" in r.text:
            return {"ok": False,
                    "error": f"{cfg['name']} 태그 개수 제한(422) — 계정 등급이 낮으면 "
                             f"태그 2개까지만 됩니다. 태그를 줄여 보세요."}
        if r.status_code != 200:
            return {"ok": False, "error": f"{cfg['name']} HTTP {r.status_code}: {r.text[:100]}"}
        try:
            data = r.json()
        except ValueError:
            return {"ok": False,
                    "error": f"{cfg['name']} 이 JSON 을 주지 않았습니다 "
                             f"(API 키가 필요할 수 있음). 단부루로 검색해 보세요."}
        posts = data.get("post", []) if isinstance(data, dict) and "post" in data else data
        if isinstance(posts, dict):
            posts = posts.get("posts", [])
    except Exception as e:
        return {"ok": False, "error": f"{cfg['name']} 검색 실패: {e}"}

    # 미러로 검색했으면 게시물 링크도 그 미러로 준다 (본 도메인이 막혀 있으면 클릭도 안 열린다)
    page_base = cfg["page"]
    if site == "danbooru":
        used_host = used.split("/")[2]
        if used_host != DANBOORU_MIRRORS[0]:
            page_base = page_base.replace(DANBOORU_MIRRORS[0], used_host)

    out = []
    for p in posts or []:
        if site == "e621":
            f = (p.get("file") or {}); pv = (p.get("preview") or {})
            tg = " ".join(sum(((p.get("tags") or {}).get(k) or []) for k in
                              ("artist", "character", "copyright", "general", "species")), )
            thumb, full = pv.get("url"), f.get("url")
        elif site == "gelbooru":
            tg = p.get("tags") or ""
            thumb, full = p.get("preview_url"), p.get("file_url")
        else:
            tg = p.get("tag_string") or ""
            thumb = p.get("preview_file_url") or p.get("large_file_url")
            full = p.get("file_url") or p.get("large_file_url")
        if not thumb:
            continue
        out.append({"id": p.get("id"), "tags": tg,
                    "artist": (p.get("tag_string_artist") or "").strip(),
                    "character": (p.get("tag_string_character") or "").strip(),
                    "copyright": (p.get("tag_string_copyright") or "").strip(),
                    "thumb": thumb, "full": full,
                    "rating": p.get("rating", ""), "score": p.get("score", 0),
                    "url": f"{page_base}/{p.get('id')}" if site != "gelbooru"
                           else f"{page_base}&id={p.get('id')}"})
    return {"ok": True, "site": site, "name": cfg["name"], "count": len(out),
            "items": out, "page": page, "note": note,
            "search_url": (f"{page_base}?tags={tags.replace(' ', '+')}"
                           if site != "gelbooru" else f"{page_base}&tags={tags}")}


# ══════════════════════════════════════════════════════════════════════
#  태그 검증 — 프롬프트의 태그가 단부루에 실제로 있는지
# ══════════════════════════════════════════════════════════════════════
# posts.json 은 비로그인 태그 2개 제한이 있지만 **tags.json 은 제한이 없다**.
# 태그 이름과 게시물 수만 묻는 것이라 프롬프트를 통째로 검사할 수 있다.
#   (착안: nais_blue 가 tags.json 으로 태그를 검증한다 — 코드는 가져오지 않았다)
# 없는 태그는 그림에 아무 영향이 없으면서 토큰만 잡아먹으므로 찾아낼 값어치가 있다.
_TAGV_CACHE = {}

# NovelAI 공식 개명표. 단부루에서는 왼쪽이 여전히 정식 태그이므로 CSV 자체는 고치지 않는다.
# https://docs.novelai.net/en/image/tags/#renamed-tags
NAI_RENAMED_TAGS = {
    "v": "peace sign",
    "double_v": "double peace",
    "|_|": "bar eyes",
    r"\||/": r"open \m/",
    ":|": "neutral face",
    ";|": "neutral face",
    "<|>_<|>": "neco-arc eyes",
    "eyepatch_bikini": "square bikini",
    "tachi-e": "character image",
}


def _nai_tag_key(raw):
    """NAI 개명표 대조용 키. `<|> <|>`를 우리 `<조각>` 문법으로 오인하지 않는다."""
    t = str(raw or "").strip().lower()
    for _ in range(4):
        m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?\s*::(.*?)::", t)
        if not m:
            break
        t = m.group(1).strip()
    t = t.translate(str.maketrans("", "", "{}[]")).strip()
    t = re.sub(r"^artists?:", "", t)
    return re.sub(r"_+", "_", re.sub(r"\s+", "_", t)).strip("_")


def nai_renamed_tag(raw):
    """단부루 이름이 NAI에서 개명됐으면 NAI 권장 이름을 돌려준다."""
    return NAI_RENAMED_TAGS.get(_nai_tag_key(raw))


def _tagv_norm(raw):
    """`1.3::artist:foo::` · `{a}` · `<조각>` 같은 표기를 단부루 태그 이름으로."""
    t = (raw or "").strip()
    if not t or t.startswith("#"):
        return ""
    renamed_key = _nai_tag_key(t)
    if renamed_key in NAI_RENAMED_TAGS:
        return renamed_key
    if t.startswith("<") and t.endswith(">"):      # 우리 조각 문법은 검사 대상이 아니다
        return ""
    for _ in range(4):                              # 1.3::a:: 를 벗겨 낸다 (겹칠 수 있다)
        m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?\s*::(.*?)::", t.strip())
        if not m:
            break
        t = m.group(1)
    # ⚠ `{}` `[]` 는 NAI 의 강조 표기라 떼지만 **`()` 는 떼면 안 된다** —
    #   `2b (nier:automata)` · `1920s (style)` 처럼 괄호가 단부루 태그 이름의 일부다.
    #   떼면 캐릭터·저작물 태그 수백 개가 통째로 '없는 태그' 로 잘못 나온다.
    t = t.translate(str.maketrans("", "", "{}[]")).strip().lower()
    # NAI 는 `artist:wanke` 로 쓰지만 단부루 태그 이름은 `wanke` 다.
    # 떼지 않으면 멀쩡한 작가 태그가 전부 '없음' 으로 나온다.
    t = re.sub(r"^artists?:", "", t)
    return re.sub(r"_+", "_", re.sub(r"\s+", "_", t)).strip("_")


def _tags_json(params):
    """tags.json 을 미러 우회까지 붙여 호출."""
    return _tags_json_at("tags.json", params)


def _tags_json_at(endpoint, params):
    """단부루의 목록 API 를 미러 우회까지 붙여 호출 (tags.json · tag_aliases.json)."""
    last = None
    for host in DANBOORU_MIRRORS:
        _booru_throttle(0.4)
        try:
            r = requests.get(f"https://{host}/{endpoint}", params=params, timeout=20,
                             headers={"User-Agent": BOORU_UA, "Accept": "application/json"})
            if r.status_code == 200:
                d = r.json()
                return d if isinstance(d, list) else []
            last = f"HTTP {r.status_code}"
        except (requests.exceptions.RequestException, ValueError) as e:
            last = type(e).__name__
    raise RuntimeError(last or "실패")


def verify_tags(text, low=100):
    """프롬프트를 훑어 태그별로 있음/드묾/없음 을 돌려준다.

    없는 태그(GHOST)에는 비슷한 이름 후보를 함께 준다 — 오타를 고치기 쉽게."""
    seen, order = {}, []
    # 세미콜론도 예전에는 구분자로 받았지만 `;|` 자체가 NAI 공식 개명 태그다.
    # 그 한 태그는 임시 표식으로 보존한 뒤 나머지 세미콜론만 구분자로 바꾼다.
    semi_tag = "\x00NAI_SEMICOLON_BAR\x00"
    prepared = (text or "").replace(";|", semi_tag)
    parts = prepared.replace(chr(10), ",").replace(";", ",").replace(semi_tag, ";|").split(",")
    for chunk in parts:
        n = _tagv_norm(chunk)
        if not n or n in seen:
            continue
        seen[n] = chunk.strip()
        order.append(n)
    out, err = [], None
    # 이름 여러 개를 한 번에 물어본다 (요청 수를 줄인다)
    todo = [n for n in order if n not in NAI_RENAMED_TAGS and n not in _TAGV_CACHE]
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        try:
            got = _tags_json({"search[name_space]": " ".join(batch), "limit": 200})
            # 게시물 수만 보면 안 된다. `bangs`·`arms`·`athletic` 처럼 **폐지된 태그**는
            # 실존하는데 post_count 가 0 이다 (is_deprecated: true). 없는 것과 구분해야
            # 멀쩡한 태그를 '없음' 이라고 잘못 말하지 않는다.
            found = {str(x.get("name")): (int(x.get("post_count") or 0),
                                          bool(x.get("is_deprecated"))) for x in got}
            for n in batch:
                _TAGV_CACHE[n] = found.get(n)      # 목록에 없으면 None = 정말 없음
        except RuntimeError as e:
            err = str(e)
            break
    # 게시물 0 장인 것은 세 가지가 섞여 있다 — 별칭 · 폐지 · 정말 없음.
    #   ⚠ 별칭된 태그도 tags.json 에 **행이 남아 있고 is_deprecated 는 false** 다
    #     (crouching 0장 false → squatting 으로 옮겨 감). 행이 없는 것만 찾으면 놓친다.
    #   그래서 '0 장인 모든 것' 을 별칭 조회에 넣는다.
    missing = [n for n in order if n not in NAI_RENAMED_TAGS
               if _TAGV_CACHE.get(n, (1, False)) is None or _TAGV_CACHE.get(n, (1, False))[0] == 0]
    aliases = {}
    for i in range(0, len(missing), 30):
        batch = missing[i:i + 30]
        try:
            for x in _tags_json_at("tag_aliases.json",
                                   {"search[antecedent_name_space]": " ".join(batch),
                                    "limit": 200}):
                # ⚠ status 가 "active" 인 것만 보면 안 된다. `arm around waist` 처럼
                #   별칭이 나중에 지워진(deleted) 경우에도 **가리키던 이름이 지금 쓰이는 태그**다
                #   (arm_around_another's_waist). 거르면 정답을 알면서 '없음' 이라 말하게 된다.
                #   active 를 더 신뢰하므로 active 가 있으면 그것으로 덮어쓴다.
                ant, con = str(x.get("antecedent_name")), str(x.get("consequent_name"))
                cur = aliases.get(ant)
                if cur is None or (x.get("status") == "active" and cur[1] != "active"):
                    aliases[ant] = (con, str(x.get("status") or ""))
        except RuntimeError:
            break

    for n in order:
        if n in NAI_RENAMED_TAGS:
            out.append({"raw": seen[n], "tag": n, "count": None,
                        "status": "nai_renamed",
                        "alias_to": NAI_RENAMED_TAGS[n]})
            continue
        if n not in _TAGV_CACHE:               # 요청 자체가 실패한 것
            out.append({"raw": seen[n], "tag": n, "count": None, "status": "unknown"})
            continue
        rec = _TAGV_CACHE[n]
        cnt, dep = (0, False) if rec is None else rec
        if cnt >= low:
            st = "ok"
        elif cnt > 0:
            st = "low"
        elif n in aliases:                     # 이름이 바뀐 것 — 새 이름을 알려 준다
            con, ast_ = aliases[n]
            out.append({"raw": seen[n], "tag": n, "count": 0, "status": "alias",
                        "alias_to": con, "alias_status": ast_})
            continue
        elif dep:                              # 폐지 — 어휘엔 있고 NAI 는 대개 알아듣는다
            st = "old"
        else:
            st = "ghost"                       # 정말 없음
        item = {"raw": seen[n], "tag": n, "count": cnt, "status": st}
        if dep:
            item["deprecated"] = True
        if st == "ghost":
            try:
                sug = _tags_json({"search[name_matches]": f"*{n}*",
                                  "search[order]": "count", "limit": 5})
                # 자기 자신과 0 장짜리는 후보로 쓸모가 없다 (`best_quality` → `best_quality`)
                item["suggest"] = [{"name": str(x.get("name")),
                                    "count": int(x.get("post_count") or 0)}
                                   for x in sug
                                   if x.get("name") and str(x.get("name")) != n
                                   and int(x.get("post_count") or 0) > 0]
            except RuntimeError:
                item["suggest"] = []
        out.append(item)
    return {"ok": True, "items": out, "error": err,
            "summary": {k: sum(1 for x in out if x["status"] == k)
                        for k in ("ok", "low", "old", "alias", "nai_renamed",
                                  "ghost", "unknown")}}


def _b64_png(img_bytes_or_image):
    """디렉터 툴은 PNG base64 를 받는다."""
    import base64
    if isinstance(img_bytes_or_image, (bytes, bytearray)):
        raw = bytes(img_bytes_or_image)
        try:
            im = Image.open(io.BytesIO(raw))
            if (im.format or "").upper() == "PNG":
                return base64.b64encode(raw).decode("ascii"), im.width, im.height
        except Exception:
            pass
        im = Image.open(io.BytesIO(raw))
    else:
        im = img_bytes_or_image
    buf = io.BytesIO()
    im.convert("RGBA" if im.mode == "RGBA" else "RGB").save(buf, "PNG")
    return __import__("base64").b64encode(buf.getvalue()).decode("ascii"), im.width, im.height


def _last_from_zip(content):
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise APIError("응답 zip 이 비어 있습니다.")
        return zf.read(names[-1])          # 마지막 항목이 결과물


def call_director(token, image_bytes, method, prompt=None, defry=0):
    """augment-image 호출. 결과 이미지 bytes 를 돌려준다."""
    b64, w, h = _b64_png(image_bytes)
    body = {"req_type": method, "image": b64, "width": w, "height": h}
    if prompt is not None:
        body["prompt"] = prompt
        body["defry"] = int(defry or 0)
    r = requests.post(AUGMENT_URL, json=body, timeout=180, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/x-zip-compressed"})
    if r.status_code == 429:
        raise RateLimitError("429 Too Many Requests")
    if r.status_code == 401:
        raise AuthError("401 — 토큰을 확인하세요.")
    if r.status_code != 200:
        raise APIError(f"HTTP {r.status_code}: {r.text[:200]}")
    return _last_from_zip(r.content)


def call_upscale(token, image_bytes, scale=4):
    """업스케일. api 호스트가 400 을 주면 image 호스트로 다시 시도한다."""
    b64, w, h = _b64_png(image_bytes)
    body = {"image": b64, "width": w, "height": h, "scale": int(scale)}
    last = ""
    for url in UPSCALE_URLS:
        r = requests.post(url, json=body, timeout=180, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/x-zip-compressed"})
        if r.status_code == 200:
            return _last_from_zip(r.content)
        if r.status_code == 401:
            raise AuthError("401 — 토큰을 확인하세요.")
        last = f"HTTP {r.status_code}: {r.text[:160]}"
        log.info(f"업스케일 {url} → {last}")
    raise APIError(last or "업스케일 실패")


def fetch_anlas_balance(token):
    """남은 Anlas 조회. 실패하면 None.
    구 호스트(api.novelai.net)는 400 + 'update to the image URL' 을 준다 — image 호스트를 써야 한다."""
    if not token:
        return None
    try:
        r = requests.get("https://image.novelai.net/user/subscription", timeout=15,
                         headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return None
        d = r.json()
        tr = (d.get("trainingStepsLeft") or {})
        fixed = int(tr.get("fixedTrainingStepsLeft") or 0)
        purchased = int(tr.get("purchasedTrainingSteps") or 0)
        tier = d.get("tier")
        return {"fixed": fixed, "purchased": purchased, "total": fixed + purchased,
                "tier": tier, "opus": tier == 3, "active": bool(d.get("active"))}
    except Exception as e:
        log.warning(f"Anlas 조회 실패: {e}")
        return None


def nai_tokens(text):
    text = strip_comment_lines(text)   # 주석 줄은 전송에서 빠지므로 세지도 않는다
    return count_tokens(text, TOKENIZER_FILE)


def tokens_exact():
    """토크나이저 vocab 이 있어서 **정확한** 토큰 수를 낼 수 있는지.
    없으면 count_tokens 가 어림값으로 떨어지는데, 그걸 정확한 값처럼 보여 주면 안 된다."""
    return TOKENIZER_FILE.exists()


REMOTE_CACHE = IMG_CACHE / "원격"          # 인터넷에서 받아온 예시 이미지(용량 상한 적용)
REMOTE_CAP_MB = 400

MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".gif": "image/gif", ".avif": "image/avif"}


def trim_remote_cache():
    """원격 캐시가 상한을 넘으면 오래된 것부터 지운다. (동봉된 로컬 이미지는 건드리지 않음)"""
    try:
        files = [(f.stat().st_mtime, f.stat().st_size, f)
                 for f in REMOTE_CACHE.glob("*") if f.is_file()]
    except Exception:
        return
    total = sum(s for _, s, _ in files)
    cap = REMOTE_CAP_MB * 1024 * 1024
    if total <= cap:
        return
    files.sort()
    for _, size, f in files:
        try:
            f.unlink()
            total -= size
        except Exception:
            pass
        if total <= cap * 0.8:
            break
    log.info(f"예시 이미지 캐시 정리 → {total/1024/1024:.0f}MB")


# 호스트별 헤더. 부루 CDN 은 Cloudflare 뒤에 있는데, 브라우저를 흉내낸
# `Mozilla/5.0` UA 는 TLS 지문이 안 맞아서 오히려 403(챌린지)을 받는다.
# 정직한 봇 UA 로 보내면 그냥 통과한다 (검색 API 도 같은 조건).
BOORU_UA = "NAI-batch-generator/1.0 (personal use)"
HOST_HEADERS = {
    "donmai.us": {"User-Agent": BOORU_UA, "Referer": "https://danbooru.donmai.us/"},
    "gelbooru.com": {"User-Agent": BOORU_UA, "Referer": "https://gelbooru.com/"},
    "e621.net": {"User-Agent": BOORU_UA, "Referer": "https://e621.net/"},
}
# 그림체 예시 이미지(도랑 위키 등)는 반대로 브라우저 UA 를 기대한다
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://wiki.dorang.uk/"}


def headers_for(url):
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    for h, hdr in HOST_HEADERS.items():
        if host == h or host.endswith("." + h):
            return hdr
    return DEFAULT_HEADERS


def fetch_cached_image(url):
    """예시 이미지를 (bytes, content-type)으로 반환.
    local:파일명 → 수집/이미지캐시 에서 바로 읽음. http(s) → 받아서 캐시."""
    import hashlib
    url = (url or "").strip()
    if not url:
        return None, None
    IMG_CACHE.mkdir(parents=True, exist_ok=True)

    if url.startswith("local:"):
        name = Path(url[6:]).name          # 경로 탈출 차단
        p = IMG_CACHE / name
        if p.exists() and p.is_file():
            return p.read_bytes(), MIME.get(p.suffix.lower(), "image/png")
        log.warning(f"로컬 이미지 없음: {name}")
        return None, None

    if not url.startswith(("http://", "https://")):
        return None, None
    suf = Path(url.split("?")[0]).suffix.lower()
    if suf not in MIME:
        suf = ".webp"
    REMOTE_CACHE.mkdir(parents=True, exist_ok=True)
    p = REMOTE_CACHE / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + suf)
    if p.exists():
        return p.read_bytes(), MIME.get(suf, "image/webp")
    try:
        r = requests.get(url, timeout=25, headers=headers_for(url))
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and ct.startswith("image/"):
            # 중간 종료 때 잘린 캐시가 정상 파일처럼 남으면 이후에도 계속 그 파일을
            # 돌려주게 된다. 캐시도 완성된 바이트만 이름을 얻는다.
            _atomic_write_bytes(p, r.content, keep_backup=False)
            note_image_origin(url, r.content)
            return r.content, ct
        log.warning(f"이미지 응답 이상 [{r.status_code} {ct}]: {url[:80]}")
    except Exception as e:
        log.warning(f"이미지 가져오기 실패: {e}")
    return None, None


# ── 그림 출처 장부 ──────────────────────────────────────────────────────────
# 자료의 `images` 는 두 모양이다 — 원격 주소(`https://…`) 또는 내용 해시(`local:<sha256>`).
# 둘 사이를 오갈 수 있어야 "가볍게 나눠 주고, 중요한 것만 동봉" 이 된다.
#
# ⚠ 그런데 `local:` 로 바꾸는 순간 **원래 주소가 사라지면 되돌릴 수 없다.**
#   그래서 주소↔해시 짝을 여기에 남긴다.
#
# ⚠ 원격 캐시 파일명은 **주소 해시(SHA-1)** 라, 주소가 다른데 같은 그림이면
#   두 번 받아 두 벌로 남는다. 내려받을 때 **내용 SHA-256** 을 함께 적어 두면
#   나중에 그걸로 묶어 지울 수 있다.
_ORIGIN_LOCK = threading.Lock()


def _img_origin_path():
    return IMG_CACHE / "출처장부.json"


def load_image_origins():
    p = _img_origin_path()
    if p.exists():
        try:
            d = load_json_recover(p)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def note_image_origin(url, data, pack=""):
    """받아온 그림의 **원본 주소 · 내용 해시 · 저장 이름**을 적어 둔다.
    나중에 원격↔로컬을 되돌리거나, 주소가 달라도 같은 그림을 묶는 근거가 된다."""
    if not url or not data:
        return None
    sha = hashlib.sha256(data).hexdigest()
    try:
        with _ORIGIN_LOCK:
            book = load_image_origins()
            row = book.get(sha) or {"sha256": sha, "urls": [], "pack": pack}
            if url not in row["urls"]:
                row["urls"].append(url)
            if pack and not row.get("pack"):
                row["pack"] = pack
            row["size"] = len(data)
            book[sha] = row
            p = _img_origin_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(p, book, indent=None)
    except Exception as e:
        log.warning(f"출처 기록 실패: {e}")
    return sha


def image_origin_stats():
    """장부 요약 — 같은 그림을 가리키는 주소가 여럿인 것이 몇 건인가."""
    book = load_image_origins()
    dup = {k: v for k, v in book.items() if len(v.get("urls") or []) > 1}
    return {"ok": True,
            "그림": len(book),
            "주소여럿": len(dup),
            "낭비주소": sum(len(v["urls"]) - 1 for v in dup.values()),
            "예시": [{"sha256": k[:16], "urls": v["urls"][:4]}
                     for k, v in list(dup.items())[:20]]}


_WARM_POOL = None
_WARM_SEEN = set()
_WARM_LOCK = threading.Lock()


def prewarm_images(items, n=48):
    """목록 응답에 딸린 예시 이미지를 미리 받아 캐시에 채운다.
    브라우저가 <img>를 요청할 땐 이미 디스크에 있어 즉시 응답된다."""
    global _WARM_POOL
    urls = []
    for it in (items or [])[:n]:
        for u in (it.get("images") or [])[:1]:
            if isinstance(u, str) and u.startswith(("http://", "https://")):
                urls.append(u)
    if not urls:
        return
    with _WARM_LOCK:
        todo = [u for u in urls if u not in _WARM_SEEN]
        _WARM_SEEN.update(todo)
        if _WARM_POOL is None:
            from concurrent.futures import ThreadPoolExecutor
            _WARM_POOL = ThreadPoolExecutor(max_workers=8,
                                            thread_name_prefix="imgwarm")
    for u in todo:
        try:
            _WARM_POOL.submit(fetch_cached_image, u)
        except Exception:
            break
    if len(_WARM_SEEN) % 600 < len(todo):
        try:
            _WARM_POOL.submit(trim_remote_cache)
        except Exception:
            pass


# ══ 그림체 라이브러리 ══════════════════════════════════════════════════
# 한 '그림체' = 작가 조합 + 베이스 프롬프트 + 네거티브 + 생성 설정값 전부
# (시드·CFG·리스케일·스텝·샘플러·스케줄러·해상도·Variety+ …).
# 수집/그림체.json 이 본체이고, 없으면 옛 작가조합.json 으로 대체한다.
STYLE_FILE = BASE_DIR / "수집" / "그림체.json"
COMBO_FILE = BASE_DIR / "수집" / "작가조합.json"
_COMBOS = {"loaded": False, "rows": []}
_COMBOS_LOCK = threading.Lock()
_STYLE_TX_LOCK = threading.RLock()

# 작가 태그는 낱개가 아니라 묶음이 기본이다. `1.7::artist:a::` `.9::artist:b::`
# `0.6::artist:a, artist:b::`(한 가중치가 여럿에 걸림) 모두 순서·가중치를 지켜 읽는다.
_CNUM = r"-?(?:\d+\.\d*|\.\d+|\d+)"
_COPEN = re.compile(rf"^\s*\{{*\s*({_CNUM})\s*::\s*")
_CART = re.compile(r"^\s*artists?\s*:\s*(.+?)\s*$", re.IGNORECASE)
_CGLUE = re.compile(rf"::\s+(?=(?:{_CNUM}\s*::\s*)?artists?\s*:)", re.IGNORECASE)
_NOT_ARTIST = {"artist collaboration", "artist name", "artist request", "artist logo",
               "artist signature", "artist self-insert", "multiple artists", "style parody"}


def parse_artist_combo(text):
    """프롬프트 → ([(가중치|None, 작가명)], 작가가 아닌 나머지 토큰)"""
    artists, rest, weight = [], [], None
    for tok in _CGLUE.sub(":: , ", text or "").replace("\n", ",").split(","):
        raw, t = tok, tok.strip()
        if not t:
            continue
        m = _COPEN.match(t)
        if m:
            weight = float(m.group(1))
            t = t[m.end():].strip()
        closing = t.endswith("::") or t.endswith("}}")
        t = t.rstrip("}").rstrip(":").rstrip().rstrip("{").strip()
        if t:
            a = _CART.match(t)
            if a:
                name = re.sub(r"\s+", " ", a.group(1)).strip(" _:")
                if name.count(")") > name.count("("):
                    name = name.rstrip(")").strip()
                if name and len(name) <= 60 and "::" not in name \
                        and name.lower() not in _NOT_ARTIST:
                    artists.append((weight, name))
            else:
                rest.append(raw.strip())
        if closing:
            weight = None
    return artists, rest


def load_combos():
    if _COMBOS["loaded"]:
        return _COMBOS["rows"]
    # 첫 화면의 개수 조회와 사용자의 모달 열기가 겹쳐도 732건 JSON을 두 번 동시에
    # 읽고 파싱하지 않는다. ThreadingHTTPServer라 잠금이 없으면 둘 다 loaded=False를
    # 보고 같은 큰 파일을 잡아 메인 화면까지 버벅였다.
    with _COMBOS_LOCK:
        if _COMBOS["loaded"]:
            return _COMBOS["rows"]
        rows = []
        for f in (STYLE_FILE, COMBO_FILE):
            if not f.exists():
                continue
            try:
                rows = load_json_recover(f)
                log.info(f"그림체 로드: {len(rows)}개 ({f.name})")
                break
            except Exception as e:
                log.warning(f"그림체 로드 실패 {f.name}: {e}")
        _COMBOS.update({"loaded": True, "rows": rows})
    return _COMBOS["rows"]


@serialized_data_write(lambda: STYLE_FILE.parent.parent)
def add_style(rec):
    """새 그림체를 라이브러리에 넣고 파일에 저장 (이미지 추출 결과 등)."""
    with _STYLE_TX_LOCK:
        # 다른 실행본이 먼저 저장했을 수 있으므로 프로세스 잠금을 얻은 뒤 캐시가
        # 아니라 디스크 최신판에서 시작한다.
        forget_collection_caches()
        rows = list(load_combos())
        key = " ".join(sorted((a or "").lower() for a in rec.get("artists", [])))
        p = rec.get("params") or {}
        for i, r in enumerate(rows):
            rp = r.get("params") or {}
            if (" ".join(sorted((a or "").lower() for a in r.get("artists", []))) == key
                    and rp.get("seed") == p.get("seed")):
                rows[i] = rec                   # 같은 조합+시드면 갱신
                break
        else:
            rows.insert(0, rec)
        STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(STYLE_FILE, rows, indent=None)
        forget_collection_caches()
        return len(rows)


# ── 그림체 정리 ────────────────────────────────────────────────────────────
# 자료를 몇천 건 넣고 나면 **지울 수 있어야** 정리가 된다. 여기까지 없었다 —
# 목록(`/api/combos`)·한 건 추가(`style_save`)·별점(`rate`) 뿐이라 한 번 들어온 것을
# 뺄 방법이 없었다.
#
# ⚠ 지운 것은 **`수집/지운그림체.json` 으로 옮긴다**(되살릴 수 있게).
#   몇천 건을 훑다 잘못 고르는 일은 반드시 생긴다.
def _trashed_style_path():
    return BASE_DIR / "수집" / "지운그림체.json"


def _load_styles_raw():
    if not STYLE_FILE.exists():
        return []
    try:
        d = load_json_recover(STYLE_FILE)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _write_styles_raw(rows):
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(STYLE_FILE, rows, indent=None)
    forget_collection_caches()


@serialized_data_write(lambda: STYLE_FILE.parent.parent)
def delete_styles(ids):
    """고른 그림체를 지운다 → 지운그림체.json 으로 옮긴다."""
    with _STYLE_TX_LOCK:
        return _delete_styles_locked(ids)


def _delete_styles_locked(ids):
    want = {str(x) for x in (ids or []) if str(x)}
    if not want:
        return {"ok": False, "error": "고른 것이 없습니다."}
    rows = _load_styles_raw()
    keep = [r for r in rows if str(r.get("id")) not in want]
    gone = [r for r in rows if str(r.get("id")) in want]
    if not gone:
        return {"ok": False, "error": "그 그림체를 못 찾았습니다."}
    p = _trashed_style_path()
    old = []
    if p.exists():
        try:
            got = load_json_recover(p)
            old = got if isinstance(got, list) else []
        except Exception:
            old = []
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for r in gone:
        r = dict(r)
        r["_지운때"] = stamp
        old.append(r)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, old[-5000:], indent=None)
    _write_styles_raw(keep)
    return {"ok": True, "지움": len(gone), "남음": len(keep), "되살릴수있음": len(old)}


@serialized_data_write(lambda: STYLE_FILE.parent.parent)
def restore_styles(ids=None):
    """지운 것을 되살린다. ids 가 없으면 **가장 최근에 지운 묶음** 전부."""
    with _STYLE_TX_LOCK:
        return _restore_styles_locked(ids)


def _restore_styles_locked(ids=None):
    p = _trashed_style_path()
    if not p.exists():
        return {"ok": False, "error": "지운 그림체가 없습니다."}
    try:
        trash = load_json_recover(p)
    except Exception:
        return {"ok": False, "error": "지운 목록을 읽지 못했습니다."}
    if not isinstance(trash, list) or not trash:
        return {"ok": False, "error": "지운 그림체가 없습니다."}
    if ids:
        want = {str(x) for x in ids}
    else:
        last = trash[-1].get("_지운때")          # 마지막 묶음만 되살린다
        want = {str(r.get("id")) for r in trash if r.get("_지운때") == last}
    back = [r for r in trash if str(r.get("id")) in want]
    if not back:
        return {"ok": False, "error": "되살릴 것을 못 찾았습니다."}
    rows = _load_styles_raw()
    have = {str(r.get("id")) for r in rows}
    added, conflicts, rest = 0, 0, []
    for r in trash:
        rid = str(r.get("id"))
        if rid not in want:
            rest.append(r)
            continue
        if rid in have:
            # 같은 id의 새 자료를 덮지 않고, 옛 자료도 휴지통에서 잃지 않는다.
            # 사용자가 새 자료를 지우거나 id를 정리한 뒤 다시 복원할 수 있다.
            rest.append(r)
            conflicts += 1
            continue
        clean = {k: v for k, v in r.items() if k != "_지운때"}
        rows.insert(0, clean)
        have.add(rid)
        added += 1
    _write_styles_raw(rows)
    atomic_write_json(p, rest, indent=None)
    return {"ok": True, "되살림": added, "충돌": conflicts, "남은휴지통": len(rest)}


def _combo_fingerprint(r):
    """같은 그림체인지 보는 지문 — 작가 조합을 **가중치·순서 빼고** 본다.
    id 는 출처마다 다르게 붙으므로(`arca-3297` · `dorang-…`) id 로는 못 잡는다."""
    arts = r.get("artists")
    if arts:
        return " ".join(sorted((str(a) or "").strip().lower() for a in arts if a))
    combo = (r.get("combo") or "").lower()
    names = re.findall(r"artist:([^,:]+)", combo)
    if names:
        return " ".join(sorted(n.strip() for n in names))
    return re.sub(r"\s+", "", combo)


def find_style_dupes():
    """같은 작가 조합인데 여러 건인 것을 묶어서 돌려준다.
    출처가 다른 자료를 합치면 반드시 생긴다 — id 가 달라 자동 병합이 못 잡는다."""
    rows = _load_styles_raw()
    groups = {}
    for r in rows:
        fp = _combo_fingerprint(r)
        if not fp:
            continue
        groups.setdefault(fp, []).append(r)
    out = []
    for fp, rs in groups.items():
        if len(rs) < 2:
            continue
        # 설정값이 있고 정보가 많은 것을 앞에 둔다 — '남길 것' 을 고르기 쉽게
        rs = sorted(rs, key=lambda r: (
            0 if (r.get("params") or {}).get("seed") else 1,
            -len(json.dumps(r, ensure_ascii=False))))
        out.append({
            "지문": fp[:120],
            "건수": len(rs),
            "항목": [{"id": r.get("id"), "title": r.get("title"),
                      "source": r.get("source"),
                      "설정값": bool((r.get("params") or {}).get("seed")),
                      "작가수": r.get("count") or len(r.get("artists") or [])}
                     for r in rs],
        })
    out.sort(key=lambda g: -g["건수"])
    return {"ok": True, "묶음": len(out),
            "겹친항목": sum(g["건수"] for g in out), "전체": len(rows), "목록": out[:300]}


STYLE_SORTS = {
    "recommend": lambda r: (-(r.get("recommend") or -1), -(r.get("count") or 0)),
    "views":     lambda r: (-(r.get("views") or -1), -(r.get("count") or 0)),
    "newest":    lambda r: (r.get("posted_at") or "", -(r.get("count") or 0)),
    "oldest":    lambda r: (r.get("posted_at") or "9999",),
    "artists":   lambda r: (-(r.get("count") or 0),),
    "default":   lambda r: (0,),
}


# ── 작가 평가 (DanbooruArtistRater 의 ratings 를 우리 구조로) ──────────
#   별점·즐겨찾기·차단·메모를 작가 태그에 붙인다. 차단한 작가가 프롬프트에 있으면
#   생성 전에 알려 준다. 그림체 라이브러리 정렬·필터에도 쓰인다.
RATINGS_FILE = BASE_DIR / "수집" / "작가평가.json"
_RATINGS = {"mtime": -1, "data": {}}
_RATINGS_LOCK = threading.RLock()


def artist_key(name):
    """작가 이름 표준화 — 저장·조회·프롬프트 판정이 **같은 규칙**을 써야 한다.
    파서가 내부 연속 공백을 하나로 줄이므로 여기서도 같이 줄인다 (R3-02)."""
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


def load_ratings():
    """파일이 바뀌었으면 다시 읽는다 — 프로필을 둘 돌려도 서로의 평가를 안 잃는다."""
    with _RATINGS_LOCK:
        try:
            mt = RATINGS_FILE.stat().st_mtime_ns if RATINGS_FILE.exists() else 0
        except OSError:
            mt = 0
        if mt != _RATINGS["mtime"]:
            d = {}
            if RATINGS_FILE.exists():
                try:
                    d = load_json_recover(RATINGS_FILE) or {}
                except Exception as e:
                    log.warning(f"작가평가.json 읽기 실패: {e}")
                    return _RATINGS["data"]        # 깨진 파일로 기억을 지우지 않는다
            _RATINGS.update({"mtime": mt, "data": d if isinstance(d, dict) else {}})
        return _RATINGS["data"]


def save_ratings(d):
    """원자적으로 저장한다 (반쪽 JSON·동시 쓰기 유실 방지 — R3-01)."""
    with _RATINGS_LOCK:
        RATINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(RATINGS_FILE, d)
        try:
            _RATINGS.update({"mtime": RATINGS_FILE.stat().st_mtime, "data": d})
        except OSError:
            _RATINGS.update({"mtime": -1, "data": d})
        return d


@serialized_data_write(lambda: RATINGS_FILE.parent.parent)
def rate_artist(name, **fields):
    """작가 하나의 평가를 고친다. fields: score(0~5) · fav · block · memo"""
    key = artist_key(name)
    if not key:
        return {}
    with _RATINGS_LOCK:
        # 프로세스 잠금을 기다린 사이 바뀐 파일을 반드시 다시 읽는다. Windows의
        # 짧은 저장 간격에서도 놓치지 않도록 load_ratings는 mtime_ns를 쓴다.
        _RATINGS["mtime"] = -1
        d = dict(load_ratings())      # 최신을 다시 읽어 병합 (남의 저장을 덮지 않게)
        cur = dict(d.get(key) or {})
        for k in ("score", "fav", "block", "memo"):
            if k in fields:
                if k == "score":
                    try:
                        cur[k] = max(0, min(5, int(fields[k] or 0)))
                    except (TypeError, ValueError):
                        cur[k] = 0
                elif k == "memo":
                    # 메모도 사용자 원문이다. 화면·API 어디에도 500자 제한을 알리지
                    # 않으면서 저장할 때만 자르면 다시 복구할 수 없다.
                    cur[k] = str(fields[k] or "")
                else:
                    v = fields[k]
                    # "false"·0·"" 같은 값이 참으로 읽히면 애먼 작가가 차단된다 (R4-01)
                    cur[k] = (v if isinstance(v, bool)
                              else str(v).strip().lower() in ("1", "true", "yes", "on"))
        if not any([cur.get("score"), cur.get("fav"), cur.get("block"), cur.get("memo")]):
            d.pop(key, None)          # 전부 비면 기록을 남기지 않는다
        else:
            d[key] = cur
        save_ratings(d)
        return cur


def blocked_artists_in(text):
    """프롬프트에 차단한 작가가 들어 있으면 목록으로 (생성 전 경고용)."""
    d = load_ratings()
    blocked = {k for k, v in d.items() if v.get("block")}
    if not blocked:
        return []
    names = {artist_key(a) for _, a in parse_artist_combo(text or "")[0]}
    return sorted(blocked & names)


def style_rating(rec, ratings=None):
    """그림체 한 줄의 평가 요약 — 작가들의 평균 별점·즐겨찾기·차단 포함 여부."""
    d = load_ratings() if ratings is None else ratings
    arts = [artist_key(a) for a in (rec.get("artists") or [])]
    vals = [d.get(a) for a in arts if d.get(a)]
    scores = [v["score"] for v in vals if v.get("score")]
    return {
        "score": round(sum(scores) / len(scores), 1) if scores else 0,
        "fav": any(v.get("fav") for v in vals),
        "block": any(v.get("block") for v in vals),
        "rated": len(vals),
    }


def search_combos(q="", limit=40, offset=0, tab="", source="", sort="", seeded="",
                  rating=""):
    """그림체 검색. q=제목/작가/프롬프트, tab=NAI·R18_NAI, source=아카·도랑·내 이미지,
    sort=recommend|views|newest|oldest|artists, seeded=1 이면 설정값 완비된 것만."""
    rows = load_combos()
    ratings = load_ratings()
    q = (q or "").strip().lower()
    hit = rows
    if q:
        terms = [t for t in q.split() if t]
        hit = [r for r in hit if all(t in (
            r.get("combo", "") + " " + r.get("title", "") + " " + r.get("source", "") +
            " " + r.get("rest", "") + " " + r.get("negative", "")).lower() for t in terms)]
    if tab and tab != "all":
        hit = [r for r in hit if (r.get("tab") or "") == tab]
    if source and source != "all":
        hit = [r for r in hit if (r.get("source") or "") == source]
    if seeded in ("1", "true", True):
        hit = [r for r in hit if (r.get("params") or {}).get("seed")]
    # 평가 필터 — fav(즐겨찾기만) · rated(별점 매긴 것만) · hideblock(차단 숨김)
    if rating:
        if rating == "fav":
            hit = [r for r in hit if style_rating(r, ratings)["fav"]]
        elif rating == "rated":
            hit = [r for r in hit if style_rating(r, ratings)["score"]]
        elif rating == "hideblock":
            hit = [r for r in hit if not style_rating(r, ratings)["block"]]
    if sort in STYLE_SORTS and sort != "default":
        rev = sort in {"newest"}
        hit = sorted(hit, key=STYLE_SORTS[sort], reverse=rev)

    def tally(key, default=""):
        out = {}
        for r in rows:
            v = r.get(key) or default
            if v:
                out[v] = out.get(v, 0) + 1
        return out

    page = hit[offset:offset + limit]
    # 목록 카드가 실제로 쓰는 값만 보낸다. 원본에는 캐릭터 전체 프롬프트·rest·weights가
    # 함께 있어 20~50개만 열어도 응답과 JSON 파싱이 불필요하게 커졌다. 그림체 적용에
    # 필요한 베이스·네거티브·생성 설정은 그대로 보존하고, 썸네일도 첫 장만 보낸다.
    card_fields = (
        "id", "title", "source", "tab", "posted_at", "recommend", "views", "url",
        "count", "combo", "artists", "base", "negative", "negative_full", "params",
        "images",
    )
    items = []
    for r in page:
        item = {k: r[k] for k in card_fields if k in r}
        if isinstance(item.get("images"), list):
            item["images"] = item["images"][:1]
        item["_rate"] = style_rating(r, ratings)
        items.append(item)
    return {"total": len(rows), "matched": len(hit),
            "sources": tally("source", "도랑"), "tabs": tally("tab"),
            "seeded": sum(1 for r in rows if (r.get("params") or {}).get("seed")),
            "items": items, "offset": offset}


# ══ 캐릭터 빌더 후보사전 (슬롯별 후보 태그 — 후보사전.json 에서 자유롭게 확장) ══
BUILDER_FILE = BASE_DIR / "후보사전.json"


# ══ 태그 사전: 태그/ 폴더의 CSV(단부루·e621 등) → 규격 슬롯별 분류 + 검색 ══
# CSV 형식: 태그,카테고리,게시물수,"별칭,별칭,..."
# 카테고리: 0 일반 / 1 작가 / 3 원작 / 4 캐릭터 / 5 메타 (e621은 5,7,8,12 등도 등장)
TAG_DIR = BASE_DIR / "태그"
_TAG_CACHE = {"loaded": False, "rows": [], "by_slot": {}}
# 사전 로드·색인은 10초쯤 걸린다. 락이 없으면 기동 예열과 첫 요청이 **같은 일을 두 번** 해서
# 오히려 두 배로 기다린다 (실측 15초). 먼저 들어온 쪽이 만들고 나머지는 기다리게 한다.
# RLock 이다 — 어느 경로에서든 겹쳐 잡혀도 멈추지 않게 (Lock 이면 교착이 난다)
_TAG_LOCK = threading.RLock()


def _slot_of_tag(tag, cat, char_rules, style_rules):
    """규격.json 의 키워드 규칙 + CSV 카테고리로 슬롯 결정. (슬롯이름, 종류) 반환"""
    if cat == 1:
        return "작가", "style"
    if cat == 3:
        return "원작/장르", "style"
    if cat == 4:
        return "기본", "char"
    core = tag.replace("_", " ").lower()
    best, best_len, kind = None, 0, "char"
    for rules, k in ((char_rules, "char"), (style_rules, "style")):
        for g in rules:
            for kw in g.get("키워드", []):
                kl = kw.lower()
                if len(kl) > best_len and kl in core:
                    best, best_len, kind = g["이름"], len(kl), k
    return best, kind


def load_tag_dict(spec):
    """CSV들을 한 번만 읽어 메모리에 인덱싱 (5~10MB, 1~2초).
    태그/*.csv 가 없으면 빈 사전으로 돌아간다 — 자동완성·빌더 사전만 비고 생성은 정상."""
    if _TAG_CACHE["loaded"]:
        return _TAG_CACHE
    with _TAG_LOCK:
        if _TAG_CACHE["loaded"]:      # 기다리는 동안 다른 쪽이 다 만들었으면 그걸 쓴다
            return _TAG_CACHE
        return _load_tag_dict_inner(spec)


def _load_tag_dict_inner(spec):
    rows, by_slot = [], {}
    if TAG_DIR.exists():
        import csv as _csv
        char_rules = spec.get("캐릭터_그룹", [])
        style_rules = spec.get("그림체_그룹", [])
        for p in sorted(TAG_DIR.glob("*.csv")):
            try:
                with open(p, encoding="utf-8", errors="ignore", newline="") as f:
                    for r in _csv.reader(f):
                        if len(r) < 3 or not r[0].strip():
                            continue
                        tag = r[0].strip()
                        try:
                            cat = int(r[1]) if r[1].strip() else 0
                            cnt = int(r[2]) if r[2].strip() else 0
                        except ValueError:
                            continue
                        slot, kind = _slot_of_tag(tag, cat, char_rules, style_rules)
                        display = tag.replace("_", " ")
                        # CSV 4열은 **별칭**이다 (`1girl,0,6008644,"1girls,sole_female"`).
                        # 예전엔 버렸다 — 별칭으로 치면 정식 태그를 못 찾았다 (F-01).
                        al = [x.strip().replace("_", " ") for x in (r[3] if len(r) > 3 else "").split(",")]
                        rows.append((display, cnt, slot or "", kind, [x for x in al if x]))
                        if slot:
                            by_slot.setdefault((kind, slot), []).append((display, cnt))
            except Exception as e:
                log.warning(f"태그 CSV 읽기 실패({p.name}): {e}")
    for k in by_slot:
        by_slot[k].sort(key=lambda x: -x[1])
    _TAG_CACHE.update({"loaded": True, "rows": rows, "by_slot": by_slot})
    log.info(f"태그 사전 로드: {len(rows):,}개 (슬롯 분류 {len(by_slot)}종)")
    return _TAG_CACHE


def _ac_index(spec):
    """자동완성 색인 — 사전 22만 줄을 매번 훑으면 한 번에 0.7초가 걸려 타이핑에 못 쓴다.
    ① 앞 두 글자 → 빈도순 목록 (앞에서 맞는 것)
    ② 전체를 빈도순으로 한 줄 (안에 든 것 — 흔한 것부터 보므로 일찍 끊을 수 있다)
    작가 태그는 `artist:` 를 뗀 형태도 같은 바구니에 넣는다."""
    if _TAG_CACHE.get("ac"):
        return _TAG_CACHE["ac"]
    with _TAG_LOCK:
        if _TAG_CACHE.get("ac"):
            return _TAG_CACHE["ac"]
        # 캐시가 있으면 CSV 파싱(10초)까지 건너뛴다
        got = _ac_cache_load()
        if got:
            _TAG_CACHE["rows"] = got["rows"]
            _TAG_CACHE["loaded"] = True
            _TAG_CACHE["ac"] = {"buckets": got["buckets"], "flat": got["flat"]}
            log.info(f"자동완성 색인(캐시): 앞2글자 {len(got['buckets']):,}종")
            return _TAG_CACHE["ac"]
        return _ac_index_inner(load_tag_dict(spec))


AC_CACHE_FILE = BASE_DIR / "수집" / "태그색인.pickle"
AC_CACHE_VER = 3      # 3 = 별칭 색인 + NAI 개명 태그 교정


def _tag_fingerprint():
    """태그 CSV 들의 (이름, 크기, 수정시각) — 사전이 바뀌면 캐시를 버린다."""
    if not TAG_DIR.exists():
        return ()
    return tuple(sorted((p.name, p.stat().st_size, int(p.stat().st_mtime))
                        for p in TAG_DIR.glob("*.csv")))


def _ac_cache_load():
    """디스크에 저장해 둔 색인을 읽는다. 처음 한 번만 13초 걸리고 그 뒤엔 1초 안이다."""
    try:
        if not AC_CACHE_FILE.exists():
            return None
        import pickle
        with open(AC_CACHE_FILE, "rb") as f:
            got = pickle.load(f)
        if got.get("fp") != _tag_fingerprint():
            log.info("태그 사전이 바뀌어 색인 캐시를 버립니다")
            return None
        # 색인 구조가 바뀌면(별칭 추가 등) 옛 캐시는 못 쓴다 — 버전으로 가른다
        if got.get("ver") != AC_CACHE_VER:
            log.info("색인 형식이 바뀌어 캐시를 다시 만듭니다")
            return None
        return got
    except Exception as e:
        log.info(f"색인 캐시 읽기 건너뜀: {e}")
        return None


def _ac_cache_save(rows, buckets, flat):
    try:
        import pickle
        AC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = AC_CACHE_FILE.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump({"fp": _tag_fingerprint(), "ver": AC_CACHE_VER, "rows": rows,
                         "buckets": buckets, "flat": flat}, f, protocol=4)
        tmp.replace(AC_CACHE_FILE)
        log.info(f"색인 캐시 저장: {AC_CACHE_FILE.stat().st_size//1024//1024}MB")
    except Exception as e:
        log.info(f"색인 캐시 저장 건너뜀: {e}")


def _ac_index_inner(d):
    # 디스크 캐시가 있으면 그걸 쓴다 (사전 로드까지 건너뛴다)
    got = _ac_cache_load()
    if got:
        d["rows"] = got["rows"]
        d["ac"] = {"buckets": got["buckets"], "flat": got["flat"]}
        log.info(f"자동완성 색인(캐시): 앞2글자 {len(got['buckets']):,}종")
        return d["ac"]
    buckets, flat = {}, []
    for row in d["rows"]:
        t, c, _slot, _k = row[0], row[1], row[2], row[3]
        aliases = row[4] if len(row) > 4 else []
        tl = t.lower()
        suggested = nai_renamed_tag(t) or t
        sl = suggested.lower()
        flat.append((suggested, c, sl))
        if sl != tl:
            flat.append((suggested, c, tl))
        keys = {tl[:2], sl[:2]}
        tb = re.sub(r"^artists?:", "", tl)
        if tb is not tl:
            keys.add(tb[:2])
        # 별칭으로 쳐도 **정식 태그**가 나오게 한다 (F-01).
        # 넣는 값은 정식 이름(t)이고 비교용 문자열만 별칭이다 — 사용자는 옳은 태그를 받는다.
        for a2 in aliases[:6]:
            al = a2.lower()
            if al and al != tl:
                flat.append((suggested, c, al))
                if len(al) >= 2:
                    keys.add(al[:2])
                    buckets.setdefault(al[:2], []).append((suggested, c, al))
        for k in keys:
            if len(k) == 2:
                buckets.setdefault(k, []).append((suggested, c, sl if k == sl[:2] else tl))
    for k in buckets:
        buckets[k].sort(key=lambda x: -x[1])
    flat.sort(key=lambda x: -x[1])
    d["ac"] = {"buckets": buckets, "flat": flat}
    log.info(f"자동완성 색인: 앞2글자 {len(buckets):,}종")
    _ac_cache_save(d["rows"], buckets, flat)
    return d["ac"]


def autocomplete_tags(spec, q, limit=12):
    """프롬프트 칸의 자동완성 — 앞에서 맞는 것 먼저, 그다음 안에 든 것.
    각 묶음 안에서는 **빈도순**(단부루 자동완성과 같은 순서).
    `_` 와 공백을 같게 보고, 작가 태그도 `artist:` 를 떼고 비교한다."""
    q = (q or "").strip().lower().replace("_", " ")
    if len(q) < 2:
        return []
    idx = _ac_index(spec)
    bare = re.sub(r"^artists?:", "", q)
    seen, out = set(), []
    for key in {q[:2], bare[:2]}:
        for t, c, tl in idx["buckets"].get(key, []):
            if t in seen:
                continue
            if tl.startswith(q) or re.sub(r"^artists?:", "", tl).startswith(bare):
                seen.add(t); out.append((t, c))
                if len(out) >= limit * 2:
                    break
    out.sort(key=lambda x: -x[1])
    if len(out) < limit:
        for t, c, tl in idx["flat"]:           # 빈도순이라 흔한 것부터 나온다
            if t in seen or q not in tl:
                continue
            seen.add(t); out.append((t, c))
            if len(out) >= limit:
                break
    return [{"tag": t, "count": c} for t, c in out[:limit]]


def search_tags(spec, kind, slot, q, limit=60):
    d = load_tag_dict(spec)
    q = (q or "").strip().lower().replace("_", " ")
    if slot:
        pool = d["by_slot"].get((kind, slot), [])
        if q:
            hit = [x for x in pool if q in x[0].lower()]
            if hit:
                return [{"tag": t, "count": c} for t, c in hit[:limit]]
            # 슬롯 키워드에 없는 태그도 찾을 수 있게 전체 사전으로 폴백
        else:
            return [{"tag": t, "count": c} for t, c in pool[:limit]]
    if not q:
        return []
    out = [(r[0], r[1]) for r in d["rows"] if q in r[0].lower()]   # rows 는 5칸(별칭 포함)
    out.sort(key=lambda x: -x[1])
    return [{"tag": t, "count": c} for t, c in out[:limit]]


def load_builder():
    if BUILDER_FILE.exists():
        try:
            data = load_json_recover(BUILDER_FILE)
            if isinstance(data, dict):
                # 후보사전은 사람이 직접 고치는 자료다. 과거에는 캐릭터의 의상·신체·
                # 성별 변형인 "예술적 변형"이 베이스 목록 안에 들어가 있었다.
                # `대상`을 명시한 단계는 파일의 물리적 위치와 무관하게 올바른 빌더로
                # 옮긴다. 이렇게 하면 기존 사용자 후보사전의 순서를 부수지 않으면서도
                # 화면과 저장 결과는 정확한 캐릭터 경로를 쓴다.
                chars = list(data.get("캐릭터단계") or [])
                base = []
                for step in list(data.get("베이스단계") or []):
                    if isinstance(step, dict) and step.get("대상") == "캐릭터":
                        chars.append(step)
                    else:
                        base.append(step)
                # 기존 후보사전의 첫 슬롯은 이름만 "작가 조합"이고 후보가 비어 있다.
                # 별도 표시값이 없어 빌더 화면에는 조합 라이브러리를 여는 버튼이 0개였다.
                # 사용자가 고친 후보사전과도 호환되게, 이 명확한 빈 전용 슬롯만 연결한다.
                for step in base:
                    for slot in (step.get("슬롯") or []) if isinstance(step, dict) else []:
                        if (slot.get("라벨") == "작가 조합"
                                and not (slot.get("후보") or [])):
                            slot.setdefault("조합전용", True)
                data["캐릭터단계"] = chars
                data["베이스단계"] = base
                return data
        except Exception as e:
            log.warning(f"후보사전.json 손상: {e}")
    return {"슬롯": [], "풀": {}, "한글": {}}

# ═══════════════════════════════════════════════════════════════════
#  규격 vs 세팅 — 이 프로그램의 기본 구분
#  · 규격 = 뼈대(원리): 캐릭터/베이스 슬롯 체계(규격.json·후보사전.json),
#           그리고 엔진이 이해하는 조립 방식("남녀"/"백합"/"단독")과
#           옵션 의미(장소테마=배경, 시간대=시간, 표정진행=단계아크, 탈의단계=백합탈의)
#  · 세팅 = 내용물(콘텐츠): 세팅/ 폴더의 파일들. 씬 모음 + 부속 옵션 + 상대역.
#           체위/표정/백합은 기본 제공 세팅일 뿐이며, 파일을 넣고 빼는 대로 UI가 바뀐다.
#
#  세팅 파일 형식: 세팅/<이름>.json
#  {"이름": "남녀 체위", "방식": "남녀"|"백합"|"단독",
#   "씬": {번호: {name, female_prompt, male_prompt/partner_prompt, category, ...}},
#   "옵션": {"장소테마": {...}, "시간대": {...}, "표정진행": {...}, "탈의단계": {...}},
#   "상대역": {"외형": "", "착의": "", "네거티브": "", "의상": ""}}
# ═══════════════════════════════════════════════════════════════════
SETTINGS_DIR = BASE_DIR / "세팅"
SCHEMA_DIR = BASE_DIR / "씬규격"   # 구버전 (마이그레이션 소스)
KINDS = ("체위", "표정", "백합")
_SETTING_TX_LOCK = threading.RLock()


def serialized_setting_write(func):
    """세팅 한 파일의 읽기→수정→쓰기를 한 덩어리로 직렬화한다.

    atomic_write_json은 반쪽 파일을 막지만, 두 요청이 같은 옛 파일을 읽은 뒤 각각
    정상 저장하면 마지막 저장이 앞 변경을 덮는 문제까지 막지는 못한다.
    """
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        with shared_data_transaction(SETTINGS_DIR.parent):
            with _SETTING_TX_LOCK:
                return func(*args, **kwargs)
    return wrapped


@serialized_setting_write
def ensure_settings_migration():
    """씬규격/(구) 또는 asset_config.json(구구) → 세팅/ 으로 1회 변환"""
    if SETTINGS_DIR.exists():
        return
    ensure_schema_split()  # asset_config → 씬규격 (더 옛 버전 대비)
    if not SCHEMA_DIR.exists():
        return
    SETTINGS_DIR.mkdir()
    mapping = {"체위": ("남녀 체위", "남녀"), "표정": ("표정", "단독"), "백합": ("백합", "백합")}
    for kind, (name, mode) in mapping.items():
        src = SCHEMA_DIR / kind / "기본.json"
        if not src.exists():
            continue
        try:
            data = load_json_recover(src)
        except Exception as e:
            log.warning(f"{kind} 변환 실패: {e}")
            continue
        out = {"이름": name, "방식": mode, "씬": data.get("씬", {}),
               "옵션": data.get("옵션", {}),
               "상대역": {"외형": "", "착의": "", "네거티브": "", "의상": ""}}
        atomic_write_json(
            SETTINGS_DIR / f"{name}.json", out, keep_backup=False)
    log.info("세팅/ 폴더 생성 완료 (씬규격에서 변환)")


def list_settings():
    """세팅/ 폴더의 세팅 파일 목록 (파일 기반 — 넣고 빼는 대로 반영)"""
    ensure_settings_migration()
    out = []
    if not SETTINGS_DIR.exists():
        return out
    for p in sorted(SETTINGS_DIR.glob("*.json")):
        try:
            data = load_json_recover(p)
            if isinstance(data, dict) and data.get("씬"):
                out.append({"file": p.name, "name": data.get("이름") or p.stem,
                            "mode": data.get("방식", "단독"), "data": data})
        except Exception as e:
            log.warning(f"세팅 파일 손상({p.name}): {e}")
    return out


def used_scene_nums(skip=None):
    """모든 세팅이 쓰는 씬 번호. **번호는 세팅끼리 공유하는 전역 이름공간**이라
    겹치면 나중에 읽힌 세팅이 앞의 것을 덮어써 조용히 사라진다."""
    used = {}
    for st in list_settings():
        if skip and st["name"] == skip:
            continue
        for k in st["data"].get("씬", {}):
            if str(k).isdigit():
                used[int(k)] = st["name"]
    return used


def free_scene_block(count, skip=None, step=100):
    """빈 번호 구간을 찾아 시작 번호를 돌려준다 (100 단위 구간으로 잡아 눈에 띄게)."""
    used = set(used_scene_nums(skip))
    start = step
    while True:
        if not any((start + i) in used for i in range(max(1, count))):
            return start
        start += step


def scene_num_clashes():
    """세팅끼리 겹치는 번호 목록 (경고용)."""
    seen, clash = {}, {}
    for st in list_settings():
        for k in st["data"].get("씬", {}):
            if not str(k).isdigit():
                continue
            n = int(k)
            if n in seen:
                clash.setdefault(n, [seen[n]]).append(st["name"])
            else:
                seen[n] = st["name"]
    return clash


def setting_thumbs(name, cfg=None):
    """세트 대표 썸네일 — 세트에 속한 씬 번호로 시작하는 결과물 중 가장 새것.
    파일명이 `101_A01_핸드잡_시작전.webp` 꼴이므로 앞 3자리로 찾는다."""
    st = next((s for s in list_settings() if s["name"] == name), None)
    if not st:
        return {}
    scenes = st["data"].get("씬", {})
    newest = {}                       # 씬번호 → (mtime, 경로)
    root = out_root(cfg) / "nsfw_seed"
    if root.exists():
        for p in root.rglob("*"):
            if p.suffix.lower() not in (".webp", ".png"):
                continue
            head = p.name[:3]
            if not head.isdigit():
                continue
            n = int(head)
            if str(n) not in scenes:
                continue
            m = p.stat().st_mtime
            if n not in newest or m > newest[n][0]:
                newest[n] = (m, p)
    out = {}
    for g in derive_setting_catalog(scenes):
        best = max((newest[i] for i in g["ids"] if i in newest),
                   default=None, key=lambda x: x[0])
        if best:
            out[str(g["id"])] = str(best[1].relative_to(out_root(cfg))).replace("\\", "/")
    return out


@serialized_setting_write
def duplicate_setting_group(name, gid):
    """세트 복제 — 그 세트의 씬들을 새 번호로 복사해 같은 세팅 파일에 넣는다."""
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅 파일을 찾을 수 없습니다."}
    d = load_json_recover(p)
    scenes = d.get("씬", {})
    group = next((g for g in derive_setting_catalog(scenes) if g["id"] == int(gid)), None)
    if not group:
        return {"ok": False, "error": "그 세트를 찾을 수 없습니다."}
    # 빈 번호 구간을 찾는다 (연속으로 len(ids)개)
    used = {int(k) for k in scenes if str(k).isdigit()}
    span = len(group["ids"])
    start = max(used) + 1
    while any((start + i) in used for i in range(span)):
        start += 1
    for i, src in enumerate(group["ids"]):
        sc = dict(scenes[str(src)])
        sc["name"] = f"{sc.get('name','')} 사본" if i == 0 else sc.get("name", "")
        # 세트 묶음 규칙은 '이름의 마지막 단어를 뗀 나머지' 다.
        # 원본 이름 뒤에 붙이면 원본과 다른 세트가 되면서 단계명은 그대로 유지된다.
        nm = scenes[str(src)].get("name", "")
        head, _, tail = nm.rpartition(" ")
        sc["name"] = f"{head} 사본 {tail}" if head else f"{nm} 사본"
        scenes[str(start + i)] = sc
    d["씬"] = scenes
    atomic_write_json(p, d, indent=1)
    return {"ok": True, "new_id": start, "count": span}


# ══════════════════════════════════════════════════════════════════════
#  세팅 빌더 — 세팅을 앱 안에서 만들고 고친다
#    세트(묶음) = 이름이 같고 단계명만 다른 씬들. 그래서 씬 이름을
#    `<세트이름> <단계명>` 으로 만들면 자동으로 한 묶음이 된다.
#    단계 수는 자유다 (묶음 안의 순서로 단계를 세므로 5장에 묶이지 않는다).
# ══════════════════════════════════════════════════════════════════════
BUILDER_MODES = ("단독", "남녀", "백합")


@serialized_setting_write
def new_setting(name, mode="단독", stages=None):
    """빈 세팅 파일을 만든다. stages 는 단계명 목록 (["시작","중간","끝"] 처럼)."""
    safe = _safe_name(name) or "새 세팅"
    if mode not in BUILDER_MODES:
        mode = "단독"
    SETTINGS_DIR.mkdir(exist_ok=True)
    target, k = SETTINGS_DIR / f"{safe}.json", 2
    while target.exists():
        target = SETTINGS_DIR / f"{safe} ({k}).json"
        k += 1
    data = {
        "이름": target.stem,
        "방식": mode,
        "단계명": [x for x in (stages or ["시작", "중간", "끝"]) if str(x).strip()],
        "계열이름": {},
        "옵션규격": {},
        "옵션": {},
        "씬": {},
        "상대역": {},
    }
    atomic_write_json(target, data, indent=1, keep_backup=False)
    return {"ok": True, "name": target.stem, "file": target.name}


@serialized_setting_write
def setting_add_set(name, label, category="", width=832, height=1216, stages=None):
    """세트 하나를 추가 — 단계명마다 씬을 하나씩 만든다."""
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
    d = load_json_recover(p)
    stages = [x for x in (stages or d.get("단계명") or ["시작", "중간", "끝"]) if str(x).strip()]
    label = (label or "새 세트").strip()
    scenes = d.setdefault("씬", {})
    mine = {int(k) for k in scenes if str(k).isdigit()}
    others = set(used_scene_nums(skip=name))
    start = (max(mine) + 1) if mine else free_scene_block(len(stages), skip=name)
    while any((start + i) in others or (start + i) in mine for i in range(len(stages))):
        start += 1
    for i, stg in enumerate(stages):
        scenes[str(start + i)] = {
            "name": f"{label} {stg}".strip(),
            "female_prompt": "", "male_prompt": "",
            "width": int(width), "height": int(height),
            "category": category or "",
        }
    atomic_write_json(p, d, indent=1)
    return {"ok": True, "start": start, "count": len(stages)}


@serialized_setting_write
def setting_meta_save(name, patch):
    """세팅의 머리 정보 (이름·방식·단계명·계열이름·옵션규격·옵션·상대역) 저장."""
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
    d = load_json_recover(p)
    for k in ("방식", "단계명", "계열이름", "옵션규격", "옵션", "상대역"):
        if k in patch:
            d[k] = patch[k]
    if d.get("방식") not in BUILDER_MODES:
        d["방식"] = "단독"
    # 이름을 바꾸면 파일명도 맞춘다
    newname = (patch.get("이름") or "").strip()
    if newname and newname != d.get("이름"):
        safe = _safe_name(newname) or d["이름"]
        tgt = SETTINGS_DIR / f"{safe}.json"
        if tgt.exists() and tgt != p:
            return {"ok": False, "error": f"'{safe}' 이름이 이미 있습니다."}
        d["이름"] = safe
        # 새 이름의 완성본을 먼저 만든 뒤 옛 이름을 치운다. 중간 종료라면 두 벌이
        # 남을 수는 있어도 세팅 내용 자체가 사라지지는 않는다.
        atomic_write_json(tgt, d, indent=1, keep_backup=False)
        recoverable_remove(p, label="이름변경")
        return {"ok": True, "name": safe, "renamed": True}
    d["이름"] = d.get("이름") or p.stem
    atomic_write_json(p, d, indent=1)
    return {"ok": True, "name": d["이름"]}


@serialized_setting_write
def setting_renumber(name, start=None):
    """이 세팅의 씬 번호를 겹치지 않는 구간으로 다시 매긴다 (세트·단계 순서는 유지)."""
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
    d = load_json_recover(p)
    scenes = d.get("씬", {})
    order = []
    for g in derive_setting_catalog(scenes):
        order.extend(g["ids"])
    for k in sorted(int(x) for x in scenes if str(x).isdigit()):
        if k not in order:
            order.append(k)
    if start is None:
        start = free_scene_block(len(order), skip=name)
    new = {}
    for i, old in enumerate(order):
        new[str(start + i)] = scenes[str(old)]
    d["씬"] = new
    atomic_write_json(p, d, indent=1)
    return {"ok": True, "start": start, "count": len(new), "clashes": scene_num_clashes()}


@serialized_setting_write
def setting_delete(name):
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
    backup = recoverable_remove(p)
    return {"ok": True, "backup": backup.name}


def export_settings_zip(names=None):
    """세팅 파일들을 ZIP 바이트로. names 가 없으면 전부."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for st in list_settings():
            if names and st["name"] not in names:
                continue
            p = SETTINGS_DIR / st["file"]
            z.write(p, p.name)
    return buf.getvalue()


@serialized_setting_write
def import_settings_bytes(data, filename=""):
    """ZIP 이든 낱개 JSON 이든 받아 세팅/ 에 넣는다. 같은 이름은 덮어쓰지 않고 ' (2)' 를 붙인다."""
    import io
    import zipfile
    SETTINGS_DIR.mkdir(exist_ok=True)
    added, skipped = [], []

    def put(stem, raw):
        try:
            d = json.loads(raw.decode("utf-8"))
        except Exception:
            skipped.append(f"{stem}: JSON 이 아닙니다")
            return
        if not (isinstance(d, dict) and d.get("씬")):
            skipped.append(f"{stem}: 세팅 파일이 아닙니다 ('씬' 이 없음)")
            return
        base = _safe_name(d.get("이름") or stem) or "세팅"
        target, k = SETTINGS_DIR / f"{base}.json", 2
        while target.exists():
            target = SETTINGS_DIR / f"{base} ({k}).json"
            k += 1
        if target.stem != base:
            d["이름"] = target.stem          # 파일명과 세팅 이름을 맞춰 둔다
        atomic_write_json(target, d, indent=1, keep_backup=False)
        added.append(target.stem)

    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.lower().endswith(".json") and not n.endswith("/"):
                    put(Path(n).stem, z.read(n))
    else:
        put(Path(filename).stem or "세팅", data)
    return {"ok": bool(added), "added": added, "skipped": skipped}


# ── 자료팩 가져오기 ────────────────────────────────────────────────────────
# 배포본에는 수집물(그림체·레시피·작가통계·예시 그림)을 넣지 않는다 — 용량이 크고
# 남이 공개한 자료라 재배포 조건을 확인하지 않았다. 대신 `배포준비.py --자료팩` 으로
# 따로 묶고, 받는 쪽은 여기로 넣는다.
#
# ⚠ **덮어쓰지 않고 없는 것만 더한다.** 받는 사람이 이미 자기 자료를 갖고 있을 수 있고
#   (사용자는 그림체 1,600건을 따로 정리 중이다), 남의 팩이 그걸 지우면 안 된다.
#   같은 열쇠가 이미 있으면 건너뛰고 몇 건인지 알려 준다.
#
# 자리는 기존 상수를 그대로 쓴다 (STYLE_FILE·RECIPE_FILE·COMBO_FILE·IMG_CACHE·TAG_DIR).
# 새 경로 상수를 만들면 두 곳이 어긋날 수 있다.
def _datapack_lists():
    """{파일이름: (저장위치, 합칠 열쇠)}"""
    return {
        "그림체.json": (STYLE_FILE, "id"),
        "레시피.json": (RECIPE_FILE, "id"),
        "작가조합.json": (COMBO_FILE, "id"),        # 그림체.json 의 구세대 판
        "작가통계.json": (BASE_DIR / "수집" / "작가통계.json", "tag"),
    }


# 새 이미지캐시는 SHA-256 내용주소를 쓰지만, 변환 전 원본 해시를 이름으로 쓴
# 구 자료도 남아 있다. 따라서 가져올 때 실제 바이트를 재어 새 이름과 JSON 참조를
# 함께 맞춘다. 기존 캐시는 참조가 살아 있으므로 자동 일괄 개명하지 않는다.
def _datapack_dirs():
    """{팩 안 경로: (저장위치, 받아들일 확장자)}"""
    return {"수집/이미지캐시": (IMG_CACHE, (".webp", ".png", ".jpg", ".jpeg")),
            "태그": (TAG_DIR, (".csv",))}


def _datapack_whole_files():
    """목록 병합이 아니라 파일 전체가 한 단위인 기본 자료.

    상수 중 SPEC_FILE은 이 함수보다 아래에서 선언되지만, 함수가 실제 호출되는 시점에는
    모듈 초기화가 끝나 있으므로 안전하다.
    """
    return {
        "후보사전.json": BUILDER_FILE,
        "규격.json": SPEC_FILE,
        "옵션.json": OPTIONS_FILE,
    }


def _pack_rel(name):
    """ZIP 안 경로를 우리 폴더 기준 상대경로로. 위험하면 None."""
    parts = [x for x in str(name).replace("\\", "/").split("/") if x not in ("", ".")]
    if any(p == ".." for p in parts) or (parts and ":" in parts[0]):
        return None                      # 경로 탈출·드라이브 지정 차단
    # 팩이 한 겹 더 감싸여 있어도(자료팩/수집/…) 알아보게 앞을 훑는다
    for i, p in enumerate(parts):
        if p in ("수집", "태그", "세팅"):
            return "/".join(parts[i:])
    return "/".join(parts)


def _read_rows(raw):
    """남이 정리한 자료도 읽어 낸다 → (목록, 어떻게 읽었는지) · 못 읽으면 (None, 까닭).

    사람마다 내보내는 모양이 달라서, 흔한 세 가지를 다 받는다:
    ① 그냥 목록 `[...]`  ② 감싼 것 `{"styles":[...]}`  ③ 줄마다 한 건(NDJSON).
    ⚠ 윈도우에서 만든 파일은 **BOM 이 붙어 있는 일이 흔하다**. `utf-8-sig` 로 읽어야
      `json.loads` 가 안 터진다 (이걸 안 하면 멀쩡한 파일이 '깨짐' 으로 나온다)."""
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        try:
            text = raw.decode("cp949")           # 옛 한글 윈도우에서 만든 것
        except Exception:
            return None, "글자를 못 읽었습니다 (UTF-8·CP949 둘 다 아님)"
    text = text.strip()
    if not text:
        return None, "빈 파일입니다"
    try:
        d = json.loads(text)
    except Exception:
        rows, bad = [], 0
        for line in text.splitlines():           # ③ NDJSON
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
        if rows and bad == 0:
            return rows, "줄마다 한 건(NDJSON)"
        return None, "JSON 으로 못 읽었습니다"
    if isinstance(d, list):
        return d, ""
    if isinstance(d, dict):                      # ② 감싼 것 — 가장 큰 목록을 고른다
        best, bk = None, ""
        for k, v in d.items():
            if isinstance(v, list) and (best is None or len(v) > len(best)):
                best, bk = v, k
        if best is not None:
            return best, f"'{bk}' 안의 목록을 꺼냄"
        return None, "목록이 들어 있지 않습니다"
    return None, "목록이 아닙니다"


def _row_key(x, key):
    """합칠 열쇠. 없으면 **내용으로 만들어 준다** — 남이 다르게 정리한 자료도
    버리지 않으면서, 같은 것을 두 번 넣어도 중복이 안 생기게."""
    k = x.get(key)
    if k not in (None, ""):
        return str(k), False
    blob = json.dumps(x, ensure_ascii=False, sort_keys=True)
    return "가져옴-" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12], True


def _merge_list_json(path, incoming, key, overwrite=False):
    """열쇠 기준으로 합친다 → 무슨 일이 있었는지 세어서 돌려준다.

    ⚠ **'못 넣음' 을 '이미 있음' 으로 뭉뚱그리지 않는다.** 예전엔 열쇠 없는 항목이
      조용히 버려지면서 '이미 있음' 으로 세어져, 아무것도 안 들어왔는데 중복인 것처럼
      보였다 (실제로 겪은 거짓 보고다)."""
    old = []
    if path.exists():
        try:
            got = load_json_recover(path)
            old = got if isinstance(got, list) else []
        except Exception:
            # 주 파일과 백업을 둘 다 못 읽으면 빈 목록으로 덮어쓰지 않는다.
            # 사용자가 가진 자료 전체를 "새 파일"로 오인해 날리는 것보다 가져오기를
            # 실패시키는 편이 안전하다.
            raise ValueError(f"{path.name}과 백업을 읽지 못해 가져오기를 중단했습니다.")
    idx = {}
    for i, x in enumerate(old):
        if isinstance(x, dict):
            kk, _ = _row_key(x, key)
            idx.setdefault(kk, i)
    n = {"새로": 0, "같음": 0, "다름": 0, "열쇠없음": 0, "항목아님": 0, "덮어씀": 0}
    added_keys = []
    for x in incoming:
        if not isinstance(x, dict):
            n["항목아님"] += 1
            continue
        kk, made = _row_key(x, key)
        if made:
            n["열쇠없음"] += 1           # 버리진 않는다 — 내용 열쇠로 넣는다
        if kk in idx:
            same = old[idx[kk]] == x
            if same:
                n["같음"] += 1
            elif overwrite:
                old[idx[kk]] = x
                n["덮어씀"] += 1
            else:
                n["다름"] += 1           # 기존 것을 지킨다. 몇 건인지는 알려 준다
            continue
        idx[kk] = len(old)
        old.append(x)
        added_keys.append(kk)
        n["새로"] += 1
    added = n["새로"] + n["덮어씀"]
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, old, indent=None)
    return n, added_keys


def _say_counts(n):
    """센 것을 사람 말로. 0 인 항목은 말하지 않는다 (읽기 어려워진다)."""
    order = [("새로", "새로 {}건"), ("덮어씀", "덮어씀 {}건"), ("같음", "이미 있음 {}건"),
             ("다름", "같은 이름인데 내용이 달라 그대로 둠 {}건"),
             ("열쇠없음", "이름표가 없어 내용으로 넣음 {}건"),
             ("항목아님", "모양이 아니라 건너뜀 {}건")]
    got = [t.format(n[k]) for k, t in order if n.get(k)]
    return " · ".join(got) or "들어온 것 없음"


def _content_image_name(name, raw):
    """자료팩 그림의 이름을 실제 바이트의 SHA-256으로 만든다.

    `local:`은 파일명을 내용 주소로 믿는다. 외부 팩의 이름이 틀렸는데 그대로
    넣으면 같은 이름의 다른 그림을 중복으로 오인하고, JSON 참조도 엉뚱한 바이트를
    가리킨다. 확장자는 화면의 MIME 판별을 위해 원래 허용 확장자를 유지한다.
    """
    suffix = Path(str(name)).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in (".webp", ".png", ".jpg"):
        suffix = ".webp"
    # 이름과 실제 형식이 다르면 이름 쪽을 믿지 않는다. 잘못된 확장자는 /img 의
    # Content-Type까지 틀리게 만들어 브라우저마다 표시 여부가 달라질 수 있다.
    try:
        with Image.open(io.BytesIO(raw)) as image:
            suffix = {
                "WEBP": ".webp", "PNG": ".png", "JPEG": ".jpg",
            }.get((image.format or "").upper(), suffix)
            image.verify()
    except Exception:
        # 자료팩 회귀 시험에는 이미지가 아닌 임의 바이트도 쓰인다. 그 경우에는
        # 기존 허용 확장자를 유지하고, 실제 무결성 검사는 별도 감사에서 막는다.
        pass
    return hashlib.sha256(raw).hexdigest() + suffix


def _rewrite_local_image_refs(value, renamed):
    """자료팩 안의 `local:옛이름`을 실측한 내용 주소로 재귀 치환한다."""
    if isinstance(value, str) and value.startswith("local:"):
        old = Path(value[6:]).name
        return "local:" + renamed.get(old, old)
    if isinstance(value, list):
        return [_rewrite_local_image_refs(x, renamed) for x in value]
    if isinstance(value, dict):
        return {k: _rewrite_local_image_refs(v, renamed) for k, v in value.items()}
    return value


_LOCAL_IMAGE_LOCK = threading.RLock()
_LOCAL_IMAGE_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}


def _collect_local_refs(value, found):
    """JSON 어느 깊이에 있든 local: 참조의 안전한 파일명만 모은다."""
    if isinstance(value, str) and value.startswith("local:"):
        found.append(Path(value[6:]).name)
    elif isinstance(value, list):
        for item in value:
            _collect_local_refs(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_local_refs(item, found)


def _local_image_audit(include_private=False):
    """현재 자료 JSON과 로컬 이미지의 실제 바이트를 서로 대조한다.

    과거 판은 PNG를 WebP로 바꾸기 *전* 바이트의 해시를 파일명으로 썼다.
    따라서 64자리 이름과 현재 바이트 해시가 다르다는 사실만으로 손상이라 하지
    않는다. 실제로 디코드되는지, 참조 파일이 있는지를 별도로 센다.
    """
    collect = BASE_DIR / "수집"
    documents, refs, invalid_json = [], [], []
    for path in sorted(collect.glob("*.json")) if collect.is_dir() else []:
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8-sig"))
            names = []
            _collect_local_refs(value, names)
            documents.append({
                "path": path, "raw": raw, "value": value, "refs": names,
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            refs.extend(names)
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            invalid_json.append({"file": path.name, "error": str(e)})

    files, by_hash, unreadable = {}, {}, []
    total_bytes = 0
    if IMG_CACHE.is_dir():
        for path in sorted(IMG_CACHE.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _LOCAL_IMAGE_SUFFIXES:
                continue
            try:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                canonical = _content_image_name(path.name, raw)
                with Image.open(io.BytesIO(raw)) as image:
                    image.verify()
                valid = True
                error = ""
            except Exception as e:
                raw = b""
                digest = ""
                canonical = ""
                valid = False
                error = str(e)
                unreadable.append({"file": path.name, "error": error})
            size = path.stat().st_size
            total_bytes += size
            files[path.name] = {
                "path": path, "raw": raw, "sha256": digest,
                "canonical": canonical, "valid": valid, "size": size,
            }
            if digest:
                by_hash.setdefault(digest, []).append(path.name)

    unique_refs = sorted(set(refs))
    missing = [name for name in unique_refs if name not in files]
    unreadable_refs = [
        name for name in unique_refs
        if name in files and not files[name]["valid"]
    ]
    mapping = {
        name: files[name]["canonical"]
        for name in unique_refs
        if name in files and files[name]["valid"]
        and name != files[name]["canonical"]
    }
    changed_documents = sum(
        any(name in mapping for name in doc["refs"]) for doc in documents
    )
    copy_names = sorted({
        canonical for canonical in mapping.values() if canonical not in files
    })
    copy_bytes = sum(next(
        files[old]["size"] for old, canonical_name in mapping.items()
        if canonical_name == canonical
    ) for canonical in copy_names)
    referenced = set(unique_refs)
    unreferenced = sorted(set(files) - referenced)
    legacy_names = sorted(
        name for name, info in files.items()
        if info["valid"] and name != info["canonical"]
    )
    duplicate_groups = [names for names in by_hash.values() if len(names) > 1]
    fingerprint_rows = (
        [f"json:{doc['path'].name}:{doc['sha256']}" for doc in documents]
        + [f"img:{name}:{info['sha256']}:{info['size']}"
           for name, info in sorted(files.items())]
    )
    result = {
        "ok": not invalid_json,
        "files": len(files),
        "bytes": total_bytes,
        "references": len(refs),
        "unique_references": len(unique_refs),
        "missing": len(missing),
        "unreadable": len(unreadable),
        "unreadable_references": len(unreadable_refs),
        "legacy_names": len(legacy_names),
        "referenced_legacy_names": len(mapping),
        "unreferenced": len(unreferenced),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_extra_files": sum(len(group) - 1 for group in duplicate_groups),
        "invalid_json": invalid_json,
        "normalization": {
            "references_to_change": sum(refs.count(name) for name in mapping),
            "files_to_copy": len(copy_names),
            "copy_bytes": copy_bytes,
            "documents_to_change": changed_documents,
            "blocked": bool(invalid_json or missing or unreadable_refs),
        },
        "samples": {
            "missing": missing[:12],
            "unreadable": unreadable[:12],
            "legacy_names": legacy_names[:12],
            "unreferenced": unreferenced[:12],
        },
        "fingerprint": hashlib.sha256(
            "\n".join(fingerprint_rows).encode("utf-8")
        ).hexdigest(),
    }
    if include_private:
        result["_documents"] = documents
        result["_files"] = files
        result["_mapping"] = mapping
        result["_copy_names"] = copy_names
    return result


def local_image_integrity():
    """UI/API용 읽기 전용 요약. '미사용'은 삭제 가능 판정이 아님을 명시한다."""
    result = _local_image_audit()
    result["note"] = (
        "과거 이름은 변환 전 해시일 수 있어 손상으로 세지 않습니다. "
        "미사용 후보도 다른 자료팩에서 쓸 수 있으므로 자동 삭제하지 않습니다."
    )
    return result


def _local_image_record_dir(batch):
    return BASE_DIR / "수집" / "이미지무결성기록" / Path(str(batch)).name


@serialized_data_write(lambda: BASE_DIR)
def normalize_local_image_refs(expected_fingerprint=""):
    """참조된 옛 이름만 실제 내용 주소로 바꾼다.

    옛 이미지는 지우거나 옮기지 않는다. 새 내용 주소 파일을 만든 뒤 JSON 원본을
    별도 기록에 보관하고 원자적으로 치환한다. 손상·누락·동시 변경이 있으면 시작
    전에 중단한다.
    """
    with _LOCAL_IMAGE_LOCK:
        audit = _local_image_audit(include_private=True)
        if expected_fingerprint and expected_fingerprint != audit["fingerprint"]:
            return {"ok": False, "error": "검사 뒤 자료가 바뀌었습니다. 다시 검사해 주세요."}
        if audit["normalization"]["blocked"]:
            return {
                "ok": False,
                "error": "누락·읽기 실패·잘못된 JSON이 있어 자동 정리를 중단했습니다.",
                "audit": local_image_integrity(),
            }
        mapping = audit["_mapping"]
        if not mapping:
            return {"ok": True, "batch": "", "changed_references": 0,
                    "changed_documents": 0, "created_files": 0}

        batch = f"{int(time.time())}-{os.urandom(4).hex()}"
        record_dir = _local_image_record_dir(batch)
        before_dir = record_dir / "before"
        before_dir.mkdir(parents=True, exist_ok=False)
        records, plans, created = [], [], []
        try:
            # 원본과 적용 예정 해시를 먼저 기록한다. 기록이 완성되기 전에는 실제
            # 자료 JSON을 한 바이트도 바꾸지 않는다.
            for doc in audit["_documents"]:
                rewritten = _rewrite_local_image_refs(doc["value"], mapping)
                after = json.dumps(
                    rewritten, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                if rewritten == doc["value"]:
                    continue
                backup = before_dir / doc["path"].name
                _atomic_write_bytes(backup, doc["raw"], keep_backup=False)
                records.append({
                    "file": doc["path"].name,
                    "before_sha256": doc["sha256"],
                    "after_sha256": hashlib.sha256(after).hexdigest(),
                })
                plans.append((doc["path"], after))

            for canonical in audit["_copy_names"]:
                old = next(
                    name for name, new_name in mapping.items()
                    if new_name == canonical
                )
                created.append({
                    "name": canonical,
                    "sha256": audit["_files"][old]["sha256"],
                    "source": old,
                })

            journal = {
                "schema": "nais-local-image-normalize/v1",
                "id": batch,
                "at": datetime.now().isoformat(timespec="seconds"),
                "status": "preparing",
                "records": records,
                "created": created,
                "mapping": mapping,
            }
            atomic_write_json(record_dir / "journal.json", journal, indent=1,
                              keep_backup=False)

            # 안전 기록 뒤 새 이름 복사본을 만든다. 옛 이름은 계속 같은 바이트를
            # 가리키므로 외부에 따로 둔 자료팩도 깨지지 않는다.
            for item in created:
                source = audit["_files"][item["source"]]
                target = IMG_CACHE / item["name"]
                if target.exists():
                    if target.read_bytes() != source["raw"]:
                        raise ValueError(f"내용 주소 충돌: {item['name']}")
                    continue
                _atomic_write_bytes(target, source["raw"], keep_backup=False)
            for path, after in plans:
                _atomic_write_bytes(path, after)

            journal["status"] = "complete"
            atomic_write_json(record_dir / "journal.json", journal, indent=1)
        except Exception:
            # JSON 적용 중 실패해도 원본 기록에서 되돌린다. 만들어진 이미지 복사본은
            # 데이터 손실 방지를 위해 기록 폴더로 옮기고 삭제하지 않는다.
            for record in records:
                backup = before_dir / record["file"]
                target = BASE_DIR / "수집" / record["file"]
                if backup.exists():
                    _atomic_write_bytes(target, backup.read_bytes())
            failed = record_dir / "적용실패-복사본"
            failed.mkdir(parents=True, exist_ok=True)
            for item in created:
                target = IMG_CACHE / item["name"]
                if target.exists():
                    os.replace(target, failed / item["name"])
            raise
        forget_collection_caches()
        return {
            "ok": True, "batch": batch,
            "changed_references": audit["normalization"]["references_to_change"],
            "changed_documents": len(records),
            "created_files": len(created),
            "kept_legacy_files": len(mapping),
        }


@serialized_data_write(lambda: BASE_DIR)
def rollback_local_image_normalize(batch):
    """정규화 직후 사용자가 다시 편집한 JSON은 덮지 않고 나머지만 복원한다."""
    with _LOCAL_IMAGE_LOCK:
        record_dir = _local_image_record_dir(batch)
        journal_path = record_dir / "journal.json"
        if not journal_path.is_file():
            return {"ok": False, "error": "되돌릴 이미지 정리 기록을 찾지 못했습니다."}
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("schema") != "nais-local-image-normalize/v1":
            return {"ok": False, "error": "알 수 없는 이미지 정리 기록입니다."}
        if journal.get("status") == "undone":
            return {"ok": True, "restored": 0, "skipped": 0, "already": True}

        restored, skipped = 0, 0
        for record in journal.get("records") or []:
            target = BASE_DIR / "수집" / Path(record.get("file", "")).name
            backup = record_dir / "before" / Path(record.get("file", "")).name
            try:
                current = target.read_bytes()
                if hashlib.sha256(current).hexdigest() != record.get("after_sha256"):
                    skipped += 1
                    continue
                _atomic_write_bytes(target, backup.read_bytes())
                restored += 1
            except OSError:
                skipped += 1

        # 복원 후 아무 JSON도 가리키지 않는 새 복사본만 기록 폴더로 옮긴다.
        live_refs, refs_complete = [], True
        for path in (BASE_DIR / "수집").glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                _collect_local_refs(value, live_refs)
            except Exception:
                refs_complete = False
        live_refs = set(live_refs)
        held_dir = record_dir / "되돌린-새이름"
        held = 0
        for item in journal.get("created") or []:
            name = Path(item.get("name", "")).name
            target = IMG_CACHE / name
            if not refs_complete or name in live_refs or not target.is_file():
                continue
            try:
                if hashlib.sha256(target.read_bytes()).hexdigest() != item.get("sha256"):
                    continue
                held_dir.mkdir(parents=True, exist_ok=True)
                os.replace(target, held_dir / name)
                held += 1
            except OSError:
                pass
        journal.update(status="undone", undone_at=datetime.now().isoformat(
            timespec="seconds"), restored=restored, skipped=skipped,
                       held_created=held)
        atomic_write_json(journal_path, journal, indent=1)
        forget_collection_caches()
        return {"ok": True, "restored": restored, "skipped": skipped,
                "held_created": held}


def forget_collection_caches():
    """자료가 늘었으니 한 번 읽고 물고 있던 것들을 놓게 한다.
    `load_combos()`·`load_recipes()` 는 `loaded` 깃발을 보고 다시 읽고,
    자동완성 색인은 `_TAG_CACHE` 를 비우면 다음 호출에 다시 만든다."""
    with _COMBOS_LOCK:
        _COMBOS["loaded"] = False
    _RECIPES["loaded"] = False
    try:
        _TAG_CACHE.clear()
    except Exception:
        pass


def _pack_log_path():
    return BASE_DIR / "수집" / "가져온기록.json"


def load_pack_log():
    p = _pack_log_path()
    if p.exists():
        try:
            d = load_json_recover(p)
            return d if isinstance(d, list) else []
        except Exception:
            return []
    return []


def save_pack_log(rows):
    p = _pack_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, rows[-50:], indent=1)


DATAPACK_SCHEMA = "nais-datapack/v1"
DATA_INDEX_SCHEMA = "nais-data-index/v1"


def _data_index_path():
    return BASE_DIR / "수집" / "자료색인.json"


def _iter_indexed_data_files():
    """다시 만들 수 있는 캐시·기록은 빼고 실제 자료 파일만 순회한다."""
    roots = [
        BASE_DIR / name for name in (
            "후보사전.json", "규격.json", "옵션.json",
            "태그", "세팅", "캐릭터", "그림체", "씬규격", "씬프리셋", "조각", "수집",
        )
    ]
    blocked_parts = {
        "원격", "가져온백업", "이미지무결성기록", "사용자복원기록",
        "__pycache__", ".NAI-휴지통",
    }
    blocked_names = {
        "자료색인.json", "가져온기록.json", "태그색인.pickle",
    }
    seen = set()
    for root in roots:
        candidates = [root] if root.is_file() else (
            sorted(root.rglob("*")) if root.is_dir() else [])
        for path in candidates:
            if (not path.is_file() or path.is_symlink()
                    or path.name in blocked_names):
                continue
            try:
                if BASE_DIR.resolve() not in path.resolve().parents:
                    continue
            except OSError:
                continue
            rel = path.relative_to(BASE_DIR)
            if any(part in blocked_parts for part in rel.parts):
                continue
            if path.suffix.lower() in (".bak", ".tmp", ".log", ".pyc", ".pickle"):
                continue
            key = rel.as_posix()
            if key in seen:
                continue
            seen.add(key)
            yield path, key


def rebuild_data_index():
    """현재 개인 자료를 파일별 SHA-256으로 다시 센다.

    색인은 원본이 아니라 파생 목록이다. 지워져도 원자료를 다시 훑어 만들 수 있다.
    """
    entries, by_root, total = [], {}, 0
    for path, rel in _iter_indexed_data_files():
        if len(entries) >= 250_000:
            raise ValueError("자료 파일이 250,000개를 넘어 색인 생성을 중단했습니다.")
        raw = path.read_bytes()
        size = len(raw)
        digest = hashlib.sha256(raw).hexdigest()
        top = rel.split("/", 1)[0]
        stat = by_root.setdefault(top, {"files": 0, "bytes": 0})
        stat["files"] += 1
        stat["bytes"] += size
        total += size
        entries.append({"path": rel, "size": size, "sha256": digest})
    fingerprint = hashlib.sha256("\n".join(
        f"{item['path']}\t{item['size']}\t{item['sha256']}" for item in entries
    ).encode("utf-8")).hexdigest()
    index = {
        "schema": DATA_INDEX_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_dir": str(BASE_DIR),
        "files": len(entries),
        "bytes": total,
        "by_root": by_root,
        "fingerprint": fingerprint,
        "entries": entries,
    }
    atomic_write_json(_data_index_path(), index, indent=1, keep_backup=False)
    return index


def data_storage_status():
    """화면용 저장 위치와 마지막 색인 요약. 토큰·프롬프트 내용은 내보내지 않는다."""
    index = None
    path = _data_index_path()
    if path.is_file():
        try:
            loaded = load_json_recover(path)
            if isinstance(loaded, dict) and loaded.get("schema") == DATA_INDEX_SCHEMA:
                index = {key: loaded.get(key) for key in (
                    "generated_at", "files", "bytes", "by_root", "fingerprint")}
        except Exception:
            pass
    return {
        "ok": True,
        "program_dir": str(PROGRAM_DIR),
        "data_dir": str(BASE_DIR),
        "separated": PROGRAM_DIR.resolve() != BASE_DIR.resolve(),
        "profile": PROFILE or "기본",
        "migration": {
            key: _DATA_MIGRATION.get(key)
            for key in ("status", "copied", "skipped", "conflicts")
        },
        "index": index,
    }


def _validate_datapack_manifest(archive):
    """v1 manifest가 있으면 쓰기 전에 파일 수·크기·내용 해시를 전부 확인한다.

    manifest가 없는 예전 자료팩은 계속 받는다. 다만 manifest가 있다고 주장한 팩은
    한 파일이라도 빠지거나 달라졌으면 일부만 설치하지 않고 전체를 거절한다.
    """
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > 100_000:
        raise ValueError("자료팩 파일 수가 비정상적으로 많습니다.")
    if any(info.file_size > 512 * 1024 * 1024 for info in infos):
        raise ValueError("자료팩의 낱개 파일이 512MB를 넘습니다.")
    if sum(info.file_size for info in infos) > 2 * 1024 * 1024 * 1024:
        raise ValueError("자료팩을 풀었을 때 크기가 2GB를 넘습니다.")

    members = {}
    manifest_name = None
    for info in infos:
        rel = _pack_rel(info.filename)
        if rel is None:
            raise ValueError("자료팩에 앱 폴더 밖을 가리키는 경로가 있습니다.")
        if rel in members:
            raise ValueError(f"자료팩에 같은 경로가 두 번 있습니다: {rel}")
        members[rel] = info.filename
        if Path(rel).name == "manifest.json" and "/" not in rel:
            manifest_name = info.filename
    if not manifest_name:
        return None
    try:
        manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"))
    except Exception as e:
        raise ValueError(f"자료팩 manifest.json을 읽지 못했습니다: {e}") from e
    if manifest.get("schema") != DATAPACK_SCHEMA:
        # 다른 도구가 넣은 일반 manifest는 기존 자료팩 호환을 위해 무시한다.
        return None

    declared, fingerprint_rows = set(), []
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("자료팩 manifest의 files가 목록이 아닙니다.")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("자료팩 manifest의 파일 항목 모양이 잘못됐습니다.")
        rel = _pack_rel(entry.get("path", ""))
        if not rel or rel == "manifest.json" or rel in declared:
            raise ValueError("자료팩 manifest에 위험하거나 중복된 경로가 있습니다.")
        member = members.get(rel)
        if not member:
            raise ValueError(f"자료팩 내용이 빠졌습니다: {rel}")
        raw = archive.read(member)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != int(entry.get("size", -1)) or digest != entry.get("sha256"):
            raise ValueError(f"자료팩 내용 검사가 실패했습니다: {rel}")
        declared.add(rel)
        fingerprint_rows.append(f"{rel}\t{len(raw)}\t{digest}")
    fingerprint = hashlib.sha256(
        "\n".join(sorted(fingerprint_rows)).encode("utf-8")
    ).hexdigest()
    if manifest.get("content_sha256") != fingerprint:
        raise ValueError("자료팩 전체 내용 지문이 manifest와 다릅니다.")

    # manifest 밖에 숨은 자료 파일이 있으면 검사를 우회할 수 있다. 사용법 문서처럼
    # 앱이 읽지 않는 파일은 허용하지만, 실제 장착 대상은 모두 선언돼야 한다.
    known_lists = set(_datapack_lists())
    known_whole = set(_datapack_whole_files())
    for rel in members:
        stem = Path(rel).name
        is_data = (
            stem in known_lists
            or stem in known_whole
            or rel.startswith(("세팅/", "태그/", "수집/이미지캐시/"))
        )
        if is_data and rel not in declared:
            raise ValueError(f"manifest에 기록되지 않은 자료가 들어 있습니다: {rel}")
    return {
        "id": str(manifest.get("id") or ""),
        "name": str(manifest.get("name") or ""),
        "version": str(manifest.get("version") or ""),
        "content_sha256": fingerprint,
        "files": len(declared),
    }


@serialized_data_write(lambda: BASE_DIR)
def import_datapack_bytes(data, filename="", overwrite=False):
    """자료팩 ZIP 이든 낱개 JSON 이든 받아 자료 종류별 제자리에 넣는다.

    무엇이 들어왔는지 `수집/가져온기록.json` 에 남겨 **통째로 되돌릴 수 있게** 한다.
    자료를 넣고 나서 정리하려면 '무엇이 이번에 들어왔나' 를 알아야 하기 때문이다."""
    import io
    import zipfile
    lists, dirs, whole = _datapack_lists(), _datapack_dirs(), _datapack_whole_files()
    report, files = [], 0
    batch_id = f"{int(time.time())}-{os.urandom(4).hex()}"
    batch = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "file": Path(filename).name or "자료팩",
              "id": batch_id, "lists": {}, "files": {}, "installed": [],
              "archive_sha256": hashlib.sha256(data).hexdigest()}

    def take_whole(label, raw, dest):
        """후보사전·규격·옵션·세팅 파일 하나를 검증한 뒤 원자적으로 설치한다.

        덮어쓸 때는 가져온 판 전용 백업을 따로 남긴다. 되돌릴 때 현재 파일이
        그 뒤 수정되지 않았을 때만 복구하므로, 자료팩 뒤의 사용자 편집을 덮지 않는다.
        """
        nonlocal files
        try:
            parsed = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            report.append(f"{label}: JSON으로 읽지 못해 건너뜀")
            return True
        if not isinstance(parsed, dict):
            report.append(f"{label}: JSON 객체가 아니라 건너뜀")
            return True
        canonical = json.dumps(parsed, ensure_ascii=False, indent=1).encode("utf-8")
        rel = dest.relative_to(BASE_DIR).as_posix()
        digest = hashlib.sha256(canonical).hexdigest()
        if dest.exists():
            try:
                same = load_json_recover(dest) == parsed
            except Exception:
                same = False
            if same:
                report.append(f"{label}: 이미 같은 자료가 있음")
                return True
            if not overwrite:
                report.append(f"{label}: 기존 자료가 달라 그대로 둠")
                return True
            backup = BASE_DIR / "수집" / "가져온백업" / batch_id / rel
            _atomic_write_bytes(backup, dest.read_bytes(), keep_backup=False)
            _atomic_write_bytes(dest, canonical)
            batch["installed"].append({
                "path": rel, "backup": backup.relative_to(BASE_DIR).as_posix(),
                "sha256": digest,
            })
            report.append(f"{label}: 기존 자료를 백업하고 새 것으로 바꿈")
        else:
            _atomic_write_bytes(dest, canonical, keep_backup=False)
            batch["installed"].append({"path": rel, "sha256": digest})
            report.append(f"{label}: 새로 넣음")
        files += 1
        return True

    local_image_renames = {}

    def take_list(stem, raw):
        nonlocal files
        spot = lists.get(stem)
        if not spot:
            return False
        dest, key = spot
        rows, how = _read_rows(raw)
        if rows is None:
            report.append(f"{stem}: {how}")
            return True
        if local_image_renames:
            rows = _rewrite_local_image_refs(rows, local_image_renames)
        n, keys = _merge_list_json(dest, rows, key, overwrite)
        report.append(f"{stem}: {_say_counts(n)}" + (f" ({how})" if how else ""))
        if keys:
            batch["lists"][stem] = keys
        files += n["새로"] + n["덮어씀"]
        return True

    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            manifest = _validate_datapack_manifest(z)
            if manifest:
                batch["manifest"] = manifest
                report.append(
                    f"자료팩 확인: {manifest['name'] or manifest['id'] or '이름 없음'}"
                    f" · 파일 {manifest['files']}개 · SHA-256 "
                    f"{manifest['content_sha256'][:12]}"
                )
            # ZIP 순서와 무관하게 목록 JSON을 읽기 전에 모든 로컬 그림의 실제
            # 내용 주소를 계산한다. 그래야 JSON이 그림보다 앞에 있어도 참조를 고친다.
            image_payloads = {}
            for n in z.namelist():
                if n.endswith("/"):
                    continue
                rel = _pack_rel(n)
                if rel is None or not rel.startswith("수집/이미지캐시/"):
                    continue
                stem = Path(rel).name
                if Path(stem).suffix.lower() not in dirs["수집/이미지캐시"][1]:
                    continue
                raw = z.read(n)
                correct = _content_image_name(stem, raw)
                local_image_renames[stem] = correct
                image_payloads[n] = (raw, correct)

            copied, skipped, renamed = {}, {}, 0
            for n in z.namelist():
                if n.endswith("/"):
                    continue
                rel = _pack_rel(n)
                if rel is None:
                    continue
                stem = Path(rel).name
                if stem in lists:
                    take_list(stem, z.read(n))
                    continue
                if stem in whole and not rel.startswith("세팅/"):
                    take_whole(stem, z.read(n), whole[stem])
                    continue
                if rel.startswith("세팅/") and stem.lower().endswith(".json"):
                    take_whole(f"세팅/{stem}", z.read(n), SETTINGS_DIR / stem)
                    continue
                for d, (root, exts) in dirs.items():
                    if rel.startswith(d + "/") and stem.lower().endswith(exts):
                        raw, saved_name = image_payloads.get(
                            n, (z.read(n), stem))
                        if d == "수집/이미지캐시" and saved_name != stem:
                            renamed += 1
                        dest = root / saved_name
                        if dest.exists() and dest.read_bytes() == raw:
                            skipped[d] = skipped.get(d, 0) + 1
                        elif dest.exists():
                            # 내용 주소와 실제 바이트가 다른 기존 파일은 없애지 않는다.
                            # 판 전용 백업에 보존하고, 되돌릴 때 복구할 수 있게 기록한다.
                            rel_dest = dest.relative_to(BASE_DIR).as_posix()
                            backup = BASE_DIR / "수집" / "가져온백업" / batch_id / rel_dest
                            _atomic_write_bytes(
                                backup, dest.read_bytes(), keep_backup=False)
                            _atomic_write_bytes(dest, raw, keep_backup=False)
                            copied[d] = copied.get(d, 0) + 1
                            batch["installed"].append({
                                "path": rel_dest,
                                "backup": backup.relative_to(BASE_DIR).as_posix(),
                                "sha256": hashlib.sha256(raw).hexdigest(),
                            })
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            _atomic_write_bytes(
                                dest, raw, keep_backup=False)
                            copied[d] = copied.get(d, 0) + 1
                            batch["files"].setdefault(d, []).append(saved_name)
                        break
            for d in dirs:
                c, s = copied.get(d, 0), skipped.get(d, 0)
                if c or s:
                    files += c
                    report.append(f"{d}: 새로 {c}개" + (f" · 이미 있음 {s}개" if s else ""))
            if renamed:
                report.append(f"이미지 내용 주소: 이름이 달랐던 {renamed}개를 바로잡음")
    else:
        stem = Path(filename).name
        if stem in whole:
            take_whole(stem, data, whole[stem])
        elif not take_list(stem, data):
            return {"ok": False,
                    "error": f"'{stem}' 은(는) 자료팩이 아닙니다. "
                             f"자료팩.zip 이나 {' · '.join(list(lists) + list(whole))} 를 넣어 주세요."}

    if not report:
        return {"ok": False, "error": "자료팩에서 알아볼 수 있는 자료를 못 찾았습니다."}
    # 알아본 자료가 있으면 성공이다. 같은 팩을 다시 넣어 **전부 중복이어도 실패가 아니다**
    # (`files` 는 새로 들어온 수이므로 0 일 수 있다). 새 것이 있었는지는 따로 알려 준다.
    if batch["lists"] or batch["files"] or batch["installed"]:
        rows = load_pack_log()
        # ⚠ 판 id 는 **초 단위 시간만으로 지으면 안 된다.** 화면의 `sendPack` 은 여러 파일을
        #   반복문으로 잇달아 넣으므로 두 파일을 함께 끌어다 놓으면 **같은 초**에 들어가
        #   id 가 겹친다. 겹치면 `undo_datapack` 이 먼저 들어온 판을 집어 **엉뚱한 자료를
        #   지우고**, 기록에서 겹친 판이 함께 빠져 나머지를 **영영 되돌릴 수 없게** 된다
        #   (되돌리기에는 휴지통이 없다). 그래서 시간 뒤에 난수를 붙인다 —
        #   앞의 시간은 사람이 읽고 정렬하기 위한 것이고, 겹침을 막는 것은 뒤의 난수다.
        #   `random` 이 아니라 `os.urandom` 을 쓰는 것은 **프로필 두 개를 나란히 돌려도**
        #   (서로 다른 프로세스) 겹치지 않게 하기 위해서다.
        #   옛 기록의 숫자만 있는 id 도 그대로 읽히고 되돌려진다 (문자열로 견준다).
        batch["새로"] = files
        batch["요약"] = " · ".join(report)
        rows.append(batch)
        save_pack_log(rows)
    return {"ok": True, "added": files, "report": report,
            "batch": batch.get("id"), "log": pack_log_brief()}


def pack_log_brief():
    """되돌리기 화면용 — 큰 id 목록은 빼고 요약만."""
    return [{"id": b.get("id"), "at": b.get("at"), "file": b.get("file"),
             "새로": b.get("새로", 0), "요약": b.get("요약", ""),
             "pack_id": (b.get("manifest") or {}).get("id", ""),
             "pack_name": (b.get("manifest") or {}).get("name", ""),
             "content_sha256": (b.get("manifest") or {}).get(
                 "content_sha256", b.get("archive_sha256", ""))}
            for b in reversed(load_pack_log())]


@serialized_data_write(lambda: BASE_DIR)
def undo_datapack(batch_id):
    """가져온 것을 통째로 되돌린다 — **그때 새로 들어온 것만** 지운다.
    원래 갖고 있던 자료는 건드리지 않는다(열쇠를 그때 기록해 뒀다)."""
    rows = load_pack_log()
    hit = next((b for b in rows if str(b.get("id")) == str(batch_id)), None)
    if not hit:
        return {"ok": False, "error": "그 기록을 못 찾았습니다."}
    lists, dirs = _datapack_lists(), _datapack_dirs()
    said = []
    for stem, keys in (hit.get("lists") or {}).items():
        spot = lists.get(stem)
        if not spot or not keys:
            continue
        path, key = spot
        if not path.exists():
            continue
        try:
            old = load_json_recover(path)
        except Exception:
            continue
        drop = set(map(str, keys))
        kept = [x for x in old
                if not (isinstance(x, dict) and _row_key(x, key)[0] in drop)]
        gone = len(old) - len(kept)
        if gone:
            atomic_write_json(path, kept, indent=None)
            said.append(f"{stem}: {gone}건 뺌")
    for d, names in (hit.get("files") or {}).items():
        root = dirs.get(d, (None, ()))[0]
        if not root:
            continue
        gone = 0
        for nm in names:
            p = root / nm
            try:
                if p.exists():
                    # 가져온 판을 되돌릴 때도 즉시 삭제하지 않는다. 잘못 고른 판이면
                    # 같은 폴더의 목록 밖 백업에서 원본 파일을 되찾을 수 있다.
                    recoverable_remove(p, label="자료팩되돌리기")
                    gone += 1
            except Exception:
                pass
        if gone:
            said.append(f"{d}: {gone}개 지움")
    for item in reversed(hit.get("installed") or []):
        try:
            rel = Path(item.get("path", ""))
            dest = (BASE_DIR / rel).resolve()
            # 기록 파일을 사람이 고쳐도 앱 폴더 밖은 절대 만지지 않는다.
            if BASE_DIR.resolve() not in dest.parents:
                continue
            if not dest.exists():
                continue
            current = hashlib.sha256(dest.read_bytes()).hexdigest()
            if current != item.get("sha256"):
                said.append(f"{rel.as_posix()}: 가져온 뒤 수정되어 그대로 둠")
                continue
            backup_rel = item.get("backup")
            if backup_rel:
                backup = (BASE_DIR / backup_rel).resolve()
                if backup.exists() and BASE_DIR.resolve() in backup.parents:
                    _atomic_write_bytes(dest, backup.read_bytes())
                    backup.unlink()
                    said.append(f"{rel.as_posix()}: 이전 자료 복구")
            else:
                recoverable_remove(dest, label="자료팩되돌리기")
                said.append(f"{rel.as_posix()}: 가져온 파일 뺌")
        except Exception as e:
            log.warning(f"자료팩 전체파일 되돌리기 실패: {e}")
    # ⚠ **되돌린 그 판만** 뺀다. 예전에는 id 가 같은 것을 모두 걸러냈는데,
    #   이미 겹쳐 있는 옛 기록(위 참조)에서는 손대지도 않은 판의 기록까지 사라져
    #   그 자료를 **영영 되돌릴 수 없게** 됐다. 객체로 견주면 옛 기록도 한 번에 한 판씩
    #   차례로 되돌릴 수 있다.
    save_pack_log([b for b in rows if b is not hit])
    forget_collection_caches()
    return {"ok": True, "report": said or ["되돌릴 것이 없었습니다"],
            "log": pack_log_brief()}


# ══ 내 자료 전체 백업 ═════════════════════════════════════════════════
BACKUP_SCHEMA = "nais-user-backup/v1"
BACKUP_SECRET_KEYS = {"token", "booru_keys", "out_dir"}


def _backup_clean_settings(raw):
    data = dict(raw or {}) if isinstance(raw, dict) else {}
    for key in BACKUP_SECRET_KEYS:
        data.pop(key, None)
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def _backup_sources(cfg):
    """토큰·생성물·재생성 가능한 캐시를 빼고 사용자 원본만 모은다."""
    files = {}

    def put(logical, path):
        try:
            if path.is_file() and not path.name.endswith((".bak", ".tmp")):
                files[logical] = path.read_bytes()
        except OSError as e:
            log.warning("백업에서 건너뜀 %s: %s", path, e)

    def tree(prefix, root, skip=()):
        if not root.is_dir():
            return
        resolved = root.resolve()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.endswith((".bak", ".tmp")):
                continue
            rel = path.relative_to(root)
            if any(part in skip for part in rel.parts):
                continue
            try:
                if resolved not in path.resolve().parents:
                    continue
            except OSError:
                continue
            put(f"common/{prefix}/{rel.as_posix()}", path)

    for name, path in (("후보사전.json", BUILDER_FILE), ("규격.json", SPEC_FILE),
                       ("옵션.json", OPTIONS_FILE)):
        put(f"common/{name}", path)
    for prefix, root in (
        ("태그", TAG_DIR), ("세팅", SETTINGS_DIR), ("씬규격", SCHEMA_DIR),
        ("씬프리셋", SCENESET_DIR), ("그림체", STYLE_DIR),
        ("캐릭터", CHAR_DIR), ("조각", FRAG_DIR), ("수집/바이브", VIBE_DIR),
    ):
        tree(prefix, root)
    collect = BASE_DIR / "수집"
    if collect.is_dir():
        for path in sorted(collect.glob("*.json")):
            put(f"common/수집/{path.name}", path)
        # local: 그림은 원본 자료다. 다시 받을 수 있는 원격/ 하위만 캐시로 제외한다.
        tree("수집/이미지캐시", collect / "이미지캐시", skip=("원격",))
    files["profile/설정.json"] = _backup_clean_settings(cfg)
    for name, path in (("선별.json", PICKS_FILE), ("씬.json", SCENES_FILE)):
        put(f"profile/{name}", path)
    return files


def export_user_backup(cfg):
    payloads = _backup_sources(cfg)
    manifest = {
        "schema": BACKUP_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile": PROFILE or "기본",
        "files": [{"path": p, "size": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest()}
                  for p, raw in sorted(payloads.items())],
        "excluded": ["API 토큰", "생성 결과(output)", "로그·진행상태",
                     "태그 검색 색인", "다운로드한 원격 이미지 캐시",
                     "자료팩 되돌리기 임시백업"],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        for logical, raw in sorted(payloads.items()):
            z.writestr("data/" + logical, raw)
    return out.getvalue()


def _backup_safe_logical(value):
    value = str(value or "").replace("\\", "/").strip("/")
    parts = value.split("/") if value else []
    if (len(parts) < 2 or parts[0] not in ("common", "profile")
            or any(p in ("", ".", "..") or ":" in p for p in parts)):
        return None
    return "/".join(parts)


def _read_user_backup(blob):
    if not blob.startswith(b"PK"):
        raise ValueError("NAI 사용자 백업 ZIP이 아닙니다.")
    archive_sha = hashlib.sha256(blob).hexdigest()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        infos = [x for x in z.infolist() if not x.is_dir()]
        if len(infos) > 50000 or sum(x.file_size for x in infos) > 1024 ** 3:
            raise ValueError("백업의 파일 수나 압축 해제 크기가 비정상적입니다.")
        try:
            manifest = json.loads(z.read("manifest.json"))
        except Exception as e:
            raise ValueError(f"manifest.json을 읽지 못했습니다: {e}") from e
        if manifest.get("schema") != BACKUP_SCHEMA:
            raise ValueError("지원하지 않는 백업 형식입니다.")
        payloads, seen = {}, set()
        for entry in manifest.get("files") or []:
            logical = _backup_safe_logical(entry.get("path"))
            if not logical or logical in seen:
                raise ValueError("백업 manifest에 위험하거나 중복된 경로가 있습니다.")
            seen.add(logical)
            try:
                raw = z.read("data/" + logical)
            except KeyError as e:
                raise ValueError(f"백업 내용이 빠졌습니다: {logical}") from e
            if (len(raw) != int(entry.get("size", -1))
                    or hashlib.sha256(raw).hexdigest() != entry.get("sha256")):
                raise ValueError(f"백업 내용 검사가 실패했습니다: {logical}")
            payloads[logical] = raw
    return manifest, payloads, archive_sha


def _backup_destination(logical):
    logical = _backup_safe_logical(logical)
    if not logical:
        raise ValueError("위험한 백업 경로입니다.")
    scope, rel = logical.split("/", 1)
    if scope == "profile":
        if rel not in {"설정.json", "선별.json", "씬.json"}:
            raise ValueError(f"허용하지 않는 프로필 자료입니다: {rel}")
        root = PROFILE_DIR.resolve()
    else:
        allowed_files = {"후보사전.json", "규격.json", "옵션.json"}
        allowed_dirs = {"태그", "세팅", "씬규격", "씬프리셋", "그림체",
                        "캐릭터", "조각", "수집"}
        if rel not in allowed_files and rel.split("/", 1)[0] not in allowed_dirs:
            raise ValueError(f"허용하지 않는 공용 자료입니다: {rel}")
        root = BASE_DIR.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("백업 경로가 앱 자료 폴더를 벗어납니다.")
    return target


def _backup_merge_secrets(logical, raw, target):
    if logical != "profile/설정.json":
        return raw
    incoming = json.loads(raw.decode("utf-8"))
    current = {}
    if target.is_file():
        try:
            current = load_json_recover(target)
        except Exception:
            pass
    for key in BACKUP_SECRET_KEYS:
        if key in current:
            incoming[key] = current[key]
    return json.dumps(incoming, ensure_ascii=False, indent=1).encode("utf-8")


def preview_user_backup(blob):
    manifest, payloads, archive_sha = _read_user_backup(blob)
    counts = {"새 파일": 0, "바뀔 파일": 0, "같은 파일": 0}
    total = 0
    for logical, raw in payloads.items():
        target = _backup_destination(logical)
        wanted = _backup_merge_secrets(logical, raw, target)
        total += len(wanted)
        if not target.exists():
            counts["새 파일"] += 1
        elif target.read_bytes() == wanted:
            counts["같은 파일"] += 1
        else:
            counts["바뀔 파일"] += 1
    return {"ok": True, "sha256": archive_sha, "files": len(payloads),
            "bytes": total, "counts": counts, "created_at": manifest.get("created_at"),
            "profile": manifest.get("profile"), "excluded": manifest.get("excluded") or []}


@serialized_data_write(lambda: BASE_DIR)
def restore_user_backup(blob, expected_sha=""):
    manifest, payloads, archive_sha = _read_user_backup(blob)
    if expected_sha and expected_sha != archive_sha:
        return {"ok": False, "error": "미리보기한 백업과 복원할 백업이 다릅니다."}
    batch = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    journal = PROFILE_DIR / "복원기록" / batch
    operations = []
    for logical, raw in sorted(payloads.items()):
        target = _backup_destination(logical)
        wanted = _backup_merge_secrets(logical, raw, target)
        old = target.read_bytes() if target.is_file() else None
        if old == wanted:
            continue
        op = {"path": logical, "new": old is None,
              "applied_sha256": hashlib.sha256(wanted).hexdigest()}
        if old is not None:
            saved = (_backup_clean_settings(json.loads(old))
                     if logical == "profile/설정.json" else old)
            _atomic_write_bytes(journal / "before" / logical, saved, keep_backup=False)
        operations.append((op, target, wanted))
    record = {"schema": "nais-restore-journal/v1", "id": batch,
              "backup_sha256": archive_sha, "status": "ready",
              "operations": [x[0] for x in operations], "completed": []}
    atomic_write_json(journal / "journal.json", record, indent=1, keep_backup=False)
    try:
        record["status"] = "applying"
        atomic_write_json(journal / "journal.json", record, indent=1, keep_backup=False)
        for op, target, wanted in operations:
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(target, wanted)
            record["completed"].append(op["path"])
            atomic_write_json(journal / "journal.json", record, indent=1, keep_backup=False)
    except Exception:
        rollback_user_backup(batch)
        raise
    record.update(status="complete",
                  completed_at=datetime.now().isoformat(timespec="seconds"))
    atomic_write_json(journal / "journal.json", record, indent=1, keep_backup=False)
    forget_collection_caches()
    return {"ok": True, "batch": batch, "changed": len(operations),
            "files": len(payloads)}


@serialized_data_write(lambda: BASE_DIR)
def rollback_user_backup(batch_id):
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", str(batch_id or "")):
        return {"ok": False, "error": "복원 기록 번호가 올바르지 않습니다."}
    root = (PROFILE_DIR / "복원기록").resolve()
    journal = (root / str(batch_id)).resolve()
    if root not in journal.parents or not (journal / "journal.json").is_file():
        return {"ok": False, "error": "복원 기록을 찾지 못했습니다."}
    record = load_json_recover(journal / "journal.json")
    if record.get("status") == "rolled_back":
        return {"ok": False, "error": "이미 되돌린 복원입니다."}
    done, restored, skipped = set(record.get("completed") or []), 0, 0
    for op in reversed(record.get("operations") or []):
        logical = op.get("path")
        if logical not in done:
            continue
        target = _backup_destination(logical)
        if (not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest()
                != op.get("applied_sha256")):
            # 복원 뒤 사용자가 다시 고친 파일은 옛 상태로 덮어쓰지 않는다.
            skipped += 1
            continue
        if op.get("new"):
            recoverable_remove(target, label="복원취소")
            restored += 1
        else:
            saved = journal / "before" / logical
            if saved.is_file():
                raw = _backup_merge_secrets(logical, saved.read_bytes(), target)
                _atomic_write_bytes(target, raw)
                restored += 1
    record.update(status="rolled_back",
                  rolled_back_at=datetime.now().isoformat(timespec="seconds"))
    atomic_write_json(journal / "journal.json", record, indent=1)
    forget_collection_caches()
    return {"ok": True, "restored": restored, "skipped": skipped}


def setting_path(name):
    for p in (SETTINGS_DIR.glob("*.json") if SETTINGS_DIR.exists() else []):
        try:
            d = load_json_recover(p)
            if (d.get("이름") or p.stem) == name:
                return p
        except Exception:
            continue
    return None


def ensure_schema_split():
    """구버전 asset_config.json + 옵션.json → 씬규격/ 3종으로 1회 분리"""
    if SCHEMA_DIR.exists() or not CONFIG_FILE.exists():
        return
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            old = json.load(f)
    except Exception as e:
        log.warning(f"asset_config.json 분리 실패: {e}")
        return
    buckets = {"체위": {}, "표정": {}, "백합": {}}
    for k, sc in old.get("scenes", {}).items():
        if not k.isdigit():
            continue
        n = int(k)
        if sc.get("pair") == "yuri" or n >= 800:
            buckets["백합"][k] = sc
        elif n < 101:
            buckets["표정"][k] = sc
        else:
            buckets["체위"][k] = sc
    opts = {
        "체위": {"장소테마": OPTIONS.get("장소테마", {}), "시간대": OPTIONS.get("시간대", {}),
                "표정진행": OPTIONS.get("표정진행", {})},
        "표정": {},
        "백합": {"탈의단계": OPTIONS.get("탈의단계", {})},
    }
    for kind in KINDS:
        d = SCHEMA_DIR / kind
        d.mkdir(parents=True, exist_ok=True)
        data = {"종류": kind, "씬": buckets[kind], "옵션": opts[kind]}
        atomic_write_json(d / "기본.json", data, keep_backup=False)
    log.info(f"씬 규격 분리 완료: 체위 {len(buckets['체위'])} / 표정 {len(buckets['표정'])} / 백합 {len(buckets['백합'])}씬")


def kind_pack_path(cfg, kind):
    key = {"체위": "pack_pos", "표정": "pack_expr", "백합": "pack_yuri"}[kind]
    name = (cfg or {}).get(key) or "기본.json"
    p = SCHEMA_DIR / kind / name
    if not p.exists():
        p = SCHEMA_DIR / kind / "기본.json"
    return p


def load_kind(cfg, kind):
    p = kind_pack_path(cfg, kind)
    if not p.exists():
        return {"종류": kind, "씬": {}, "옵션": {}}
    try:
        data = load_json_recover(p)
        # 다른 프로그램 형식 관용: scenes 키도 인정
        if "씬" not in data and "scenes" in data:
            data["씬"] = data["scenes"]
        return data
    except Exception as e:
        log.warning(f"{kind} 규격 로드 실패({p.name}): {e}")
        return {"종류": kind, "씬": {}, "옵션": {}}


def list_kind_packs(kind):
    packs = []
    d = SCHEMA_DIR / kind
    if d.exists():
        for p in sorted(d.glob("*.json")):
            packs.append({"file": p.name, "name": p.stem})
    return packs


def derive_setting_catalog(scenes_dict):
    """한 세팅의 씬들 → 세트 묶음 목록. 묶음 규칙: 이름 마지막 단어(단계명)를 뗀 나머지가 같으면 한 세트.
    단일 씬(표정 등)은 1개짜리 세트가 된다."""
    groups, seen = [], {}
    for k in sorted(int(x) for x in scenes_dict if str(x).isdigit()):
        sc = scenes_dict[str(k)]
        name = sc.get("name", str(k))
        gkey = name.rsplit(" ", 1)[0] if " " in name else name
        cat = sc.get("category", "")
        key = (cat, gkey)
        if key in seen and len(name.split()) > 1:
            seen[key]["ids"].append(k)
        else:
            g = {"id": k, "ids": [k], "cat": cat, "label": gkey,
                 "mood": sc.get("mood", "")}
            seen[key] = g
            groups.append(g)
    return groups

# ── 프롬프트 규격 (규격.json 으로 저장되며, 그룹 이름/순서/분류 키워드를 마음대로 수정 가능) ──
DEFAULT_SPEC = {
    "_설명": "규격화 도구의 그룹 구성입니다. 그룹 추가/삭제/순서변경/키워드 수정 전부 자유. 키워드는 태그에 '포함'되면 그 그룹으로 분류됩니다 (위에서부터 먼저 맞는 그룹 우선).",
    "캐릭터_그룹": [
        {"이름": "기본", "키워드": ["1girl", "1boy", "solo", "looking at", "looking away", "eye contact", "looking back"]},
        {"이름": "상황", "키워드": ["knight", "elf", "maid", "idol", "student", "teacher", "nurse", "witch", "demon", "angel", "vampire", "android", "princess", "queen", "goddess", "restrained", "fighting", "office lady"]},
        {"이름": "행동", "키워드": ["standing", "sitting", "lying", "kneeling", "holding", "drinking", "eating", "smile", "blush", "open mouth", "closed eyes", "pose", "crossed arms", "pointing", "waving", "running", "walking", "leaning", "hug", "grin", "smirk", "frown", "tears", "crying", "laughing", "wink", "tongue", "hand on", "hands on", "arms up", "arms behind"]},
        {"이름": "외모", "키워드": ["hair", "eyes", "pupils", "bangs", "ponytail", "twintails", "braid", "ahoge", "breasts", "skin", "tall", "petite", "muscular", "thigh", "hips", "mole", "freckles", "tan", "scar", "fang", "horn", "tail", "wing", "ears", "face", "body", "waist", "navel", "abs", "curvy", "slim", "eyelash", "eyebrow", "lips", "teeth", "forehead", "sidelocks", "nude", "nipples", "female", "mature"]},
        {"이름": "의상", "키워드": ["dress", "shirt", "skirt", "uniform", "jacket", "coat", "pants", "shorts", "bikini", "swimsuit", "leotard", "kimono", "sweater", "hoodie", "vest", "cape", "apron", "lingerie", "bra", "panties", "underwear", "sleeve", "off shoulder", "collar", "neckline", "lace", "leather", "denim", "frill", "pleated", "suit", "blazer", "cardigan", "camisole", "bodysuit", "gown", "robe", "armor", "corset", "garter", "stocking", "pantyhose", "socks", "shoulder patch"]},
        {"이름": "장신구", "키워드": ["hairpin", "hair ornament", "ribbon", "bow", "choker", "necklace", "earring", "bracelet", "belt", "glasses", "hat", "cap", "crown", "tiara", "headband", "hairband", "scrunchie", "bag", "glove", "scarf", "jewelry", "ring", "piercing", "thighhigh", "wristband", "anklet", "mask", "veil", "halo"]},
        {"이름": "마무리", "키워드": ["boots", "heels", "shoes", "sneakers", "sandals", "loafers", "footwear", "barefoot", "slippers", "mary janes"]},
    ],
    "캐릭터_기본그룹": "외모",
    "그림체_그룹": [
        {"이름": "프레임", "키워드": ["1girl", "2girls", "1boy", "2boys", "solo", "upper body", "cowboy shot", "full body", "portrait", "close-up", "from above", "from below", "from side", "from behind", "dutch angle", "pov", "wide shot", "straight-on", "multiple views"]},
        {"이름": "장소", "키워드": ["indoors", "outdoors", "classroom", "beach", "room", "city", "forest", "sky", "night", "daytime", "sunlight", "backlight", "lens flare", "depth of field", "bokeh", "lighting", "shadow", "cinematic"]},
        {"이름": "작가", "키워드": ["artist:", "year 20", "artist collaboration"]},
        {"이름": "스타일", "키워드": ["masterpiece", "quality", "aesthetic", "absurdres", "highres", "detail", "anime", "realistic", "official art", "game cg", "sketch", "illustration", "coloring", "3d", "monochrome", "flat color", "novel", "shiny"]},
    ],
    "그림체_기본그룹": "스타일",
}
SPEC_FILE = BASE_DIR / "규격.json"
STYLE_DIR = BASE_DIR / "그림체"


def load_spec():
    if SPEC_FILE.exists():
        try:
            data = load_json_recover(SPEC_FILE)
            merged = dict(DEFAULT_SPEC)
            merged.update(data)
            return merged
        except Exception as e:
            log.warning(f"규격.json 손상 — 기본 규격 사용: {e}")
            return dict(DEFAULT_SPEC)
    # 규격도 빈 본체에서 자동 생성하지 않는다. 내장 기본값으로 기능은 유지하고,
    # 별도 기본 자료팩을 넣거나 사용자가 저장할 때만 외부 파일이 생긴다.
    return dict(DEFAULT_SPEC)


def _compose_ordered(groups, order_names):
    parts = []
    for name in order_names:
        v = (groups or {}).get(name, "")
        v = v.strip().rstrip(",") if isinstance(v, str) else ""
        if v:
            parts.append(v)
    return ", ".join(parts)


def list_styles(spec):
    """그림체/ 폴더의 규격 JSON 목록. {이름, 프롬프트} (그룹형이면 규격 순서로 조합)"""
    styles = []
    if not STYLE_DIR.exists():
        return styles
    order = [g["이름"] for g in spec.get("그림체_그룹", [])]
    for p in sorted(STYLE_DIR.glob("*.json")):
        try:
            data = load_json_recover(p)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        prompt = (data.get("프롬프트") or "").strip() or _compose_ordered(data.get("그룹"), order)
        if prompt:
            styles.append({"name": data.get("이름") or p.stem, "prompt": prompt,
                           "settings": data.get("설정") or {}, "negative": data.get("네거티브", "")})
    return styles


@serialized_data_write(lambda: STYLE_DIR.parent)
def save_style_file(name, prompt="", groups=None, settings=None, negative=""):
    STYLE_DIR.mkdir(exist_ok=True)
    data = {"이름": name}
    if groups:
        data["그룹"] = groups
    if prompt:
        data["프롬프트"] = prompt
    if settings:
        data["설정"] = settings
    if negative:
        data["네거티브"] = negative
    atomic_write_json(
        STYLE_DIR / f"{_safe_name(name)}.json", data)


# ══ 자료 비교 생성 ════════════════════════════════════════════════════
# 그림체·캐릭터 자료가 많아지면 한 항목씩 손으로 적용해 보는 것 자체가 일이 된다.
# 같은 시드·같은 크기로 한 장씩 뽑아 차이만 보되, 그림체의 베이스·네거티브·생성
# 설정은 한 덩어리로 유지한다. 크기 고정은 비교를 위한 명시적 단일 예외다.
COMPARE_MODE_LABELS = {
    "styles": "그림체 전체",
    "characters": "캐릭터 전체",
    "both": "그림체 × 캐릭터",
}
COMPARE_MAX_JOBS = 2_000_000
COMPARE_RECIPE_SETTING_KEYS = (
    "model", "width", "height", "cfg_scale", "cfg_rescale", "steps",
    "sampler", "scheduler", "variety", "uc_preset", "quality_toggle",
    "smea", "smea_dyn", "dynamic_thresholding", "uncond_scale",
    "controlnet_strength", "prefer_brownian",
    "deliberate_euler_ancestral_bug", "legacy_v3_extend", "use_coords",
)


def _comparison_id(prefix, *parts):
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:20]}"


def comparison_styles(spec=None):
    """수집 그림체와 사용자가 저장한 그림체 프리셋을 같은 실행 목록으로 합친다."""
    out, seen = [], set()
    for i, raw in enumerate(load_combos()):
        if not isinstance(raw, dict):
            continue
        base = (raw.get("base") or raw.get("combo") or "").strip()
        if not base:
            continue
        item = dict(raw)
        ident = str(item.get("id") or _comparison_id(
            "style", item.get("title"), base, item.get("negative"),
            item.get("params"), i))
        # 외부 자료의 id가 겹쳐도 둘 중 하나를 조용히 버리지 않는다.
        if ident in seen:
            ident = _comparison_id("style", ident, base, item.get("params"), i)
        seen.add(ident)
        item["_compare_id"] = ident
        item["_compare_name"] = (item.get("title") or item.get("combo")
                                 or f"그림체 {i + 1}").strip()
        item["_compare_kind"] = "수집"
        out.append(item)

    for i, saved in enumerate(list_styles(spec or load_spec())):
        if not isinstance(saved, dict) or not (saved.get("prompt") or "").strip():
            continue
        settings = dict(saved.get("settings") or {})
        params = {
            "scale": settings.get("cfg_scale"),
            "cfg_rescale": settings.get("cfg_rescale"),
            "steps": settings.get("steps"),
            "sampler": settings.get("sampler"),
            "noise_schedule": settings.get("scheduler"),
            "variety_plus": settings.get("variety"),
            "model": settings.get("model"),
            "width": settings.get("width"),
            "height": settings.get("height"),
            "uc_preset": settings.get("uc_preset"),
            "quality_toggle": settings.get("quality_toggle"),
        }
        params = {k: v for k, v in params.items() if v is not None}
        ident = _comparison_id(
            "preset", saved.get("name"), saved.get("prompt"),
            saved.get("negative"), params, i)
        if ident in seen:
            continue
        seen.add(ident)
        out.append({
            "id": ident,
            "_compare_id": ident,
            "_compare_name": saved.get("name") or f"내 프리셋 {i + 1}",
            "_compare_kind": "내 프리셋",
            "base": saved.get("prompt", ""),
            "negative": saved.get("negative", ""),
            "params": params,
        })
    return out


def _comparison_character_prompt(item):
    """저장 캐릭터도 일반 캐릭터 칸과 같은 `외형 + 착의` 한 덩어리로 보낸다."""
    return slot_prompt({
        "prompt": (item or {}).get("female", ""),
        "outfit": (item or {}).get("clothed", ""),
    })


def comparison_characters(cfg):
    """라이브러리의 캐릭터 전체. 켜짐 여부는 현재 화면용 상태라 전수 비교에서는 무시한다."""
    out = []
    for i, raw in enumerate((cfg or {}).get("characters") or []):
        if not isinstance(raw, dict):
            continue
        prompt = _comparison_character_prompt(raw)
        if not prompt:
            continue
        item = dict(raw)
        item["_compare_id"] = str(item.get("id") or _comparison_id(
            "char", item.get("name"), prompt, item.get("negative"), i))
        item["_compare_name"] = (item.get("name") or f"캐릭터 {i + 1}").strip()
        out.append(item)
    return out


def _compare_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def normalize_comparison_options(raw, cfg):
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("mode") or "styles")
    if mode not in COMPARE_MODE_LABELS:
        mode = "styles"
    try:
        limit = max(0, min(int(raw.get("limit") or 0), COMPARE_MAX_JOBS))
    except (TypeError, ValueError, OverflowError):
        limit = 0
    try:
        seed = max(0, min(int(raw.get("seed") or 0), 2**32 - 1))
    except (TypeError, ValueError, OverflowError):
        seed = 0
    try:
        seed_count = max(1, min(int(raw.get("seed_count") or 1), 4))
    except (TypeError, ValueError, OverflowError):
        seed_count = 1
    try:
        width = normalize_resolution(raw.get("width", cfg.get("width", 832)))
        height = normalize_resolution(raw.get("height", cfg.get("height", 1216)))
    except (TypeError, ValueError, OverflowError):
        width = normalize_resolution(cfg.get("width", 832))
        height = normalize_resolution(cfg.get("height", 1216))
    return {
        "mode": mode,
        "fixed_size": _compare_bool(raw.get("fixed_size"), True),
        "width": width,
        "height": height,
        "same_seed": _compare_bool(raw.get("same_seed"), True),
        "seed": seed,
        "seed_count": seed_count,
        "limit": limit,
        # 레퍼런스는 비교 변수를 흐리고 추가 과금도 생기므로 사용자가 켠 경우만 쓴다.
        "include_refs": _compare_bool(raw.get("include_refs"), False),
    }


def comparison_style_config(cfg, style, options):
    """그림체 한 건의 설정 묶음을 실행용 cfg 사본에 적용한다."""
    used = dict(cfg or {})
    p = (style or {}).get("params") or {}
    mapping = {
        "scale": "cfg_scale",
        "cfg_rescale": "cfg_rescale",
        "steps": "steps",
        "sampler": "sampler",
        "noise_schedule": "scheduler",
        "variety_plus": "variety",
        "uc_preset": "uc_preset",
        "quality_toggle": "quality_toggle",
        "sm": "smea",
        "sm_dyn": "smea_dyn",
        "dynamic_thresholding": "dynamic_thresholding",
        "uncond_scale": "uncond_scale",
        "controlnet_strength": "controlnet_strength",
        "prefer_brownian": "prefer_brownian",
        "deliberate_euler_ancestral_bug": "deliberate_euler_ancestral_bug",
    }
    for source, target in mapping.items():
        if p.get(source) is not None:
            used[target] = p[source]
    if p.get("model"):
        used["model"] = model_id_from_metadata(
            p.get("model"), used.get("model") or "nai-diffusion-4-5-full")
    if p.get("width"):
        used["width"] = normalize_resolution(p["width"])
    if p.get("height"):
        used["height"] = normalize_resolution(p["height"])
    if options.get("fixed_size"):
        used["width"], used["height"] = options["width"], options["height"]
    return used


def comparison_sources(cfg, spec=None):
    return comparison_styles(spec), comparison_characters(cfg)


def comparison_plan(cfg, raw, spec=None, opus=None):
    """실행 전에 장수와 과금 범위를 계산한다. API 호출은 하지 않는다."""
    options = normalize_comparison_options(raw, cfg)
    styles, chars = comparison_sources(cfg, spec)
    mode = options["mode"]
    current_slots = [
        s for s in (cfg.get("char_slots") or [])
        if slot_prompt(s).strip() and s.get("enabled") is not False
    ]
    combinations = (len(styles) if mode == "styles"
                    else len(chars) if mode == "characters"
                    else len(styles) * len(chars))
    total = combinations * options["seed_count"]
    count = min(total, options["limit"]) if options["limit"] else total
    errors = []
    if mode in ("styles", "both") and not styles:
        errors.append("비교할 그림체가 없습니다. 자료팩이나 그림체 자료를 먼저 넣어주세요.")
    if mode in ("characters", "both") and not chars:
        errors.append("비교할 캐릭터가 없습니다. 캐릭터 라이브러리에 먼저 저장해주세요.")
    if count > COMPARE_MAX_JOBS:
        errors.append(f"한 계획은 최대 {COMPARE_MAX_JOBS:,}장까지 만들 수 있습니다.")

    refs = (sum(1 for r in cfg.get("char_refs", []) if r.get("enabled"))
            if options["include_refs"] else 0)
    paid_total = opus_total = eligible = 0
    remain = count

    def add_cost(job_cfg, multiplier):
        nonlocal paid_total, opus_total, eligible, remain
        n = max(0, min(int(multiplier), remain))
        if not n:
            return
        paid = anlas_estimate(job_cfg, 1, opus=False, char_refs=refs)
        free = anlas_estimate(job_cfg, 1, opus=True, char_refs=refs)
        paid_total += paid["per_image"] * n
        opus_total += free["per_image"] * n
        if free["free_eligible"]:
            eligible += n
        remain -= n

    if mode == "characters":
        used = comparison_style_config(cfg, None, options)
        add_cost(used, count)
    elif mode == "styles":
        for style in styles:
            if remain <= 0:
                break
            add_cost(
                comparison_style_config(cfg, style, options),
                options["seed_count"],
            )
    else:
        for style in styles:
            if remain <= 0:
                break
            add_cost(
                comparison_style_config(cfg, style, options),
                len(chars) * options["seed_count"],
            )

    expected = None
    if opus is True:
        expected = opus_total
    elif opus is False:
        expected = paid_total
    return {
        "ok": not errors,
        "errors": errors,
        "options": options,
        "mode_label": COMPARE_MODE_LABELS[mode],
        "styles": len(styles),
        "characters": len(chars),
        "current_slots": len(current_slots),
        "combinations": combinations,
        "seed_count": options["seed_count"],
        "total": total,
        "count": count,
        "limited": count < total,
        "free_eligible": eligible,
        "paid_anlas_max": paid_total,
        "opus_anlas": opus_total,
        "expected_anlas": expected,
        "subscription_known": opus is not None,
        "sample_styles": [x["_compare_name"] for x in styles[:3]],
        "sample_characters": [x["_compare_name"] for x in chars[:3]],
    }


def comparison_signature(cfg, plan, styles, chars):
    options = plan["options"]
    relevant_cfg = {
        k: cfg.get(k) for k in (
            "base_prompt", "negative_prompt", "cfg_scale", "cfg_rescale", "steps",
            "sampler", "scheduler", "variety", "model", "uc_preset",
            "quality_toggle", "smea", "smea_dyn", "dynamic_thresholding",
            "uncond_scale", "controlnet_strength", "prefer_brownian",
            "deliberate_euler_ancestral_bug", "use_coords", "char_slots",
            "char_centers", "vibes", "char_refs", "out_dir", "out_by_date",
        )
    }
    raw = {
        "options": options,
        "config": relevant_cfg,
        "styles": [
            (x["_compare_id"], x.get("base"), x.get("combo"),
             x.get("negative"), x.get("params")) for x in styles
        ] if options["mode"] in ("styles", "both") else [],
        "characters": [
            (x["_compare_id"], x.get("female"), x.get("clothed"), x.get("negative"))
            for x in chars
        ] if options["mode"] in ("characters", "both") else [],
    }
    return hashlib.sha256(json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")).hexdigest()


def iter_comparison_jobs(cfg, plan, styles, chars):
    """큰 직교곱도 목록 전체를 메모리에 만들지 않고 한 건씩 낸다."""
    options, made = plan["options"], 0
    limit = plan["count"]

    def emit(style, char, style_name, char_name, key, seed_index):
        nonlocal made
        if made >= limit:
            return None
        made += 1
        return {
            "index": made,
            "key": _comparison_id(
                "job", options["mode"], key, int(seed_index)),
            "style": style,
            "character": char,
            "style_name": style_name,
            "char_name": char_name,
            "seed_index": int(seed_index),
        }

    if options["mode"] == "styles":
        slots = [
            s for s in (cfg.get("char_slots") or [])
            if slot_prompt(s).strip() and s.get("enabled") is not False
        ]
        char_name = (f"현재 캐릭터 {len(slots)}명" if slots else "캐릭터 없음")
        slot_key = [(slot_prompt(s), s.get("negative", "")) for s in slots]
        for style in styles:
            for seed_index in range(options["seed_count"]):
                job = emit(style, None, style["_compare_name"], char_name,
                           (style["_compare_id"], slot_key), seed_index)
                if job is None:
                    return
                yield job
    elif options["mode"] == "characters":
        for char in chars:
            for seed_index in range(options["seed_count"]):
                job = emit(None, char, "현재 그림체", char["_compare_name"],
                           ("current", char["_compare_id"]), seed_index)
                if job is None:
                    return
                yield job
    else:
        for style in styles:
            for char in chars:
                for seed_index in range(options["seed_count"]):
                    job = emit(
                        style, char, style["_compare_name"],
                        char["_compare_name"],
                        (style["_compare_id"], char["_compare_id"]),
                        seed_index,
                    )
                    if job is None:
                        return
                    yield job


def comparison_job_values(cfg, plan, job):
    options = plan["options"]
    style = job.get("style")
    used = comparison_style_config(cfg, style, options)
    base = ((style or {}).get("base") or (style or {}).get("combo")
            or cfg.get("base_prompt") or "1girl").strip()
    negative = ((style or {}).get("negative")
                if style is not None else cfg.get("negative_prompt", ""))
    negative = negative or ""
    char = job.get("character")
    if char is not None:
        # 캐릭터 자료의 외형+착의를 일반 캐릭터 칸과 같은 한 덩어리로 보낸다.
        people = [{"prompt": _comparison_character_prompt(char),
                   "negative": char.get("negative", "") or ""}]
        centers = [{"x": 0.5, "y": 0.5}]
    else:
        # active_people가 원래 칸 index로 좌표를 함께 거른다. 슬롯을 먼저 줄이면
        # 꺼진 캐릭터 뒤의 인물이 앞 캐릭터 좌표를 받는다.
        people, centers = active_people(
            cfg.get("char_slots") or [], cfg.get("char_centers"))
    return used, base, negative, people, centers


def comparison_recipe_context(cfg, plan, styles, chars):
    """비교 결과가 현재 자료 변경 뒤에도 재현되도록 원문을 한 번만 스냅샷한다."""
    options = plan.get("options") or {}
    all_slots = cfg.get("char_slots") or []
    active_slots = [
        dict(slot) for slot in all_slots
        if isinstance(slot, dict) and slot_prompt(slot).strip()
        and slot.get("enabled") is not False
    ][:MAX_CHARS]
    _, active_centers = active_people(
        all_slots, cfg.get("char_centers"))
    config = {
        key: cfg.get(key) for key in (
            "base_prompt", "negative_prompt", "style_name",
            *COMPARE_RECIPE_SETTING_KEYS,
        )
    }
    if options.get("include_refs"):
        config["vibes"] = cfg.get("vibes") or []
        config["char_refs"] = cfg.get("char_refs") or []
    return {
        "version": 1,
        "options": options,
        "config": config,
        "char_slots": active_slots,
        "char_centers": active_centers,
        "styles": [{
            "id": item.get("_compare_id"),
            "name": item.get("_compare_name"),
            "kind": item.get("_compare_kind"),
            "base": item.get("base") or item.get("combo") or "",
            "negative": item.get("negative") or "",
            "params": item.get("params") or {},
        } for item in styles
            if options.get("mode") in ("styles", "both")],
        "characters": [{
            "id": item.get("_compare_id"),
            "name": item.get("_compare_name"),
            "female": item.get("female") or "",
            "clothed": item.get("clothed") or "",
            "negative": item.get("negative") or "",
            "source": item.get("source") or "",
        } for item in chars
            if options.get("mode") in ("characters", "both")],
    }


class RateLimitError(Exception):
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = max(1.0, min(float(retry_after or 60), 600.0))


class AccountBannedError(Exception):
    pass


class AuthError(Exception):
    pass


class APIError(Exception):
    def __init__(self, message, status_code=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = bool(retryable)


def retry_after_seconds(value, default=60):
    """Retry-After의 초/HTTP-date 두 형식을 읽고 비정상 값은 안전한 기본값으로."""
    text = str(value or "").strip()
    if not text:
        return float(default)
    try:
        return max(1.0, min(float(text), 600.0))
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
            now = datetime.now(when.tzinfo) if when.tzinfo else datetime.now()
            return max(1.0, min((when - now).total_seconds(), 600.0))
        except (TypeError, ValueError, OverflowError):
            return float(default)


class FatalStopError(Exception):
    """계정 정지/인증 오류 등 프로그램 자체를 완전히 끝내야 하는 경우."""
    pass


# ═══════════════ 설정 로드/저장 ═══════════════

def _read_legacy_txt():
    """예전 설정.txt 포맷을 1회성으로 읽어온다 (마이그레이션용)."""
    s = {}
    if not LEGACY_SETTINGS_FILE.exists():
        return s
    with open(LEGACY_SETTINGS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                s[k.strip()] = v.strip()
    return s


def _migrate_legacy(cfg):
    old = _read_legacy_txt()
    if not old:
        return cfg
    log.info("설정.txt 발견 — 설정.json 으로 1회 이전합니다.")
    cfg["token"] = old.get("토큰", cfg["token"])
    if old.get("시드", "").isdigit():
        cfg["seed"] = int(old["시드"])
    cfg["base_prompt"] = old.get("그림체", cfg["base_prompt"])
    cfg["negative_prompt"] = old.get("네거티브", cfg["negative_prompt"])
    cfg["male_prompt"] = old.get("남자", cfg["male_prompt"])
    for key, cast, target in (("CFG", float, "cfg_scale"), ("리스케일", float, "cfg_rescale"),
                               ("스텝", int, "steps")):
        v = old.get(key, "")
        if v:
            try:
                cfg[target] = cast(v)
            except ValueError:
                pass
    if old.get("샘플러"):
        cfg["sampler"] = old["샘플러"]
    if old.get("노이즈"):
        cfg["scheduler"] = old["노이즈"]
    if old.get("버라이어티"):
        cfg["variety"] = old["버라이어티"].lower() in ("켬", "on", "true", "1", "yes")

    if old.get("여자"):
        cfg["characters"].append({
            "id": "char1", "name": "캐릭터 1", "female": old["여자"], "negative": "",
            "enabled": True, "folder_id": None, "subfolder_id": None,
        })

    # 설정.txt 하단의 [여자 이름]/[남자 이름] 캐릭터 섹션도 이전
    cur = None
    sections = {}
    try:
        with open(LEGACY_SETTINGS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip().lstrip("﻿")
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    head = line[1:-1].strip()
                    parts = head.split(None, 1)
                    if len(parts) == 2 and parts[0] in ("여자", "남자"):
                        cur = (parts[0], parts[1].strip())
                        sections[cur] = {}
                    else:
                        cur = None
                elif "=" in line and cur:
                    k, v = line.split("=", 1)
                    sections[cur][k.strip()] = v.strip()
    except OSError:
        pass
    for (ctype, cname), fields in sections.items():
        if ctype == "여자" and fields.get("외형"):
            if any(c.get("name") == cname for c in cfg["characters"]):
                continue
            cfg["characters"].append({
                "id": "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
                "name": cname, "female": fields.get("외형", ""),
                "clothed": fields.get("착의", ""), "negative": fields.get("네거티브", ""),
                "enabled": True, "folder_id": None, "subfolder_id": None,
            })
        elif ctype == "남자" and fields.get("외형") and not cfg.get("male_prompt"):
            cfg["male_prompt"] = fields["외형"]

    select_raw = old.get("선택체위", "").strip()
    if select_raw:
        cfg["selected_positions"] = [int(x) for x in select_raw.split(",") if x.strip().isdigit()]
    else:
        preset_name = old.get("세트", "전체")
        if preset_name == "가벼움":
            cfg["selected_positions"] = list(LIGHT_PRESET)
        else:
            cfg["selected_positions"] = [p["id"] for p in POSITIONS]
    return cfg


def _prefill_partner_defaults(cfg):
    """새 설정을 만들 때 asset_config.json 의 기본 파트너(백합 상대역) 외형을 미리 채워준다."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            acfg = json.load(f)
        pchar = acfg.get("characters", {}).get("partner", {})
        if not cfg.get("partner_prompt"):
            cfg["partner_prompt"] = pchar.get("nude", "")
        if not cfg.get("partner_negative"):
            cfg["partner_negative"] = pchar.get("negative", "")
    except Exception:
        pass
    return cfg


def load_or_init_config():
    global STARTUP_RECOVERY_NOTICE
    STARTUP_RECOVERY_NOTICE = None
    if SETTINGS_FILE.exists():
        try:
            cfg = load_json_recover(SETTINGS_FILE)
        except json.JSONDecodeError as e:
            # 주 파일과 `.bak`이 모두 JSON으로 읽히지 않는 경우만 구조 시작으로 전환한다.
            # 권한·디스크 오류는 손상으로 오인해 파일을 옮기지 않고 그대로 알린다.
            STARTUP_RECOVERY_NOTICE = quarantine_corrupt_settings(
                SETTINGS_FILE, e)
            log.critical(
                "설정과 자동 백업이 모두 손상되어 원본을 보관하고 기본 설정으로 시작합니다: %s",
                STARTUP_RECOVERY_NOTICE["folder"])
            cfg = dict(DEFAULT_CONFIG)
            cfg = _migrate_legacy(cfg)
            ensure_settings_migration()
            migrate_legacy_selections(cfg)
            import_char_files(cfg)
            sync_chars_to_files(cfg)
            save_config(cfg)
            return cfg
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        ensure_settings_migration()
        migrate_legacy_selections(merged)
        migrate_char_slots(merged)
        import_char_files(merged)
        sync_chars_to_files(merged)
        save_config(merged)
        return merged
    cfg = dict(DEFAULT_CONFIG)
    cfg = _migrate_legacy(cfg)
    ensure_settings_migration()
    migrate_legacy_selections(cfg)
    import_char_files(cfg)
    sync_chars_to_files(cfg)
    save_config(cfg)
    return cfg


# ═══════════════ 캐릭터 파일 라이브러리 (캐릭터/ 폴더 = 규격 JSON) ═══════════════
#
# 규격: 캐릭터/<폴더>/<하위폴더>/<이름>.json
# {
#   "이름": "레이나",
#   "외형": "girl, black hair, ...",          ← 나체/기본 외형 (또는 "그룹"으로 대체)
#   "착의": "girl, black hair, ..., dress",   ← 선택
#   "네거티브": "choker, sword",               ← 선택
#   "출처": "https://wiki...",                 ← 선택 (메모용)
#   "그룹": {"기본":"", "상황":"", "행동":"", "외모":"", "의상":"", "장신구":"", "마무리":""}
#        ← 선택. "외형"이 비어 있으면 이 순서(기본→상황→행동→외모→의상→장신구→마무리)로 합쳐서 사용
# }
# 위키 등에서 가져온 프롬프트를 이 규격의 .json 으로 폴더에 넣으면 다음 실행 때 자동 등록되고,
# UI에서 수정하면 파일에도 반영, UI에서 삭제하면 파일도 삭제됩니다.

CHAR_DIR = BASE_DIR / "캐릭터"
GROUP_ORDER = ["기본", "상황", "행동", "외모", "의상", "장신구", "마무리"]


def _safe_name(name):
    bad = '<>:"/\\|?*'
    out = "".join(c for c in (name or "") if c not in bad).strip()
    return out or "이름없음"


def _compose_from_groups(groups):
    parts = []
    for g in GROUP_ORDER:
        v = (groups or {}).get(g, "").strip().rstrip(",")
        if v:
            parts.append(v)
    return ", ".join(parts)


def _folder_by_name(cfg, name, parent_id=None):
    for f in cfg.get("character_folders", []):
        if f.get("name") == name and f.get("parent_id") == parent_id:
            return f
    f = {"id": "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
         "name": name, "parent_id": parent_id}
    cfg.setdefault("character_folders", []).append(f)
    return f


def _read_char_documents(paths):
    """많은 독립 JSON을 원자 저장 잠금 밖에서 병렬로 읽는다.

    파일 교체는 os.replace라 잠금 없는 독자는 완성된 이전판 또는 새 판만 본다.
    깨진 파일만 기존 복구 경로로 다시 읽어 `.bak`을 살린다. Windows에서 파일
    1,000개를 직렬 open하면 보안 검사 지연만 수십 초가 걸려 자료 수에 비례해
    시작이 멈추므로, 충분히 많을 때만 제한된 읽기 풀을 쓴다.
    """
    paths = list(paths)

    def one(path):
        try:
            return path, json.loads(path.read_text(encoding="utf-8-sig")), None
        except Exception as first:
            try:
                return path, load_json_recover(path), None
            except Exception:
                return path, None, first

    if len(paths) < 32:
        return [one(path) for path in paths]
    from concurrent.futures import ThreadPoolExecutor
    workers = min(16, max(4, (os.cpu_count() or 4) * 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, paths))


def import_char_files(cfg):
    """캐릭터/ 폴더의 규격 JSON을 등록하고, 더 새 외부 편집은 설정에 반영한다.

    UI 저장은 캐릭터 파일을 먼저 쓰고 설정.json을 나중에 쓰므로 정상 저장 뒤에는
    설정 쪽 시각이 더 새롭다. 반대로 사용자가 캐릭터 JSON을 직접 고친 경우에만
    파일 쪽이 더 새로워진다. 같은 id라는 이유로 그 편집을 무시한 뒤 옛 설정으로
    덮어쓰지 않는다.
    """
    if not CHAR_DIR.exists():
        return
    known = {c.get("id"): c for c in cfg.get("characters", []) if c.get("id")}
    try:
        settings_mtime = SETTINGS_FILE.stat().st_mtime_ns
    except OSError:
        settings_mtime = -1
    registered, refreshed = [], []
    paths = sorted(CHAR_DIR.rglob("*.json"))
    for p, data, error in _read_char_documents(paths):
        if error is not None:
            log.warning(f"캐릭터 파일 손상(건너뜀): {p.name}")
            continue
        if not isinstance(data, dict):
            continue
        cid = data.get("id")
        female = (data.get("외형") or "").strip() or _compose_from_groups(data.get("그룹"))
        clothed = data.get("착의", "")
        if not (female or str(clothed or "").strip()):
            continue
        rel = p.relative_to(CHAR_DIR).parts[:-1]  # 폴더 경로 (최대 2단계)
        folder_id = subfolder_id = None
        if len(rel) >= 1:
            folder = _folder_by_name(cfg, rel[0])
            folder_id = folder["id"]
        if len(rel) >= 2:
            sub = _folder_by_name(cfg, rel[1], parent_id=folder_id)
            subfolder_id = sub["id"]
        if cid and cid in known:
            try:
                externally_newer = p.stat().st_mtime_ns > settings_mtime
            except OSError:
                externally_newer = False
            if not externally_newer:
                continue
            current = known[cid]
            current.update({
                "name": data.get("이름") or p.stem,
                "female": female,
                "clothed": clothed,
                "negative": data.get("네거티브", ""),
                "source": data.get("출처", ""),
                "folder_id": folder_id,
                "subfolder_id": subfolder_id,
            })
            if data.get("그룹"):
                current["groups"] = data["그룹"]
            else:
                current.pop("groups", None)
            refreshed.append(str(p.relative_to(CHAR_DIR)))
            continue
        new_id = cid or "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        new_char = {
            "id": new_id, "name": data.get("이름") or p.stem,
            "female": female, "clothed": clothed,
            "negative": data.get("네거티브", ""), "source": data.get("출처", ""),
            "enabled": True, "folder_id": folder_id, "subfolder_id": subfolder_id,
        }
        if data.get("그룹"):
            new_char["groups"] = data["그룹"]
        cfg.setdefault("characters", []).append(new_char)
        known[new_id] = new_char
        registered.append(str(p.relative_to(CHAR_DIR)))
    if registered:
        sample = ", ".join(registered[:3])
        log.info(
            f"캐릭터 파일 등록: {len(registered):,}개"
            + (f" (예: {sample})" if sample else "")
        )
    if refreshed:
        sample = ", ".join(refreshed[:3])
        log.info(
            f"외부에서 더 새로 편집한 캐릭터 반영: {len(refreshed):,}개"
            + (f" (예: {sample})" if sample else "")
        )


def sync_chars_to_files(cfg):
    """설정의 캐릭터를 캐릭터/ 폴더 규격 JSON으로 내보낸다 (UI 폴더 = 실제 디렉터리)."""
    CHAR_DIR.mkdir(exist_ok=True)
    folders = {f["id"]: f for f in cfg.get("character_folders", [])}
    # 시작할 때 수천 파일을 내용이 같은데도 모두 다시 fsync하면 실행이 수십 초
    # 느려지고 .bak도 쓸데없이 수천 개 생긴다. id별 현재 파일과 원문을 한 번 읽어,
    # 그대로인 파일은 건드리지 않고 이름·폴더·내용이 바뀐 것만 쓴다.
    existing_by_id, existing_by_path = {}, {}
    for old_path, old_data, error in _read_char_documents(
            CHAR_DIR.rglob("*.json")):
        if error is not None:
            continue
        if not isinstance(old_data, dict) or not old_data.get("id"):
            continue
        existing_by_id.setdefault(str(old_data["id"]), []).append(
            (old_path, old_data))
        existing_by_path[old_path.resolve()] = old_data
    keep = set()
    for c in cfg.get("characters", []):
        parts = []
        f = folders.get(c.get("folder_id"))
        if f:
            parts.append(_safe_name(f["name"]))
        sf = folders.get(c.get("subfolder_id"))
        if sf:
            parts.append(_safe_name(sf["name"]))
        d = CHAR_DIR.joinpath(*parts) if parts else CHAR_DIR
        d.mkdir(parents=True, exist_ok=True)
        desired = d / f"{_safe_name(c.get('name') or c['id'])}.json"
        candidates = existing_by_id.get(str(c["id"]), [])
        # 외부 파일을 처음 읽은 직후에는 원래 파일명과 알려지지 않은 필드를
        # 그대로 지킨다. UI에서 이름·폴더를 바꾼 경우에만 새 위치로 옮긴다.
        stable = next((
            old_path for old_path, old_data in candidates
            if old_path.parent.resolve() == d.resolve()
            and str(old_data.get("이름") or old_path.stem)
                == str(c.get("name") or "")
        ), None)
        p = stable or desired
        if stable is None:
            serial = 2
            while p.exists():
                occupant = existing_by_path.get(p.resolve())
                if isinstance(occupant, dict) and str(occupant.get("id")) == str(c["id"]):
                    break
                p = d / f"{_safe_name(c.get('name') or c['id'])} ({serial}).json"
                serial += 1
        prior = existing_by_path.get(p.resolve())
        if prior is None and candidates:
            # 이름·폴더 이동에서도 외부 도구가 적은 알 수 없는 필드를 버리지 않는다.
            prior = candidates[0][1]
        data = dict(prior) if isinstance(prior, dict) else {}
        data.update({
            "id": c["id"], "이름": c.get("name", ""), "외형": c.get("female", ""),
            "착의": c.get("clothed", ""), "네거티브": c.get("negative", ""),
        })
        if c.get("groups"):
            data["그룹"] = c["groups"]
        else:
            data.pop("그룹", None)
        if c.get("source"):
            data["출처"] = c["source"]
        else:
            data.pop("출처", None)
        try:
            if not (p.is_file() and existing_by_path.get(p.resolve()) == data):
                atomic_write_json(p, data)
            keep.add(p.resolve())
        except OSError as e:
            log.warning(f"캐릭터 파일 저장 실패({p.name}): {e}")
    # 설정에 있는 캐릭터의 옛 파일(이동/이름변경/삭제 잔재) 정리
    ids = {c["id"] for c in cfg.get("characters", [])}
    for p, data in (
        (old_path, old_data)
        for rows in existing_by_id.values()
        for old_path, old_data in rows
    ):
        if p.resolve() in keep:
            continue
        if isinstance(data, dict) and data.get("id") and data["id"] in ids:
            # 같은 캐릭터의 새 위치 파일이 먼저 확정된 뒤 옛 위치는 복구 가능한
            # 백업으로 옮긴다. 이동 중 중단돼도 캐릭터 원문은 남는다.
            recoverable_remove(p, label="옛위치")


def delete_char_files(cfg, removed_ids):
    """UI에서 삭제된 캐릭터의 파일을 지운다."""
    if not CHAR_DIR.exists() or not removed_ids:
        return
    for p in list(CHAR_DIR.rglob("*.json")):
        try:
            data = load_json_recover(p)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id") in removed_ids:
            recoverable_remove(p)


def save_config(cfg):
    # `_` 로 시작하는 키는 실행 중에만 쓰는 임시값이다
    # (_vibes · _char_refs · _frag_counters …). 설정.json 에 새면 안 된다.
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    _BOORU_KEYS.clear()
    _BOORU_KEYS.update(clean.get("booru_keys") or {})
    atomic_write_json(SETTINGS_FILE, clean)


# ═══════════════ 프롬프트 조합 ═══════════════

def clean_char_prompt(raw):
    return ", ".join(
        t.strip()
        for t in (raw or "").replace("\n", ",").split(",")
        if t.strip() and not t.strip().startswith("#")
    )


def setting_state(cfg, name):
    """설정.json 에 저장되는 세팅별 선택 상태: {use, selected(그룹 id들), opts{옵션명: 선택값}}"""
    return (cfg.get("setting_state") or {}).get(name, {})


def load_asset_config(cfg):
    """세팅/ 폴더의 모든 세팅을 병합. 각 씬에 _setting(이름)/_mode(방식)를 부여하고,
    세팅별 옵션 선택값(setting_state)을 규격이 아는 의미대로 반영한다."""
    style = (cfg.get("base_prompt") or "").strip()
    acfg = {
        "base": {
            "nsfw_base_prompt": "1girl, 1boy" + (f", {style}" if style else ""),
            "yuri_base_prompt": "2girls, yuri" + (f", {style}" if style else ""),
            "base_prompt": "1girl" + (f", {style}" if style else ""),
            "nsfw_negative_prompt": cfg.get("negative_prompt", ""),
            "negative_prompt": cfg.get("negative_prompt", ""),
            "cfg_scale": cfg.get("cfg_scale", 5.5),
            "cfg_rescale": cfg.get("cfg_rescale", 0.56),
            "sampler": cfg.get("sampler", "k_euler_ancestral"),
            "scheduler": cfg.get("scheduler", "karras"),
            "uc_preset": 3,
        },
        "scenes": {},
        "_settings": {},   # 이름 → {mode, options, role, opts(선택값)}
    }
    for st in list_settings():
        name, mode, data = st["name"], st["mode"], st["data"]
        state = setting_state(cfg, name)
        opts_chosen = state.get("opts", {})
        options = data.get("옵션", {})
        role = data.get("상대역", {})
        specs = axis_specs(data)
        acfg["_settings"][name] = {"mode": mode, "options": options, "role": role,
                                   "opts": opts_chosen, "file": st["file"],
                                   "specs": specs}
        # 씬이 자기 묶음(세트) 안에서 몇 번째인지 미리 새겨 둔다.
        #   예전엔 `(번호-1) % 5` 로 단계를 셌는데 그러면 **5장 묶음에 묶여 있다.**
        #   묶음 안의 순서를 쓰면 단계 수가 3장이든 7장이든 그대로 돌아간다.
        stage_of, stages_of = {}, {}
        for g in derive_setting_catalog(data.get("씬", {})):
            for i, sn in enumerate(g["ids"]):
                stage_of[sn] = i
                stages_of[sn] = len(g["ids"])
        for k, sc in data.get("씬", {}).items():
            if not str(k).isdigit():
                continue
            if str(k) in acfg["scenes"]:
                log.warning(f"씬 번호 {k} 가 겹칩니다 "
                            f"({acfg['scenes'][str(k)].get('_setting')} ↔ {name}) — "
                            f"뒤에 읽힌 쪽이 이깁니다. 세팅 빌더의 '번호 다시 매기기' 를 쓰세요.")
            sc = dict(sc)
            sc["_setting"] = name
            sc["_mode"] = mode
            sc["_num"] = int(k)
            sc["_stage"] = stage_of.get(int(k), 0)
            sc["_stages"] = stages_of.get(int(k), 1)
            # 베이스로 갈 옵션(배경·시간 등)은 씬을 만들 때 미리 합쳐 둔다
            loc = apply_axes(specs, options, opts_chosen, sc, "base")
            if loc:
                sc["location"] = loc
            acfg["scenes"][str(k)] = sc
    return acfg


# ══════════════════════════════════════════════════════════════════════
#  옵션 축 — 세팅이 스스로 "이 축이 어디에 어떻게 붙는지" 말할 수 있게 한다.
#    세팅 파일에 `옵션규격` 이 있으면 그것을 따르고, 없으면 **값 모양으로 추론**한다.
#    (기존 세팅 3종은 규격이 없으므로 추론 경로로 예전과 똑같이 동작한다)
#
#    "옵션규격": { "장소테마": {"적용": "base",  "방식": "계열별"},
#                 "시간대":   {"적용": "base",  "방식": "고정"},
#                 "표정진행": {"적용": "여자",  "방식": "단계별"},
#                 "말투":     {"적용": "네거티브", "방식": "고정"} }
#
#    적용: base | 여자 | 남자 | 네거티브       방식: 고정 | 계열별 | 단계별
# ══════════════════════════════════════════════════════════════════════
AXIS_TARGETS = ("base", "여자", "남자", "네거티브")
AXIS_SHAPES = ("고정", "계열별", "단계별")
# 이름만 보고 아는 것 (예전 세팅과 호환)
LEGACY_AXES = {
    "장소테마": ("base", "계열별"),
    "시간대": ("base", "고정"),
    "표정진행": ("여자", "단계별"),
}


def _guess_shape(items):
    """항목 값의 모양으로 방식을 추론한다."""
    for v in (items or {}).values():
        if isinstance(v, list):
            return "단계별"
        if isinstance(v, dict):
            return "계열별"
        return "고정"
    return "고정"


def axis_specs(data):
    """세팅 파일 → {축이름: (적용, 방식)}. 규격이 없으면 이름·모양으로 추론."""
    declared = data.get("옵션규격") or {}
    out = {}
    for ax, items in (data.get("옵션") or {}).items():
        d = declared.get(ax) or {}
        target = d.get("적용")
        shape = d.get("방식")
        if target not in AXIS_TARGETS or shape not in AXIS_SHAPES:
            lt, ls = LEGACY_AXES.get(ax, (None, None))
            target = target if target in AXIS_TARGETS else (lt or "base")
            shape = shape if shape in AXIS_SHAPES else (ls or _guess_shape(items))
        out[ax] = (target, shape)
    return out


def apply_axes(specs, options, chosen, scene, target):
    """이 씬에서 `target` 자리에 붙을 옵션 태그들을 이어 붙여 돌려준다."""
    parts = []
    for ax, (tgt, shape) in (specs or {}).items():
        if tgt != target:
            continue
        pick = chosen.get(ax, "")
        if not pick:
            continue
        val = (options.get(ax) or {}).get(pick)
        if not val:
            continue
        if shape == "계열별" and isinstance(val, dict):
            v = val.get(scene.get("category", ""))
            if v:
                parts.append(v)
        elif shape == "단계별" and isinstance(val, (list, tuple)):
            i = int(scene.get("_stage", 0))
            if 0 <= i < len(val) and val[i]:
                parts.append(val[i])
        elif isinstance(val, str):
            parts.append(val)
    return ", ".join(x for x in parts if x)


def _setting_ctx(acfg, scene):
    return acfg.get("_settings", {}).get(scene.get("_setting", ""), {})


def build_scene(acfg, char, cfg, scene_num):
    """방식(남녀/백합/단독)에 따라 프롬프트 조립. 반환: (base, cap1, cap2, neg1, neg2, w, h)"""
    scene = acfg["scenes"][str(scene_num)]
    mode = scene.get("_mode", "단독")
    if mode == "백합":
        return _build_yuri(acfg, char, scene)
    return _build_std(acfg, char, scene, mode)


def _build_std(acfg, char, scene, mode):
    kind = "표정" if mode == "단독" else "체위"
    variant = "clothed" if mode == "단독" else "nude"
    base = acfg["base"]["nsfw_base_prompt"] if variant == "nude" else acfg["base"]["base_prompt"]
    ctx = _setting_ctx(acfg, scene)

    raw_char = char.get("female", "")
    cleaned_char = clean_char_prompt(raw_char)
    char_negative = char.get("negative", "")

    location = scene.get("location", "")
    if location:
        base = f"{base}, {location}"

    remove_char_tags = scene.get("remove_char_tags", [])
    if remove_char_tags:
        subs = [s.lower() for s in remove_char_tags]
        parts = [t.strip() for t in cleaned_char.split(",") if t.strip()]
        parts = [t for t in parts if not any(sub in t.lower() for sub in subs)]
        cleaned_char = ", ".join(parts)

    female_scene = scene.get("female_prompt", "")
    male_caption = scene.get("male_prompt", "")

    female_caption = _join_tags(cleaned_char, female_scene)

    scene_num = scene.get("_num", 0)
    role = ctx.get("role", {})
    opts_chosen = ctx.get("opts", {})

    # 단계 = **묶음 안의 순서**. `(번호-1) % 5` 를 쓰면 5장 묶음에 갇힌다.
    stage = int(scene.get("_stage", (scene_num - 1) % 5))
    specs = ctx.get("specs") or {}
    options = ctx.get("options", {})

    # 여자 칸에 붙는 축 (표정진행 등)
    add_f = apply_axes(specs, options, opts_chosen, scene, "여자")
    if add_f:
        female_caption = _join_tags(female_caption, add_f)

    if mode == "남녀":
        # 상대역(남자)은 세팅 파일의 것 — 씬 태그가 비어 있어도 항상 포함
        male_base = clean_char_prompt(role.get("외형", "") or char.get("male_prompt_base", ""))
        wear_mode = opts_chosen.get("남자옷", "나체")
        outfit = role.get("의상", "")
        wear = ""
        if wear_mode == "착의":
            wear = f"{outfit}, clothed male, clothed sex, open pants"
        elif wear_mode == "탈의진행":
            if stage <= 1:
                wear = f"{outfit}, clothed male, clothed sex, open pants"
            elif stage == 2:
                wear = "topless male, open pants, clothed sex"
        add_m = apply_axes(specs, options, opts_chosen, scene, "남자")
        male_caption = ", ".join(x for x in (male_base, wear, male_caption, add_m) if x)
        male_negative = role.get("네거티브", "")
    else:  # 단독
        male_caption = apply_axes(specs, options, opts_chosen, scene, "남자")
        male_negative = ""

    # 네거티브에 붙는 축
    add_n = apply_axes(specs, options, opts_chosen, scene, "네거티브")
    if add_n:
        char_negative = _join_tags(char_negative, add_n)

    return (base, female_caption, male_caption, char_negative, male_negative,
            scene["width"], scene["height"])


def slot_prompt(sl):
    """캐릭터 칸의 전송값 = 외형 + 의상. 의상을 따로 두면 외형을 안 건드리고 갈아입힐 수 있다.
    ⚠ 주석 제거를 **여기서** 한다 — 활성 판정(active_people)과 전송이 같은 값을 봐야
    주석 전용 슬롯이 (people, centers) 짝을 어긋내지 못한다 (CQA-003)."""
    if not isinstance(sl, dict):
        return ""
    return _join_tags(strip_comment_lines(sl.get("prompt", "")),
                      strip_comment_lines(sl.get("outfit", "")))


def _join_tags(*parts):
    """빈 조각을 걸러서 콤마로 잇는다. 캐릭터 칸이 비었을 때
    ', scene tags' 처럼 앞에 콤마만 남는 것을 막는다."""
    return ", ".join(p.strip().strip(",").strip() for p in parts
                     if p and p.strip().strip(",").strip())


def _strip_subject_prefix(text):
    """'1girl, 1boy, ' 등 인원수 프리픽스를 제거해 순수 화풍 태그만 남긴다."""
    text = text or ""
    for prefix in ("1girl, 1boy, ", "1girl,1boy,", "1girl, "):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _build_yuri(acfg, char, scene):
    """백합 — 파트너는 세팅 파일의 상대역, 탈의단계는 세팅 옵션에서."""
    ctx = _setting_ctx(acfg, scene)
    role = ctx.get("role", {})
    opts_chosen = ctx.get("opts", {})
    undress_tags = ctx.get("options", {}).get("탈의단계", {})

    base = acfg["base"].get("yuri_base_prompt", "2girls, yuri")
    if scene.get("base_tags"):
        base = f"{base}, {scene['base_tags']}"
    if scene.get("location"):
        base = f"{base}, {scene['location']}"

    u1, u2 = scene.get("undress1", 4), scene.get("undress2", 4)
    if opts_chosen.get("옷진행", "진행") == "나체":
        u1 = u2 = 4

    def girl_text(nude_raw, clothed_raw, level):
        raw = nude_raw if level >= 4 or not clothed_raw else clothed_raw
        text = clean_char_prompt(raw)
        extra = undress_tags.get(str(level), "")
        return f"{text}, {extra}" if extra else text

    female_text = girl_text(char.get("female", ""), char.get("clothed", ""), u1)
    partner_text = girl_text(role.get("외형", ""), role.get("착의", ""), u2)

    female_scene = scene.get("female_prompt", "")
    partner_scene = scene.get("partner_prompt", "")

    female_caption = _join_tags(female_text, female_scene)
    partner_caption = _join_tags(partner_text, partner_scene)

    return (base, female_caption, partner_caption, char.get("negative", ""),
            role.get("네거티브", ""), scene["width"], scene["height"])


# ═══════════════ NAI API ═══════════════

def _ref_fields(p):
    """바이브·캐릭터 레퍼런스 페이로드 필드 (NAIS3 와 같은 형태).
    호출 쪽에서 미리 준비해 `_vibes` / `_char_refs` 로 넣어 준다."""
    out = {}
    vibes = p.get("_vibes") or {}
    enc, st = vibes.get("encoded") or [], vibes.get("strengths") or []
    if enc:
        ies = vibes.get("ies") or [0.7] * len(enc)
        out["reference_image_multiple"] = enc
        out["reference_strength_multiple"] = st
        # ★ 길이가 reference_image_multiple 과 반드시 같아야 한다.
        #   다르면 NAI 가 400 "must be the same length" 로 거부한다.
        out["reference_information_extracted_multiple"] = ies
    refs = p.get("_char_refs") or {}
    imgs = refs.get("images") or []
    if imgs and enc:
        # SDStudio 는 V4.5 에서 캐릭레퍼가 있으면 바이브를 무효화하고 UI 도 잠근다.
        # NAI 가 400 을 주는지 품질만 떨어지는지는 **검증하지 못했다** — 막지 않고 알리기만 한다
        # (사용자가 일부러 같이 쓸 수 있다). SDS-C
        log.warning(f"바이브 {len(enc)}개와 캐릭터 레퍼런스 {len(imgs)}개를 함께 보냅니다 — "
                    "다른 앱은 이 조합을 막습니다. 결과가 이상하면 하나만 켜 보세요.")
    if imgs:
        out["director_reference_images"] = imgs
        # 설명은 **v4 프롬프트와 같은 모양의 객체**다 (문자열이 아니다).
        # 실제 NAI 메타데이터에 use_coords·use_order 까지 들어 있다.
        out["director_reference_descriptions"] = [
            {"caption": {"base_caption": t, "char_captions": []},
             "use_coords": False, "use_order": False, "legacy_uc": False}
            for t in (refs.get("types") or [])]
        # ★ 정보추출은 **정확히 1.0** 이어야 한다
        #   (0.7 을 보내면 400 "must be EXACTLY 1.0 for each entry at this time")
        out["director_reference_information_extracted"] = [1.0] * len(imgs)
        # ⚠ **요청 키와 메타데이터 키가 다르다.** 실측으로 가렸다:
        #   요청  → `director_reference_strength_values` (이걸 안 쓰면
        #           400 "arrays must have matching lengths: … strengths=0")
        #   기록  → `director_reference_strengths` (이미지 메타데이터에 남는 이름)
        #   메타데이터에 있는 이름을 그대로 요청에 쓰면 조용히 길이 0 으로 잡힌다.
        # 1차 세기 — **자유롭게 조절된다.** 실측으로 0.0 · 0.5 · 1.5 · 2.0 · -0.5 전부 200 이고
        #   같은 시드에서 0.0 vs 2.0 의 픽셀 차이가 104.69/255 였다 (무시되지 않는다).
        #   ⚠ ComfyUI_NAIDGenerator 가 primary 를 1.0 으로 고정하는 것은 **그쪽 설계 선택**이다.
        #      API 제약으로 착각해 한때 우리도 1.0 으로 박아 뒀다가 실측으로 되돌렸다.
        #   (`information_extracted` 만은 진짜로 1.0 강제다 — 검증 메시지로 확인)
        out["director_reference_strength_values"] = refs.get("strengths") or []
        out["director_reference_secondary_strength_values"] = [
            1 - f for f in (refs.get("fidelities") or [])]
    return out


def fixed_seed(cfg):
    """NAI 시드 고정값. 비어 있거나 0이면 None (= 장마다 다른 시드).
    그림체를 통째로 적용하면 원본 시드가 여기 들어가 그림이 그대로 재현된다."""
    try:
        v = int(cfg.get("nai_seed") or 0)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def seed_for(cfg, base_seed, index):
    """이 한 장에 쓸 NAI 시드.

    NAI 는 한 장에 시드 하나다. 그 성질을 그대로 두고 '회차'만 얹었다.
      · NAI 시드를 넣으면  → 모든 장이 그 시드 (완전 고정)
      · 0이면              → 회차 기준시드 + 장 번호  →
                            장마다 다른 시드지만, 같은 회차를 다시 돌리면 같은 시드가 나온다
    이렇게 하면 '회차'는 NAI 동작을 바꾸지 않고 재현성만 더해 주는 기능이 된다."""
    fixed = fixed_seed(cfg)
    if fixed:
        return fixed
    return (int(base_seed) + int(index)) % (2 ** 32)


SAMPLERS = ["k_euler_ancestral", "k_euler", "k_dpmpp_2s_ancestral",
            "k_dpmpp_2m", "k_dpmpp_2m_sde", "k_dpmpp_sde"]
NOISE_SCHEDULES = ["karras", "native", "exponential", "polyexponential"]
MODELS = [
    ("nai-diffusion-4-5-full", "V4.5 Full (기본)"),
    ("nai-diffusion-4-5-curated", "V4.5 Curated"),
    ("nai-diffusion-4-full", "V4 Full"),
    ("nai-diffusion-4-curated-preview", "V4 Curated"),
    ("nai-diffusion-3", "V3 (Anime)"),
    ("nai-diffusion-furry-3", "V3 Furry"),
]
UC_PRESETS = [(0, "Heavy"), (1, "Light"), (3, "Human Focus"), (4, "None")]


def model_id_from_metadata(value, fallback="nai-diffusion-4-5-full"):
    """NAI PNG의 표시명/Source 문자열을 실제 API 모델 ID로 바꾼다.

    Source 끝의 8자리 빌드 해시는 모델 버전이 아니므로 버전 토큰만 판정한다.
    알 수 없는 구형/타사 모델은 사용자가 고른 지원 모델로 안전하게 되돌린다.
    """
    supported = {model_id for model_id, _label in MODELS}
    fallback = fallback if fallback in supported else "nai-diffusion-4-5-full"
    text = str(value or "").strip()
    if text in supported:
        return text
    low = text.casefold()
    curated = "curated" in low
    if re.search(r"\bv?4(?:[._ -]?5)\b", low):
        return "nai-diffusion-4-5-curated" if curated else "nai-diffusion-4-5-full"
    if "furry" in low and re.search(r"\bv?3\b", low):
        return "nai-diffusion-furry-3"
    if re.search(r"\bv?4\b", low):
        return "nai-diffusion-4-curated-preview" if curated else "nai-diffusion-4-full"
    if re.search(r"\bv?3\b", low) or low.startswith("stable diffusion xl"):
        return "nai-diffusion-3"
    return fallback


# ══ 모델별 퀄리티 태그·UC 프리셋의 실제 문구 ═══════════════════════════
# NovelAI 공식 문서(2026-07-27 확인):
#   https://docs.novelai.net/en/image/qualitytags/
#   https://docs.novelai.net/en/image/undesiredcontent/
QUALITY_SUFFIX_TEXT = {
    "nai-diffusion-4-5-full":
        "very aesthetic, masterpiece, no text",
    "nai-diffusion-4-5-curated":
        "masterpiece, no text, -0.8::feet::, rating:general",
    "nai-diffusion-4-full":
        "no text, best quality, very aesthetic, absurdres",
    "nai-diffusion-4-curated-preview":
        "rating:general, amazing quality, very aesthetic, absurdres",
    "nai-diffusion-3":
        "best quality, amazing quality, very aesthetic, absurdres",
    "nai-diffusion-furry-3":
        "{best quality}, {amazing quality}",
}
# 기존 테스트·외부 호출 호환용 이름. 실제 조립은 quality_suffix_text(model)을 쓴다.
QUALITY_SUFFIX = ", " + QUALITY_SUFFIX_TEXT["nai-diffusion-4-5-full"]


def quality_suffix_text(model):
    return QUALITY_SUFFIX_TEXT.get(str(model or ""), "")


def annotate_nai_comment(comment, quality_toggle, uc_preset):
    """NAI가 생략하는 UI 토글 두 값을 결과 Comment JSON에 명시해 왕복을 보장한다."""
    try:
        data = json.loads(str(comment or ""))
        if not isinstance(data, dict):
            return comment
        data["qualityToggle"] = bool(quality_toggle)
        data["ucPreset"] = int(uc_preset)
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return comment


def merge_quality_suffix(prompt, model):
    text = quality_suffix_text(model)
    raw = str(prompt or "").rstrip().rstrip(",")
    if not text or raw.endswith(text):
        return raw
    return f"{raw}, {text}" if raw else text


def split_quality_suffix(prompt, model=None):
    """끝에 붙은 공식 퀄리티 태그를 떼어 (사용자 프롬프트, 켜짐)으로."""
    raw = str(prompt or "").strip().rstrip(",")
    candidates = []
    if model and quality_suffix_text(model):
        candidates.append(quality_suffix_text(model))
    else:
        candidates.extend(QUALITY_SUFFIX_TEXT.values())
    # 이전 배포본이 넣던 잘못된 location 포함 문구도 가져오기 때만 떼어낸다.
    candidates.extend([
        "location, very aesthetic, masterpiece, no text",
        "location, masterpiece, no text, -0.8::feet::, rating:general",
    ])
    for text in sorted(set(candidates), key=len, reverse=True):
        if raw == text:
            return "", True
        if raw.endswith(", " + text):
            return raw[:-(len(text) + 2)].rstrip().rstrip(","), True
        if raw.startswith(text + ", "):
            return raw[len(text) + 2:].lstrip().lstrip(","), True
        marker = ", " + text + ", "
        if marker in raw:
            left, right = raw.split(marker, 1)
            joined = ", ".join(x for x in (left.rstrip(" ,"), right.lstrip(" ,")) if x)
            return joined, True
    return raw, False


def restore_quality_prompt(prompt, model, params):
    """명시된 메타데이터 상태를 우선하고, 없는 구형 파일만 문구로 추정한다."""
    if "quality_toggle" in params:
        enabled = bool(params["quality_toggle"])
        if not enabled:
            return str(prompt or "").strip().rstrip(","), False
        base, _ = split_quality_suffix(prompt, model)
        return base, True
    return split_quality_suffix(prompt, model)


# ⚠ NAI 는 요청의 `ucPreset` 숫자를 **그림에 반영하지 않는다.** 실측(2026-07):
#     같은 시드로 ucPreset 0 과 4 를 보냈을 때 픽셀 차이 0.00/255
#     같은 시드로 프리셋 문구를 네거티브에 직접 합쳤을 때 차이 58.65/255
#   즉 `ucPreset` 은 화면 상태를 적어 두는 값일 뿐이고, **문구를 합치는 것은
#   클라이언트 몫**이다. 숫자만 보내면 프리셋은 아무 일도 하지 않는다.
# `nsfw` 는 사용자 UC일 수 있지만 프리셋 자체에는 없다. 자동으로 끼워 넣지 않는다.
_V45_FULL_HEAVY = ("lowres, artistic error, film grain, scan artifacts, worst quality, "
                   "bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, "
                   "halftone, screentone, multiple views, logo, too many watermarks, negative space, "
                   "blank page")
UC_PRESET_TEXT = {
    "nai-diffusion-4-5-full": {
        0: _V45_FULL_HEAVY,
        1: ("lowres, artistic error, scan artifacts, worst quality, bad quality, jpeg artifacts, "
            "multiple views, very displeasing, too many watermarks, negative space, blank page"),
        3: _V45_FULL_HEAVY + ", @_@, mismatched pupils, glowing eyes, bad anatomy",
        4: "",
    },
    "nai-diffusion-4-5-curated": {
        0: ("blurry, lowres, upscaled, artistic error, film grain, scan artifacts, worst quality, "
            "bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, "
            "multiple views, logo, too many watermarks, negative space, blank page"),
        1: ("blurry, lowres, upscaled, artistic error, scan artifacts, jpeg artifacts, logo, "
            "too many watermarks, negative space, blank page"),
        3: ("blurry, lowres, upscaled, artistic error, film grain, scan artifacts, bad anatomy, "
            "bad hands, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic "
            "aberration, halftone, multiple views, logo, too many watermarks, @_@, mismatched "
            "pupils, glowing eyes, negative space, blank page"),
        4: "",
    },
    "nai-diffusion-4-full": {
        0: ("blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, "
            "jpeg artifacts, very displeasing, chromatic aberration, multiple views, logo, "
            "too many watermarks"),
        1: "blurry, lowres, error, worst quality, bad quality, jpeg artifacts, very displeasing",
        4: "",
    },
    "nai-diffusion-4-curated-preview": {
        0: ("blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, "
            "jpeg artifacts, very displeasing, chromatic aberration, logo, dated, signature, "
            "multiple views, gigantic breasts"),
        1: ("blurry, lowres, error, worst quality, bad quality, jpeg artifacts, very displeasing, "
            "logo, dated, signature"),
        4: "",
    },
    "nai-diffusion-3": {
        0: ("lowres, {bad}, error, fewer, extra, missing, worst quality, jpeg artifacts, bad "
            "quality, watermark, unfinished, displeasing, chromatic aberration, signature, extra "
            "digits, artistic error, username, scan, [abstract],"),
        1: "lowres, jpeg artifacts, worst quality, watermark, blurry, very displeasing,",
        3: ("lowres, {bad}, error, fewer, extra, missing, worst quality, jpeg artifacts, bad "
            "quality, watermark, unfinished, displeasing, chromatic aberration, signature, extra "
            "digits, artistic error, username, scan, [abstract], bad anatomy, bad hands, @_@, "
            "mismatched pupils, heart-shaped pupils, glowing eyes,"),
        4: "",
    },
    "nai-diffusion-furry-3": {
        0: ("{{worst quality}}, [displeasing], {unusual pupils}, guide lines, {{unfinished}}, "
            "{bad}, url, artist name, {{tall image}}, mosaic, {sketch page}, comic panel, impact "
            "(font), [dated], {logo}, ych, {what}, {where is your god now}, {distorted text}, "
            "repeated text, {floating head}, {1994}, {widescreen}, absolutely everyone, sequence, "
            "{compression artifacts}, hard translated, {cropped}, {commissioner name}, unknown "
            "text, high contrast,"),
        1: ("{worst quality}, guide lines, unfinished, bad, url, tall image, widescreen, "
            "compression artifacts, unknown text,"),
        4: "",
    },
}


def uc_preset_text(model, preset):
    """이 모델에서 이 프리셋의 문구. 모르는 모델이면 빈 문자열."""
    return UC_PRESET_TEXT.get(str(model or ""), {}).get(
        int(preset or 0), ""
    ).strip().rstrip(",")


def merge_uc_preset(negative, model, preset):
    """프리셋 문구를 네거티브 앞에 붙인다. 이미 붙어 있으면 그대로 둔다."""
    txt = uc_preset_text(model, preset)
    if not txt:
        return negative or ""
    neg = (negative or "").strip()
    if neg == txt or txt in neg:
        return neg
    return f"{txt}, {neg}" if neg else txt


def split_uc_preset(negative, model=None):
    """네거티브 앞에 붙은 프리셋 문구를 떼어 (프리셋번호, 사용자부분) 으로.

    그림에서 설정을 읽어 올 때 쓴다. 떼지 않으면 다시 생성할 때 문구가 **두 번**
    붙는다. 가장 긴 것부터 맞춰 본다 (3 번은 0 번을 포함하므로)."""
    neg = (negative or "").strip()
    table = UC_PRESET_TEXT.get(str(model or ""), {})
    candidates = list(table.items()) if table else [
        item for preset_table in UC_PRESET_TEXT.values() for item in preset_table.items()
    ]
    candidates = [(num, txt.strip().rstrip(",")) for num, txt in candidates]
    for num, txt in sorted(candidates, key=lambda kv: -len(kv[1])):
        if not txt:
            continue
        at = neg.find(txt)
        if at < 0:
            continue
        before = neg[:at].strip().strip(",").strip()
        after = neg[at + len(txt):].strip().strip(",").strip()
        user = ", ".join(part for part in (before, after) if part)
        return num, user
    return None, neg
RESOLUTIONS = [(832, 1216, "세로"), (1216, 832, "가로"), (1024, 1024, "정사각"),
               (1024, 1536, "세로 대형"), (1536, 1024, "가로 대형"),
               (1472, 1472, "정사각 대형"), (1920, 1088, "와이드"), (1088, 1920, "세로 와이드"),
               (512, 768, "세로 작게"), (768, 512, "가로 작게"), (640, 640, "정사각 작게")]

# ── 모델 세대별로 쓰이는 파라미터 ──────────────────────────────────────
# 실제 NAI 메타데이터 1,687장을 훑어 확인한 결과:
#   V4/V4.5 이미지에서 아래 값들은 예외 없이 중립값(false / 0.0 / 1.0)이었다.
#   V4 계열에 켜면 무시되거나 결과가 망가지므로, 모델이 V4면 강제로 중립값을 보낸다.
V3_ONLY = {
    "smea": ("sm", False),                       # SMEA — V3 전용
    "smea_dyn": ("sm_dyn", False),               # SMEA DYN — V3 전용
    "dynamic_thresholding": ("dynamic_thresholding", False),   # Decrisper — V3 전용
    "uncond_scale": ("uncond_scale", 0.0),       # Undesired Content Strength — V3 전용
    "controlnet_strength": ("controlnet_strength", 1.0),       # ControlNet — V3 전용
    "legacy_v3_extend": ("legacy_v3_extend", False),
}
# V4 계열에서만 의미가 있는 것 (V3에서는 무시됨)
V4_ONLY = ("variety", "use_coords", "deliberate_euler_ancestral_bug", "prefer_brownian")


def is_v4_model(model):
    return str(model or "").startswith("nai-diffusion-4")


def variety_sigma(model):
    """Variety+ 의 기준 시그마 계수. 모델 세대마다 다르다 (SDS-A).
    V4.5 계열 58.0 · 그 외 19.0. 실제 NAI 이미지 128장 역산: 58 이 121장, 19 는 4장."""
    return 58.0 if "4-5" in str(model or "") else 19.0


def _variety_sigma_value(model, width, height, variety, p):
    """Variety+ 값. 캐릭터 레퍼런스와의 조합은 경고하되 사용자 선택을 보존한다.

    SDStudio와 NAIA가 이 조합을 피한다는 간접 근거는 있지만 우리 실호출 재현은 없다.
    따라서 자동으로 기능을 끄지 않고, 진단에 조건부 위험을 남긴 뒤 그대로 전송한다.
    """
    if not variety:
        return None
    if (p.get("_char_refs") or {}).get("images"):
        log.warning(
            "Variety+와 캐릭터 레퍼런스를 함께 보냅니다 — 다른 앱 두 곳은 결과 이상을 "
            "피하려 이 조합을 막습니다. 문제가 생기면 둘 중 하나를 꺼 보세요 (SDS-B 조건부)"
        )
    return variety_sigma(model) * ((width * height) / (832 * 1216)) ** 0.5


POS_GRID = [0.1, 0.3, 0.5, 0.7, 0.9]      # NAI 좌표 격자 (실제 이미지에서 이 5값만 나온다)


def active_people(slots, centers=None, extra=None):
    """캐릭터 칸에서 **켠 인물만** 골라 (people, centers) 로 돌려준다.
    칸은 6명 넘게 둬도 되고, 보내는 것만 6명으로 자른다 (`enabled: False` 는 건너뜀).
    좌표는 **칸 순서**로 저장돼 있으므로 켠 인물에 맞춰 같이 골라야 짝이 안 어긋난다."""
    centers = centers or []
    people, ctrs = [], []
    for i, sl in enumerate(slots or []):
        if not isinstance(sl, dict) or sl.get("enabled") is False:
            continue
        cap = slot_prompt(sl)
        if not (cap or "").strip():
            continue
        people.append({"prompt": cap, "negative": sl.get("negative", "")})
        c = centers[i] if i < len(centers) and isinstance(centers[i], dict) else None
        ctrs.append(c or {"x": 0.5, "y": 0.5})
    for e in (extra or []):
        cap = strip_comment_lines(e.get("prompt") or "")   # 씬 인물 칸도 같은 규칙 (CQA-003)
        if cap.strip():
            people.append({"prompt": cap,
                           "negative": strip_comment_lines(e.get("negative") or "")})
            ctrs.append(e.get("center") or {"x": 0.5, "y": 0.5})
    if len(people) > MAX_CHARS:
        log.warning(f"켠 인물이 {len(people)}명입니다 — NAI 상한 {MAX_CHARS}명까지만 보냅니다 "
                    f"(칸은 그대로 남습니다).")
        people, ctrs = people[:MAX_CHARS], ctrs[:MAX_CHARS]
    return people, ctrs


def with_centers(cfg, ctrs):
    """params 사본에 이 장에 쓸 좌표를 실어 준다 (원본 cfg 는 안 건드린다)."""
    q = dict(cfg or {})
    q["char_centers"] = ctrs
    return q


def spread_centers(n):
    """인물 n 명을 격자에 **겹치지 않게** 벌린 좌표.
    한 줄은 5칸까지라 6명부터는 두 줄로 나눈다 (안 그러면 좌표가 겹쳐
    좌표를 켜도 분리가 안 된다 — 실측에서 0.5 가 두 번 나와 잡았다).
    2명은 실제 NAI 이미지에서 가장 흔한 0.3 / 0.7 을 쓴다."""
    if n <= 1:
        return [{"x": 0.5, "y": 0.5}]
    if n == 2:
        return [{"x": 0.3, "y": 0.5}, {"x": 0.7, "y": 0.5}]
    rows = 1 if n <= 5 else 2
    per = -(-n // rows)                    # 줄당 인원 (올림)
    ys = [0.5] if rows == 1 else [0.3, 0.7]

    def pick(k, total):
        """격자 5칸에서 total 명을 고르게 — 인덱스가 겹치지 않게 고른다"""
        if total == 1:
            return POS_GRID[2]
        step = 4 / (total - 1)
        return POS_GRID[min(4, round(k * step))]

    out = []
    for i in range(n):
        r = i // per
        k = i % per
        cnt = min(per, n - r * per)
        out.append({"x": pick(k, cnt), "y": ys[min(r, len(ys) - 1)]})
    return out


def _i2i_fields(i2i, action, seed):
    """img2img · 인페인트 전용 필드. 일반 생성이면 아무것도 안 넣는다."""
    if action == "generate" or not i2i.get("image"):
        return {}
    # 강도 상한이 모드마다 다르다 — 인페인트 1.00 / img2img 0.99.
    # img2img 에서 1.00 은 원본을 아예 안 보는 뜻이라 NAI 가 거부한다.
    cap = 1.0 if action == "infill" else 0.99
    strength = min(cap, max(0.01, float(i2i.get("strength", 0.7))))
    out = {
        "image": i2i["image"],                       # 원본 PNG base64
        "strength": strength,                        # 얼마나 바꿀지 (0=원본, 1=완전히)
        "noise": float(i2i.get("noise", 0.0)),
        # NAI 웹 실캡처와 비교 구현 4곳이 본 시드보다 1 작은 uint32를 쓴다.
        "extra_noise_seed": (int(i2i.get("seed") or seed) - 1) % (2**32),
        "color_correct": False,
    }
    if action == "infill":
        out["mask"] = i2i["mask"]                    # 칠한 곳만 다시 그린다
        # 인페인트는 칠하지 않은 곳을 원본 그대로 둬야 한다
        out["add_original_image"] = True
        out["inpaintImg2ImgStrength"] = strength
    return {k: v for k, v in out.items() if v is not None}


def call_nai_api(token, base_prompt, female_caption, male_caption, negative, width, height,
                 char_negative="", male_negative="", scale=5.5, cfg_rescale=0.56, steps=28,
                 sampler="k_euler_ancestral", scheduler="karras", uc_preset=3,
                 seed=None, variety=False, params=None, chars=None):
    """params: 설정.json 의 고급 파라미터 dict (없으면 기존 기본값 그대로)
    chars: 인물 목록 [{prompt, negative}, …] — 주면 female/male 대신 이것을 쓴다 (최대 6명)"""
    p = dict(params or {})
    # ── 전처리 순서: 주석 제거 → 조각 치환 → 정규화 ──────────────────
    # ⚠ 이 순서와 대상 목록이 중요하다 (CQA-004·005):
    #   ① 주석을 **먼저** 지워야 메모 속 `<*이름>` 이 순번을 헛되이 소비하지 않는다.
    #   ② `chars=` 로 온 인물 칸도 함께 풀어야 한다 — 예전엔 base/negative 와
    #      옛 female/male 인자만 풀어서 캐릭터 칸의 조각이 그대로 NAI 로 나갔다.
    #   ③ 한 이미지의 모든 칸을 **한 번의 resolve_fragments** 로 처리해야
    #      `<*이름>` 순번이 칸마다 따로 돌지 않는다.
    chars_list = []
    if chars:
        for c in chars:
            if isinstance(c, dict):
                chars_list.append([c.get("prompt", ""), c.get("negative", "")])
            else:
                pair = (list(c) + ["", ""])[:2]
                chars_list.append([pair[0], pair[1]])
    fixed = [strip_comment_lines(x) for x in
             (base_prompt, negative, female_caption, male_caption, char_negative, male_negative)]
    flat_chars = [strip_comment_lines(x) for pair in chars_list for x in pair]
    if p.get("use_fragments", True):
        resolved, counters = resolve_fragments(fixed + flat_chars,
                                               counters=p.get("_frag_counters"))
        fixed, flat_chars = list(resolved[:6]), list(resolved[6:])
        if p.get("_frag_counters") is not None:
            p["_frag_counters"].update(counters)     # 호출자가 이어서 쓴다
    # 숫자로 끝나는 태그가 `::` 에 붙으면 NAI 가 그 숫자를 새 가중치로 읽어
    # 묶음이 닫히지 않는다 (`2::tag_number_37::` → 37 이 가중치가 됨).
    # 닫는 `::` 앞에 공백을 넣어 원래 의도대로 전달한다. **캐릭터 칸도 똑같이.**
    (base_prompt, negative, female_caption, male_caption,
     char_negative, male_negative) = [normalize_prompt(x) for x in fixed]
    flat_chars = [normalize_prompt(x) for x in flat_chars]
    for i in range(len(chars_list)):
        chars_list[i] = [flat_chars[i * 2], flat_chars[i * 2 + 1]]
    model = p.get("model") or "nai-diffusion-4-5-full"
    if is_v4_model(model):
        # V3 전용 값이 남아 있어도 V4에서는 중립값으로 보낸다 (결과 망가짐 방지)
        for key, (_, neutral) in V3_ONLY.items():
            if p.get(key) not in (None, neutral):
                log.info(f"{key} 은(는) V3 전용이라 이 모델에서는 무시합니다 (중립값 {neutral})")
            p[key] = neutral
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    if p.get("quality_toggle"):
        base_prompt = merge_quality_suffix(base_prompt, model)
    # UC 프리셋도 여기서 합친다 — 숫자만 보내면 NAI 가 무시한다(실측 픽셀차 0.00).
    # 이미 붙어 있으면 그대로 두므로 그림에서 읽어 온 네거티브도 이중이 되지 않는다.
    negative = merge_uc_preset(negative, model, p.get("uc_preset"))

    # 차단해 둔 작가가 실제로 나가는 프롬프트에 있으면 알린다 (R5-01).
    # 막지는 않는다 — 사용자가 일부러 넣었을 수 있다. 다만 모르고 나가지는 않게.
    try:
        blocked = blocked_artists_in(base_prompt)
        if blocked:
            log.warning(f"⛔ 차단해 둔 작가가 프롬프트에 있습니다: {', '.join(blocked)}")
    except Exception:
        pass

    # 캐릭터 위치. NAI 는 인물마다 centers 를 하나씩 받는다.
    # ⚠ **위치 지정을 끄면 좌표를 보내지 않는다** — 0.5/0.5 로 보낸다 (MM-B).
    #   예전에는 꺼도 사용자가 고른 좌표가 그대로 나갔다. 그림은 안 바뀌지만(NAI 가 무시)
    #   **저장 메타데이터에 적용된 적 없는 좌표가 남아**, 나중에 그 그림을 불러오면
    #   "이 자리에 놓고 뽑았다"고 오해하게 된다. 공홈·NAIS3-MM·nais_blue 모두 끄면 0.5/0.5 다.
    use_coords = bool(p.get("use_coords", False))
    ctrs = p.get("char_centers") or []

    def center(i):
        if not use_coords:
            return [{"x": 0.5, "y": 0.5}]
        c = ctrs[i] if i < len(ctrs) and isinstance(ctrs[i], dict) else {}
        return [{"x": float(c.get("x", 0.5)), "y": float(c.get("y", 0.5))}]

    # 인물 목록 — NAI 는 **최대 6명**까지 받는다.
    #   chars 를 주면 그것을 쓰고, 없으면 예전처럼 여자/남자 두 칸을 쓴다
    #   (세팅=체위는 '주인공+상대역' 2인 구조라 그대로 둔다).
    people = []
    if chars:
        # 위에서 주석 제거·조각 치환·정규화를 마친 값이다 (CQA-004·005)
        for cap, ng in chars_list:
            if (cap or "").strip():
                people.append((cap, ng or ""))
    else:
        if female_caption:
            people.append((female_caption, char_negative or ""))
        if male_caption:
            people.append((male_caption, male_negative or ""))
    if len(people) > MAX_CHARS:
        log.warning(f"인물이 {len(people)}명인데 NAI 는 {MAX_CHARS}명까지입니다 — "
                    f"뒤쪽 {len(people)-MAX_CHARS}명은 보내지 않습니다.")
        people = people[:MAX_CHARS]

    char_captions, neg_char_captions = [], []
    for i, (cap, ng) in enumerate(people):
        char_captions.append({"char_caption": cap, "centers": center(i)})
        # 네거티브도 **인물 수만큼** 맞춰야 한다 (개수가 다르면 짝이 어긋난다)
        neg_char_captions.append({"char_caption": ng, "centers": center(i)})

    # img2img / 인페인트 — `_i2i` 가 있으면 그 모드로 보낸다.
    #   img2img : action="img2img" + image(base64) + strength/noise
    #   인페인트: action="infill"  + image + mask, 모델도 -inpainting 으로 바꿔야 한다
    i2i = p.get("_i2i") or {}
    action = "generate"
    if i2i.get("image"):
        action = "infill" if i2i.get("mask") else "img2img"
        if action == "infill" and not model.endswith("-inpainting"):
            model = model + "-inpainting"

    payload = {
        "input": base_prompt,
        "model": model,
        "action": action,
        "parameters": {
            "width": width, "height": height, "n_samples": 1, "steps": steps,
            "scale": scale, "uncond_scale": float(p.get("uncond_scale", 0.0)),
            "cfg_rescale": cfg_rescale,
            "sampler": sampler, "noise_schedule": scheduler,
            "seed": seed,
            "negative_prompt": negative,
            "params_version": 3, "legacy": False,
            "image_format": "png",
            # ⚠ `extra_passthrough_testing` 은 **메타데이터에만** 남는 값이다.
            #   요청에 넣으면 NAI 가 400 "extra_passthrough_testing is not allowed" 로 거부한다.
            #   (실제 이미지 99% 에 있다고 해서 요청에 넣어도 되는 건 아니다 — 실측으로 확인)
            "version": 1,
            "legacy_v3_extend": bool(p.get("legacy_v3_extend", False)),
            "add_original_image": True,
            "prefer_brownian": bool(p.get("prefer_brownian", True)),
            "deliberate_euler_ancestral_bug": bool(p.get("deliberate_euler_ancestral_bug", False)),
            "dynamic_thresholding": bool(p.get("dynamic_thresholding", False)),
            "dynamic_thresholding_percentile": 0.999,
            "dynamic_thresholding_mimic_scale": 10.0,
            "sm": bool(p.get("smea", False)), "sm_dyn": bool(p.get("smea_dyn", False)),
            # Variety+ 기준 시그마. **모델 세대마다 계수가 다르다** (SDS-A, 2026-07 실측).
            #   V4.5 계열 = 58.0 · 그 외 V4 = 19.0
            #   근거: 우리 수집물의 실제 NAI 이미지 128장을 역산하니 121장이 58, 4장만 19(옛 상수).
            #   SDStudio(nai.ts)도 같은 분기를 쓴다. 예전엔 19 고정이라 기본 모델(4-5-full)에서
            #   Variety+ 가 공홈의 1/3 강도로만 걸렸다.
            "skip_cfg_above_sigma": _variety_sigma_value(model, width, height, variety, p),
            "skip_cfg_below_sigma": 0.0,
            "ucPreset": uc_preset, "use_coords": use_coords,
            "cfg_sched_eligibility": "enable_for_post_summer_samplers",
            "explike_fine_detail": False, "minimize_sigma_inf": False,
            "uncond_per_vibe": True, "wonky_vibe_correlation": True,
            "controlnet_strength": float(p.get("controlnet_strength", 1)),
            "controlnet_model": None,
            "lora_unet_weights": None, "lora_clip_weights": None,
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": [],
            "normalize_reference_strength_multiple": True,
            **_ref_fields(p),
            **_i2i_fields(i2i, action, seed),
            # V4 웹 페이로드 12/12와 비교 구현 5/5가 함께 보내는 레거시 배열.
            # 서버 입력 호환뿐 아니라 NAI 표준 메타데이터 왕복에도 쓰인다.
            "characterPrompts": [
                {
                    "prompt": cap,
                    "uc": ng,
                    "center": center(i)[0],
                    "enabled": True,
                }
                for i, (cap, ng) in enumerate(people)
            ],
            "v4_prompt": {
                "caption": {"base_caption": base_prompt, "char_captions": char_captions},
                "use_coords": use_coords, "use_order": True, "legacy_uc": False,
            },
            "v4_negative_prompt": {
                "caption": {"base_caption": negative, "char_captions": neg_char_captions},
                "use_coords": use_coords, "use_order": False, "legacy_uc": False,
            },
            "request_type": "PromptGenerateRequest",
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/x-zip-compressed",
    }
    resp = requests.post(NAI_API_URL, json=payload, headers=headers, timeout=120)
    if resp.status_code == 429:
        wait = retry_after_seconds(resp.headers.get("Retry-After"), 60)
        raise RateLimitError(f"429 Too Many Requests — {wait:g}초 뒤 재시도", wait)
    if resp.status_code == 403:
        raise AccountBannedError("403 Forbidden — 계정 보호를 위해 즉시 중단합니다.")
    if resp.status_code == 401:
        raise AuthError("401 — 토큰이 만료되었거나 잘못되었습니다.")
    if resp.status_code != 200:
        raise APIError(
            f"HTTP {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
            retryable=(resp.status_code == 408 or resp.status_code >= 500),
        )

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        raw = zf.read(zf.namelist()[0])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    # NAI가 돌려준 원본 메타데이터를 이미지에 붙여 둔다.
    # 저장할 때 WebP EXIF 로 심어서, 나중에 그림만 보고도 시드·설정을 되찾을 수 있게 한다.
    chunks = png_text_chunks(raw)
    img.nai_seed = seed
    img.nai_comment = annotate_nai_comment(
        next((chunks[k] for k in chunks if k.lower() == "comment"), ""),
        p.get("quality_toggle", False),
        uc_preset,
    )
    return img


def out_format(cfg):
    """저장 포맷 — 공홈처럼 PNG / WebP 를 고를 수 있게. 기본은 WebP(용량이 작다)."""
    f = str((cfg or {}).get("save_format", "webp")).lower()
    return "png" if f == "png" else "webp"


def _ocargs(cfg):
    """save_with_meta 에 넘길 (clean, max_side) — 호출부를 짧게 유지하려고."""
    clean, side, _q = out_clean(cfg)
    return (clean, side)


def out_clean(cfg):
    """저장할 때 아예 메타 없이 · 가볍게 저장할지 (NAIS2-Custom 의 '메타데이터 제거 저장').
    반환: (메타지울까, 긴변상한, 품질)  — 긴변 0 이면 원본 크기."""
    c = cfg or {}
    if not c.get("save_clean"):
        return False, 0, int(c.get("save_quality", 92) or 92)
    return True, int(c.get("save_max_side", 0) or 0), int(c.get("save_quality", 92) or 92)


def _atomic_save_image(path, writer):
    """생성 결과도 완전히 인코딩된 뒤에만 최종 파일명으로 보이게 한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        writer(tmp)
        # Windows의 fsync는 읽기 전용 핸들을 거부할 수 있어 쓰기 가능한 핸들로 연다.
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def save_with_meta(img, path, quality=92, fmt="webp", clean=False, max_side=0):
    """생성 결과를 저장하면서 NAI 메타데이터(시드·프롬프트·설정)를 EXIF 로 심는다.
    이렇게 해두면 나중에 이 그림을 앱에 끌어다 놓아 그림체를 복원할 수 있다.
    fmt="png" 이면 확장자를 .png 로 바꿔 무손실로 저장한다.

    clean=True 면 **메타를 아예 안 넣고** 저장한다 (NAIS2-Custom 의 '메타데이터 제거 저장').
    스텔스(알파 LSB)가 들어갈 자리도 없애려고 픽셀을 새로 만든다.
    max_side>0 이면 긴 변을 줄여 함께 가볍게 만든다.
    ⚠ 이렇게 저장한 그림은 **끌어다 놓아도 그림체가 복원되지 않는다** — 공유용이다."""
    if clean:
        path = Path(path)
        if max_side and max(img.size) > max_side:
            r = max_side / max(img.size)
            img = img.resize((max(1, round(img.width * r)), max(1, round(img.height * r))),
                             Image.LANCZOS)
        if fmt == "png":
            path = path.with_suffix(".png")
            flat = Image.new("RGB", img.size)
            flat.putdata(list(img.convert("RGB").getdata()))
            _atomic_save_image(
                path, lambda tmp: flat.save(tmp, "PNG"))
        else:
            path = path.with_suffix(".webp")
            flat = Image.new("RGB", img.size)
            flat.putdata(list(img.convert("RGB").getdata()))
            _atomic_save_image(
                path, lambda tmp: flat.save(tmp, "WEBP", quality=quality))
        return path
    path = Path(path)
    if fmt == "png" and path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    elif fmt == "webp" and path.suffix.lower() != ".webp":
        path = path.with_suffix(".webp")
    exif_bytes = None
    comment = getattr(img, "nai_comment", "")
    try:
        if comment:
            ex = Image.Exif()
            ex[270] = comment                      # ImageDescription
            ex[305] = "NovelAI"                    # Software
            exif_bytes = ex.tobytes()
    except Exception as e:
        log.warning(f"EXIF 준비 실패(그림은 그대로 저장): {e}")
    if fmt == "png":
        # PNG 는 NAI 와 같은 방식으로 텍스트 청크에 넣는다 (EXIF 보다 널리 읽힌다)
        def save_png(tmp):
            try:
                from PIL import PngImagePlugin
                info = PngImagePlugin.PngInfo()
                if comment:
                    info.add_text("Comment", comment)
                    info.add_text("Software", "NovelAI")
                img.save(tmp, "PNG", pnginfo=info)
            except Exception as e:
                log.warning(f"PNG 메타 심기 실패(그림은 그대로 저장): {e}")
                img.save(tmp, "PNG")
        _atomic_save_image(path, save_png)
        return path
    def save_webp(tmp):
        try:
            if exif_bytes:
                img.save(tmp, "WEBP", quality=quality, exif=exif_bytes)
            else:
                img.save(tmp, "WEBP", quality=quality)
        except Exception:
            # EXIF 때문에 실패하면 메타 없이라도 저장
            img.save(tmp, "WEBP", quality=quality)
    _atomic_save_image(path, save_webp)
    return path


def available_output_path(path, fmt="webp"):
    """기존 생성물을 덮지 않는 실제 확장자 경로를 예약한다(단일 실행 owner 전제)."""
    path = Path(path).with_suffix(".png" if fmt == "png" else ".webp")
    if not path.exists():
        return path
    stem, suffix, n = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem}_{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


# ══════════════════════════════════════════════════════════════════════
#  메타데이터 제거 — 공유용 사본
#    NAI 그림에는 프롬프트가 **두 군데** 들어 있다:
#      ① PNG tEXt/zTXt/iTXt · WebP EXIF   ② 알파 채널 LSB (스텔스)
#    ①만 지우면 novelai.net/inspect 로 ②가 그대로 읽힌다. 둘 다 지워야 한다.
# ══════════════════════════════════════════════════════════════════════
# 메타 제거 사본 — 저장 폴더 설정을 따른다 (out_root)
def strip_dir(cfg=None):
    d = out_root(cfg) / "메타제거"
    d.mkdir(parents=True, exist_ok=True)
    return d
PICKS_FILE = PROFILE_DIR / "선별.json"     # 프로필별 (생성물이 갈리므로)
IMG_EXT = (".webp", ".png", ".jpg", ".jpeg")


def load_picks():
    """선별·즐겨찾기·가상 폴더. **원본 파일은 절대 옮기지 않는다** —
    경로에 이름표만 붙인다 (mm 의 '원본 경로 유지' 와 같은 생각)."""
    if PICKS_FILE.exists():
        try:
            d = load_json_recover(PICKS_FILE)
            if isinstance(d, dict):
                d.setdefault("picked", [])
                d.setdefault("fav", [])
                d.setdefault("folders", {})     # 폴더이름 → [경로…]
                d.setdefault("ranks", {})       # 경로 → 월드컵 순위(1등이 1)
                d.setdefault("ratings", {})     # 경로 → 0~5점
                d.setdefault("tags", {})        # 경로 → [짧은 판단 태그…]
                return normalize_picks(d)
        except Exception as e:
            log.warning(f"선별.json 읽기 실패: {e}")
    return {
        "picked": [], "fav": [], "folders": {}, "ranks": {},
        "ratings": {}, "tags": {},
    }


def normalize_picks(d):
    """선별 이름표를 작은 JSON 값으로 제한해 손상·무한 증식을 막는다."""
    d = dict(d or {})
    for key in ("picked", "fav"):
        d[key] = list(dict.fromkeys(
            str(path).replace("\\", "/") for path in (d.get(key) or [])
            if str(path).strip()
        ))
    clean_folders = {}
    for name, paths in (d.get("folders") or {}).items():
        clean_name = str(name).strip()[:40]
        if not clean_name or not isinstance(paths, list):
            continue
        # 긴 이름 둘이 같은 40자 이름으로 정리되어도 먼저 저장한 후보를 잃지 않는다.
        clean_folders[clean_name] = list(dict.fromkeys([
            *clean_folders.get(clean_name, []),
            *(
                str(path).replace("\\", "/") for path in paths
                if str(path).strip()
            ),
        ]))
    d["folders"] = clean_folders
    d["ranks"] = {
        str(path).replace("\\", "/"): max(1, int(rank))
        for path, rank in (d.get("ranks") or {}).items()
        if str(path).strip() and str(rank).lstrip("-").isdigit()
    }
    d["ratings"] = {
        str(path).replace("\\", "/"): max(1, min(5, int(score)))
        for path, score in (d.get("ratings") or {}).items()
        if str(path).strip() and str(score).isdigit() and int(score) > 0
    }
    clean_tags = {}
    for path, tags in (d.get("tags") or {}).items():
        if not str(path).strip() or not isinstance(tags, list):
            continue
        cleaned = list(dict.fromkeys(
            str(tag).strip()[:40] for tag in (tags or [])
            if str(tag).strip()
        ))[:12]
        if cleaned:
            clean_tags[str(path).replace("\\", "/")] = cleaned
    d["tags"] = clean_tags
    return d


def save_picks(d):
    cleaned = normalize_picks(d)
    atomic_write_json(PICKS_FILE, cleaned, indent=1)
    return cleaned


TRASH_DIR_NAME = ".NAI-휴지통"


def _path_is_inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    try:
        return path.is_relative_to(root)
    except AttributeError:
        return os.path.commonpath((str(path), str(root))) == str(root)


def output_file_for_preview(cfg, rel):
    """탐색기에서 보여 줄 출력 파일만 돌려준다.

    휴지통은 목록뿐 아니라 `/setout` 직접 URL에서도 열리지 않아야 한다.
    원래 경로를 복원하기 전까지는 삭제된 파일로 취급한다.
    """
    rel = str(rel or "").replace("\\", "/")
    if (not rel
            or TRASH_DIR_NAME.casefold() in
            {part.casefold() for part in Path(rel).parts}):
        return None
    root = out_root(cfg).resolve()
    trash_root = (root / TRASH_DIR_NAME).resolve()
    candidate = (root / rel).resolve()
    if (not _path_is_inside(candidate, root)
            or _path_is_inside(candidate, trash_root)
            or not candidate.is_file()):
        return None
    return candidate


def trash_output_files(cfg, targets, keep=()):
    """출력물을 즉시 지우지 않고 같은 출력 루트의 복구 가능한 묶음으로 옮긴다."""
    root = out_root(cfg).resolve()
    trash_root = (root / TRASH_DIR_NAME).resolve()
    keep = set(keep or ())
    batch_id = (datetime.now().strftime("%Y%m%d-%H%M%S")
                + f"-{time.time_ns() % 1_000_000:06d}")
    batch_dir = trash_root / batch_id
    moved = []
    picks = load_picks()
    for rel in targets or ():
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if not rel or rel in keep or rel.startswith(TRASH_DIR_NAME + "/"):
            continue
        source = (root / rel).resolve()
        if not _path_is_inside(source, root) or not source.is_file():
            continue
        dest = (batch_dir / rel).resolve()
        if not _path_is_inside(dest, batch_dir):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        moved.append({"original": rel, "trashed": dest.relative_to(root).as_posix()})
    if moved:
        moved_paths = {item["original"] for item in moved}
        labels = {}
        for rel in moved_paths:
            record = {}
            if rel in picks.get("picked", []):
                record["picked"] = True
            if rel in picks.get("fav", []):
                record["fav"] = True
            folders = [
                name for name, paths in picks.get("folders", {}).items()
                if rel in paths
            ]
            if folders:
                record["folders"] = folders
            for key in ("ranks", "ratings", "tags"):
                if rel in picks.get(key, {}):
                    record[key] = picks[key][rel]
            if record:
                labels[rel] = record
        atomic_write_json(batch_dir / "manifest.json", {
            "batch_id": batch_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "items": moved,
            "labels": labels,
        }, indent=2)
    return {
        "deleted": len(moved),
        "batch_id": batch_id if moved else None,
        # 호출자가 실제로 옮기지 못한 경로의 이름표까지 지우지 않도록 근거를 돌려준다.
        "paths": [item["original"] for item in moved],
    }


def restore_trash_batch(cfg, batch_id):
    """지운 묶음을 원래 위치로 복원한다. 충돌하면 번호를 붙여 기존 파일을 보존한다."""
    root = out_root(cfg).resolve()
    trash_root = (root / TRASH_DIR_NAME).resolve()
    batch = (trash_root / str(batch_id or "")).resolve()
    if not _path_is_inside(batch, trash_root):
        raise ValueError("잘못된 휴지통 묶음입니다.")
    manifest_path = batch / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("복원할 휴지통 묶음을 찾을 수 없습니다.")
    manifest = load_json_recover(manifest_path)
    restored = []
    restored_map = {}
    for item in manifest.get("items") or []:
        source = (root / str(item.get("trashed") or "")).resolve()
        target = (root / str(item.get("original") or "")).resolve()
        if (not _path_is_inside(source, batch)
                or not _path_is_inside(target, root)
                or not source.is_file()):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stem, suffix, serial = target.stem, target.suffix, 2
            while target.exists():
                target = target.with_name(f"{stem}_{serial}{suffix}")
                serial += 1
        shutil.move(str(source), str(target))
        restored_rel = target.relative_to(root).as_posix()
        restored.append(restored_rel)
        restored_map[str(item.get("original") or "").replace("\\", "/")] = restored_rel
    # 지울 때 함께 보관한 가상 이름표도 실제 복원 경로에 되붙인다.
    # 경로 충돌로 `(2)`가 붙었으면 옛 원래 경로가 아니라 새 파일에 붙여야 한다.
    labels = manifest.get("labels") or {}
    if restored_map and isinstance(labels, dict):
        with _JSON_IO_LOCK:
            picks = load_picks()
            for original, restored_rel in restored_map.items():
                record = labels.get(original) or {}
                # 이동 직후 프로세스가 꺼져 이름표 정리가 끝나지 못한 경우도 있다.
                # 원래 경로의 낡은 이름표를 먼저 떼고 실제 복원된 경로로 옮긴다.
                picks["picked"] = [x for x in picks["picked"] if x != original]
                picks["fav"] = [x for x in picks["fav"] if x != original]
                for paths in picks["folders"].values():
                    paths[:] = [x for x in paths if x != original]
                for key in ("ranks", "ratings", "tags"):
                    picks[key].pop(original, None)
                if record.get("picked") and restored_rel not in picks["picked"]:
                    picks["picked"].append(restored_rel)
                if record.get("fav") and restored_rel not in picks["fav"]:
                    picks["fav"].append(restored_rel)
                for name in record.get("folders") or []:
                    paths = picks["folders"].setdefault(str(name)[:40], [])
                    if restored_rel not in paths:
                        paths.append(restored_rel)
                for key in ("ranks", "ratings", "tags"):
                    if key in record:
                        picks[key][restored_rel] = record[key]
            save_picks(picks)
    manifest["restored_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["restored"] = restored
    atomic_write_json(manifest_path, manifest, indent=2)
    return {"restored": len(restored), "paths": restored}


def list_trash_batches(cfg):
    """앱을 다시 연 뒤에도 복원할 수 있도록 휴지통 묶음의 가벼운 목록만 만든다."""
    root = out_root(cfg).resolve()
    trash_root = (root / TRASH_DIR_NAME).resolve()
    if not trash_root.is_dir():
        return {"ok": True, "batches": [], "total_files": 0, "total_bytes": 0}
    rows = []
    for batch in sorted(trash_root.iterdir(), reverse=True):
        manifest_path = batch / "manifest.json"
        if not batch.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = load_json_recover(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        available, size = 0, 0
        for item in manifest.get("items") or []:
            path = (root / str(item.get("trashed") or "")).resolve()
            if _path_is_inside(path, batch) and path.is_file():
                available += 1
                try:
                    size += path.stat().st_size
                except OSError:
                    pass
        rows.append({
            "batch_id": str(manifest.get("batch_id") or batch.name),
            "created_at": str(manifest.get("created_at") or ""),
            "available": available,
            "total": len(manifest.get("items") or []),
            "bytes": size,
        })
    return {
        "ok": True,
        "batches": rows,
        "total_files": sum(row["available"] for row in rows),
        "total_bytes": sum(row["bytes"] for row in rows),
    }


_DIR_COUNT_CACHE = {}   # 경로 → (재귀 이미지 수, 기록 시각) — CQA-002 부분 조치


def _dir_img_count(p):
    """하위 폴더의 재귀 이미지 수 — 30초 캐시. 탐색기를 오갈 때마다
    전체 트리를 다시 걷는 낭비를 막는다 (완전한 서버측 페이징은 필터
    의미가 바뀌는 문제라 사용자 결정 대기)."""
    now = time.time()
    hit = _DIR_COUNT_CACHE.get(str(p))
    if hit and now - hit[1] < 30:
        return hit[0]
    n = sum(1 for f in p.rglob("*") if f.suffix.lower() in IMG_EXT)
    _DIR_COUNT_CACHE[str(p)] = (n, now)
    return n


def list_output(sub="", cfg=None, limit=0, offset=0, only_pick=False, only_fav=False):
    """생성물 뿌리 아래를 훑는다. sub 가 비면 최상위.
    저장 폴더를 바꿨으면(out_dir) 그쪽을 본다 — 탐색기와 저장이 어긋나면 안 된다.
    limit>0 이면 정렬·필터 뒤 해당 페이지만 반환한다. 기본 0은 내부 호환용 전체 반환."""
    root = out_root(cfg).resolve()
    base = (root / sub).resolve() if sub else root
    trash_root = (root / TRASH_DIR_NAME).resolve()
    try:
        inside = base.is_relative_to(root)
    except AttributeError:
        inside = str(base).startswith(str(root))
    if (not (inside and base.is_dir())
            or base == trash_root or _path_is_inside(base, trash_root)):
        return {"ok": False, "error": "그런 폴더가 없습니다."}
    dirs, files = [], []
    for p in sorted(base.iterdir()):
        if p.name == TRASH_DIR_NAME:
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if p.is_dir():
            dirs.append({"name": p.name, "path": rel, "count": _dir_img_count(p)})
        elif p.suffix.lower() in IMG_EXT:
            st = p.stat()
            files.append({"name": p.name, "path": rel,
                          "bytes": st.st_size, "mtime": int(st.st_mtime)})
    files.sort(key=lambda x: -x["mtime"])
    picks = load_picks()
    if only_pick:
        chosen = set(picks["picked"])
        files = [f for f in files if f["path"] in chosen]
    if only_fav:
        chosen = set(picks["fav"])
        files = [f for f in files if f["path"] in chosen]
    total = len(files)
    offset = max(0, int(offset or 0))
    limit = max(0, min(500, int(limit or 0)))
    if limit:
        files = files[offset:offset + limit]
    else:
        offset = 0
    return {"ok": True, "dir": sub, "dirs": dirs, "files": files,
            "total": total, "offset": offset,
            "has_more": bool(limit and offset + len(files) < total),
            "picked": picks["picked"], "fav": picks["fav"],
            "folders": picks["folders"], "ranks": picks.get("ranks", {}),
            "ratings": picks.get("ratings", {}),
            "tags": picks.get("tags", {}),
            "up": str(Path(sub).parent).replace("\\", "/") if sub and sub != "." else ""}


def strip_metadata(data, filename="image.png", max_side=0, quality=95, force_webp=False):
    """메타를 지운 이미지 바이트를 돌려준다. (bytes, 확장자)
    max_side>0 이면 긴 변을 그 크기로 줄인다(경량화). quality 는 WebP 품질."""
    with Image.open(io.BytesIO(data)) as im:
        if max_side and max(im.size) > max_side:
            r = max_side / max(im.size)
            im = im.resize((max(1, round(im.width * r)), max(1, round(im.height * r))),
                           Image.LANCZOS)
        has_alpha = (im.mode in ("RGBA", "LA") or "transparency" in im.info) and not force_webp
        # 알파를 살려야 하는 그림(배경 제거본)이면 RGBA 로, 아니면 RGB 로.
        # 어느 쪽이든 **픽셀을 새로 만들어** 스텔스 LSB 를 함께 날린다.
        if has_alpha:
            im = im.convert("RGBA")
            r, g, b, a = im.split()
            # 알파 최하위 비트를 0 으로 밀어 숨은 문자열을 지운다
            a = a.point(lambda v: v & 0xFE)
            clean = Image.merge("RGBA", (r, g, b, a))
            out = io.BytesIO()
            clean.save(out, "PNG")          # info 를 안 넘기므로 텍스트 청크도 사라진다
            return out.getvalue(), ".png"
        clean = Image.new("RGB", im.size)
        clean.putdata(list(im.convert("RGB").getdata()))
        out = io.BytesIO()
        clean.save(out, "WEBP", quality=int(quality))
        return out.getvalue(), ".webp"


def strip_and_save(data, filename="image.png", max_side=0, quality=95, force_webp=False, cfg=None):
    _dir = strip_dir(cfg)
    blob, ext = strip_metadata(data, filename, max_side, quality, force_webp)
    stem = _safe_name(Path(filename).stem) or "image"
    target, k = _dir / f"{stem}{ext}", 2
    while target.exists():
        target = _dir / f"{stem} ({k}){ext}"
        k += 1
    _atomic_write_bytes(target, blob, keep_backup=False)
    # 정말 지워졌는지 스스로 확인한다 (스텔스까지).
    # ⚠ extract_nai_metadata 는 **아무것도 없어도 dict 를 돌려준다.**
    #   bool() 로 재면 늘 '남아 있음' 이 되므로 알맹이를 봐야 한다.
    left = extract_nai_metadata(blob, "image/png" if ext == ".png" else "image/webp") or {}
    remains = bool((left.get("raw") or {}) or (left.get("base") or "")
                   or (left.get("negative") or "") or (left.get("characters") or []))
    return {"ok": True, "file": target.name,
            "path": str(target.relative_to(out_root(cfg))).replace("\\", "/"),
            "bytes": len(blob), "before": len(data), "남은메타": remains}


# ══════════════════════════════════════════════════════════════════════
#  조각 (와일드카드) — 프롬프트 어디서나 쓰는 치환 계층
#    <이름>   그 조각의 줄 하나를 무작위로
#    <*이름>  줄을 차례대로 (배치 내내 순번이 이어진다 · 상태.json 에 저장)
#    {a|b|c}  그 자리에서 셋 중 하나
#  한 줄짜리 조각은 사실상 '고정 치환' 이 된다.
#  세팅·씬·기본 생성 **어디서나** 같은 규칙으로 먹는다.
# ══════════════════════════════════════════════════════════════════════
FRAG_DIR = BASE_DIR / "조각"               # 공용 — 프롬프트 자산은 나눌 이유가 없다
FRAG_MAX_DEPTH = 5          # 조각이 조각을 부를 때 무한루프 방지


def list_fragments():
    """조각/*.txt → {이름: [줄, …]}. 빈 줄은 버린다."""
    out = {}
    if not FRAG_DIR.exists():
        return out
    for p in sorted(FRAG_DIR.glob("*.txt")):
        try:
            lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()]
        except Exception as e:
            log.warning(f"조각 읽기 실패({p.name}): {e}")
            continue
        out[p.stem] = [ln for ln in lines if ln]
    return out


def save_fragment(name, lines):
    FRAG_DIR.mkdir(exist_ok=True)
    safe = _safe_name(name) or "조각"
    atomic_write_text(
        FRAG_DIR / f"{safe}.txt",
        "\n".join(x.strip() for x in lines if x.strip()) + "\n")
    return safe


# ══════════════════════════════════════════════════════════════════════
#  씬 모드 — NAIS3 식 평면 씬 목록. 세팅과 **별도로 병존**한다.
#    세팅 = 5장 묶음 + 문맥에 반응하는 옵션 (구조적 대규모)
#    씬   = 이름·프롬프트·네거티브·해상도만 있는 낱개 (가볍게 즉석 변주)
#  둘은 서로를 대체하지 않는다. 조각은 양쪽 모두에서 먹는다.
# ══════════════════════════════════════════════════════════════════════
SCENES_FILE = PROFILE_DIR / "씬.json"      # 프로필별 (계정마다 다른 작업)


def load_scenes():
    if not SCENES_FILE.exists():
        return []
    try:
        d = load_json_recover(SCENES_FILE)
        return d if isinstance(d, list) else d.get("씬", [])
    except Exception as e:
        log.warning(f"씬.json 읽기 실패: {e}")
        return []


def save_scenes(scenes):
    out, used_ids = [], set()
    for s in scenes or []:
        root_id = _safe_name(str(s.get("id") or s.get("name") or f"scene{len(out)+1}"))
        sid, serial = root_id, 2
        while sid.casefold() in used_ids:
            sid = f"{root_id}-{serial}"
            serial += 1
        used_ids.add(sid.casefold())
        out.append({
            "id": sid,
            "name": (s.get("name") or "").strip() or "이름 없음",
            "prompt": s.get("prompt", ""),
            # 씬이 **인물별 프롬프트**도 가질 수 있다 (배경·구도는 prompt, 인물은 여기).
            # 씬 프롬프트에 인물 묘사를 적으면 base 로 들어가 왼쪽 캐릭터와 뭉개진다 —
            # NAIS3 에서 "씬에 여자 프롬을 넣었더니 베이스의 여자와 합쳐졌다" 는 그 문제다.
            "char1": s.get("char1", ""),
            "char2": s.get("char2", ""),
            "char1_neg": s.get("char1_neg", ""),
            "char2_neg": s.get("char2_neg", ""),
            "negative": s.get("negative", ""),
            "width": int(s.get("width") or 832),
            "height": int(s.get("height") or 1216),
            "reserve": max(0, int(s.get("reserve") or 0)),   # 0 = 안 뽑음
            # 해상도를 직접 입력으로 두겠다는 표시 (프리셋과 값이 같아도 칸을 보여 준다)
            "custom_res": bool(s.get("custom_res")),
        })
    atomic_write_json(SCENES_FILE, out, indent=1)
    return out


def scene_mode_pending(cfg):
    """씬 모드에서 뽑을 목록 — 예약 매수가 1 이상인 씬만, 매수만큼."""
    out = []
    for sc in load_scenes():
        for copy in range(1, int(sc.get("reserve") or 0) + 1):
            out.append((sc, copy))
    return out


def export_fragments_zip():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(FRAG_DIR.glob("*.txt")) if FRAG_DIR.exists() else []:
            z.write(p, p.name)
    return buf.getvalue()


def import_fragments_bytes(data, filename=""):
    """조각 TXT 낱개 또는 ZIP. 같은 이름이면 덮지 않고 ' (2)' 를 붙인다."""
    import io
    import zipfile
    FRAG_DIR.mkdir(exist_ok=True)
    added, skipped = [], []

    def put(stem, raw):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp949")       # 메모장에서 만든 파일
            except Exception:
                skipped.append(f"{stem}: 글자 인코딩을 못 읽었습니다")
                return
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if not lines:
            skipped.append(f"{stem}: 빈 파일")
            return
        base = _safe_name(stem) or "조각"
        target, k = FRAG_DIR / f"{base}.txt", 2
        while target.exists():
            target = FRAG_DIR / f"{base} ({k}).txt"
            k += 1
        atomic_write_text(
            target, "\n".join(lines) + "\n", keep_backup=False)
        added.append(target.stem)

    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.lower().endswith(".txt") and not n.endswith("/"):
                    put(Path(n).stem, z.read(n))
    else:
        put(Path(filename).stem or "조각", data)
    return {"ok": bool(added), "added": added, "skipped": skipped,
            "fragments": list_fragments()}


def resolve_fragments(texts, frags=None, counters=None, rng=None):
    """여러 프롬프트 칸을 **한 번에** 푼다.
    한 이미지에서 `<*표정>` 이 베이스와 캐릭터 칸에 함께 있어도 순번은 한 번만 는다.
    반환: (푼 텍스트 목록, 바뀐 순번 dict)"""
    import random as _random
    frags = list_fragments() if frags is None else frags
    counters = dict(counters or {})
    rng = rng or _random
    if not frags and not any("{" in (t or "") for t in texts):
        return list(texts), counters

    step = {}          # 이 이미지에서 <*이름> 이 이미 고른 값 (칸이 달라도 같은 값)
    pick = {}          # 이 이미지에서 <이름> 이 이미 고른 값

    def one(m):
        seq = m.group(1) == "*"
        name = m.group(2).strip()
        opts = frags.get(name)
        if not opts:
            return m.group(0)          # 없는 조각은 건드리지 않는다 (오타를 눈에 띄게)
        if len(opts) == 1:
            return opts[0]
        if seq:
            if name not in step:
                i = int(counters.get(name, 0))
                step[name] = opts[i % len(opts)]
                counters[name] = i + 1
            return step[name]
        if name not in pick:
            pick[name] = rng.choice(opts)
        return pick[name]

    def inline(m):
        parts = [x.strip() for x in m.group(1).split("|")]
        # ⚠ `{| |}`(23,000장)·`{|_|}`(11,000장) 은 **실제 단부루 태그**다 (얼굴 표정).
        #   빈 칸이 하나라도 있으면 인라인 선택이 아니라 태그로 보고 **원문을 그대로 둔다**.
        #   예전엔 빈 조각을 걸러내 `{| |}` 가 통째로 사라졌다 (NAIS3 세션 지적).
        if any(not x for x in parts) or len(parts) < 2:
            return m.group(0)
        return rng.choice(parts)

    out = []
    for t in texts:
        s = t or ""
        for _ in range(FRAG_MAX_DEPTH):
            new = re.sub(r"<(\*?)([^<>]+)>", one, s)
            new = re.sub(r"\{([^{}]*\|[^{}]*)\}", inline, new)
            if new == s:
                break
            s = new
        out.append(s)
    return out, counters


def finalized_token_texts(base, negative, chars, char_negatives, cfg):
    """Return NAI-bound prompt strings without advancing fragment state.

    The token preview must expand fragments, normalize weights, append the
    quality suffix, and merge the UC preset just like ``call_nai_api``. A
    private RNG keeps a preview from consuming the generator random stream.
    """
    chars = list(chars or [])
    char_negatives = list(char_negatives or [])
    count = max(len(chars), len(char_negatives))
    chars += [""] * (count - len(chars))
    char_negatives += [""] * (count - len(char_negatives))
    pairs = [[chars[i], char_negatives[i]] for i in range(count)]

    fixed = [strip_comment_lines(x) for x in (base, negative, "", "", "", "")]
    flat = [strip_comment_lines(x) for pair in pairs for x in pair]
    if cfg.get("use_fragments", True):
        counters = cfg.get("_frag_counters")
        if counters is None:
            try:
                counters = load_state().get("frag_seq", {})
            except Exception:
                counters = {}
        resolved, _ = resolve_fragments(
            fixed + flat, counters=dict(counters or {}), rng=random.Random(0))
        fixed, flat = list(resolved[:6]), list(resolved[6:])

    fixed = [normalize_prompt(x) for x in fixed]
    flat = [normalize_prompt(x) for x in flat]
    base, negative = fixed[0], fixed[1]
    if cfg.get("quality_toggle"):
        base = merge_quality_suffix(
            base,
            cfg.get("model") or "nai-diffusion-4-5-full",
        )
    negative = merge_uc_preset(
        negative,
        cfg.get("model") or "nai-diffusion-4-5-full",
        cfg.get("uc_preset"),
    )
    return {
        "base": base,
        "negative": negative,
        "chars": [flat[i * 2] for i in range(count)],
        "char_negatives": [flat[i * 2 + 1] for i in range(count)],
    }


# ═══════════════ 진행 상태 (재개용) ═══════════════

def load_state():
    if STATE_FILE.exists():
        return load_json_recover(STATE_FILE)
    return {"seeds": {}, "progress": {}, "daily": {}, "total_generated": 0}


def save_state(state):
    atomic_write_json(STATE_FILE, state)


def daily_count(state):
    return state["daily"].get(date.today().isoformat(), 0)


def bump_daily(state):
    key = date.today().isoformat()
    state["daily"][key] = state["daily"].get(key, 0) + 1
    state["total_generated"] += 1


# ── 모든 생성 경로가 지나는 밴 예방 관문 (CQA-013) ──────────────────
#   예전에는 배치·복구에만 간격/일일 상한이 있고 단독 생성·씬 모드는 그냥 나갔다.
#   사용자가 설정한 보호값이 경로에 따라 안 먹으면 설정 자체가 거짓말이 된다.
_LAST_CALL = {"t": 0.0}


def pace_gate(cfg, live=None, label=""):
    """Wait until the configured gap since the previous API completion.

    The completion timestamp is written by ``pace_complete`` in each call
    site's ``finally`` block. Measuring from request start can collapse the
    real gap to zero when a slow API call lasts longer than the configured gap.
    """
    pc = pace(cfg)
    st = load_state()
    if daily_count(st) >= pc["daily_cap"]:
        return False, f"일일 상한 {pc['daily_cap']}장에 도달했습니다 — 내일 이어서 하세요."
    gap = random.uniform(pc["delay_min"], pc["delay_max"])
    while True:
        wait = _LAST_CALL["t"] + gap - time.time()
        if wait <= 0:
            return True, ""
        if live is not None and getattr(live, "stop_req", False):
            return False, "중지되었습니다."
        time.sleep(min(0.5, wait))


def pace_complete():
    """Mark the end of an attempted NAI generation request."""
    _LAST_CALL["t"] = time.time()

# ═══════════════ 브라우저 UI (설정 + 실시간 미리보기) ═══════════════

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NAI 배치 생성기__PROFTITLE__</title>
<style>
  :root{
    /* 기본 = 슬레이트 (밝고 가시성 높은 쪽). NAIS3 도 :root 가 밝은 테마다.
       어두운 쪽은 data-theme="midnight" 로 골라 쓴다. */
    --bg:#edf1f7;--paper:#ffffff;--paper2:#f6f8fb;--line:#d6dee9;
    --text:#172033;--muted:#667085;--accent:#3158c9;--accent-dim:#3158c918;
    --good:#087a5b;--danger:#c4322b;--gold:#3158c9;
    /* 모서리 기본 = 각짐. --radius-pill 은 알약/칩용(각짐일 땐 같이 각진다) */
    --radius:6px;--radius-pill:999px;
    /* 글자 크기 사다리 — 5단. `--fs-2xs`·`--fs-lg` 는 그동안 px 로 박혀 있던 자리를
       설정에 따라 같이 움직이게 하려고 추가했다 (배지·툴팁이 11px, 제목이 17px 로
       고정이라 '글씨 크게' 를 골라도 안 따라오던 자리가 41곳 있었다). */
    --fs-2xs:11px;--fs-xs:12px;--fs-sm:13.5px;--fs:15px;--fs-lg:17px;
    --mono:'JetBrains Mono','Consolas',monospace;
    --sans:-apple-system,'Pretendard','Malgun Gothic',sans-serif;
  }
  /* ── 테마 ── */
  :root[data-theme="midnight"]{ /* 미드나잇 (기존 기본) */
    --bg:#0e1014;--paper:#161920;--paper2:#1c2029;--line:#2a2f3a;
    --text:#e8eaee;--muted:#8a90a0;--accent:#7c8cff;--accent-dim:#7c8cff26;
    --good:#5fd4a0;--danger:#ff7a7a;--gold:#b8934a;}
  :root[data-theme="paper"]{  /* 종이 (NAIS 라이트) */
    --bg:#f3f1ec;--paper:#ffffff;--paper2:#f7f6f2;--line:#dedbd4;
    --text:#1f1f1e;--muted:#6f6c66;--accent:#4a6cf7;--accent-dim:#4a6cf71a;
    --good:#1f9d68;--danger:#c94a4a;--gold:#a3803a;}
  :root[data-theme="sepia"]{  /* 고서 */
    --bg:#efe6d4;--paper:#faf4e6;--paper2:#f3ead6;--line:#d9c9a8;
    --text:#3b2f1e;--muted:#8a7a5e;--accent:#9a6a2f;--accent-dim:#9a6a2f1f;
    --good:#5c7a3a;--danger:#a33d2d;--gold:#9a6a2f;}
  :root[data-theme="sakura"]{ /* 벚꽃 */
    --bg:#fdf2f6;--paper:#ffffff;--paper2:#fce8f0;--line:#f2cfdd;
    --text:#3d2530;--muted:#96707f;--accent:#e0508f;--accent-dim:#e0508f1a;
    --good:#3fa08a;--danger:#d94a5a;--gold:#c08a3e;}
  :root[data-theme="ocean"]{  /* 오션 */
    --bg:#0b1a24;--paper:#11242f;--paper2:#16303e;--line:#1f4152;
    --text:#e2f0f5;--muted:#7fa3b3;--accent:#3ec9e0;--accent-dim:#3ec9e026;
    --good:#4fd6a5;--danger:#ff8080;--gold:#d9a441;}
  :root[data-theme="forest"]{ /* 포레스트 */
    --bg:#101a12;--paper:#16231a;--paper2:#1c2c21;--line:#2b4232;
    --text:#e4f0e6;--muted:#8daa93;--accent:#5fd47a;--accent-dim:#5fd47a26;
    --good:#7fdc6a;--danger:#ff8a7a;--gold:#c9a44a;}
  :root[data-theme="terminal"]{ /* 터미널 */
    --bg:#07100a;--paper:#0b160f;--paper2:#0f1e14;--line:#1c3524;
    --text:#c8f5cf;--muted:#6b9a76;--accent:#39ff87;--accent-dim:#39ff8722;
    --good:#39ff87;--danger:#ff5f5f;--gold:#d8c34a;}
  :root[data-theme="mono"]{   /* 모노크롬 */
    --bg:#141414;--paper:#1c1c1c;--paper2:#232323;--line:#333;
    --text:#ededed;--muted:#8f8f8f;--accent:#d8d8d8;--accent-dim:#d8d8d81f;
    --good:#b9b9b9;--danger:#e08a8a;--gold:#c0c0c0;}
  :root[data-theme="wine"]{   /* 와인 */
    --bg:#170f14;--paper:#20161c;--paper2:#291c24;--line:#3d2833;
    --text:#f0e4ea;--muted:#a88b99;--accent:#e05780;--accent-dim:#e0578026;
    --good:#5fd4a0;--danger:#ff7a7a;--gold:#c9a24a;}
  /* ── 강조색 오버라이드 ── */
  :root[data-accent="blue"]{--accent:#4a8cff;--accent-dim:#4a8cff26;}
  :root[data-accent="violet"]{--accent:#a56cff;--accent-dim:#a56cff26;}
  :root[data-accent="pink"]{--accent:#ff6ba9;--accent-dim:#ff6ba926;}
  :root[data-accent="green"]{--accent:#4fd67f;--accent-dim:#4fd67f26;}
  :root[data-accent="amber"]{--accent:#f0a83c;--accent-dim:#f0a83c26;}
  :root[data-accent="cyan"]{--accent:#3ec9e0;--accent-dim:#3ec9e026;}
  :root[data-accent="red"]{--accent:#ff6b6b;--accent-dim:#ff6b6b26;}
  /* ── 글씨 크기 ── */
  :root[data-fs="s"]{--fs-2xs:10px;--fs-xs:11px;--fs-sm:12px;--fs:13.5px;--fs-lg:15px;}
  :root[data-fs="l"]{--fs-2xs:12px;--fs-xs:13px;--fs-sm:14.5px;--fs:16px;--fs-lg:18px;}
  :root[data-fs="xl"]{--fs-2xs:13px;--fs-xs:14px;--fs-sm:15.5px;--fs:17px;--fs-lg:19px;}
  /* ── 모서리 ── ('' = 각짐이 기본) */
  :root[data-radius="soft"]{--radius:8px;--radius-pill:99px;}
  :root[data-radius="round"]{--radius:16px;--radius-pill:99px;}
  *{box-sizing:border-box;}
  html,body{height:100%;}
  body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:var(--fs);overflow:hidden;transition:background .2s,color .2s;line-height:1.45;}
  button{font-family:var(--sans);font-size:var(--fs-sm);background:var(--paper2);color:var(--text);
    border:1px solid var(--line);border-radius:var(--radius);padding:8px 12px;min-height:34px;cursor:pointer;font-size:var(--fs-sm);transition:border-color .15s,background .15s,color .15s,transform .08s;}
  button:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-dim);}
  button:active{transform:translateY(1px);}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700;}
  button.primary:hover{filter:brightness(1.06);color:#fff;background:var(--accent);}
  button.danger{color:var(--danger);border-color:var(--danger);}
  button:disabled{opacity:.45;cursor:not-allowed;}
  input,textarea,select{width:100%;background:var(--paper2);border:1px solid var(--line);color:var(--text);
    border-radius:var(--radius);padding:8px 10px;min-height:34px;font-family:var(--mono);font-size:var(--fs-sm);resize:none;}
  input:focus,textarea:focus,select:focus{outline:2px solid var(--accent-dim);outline-offset:1px;border-color:var(--accent);}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  select{font-family:var(--sans);cursor:pointer;}
/* Highlight Emphasis — 프롬프트 칸의 가중치를 색으로 보여준다.
   투명 textarea 를 하이라이트 레이어 위에 겹치는 방식이므로
   글꼴·크기·줄간격·여백·테두리가 완전히 같아야 글자가 어긋나지 않는다. */
.hlwrap{position:relative;flex:1;display:flex;}
.hlwrap textarea{position:relative;z-index:2;background:transparent;caret-color:var(--text);}
/* textarea 의 줄바꿈 규칙과 완전히 같아야 한다.
   word-break:break-word 를 쓰면 긴 줄에서 줄바꿈 위치가 달라져 하이라이트가 어긋난다.
   폭은 스크롤바를 뺀 clientWidth 로 JS 가 맞춰준다. */
/* textarea 와 같은 투명 테두리·여백을 둔다. 예전의 top/left 1px + padding 7/9px은
   실제 글자 시작점보다 가로·세로 모두 1px 앞서 배경띠가 두 겹 글자처럼 보였다. */
.hlwrap .hl{position:absolute;top:0;left:0;z-index:1;overflow:hidden;pointer-events:none;
  white-space:pre-wrap;word-break:normal;overflow-wrap:break-word;color:transparent;
  -webkit-text-fill-color:transparent;text-shadow:none;
  padding:8px 10px;border:1px solid transparent;border-radius:var(--radius);
  font-family:var(--mono);font-size:var(--fs-sm);line-height:1.55;
  box-sizing:border-box;tab-size:8;}
.psec-body .hlwrap .hl{line-height:1.55;}
/* 브라우저 기본 b 스타일이나 테마 규칙이 투명 글자를 되살리지 못하게, 하이라이트
   거울층의 모든 자손은 글리프를 절대 그리지 않는다. 실제 글자는 textarea 한 층뿐이다. */
.hlwrap .hl *{color:transparent!important;-webkit-text-fill-color:transparent!important;
  text-shadow:none!important;text-decoration:none!important;}
/* NAI 와 같은 색 규칙: 강조(1보다 큼)는 붉은색, 약화·음수는 파란색.
   숫자가 클수록 / 작을수록 진해진다. */
.hl b{font-weight:400;border-radius:3px;padding:0;}
.hl .w-up3{background:rgba(190,70,70,.42);}     /* 2.0 이상 — 아주 강함 */
.hl .w-up2{background:rgba(180,74,74,.30);}     /* 1.4~2.0 */
.hl .w-up1{background:rgba(170,80,80,.20);}     /* 1.0~1.4 — 살짝 강함 */
.hl .w-dn1{background:rgba(74,124,196,.22);}    /* 0.5~1.0 — 약함 */
.hl .w-dn2{background:rgba(64,108,196,.32);}    /* 0.5 미만 — 많이 약함 */
.hl .w-neg{background:rgba(48,96,204,.46);}     /* 음수 — 빼기 (가장 진한 파랑) */
/* textarea 원문이 이미 위에서 그려진다. 거울층은 배경 위치만 계산한다. */

/* 창 아무 데나 그림을 떨어뜨릴 때 뜨는 안내 */
#dropOverlay{position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;
  background:rgba(0,0,0,.55);backdrop-filter:blur(2px);font-size:var(--fs-lg);font-weight:600;color:#fff;
  border:3px dashed var(--accent);pointer-events:none;text-align:center;padding:20px;}
#dropOverlay.on{display:flex;}

/* .hidden 이 지금까지 .psec-body / .ovl / .sec-body 에만 걸려 있어서
   다른 요소에 붙이면 안 먹었다. 전역 규칙을 둔다. */
.hidden{display:none;}

.grid4{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--bcard,150px),1fr));gap:8px;}

/* 레퍼런스 탭 */
.reftabs{display:flex;gap:6px;margin:6px 0 8px;}
.reftabs button{flex:1;}
.reftabs button.on{background:var(--accent-dim);border-color:var(--accent);color:var(--text);}
.reftabs span{opacity:.7;margin-left:4px;}

/* 캐릭터 위치 격자 — NAI 처럼 화면 어디에 둘지 5×5 로 고른다 */
.posrow{display:flex;align-items:center;gap:7px;margin-top:4px;}
.posgrid{display:grid;grid-template-columns:repeat(5,10px);grid-template-rows:repeat(5,10px);
  gap:2px;flex:none;}
.poscell{width:10px;height:10px;border-radius:2px;background:var(--line);cursor:pointer;}
.poscell:hover{background:var(--accent-dim);}
.poscell.on{background:var(--accent);box-shadow:0 0 0 1px var(--accent);}
.posnum{width:52px;padding:2px 4px;font-size:var(--fs-xs);}

/* 필터 줄: 셀렉트/체크박스가 한 줄에 나란히 (input,select의 width:100% 무력화) */
.filterbar{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 8px;}
.filterbar select{width:auto;flex:0 0 auto;padding:6px 8px;font-size:var(--fs-sm);}
.filterbar input[type=text]{flex:1 1 200px;min-width:160px;}
.filterbar input[type=checkbox]{width:13px;height:13px;flex:none;accent-color:var(--accent);}
.filterbar label{display:flex;align-items:center;gap:5px;white-space:nowrap;cursor:pointer;}
.filterbar .n{margin-left:auto;white-space:nowrap;}
  label{display:block;font-size:var(--fs-xs);color:var(--muted);margin-bottom:4px;}

  /* ── 타이틀바 ── */
  .titlebar{height:56px;display:flex;align-items:center;gap:22px;padding:0 18px;
    border-bottom:1px solid var(--line);background:var(--paper);box-shadow:0 1px 4px #1018280b;position:relative;z-index:30;}
  .titlebar .app{font-weight:800;font-size:var(--fs-lg);letter-spacing:-.01em;white-space:nowrap;}
  .titlebar .app span{color:var(--accent);}
  .titlebar .app .save-state{display:inline-block;margin-left:8px;padding:2px 6px;
    border:1px solid var(--line);border-radius:var(--radius-pill);color:var(--muted);
    font-size:var(--fs-2xs);font-weight:600;vertical-align:2px;}
  .titlebar .app .save-state.busy{color:var(--accent);border-color:var(--accent);}
  .titlebar .app .save-state.fail{color:var(--danger);border-color:var(--danger);}
  .modes{display:flex;align-self:stretch;gap:2px;}
  .modes button{padding:0 16px;border:0;border-bottom:3px solid transparent;border-radius:0;background:transparent;font-size:var(--fs-sm);font-weight:600;}
  /* 켜진 탭은 칠해서 확실히 구분한다 (테두리 색만 바꾸면 밝은 테마에서 잘 안 보였다) */
  .modes button.on{background:var(--accent-dim);border-bottom-color:var(--accent);color:var(--accent);font-weight:800;}
  .modes button.on:hover{color:var(--accent);}
  .titlebar .spacer{flex:1;}
  .titlebar .stat{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:340px;}

  /* ── 3단 레이아웃 ── */
  #app{--colL:var(--lw,360px);--colR:280px;
       display:grid;grid-template-columns:var(--colL) minmax(520px,1fr) var(--colR);height:calc(100vh - 56px);}
  /* 넓은 화면에서 가운데가 논다 — 1600×1000 실측에서 좌 360 / 중 960 / 우 280 이었고,
     그동안 프롬프트 칸은 보이는 높이 228px 에 내용 1,104px(80% 가 잘림)이었다.
     좌·우를 넓혀 같은 글이 세로로 덜 접히게 한다. `--lw` 는 사용자가 손잡이를 끌면
     localStorage 에 남으므로, **직접 정한 폭이 있으면 그쪽이 이긴다.** */
  @media (min-width:1200px){
    #app{--colL:var(--lw,400px);--colR:280px;}
  }
  @media (min-width:1500px){
    #app{--colL:var(--lw,440px);--colR:300px;
         grid-template-columns:var(--colL) minmax(560px,1fr) var(--colR);}
  }
  @media (min-width:1900px){
    #app{--colL:var(--lw,500px);--colR:320px;
         grid-template-columns:var(--colL) minmax(640px,1fr) var(--colR);}
  }
  .left{border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0;position:relative;background:var(--paper);box-shadow:2px 0 10px #10182808;z-index:2;}
  /* 왼쪽 패널 폭 조절 손잡이 (Forge 참고) — 드래그로 240~560px */
  /* ⚠ right:-3px 로 패널 밖에 두면 문서 폭이 3px 늘어 좁은 창에서 가로 스크롤이 생긴다.
     안쪽으로 붙이고 폭을 넉넉히 준다 (잡기 쉬움은 유지). */
  #lwDrag{position:absolute;top:0;right:0;width:6px;height:100%;cursor:col-resize;z-index:5;}
  #lwDrag:hover{background:var(--accent-dim);}
  .center{min-width:0;overflow-y:auto;padding:22px 24px;scrollbar-gutter:stable;}
  .center>.view{width:100%;max-width:1120px;margin:0 auto;}
  .right{border-left:1px solid var(--line);overflow-y:auto;padding:14px;background:var(--paper);box-shadow:-2px 0 10px #10182808;}

  /* ── 패널 접기 (Forge · blue 둘 다 갖고 있다) ──────────────────────────
     Forge v1.2.11 `ThreeColumnLayout.tsx:230` 이 `!leftSidebarVisible && "hidden"` 으로
     좌패널을 통째로 감추고, blue v2.11.2 `stores/layout-store.ts:6-37` 은 **좌·우 둘 다**
     감추고 그 상태를 저장한다. 우리는 폭 손잡이만 있어 자료·세팅 탭에서 프롬프트 칸이
     차지한 자리를 되찾을 방법이 없었다 (1600 에서 좌 440 + 우 300 = 46%).
     ⚠ 접었을 때 **폭을 0 으로 만들지 않고 열에서 뺀다** — `grid-template-columns` 를
       다시 써야 가운데가 그 자리를 실제로 가져간다. 폭만 0 으로 하면 padding·border 가
       남아 몇 px 이 뜨고 손잡이도 잡히는 채로 남는다. */
  /* ⚠ 세 패널의 **열을 못박아야** 한다. `display:none` 은 항목을 격자 흐름에서 빼므로
     열을 안 정해 두면 자동 배치가 한 칸씩 당겨져, 좌패널을 접었을 때 가운데가 1번 열
     (0px)로 밀리고 오른쪽이 `1fr` 을 차지한다 — 실측에서 중 860→48 · 우 300→1300 이었다. */
  .left{grid-column:1;} .center{grid-column:2;} .right{grid-column:3;}
  #app[data-lhide="1"] .left{display:none;}
  #app[data-rhide="1"] .right{display:none;}
  /* 폭은 `--colL`·`--colR` 한 곳에서만 정한다. 접기는 그 변수를 0 으로 만들 뿐이라
     화면 폭 단계(1200·1500·1900)에서 정한 값이 그대로 보존된다.
     열 정의를 여기서 다시 쓰면 넓은 화면의 우 300·320 이 280 으로 되돌아간다. */
  #app[data-lhide="1"]{--colL:0;}
  #app[data-rhide="1"]{--colR:0;}
  .paneltog{display:inline-flex;align-items:center;justify-content:center;width:26px;height:24px;
    border:1px solid var(--line);background:var(--paper);color:var(--muted);cursor:pointer;
    border-radius:var(--radius);font-size:var(--fs-xs);line-height:1;padding:0;}
  .paneltog:hover{color:var(--fg);border-color:var(--accent);}
  .paneltog[aria-pressed="true"]{color:var(--accent);border-color:var(--accent);background:var(--accent-dim);}

  /* ── 왼쪽: 프롬프트 패널 (NAIS3 구조) ── */
  .preset-bar{display:flex;gap:8px;padding:12px 14px 10px;border-bottom:1px solid var(--line);background:var(--paper);}
  .preset-bar select{flex:1;font-size:var(--fs-sm);padding:6px 8px;}
  .preset-bar button{padding:6px 9px;font-size:var(--fs-xs);}
  .psec{display:flex;flex-direction:column;min-height:0;}
  .psec-head{display:flex;align-items:center;gap:8px;padding:10px 14px 7px;cursor:pointer;user-select:none;}
  .psec-head .t{font-size:var(--fs-sm);color:var(--text);font-weight:750;}
  .psec-head .chev{font-size:var(--fs-xs);color:var(--muted);transition:transform .15s;}
  .psec-head.closed .chev{transform:rotate(-90deg);}
  .psec-head .count{margin-left:auto;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);}
  .psec-body{padding:0 14px 10px;flex:1;min-height:0;display:flex;}
  .psec-body.hidden{display:none;}
  .psec-body textarea{flex:1;min-height:90px;line-height:1.55;}
  /* 3분할 — `:not(.hidden)` 으로 써야 `.hidden{display:none}` 이 이긴다.
     `#split3{display:flex}` 로 두면 id 우선순위(1-0-0)가 클래스(0-1-0)를 눌러
     예전처럼 영영 안 숨는다. */
  #split3:not(.hidden){display:flex;}
  .tools{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:10px 14px;border-top:1px solid var(--line);}
  .tools.jumps{grid-template-columns:repeat(2,1fr);border-top:0;padding-top:0;}
  .tool.jump{background:transparent;color:var(--muted);}
  .tool .ar{position:absolute;right:4px;top:3px;font-size:var(--fs-xs);color:var(--muted);}
  /* 세트 대표 그림 (세팅 목록에서 바로 확인) */
  /* 태그 자동완성 */
  .acbox{position:fixed;z-index:120;background:var(--paper);border:1px solid var(--accent);
    border-radius:var(--radius);box-shadow:0 6px 18px #0003;max-height:260px;overflow-y:auto;
    font-size:var(--fs-sm);}
  .acrow{display:flex;align-items:center;gap:8px;padding:3px 8px;cursor:pointer;}
  .acrow .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .acrow .n{color:var(--muted);font-family:var(--mono);font-size:var(--fs-xs);flex:none;}
  .acrow.on{background:var(--accent-dim);color:var(--accent);}
  .setthumb{width:26px;height:26px;object-fit:cover;border-radius:var(--radius);
    border:1px solid var(--line);flex:none;background:var(--paper2);}
  .tool{position:relative;display:flex;flex-direction:column;align-items:center;gap:5px;
    padding:10px 3px;font-size:var(--fs-xs);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .tool .ico{font-size:var(--fs-lg);line-height:1;}
  .tool.on{border-color:var(--accent);color:var(--accent);background:var(--accent-dim);}
  .tool .badge{position:absolute;right:1px;top:1px;min-width:16px;height:16px;border-radius:var(--radius-pill);
    background:var(--danger);color:#12131a;font-size:var(--fs-xs);font-weight:700;display:flex;align-items:center;
    justify-content:center;padding:0 4px;font-family:var(--mono);}
  .genrow{display:flex;align-items:center;gap:9px;padding:11px 14px 13px;border-top:1px solid var(--line);}
  .genrow .qty{display:flex;align-items:center;border:1px solid var(--line);border-radius:var(--radius);background:var(--paper2);}
  .genrow .qty button{border:none;background:none;padding:6px 9px;border-radius:0;}
  .genrow .qty input{width:38px;border:none;background:none;text-align:center;padding:6px 0;font-size:var(--fs-sm);}
  .genrow .go{flex:1;padding:11px;font-size:var(--fs);min-height:42px;}

  /* ── 왼쪽 오버레이 (캐릭터/캐스트 편집) ── */
  .ovl{position:absolute;inset:0;background:var(--paper);z-index:20;display:flex;flex-direction:column;}
  .ovl.hidden{display:none;}
  .ovl-head{display:flex;align-items:center;gap:8px;padding:11px 12px;border-bottom:1px solid var(--line);}
  .ovl-head .t{font-weight:700;font-size:var(--fs-sm);}
  .ovl-head .x{margin-left:auto;padding:4px 9px;}
  .ovl-body{flex:1;overflow-y:auto;padding:10px 12px;}
  .slot{border:1px solid var(--line);border-radius:var(--radius);padding:10px;margin-bottom:8px;background:var(--paper2);}
  .slot .r1{display:flex;gap:6px;margin-bottom:6px;}
  .slot .r1 input{flex:1;font-family:var(--sans);font-weight:600;font-size:var(--fs-sm);}
  .slot textarea{min-height:52px;margin-bottom:4px;}

  /* ── 가운데 공통 ── */
  .card{background:var(--paper);border:1px solid var(--line);border-radius:calc(var(--radius) + 4px);padding:18px 20px;margin-bottom:16px;box-shadow:0 2px 8px #1018280a;}
  .card h2{font-size:calc(var(--fs) + 1px);margin:0 0 6px;display:flex;align-items:center;gap:9px;letter-spacing:-.01em;}
  .card h2 .n{font-family:var(--mono);font-size:var(--fs-xs);color:var(--accent);background:var(--accent-dim);
    border-radius:var(--radius-pill);padding:2px 7px;}
  .combo-card{content-visibility:auto;contain-intrinsic-size:auto 154px;}
  .hint{color:var(--muted);font-size:var(--fs-xs);margin:0 0 12px;line-height:1.65;}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:11px;}
  .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:11px;}
  .field{margin-bottom:10px;}
  .bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:10px;}
  /* .bar 가 전역 .hidden 보다 뒤에 선언되어 display:flex 로 되살아나는 것을 막는다.
     비교 해상도의 직접 입력칸은 "직접 입력"을 고른 때에만 보여야 한다. */
  #cmpCustom.hidden{display:none;}
  .bar .n{margin-left:auto;font-family:var(--mono);font-size:var(--fs-xs);color:var(--good);}
  .chip{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border:1px solid var(--line);
    border-radius:var(--radius-pill);font-size:var(--fs-xs);cursor:pointer;margin:0 5px 5px 0;background:var(--paper2);color:var(--muted);}
  .chip.on{border-color:var(--accent);color:var(--accent);background:var(--accent-dim);}
  .chip:hover{border-color:var(--accent);}
  .row{border:1px solid var(--line);border-radius:var(--radius);padding:12px 14px;margin-bottom:10px;background:var(--paper2);}
  .row .tag{font-family:var(--mono);font-size:var(--fs-xs);color:var(--accent);margin-bottom:7px;}
  .items{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:1px;}
  .item{display:flex;align-items:center;gap:6px;padding:5px 7px;border-radius:var(--radius);font-size:var(--fs-xs);cursor:pointer;}
  .item:hover{background:var(--accent-dim);}
  .item input{width:13px;height:13px;accent-color:var(--accent);flex:none;}
  .item span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .item .ed{margin-left:auto;color:var(--muted);padding:0 4px;border-radius:var(--radius);flex:none;}
  .item .ed:hover{color:var(--accent);background:var(--accent-dim);}
  .sec{border:1px solid var(--line);border-radius:var(--radius);margin-bottom:9px;overflow:hidden;background:var(--paper2);}
  .sec-head{display:flex;align-items:center;gap:9px;padding:9px 12px;cursor:pointer;user-select:none;}
  .sec-head:hover{background:var(--accent-dim);}
  .sec-head .badge{font-family:var(--mono);font-size:var(--fs-xs);color:#12131a;background:var(--accent);
    border-radius:var(--radius);padding:2px 6px;font-weight:700;}
  .sec-head .nm{font-weight:600;font-size:var(--fs-sm);}
  .sec-head .sub{font-size:var(--fs-xs);color:var(--muted);}
  .sec-head .cnt{margin-left:auto;font-family:var(--mono);font-size:var(--fs-xs);color:var(--good);}
  .sec-body{padding:11px 13px;border-top:1px solid var(--line);}
  .sec-body.hidden{display:none;}
  .tagres{max-height:92px;overflow-y:auto;margin:4px 0;}
  /* ── 빌더: "태그 수천 개"보다 "무엇을 만드는 중인가"가 먼저 보이게 ── */
  .builder-entry-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:13px;}
  .builder-entry{display:flex;flex-direction:column;align-items:flex-start;min-height:142px;padding:16px;
    border:1px solid var(--line);border-radius:calc(var(--radius) + 3px);background:var(--paper2);}
  .builder-entry.char{background:linear-gradient(145deg,var(--paper2),var(--accent-dim));}
  .builder-entry .eyebrow{font-family:var(--mono);font-size:var(--fs-2xs);color:var(--accent);
    letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px;}
  .builder-entry strong{font-size:calc(var(--fs) + 1px);margin-bottom:5px;}
  .builder-entry p{font-size:var(--fs-xs);line-height:1.6;color:var(--muted);margin:0 0 13px;}
  .builder-entry button{margin-top:auto;}
  .builder-tools{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px;padding-top:12px;
    border-top:1px solid var(--line);}
  .builder-tools .label{font-size:var(--fs-xs);font-weight:700;color:var(--muted);margin-right:3px;}
  .modal.builder-modal{max-width:1180px;}
  .builder-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;
    margin:-2px 0 12px;padding:12px 14px;border:1px solid var(--line);border-radius:var(--radius);
    background:var(--paper2);}
  .builder-intro .flow{font-size:var(--fs-xs);line-height:1.65;color:var(--muted);}
  .builder-intro .flow b{color:var(--text);}
  .builder-intro .route{flex:none;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--accent);
    border:1px solid var(--accent);border-radius:var(--radius-pill);padding:4px 9px;background:var(--accent-dim);}
  .builder-toolbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:12px;}
  .builder-toolbar .n{margin-left:auto;}
  .builder-shell{display:grid;grid-template-columns:minmax(0,1fr) 320px;align-items:start;gap:15px;}
  .builder-steps{min-width:0;}
  .builder-steps.builder-core-only .sec:not(.essential){display:none;}
  .builder-summary{position:sticky;top:0;padding:14px;border:1px solid var(--line);
    border-radius:calc(var(--radius) + 3px);background:var(--paper2);box-shadow:0 6px 18px #10182810;}
  .builder-summary h4{margin:0 0 5px;font-size:var(--fs-sm);}
  .builder-summary .summary-note{font-size:var(--fs-xs);line-height:1.55;color:var(--muted);margin:0 0 12px;}
  .builder-summary .field{margin-bottom:11px;}
  .builder-summary textarea{min-height:68px;}
  .builder-summary #bldPreview{min-height:112px;color:var(--good);}
  .builder-summary .apply-now{display:flex;align-items:flex-start;gap:8px;padding:9px 10px;
    border:1px solid var(--accent);border-radius:var(--radius);background:var(--accent-dim);
    font-size:var(--fs-xs);line-height:1.45;}
  .builder-summary .apply-now input{width:auto;margin-top:2px;accent-color:var(--accent);}
  .modal.builder-modal > .bar:last-child{position:sticky;bottom:-20px;z-index:4;margin:12px -20px -20px!important;
    padding:11px 20px 13px;background:color-mix(in srgb,var(--paper) 94%,transparent);
    border-top:1px solid var(--line);backdrop-filter:blur(10px);}
  .builder-progress{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 10px;min-height:22px;}
  .builder-progress .empty{font-size:var(--fs-2xs);color:var(--muted);}
  .builder-progress button{padding:3px 7px;font-size:var(--fs-2xs);color:var(--good);
    border-color:color-mix(in srgb,var(--good) 45%,var(--line));background:var(--paper);}
  .builder-stage-route{font-family:var(--mono);font-size:var(--fs-2xs);padding:2px 6px;
    border-radius:var(--radius-pill);border:1px solid var(--line);color:var(--muted);}
  .builder-stage-route.negative{color:var(--danger);border-color:color-mix(in srgb,var(--danger) 45%,var(--line));}
  .bld-slot{margin-bottom:12px;padding:10px;border:1px solid color-mix(in srgb,var(--line) 80%,transparent);
    border-radius:var(--radius);background:var(--paper);}
  .bld-slot:last-child{margin-bottom:0;}
  .bld-slot-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:7px;}
  .bld-slot-head .slot-name{color:var(--accent);font-weight:650;font-size:var(--fs-sm);}
  .bld-slot-head .slot-count{color:var(--muted);font-size:var(--fs-2xs);}
  .bld-slot-actions{margin-left:auto;display:flex;gap:4px;align-items:center;}
  .bld-slot-actions button{padding:4px 7px;font-size:var(--fs-xs);}
  .bld-search{width:150px;font-size:var(--fs-xs);padding:4px 7px;}
  .bld-selects select + select{margin-top:5px;}

  /* ── 스위치 ── */
  .sw{position:relative;display:inline-block;width:32px;height:18px;flex:none;}
  .sw input{opacity:0;width:0;height:0;}
  .sw .sl{position:absolute;inset:0;background:var(--line);border-radius:99px;transition:.15s;cursor:pointer;}
  .sw .sl::before{content:"";position:absolute;width:13px;height:13px;left:2.5px;top:2.5px;
    background:var(--muted);border-radius:50%;transition:.15s;}
  .sw input:checked + .sl{background:var(--accent-dim);}
  .sw input:checked + .sl::before{transform:translateX(14px);background:var(--accent);}

  /* ── 가운데: 미리보기 ── */
  .pv{display:flex;flex-direction:column;align-items:center;gap:14px;}
  .pv-img{width:min(100%,720px);max-height:calc(100vh - 190px);aspect-ratio:1/1;background:#080a0f;border-radius:calc(var(--radius) + 4px);overflow:hidden;
    display:flex;align-items:center;justify-content:center;border:1px solid #000;box-shadow:0 10px 32px #10182824;}
  .pv-img img{width:100%;height:100%;object-fit:contain;}
  /* ── 아직 아무것도 안 뽑았을 때 ────────────────────────────────────────
     그림이 들어오면 어두운 바탕이 맞다(그림을 보는 자리다). 그런데 **빈 채로도**
     720×720 검은 정사각형이 서 있어서, 첫 화면에서 가장 큰 시각 요소가 빈 상자였다.
     1600 실측에서 미리보기 720×620 + 우패널 300×930 이 모두 빈 자리였다.
     그래서 **비었을 때만** 낮고 옅은 자리표시로 바꾼다 — 기능은 그대로고 모양만 바뀐다.
     ⚠ `pvImg` 는 한 번 채워지면 다시 비지 않으므로(`innerHTML` 로 넣기만 한다)
       `:has(img)` 로 갈라도 깜빡이지 않는다. `:has` 를 모르는 브라우저에서는
       이 규칙만 통째로 무시되어 예전 모습으로 돌아갈 뿐 깨지지 않는다. */
  .pv-img:not(:has(img)){
    aspect-ratio:auto;min-height:190px;background:var(--paper2);
    border:1px dashed var(--line);box-shadow:none;}
  .pv-meta{width:100%;max-width:720px;}
  .pv-meta .nm{font-weight:700;color:var(--accent);font-size:var(--fs);}
  .pv-meta .fn{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin-top:3px;}
  .pv-status{font-size:var(--fs-xs);margin-top:5px;line-height:1.45;}
  .phase-pill{display:inline-flex;align-items:center;padding:2px 7px;border-radius:var(--radius-pill);
    font-size:var(--fs-2xs);font-weight:700;background:var(--paper2);color:var(--muted);}
  .phase-pill[data-phase="running"],.phase-pill[data-phase="stopping"]{color:var(--warn);}
  .phase-pill[data-phase="completed"]{color:var(--good);}
  .phase-pill[data-phase="partial"],.phase-pill[data-phase="failed"]{color:var(--danger);}
  .pbar{height:6px;border-radius:var(--radius-pill);background:var(--paper2);overflow:hidden;margin-top:9px;}
  .pbar div{height:100%;background:var(--good);width:0;transition:width .3s;}

  /* ── 오른쪽: 히스토리 ── */
  .hist-t{font-size:var(--fs-xs);color:var(--muted);margin-bottom:10px;padding:4px 2px 8px;border-bottom:1px solid var(--line);font-weight:700;}
  .hist-g{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
  .hist-g img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:var(--radius);border:1px solid var(--line);cursor:pointer;}
  .hist-g:empty::before{content:"생성된 이미지가 여기에 쌓입니다.";grid-column:1/-1;color:var(--muted);
    font-size:var(--fs-xs);line-height:1.6;padding:14px 4px;}

  /* ── 모달 ── */
  .modal-bg{position:fixed;inset:0;background:#000c;z-index:60;display:flex;align-items:flex-start;
    justify-content:center;padding:36px 18px;overflow-y:auto;}
  .modal{background:var(--paper);border:1px solid var(--line);border-radius:calc(var(--radius) + 2px);max-width:880px;width:100%;padding:20px;}
  .modal h3{margin:0 0 13px;font-size:var(--fs);}
  .flash{font-family:var(--mono);font-size:var(--fs-xs);color:var(--good);}
  @media(max-width:1200px){
    body{overflow:auto;}
    #app{display:flex;flex-direction:column;height:auto;min-height:calc(100vh - 56px);}
    body[data-mode="preview"] .left{order:1;}
    body[data-mode="preview"] .center{order:2;}
    body:not([data-mode="preview"]) .center{order:1;}
    body:not([data-mode="preview"]) .left{order:2;}
    .right{order:3;}
    .left,.right{border:none;border-bottom:1px solid var(--line);box-shadow:none;}
    .left{min-height:680px;}
    .center{overflow:visible;padding:20px;}
    .right{min-height:120px;}
    #lwDrag{display:none;}
    .builder-shell{grid-template-columns:minmax(0,1fr) 300px;}
  }
  @media(max-width:920px){
    .builder-shell{grid-template-columns:1fr;}
    .builder-summary{position:static;grid-row:1;}
  }
  @media(max-width:700px){
    .titlebar{height:auto;min-height:98px;padding:8px 10px;gap:7px;display:grid;
      grid-template-columns:1fr auto;grid-template-rows:32px 46px;position:sticky;top:0;}
    .titlebar .app{font-size:var(--fs);grid-column:1;grid-row:1;}
    .titlebar .stat{max-width:180px;text-align:right;grid-column:2;grid-row:1;}
    .titlebar .spacer{display:none;}
    .modes{grid-column:1/-1;grid-row:2;width:100%;overflow-x:auto;gap:2px;}
    .modes button{flex:1 0 68px;padding:0 7px;font-size:var(--fs-xs);white-space:nowrap;}
    #app{min-height:calc(100vh - 98px);}
    .center{padding:14px 10px;}
    .card{padding:15px 13px;margin-bottom:12px;}
    .grid2,.grid3{grid-template-columns:1fr;}
    .left{min-height:0;}
    /* ⚠ 예전엔 max-height:150px 였다. 390×844 실측에서 내용 999px 중 150px 만 보여
       85% 가 잘렸다. 화면 높이에 비례하게 바꿔 좁은 기기에서도 한 번에 더 읽힌다. */
    .psec-body textarea{min-height:170px;max-height:38vh;}
    .tools{gap:6px;padding-inline:10px;}
    .tool{padding:9px 2px;}
    .pv-img{width:100%;max-height:none;border-radius:var(--radius);}
    .right{padding:12px 10px;}
    .modal-bg{padding:12px 7px;}
    .modal{padding:15px 12px;}
    .modal.builder-modal > .bar:last-child{bottom:-15px;margin:12px -12px -15px!important;padding:10px 12px 12px;}
    .builder-entry-grid{grid-template-columns:1fr;}
    .builder-entry{min-height:0;}
    .builder-intro{display:block;}
    .builder-intro .route{display:inline-block;margin-top:8px;}
    .builder-toolbar .n{width:100%;margin-left:0;}
    .bld-slot-actions{width:100%;margin-left:0;}
    .bld-search{flex:1;min-width:120px;width:auto;}
  }
  </style>
  <!-- 작업실 화면 구성은 별도 자산으로 유지한다. 파일이 없어도 기존 호환 UI는 동작한다. -->
  <link rel="stylesheet" href="/ui/studio.css">
  </head>
<body data-mode="preview">

<div class="titlebar">
  <div class="app">NAI <span>배치 생성기</span>__PROFBADGE__
    <span class="save-state" id="saveState" title="설정.json 자동저장 상태">저장됨 ✓</span></div>
  <!-- 계획서의 5탭 순서 그대로: 기본 생성 · 자료 · 빌더 · 세팅 · 기타.
       숫자키 1~5 로도 옮긴다. -->
  <div class="modes" id="modes">
    <button data-mode="preview" class="on" title="Alt+1"><span class="navico" aria-hidden="true">◉</span><span>생성</span></button>
    <button data-mode="library" title="Alt+2"><span class="navico" aria-hidden="true">▦</span><span>자료</span></button>
    <button data-mode="builder" title="Alt+3"><span class="navico" aria-hidden="true">◇</span><span>빌더</span></button>
    <button data-mode="settings" title="Alt+4"><span class="navico" aria-hidden="true">≋</span><span>세팅</span></button>
    <button data-mode="system" title="Alt+5"><span class="navico" aria-hidden="true">⚙</span><span>기타</span></button>
  </div>
  <div class="spacer"></div>
  <div class="stat" id="topStat">-</div>
  <!-- 패널 접기 — Forge 는 타이틀바 우측에 같은 것을 둔다 (`CustomTitleBar.tsx:110-`) -->
  <button class="paneltog" id="togLeft" aria-pressed="false"
    title="프롬프트 패널 접기 / 펴기 (Alt+[)">◧</button>
  <button class="paneltog" id="togRight" aria-pressed="false"
    title="최근 생성 패널 접기 / 펴기 (Alt+])">◨</button>
</div>

<div id="startupRecovery" role="alert"
  style="position:fixed;z-index:120;left:12px;right:12px;top:54px;padding:11px 13px;
  border:2px solid var(--warn);border-radius:var(--radius);background:var(--card);
  box-shadow:0 8px 28px #0005;display:none;align-items:center;gap:10px;flex-wrap:wrap;">
  <div style="flex:1;min-width:240px;"><b>설정 손상을 안전하게 격리하고 기본 설정으로 시작했습니다.</b>
    <div class="hint" id="startupRecoveryDetail"></div></div>
  <button type="button" id="startupRecoveryBackup">내 자료 백업·복원 열기</button>
  <button type="button" id="startupRecoveryClose">확인</button>
</div>

<div class="app" id="app">
  <!-- ══ 왼쪽: 프롬프트 패널 ══ -->
  <div class="left"><div id="lwDrag" title="드래그로 패널 폭 조절"></div>
    <div class="preset-bar">
      <select id="presetSel"><option value="">베이스 프리셋 불러오기...</option></select>
      <button id="presetSave" title="현재 프롬프트+네거티브+파라미터를 파일로 저장">저장</button>
    </div>

    <!-- ⚠ 이 1.2 : 1 배분을 건드리기 전에 아래를 읽을 것 (두 번 헛짚었다).
         ① **칸이 커 보인다고 줄이지 말 것.** 빈 화면에서만 커 보인다. `수집/그림체.json`
            732건 실측은 base 중앙값 593자 · negative 중앙값 1,080자(UC 프리셋 문구를
            `split_uc_preset` 으로 뗀 뒤)다. 지금도 1280 에서는 **중앙값 프롬프트가 38%
            잘린다.** 라운드10 이 잘림을 80%→34% 로 줄이려 키운 자리다.
         ② **길이가 길다고 네거티브에 더 주지도 말 것.** 1 : 1.5 로 뒤집어 실측했더니
            두 칸 잘림 **합계가 그대로였다** (1600 317→317px · 1280 521→522px).
            세로는 총량이 정해져 있어 순수 재분배이고, 자주 고치는 프롬프트 칸만
            14%→42% 로 나빠졌다. 네거티브는 그림체에서 통째로 받아 두고 거의 안 고친다.
            그래서 **자주 고치는 쪽에 더 주는 지금 배분을 유지한다.**
         진짜로 나아지려면 총 높이를 늘리거나(접기·오버레이) 칸을 자동으로 키워야 한다. -->
    <div class="psec" style="flex:1.2;">
      <div class="psec-head" data-fold="pPos"><span class="chev">▾</span><span class="t">프롬프트</span>
        <span class="count" id="posTok">0</span>
        <span class="ed" id="tagVerifyBtn" title="단부루에 실제로 있는 태그인지 확인 (없는 태그는 토큰만 먹는다)">✓태그</span>
        <span class="ed" id="findRepBtn" title="프롬프트·네거티브·캐릭터 칸에서 한꺼번에 찾아 바꾸기 (SDStudio 참고)">⇄바꾸기</span>
        <span class="ed" id="split3Btn" title="고정 / 가변 / 디테일 세 칸으로 나누기">⋮⋮</span></div>
      <div class="psec-body" id="pPos">
        <textarea id="basePrompt" placeholder="1girl, artist:..., masterpiece"></textarea>
        <!-- 3분할 — 켜면 아래 세 칸이 위 칸을 대신한다. 보낼 때는 위에서부터 이어 붙인다.
             그림체는 고정에 두고 가변만 굴리는 식으로 쓴다. -->
        <!-- ⚠ 여기 `style="display:flex"` 를 인라인으로 두면 `.hidden{display:none}` 이
             **절대 못 이긴다**(인라인이 항상 위다). 그래서 `⋮⋮` 토글이 클래스를 붙였다 떼도
             3분할이 늘 보였고, 프롬프트 칸이 좌우로 반 토막 나 있었다
             (1600px 실측: 439px 중 206px 만 씀). display 는 CSS 로 옮겼다. -->
        <div id="split3" class="hidden" style="flex-direction:column;gap:5px;flex:1;min-height:0;">
          <textarea id="baseFixed" data-s3 placeholder="고정 — 그림체·작가 조합처럼 늘 들어갈 것" style="flex:1;"></textarea>
          <textarea id="baseVar" data-s3 placeholder="가변 — 매번 바꿔 굴릴 것 (조각 &lt;이름&gt; 쓰기 좋음)" style="flex:1;"></textarea>
          <textarea id="baseDetail" data-s3 placeholder="디테일 — 세부 묘사·마감" style="flex:1;"></textarea>
        </div>
        <div id="tagVerifyOut" class="hidden" style="font-size:var(--fs-2xs);line-height:1.7;padding:6px 2px 0;"></div>
      </div>
    </div>

    <div class="psec" style="flex:1;">
      <div class="psec-head" data-fold="pNeg"><span class="chev">▾</span><span class="t">네거티브</span>
        <span class="count" id="negTok">0</span></div>
      <div class="psec-body" id="pNeg"><textarea id="negPrompt" placeholder="lowres, bad anatomy, ..."></textarea></div>
    </div>

    <!-- 이 줄은 '여기서 바로 여는 것' — 오버레이가 프롬프트 패널 위에 뜬다 -->
    <div class="tools">
      <button class="tool" data-ovl="chars"><span class="ico">👥</span>캐릭터<span class="badge" id="bgChars">0</span></button>
      <button class="tool" data-ovl="refs"><span class="ico">🎨</span>레퍼런스<span class="badge" id="bgRefs">0</span></button>
      <button class="tool" data-ovl="params"><span class="ico">🎚</span>파라미터</button>
      <button class="tool" data-ovl="frags"><span class="ico">🎲</span>조각<span class="badge" id="bgFrags">0</span></button>
    </div>
    <!-- 이 줄은 '다른 탭으로 넘어가는 것'. 같은 모양이면 눌러 보고서야
         알게 되므로 줄을 나누고 ↗ 를 붙였다. -->
    <div class="tools jumps">
      <button class="tool jump" data-mode-jump="settings"><span class="ico">🎬</span>세팅<span class="ar">↗</span><span class="badge" id="bgSets">0</span></button>
      <button class="tool jump" data-mode-jump="builder"><span class="ico">🧰</span>빌더<span class="ar">↗</span></button>
    </div>

    <div class="genrow">
      <div class="qty">
        <button id="qtyM" title="수량 줄이기">−</button>
        <input id="qty" type="number" value="1" min="1" max="99" step="1"
          inputmode="numeric" aria-label="빠른 생성 수량 (1~99)">
        <button id="qtyP" title="수량 늘리기 (최대 99)">+</button>
      </div>
      <button class="primary go" id="genBtn">생성</button>
      <button class="danger go hidden" id="stopBtn" title="도는 작업을 장 경계에서 멈춥니다 (전송 중인 장은 마저 받음)"
        onclick="fetch('/api/stop',{method:'POST'})">■ 중지</button>
    </div>
    <div class="genrow" style="border:none;padding-top:0;">
      <button class="go" id="batchBtn" style="flex:1;">🎬 선택 세팅 일괄 생성</button>
    </div>
    <div class="genrow" id="anlasRow" style="border:none;padding-top:0;justify-content:space-between;">
      <span class="hint" id="anlasCost">비용 계산 중...</span>
      <button id="anlasBal" title="NAI 계정의 남은 Anlas 조회">잔액 확인</button>
    </div>

    <!-- 캐릭터 오버레이 -->
    <div class="ovl hidden" id="ovlChars">
      <div class="ovl-head"><span class="t">👥 캐릭터</span>
        <span class="count" style="font-size:var(--fs-2xs);color:var(--muted);">한 그림에 함께 들어갈 인물 · 보내는 건 켠 것만 (NAI 상한 6명)</span>
        <button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <div class="bar" style="margin-bottom:6px;">
          <label class="hint" style="display:flex;align-items:center;gap:6px;cursor:pointer;"
                 title="끄면 AI's Choice (NAI가 위치 결정)">
            <input type="checkbox" id="chUseCoords"> 위치 지정</label>
          <span class="hint" id="chCoordsNote"></span>
        </div>
        <!-- 인물이 둘 이상인데 좌표를 안 쓰면 NAI 가 몸을 겹쳐 그리는 일이 흔하다.
             한 번 눌러 좌우로 떨어뜨릴 수 있게 해 둔다. -->
        <div class="row hidden" id="chFuseWarn" style="margin:0 0 8px;padding:8px 10px;">
          <div style="font-size:var(--fs-xs);"><b>인물이 둘 이상인데 위치를 안 정했습니다.</b>
            이러면 NAI 가 <b>몸을 붙여</b> 그리는 일이 흔합니다.</div>
          <div class="bar" style="margin-top:6px;">
            <button class="primary" id="chSpread">좌우로 떨어뜨리기</button>
            <span class="hint">위치 지정을 켜고 x 0.3 / 0.7 로 놓습니다</span>
          </div>
        </div>
        <div id="slotList"></div>
        <div class="bar" style="margin-top:8px;">
          <button id="slotAdd">+ 직접 입력</button>
          <select id="slotLib" style="flex:1;"><option value="">+ 라이브러리에서...</option></select>
        </div>
        <!-- 인물 칸 일괄 손질 (NAIS3 의 캐릭터 다중 선택·일괄 편집을 우리 구조로) -->
        <div class="bar" style="margin-top:4px;flex-wrap:wrap;">
          <span class="hint">일괄:</span>
          <button id="slotAllOn" title="모든 칸 켜기">전부 켜기</button>
          <button id="slotAllOff" title="모든 칸 끄기 — 칸은 남습니다">전부 끄기</button>
          <button id="slotBulkAdd" title="켠 칸의 외형 뒤에 같은 태그를 한꺼번에 붙입니다">＋태그 주입</button>
          <button id="slotDupAll" title="켠 칸을 복제합니다">⧉ 복제</button>
          <!-- 되돌릴 수 없는 단추는 만드는 단추 옆에 붙이지 않는다 (자료 탭과 같은 규칙).
               없애지도, 빨간색을 빼지도 않는다 — 자리만 떼어 잘못 눌리는 것을 막는다.
               ⚠ `<span style="flex:1">` 스페이서를 쓰면 안 된다. `.bar` 는 `flex-wrap:wrap`
                 이라 좁은 오버레이에서 스페이서가 남은 자리를 다 먹고 **단추를 다음 줄
                 왼쪽 끝으로 밀어낸다**(실측: x=12 로 감). `margin-left:auto` 는 어느 줄에
                 놓이든 그 줄의 오른쪽 끝으로 간다. -->
          <button class="danger" id="slotDelOff" style="margin-left:auto;"
            title="꺼 둔 칸을 모두 지웁니다">꺼진 칸 정리</button>
        </div>
      </div>
    </div>


    <!-- 레퍼런스 오버레이 (바이브 · 캐릭터 레퍼런스) -->
    <div class="ovl hidden" id="ovlRefs">
      <div class="ovl-head"><span class="t">🎨 레퍼런스</span>
        <span class="count" style="font-size:var(--fs-2xs);color:var(--muted);">그림으로 분위기·생김새를 참조</span>
        <button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <p class="hint"><b>바이브</b>는 그림의 분위기를 옮깁니다. 처음 한 번만 인코딩(2 Anlas)하고
        그 뒤로는 <b>공짜로 계속</b> 쓰입니다 — 배치 생성에 딱 맞습니다.<br>
        <b>캐릭터 레퍼런스</b>는 생김새를 참조합니다. Opus 무료 생성은 유지되며
        <b>레퍼런스 1개당 장당 5 Anlas</b>만 별도로 붙습니다.</p>
        <div class="reftabs">
          <button class="on" data-reftab="vibe">바이브 <span id="bgVibe">0</span></button>
          <button data-reftab="cref">캐릭터 레퍼런스 <span id="bgCref">0</span></button>
        </div>
        <div data-refpane="vibe">
          <div id="vibeDrop" class="row" style="text-align:center;padding:16px;border-style:dashed;cursor:pointer;">
            <b>＋ 바이브 그림 추가</b>
            <div class="hint" style="margin-top:3px;">분위기를 가져올 그림 · PNG / WebP</div>
            <input type="file" id="vibeFile" accept="image/png,image/webp" multiple style="display:none;"></div>
          <div id="vibeList"></div>
        </div>
        <div data-refpane="cref" class="hidden">
          <div id="crefDrop" class="row" style="text-align:center;padding:16px;border-style:dashed;cursor:pointer;">
            <b>＋ 캐릭터 레퍼런스 추가</b>
            <div class="hint" style="margin-top:3px;">생김새를 참조할 그림 · 장당 5 Anlas</div>
            <input type="file" id="crefFile" accept="image/png,image/webp" multiple style="display:none;"></div>
          <div id="crefList"></div>
        </div>
        <p class="hint" id="refMsg" style="margin-top:6px;"></p>
      </div>
    </div>

    <!-- 파라미터 오버레이 -->
    <!-- 조각(와일드카드) — 프롬프트 어디서나 쓰는 치환. 세팅·씬을 대체하지 않는다 -->
    <div class="ovl hidden" id="ovlFrags">
      <div class="ovl-head"><span class="t">🎲 조각 (와일드카드)</span><button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <p class="hint">프롬프트 어디에든 <b>&lt;이름&gt;</b> 을 쓰면 그 조각의 한 줄로 바뀝니다.
        <b>&lt;*이름&gt;</b> 은 차례대로(다음 장에 다음 줄), <b>{a|b|c}</b> 는 그 자리에서 셋 중 하나.
        한 줄짜리 조각은 고정 치환이 됩니다. 기본 생성·씬·세팅 <b>어디서나</b> 같습니다.</p>
        <div class="bar">
          <button id="fragNew">+ 새 조각</button>
          <button id="fragExport" title="조각/*.txt 를 ZIP 으로">📤 내보내기</button>
          <button id="fragImport" title="TXT·ZIP 을 조각/ 에 넣기">📥 가져오기</button>
          <input type="file" id="fragImportFile" accept=".txt,.zip" multiple style="display:none;">
          <button id="fragReset" title="&lt;*이름&gt; 의 순번을 처음으로">순번 리셋</button>
          <span class="n" id="fragMsg" style="margin-left:auto;"></span>
        </div>
        <div id="fragList" style="margin-top:8px;"></div>
        <div class="field" style="margin-top:10px;">
          <label>시험해 보기 — 여기 적으면 실제로 어떻게 바뀌는지 보여줍니다 (순번은 안 올라감)</label>
          <input type="text" id="fragTry" placeholder="1girl, <표정>, {smile|serious}">
          <div class="hint" id="fragTryOut" style="margin-top:5px;font-family:var(--mono);"></div>
        </div>
      </div>
    </div>

    <div class="ovl hidden" id="ovlParams">
      <div class="ovl-head"><span class="t">🎚 생성 파라미터</span><button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <div class="grid2">
          <div class="field"><label>모델</label><select id="pModel">__MODELS__</select></div>
          <div class="field"><label>저장 포맷 <span class="hint">(공홈과 같은 선택)</span></label>
            <select id="pFormat">
              <option value="webp">WebP — 용량이 작음 (기본)</option>
              <option value="png">PNG — 무손실 · 투명 지원</option></select></div>
          <!-- 저장 폴더 — 비우면 프로필의 output/. 탐색기도 이 폴더를 본다 -->
          <div class="field"><label>저장 폴더 <span class="hint">(비우면 기본 output)</span></label>
            <input type="text" id="pOutDir" placeholder="예: D:\\NAI결과"></div>
          <div class="field"><label>날짜별로 나누기</label>
            <select id="pOutDate">
              <option value="off">한 폴더에 모으기 (기본)</option>
              <option value="on">모드 폴더 아래 날짜별로</option></select></div>
          <!-- 저장 시점에 메타를 아예 안 넣는 선택. 나중에 따로 지우는 기능(기타 탭)은 그대로 둔다. -->
          <div class="field"><label>메타데이터 <span class="hint">(저장 시점)</span></label>
            <select id="pClean">
              <option value="off">넣기 — 나중에 끌어다 놓아 그림체 복원 가능 (기본)</option>
              <option value="on">지우고 저장 — 공유용 · 복원 불가</option></select></div>
          <div class="field" id="pCleanOpts" style="display:none;"><label>가볍게 — 긴 변
            <span class="hint">품질은 아래 저장 품질</span></label>
            <select id="pMaxSide">
              <option value="0">그대로</option><option value="1536">1536px</option>
              <option value="1024">1024px</option><option value="768">768px</option></select></div>
          <div class="field"><label>저장 품질 <span class="hint">(WebP · 40~100)</span></label>
            <input type="number" id="pSaveQ" min="40" max="100" step="5"></div>
          <div class="field"><label>해상도 <span class="hint">(세팅 씬은 씬별 값을 씀)</span></label>
            <select id="pRes">__RES__<option value="">직접 입력...</option></select></div>
          <div class="field" id="pWHwrap" style="display:none;"><label>가로 × 세로</label>
            <div class="bar"><input type="number" id="pWidth" step="64" min="64" max="2048" style="flex:1;">
            <input type="number" id="pHeight" step="64" min="64" max="2048" style="flex:1;"></div>
            <span class="hint" id="pResNote"></span></div>
          <div class="field"><label>CFG (Prompt Guidance)</label><input type="number" id="pScale" step="0.1" min="1" max="10"></div>
          <div class="field"><label>리스케일</label><input type="number" id="pRescale" step="0.02" min="0" max="1"></div>
          <div class="field"><label>스텝</label><input type="number" id="pSteps" min="1" max="50"></div>
          <div class="field"><label>샘플러</label><select id="pSampler">__SAMPLERS__</select></div>
          <div class="field"><label>노이즈 스케줄</label><select id="pSched">__SCHEDS__</select></div>
          <div class="field"><label>UC 프리셋 <span class="hint">(네거티브 기본 묶음)</span></label><select id="pUc">__UCP__</select></div>
          <div class="field"><label>퀄리티 태그 <span class="hint">(끝에 자동 추가)</span></label>
            <select id="pQuality"><option value="off">끔</option><option value="on">켬</option></select></div>
          <div class="field"><label>Variety+</label><select id="pVariety"><option value="off">끔</option><option value="on">켬</option></select></div>
          <div class="field"><label>회차 번호 <span class="hint">(같은 번호 = 같은 결과 재현)</span></label>
            <input type="number" id="pSeed"></div>
          <div class="field"><label>NAI 시드 <span class="hint">(0 = 장마다 다름)</span></label>
            <div class="bar"><input type="number" id="pNaiSeed" placeholder="0" style="flex:1;">
              <button id="pSeedRoll" title="새 랜덤 시드">🎲</button>
              <button id="pSeedClear" title="고정 해제 (0)">✕</button></div>
            <p class="hint" id="pSeedNow" style="margin-top:5px;"></p></div>
        </div>
        <div class="fold closed" id="pAdvHead" data-fold="pAdv" style="margin-top:10px;">고급 (기본값 그대로 두어도 됩니다)</div>
        <div id="pAdv" class="hidden">
          <p class="hint" id="pAdvNote"></p>
          <div class="grid2">
            <div class="field" data-gen="v3"><label>SMEA</label><select id="pSmea"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v3"><label>SMEA DYN</label><select id="pSmeaDyn"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v3"><label>Dynamic Thresholding <span class="hint">(Decrisper)</span></label><select id="pDynThr"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v3"><label>Uncond Scale <span class="hint">(네거티브 강도)</span></label><input type="number" id="pUncond" step="0.05" min="0" max="1.5"></div>
            <div class="field" data-gen="v3"><label>ControlNet Strength</label><input type="number" id="pCtrl" step="0.1" min="0" max="2"></div>
            <div class="field" data-gen="v4"><label>Prefer Brownian</label><select id="pBrownian"><option value="on">켬</option><option value="off">끔</option></select></div>
            <div class="field" data-gen="v4"><label>Euler Ancestral 버그 재현 <span class="hint">(구버전 그림체 재현용)</span></label>
              <select id="pEulerBug"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v4"><label>캐릭터 위치 좌표 사용 <span class="hint">(끄면 NAI가 배치)</span></label>
              <select id="pCoords"><option value="off">끔</option><option value="on">켬</option></select></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ 가운데: 모드 영역 ══ -->
  <div class="center" id="center">
    <div class="view" id="vPreview">
      <!-- 첫 실행 안내 — 프롬프트가 비어 있을 때만 -->
      <div class="card hidden" id="welcome">
        <h2><span class="n">시작</span>마음에 드는 그림에서 설정을 가져오세요</h2>
        <p class="hint">직접 프롬프트를 짤 필요 없습니다. NAI로 만든 그림 파일을 넣으면
        <b>프롬프트·네거티브·설정값(CFG·리스케일·스텝·샘플러·시드)</b>을 통째로 읽어옵니다.</p>
        <div id="welcomeDrop" class="row" style="text-align:center;padding:26px 14px;border-style:dashed;cursor:pointer;">
          <div style="font-size:var(--fs);font-weight:600;">🖼️ 여기에 그림을 끌어다 놓으세요</div>
          <div class="hint" style="margin-top:6px;">눌러서 파일을 골라도 됩니다 · PNG / WebP · 여러 장 한꺼번에 가능</div>
          <input type="file" id="welcomeFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
        <p class="hint" style="margin-top:10px;">
          가진 그림이 없다면 <b>[자료]</b>의 그림체 라이브러리(<span id="welcomeCount">…</span>개)에서 골라도 됩니다.
          카톡·디스코드를 거친 그림은 정보가 지워져 있으니 <b>원본 파일</b>을 넣어주세요.</p>
        <div class="bar" style="margin-top:8px;">
          <button class="primary" id="welcomeLib">📚 그림체 고르러 가기</button>
          <button id="welcomeSkip">직접 입력할래요</button>
          <span class="n" id="welcomeMsg" style="margin-left:auto;"></span>
        </div>
      </div>
      <div class="pv">
        <div class="pv-img" id="pvImg"><span style="color:var(--muted);font-size:var(--fs-xs);text-align:center;">
          왼쪽에서 프롬프트·캐릭터를 넣고<br>[생성]을 누르면 여기에 표시됩니다.</span></div>
        <div class="pv-meta">
          <div class="bar"><div class="nm" id="pvName">대기 중</div>
            <span class="phase-pill" id="pvPhase" data-phase="idle">대기</span></div>
          <div class="fn" id="pvFile">-</div>
          <div class="pv-status" id="pvStatus">설정을 준비하고 있습니다.</div>
          <div class="bar" style="margin:8px 0 0;"><span class="n" id="pvProg">0 / 0</span>
            <span class="n" id="pvCounts"></span>
            <span style="font-size:var(--fs-2xs);color:var(--muted);" id="pvEta">남은 시간 —</span>
            <span style="font-size:var(--fs-2xs);color:var(--muted);" id="pvDaily"></span>
            <button id="pvReturn" class="hidden">다시 실행할 화면</button></div>
          <div class="bar" id="pvSeedRow" style="margin:6px 0 0;display:none;">
            <span class="n" id="pvSeed" title="이 그림의 NAI 시드"></span>
            <button id="pvSeedCopy" title="시드 복사">복사</button>
            <button id="pvSeedLock" title="이 시드로 고정">고정</button></div>
          <div class="pbar"><div id="pvBar"></div></div>
        </div>
      </div>
      <!-- img2img · 인페인트 — 왼쪽 프롬프트·파라미터를 그대로 쓰고 원본만 더한다 -->
      <div class="card">
        <h2><span class="n">고쳐 그리기</span>img2img · 인페인트
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">왼쪽 프롬프트·파라미터를 그대로 씁니다</span></h2>
        <p class="hint">그림을 넣고 <b>변화 강도</b>만 주면 <b>img2img</b>(전체를 다시 그림),
        칠한 곳이 있으면 <b>인페인트</b>(칠한 곳만 다시 그림)로 나갑니다.
        결과는 <b>output/img2img/</b> · <b>output/인페인트/</b> 에 저장됩니다.</p>
        <div id="i2iDrop" class="row" style="text-align:center;padding:18px 14px;border-style:dashed;cursor:pointer;">
          <b>🖌️ 고칠 그림을 여기에 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">PNG / WebP · 넣으면 아래에 뜹니다</div>
          <input type="file" id="i2iFile" accept="image/png,image/webp" style="display:none;">
        </div>
        <div id="i2iStage" class="hidden" style="margin-top:8px;">
          <!-- 겹쳐 그리려면 두 캔버스의 화면 크기가 정확히 같아야 한다.
               배율은 JS 가 style.width 로 직접 준다 (max-width 로 눌리면 어긋난다). -->
          <div id="i2iWrap" style="overflow:auto;max-height:78vh;border:1px solid var(--line);
               border-radius:var(--radius);background:var(--paper2);">
            <div id="i2iPad" style="position:relative;display:inline-block;">
              <canvas id="i2iBase" style="display:block;"></canvas>
              <canvas id="i2iMask" style="position:absolute;left:0;top:0;cursor:crosshair;opacity:.55;"></canvas>
            </div>
          </div>
          <div class="filterbar" style="margin-top:8px;">
            <span class="hint" style="white-space:nowrap;">변화 강도</span>
            <input type="range" id="i2iStrength" min="0.1" max="1" step="0.01" value="0.7" style="flex:1;"
              title="인페인트는 1.00 까지 · img2img 는 0.99 까지 (1.00 이면 원본을 아예 안 보므로 NAI 가 막습니다)">
            <span class="n" id="i2iStrengthN">0.70</span>
            <span class="hint" style="white-space:nowrap;">붓 굵기</span>
            <input type="range" id="i2iBrush" min="2" max="300" step="1" value="48" style="width:110px;">
            <span class="n" id="i2iBrushN">48px</span>
            <button id="i2iErase" title="지우개로 바꿔 칠한 것을 부분만 지웁니다">🧽 지우개</button>
            <button id="i2iUndo" title="직전 붓질만 되돌립니다 (Ctrl+Z)">↶ 되돌리기</button>
            <button id="i2iClear">전부 지우기</button>
            <span class="hint" style="white-space:nowrap;">화면 크기</span>
            <select id="i2iZoom">
              <option value="0.5">50%</option><option value="0.75">75%</option>
              <option value="1" selected>100%</option><option value="1.5">150%</option>
              <option value="2">200%</option></select>
          </div>
          <div class="bar" style="margin-top:6px;">
            <span class="n" id="i2iMode">칠하지 않음 → img2img</span>
            <span class="hint" id="i2iCost" style="margin-left:auto;"></span>
            <button class="primary" id="i2iGo">▶ 고쳐 그리기</button>
            <button id="i2iDrop2">다른 그림</button>
          </div>
          <p class="hint" id="i2iMsg"></p>
        </div>
      </div>

      <div class="card">
        <h2><span class="n">디렉터</span>NAI 가 그림을 다시 손봐줍니다 <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">배경 제거 · 라인아트 · 스케치 · 색칠 · 표정 · 정리 · 업스케일</span></h2>
        <p class="hint">이미 있는 그림을 넣으면 NAI 가 손봐서 돌려줍니다. 결과는
        <b>output/디렉터/</b> 에 저장되고 미리보기에도 뜹니다.
        배경 제거는 투명 PNG 로, 나머지는 WebP 로 저장됩니다.</p>
        <div id="dirDrop" class="row" style="text-align:center;padding:20px 14px;border-style:dashed;cursor:pointer;">
          <b>🖼️ 손볼 그림을 여기에 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">PNG / WebP · 여러 장이면 차례로 처리합니다</div>
          <input type="file" id="dirFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
        <div class="filterbar" style="margin-top:8px;">
          <select id="dirTool">__DIRTOOLS__<option value="upscale">업스케일 (해상도 올리기)</option></select>
          <select id="dirEmotion" style="display:none;">__EMOTIONS__</select>
          <input type="text" id="dirPrompt" placeholder="색 유도 프롬프트 (선택)" style="display:none;">
          <select id="dirDefry" style="display:none;">
            <option value="0">기본 강도</option><option value="1">강하게 1</option>
            <option value="2">강하게 2</option><option value="3">강하게 3</option>
            <option value="4">강하게 4</option><option value="5">강하게 5</option></select>
          <select id="dirScale" style="display:none;">
            <option value="2">2배</option><option value="4" selected>4배</option></select>
          <span class="n" id="dirMsg"></span>
        </div>
        <p class="hint">디렉터 툴은 Anlas 를 씁니다 — Opus 는 409,600px 까지 대부분 무료(배경 제거는 예외).
        배경 제거는 rembg 같은 로컬 무료 도구로 대신할 수도 있습니다.</p>
      </div>

    </div>

    <div class="view" id="vSettings" style="display:none;">
      <div id="studioSettingsNav" class="studio-subnav hidden" aria-label="세팅 작업 선택">
        <div class="studio-subnav-copy">
          <span class="eyebrow">Setting workspace</span>
          <strong>골라 쓰고, 가볍게 변주하고, 필요할 때만 구조를 편집합니다</strong>
        </div>
        <div class="studio-subnav-actions" role="tablist" aria-label="세팅 작업">
          <button type="button" data-settings-work="select" role="tab">씬 고르기</button>
          <button type="button" data-settings-work="quick" role="tab">빠른 변주</button>
          <button type="button" data-settings-work="build" role="tab">세팅 만들기</button>
        </div>
      </div>
      <span id="compareClassicHome" hidden aria-hidden="true"></span>
      <div class="card" id="compareCard">
        <h2><span class="n">비교 생성</span>내 자료를 같은 조건으로 한 장씩 보기
          <span class="count" id="cmpCounts" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">그림체·캐릭터를 손으로 하나씩 바꾸지 않고 같은 조건으로 돌려
        <b>output/비교생성/</b>에 모읍니다. 그림체는 <b>베이스+네거티브+생성 설정값</b>을
        통째로 유지하며, 아래에서 켠 경우에만 비교를 위해 해상도를 하나로 고정합니다.
        <b>그림체×캐릭터</b>는 두 자료 수를 곱하므로 실행 전 장수를 반드시 확인합니다.</p>

        <div class="grid3" role="radiogroup" aria-label="비교할 자료">
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="styles" checked style="width:auto;flex:none;">
            <span><b>그림체 전체</b><br><span class="hint">현재 캐릭터는 고정</span></span></label>
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="characters" style="width:auto;flex:none;">
            <span><b>캐릭터 전체</b><br><span class="hint">현재 그림체는 고정</span></span></label>
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="both" style="width:auto;flex:none;">
            <span><b>둘 다 조합</b><br><span class="hint">그림체 × 캐릭터</span></span></label>
        </div>

        <div class="grid3" style="margin-top:8px;">
          <div class="field"><label>비교 해상도</label>
            <select id="cmpRes">__RES__<option value="custom">직접 입력</option></select>
            <div class="hidden" id="cmpCustom" style="margin-top:5px;display:grid;
              grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:5px;">
              <input type="number" id="cmpW" min="64" max="2048" step="64" value="832" aria-label="비교 너비">
              <span>×</span>
              <input type="number" id="cmpH" min="64" max="2048" step="64" value="1216" aria-label="비교 높이">
            </div>
            <label class="hint" style="display:flex;align-items:center;gap:5px;margin-top:6px;">
              <input type="checkbox" id="cmpFix" checked style="width:auto;flex:none;"> 모든 결과를 이 크기로 고정</label>
          </div>
          <div class="field"><label>비교 시드</label>
            <input type="number" id="cmpSeed" min="0" max="4294967295" step="1" value="0"
              placeholder="0 = 시작할 때 한 번 정함">
            <label class="hint" style="display:flex;align-items:center;gap:7px;margin-top:6px;">
              자료마다 확인할 시드
              <select id="cmpSeedCount" style="width:auto;">
                <option value="1">1개</option><option value="2">2개</option>
                <option value="3">3개</option><option value="4">4개</option>
              </select>
            </label>
            <label class="hint" style="display:flex;align-items:center;gap:5px;margin-top:6px;">
              <input type="checkbox" id="cmpSameSeed" checked style="width:auto;flex:none;">
              같은 시드 차례끼리 공정하게 비교</label>
          </div>
          <div class="field"><label>시험 상한 <span class="hint">(0 = 전부)</span></label>
            <input type="number" id="cmpLimit" min="0" max="2000000" step="1" value="0">
            <label class="hint" style="display:flex;align-items:center;gap:5px;margin-top:6px;">
              <input type="checkbox" id="cmpRefs" style="width:auto;flex:none;"> 현재 바이브·캐릭터 레퍼런스도 포함</label>
          </div>
        </div>

        <details class="row" id="cmpHistory" style="margin-top:8px;">
          <summary style="cursor:pointer;font-weight:700;">지난 비교 실험 · 중단 작업</summary>
          <div class="bar" style="margin-top:8px;flex-wrap:wrap;">
            <select id="cmpRuns" style="flex:1;min-width:260px;">
              <option value="">실험 기록을 불러오는 중...</option>
            </select>
            <button type="button" id="cmpRunRefresh">새로고침</button>
            <button type="button" id="cmpRunLoad">계획 불러오기</button>
            <button type="button" id="cmpRunOpen">결과 선별</button>
          </div>
          <div class="hint" id="cmpRunMsg" style="margin-top:6px;">
            중단된 실험은 당시 계획을 불러온 뒤 현재 장수와 비용을 다시 확인해야 이어집니다.
          </div>
        </details>
        <div class="row" id="cmpSummary" style="margin-top:8px;line-height:1.6;">
          자료 수와 생성 장수를 계산하는 중입니다.
        </div>
        <div class="bar" style="margin-top:8px;align-items:center;">
          <label style="display:flex;align-items:center;gap:6px;flex:1;">
            <input type="checkbox" id="cmpConfirm" style="width:auto;flex:none;">
            <span id="cmpConfirmText">장수와 API 호출 횟수를 확인했습니다.</span></label>
          <button type="button" id="cmpOpenResults">▦ 최근 결과 선별</button>
          <button class="go" id="cmpStart" disabled>▶ 비교 생성 시작</button>
        </div>
      </div>

      <div class="card" id="settingSelectCard">
        <h2><span class="n">세팅</span>씬 세트 <span class="count" id="setCount" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">세팅 = 씬 모음 + 부속 옵션 + 상대역이 담긴 <b>세팅/ 폴더의 파일</b>. 파일을 넣고 빼면 목록이 바뀝니다.
        각 세팅의 <b>전용 캐스트</b>를 비우면 왼쪽 [캐릭터]의 인물로 생성됩니다.</p>
        <div class="bar" style="margin-bottom:8px;">
          <button id="setExport" title="세팅/ 폴더의 세팅 파일들을 ZIP 으로 내려받습니다">📤 세팅 내보내기 (ZIP)</button>
          <button id="setImport" title="받은 세팅 ZIP·JSON 을 세팅/ 폴더에 넣습니다">📥 세팅 가져오기</button>
          <input type="file" id="setImportFile" accept=".zip,.json" multiple style="display:none;">
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="setThumbs"> 세트 대표 그림 보기</label>
          <span class="n" id="setMsg" style="margin-left:auto;"></span>
        </div>
        <div id="setList"></div>
        <div class="bar" style="margin-top:10px;">
          <select id="scenePreset" style="flex:1;"><option value="">씬 프리셋 불러오기...</option></select>
          <button id="scenePresetSave">현재 구성 저장</button>
        </div>
      </div>

      <!-- 씬 모드 — 세팅과 별도로 병존한다. 세팅을 대체하지 않는다. -->
      <div class="card" id="sceneQuickCard">
        <h2><span class="n">씬</span>씬 모드 (가벼운 낱개 변주)
          <span class="count" id="sceneCount" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">세팅이 <b>5장 묶음 + 문맥에 반응하는 옵션</b>이라면, 씬은 <b>이름·프롬프트·해상도만 있는 낱개</b>입니다.
        즉석에서 변주를 뽑을 때 씁니다. 씬 프롬프트는 왼쪽 그림체 뒤에 붙고, 조각 <b>&lt;이름&gt;</b> 도 그대로 먹습니다.
        <b>예약 매수를 1 이상</b>으로 걸어 둔 씬만 생성합니다. 결과는 <b>output/씬/</b> 에 쌓입니다.</p>
        <div class="bar">
          <button id="sceneAdd">+ 씬 추가</button>
          <button id="sceneRun" class="primary">▶ 예약한 씬 생성</button>
          <span class="n" id="sceneMsg" style="margin-left:auto;"></span>
        </div>
        <div id="sceneList" style="margin-top:8px;"></div>
      </div>

      <!-- 세팅 빌더 — 세팅을 앱 안에서 만들고 고친다 -->
      <div class="card" id="settingBuilderCard">
        <h2><span class="n">빌더</span>세팅 빌더
          <span class="count" id="sbClash" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--danger);"></span></h2>
        <p class="hint">세팅은 <b>세트(묶음)</b>의 모음입니다. 세트는 <b>단계명마다 씬 하나</b>로 이루어지고,
        단계 수는 <b>자유</b>입니다 (3단계든 7단계든). 씬 이름을 <b>「세트이름 단계명」</b>으로 지으면
        자동으로 한 묶음이 됩니다.</p>
        <div class="bar">
          <select id="sbPick" style="flex:1;"><option value="">고칠 세팅 고르기...</option></select>
          <button id="sbNew">+ 새 세팅</button>
          <button id="sbRenum" title="이 세팅의 씬 번호를 겹치지 않는 구간으로 다시 매깁니다">번호 다시 매기기</button>
          <!-- 세팅 삭제는 씬 수백 개가 함께 사라진다. `+ 새 세팅` 바로 옆은 위험하다.
               스페이서 대신 `margin-left:auto` — 위 캐릭터 칸 주석 참조. -->
          <button id="sbDel" class="danger" style="margin-left:auto;">세팅 삭제</button>
        </div>
        <div id="sbBody" class="hidden" style="margin-top:8px;">
          <div class="grid3">
            <div class="field"><label>세팅 이름</label><input type="text" id="sbName"></div>
            <div class="field"><label>방식 <span class="hint">(상대역·조립 규칙이 달라집니다)</span></label>
              <select id="sbMode">
                <option value="단독">단독 — 인물 1명</option>
                <option value="남녀">남녀 — 주인공 + 상대역(남자)</option>
                <option value="백합">백합 — 여×여</option></select></div>
            <div class="field"><label>단계명 <span class="hint">(콤마로 구분 · 세트당 씬 수)</span></label>
              <input type="text" id="sbStages" placeholder="시작, 중간, 끝"></div>
          </div>
          <div class="field"><label>계열 이름표 <span class="hint">(A=이름, B=이름 … 목록 머리글에 뜹니다)</span></label>
            <input type="text" id="sbCats" placeholder="A=바깥 계열, B=실내 계열"></div>

          <div class="sec" style="margin-top:8px;">
            <div class="sec-head" data-sbfold="sbRole"><span class="nm">상대역</span>
              <span class="sub">남녀·백합에서 쓰입니다</span></div>
            <div class="sec-body hidden" id="sbRole">
              <div class="grid2">
                <div class="field"><label>외형</label><textarea id="sbRoleLook" style="min-height:40px;"></textarea></div>
                <div class="field"><label>착의 <span class="hint">(백합)</span></label><textarea id="sbRoleWear" style="min-height:40px;"></textarea></div>
                <div class="field"><label>의상 <span class="hint">(남녀)</span></label><input type="text" id="sbRoleOutfit"></div>
                <div class="field"><label>네거티브</label><input type="text" id="sbRoleNeg"></div>
              </div>
            </div>
          </div>

          <div class="sec">
            <div class="sec-head" data-sbfold="sbAxes"><span class="nm">옵션 축</span>
              <span class="sub">고르는 값에 따라 프롬프트가 달라지는 축</span></div>
            <div class="sec-body hidden" id="sbAxes">
              <p class="hint"><b>적용</b> = 어디에 붙는지 (베이스·여자·남자·네거티브) ·
              <b>방식</b> = 어떻게 붙는지 —
              <b>고정</b>은 그대로, <b>계열별</b>은 씬의 계열(A·B…)에 따라, <b>단계별</b>은 단계 순서에 따라.</p>
              <div id="sbAxisList"></div>
              <div class="bar" style="margin-top:6px;"><button id="sbAxisAdd">+ 축 추가</button></div>
            </div>
          </div>

          <div class="sec">
            <div class="sec-head" data-sbfold="sbSets"><span class="nm">세트 추가</span>
              <span class="sub">단계명마다 씬 하나가 생깁니다</span></div>
            <div class="sec-body hidden" id="sbSets">
              <div class="grid3">
                <div class="field"><label>세트 이름</label><input type="text" id="sbSetLabel" placeholder="예: 카페"></div>
                <div class="field"><label>계열 <span class="hint">(비우면 없음)</span></label><input type="text" id="sbSetCat" placeholder="A"></div>
                <div class="field"><label>해상도</label><select id="sbSetRes"></select></div>
              </div>
              <div class="bar"><button class="primary" id="sbSetAdd">+ 세트 추가</button>
                <span class="hint">추가한 뒤 위 세팅 목록의 ✎ 로 씬 프롬프트를 채우세요</span></div>
            </div>
          </div>
          <div class="bar" style="margin-top:8px;">
            <button class="primary" id="sbSave">머리 정보 저장</button>
            <span class="n" id="sbMsg" style="margin-left:auto;"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="view" id="vBuilder" style="display:none;">
      <div class="card">
        <h2><span class="n">빌더</span>그림체와 캐릭터 만들기</h2>
        <p class="hint">수천 개 태그를 외우지 않아도 됩니다. 만들 대상을 먼저 고른 뒤 필요한 항목만 채우세요.
        결과는 원문을 줄이지 않고 파일과 라이브러리에 저장합니다.</p>
        <div class="builder-entry-grid">
          <div class="builder-entry">
            <span class="eyebrow">Style set</span><strong>🖼️ 그림체 한 세트</strong>
            <p>작가·구도·조명·화풍과 <b>네거티브·생성 설정값</b>을 한 묶음으로 보관합니다.</p>
            <button class="primary" id="bStyle">그림체 만들기</button>
          </div>
          <div class="builder-entry char">
            <span class="eyebrow">Character</span><strong>👤 캐릭터 한 명</strong>
            <p>정체·외형·머리·의상·원작과 다른 변형을 고릅니다. 저장 후 캐릭터 칸에 바로 넣을 수 있습니다.</p>
            <button class="primary" id="bChar">캐릭터 만들기</button>
          </div>
        </div>
        <div class="builder-tools">
          <span class="label">보조 도구</span>
          <button id="bCombo">🎨 작가 조합 고르기</button>
          <button id="bNorm">📋 기존 프롬프트 자동 분류</button>
        </div>
      </div>
      <div class="card">
        <h2><span class="n">검색</span>태그 사전</h2>
        <p class="hint">태그/ 폴더의 CSV에서 검색합니다. 클릭하면 복사돼요.</p>
        <div class="bar"><input type="text" data-tagq="char|" placeholder="🔍 태그 검색 (예: kimono, cowgirl, artist 이름)" style="flex:1;"></div>
        <div data-tagres="char|" class="tagres" style="max-height:220px;"></div>
      </div>
    </div>

    <div class="view" id="vLibrary" style="display:none;">
      <div id="studioLibraryNav" class="studio-subnav hidden" aria-label="자료 작업 선택">
        <div class="studio-subnav-copy">
          <span class="eyebrow">Library workspace</span>
          <strong>자료를 찾고 정리한 뒤, 같은 조건으로 비교합니다</strong>
        </div>
        <div class="studio-subnav-actions" role="tablist" aria-label="자료 작업">
          <button type="button" data-library-work="browse" role="tab">찾기·정리</button>
          <button type="button" data-library-work="compare" role="tab">비교·선별</button>
        </div>
      </div>
      <span id="studioCompareHome" hidden aria-hidden="true"></span>
      <div id="studioLibraryBrowse">
      <!-- 생성물 탐색기 — 선별 · 비교 · 가상 폴더. 파일은 옮기지 않는다 -->
      <div class="card">
        <h2><span class="n">생성물</span>탐색기 · 선별
          <span class="count" id="expCount" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">뽑아 둔 그림을 훑어보고 <b>고르는</b> 곳입니다. 그림을 누르면 크게 보이고,
        <b>←→</b> 로 넘기고 <b>F</b> 로 선별, <b>C</b> 로 비교함에 담고, <b>Esc</b> 로 닫습니다.
        폴더는 <b>이름표</b>일 뿐이라 원본 파일은 제자리에 그대로 둡니다.</p>
        <div class="filterbar">
          <button id="expUp" title="상위 폴더">⬆ 위로</button>
          <span class="n" id="expPath">output/</span>
          <label class="hint"><input type="checkbox" id="expOnlyPick"> 선별한 것만</label>
          <label class="hint"><input type="checkbox" id="expOnlyFav"> 즐겨찾기만</label>
          <select id="expSize"><option value="90">작게</option>
            <option value="130" selected>보통</option><option value="200">크게</option></select>
          <button id="expReload">새로고침</button>
        </div>
        <!-- ⚠ 한 줄에 `margin-left:auto` 를 **둘** 두지 말 것. `.bar .n{margin-left:auto}`
             에 더해 `expCompare` 에도 auto 가 붙어 있어서, 상태글이 줄 한복판에 뜨고
             단추가 좌우로 흩어져 무엇이 한 묶음인지 읽히지 않았다.
             지금은 auto 가 `expStat` 하나뿐이라 [고르는 도구들] … 상태 [지우기] 로 읽힌다.
             파괴적인 `선별 외 삭제` 는 상태글을 사이에 두고 **끝으로 떼어 놨다** — 없애지
             않았고 빨간색도 그대로다(경고는 유지해야 한다). 옆에 붙어 잘못 눌리는 것만 막는다. -->
        <div class="bar" style="margin-top:6px;">
          <button id="expCup" title="보이는 그림들을 1:1 로 붙여 순위를 매깁니다 (SDStudio 의 이미지 월드컵)">🏆 월드컵</button>
          <button id="expCompare">🔍 비교함 보기 (<span id="expCmpN">0</span>)</button>
          <button id="expCmpClear">비교함 비우기</button>
          <button id="expApplyPicked" title="이 폴더에서 선별한 비교 결과 한 장의 원문 설정을 생성 화면에 적용합니다">↳ 선별 1장 생성에 적용</button>
          <span class="n" id="expStat"></span>
          <button id="expDelUnpicked" class="danger" title="이 폴더에서 선별 안 된 것을 실제로 지웁니다">선별 외 삭제</button>
        </div>
        <div class="bar" style="margin-top:6px;flex-wrap:wrap;">
          <span class="tag">후보군</span>
          <select id="expGroupFilter" style="width:auto;min-width:150px;">
            <option value="">전체 보기</option>
          </select>
          <input type="text" id="expGroupName"
            placeholder="후보군 이름" style="width:150px;">
          <button id="expGroupSave">선별을 후보군에 추가</button>
          <button id="expGroupDelete">후보군 이름표 삭제</button>
          <span class="hint">원본 파일은 이동하지 않습니다.</span>
        </div>
        <div id="expDirs" class="bar" style="flex-wrap:wrap;margin-top:8px;"></div>
        <div id="expGrid" style="display:grid;gap:6px;margin-top:8px;
          grid-template-columns:repeat(auto-fill,minmax(var(--ecard,130px),1fr));"></div>
      </div>

      <!-- 그림체 복구 — 뽑아 둔 그림의 메타를 읽어 그 설정 그대로 다시 돌린다.
           탐색·선별과는 하는 일이 다르다(고르는 것이 아니라 **새로 뽑는다**. 결과도
           `output/복구/` 라는 다른 자리에 쌓이고 Anlas 도 든다). 한 카드 안에 있을 때는
           선별 도구 사이에 끼어 '이것도 고르는 기능인가' 로 읽혔다. 카드를 갈랐다. -->
      <div class="card">
        <h2><span class="n">복구</span>그림체 복구 — 그 설정 그대로 다시 뽑기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">결과는 output/복구/ 에</span></h2>
        <p class="hint">그림에 박힌 <b>프롬프트·시드·설정값</b>을 읽어 그대로 다시 돌립니다.
        메타가 지워진 그림(카톡·디스코드 경유, 메타 제거본)은 건너뜁니다.</p>
        <div class="filterbar">
          <select id="regenMode">
            <option value="generate">같은 설정으로 다시 뽑기 (시드까지 그대로)</option>
            <option value="img2img">원본을 바탕에 두고 다듬기 (img2img)</option>
          </select>
          <span class="hint" style="white-space:nowrap;">변화 강도</span>
          <input type="number" id="regenStrength" value="0.5" min="0.1" max="0.99" step="0.05" style="width:62px;">
          <button id="regenPicked">선별한 것 복구</button>
          <button id="regenAll">보이는 것 전부 복구</button>
        </div>
      </div>

      <div class="card">
        <h2><span class="n">자료팩</span>자료 넣기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">후보·태그·세팅·수집물을 한 번에</span></h2>
        <p class="hint">앱 본체에는 <b>후보사전·태그·세팅·수집 자료가 들어 있지 않습니다.</b>
        <b>기본자료팩.zip</b>, 개인 자료팩 또는 <b>그림체.json · 레시피.json · 작가통계.json</b>을
        여기에 넣으면 후보사전·규격·옵션·태그·세팅·수집물별 제자리로 정리됩니다.<br>
        <b>덮어쓰지 않고 없는 것만 더합니다</b> — 이미 갖고 있는 자료는 그대로 둡니다.
        같은 팩을 두 번 넣어도 안전합니다.</p>
        <div id="packDrop" class="drop" style="padding:18px;text-align:center;
          border:2px dashed var(--line);border-radius:var(--radius);cursor:pointer;">
          여기에 <b>자료팩.zip</b> 을 끌어다 놓거나 눌러서 고르세요
        </div>
        <input type="file" id="packFile" accept=".zip,.json" multiple style="display:none;">
        <label class="hint" style="display:flex;align-items:center;gap:6px;margin-top:8px;">
          <input type="checkbox" id="packOver" style="width:auto;flex:none;margin:0;">
          <span>같은 이름이면 <b>새 것으로 바꾸기</b> (기본은 갖고 있던 것을 지킵니다)</span>
        </label>
        <div id="packMsg" class="hint" style="margin-top:8px;"></div>
        <div id="packLog" style="margin-top:10px;"></div>
        <div class="bar" style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line);
          align-items:flex-start;">
          <div id="dataStorageStatus" class="hint" style="flex:1;min-width:0;">
            자료 저장 위치를 확인하는 중입니다.
          </div>
          <button type="button" id="dataIndexBuild">자료 색인 다시 만들기</button>
        </div>
        <p class="hint" style="margin-top:6px;">색인은 자료 파일의 경로·크기·SHA-256만 다시 세는
        파생 목록입니다. 원본을 옮기거나 지우지 않으며, 대용량 자료에서는 시간이 걸릴 수 있습니다.</p>
      </div>

      <div class="card">
        <h2><span class="n">검색</span>단부루에서 찾기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">태그·그림체를 실제 그림에서 가져오기</span></h2>
        <p class="hint">태그로 검색해서 마음에 드는 그림의 <b>태그를 그대로 가져오거나</b>,
        그 그림을 <b>바이브·캐릭터 레퍼런스로 등록</b>할 수 있습니다.
        NAI 로 만든 그림이면 <b>그림체까지</b> 뽑아옵니다.</p>
        <div class="filterbar">
          <input type="text" id="booruQ" placeholder="🔍 태그로 검색 (예: 1girl long_hair smile · 띄어쓰기로 여러 개)">
          <select id="booruSite">__BOORUS__</select>
          <select id="booruLimit"><option>20</option><option selected>40</option>
            <option>60</option><option>100</option></select>
          <select id="booruCard"><option value="small">작게</option>
            <option value="medium" selected>보통</option><option value="large">크게</option></select>
          <button id="booruGo" class="primary">검색</button>
          <button id="booruOpen" title="원본 사이트를 새 창으로">↗ 사이트에서 보기</button>
          <span class="n" id="booruStat"></span>
        </div>
        <div id="booruGrid" class="grid4"></div>
        <div class="bar"><button id="booruMore" style="flex:1;display:none;">다음 쪽 ▾</button></div>
      </div>
      <div class="card">
        <h2><span class="n">DB</span>캐릭터 · 그림체 라이브러리</h2>
        <p class="hint">캐릭터/ · 그림체/ 폴더의 파일 전부. 남이 만든 파일을 넣으면 여기 뜨고, 눌러서 내 것으로 가져올 수 있습니다.</p>
        <div class="filterbar">
          <input type="search" id="libFilter" placeholder="캐릭터·그림체 이름과 프롬프트 검색">
          <select id="libType" style="width:auto;">
            <option value="">전체 자료</option><option value="캐릭터">캐릭터</option>
            <option value="그림체">그림체</option>
          </select>
          <button id="libAddChar">+ 캐릭터 추가</button>
          <button id="libAddFolder">+ 폴더 추가</button>
          <span class="n" id="libCount" style="margin-left:auto;"></span>
        </div>
        <div id="libGrid" class="items" style="grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:7px;"></div>
        <div class="bar"><button type="button" id="libMore" style="flex:1;display:none;">더 보기 ▾</button></div>
      </div>
      <div class="card">
        <h2><span class="n">레시피</span>남들의 조합 <span class="n" id="recStat" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);"></span></h2>
        <p class="hint">도랑위키 등에서 모은 실제 사용 프롬프트입니다. 눌러서 태그·포지티브·네거티브를 보고 내 것으로 가져오세요.</p>
        <div class="bar">
          <input type="text" id="recQ" placeholder="🔍 레시피 검색 (예: 정상위, 작가, 역광)" style="flex:1;">
          <select id="recAxis" style="width:auto;"><option value="">전체 축</option></select>
        </div>
        <div id="recGrid" class="items" style="grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:9px;"></div>
        <div class="bar" style="margin-top:10px;"><button id="recMore" style="flex:1;">더 보기 ▾</button></div>
      </div>

      <div class="card">
        <h2><span class="n">편집</span>캐릭터 상세
          <button type="button" id="charUndo" class="hidden" style="margin-left:auto;">↶ 최근 삭제 되돌리기</button></h2>
        <p class="hint" id="charEditMsg">복제로 의상·예술적 변형을 나누고, 삭제한 항목은 이 화면을 닫기 전 되돌릴 수 있습니다.</p>
        <div class="filterbar">
          <input type="search" id="charFilter" placeholder="편집할 캐릭터 이름·프롬프트 검색">
          <span class="n" id="charCount" style="margin-left:auto;"></span>
        </div>
        <div id="charList"></div>
        <div class="bar"><button type="button" id="charMore" style="flex:1;display:none;">편집할 캐릭터 더 보기 ▾</button></div>
        <div id="folderList"></div>
      </div>
      </div>
    </div>

    <div class="view" id="vSystem" style="display:none;">
      <div class="card">
        <h2><span class="n">01</span>API</h2>
        <p class="hint">novelai.net → 설정(톱니바퀴) → Account → Get Persistent API Token</p>
        <div class="field"><label>NAI 토큰 (pst-...)</label><input type="text" id="token" placeholder="pst-..."></div>
        <hr style="border:0;border-top:1px solid var(--line);margin:14px 0 10px;">
        <label style="font-weight:600;">부루 계정 <span class="hint">— 자료 탭의 태그 검색에 씁니다 (선택)</span></label>
        <p class="hint" style="margin:4px 0 8px;">
          <b>겔부루</b>는 키가 없으면 아예 검색되지 않습니다.
          <b>단부루</b>는 안 넣어도 되지만 넣으면(골드 이상) 태그 2개 제한이 6개로 풀립니다.
          <b>e621</b>은 한국에서 지역 차단이라 키가 있어도 막힙니다.
        </p>
        <div class="grid2">
          <div class="field"><label>단부루 아이디</label><input type="text" id="bkDanUser" placeholder="로그인 이름"></div>
          <div class="field"><label>단부루 API Key</label><input type="password" id="bkDanKey" placeholder="My Account → API Key"></div>
          <div class="field"><label>겔부루 user_id</label><input type="text" id="bkGelUser" placeholder="숫자"></div>
          <div class="field"><label>겔부루 api_key</label><input type="password" id="bkGelKey" placeholder="Options → API Access Credentials"></div>
          <div class="field"><label>e621 아이디</label><input type="text" id="bkE6User" placeholder="로그인 이름"></div>
          <div class="field"><label>e621 API Key</label><input type="password" id="bkE6Key" placeholder="Manage API Access"></div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
          <button class="btn" id="bkTest">연결 확인</button>
          <span class="hint" id="bkMsg"></span>
        </div>
      </div>
      <div class="card">
        <h2><span class="n">02</span>화면 · 디자인</h2>
        <p class="hint">화면 구성과 색 테마·강조색·글씨 크기·모서리를 바꿀 수 있습니다. 즉시 반영되고 저장됩니다.</p>
        <div class="field"><label>화면 구성</label><div id="layoutChips"></div>
          <p class="hint" style="margin-top:5px;">작업실은 기능을 줄이지 않고 탭마다 필요한 작업면을 크게 씁니다. 익숙한 배치가 필요하면 기존 호환으로 돌아갈 수 있습니다.</p>
        </div>
        <div class="field"><label>테마</label><div id="themeChips"></div></div>
        <div class="grid3">
          <div class="field"><label>강조색</label><div id="accentChips"></div></div>
          <div class="field"><label>글씨 크기</label><div id="fsChips"></div></div>
          <div class="field"><label>모서리</label><div id="radiusChips"></div></div>
        </div>
        <div class="field" style="margin-top:8px;">
          <label>가중치 색으로 보기 <span class="hint">— 프롬프트 칸의 강조·약화를 색으로 표시</span></label>
          <select id="uiHighlight"><option value="off">끔 (선명한 원문)</option><option value="on">켬</option></select>
          <p class="hint" style="margin-top:5px;">
            <b style="background:rgba(190,70,70,.42);padding:0 3px;border-radius:3px;">2.0↑ 아주 강함</b>
            <b style="background:rgba(180,74,74,.30);padding:0 3px;border-radius:3px;">1.4~2.0</b>
            <b style="background:rgba(170,80,80,.20);padding:0 3px;border-radius:3px;">1.0~1.4</b>
            <b style="background:rgba(74,124,196,.22);padding:0 3px;border-radius:3px;">0.5~1.0 약함</b>
            <b style="background:rgba(64,108,196,.32);padding:0 3px;border-radius:3px;">0.5↓</b>
            <b style="background:rgba(48,96,204,.46);padding:0 3px;border-radius:3px;">음수 = 빼기</b></p>
          <p class="hint" style="margin-top:4px;">NAI 와 같은 규칙입니다 —
            <b>강조는 붉은색, 약화·음수는 파란색</b>.</p>
        </div>
      </div>

      <div class="card">
        <h2><span class="n">03</span>계정 여러 개 (프로필)
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">지금: __PROFNOW__</span></h2>
        <p class="hint">계정을 <b>따로 결제해서 두 대를 동시에</b> 돌릴 때 씁니다.
        프로필마다 <b>토큰·설정·진행상태·생성물</b>이 갈리고, 그림체·태그·후보사전·조각은 <b>함께</b> 씁니다.
        포트도 자동으로 갈립니다 (첫째 8787 · 둘째 8788 …).</p>
        <p class="hint"><b>쓰는 법</b> — 폴더의 <b>실행_둘째계정.bat</b> 을 더블클릭하면 둘째 프로필로 열립니다.
        직접 이름을 정하려면 명령창에서 <b>실행.bat --profile 이름</b>.
        프로필 데이터는 <b>프로필/&lt;이름&gt;/</b> 에 쌓입니다.</p>
        <p class="hint" style="color:var(--danger);">⚠ <b>같은 계정으로 두 대를 돌리지 마세요.</b>
        요청이 겹쳐 제한에 걸릴 위험이 커집니다. 프로필은 계정이 <b>다를 때</b> 쓰는 기능입니다.</p>
      </div>

      <div class="card" id="backupCard">
        <h2><span class="n">안전</span>내 자료 전체 백업</h2>
        <p class="hint">현재 프로필의 설정·선별과 공용 캐릭터·그림체·세팅·조각·자료 원문을
        manifest와 SHA-256 내용 검사로 한 ZIP에 묶습니다.
        <b>API 토큰·output 생성물·로그·원격 이미지 캐시는 넣지 않습니다.</b>
        복원할 때도 기존에만 있는 파일은 지우지 않으며, 먼저 변경 수를 보여 준 뒤 실행합니다.</p>
        <div class="bar" style="flex-wrap:wrap;">
          <button type="button" id="backupExport" class="primary">⬇ 내 자료 백업 만들기</button>
          <button type="button" id="backupChoose">⬆ 백업 파일 검사</button>
          <input type="file" id="backupFile" accept=".zip" style="display:none;">
          <button type="button" id="backupRestore" class="danger" disabled>검사한 백업 복원</button>
          <button type="button" id="backupRollback" class="hidden">↶ 방금 복원 되돌리기</button>
        </div>
        <div id="backupMsg" class="hint" style="margin-top:8px;"></div>
      </div>

      <div class="card" id="trashCard">
        <h2><span class="n">안전</span>생성물 휴지통
          <button type="button" id="trashRefresh" style="margin-left:auto;">↻ 새로고침</button></h2>
        <p class="hint">생성물 탐색기에서 치운 파일은 영구 삭제되지 않고 묶음별로 남습니다.
        앱을 다시 연 뒤에도 원하는 묶음을 복원할 수 있으며,
        <b>선별·즐겨찾기·후보군·순위·별점·판단 태그</b>도 함께 돌아옵니다.
        자동 만료와 영구 비우기는 하지 않습니다.</p>
        <div id="trashList" class="hint">휴지통을 확인하는 중입니다.</div>
      </div>

      <div class="card" id="localImageCard">
        <h2><span class="n">안전</span>자료 이미지 무결성</h2>
        <p class="hint">그림체·레시피 JSON의 <code>local:</code> 참조와 실제 이미지 바이트를 맞춰 봅니다.
        과거 판의 파일명 해시가 현재 WebP 바이트와 다른 것은 곧바로 손상으로 판정하지 않습니다.
        <b>파일 누락과 실제 이미지 열기 실패를 따로 검사</b>하며, 미사용 후보는 자동 삭제하지 않습니다.</p>
        <div class="bar" style="flex-wrap:wrap;">
          <button type="button" id="localImageScan" class="primary">이미지 검사</button>
          <button type="button" id="localImageNormalize" disabled>참조 이름 안전 정리</button>
          <button type="button" id="localImageRollback" class="hidden">↶ 방금 정리 되돌리기</button>
        </div>
        <div id="localImageMsg" class="hint" style="margin-top:8px;"></div>
      </div>

      <div class="card">
        <h2><span class="n">04</span>알림 · 단축키
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">565장은 몇 시간이 걸립니다</span></h2>
        <div class="bar" style="flex-wrap:wrap;">
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="notifySound"> 다 끝나면 소리로 알리기</label>
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="notifySystem"> 시스템 알림 띄우기</label>
          <button id="notifyTest">지금 시험해 보기</button>
          <span class="n" id="notifyMsg"></span>
        </div>
        <p class="hint" style="margin-top:8px;"><b>단축키</b> —
          <b>Alt+1~5</b> 탭 이동 ·
          생성물 탐색기에서 그림을 열면 <b>←→</b> 넘기기 · <b>F</b> 선별 · <b>S</b> 즐겨찾기 ·
          <b>C</b> 비교함 · <b>Esc</b> 닫기</p>
      </div>

      <!-- 진단 — 무엇이 왜 실패했는지 앱 안에서 본다 (nais_blue 의 DiagnosticDrawer) -->
      <div class="card">
        <h2><span class="n">04b</span>진단 · 최근 기록
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">생성.log 를 앱 안에서</span></h2>
        <p class="hint">실패 원인을 파일을 찾아 열지 않고 시간·심각도·종류별로 봅니다.
        토큰·서명·사용자 홈 경로는 서버에서 지운 뒤 표시합니다. <b>오류만</b>을 켜면 경고·오류만 남습니다.</p>
        <div class="bar" style="flex-wrap:wrap;">
          <button id="diagLoad">↻ 불러오기</button>
          <label class="hint"><input type="checkbox" id="diagErrOnly"> 오류만</label>
          <select id="diagN" title="줄 수"><option>100</option><option selected>300</option><option>1000</option></select>
          <button id="diagCopy">📋 복사</button>
          <button id="diagExport">⬇ 안전 JSON</button>
          <span class="n" id="diagStat" style="margin-left:auto;"></span>
        </div>
        <pre id="diagOut" style="max-height:260px;overflow:auto;background:var(--bg);padding:8px;
          font-size:var(--fs-2xs);line-height:1.45;white-space:pre-wrap;word-break:break-all;margin:6px 0 0;"></pre>
      </div>

      <div class="card">
        <h2><span class="n">05</span>모자이크 칠하기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">내 컴퓨터에서 · Anlas 안 듦</span></h2>
        <p class="hint">가릴 곳을 붓으로 칠하면 그 부분만 모자이크로 바꿉니다. NAI 를 거치지 않아 <b>공짜</b>입니다.
        결과는 <b>output/모자이크/</b> 에 저장됩니다.</p>
        <div id="mosDrop" class="row" style="text-align:center;padding:16px 14px;border-style:dashed;cursor:pointer;">
          <b>🟦 가릴 그림을 여기에 놓거나 눌러서 고르세요</b>
          <input type="file" id="mosFile" accept="image/png,image/webp" style="display:none;">
        </div>
        <div id="mosStage" class="hidden" style="margin-top:8px;">
          <canvas id="mosCanvas" style="max-width:100%;display:block;border:1px solid var(--line);
            border-radius:var(--radius);cursor:crosshair;"></canvas>
          <div class="filterbar" style="margin-top:8px;">
            <span class="hint" style="white-space:nowrap;">붓 굵기</span>
            <input type="range" id="mosBrush" min="16" max="200" step="4" value="72" style="width:120px;">
            <span class="hint" style="white-space:nowrap;">모자이크 크기</span>
            <input type="range" id="mosBlock" min="4" max="48" step="2" value="16" style="width:120px;">
            <span class="n" id="mosBlockN">16px</span>
            <button id="mosReset">처음으로</button>
            <button class="primary" id="mosSave">저장</button>
          </div>
          <p class="hint" id="mosMsg"></p>
        </div>
      </div>

      <div class="card">
        <h2><span class="n">06</span>밴 예방 · 속도 <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">쉬는 자리는 장과 장 사이입니다</span></h2>
        <p class="hint">한꺼번에 몰아치면 NAI 가 요청을 막습니다. 장 사이에 쉬고, 일정 장수마다 길게 쉽니다.
        <b>생성 도중에는 절대 끊지 않습니다</b> — 항상 한 장을 끝낸 뒤에 쉽니다.</p>
        <div class="grid3">
          <div class="field"><label>장 사이 간격 — 최소 (초)</label>
            <input type="number" id="paceDmin" step="0.5" min="0" max="120"></div>
          <div class="field"><label>장 사이 간격 — 최대 (초)</label>
            <input type="number" id="paceDmax" step="0.5" min="0" max="300"></div>
          <div class="field"><label>일일 상한 (장)</label>
            <input type="number" id="paceDaily" step="100" min="1" max="100000"></div>
          <div class="field"><label>짧게 쉬기 — 몇 장마다 (0=안 함)</label>
            <input type="number" id="paceSoftEvery" step="10" min="0" max="100000"></div>
          <div class="field"><label>짧게 쉬기 — 몇 초</label>
            <input type="number" id="paceSoftSec" step="5" min="1" max="3600"></div>
          <div class="field"><label>길게 쉬기 — 몇 장마다 (0=안 함)</label>
            <input type="number" id="paceCoolEvery" step="100" min="0" max="100000"></div>
          <div class="field"><label>길게 쉬기 — 몇 초</label>
            <input type="number" id="paceCoolSec" step="30" min="1" max="7200"></div>
        </div>
        <p class="hint" id="paceCalc"></p>
      </div>

      <div class="card">
        <h2><span class="n">07</span>메타데이터 제거 <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">남에게 줄 사본 만들기</span></h2>
        <p class="hint">NAI 그림에는 프롬프트가 <b>두 군데</b> 들어 있습니다 —
        파일 정보(EXIF·PNG 텍스트)와 <b>알파 채널에 숨은 스텔스</b>. 앞엣것만 지우면
        novelai.net/inspect 로 뒤엣것이 그대로 읽힙니다. 여기서는 <b>둘 다</b> 지웁니다.
        원본은 그대로 두고 <b>output/메타제거/</b> 에 사본을 만듭니다.</p>
        <div id="stripDrop" class="row" style="text-align:center;padding:20px 14px;border-style:dashed;cursor:pointer;">
          <b>🧹 메타를 지울 그림을 여기에 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">PNG / WebP · 여러 장 가능 · 투명 그림은 PNG 로, 나머지는 WebP 로 나옵니다</div>
          <input type="file" id="stripFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
        <div class="filterbar" style="margin-top:8px;">
          <span class="hint" style="white-space:nowrap;">경량화 — 긴 변</span>
          <select id="stripSide">
            <option value="0" selected>그대로</option><option value="1536">1536px</option>
            <option value="1024">1024px</option><option value="768">768px</option>
            <option value="512">512px</option></select>
          <span class="hint" style="white-space:nowrap;">품질</span>
          <input type="number" id="stripQ" value="95" min="40" max="100" step="5" style="width:60px;">
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="stripWebp"> 투명 그림도 WebP 로 (더 작게)</label>
        </div>
        <div class="bar" style="margin-top:6px;"><span class="n" id="stripMsg"></span></div>
      </div>

      <div class="card">
        <h2><span class="n">08</span>파일 구조</h2>
        <p class="hint">
        <b>세팅/</b> 씬 세트 · <b>캐릭터/</b> 캐릭터 DB · <b>그림체/</b> 베이스 프리셋 · <b>태그/</b> 태그 사전 CSV<br>
        <b>규격.json</b> 분류 원리 · <b>후보사전.json</b> 빌더 슬롯/후보 · <b>씬프리셋/</b> 조합 저장 · <b>설정.json</b> 현재 상태</p>
      </div>
    </div>
  </div>

  <!-- ══ 오른쪽: 히스토리 ══ -->
  <div class="right">
    <div class="hist-t">최근 생성</div>
    <div class="hist-g" id="hist"></div>
  </div>
</div>

<div class="modal-bg" id="modalBg" style="display:none;">
  <div class="modal">
    <h3 id="modalTitle"></h3>
    <div id="modalBody"></div>
    <div class="bar" style="margin-top:12px;">
      <button class="primary" id="modalSave">저장</button>
      <button id="modalClose">닫기</button>
      <span class="flash" id="modalFlash"></span>
    </div>
  </div>
</div>
<script>
function showFatalError(reason){
  const message = reason && (reason.message || reason.stack || String(reason));
  let bar = document.getElementById('fatalErrorBar');
  if(!bar){
    bar = document.createElement('div');
    bar.id = 'fatalErrorBar';
    bar.setAttribute('role', 'alert');
    bar.style.cssText = 'position:fixed;z-index:99999;left:12px;right:12px;top:12px;'
      + 'padding:12px 14px;border:2px solid #b42318;border-radius:10px;background:#fff1f0;'
      + 'color:#7a271a;font:14px/1.45 system-ui;box-shadow:0 6px 24px #0004';
    const title = document.createElement('strong');
    title.textContent = '화면 실행 중 오류가 발생했습니다.';
    const detail = document.createElement('div');
    detail.id = 'fatalErrorDetail';
    detail.style.cssText = 'margin-top:4px;white-space:pre-wrap;word-break:break-word';
    const reload = document.createElement('button');
    reload.type = 'button';
    reload.textContent = '새로고침';
    reload.style.cssText = 'margin-top:8px;padding:5px 10px;cursor:pointer';
    reload.addEventListener('click', () => location.reload());
    bar.append(title, detail, reload);
    (document.body || document.documentElement).appendChild(bar);
  }
  const detail = document.getElementById('fatalErrorDetail');
  if(detail) detail.textContent = (message || '알 수 없는 오류') + '\n생성.log의 마지막 오류도 함께 확인해 주세요.';
}
window.addEventListener('error', event => showFatalError(event.error || event.message));
window.addEventListener('unhandledrejection', event => showFatalError(event.reason));

let STATE = null, SAVED_STATE = null, SETTINGS = [], STYLES = [], SPEC = {}, BUILDER = {}, SCENE_PRESETS = [], HIST = [];
let FRAGS = {};
const RES_PRESETS = __RESJSON__;   // 해상도 프리셋 (파이썬 RESOLUTIONS 와 같은 목록)

function genId(){ return Math.random().toString(36).slice(2,10); }
function esc(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function escA(s){ return esc(s).replace(/"/g,'&quot;'); }
function $(id){ return document.getElementById(id); }

function showStartupRecovery(notice){
  const bar = $('startupRecovery');
  if(!bar || !notice) return;
  bar.style.display = 'flex';
  $('startupRecoveryDetail').textContent =
    `원본 ${Number((notice.files||[]).length).toLocaleString()}개를 ${notice.folder || '복구보관 폴더'}에 보존했습니다.`
    + ' 아무 자료도 영구 삭제하지 않았습니다.';
  $('startupRecoveryClose').addEventListener('click', () => bar.style.display = 'none');
  $('startupRecoveryBackup').addEventListener('click', () => {
    bar.style.display = 'none';
    setMode('system');
    setTimeout(() => $('backupCard') && $('backupCard').scrollIntoView({behavior:'smooth'}), 0);
  });
}

async function init(){
  const d = await (await fetch('/api/config')).json();
  STATE = d.config;
  SAVED_STATE = JSON.parse(JSON.stringify(STATE));
  SETTINGS = d.settings || [];
  STYLES = d.styles || [];
  SPEC = d.spec || {};
  BUILDER = d.builder || {};
  SCENE_PRESETS = d.scene_presets || [];
  FRAGS = d.fragments || {};
  CLASHES = d.scene_clashes || {};
  SCENES = d.scenes || [];
  showStartupRecovery(d.startup_recovery);
  paint();
  bindTagSearch(document);
}

/* 세팅 파일이 디스크에서 바뀐 뒤 목록만 다시 받는다.
   STATE 는 건드리지 않는다 — 저장 안 된 편집이 날아가면 안 된다. */
async function reloadConfig(){
  const d = await (await fetch('/api/config')).json();
  SETTINGS = d.settings || [];
  CLASHES = d.scene_clashes || {};
  renderSettings(); tokens(); counts(); sbPickList(); paintClash();
  if($('setThumbs') && $('setThumbs').checked) loadSetThumbs();
}

function paint(){
  $('basePrompt').value = STATE.base_prompt || '';
  $('negPrompt').value = STATE.negative_prompt || '';
  $('token').value = STATE.token || '';
  const BK = [['bkDanUser','danbooru','user'],['bkDanKey','danbooru','key'],['bkGelUser','gelbooru','user'],['bkGelKey','gelbooru','key'],['bkE6User','e621','user'],['bkE6Key','e621','key']];
  BK.forEach(([id, site, f]) => { const e=$(id); if(e) e.value = ((STATE.booru_keys||{})[site]||{})[f] || ''; });
  $('pScale').value = STATE.cfg_scale ?? 5.5;
  $('pRescale').value = STATE.cfg_rescale ?? 0.56;
  $('pSteps').value = STATE.steps ?? 28;
  $('pSeed').value = STATE.seed ?? 1;
  $('pNaiSeed').value = STATE.nai_seed ?? 0;
  $('pSampler').value = STATE.sampler || 'k_euler_ancestral';
  $('pSched').value = STATE.scheduler || 'karras';
  $('pVariety').value = STATE.variety ? 'on' : 'off';
  paintParams();
  renderPresets(); renderSlots(); renderSettings(); renderLibrary(); renderScenePresets();
  bindComparison(); bindUserBackup(); bindTrashCenter(); bindLocalImageIntegrity();
  renderFrags(); renderScenes(); applySplit3(); paintPace(); acScan(document);
  sbPickList(); paintClash();
  if($('expGrid')) expLoad('');
  bindWelcome(); refreshWelcome();
  setupHL(); bindHLToggle(); bindDirector(); bindRefs(); bindUseCoords(); bindBooru();
  if(!$('anlasBal')._bound){
    $('anlasBal')._bound = true;
    $('anlasBal').addEventListener('click', () => anlasRefresh(true));
    ['qty','qtyM','qtyP'].forEach(id => $(id) &&
      $(id).addEventListener('click', () => anlasRefresh(false)));
    $('qty').addEventListener('input', () => anlasRefresh(false));
  }
  anlasRefresh(false);
  /* 레시피 6,388건은 자료 탭에서 그 영역을 실제로 볼 때 읽는다.
     첫 화면에서 미리 읽고 이미지 60장을 예열하면, 사용자가 먼저 누른
     작가 조합 빌더와 디스크·네트워크 작업이 겹쳐 화면이 멈춘다. */
  bindRecipes();
  applyUI(); renderUIChips();
  if($('notifySound')) $('notifySound').checked = !!(STATE.ui||{}).notify_sound;
  if($('notifySystem')) $('notifySystem').checked = !!(STATE.ui||{}).notify_system;
  tokens();
}

/* ── 자료 비교 생성 ───────────────────────────────────────────────────
   그림체 전체 / 캐릭터 전체 / 직교 조합을 같은 크기·시드로 한 장씩 본다.
   실제 장수는 서버가 자료 파일을 다시 세어 확정하며, 확인한 수와 달라지면 시작을 거부한다. */
let CMP_PLAN = null, CMP_TIMER = null, CMP_RUNS = [];
function comparisonRead(){
  const mode = (document.querySelector('input[name="cmpMode"]:checked') || {}).value || 'styles';
  let w = Number($('cmpW').value) || Number(STATE.width) || 832;
  let h = Number($('cmpH').value) || Number(STATE.height) || 1216;
  if($('cmpRes').value !== 'custom'){
    const parts = $('cmpRes').value.split('x').map(Number);
    if(parts.length === 2 && parts.every(Number.isFinite)){ w = parts[0]; h = parts[1]; }
  }
  return {
    mode,
    fixed_size: $('cmpFix').checked,
    width: w, height: h,
    same_seed: $('cmpSameSeed').checked,
    seed: Math.max(0, Math.trunc(Number($('cmpSeed').value) || 0)),
    seed_count: Math.max(1, Math.min(4,
      Math.trunc(Number($('cmpSeedCount').value) || 1))),
    limit: Math.max(0, Math.trunc(Number($('cmpLimit').value) || 0)),
    include_refs: $('cmpRefs').checked
  };
}
function comparisonStore(opts){
  STATE.ui = STATE.ui || {};
  STATE.ui.comparison = Object.assign({}, opts);
  save();
}
function comparisonApply(saved){
  saved = saved || {};
  const mode = ['styles','characters','both'].includes(saved.mode) ? saved.mode : 'styles';
  const radio = document.querySelector(`input[name="cmpMode"][value="${mode}"]`);
  if(radio) radio.checked = true;
  const w = Number(saved.width || STATE.width || 832);
  const h = Number(saved.height || STATE.height || 1216);
  const res = `${w}x${h}`;
  $('cmpRes').value = [...$('cmpRes').options].some(o => o.value === res) ? res : 'custom';
  $('cmpW').value = w; $('cmpH').value = h;
  $('cmpFix').checked = saved.fixed_size !== false;
  $('cmpSameSeed').checked = saved.same_seed !== false;
  $('cmpSeed').value = Number(saved.seed) || 0;
  $('cmpSeedCount').value = String(Math.max(1, Math.min(4,
    Math.trunc(Number(saved.seed_count) || 1))));
  $('cmpLimit').value = Number(saved.limit) || 0;
  $('cmpRefs').checked = saved.include_refs === true;
  comparisonPaintControls();
}
function comparisonRestore(){
  comparisonApply(((STATE.ui || {}).comparison) || {});
}
function comparisonPaintControls(){
  const custom = $('cmpRes').value === 'custom';
  $('cmpCustom').classList.toggle('hidden', !custom);
  $('cmpRes').disabled = !$('cmpFix').checked;
  $('cmpW').disabled = !$('cmpFix').checked;
  $('cmpH').disabled = !$('cmpFix').checked;
}
function comparisonRunSelected(){
  const folder = ($('cmpRuns') || {}).value || '';
  return CMP_RUNS.find(x => x.folder === folder) || null;
}
async function comparisonRunsLoad(){
  const select = $('cmpRuns'); if(!select) return;
  select.innerHTML = '<option value="">실험 기록을 불러오는 중...</option>';
  try{
    const r = await (await fetch('/api/compare_runs')).json();
    if(!r.ok) throw new Error(r.error || '실험 기록을 읽지 못했습니다.');
    CMP_RUNS = r.runs || [];
    if(!CMP_RUNS.length){
      select.innerHTML = '<option value="">아직 비교 실험이 없습니다.</option>';
      $('cmpRunMsg').textContent = '비교 생성이 시작되면 각 결과 폴더의 기록이 여기에 남습니다.';
      return;
    }
    const statusName = {
      complete:'완료', stopped:'중지', daily_limit:'일일 상한',
      partial:'일부 실패', fatal:'오류', running:'진행 기록'
    };
    select.innerHTML = CMP_RUNS.map((run, i) => {
      const state = statusName[run.status] || run.status || '상태 미상';
      const date = run.updated_at ? ` · ${run.updated_at}` : '';
      return `<option value="${escA(run.folder)}"${i===0?' selected':''}>`
        + `${esc(run.mode_label || run.name)} · ${state} · `
        + `${Number(run.completed||0).toLocaleString()}/${Number(run.total||0).toLocaleString()}장`
        + `${esc(date)}</option>`;
    }).join('');
    $('cmpRunMsg').textContent =
      '중단된 실험은 계획을 불러온 뒤 현재 자료 수·비용을 다시 확인하면 이어집니다.';
  }catch(e){
    CMP_RUNS = [];
    select.innerHTML = '<option value="">실험 기록을 읽지 못했습니다.</option>';
    $('cmpRunMsg').textContent = String(e);
  }
}
async function openComparisonFolder(folder, message='비교 결과를 선별하세요.'){
  if(!folder) return;
  STATE.ui = STATE.ui || {};
  STATE.ui.library_work = 'browse';
  setMode('library');
  arrangeStudioWorkspace();
  await expLoad(folder);
  $('expStat').textContent = message;
  $('expGrid').scrollIntoView({behavior:'smooth', block:'start'});
}
async function comparisonPreview(){
  const opts = comparisonRead();
  comparisonStore(opts);
  CMP_PLAN = null;
  $('cmpConfirm').checked = false;
  $('cmpStart').disabled = true;
  $('cmpSummary').textContent = '자료 수와 생성 장수를 계산하는 중입니다.';
  try{
    const r = await (await fetch('/api/compare_preview', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(opts)})).json();
    CMP_PLAN = r;
    $('cmpCounts').textContent = `그림체 ${Number(r.styles||0).toLocaleString()} · 캐릭터 ${Number(r.characters||0).toLocaleString()}`;
    if(!r.ok){
      $('cmpSummary').innerHTML = `<span style="color:var(--danger)">${esc((r.errors||[r.error||'계산 실패']).join(' '))}</span>`;
      return;
    }
    let formula = '';
    if(opts.mode === 'styles'){
      formula = `그림체 ${r.styles.toLocaleString()}개 × 현재 캐릭터 묶음 1개`
        + ` (${r.current_slots.toLocaleString()}명 함께)`;
    }else if(opts.mode === 'characters'){
      formula = `현재 그림체 1개 × 캐릭터 ${r.characters.toLocaleString()}개`;
    }else{
      formula = `그림체 ${r.styles.toLocaleString()}개 × 캐릭터 ${r.characters.toLocaleString()}개`;
    }
    if(Number(r.seed_count || 1) > 1){
      formula += ` × 시드 ${Number(r.seed_count).toLocaleString()}개`;
    }
    const cap = r.limited ? ` · 전체 ${r.total.toLocaleString()}장 중 앞 ${r.count.toLocaleString()}장` : '';
    let cost = '';
    if(r.subscription_known){
      cost = ` · 현재 구독 기준 예상 ${Number(r.expected_anlas||0).toLocaleString()} Anlas`;
    }else{
      cost = ` · 예상 범위 ${Number(r.opus_anlas||0).toLocaleString()}~${Number(r.paid_anlas_max||0).toLocaleString()} Anlas`
        + ' (구독 확인 전)';
    }
    const free = r.free_eligible === r.count
      ? ' · 전부 Opus 무료 크기·스텝 범위'
      : ` · 무료 조건 범위 ${Number(r.free_eligible||0).toLocaleString()}/${r.count.toLocaleString()}장`;
    const ref = opts.include_refs ? ' · 레퍼런스 포함(추가 과금 가능)' : ' · 레퍼런스 제외';
    $('cmpSummary').innerHTML = `<b>${esc(formula)} = ${r.count.toLocaleString()}장</b>${esc(cap + cost + free + ref)}
      <div class="hint" style="margin-top:4px;">중지하거나 일일 상한에 닿아도 같은 계획으로 다시 누르면 이어집니다.
      그림체 원본 시드는 쓰지 않고 비교 시드 규칙을 적용합니다.</div>`;
    $('cmpConfirmText').textContent = `${r.count.toLocaleString()}번의 순차 API 호출과 저장을 확인했습니다.`;
    $('cmpStart').disabled = !$('cmpConfirm').checked;
  }catch(e){
    $('cmpSummary').textContent = '계산 실패: ' + e;
  }
}
function comparisonSchedule(){
  comparisonPaintControls();
  clearTimeout(CMP_TIMER);
  CMP_TIMER = setTimeout(comparisonPreview, 180);
}
function bindComparison(){
  if(!$('compareCard') || $('compareCard')._bound) return;
  $('compareCard')._bound = true;
  comparisonRestore();
  document.querySelectorAll('input[name="cmpMode"]').forEach(x => x.addEventListener('change', comparisonSchedule));
  ['cmpRes','cmpFix','cmpSameSeed','cmpSeed','cmpSeedCount',
   'cmpLimit','cmpRefs','cmpW','cmpH'].forEach(id => {
    const el = $(id); if(!el) return;
    el.addEventListener('change', comparisonSchedule);
    if(['cmpSeed','cmpLimit','cmpW','cmpH'].includes(id)) el.addEventListener('input', comparisonSchedule);
  });
  $('cmpConfirm').addEventListener('change', () => {
    $('cmpStart').disabled = !(CMP_PLAN && CMP_PLAN.ok && CMP_PLAN.count && $('cmpConfirm').checked);
  });
  $('cmpRunRefresh').addEventListener('click', comparisonRunsLoad);
  $('cmpRunOpen').addEventListener('click', async () => {
    const run = comparisonRunSelected();
    if(!run){ $('cmpRunMsg').textContent = '열 비교 실험을 선택해주세요.'; return; }
    await openComparisonFolder(
      run.folder,
      `${run.mode_label || run.name} · ${Number(run.completed||0).toLocaleString()}/${Number(run.total||0).toLocaleString()}장`,
    );
  });
  $('cmpRunLoad').addEventListener('click', async () => {
    const run = comparisonRunSelected();
    if(!run){ $('cmpRunMsg').textContent = '불러올 비교 실험을 선택해주세요.'; return; }
    const r = await (await fetch('/api/compare_activate', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({folder:run.folder})})).json();
    if(!r.ok){ $('cmpRunMsg').textContent = r.error || '계획을 불러오지 못했습니다.'; return; }
    comparisonApply(r.options || {});
    $('cmpRunMsg').textContent = r.resumable
      ? `중단 지점 ${Number(r.completed||0).toLocaleString()}/${Number(r.total||0).toLocaleString()}장을 활성화했습니다. 아래 장수와 비용을 다시 확인해주세요.`
      : '완료된 실험의 조건을 새 계획으로 불러왔습니다. 기존 결과는 덮어쓰지 않습니다.';
    comparisonSchedule();
  });
  $('cmpOpenResults').addEventListener('click', async () => {
    const r = await (await fetch('/api/compare_progress')).json();
    if(!r.ok){
      $('cmpSummary').textContent = r.error || '아직 선별할 비교 결과가 없습니다.';
      return;
    }
    const done = Number(r.completed || 0).toLocaleString();
    const total = Number(r.total || 0).toLocaleString();
    await openComparisonFolder(
      r.folder, `최근 비교 결과 ${done}/${total}장 · 선별을 시작하세요.`);
  });
  $('cmpStart').addEventListener('click', async () => {
    if(!(CMP_PLAN && CMP_PLAN.ok && $('cmpConfirm').checked)) return;
    const opts = comparisonRead();
    $('cmpStart').disabled = true;
    const r = await (await fetch('/api/compare_run', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Object.assign(opts, {
        confirmed:true, confirmed_count:CMP_PLAN.count
      }))})).json();
    if(!r.ok){
      alert(r.error || '비교 생성을 시작하지 못했습니다.');
      comparisonSchedule();
      return;
    }
    setMode('preview');
  });
  comparisonRunsLoad();
  comparisonPreview();
}

/* ── 내 자료 전체 백업 ─────────────────────────────────────────────── */
let BACKUP_FILE = null, BACKUP_SHA = '', BACKUP_BATCH = '';
function bindUserBackup(){
  if(!$('backupCard') || $('backupCard')._bound) return;
  $('backupCard')._bound = true;
  BACKUP_BATCH = sessionStorage.getItem('naisBackupRollback') || '';
  if(BACKUP_BATCH){
    $('backupRollback').classList.remove('hidden');
    $('backupMsg').textContent = '방금 복원한 자료가 적용되었습니다. 문제가 있으면 복원 전 상태로 되돌릴 수 있습니다.';
  }
  $('backupExport').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = '/api/backup_export';
    a.download = 'NAI배치생성기-내자료백업.zip';
    document.body.appendChild(a); a.click(); a.remove();
    $('backupMsg').textContent = '백업 ZIP을 만드는 중입니다. 다운로드가 시작될 때까지 기다려주세요.';
  });
  $('backupChoose').addEventListener('click', () => $('backupFile').click());
  $('backupFile').addEventListener('change', async () => {
    const file = $('backupFile').files[0];
    $('backupFile').value = '';
    if(!file) return;
    BACKUP_FILE = file; BACKUP_SHA = '';
    $('backupRestore').disabled = true;
    $('backupMsg').textContent = '백업의 경로·크기·내용 해시를 검사하는 중입니다.';
    try{
      const r = await (await fetch('/api/backup_preview', {method:'POST',
        headers:{'X-Filename':encodeURIComponent(file.name)},
        body:await file.arrayBuffer()})).json();
      if(!r.ok){ $('backupMsg').textContent = r.error || '백업 검사 실패'; return; }
      BACKUP_SHA = r.sha256;
      const c = r.counts || {};
      $('backupMsg').innerHTML =
        `<b>${Number(r.files||0).toLocaleString()}개 · ${(Number(r.bytes||0)/1048576).toFixed(1)}MB</b>`
        + ` — 새 파일 ${Number(c['새 파일']||0).toLocaleString()} · 바뀔 파일 ${Number(c['바뀔 파일']||0).toLocaleString()}`
        + ` · 같은 파일 ${Number(c['같은 파일']||0).toLocaleString()}`
        + `<br>백업 시점 ${esc(r.created_at||'?')} · 토큰·생성물·원격 캐시는 복원하지 않습니다.`;
      $('backupRestore').disabled = false;
    }catch(e){ $('backupMsg').textContent = '백업 검사 실패: ' + e; }
  });
  $('backupRestore').addEventListener('click', async () => {
    if(!BACKUP_FILE || !BACKUP_SHA) return;
    if(!confirm('검사한 백업으로 같은 이름의 자료를 바꿀까요?\\n현재 파일은 복원 기록에 보존되며 바로 되돌릴 수 있습니다.')) return;
    $('backupRestore').disabled = true;
    $('backupMsg').textContent = '기존 파일을 복원 기록에 보존한 뒤 적용하는 중입니다.';
    try{
      const r = await (await fetch('/api/backup_restore', {method:'POST',
        headers:{'X-Backup-SHA256':BACKUP_SHA}, body:await BACKUP_FILE.arrayBuffer()})).json();
      if(!r.ok){ $('backupMsg').textContent = r.error || '복원 실패'; $('backupRestore').disabled=false; return; }
      BACKUP_BATCH = r.batch || '';
      if(BACKUP_BATCH) sessionStorage.setItem('naisBackupRollback', BACKUP_BATCH);
      $('backupMsg').textContent = `${r.changed}개 파일 복원 완료 · 토큰과 출력 폴더 설정은 현재 값을 유지했습니다. 화면을 안전하게 다시 불러옵니다.`;
      $('backupRollback').classList.toggle('hidden', !BACKUP_BATCH);
      setTimeout(() => location.reload(), 700);
    }catch(e){ $('backupMsg').textContent = '복원 실패: ' + e; $('backupRestore').disabled=false; }
  });
  $('backupRollback').addEventListener('click', async () => {
    if(!BACKUP_BATCH) return;
    const r = await (await fetch('/api/backup_rollback', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:BACKUP_BATCH})})).json();
    const skipped = Number(r.skipped || 0);
    $('backupMsg').textContent = r.ok
      ? `${r.restored}개 파일을 복원 전 상태로 되돌렸습니다.`
        + (skipped ? ` 복원 뒤 다시 바뀐 ${skipped}개 파일은 덮어쓰지 않았습니다.` : '')
      : (r.error || '되돌리기 실패');
    if(r.ok){
      BACKUP_BATCH='';
      sessionStorage.removeItem('naisBackupRollback');
      $('backupRollback').classList.add('hidden');
      setTimeout(() => location.reload(), 700);
    }
  });
}

/* ── 생성물 휴지통 센터 ───────────────────────────────────────────── */
async function trashCenterLoad(){
  const box = $('trashList');
  if(!box) return;
  box.textContent = '휴지통 묶음을 확인하는 중입니다.';
  try{
    const r = await (await fetch('/api/trash', {cache:'no-store'})).json();
    if(!r.ok){ box.textContent = r.error || '휴지통 확인 실패'; return; }
    const rows = r.batches || [];
    if(!rows.length){
      box.innerHTML = '<span class="n">휴지통이 비어 있습니다.</span>';
      return;
    }
    box.innerHTML = `<div class="bar" style="margin-bottom:7px;">
      <b>${Number(r.total_files||0).toLocaleString()}개 복원 가능</b>
      <span>${(Number(r.total_bytes||0)/1048576).toFixed(1)}MB</span></div>`
      + rows.map(row => `<div class="row" style="display:flex;align-items:center;gap:8px;">
        <div style="flex:1;min-width:0;"><b>${esc(row.created_at || row.batch_id)}</b>
          <div class="hint">${Number(row.available||0).toLocaleString()} / ${Number(row.total||0).toLocaleString()}개 남음
          · ${(Number(row.bytes||0)/1048576).toFixed(1)}MB</div></div>
        <button type="button" data-trash-restore="${escA(row.batch_id)}"
          ${Number(row.available||0) ? '' : 'disabled'}>↶ 이 묶음 복원</button></div>`).join('');
  }catch(e){
    box.textContent = '휴지통 확인 실패: ' + e;
  }
}
function bindTrashCenter(){
  if(!$('trashCard') || $('trashCard')._bound) return;
  $('trashCard')._bound = true;
  $('trashRefresh').addEventListener('click', trashCenterLoad);
  $('trashList').addEventListener('click', async event => {
    const button = event.target.closest('[data-trash-restore]');
    if(!button || button.disabled) return;
    if(!confirm('이 묶음을 원래 위치로 복원할까요?\\n같은 이름의 새 파일은 덮어쓰지 않습니다.')) return;
    button.disabled = true;
    const r = await (await fetch('/api/picks_restore', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({batch_id:button.dataset.trashRestore})})).json();
    if(!r.ok) alert(r.error || '복원 실패');
    else if($('expGrid')) await expLoad(EXP.dir || '');
    await trashCenterLoad();
  });
  trashCenterLoad();
}

/* ── 자료 이미지 무결성 ────────────────────────────────────────────── */
let LOCAL_IMAGE_FINGERPRINT = '', LOCAL_IMAGE_BATCH = '';
function bindLocalImageIntegrity(){
  if(!$('localImageCard') || $('localImageCard')._bound) return;
  $('localImageCard')._bound = true;
  LOCAL_IMAGE_BATCH = sessionStorage.getItem('naisLocalImageRollback') || '';
  if(LOCAL_IMAGE_BATCH){
    $('localImageRollback').classList.remove('hidden');
    $('localImageMsg').textContent = '방금 정리한 참조를 원래 이름으로 되돌릴 수 있습니다.';
  }
  $('localImageScan').addEventListener('click', async () => {
    $('localImageScan').disabled = true;
    $('localImageNormalize').disabled = true;
    $('localImageMsg').textContent = '자료 JSON과 실제 이미지 바이트를 읽어 대조하는 중입니다.';
    try{
      const r = await (await fetch('/api/local_image_integrity')).json();
      if(!r.ok && (r.invalid_json||[]).length){
        $('localImageMsg').textContent = `읽지 못한 자료 JSON ${r.invalid_json.length}개가 있어 먼저 복구해야 합니다.`;
        return;
      }
      LOCAL_IMAGE_FINGERPRINT = r.fingerprint || '';
      const n = r.normalization || {};
      const danger = Number(r.missing||0) + Number(r.unreadable_references||0);
      $('localImageMsg').innerHTML =
        `<b>참조 ${Number(r.unique_references||0).toLocaleString()}개</b> — `
        + `누락 ${Number(r.missing||0).toLocaleString()} · 열기 실패 ${Number(r.unreadable_references||0).toLocaleString()}`
        + ` · 과거 이름 ${Number(r.referenced_legacy_names||0).toLocaleString()}`
        + ` · 현재 자료에서 미사용 ${Number(r.unreferenced||0).toLocaleString()}`
        + `<br>${danger ? '<b style="color:var(--danger);">손상 가능성이 있어 자동 정리를 막았습니다.</b>' :
          `표시 가능한 참조는 모두 있습니다. 안전 정리 시 JSON ${Number(n.documents_to_change||0)}개에서 `
          + `${Number(n.references_to_change||0).toLocaleString()}개 참조를 바꾸고 `
          + `${(Number(n.copy_bytes||0)/1048576).toFixed(1)}MB를 복사합니다.`}`
        + '<br>옛 파일과 미사용 후보는 지우지 않습니다.';
      $('localImageNormalize').disabled =
        !!n.blocked || !Number(n.references_to_change||0);
    }catch(e){
      $('localImageMsg').textContent = '이미지 검사 실패: ' + e;
    }finally{
      $('localImageScan').disabled = false;
    }
  });
  $('localImageNormalize').addEventListener('click', async () => {
    if(!LOCAL_IMAGE_FINGERPRINT) return;
    if(!confirm('검사한 참조를 실제 이미지 내용 해시 이름으로 정리할까요?\\n옛 파일은 지우지 않고 JSON 원본도 별도 기록에 보존합니다.')) return;
    $('localImageNormalize').disabled = true;
    $('localImageMsg').textContent = '새 이름 복사본과 JSON 원본 기록을 만든 뒤 참조를 바꾸는 중입니다.';
    try{
      const r = await (await fetch('/api/local_image_normalize', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({fingerprint:LOCAL_IMAGE_FINGERPRINT})
      })).json();
      if(!r.ok){ $('localImageMsg').textContent = r.error || '이미지 정리 실패'; return; }
      LOCAL_IMAGE_BATCH = r.batch || '';
      if(LOCAL_IMAGE_BATCH){
        sessionStorage.setItem('naisLocalImageRollback', LOCAL_IMAGE_BATCH);
        $('localImageRollback').classList.remove('hidden');
      }
      $('localImageMsg').textContent =
        `${Number(r.changed_references||0).toLocaleString()}개 참조를 안전 정리했습니다. `
        + `옛 이름 파일 ${Number(r.kept_legacy_files||0).toLocaleString()}개는 그대로 보존했습니다.`;
      LOCAL_IMAGE_FINGERPRINT = '';
    }catch(e){ $('localImageMsg').textContent = '이미지 정리 실패: ' + e; }
  });
  $('localImageRollback').addEventListener('click', async () => {
    if(!LOCAL_IMAGE_BATCH) return;
    const r = await (await fetch('/api/local_image_rollback', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:LOCAL_IMAGE_BATCH})
    })).json();
    $('localImageMsg').textContent = r.ok
      ? `자료 JSON ${Number(r.restored||0)}개를 정리 전으로 되돌렸습니다.`
        + (Number(r.skipped||0) ? ` 이후 다시 편집된 ${r.skipped}개는 덮어쓰지 않았습니다.` : '')
      : (r.error || '되돌리기 실패');
    if(r.ok){
      LOCAL_IMAGE_BATCH = '';
      sessionStorage.removeItem('naisLocalImageRollback');
      $('localImageRollback').classList.add('hidden');
      LOCAL_IMAGE_FINGERPRINT = '';
    }
  });
}

/* 실제 NAI 토큰 수 — 서버의 T5 토크나이저에 물어본다 (입력이 멈추면 한 번) */
let tokT = null;
async function naiTokens(){
  clearTimeout(tokT);
  tokT = setTimeout(async () => {
    try{
      /* ⚠ 실제 전송값은 prompt + outfit 이다 — 의상을 빼고 세면 화면은 512 이하인데
         실전송이 넘어 뒷부분이 잘린다 (CQA-009). 캐릭터 네거티브도 함께 센다.
         켠 칸만 세는 것도 전송 규칙과 같다. */
      const clean = x => (x || '').replace(/^[ \t]*#.*$/gm, '').trim();
      const join = (a, b) => [a, b].map(x => clean(x).replace(/^,|,$/g, '').trim())
        .filter(Boolean).join(', ');
      const slots = (STATE.char_slots || []).filter(s => s && s.enabled !== false
        && clean(join(s.prompt, s.outfit)));
      const chars = slots.map(s => join(s.prompt, s.outfit)).filter(Boolean);
      const charNegs = slots.map(s => s.negative || '').filter(Boolean);
      const r = await (await fetch('/api/tokens', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({base: $('basePrompt').value,
                              negative: $('negPrompt').value, chars,
                              char_negatives: charNegs, finalize: true})})).json();
      if(!r.ok) return;
      const over = r.shared > r.limit;
      /* 토크나이저 vocab 이 없으면 어림값이다 — 정확한 값처럼 보여 주면 안 된다 */
      const approx = r.exact === false ? '≈' : '';
      $('posTok').innerHTML = `${approx}${r.base} 토큰`
        + (chars.length ? ` <span style="opacity:.7">+캐릭터 ${r.shared - r.base}</span>` : '')
        + ` <span style="color:${over ? '#e0574e' : 'var(--muted)'}">/ ${r.limit}</span>`
        + (over ? ' <span style="color:#e0574e">⚠ 입력은 보존</span>' : '');
      $('posTok').title = (r.finalized ? '조각·품질·UC 반영값입니다. 무작위 조각은 실제 선택에 따라 달라질 수 있습니다. ' : '')
        + (approx ? 't5_tokenizer.json 이 없어 어림값입니다 (≈). ' : '')
        + (over
          ? `약 512 토큰을 ${r.shared - r.limit} 초과했습니다. 입력·저장·API 전송은 원문 그대로 하지만, `
            + '모델이 참고할 수 있는 문맥은 베이스와 모든 캐릭터를 합쳐 약 512 토큰이라 뒤쪽 영향이 약해지거나 무시될 수 있습니다.'
          : '베이스 + 모든 캐릭터 프롬프트가 약 512 T5 토큰을 함께 씁니다');
      // 네거티브가 부실한데 UC 프리셋이 None 이면 NAI 가 아무것도 안 보태서
      // 그림이 흐릿하고 뭉개진다. 실제로 확인한 조합이라 경고를 띄운다.
      const ucNone = Number((STATE.uc_preset ?? 4)) === 4;
      const weak = r.negative < 25;
      const negShared = r.shared_negative ?? r.negative;
      const negOver = negShared > r.limit;
      $('negTok').innerHTML = `${approx}${r.negative} 토큰`
        + (negShared > r.negative
            ? ` <span style="opacity:.7">+캐릭터 ${negShared - r.negative}</span>` : '')
        + ` <span style="color:${negOver ? '#e0574e' : 'var(--muted)'}">/ ${r.limit}</span>`
        + (negOver ? ' <span style="color:#e0574e">⚠ 입력은 보존</span>' : '')
        + (ucNone && weak ? ' <span style="color:#e0a04e">⚠ UC 프리셋이 None</span>' : '');
      const negNotes = [];
      if(negOver) negNotes.push(
        `약 512 토큰을 ${negShared - r.limit} 초과했습니다. 입력·저장·API 전송은 원문 그대로 하지만, `
        + '네거티브와 캐릭터별 네거티브가 같은 문맥 한도를 쓰므로 뒤쪽 영향이 약해지거나 무시될 수 있습니다.');
      else negNotes.push('네거티브 + 모든 캐릭터별 네거티브가 약 512 T5 토큰을 함께 씁니다.');
      if(ucNone && weak) negNotes.push(
        '네거티브가 너무 짧고 UC 프리셋이 None 입니다 — NAI 가 품질 태그를 하나도 보태지 '
        + '않아 그림이 흐려질 수 있습니다. 네거티브를 채우거나 파라미터에서 UC 프리셋을 '
        + 'Heavy/Human Focus 로 바꾸세요.');
      $('negTok').title = negNotes.join(' ');
    }catch(e){}
  }, 350);
}
function tokens(){
  const t = s => (s||'').split(',').filter(x=>x.trim()).length;
  $('posTok').textContent = t($('basePrompt').value) + '태그';
  $('negTok').textContent = t($('negPrompt').value) + '태그';
  naiTokens();   // 정확한 토큰 수로 곧 갈아치운다
  redrawHL();   // 프롬프트가 바뀔 때마다 하이라이트도 다시 그림
  const n = activeSlotIdx().length;
  $('bgChars').textContent = n;
  $('bgChars').style.display = n ? 'flex' : 'none';
  let sets = 0;
  SETTINGS.forEach(st => { const s = stState(st.name); if(s.use !== false && s.selected.length) sets++; });
  anlasRefresh(false);          // 수량·해상도·스텝이 바뀌면 비용도 다시
  $('bgSets').textContent = sets;
  $('bgSets').style.display = sets ? 'flex' : 'none';
  let total = 0;
  SETTINGS.forEach(st => {
    const s = stState(st.name);
    if(s.use === false || !s.selected.length) return;
    /* 예약 매수(세트마다 몇 벌)와 단계 선택을 함께 반영한다 */
    const rep = s.reserve || {};
    const stg = new Set((s.stages || []).map(Number));
    let shots = 0;
    st.groups.forEach(g => {
      if(!s.selected.includes(g.id)) return;
      const cuts = stg.size ? g.ids.filter((_, i) => stg.has(i + 1)).length : g.ids.length;
      shots += cuts * Math.max(1, Number(rep[g.id]) || 1);
    });
    /* 전용 캐스트만 벌을 늘린다 ("각자 따로 전체 씬 생성").
       ① 설정의 캐릭터 칸은 한 그림에 함께 들어가므로 장수를 곱하지 않는다. */
    const cast = (s.cast||[]).filter(c=>(c.prompt||'').trim()).length;
    total += shots * (cast || 1);
  });
  $('topStat').textContent = `캐릭터 ${n} · 세팅 ${sets} · 일괄 ${total}장`;
}

/* ── Highlight Emphasis ────────────────────────────────────────────
   NAI 의 같은 이름 기능. 가중치 표기를 색으로 보여준다.
     1.4::tag::   가중치 묶음 (강하면 따뜻한 색, 약하면 찬 색)
     -3::tag::    음수 = 빼기 (붉은색)
     {tag} [tag]  구형 강조/약화 (겹칠수록 진하게)
*/
function hlClass(w){
  if(w < 0) return 'w-neg';
  if(w >= 2) return 'w-up3';
  if(w >= 1.4) return 'w-up2';
  if(w > 1.0) return 'w-up1';
  if(w >= 0.5) return 'w-dn1';
  return 'w-dn2';
}
function highlightPrompt(text){
  const esc2 = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  let out = '';
  const lines = String(text || '').split('\n');
  lines.forEach((line, li) => {
    if(li) out += '\n';
    // 가중치 묶음: (숫자)::내용:: — 안쪽에 또 묶음이 올 수 있어 가장 짧게 잡는다
    let rest = line, guard = 0;
    while(rest && guard++ < 600){
      const m = rest.match(/(-?(?:\d+\.\d*|\.\d+|\d+))\s*::([\s\S]*?)::/);
      if(!m){ out += esc2(rest); break; }
      out += esc2(rest.slice(0, m.index));
      const w = parseFloat(m[1]);
      out += `<b class="${hlClass(w)}"><span class="w-num">${esc2(m[1])}::</span>`
           + esc2(m[2]) + '<span class="w-num">::</span></b>';
      rest = rest.slice(m.index + m[0].length);
    }
  });
  // 구형 {강조} [약화] — 중첩 깊이만큼 진하게
  out = out.replace(/(\{+)([^{}<]*)(\}+)/g, (s,a,b,c) =>
          `<b class="${a.length>=3?'w-up3':a.length===2?'w-up2':'w-up1'}">${a}${b}${c}</b>`)
           .replace(/(\[+)([^\[\]<]*)(\]+)/g, (s,a,b,c) =>
          `<b class="${a.length>=2?'w-dn2':'w-dn1'}">${a}${b}${c}</b>`);
  return out;
}
function attachHL(ta){
  if(!ta || ta._hl) return;
  const wrap = document.createElement('div');
  wrap.className = 'hlwrap';
  ta.parentNode.insertBefore(wrap, ta);
  const layer = document.createElement('div');
  layer.className = 'hl';
  wrap.appendChild(layer); wrap.appendChild(ta);
  ta._hl = layer;
  const sync = () => {
    // clientWidth/Height 는 textarea 테두리를 뺀 값이다. 거울층에도 같은 1px 테두리를
    // 두므로 양쪽 테두리 2px를 되붙여야 내용 폭·줄바꿈·스크롤 위치가 정확히 같다.
    // 세로 스크롤바가 나타나면 clientWidth가 줄어드는 것도 그대로 따라간다.
    layer.style.width = (ta.clientWidth + 2) + 'px';
    layer.style.height = (ta.clientHeight + 2) + 'px';
    layer.scrollTop = ta.scrollTop;
    layer.scrollLeft = ta.scrollLeft;
  };
  const draw = () => {
    if(!hlOn()){ layer.innerHTML = ''; return; }
    layer.innerHTML = highlightPrompt(ta.value) + '\n';
    sync();
  };
  ta.addEventListener('input', draw);
  ta.addEventListener('scroll', sync);
  window.addEventListener('resize', draw);
  if(window.ResizeObserver) new ResizeObserver(sync).observe(ta);
  ta._hlDraw = draw;
  draw();
}
/* 겹친 거울층은 브라우저·배율에 따라 글자가 번져 보일 수 있다. 기본은 원문 한 층만
   쓰고, 사용자가 기타 → 화면에서 직접 켰을 때만 가중치 배경을 그린다. */
function hlOn(){ return (STATE.ui || {}).highlight === true; }
function redrawHL(){
  document.querySelectorAll('textarea').forEach(t => { if(t._hlDraw) t._hlDraw(); });
}
function setupHL(){
  ['basePrompt','negPrompt'].forEach(id => attachHL($(id)));
  redrawHL();
}
function bindHLToggle(){
  const s = $('uiHighlight');
  if(!s || s._bound) return;
  s._bound = true;
  s.value = hlOn() ? 'on' : 'off';
  s.addEventListener('change', () => {
    STATE.ui = STATE.ui || {};
    STATE.ui.highlight = s.value === 'on';
    redrawHL(); save();
  });
}

/* ── 바이브 · 캐릭터 레퍼런스 ────────────────────────────────────────
   바이브는 인코딩 캐시가 핵심이다. 정보추출(information_extracted)을 바꾸면
   캐시가 무효가 되어 다음 생성에서 다시 인코딩(2 Anlas)한다. */
const REF_TYPE_KO = {'character&style':'생김새 + 화풍', 'character':'생김새만', 'style':'화풍만'};
function renderRefs(){
  const rows = (host, list, kind) => {
    const h = $(host); if(!h) return;
    h.innerHTML = '';
    (list || []).forEach((r, i) => {
      const el = document.createElement('div');
      el.className = 'row'; el.style.margin = '6px 0 0';
      const cached = kind === 'vibe' && r.encoded_ie != null;
      const thumb = `/refimg?id=${encodeURIComponent(r.id)}&kind=${kind}`;
      el.innerHTML = `<div class="tag">
          <label class="hint" style="cursor:pointer;"><input type="checkbox" data-ren="${kind}|${i}"
            ${r.enabled ? 'checked' : ''}> ${esc(r.name || '무제')}</label>
          ${kind === 'vibe' ? `<span class="hint" style="margin-left:6px;">${cached ? '인코딩됨 (공짜)' : '미인코딩 (2 Anlas)'}</span>` : ''}
          <button class="danger" data-rdel="${kind}|${i}" style="float:right;">✕</button></div>
        <div style="display:flex;gap:8px;">
        <img src="${thumb}" alt="" loading="lazy" onerror="this.style.display='none'"
          style="width:72px;height:72px;object-fit:cover;border-radius:var(--radius);
                 border:1px solid var(--line);flex:none;background:#0004;">
        <div style="flex:1;min-width:0;">
        <div class="grid2">
          ${kind === 'vibe' ? `
          <!-- 바이브는 공홈처럼 1 초과·0 미만도 받는다 (과하게 밀거나 반대로 밀 때) -->
          <div class="field"><label>강도 <span class="hint">1 넘김·0 미만도 가능</span></label>
            <input type="number" data-rf="vibe|${i}|strength" value="${r.strength ?? 0.6}"
              step="0.05" min="-1" max="2"></div>
          <div class="field"><label>정보 추출 <span class="hint">(바꾸면 재인코딩)</span></label>
            <input type="number" data-rf="vibe|${i}|info_extracted" value="${r.info_extracted ?? 0.7}"
              step="0.05" min="-1" max="2"></div>` : `
          <!-- 캐릭레퍼: 세기·충실도 둘 다 조절된다 (실측 -0.5~2.0 전부 통과).
               정보추출만 NAI 가 1.0 으로 강제하므로 칸을 두지 않는다. -->
          <div class="field"><label>세기 <span class="hint">1 넘김·0 미만도 가능</span></label>
            <input type="number" data-rf="cref|${i}|strength" value="${r.strength ?? 1.0}"
              step="0.05" min="-1" max="2"></div>
          <div class="field"><label>충실도 <span class="hint">높이면 원본을 더 따라갑니다</span></label>
            <input type="number" data-rf="cref|${i}|fidelity" value="${r.fidelity ?? 0.6}"
              step="0.05" min="-1" max="2"></div>` }
        </div>
        ${kind === 'cref' ? `<div class="field"><label>참조 종류</label>
          <select data-rf="cref|${i}|ref_type">${Object.entries(REF_TYPE_KO).map(([v,l]) =>
            `<option value="${v}"${(r.ref_type||'character&style')===v?' selected':''}>${l}</option>`).join('')}</select></div>` : ''}
        </div></div>`;
      h.appendChild(el);
    });
  };
  rows('vibeList', STATE.vibes, 'vibe');
  rows('crefList', STATE.char_refs, 'cref');
  const onV = (STATE.vibes || []).filter(v => v.enabled).length;
  const onC = (STATE.char_refs || []).filter(v => v.enabled).length;
  if($('bgVibe')) $('bgVibe').textContent = onV;
  if($('bgCref')) $('bgCref').textContent = onC;
  const badge = $('bgRefs');
  if(badge){ badge.textContent = onV + onC; badge.style.display = (onV + onC) ? 'flex' : 'none'; }
  const list = k => k === 'vibe' ? (STATE.vibes = STATE.vibes || [])
                                 : (STATE.char_refs = STATE.char_refs || []);
  document.querySelectorAll('[data-ren]').forEach(c => c.addEventListener('change', () => {
    const [k, i] = c.dataset.ren.split('|'); list(k)[+i].enabled = c.checked; saveRefs();
  }));
  document.querySelectorAll('[data-rf]').forEach(el => el.addEventListener('change', () => {
    const [k, i, f] = el.dataset.rf.split('|');
    list(k)[+i][f] = (f === 'ref_type') ? el.value : (Number(el.value) || 0);
    saveRefs();
  }));
  document.querySelectorAll('[data-rdel]').forEach(b => b.addEventListener('click', () => {
    const [k, i] = b.dataset.rdel.split('|'); list(k).splice(+i, 1); saveRefs();
  }));
}
async function saveRefs(){
  const changed = ['vibes','char_refs'].filter(key =>
    JSON.stringify((STATE||{})[key] || []) !==
    JSON.stringify((SAVED_STATE||{})[key] || []));
  if(!changed.length) return;
  const payload = {_revision:STATE._revision, _base:{}};
  changed.forEach(key => {
    payload[key] = STATE[key] || [];
    payload._base[key] = (SAVED_STATE||{})[key] || [];
  });
  const r = await (await fetch('/api/ref_save', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)})).json();
  if(r.conflict){ flash(r.error || '참조 목록 저장 충돌'); return; }
  if(r.ok){
    STATE.vibes = r.vibes; STATE.char_refs = r.char_refs;
    if(r.revision != null) STATE._revision = r.revision;
    rememberSavedKeys(changed);
    renderRefs(); anlasRefresh(false);
  }
}
async function addRefs(files, kind){
  const imgs = files.filter(f => /\.(png|webp)$/i.test(f.name));
  if(!imgs.length){ $('refMsg').textContent = 'PNG 또는 WebP 를 넣어주세요.'; return; }
  for(const f of imgs){
    $('refMsg').textContent = `${f.name} 등록 중...`
      + (kind === 'vibe' ? ' (인코딩 2 Anlas)' : '');
    try{
      const r = await (await fetch('/api/ref_add', {method:'POST', headers:{
        'X-Kind': kind, 'X-Filename': encodeURIComponent(f.name)},
        body: await f.arrayBuffer()})).json();
      if(r.ok){
        if(r.vibes) STATE.vibes = r.vibes;
        if(r.char_refs) STATE.char_refs = r.char_refs;
        if(r.revision != null) STATE._revision = r.revision;
        rememberSavedKeys(r.vibes ? ['vibes'] : ['char_refs']);
        $('refMsg').textContent = r.warn || `${f.name} 등록 ✓`;
      } else $('refMsg').textContent = r.error;
    }catch(e){ $('refMsg').textContent = String(e); }
  }
  renderRefs(); anlasRefresh(false);
}
function bindRefs(){
  if(!$('vibeDrop') || $('vibeDrop')._bound) return;
  $('vibeDrop')._bound = true;
  [['vibeDrop','vibeFile','vibe'], ['crefDrop','crefFile','cref']].forEach(([z, fi, kind]) => {
    const zone = $(z), file = $(fi);
    zone.addEventListener('click', () => file.click());
    file.addEventListener('change', () => { addRefs([...file.files], kind); file.value = ''; });
    ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.style.borderColor = 'var(--accent)'; }));
    ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.style.borderColor = ''; }));
    zone.addEventListener('drop', e => { e.stopPropagation(); addRefs([...(e.dataTransfer.files||[])], kind); });
  });
  document.querySelectorAll('[data-reftab]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-reftab]').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('[data-refpane]').forEach(x =>
      x.classList.toggle('hidden', x.dataset.refpane !== b.dataset.reftab));
  }));
  renderRefs();
}

/* NAIS3 와 같은 스위치 — 끄면 NAI 가 알아서 배치한다 (AI's Choice) */
function bindUseCoords(){
  const c = $('chUseCoords');
  if(!c || c._bound) return;
  c._bound = true;
  const paint = () => {
    c.checked = !!STATE.use_coords;
    /* 실측(라운드01): 좌표는 2명부터 적용된다 — 1명일 때는 NAI 가 통째로 무시.
       0명일 때 "1명" 안내를 내면 거짓말이 된다 — 정확히 1명일 때만 */
    const solo = activeSlotIdx().length === 1;
    $('chCoordsNote').textContent = STATE.use_coords
      ? (solo
        ? '켜져 있지만 인물이 1명일 때는 좌표가 무시됩니다(V4.5 실측) — 2명부터 적용됩니다.'
        : '인물마다 격자(빠른 선택)나 숫자 칸(0~1 자유값)으로 자리를 정합니다.')
      : "끔 = AI's Choice — NAI 가 알아서 배치합니다.";
    /* 몸이 붙는 조건 두 가지 — ① 좌표를 안 씀 ② 좌표가 서로 겹침 */
    const n = activeSlotIdx().length;
    const over = n > MAX_CHARS;
    const warn = $('chFuseWarn');
    if(warn){
      const off = n >= 2 && !STATE.use_coords;
      const clash = coordsClash();
      warn.classList.toggle('hidden', !(off || clash || over));
      if(off || clash || over){
        /* ⚠ 아래에서 이 div 의 innerHTML 을 다시 쓰므로 그 안에 있던
           #chFuseN span 은 사라진다. 인원수는 문구에 직접 박아 넣는다. */
        const w = warn.querySelector('div');
        if(w) w.innerHTML = over
          ? `<b>켠 인물이 ${n}명입니다.</b> NAI 는 <b>${MAX_CHARS}명</b>까지만 받습니다 —
             앞 ${MAX_CHARS}명만 보내고 나머지는 <b>칸에 그대로 남습니다</b>.
             안 보낼 인물은 왼쪽 스위치를 끄세요.`
          : off
          ? `<b>인물이 ${n}명인데 위치를 안 정했습니다.</b> 이러면 NAI 가 <b>몸을 붙여</b> 그리는 일이 흔합니다.`
          : `<b>인물 ${n}명 중 같은 자리에 겹친 사람이 있습니다.</b> 겹치면 위치를 켜도 <b>몸이 붙습니다</b>.`;
        const btn = $('chSpread');
        if(btn) btn.style.display = over ? 'none' : '';
      }
    }
  };
  c.addEventListener('change', () => {
    STATE.use_coords = c.checked;
    if($('pCoords')) $('pCoords').value = c.checked ? 'on' : 'off';
    paint(); save();
  });
  const spread = $('chSpread');
  if(spread) spread.addEventListener('click', () => {
    /* 실제 NAI 이미지에서 2인 구도에 가장 흔한 값이 x 0.3 / 0.7 · y 0.5 다.
       3명 이상이면 0.1~0.9 사이를 고르게 나눈다. 6명부터는 두 줄.
       좌표는 **칸 순서**로 저장하므로 켠 인물의 자리만 다시 배치한다. */
    const idx = activeSlotIdx();
    const n = idx.length || 2;
    const auto = spreadCenters(n);
    const cs = (STATE.char_centers || []).slice();
    while(cs.length < (STATE.char_slots || []).length) cs.push(null);
    idx.forEach((i, k) => { cs[i] = auto[k]; });
    STATE.char_centers = cs;
    STATE.use_coords = true;
    if($('pCoords')) $('pCoords').value = 'on';
    paint(); drawPosGrids(); save();
    flash(`켠 인물 ${n}명을 ${auto.map(c=>`x${c.x}·y${c.y}`).join(' / ')} 로 떨어뜨렸습니다.`);
  });
  paint();
  window._paintCoords = paint;
}

/* ── 캐릭터 위치 (centers) ──────────────────────────────────────────
   NAI 는 인물마다 화면 어디에 둘지 좌표를 받는다. 공홈 UI 는 5×5 격자만 보여주지만
   **서버는 0~1 자유값을 받고 격자로 반올림하지 않는다** (라운드01 실측 — 0.05 차이도 반영).
   격자는 빠른 선택용으로 남기고 숫자 칸으로 자유값을 넣는다.
   ⚠ 실측 주의(2026-07 · V4.5 full 기준): **인물이 1명이면 좌표가 통째로 무시된다**
   (12장 픽셀 동일 확인). 좌표는 2명부터 적용되고, 핀 고정이 아니라 느슨한 유도다.
   다른 모델·향후 서버에서는 다를 수 있다 — 모델이 바뀌면 재실측할 것.
   '캐릭터 위치 좌표 사용'(use_coords)이 꺼져 있으면 NAI 가 알아서 배치한다. */
const POS_STEPS = [0.1, 0.3, 0.5, 0.7, 0.9];
const MAX_CHARS = 6;      // NAI 가 한 그림에 받는 인물 수 (서버 상수와 같음)
/* 인물 n 명을 겹치지 않게 벌린 좌표 — 서버 spread_centers() 와 같은 규칙.
   한 줄은 5칸까지라 6명부터는 두 줄(y 0.3 / 0.7)로 나눈다. */
function spreadCenters(n){
  if(n <= 1) return [{x:0.5, y:0.5}];
  if(n === 2) return [{x:0.3, y:0.5}, {x:0.7, y:0.5}];
  const rows = n <= 5 ? 1 : 2;
  const per = Math.ceil(n / rows);
  const ys = rows === 1 ? [0.5] : [0.3, 0.7];
  const pick = (k, total) => total === 1 ? POS_STEPS[2]
    : POS_STEPS[Math.min(4, Math.round(k * 4 / (total - 1)))];
  const out = [];
  for(let i = 0; i < n; i++){
    const r = Math.floor(i / per), k = i % per;
    out.push({x: pick(k, Math.min(per, n - r * per)), y: ys[Math.min(r, ys.length - 1)]});
  }
  return out;
}
function slotCenter(i){
  const c = (STATE.char_centers || [])[i];
  return {x: (c && c.x != null) ? c.x : 0.5, y: (c && c.y != null) ? c.y : 0.5};
}
function drawPosGrids(){
  document.querySelectorAll('[data-pos]').forEach(host => {
    const i = +host.dataset.pos;
    const cur = slotCenter(i);
    host.innerHTML = '';
    POS_STEPS.forEach(y => POS_STEPS.forEach(x => {
      const cell = document.createElement('span');
      const on = Math.abs(x - cur.x) < 0.01 && Math.abs(y - cur.y) < 0.01;
      cell.className = 'poscell' + (on ? ' on' : '');
      cell.title = `x ${x} · y ${y}`;
      cell.addEventListener('click', () => {
        STATE.char_centers = STATE.char_centers || [];
        while(STATE.char_centers.length <= i) STATE.char_centers.push({x:0.5, y:0.5});
        STATE.char_centers[i] = {x, y};
        drawPosGrids(); save();
        if(!(STATE.use_coords)) flash('위치를 쓰려면 파라미터에서 [캐릭터 위치 좌표 사용]을 켜세요.');
      });
      host.appendChild(cell);
    }));
    /* 숫자 칸도 현재 값으로 (포커스 중인 칸은 건드리지 않는다 — 입력을 지우게 된다) */
    const nx = document.querySelector(`[data-posx="${i}"]`);
    const ny = document.querySelector(`[data-posy="${i}"]`);
    if(nx && document.activeElement !== nx) nx.value = cur.x;
    if(ny && document.activeElement !== ny) ny.value = cur.y;
    const lab = document.querySelector(`[data-poslabel="${i}"]`);
    if(lab) lab.textContent = (cur.x === 0.5 && cur.y === 0.5)
      ? '가운데 (기본)' : `x ${cur.x} · y ${cur.y}`;
  });
}

/* ── 디렉터 툴 ──────────────────────────────────────────────────────
   그림을 넣으면 NAI 가 손봐서 돌려준다. 도구에 따라 필요한 칸만 보인다. */
function dirSync(){
  const t = $('dirTool').value;
  const show = (id, on) => { $(id).style.display = on ? '' : 'none'; };
  show('dirEmotion', t === 'emotion');
  show('dirPrompt', t === 'colorize' || t === 'emotion');
  show('dirDefry', t === 'colorize' || t === 'emotion');
  show('dirScale', t === 'upscale');
  $('dirPrompt').placeholder = t === 'emotion'
    ? '추가 지시 (선택 — 감정은 왼쪽에서 고름)' : '색 유도 프롬프트 (선택)';
}
async function runDirector(files){
  const imgs = files.filter(f => /\.(png|webp)$/i.test(f.name));
  if(!imgs.length){ $('dirMsg').textContent = 'PNG 또는 WebP 를 넣어주세요.'; return; }
  const tool = $('dirTool').value;
  let prompt = $('dirPrompt').value || '';
  if(tool === 'emotion'){
    prompt = [$('dirEmotion').value, prompt].filter(Boolean).join(', ');
  }
  let ok = 0, fail = [];
  for(let i = 0; i < imgs.length; i++){
    const f = imgs[i];
    $('dirMsg').textContent = `${i+1}/${imgs.length} ${f.name} — ${tool} 처리 중...`;
    try{
      const r = await (await fetch('/api/director', {method:'POST', headers:{
        'X-Tool': tool, 'X-Prompt': encodeURIComponent(prompt),
        'X-Defry': $('dirDefry').value, 'X-Scale': $('dirScale').value,
        'X-Filename': encodeURIComponent(f.name)},
        body: await f.arrayBuffer()})).json();
      if(r.ok){ ok++; $('dirMsg').textContent = `${r.file} (${r.width}×${r.height}) ✓`; }
      else fail.push(r.error);
    }catch(e){ fail.push(String(e)); }
  }
  $('dirMsg').textContent = `${ok}개 완료`
    + (fail.length ? ` · ${fail.length}개 실패: ${fail[0].slice(0,60)}` : ' — output/디렉터/ 에 저장');
}
function bindDirector(){
  if(!$('dirTool') || $('dirTool')._bound) return;
  $('dirTool')._bound = true;
  $('dirTool').addEventListener('change', dirSync);
  dirSync();
  const zone = $('dirDrop'), file = $('dirFile');
  zone.addEventListener('click', () => file.click());
  file.addEventListener('change', () => { runDirector([...file.files]); file.value = ''; });
  ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = ''; }));
  zone.addEventListener('drop', e => {
    e.stopPropagation();               // 전역 그림체 추출로 새지 않게
    runDirector([...(e.dataTransfer.files || [])]);
  });
}

/* ── Anlas 비용 ────────────────────────────────────────────────────
   565장 돌리기 전에 총액을 먼저 보여준다. Opus 무료 조건도 함께. */
let anlasT = null;
function anlasRefresh(withBalance){
  clearTimeout(anlasT);
  anlasT = setTimeout(async () => {
    try{
      // 일괄 생성이면 선택된 세팅의 총 장수, 아니면 수량칸
      const m = ($('topStat').textContent || '').match(/일괄 ([\d,]+)장/);
      const batch = m ? Number(m[1].replace(/,/g,'')) : 0;
      const count = batch || Number($('qty').value) || 1;
      const r = await (await fetch('/api/anlas', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({count, batch: batch > 0, balance: !!withBalance})})).json();
      if(!r.ok) return;
      const e = r.est;
      // '무엇을 몇 장' 인지 먼저 말한다. 숫자만 던지면 뜬금없다.
      const what = e.batch
        ? `🎬 선택한 세팅 ${e.count.toLocaleString()}장`
        : `🖼 지금 설정으로 ${e.count.toLocaleString()}장`;
      let txt;
      if(e.free){
        txt = `${what} — <b>Anlas 0</b>`
            + (e.batch ? ' <span style="opacity:.7">(Opus 무료 범위)</span>'
                       : ` <span style="opacity:.7">(Opus 무료 · ${e.width}×${e.height} · ${e.steps}스텝)</span>`);
      } else if(e.batch){
        txt = `${what} — <b>${e.total.toLocaleString()} Anlas</b>`;
      } else {
        txt = `${what} — 장당 ${e.per_image} × ${e.count.toLocaleString()} = `
            + `<b>${e.total.toLocaleString()} Anlas</b>`;
      }
      if(e.subscription_known === false){
        txt += ' <span style="color:#9a6700">(구독 등급 미확인 · 유료 기준 예상, 잔액 확인을 눌러주세요)</span>';
      }
      if(r.balance){
        const b = r.balance;
        const after = b.total - e.total;
        txt += ` · 잔액 ${b.total.toLocaleString()}`
             + (e.total ? ` → ${after.toLocaleString()}` : '')
             + (b.opus ? ' (Opus)' : ` (tier ${b.tier})`);
        if(after < 0) txt += ' <b style="color:#e0574e">부족!</b>';
      }
      $('anlasCost').innerHTML = txt;
      $('anlasCost').title = e.why;
    }catch(err){}
  }, 400);
}

/* ── 생성 파라미터 ── */
const ONOFF = [['pQuality','quality_toggle'],['pSmea','smea'],['pSmeaDyn','smea_dyn'],
  ['pDynThr','dynamic_thresholding'],['pBrownian','prefer_brownian'],
  ['pEulerBug','deliberate_euler_ancestral_bug'],['pCoords','use_coords']];
const NUMS = [['pUncond','uncond_scale',0],['pCtrl','controlnet_strength',1]];
const STYLE_PARAM_IDS = new Set([
  'basePrompt','negPrompt','pModel','pScale','pRescale','pSteps','pSampler','pSched',
  'pVariety','pQuality','pUc','pRes','pWidth','pHeight','pSmea','pSmeaDyn',
  'pDynThr','pUncond','pCtrl','pBrownian','pEulerBug'
]);

/* ── 시드 ──────────────────────────────────────────────────────────
   NAI 시드 = 0 이면 회차 시드를 쓰고(회차마다 하나 뽑아 상태.json에 저장),
   값이 있으면 그 시드로 고정한다. 생성된 그림의 실제 시드는 미리보기에 나온다. */
let lastSeed = 0;
function seedNote(){
  const v = Number($('pNaiSeed').value) || 0;
  $('pSeedNow').textContent = v
    ? `고정 — 모든 장이 시드 ${v}. 같은 그림을 다시 뽑을 때 씁니다.`
    : (lastSeed
        ? `장마다 다른 시드 (직전 장 ${lastSeed}). 회차 번호가 같으면 같은 결과가 재현됩니다.`
        : '장마다 다른 시드 — NAI 기본 동작. 회차 번호가 같으면 같은 결과가 재현됩니다.');
}
function bindSeed(){
  if(window._seedBound) return;
  window._seedBound = true;
  $('pSeedRoll').addEventListener('click', () => {
    STATE.nai_seed = Math.floor(Math.random() * 4294967295);
    $('pNaiSeed').value = STATE.nai_seed; seedNote(); save();
  });
  $('pSeedClear').addEventListener('click', () => {
    STATE.nai_seed = 0; $('pNaiSeed').value = 0; seedNote(); save();
  });
  $('pNaiSeed').addEventListener('input', seedNote);
  $('pvSeedCopy').addEventListener('click', () => {
    if(!lastSeed) return;
    navigator.clipboard?.writeText(String(lastSeed));
    $('pvSeed').textContent = `시드 ${lastSeed} — 복사됨 ✓`;
  });
  $('pvSeedLock').addEventListener('click', () => {
    if(!lastSeed) return;
    STATE.nai_seed = lastSeed; $('pNaiSeed').value = lastSeed; seedNote(); save();
    $('pvSeed').textContent = `시드 ${lastSeed} — 고정됨 ✓`;
  });
}

let paramsPainted = false;
function paintParams(){
  $('pModel').value = STATE.model || 'nai-diffusion-4-5-full';
  $('pFormat').value = STATE.save_format || 'webp';
  if($('pOutDir')) $('pOutDir').value = STATE.out_dir || '';
  if($('pOutDate')) $('pOutDate').value = STATE.out_by_date ? 'on' : 'off';
  $('pClean').value = STATE.save_clean ? 'on' : 'off';
  $('pMaxSide').value = String(STATE.save_max_side || 0);
  $('pSaveQ').value = STATE.save_quality ?? 92;
  $('pCleanOpts').style.display = STATE.save_clean ? '' : 'none';
  $('pUc').value = String(STATE.uc_preset ?? 3);
  const w = STATE.width || 832, h = STATE.height || 1216;
  $('pWidth').value = w; $('pHeight').value = h;
  const key = `${w}x${h}`;
  const known = [...$('pRes').options].some(o => o.value === key);
  $('pRes').value = known ? key : '';
  $('pWHwrap').style.display = known ? 'none' : '';
  ONOFF.forEach(([id,k]) => { const d = (k==='prefer_brownian'); $(id).value = (STATE[k] ?? d) ? 'on' : 'off'; });
  NUMS.forEach(([id,k,d]) => { $(id).value = STATE[k] ?? d; });
  gateByModel();
  bindSeed(); seedNote();
  paramsPainted = true;
}

/* 모델 세대에 따라 안 쓰이는 파라미터를 잠근다.
   V3 전용을 V4에 켜면 무시되거나 결과가 망가지므로 아예 못 만지게 한다. */
function gateByModel(){
  const v4 = (STATE.model || '').startsWith('nai-diffusion-4');
  document.querySelectorAll('#pAdv [data-gen]').forEach(f => {
    const on = f.dataset.gen === (v4 ? 'v4' : 'v3');
    f.style.opacity = on ? '' : '.42';
    f.querySelectorAll('input,select').forEach(el => { el.disabled = !on; });
    const lab = f.querySelector('label');
    let tag = lab.querySelector('.genTag');
    if(!tag){ tag = document.createElement('span'); tag.className = 'genTag hint'; lab.appendChild(tag); }
    tag.textContent = on ? '' : (f.dataset.gen === 'v3' ? '  — V3 전용' : '  — V4 전용');
  });
  // Variety+ 도 V4 전용
  const vf = $('pVariety');
  if(vf){ vf.disabled = !v4; vf.parentElement.style.opacity = v4 ? '' : '.42'; }
  $('pAdvNote').textContent = v4
    ? '지금 모델은 V4 계열입니다. SMEA·Dynamic Thresholding·Uncond Scale·ControlNet 은 V3 전용이라 잠겨 있습니다.'
    : '지금 모델은 V3 계열입니다. Variety+·캐릭터 좌표·Euler 버그 재현은 V4 전용이라 잠겨 있습니다.';
}
function readParams(){
  // 화면이 아직 설정값으로 채워지기 전이면 읽지 않는다 (기본값으로 덮어쓰기 방지)
  if(!paramsPainted) return;
  STATE.model = $('pModel').value;
  STATE.save_format = $('pFormat').value;
  if($('pOutDir')) STATE.out_dir = $('pOutDir').value.trim();
  if($('pOutDate')) STATE.out_by_date = $('pOutDate').value === 'on';
  STATE.save_clean = $('pClean').value === 'on';
  STATE.save_max_side = Number($('pMaxSide').value) || 0;
  STATE.save_quality = Number($('pSaveQ').value) || 92;
  $('pCleanOpts').style.display = STATE.save_clean ? '' : 'none';
  STATE.uc_preset = Number($('pUc').value);
  const r = $('pRes').value;
  if(r){ const [w,h] = r.split('x').map(Number); STATE.width = w; STATE.height = h;
         $('pWidth').value = w; $('pHeight').value = h; $('pWHwrap').style.display = 'none'; }
  else { STATE.width = Number($('pWidth').value) || 832;
         STATE.height = Number($('pHeight').value) || 1216; $('pWHwrap').style.display = ''; }
  ONOFF.forEach(([id,k]) => { STATE[k] = $(id).value === 'on'; });
  NUMS.forEach(([id,k,d]) => { const v = Number($(id).value); STATE[k] = isNaN(v) ? d : v; });
  gateByModel();
  if(window._paintCoords) window._paintCoords();
  tokens(); save();
}
['pModel','pFormat','pOutDir','pOutDate','pClean','pMaxSide','pSaveQ','pUc','pRes','pWidth','pHeight',...ONOFF.map(x=>x[0]),...NUMS.map(x=>x[0])]
  .forEach(id => { const el = $(id); if(!el) return;
    const changed = () => { readParams(); if(STYLE_PARAM_IDS.has(id)) clearActiveStyle(); };
    el.addEventListener('change', changed); el.addEventListener('input', changed); });

/* ── 저장 ── */
let saveT = null, saveBusy = false, saveQueued = false, reloadAfterSave = false;
function stateSavePatch(){
  const patch = {_revision: STATE._revision, _base:{}};
  for(const [key, value] of Object.entries(STATE || {})){
    if(key.startsWith('_')) continue;
    const before = SAVED_STATE ? SAVED_STATE[key] : undefined;
    if(JSON.stringify(value) === JSON.stringify(before)) continue;
    patch[key] = value;
    patch._base[key] = before;
  }
  return patch;
}
function rememberSavedKeys(keys){
  SAVED_STATE = SAVED_STATE || {};
  (keys || []).forEach(key => {
    if(key in STATE) SAVED_STATE[key] = JSON.parse(JSON.stringify(STATE[key]));
  });
  SAVED_STATE._revision = STATE._revision;
}
function save(){
  clearTimeout(saveT);
  saveState('busy', '저장 대기…');
  /* 자동완성은 160ms 뒤 시작하며 첫 색인은 22만 태그를 읽는다.
     저장을 그보다 먼저 보내 새 설치의 첫 입력도 색인 예열 뒤로 밀리지 않게 한다. */
  saveT = setTimeout(doSave, 100);
}
function saveState(kind, text, detail=''){
  const el = $('saveState'); if(!el) return;
  el.className = 'save-state' + (kind ? ' ' + kind : '');
  el.textContent = text;
  el.title = detail || '설정.json 자동저장 상태';
}
async function doSave(){
  saveT = null;
  /* 앞 요청보다 옛 STATE가 늦게 도착해 새 값을 덮지 않도록 한 번에 하나만 보낸다. */
  if(saveBusy){ saveQueued = true; return; }
  saveBusy = true;
  saveState('busy', '저장 중…');
  try{
    const patch = stateSavePatch();
    const changed = Object.keys(patch).filter(key => !key.startsWith('_'));
    if(!changed.length){ saveState('', '저장됨 ✓'); return; }
    const r = await (await fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(patch)})).json();
    if(r && r.conflict){
      const msg = r.error || '다른 화면에서 설정이 변경됐습니다. 새로고침해주세요.';
      saveState('fail', '저장 충돌 ⚠', msg); flash(msg); return;
    }
    if(r && r.revision != null) STATE._revision = r.revision;
    const f = (r && r.fixed) || {};
    const ids = {width:'pWidth',height:'pHeight',steps:'pSteps',cfg_scale:'pScale',
      cfg_rescale:'pRescale',save_quality:'pSaveQ',seed:'pSeed',nai_seed:'pNaiSeed',
      uncond_scale:'pUncond',controlnet_strength:'pCtrl'};
    Object.entries(f).forEach(([k, v]) => {
      if(k.startsWith('pace.')){
        const pk = k.slice(5); STATE.pace = STATE.pace || {}; STATE.pace[pk] = v.used;
        const pe = Object.entries(PACE_FIELDS).find(([,key]) => key === pk);
        if(pe && $(pe[0])) $(pe[0]).value = v.used;
      }else if(ids[k]){
        STATE[k] = v.used; if($(ids[k])) $(ids[k]).value = v.used;
      }
    });
    const wh = ['width','height'].filter(k => f[k]);
    const note = $('pResNote');
    if(note) note.textContent = wh.length
      ? `⚠ NAI 규격(64 배수·64~2048)으로 맞췄습니다: ${wh.map(k => `${k==='width'?'가로':'세로'} ${f[k].sent}→${f[k].used}`).join(' · ')}` : '';
    if(r && r.rejected && r.rejected.length) flash(`저장하지 않은 잘못된 값: ${r.rejected.join(', ')}`);
    rememberSavedKeys((r && r.accepted) || changed);
    if(r && r.external_changes && r.external_changes.length){
      reloadAfterSave = true;
      flash(`다른 실행본의 변경 ${r.external_changes.length}개도 반영했습니다. 화면을 맞추는 중입니다.`);
    }
    saveState('', '저장됨 ✓');
  }catch(e){
    console.warn('설정 저장 실패', e);
    saveState('fail', '저장 실패 ⚠',
      '설정.json에 저장하지 못했습니다. 앱을 닫지 말고 연결 상태와 생성.log를 확인하세요.');
  }
  finally{
    saveBusy = false;
    if(saveQueued){ saveQueued = false; doSave(); }
    else if(reloadAfterSave){
      const pending = Object.keys(stateSavePatch()).some(key => !key.startsWith('_'));
      if(pending){
        if(!saveT) save();
      }else{
        reloadAfterSave = false;
        location.reload();
      }
    }
  }
}
/* 입력 직후 100ms 안에 탭을 닫아도 마지막 변경을 서버에 넘긴다.
   입력 원문은 그대로 보내며 길이 제한을 두지 않는다. */
window.addEventListener('pagehide', () => {
  if(!saveT || saveBusy || !navigator.sendBeacon) return;
  clearTimeout(saveT); saveT = null;
  const patch = stateSavePatch();
  if(!Object.keys(patch).some(key => !key.startsWith('_'))) return;
  navigator.sendBeacon('/api/save',
    new Blob([JSON.stringify(patch)], {type:'application/json'}));
});
['basePrompt','negPrompt','token','pScale','pRescale','pSteps','pSeed','pNaiSeed','pSampler','pSched','pVariety'].forEach(id => {
  const el = $(id);
  const h = () => {
    STATE.base_prompt = $('basePrompt').value;
    STATE.negative_prompt = $('negPrompt').value;
    STATE.token = $('token').value;
    STATE.cfg_scale = Number($('pScale').value) || 5.5;
    STATE.cfg_rescale = Number($('pRescale').value) || 0.56;
    STATE.steps = Number($('pSteps').value) || 28;
    STATE.seed = Number($('pSeed').value) || 1;
    STATE.nai_seed = Number($('pNaiSeed').value) || 0;
    STATE.sampler = $('pSampler').value || 'k_euler_ancestral';
    STATE.scheduler = $('pSched').value || 'karras';
    STATE.variety = $('pVariety').value === 'on';
    if(STYLE_PARAM_IDS.has(id)) clearActiveStyle();
    tokens(); save();
  };
  el.addEventListener('input', h); el.addEventListener('change', h);
});
/* 부루 계정 — 다른 파라미터 저장 훅과 섞으면 서로 덮어쓰므로 따로 둔다 */
[['bkDanUser','danbooru','user'],['bkDanKey','danbooru','key'],['bkGelUser','gelbooru','user'],['bkGelKey','gelbooru','key'],['bkE6User','e621','user'],['bkE6Key','e621','key']].forEach(([id, site, f]) => {
  const el = $(id); if(!el) return;
  const h = () => {
    STATE.booru_keys = STATE.booru_keys || {};
    STATE.booru_keys[site] = STATE.booru_keys[site] || {};
    STATE.booru_keys[site][f] = el.value.trim();
    save();
  };
  el.addEventListener('input', h); el.addEventListener('change', h);
});
if($('bkTest')) $('bkTest').addEventListener('click', async () => {
  const m = $('bkMsg'); m.textContent = '확인 중...';
  const out = [];
  for(const site of ['danbooru','gelbooru','e621']){
    try{
      const r = await (await fetch('/api/booru?site='+site+'&q=1girl&limit=1')).json();
      out.push((site==='danbooru'?'단부루':site==='gelbooru'?'겔부루':'e621')
        + ': ' + (r.ok ? (r.items||[]).length+'건 OK' : '실패'));
      if(!r.ok) console.log(site, r.error);
    }catch(e){ out.push(site+': 오류'); }
  }
  m.textContent = out.join(' · ') + ' (실패 이유는 검색 화면에 나옵니다)';
});

/* ── 접기/오버레이/모드 ── */
document.querySelectorAll('[data-fold]').forEach(h => h.addEventListener('click', () => {
  h.classList.toggle('closed'); $(h.dataset.fold).classList.toggle('hidden');
}));
document.querySelectorAll('[data-ovl]').forEach(b => b.addEventListener('click', () => {
  // data-ovl="refs" → #ovlRefs. 오버레이를 늘려도 여기 손대지 않아도 된다
  const k = b.dataset.ovl;
  const id = 'ovl' + k.charAt(0).toUpperCase() + k.slice(1);
  const target = $(id);
  if(!target){ console.warn('오버레이 없음:', id); return; }
  const wasOpen = !target.classList.contains('hidden');
  document.querySelectorAll('.ovl').forEach(o => o.classList.add('hidden'));
  if(!wasOpen) target.classList.remove('hidden');   // 같은 버튼을 다시 누르면 닫힘
}));
document.querySelectorAll('[data-ovl-close]').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.ovl').forEach(o => o.classList.add('hidden'));
}));

/* 작업실의 자료 화면은 "찾기·정리 → 비교·선별" 흐름으로 나눈다.
   비교 생성의 DOM·이벤트·설정은 복제하지 않고 카드 하나를 옮긴다. 기존 화면으로
   돌아가면 원래 세팅 탭의 앵커로 즉시 복원되므로 두 구현이 어긋나지 않는다. */
function bindStudioLibraryNav(){
  const nav = $('studioLibraryNav');
  if(!nav || nav._bound) return;
  nav._bound = true;
  nav.querySelectorAll('[data-library-work]').forEach(button => {
    button.addEventListener('click', () => {
      STATE.ui = STATE.ui || {};
      STATE.ui.library_work = button.dataset.libraryWork === 'compare' ? 'compare' : 'browse';
      arrangeStudioWorkspace();
      save();
    });
  });
}
function bindStudioSettingsNav(){
  const nav = $('studioSettingsNav');
  if(!nav || nav._bound) return;
  nav._bound = true;
  nav.querySelectorAll('[data-settings-work]').forEach(button => {
    button.addEventListener('click', () => {
      const next = button.dataset.settingsWork;
      if(!['select','quick','build'].includes(next)) return;
      STATE.ui = STATE.ui || {};
      STATE.ui.settings_work = next;
      arrangeStudioWorkspace();
      save();
    });
  });
}
function arrangeStudioWorkspace(){
  if(!STATE) return;
  bindStudioLibraryNav();
  bindStudioSettingsNav();
  const studio = (STATE.ui || {}).layout !== 'classic';

  const card = $('compareCard');
  const classicHome = $('compareClassicHome');
  const studioHome = $('studioCompareHome');
  const libraryNav = $('studioLibraryNav');
  const browse = $('studioLibraryBrowse');
  if(card && classicHome && studioHome && libraryNav && browse){
    const libraryWork = (STATE.ui || {}).library_work === 'compare' ? 'compare' : 'browse';
    const home = studio ? studioHome : classicHome;
    if(home.nextElementSibling !== card) home.insertAdjacentElement('afterend', card);

    libraryNav.classList.toggle('hidden', !studio);
    browse.classList.toggle('hidden', studio && libraryWork === 'compare');
    card.classList.toggle('hidden',
      studio && (document.body.dataset.mode !== 'library' || libraryWork !== 'compare'));
    libraryNav.querySelectorAll('[data-library-work]').forEach(button => {
      const on = button.dataset.libraryWork === libraryWork;
      button.classList.toggle('on', on);
      button.setAttribute('aria-selected', on ? 'true' : 'false');
      button.tabIndex = on ? 0 : -1;
    });
  }

  const settingsNav = $('studioSettingsNav');
  const settingsCards = {
    select: $('settingSelectCard'),
    quick: $('sceneQuickCard'),
    build: $('settingBuilderCard'),
  };
  if(settingsNav && Object.values(settingsCards).every(Boolean)){
    const savedSettingsWork = (STATE.ui || {}).settings_work;
    const settingsWork = ['select','quick','build'].includes(savedSettingsWork)
      ? savedSettingsWork : 'select';
    settingsNav.classList.toggle('hidden', !studio);
    Object.entries(settingsCards).forEach(([key, settingsCard]) => {
      settingsCard.classList.toggle('hidden', studio && key !== settingsWork);
    });
    settingsNav.querySelectorAll('[data-settings-work]').forEach(button => {
      const on = button.dataset.settingsWork === settingsWork;
      button.classList.toggle('on', on);
      button.setAttribute('aria-selected', on ? 'true' : 'false');
      button.tabIndex = on ? 0 : -1;
    });
  }
}
function setMode(m){
  document.body.dataset.mode = m;
  document.querySelectorAll('#modes button').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
  ['preview','settings','builder','library','system'].forEach(x =>
    $('v' + x[0].toUpperCase() + x.slice(1)).style.display = (x === m ? '' : 'none'));
  arrangeStudioWorkspace();
}
document.querySelectorAll('#modes button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
document.querySelectorAll('[data-mode-jump]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.modeJump)));
/* Alt+1~5 로 탭 이동. Alt 를 쓰는 이유 — 프롬프트 칸에서 숫자를 칠 수 있어야 한다 */
window.addEventListener('keydown', e => {
  if(!e.altKey || e.ctrlKey || e.metaKey) return;
  const i = ['1','2','3','4','5'].indexOf(e.key);
  if(i < 0) return;
  const b = document.querySelectorAll('#modes button')[i];
  if(b){ e.preventDefault(); setMode(b.dataset.mode); }
});

/* ── 베이스 프리셋 (그림체 파일) ── */
function paintActiveStyle(){
  const s = $('presetSel'); if(!s) return;
  const active = (STATE && STATE.style_name) || '';
  const idx = STYLES.findIndex(x => x.name === active);
  s.options[0].textContent = active && idx < 0
    ? `현재 그림체: ${active}` : '베이스 프리셋 불러오기...';
  s.value = idx >= 0 ? String(idx) : '';
  s.title = active ? `현재 그림체 묶음: ${active}` : '현재 값은 직접 편집한 상태입니다.';
}
function clearActiveStyle(){
  if(!STATE || !STATE.style_name) return;
  STATE.style_name = '';
  paintActiveStyle();
}
function styleSettingsFromUI(){
  return {
    model: $('pModel').value,
    cfg_scale: Number($('pScale').value),
    cfg_rescale: Number($('pRescale').value),
    steps: Number($('pSteps').value),
    sampler: $('pSampler').value,
    scheduler: $('pSched').value,
    variety: $('pVariety').value === 'on',
    width: Number($('pWidth').value) || STATE.width,
    height: Number($('pHeight').value) || STATE.height,
    uc_preset: Number($('pUc').value),
    quality_toggle: $('pQuality').value === 'on',
    smea: $('pSmea').value === 'on',
    smea_dyn: $('pSmeaDyn').value === 'on',
    dynamic_thresholding: $('pDynThr').value === 'on',
    uncond_scale: Number($('pUncond').value),
    controlnet_strength: Number($('pCtrl').value),
    prefer_brownian: $('pBrownian').value === 'on',
    deliberate_euler_ancestral_bug: $('pEulerBug').value === 'on',
    legacy_v3_extend: !!STATE.legacy_v3_extend
  };
}
function applyStyleSettings(raw){
  const p = raw || {};
  const first = (...keys) => {
    const key = keys.find(k => Object.prototype.hasOwnProperty.call(p, k));
    return key == null ? undefined : p[key];
  };
  const set = (key, value, cast) => {
    if(value === undefined || value === null || value === '') return;
    STATE[key] = cast ? cast(value) : value;
  };
  set('model', first('model'), String);
  set('cfg_scale', first('cfg_scale', 'scale'), Number);
  set('cfg_rescale', first('cfg_rescale'), Number);
  set('steps', first('steps'), Number);
  set('sampler', first('sampler'), String);
  set('scheduler', first('scheduler', 'noise_schedule'), String);
  set('variety', first('variety', 'variety_plus'), Boolean);
  set('width', first('width'), Number);
  set('height', first('height'), Number);
  set('uc_preset', first('uc_preset', 'ucPreset'), Number);
  set('quality_toggle', first('quality_toggle'), Boolean);
  set('smea', first('smea', 'sm'), Boolean);
  set('smea_dyn', first('smea_dyn', 'sm_dyn'), Boolean);
  set('dynamic_thresholding', first('dynamic_thresholding'), Boolean);
  set('uncond_scale', first('uncond_scale'), Number);
  set('controlnet_strength', first('controlnet_strength'), Number);
  set('prefer_brownian', first('prefer_brownian'), Boolean);
  set('deliberate_euler_ancestral_bug', first('deliberate_euler_ancestral_bug'), Boolean);
  set('legacy_v3_extend', first('legacy_v3_extend'), Boolean);
  paintParams();
}
function renderPresets(){
  const s = $('presetSel');
  s.innerHTML = '<option value="">베이스 프리셋 불러오기...</option>';
  STYLES.forEach((x,i) => { const o = document.createElement('option'); o.value = i; o.textContent = x.name; s.appendChild(o); });
  paintActiveStyle();
}
$('presetSel').addEventListener('change', () => {
  const i = $('presetSel').value;
  if(i === '') return;
  const st = STYLES[i];
  STATE.base_prompt = st.prompt; $('basePrompt').value = st.prompt;
  STATE.negative_prompt = st.negative || ''; $('negPrompt').value = STATE.negative_prompt;
  applyStyleSettings(st.settings);
  STATE.style_name = st.name;
  paintActiveStyle(); tokens(); save();
});
$('presetSave').addEventListener('click', async () => {
  const name = prompt('베이스 프리셋 이름 (프롬프트+네거티브+파라미터가 함께 저장):');
  if(!name) return;
  const r = await fetch('/api/style_save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, prompt: $('basePrompt').value, negative: $('negPrompt').value,
      settings: styleSettingsFromUI()})});
  const res = await r.json();
  if(res.ok){
    STYLES = res.styles; STATE.style_name = name;
    renderPresets(); renderLibrary(); save();
    alert(`그림체/${name}.json 저장됨`);
  }
  else alert(res.error || '저장 실패');
});

/* ── 캐릭터 슬롯 ── */
function renderSlots(){
  const h = $('slotList'); h.innerHTML = '';
  (STATE.char_slots || []).forEach((s,i) => {
    const el = document.createElement('div');
    el.className = 'slot';
    const on = s.enabled !== false;
    if(!on) el.style.opacity = '.55';
    el.innerHTML = `<div class="r1">
      <label class="sw" title="끄면 이 인물은 보내지 않습니다 (칸은 남습니다)">
        <input type="checkbox" data-sen="${i}" ${on ? 'checked' : ''}><span class="sl"></span></label>
      <input type="text" data-sf="name" data-si="${i}" placeholder="이름" value="${escA(s.name)}">
      <button class="danger" data-sdel="${i}">✕</button></div>
      <textarea data-sf="prompt" data-si="${i}" placeholder="girl, ... (외형 — 잘 안 바꾸는 것)">${esc(s.prompt)}</textarea>
      <!-- 의상을 따로 둔다 (NAIS2-Forge 와 같은 생각) — 외형은 그대로 두고 옷만 갈아입힐 수 있다.
           전송할 때 외형 뒤에 이어 붙는다. -->
      <input type="text" data-sf="outfit" data-si="${i}" placeholder="의상 (비워도 됨 · 외형 뒤에 붙습니다)" value="${escA(s.outfit || '')}">
      <input type="text" data-sf="negative" data-si="${i}" placeholder="이 인물 전용 네거티브" value="${escA(s.negative)}">
      <div class="posrow"><span class="hint">위치</span>
        <div class="posgrid" data-pos="${i}"></div>
        <input type="number" class="posnum" data-posx="${i}" min="0" max="1" step="0.01" title="x (0~1 자유값 — 격자 밖도 됩니다)">
        <input type="number" class="posnum" data-posy="${i}" min="0" max="1" step="0.01" title="y (0~1 자유값 — 격자 밖도 됩니다)">
        <span class="hint" data-poslabel="${i}"></span></div>`;
    h.appendChild(el);
  });
  drawPosGrids();
  h.querySelectorAll('[data-sf]').forEach(el => el.addEventListener('input', () => {
    STATE.char_slots[+el.dataset.si][el.dataset.sf] = el.value; tokens(); save();
  }));
  h.querySelectorAll('[data-sen]').forEach(x => x.addEventListener('change', () => {
    STATE.char_slots[+x.dataset.sen].enabled = x.checked;
    /* 켠 인물 수가 바뀌면 좌표·경고도 다시 (끈 인물은 보내지 않는다) */
    autoCoordsOnSecond(); renderSlots(); tokens(); save();
  }));
  h.querySelectorAll('[data-sdel]').forEach(b => b.addEventListener('click', () => {
    STATE.char_slots.splice(+b.dataset.sdel, 1);
    (STATE.char_centers || []).splice(+b.dataset.sdel, 1);   // 좌표도 같이 지운다
    autoCoordsOnSecond(); renderSlots(); tokens(); save();
  }));
  /* 좌표 숫자 칸 — 격자(5×5)는 빠른 선택용이고, 여기는 0~1 자유값.
     실측(라운드01): NAI 서버는 좌표를 격자로 반올림하지 않는다 — 0.05 차이도 반영된다.
     'change' 에만 묶는다 (입력 중 다시 그리면 커서를 잃는다). */
  h.querySelectorAll('[data-posx],[data-posy]').forEach(el => el.addEventListener('change', () => {
    const i = +(el.dataset.posx != null ? el.dataset.posx : el.dataset.posy);
    const axis = el.dataset.posx != null ? 'x' : 'y';
    let v = parseFloat(el.value);
    if(!isFinite(v)) v = 0.5;
    v = Math.min(1, Math.max(0, Math.round(v * 100) / 100));
    STATE.char_centers = STATE.char_centers || [];
    while(STATE.char_centers.length <= i) STATE.char_centers.push({x:0.5, y:0.5});
    STATE.char_centers[i] = Object.assign({x:0.5, y:0.5}, STATE.char_centers[i]);
    STATE.char_centers[i][axis] = v;
    /* 보정값을 칸에 바로 되쓴다 — drawPosGrids 는 포커스 중인 칸을 안 건드리는데
       change 는 포커스가 남은 채로도 오므로, 안 쓰면 화면 1.5 / 저장 1 처럼 어긋난다 */
    el.value = String(v);
    drawPosGrids(); save();
    if(!(STATE.use_coords)) flash('위치를 쓰려면 파라미터에서 [캐릭터 위치 좌표 사용]을 켜세요.');
  }));
  const lib = $('slotLib');
  lib.innerHTML = '<option value="">+ 라이브러리에서...</option>';
  (STATE.characters||[]).forEach(c => { const o = document.createElement('option'); o.value = c.id; o.textContent = c.name || '(무명)'; lib.appendChild(o); });
  if(window._paintCoords) window._paintCoords();   // 인물 수가 바뀌면 몸 붙음 경고도 다시
}
/* 공홈은 **인물을 둘째로 넣는 순간 좌표를 켠다**. 그래야 몸이 안 붙는다.
   NAIS2 는 V3 라 좌표 개념이 없어서 이 문제가 없었고, NAIS3 는 좌표를 쓰면서
   기본을 안 켜 둬서 몸이 붙었다. 우리는 공홈을 따라간다. */
/* 보낼 인물 = 켠 것 + 내용이 있는 것. 칸은 6명 넘게 둬도 된다. */
function activeSlotIdx(){
  /* 주석(#) 줄만 있는 칸은 '켠 인물'이 아니다 — 서버 slot_prompt 와 같은 규칙 (CQA-003) */
  return (STATE.char_slots || [])
    .map((s, i) => ({s, i}))
    .filter(x => x.s.enabled !== false
      && [x.s.prompt, x.s.outfit].some(v =>
        ((v || '').replace(/^[ \t]*#.*$/gm, '')).trim()))
    .map(x => x.i);
}
function autoCoordsOnSecond(){
  const n = activeSlotIdx().length;
  if(n < 2) return false;
  const first = !STATE.use_coords;
  if(first){
    STATE.use_coords = true;
    if($('pCoords')) $('pCoords').value = 'on';
  }
  /* ★ 인물이 늘 때 좌표도 따라가야 한다.
     안 그러면 셋째부터는 기본 0.5/0.5 를 써서 서로 겹치고, 좌표를 켜 둔 게 무의미해진다
     (2명 기준 0.3/0.7 에 멈춰 있던 것을 실측에서 잡았다).
     이미 손으로 고른 자리가 있으면 그건 건드리지 않고 **빈 칸만** 채운다. */
  /* ⚠ 좌표는 **칸 index** 로 저장한다 (껐다 켜도 자리가 유지되게).
     예전에는 `slice(0, n)` 으로 **켠 인물 수**만큼 잘라서, 꺼 둔 칸이 앞에 있으면
     뒤쪽 칸의 좌표가 통째로 날아갔다 (복제 후 좌표 소실 — Codex 재현 04:53).
     자를 게 아니라 **칸 수만큼 유지하고, 켠 칸의 빈 자리만** 채운다. */
  const idx = activeSlotIdx();
  const slots = (STATE.char_slots || []).length;
  const cs = (STATE.char_centers || []).slice(0, Math.max(slots, 0));
  while(cs.length < slots) cs.push(null);
  const auto = spreadCenters(n);
  const taken = new Set(cs.filter(Boolean).map(c => `${c.x},${c.y}`));
  idx.forEach((slotI, k) => {
    if(cs[slotI] && cs[slotI].x != null) return;      // 손으로 고른 자리는 보존
    const free = auto.find(a => !taken.has(`${a.x},${a.y}`)) || auto[k] || {x:0.5, y:0.5};
    cs[slotI] = free; taken.add(`${free.x},${free.y}`);
  });
  STATE.char_centers = cs.map(c => c || {x:0.5, y:0.5});
  return first;
}
/* 좌표가 서로 겹치는 인물이 있는지 (겹치면 분리가 안 된다) */
function coordsClash(){
  const idx = activeSlotIdx();
  if(idx.length < 2 || !STATE.use_coords) return false;
  const seen = new Set();
  for(const i of idx){
    const c = (STATE.char_centers || [])[i] || {x:0.5, y:0.5};
    const k = `${c.x ?? 0.5},${c.y ?? 0.5}`;
    if(seen.has(k)) return true;
    seen.add(k);
  }
  return false;
}
$('slotAdd').addEventListener('click', () => {
  (STATE.char_slots = STATE.char_slots || []).push({name:'', prompt:'', negative:''});
  if(autoCoordsOnSecond()) flash('인물이 둘이 되어 위치 지정을 켜고 좌우로 벌렸습니다 (공홈과 같은 동작).');
  renderSlots(); tokens(); save();
});
/* ── 진단 서랍 — 서버에서 먼저 redaction한 구조화 이벤트만 받는다 ── */
let DIAG_LAST = null;
async function diagLoad(){
  const box = $('diagOut'); if(!box) return;
  box.textContent = '읽는 중...';
  try{
    const r = await (await fetch('/api/diag?n=' + (($('diagN')||{}).value || 300)
      + (($('diagErrOnly')||{}).checked ? '&err=1' : ''))).json();
    if(!r.ok){ DIAG_LAST = null; box.textContent = r.error || '못 읽음'; return; }
    DIAG_LAST = r;
    box.textContent = r.lines.join(String.fromCharCode(10)) || '(기록 없음)';
    $('diagStat').textContent = `${r.events.length}건` + (r.errors != null ? ` · 오류/경고 ${r.errors}` : '');
    box.scrollTop = box.scrollHeight;
  }catch(e){ DIAG_LAST = null; box.textContent = String(e); }
}
if($('diagLoad')){
  $('diagLoad').addEventListener('click', diagLoad);
  ['diagErrOnly','diagN'].forEach(id => $(id) && $(id).addEventListener('change', diagLoad));
  $('diagCopy').addEventListener('click', () => {
    navigator.clipboard.writeText($('diagOut').textContent || '')
      .then(() => $('diagStat').textContent = '복사됨 ✓');
  });
  $('diagExport').addEventListener('click', () => {
    if(!DIAG_LAST){ $('diagStat').textContent = '먼저 불러오세요'; return; }
    const now = new Date();
    const pad2 = n => String(n).padStart(2, '0');
    const localDay = `${now.getFullYear()}-${pad2(now.getMonth()+1)}-${pad2(now.getDate())}`;
    const safe = {
      schema: DIAG_LAST.schema,
      exported_at: now.toISOString(),
      errors: DIAG_LAST.errors,
      events: DIAG_LAST.events
    };
    const blob = new Blob([JSON.stringify(safe, null, 2)], {type:'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nais-diagnostics-${localDay}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    $('diagStat').textContent = '안전 JSON 저장됨 ✓';
  });
}

/* 인물 칸 일괄 손질 (NAIS3 의 캐릭터 다중 선택·일괄 편집을 우리 구조로).
   칸이 여럿일 때 하나씩 누르는 수고를 줄인다. 켬/끔은 '보낼지'만 정하고 칸은 남는다. */
function slotsBulk(fn){
  /* ⚠ 좌표(char_centers)는 **칸 index** 로 짝지어져 있다. 칸 수가 안 바뀌는 동작
     (켜기/끄기·태그 주입)에서 자동 재배치를 부르면 손으로 잡아 둔 자리가 날아간다.
     칸 수가 실제로 바뀐 경우에만 자동 좌표를 손댄다 (Codex 재현 보고 04:53). */
  STATE.char_slots = STATE.char_slots || [];
  const before = STATE.char_slots.length;
  fn(STATE.char_slots);
  if(STATE.char_slots.length !== before) autoCoordsOnSecond();
  renderSlots(); tokens(); save();
}
if($('slotAllOn')) $('slotAllOn').addEventListener('click', () =>
  slotsBulk(ss => ss.forEach(s => s.enabled = true)));
if($('slotAllOff')) $('slotAllOff').addEventListener('click', () =>
  slotsBulk(ss => ss.forEach(s => s.enabled = false)));
if($('slotBulkAdd')) $('slotBulkAdd').addEventListener('click', () => {
  const t = prompt('켠 인물 칸의 외형 뒤에 붙일 태그 (콤마로 여러 개):');
  if(!t || !t.trim()) return;
  slotsBulk(ss => ss.forEach(s => {
    if(s.enabled === false) return;
    const cur = (s.prompt || '').trim().replace(/,$/, '');
    s.prompt = cur ? cur + ', ' + t.trim() : t.trim();
  }));
});
if($('slotDupAll')) $('slotDupAll').addEventListener('click', () => {
  slotsBulk(ss => {
    /* 칸을 복제하면 **좌표도 같은 자리에서 복제**해야 짝이 안 어긋난다.
       (예전엔 칸만 늘어나 뒤쪽 칸의 좌표가 밀렸다 — Codex 가 A/B/C 시퀀스로 잡음) */
    STATE.char_centers = STATE.char_centers || [];
    const copies = [], ctrs = [];
    ss.forEach((s, i) => {
      if(s.enabled === false) return;
      copies.push(Object.assign({}, s, {name: (s.name || '인물') + ' 사본'}));
      ctrs.push(Object.assign({x:0.5, y:0.5}, STATE.char_centers[i] || {}));
    });
    if(!copies.length){ flash('켠 인물 칸이 없습니다.'); return; }
    while(STATE.char_centers.length < ss.length) STATE.char_centers.push({x:0.5, y:0.5});
    ss.push(...copies);
    STATE.char_centers.push(...ctrs);
  });
});
if($('slotDelOff')) $('slotDelOff').addEventListener('click', () => {
  const off = (STATE.char_slots || []).filter(s => s.enabled === false).length;
  if(!off){ flash('꺼 둔 칸이 없습니다.'); return; }
  if(!confirm(`꺼 둔 칸 ${off}개를 지울까요? (좌표도 함께 지웁니다)`)) return;
  slotsBulk(ss => {
    const keep = [], ctrs = [];
    ss.forEach((s, i) => {
      if(s.enabled === false) return;
      keep.push(s); ctrs.push((STATE.char_centers || [])[i] || {x:0.5, y:0.5});
    });
    STATE.char_centers = ctrs;         // 좌표는 칸 index 라 같이 추려야 짝이 안 어긋난다
    ss.length = 0; ss.push(...keep);
  });
});
$('slotLib').addEventListener('change', () => {
  const c = (STATE.characters||[]).find(x => x.id === $('slotLib').value);
  if(c){ (STATE.char_slots = STATE.char_slots || []).push({name: c.name||'', prompt: c.female||'', negative: c.negative||''});
  if(autoCoordsOnSecond()) flash('인물이 둘이 되어 위치 지정을 켜고 좌우로 벌렸습니다 (공홈과 같은 동작).');
    renderSlots(); tokens(); save(); }
  $('slotLib').value = '';
});

/* ── 생성 ── */
const QUICK_QTY_MAX = 99;
function quickQty(value, notify=false){
  const raw = Number(value);
  const clean = Math.min(QUICK_QTY_MAX, Math.max(1, Number.isFinite(raw) ? Math.trunc(raw) : 1));
  if(notify && clean !== raw) flash(`빠른 생성 수량은 1~${QUICK_QTY_MAX}장으로 맞췄습니다.`);
  $('qty').value = clean;
  return clean;
}
$('qtyM').addEventListener('click', () => quickQty((+$('qty').value||1) - 1));
$('qtyP').addEventListener('click', () => quickQty((+$('qty').value||1) + 1, true));
$('qty').addEventListener('change', () => quickQty($('qty').value, true));
$('genBtn').addEventListener('click', async () => {
  await doSave();
  const n = quickQty($('qty').value, true);
  setMode('preview');
  for(let i = 0; i < n; i++){
    const r = await (await fetch('/api/generate_one', {method:'POST'})).json();
    if(!r.ok){ alert(r.error || '생성 실패'); return; }
    await waitIdle();
  }
});
async function waitIdle(){
  for(;;){
    await new Promise(r => setTimeout(r, 900));
    const s = await (await fetch('/status.json', {cache:'no-store'})).json();
    if(!s.running) return;
  }
}
$('batchBtn').addEventListener('click', async () => {
  await doSave();
  const r = await (await fetch('/api/start', {method:'POST'})).json();
  if(!r.ok){ alert(r.error || '시작할 수 없습니다.'); return; }
  setMode('preview');
});

/* ── 세팅 ── */
function stState(name){
  STATE.setting_state = STATE.setting_state || {};
  const s = STATE.setting_state[name] = STATE.setting_state[name] || {use:true, selected:[], opts:{}, cast:[]};
  s.opts = s.opts || {}; s.selected = s.selected || []; s.cast = s.cast || [];
  return s;
}
/* 어느 세팅이 펼쳐져 있었는지 기억한다 — 단계 칩 하나 눌렀다고 다시 접히면
   자리를 잃는다 (대표 그림도 숨은 채라 안 뜬다). */
const SET_OPEN = new Set();
function renderSettings(){
  const host = $('setList');
  host.querySelectorAll('[data-sb]').forEach(el => {
    if(!el.classList.contains('hidden')) SET_OPEN.add(el.dataset.sb);
    else SET_OPEN.delete(el.dataset.sb);
  });
  host.innerHTML = '';
  $('setCount').textContent = `${SETTINGS.length}개`;
  if(!SETTINGS.length){
    host.innerHTML = `<div class="row" style="padding:18px;text-align:center;">
      <b>아직 넣은 세팅이 없습니다.</b>
      <p class="hint" style="margin:7px 0 10px;">본체와 자료는 분리되어 있습니다.
      기본자료팩을 자료 탭에 넣거나, 위의 새 세팅으로 직접 만드세요.</p>
      <button id="setGoData">기본자료팩 넣으러 가기</button></div>`;
    $('setGoData').addEventListener('click', () => setMode('library'));
  }
  SETTINGS.forEach(st => {
    const s = stState(st.name);
    const tot = st.groups.reduce((a,g)=>a+g.ids.length,0);
    const sel = new Set(s.selected);
    const sec = document.createElement('div');
    sec.className = 'sec';
    const mb = {'남녀':'👫 남녀','백합':'👭 여×여','단독':'👤 단독'}[st.mode] || st.mode;
    sec.innerHTML = `<div class="sec-head" data-sh="${escA(st.name)}">
        <label class="sw"><input type="checkbox" data-suse="${escA(st.name)}" ${s.use===false?'':'checked'}><span class="sl"></span></label>
        <span class="nm">${esc(st.name)}</span><span class="badge">${mb}</span>
        <span class="sub">${st.groups.length}세트 · ${tot}장</span>
        <span class="cnt" data-scnt="${escA(st.name)}"></span></div>
      <div class="sec-body${SET_OPEN.has(st.name) ? '' : ' hidden'}" data-sb="${escA(st.name)}"></div>`;
    const b = sec.querySelector('.sec-body');

    b.insertAdjacentHTML('beforeend', `<div class="field"><label>전용 캐스트 (각자 따로 전체 씬 생성 · 비우면 왼쪽 [캐릭터] 사용)</label>
      <div data-cast="${escA(st.name)}"></div>
      <div class="bar" style="margin:5px 0 0;"><button data-castadd="${escA(st.name)}">+ 직접 입력</button>
      <select data-castlib="${escA(st.name)}" style="flex:1;"><option value="">+ 라이브러리에서...</option></select></div></div>`);

    const role = st.role || {};
    if(st.mode === '남녀' || st.mode === '백합'){
      const t = st.mode === '남녀' ? '상대역(남자)' : '상대역(파트너)';
      b.insertAdjacentHTML('beforeend', `<div class="field"><label>${t} — 이 세팅 파일에 저장됩니다</label>
        <textarea data-role="${escA(st.name)}" data-rf="외형" style="min-height:44px;">${esc(role['외형']||'')}</textarea></div>
        <div class="grid3">
          ${st.mode==='백합' ? `<div class="field"><label>상대역 착의</label><input type="text" data-role="${escA(st.name)}" data-rf="착의" value="${escA(role['착의']||'')}"></div>` : ''}
          <div class="field"><label>상대역 네거티브</label><input type="text" data-role="${escA(st.name)}" data-rf="네거티브" value="${escA(role['네거티브']||'')}"></div>
          ${st.mode==='남녀' ? `<div class="field"><label>상대역 의상</label><input type="text" data-role="${escA(st.name)}" data-rf="의상" value="${escA(role['의상']||'')}"></div>` : ''}
        </div>`);
    }

    const oks = Object.keys(st.options||{}).filter(k=>!k.startsWith('_'));
    const extra = st.mode === '남녀' ? ['남자옷'] : (st.mode === '백합' ? ['옷진행'] : []);
    if(oks.length || extra.length){
      let g = '<div class="grid3">';
      extra.forEach(k => {
        const vals = k === '남자옷' ? ['나체','착의','탈의진행'] : ['진행','나체'];
        g += `<div class="field"><label>${k}</label><select data-sopt="${escA(st.name)}" data-on="${k}">` +
          vals.map(v => `<option${(s.opts[k]||vals[0])===v?' selected':''}>${v}</option>`).join('') + '</select></div>';
      });
      oks.forEach(ok => {
        const names = Object.keys(st.options[ok]||{});
        g += `<div class="field"><label>${esc(ok)}</label><select data-sopt="${escA(st.name)}" data-on="${escA(ok)}">
          <option value="">없음</option>` + names.map(n => `<option${s.opts[ok]===n?' selected':''}>${esc(n)}</option>`).join('') + '</select></div>';
      });
      b.insertAdjacentHTML('beforeend', g + '</div>' +
        (oks.length ? `<div class="bar"><button data-optedit="${escA(st.name)}">옵션 항목 편집 (보기·수정·추가·삭제)</button></div>` : ''));
    }

    const hasMood = st.groups.some(g => g.mood);
    /* 단계 선택 — 세트를 가로로 자른다 ("전 체위의 사정 컷만").
       세트마다 단계 수가 다를 수 있으니 가장 긴 세트를 기준으로 칩을 만든다. */
    const maxStage = st.groups.reduce((a,g) => Math.max(a, g.ids.length), 1);
    const stg = new Set((s.stages || []).map(Number));
    const stageRow = maxStage > 1 ? `<div class="filterbar" style="margin-top:6px;">
        <span class="hint" style="white-space:nowrap;">단계</span>
        ${Array.from({length: maxStage}, (_, i) => `<span class="chip${stg.has(i+1)?' on':''}"
           data-sstage="${escA(st.name)}" data-st="${i+1}">${i+1}</span>`).join('')}
        <span class="hint" data-sstagemsg="${escA(st.name)}">${stg.size
          ? `${[...stg].sort((a,b)=>a-b).join('·')}번 컷만 (세트당 ${stg.size}장)`
          : '전 단계'}</span>
        ${stg.size ? `<button data-sstageall="${escA(st.name)}">전 단계로</button>` : ''}
      </div>` : '';
    b.insertAdjacentHTML('beforeend', `<div class="bar" style="margin-top:6px;">
      <button data-sall="${escA(st.name)}">전체 선택</button><button data-snone="${escA(st.name)}">전체 해제</button>
      ${hasMood ? `<button data-smood="${escA(st.name)}|가벼움">가벼움만</button><button data-smood="${escA(st.name)}|진함">진함만</button>` : ''}</div>
      ${stageRow}
      <div class="filterbar" style="margin-top:6px;">
        <input type="text" data-sfind="${escA(st.name)}" placeholder="🔍 세트 이름으로 찾기 (예: 사우스폴, A01)">
        <label class="hint"><input type="checkbox" data-sonly="${escA(st.name)}"> 켠 것만</label>
        <span class="n" data-sfound="${escA(st.name)}"></span>
      </div>`);

    const byCat = {};
    st.groups.forEach(g => (byCat[g.cat||''] = byCat[g.cat||'']||[]).push(g));
    Object.keys(byCat).sort().forEach(cat => {
      if(cat) b.insertAdjacentHTML('beforeend', `<div class="tag" style="margin:9px 0 3px;">${esc(cat)} · ${esc(((st.category_meta||{})[cat]||{}).name||'')}</div>`);
      const gr = document.createElement('div'); gr.className = 'items';
      byCat[cat].forEach(g => {
        const it = document.createElement('label'); it.className = 'item';
        const rep = (s.reserve || {})[g.id] || 1;
        it.dataset.name = (g.label || '').toLowerCase();
        it.dataset.on = sel.has(g.id) ? '1' : '0';
        it.innerHTML = `<input type="checkbox" data-ssel="${escA(st.name)}" data-id="${g.id}" ${sel.has(g.id)?'checked':''}>
          <span>${esc(g.label)}${g.mood==='진함'?' 🔥':''}${g.ids.length>1?` (${g.ids.length})`:''}</span>
          <input type="number" class="rep" data-srep="${escA(st.name)}" data-id="${g.id}"
            value="${rep}" min="1" max="20" title="이 세트를 몇 벌 뽑을지 (기본 1벌)"
            style="width:34px;padding:2px 3px;font-size:var(--fs-2xs);text-align:center;">
          <span class="ed" data-sedit="${escA(st.name)}" data-ids="${g.ids.join(',')}">✎</span>
          <span class="ed" data-sdup="${escA(st.name)}" data-id="${g.id}"
            title="이 세트를 복제 (씬을 새 번호로 복사)">⧉</span>`;
        gr.appendChild(it);
      });
      b.appendChild(gr);
    });
    host.appendChild(sec);
  });
  bindSettings();
  /* 목록을 다시 그리면 붙여 둔 대표 그림이 날아간다. 켜져 있으면 다시 붙인다. */
  if($('setThumbs') && $('setThumbs').checked) loadSetThumbs();
}

function bindSettings(){
  const h = $('setList');
  h.querySelectorAll('[data-sh]').forEach(x => x.addEventListener('click', e => {
    if(e.target.tagName === 'INPUT' || e.target.closest('.sw')) return;
    const bd = h.querySelector(`[data-sb="${CSS.escape(x.dataset.sh)}"]`);
    bd.classList.toggle('hidden');
    bd.classList.contains('hidden') ? SET_OPEN.delete(x.dataset.sh) : SET_OPEN.add(x.dataset.sh);
    if(!bd.classList.contains('hidden') && $('setThumbs') && $('setThumbs').checked) loadSetThumbs();
  }));
  h.querySelectorAll('[data-suse]').forEach(x => x.addEventListener('change', () => {
    stState(x.dataset.suse).use = x.checked; tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-ssel]').forEach(x => x.addEventListener('change', () => {
    const s = stState(x.dataset.ssel), id = +x.dataset.id;
    s.selected = s.selected.filter(v => v !== id);
    if(x.checked) s.selected.push(id);
    tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-sall]').forEach(b => b.addEventListener('click', () => {
    const st = SETTINGS.find(s => s.name === b.dataset.sall);
    stState(st.name).selected = st.groups.map(g => g.id);
    h.querySelectorAll(`[data-ssel="${CSS.escape(st.name)}"]`).forEach(c => c.checked = true);
    tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-snone]').forEach(b => b.addEventListener('click', () => {
    stState(b.dataset.snone).selected = [];
    h.querySelectorAll(`[data-ssel="${CSS.escape(b.dataset.snone)}"]`).forEach(c => c.checked = false);
    tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-smood]').forEach(b => b.addEventListener('click', () => {
    const [n, m] = b.dataset.smood.split('|');
    const st = SETTINGS.find(s => s.name === n);
    const ids = st.groups.filter(g => g.mood === m).map(g => g.id);
    stState(n).selected = ids;
    h.querySelectorAll(`[data-ssel="${CSS.escape(n)}"]`).forEach(c => c.checked = ids.includes(+c.dataset.id));
    tokens(); save(); counts();
  }));
  /* 세트 복제 — 씬을 새 번호로 복사해 세팅 파일에 넣는다 */
  h.querySelectorAll('[data-sdup]').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation(); e.preventDefault();
    const name = b.dataset.sdup;
    const r = await (await fetch('/api/setting_dup', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, id: +b.dataset.id})})).json();
    if(!r.ok){ $('setMsg').textContent = r.error || '복제 실패'; return; }
    $('setMsg').textContent = `세트 복제 ✓ (씬 ${r.count}개 · ${r.new_id}번부터)`;
    await reloadConfig();      // 세팅 파일이 바뀌었으니 목록을 다시 받는다
  }));
  /* 단계 칩 — 켜진 것이 하나도 없으면 '전 단계' 로 돌아간다 */
  h.querySelectorAll('[data-sstage]').forEach(c => c.addEventListener('click', () => {
    const s = stState(c.dataset.sstage), n = +c.dataset.st;
    const cur = new Set((s.stages || []).map(Number));
    cur.has(n) ? cur.delete(n) : cur.add(n);
    s.stages = [...cur].sort((a, b) => a - b);
    save(); renderSettings(); tokens(); counts();
  }));
  h.querySelectorAll('[data-sstageall]').forEach(b => b.addEventListener('click', () => {
    stState(b.dataset.sstageall).stages = [];
    save(); renderSettings(); tokens(); counts();
  }));
  h.querySelectorAll('[data-sopt]').forEach(x => x.addEventListener('change', () => {
    stState(x.dataset.sopt).opts[x.dataset.on] = x.value; save();
  }));
  h.querySelectorAll('[data-role]').forEach(x => x.addEventListener('input', () => {
    const n = x.dataset.role;
    clearTimeout(window['rt_'+n]);
    window['rt_'+n] = setTimeout(async () => {
      const role = {};
      h.querySelectorAll(`[data-role="${CSS.escape(n)}"]`).forEach(y => role[y.dataset.rf] = y.value);
      await fetch('/api/role_save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({setting:n, role})});
    }, 600);
  }));
  h.querySelectorAll('[data-sedit]').forEach(b => b.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation();
    openScene(b.dataset.sedit, b.dataset.ids.split(',').map(Number));
  }));
  /* 세트 이름 찾기 — 565개를 스크롤로 훑지 않아도 되게 */
  h.querySelectorAll('[data-sfind]').forEach(inp => {
    const name = inp.dataset.sfind;
    const apply = () => {
      const q = (inp.value || '').trim().toLowerCase();
      const onlyOn = (h.querySelector(`[data-sonly="${CSS.escape(name)}"]`) || {}).checked;
      const body = h.querySelector(`[data-sb="${CSS.escape(name)}"]`);
      let shown = 0, total = 0;
      body.querySelectorAll('.items > .item').forEach(it => {
        total++;
        const okQ = !q || (it.dataset.name || '').includes(q);
        const okOn = !onlyOn || it.dataset.on === '1';
        const ok = okQ && okOn;
        it.style.display = ok ? '' : 'none';
        if(ok) shown++;
      });
      // 결과가 없는 계열 헤더는 숨긴다
      body.querySelectorAll('.items').forEach(gr => {
        const any = [...gr.children].some(c => c.style.display !== 'none');
        gr.style.display = any ? '' : 'none';
        const head = gr.previousElementSibling;
        if(head && head.classList.contains('tag')) head.style.display = any ? '' : 'none';
      });
      const f = h.querySelector(`[data-sfound="${CSS.escape(name)}"]`);
      if(f) f.textContent = (q || onlyOn) ? `${shown} / ${total}개` : '';
    };
    inp.addEventListener('input', apply);
    const only = h.querySelector(`[data-sonly="${CSS.escape(name)}"]`);
    if(only) only.addEventListener('change', apply);
  });
  /* 세트별 예약 매수 */
  h.querySelectorAll('[data-srep]').forEach(inp => {
    inp.addEventListener('click', e => e.preventDefault());   // 라벨 클릭으로 체크 토글 방지
    inp.addEventListener('input', () => {
      const st = stState(inp.dataset.srep);
      st.reserve = st.reserve || {};
      const v = Math.max(1, Math.min(20, Number(inp.value) || 1));
      if(v === 1) delete st.reserve[inp.dataset.id]; else st.reserve[inp.dataset.id] = v;
      save(); counts();
    });
  });
  h.querySelectorAll('[data-optedit]').forEach(b => b.addEventListener('click', () => openOpts(b.dataset.optedit)));
  h.querySelectorAll('[data-cast]').forEach(el => renderCast(el.dataset.cast));
  h.querySelectorAll('[data-castadd]').forEach(b => b.addEventListener('click', () => {
    stState(b.dataset.castadd).cast.push({name:'', prompt:'', negative:''});
    renderCast(b.dataset.castadd); tokens(); save();
  }));
  h.querySelectorAll('[data-castlib]').forEach(sel => {
    (STATE.characters||[]).forEach(c => { const o = document.createElement('option'); o.value = c.id; o.textContent = c.name||'(무명)'; sel.appendChild(o); });
    sel.addEventListener('change', () => {
      const c = (STATE.characters||[]).find(x => x.id === sel.value);
      if(c){ stState(sel.dataset.castlib).cast.push({name:c.name||'', prompt:c.female||'', negative:c.negative||''});
        renderCast(sel.dataset.castlib); tokens(); save(); }
      sel.value = '';
    });
  });
  counts();
}
function counts(){
  SETTINGS.forEach(st => {
    const s = stState(st.name); const sel = new Set(s.selected);
    const rep = s.reserve || {};
    const stg = new Set((s.stages || []).map(Number));
    let im = 0;
    st.groups.forEach(g => {
      if(!sel.has(g.id)) return;
      const cuts = stg.size ? g.ids.filter((_, i) => stg.has(i + 1)).length : g.ids.length;
      im += cuts * (rep[g.id] || 1);
    });
    const el = document.querySelector(`[data-scnt="${CSS.escape(st.name)}"]`);
    if(el) el.textContent = s.selected.length ? `${s.selected.length}세트 · ${im}장` : '';
  });
}
function renderCast(name){
  const host = document.querySelector(`[data-cast="${CSS.escape(name)}"]`);
  if(!host) return;
  const s = stState(name);
  host.innerHTML = '';
  s.cast.forEach((c,i) => {
    const el = document.createElement('div'); el.className = 'slot';
    el.innerHTML = `<div class="r1"><input type="text" data-cf="name" data-ci="${i}" placeholder="이름" value="${escA(c.name)}">
      <button class="danger" data-cdel="${i}">✕</button></div>
      <textarea data-cf="prompt" data-ci="${i}" placeholder="girl, ...">${esc(c.prompt)}</textarea>
      <input type="text" data-cf="negative" data-ci="${i}" placeholder="전용 네거티브" value="${escA(c.negative)}">`;
    host.appendChild(el);
  });
  host.querySelectorAll('[data-cf]').forEach(el => el.addEventListener('input', () => {
    s.cast[+el.dataset.ci][el.dataset.cf] = el.value; tokens(); save();
  }));
  host.querySelectorAll('[data-cdel]').forEach(b => b.addEventListener('click', () => {
    s.cast.splice(+b.dataset.cdel, 1); renderCast(name); tokens(); save();
  }));
}

/* ── 씬 프리셋 ── */
function renderScenePresets(){
  const s = $('scenePreset');
  s.innerHTML = '<option value="">씬 프리셋 불러오기...</option>';
  SCENE_PRESETS.forEach((p,i) => { const o = document.createElement('option'); o.value = i; o.textContent = p.name; s.appendChild(o); });
}
$('scenePreset').addEventListener('change', async () => {
  const i = $('scenePreset').value; if(i === '') return;
  Object.assign(STATE, SCENE_PRESETS[i].data);
  await doSave(); location.reload();
});
$('scenePresetSave').addEventListener('click', async () => {
  const name = prompt('씬 프리셋 이름:'); if(!name) return;
  await doSave();
  const r = await (await fetch('/api/sceneset_save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})})).json();
  if(r.ok){ SCENE_PRESETS = r.scene_presets; renderScenePresets(); alert('저장됨'); } else alert(r.error);
});

/* ── img2img · 인페인트 ─────────────────────────────────────────────
   마스크는 흰색이 '다시 그릴 곳'. NAI 는 64 배수 크기를 원하므로 맞춰서 보낸다. */
let I2I = {img:null, painting:false, erase:false, undo:[]};
function i2iLoad(file){
  const fr = new FileReader();
  fr.onload = () => {
    const im = new Image();
    im.onload = () => {
      I2I.img = im;
      const w = Math.max(64, Math.floor(im.width / 64) * 64);
      const h = Math.max(64, Math.floor(im.height / 64) * 64);
      const b = $('i2iBase'), m = $('i2iMask');
      b.width = m.width = w; b.height = m.height = h;
      b.getContext('2d').drawImage(im, 0, 0, w, h);
      m.getContext('2d').clearRect(0, 0, w, h);
      I2I.undo = [];
      $('i2iStage').classList.remove('hidden');
      i2iZoom();
      $('i2iMsg').textContent = `${im.width}×${im.height} → ${w}×${h} 로 맞춰 보냅니다 (NAI 는 64 배수만 받습니다)`;
      i2iMode();
      if(window.i2iCostRefresh) window.i2iCostRefresh();
    };
    im.src = fr.result;
  };
  fr.readAsDataURL(file);
}
function i2iPainted(){
  const m = $('i2iMask'); if(!m.width) return false;
  const d = m.getContext('2d').getImageData(0, 0, m.width, m.height).data;
  for(let i = 3; i < d.length; i += 4) if(d[i] > 8) return true;
  return false;
}
function i2iMode(){
  const painted = i2iPainted();
  /* 강도 상한이 모드마다 다르다.
     인페인트는 1.00 까지 쓸 수 있다 (칠한 곳을 완전히 새로 그림).
     img2img 는 0.99 가 끝이다 — 1.00 이면 원본을 아예 안 보게 되어 NAI 가 막는다. */
  const cap = painted ? 1 : 0.99;
  const sl = $('i2iStrength');
  sl.max = String(cap);
  /* ⚠ max 를 바꾸면 브라우저가 value 를 **먼저** 잘라낸다.
     그래서 '넘쳤나' 를 따로 재면 안 걸린다 — 표시는 늘 현재 값으로 맞춘다. */
  $('i2iStrengthN').textContent = Number(sl.value).toFixed(2);
  $('i2iMode').textContent = (painted
    ? '칠한 곳만 다시 그림 → 인페인트 (강도 1.00 까지)'
    : '칠하지 않음 → img2img (전체를 다시 그림 · 강도 0.99 까지)');
  if(window.i2iCostRefresh) window.i2iCostRefresh();   // 모드가 바뀌면 비용도 (CQA-008)
}
function i2iZoom(){
  const b = $('i2iBase'), m = $('i2iMask');
  if(!b.width) return;
  const z = Number($('i2iZoom').value) || 1;
  const w = Math.round(b.width * z), h = Math.round(b.height * z);
  b.style.width = m.style.width = w + 'px';
  b.style.height = m.style.height = h + 'px';
}
if($('i2iDrop')){
  const m = $('i2iMask');
  const at = e => {
    const r = m.getBoundingClientRect();
    return [(e.clientX - r.left) * (m.width / r.width), (e.clientY - r.top) * (m.height / r.height)];
  };
  const dab = (x, y) => {
    const c = m.getContext('2d');
    /* 지우개는 합성 모드만 바꾼다 — 칠한 자리를 부분만 파낸다 */
    c.globalCompositeOperation = I2I.erase ? 'destination-out' : 'source-over';
    c.fillStyle = '#fff'; c.beginPath();
    c.arc(x, y, Number($('i2iBrush').value) / 2, 0, Math.PI * 2); c.fill();
    c.globalCompositeOperation = 'source-over';
  };
  /* 붓질 하나를 시작할 때 직전 상태를 쌓아 둔다 → 이어서 고쳐 그릴 수 있다
     (예전엔 지우면 전부 날아가서 처음부터 다시 칠해야 했다) */
  const pushUndo = () => {
    try{
      I2I.undo.push(m.getContext('2d').getImageData(0, 0, m.width, m.height));
      if(I2I.undo.length > 20) I2I.undo.shift();
    }catch(e){}
  };
  m.addEventListener('pointerdown', e => {
    pushUndo(); I2I.painting = true; m.setPointerCapture(e.pointerId); dab(...at(e));
  });
  m.addEventListener('pointermove', e => { if(I2I.painting) dab(...at(e)); });
  ['pointerup','pointercancel','pointerleave'].forEach(ev =>
    m.addEventListener(ev, () => { if(I2I.painting){ I2I.painting = false; i2iMode(); } }));
  $('i2iUndo').addEventListener('click', () => {
    const prev = I2I.undo.pop();
    if(!prev){ $('i2iMsg').textContent = '되돌릴 붓질이 없습니다.'; return; }
    m.getContext('2d').putImageData(prev, 0, 0); i2iMode();
  });
  window.addEventListener('keydown', e => {
    if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && $('i2iStage')
       && !$('i2iStage').classList.contains('hidden')
       && !/INPUT|TEXTAREA|SELECT/.test((document.activeElement||{}).tagName || '')){
      e.preventDefault(); $('i2iUndo').click();
    }
  });
  $('i2iErase').addEventListener('click', () => {
    I2I.erase = !I2I.erase;
    $('i2iErase').textContent = I2I.erase ? '🖌️ 붓으로' : '🧽 지우개';
    $('i2iErase').style.borderColor = I2I.erase ? 'var(--accent)' : '';
  });
  $('i2iZoom').addEventListener('change', i2iZoom);
  $('i2iClear').addEventListener('click', () => {
    pushUndo();
    m.getContext('2d').clearRect(0, 0, m.width, m.height); i2iMode();
  });
  $('i2iBrush').addEventListener('input', () => $('i2iBrushN').textContent = $('i2iBrush').value + 'px');
  $('i2iStrength').addEventListener('input', () =>
    $('i2iStrengthN').textContent = Number($('i2iStrength').value).toFixed(2));
  $('i2iDrop').addEventListener('click', () => $('i2iFile').click());
  $('i2iDrop2').addEventListener('click', () => $('i2iFile').click());
  $('i2iFile').addEventListener('change', () => {
    if($('i2iFile').files[0]) i2iLoad($('i2iFile').files[0]);
    $('i2iFile').value = '';
  });
  ['dragover','dragenter'].forEach(ev => $('i2iDrop').addEventListener(ev, e => {
    e.preventDefault(); $('i2iDrop').style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => $('i2iDrop').addEventListener(ev, e => {
    e.preventDefault(); $('i2iDrop').style.borderColor = ''; }));
  $('i2iDrop').addEventListener('drop', e => {
    const f = [...(e.dataTransfer.files || [])].find(x => /image\/(png|webp)/.test(x.type));
    if(f) i2iLoad(f);
  });
  /* 원본 그림을 쓰는 작업은 Opus 무료가 아니다 — 실행 버튼 옆에 실제 비용을 띄운다 (CQA-008) */
  window.i2iCostRefresh = async () => {
    const el = $('i2iCost');
    if(!el || !I2I.img) return;
    const painted = i2iPainted();
    const b = $('i2iBase');
    const w = Math.max(64, Math.floor(b.width / 64) * 64), h = Math.max(64, Math.floor(b.height / 64) * 64);
    try{
      const r = await (await fetch('/api/anlas', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({count:1, mode: painted ? 'infill' : 'img2img', width:w, height:h,
          strength: Number($('i2iStrength').value)})})).json();
      if(r.ok) el.textContent = r.est.total > 0
        ? `💰 ${r.est.total} Anlas (${painted ? '인페인트' : 'img2img'} — 원본을 쓰면 무료가 아닙니다)`
        : `${painted ? '인페인트' : 'img2img'} — ${r.est.why}`;
    }catch(e){}
  };
  if($('i2iStrength')) $('i2iStrength').addEventListener('change', () => window.i2iCostRefresh());
  $('i2iGo').addEventListener('click', async () => {
    if(!I2I.img){ $('i2iMsg').textContent = '먼저 그림을 넣어주세요.'; return; }
    const painted = i2iPainted();
    /* 마스크는 흑백 PNG 로 보낸다 — 칠한 곳이 흰색 */
    let mask = null;
    if(painted){
      const t = document.createElement('canvas');
      t.width = m.width; t.height = m.height;
      const c = t.getContext('2d');
      c.fillStyle = '#000'; c.fillRect(0, 0, t.width, t.height);
      c.drawImage(m, 0, 0);
      mask = t.toDataURL('image/png');
    }
    $('i2iMsg').textContent = (painted ? '인페인트' : 'img2img') + ' 보내는 중...';
    const r = await (await fetch('/api/i2i', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({image: $('i2iBase').toDataURL('image/png'), mask,
        strength: Number($('i2iStrength').value)})})).json();
    $('i2iMsg').textContent = r.ok
      ? `${r.mode} 시작 (${r.width}×${r.height}) — 위 미리보기에 나옵니다`
      : (r.error || '실패');
  });
}

/* ── 생성물 탐색기 · 선별 · 비교함 ──────────────────────────────────
   원본 파일은 옮기지 않는다. 선별·즐겨찾기는 경로에 붙는 이름표(선별.json)다. */
const EXP_CHUNK = 120;
let EXP = {dir:'', files:[], dirs:[], total:0, loading:false,
  loadSeq:0, picked:new Set(), fav:new Set(), cmp:new Set(), open:-1,
  folders:{}, ranks:{}, ratings:{}, tags:{}};
function expListUrl(dir, offset=0){
  const q = new URLSearchParams({
    dir: dir ?? EXP.dir, limit: String(EXP_CHUNK), offset: String(offset)
  });
  if($('expOnlyPick').checked) q.set('only_pick', '1');
  if($('expOnlyFav').checked) q.set('only_fav', '1');
  return '/api/out_list?' + q.toString();
}
async function expLoad(dir){
  /* 폴더·필터를 빨리 바꾸면 이전의 느린 응답이 나중 상태를 덮을 수 있다.
     요청 세대를 올려 **마지막 선택의 응답만** 적용한다. */
  const seq = ++EXP.loadSeq;
  EXP.loading = true;
  let r;
  try{
    r = await (await fetch(expListUrl(dir ?? EXP.dir, 0))).json();
  }catch(e){
    if(seq === EXP.loadSeq){ EXP.loading = false; $('expStat').textContent = String(e); }
    return;
  }
  if(seq !== EXP.loadSeq) return;
  EXP.loading = false;
  if(!r.ok){ $('expStat').textContent = r.error || '못 읽음'; return; }
  EXP.dir = r.dir; EXP.files = r.files; EXP.dirs = r.dirs;
  EXP.total = Number.isFinite(r.total) ? r.total : r.files.length;
  EXP.picked = new Set(r.picked); EXP.fav = new Set(r.fav); EXP.ranks = r.ranks || {};
  EXP.folders = r.folders || {}; EXP.ratings = r.ratings || {}; EXP.tags = r.tags || {};
  $('expPath').textContent = 'output/' + (r.dir ? r.dir + '/' : '');
  /* 최상위에서는 위로 갈 곳이 없다 — 눌려도 아무 일 없으면 고장으로 보인다 */
  const up = $('expUp');
  if(up){ up.disabled = !r.dir; up.title = r.dir ? '상위 폴더' : '이미 최상위입니다'; }
  expDraw();
}
async function expFetchMore(draw=true){
  if(EXP.loading || EXP.files.length >= EXP.total) return false;
  const seq = EXP.loadSeq;
  EXP.loading = true;
  let r;
  try{
    r = await (await fetch(expListUrl(EXP.dir, EXP.files.length))).json();
  }catch(e){
    if(seq === EXP.loadSeq){ EXP.loading = false; $('expStat').textContent = String(e); }
    return false;
  }
  if(seq !== EXP.loadSeq) return false;
  EXP.loading = false;
  if(!r.ok){ $('expStat').textContent = r.error || '못 읽음'; return false; }
  const seen = new Set(EXP.files.map(f => f.path));
  const added = (r.files || []).filter(f => !seen.has(f.path));
  EXP.files.push(...added);
  EXP.total = Number.isFinite(r.total) ? r.total : EXP.files.length;
  EXP.vis = expVisible();
  if(draw) expChunk();
  return added.length > 0;
}
async function expEnsureAll(){
  while(EXP.files.length < EXP.total){
    const before = EXP.files.length;
    if(!await expFetchMore(false) || EXP.files.length === before) break;
  }
  EXP.vis = expVisible();
  return EXP.vis;
}
function expVisible(){
  let f = EXP.files;
  if($('expOnlyPick').checked) f = f.filter(x => EXP.picked.has(x.path));
  if($('expOnlyFav').checked) f = f.filter(x => EXP.fav.has(x.path));
  const group = ($('expGroupFilter') || {}).value || '';
  if(group){
    const members = new Set(EXP.folders[group] || []);
    f = f.filter(x => members.has(x.path));
  }
  return f;
}
function expPaintGroups(){
  const select = $('expGroupFilter'); if(!select) return;
  const before = select.value;
  const names = Object.keys(EXP.folders || {}).sort((a,b) => a.localeCompare(b));
  select.innerHTML = '<option value="">전체 보기</option>'
    + names.map(name => `<option value="${escA(name)}">${esc(name)}`
      + ` (${(EXP.folders[name] || []).length.toLocaleString()})</option>`).join('');
  select.value = names.includes(before) ? before : '';
}
function expDraw(){
  const dh = $('expDirs'); dh.innerHTML = '';
  EXP.dirs.forEach(d => {
    const b = document.createElement('button');
    b.textContent = `📁 ${d.name} (${d.count})`;
    b.addEventListener('click', () => expLoad(d.path));
    dh.appendChild(b);
  });
  const g = $('expGrid'); g.innerHTML = '';
  g.style.setProperty('--ecard', $('expSize').value + 'px');
  expPaintGroups();
  const vis = expVisible();
  $('expCount').textContent = `${EXP.total}장`;
  $('expStat').textContent = `${vis.length}/${EXP.total}장 불러옴 · 선별 ${EXP.picked.size}`
    + ` · 즐겨찾기 ${EXP.fav.size} · 평가 ${Object.keys(EXP.ratings||{}).length}`;
  $('expCmpN').textContent = EXP.cmp.size;
  /* 수천 장을 한 번에 그리면 초기 로딩·메모리가 터진다 (Custom 의 페이지 분할 참고).
     120장씩 그리고, '더 보기'가 화면에 가까워지면 자동으로 다음 묶음. */
  EXP.vis = vis; EXP.shown = 0;
  expChunk();
}
function expChunk(){
  const g = $('expGrid');
  const vis = EXP.vis || [];
  const end = Math.min(vis.length, EXP.shown + EXP_CHUNK);
  for(let i = EXP.shown; i < end; i++){
    const f = vis[i];
    const score = Number((EXP.ratings || {})[f.path] || 0);
    const tags = (EXP.tags || {})[f.path] || [];
    const el = document.createElement('div');
    el.style.cssText = 'position:relative;cursor:pointer;';
    el.innerHTML = `<img src="/setout?p=${encodeURIComponent(f.path)}" alt="" loading="lazy"
        style="width:100%;aspect-ratio:1/1;object-fit:cover;display:block;
        border:2px solid ${EXP.picked.has(f.path)?'var(--good)':'var(--line)'};
        border-radius:var(--radius);${EXP.cmp.has(f.path)?'outline:2px dashed var(--accent);outline-offset:1px;':''}">
      <div style="position:absolute;top:2px;right:3px;font-size:var(--fs-sm);text-shadow:0 0 3px #000;">
        ${EXP.fav.has(f.path)?'⭐':''}${EXP.picked.has(f.path)?'✔':''}</div>
      ${((EXP.ranks||{})[f.path] || score) ? `<div style="position:absolute;top:2px;left:3px;font-size:var(--fs-2xs);
        background:#000a;color:#ffd76e;padding:1px 4px;border-radius:var(--radius-pill);">
        ${(EXP.ranks||{})[f.path] ? `🏆${EXP.ranks[f.path]}` : ''}${score ? ` ${'★'.repeat(score)}` : ''}</div>` : ''}
      <div class="tag" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(f.name)}</div>
      ${tags.length ? `<div class="hint" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(tags.slice(0,3).join(' · '))}</div>` : ''}`;
    el.addEventListener('click', () => expOpen(i));
    g.appendChild(el);
  }
  EXP.shown = end;
  let more = $('expMore');
  if(!more){
    more = document.createElement('button');
    more.id = 'expMore';
    more.style.cssText = 'grid-column:1/-1;padding:8px 0;';
    more.addEventListener('click', () =>
      EXP.shown < (EXP.vis || []).length ? expChunk() : expFetchMore());
    /* 화면에 가까워지면 자동 로딩 — 탭이 숨어 있으면 안 돌므로 안전하다 */
    new IntersectionObserver(es => es.forEach(e => {
      if(!e.isIntersecting) return;
      if(EXP.shown < (EXP.vis || []).length) expChunk();
      else if(EXP.files.length < EXP.total) expFetchMore();
    }), {rootMargin: '600px'}).observe(more);
  }
  g.appendChild(more);   // 항상 그리드 맨 끝
  more.textContent = `더 보기 (${Math.max(0, EXP.total - EXP.shown)}장 남음)`;
  more.classList.toggle('hidden', EXP.shown >= EXP.total);
}
/* ── 🏆 이미지 월드컵 (SDStudio 의 토너먼트를 우리 탐색기에) ──────────────
   보이는 그림을 무작위로 짝지어 1:1 로 이긴 쪽만 다음 판에 올린다.
   판마다 진 쪽은 그 라운드의 등수를 받는다 → 마지막에 순위가 나온다.
   순위는 선별.json 의 ranks 에 저장되어 카드에 배지로 남는다.
   조작: ←/→ 또는 클릭으로 승자 · Space 무승부(둘 다 진출) · Esc 중단 */
let CUP = null;
async function cupStart(){
  const vis = await expEnsureAll();
  if(vis.length < 2){ $('expStat').textContent = '월드컵은 그림이 2장 이상일 때 할 수 있습니다.'; return; }
  const pool = vis.map(f => f.path);
  for(let i = pool.length - 1; i > 0; i--){          // 섞기
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  CUP = {round: pool, next: [], i: 0, ranks: {}, place: pool.length, total: pool.length, matches: 0};
  cupDraw();
}
function cupFinish(){
  const el = $('cupBg'); if(el) el.remove();
  const ranked = Object.entries(CUP.ranks).sort((a, b) => a[1] - b[1]);
  Object.assign(EXP.ranks, CUP.ranks);
  picksSave();
  $('expStat').textContent = `🏆 월드컵 끝 — ${CUP.matches}판, 1등 ${ranked.length ? ranked[0][0].split('/').pop() : '?'}`;
  CUP = null;
  expDraw();
}
function cupDraw(){
  if(!CUP) return;
  /* 이번 라운드가 끝났으면 다음 라운드로 */
  if(CUP.i >= CUP.round.length){
    if(CUP.next.length <= 1){
      if(CUP.next.length === 1) CUP.ranks[CUP.next[0]] = 1;   // 우승
      cupFinish(); return;
    }
    /* 모두 '둘 다'를 고른 라운드는 참가 수가 줄지 않는다. 전원 공동 1위로 종료한다. */
    if(CUP.next.length === CUP.round.length){
      CUP.next.forEach(p => { CUP.ranks[p] = 1; });
      cupFinish(); return;
    }
    CUP.round = CUP.next; CUP.next = []; CUP.i = 0;
  }
  /* 홀수로 남은 마지막 한 장은 부전승 */
  if(CUP.i === CUP.round.length - 1){
    CUP.next.push(CUP.round[CUP.i]); CUP.i++;
    cupDraw(); return;
  }
  const a = CUP.round[CUP.i], b = CUP.round[CUP.i + 1];
  let ov = $('cupBg');
  if(!ov){
    ov = document.createElement('div'); ov.id = 'cupBg';
    ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:#000d;display:flex;'
      + 'flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:12px;';
    document.body.appendChild(ov);
  }
  const left = Math.max(0, CUP.round.length - CUP.i) + CUP.next.length;
  ov.innerHTML = `<div style="color:#eee;font-size:var(--fs-sm);">
      🏆 이미지 월드컵 — ${CUP.total}장 중 ${left}장 남음 · ${CUP.matches + 1}번째 판
      <span style="opacity:.7;margin-left:10px;">←/→ 또는 클릭으로 승자 · Space 둘 다 · Esc 중단</span></div>
    <div style="display:flex;gap:12px;align-items:center;justify-content:center;max-height:78vh;">
      <img data-cup="L" src="/setout?p=${encodeURIComponent(a)}" style="max-width:46vw;max-height:74vh;object-fit:contain;cursor:pointer;border:3px solid transparent;border-radius:var(--radius);">
      <img data-cup="R" src="/setout?p=${encodeURIComponent(b)}" style="max-width:46vw;max-height:74vh;object-fit:contain;cursor:pointer;border:3px solid transparent;border-radius:var(--radius);">
    </div>
    <div style="color:#aaa;font-size:var(--fs-2xs);">${esc(a.split('/').pop())} vs ${esc(b.split('/').pop())}</div>`;
  ov.querySelectorAll('[data-cup]').forEach(im => {
    im.addEventListener('mouseenter', () => im.style.borderColor = 'var(--accent)');
    im.addEventListener('mouseleave', () => im.style.borderColor = 'transparent');
    im.addEventListener('click', () => cupPick(im.dataset.cup === 'L' ? 'a' : 'b'));
  });
}
function cupPick(which){
  if(!CUP) return;
  const a = CUP.round[CUP.i], b = CUP.round[CUP.i + 1];
  CUP.matches++;
  if(which === 'both'){ CUP.next.push(a, b); }
  else {
    const win = which === 'a' ? a : b, lose = which === 'a' ? b : a;
    CUP.next.push(win);
    CUP.ranks[lose] = CUP.place--;          // 진 쪽은 남은 등수 중 가장 낮은 자리
  }
  CUP.i += 2;
  cupDraw();
}
async function picksSave(){
  await fetch('/api/picks_save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      picked:[...EXP.picked], fav:[...EXP.fav],
      folders:EXP.folders || {}, ranks:EXP.ranks || {},
      ratings:EXP.ratings || {}, tags:EXP.tags || {}
    })});
}
let EXP_RECIPE_UNDO = null;
let EXP_APPLIED_RECIPE = null;
let EXP_APPLIED_PATH = '';
const EXP_RECIPE_KEYS = [
  'base_prompt','negative_prompt','style_name','nai_seed','char_slots','char_centers',
  'vibes','char_refs','model','width','height','cfg_scale','cfg_rescale','steps',
  'sampler','scheduler','variety','uc_preset','quality_toggle','smea','smea_dyn',
  'dynamic_thresholding','uncond_scale','controlnet_strength','prefer_brownian',
  'deliberate_euler_ancestral_bug','legacy_v3_extend','use_coords'
];
function comparisonRecipeSnapshot(){
  const out = {};
  EXP_RECIPE_KEYS.forEach(key => {
    out[key] = JSON.parse(JSON.stringify(STATE[key] === undefined ? null : STATE[key]));
  });
  return out;
}
function comparisonRecipePaint(){
  $('basePrompt').value = STATE.base_prompt || '';
  $('negPrompt').value = STATE.negative_prompt || '';
  paintParams();
  renderSlots();
  renderRefs();
  tokens();
  save();
}
function expRecipeActions(message){
  if(!EXP_APPLIED_RECIPE) return;
  const hasCharacters = (EXP_APPLIED_RECIPE.char_slots || []).length > 0;
  $('expStat').innerHTML = `${esc(message)}`
    + ` <button type="button" id="expGoGenerate" class="primary">생성 화면으로</button>`
    + ` <button type="button" id="expPromoteStyle">그림체 묶음으로 저장</button>`
    + (hasCharacters
      ? ` <button type="button" id="expPromoteChars">캐릭터를 각각 저장</button>` : '')
    + ` <button type="button" id="expUndoRecipe">적용 전으로 되돌리기</button>`
    + ` <span class="hint">세팅은 이 비교에 포함되지 않아 그림에서 추정해 저장하지 않습니다.</span>`;
  $('expGoGenerate').addEventListener('click', () => setMode('preview'));
  $('expPromoteStyle').addEventListener('click', async () => {
    const suggested = EXP_APPLIED_RECIPE.style_name || '비교 결과 그림체';
    const name = prompt(
      '그림체 이름 (베이스+네거티브+생성 설정을 한 묶음으로 저장):',
      suggested
    );
    if(!name) return;
    const r = await (await fetch('/api/compare_promote', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:EXP_APPLIED_PATH, kind:'style', name})
    })).json();
    if(!r.ok){ expRecipeActions(r.error || '그림체를 저장하지 못했습니다.'); return; }
    if(r.styles) STYLES = r.styles;
    renderPresets(); renderLibrary();
    expRecipeActions(r.saved
      ? `그림체 '${r.names[0]}'에 베이스·네거티브·생성 설정을 함께 저장했습니다.`
      : `같은 내용의 그림체 '${r.names[0]}'가 있어 중복 저장하지 않았습니다.`);
  });
  if(hasCharacters) $('expPromoteChars').addEventListener('click', async () => {
    const count = EXP_APPLIED_RECIPE.char_slots.length;
    if(!confirm(
      `이 결과의 캐릭터 ${count}명을 각각 전체 프롬프트로 저장할까요?\n`
      + '같은 외형·착의·네거티브가 이미 있으면 중복 저장하지 않습니다.'
    )) return;
    const r = await (await fetch('/api/compare_promote', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:EXP_APPLIED_PATH, kind:'characters'})
    })).json();
    if(!r.ok){ expRecipeActions(r.error || '캐릭터를 저장하지 못했습니다.'); return; }
    if(r.characters) STATE.characters = r.characters;
    if(r.revision != null) STATE._revision = r.revision;
    renderLibrary();
    expRecipeActions(
      `캐릭터 ${r.saved}명 저장`
      + (r.existing ? ` · 같은 내용 ${r.existing}명은 중복 생략` : '')
      + ` (${(r.names || []).join(', ')})`
    );
  });
  $('expUndoRecipe').addEventListener('click', () => {
    if(!EXP_RECIPE_UNDO) return;
    Object.entries(EXP_RECIPE_UNDO).forEach(([key, value]) => {
      STATE[key] = JSON.parse(JSON.stringify(value));
    });
    EXP_RECIPE_UNDO = null;
    EXP_APPLIED_RECIPE = null;
    EXP_APPLIED_PATH = '';
    comparisonRecipePaint();
    $('expStat').textContent = '비교 결과를 적용하기 전 설정으로 되돌렸습니다.';
  });
}
async function expApplyPickedRecipe(){
  const visible = await expEnsureAll();
  const chosen = visible.filter(file => EXP.picked.has(file.path));
  if(chosen.length !== 1){
    $('expStat').textContent = chosen.length
      ? `이 폴더에서 선별한 ${chosen.length}장 중 적용할 한 장만 남겨주세요.`
      : '이 폴더에서 비교 결과 한 장을 먼저 선별해주세요.';
    return;
  }
  const r = await (await fetch('/api/compare_recipe', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:chosen[0].path})})).json();
  if(!r.ok){ $('expStat').textContent = r.error || '원문 레시피를 읽지 못했습니다.'; return; }
  const recipe = r.recipe || {};
  const people = (recipe.char_slots || []).length;
  if(!confirm(
    `선택한 결과의 그림체·네거티브·생성 설정·시드·캐릭터 ${people}명을 현재 생성에 적용할까요?\n`
    + '적용 직후 이 화면에서 되돌릴 수 있습니다.'
  )) return;
  EXP_RECIPE_UNDO = comparisonRecipeSnapshot();
  EXP_APPLIED_RECIPE = JSON.parse(JSON.stringify(recipe));
  EXP_APPLIED_PATH = chosen[0].path;
  STATE.base_prompt = recipe.base_prompt || '';
  STATE.negative_prompt = recipe.negative_prompt || '';
  STATE.style_name = recipe.style_name || '';
  STATE.nai_seed = Number(recipe.nai_seed) || 0;
  STATE.char_slots = JSON.parse(JSON.stringify(recipe.char_slots || []));
  STATE.char_centers = JSON.parse(JSON.stringify(recipe.char_centers || []));
  if(recipe.include_refs){
    STATE.vibes = JSON.parse(JSON.stringify(recipe.vibes || []));
    STATE.char_refs = JSON.parse(JSON.stringify(recipe.char_refs || []));
  }else{
    STATE.vibes = (STATE.vibes || []).map(item => Object.assign({}, item, {enabled:false}));
    STATE.char_refs = (STATE.char_refs || []).map(item => Object.assign({}, item, {enabled:false}));
  }
  Object.entries(recipe.settings || {}).forEach(([key, value]) => {
    if(EXP_RECIPE_KEYS.includes(key) && value !== null && value !== undefined){
      STATE[key] = value;
    }
  });
  comparisonRecipePaint();
  expRecipeActions('선별 결과 원문을 현재 생성에 적용했습니다.');
}
/* 크게 보기 — 여기서 ←→ F C Esc 가 먹는다 */
function expOpen(i){
  const vis = expVisible();
  if(i < 0 || i >= vis.length) return;
  EXP.open = i;
  const f = vis[i];
  let ov = $('expViewer');
  if(!ov){
    ov = document.createElement('div'); ov.id = 'expViewer';
    ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:#000c;display:flex;'
      + 'flex-direction:column;align-items:center;justify-content:center;gap:8px;padding:14px;';
    ov.addEventListener('click', e => { if(e.target === ov) expClose(); });
    document.body.appendChild(ov);
  }
  const score = Number((EXP.ratings || {})[f.path] || 0);
  const tags = (EXP.tags || {})[f.path] || [];
  ov.innerHTML = `<img src="/setout?p=${encodeURIComponent(f.path)}" alt=""
      style="max-width:96vw;max-height:82vh;object-fit:contain;border-radius:var(--radius);">
    <div class="bar" style="background:var(--paper);padding:7px 11px;border-radius:var(--radius);flex-wrap:wrap;">
      <span class="n">${i+1} / ${vis.length}</span>
      <b style="font-size:var(--fs-xs);">${esc(f.name)}</b>
      <span class="tag">${EXP.picked.has(f.path)?'✔ 선별됨':'F = 선별'}</span>
      <span class="tag">${EXP.cmp.has(f.path)?'비교함에 있음':'C = 비교함'}</span>
      <span class="tag">${EXP.fav.has(f.path)?'⭐':'S = 즐겨찾기'}</span>
      <select id="expRate" aria-label="이 그림 별점" style="width:auto;">
        <option value="0"${score===0?' selected':''}>별점 없음</option>
        ${[1,2,3,4,5].map(n => `<option value="${n}"${score===n?' selected':''}>${'★'.repeat(n)}</option>`).join('')}
      </select>
      <input type="text" id="expTagInput" value="${escA(tags.join(', '))}"
        placeholder="판단 태그 (쉼표로 구분)" style="width:220px;">
      <button type="button" id="expTagSave">태그 저장</button>
      <span class="hint">←→ 넘기기 · Esc 닫기</span>
    </div>`;
  $('expRate').addEventListener('change', async () => {
    const value = Number($('expRate').value) || 0;
    if(value) EXP.ratings[f.path] = value;
    else delete EXP.ratings[f.path];
    await picksSave(); expDraw(); expOpen(EXP.open);
  });
  $('expTagSave').addEventListener('click', async () => {
    const values = [...new Set(
      $('expTagInput').value.split(',').map(x => x.trim().slice(0,40)).filter(Boolean)
    )].slice(0,12);
    if(values.length) EXP.tags[f.path] = values;
    else delete EXP.tags[f.path];
    await picksSave(); expDraw(); expOpen(EXP.open);
  });
}
function expClose(){ const o = $('expViewer'); if(o) o.remove(); EXP.open = -1; }
window.addEventListener('keydown', async e => {
  /* 월드컵이 열려 있으면 그쪽이 키를 먼저 먹는다 */
  if(CUP){
    if(e.key === 'ArrowLeft'){ e.preventDefault(); cupPick('a'); return; }
    if(e.key === 'ArrowRight'){ e.preventDefault(); cupPick('b'); return; }
    if(e.key === ' '){ e.preventDefault(); cupPick('both'); return; }
    if(e.key === 'Escape'){ e.preventDefault(); const el = $('cupBg'); if(el) el.remove(); CUP = null; return; }
    return;
  }
  if(EXP.open < 0) return;
  const vis = expVisible(); const f = vis[EXP.open]; if(!f) return;
  const k = e.key.toLowerCase();
  if(e.key === 'Escape'){ expClose(); return; }
  if(e.key === 'ArrowRight'){
    e.preventDefault();
    if(EXP.open >= vis.length-1 && EXP.files.length < EXP.total) await expFetchMore(false);
    expOpen(Math.min(EXP.open+1, expVisible().length-1)); return;
  }
  if(e.key === 'ArrowLeft'){ e.preventDefault(); expOpen(Math.max(EXP.open-1, 0)); return; }
  if(k === 'f'){ e.preventDefault();
    EXP.picked.has(f.path) ? EXP.picked.delete(f.path) : EXP.picked.add(f.path);
    await picksSave(); expDraw(); expOpen(EXP.open); return; }
  if(k === 's'){ e.preventDefault();
    EXP.fav.has(f.path) ? EXP.fav.delete(f.path) : EXP.fav.add(f.path);
    await picksSave(); expDraw(); expOpen(EXP.open); return; }
  if(k === 'c'){ e.preventDefault();
    EXP.cmp.has(f.path) ? EXP.cmp.delete(f.path) : EXP.cmp.add(f.path);
    expDraw(); expOpen(EXP.open); return; }
});
if($('expUp')){
  $('expUp').addEventListener('click', () => expLoad(EXP.dir.includes('/')
    ? EXP.dir.slice(0, EXP.dir.lastIndexOf('/')) : ''));
  $('expReload').addEventListener('click', () => expLoad());
  ['expOnlyPick','expOnlyFav'].forEach(id => $(id).addEventListener('change', () => expLoad(EXP.dir)));
  $('expSize').addEventListener('change', expDraw);
  $('expGroupFilter').addEventListener('change', expDraw);
  $('expGroupSave').addEventListener('click', async () => {
    const name = $('expGroupName').value.trim().slice(0,40);
    if(!name){ $('expStat').textContent = '후보군 이름을 입력해주세요.'; return; }
    const visible = await expEnsureAll();
    const chosen = visible.map(file => file.path).filter(path => EXP.picked.has(path));
    if(!chosen.length){ $('expStat').textContent = '이 폴더에서 후보군에 넣을 그림을 먼저 선별해주세요.'; return; }
    EXP.folders[name] = [...new Set([...(EXP.folders[name] || []), ...chosen])];
    await picksSave();
    expPaintGroups(); $('expGroupFilter').value = name; expDraw();
    $('expStat').textContent = `'${name}' 후보군에 선별 ${chosen.length}장을 이름표로 연결했습니다.`;
  });
  $('expGroupDelete').addEventListener('click', async () => {
    const name = $('expGroupFilter').value;
    if(!name){ $('expStat').textContent = '삭제할 후보군 이름표를 선택해주세요.'; return; }
    if(!confirm(`후보군 '${name}' 이름표를 지울까요? 원본 그림과 선별 표시는 그대로 남습니다.`)) return;
    delete EXP.folders[name];
    await picksSave(); expPaintGroups(); expDraw();
    $('expStat').textContent = `'${name}' 후보군 이름표만 지웠습니다.`;
  });
  $('expCmpClear').addEventListener('click', () => { EXP.cmp.clear(); expDraw(); });
  if($('expCup')) $('expCup').addEventListener('click', cupStart);
  if($('expApplyPicked')) $('expApplyPicked').addEventListener(
    'click', expApplyPickedRecipe);
  $('expCompare').addEventListener('click', () => {
    if(!EXP.cmp.size){ $('expStat').textContent = '비교함이 비어 있습니다 (그림을 열고 C)'; return; }
    let ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:#000d;display:flex;'
      + 'align-items:center;gap:6px;overflow:auto;padding:14px;';
    ov.innerHTML = [...EXP.cmp].map(p => `<img src="/setout?p=${encodeURIComponent(p)}"
      style="max-height:88vh;object-fit:contain;border-radius:var(--radius);">`).join('')
      + '<div class="hint" style="position:fixed;left:14px;bottom:10px;color:#fff;">아무 데나 눌러 닫기</div>';
    ov.addEventListener('click', () => ov.remove());
    document.body.appendChild(ov);
  });
  const regen = async (paths) => {
    if(!paths.length){ $('expStat').textContent = '복구할 그림을 먼저 고르세요.'; return; }
    const r = await (await fetch('/api/regen', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({paths, mode: $('regenMode').value,
                            strength: Number($('regenStrength').value)})})).json();
    $('expStat').textContent = r.ok
      ? `${r.count}장 복구 시작 (${r.mode === 'img2img' ? 'img2img' : '같은 설정'}) — 생성 탭 미리보기에 나옵니다`
      : (r.error || '실패');
  };
  $('regenPicked').addEventListener('click', async () => {
    const vis = await expEnsureAll();
    regen(vis.map(f => f.path).filter(p => EXP.picked.has(p)));
  });
  $('regenAll').addEventListener('click', async () => {
    const paths = (await expEnsureAll()).map(f => f.path);
    if(paths.length > 20 && !confirm(`${paths.length}장을 복구합니다. 시간이 오래 걸립니다. 계속할까요?`)) return;
    regen(paths);
  });
  $('expDelUnpicked').addEventListener('click', async () => {
    const vis = await expEnsureAll();
    const targets = vis.map(f => f.path).filter(p => !EXP.picked.has(p));
    if(!targets.length){ $('expStat').textContent = '지울 것이 없습니다 (전부 선별됨)'; return; }
    if(!confirm(`선별 안 된 ${targets.length}장을 휴지통으로 옮길까요?\n바로 다음 안내에서 되돌릴 수 있습니다.`)) return;
    const r = await (await fetch('/api/picks_del', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({targets, keep:[...EXP.picked]})})).json();
    if(!r.ok){ $('expStat').textContent = r.error || '실패'; return; }
    $('expStat').innerHTML = `${r.deleted}장 휴지통으로 이동`
      + (r.batch_id ? ` <button id="expUndoDelete" class="primary">되돌리기</button>` : '');
    if(r.batch_id) $('expUndoDelete').addEventListener('click', async () => {
      const rr = await (await fetch('/api/picks_restore', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({batch_id:r.batch_id})})).json();
      $('expStat').textContent = rr.ok ? `${rr.restored}장 복원됨` : (rr.error || '복원 실패');
      expLoad();
    });
    expLoad();
  });
}

/* ── 알림 (다 끝났을 때) ────────────────────────────────────────────
   565장은 몇 시간이 걸린다. 자리를 떠도 끝난 걸 알 수 있어야 한다.
   소리는 WebAudio 로 직접 만든다 — 음원 파일을 배포본에 넣지 않으려고. */
function beep(){
  try{
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    [880, 1180, 1480].forEach((f, i) => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sine'; o.frequency.value = f;
      o.connect(g); g.connect(ac.destination);
      const t = ac.currentTime + i * 0.18;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.22, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.17);
      o.start(t); o.stop(t + 0.18);
    });
    setTimeout(() => ac.close(), 900);
  }catch(e){}
}
function notifyDone(text){
  const u = STATE.ui || {};
  if(u.notify_sound) beep();
  if(u.notify_system){
    if(Notification.permission === 'granted') new Notification('NAI 배치 생성기', {body: text});
    else if(Notification.permission !== 'denied')
      Notification.requestPermission().then(p => {
        if(p === 'granted') new Notification('NAI 배치 생성기', {body: text});
      });
  }
}
if($('notifySound')){
  ['notifySound','notifySystem'].forEach(id => {
    const key = id === 'notifySound' ? 'notify_sound' : 'notify_system';
    const e = $(id);
    e.addEventListener('change', () => {
      STATE.ui = STATE.ui || {}; STATE.ui[key] = e.checked;
      if(e.checked && key === 'notify_system' && Notification.permission === 'default')
        Notification.requestPermission();
      save();
    });
  });
  $('notifyTest').addEventListener('click', () => {
    notifyDone('알림 시험입니다 — 이렇게 알려 드립니다.');
    $('notifyMsg').textContent = '보냈습니다 (소리·알림 중 켜 둔 것)';
  });
}

/* ── 모자이크 칠하기 (내 컴퓨터에서 · 공짜) ─────────────────────────
   칠한 자리만 블록 평균색으로 덮는다. 원본 픽셀을 따로 들고 있다가
   '처음으로' 를 누르면 되돌린다. */
let MOS = {img:null, painting:false};
function mosLoad(file){
  const fr = new FileReader();
  fr.onload = () => {
    const im = new Image();
    im.onload = () => {
      MOS.img = im;
      const c = $('mosCanvas');
      c.width = im.width; c.height = im.height;
      c.getContext('2d').drawImage(im, 0, 0);
      $('mosStage').classList.remove('hidden');
      $('mosMsg').textContent = `${im.width}×${im.height} — 가릴 곳을 칠하세요`;
    };
    im.src = fr.result;
  };
  fr.readAsDataURL(file);
}
function mosDab(x, y){
  const c = $('mosCanvas'), ctx = c.getContext('2d');
  const bs = Number($('mosBlock').value), r = Number($('mosBrush').value) / 2;
  const x0 = Math.max(0, Math.floor((x - r) / bs) * bs);
  const y0 = Math.max(0, Math.floor((y - r) / bs) * bs);
  const x1 = Math.min(c.width, Math.ceil((x + r) / bs) * bs);
  const y1 = Math.min(c.height, Math.ceil((y + r) / bs) * bs);
  if(x1 <= x0 || y1 <= y0) return;
  const img = ctx.getImageData(x0, y0, x1 - x0, y1 - y0);
  const d = img.data, w = x1 - x0;
  for(let by = 0; by < y1 - y0; by += bs){
    for(let bx = 0; bx < w; bx += bs){
      /* 이 블록의 중심이 붓 원 안에 있을 때만 */
      const cx = x0 + bx + bs / 2, cy = y0 + by + bs / 2;
      if((cx - x) ** 2 + (cy - y) ** 2 > r * r) continue;
      let sr = 0, sg = 0, sb = 0, n = 0;
      for(let yy = by; yy < Math.min(by + bs, y1 - y0); yy++){
        for(let xx = bx; xx < Math.min(bx + bs, w); xx++){
          const i = (yy * w + xx) * 4;
          sr += d[i]; sg += d[i+1]; sb += d[i+2]; n++;
        }
      }
      if(!n) continue;
      sr = sr / n | 0; sg = sg / n | 0; sb = sb / n | 0;
      for(let yy = by; yy < Math.min(by + bs, y1 - y0); yy++){
        for(let xx = bx; xx < Math.min(bx + bs, w); xx++){
          const i = (yy * w + xx) * 4;
          d[i] = sr; d[i+1] = sg; d[i+2] = sb;
        }
      }
    }
  }
  ctx.putImageData(img, x0, y0);
}
if($('mosDrop')){
  const c = $('mosCanvas');
  const at = e => {
    const r = c.getBoundingClientRect();
    return [(e.clientX - r.left) * (c.width / r.width), (e.clientY - r.top) * (c.height / r.height)];
  };
  c.addEventListener('pointerdown', e => { MOS.painting = true; c.setPointerCapture(e.pointerId); mosDab(...at(e)); });
  c.addEventListener('pointermove', e => { if(MOS.painting) mosDab(...at(e)); });
  ['pointerup','pointercancel','pointerleave'].forEach(ev =>
    c.addEventListener(ev, () => MOS.painting = false));
  $('mosBlock').addEventListener('input', () => $('mosBlockN').textContent = $('mosBlock').value + 'px');
  $('mosDrop').addEventListener('click', () => $('mosFile').click());
  $('mosFile').addEventListener('change', () => {
    if($('mosFile').files[0]) mosLoad($('mosFile').files[0]);
    $('mosFile').value = '';
  });
  ['dragover','dragenter'].forEach(ev => $('mosDrop').addEventListener(ev, e => {
    e.preventDefault(); $('mosDrop').style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => $('mosDrop').addEventListener(ev, e => {
    e.preventDefault(); $('mosDrop').style.borderColor = ''; }));
  $('mosDrop').addEventListener('drop', e => {
    const f = [...(e.dataTransfer.files || [])].find(x => /image\/(png|webp)/.test(x.type));
    if(f) mosLoad(f);
  });
  $('mosReset').addEventListener('click', () => {
    if(!MOS.img) return;
    $('mosCanvas').getContext('2d').drawImage(MOS.img, 0, 0);
    $('mosMsg').textContent = '되돌렸습니다';
  });
  $('mosSave').addEventListener('click', async () => {
    if(!MOS.img){ $('mosMsg').textContent = '먼저 그림을 넣어주세요.'; return; }
    const blob = await new Promise(r => $('mosCanvas').toBlob(r, 'image/png'));
    const r = await (await fetch('/api/mosaic_save', {method:'POST',
      headers:{'X-Filename': encodeURIComponent('mosaic.png')}, body: blob})).json();
    $('mosMsg').textContent = r.ok ? `저장됨 → output/모자이크/${r.file}` : (r.error || '실패');
  });
}

/* ── 밴 예방 · 속도 ────────────────────────────────────────────────── */
const PACE_FIELDS = {paceDmin:'delay_min', paceDmax:'delay_max', paceDaily:'daily_cap',
  paceSoftEvery:'soft_every', paceSoftSec:'soft_seconds',
  paceCoolEvery:'cool_every', paceCoolSec:'cool_seconds'};
const PACE_DEF = {delay_min:5.5, delay_max:11.5, daily_cap:7000,
  soft_every:350, soft_seconds:30, cool_every:3000, cool_seconds:300};
function paintPace(){
  const p = Object.assign({}, PACE_DEF, STATE.pace || {});
  Object.entries(PACE_FIELDS).forEach(([id, k]) => { if($(id)) $(id).value = p[k]; });
  paceCalc();
}
function paceCalc(){
  const p = Object.assign({}, PACE_DEF, STATE.pace || {});
  const avg = (Number(p.delay_min) + Number(p.delay_max)) / 2;
  const per100 = avg * 100
    + (p.soft_every ? Math.floor(100 / p.soft_every) * Number(p.soft_seconds) : 0)
    + (p.cool_every ? Math.floor(100 / p.cool_every) * Number(p.cool_seconds) : 0);
  const m = Math.round(per100 / 60);
  $('paceCalc').textContent = `지금 값이면 100장에 대략 ${m}분 `
    + `(장당 평균 ${avg.toFixed(1)}초 + 쉬는 시간). 하루 ${p.daily_cap}장까지.`;
}
Object.entries(PACE_FIELDS).forEach(([id, k]) => {
  const e = $(id); if(!e) return;
  e.addEventListener('change', () => {
    STATE.pace = Object.assign({}, PACE_DEF, STATE.pace || {});
    STATE.pace[k] = Number(e.value);
    if(STATE.pace.delay_max < STATE.pace.delay_min){
      STATE.pace.delay_max = STATE.pace.delay_min;
      $('paceDmax').value = STATE.pace.delay_max;
    }
    paceCalc(); save();
  });
});

/* ── 메타데이터 제거 ────────────────────────────────────────────────── */
async function stripFiles(files){
  const ok = [], bad = [];
  for(const f of files){
    $('stripMsg').textContent = `${f.name} 지우는 중...`;
    try{
      const r = await (await fetch('/api/strip_meta', {method:'POST',
        headers:{'X-Filename': encodeURIComponent(f.name),
                 'X-MaxSide': $('stripSide').value,
                 'X-Quality': $('stripQ').value,
                 'X-ForceWebp': $('stripWebp').checked ? '1' : '0'}, body: f})).json();
      if(r.ok) ok.push(r.file + ` (${Math.round(r.before/1024)}→${Math.round(r.bytes/1024)}KB)`
        + (r['남은메타'] ? ' ⚠남은 메타 있음' : ''));
      else bad.push(f.name + ': ' + (r.error || '실패'));
    }catch(e){ bad.push(f.name + ': ' + e); }
  }
  $('stripMsg').textContent = (ok.length ? `${ok.length}장 완료 → output/메타제거/ (${ok[0]}${ok.length>1?' 외':''})` : '')
    + (bad.length ? ` · 실패 ${bad.length}건: ${bad[0]}` : '');
}
if($('stripDrop')){
  $('stripDrop').addEventListener('click', () => $('stripFile').click());
  $('stripFile').addEventListener('change', () => {
    stripFiles([...$('stripFile').files]); $('stripFile').value = '';
  });
  ['dragover','dragenter'].forEach(ev => $('stripDrop').addEventListener(ev, e => {
    e.preventDefault(); $('stripDrop').style.borderColor = 'var(--accent)';
  }));
  ['dragleave','drop'].forEach(ev => $('stripDrop').addEventListener(ev, e => {
    e.preventDefault(); $('stripDrop').style.borderColor = '';
  }));
  $('stripDrop').addEventListener('drop', e => {
    const fs = [...(e.dataTransfer.files || [])].filter(f => /image\/(png|webp)/.test(f.type));
    if(fs.length) stripFiles(fs);
  });
}

/* ── 세팅 빌더 ───────────────────────────────────────────────────────
   세팅 = 세트(묶음)의 모음. 세트 = 단계명마다 씬 하나.
   단계 수가 자유인 이유는 단계를 **묶음 안의 순서**로 세기 때문이다. */
let SB = {name:'', axes:{}}, CLASHES = {};
/* 씬 번호가 세팅끼리 겹치면 나중에 읽힌 쪽이 이겨 조용히 사라진다 — 눈에 띄게 알린다 */
function paintClash(){
  const el = $('sbClash'); if(!el) return;
  const n = Object.keys(CLASHES || {}).length;
  el.textContent = n ? `⚠ 씬 번호 ${n}개가 겹칩니다 — [번호 다시 매기기]를 쓰세요` : '';
}
const NL1 = String.fromCharCode(10);

function sbPickList(){
  const sel = $('sbPick'); if(!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">고칠 세팅 고르기...</option>' +
    SETTINGS.map(st => `<option value="${escA(st.name)}"${st.name===cur?' selected':''}>${esc(st.name)} · ${esc(st.mode)} · ${st.groups.length}세트</option>`).join('');
  const res = $('sbSetRes');
  if(res) res.innerHTML = RES_PRESETS.map(r =>
    `<option value="${r.w}x${r.h}"${r.w===832&&r.h===1216?' selected':''}>${r.label} ${r.w}×${r.h}</option>`).join('');
}
function sbLoad(name){
  const st = SETTINGS.find(x => x.name === name);
  SB.name = name;
  $('sbBody').classList.toggle('hidden', !st);
  if(!st) return;
  $('sbName').value = st.name;
  $('sbMode').value = st.mode || '단독';
  $('sbStages').value = (st.stages || []).join(', ');
  $('sbCats').value = Object.entries(st.cat_names || {}).map(([k,v]) => k + '=' + v).join(', ');
  const r = st.role || {};
  $('sbRoleLook').value = r['외형'] || ''; $('sbRoleWear').value = r['착의'] || '';
  $('sbRoleOutfit').value = r['의상'] || ''; $('sbRoleNeg').value = r['네거티브'] || '';
  SB.axes = {};
  Object.entries(st.options || {}).forEach(([ax, items]) => {
    const spec = (st.axis_specs || {})[ax] || {};
    SB.axes[ax] = {적용: spec['적용'] || 'base', 방식: spec['방식'] || '고정', 항목: items || {}};
  });
  sbDrawAxes();
  const ns = st.nums || [];
  $('sbMsg').textContent = `씬 ${ns.length}개` + (ns.length ? ` · 번호 ${ns[0]}~${ns[ns.length-1]}` : '');
}
/* 항목 값을 사람이 읽고 쓰기 쉬운 글로 (방식마다 다르다) */
function sbItemToText(shape, v){
  if(shape === '계열별' && v && typeof v === 'object' && !Array.isArray(v))
    return Object.entries(v).map(([k, t]) => k + '=' + t).join(NL1);
  if(shape === '단계별' && Array.isArray(v)) return v.join(NL1);
  return String(v == null ? '' : v);
}
function sbTextToItem(shape, text){
  const lines = String(text || '').split(NL1).map(x => x.replace(/\r$/, '').trim()).filter(Boolean);
  if(shape === '계열별'){
    const o = {};
    lines.forEach(l => { const i = l.indexOf('='); if(i > 0) o[l.slice(0,i).trim()] = l.slice(i+1).trim(); });
    return o;
  }
  if(shape === '단계별') return lines;
  return lines.join(', ');
}
function sbDrawAxes(){
  const h = $('sbAxisList'); if(!h) return;
  h.innerHTML = '';
  Object.entries(SB.axes).forEach(([ax, a]) => {
    const el = document.createElement('div'); el.className = 'slot';
    const hint = a.방식 === '계열별' ? '한 줄에 <b>계열=태그</b> (예: A=sunny, bright)'
      : a.방식 === '단계별' ? '한 줄에 한 단계씩 (위에서부터 1단계)'
      : '태그를 그대로';
    el.innerHTML = `<div class="r1">
        <input type="text" data-axname="${escA(ax)}" value="${escA(ax)}" placeholder="축 이름" style="flex:1;">
        <select data-axtgt="${escA(ax)}">
          ${['base','여자','남자','네거티브'].map(t =>
            `<option value="${t}"${a.적용===t?' selected':''}>${t==='base'?'베이스':t}</option>`).join('')}
        </select>
        <select data-axshape="${escA(ax)}">
          ${['고정','계열별','단계별'].map(t =>
            `<option value="${t}"${a.방식===t?' selected':''}>${t}</option>`).join('')}
        </select>
        <button class="danger" data-axdel="${escA(ax)}">✕</button></div>
      <div class="hint" style="margin:2px 0 4px;">${hint}</div>
      <div data-axitems="${escA(ax)}"></div>
      <div class="bar" style="margin-top:4px;"><button data-axitemadd="${escA(ax)}">+ 선택지</button></div>`;
    h.appendChild(el);
    const box = el.querySelector('[data-axitems]');
    Object.entries(a.항목 || {}).forEach(([pick, val]) => {
      const row = document.createElement('div'); row.className = 'field';
      row.innerHTML = `<label><input type="text" data-axpick="${escA(ax)}" data-old="${escA(pick)}" value="${escA(pick)}" placeholder="선택지 이름" style="width:150px;">
        <button class="danger" data-axpickdel="${escA(ax)}|${escA(pick)}" style="padding:1px 6px;">✕</button></label>
        <textarea data-axval="${escA(ax)}|${escA(pick)}" style="min-height:38px;">${esc(sbItemToText(a.방식, val))}</textarea>`;
      box.appendChild(row);
    });
  });
  h.querySelectorAll('[data-axname]').forEach(x => x.addEventListener('change', () => {
    const old = x.dataset.axname, nw = x.value.trim();
    if(!nw || nw === old) return;
    SB.axes[nw] = SB.axes[old]; delete SB.axes[old]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axtgt]').forEach(x => x.addEventListener('change', () => {
    SB.axes[x.dataset.axtgt].적용 = x.value;
  }));
  h.querySelectorAll('[data-axshape]').forEach(x => x.addEventListener('change', () => {
    const ax = x.dataset.axshape, a = SB.axes[ax];
    /* 방식이 바뀌면 값 모양도 바꿔야 한다 (글로 풀었다가 다시 담는다) */
    const asText = {};
    Object.entries(a.항목 || {}).forEach(([k, v]) => asText[k] = sbItemToText(a.방식, v));
    a.방식 = x.value;
    a.항목 = {};
    Object.entries(asText).forEach(([k, t]) => a.항목[k] = sbTextToItem(a.방식, t));
    sbDrawAxes();
  }));
  h.querySelectorAll('[data-axdel]').forEach(b2 => b2.addEventListener('click', () => {
    if(!confirm(`축 '${b2.dataset.axdel}' 을 지울까요?`)) return;
    delete SB.axes[b2.dataset.axdel]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axitemadd]').forEach(b2 => b2.addEventListener('click', () => {
    const ax = b2.dataset.axitemadd, a = SB.axes[ax];
    let n = 1; while(a.항목[`선택지 ${n}`] !== undefined) n++;
    a.항목[`선택지 ${n}`] = a.방식 === '단계별' ? [] : (a.방식 === '계열별' ? {} : '');
    sbDrawAxes();
  }));
  h.querySelectorAll('[data-axpick]').forEach(x => x.addEventListener('change', () => {
    const ax = x.dataset.axpick, old = x.dataset.old, nw = x.value.trim();
    if(!nw || nw === old) return;
    const a = SB.axes[ax];
    a.항목[nw] = a.항목[old]; delete a.항목[old]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axpickdel]').forEach(b2 => b2.addEventListener('click', () => {
    const parts = b2.dataset.axpickdel.split('|');
    delete SB.axes[parts[0]].항목[parts[1]]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axval]').forEach(t => t.addEventListener('change', () => {
    const parts = t.dataset.axval.split('|');
    SB.axes[parts[0]].항목[parts[1]] = sbTextToItem(SB.axes[parts[0]].방식, t.value);
  }));
}
if($('sbPick')){
  $('sbPick').addEventListener('change', () => sbLoad($('sbPick').value));
  document.querySelectorAll('[data-sbfold]').forEach(hd => hd.addEventListener('click', () => {
    const b2 = $(hd.dataset.sbfold); if(b2) b2.classList.toggle('hidden');
  }));
  $('sbNew').addEventListener('click', async () => {
    const name = prompt('새 세팅 이름:'); if(!name) return;
    const stages = prompt('단계명 (콤마로 구분 · 세트당 씬 수가 됩니다):', '시작, 중간, 끝');
    if(stages === null) return;
    const r = await (await fetch('/api/sb_new', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, mode:'단독',
        stages: stages.split(',').map(x=>x.trim()).filter(Boolean)})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    await reloadConfig(); sbPickList();
    $('sbPick').value = r.name; sbLoad(r.name);
    $('sbMsg').textContent = `'${r.name}' 만들었습니다 — 아래 [세트 추가] 로 씬을 만드세요`;
  });
  $('sbAxisAdd').addEventListener('click', () => {
    let n = 1; while(SB.axes[`새 축 ${n}`]) n++;
    SB.axes[`새 축 ${n}`] = {적용:'base', 방식:'고정', 항목:{}};
    sbDrawAxes();
  });
  $('sbSetAdd').addEventListener('click', async () => {
    if(!SB.name){ $('sbMsg').textContent = '세팅을 먼저 고르세요.'; return; }
    const label = $('sbSetLabel').value.trim();
    if(!label){ $('sbMsg').textContent = '세트 이름을 넣으세요.'; return; }
    const wh = ($('sbSetRes').value || '832x1216').split('x').map(Number);
    const stages = $('sbStages').value.split(',').map(x=>x.trim()).filter(Boolean);
    if(!stages.length){ $('sbMsg').textContent = '단계명을 먼저 넣으세요.'; return; }
    /* ★ 단계명 칸을 먼저 저장한다. 안 그러면 화면 값과 파일 값이 어긋나 세트마다
       단계 수가 달라진다 (시험에서 한 세트는 4단계, 다음은 3단계로 갈렸다). */
    await fetch('/api/sb_meta', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name, patch: {'단계명': stages}})});
    const r = await (await fetch('/api/sb_addset', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name, label, category: $('sbSetCat').value.trim(),
                            width: wh[0], height: wh[1], stages})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    $('sbSetLabel').value = '';
    await reloadConfig(); sbPickList(); sbLoad(SB.name);
    $('sbMsg').textContent = `세트 '${label}' 추가 — 씬 ${r.count}개 (${r.start}번부터). 위 목록의 ✎ 로 프롬프트를 채우세요`;
  });
  $('sbSave').addEventListener('click', async () => {
    if(!SB.name) return;
    const cats = {};
    $('sbCats').value.split(',').forEach(t => {
      const i = t.indexOf('='); if(i > 0) cats[t.slice(0,i).trim()] = t.slice(i+1).trim();
    });
    const specs = {}, options = {};
    Object.entries(SB.axes).forEach(([ax, a]) => {
      specs[ax] = {'적용': a.적용, '방식': a.방식};
      options[ax] = a.항목 || {};
    });
    const patch = {
      '이름': $('sbName').value.trim(),
      '방식': $('sbMode').value,
      '단계명': $('sbStages').value.split(',').map(x=>x.trim()).filter(Boolean),
      '계열이름': cats, '옵션규격': specs, '옵션': options,
      '상대역': {'외형': $('sbRoleLook').value, '착의': $('sbRoleWear').value,
                '의상': $('sbRoleOutfit').value, '네거티브': $('sbRoleNeg').value},
    };
    const r = await (await fetch('/api/sb_meta', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name, patch})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    SB.name = r.name;
    await reloadConfig(); sbPickList();
    $('sbPick').value = r.name; sbLoad(r.name);
    $('sbMsg').textContent = '저장했습니다 ✓' + (r.renamed ? ' (파일 이름도 바꿨습니다)' : '');
  });
  $('sbRenum').addEventListener('click', async () => {
    if(!SB.name) return;
    const r = await (await fetch('/api/sb_renumber', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    await reloadConfig(); sbPickList(); sbLoad(SB.name);
    $('sbMsg').textContent = `번호를 ${r.start}번부터 다시 매겼습니다 (씬 ${r.count}개)`;
  });
  $('sbDel').addEventListener('click', async () => {
    if(!SB.name) return;
    if(!confirm(`세팅 '${SB.name}' 을 지울까요? 세팅 폴더의 파일이 지워집니다.`)) return;
    const r = await (await fetch('/api/sb_del', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    SB.name = ''; $('sbBody').classList.add('hidden');
    await reloadConfig(); sbPickList();
    $('sbMsg').textContent = '지웠습니다';
  });
}

/* ── 씬 모드 ────────────────────────────────────────────────────────
   씬.json 이 원본. 세팅과 별도로 병존한다. */
let SCENES = [];
function renderScenes(){
  const host = $('sceneList'); if(!host) return;
  host.innerHTML = '';
  const booked = SCENES.reduce((a,s) => a + (Number(s.reserve)||0), 0);
  $('sceneCount').textContent = SCENES.length
    ? `${SCENES.length}개 · 예약 ${booked}장` : '';
  if(!SCENES.length){
    host.innerHTML = '<p class="hint">아직 씬이 없습니다. [+ 씬 추가] 를 누르세요.</p>';
    return;
  }
  SCENES.forEach((s, i) => {
    const el = document.createElement('div'); el.className = 'slot';
    el.draggable = true; el.dataset.si = i;
    el.innerHTML = `<div class="r1">
        <span class="ed" title="끌어서 순서 바꾸기" style="cursor:grab;">⠿</span>
        <input type="text" data-sc="name" data-i="${i}" value="${escA(s.name)}" placeholder="씬 이름" style="flex:1;">
        <select data-scres="${i}" title="해상도 — NAI 의 대표 크기들" style="width:132px;">
          ${RES_PRESETS.map(r => `<option value="${r.w}x${r.h}"${(r.w===s.width&&r.h===s.height)?' selected':''}
            >${r.label} ${r.w}×${r.h}</option>`).join('')}
          <option value=""${(!s.custom_res && RES_PRESETS.some(r=>r.w===s.width&&r.h===s.height))?'':' selected'}>직접 입력…</option>
        </select>
        <input type="number" data-sc="width" data-i="${i}" value="${s.width}" min="64" max="2048" step="64"
          title="가로 (직접 입력)" style="width:58px;text-align:center;${(!s.custom_res && RES_PRESETS.some(r=>r.w===s.width&&r.h===s.height))?'display:none;':''}">
        <input type="number" data-sc="height" data-i="${i}" value="${s.height}" min="64" max="2048" step="64"
          title="세로 (직접 입력)" style="width:58px;text-align:center;${(!s.custom_res && RES_PRESETS.some(r=>r.w===s.width&&r.h===s.height))?'display:none;':''}">
        <input type="number" data-sc="reserve" data-i="${i}" value="${s.reserve}" min="0" max="99"
          title="예약 매수 — 0 이면 안 뽑습니다" style="width:44px;text-align:center;">
        <button class="danger" data-scdel="${i}">✕</button></div>
      <textarea data-sc="prompt" data-i="${i}" placeholder="씬 프롬프트 — 배경·구도·분위기 (베이스에 붙습니다)">${esc(s.prompt||'')}</textarea>
      <input type="text" data-sc="negative" data-i="${i}" placeholder="씬 전용 네거티브 (선택)" value="${escA(s.negative||'')}">
      <!-- ★ 인물 묘사는 여기에. 씬 프롬프트에 넣으면 베이스로 가서 왼쪽 캐릭터와 뭉개진다. -->
      <div class="hint" style="margin:5px 0 3px;">인물 칸 — <b>사람 묘사는 여기</b>에 넣으세요
        (비우면 왼쪽 [캐릭터] 그대로 · 둘 다 있으면 이어 붙습니다)</div>
      <div class="grid2">
        <div class="field"><label>인물 1</label>
          <input type="text" data-sc="char1" data-i="${i}" placeholder="예: 1girl, blue hair, smile" value="${escA(s.char1||'')}"></div>
        <div class="field"><label>인물 2</label>
          <input type="text" data-sc="char2" data-i="${i}" placeholder="예: 1boy, black hair" value="${escA(s.char2||'')}"></div>
        <div class="field"><label>인물 1 네거티브</label>
          <input type="text" data-sc="char1_neg" data-i="${i}" value="${escA(s.char1_neg||'')}"></div>
        <div class="field"><label>인물 2 네거티브</label>
          <input type="text" data-sc="char2_neg" data-i="${i}" value="${escA(s.char2_neg||'')}"></div>
      </div>`;
    host.appendChild(el);
  });
  /* 프리셋을 고르면 가로·세로를 채우고 직접 입력 칸을 숨긴다 (직접 입력을 고르면 다시 보인다) */
  host.querySelectorAll('[data-scres]').forEach(sel => sel.addEventListener('change', () => {
    const i = +sel.dataset.scres, s2 = SCENES[i];
    if(sel.value){
      const [w, h] = sel.value.split('x').map(Number);
      s2.width = w; s2.height = h;
      s2.custom_res = false;
      scenesSave(true);
    } else {
      /* '직접 입력' 을 고르면 칸을 보여 주고 **다시 그리지 않는다**.
         다시 그리면 지금 크기가 프리셋과 맞아떨어져 프리셋으로 되돌아가 버린다. */
      s2.custom_res = true;
      const row = sel.closest('.r1');
      row.querySelectorAll('[data-sc="width"], [data-sc="height"]')
         .forEach(x => x.style.display = '');
      scenesSave(false);
    }
  }));
  host.querySelectorAll('[data-sc]').forEach(e => e.addEventListener('change', () => {
    const s = SCENES[+e.dataset.i], k = e.dataset.sc;
    s[k] = (k === 'width' || k === 'height' || k === 'reserve') ? (Number(e.value)||0) : e.value;
    scenesSave();
  }));
  /* 끌어서 순서 바꾸기 — 씬은 순서대로 생성되므로 순서가 곧 작업 순서다 */
  let dragFrom = -1;
  host.querySelectorAll('[data-si]').forEach(el => {
    el.addEventListener('dragstart', e => {
      dragFrom = +el.dataset.si; el.style.opacity = '.4';
      e.dataTransfer.effectAllowed = 'move';
    });
    el.addEventListener('dragend', () => { el.style.opacity = ''; });
    el.addEventListener('dragover', e => {
      e.preventDefault();
      el.style.borderTopColor = 'var(--accent)';
    });
    el.addEventListener('dragleave', () => { el.style.borderTopColor = ''; });
    el.addEventListener('drop', e => {
      e.preventDefault(); el.style.borderTopColor = '';
      const to = +el.dataset.si;
      if(dragFrom < 0 || dragFrom === to) return;
      const [moved] = SCENES.splice(dragFrom, 1);
      SCENES.splice(to, 0, moved);
      dragFrom = -1;
      scenesSave(true);
    });
  });
  host.querySelectorAll('[data-scdel]').forEach(b => b.addEventListener('click', () => {
    if(!confirm(`씬 '${SCENES[+b.dataset.scdel].name}' 을 지울까요?`)) return;
    SCENES.splice(+b.dataset.scdel, 1); scenesSave(true);
  }));
}
async function scenesSave(redraw){
  const r = await (await fetch('/api/scenes_save', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({scenes: SCENES})})).json();
  if(r.ok){ SCENES = r.scenes; if(redraw) renderScenes(); else {
    const booked = SCENES.reduce((a,s)=>a+(Number(s.reserve)||0),0);
    $('sceneCount').textContent = `${SCENES.length}개 · 예약 ${booked}장`;
  } $('sceneMsg').textContent = '저장됨 ✓'; }
  else $('sceneMsg').textContent = r.error || '저장 실패';
}
$('sceneAdd').addEventListener('click', () => {
  SCENES.push({name: `씬 ${SCENES.length+1}`, prompt:'', negative:'',
               char1:'', char2:'', char1_neg:'', char2_neg:'',
               width: Number(STATE.width)||832, height: Number(STATE.height)||1216, reserve: 1});
  scenesSave(true);
});
$('sceneRun').addEventListener('click', async () => {
  const r = await (await fetch('/api/scenes_run', {method:'POST'})).json();
  $('sceneMsg').textContent = r.ok ? `${r.count}장 생성 시작` : (r.error || '실패');
});

/* ── 태그 자동완성 ──────────────────────────────────────────────────
   프롬프트 칸에서 마지막 콤마 뒤의 토막을 사전에서 찾아 띄운다.
   ↑↓ 로 고르고 Enter/Tab 으로 넣고 Esc 로 닫는다.
   가중치 표기(`1.4::`)와 조각(`<이름>`)은 건드리지 않는다. */
let AC = {box:null, items:[], sel:-1, target:null, from:0, to:0, timer:null};

function acClose(){
  if(AC.box) AC.box.remove();
  AC = {box:null, items:[], sel:-1, target:null, from:0, to:0, timer:AC.timer};
}
/* 캐럿 앞의 '쓰고 있는 토막' 을 찾는다 — 콤마·줄바꿈·`::`·`<>` 가 경계다 */
function acFragment(el){
  /* 캐럿 앞의 '쓰고 있는 토막' 을 찾는다.
     경계는 콤마·줄바꿈·`:`·`<>{}[]` 다. 정규식에 줄바꿈 이스케이프를 쓰면
     문자열로 심을 때 실제 줄바꿈으로 바뀌어 깨지므로 문자 비교로 찾는다. */
  const pos = el.selectionStart ?? 0;
  const left = el.value.slice(0, pos);
  const NL = String.fromCharCode(10);
  const BOUND = ',' + NL + String.fromCharCode(13) + ':<>{}[]';
  let a = pos;
  while(a > 0 && BOUND.indexOf(left[a-1]) < 0) a--;
  const frag = left.slice(a);
  const trimmed = frag.replace(/^ +/, '');
  return {text: trimmed, from: pos - trimmed.length, to: pos};
}

async function acQuery(el){
  const f = acFragment(el);
  if(!f || f.text.trim().length < 2){ acClose(); return; }
  const q = f.text.trim();
  let r;
  try{ r = await (await fetch('/api/ac?q=' + encodeURIComponent(q) + '&limit=12')).json(); }
  catch(e){ return; }
  if(!r.ok || !r.items.length){ acClose(); return; }
  /* 요청 도중에 다른 칸으로 옮겼거나 글자가 바뀌었으면 버린다 */
  const now = acFragment(el);
  if(document.activeElement !== el || !now || now.text.trim() !== q) return;
  acShow(el, r.items, now);
}
function acShow(el, items, f){
  acClose();
  AC.target = el; AC.items = items; AC.sel = 0; AC.from = f.from; AC.to = f.to;
  const box = document.createElement('div');
  box.className = 'acbox';
  box.innerHTML = items.map((it, i) =>
    `<div class="acrow${i === 0 ? ' on' : ''}" data-ac="${i}">
       <span class="t">${esc(it.tag)}</span>
       <span class="n">${it.count >= 1000 ? Math.round(it.count/1000) + 'k' : it.count}</span>
     </div>`).join('');
  document.body.appendChild(box);
  AC.box = box;
  /* 칸 아래에 붙인다 (화면 밖으로 나가면 위로) */
  const r = el.getBoundingClientRect();
  const h = Math.min(items.length * 24 + 8, 260);
  const below = window.innerHeight - r.bottom > h + 8;
  box.style.left = Math.min(r.left, window.innerWidth - 250) + 'px';
  box.style.top = (below ? r.bottom + 3 : r.top - h - 3) + 'px';
  box.style.width = Math.max(200, Math.min(r.width, 330)) + 'px';
  box.querySelectorAll('[data-ac]').forEach(row =>
    row.addEventListener('mousedown', e => { e.preventDefault(); acPick(+row.dataset.ac); }));
}
function acMove(d){
  if(!AC.box) return;
  AC.sel = (AC.sel + d + AC.items.length) % AC.items.length;
  AC.box.querySelectorAll('.acrow').forEach((r, i) => r.classList.toggle('on', i === AC.sel));
  const on = AC.box.querySelector('.acrow.on');
  if(on) on.scrollIntoView({block:'nearest'});
}
function acPick(i){
  const el = AC.target, it = AC.items[i ?? AC.sel];
  if(!el || !it) return acClose();
  const before = el.value.slice(0, AC.from), after = el.value.slice(AC.to);
  /* 뒤에 이미 콤마/줄바꿈이 있으면 또 붙이지 않는다 (이스케이프 없이 문자 비교) */
  const nx = after.replace(/^ +/, '')[0] || '';
  const tail = (nx === ',' || nx === String.fromCharCode(10) || nx === '') ? '' : ', ';
  el.value = before + it.tag + tail + after;
  const caret = (before + it.tag + tail).length;
  acClose();
  el.focus(); el.selectionStart = el.selectionEnd = caret;
  el.dispatchEvent(new Event('input', {bubbles:true}));
}
/* 프롬프트 성격의 칸에만 붙인다 */
function acAttach(el){
  if(!el || el._ac) return;
  el._ac = true;
  el.addEventListener('input', () => {
    clearTimeout(AC.timer);
    AC.timer = setTimeout(() => acQuery(el), 160);
  });
  el.addEventListener('keydown', e => {
    if(!AC.box || AC.target !== el) return;
    if(e.key === 'ArrowDown'){ e.preventDefault(); acMove(1); }
    else if(e.key === 'ArrowUp'){ e.preventDefault(); acMove(-1); }
    else if(e.key === 'Enter' || e.key === 'Tab'){ e.preventDefault(); acPick(); }
    else if(e.key === 'Escape'){ e.preventDefault(); acClose(); }
  });
  el.addEventListener('blur', () => setTimeout(acClose, 120));
}
/* 지금 있는 것 + 나중에 그려지는 것 모두 (세팅·씬·캐릭터 칸은 다시 그려진다) */
function acScan(root){
  (root || document).querySelectorAll(
    '#basePrompt, #negPrompt, [data-s3], [data-sf="prompt"], [data-sf="outfit"], ' +
    '[data-sf="negative"], [data-cf="prompt"], [data-cf="negative"], ' +
    '[data-sc="prompt"], [data-sc="char1"], [data-sc="char2"], ' +
    '[data-role], [data-flines], #fragTry'
  ).forEach(acAttach);
}
new MutationObserver(() => acScan(document)).observe(document.body, {childList:true, subtree:true});

/* ── 프롬프트 3분할 (고정 / 가변 / 디테일) ─────────────────────────
   보내는 값은 여전히 basePrompt 하나다. 세 칸을 이어 붙여 거기에 써 넣으므로
   생성·토큰 계산·그림체 저장 등 아랫단은 아무것도 안 바뀐다. */
function split3On(){ return !!(STATE.ui && STATE.ui.split3); }
function joinSplit3(){
  const v = ['baseFixed','baseVar','baseDetail']
    .map(id => ($(id).value || '').trim().replace(/,\s*$/, ''))
    .filter(Boolean);
  STATE.base_fixed = $('baseFixed').value;
  STATE.base_var = $('baseVar').value;
  STATE.base_detail = $('baseDetail').value;
  $('basePrompt').value = v.join(', ');
  STATE.base_prompt = $('basePrompt').value;
  clearActiveStyle();
}
function applySplit3(){
  const on = split3On();
  $('split3').classList.toggle('hidden', !on);
  $('basePrompt').classList.toggle('hidden', on);
  $('split3Btn').style.color = on ? 'var(--accent)' : '';
  if(on){
    /* 처음 켤 때 — 기존 프롬프트를 통째로 '고정' 에 넣는다. 내용이 사라지면 안 된다 */
    if(!(STATE.base_fixed || STATE.base_var || STATE.base_detail))
      STATE.base_fixed = STATE.base_prompt || '';
    $('baseFixed').value = STATE.base_fixed || '';
    $('baseVar').value = STATE.base_var || '';
    $('baseDetail').value = STATE.base_detail || '';
    joinSplit3();
  }
}
if($('findRepBtn')) $('findRepBtn').addEventListener('click', openFindReplace);
$('split3Btn').addEventListener('click', () => {
  STATE.ui = STATE.ui || {};
  STATE.ui.split3 = !split3On();
  applySplit3(); tokens(); save();
});
document.querySelectorAll('[data-s3]').forEach(t => t.addEventListener('input', () => {
  joinSplit3(); tokens(); save();
}));

/* ── 조각 (와일드카드) ─────────────────────────────────────────────
   조각/*.txt 가 원본이다. 앱은 그 파일을 읽고 쓴다. */
function renderFrags(){
  const host = $('fragList'); if(!host) return;
  host.innerHTML = '';
  const names = Object.keys(FRAGS).sort();
  $('bgFrags').textContent = names.length;
  $('bgFrags').style.display = names.length ? 'flex' : 'none';
  if(!names.length){
    host.innerHTML = '<p class="hint">아직 조각이 없습니다. [+ 새 조각] 을 누르거나 TXT 를 가져오세요.</p>';
    return;
  }
  names.forEach(n => {
    const lines = FRAGS[n] || [];
    const el = document.createElement('div'); el.className = 'slot';
    el.innerHTML = `<div class="r1">
        <input type="text" data-fname value="${escA(n)}" data-old="${escA(n)}" style="flex:1;">
        <span class="tag">${lines.length}줄${lines.length===1?' · 고정':''}</span>
        <button data-fins="${escA(n)}" title="프롬프트 칸에 &lt;${escA(n)}&gt; 넣기">＜＞</button>
        <button data-finsq="${escA(n)}" title="차례대로 쓰기 — &lt;*${escA(n)}&gt; 넣기">＜*＞</button>
        <button class="danger" data-fdel="${escA(n)}">✕</button></div>
      <textarea data-flines style="min-height:64px;" placeholder="한 줄에 하나씩">${esc(lines.join('\\n'))}</textarea>`;
    host.appendChild(el);
  });
  host.querySelectorAll('[data-flines]').forEach(t => t.addEventListener('change', async () => {
    const slot = t.closest('.slot'), inp = slot.querySelector('[data-fname]');
    await fragSave(inp.dataset.old, inp.value, t.value.split('\n'));
  }));
  host.querySelectorAll('[data-fname]').forEach(i => i.addEventListener('change', async () => {
    const slot = i.closest('.slot');
    await fragSave(i.dataset.old, i.value, slot.querySelector('[data-flines]').value.split('\n'));
  }));
  host.querySelectorAll('[data-fdel]').forEach(b => b.addEventListener('click', async () => {
    if(!confirm(`조각 '${b.dataset.fdel}' 을 지울까요? (조각/${b.dataset.fdel}.txt 파일이 지워집니다)`)) return;
    const r = await (await fetch('/api/frag_del', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: b.dataset.fdel})})).json();
    if(r.ok){ FRAGS = r.fragments; renderFrags(); $('fragMsg').textContent = '지웠습니다'; }
  }));
  host.querySelectorAll('[data-fins]').forEach(b => b.addEventListener('click',
    () => insertAtPrompt('<' + b.dataset.fins + '>')));
  host.querySelectorAll('[data-finsq]').forEach(b => b.addEventListener('click',
    () => insertAtPrompt('<*' + b.dataset.finsq + '>')));
}
/* 마지막으로 만졌던 프롬프트 칸에 끼워 넣는다 */
let LAST_PROMPT = null;
['basePrompt','negPrompt'].forEach(id => {
  const e = $(id); if(e) e.addEventListener('focus', () => LAST_PROMPT = e);
});
function insertAtPrompt(txt){
  const t = LAST_PROMPT || $('basePrompt');
  const a = t.selectionStart ?? t.value.length, b = t.selectionEnd ?? a;
  const need = a > 0 && !/[\s,]$/.test(t.value.slice(0, a));
  const ins = (need ? ', ' : '') + txt;
  t.value = t.value.slice(0, a) + ins + t.value.slice(b);
  t.focus(); t.selectionStart = t.selectionEnd = a + ins.length;
  t.dispatchEvent(new Event('input', {bubbles:true}));
  $('fragMsg').textContent = txt + ' 넣음';
}
async function fragSave(old, name, lines){
  const r = await (await fetch('/api/frag_save', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({old, name, lines})})).json();
  if(r.ok){ FRAGS = r.fragments; renderFrags(); $('fragMsg').textContent = `'${r.name}' 저장 ✓`; }
  else $('fragMsg').textContent = r.error || '저장 실패';
}
$('fragNew').addEventListener('click', async () => {
  const n = prompt('조각 이름 (프롬프트에서 <이름> 으로 씁니다):'); if(!n) return;
  await fragSave('', n, ['첫 줄', '둘째 줄']);
});
$('fragExport').addEventListener('click', () => {
  $('fragMsg').textContent = '내보내는 중...';
  window.location.href = '/api/frag_export';
  setTimeout(() => { $('fragMsg').textContent = '내보냄 ✓'; }, 800);
});
$('fragImport').addEventListener('click', () => $('fragImportFile').click());
$('fragImportFile').addEventListener('change', async () => {
  const files = [...$('fragImportFile').files]; if(!files.length) return;
  const added = [], skipped = [];
  for(const f of files){
    $('fragMsg').textContent = `${f.name} 넣는 중...`;
    const r = await (await fetch('/api/frag_import', {method:'POST',
      headers:{'X-Filename': encodeURIComponent(f.name)}, body: f})).json();
    (r.added||[]).forEach(x => added.push(x));
    (r.skipped||[]).forEach(x => skipped.push(x));
    if(r.fragments) FRAGS = r.fragments;
  }
  $('fragImportFile').value = '';
  renderFrags();
  $('fragMsg').textContent = (added.length ? `${added.length}개 들어옴` : '들어온 것 없음')
    + (skipped.length ? ` · 건너뜀: ${skipped[0]}` : '');
});
$('fragReset').addEventListener('click', async () => {
  const r = await (await fetch('/api/frag_reset', {method:'POST'})).json();
  $('fragMsg').textContent = r.ok ? '순번을 처음으로 돌렸습니다' : (r.error || '실패');
});
let fragTryT = null;
$('fragTry').addEventListener('input', () => {
  clearTimeout(fragTryT);
  fragTryT = setTimeout(async () => {
    const t = $('fragTry').value;
    if(!t){ $('fragTryOut').textContent = ''; return; }
    const r = await (await fetch('/api/frag_try', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({text:t})})).json();
    $('fragTryOut').textContent = r.ok ? '→ ' + r.text : (r.error || '');
  }, 300);
});

/* ── 세팅 내보내기 / 가져오기 / 세트 대표 그림 ────────────────────
   세팅은 '세팅/ 폴더의 파일' 이므로 주고받기는 파일 단위로 한다. */
$('setExport').addEventListener('click', () => {
  /* 켜 둔 세팅만 내보낸다. 하나도 안 켜 뒀으면 전부 */
  const on = SETTINGS.filter(st => stState(st.name).use !== false).map(st => st.name);
  const q = (on.length && on.length < SETTINGS.length)
    ? on.map(n => 'name=' + encodeURIComponent(n)).join('&') : '';
  $('setMsg').textContent = (q ? `${on.length}개` : '전체') + ' 내보내는 중...';
  window.location.href = '/api/setting_export' + (q ? '?' + q : '');
  setTimeout(() => { $('setMsg').textContent = '내보냄 ✓'; }, 800);
});
/* ── 자료팩 넣기 ───────────────────────────────────────────────────
   배포본에 수집물을 넣지 않으므로 여기로 받는다. 서버가 합쳐 주고(덮어쓰지 않음)
   무엇이 몇 건 들어왔는지 그대로 보여 준다. */
function esc(s){ return String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

/* 가져온 기록 — 넣고 나서 정리하려면 '이번에 무엇이 들어왔나' 를 볼 수 있어야 한다.
   되돌리기는 **그때 새로 들어온 것만** 뺀다 (원래 갖고 있던 자료는 안 건드린다). */
function renderPackLog(log){
  const host = $('packLog'); if(!host) return;
  if(!log || !log.length){ host.innerHTML = ''; return; }
  host.innerHTML = '<div class="hint" style="margin-bottom:4px;">장착한 자료팩</div>' +
    log.map(b => `<div class="bar" style="gap:8px;align-items:flex-start;
        padding:6px 0;border-top:1px solid var(--line);">
      <div style="flex:1;min-width:0;">
        <div style="font-size:var(--fs-sm);">${esc(b.at)} · ${esc(b.pack_name || b.file)}
          <b>새로 ${b['새로']||0}</b></div>
        <div class="hint" style="font-size:var(--fs-2xs);">${esc(b['요약']||'')}
          ${b.content_sha256 ? ` · SHA-256 ${esc(b.content_sha256.slice(0,12))}` : ''}</div>
      </div>
      <button data-undo="${esc(b.id)}" title="이 팩으로 새로 들어온 것만 뺍니다">해제</button>
    </div>`).join('');
  host.querySelectorAll('[data-undo]').forEach(btn => btn.addEventListener('click', async () => {
    if(!confirm('이 자료팩으로 새로 들어온 것만 뺍니다. 개인 자료는 그대로 둡니다. 해제할까요?')) return;
    btn.disabled = true;
    const r = await (await fetch('/api/pack_undo', {method:'POST',
      body: JSON.stringify({id: btn.dataset.undo})})).json();
    $('packMsg').innerHTML = r.error ? esc(r.error) : (r.report||[]).map(esc).join('<br>');
    renderPackLog(r.log); await reloadConfig();
  }));
}

async function loadDataStorageStatus(){
  const host = $('dataStorageStatus'); if(!host) return;
  try{
    const r = await (await fetch('/api/data_storage')).json();
    if(!r.ok){ host.textContent = r.error || '자료 저장 위치를 확인하지 못했습니다.'; return; }
    const where = r.separated ? '<b>프로그램과 분리됨</b>' : '<b>소스·휴대 모드</b>';
    const idx = r.index
      ? ` · 마지막 색인 ${Number(r.index.files||0).toLocaleString()}개`
        + ` / ${(Number(r.index.bytes||0)/1024/1024).toFixed(1)}MB`
        + ` · ${esc(r.index.generated_at||'')}`
      : ' · 아직 만든 색인 없음';
    const moved = r.migration && Number(r.migration.copied||0)
      ? ` · 옛 설치 자료 ${Number(r.migration.copied).toLocaleString()}개를 원본을 남긴 채 복사함`
      : '';
    host.innerHTML = `<div>${where}${idx}</div>
      <div style="margin-top:3px;">개인 자료 폴더
        <span style="font-family:var(--mono);word-break:break-all;">${esc(r.data_dir)}</span>
        ${moved}</div>`;
  }catch(e){ host.textContent = '자료 저장 위치 확인 실패: ' + e; }
}

if($('dataIndexBuild')) $('dataIndexBuild').addEventListener('click', async () => {
  const btn = $('dataIndexBuild');
  btn.disabled = true;
  $('dataStorageStatus').textContent = '원본을 바꾸지 않고 파일별 SHA-256 색인을 만드는 중입니다...';
  try{
    const r = await (await fetch('/api/data_index_rebuild', {method:'POST', body:'{}'})).json();
    if(!r.ok){ $('dataStorageStatus').textContent = r.error || '자료 색인 생성 실패'; return; }
    await loadDataStorageStatus();
  }catch(e){ $('dataStorageStatus').textContent = '자료 색인 생성 실패: ' + e; }
  finally{ btn.disabled = false; }
});

async function sendPack(files){
  if(!files.length) return;
  const lines = [];
  let log = null;
  const over = $('packOver') && $('packOver').checked ? '?overwrite=1' : '';
  for(const f of files){
    $('packMsg').textContent = f.name + ' 넣는 중... (큰 팩은 시간이 걸립니다)';
    let r;
    try{
      r = await (await fetch('/api/pack_import' + over, {method:'POST',
        headers:{'X-Filename': encodeURIComponent(f.name)}, body: f})).json();
    }catch(e){ r = {ok:false, error:String(e)}; }
    if(r.error) lines.push(f.name + ': ' + r.error);
    else (r.report || []).forEach(x => lines.push(x));
    if(r.log) log = r.log;
  }
  $('packMsg').innerHTML = lines.map(esc).join('<br>') || '들어온 것 없음';
  if(log) renderPackLog(log);
  await reloadConfig();
}
if($('packDrop')){
  $('packDrop').addEventListener('click', () => $('packFile').click());
  $('packFile').addEventListener('change', async () => {
    const fs = [...$('packFile').files]; $('packFile').value = '';
    await sendPack(fs);
  });
  $('packDrop').addEventListener('dragover', e => {
    e.preventDefault(); $('packDrop').style.borderColor = 'var(--accent)';
  });
  $('packDrop').addEventListener('dragleave', () => {
    $('packDrop').style.borderColor = '';
  });
  $('packDrop').addEventListener('drop', async e => {
    e.preventDefault(); $('packDrop').style.borderColor = '';
    await sendPack([...(e.dataTransfer.files || [])]);
  });
  /* 화면을 처음 열 때 지난 기록을 보여 준다 (앱을 껐다 켜도 남아 있다) */
  fetch('/api/pack_log').then(r => r.json())
    .then(r => renderPackLog(r.log)).catch(() => {});
  loadDataStorageStatus();
}

$('setImport').addEventListener('click', () => $('setImportFile').click());
$('setImportFile').addEventListener('change', async () => {
  const files = [...$('setImportFile').files];
  if(!files.length) return;
  const added = [], skipped = [];
  for(const f of files){
    $('setMsg').textContent = `${f.name} 넣는 중...`;
    const r = await (await fetch('/api/setting_import', {method:'POST',
      headers:{'X-Filename': encodeURIComponent(f.name)}, body: f})).json();
    (r.added || []).forEach(x => added.push(x));
    (r.skipped || []).forEach(x => skipped.push(x));
    if(r.error) skipped.push(f.name + ': ' + r.error);
  }
  $('setImportFile').value = '';
  await reloadConfig();
  $('setMsg').textContent = (added.length ? `${added.length}개 들어옴 (${added.join(', ')})` : '들어온 것 없음')
    + (skipped.length ? ` · 건너뜀 ${skipped.length}개: ${skipped[0]}` : '');
});
async function loadSetThumbs(){
  for(const st of SETTINGS){
    const r = await (await fetch('/api/setting_thumbs?name=' + encodeURIComponent(st.name))).json();
    if(!r.ok) continue;
    Object.entries(r.thumbs).forEach(([gid, rel]) => {
      const box = document.querySelector(`[data-ssel="${CSS.escape(st.name)}"][data-id="${gid}"]`);
      if(!box) return;
      const item = box.closest('.item');
      if(!item || item.querySelector('.setthumb')) return;
      const im = document.createElement('img');
      /* 26px 짜리 로컬 파일이라 지연 로딩은 이득이 없다.
         오히려 접힌 구획 안에서는 관찰자가 안 돌아 영영 안 뜬다. */
      im.className = 'setthumb';
      im.src = '/setout?p=' + encodeURIComponent(rel);
      im.title = rel;
      item.insertBefore(im, box.nextSibling);
    });
  }
}
$('setThumbs').addEventListener('change', () => {
  if($('setThumbs').checked){ $('setMsg').textContent = '대표 그림 찾는 중...';
    loadSetThumbs().then(() => { $('setMsg').textContent = '대표 그림 표시 ✓'; }); }
  else { document.querySelectorAll('.setthumb').forEach(e => e.remove());
    $('setMsg').textContent = ''; }
});

/* ── 라이브러리 ── */
var LIB_LIMIT = 100, CHAR_EDIT_LIMIT = 24;
var LIB_FILTER_TIMER = null, CHAR_FILTER_TIMER = null;
function libraryNeedle(value){
  return String(value || '').normalize('NFKC').toLocaleLowerCase();
}
function renderLibrary(){
  const g = $('libGrid'); if(!g) return;
  g.innerHTML = '';
  LIB_LIMIT = Number(LIB_LIMIT) || 100;
  const items = [];
  (STATE.characters||[]).forEach(c => items.push({t:'캐릭터', n:c.name||'(무명)', b:c.female||'', groups:c.groups, ref:c}));
  STYLES.forEach(s => items.push({t:'그림체', n:s.name, b:s.prompt, ref:s}));
  const query = libraryNeedle(($('libFilter')||{}).value);
  const kind = (($('libType')||{}).value) || '';
  const filtered = items.filter(it => {
    if(kind && it.t !== kind) return false;
    if(!query) return true;
    return libraryNeedle([
      it.n, it.b, it.ref && it.ref.clothed,
      it.ref && it.ref.negative, it.ref && it.ref.source,
    ].join(' ')).includes(query);
  });
  const shown = filtered.slice(0, LIB_LIMIT);
  shown.forEach(it => {
    const el = document.createElement('div'); el.className = 'row'; el.style.cursor = 'pointer'; el.style.margin = '0';
    el.innerHTML = `<div class="tag">${it.t}</div><b style="font-size:var(--fs-xs);">${esc(it.n)}</b>
      <div style="font-size:var(--fs-2xs);color:var(--muted);margin-top:4px;max-height:44px;overflow:hidden;">${esc(String(it.b||'').slice(0,100))}</div>`;
    el.addEventListener('click', () => openLib(it));
    g.appendChild(el);
  });
  if(!shown.length){
    g.innerHTML = '<div class="row hint">조건에 맞는 캐릭터·그림체가 없습니다.</div>';
  }
  if($('libCount')) $('libCount').textContent =
    `${shown.length.toLocaleString()} / ${filtered.length.toLocaleString()}개`;
  if($('libMore')){
    $('libMore').style.display = shown.length < filtered.length ? '' : 'none';
    $('libMore').textContent =
      `더 보기 · 남은 ${(filtered.length - shown.length).toLocaleString()}개 ▾`;
  }
  renderCharCards();
}
if($('libFilter')) $('libFilter').addEventListener('input', () => {
  clearTimeout(LIB_FILTER_TIMER);
  LIB_FILTER_TIMER = setTimeout(() => {
    LIB_LIMIT = 100;
    renderLibrary();
  }, 100);
});
if($('libType')) $('libType').addEventListener('change', () => {
  LIB_LIMIT = 100;
  renderLibrary();
});
if($('libMore')) $('libMore').addEventListener('click', () => {
  LIB_LIMIT += 100;
  renderLibrary();
});
if($('charFilter')) $('charFilter').addEventListener('input', () => {
  clearTimeout(CHAR_FILTER_TIMER);
  CHAR_FILTER_TIMER = setTimeout(() => {
    CHAR_EDIT_LIMIT = 24;
    renderCharCards();
  }, 100);
});
if($('charMore')) $('charMore').addEventListener('click', () => {
  CHAR_EDIT_LIMIT += 24;
  renderCharCards();
});
const DELETED_CHARS = [];
function updateCharUndo(){
  const button = $('charUndo'), message = $('charEditMsg');
  if(!button || !message) return;
  button.classList.toggle('hidden', !DELETED_CHARS.length);
  if(DELETED_CHARS.length){
    const last = DELETED_CHARS[DELETED_CHARS.length - 1].character;
    message.textContent = `'${last.name || '캐릭터'}' 삭제됨 · 이 화면에서 되돌릴 수 있습니다.`;
  }else{
    message.textContent = '복제로 의상·예술적 변형을 나누고, 삭제한 항목은 이 화면을 닫기 전 되돌릴 수 있습니다.';
  }
}
function renderCharCards(){
  const h = $('charList'); if(!h) return;
  h.innerHTML = '';
  CHAR_EDIT_LIMIT = Number(CHAR_EDIT_LIMIT) || 24;
  const query = libraryNeedle(($('charFilter')||{}).value);
  const filtered = (STATE.characters||[]).filter(c => !query || libraryNeedle([
    c.name, c.female, c.clothed, c.negative, c.source,
  ].join(' ')).includes(query));
  const shown = filtered.slice(0, CHAR_EDIT_LIMIT);
  shown.forEach(c => {
    const el = document.createElement('div'); el.className = 'slot';
    el.innerHTML = `<div class="r1"><input type="text" data-xc="${c.id}" data-xf="name" value="${escA(c.name)}" placeholder="이름">
      <button data-xdup="${c.id}" title="이 캐릭터를 복사해 의상·변형만 바꿉니다">복제</button>
      <button class="danger" data-xdel="${c.id}">삭제</button></div>
      <textarea data-xc="${c.id}" data-xf="female" placeholder="girl, ...">${esc(c.female)}</textarea>
      <input type="text" data-xc="${c.id}" data-xf="clothed" placeholder="착의 (선택)" value="${escA(c.clothed)}" style="margin-top:4px;">
      <input type="text" data-xc="${c.id}" data-xf="negative" placeholder="전용 네거티브" value="${escA(c.negative)}" style="margin-top:4px;">`;
    h.appendChild(el);
  });
  if(!shown.length){
    h.innerHTML = '<div class="row hint">조건에 맞는 캐릭터가 없습니다.</div>';
  }
  if($('charCount')) $('charCount').textContent =
    `${shown.length.toLocaleString()} / ${filtered.length.toLocaleString()}명`;
  if($('charMore')){
    $('charMore').style.display = shown.length < filtered.length ? '' : 'none';
    $('charMore').textContent =
      `편집할 캐릭터 더 보기 · 남은 ${(filtered.length - shown.length).toLocaleString()}명 ▾`;
  }
  h.querySelectorAll('[data-xc]').forEach(el => el.addEventListener('input', () => {
    const c = (STATE.characters||[]).find(x => x.id === el.dataset.xc);
    if(c){ c[el.dataset.xf] = el.value; save(); }
  }));
  h.querySelectorAll('[data-xdup]').forEach(b => b.addEventListener('click', () => {
    const chars = STATE.characters || [];
    const at = chars.findIndex(x => x.id === b.dataset.xdup);
    if(at < 0) return;
    // 최신 화면 값을 그대로 깊은 복사한다. groups·폴더·전용 네거티브도 보존하되
    // 파일 동기화에서 원본을 덮지 않도록 id와 이름만 새로 만든다.
    const cloned = JSON.parse(JSON.stringify(chars[at]));
    const names = new Set(chars.map(x => String(x.name || '').trim().toLocaleLowerCase()));
    const root = `${String(chars[at].name || '캐릭터').trim() || '캐릭터'} 복사본`;
    let name = root, serial = 2;
    while(names.has(name.toLocaleLowerCase())) name = `${root} ${serial++}`;
    cloned.id = genId();
    cloned.name = name;
    chars.splice(at + 1, 0, cloned);
    renderLibrary(); renderSlots(); save();
    const input = document.querySelector(`[data-xc="${cloned.id}"][data-xf="name"]`);
    if(input){ input.focus(); input.select(); }
    flash(`'${name}' 복제됨 — 이름·의상·예술적 변형을 바꿔 저장하세요.`);
  }));
  h.querySelectorAll('[data-xdel]').forEach(b => b.addEventListener('click', () => {
    const chars = STATE.characters || [];
    const at = chars.findIndex(x => x.id === b.dataset.xdel);
    if(at < 0) return;
    const character = chars[at];
    if(!confirm(`'${character.name || '캐릭터'}'을 삭제할까요? 이 화면을 닫기 전에는 되돌릴 수 있습니다.`)) return;
    DELETED_CHARS.push({character:JSON.parse(JSON.stringify(character)), index:at});
    chars.splice(at, 1);
    renderLibrary(); renderSlots(); updateCharUndo(); save();
  }));
}
$('charUndo').addEventListener('click', () => {
  const deleted = DELETED_CHARS.pop();
  if(!deleted) return;
  const chars = STATE.characters || (STATE.characters = []);
  const restored = deleted.character;
  if(chars.some(x => x.id === restored.id)) restored.id = genId();
  const names = new Set(chars.map(x => String(x.name || '').trim().toLocaleLowerCase()));
  if(names.has(String(restored.name || '').trim().toLocaleLowerCase())){
    const root = `${String(restored.name || '캐릭터').trim() || '캐릭터'} 복구본`;
    let name = root, serial = 2;
    while(names.has(name.toLocaleLowerCase())) name = `${root} ${serial++}`;
    restored.name = name;
  }
  chars.splice(Math.min(deleted.index, chars.length), 0, restored);
  renderLibrary(); renderSlots(); updateCharUndo(); save();
  const input = document.querySelector(`[data-xc="${restored.id}"][data-xf="name"]`);
  if(input) input.focus();
});
$('libAddChar').addEventListener('click', () => {
  (STATE.characters = STATE.characters||[]).push({id:genId(), name:'새 캐릭터', female:'', clothed:'', negative:'', enabled:true});
  if($('libFilter')) $('libFilter').value = '';
  if($('charFilter')) $('charFilter').value = '새 캐릭터';
  LIB_LIMIT = 100; CHAR_EDIT_LIMIT = 24;
  renderLibrary(); save();
});
$('libAddFolder').addEventListener('click', () => {
  (STATE.character_folders = STATE.character_folders||[]).push({id:genId(), name:'새 폴더', parent_id:null});
  save(); alert('폴더 추가됨 (캐릭터 파일이 이 폴더로 저장됩니다)');
});
function openLib(it){
  window._mm = 'lib';
  $('modalTitle').textContent = `${it.t} · ${it.n}`;
  const b = $('modalBody'); b.innerHTML = '';
  if(it.groups && Object.keys(it.groups).length){
    Object.entries(it.groups).forEach(([k,v]) => b.insertAdjacentHTML('beforeend',
      `<div class="row"><div class="tag">${esc(k)}</div><div style="font-size:var(--fs-xs);">${esc(String(v))}</div></div>`));
  } else {
    b.insertAdjacentHTML('beforeend', `<div class="row"><div style="font-family:var(--mono);font-size:var(--fs-2xs);white-space:pre-wrap;">${esc(it.b)}</div></div>`);
  }
  b.insertAdjacentHTML('beforeend', `<div class="bar"><button class="primary" id="libTake">${it.t==='캐릭터'?'왼쪽 캐릭터 칸에 추가':'현재 베이스로 적용'}</button></div>`);
  $('libTake').addEventListener('click', () => {
    if(it.t === '캐릭터'){
      (STATE.char_slots = STATE.char_slots||[]).push({name:it.ref.name||'', prompt:it.ref.female||'', negative:it.ref.negative||''});
      renderSlots(); tokens(); save();
      $('modalFlash').textContent = '왼쪽 캐릭터 칸에 추가됨 ✓';
    } else {
      $('presetSel').value = STYLES.indexOf(it.ref);
      $('presetSel').dispatchEvent(new Event('change'));
      $('modalFlash').textContent = '베이스로 적용됨 ✓';
    }
  });
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
}

/* ── 그림체 라이브러리 ──────────────────────────────────────────────
   한 그림체 = 작가 조합 + 베이스 + 네거티브 + 생성 설정값 전부(시드·CFG·
   리스케일·스텝·샘플러·스케줄러·해상도·Variety+). 셋이 합쳐져야 그림체다. */
let comboOffset = 0, comboT = null, COMBO_RETURN = null, WELCOME_COUNT_TIMER = null;
const CARD_PX = {small: 74, medium: 116, large: 190};
function cq(){ return {
  q: ($('comboQ')||{}).value || '', tab: ($('comboTab')||{}).value || '',
  source: ($('comboSrc')||{}).value || '', sort: ($('comboSort')||{}).value || '',
  seeded: ($('comboSeeded')||{}).checked ? '1' : '',
  rating: ($('comboRate')||{}).value || '',
  size: +(($('comboSize')||{}).value || 50) }; }

function openCombos(target){
  if(WELCOME_COUNT_TIMER){
    clearTimeout(WELCOME_COUNT_TIMER);
    WELCOME_COUNT_TIMER = null;
  }
  /* 빌더 안에서 열면 기존 빌더 DOM을 지우지 않고 잠시 떼어 둔다.
     예전에는 innerHTML로 빌더를 지운 뒤 이미 사라진 select를 target으로 들고 있어,
     '이 조합 쓰기'를 눌러도 아무 일도 하지 못했다. */
  if(target && document.body.contains(target)){
    const saved = document.createDocumentFragment();
    while($('modalBody').firstChild) saved.appendChild($('modalBody').firstChild);
    COMBO_RETURN = {
      body:saved, target, mode:window._mm,
      title:$('modalTitle').textContent, flash:$('modalFlash').textContent,
      saveDisplay:$('modalSave').style.display,
    };
  }else{
    COMBO_RETURN = null;
    target = null;
  }
  window._mm = 'combo';
  window._comboTarget = target || null;   // 빌더 슬롯이면 select, 아니면 설정에 적용
  $('modalSave').style.display = 'none';
  $('modalTitle').textContent = '🎨 그림체 — 프롬프트·네거티브·설정값 한 세트';
  $('modalBody').innerHTML = `
    ${COMBO_RETURN ? '<div class="bar"><button type="button" id="comboBack">← 빌더로 돌아가기</button></div>' : ''}
    <p class="hint">작가 조합만이 아니라 <b>베이스 + 네거티브 + 설정값(CFG·리스케일·스텝·샘플러·시드)</b>이
    합쳐진 한 세트입니다. <b>쪼개지 않고 통째로만</b> 적용합니다 —
    일부만 가져오면 원래 그림이 재현되지 않기 때문입니다.</p>
    <div class="filterbar">
      <input type="text" id="comboQ" placeholder="🔍 작가·제목·프롬프트 검색 (띄어쓰기로 여러 단어)">
      <select id="comboSort" title="정렬">
        <option value="default">기본순</option><option value="recommend">추천순</option>
        <option value="views">조회순</option><option value="newest">최신순</option>
        <option value="oldest">오래된순</option><option value="artists">작가 많은순</option>
      </select>
      <select id="comboTab" title="게시판"><option value="all">전체 판</option>
        <option value="NAI">NAI</option><option value="R18_NAI">🔞 NAI</option></select>
      <select id="comboSrc" title="출처"><option value="all">전체 출처</option></select>
      <select id="comboSize" title="표시 개수">
        <option selected>20</option><option>50</option><option>100</option><option>200</option></select>
      <select id="comboCard" title="카드 크기">
        <option value="small">작게</option><option value="medium" selected>보통</option>
        <option value="large">크게</option></select>
      <label class="hint"><input type="checkbox" id="comboSeeded"> 설정값만</label>
      <select id="comboRate" title="작가 평가 필터">
        <option value="">평가 전체</option><option value="fav">💛 즐겨찾기만</option>
        <option value="rated">★ 별점 매긴 것만</option><option value="hideblock">⛔ 차단 숨기기</option></select>
      <span class="n" id="comboStat"></span>
    </div>
    <div id="comboDrop" class="row" style="text-align:center;padding:14px;border-style:dashed;cursor:pointer;">
      <b>＋ 이미지에서 그림체 뽑기</b>
      <div class="hint" style="margin-top:4px;">NAI로 만든 PNG/WebP를 여기에 끌어다 놓거나 눌러서 고르세요.
      프롬프트·네거티브·설정값을 통째로 읽어옵니다. (novelai.net/inspect 와 같은 데이터)</div>
      <input type="file" id="comboFile" accept="image/png,image/webp" multiple style="display:none;"></div>
    <div class="filterbar" style="gap:8px;flex-wrap:wrap;">
      <label class="hint" style="display:flex;align-items:center;gap:4px;white-space:nowrap;">
        <input type="checkbox" id="comboTidy" style="width:auto;flex:none;"> 🧹 정리하기</label>
      <span id="comboTidyBar" class="hidden" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
        <button id="comboAll" class="mini">보이는 것 전부</button>
        <button id="comboNone" class="mini">고르기 해제</button>
        <button id="comboDupes" class="mini">🔁 겹친 것 찾기</button>
        <button id="comboDel" class="mini" style="color:var(--bad);">고른 것 지우기</button>
        <button id="comboUndo" class="mini">↩ 되살리기</button>
        <span id="comboPickN" class="hint"></span>
      </span>
    </div>
    <div id="comboTidyMsg" class="hint"></div>
    <div id="comboList"></div>
    <div class="bar"><button id="comboMore" style="flex:1;">더 보기 ▾</button></div>`;
  if($('comboBack')) $('comboBack').addEventListener('click', () => returnToBuilder());
  bindTidy();
  $('comboQ').addEventListener('input', () => { clearTimeout(comboT); comboT = setTimeout(() => loadCombos(false), 300); });
  ['comboSort','comboTab','comboSrc','comboSize','comboSeeded','comboRate'].forEach(id =>
    $(id).addEventListener('change', () => loadCombos(false)));
  $('comboCard').addEventListener('change', () => {
    const px = CARD_PX[$('comboCard').value] || 116;
    $('comboList').querySelectorAll('img').forEach(i => { i.style.width = px+'px'; i.style.height = px+'px'; });
  });
  $('comboMore').addEventListener('click', () => loadCombos(true));
  setupInspectDrop();
  loadCombos(false);
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
}

function returnToBuilder(comboValue){
  const back = COMBO_RETURN;
  if(!back) return false;
  $('modalBody').replaceChildren(back.body);
  $('modalTitle').textContent = back.title;
  window._mm = back.mode;
  $('modalSave').style.display = back.saveDisplay;
  window._comboTarget = null;
  COMBO_RETURN = null;
  const target = back.target;
  if(comboValue != null && document.body.contains(target)){
    if(![...target.options].some(o => o.value === comboValue)){
      const option = document.createElement('option');
      option.value = comboValue;
      option.textContent = comboValue.slice(0, 60) + (comboValue.length > 60 ? '…' : '');
      target.insertBefore(option, target.options[1] || null);
    }
    target.value = comboValue;
    if(window._bldRefresh) window._bldRefresh();
    $('modalFlash').textContent = '작가 조합을 넣고 빌더로 돌아왔습니다 ✓';
  }else{
    $('modalFlash').textContent = back.flash || '';
  }
  return true;
}

function discardComboReturn(){
  COMBO_RETURN = null;
  window._comboTarget = null;
  $('modalSave').style.display = '';
}

/* ── 그림에서 읽은 그림체 보여 주기 ────────────────────────────────
   ★ 그림체는 `베이스 + 네거티브 + NAI 생성 설정 전체` 가 **분리 불가능한 한 덩어리**다.
     화면에서 읽기 좋게 나눠 보여줄 수는 있어도 **적용은 언제나 통째로** 한다.
   예전에는 항목마다 체크박스를 두어 골라 넣게 했는데(`applyStyle(c, pick)`),
   그렇게 섞으면 베이스는 이 그림 것인데 설정값은 남의 것인 잡종이 되어
   **원래 그림이 재현되지 않는다.** 그래서 고르는 길을 없앴다. */
function openApplyPicker(c){
  const p = c.params || {};
  const rows = [
    ['프롬프트(베이스)', c.base ? c.base.slice(0, 90) : '', !!c.base],
    ['네거티브', (c.negative || (c.negative_full != null ? '(비움)' : '')).slice(0, 90),
      !!(c.negative || c.negative_full != null)],
    ['설정값 (CFG·리스케일·스텝·샘플러·스케줄)',
      [p.scale != null ? `CFG ${p.scale}` : '', p.cfg_rescale != null ? `리스케일 ${p.cfg_rescale}` : '',
       p.steps ? `${p.steps}스텝` : '', p.sampler || '', p.noise_schedule || ''].filter(Boolean).join(' · '),
      p.scale != null || p.steps != null || !!p.sampler],
    ['해상도', (p.width && p.height) ? `${p.width}×${p.height}` : '', !!(p.width && p.height)],
    ['UC 프리셋 · 퀄리티 태그',
      [p.uc_preset != null ? `UC ${p.uc_preset}` : '', p.quality_toggle != null ? (p.quality_toggle ? '퀄리티 켬' : '퀄리티 끔') : ''].filter(Boolean).join(' · '),
      p.uc_preset != null || p.quality_toggle != null],
    ['시드', p.seed ? String(p.seed) : '', !!p.seed],
  ].filter(r => r[2]);
  $('modalTitle').textContent = '🖼 그림에서 읽은 그림체';
  $('modalBody').innerHTML = `
    <p class="hint">그림체는 <b>베이스·네거티브·생성 설정이 한 덩어리</b>입니다.
    쪼개서 넣으면 원래 그림이 재현되지 않으므로 <b>통째로만</b> 넣습니다.</p>
    ${rows.map(([label, val]) => `<div class="row">
      <b>${esc(label)}</b>
      ${val ? `<div class="hint" style="font-family:var(--mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(val)}</div>` : ''}</div>`).join('')}
    <div class="bar"><button class="primary" id="impAll">그림체 통째로 적용</button></div>`;
  $('modalBg').style.display = 'flex';
  $('impAll').addEventListener('click', () => {
    applyStyle(c);
    $('modalBg').style.display = 'none';
  });
}

/* ── ⇄ 찾아 바꾸기 (SDStudio 의 FindReplaceDialog) ─────────────────────
   프롬프트·네거티브·3분할·캐릭터 칸(외형·의상·전용 네거티브)을 한꺼번에.
   작가를 통째로 갈아끼우거나 오타를 한 번에 고칠 때 쓴다. 미리보기 후 적용. */
function openFindReplace(){
  $('modalTitle').textContent = '⇄ 찾아 바꾸기';
  $('modalBody').innerHTML = `
    <p class="hint">프롬프트·네거티브·캐릭터 칸에서 한꺼번에 바꿉니다. 먼저 <b>몇 군데인지</b> 보여 주고,
    <b>바꾸기</b>를 눌러야 실제로 바뀝니다.</p>
    <div class="bar"><input type="text" id="frFind" placeholder="찾을 말 (예: artist:wanke)" style="flex:1;">
      <input type="text" id="frRepl" placeholder="바꿀 말 (비우면 지움)" style="flex:1;"></div>
    <div class="bar" style="flex-wrap:wrap;">
      <label class="hint"><input type="checkbox" id="frCase"> 대소문자 구분</label>
      <label class="hint"><input type="checkbox" id="frWord"> 태그 통째로만 (콤마 경계)</label>
      <span class="n" id="frStat" style="margin-left:auto;"></span></div>
    <div id="frPrev" class="hint" style="max-height:200px;overflow:auto;font-family:var(--mono);"></div>
    <div class="bar"><button class="primary" id="frGo">바꾸기</button></div>`;
  $('modalBg').style.display = 'flex';
  const targets = () => {
    const list = [
      ['프롬프트', () => $('basePrompt').value, v => { $('basePrompt').value = v; STATE.base_prompt = v; }],
      ['네거티브', () => $('negPrompt').value, v => { $('negPrompt').value = v; STATE.negative_prompt = v; }],
    ];
    ['baseFixed','baseVar','baseDetail'].forEach((id, i) => {
      if($(id)) list.push([['고정','가변','디테일'][i], () => $(id).value,
        v => { $(id).value = v; STATE[['base_fixed','base_var','base_detail'][i]] = v; }]);
    });
    (STATE.char_slots || []).forEach((s, i) => {
      ['prompt','outfit','negative'].forEach(k => {
        list.push([`인물${i+1}·${{prompt:'외형',outfit:'의상',negative:'네거'}[k]}`,
          () => STATE.char_slots[i][k] || '', v => { STATE.char_slots[i][k] = v; }]);
      });
    });
    return list;
  };
  const build = () => {
    const find = $('frFind').value;
    if(!find){ $('frStat').textContent = ''; $('frPrev').innerHTML = ''; return []; }
    const flags = $('frCase').checked ? 'g' : 'gi';
    const esc2 = find.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp($('frWord').checked ? `(^|,)\\s*${esc2}\\s*(?=,|$)` : esc2, flags);
    const hits = [];
    targets().forEach(([name, get, set]) => {
      const cur = get();
      if(cur && re.test(cur)){
        re.lastIndex = 0;
        const n = (cur.match(re) || []).length;
        hits.push({name, get, set, n, re});
      }
      re.lastIndex = 0;
    });
    const total = hits.reduce((a, h) => a + h.n, 0);
    $('frStat').textContent = total ? `${hits.length}칸 · ${total}군데` : '없음';
    $('frPrev').innerHTML = hits.map(h => `<div>· ${esc(h.name)} — ${h.n}군데</div>`).join('');
    return hits;
  };
  ['frFind','frRepl','frCase','frWord'].forEach(id => $(id).addEventListener('input', build));
  ['frCase','frWord'].forEach(id => $(id).addEventListener('change', build));
  $('frGo').addEventListener('click', () => {
    const hits = build();
    if(!hits.length){ $('frStat').textContent = '바꿀 것이 없습니다.'; return; }
    const repl = $('frRepl').value;
    let n = 0;
    hits.forEach(h => {
      const cur = h.get();
      h.re.lastIndex = 0;
      let out = $('frWord').checked
        ? cur.replace(h.re, (m, p1) => (repl ? `${p1 || ''}${p1 ? ' ' : ''}${repl}` : (p1 || '')))
        : cur.replace(h.re, repl);
      /* 통째로 삭제할 때 `a,, b`나 선두 콤마를 남기지 않는다. */
      if($('frWord').checked) out = out.split(',').map(x => x.trim()).filter(Boolean).join(', ');
      h.set(out); n += h.n;
    });
    if(hits.some(h => ['프롬프트','네거티브','고정','가변','디테일'].includes(h.name))){
      clearActiveStyle();
    }
    if(window.renderSlots) renderSlots();
    tokens(); save();
    $('frStat').textContent = `${n}군데 바꿨습니다 ✓`;
    build();
  });
}

/* 작가 평가 배지 — 별점·즐겨찾기·차단을 한눈에 (rater 의 ratings 를 우리 식으로) */
function rateBadge(r){
  r = r || {};
  if(r.block) return '⛔ 차단됨';
  const s = r.score ? '★'.repeat(Math.round(r.score)) + `${r.score}` : '☆ 평가';
  return (r.fav ? '💛 ' : '') + s;
}
/* 작가 평가 모달 — 조합 안의 작가마다 별점·즐겨찾기·차단·메모 */
async function openRate(artists){
  const cur = await (await fetch('/api/rate', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({list:true})})).json();
  const R = (cur.ok && cur.ratings) || {};
  const rows = artists.map(a => {
    const k = String(a).toLowerCase(), v = R[k] || {};
    return `<div class="row" data-art="${escA(k)}" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
      <b style="min-width:150px;font-family:var(--mono);font-size:var(--fs-xs);">${esc(a)}</b>
      <span>${[0,1,2,3,4,5].map(n => `<button data-star="${n}" style="padding:2px 5px;${(v.score||0)===n?'background:var(--accent);color:#fff;':''}">${n===0?'—':'★'+n}</button>`).join('')}</span>
      <label style="display:flex;gap:3px;align-items:center;"><input type="checkbox" data-fav ${v.fav?'checked':''}>즐겨찾기</label>
      <label style="display:flex;gap:3px;align-items:center;"><input type="checkbox" data-block ${v.block?'checked':''}>차단</label>
      <input type="text" data-memo placeholder="메모" value="${escA(v.memo||'')}" style="flex:1;min-width:120px;">
    </div>`;
  }).join('');
  $('modalTitle').textContent = '⭐ 작가 평가';
  $('modalBody').innerHTML = `<p class="hint">별점·즐겨찾기는 그림체 목록의 필터로 쓰이고, 차단한 작가가
    프롬프트에 있으면 생성 전에 알려 줍니다. 저장은 즉시 됩니다 (수집/작가평가.json).</p>${rows}`;
  $('modalBg').style.display = 'flex';
  const send = async (el, body) => {
    const art = el.closest('[data-art]').dataset.art;
    await fetch('/api/rate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Object.assign({artist: art}, body))});
  };
  document.querySelectorAll('#modalBody [data-star]').forEach(b => b.addEventListener('click', async () => {
    await send(b, {score: Number(b.dataset.star)});
    b.parentElement.querySelectorAll('[data-star]').forEach(x => x.style.background = '');
    b.style.background = 'var(--accent)'; b.style.color = '#fff';
  }));
  document.querySelectorAll('#modalBody [data-fav]').forEach(c2 => c2.addEventListener('change', () => send(c2, {fav: c2.checked})));
  document.querySelectorAll('#modalBody [data-block]').forEach(c2 => c2.addEventListener('change', () => send(c2, {block: c2.checked})));
  document.querySelectorAll('#modalBody [data-memo]').forEach(t => t.addEventListener('change', () => send(t, {memo: t.value})));
}

function styleCard(c){
  const p = c.params || {};
  const px = CARD_PX[($('comboCard')||{}).value || 'medium'];
  const bits = [];
  if(p.steps) bits.push(`스텝 ${p.steps}`);
  if(p.scale != null) bits.push(`CFG ${p.scale}`);
  if(p.cfg_rescale != null) bits.push(`리스케일 ${p.cfg_rescale}`);
  if(p.sampler) bits.push(String(p.sampler).replace('k_',''));
  if(p.noise_schedule) bits.push(p.noise_schedule);
  if(p.width && p.height) bits.push(`${p.width}×${p.height}`);
  if(p.variety_plus) bits.push('Variety+');
  if(p.seed) bits.push(`시드 ${p.seed}`);
  const meta = [];
  if(c.recommend != null) meta.push(`추천 ${c.recommend}`);
  if(c.views != null) meta.push(`조회 ${c.views}`);
  if(c.posted_at) meta.push(c.posted_at);
  const el = document.createElement('div');
  el.className = 'row combo-card';
  // 전체 레코드를 data-* 문자열로 버튼마다 복제하지 않는다.
  // 긴 프롬프트·메타데이터가 있는 50개 카드에서 HTML이 수백 KB로 불어나고,
  // 파싱·속성 디코딩·JSON 재파싱이 메인 스레드를 막았다.
  el._comboRecord = c;
  el.innerHTML = `<div class="tag">${esc(c.source||'도랑')}${c.tab ? ' · '+esc(c.tab) : ''} · 작가 ${c.count}명${c.title ? ' · '+esc(c.title.slice(0,34)) : ''}${meta.length ? ' · '+esc(meta.join(' · ')) : ''}</div>
    <div style="display:flex;gap:9px;">
      ${(c.images && c.images[0]) ? `<img src="/img?u=${encodeURIComponent(c.images[0])}" loading="lazy" decoding="async" fetchpriority="low" alt="" onerror="this.style.display='none'" style="width:${px}px;height:${px}px;object-fit:cover;border-radius:var(--radius);border:1px solid var(--line);flex:none;background:#0004;">` : ''}
      <div style="flex:1;min-width:0;">
        <div style="font-family:var(--mono);font-size:var(--fs-xs);line-height:1.5;max-height:66px;overflow:auto;">${esc(c.combo || '(작가 태그 없음)')}</div>
        ${bits.length ? `<div class="hint" style="margin-top:5px;">⚙ ${esc(bits.join(' · '))}</div>` : ''}
        <div class="bar" style="margin:6px 0 0;flex-wrap:wrap;">
          ${window._comboTarget ? `<button data-cuse
            title="빌더의 작가 조합 칸에 이 값을 넣습니다">이 조합 쓰기</button>` : ''}
          <button class="primary" data-cfull>그림체 통째로 적용</button>
          <button data-csave>내 프리셋으로 저장</button>
          <button data-crate
            title="이 조합의 작가들에게 별점·즐겨찾기·차단을 매깁니다">${rateBadge(c._rate)}</button>
          ${c.url ? `<a href="${escA(c.url)}" target="_blank" style="font-size:var(--fs-xs);color:var(--muted);">원본 ↗</a>` : ''}
        </div>
      </div>
    </div>`;
  return el;
}

/* 상태 메시지 — 모달이 열려 있으면 모달에, 아니면 첫 화면 안내에 */
function flash(msg, extraBtn){
  const inModal = $('modalBg').style.display === 'flex';
  const el = inModal ? $('modalFlash') : $('welcomeMsg');
  if(!el) return;
  el.textContent = msg;
  if(extraBtn) el.appendChild(extraBtn);
}

/* ★ 그림체 적용 — 언제나 통째로.
   그림체의 최소 단위는 `베이스 + 네거티브 + NAI 생성 설정 전체` 한 덩어리다.
   쪼개서 넣으면 베이스는 이 그림 것인데 설정값은 남의 것인 잡종이 되어
   **원래 그림이 재현되지 않는다.** 그래서 '무엇을 넣을지 고르는' 인자를 없앴다 —
   경고로 막는 대신 **애초에 부분 적용이 불가능한 모양**으로 둔다. */
function applyStyle(c){
  const p = c.params || {};
  if(Object.prototype.hasOwnProperty.call(c, 'base')){
    STATE.base_prompt = c.base || ''; $('basePrompt').value = STATE.base_prompt;
  }
  /* negative_full 이 있으면 프리셋을 떼어낸 결과라 빈 문자열도 뜻이 있다 (그대로 비운다) */
  const hasNegative = Object.prototype.hasOwnProperty.call(c, 'negative')
    || c.negative_full != null;
  if(hasNegative){
    const nv = c.negative || '';
    STATE.negative_prompt = nv; $('negPrompt').value = nv;
  }
  applyStyleSettings(p);
  STATE.style_name = c.title || c.name || c.id || '가져온 그림체';
  paintActiveStyle(); tokens(); save();
  const bits = [];
  if(Object.prototype.hasOwnProperty.call(c, 'base')) bits.push('베이스');
  if(hasNegative) bits.push('네거티브');
  if(Object.keys(p).length) bits.push('설정값');
  refreshWelcome();
  let msg = bits.join(' + ') + ' 적용됨 ✓';
  /* NAI 는 UC 프리셋·퀄리티 태그를 메타에 안 남긴다 — 문구로 되짚은 것이라 밝혀 둔다 */
  if(p.uc_preset_guessed || p.quality_toggle_guessed){
    const g = [];
    if(p.uc_preset_guessed) g.push('UC 프리셋');
    if(p.quality_toggle_guessed) g.push('퀄리티 태그');
    msg += ` (${g.join('·')}은 문구로 되짚음)`;
  }
  if(p.seed){
    const el = document.createElement('button');
    el.textContent = `시드 ${p.seed} 고정하기`;
    el.style.marginLeft = '8px';
    el.addEventListener('click', () => {
      STATE.nai_seed = Number(p.seed) || 0;
      if($('pNaiSeed')) $('pNaiSeed').value = STATE.nai_seed;
      save();
      flash(`NAI 시드 ${p.seed} 고정 ✓ (원본과 같은 그림이 나옵니다)`);
    });
    flash(msg + ` — 원본 시드 ${p.seed}`, el);
    return;
  }
  flash(msg);
}

/* ── 그림체 정리 ───────────────────────────────────────────────────
   자료를 몇천 건 넣고 나면 **지울 수 있어야** 정리가 된다.
   지운 것은 지운그림체.json 으로 가므로 되살릴 수 있다. */
const PICKED = new Set();

function tidyOn(){ return $('comboTidy') && $('comboTidy').checked; }

function paintPicks(){
  const host = $('comboList'); if(!host) return;
  host.querySelectorAll('[data-pick]').forEach(b => {
    const on = PICKED.has(b.dataset.pick);
    b.textContent = on ? '☑' : '☐';
    b.closest('.row,.card,div').style.outline = on ? '2px solid var(--accent)' : '';
  });
  if($('comboPickN')) $('comboPickN').textContent = PICKED.size ? PICKED.size + '개 고름' : '';
}

/* 카드마다 고르기 단추를 붙인다. 카드 마크업은 건드리지 않는다 —
   정리를 끌 때 원래 모습으로 정확히 돌아가야 하기 때문이다. */
function addPickBoxes(){
  const host = $('comboList'); if(!host) return;
  host.querySelectorAll('[data-cfull]').forEach(b => {
    const box = b.closest('.row') || b.parentElement;
    if(!box || box.querySelector('[data-pick]')) return;
    const id = String((box._comboRecord || {}).id || '');
    if(!id) return;
    const t = document.createElement('button');
    t.dataset.pick = id; t.className = 'mini'; t.title = '고르기';
    t.style.cssText = 'margin-right:6px;';
    t.addEventListener('click', e => {
      e.stopPropagation();
      PICKED.has(id) ? PICKED.delete(id) : PICKED.add(id);
      paintPicks();
    });
    box.insertBefore(t, box.firstChild);
  });
  paintPicks();
}

function clearPickBoxes(){
  const host = $('comboList'); if(!host) return;
  host.querySelectorAll('[data-pick]').forEach(b => {
    const box = b.closest('.row,.card,div'); if(box) box.style.outline = '';
    b.remove();
  });
}

async function tidyDupes(){
  $('comboTidyMsg').textContent = '겹친 것 찾는 중...';
  const r = await (await fetch('/api/style_dupes')).json();
  if(!r.ok){ $('comboTidyMsg').textContent = r.error || '실패'; return; }
  if(!r['묶음']){ $('comboTidyMsg').textContent = '겹친 것이 없습니다.'; return; }
  /* 각 묶음의 **첫째를 남기고 나머지를 고른다** — 첫째는 설정값이 있고
     정보가 많은 것으로 서버가 정렬해 뒀다. 지우기 전에 눈으로 볼 수 있다. */
  PICKED.clear();
  r['목록'].forEach(g => g['항목'].slice(1).forEach(it => PICKED.add(String(it.id))));
  paintPicks();
  $('comboTidyMsg').innerHTML =
    `같은 작가 조합이 <b>${r['묶음']}종 ${r['겹친항목']}건</b> (전체 ${r['전체']}건). ` +
    `묶음마다 <b>가장 정보가 많은 하나를 남기고</b> ${PICKED.size}건을 골라 뒀습니다. ` +
    `목록에서 확인한 뒤 '고른 것 지우기' 를 누르세요. (지워도 되살릴 수 있습니다)`;
}

function bindTidy(){
  if(!$('comboTidy')) return;
  $('comboTidy').addEventListener('change', () => {
    $('comboTidyBar').classList.toggle('hidden', !tidyOn());
    if(tidyOn()) addPickBoxes();
    else { PICKED.clear(); clearPickBoxes(); $('comboTidyMsg').textContent = ''; }
  });
  $('comboAll').addEventListener('click', () => {
    $('comboList').querySelectorAll('[data-pick]').forEach(b => PICKED.add(b.dataset.pick));
    paintPicks();
  });
  $('comboNone').addEventListener('click', () => { PICKED.clear(); paintPicks(); });
  $('comboDupes').addEventListener('click', tidyDupes);
  $('comboDel').addEventListener('click', async () => {
    if(!PICKED.size){ $('comboTidyMsg').textContent = '고른 것이 없습니다.'; return; }
    if(!confirm(PICKED.size + '개를 지웁니다. (되살릴 수 있습니다)')) return;
    const r = await (await fetch('/api/style_del', {method:'POST',
      body: JSON.stringify({ids:[...PICKED]})})).json();
    $('comboTidyMsg').textContent = r.error ? r.error
      : `${r['지움']}건 지움 · 남은 그림체 ${r['남음']}건 · 되살릴 수 있는 것 ${r['되살릴수있음']}건`;
    PICKED.clear(); await loadCombos(false); if(tidyOn()) addPickBoxes();
  });
    $('comboUndo').addEventListener('click', async () => {
      const r = await (await fetch('/api/style_restore', {method:'POST', body:'{}'})).json();
      $('comboTidyMsg').textContent = r.error ? r.error
      : `${r['되살림']}건 되살림`
        + (r['충돌'] ? ` · 같은 id ${r['충돌']}건은 덮지 않고 휴지통에 보존` : '')
        + ` · 휴지통에 ${r['남은휴지통']}건 남음`;
      await loadCombos(false); if(tidyOn()) addPickBoxes();
    });
}

async function loadCombos(append){
  const f = cq();
  if(!append) comboOffset = 0;
  const url = `/api/combos?q=${encodeURIComponent(f.q)}&limit=${f.size}&offset=${comboOffset}`
    + `&tab=${encodeURIComponent(f.tab)}&source=${encodeURIComponent(f.source)}`
    + `&sort=${encodeURIComponent(f.sort)}&seeded=${f.seeded}`
    + `&rating=${encodeURIComponent(f.rating || '')}`;
  const r = await (await fetch(url)).json();
  if(!r.ok) return;
  $('comboStat').textContent = `${r.matched} / ${r.total}개 (설정값 ${r.seeded})`;
  const sel = $('comboSrc');
  if(sel && sel.options.length <= 1 && r.sources){
    Object.entries(r.sources).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => {
      const o = document.createElement('option'); o.value = k; o.textContent = `${k} (${v})`; sel.appendChild(o); });
  }
  const host = $('comboList');
  if(!append) host.innerHTML = '';
  // DocumentFragment로 한 번만 레이아웃한다. 50~200장을 한 장씩 붙이면
  // 모달 높이 계산과 스타일 계산이 카드 수만큼 반복된다.
  const fragment = document.createDocumentFragment();
  const added = r.items.map(c => {
    const card = styleCard(c);
    fragment.appendChild(card);
    return card;
  });
  host.appendChild(fragment);
  /* '이 조합 쓰기' 는 **빌더에서 열었을 때만** 나온다.
     빌더의 작가 조합 칸에 값을 고르는 일이지 '그림체를 적용' 하는 것이 아니다.
     그림체를 왼쪽 화면에 넣는 길은 '통째로 적용' **하나뿐**이다 — 베이스만·설정만
     넣는 길을 두면 원래 그림이 재현되지 않는 잡종이 만들어진다. */
  added.flatMap(card => [...card.querySelectorAll('[data-cuse]')]).forEach(btn => {
    btn.addEventListener('click', () => {
      const val = (btn.closest('.row')._comboRecord || {}).combo || '';
      returnToBuilder(val);
    });
  });
  added.flatMap(card => [...card.querySelectorAll('[data-cfull]')]).forEach(b =>
    b.addEventListener('click', () => applyStyle(b.closest('.row')._comboRecord)));
  if(tidyOn()) addPickBoxes();      /* 더 보기로 이어 붙인 카드에도 붙는다 */
  added.flatMap(card => [...card.querySelectorAll('[data-crate]')]).forEach(b => b.addEventListener('click', () => {
    const arts = (b.closest('.row')._comboRecord || {}).artists || [];
    if(!arts.length){ flash('이 조합에는 작가 태그가 없습니다.'); return; }
    openRate(arts);
  }));
  added.flatMap(card => [...card.querySelectorAll('[data-csave]')]).forEach(b => b.addEventListener('click', async () => {
    const c = b.closest('.row')._comboRecord;
    const name = prompt('프리셋 이름:', (c.title || '그림체').slice(0, 30));
    if(!name) return;
    const p = c.params || {};
    const res = await (await fetch('/api/style_save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, prompt: c.base || c.combo, negative: c.negative || '',
        settings: {cfg_scale: p.scale, cfg_rescale: p.cfg_rescale, steps: p.steps,
          sampler: p.sampler, scheduler: p.noise_schedule, variety: !!p.variety_plus,
          width: p.width, height: p.height,
          uc_preset: (p.uc_preset != null ? p.uc_preset : STATE.uc_preset),
          quality_toggle: (p.quality_toggle != null ? p.quality_toggle : STATE.quality_toggle)}})})).json();
    if(res.ok){ STYLES = res.styles; renderPresets(); renderLibrary();
      $('modalFlash').textContent = `프리셋 "${name}" 저장됨 ✓`; }
    else $('modalFlash').textContent = res.error || '저장 실패';
  }));
  comboOffset += r.items.length;
  $('comboMore').style.display = (comboOffset < r.matched) ? '' : 'none';
  $('comboMore').textContent = `더 보기 ▾ (${comboOffset} / ${r.matched})`;
}

/* ── 이미지 → 그림체 추출 (novelai.net/inspect 를 로컬에서) ──
   드롭존은 세 곳: 첫 화면 안내 · 그림체 모달 · 창 아무 데나 */
function bindDropZone(zone, file){
  if(!zone) return;
  if(file){
    zone.addEventListener('click', () => file.click());
    file.addEventListener('change', () => { inspectImages([...file.files]); file.value = ''; });
  }
  ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = ''; }));
  zone.addEventListener('drop', e => {
    e.stopPropagation();
    inspectImages([...(e.dataTransfer.files || [])]);
  });
}
function setupInspectDrop(){ bindDropZone($('comboDrop'), $('comboFile')); }

async function inspectImages(files){
  const imgs = files.filter(f => /\.(png|webp)$/i.test(f.name));
  if(!imgs.length){ flash('PNG 또는 WebP 파일을 넣어주세요.'); return 0; }
  let ok = 0, fail = 0, last = null;
  for(const f of imgs){
    flash(`읽는 중... ${f.name}`);
    try{
      const r = await (await fetch('/api/inspect', {method:'POST',
        headers:{'X-Filename': encodeURIComponent(f.name), 'X-Save':'1'},
        body: await f.arrayBuffer()})).json();
      if(r.ok){ ok++; last = r.style; } else fail++;
    }catch(e){ fail++; }
  }
  flash(`${ok}개 추출 완료${fail ? `, ${fail}개는 생성 정보가 없었습니다` : ''}`);
  if(ok){
    if($('comboList')){ $('comboQ').value = ''; $('comboSrc').value = '내 이미지'; await loadCombos(false); }
    /* 한 장이면 **읽은 내용을 보여 준 뒤** 넣고, 여러 장이면 마지막 것을 바로 넣는다.
       ⚠ 예전 주석은 "무엇을 가져올지 고르게 한다(SDStudio 의 항목별 적용)" 였는데
         **지금은 고르는 길이 없다.** 그림체는 베이스+네거티브+생성 설정이 한 덩어리라
         쪼개 넣으면 원래 그림이 재현되지 않아서다(`29cf044` 에서 없앴다).
         `openApplyPicker` 는 **읽기 전용 요약 + `통째로 적용` 단추 하나**뿐이다
         (실측: 항목별 체크박스 0개 · 단추 1개). 낡은 설명이 남아 있어 바로잡는다. */
    if(last) (imgs.length === 1 ? openApplyPicker(last) : applyStyle(last));
  }
  return ok;
}

/* 창 아무 데나 그림을 떨어뜨려도 추출 */
(function(){
  const ov = document.createElement('div');
  ov.id = 'dropOverlay';
  ov.textContent = '🖼️ 놓으면 이 그림의 프롬프트·설정값을 가져옵니다';
  document.body.appendChild(ov);
  let depth = 0;
  const hasFiles = e => [...((e.dataTransfer || {}).types || [])].includes('Files');
  document.addEventListener('dragenter', e => {
    if(!hasFiles(e)) return;
    depth++; ov.classList.add('on');
  });
  document.addEventListener('dragover', e => { if(hasFiles(e)) e.preventDefault(); });
  document.addEventListener('dragleave', () => { if(--depth <= 0){ depth = 0; ov.classList.remove('on'); } });
  document.addEventListener('drop', e => {
    if(!hasFiles(e)) return;
    e.preventDefault(); depth = 0; ov.classList.remove('on');
    inspectImages([...(e.dataTransfer.files || [])]);
  });
})();

/* ── 첫 실행 안내 ── */
function refreshWelcome(){
  const w = $('welcome');
  if(!w) return;
  const empty = !(STATE.base_prompt || '').trim();
  w.classList.toggle('hidden', !empty || (STATE.ui || {}).welcome_off === true);
}
function bindWelcome(){
  if(window._welcomeBound) return;
  window._welcomeBound = true;
  bindDropZone($('welcomeDrop'), $('welcomeFile'));
  $('welcomeLib').addEventListener('click', () => {
    const b = document.querySelector('[data-mode="library"]');
    if(b) b.click();
    openCombos(null);
  });
  $('welcomeSkip').addEventListener('click', () => {
    STATE.ui = STATE.ui || {}; STATE.ui.welcome_off = true;
    save(); refreshWelcome(); $('basePrompt').focus();
  });
  const loadWelcomeCount = () => fetch('/api/combos?limit=0').then(r => r.json()).then(r => {
    if(r.ok && $('welcomeCount')) $('welcomeCount').textContent = r.total.toLocaleString();
  }).catch(() => {});
  /* requestIdleCallback은 첫 페인트 직후 곧바로 실행될 수 있어 사용자가 누른
     조합 요청보다 먼저 같은 파일을 잡았다. 숫자는 기능이 아니므로 2.5초 뒤로
     미루고, 사용자가 조합 창을 먼저 열면 취소한다. */
  WELCOME_COUNT_TIMER = setTimeout(() => {
    WELCOME_COUNT_TIMER = null;
    loadWelcomeCount();
  }, 2500);
}


/* ── 단부루 검색 ──────────────────────────────────────────────────────
   태그로 실제 그림을 찾아 ① 태그 가져오기 ② 바이브·캐릭레퍼 등록
   ③ NAI 그림이면 그림체까지 추출. 썸네일은 /img 프록시로 받는다. */
let booruPage = 1;
const BCARD = {small: '110px', medium: '150px', large: '220px'};
async function booruSearch(next){
  const q = ($('booruQ').value || '').trim();
  const site = $('booruSite').value, limit = $('booruLimit').value;
  booruPage = next ? booruPage + 1 : 1;
  $('booruStat').textContent = '찾는 중...';
  const r = await (await fetch(`/api/booru?site=${site}&q=${encodeURIComponent(q)}`
    + `&page=${booruPage}&limit=${limit}`)).json();
  if(!r.ok){ $('booruStat').textContent = r.error || '검색 실패'; return; }
  $('booruStat').textContent = `${r.name} · ${r.count}장 (${booruPage}쪽)`
    + (r.note ? ' — ' + r.note : '');
  window._booruUrl = r.search_url;
  const g = $('booruGrid');
  if(!next) g.innerHTML = '';
  g.style.setProperty('--bcard', BCARD[$('booruCard').value] || '150px');
  r.items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'row'; el.style.margin = '0'; el.style.padding = '0'; el.style.overflow = 'hidden';
    const who = [it.artist, it.character, it.copyright].filter(Boolean).join(' · ').slice(0, 60);
    /* 부루 CDN 은 Cloudflare 챌린지 때문에 서버(프록시)로는 못 받는다.
       브라우저는 직접 받을 수 있으니 원본 주소를 그대로 쓰고, 실패하면 프록시로. */
    el.innerHTML = `<img src="${escA(it.thumb)}" loading="lazy" alt="" referrerpolicy="no-referrer"
        onerror="if(!this.dataset.retry){this.dataset.retry=1;
                 this.src='/img?u='+encodeURIComponent(this.dataset.src);}
                 else this.style.display='none';"
        data-src="${escA(it.thumb)}"
        style="width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#0004;">
      <div style="padding:6px 8px;">
        <div class="tag" style="margin-bottom:4px;">${it.score != null ? '★' + it.score : ''}
          ${it.rating ? ' · ' + esc(String(it.rating)) : ''}${who ? ' · ' + esc(who) : ''}</div>
        <div class="bar" style="flex-wrap:wrap;gap:4px;">
          <button data-btags="${escA(it.tags)}">태그</button>
          <button data-bref="${escA(it.full || it.thumb)}|vibe">바이브</button>
          <button data-bref="${escA(it.full || it.thumb)}|cref">캐릭레퍼</button>
          <button data-bstyle="${escA(it.full || it.thumb)}">그림체</button>
          <a href="${escA(it.url)}" target="_blank" style="font-size:var(--fs-xs);color:var(--muted);">원본↗</a>
        </div></div>`;
    g.appendChild(el);
  });
  g.querySelectorAll('[data-btags]').forEach(b => b.addEventListener('click', () => {
    const tags = b.dataset.btags.split(/\s+/).filter(Boolean).map(t => t.replace(/_/g, ' ')).join(', ');
    const cur = $('basePrompt').value.trim().replace(/,$/, '');
    STATE.base_prompt = cur ? cur + ', ' + tags : tags;
    $('basePrompt').value = STATE.base_prompt; clearActiveStyle(); tokens(); save();
    $('booruStat').textContent = '태그를 베이스에 붙였습니다 ✓';
  }));
  g.querySelectorAll('[data-bref]').forEach(b => b.addEventListener('click', async () => {
    const [url, kind] = b.dataset.bref.split('|');
    $('booruStat').textContent = '받아서 등록 중...';
    try{
      const blob = await (await fetch('/img?u=' + encodeURIComponent(url))).blob();
      const f = new File([blob], `booru_${Date.now()}.png`, {type: 'image/png'});
      await addRefs([f], kind);
      $('booruStat').textContent = (kind === 'vibe' ? '바이브' : '캐릭레퍼') + ' 등록 ✓';
    }catch(e){ $('booruStat').textContent = String(e); }
  }));
  g.querySelectorAll('[data-bstyle]').forEach(b => b.addEventListener('click', async () => {
    $('booruStat').textContent = '그림체 추출 중...';
    try{
      const blob = await (await fetch('/img?u=' + encodeURIComponent(b.dataset.bstyle))).blob();
      const f = new File([blob], `booru_${Date.now()}.png`, {type: 'image/png'});
      const n = await inspectImages([f]);
      if(!n) $('booruStat').textContent = 'NAI 로 만든 그림이 아니라 생성 정보가 없습니다.';
    }catch(e){ $('booruStat').textContent = String(e); }
  }));
  $('booruMore').style.display = r.count >= Number(limit) ? '' : 'none';
}
function bindBooru(){
  if(!$('booruGo') || $('booruGo')._bound) return;
  $('booruGo')._bound = true;
  $('booruGo').addEventListener('click', () => booruSearch(false));
  $('booruQ').addEventListener('keydown', e => { if(e.key === 'Enter') booruSearch(false); });
  ['booruSite','booruLimit'].forEach(id => $(id).addEventListener('change', () => booruSearch(false)));
  $('booruCard').addEventListener('change', () =>
    $('booruGrid').style.setProperty('--bcard', BCARD[$('booruCard').value] || '150px'));
  $('booruMore').addEventListener('click', () => booruSearch(true));
  /* 검색 전에는 고른 사이트의 첫 화면으로 (예전엔 늘 단부루로 갔다) */
  const HOMES = {danbooru:'https://danbooru.donmai.us/posts',
                 gelbooru:'https://gelbooru.com/index.php?page=post&s=list',
                 e621:'https://e621.net/posts'};
  $('booruOpen').addEventListener('click', () =>
    window.open(window._booruUrl || HOMES[$('booruSite').value] || HOMES.danbooru, '_blank'));
}

/* ── 레시피 라이브러리 ── */
const AXIS_KO = {artist:'작가', style:'화풍', camera:'카메라', background:'배경', effect:'효과',
  hair:'머리', outfit:'의상', body:'신체', body_state:'신체상태', expression:'표정',
  pose:'포즈', action:'행동', sexual_action:'성행위', character:'캐릭터', unknown:'기타'};
let recT = null, recOffset = 0;
let RECIPES_READY = false, RECIPES_LOADING = false, RECIPES_OBSERVER = null;

function bindRecipes(){
  const q = $('recQ'), grid = $('recGrid');
  if(!q || !grid || q._bound) return;
  q._bound = true;
  const request = () => {
    clearTimeout(recT);
    recT = setTimeout(() => RECIPES_READY ? loadRecipes(false) : ensureRecipes(), 300);
  };
  q.addEventListener('input', request);
  $('recAxis').addEventListener('change', () =>
    RECIPES_READY ? loadRecipes(false) : ensureRecipes());
  $('recMore').addEventListener('click', () => loadRecipes(true));
  const target = grid.closest('.card') || grid;
  if('IntersectionObserver' in window){
    RECIPES_OBSERVER = new IntersectionObserver(entries => {
      if(entries.some(entry => entry.isIntersecting)){
        RECIPES_OBSERVER.disconnect();
        RECIPES_OBSERVER = null;
        ensureRecipes();
      }
    }, {rootMargin:'240px 0px'});
    RECIPES_OBSERVER.observe(target);
  }else{
    /* 구형 브라우저에서도 첫 화면과 겹치지 않게 충분히 뒤로 미룬다. */
    setTimeout(ensureRecipes, 2500);
  }
}

async function ensureRecipes(){
  if(RECIPES_READY || RECIPES_LOADING) return;
  RECIPES_LOADING = true;
  if($('recStat')) $('recStat').textContent = '레시피를 불러오는 중...';
  try{
    await loadRecipes(false);
    RECIPES_READY = true;
  }catch(e){
    if($('recStat')) $('recStat').textContent = '레시피를 불러오지 못했습니다. 검색하면 다시 시도합니다.';
  }finally{
    RECIPES_LOADING = false;
  }
}

async function loadRecipes(append){
  const q = ($('recQ') || {}).value || '';
  const ax = ($('recAxis') || {}).value || '';
  if(!append) recOffset = 0;
  const r = await (await fetch(`/api/recipes?q=${encodeURIComponent(q)}&axis=${encodeURIComponent(ax)}&limit=60&offset=${recOffset}`)).json();
  if(!r.ok) throw new Error(r.error || '레시피 불러오기 실패');
  $('recStat').textContent = `${r.matched.toLocaleString()} / ${r.total.toLocaleString()}건`;
  const sel = $('recAxis');
  if(sel.options.length <= 1){
    Object.entries(r.axes).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => {
      const o = document.createElement('option');
      o.value = k; o.textContent = `${AXIS_KO[k]||k} (${v})`;
      sel.appendChild(o);
    });
  }
  const g = $('recGrid');
  if(!append) g.innerHTML = '';
  r.items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'row'; el.style.cursor = 'pointer'; el.style.margin = '0'; el.style.padding = '0';
    el.style.overflow = 'hidden';
    const img = (it.images && it.images[0]) ? `<img src="/img?u=${encodeURIComponent(it.images[0])}" loading="lazy"
      onerror="this.style.display='none'" alt=""
      style="width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#0004;">` : '';
    el.innerHTML = `${img}<div style="padding:8px 10px;">
      <div class="tag" style="margin-bottom:4px;">${esc(AXIS_KO[it.axis]||it.axis)}${it.concept_ko ? ' · ' + esc(it.concept_ko) : ''}</div>
      <b style="font-size:var(--fs-2xs);line-height:1.35;display:block;">${esc((it.title||'(제목 없음)').slice(0,48))}</b></div>`;
    el.addEventListener('click', () => openRecipe(it));
    g.appendChild(el);
  });
  recOffset += r.items.length;
  $('recMore').style.display = (recOffset < r.matched) ? '' : 'none';
  $('recMore').textContent = `더 보기 ▾ (${recOffset.toLocaleString()} / ${r.matched.toLocaleString()})`;
}
function openRecipe(it){
  window._mm = 'recipe';
  $('modalTitle').textContent = `${AXIS_KO[it.axis]||it.axis} · ${it.title || '레시피'}`;
  const b = $('modalBody');
  b.innerHTML = `
    ${(it.images && it.images.length) ? `<div class="grid2" style="margin-bottom:10px;">
      ${it.images.map(u => `<img src="/img?u=${encodeURIComponent(u)}" style="width:100%;border-radius:var(--radius);border:1px solid var(--line);">`).join('')}</div>` : ''}
    <div class="row"><div class="tag">태그 ${it.tags.length}개</div>
      <div>${it.tags.map(x => `<span class="chip" data-rt="${escA(x)}">${esc(x)}</span>`).join('')}</div></div>
    ${it.positive ? `<div class="field"><label>포지티브</label><textarea readonly style="min-height:70px;">${esc(it.positive)}</textarea></div>` : ''}
    ${it.negative ? `<div class="field"><label>네거티브</label><textarea readonly style="min-height:52px;">${esc(it.negative)}</textarea></div>` : ''}
    <div class="bar">
      <button class="primary" id="recToBase">베이스 프롬프트로</button>
      <button id="recAppend">베이스에 이어붙이기</button>
      <button id="recToChar">캐릭터 칸에 추가</button>
      ${it.negative ? '<button id="recToNeg">네거티브로</button>' : ''}
      ${it.url ? `<a href="${escA(it.url)}" target="_blank" style="font-size:var(--fs-xs);color:var(--muted);margin-left:auto;">원본 보기 ↗</a>` : ''}
    </div>`;
  const body = it.positive || it.tags.join(', ');
  $('recToBase').addEventListener('click', () => {
    STATE.base_prompt = body; $('basePrompt').value = body; clearActiveStyle();
    tokens(); save(); $('modalFlash').textContent = '베이스로 적용됨 ✓';
  });
  $('recAppend').addEventListener('click', () => {
    const cur = $('basePrompt').value.trim().replace(/,$/, '');
    const v = cur ? cur + ', ' + body : body;
    STATE.base_prompt = v; $('basePrompt').value = v; clearActiveStyle();
    tokens(); save(); $('modalFlash').textContent = '이어붙였습니다 ✓';
  });
  $('recToChar').addEventListener('click', () => {
    (STATE.char_slots = STATE.char_slots || []).push({name: it.title.slice(0,20) || '레시피', prompt: body, negative: ''});
    renderSlots(); tokens(); save(); $('modalFlash').textContent = '캐릭터 칸에 추가됨 ✓';
  });
  if($('recToNeg')) $('recToNeg').addEventListener('click', () => {
    STATE.negative_prompt = it.negative; $('negPrompt').value = it.negative;
    clearActiveStyle(); tokens(); save(); $('modalFlash').textContent = '네거티브로 적용됨 ✓';
  });
  b.querySelectorAll('[data-rt]').forEach(c => c.addEventListener('click', () => {
    const cur = $('basePrompt').value.trim().replace(/,$/, '');
    const v = cur ? cur + ', ' + c.dataset.rt : c.dataset.rt;
    STATE.base_prompt = v; $('basePrompt').value = v; clearActiveStyle(); tokens(); save();
    c.classList.add('on');
  }));
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
}

/* ── 태그 사전 검색 ── */
let tt = {};
function bindTagSearch(scope){
  scope.querySelectorAll('[data-tagq]').forEach(inp => {
    if(inp._b) return; inp._b = 1;
    const key = inp.dataset.tagq, [kind, slot] = key.split('|');
    const box = scope.querySelector(`[data-tagres="${CSS.escape(key)}"]`);
    const run = async () => {
      const q = inp.value.trim();
      const r = await (await fetch(`/api/tags?kind=${kind}&slot=${encodeURIComponent(slot)}&q=${encodeURIComponent(q)}&limit=40`)).json();
      box.innerHTML = '';
      if(!r.ok || !r.tags.length){ box.innerHTML = `<span style="font-size:var(--fs-2xs);color:var(--muted);">${q?'결과 없음':''}</span>`; return; }
      r.tags.forEach(t => {
        const c = document.createElement('span'); c.className = 'chip';
        c.innerHTML = `${esc(t.tag)} <span style="font-size:var(--fs-2xs);color:var(--muted)">${t.count>=1000?Math.round(t.count/1000)+'k':t.count}</span>`;
        c.addEventListener('click', () => {
          // 빌더 안이면 그 슬롯 칩 목록에 바로 추가하고 선택 상태로
          const field = inp.closest('[data-slot]');
          const sels = field && field.querySelector('[data-sels]');
          if(sels){
            let target = Array.from(sels.querySelectorAll('select')).find(s => !s.value) || sels.querySelector('select');
            if(!Array.from(target.options).some(o => o.value === t.tag)){
              const o = document.createElement('option');
              o.value = t.tag; o.textContent = t.tag + ' (사전)';
              target.insertBefore(o, target.options[1] || null);
            }
            target.value = t.tag;
            if(window._bldRefresh) window._bldRefresh();
            return;
          }
          const tg = scope.querySelector('#bldExtra');
          if(tg){ tg.value = (tg.value.trim() ? tg.value.trim().replace(/,$/,'') + ', ' : '') + t.tag;
            tg.dispatchEvent(new Event('input', {bubbles:true})); }
          else { navigator.clipboard && navigator.clipboard.writeText(t.tag); c.style.borderColor = 'var(--good)'; }
        });
        box.appendChild(c);
      });
    };
    inp.addEventListener('input', () => { clearTimeout(tt[key]); tt[key] = setTimeout(run, 250); });
    inp.addEventListener('focus', () => { if(!box.innerHTML) run(); });
  });
}

/* ── 빌더 ── */
/* ── 빌더 (드롭다운 + 잠금 + 랜덤) ── */
function openBuilder(kind){
  window._mm = kind;
  $('modalSave').style.display = '';
  const steps = BUILDER[kind === 'char' ? '캐릭터단계' : '베이스단계'] || [];
  const ko = BUILDER['한글'] || {};
  const isBase = kind !== 'char';
  const nSteps = steps.length;
  const hasPickedNegative = steps.some(st => st['출력'] === 'negative');
  const charCore = new Set(['인물','역할·종족','얼굴 외형','헤어','상반신 신체',
    '하반신 신체','옷 — 부위별','예술적 변형 (원작과 다르게)']);
  $('modalTitle').textContent = (isBase ? '🖼️ 베이스 빌더' : '👤 캐릭터 빌더')
    + (nSteps ? ` (${nSteps}단계)` : '');
  $('modalBody').closest('.modal').classList.add('builder-modal');
  const b = $('modalBody');
  b.innerHTML = `<div class="builder-intro">
      <div class="flow">${isBase
        ? '<b>그림체의 뼈대 → 구도·빛·화풍 → 네거티브</b> 순으로 고릅니다. 네거티브와 생성 설정은 그림체에서 분리하지 않습니다.'
        : '<b>정체 → 외모 → 머리 → 체형 → 의상 → 예술적 변형</b> 순으로 고릅니다. 상황·자세·행동은 필요할 때만 세부 단계에서 더합니다.'}</div>
      <span class="route">${isBase ? '그림체로 저장' : '캐릭터로 저장'}</span>
    </div>
    <div class="builder-toolbar">
      ${isBase ? '' : '<button id="bldCore" aria-pressed="true">모든 세부 단계 보기</button>'}
      <button id="bldOpenAll">보이는 단계 펼치기</button><button id="bldCloseAll">전부 접기</button>
      <button id="bldRnd">${isBase ? '🎲 그림체 초안' : '🎲 캐릭터 초안'}</button>
      <button id="bldClear">선택 비우기</button><span class="n" id="bldStat"></span>
    </div>
    <div class="builder-shell">
      <section class="builder-steps ${isBase ? '' : 'builder-core-only'}" id="bldSteps"></section>
      <aside class="builder-summary">
        <h4>${isBase ? '그림체 묶음' : '캐릭터 한 명'}</h4>
        <p class="summary-note">${isBase
          ? '베이스·네거티브·생성 설정을 함께 저장합니다. 설정값은 현재 생성 화면의 값을 사용합니다.'
          : '이름을 먼저 적고 외형을 고르세요. 의상·예술적 변형도 이 캐릭터 프롬프트에 함께 저장됩니다.'}</p>
        <div class="field"><label>이름</label><input type="text" id="bldName"
          placeholder="${isBase ? '예: 시네마틱 야간' : '예: 레이나'}"></div>
        <div class="builder-progress" id="bldProgress"><span class="empty">아직 고른 단계가 없습니다.</span></div>
        <div class="field"><label>직접 더할 태그</label>
          <textarea id="bldExtra" placeholder="목록에 없는 특징을 원문 그대로 입력"></textarea></div>
        <div class="field"><label>${isBase ? '베이스' : '캐릭터'} 프롬프트 미리보기</label>
          <textarea id="bldPreview" readonly></textarea></div>
        ${hasPickedNegative ? `<div class="field"><label>목록에서 고른 네거티브</label>
          <textarea id="bldNegPick" readonly></textarea></div>` : ''}
        <div class="field"><label>${isBase ? '네거티브 프롬프트' : '캐릭터 전용 네거티브 (선택)'}</label>
          <textarea id="bldNeg" placeholder="${isBase ? '직접 더할 네거티브' : '이 인물에만 적용할 네거티브'}"></textarea>
          ${isBase ? `<div class="bar" style="margin-top:5px;">
            <button id="bldPreQ">추천 퀄리티 넣기</button><button id="bldPreN">추천 네거티브 넣기</button></div>` : ''}
        </div>
        ${isBase ? '' : `<label class="apply-now"><input type="checkbox" id="bldUseNow" checked>
          <span><b>저장 후 캐릭터 칸에 바로 넣기</b><br>라이브러리에서 다시 찾는 단계를 생략합니다.</span></label>`}
      </aside>
    </div>`;
  const stepsBox = $('bldSteps');
  if(!nSteps){
    stepsBox.innerHTML = `<div class="row" style="padding:20px;text-align:center;">
      <b>빌더 후보 자료가 아직 없습니다.</b>
      <p class="hint" style="margin:7px 0 0;">기본자료팩을 자료 탭에 넣으면 후보 단계가 채워집니다.
      지금도 오른쪽의 직접 태그 입력으로 저장할 수 있습니다.</p></div>`;
  }

  /* 접힌 18단계의 후보 3천여 개를 모달을 여는 순간 전부 option으로 만들지 않는다.
     단계 헤더와 후보 수는 즉시 보이고, 실제 선택지는 그 단계를 처음 펼칠 때 채운다. */
  const hydrateSection = sec => {
    if(!sec) return;
    sec.querySelectorAll('select[data-pick]').forEach(select => {
      if(select.dataset.hydrated === '1') return;
      const fragment = document.createDocumentFragment();
      (select._bldCandidates || []).forEach(tag => {
        const option = document.createElement('option');
        option.value = tag;
        option.textContent = tag + (ko[tag] ? ' — ' + ko[tag] : '');
        fragment.appendChild(option);
      });
      select.appendChild(fragment);
      select.dataset.hydrated = '1';
    });
  };

  steps.forEach((st, si) => {
    const output = st['출력'] === 'negative' ? 'negative' : 'positive';
    const essential = !isBase && charCore.has(st['이름']);
    const sec = document.createElement('div');
    sec.className = 'sec' + (essential ? ' essential' : '');
    sec.dataset.output = output;
    sec.dataset.stepName = st['이름'];
    const rows = (st['슬롯'] || []).map((sl, li) => {
      const id = `${si}-${li}`;
      return `<div class="bld-slot" data-slot="${id}">
        <div class="bld-slot-head">
          <span class="slot-name">${esc(sl['라벨'])}</span>
          <span class="slot-count">${(sl['후보']||[]).length}개 후보</span>
          <span class="bld-slot-actions">
            <button data-lock="${id}" title="랜덤에서 제외" style="padding:3px 7px;font-size:var(--fs-xs);">🔓</button>
            <button data-more="${id}" title="같은 항목 하나 더" style="padding:3px 8px;font-size:var(--fs-xs);">＋</button>
            ${sl['조합전용'] ? `<button data-combo="${id}" style="padding:3px 8px;font-size:var(--fs-xs);color:var(--accent);">조합 고르기</button>` : ''}
            <input type="text" data-tagq="${escA(kind + '|' + st['이름'] + '·' + sl['라벨'])}"
              placeholder="🔍 후보 검색" class="bld-search">
          </span>
        </div>
        <div data-tagres="${escA(kind + '|' + st['이름'] + '·' + sl['라벨'])}" class="tagres"></div>
        <div data-sels="${id}" class="bld-selects"><select data-pick="${id}" data-output="${output}">
          <option value="">(선택 안 함)</option></select></div>
      </div>`;
    }).join('');
    sec.innerHTML = `<div class="sec-head" data-bstep="${si}">
        <span class="badge">${esc(st['번호'])}</span><span class="nm">${esc(st['이름'])}</span>
        <span class="sub">${(st['슬롯']||[]).length}항목</span>
        <span class="builder-stage-route ${output}">${output === 'negative' ? '네거티브로' : (isBase ? '베이스로' : '캐릭터로')}</span>
        <span class="cnt" data-bcnt="${si}"></span></div>
      <div class="sec-body ${si < (isBase ? 2 : 1) ? '' : 'hidden'}" data-bbody="${si}">${rows}</div>`;
    sec.querySelectorAll('select[data-pick]').forEach((select, li) => {
      select._bldCandidates = [...(((st['슬롯'] || [])[li] || {})['후보'] || [])];
    });
    stepsBox.appendChild(sec);
    if(!sec.querySelector('.sec-body').classList.contains('hidden')) hydrateSection(sec);
  });

  const composeSelected = output => {
    const parts = [];
    b.querySelectorAll(`select[data-pick][data-output="${output}"]`).forEach(s => {
      if(s.value) parts.push(s.value);
    });
    if(output === 'positive'){
      ($('bldExtra').value || '').split(',').map(x => x.trim()).filter(Boolean).forEach(x => parts.push(x));
    }
    return parts.join(', ');
  };
  const compose = () => composeSelected('positive');
  const composeNegative = () => [composeSelected('negative'), ($('bldNeg').value || '').trim()]
    .filter(Boolean).join(', ');
  window._comp = compose;
  window._compNeg = composeNegative;
  const refresh = () => {
    $('bldPreview').value = compose();
    if($('bldNegPick')) $('bldNegPick').value = composeSelected('negative');
    let pos = 0, neg = 0;
    const activeSteps = [];
    stepsBox.querySelectorAll('.sec').forEach((sec, i) => {
      const n = Array.from(sec.querySelectorAll('select[data-pick]')).filter(s => s.value).length;
      if(sec.dataset.output === 'negative') neg += n; else pos += n;
      const el = sec.querySelector(`[data-bcnt="${i}"]`);
      if(el) el.textContent = n ? `${n}개` : '';
      if(n) activeSteps.push({i, name:sec.dataset.stepName, n});
    });
    $('bldStat').textContent = `${pos}개 선택` + (neg ? ` · 네거티브 ${neg}개` : '');
    $('bldProgress').innerHTML = activeSteps.length
      ? activeSteps.map(x => `<button data-jumpstep="${x.i}">${esc(x.name)} ${x.n}</button>`).join('')
      : '<span class="empty">아직 고른 단계가 없습니다.</span>';
  };
  window._bldRefresh = refresh;

  if(window._bldClick) b.removeEventListener('click', window._bldClick);
  if(window._bldChange) b.removeEventListener('change', window._bldChange);
  if(window._bldInput) b.removeEventListener('input', window._bldInput);
  window._bldClick = e => {
    const jp = e.target.closest('[data-jumpstep]');
    if(jp){
      const head = stepsBox.querySelector(`[data-bstep="${jp.dataset.jumpstep}"]`);
      const sec = head && head.closest('.sec');
      if(sec){
        sec.querySelector('.sec-body').classList.remove('hidden');
        sec.scrollIntoView({behavior:'smooth', block:'start'});
      }
      return;
    }
    const h = e.target.closest('[data-bstep]');
    if(h){
      const body = b.querySelector(`[data-bbody="${h.dataset.bstep}"]`);
      if(body.classList.contains('hidden')) hydrateSection(h.closest('.sec'));
      body.classList.toggle('hidden');
      return;
    }
    const lk = e.target.closest('[data-lock]');
    if(lk){
      const f = b.querySelector(`[data-slot="${CSS.escape(lk.dataset.lock)}"]`);
      const on = f.dataset.locked === '1';
      f.dataset.locked = on ? '' : '1';
      lk.textContent = on ? '🔓' : '🔒';
      lk.style.color = on ? '' : 'var(--good)';
      return;
    }
    const cb = e.target.closest('[data-combo]');
    if(cb){
      const box = b.querySelector(`[data-sels="${CSS.escape(cb.dataset.combo)}"]`);
      openCombos(box.querySelector('select'));
      return;
    }
    const mr = e.target.closest('[data-more]');
    if(mr){
      const box = b.querySelector(`[data-sels="${CSS.escape(mr.dataset.more)}"]`);
      const first = box.querySelector('select');
      const cl = first.cloneNode(true);
      cl.value = '';
      box.appendChild(cl);
      return;
    }
  };
  window._bldChange = () => refresh();
  window._bldInput = () => refresh();
  b.addEventListener('click', window._bldClick);
  b.addEventListener('change', window._bldChange);
  b.addEventListener('input', window._bldInput);

  if($('bldCore')) $('bldCore').addEventListener('click', () => {
    const coreOnly = stepsBox.classList.toggle('builder-core-only');
    $('bldCore').textContent = coreOnly ? '모든 세부 단계 보기' : '핵심 단계만 보기';
    $('bldCore').setAttribute('aria-pressed', coreOnly ? 'true' : 'false');
  });
  $('bldOpenAll').addEventListener('click', () => stepsBox.querySelectorAll('.sec').forEach(sec => {
    if(sec.offsetParent !== null){
      hydrateSection(sec);
      sec.querySelector('.sec-body').classList.remove('hidden');
    }
  }));
  $('bldCloseAll').addEventListener('click', () => stepsBox.querySelectorAll('.sec-body').forEach(x => x.classList.add('hidden')));
  $('bldClear').addEventListener('click', () => {
    stepsBox.querySelectorAll('[data-slot]').forEach(f => {
      if(f.dataset.locked !== '1') f.querySelectorAll('select').forEach(s => s.value = '');
    });
    refresh();
  });
  $('bldRnd').addEventListener('click', () => {
    /* 76개 슬롯을 각각 60%로 채우던 랜덤은 캐릭터를 쉽게 만드는 대신
       서로 충돌하는 태그를 과도하게 만들었다. 핵심 단계에서 한 특징을 중심으로
       가볍게 초안을 만들고, 네거티브는 사용자가 명시적으로 고르게 둔다. */
    stepsBox.querySelectorAll('.sec').forEach(sec => {
      if(sec.dataset.output === 'negative' || (!isBase && !sec.classList.contains('essential'))) return;
      hydrateSection(sec);
      sec.querySelectorAll('[data-slot]').forEach((f, fi) => {
        if(f.dataset.locked === '1') return;
        const s = f.querySelector('select');
        if(!s || s.options.length <= 1) return;
        const chance = !isBase && sec.dataset.stepName === '인물' && fi === 0
          ? 1 : (fi === 0 ? .62 : (isBase ? .24 : .16));
        if(Math.random() < chance) s.selectedIndex = 1 + Math.floor(Math.random() * (s.options.length - 1));
        else s.value = '';
      });
    });
    refresh();
  });
  if(isBase){
    const PR = BUILDER['프리셋'] || {};
    $('bldPreQ').addEventListener('click', () => {
      $('bldExtra').value = ($('bldExtra').value.trim() ? $('bldExtra').value.trim().replace(/,$/,'') + ', ' : '') + (PR['추천 퀄리티'] || '');
      refresh();
    });
    $('bldPreN').addEventListener('click', () => { $('bldNeg').value = PR['추천 네거티브'] || ''; });
  }
  bindTagSearch(b);
  refresh();
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
  setTimeout(() => { const name = $('bldName'); if(name) name.focus(); }, 0);
}
$('bCombo').addEventListener('click', () => openCombos(null));
$('bStyle').addEventListener('click', () => openBuilder('style'));
$('bChar').addEventListener('click', () => openBuilder('char'));

$('bNorm').addEventListener('click', () => {
  window._mm = 'norm';
  $('modalTitle').textContent = '📋 프롬프트 규격화';
  const b = $('modalBody');
  b.innerHTML = `<p class="hint">아무 데서나 복사한 프롬프트를 붙여넣고 [분류]를 누르면 규격 그룹으로 자동 정리됩니다. 규격은 규격.json에서 수정 가능.</p>
    <div class="field"><label>원본</label><textarea id="nmIn" style="min-height:64px;" placeholder="black hair, school uniform, artist:xxx, masterpiece..."></textarea></div>
    <div class="bar"><select id="nmType" style="width:auto;"><option value="char">캐릭터 규격</option><option value="style">그림체 규격</option></select>
      <button id="nmRun">분류</button><span class="n" id="nmStat"></span></div>
    <div id="nmG"></div>
    <div class="field"><label>이름</label><input type="text" id="nmName" placeholder="저장 이름"></div>`;
  $('nmRun').addEventListener('click', () => {
    const isS = $('nmType').value === 'style';
    const groups = isS ? (SPEC['그림체_그룹']||[]) : (SPEC['캐릭터_그룹']||[]);
    const def = isS ? SPEC['그림체_기본그룹'] : SPEC['캐릭터_기본그룹'];
    const res = {}; groups.forEach(g => res[g['이름']] = []);
    ($('nmIn').value||'').replace(/\n/g,',').split(',').map(x=>x.trim()).filter(Boolean).forEach(tag => {
      const m = tag.match(/^-?[\d.]+::(.*?)::?$/);
      const core = (m ? m[1] : tag).trim().toLowerCase();
      let best = null, bl = 0;
      groups.forEach(g => (g['키워드']||[]).forEach(k => { const kl = k.toLowerCase(); if(kl.length > bl && core.includes(kl)){ best = g['이름']; bl = kl.length; } }));
      res[best || def || groups[groups.length-1]['이름']].push(tag);
    });
    let n = 0;
    $('nmG').innerHTML = groups.map(g => { const v = res[g['이름']]||[]; n += v.length;
      return `<div class="field"><label>[${esc(g['이름'])}] ${v.length}개</label><textarea data-ng="${escA(g['이름'])}" style="min-height:36px;">${esc(v.join(', '))}</textarea></div>`; }).join('');
    $('nmStat').textContent = `${n}개 분류됨`;
  });
  $('modalFlash').textContent = ''; $('modalBg').style.display = 'flex';
});

/* ── 씬/옵션 편집 모달 ── */
async function openScene(setName, ids){
  window._mm = 'scene';
  const st = SETTINGS.find(s => s.name === setName) || {};
  const r = await (await fetch('/api/scenes?ids=' + ids.join(','))).json();
  if(!r.ok || !r.scenes.length){ alert('불러오기 실패'); return; }
  $('modalTitle').textContent = `${setName} · ${r.scenes[0].name}${ids.length>1?` 외 ${ids.length}단계`:''}`;
  const f = (id,k,l,v) => `<div class="field"><label>${l}</label><textarea data-sid="${id}" data-sk="${k}" style="min-height:42px;">${esc(v||'')}</textarea></div>`;
  $('modalBody').innerHTML = r.scenes.map(s => {
    /* 씬 모드에는 있는데 세팅에서 못 고치던 것들 — 해상도 프리셋 · 씬 전용 네거티브 */
    const isPreset = RES_PRESETS.some(r => r.w === s.width && r.h === s.height);
    let x = `<div class="row"><div class="tag">#${s.id} · ${esc(s.name)}
      <button data-preview="${s.id}" style="float:right;">🔍 최종 프롬프트 보기</button></div>
      <div class="filterbar" style="margin:0 0 6px;">
        <span class="hint" style="white-space:nowrap;">해상도</span>
        <select data-sid="${s.id}" data-sk="_res" style="width:132px;">
          ${RES_PRESETS.map(r => `<option value="${r.w}x${r.h}"${(isPreset && r.w===s.width && r.h===s.height)?' selected':''}
            >${r.label} ${r.w}×${r.h}</option>`).join('')}
          <option value=""${isPreset?'':' selected'}>직접 입력…</option>
        </select>
        <input type="number" data-sid="${s.id}" data-sk="width" value="${s.width||832}"
          min="64" max="2048" step="64" title="가로" style="width:58px;text-align:center;">
        <input type="number" data-sid="${s.id}" data-sk="height" value="${s.height||1216}"
          min="64" max="2048" step="64" title="세로" style="width:58px;text-align:center;">
      </div>`;
    if(st.mode === '백합'){ x += f(s.id,'base_tags','장면 공통',s.base_tags) + f(s.id,'female_prompt','주인공 쪽',s.female_prompt) + f(s.id,'partner_prompt','상대역 쪽',s.partner_prompt); }
    else if(st.mode === '단독'){ x += f(s.id,'female_prompt','프롬프트',s.female_prompt); }
    else { x += f(s.id,'female_prompt','여성 쪽',s.female_prompt) + f(s.id,'male_prompt','남성 (장면)',s.male_prompt); }
    return x + f(s.id, 'negative', '이 씬 전용 네거티브 (선택 · 기본 네거티브 뒤에 붙습니다)', s.negative)
             + `<div class="hint" id="pv-${s.id}"></div></div>`;
  }).join('');
  $('modalBody').querySelectorAll('[data-preview]').forEach(b =>
    b.addEventListener('click', () => scenePreview(b.dataset.preview)));
  /* 해상도 프리셋 → 숫자칸 채우기 (저장은 숫자칸 값으로 나간다) */
  $('modalBody').querySelectorAll('[data-sk="_res"]').forEach(sel =>
    sel.addEventListener('change', () => {
      if(!sel.value) return;
      const [w, h] = sel.value.split('x').map(Number);
      const box = sel.closest('.filterbar');
      box.querySelector('[data-sk="width"]').value = w;
      box.querySelector('[data-sk="height"]').value = h;
    }));
  $('modalFlash').textContent = ''; $('modalBg').style.display = 'flex';
}

/* 씬 하나가 NAI 로 어떻게 나가는지 그대로 보여준다.
   옵션(장소테마·시간대·표정진행·남자옷)을 곱한 결과라 조합 실수를 여기서 잡는다. */
async function scenePreview(num){
  const host = $('pv-' + num);
  if(!host) return;
  if(host.dataset.open === '1'){ host.innerHTML = ''; host.dataset.open = '0'; return; }
  host.innerHTML = '조립 중...';
  host.dataset.open = '1';
  const r = await (await fetch('/api/scene_preview', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({num: Number(num)})})).json();
  if(!r.ok){ host.innerHTML = `<span style="color:#e0574e">${esc(r.error)}</span>`; return; }
  const box = (label, val, tok) => val ? `<div class="field" style="margin-top:6px;">
      <label>${label}${tok != null ? ` <span class="hint">${tok} 토큰</span>` : ''}</label>
      <textarea readonly style="min-height:44px;">${esc(val)}</textarea></div>` : '';
  host.innerHTML = `<div class="row" style="margin:8px 0 0;background:var(--paper2);">
    <div class="tag">실제 전송값 · ${esc(r.setting)}(${esc(r.mode)}) · 캐스트 ${esc(r.cast)}
      · ${r.width}×${r.height} · 시드 ${r.seed}</div>
    ${box('베이스 (그림체 + 장소 + 시간대)', r.base, r.tokens.base)}
    ${box('캐릭터 1 (주인공 + 씬 + 표정아크)', r.female, r.tokens.female)}
    ${box('캐릭터 2 (상대역 + 옷단계 + 씬)', r.male, r.tokens.male)}
    ${box('네거티브', r.negative)}
    ${box('캐릭터 1 네거티브', r.char_negative)}
    ${box('캐릭터 2 네거티브', r.male_negative)}
  </div>`;
}

function optText(v){
  if(Array.isArray(v)) return v.join('\n');
  if(v && typeof v === 'object') return Object.entries(v).map(([k,x]) => `${k}: ${x}`).join('\n');
  return String(v ?? '');
}
function optVal(name, text){
  text = text.trim();
  if(name === '표정진행') return text.split('\n').map(x=>x.trim()).filter(Boolean);
  if(text.includes('\n') && text.includes(':')){
    const o = {};
    text.split('\n').forEach(l => { const i = l.indexOf(':'); if(i>0) o[l.slice(0,i).trim()] = l.slice(i+1).trim(); });
    return o;
  }
  return text;
}
function openOpts(name){
  window._mm = 'opts'; window._os = name;
  $('modalTitle').textContent = `'${name}' 옵션 항목 — 세팅 파일에 저장`;
  drawOpts();
  $('modalFlash').textContent = ''; $('modalBg').style.display = 'flex';
}
function drawOpts(){
  const st = SETTINGS.find(s => s.name === window._os);
  const b = $('modalBody'); b.innerHTML = '';
  if(!st) return;
  Object.keys(st.options||{}).filter(k=>!k.startsWith('_')).forEach(ok => {
    const opts = st.options[ok]||{};
    let x = `<div class="row"><div class="tag">${esc(ok)}</div>`;
    Object.keys(opts).forEach(n => {
      x += `<div class="bar" style="margin:3px 0;"><span style="min-width:78px;font-size:var(--fs-xs);font-weight:600;">${esc(n)}</span>
        <span style="flex:1;font-size:var(--fs-2xs);color:var(--muted);overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">${esc(optText(opts[n]).replace(/\n/g,' / ').slice(0,64))}</span>
        <button data-ol="${escA(ok)}" data-on="${escA(n)}">수정</button>
        <button class="danger" data-od="${escA(ok)}" data-on="${escA(n)}">삭제</button></div>`;
    });
    x += `<div class="grid2" style="margin-top:7px;"><div class="field"><label>이름</label><input type="text" data-onn="${escA(ok)}"></div>
      <div class="field"><label>내용</label><textarea data-onv="${escA(ok)}" style="min-height:38px;"></textarea></div></div>
      <button data-oa="${escA(ok)}">+ 추가/변경</button></div>`;
    b.insertAdjacentHTML('beforeend', x);
  });
  b.querySelectorAll('[data-od]').forEach(x => x.addEventListener('click', () => optSave(x.dataset.od, 'del', x.dataset.on, null)));
  b.querySelectorAll('[data-ol]').forEach(x => x.addEventListener('click', () => {
    const st2 = SETTINGS.find(s => s.name === window._os);
    b.querySelector(`[data-onn="${CSS.escape(x.dataset.ol)}"]`).value = x.dataset.on;
    b.querySelector(`[data-onv="${CSS.escape(x.dataset.ol)}"]`).value = optText((st2.options[x.dataset.ol]||{})[x.dataset.on]);
  }));
  b.querySelectorAll('[data-oa]').forEach(x => x.addEventListener('click', () => {
    const ok = x.dataset.oa;
    const n = b.querySelector(`[data-onn="${CSS.escape(ok)}"]`).value.trim();
    const v = b.querySelector(`[data-onv="${CSS.escape(ok)}"]`).value;
    if(!n){ alert('이름을 입력해주세요.'); return; }
    optSave(ok, 'set', n, optVal(ok, v));
  }));
}
async function optSave(option, op, name, value){
  const r = await (await fetch('/api/option_item', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({setting: window._os, option, op, name, value})})).json();
  if(r.ok){ SETTINGS = r.snapshot.settings || []; drawOpts(); renderSettings();
    $('modalFlash').textContent = `${option} '${name}' ${op==='del'?'삭제':'저장'}됨 ✓`; }
  else $('modalFlash').textContent = r.error || '실패';
}

/* ── 모달 저장/닫기 ── */
$('modalClose').addEventListener('click', () => {
  if(window._mm === 'combo') discardComboReturn();
  $('modalBg').style.display = 'none';
  $('modalBody').closest('.modal').classList.remove('builder-modal');
});
$('modalBg').addEventListener('click', e => {
  if(e.target.id === 'modalBg'){
    if(window._mm === 'combo') discardComboReturn();
    $('modalBg').style.display = 'none';
    $('modalBody').closest('.modal').classList.remove('builder-modal');
  }
});
$('modalSave').addEventListener('click', async () => {
  const m = window._mm;
  if(m === 'lib' || m === 'opts' || m === 'recipe' || m === 'combo'){
    if(m === 'combo') discardComboReturn();
    $('modalBg').style.display = 'none';
    return;
  }
  if(m === 'scene'){
    const u = {};
    /* textarea 뿐 아니라 숫자칸(해상도)도 함께 모은다. `_res` 셀렉트는 보내지 않는다
       (그건 숫자칸을 채우는 도우미일 뿐이다). */
    $('modalBody').querySelectorAll('[data-sid]').forEach(t => {
      if(t.dataset.sk === '_res') return;
      (u[t.dataset.sid] = u[t.dataset.sid]||{})[t.dataset.sk] = t.value;
    });
    const r = await (await fetch('/api/scene_save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({updates:u})})).json();
    $('modalFlash').textContent = r.ok ? `저장됨 ✓ ${r.updated}씬` : (r.error||'실패');
    return;
  }
  if(m === 'style' || m === 'char'){
    const name = ($('bldName') || {value:''}).value.trim();
    if(!name){ alert('이름을 입력해주세요.'); return; }
    const composed = window._comp ? window._comp() : '';
    const negative = window._compNeg ? window._compNeg() : (($('bldNeg') || {value:''}).value || '');
    if(!composed){ alert('선택된 태그가 없습니다.'); return; }
    const groups = {};
    $('modalBody').querySelectorAll('.sec').forEach(sec => {
      const step = sec.querySelector('.nm').textContent;
      sec.querySelectorAll('[data-slot]').forEach(f => {
        const lb = f.querySelector('.slot-name');
        const vals = Array.from(f.querySelectorAll('select')).map(s => s.value).filter(Boolean);
        if(vals.length && lb) groups[`${step}·${lb.textContent}`] = vals.join(', ');
      });
    });
    const ex = ($('bldExtra') || {}).value;
    if(ex && ex.trim()) groups['추가'] = ex.trim();
    if(m === 'style'){
      const r = await (await fetch('/api/style_save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name, prompt: composed, groups,
          negative, settings:styleSettingsFromUI()})})).json();
      if(r.ok){ STYLES = r.styles; renderPresets(); renderLibrary(); $('modalFlash').textContent = `그림체/${name}.json 저장됨 ✓`; }
      else $('modalFlash').textContent = r.error;
    } else {
      const r = await (await fetch('/api/norm_save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({type:'char', name, negative,
          groups:{'조합': composed}, builder_groups: groups})})).json();
      if(r.ok){
        STATE.characters = r.characters;
        let used = false;
        if(($('bldUseNow') || {}).checked){
          const c = r.characters[r.characters.length - 1] || {};
          (STATE.char_slots = STATE.char_slots || []).push({
            name:c.name || name, prompt:c.female || composed, outfit:'',
            negative:c.negative || negative, enabled:true
          });
          autoCoordsOnSecond();
          used = true;
          save();
        }
        renderLibrary(); renderSlots(); tokens();
        $('modalFlash').textContent = `캐릭터 '${name}' 저장됨 ✓` + (used ? ' · 캐릭터 칸에 추가됨' : '');
      }
      else $('modalFlash').textContent = r.error;
    }
    return;
  }
  if(m === 'norm'){
    const name = $('nmName').value.trim();
    if(!name){ alert('이름을 입력해주세요.'); return; }
    const groups = {};
    $('modalBody').querySelectorAll('[data-ng]').forEach(t => { if(t.value.trim()) groups[t.dataset.ng] = t.value.trim(); });
    const isS = $('nmType').value === 'style';
    const r = await (await fetch('/api/norm_save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({type: isS?'style':'char', name, groups})})).json();
    if(r.ok){
      if(isS){ STYLES = r.styles; renderPresets(); } else { STATE.characters = r.characters; renderSlots(); }
      renderLibrary();
      $('modalFlash').textContent = `'${name}' 저장됨 ✓`;
    } else $('modalFlash').textContent = r.error;
  }
});

/* ── UI 테마 ── */
/* '' = 슬레이트(:root 기본). 밝은 것 먼저, 어두운 것 뒤로 묶어 뒀다 */
/* [값, 이름, 배경, 카드, 강조] — 칩에 그 테마 색을 실제로 보여 준다 */
const THEMES = [
  ['','슬레이트','#e9ecef','#ffffff','#2563eb'],
  ['paper','종이','#f3f1ec','#ffffff','#4a6cf7'],
  ['sepia','고서','#efe6d4','#faf4e6','#9a6a2f'],
  ['sakura','벚꽃','#fdf2f6','#ffffff','#e0508f'],
  ['midnight','미드나잇','#0e1014','#161920','#7c8cff'],
  ['ocean','오션','#0b1a24','#11242f','#3ec9e0'],
  ['forest','포레스트','#101a12','#16231a','#5fd47a'],
  ['terminal','터미널','#07100a','#0b160f','#39ff87'],
  ['mono','모노크롬','#141414','#1c1c1c','#d8d8d8'],
  ['wine','와인','#170f14','#20161c','#e05780'],
];
const LAYOUTS = [['studio','작업실'],['classic','기존 호환']];
const ACCENTS = [['','기본'],['blue','파랑'],['violet','보라'],['pink','분홍'],['green','초록'],['amber','앰버'],['cyan','시안'],['red','빨강']];
const FSIZES = [['s','작게'],['','보통'],['l','크게'],['xl','아주 크게']];
const RADII = [['','기본'],['soft','살짝 둥글게'],['round','둥글게']];
function applyUI(){
  const u = STATE.ui || {};
  const r = document.documentElement;
  /* 옛 설정 이관 — 'slate'·'sharp' 는 이제 :root 기본값 자체다.
     그냥 두면 칩 강조가 어긋나므로 빈 값으로 접어 준다. */
  if(u.theme === 'slate') u.theme = '';
  if(u.radius === 'sharp') u.radius = '';
  const layout = u.layout === 'classic' ? 'classic' : 'studio';
  layout === 'studio'
    ? r.setAttribute('data-layout', 'studio')
    : r.removeAttribute('data-layout');
  u.theme ? r.setAttribute('data-theme', u.theme) : r.removeAttribute('data-theme');
  u.accent ? r.setAttribute('data-accent', u.accent) : r.removeAttribute('data-accent');
  u.fs ? r.setAttribute('data-fs', u.fs) : r.removeAttribute('data-fs');
  u.radius ? r.setAttribute('data-radius', u.radius) : r.removeAttribute('data-radius');
  arrangeStudioWorkspace();
}
function renderUIChips(){
  const mk = (host, list, key) => {
    const h = $(host); if(!h) return;
    h.innerHTML = '';
    list.forEach(([v, label, bg, card, accent]) => {
      const c = document.createElement('span');
      const current = key === 'layout'
        ? ((STATE.ui||{}).layout === 'classic' ? 'classic' : 'studio')
        : ((STATE.ui||{})[key]||'');
      c.className = 'chip' + (current === v ? ' on' : '');
      if(bg){
        /* 테마 칩은 그 테마의 배경·카드·강조색을 작은 점으로 미리 보여 준다 */
        c.innerHTML = `<span style="display:inline-flex;gap:2px;vertical-align:-1px;margin-right:5px;">
          <i style="width:8px;height:8px;background:${bg};border:1px solid #8886;display:inline-block;"></i>
          <i style="width:8px;height:8px;background:${card};border:1px solid #8886;display:inline-block;"></i>
          <i style="width:8px;height:8px;background:${accent};border:1px solid #8886;display:inline-block;"></i>
        </span>${label}`;
      } else c.textContent = label;
      c.addEventListener('click', () => {
        STATE.ui = STATE.ui || {};
        STATE.ui[key] = v;
        applyUI(); renderUIChips(); save();
      });
      h.appendChild(c);
    });
  };
  mk('layoutChips', LAYOUTS, 'layout');
  mk('themeChips', THEMES, 'theme');
  mk('accentChips', ACCENTS, 'accent');
  mk('fsChips', FSIZES, 'fs');
  mk('radiusChips', RADII, 'radius');
}

/* ── 상태 폴링 ── */
let lastFile = '';
let WAS_RUNNING = false;
let LAST_LIVE_STATUS = null;
const LIVE_PHASE_LABEL = {
  idle:'대기', running:'진행 중', stopping:'중지 중', completed:'완료',
  partial:'일부 실패', failed:'실패', stopped:'중지됨'
};
function compactDuration(seconds){
  const n = Math.max(0, Math.round(Number(seconds) || 0));
  if(n < 60) return `${n}초`;
  const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60);
  return h ? `${h}시간 ${m}분` : `${m}분`;
}
if($('pvReturn')) $('pvReturn').addEventListener('click', () => {
  const mode = LAST_LIVE_STATUS && LAST_LIVE_STATUS.retry_mode;
  setMode(['preview','settings','builder','library','system'].includes(mode) ? mode : 'preview');
});
async function poll(){
  try{
    const s = await (await fetch('/status.json', {cache:'no-store'})).json();
    LAST_LIVE_STATUS = s;
    $('pvName').textContent = s.operation || s.char_name || '대기 중';
    $('pvFile').textContent = s.filename || '아직 저장된 파일 없음';
    $('pvStatus').textContent = s.status_text || '-';
    $('pvPhase').dataset.phase = s.phase || 'idle';
    $('pvPhase').textContent = LIVE_PHASE_LABEL[s.phase] || s.phase || '대기';
    $('pvProg').textContent = `${s.index} / ${s.total}`;
    $('pvCounts').textContent = `성공 ${s.completed || 0} · 실패 ${s.failed || 0}`
      + (s.retry_count ? ` · 자동 재시도 ${s.retry_count}` : '');
    $('pvEta').textContent = s.running
      ? (s.eta_seconds == null
          ? `남은 시간 계산 중${s.elapsed_seconds ? ` · 경과 ${compactDuration(s.elapsed_seconds)}` : ''}`
          : `약 ${compactDuration(s.eta_seconds)} 남음 · 경과 ${compactDuration(s.elapsed_seconds)}`)
      : (s.phase === 'completed' && s.elapsed_seconds
          ? `걸린 시간 ${compactDuration(s.elapsed_seconds)}` : '남은 시간 —');
    $('pvDaily').textContent = `오늘 ${s.daily} / ${s.daily_cap}`;
    $('pvReturn').classList.toggle('hidden', !s.can_retry || !!s.running);
    $('pvBar').style.width = (s.total ? Math.round(s.index/s.total*100) : 0) + '%';
    lastSeed = s.seed || 0;
    $('pvSeedRow').style.display = lastSeed ? 'flex' : 'none';
    $('pvSeed').textContent = '시드 ' + lastSeed + (s.seed_key ? ` (회차 ${s.seed_key})` : '');
    if(s.has_image){
      const u = '/latest.webp?t=' + Date.now();
      $('pvImg').innerHTML = `<img src="${u}">`;
      if(s.filename && s.filename !== lastFile){
        lastFile = s.filename;
        HIST.unshift(u); HIST = HIST.slice(0, 12);
        $('hist').innerHTML = HIST.map(x => `<img src="${x}">`).join('');
      }
    }
    $('batchBtn').disabled = s.running;
    $('genBtn').disabled = s.running;
    $('genBtn').textContent = s.running ? '생성 중...' : '생성';
    if($('stopBtn')){
      $('stopBtn').classList.toggle('hidden', !s.running);
      $('stopBtn').disabled = !!s.stopping;
      $('stopBtn').textContent = s.stopping ? '중지 중…' : '■ 중지';
    }
    /* 돌던 것이 멈춘 순간에만 한 번 알린다 (계속 울리면 안 된다) */
    if(WAS_RUNNING && !s.running) notifyDone(s.status_text || '생성이 끝났습니다.');
    WAS_RUNNING = s.running;
  }catch(e){}
  setTimeout(poll, 1400);
}

init();
poll();

/* ── 왼쪽 패널 폭 드래그 조절 — 브라우저별 취향이라 localStorage 에 저장 ── */
(function(){
  const d = $('lwDrag');
  if(!d) return;
  const clamp = w => Math.min(560, Math.max(240, w));
  const apply = w => document.documentElement.style.setProperty('--lw', w + 'px');
  const saved = parseInt(localStorage.getItem('lw') || '', 10);
  if(saved) apply(clamp(saved));
  let on = false;
  d.addEventListener('mousedown', e => { on = true; e.preventDefault(); });
  document.addEventListener('mousemove', e => { if(on) apply(clamp(e.clientX)); });
  document.addEventListener('mouseup', e => {
    if(!on) return;
    on = false;
    localStorage.setItem('lw', clamp(e.clientX));
  });
})();

/* ── 패널 접기 (Forge · blue 둘 다 갖고 있다) ────────────────────────────
   Forge v1.2.11 는 타이틀바에서 좌패널을 감추고(`CustomTitleBar.tsx:110-`),
   blue v2.11.2 는 좌·우 둘 다 감추고 그 상태를 저장한다(`layout-store.ts:6-37`).
   우리는 폭 손잡이만 있어 자료·세팅 탭에서 프롬프트 칸이 차지한 자리를 되찾을 수
   없었다 (1600 에서 좌 440 + 우 300 = 46% 가 그 탭의 일과 무관하게 고정).
   ⚠ 저장은 `--lw` 와 같이 **localStorage** 에 둔다. 브라우저별 취향이고,
     `설정.json` 에 넣으면 옛 설정 파일과 스키마가 갈린다. */
(function(){
  const app = $('app');
  if(!app) return;
  const PANES = [['togLeft', 'lhide', 'panelL'], ['togRight', 'rhide', 'panelR']];
  const paint = (btn, hidden) => {
    if(!btn) return;
    btn.setAttribute('aria-pressed', hidden ? 'true' : 'false');
  };
  PANES.forEach(([id, attr, key]) => {
    const btn = $(id);
    const hidden = localStorage.getItem(key) === '1';
    if(hidden) app.setAttribute('data-' + attr, '1');
    paint(btn, hidden);
    if(!btn) return;
    btn.addEventListener('click', () => {
      const now = app.getAttribute('data-' + attr) === '1';
      if(now) app.removeAttribute('data-' + attr);
      else app.setAttribute('data-' + attr, '1');
      localStorage.setItem(key, now ? '0' : '1');
      paint(btn, !now);
    });
  });
  /* Alt+[ / Alt+] — 탭 전환이 Alt+1~5 라 같은 결로 맞췄다 */
  document.addEventListener('keydown', e => {
    if(!e.altKey || e.ctrlKey || e.metaKey) return;
    if(e.key === '[' && $('togLeft')){ e.preventDefault(); $('togLeft').click(); }
    if(e.key === ']' && $('togRight')){ e.preventDefault(); $('togRight').click(); }
  });
})();

/* ── 태그 검증 ────────────────────────────────────────────────────────
   posts.json 은 비로그인 태그 2개 제한이 있지만 tags.json 은 제한이 없다.
   없는 태그는 그림에 아무 영향 없이 토큰만 먹으므로 찾아낼 값어치가 있다. */
async function runTagVerify(){
  const box = $('tagVerifyOut'), btn = $('tagVerifyBtn');
  if(!box) return;
  const text = [$('basePrompt').value, $('baseFixed') ? $('baseFixed').value : '',
                $('baseVar') ? $('baseVar').value : '',
                $('baseDetail') ? $('baseDetail').value : ''].join(',');
  if(!text.replace(/[,\s]/g, '')){ box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  box.innerHTML = '<span style="color:var(--muted)">확인 중...</span>';
  if(btn) btn.style.opacity = '.4';
  try{
    const r = await (await fetch('/api/verify_tags', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})})).json();
    if(!r.ok){ box.innerHTML = '<span style="color:#e0574e">'+(r.error||'실패')+'</span>'; return; }
    const s = r.summary || {};
    const ghosts = (r.items||[]).filter(x => x.status === 'ghost');
    const lows   = (r.items||[]).filter(x => x.status === 'low');
    const olds   = (r.items||[]).filter(x => x.status === 'old');
    const als    = (r.items||[]).filter(x => x.status === 'alias');
    const nais   = (r.items||[]).filter(x => x.status === 'nai_renamed');
    let html = '<b>있음 '+(s.ok||0)+'</b>'
      + ' · <span style="color:#c9a227">드묾 '+(s.low||0)+'</span>'
      + (s.old ? ' · <span style="color:#4a7cc4">폐지됨 '+s.old+'</span>' : '')
      + (s.alias ? ' · <span style="color:#4a7cc4">이름바뀜 '+s.alias+'</span>' : '')
      + (s.nai_renamed ? ' · <span style="color:#7950a8">NAI 개명 '+s.nai_renamed+'</span>' : '')
      + ' · <span style="color:#e0574e">없음 '+(s.ghost||0)+'</span>'
      + (s.unknown ? ' · <span style="color:var(--muted)">확인못함 '+s.unknown+'</span>' : '')
      + ' <span style="color:var(--muted)">(단부루 기준 · 100장 미만이면 드묾)</span>';
    /* 품질·스타일 낱말은 단부루 태그가 아니다 — '없음' 이 곧 잘못이라는 뜻은 아니라고 알려 준다 */
    if((s.ghost||0) > 0){
      html += '<div style="color:var(--muted);margin-top:3px;">'
        + 'best quality · 8k 처럼 품질·화풍을 가리키는 낱말은 단부루 태그가 아니어서 여기 걸립니다'
        + ' (NAI 는 알아듣기도 합니다).</div>';
    }
    if(ghosts.length){
      html += '<div style="margin-top:5px;">';
      ghosts.forEach(g => {
        html += '<div><span style="color:#e0574e">✗ '+esc(g.raw)+'</span>';
        if((g.suggest||[]).length){
          html += ' <span style="color:var(--muted)">→</span> ' + g.suggest.map(x =>
            '<span class="tvsug" data-old="'+esc(g.raw)+'" data-new="'+esc(x.name)+'" '
            + 'style="cursor:pointer;text-decoration:underline dotted;" '
            + 'title="눌러서 바꾸기">'+esc(x.name)+'<span style="opacity:.6">('+x.count+')</span></span>'
          ).join(', ');
        }
        html += '</div>';
      });
      html += '</div>';
    }
    if(lows.length){
      html += '<div style="margin-top:4px;color:#c9a227">△ '
        + lows.map(x => esc(x.raw)+'('+x.count+')').join(', ') + '</div>';
    }
    /* 폐지된 태그 — 단부루 어휘에는 있지만 더는 쓰지 않는다.
       NAI 는 학습 당시 사전을 쓰므로 대개 알아듣는다. 없는 태그와 구분해서 보여 준다. */
    if(olds.length){
      html += '<div style="margin-top:4px;color:#4a7cc4">↷ 폐지된 태그(NAI 는 대개 알아듣습니다): '
        + olds.map(x => esc(x.raw)).join(', ') + '</div>';
    }
    /* 이름이 바뀐 것 — 새 이름을 눌러서 바로 갈아 끼울 수 있다 */
    if(als.length){
      html += '<div style="margin-top:4px;color:#4a7cc4">↷ 이름 바뀜: ' + als.map(x =>
        esc(x.raw)+' → <span class="tvsug" data-old="'+esc(x.raw)+'" data-new="'+esc(x.alias_to)
        + '" style="cursor:pointer;text-decoration:underline dotted;" title="눌러서 새 이름으로">'
        + esc(x.alias_to)+'</span>').join(', ') + '</div>';
    }
    /* NovelAI가 단부루 원래 이름과 다르게 쓰는 공식 개명 태그 */
    if(nais.length){
      html += '<div style="margin-top:4px;color:#7950a8">◆ NovelAI 권장 이름: ' + nais.map(x =>
        esc(x.raw)+' → <span class="tvsug" data-old="'+esc(x.raw)+'" data-new="'+esc(x.alias_to)
        + '" style="cursor:pointer;text-decoration:underline dotted;" title="눌러서 NovelAI 이름으로">'
        + esc(x.alias_to)+'</span>').join(', ') + '</div>';
    }
    if(r.error) html += '<div style="color:var(--muted);margin-top:4px;">일부 확인 실패: '+esc(r.error)+'</div>';
    box.innerHTML = html;
    /* 후보를 누르면 프롬프트에서 그 태그만 바꿔 준다 */
    box.querySelectorAll('.tvsug').forEach(el => el.addEventListener('click', () => {
      const oldT = el.dataset.old, newT = el.dataset.new;
      ['basePrompt','baseFixed','baseVar','baseDetail'].forEach(id => {
        const t = $(id); if(!t) return;
        const parts = t.value.split(',');
        let hit = false;
        const next = parts.map(x => {
          if(!hit && x.trim() === oldT.trim()){ hit = true; return x.replace(oldT.trim(), newT); }
          return x;
        });
        if(hit){ t.value = next.join(','); t.dispatchEvent(new Event('input')); }
      });
      runTagVerify();
    }));
  }catch(e){
    box.innerHTML = '<span style="color:#e0574e">확인 실패: '+e+'</span>';
  }finally{
    if(btn) btn.style.opacity = '';
  }
}
if($('tagVerifyBtn')) $('tagVerifyBtn').addEventListener('click', (e) => {
  e.stopPropagation();   /* 머리를 누르면 접히므로 막는다 */
  runTagVerify();
});

</script>
</body></html>
"""


def render_page():
    """파라미터 선택지를 파이썬 상수에서 채워 넣는다 (목록을 한 곳에서만 관리)."""
    def opts(pairs):
        return "".join(f'<option value="{v}">{esc_html(l)}</option>' for v, l in pairs)
    return (PAGE_TEMPLATE
            .replace("__MODELS__", opts(MODELS))
            .replace("__SAMPLERS__", opts((s, s.replace("k_", "")) for s in SAMPLERS))
            .replace("__SCHEDS__", opts((s, s) for s in NOISE_SCHEDULES))
            .replace("__UCP__", opts((str(v), f"{v} · {l}") for v, l in UC_PRESETS))
            .replace("__RES__", opts((f"{w}x{h}", f"{lbl} {w}×{h}") for w, h, lbl in RESOLUTIONS))
            .replace("__RESJSON__", json.dumps(
                [{"w": w, "h": h, "label": lbl} for w, h, lbl in RESOLUTIONS], ensure_ascii=False))
            .replace("__DIRTOOLS__", opts((t, lbl) for t, lbl, _ in DIRECTOR_TOOLS))
            .replace("__EMOTIONS__", opts((e, e) for e in EMOTIONS))
            .replace("__BOORUS__", opts((k, v["name"] + v.get("note", ""))
                                       for k, v in BOORUS.items()))
            .replace("__PROFNOW__", f"프로필 「{PROFILE}」" if PROFILE else "기본 (첫째 계정)")
            .replace("__PROFTITLE__", f" — {PROFILE}" if PROFILE else "")
            .replace("__PROFBADGE__", (f'<span class="badge" style="margin-left:7px;">'
                                       f'프로필 {PROFILE}</span>') if PROFILE else ""))


def esc_html(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# 서버는 HTML input의 min/max를 신뢰하지 않는다. 직접 HTTP 요청과 손상된 설정도 같은 규칙을 거친다.
_NUMERIC_RULES = {
    "steps": (1, 50, True), "cfg_scale": (1.0, 10.0, False),
    "cfg_rescale": (0.0, 1.0, False), "save_quality": (40, 100, True),
    "seed": (1, 999999999, True), "nai_seed": (0, 2**32 - 1, True),
    "uncond_scale": (0.0, 1.5, False), "controlnet_strength": (0.0, 2.0, False),
}
_PACE_RULES = {
    "delay_min": (0.0, 120.0, False), "delay_max": (0.0, 300.0, False),
    "daily_cap": (1, 100000, True), "soft_every": (0, 100000, True),
    "soft_seconds": (1, 3600, True), "cool_every": (0, 100000, True),
    "cool_seconds": (1, 7200, True),
}


def _bounded_number(value, low, high, integer=False):
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("number must be finite")
    if integer:
        number = int(number)
    used = max(low, min(high, number))
    return int(used) if integer else float(used)


def normalize_resolution(value):
    raw = _bounded_number(value, 64, 2048, True)
    return max(64, min(2048, raw // 64 * 64))


def validate_config_value(key, value, current):
    """(ok, value, corrections). corrections는 UI에 보낼 dotted-key 사전."""
    fixed = {}
    try:
        if key in ("width", "height"):
            used = normalize_resolution(value)
        elif key in _NUMERIC_RULES:
            used = _bounded_number(value, *_NUMERIC_RULES[key])
        elif key == "save_max_side":
            used = int(value)
            if used not in (0, 768, 1024, 1536):
                raise ValueError("unsupported save size")
        elif key == "uc_preset":
            used = int(value)
            if used not in (0, 1, 3, 4):
                raise ValueError("unsupported UC preset")
        elif key == "pace":
            if not isinstance(value, dict):
                raise ValueError("pace must be an object")
            used = dict(current) if isinstance(current, dict) else dict(PACE_DEFAULT)
            for pkey, rule in _PACE_RULES.items():
                if pkey not in value:
                    continue
                pused = _bounded_number(value[pkey], *rule)
                used[pkey] = pused
                if pused != value[pkey]:
                    fixed[f"pace.{pkey}"] = {"sent": value[pkey], "used": pused}
            unknown = set(value) - set(_PACE_RULES)
            if unknown:
                raise ValueError(f"unknown pace fields: {sorted(unknown)}")
            if used.get("delay_max", 0) < used.get("delay_min", 0):
                sent = used["delay_max"]
                used["delay_max"] = used["delay_min"]
                fixed["pace.delay_max"] = {"sent": sent, "used": used["delay_max"]}
        else:
            return True, value, fixed
    except (TypeError, ValueError, OverflowError):
        return False, current, fixed
    if used != value:
        fixed[key] = {"sent": value, "used": used}
    return True, used, fixed


class LiveState:
    """생성 진행 상황을 브라우저에 공유하기 위한 상태 저장소."""

    def __init__(self):
        self.lock = threading.Lock()
        self.image_bytes = None
        self.filename = ""
        self.char_name = ""
        self.index = 0
        self.total = 0
        self.daily = 0
        self.daily_cap = DAILY_CAP
        self.status_text = "설정 중..."
        self.running = False
        self._owner = 0        # 실행권 토큰 (아래 try_claim/release)
        self.stop_req = False  # 중지 요청 — 실행권과 별개다 (CQA-001)
        self.seed = 0          # 마지막으로 생성한 그림의 실제 NAI 시드
        self.seed_key = ""     # 배치 회차 번호 (01, 02 …)
        self.operation = "대기"
        self.phase = "idle"    # idle/running/stopping/completed/partial/failed/stopped
        self.completed = 0
        self.failed = 0
        self.retry_count = 0
        self.last_error = ""
        self.can_retry = False
        self.retry_mode = "preview"
        self.started_at = 0.0
        self.finished_at = 0.0
        self.eta_base_completed = 0

    def update(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def note_retry(self, error=""):
        with self.lock:
            self.retry_count += 1
            if error:
                self.last_error = str(error)

    # 이중 POST 레이스 방지 (라운드04 — Forge 가 실사용에서 겪은 함정과 같은 계열).
    # 예전에는 `if running: 거절` 검사와 스레드 안의 `running=True` 사이에 틈이 있어
    # 빠른 이중 요청이 둘 다 통과했고, 먼저 끝난 쪽 finally 가 남의 running 을 껐다.
    def try_claim(self, operation="생성", retry_mode="preview"):
        """실행권 원자 선점 — 성공하면 소유 토큰, 이미 실행 중이면 None.
        ⚠ 중지 요청이 와도 실행권은 owner 가 release 할 때까지 잡혀 있다 (CQA-001) —
        중지 직후 재시작해도 옛 작업이 실제로 끝나기 전에는 새 작업이 못 들어온다."""
        with self.lock:
            if self.running:
                return None
            self.running = True
            self.stop_req = False
            self._owner += 1
            self.operation = str(operation or "생성")
            self.phase = "running"
            self.completed = 0
            self.failed = 0
            self.retry_count = 0
            self.last_error = ""
            self.can_retry = False
            self.retry_mode = str(retry_mode or "preview")
            self.started_at = time.time()
            self.finished_at = 0.0
            self.eta_base_completed = 0
            return self._owner

    def release(self, token):
        """소유 토큰이 맞을 때만 running 을 끈다 — 옛 작업이 새 작업 상태를 못 끄게."""
        with self.lock:
            if self._owner == token:
                if self.stop_req and self.phase in ("running", "stopping"):
                    self.phase = "stopped"
                    self.can_retry = True
                elif self.phase in ("running", "stopping"):
                    self.phase = "completed"
                self.finished_at = time.time()
                self.running = False
                self.stop_req = False

    def wait_cancelable(self, seconds):
        """중지를 존중하는 대기 — 중지되면 즉시 True 를 돌려준다 (CQA-019).
        휴식·429·재시도 대기가 통짜 sleep 이면 중지를 눌러도 최대 60초 뒤 한 장이 더 나간다."""
        end = time.time() + max(0.0, float(seconds))
        while time.time() < end:
            if self.stop_req:
                return True
            time.sleep(min(0.5, end - time.time()))
        return self.stop_req

    def request_stop(self):
        """중지 요청 — 도는 작업이 장(파일) 경계에서 보고 멈춘다. 실행권은 안 푼다."""
        with self.lock:
            if not self.running:
                return False
            self.stop_req = True
            self.phase = "stopping"
            self.status_text = "중지 요청 — 이번 장까지 마치고 멈춥니다."
            return True

    def set_image(self, img):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=85)
        with self.lock:
            self.image_bytes = buf.getvalue()
            s = getattr(img, "nai_seed", None)
            if s:
                self.seed = int(s)

    def snapshot(self):
        with self.lock:
            end = (time.time() if self.running else
                   (self.finished_at or self.started_at or 0.0))
            elapsed = max(0.0, end - self.started_at) if self.started_at else 0.0
            run_done = max(0, int(self.completed) - int(self.eta_base_completed))
            remaining = max(0, int(self.total) - int(self.completed))
            eta = None
            if self.running and run_done > 0 and remaining > 0:
                eta = elapsed / run_done * remaining
            elif self.phase == "completed" and self.total:
                eta = 0.0
            return {
                "filename": self.filename, "char_name": self.char_name,
                "index": self.index, "total": self.total,
                "daily": self.daily, "daily_cap": self.daily_cap,
                "status_text": self.status_text,
                "running": self.running,
                "stopping": self.stop_req,
                "has_image": self.image_bytes is not None,
                "seed": self.seed, "seed_key": self.seed_key,
                "operation": self.operation, "phase": self.phase,
                "completed": self.completed, "failed": self.failed,
                "retry_count": self.retry_count,
                "last_error": self.last_error,
                "can_retry": self.can_retry,
                "retry_mode": self.retry_mode,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_seconds": round(elapsed, 1),
                "eta_seconds": round(eta, 1) if eta is not None else None,
                "eta_samples": run_done,
            }

    def image(self):
        with self.lock:
            return self.image_bytes


class ConfigServer:
    """설정 편집(실시간 자동저장) + 생성 시작 신호 + 실시간 미리보기를 모두 담당."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.spec = load_spec()
        self.live = LiveState()
        self.start_event = threading.Event()
        self.httpd = None
        self.url = None
        self.config_lock = threading.RLock()
        self.config_revision = 0
        self.anlas_balance_cache = None
        self.anlas_balance_token_key = None

    def latest_config_from_disk(self):
        """프로세스 잠금 안에서 공용 설정 최신판과 런타임 전용 값을 합친다."""
        runtime = {
            key: value for key, value in self.cfg.items()
            if str(key).startswith("_")
        }
        latest = {
            key: value for key, value in self.cfg.items()
            if not str(key).startswith("_")
        }
        if SETTINGS_FILE.is_file():
            try:
                loaded = load_json_recover(SETTINGS_FILE)
                if isinstance(loaded, dict):
                    latest = loaded
            except Exception:
                pass
        merged = dict(DEFAULT_CONFIG)
        merged.update(latest)
        merged.update(runtime)
        migrate_legacy_selections(merged)
        migrate_char_slots(merged)
        return merged

    def use_latest_config(self):
        merged = self.latest_config_from_disk()
        self.cfg.clear()
        self.cfg.update(merged)
        return merged

    def snapshot_config(self):
        settings_out = []
        try:
            for st in list_settings():
                scenes = st["data"].get("씬", {})
                groups = derive_setting_catalog(scenes)
                cats = {}
                for g in groups:
                    cats[g["cat"]] = cats.get(g["cat"], 0) + 1
                # 계열 이름표는 **세팅 파일의 '계열이름'** 이 먼저다.
                # 없으면 내장 표(체위용), 그것도 없으면 'H 계열' 식으로 자동.
                labels = st["data"].get("계열이름") or {}
                meta = {c: {"name": (labels.get(c)
                                     or CATEGORY_META.get(c, {}).get("name")
                                     or (f"{c} 계열" if c else "전체")),
                            "sub": f"{n}종"} for c, n in cats.items()}
                settings_out.append({
                    "file": st["file"], "name": st["name"], "mode": st["mode"],
                    "groups": groups, "category_meta": meta,
                    "options": st["data"].get("옵션", {}),
                    "role": st["data"].get("상대역", {}),
                    # ↓ 세팅 빌더용
                    "stages": st["data"].get("단계명") or [],
                    "axis_specs": {k: {"적용": t, "방식": sh}
                                   for k, (t, sh) in axis_specs(st["data"]).items()},
                    "cat_names": st["data"].get("계열이름") or {},
                    "nums": sorted(int(k) for k in st["data"].get("씬", {}) if str(k).isdigit()),
                })
        except Exception as e:
            log.warning(f"세팅 로드 실패: {e}")
        return {
            "config": {**{k: v for k, v in self.cfg.items() if not k.startswith("_")},
                       "_revision": self.config_revision},
            "settings": settings_out,
            "scene_clashes": scene_num_clashes(),
            "fragments": list_fragments(),
            "scenes": load_scenes(),
            "spec": self.spec,
            "styles": list_styles(self.spec),
            "builder": load_builder(),
            "scene_presets": list_scene_presets(),
            "startup_recovery": STARTUP_RECOVERY_NOTICE,
        }

    def handle_generate_one(self):
        """① 설정만으로 단독 1장 생성 (세팅 무관 — NAI 기본 생성처럼)"""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        cfg = self.cfg
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        slots = [s for s in cfg.get("char_slots", [])
                 if slot_prompt(s).strip() and s.get("enabled") is not False]
        tok = self.live.try_claim("단독 생성", "preview")
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        def run():
            self.live.update(status_text="단독 생성 중...", char_name="단독 생성",
                             filename="", index=1, total=1)
            try:
                okp, why = pace_gate(cfg, self.live, "단독")   # 밴 예방 (CQA-013)
                if not okp:
                    self.live.update(
                        status_text=why, phase="stopped", can_retry=True)
                    return
                style = (cfg.get("base_prompt") or "").strip()
                base = style or "1girl"
                # 켠 인물만 보낸다 (칸은 6명 넘게 둬도 된다)
                people, ctrs = active_people(slots, cfg.get("char_centers"))
                params = runtime_generation_params(cfg, cfg["token"])
                state = load_state()
                try:
                    img = call_nai_api(
                        cfg["token"], base, "", "",
                        cfg.get("negative_prompt", ""),
                        int(cfg.get("width", 832)), int(cfg.get("height", 1216)),
                        chars=people,
                        scale=cfg.get("cfg_scale", 5.5), cfg_rescale=cfg.get("cfg_rescale", 0.56),
                        steps=int(cfg.get("steps", 28)), sampler=cfg.get("sampler", "k_euler_ancestral"),
                        scheduler=cfg.get("scheduler", "karras"), variety=cfg.get("variety", False),
                        uc_preset=int(cfg.get("uc_preset", 3)),
                        seed=fixed_seed(cfg), params=with_centers(params, ctrs))
                finally:
                    pace_complete()
                out_dir = out_sub(cfg, "단독")
                n = len([x for x in out_dir.iterdir() if x.suffix.lower() in (".webp", ".png")]) + 1
                save_with_meta(img, out_dir / f"{n:04d}.webp", fmt=out_format(cfg), clean=_ocargs(cfg)[0], max_side=_ocargs(cfg)[1],
                                quality=out_clean(cfg)[2])
                self.live.set_image(img)
                bump_daily(state)
                save_state(state)
                self.live.update(
                    status_text=f"단독 생성 완료 ✓ (output/단독/{n:04d}.webp)",
                    completed=1, phase="completed")
            except Exception as e:
                log.error(f"단독 생성 실패: {e}")
                self.live.update(
                    status_text=f"단독 생성 실패: {e}", failed=1,
                    last_error=str(e), can_retry=True, phase="failed")
            finally:
                self.live.release(tok)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def handle_i2i(self, body):
        """img2img · 인페인트 — 왼쪽 프롬프트/파라미터를 그대로 쓰고 원본 그림만 더한다.
        body: {image: dataURL, mask: dataURL|없음, strength, noise, seed}"""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        cfg = self.cfg
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        try:
            d = json.loads(body or b"{}")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        img_b64 = (d.get("image") or "").split(",", 1)[-1]
        if not img_b64:
            return {"ok": False, "error": "원본 그림이 없습니다."}
        mask_b64 = (d.get("mask") or "").split(",", 1)[-1] or None
        mode = "인페인트" if mask_b64 else "img2img"
        try:
            raw = base64.b64decode(img_b64)
            with Image.open(io.BytesIO(raw)) as im:
                w, h = im.size
        except Exception as e:
            return {"ok": False, "error": f"그림을 못 읽었습니다: {e}"}
        # NAI 는 64 의 배수를 원한다
        w, h = max(64, w // 64 * 64), max(64, h // 64 * 64)
        tok = self.live.try_claim(mode, "preview")
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        def run():
            self.live.update(status_text=f"{mode} 생성 중...",
                             char_name=mode, index=1, total=1)
            try:
                okp, why = pace_gate(cfg, self.live, mode)     # 밴 예방 (CQA-013)
                if not okp:
                    self.live.update(
                        status_text=why, phase="stopped", can_retry=True)
                    return
                slots = [s for s in cfg.get("char_slots", [])
                 if slot_prompt(s).strip() and s.get("enabled") is not False]
                seed = int(d.get("seed") or 0) or random.randint(0, 2**32 - 1)
                params = runtime_generation_params(cfg, cfg["token"])
                params["_i2i"] = {"image": img_b64, "mask": mask_b64,
                                  "strength": float(d.get("strength", 0.7)),
                                  "noise": float(d.get("noise", 0.0)), "seed": seed}
                try:
                    img = call_nai_api(
                        cfg["token"], cfg.get("base_prompt", "") or "1girl", "", "",
                        cfg.get("negative_prompt", ""), w, h,
                        chars=active_people(slots, cfg.get("char_centers"))[0],
                        scale=cfg.get("cfg_scale", 5.5), cfg_rescale=cfg.get("cfg_rescale", 0.56),
                        steps=int(cfg.get("steps", 28)), sampler=cfg.get("sampler", "k_euler_ancestral"),
                        scheduler=cfg.get("scheduler", "karras"), variety=cfg.get("variety", False),
                        uc_preset=int(cfg.get("uc_preset", 3)), seed=seed,
                        params=with_centers(params, active_people(slots, cfg.get("char_centers"))[1]))
                finally:
                    pace_complete()
                out_dir = out_sub(cfg, mode)
                n = len([x for x in out_dir.iterdir() if x.suffix.lower() in (".webp", ".png")]) + 1
                save_with_meta(img, out_dir / f"{n:04d}.webp", fmt=out_format(cfg), clean=_ocargs(cfg)[0], max_side=_ocargs(cfg)[1],
                                quality=out_clean(cfg)[2])
                self.live.set_image(img)
                st = load_state(); bump_daily(st); save_state(st)
                self.live.update(
                    status_text=f"{mode} 완료 ✓ (output/{mode}/{n:04d}.webp · 시드 {seed})",
                    seed=seed, completed=1, phase="completed")
            except Exception as e:
                log.error(f"{mode} 실패: {e}")
                self.live.update(
                    status_text=f"{mode} 실패: {e}", failed=1,
                    last_error=str(e), can_retry=True, phase="failed")
            finally:
                self.live.release(tok)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "mode": mode, "width": w, "height": h}

    def handle_regen(self, body):
        """그림체 복구 — 뽑아 둔 그림의 **메타데이터를 읽어 그 설정 그대로 다시 돌린다**.
        (NAIS3-Custom 의 '그림체 복구(메타데이터 i2i 일괄 재생성)' 와 같은 생각)
        용도: 흐릿하게 나온 장을 같은 프롬프트·시드로 다시 뽑거나,
              img2img 로 원본을 바탕에 두고 다듬는다.
        body: {paths: [output 상대경로…], mode: "generate"|"img2img", strength}"""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        cfg = self.cfg
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        try:
            d = json.loads(body or b"{}")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        mode = d.get("mode") or "generate"
        strength = float(d.get("strength", 0.5))
        root = out_root(cfg).resolve()
        jobs = []
        for rel in (d.get("paths") or []):
            f = (root / rel).resolve()
            try:
                inside = f.is_relative_to(root)
            except AttributeError:
                inside = str(f).startswith(str(root))
            if not (inside and f.is_file()):
                continue
            meta = extract_nai_metadata(f.read_bytes(),
                                       "image/png" if f.suffix.lower() == ".png" else "image/webp")
            raw = (meta or {}).get("raw") or {}
            if not raw:
                continue                      # 메타가 없는 그림은 되살릴 수 없다
            # ⚠ 모델은 `raw` 가 아니라 `params["model"]` 에 **표시명**으로 들어 있다
            #   ("NovelAI Diffusion V4.5 4BDE2A90" 같은 꼴). 예전엔 `raw["source_model"]`
            #   을 읽었는데 그 키는 어디서도 만들어지지 않아 **모델 복원이 늘 무시**됐다.
            #   표시명을 그대로 보내면 400 이므로 `model_id_from_metadata()` 로 옮긴다.
            #   Variety+ 시그마도 모델에서 역산하므로 이걸 고쳐야 재현이 맞는다.
            meta_model = ((meta or {}).get("params") or {}).get("model")
            jobs.append((f, raw, meta_model))
        if not jobs:
            return {"ok": False, "error": "메타데이터가 있는 그림이 없습니다. "
                                          "(카톡·디스코드를 거친 그림은 정보가 지워집니다)"}
        tok = self.live.try_claim("그림체 복구", "library")
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        def run():
            out_dir = out_sub(cfg, "복구")
            state = load_state()
            done = 0
            failed = 0
            blocked = False
            self.live.update(total=len(jobs), index=0, char_name="그림체 복구")
            try:
                for i, (f, raw, meta_model) in enumerate(jobs, 1):
                    if self.live.stop_req:
                        break
                    self.live.update(index=i, filename=f.name, status_text="복구 중...")
                    # 메타에서 그때 쓴 값을 그대로 꺼낸다
                    v4 = raw.get("v4_prompt") or {}
                    cap = (v4.get("caption") or {})
                    base = cap.get("base_caption") or raw.get("prompt") or ""
                    v4n = (raw.get("v4_negative_prompt") or {}).get("caption") or {}
                    neg = v4n.get("base_caption") or raw.get("uc") or ""
                    chars = [{"prompt": c.get("char_caption", ""), "negative": ""}
                             for c in (cap.get("char_captions") or [])]
                    for k, c in enumerate(v4n.get("char_captions") or []):
                        if k < len(chars):
                            chars[k]["negative"] = c.get("char_caption", "")
                    ctrs = [(c.get("centers") or [{}])[0] for c in (cap.get("char_captions") or [])]
                    prm = runtime_generation_params(cfg, cfg["token"], include_refs=False)
                    prm.update({
                        "model": model_id_from_metadata(
                            meta_model, cfg.get("model") or "nai-diffusion-4-5-full"),
                        "use_coords": bool(v4.get("use_coords")),
                        "char_centers": [{"x": float(c.get("x", 0.5)), "y": float(c.get("y", 0.5))}
                                         for c in ctrs],
                        "smea": bool(raw.get("sm")), "smea_dyn": bool(raw.get("sm_dyn")),
                        "prefer_brownian": bool(raw.get("prefer_brownian", True)),
                        "variety": raw.get("skip_cfg_above_sigma") is not None,
                    })
                    if mode == "img2img":
                        with Image.open(f) as im:
                            w0 = max(64, im.width // 64 * 64)
                            h0 = max(64, im.height // 64 * 64)
                            b = io.BytesIO(); im.convert("RGB").resize((w0, h0)).save(b, "PNG")
                        prm["_i2i"] = {"image": base64.b64encode(b.getvalue()).decode(),
                                       "mask": None, "strength": strength, "noise": 0.0}
                    seed = int(raw.get("seed") or 0) or random.randint(0, 2**32 - 1)
                    okp, why = pace_gate(cfg, self.live, "복구")
                    if not okp:
                        self.live.update(status_text=why)
                        blocked = True
                        break
                    try:
                        try:
                            img = call_nai_api(
                                cfg["token"], base, "", "", neg,
                                int(raw.get("width") or cfg.get("width", 832)),
                                int(raw.get("height") or cfg.get("height", 1216)),
                                scale=float(raw.get("scale") or cfg.get("cfg_scale", 5.5)),
                                cfg_rescale=float(raw.get("cfg_rescale") or 0.0),
                                steps=int(raw.get("steps") or 28),
                                sampler=raw.get("sampler") or "k_euler_ancestral",
                                scheduler=raw.get("noise_schedule") or "karras",
                                uc_preset=int(raw.get("ucPreset", cfg.get("uc_preset", 3))),
                                seed=seed, params=prm, chars=chars)
                        finally:
                            pace_complete()
                    except Exception as e:
                        log.error(f"복구 실패 {f.name}: {e}")
                        failed += 1
                        self.live.update(
                            status_text=f"{f.name} 실패: {e}", failed=failed,
                            last_error=str(e))
                        continue
                    tag = "_i2i" if mode == "img2img" else ""
                    save_with_meta(img, out_dir / f"{f.stem}{tag}.webp",
                                   fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                                   max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                    self.live.set_image(img)
                    bump_daily(state); save_state(state)
                    done += 1
                if self.live.stop_req:
                    phase = "stopped"
                    text = f"그림체 복구 중지 — {done}/{len(jobs)}장 (다시 실행 가능)"
                elif blocked:
                    phase = "stopped"
                    text = self.live.status_text
                elif failed:
                    phase = "partial"
                    text = f"그림체 복구 일부 완료 — 성공 {done} · 실패 {failed}"
                else:
                    phase = "completed"
                    text = f"그림체 복구 완료 ✓ {done}/{len(jobs)}장 (output/복구/)"
                self.live.update(
                    status_text=text, completed=done, failed=failed, phase=phase,
                    can_retry=bool(failed or blocked or self.live.stop_req))
            finally:
                self.live.release(tok)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "count": len(jobs), "mode": mode}

    def handle_scene_run(self):
        """씬 모드 일괄 — 예약 매수를 걸어 둔 씬만 그 매수만큼 뽑는다.
        세팅 배치와 별개의 가벼운 경로다 (세팅 상태를 건드리지 않는다)."""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        cfg = self.cfg
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        jobs = scene_mode_pending(cfg)
        if not jobs:
            return {"ok": False, "error": "예약 매수를 1 이상으로 걸어 둔 씬이 없습니다."}
        slots = [s for s in cfg.get("char_slots", [])
                 if slot_prompt(s).strip() and s.get("enabled") is not False]
        tok = self.live.try_claim("씬 모드", "settings")
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        def run():
            state = load_state()
            state.setdefault("frag_seq", {})
            cfg["_frag_counters"] = state["frag_seq"]
            params = runtime_generation_params(cfg, cfg["token"])
            out_dir = out_sub(cfg, "씬")
            seed_key = f"{int(cfg.get('seed', 1)):02d}"
            state.setdefault("seeds", {})
            if seed_key not in state["seeds"]:
                state["seeds"][seed_key] = random.randint(0, 2**32 - 1)
                save_state(state)
            base_seed = state["seeds"][seed_key]
            style = (cfg.get("base_prompt") or "").strip()
            done = 0
            failed = 0
            blocked = False
            self.live.update(total=len(jobs), index=0, char_name="씬 모드")
            try:
                for i, (sc, copy) in enumerate(jobs, 1):
                    if self.live.stop_req:
                        break
                    okp, why = pace_gate(cfg, self.live, "씬")   # 밴 예방 (CQA-013)
                    if not okp:
                        self.live.update(status_text=why)
                        blocked = True
                        break
                    suffix = "" if copy == 1 else f"_{copy}벌"
                    seed = seed_for(cfg, base_seed, i + (copy - 1) * 100003)
                    scene_id = _safe_name(str(sc.get("id") or f"scene-{i}"))
                    stem = f"{scene_id}_{_safe_name(sc['name'])}_seed{seed}{suffix}"
                    target = available_output_path(out_dir / f"{stem}.webp", out_format(cfg))
                    fname = target.name
                    self.live.update(index=i, filename=fname, status_text="생성 중...", seed=seed)
                    # 씬 프롬프트는 그림체(베이스) 뒤에 붙는다 — 세팅과 같은 규칙.
                    # ★ 인물 묘사는 base 가 아니라 **캐릭터 칸**으로 보내야 한다.
                    #   씬의 char1/char2 가 있으면 그것을 쓰고, 없으면 왼쪽 캐릭터 칸을 쓴다.
                    #   왼쪽 칸과 씬 칸이 모두 있으면 이어 붙인다 (씬이 그 인물을 꾸미는 셈).
                    base = _join_tags(style, sc.get("prompt", ""))
                    neg = _join_tags(cfg.get("negative_prompt", ""), sc.get("negative", ""))
                    # ★ 씬의 인물 칸은 **별개 인물**이다 (왼쪽 칸에 이어 붙이지 않는다).
                    #   왼쪽에 남자만 넣고 씬에 여자를 적는 식으로 쓰는 게 목적이라,
                    #   합쳐 버리면 한 사람 안에 두 사람이 들어가 몸이 뭉개진다.
                    extra = [{"prompt": sc[k], "negative": sc.get(k + "_neg", "")}
                             for k in ("char1", "char2") if (sc.get(k) or "").strip()]
                    people, ctrs = active_people(slots, cfg.get("char_centers"), extra)
                    # 인물이 둘 이상이면 좌표를 켜고 고르게 벌린다 (공홈과 같은 동작).
                    # 안 그러면 NAI 가 몸을 붙여 그린다.
                    if len(people) > 1 and not cfg.get("use_coords"):
                        cfg["use_coords"] = True
                        log.info(f"씬에 인물이 {len(people)}명이라 캐릭터 좌표를 켰습니다")
                    # 좌표가 없거나 겹치면 고르게 다시 벌린다
                    if len(people) > 1:
                        pts = {(c.get("x"), c.get("y")) for c in ctrs}
                        if len(pts) < len(people):
                            ctrs = spread_centers(len(people))
                    try:
                        try:
                            img = call_nai_api(
                                cfg["token"], base, "", "",
                                neg, int(sc.get("width", 832)), int(sc.get("height", 1216)),
                                chars=people,
                                scale=cfg.get("cfg_scale", 5.5),
                                cfg_rescale=cfg.get("cfg_rescale", 0.56),
                                steps=int(cfg.get("steps", 28)),
                                sampler=cfg.get("sampler", "k_euler_ancestral"),
                                scheduler=cfg.get("scheduler", "karras"),
                                variety=cfg.get("variety", False),
                                uc_preset=int(cfg.get("uc_preset", 3)),
                                seed=seed, params=with_centers(params, ctrs))
                        finally:
                            pace_complete()
                    except Exception as e:
                        log.error(f"씬 '{sc['name']}' 실패: {e}")
                        failed += 1
                        self.live.update(
                            status_text=f"'{sc['name']}' 실패: {e}", failed=failed,
                            last_error=str(e))
                        continue
                    saved_path = save_with_meta(img, target, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                                                max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                    self.live.update(filename=saved_path.name)
                    self.live.set_image(img)
                    bump_daily(state)
                    save_state(state)
                    done += 1
                if self.live.stop_req:
                    phase = "stopped"
                    text = f"씬 모드 중지 — {done}/{len(jobs)}장 (다시 실행 가능)"
                elif blocked:
                    phase = "stopped"
                    text = self.live.status_text
                elif failed:
                    phase = "partial"
                    text = f"씬 모드 일부 완료 — 성공 {done} · 실패 {failed}"
                else:
                    phase = "completed"
                    text = f"씬 모드 완료 ✓ {done}/{len(jobs)}장 (output/씬/)"
                self.live.update(
                    status_text=text, completed=done, failed=failed, phase=phase,
                    can_retry=bool(failed or blocked or self.live.stop_req))
            finally:
                cfg.pop("_frag_counters", None)
                self.live.release(tok)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "count": len(jobs)}

    @serialized_setting_write
    def handle_role_save(self, body):
        """세팅의 상대역 저장 → 세팅 파일에 기록"""
        try:
            data = json.loads(body)
            path = setting_path(data.get("setting", ""))
            if not path:
                return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
            pack = load_json_recover(path)
            role = pack.setdefault("상대역", {})
            for k in ("외형", "착의", "네거티브", "의상"):
                if k in (data.get("role") or {}):
                    role[k] = data["role"][k]
            atomic_write_json(path, pack)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def handle_sceneset_save(self, body):
        try:
            data = json.loads(body)
            name = (data.get("name") or "").strip()
            if not name:
                return {"ok": False, "error": "프리셋 이름을 입력해주세요."}
            SCENESET_DIR.mkdir(exist_ok=True)
            preset = {k: self.cfg.get(k) for k in SCENESET_KEYS}
            atomic_write_json(SCENESET_DIR / f"{_safe_name(name)}.json", preset)
            return {"ok": True, "scene_presets": list_scene_presets()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @serialized_setting_write
    def handle_option_item(self, body):
        """세팅에 소속된 옵션의 항목 추가/삭제. {setting, option, op: set|del, name, value}"""
        try:
            data = json.loads(body)
            option = (data.get("option") or "").strip()
            name = (data.get("name") or "").strip()
            op = data.get("op")
            path = setting_path(data.get("setting", ""))
            if not path or not option or not name or op not in ("set", "del"):
                return {"ok": False, "error": "잘못된 요청입니다."}
            pack = load_json_recover(path)
            opts = pack.setdefault("옵션", {}).setdefault(option, {})
            if op == "del":
                opts.pop(name, None)
            else:
                opts[name] = data.get("value")
            atomic_write_json(path, pack)
            return {"ok": True, "snapshot": self.snapshot_config()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def handle_style_save(self, body):
        try:
            data = json.loads(body)
            name = (data.get("name") or "").strip()
            if not name:
                return {"ok": False, "error": "그림체 이름을 입력해주세요."}
            save_style_file(name, prompt=data.get("prompt", ""), groups=data.get("groups"),
                            settings=data.get("settings"), negative=data.get("negative", ""))
            return {"ok": True, "styles": list_styles(self.spec)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @serialized_data_write(lambda: BASE_DIR)
    def handle_compare_promote(self, body):
        """비교 결과의 서버 원문을 기존 그림체/캐릭터 자료 형식으로 명시적으로 저장."""
        try:
            data = json.loads(body or b"{}")
            with self.config_lock:
                self.use_latest_config()
                result = promote_comparison_recipe_assets(
                    self.cfg,
                    data.get("path"),
                    data.get("kind"),
                    name=data.get("name"),
                    spec=self.spec,
                )
                if result.get("changed_config"):
                    self.config_revision += 1
                result["revision"] = self.config_revision
                return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def handle_compare_preview(self, body):
        """자료 비교 생성의 실제 장수·비용 범위를 계산한다. 생성이나 저장은 하지 않는다."""
        try:
            data = json.loads(body or b"{}")
            opus = None
            if self.anlas_balance_cache is not None:
                opus = bool(self.anlas_balance_cache.get("opus"))
            return comparison_plan(self.cfg, data, self.spec, opus=opus)
        except Exception as e:
            return {"ok": False, "errors": [str(e)], "error": str(e)}

    def handle_compare_run(self, body):
        """그림체 전체·캐릭터 전체·직교 조합을 같은 조건으로 한 장씩 생성한다."""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        if not self.cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        try:
            data = json.loads(body or b"{}")
        except Exception as e:
            return {"ok": False, "error": f"잘못된 요청입니다: {e}"}
        opus = None
        if self.anlas_balance_cache is not None:
            opus = bool(self.anlas_balance_cache.get("opus"))
        plan = comparison_plan(self.cfg, data, self.spec, opus=opus)
        if not plan["ok"] or not plan["count"]:
            return {"ok": False, "error": " ".join(plan.get("errors") or [])
                    or "생성할 항목이 없습니다."}
        try:
            confirmed_count = int(data.get("confirmed_count"))
        except (TypeError, ValueError):
            confirmed_count = -1
        if not data.get("confirmed") or confirmed_count != plan["count"]:
            return {"ok": False, "error":
                    f"실행 직전 장수 확인이 필요합니다. 현재 계획은 {plan['count']:,}장입니다.",
                    "plan": plan}
        tok = self.live.try_claim("자료 비교 생성", "library")
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        # 실행 중 화면 편집이 앞 장과 뒤 장의 비교 조건을 바꾸지 않도록 시작 시점 사본을 쓴다.
        run_cfg = json.loads(json.dumps(self.cfg, ensure_ascii=False, default=str))
        styles, chars = comparison_sources(run_cfg, self.spec)

        def run():
            try:
                _run_comparison(self, run_cfg, plan, styles, chars)
            except Exception as e:
                log.error(f"자료 비교 생성 실패: {e}")
                log.error(traceback.format_exc())
                self.live.update(
                    status_text=f"자료 비교 생성 실패: {e}",
                    failed=max(1, self.live.failed), last_error=str(e),
                    can_retry=True, phase="failed")
            finally:
                self.live.release(tok)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "plan": plan}

    def handle_inspect(self, body, filename="", save_flag=""):
        """이미지에서 NAI 메타데이터를 뽑아 그림체 레코드로. (novelai.net/inspect 대체)
        X-Save: 1 이면 그림체 라이브러리에도 넣는다."""
        try:
            from urllib.parse import unquote
            name = Path(unquote(filename or "")).name or "붙여넣은 이미지"
            if not body:
                return {"ok": False, "error": "이미지가 비어 있습니다."}
            ct = "image/webp" if body[:4] == b"RIFF" else "image/png"
            m = extract_nai_metadata(body, ct)
            if m["metadata_status"] != "ok":
                return {"ok": False, "error":
                        "이 이미지에는 NAI 생성 정보가 없습니다. "
                        "(카톡·디스코드 등을 거치면 지워집니다 — 원본 파일을 넣어주세요)"}
            artists, rest = parse_artist_combo(m["base"])
            # 새 결과에는 우리가 ucPreset·qualityToggle 을 Comment JSON에 직접 기록한다.
            # 옛 NAI 파일처럼 값이 없을 때만 문구에서 역추적한다.
            params = dict(m["params"] or {})
            source_model = model_id_from_metadata(
                params.get("model"),
                self.cfg.get("model") or "nai-diffusion-4-5-full",
            )
            ucp, user_neg = split_uc_preset(m["negative"], source_model)
            if "uc_preset" not in params and ucp is not None:
                params["uc_preset"] = ucp
                params["uc_preset_guessed"] = True
            # 퀄리티 접미사도 UC 프리셋처럼 **떼고** 토글만 켠다.
            # 안 떼면 프롬프트 칸에 구워진 채 남아, 토글을 꺼도 접미사가 계속 전송된다
            # (외부 감사 nais_blue B-2 와 같은 계열 — 우리는 이중 추가는 가드가 막았지만
            #  '끄기가 안 듣는' 쪽이 남아 있었다. ai-review/외부감사/ 참고)
            base_txt, qt = restore_quality_prompt(m["base"], source_model, params)
            if "quality_toggle" not in params:
                params["quality_toggle"] = qt
                params["quality_toggle_guessed"] = True
            rec = {
                "id": f"file-{abs(hash(body[:4096])) % 10**10}",
                "title": Path(name).stem[:80], "source": "내 이미지",
                "tab": "", "posted_at": "", "recommend": None, "views": None, "url": "",
                "count": len(artists),
                "combo": ", ".join(f"{w:g}::artist:{n}::" if w is not None else f"artist:{n}"
                                   for w, n in artists),
                "artists": [n for _, n in artists],
                "weights": {n: (w if w is not None else 1.0) for w, n in artists},
                # ⚠ 프롬프트는 **자르지 않는다.** `rest` 는 `base` 에서 작가 태그를 뺀
                #   파생값이라 예전엔 1,200자에서 잘랐는데, 사용자 원본 자료를 말없이
                #   줄이는 셈이라 없앴다. 원본은 `base` 에 온전히 있고 크기 문제도 없다.
                "base": base_txt, "rest": ", ".join(rest),
                # 네거티브는 프리셋을 뗀 '사용자가 쓴 부분' 만 담는다
                "negative": user_neg if ucp is not None else m["negative"],
                "negative_full": m["negative"],
                "characters": m["characters"],
                # 지금 버전이 모르는 필드도 버리지 않는다. 생성 요청에는 보내지 않고
                # 원본 메타데이터 보존·후속 버전의 재해석에만 쓴다.
                "metadata_raw": m["raw"],
                "params": params, "images": [],
            }
            # 썸네일도 캐시에 넣어 목록에서 바로 보이게
            try:
                # local: 이름은 실제로 저장하는 WebP 바이트의 SHA-256이다.
                # 원본 PNG의 SHA-1으로 이름을 만들면 같은 내용 해시라는 자료팩 규칙과
                # 달라지고, 파일 무결성도 이름만으로 확인할 수 없다.
                thumb_io = io.BytesIO()
                with Image.open(io.BytesIO(body)) as im:
                    im = im.convert("RGB")
                    im.thumbnail((512, 512), Image.LANCZOS)
                    im.save(thumb_io, "WEBP", quality=74, method=4)
                thumb = thumb_io.getvalue()
                key = hashlib.sha256(thumb).hexdigest() + ".webp"
                out = IMG_CACHE / key
                if not out.exists():
                    _atomic_write_bytes(out, thumb, keep_backup=False)
                rec["images"] = [f"local:{key}"]
            except Exception as e:
                log.warning(f"추출 썸네일 실패: {e}")
            total = add_style(rec) if save_flag in ("1", "true") else None
            return {"ok": True, "style": rec, "saved": total}
        except Exception as e:
            log.warning(f"메타데이터 추출 실패: {traceback.format_exc()}")
            return {"ok": False, "error": str(e)}

    def handle_ref_add(self, body, kind, filename=""):
        """바이브/캐릭터 레퍼런스에 그림을 추가. 바이브는 바로 인코딩까지 한다."""
        try:
            from urllib.parse import unquote
            if not body:
                return {"ok": False, "error": "이미지가 비어 있습니다."}
            name = Path(unquote(filename or "")).stem[:40] or "레퍼런스"
            VIBE_DIR.mkdir(parents=True, exist_ok=True)
            rid = f"{kind}_{int(time.time()*1000) % 10**10}-{os.urandom(3).hex()}"
            im = Image.open(io.BytesIO(body))
            if kind == "vibe":
                with shared_data_transaction(VIBE_DIR.parent.parent):
                    with self.config_lock:
                        self.use_latest_config()
                        p, _ = vibe_paths(rid)
                        converted = im.convert("RGB")
                        _atomic_save_image(p, lambda tmp: converted.save(tmp, "PNG"))
                        item = {"id": rid, "name": name, "enabled": True,
                                "strength": 0.6, "info_extracted": 0.7,
                                "encoded_ie": None}
                        self.cfg.setdefault("vibes", []).append(item)
                        save_config(self.cfg)
                        self.config_revision += 1
                token = (self.cfg.get("token") or "").strip()
                if token:
                    # 최대 180초인 유료 인코딩 통신 중에는 다른 자료 저장을 막지 않는다.
                    # 파일명에 난수가 있어 다른 프로필의 신규 참조와도 충돌하지 않는다.
                    try:
                        prepare_vibes(self.cfg, token)
                        item["encoded"] = True
                    except Exception as e:
                        return {"ok": True, "item": item, "vibes": self.cfg["vibes"],
                                "warn": f"등록은 됐지만 인코딩 실패: {e}",
                                "revision": self.config_revision}
                return {"ok": True, "item": item, "vibes": self.cfg["vibes"],
                        "revision": self.config_revision}
            else:
                with shared_data_transaction(VIBE_DIR.parent.parent):
                    with self.config_lock:
                        self.use_latest_config()
                        p = VIBE_DIR / f"{rid}.ref.png"
                        converted = im.convert("RGB")
                        _atomic_save_image(p, lambda tmp: converted.save(tmp, "PNG"))
                        item = {"id": rid, "name": name, "enabled": True,
                                "ref_type": "character&style", "strength": 0.6,
                                "fidelity": 0.6}
                        self.cfg.setdefault("char_refs", []).append(item)
                        save_config(self.cfg)
                        self.config_revision += 1
                return {"ok": True, "item": item, "char_refs": self.cfg["char_refs"],
                        "revision": self.config_revision}
        except Exception as e:
            log.warning(f"레퍼런스 추가 실패: {traceback.format_exc()}")
            return {"ok": False, "error": str(e)}

    @serialized_data_write(lambda: VIBE_DIR.parent.parent)
    def handle_ref_save(self, body):
        """목록 갱신(강도·정보추출·켜기/끄기·삭제)."""
        try:
            d = json.loads(body or b"{}")
            revision = d.pop("_revision", None)
            base_values = d.pop("_base", {})
            if not isinstance(base_values, dict):
                base_values = {}
            with self.config_lock:
                if revision is not None:
                    try:
                        stale = int(revision) != self.config_revision
                    except (TypeError, ValueError):
                        stale = True
                    if stale:
                        return {"ok": False, "conflict": True,
                                "revision": self.config_revision,
                                "error": "다른 화면에서 참조 설정이 먼저 변경됐습니다. "
                                         "새로고침 후 다시 시도하세요."}
                merged = self.latest_config_from_disk()
                conflicts = [
                    key for key in ("vibes", "char_refs")
                    if key in d and key in base_values
                    and merged.get(key) != base_values.get(key)
                    and d.get(key) != merged.get(key)
                ]
                if conflicts:
                    self.cfg.clear()
                    self.cfg.update(merged)
                    self.config_revision += 1
                    return {"ok": False, "conflict": True,
                            "conflict_keys": conflicts,
                            "revision": self.config_revision,
                            "error": "다른 실행본이 같은 참조 목록을 먼저 변경했습니다. "
                                     "새로고침 후 다시 시도하세요."}
                self.cfg.clear()
                self.cfg.update(merged)
                for key in ("vibes", "char_refs"):
                    if key not in d:
                        continue
                    old = {x.get("id"): x for x in self.cfg.get(key, [])}
                    new = d[key]
                    # 사라진 항목의 파일 정리
                    for gone in set(old) - {x.get("id") for x in new}:
                        for p in (VIBE_DIR / f"{gone}.png", VIBE_DIR / f"{gone}.vibe",
                                  VIBE_DIR / f"{gone}.ref.png"):
                            if p.exists():
                                recoverable_remove(p)
                    # 정보추출이 바뀌면 캐시를 버려 다음 생성에서 다시 인코딩
                    for x in new:
                        o = old.get(x.get("id"))
                        if o and abs(float(x.get("info_extracted", 0.7))
                                     - float(o.get("info_extracted", 0.7))) > 1e-9:
                            x["encoded_ie"] = None
                    self.cfg[key] = new
                save_config(self.cfg)
                self.config_revision += 1
                return {"ok": True, "vibes": self.cfg.get("vibes", []),
                        "char_refs": self.cfg.get("char_refs", []),
                        "revision": self.config_revision}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def handle_director(self, body, tool, prompt="", defry="0", scale="4", filename=""):
        """디렉터 툴 실행 → 결과를 output/디렉터/ 에 저장하고 미리보기에 띄운다."""
        try:
            if not body:
                return {"ok": False, "error": "이미지가 비어 있습니다."}
            token = (self.cfg.get("token") or "").strip()
            if not token:
                return {"ok": False, "error": "시스템에서 NAI 토큰을 먼저 넣어주세요."}
            names = {t for t, _, _ in DIRECTOR_TOOLS} | {"upscale"}
            if tool not in names:
                return {"ok": False, "error": f"알 수 없는 도구: {tool}"}

            if tool == "upscale":
                out = call_upscale(token, body, int(scale or 4))
            else:
                needs = next(n for t, _, n in DIRECTOR_TOOLS if t == tool)
                out = call_director(token, body, tool,
                                    prompt=(prompt or "") if needs else None,
                                    defry=defry)

            img = Image.open(io.BytesIO(out))
            keep_alpha = tool == "bg-removal"        # 배경 제거는 투명도를 살려야 한다
            d = out_sub(self.cfg, "디렉터")
            d.mkdir(parents=True, exist_ok=True)
            stem = _safe_name(Path(filename or "결과").stem)[:40] or "결과"
            ext = "png" if keep_alpha else "webp"
            p = d / f"{stem}_{tool}.{ext}"
            i = 2
            while p.exists():
                p = d / f"{stem}_{tool}_{i}.{ext}"
                i += 1
            if keep_alpha:
                converted = img.convert("RGBA")
                _atomic_save_image(p, lambda tmp: converted.save(tmp, "PNG"))
            else:
                converted = img.convert("RGB")
                _atomic_save_image(
                    p, lambda tmp: converted.save(tmp, "WEBP", quality=95))
            self.live.set_image(img.convert("RGB"))
            self.live.update(filename=p.name, char_name=f"디렉터 · {tool}",
                             status_text="디렉터 툴 완료")
            log.info(f"디렉터 {tool} → {p.name} ({img.width}×{img.height})")
            return {"ok": True, "tool": tool, "file": p.name,
                    "path": str(p), "width": img.width, "height": img.height}
        except Exception as e:
            log.warning(f"디렉터 툴 실패: {traceback.format_exc()}")
            return {"ok": False, "error": str(e)}

    @serialized_data_write(lambda: CHAR_DIR.parent)
    def handle_norm_save(self, body):
        """규격화 도구 저장: type=char → 캐릭터 등록+파일, type=style → 그림체 파일"""
        try:
            data = json.loads(body)
            name = (data.get("name") or "").strip()
            groups = data.get("groups") or {}
            if not name:
                return {"ok": False, "error": "이름을 입력해주세요."}
            if data.get("type") == "style":
                order = [g["이름"] for g in self.spec.get("그림체_그룹", [])]
                prompt = _compose_ordered(groups, order)
                if not prompt:
                    return {"ok": False, "error": "내용이 비어 있습니다."}
                save_style_file(name, groups=groups)
                return {"ok": True, "styles": list_styles(self.spec)}
            order = [g["이름"] for g in self.spec.get("캐릭터_그룹", [])]
            female = _compose_ordered(groups, order)
            if not female:
                # 규격 그룹명과 다른 그룹(빌더 등) → 값을 순서대로 이어붙임
                female = ", ".join(v.strip().rstrip(",") for v in groups.values()
                                   if isinstance(v, str) and v.strip())
            if not female:
                return {"ok": False, "error": "내용이 비어 있습니다."}
            with self.config_lock:
                self.use_latest_config()
                new_char = {
                    "id": "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
                    "name": name, "female": female, "clothed": "",
                    "negative": data.get("negative", ""),
                    "groups": data.get("builder_groups") or groups, "enabled": True,
                    "folder_id": data.get("folder_id") or None,
                    "subfolder_id": data.get("subfolder_id") or None,
                }
                self.cfg.setdefault("characters", []).append(new_char)
                sync_chars_to_files(self.cfg)
                save_config(self.cfg)
                self.config_revision += 1
                return {"ok": True, "characters": self.cfg["characters"],
                        "revision": self.config_revision}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @serialized_data_write(lambda: CHAR_DIR.parent)
    def handle_save(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "error": "잘못된 데이터"}
        revision = data.pop("_revision", None)
        base_values = data.pop("_base", {})
        if not isinstance(base_values, dict):
            base_values = {}
        with self.config_lock:
            if revision is not None:
                try:
                    stale = int(revision) != self.config_revision
                except (TypeError, ValueError):
                    stale = True
                if stale:
                    return {"ok": False, "conflict": True, "revision": self.config_revision,
                            "error": "다른 화면에서 설정이 먼저 변경됐습니다. 새로고침 후 다시 시도하세요."}
            # 다른 프로세스는 각자 config_revision을 가지므로 파일 잠금만으로는 부족하다.
            # 잠금을 얻은 뒤 디스크 최신판을 다시 읽고, 이번 요청이 실제로 바꾼
            # top-level 키만 그 위에 적용한다. 같은 키가 시작값과 달라졌다면 조용히
            # 덮지 않고 충돌로 돌려준다.
            local_before = dict(self.cfg)
            merged = self.latest_config_from_disk()
            allowed = {k for k in DEFAULT_CONFIG if not k.startswith("_")}
            allowed |= {"booru_keys"}
            allowed -= {"male_prompt"}
            external_changes = sorted(
                key for key in allowed
                if key not in data and local_before.get(key) != merged.get(key)
            )
            conflicts = [
                key for key, incoming in data.items()
                if key in allowed and key in base_values
                and merged.get(key) != base_values.get(key)
                and incoming != merged.get(key)
            ]
            if conflicts:
                self.cfg.clear()
                self.cfg.update(merged)
                self.config_revision += 1
                return {
                    "ok": False, "conflict": True,
                    "conflict_keys": sorted(conflicts),
                    "revision": self.config_revision,
                    "error": "다른 실행본이 같은 설정을 먼저 변경했습니다. "
                             "새로고침 후 값을 확인하고 다시 시도하세요.",
                }
            self.cfg.clear()
            self.cfg.update(merged)
            old_ids = {c.get("id") for c in self.cfg.get("characters", [])}
            accepted, rejected, fixed_vals = [], [], {}
            for key, val in data.items():
                if key not in allowed:
                    if not key.startswith("_"):
                        rejected.append(key)
                    continue
                ok, used, fixes = validate_config_value(key, val, self.cfg.get(key))
                fixed_vals.update(fixes)
                if not ok:
                    rejected.append(key)
                    continue
                self.cfg[key] = used
                accepted.append(key)
            new_ids = {c.get("id") for c in self.cfg.get("characters", [])}
            sync_chars_to_files(self.cfg)
            # 새 설정과 남은 캐릭터 파일이 먼저 디스크에 확정된 뒤 삭제본을 목록 밖
            # 백업으로 옮긴다. 중간 종료 시 삭제가 취소될 수는 있어도 원문이 사라지지 않는다.
            save_config(self.cfg)
            delete_char_files(self.cfg, old_ids - new_ids)
            self.config_revision += 1
            if rejected:
                log.warning(f"설정 저장에서 잘못된 키/값을 거절함: {', '.join(sorted(rejected))}")
            if fixed_vals:
                log.info(f"설정값을 허용 범위로 맞췄습니다: {fixed_vals}")
            return {"ok": True, "accepted": accepted, "rejected": rejected,
                    "fixed": fixed_vals, "revision": self.config_revision,
                    "external_changes": external_changes}

    @serialized_setting_write
    def handle_scene_save(self, body):
        """씬 내부 프롬프트 수정 → asset_config.json 에 저장 (생성 중이면 다음 장부터 반영)"""
        try:
            data = json.loads(body)
            updates = data.get("updates") or {}
            # 씬 모드에 있는 것 중 세팅에서 못 고치던 것들도 열었다:
            #   negative(씬 전용 네거티브) · width/height(해상도)
            allowed = ("female_prompt", "male_prompt", "partner_prompt", "base_tags",
                       "negative", "width", "height")
            NUMS = ("width", "height")
            n = 0
            for p in (SETTINGS_DIR.glob("*.json") if SETTINGS_DIR.exists() else []):
                try:
                    pack = load_json_recover(p)
                except Exception:
                    continue
                scenes = pack.get("씬") or {}
                changed = False
                for sid, fields in updates.items():
                    sc = scenes.get(str(sid))
                    if not sc or not isinstance(fields, dict):
                        continue
                    for k in allowed:
                        if k in fields:
                            v = fields[k]
                            if k in NUMS:
                                try:
                                    v = normalize_resolution(v)
                                except (TypeError, ValueError, OverflowError):
                                    continue
                            sc[k] = v
                    changed = True
                    n += 1
                if changed:
                    atomic_write_json(p, pack)
            return {"ok": True, "updated": n}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def handle_start(self):
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        if not self.cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요 (pst-... 형식)."}
        has_slot = any(slot_prompt(s).strip() for s in self.cfg.get("char_slots", []))
        has_cast = any(strip_comment_lines(c.get("prompt") or "").strip()
                       for st in (self.cfg.get("setting_state") or {}).values()
                       for c in st.get("cast", []))
        if not (has_slot or has_cast):
            return {"ok": False, "error": "설정의 캐릭터 칸 또는 세팅의 캐스트에 인물을 1명 이상 넣어주세요."}
        if not any((st.get("use") is not False and st.get("selected"))
                   for st in (self.cfg.get("setting_state") or {}).values()):
            return {"ok": False, "error": "세팅 탭에서 씬을 1개 이상 선택해주세요."}
        self.start_event.set()
        return {"ok": True}

    def start(self, open_browser=True):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, obj, status=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _trusted_post(self):
                """브라우저의 다른 사이트가 127.0.0.1 API를 대신 누르지 못하게 한다."""
                from urllib.parse import urlparse
                allowed = {"127.0.0.1", "localhost", "::1"}
                try:
                    host = urlparse("http://" + (self.headers.get("Host") or ""))
                    if host.hostname not in allowed or host.port != self.server.server_port:
                        return False
                    origin = self.headers.get("Origin")
                    if origin:
                        src = urlparse(origin)
                        if (src.scheme != "http" or src.hostname not in allowed
                                or src.port != self.server.server_port):
                            return False
                    fetch_site = (self.headers.get("Sec-Fetch-Site") or "").lower()
                    if fetch_site and fetch_site != "same-origin":
                        return False
                    return True
                except (TypeError, ValueError):
                    return False

            def do_GET(self):
                if self.path == "/ui/studio.css":
                    # 프로그램 UI 자산만 고정 경로로 제공한다. 사용자 경로를 받지 않아
                    # 정적 파일 제공 때문에 경로 탈출 표면이 늘어나지 않는다.
                    f = UI_DIR / "studio.css"
                    if not f.is_file():
                        self.send_response(404); self.end_headers(); return
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/css; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith("/api/config"):
                    self._json(server.snapshot_config())
                elif self.path.startswith("/api/trash"):
                    try:
                        self._json(list_trash_batches(server.cfg))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/refimg"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    rid = Path(q.get("id", [""])[0]).name        # 경로 탈출 차단
                    kind = q.get("kind", ["vibe"])[0]
                    f = VIBE_DIR / (f"{rid}.ref.png" if kind == "cref" else f"{rid}.png")
                    if not (rid and f.exists() and f.is_file()):
                        self.send_response(404); self.end_headers(); return
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "max-age=3600")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith("/setout"):
                    # 세트 대표 썸네일 — output/ 아래만, 경로 탈출·휴지통 접근 차단
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    rel = unquote(q.get("p", [""])[0])
                    f = output_file_for_preview(server.cfg, rel)
                    if f is None:
                        self.send_response(404); self.end_headers(); return
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", MIME.get(f.suffix.lower(), "image/webp"))
                    self.send_header("Cache-Control", "max-age=60")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith("/api/out_list"):
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        self._json(list_output(
                            unquote(q.get("dir", [""])[0]), server.cfg,
                            limit=int(q.get("limit", ["0"])[0]),
                            offset=int(q.get("offset", ["0"])[0]),
                            only_pick=q.get("only_pick", [""])[0] in ("1", "true"),
                            only_fav=q.get("only_fav", [""])[0] in ("1", "true")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/setting_thumbs"):
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        self._json({"ok": True,
                                    "thumbs": setting_thumbs(unquote(q.get("name", [""])[0]), server.cfg)})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/backup_export"):
                    try:
                        blob = export_user_backup(server.cfg)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)}); return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition",
                                     'attachment; filename="nais-user-backup.zip"')
                    self.send_header("Content-Length", str(len(blob)))
                    self.end_headers()
                    self.wfile.write(blob)
                elif self.path.startswith("/api/frag_export"):
                    try:
                        blob = export_fragments_zip()
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)}); return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", 'attachment; filename="fragments.zip"')
                    self.send_header("Content-Length", str(len(blob)))
                    self.end_headers()
                    self.wfile.write(blob)
                elif self.path.startswith("/api/setting_export"):
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    names = [n for n in (unquote(x) for x in q.get("name", [])) if n]
                    try:
                        blob = export_settings_zip(names or None)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)}); return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition",
                                     'attachment; filename="settings.zip"')
                    self.send_header("Content-Length", str(len(blob)))
                    self.end_headers()
                    self.wfile.write(blob)
                elif self.path.startswith("/img"):
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    data, ctype = fetch_cached_image(unquote(q.get("u", [""])[0]))
                    if not data:
                        self.send_response(404); self.end_headers(); return
                    self.send_response(200)
                    self.send_header("Content-Type", ctype or "image/webp")
                    self.send_header("Cache-Control", "max-age=86400")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith("/api/booru"):
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    res = search_booru(q.get("site", ["danbooru"])[0],
                                       unquote(q.get("q", [""])[0]),
                                       int(q.get("page", ["1"])[0]),
                                       int(q.get("limit", ["40"])[0]))
                    # 부루 썸네일은 브라우저가 직접 받는다 (Cloudflare 때문에
                    # 서버에서 미리 받아 두면 전부 403 이 되어 헛일이다).
                    self._json(res)
                elif self.path.startswith("/api/style_dupes"):
                    # 출처가 다른 자료를 합치면 같은 조합이 여러 번 들어온다 (id 가 달라
                    # 자동 병합이 못 잡는다). 묶어서 보여 주고 고르게 한다.
                    try:
                        self._json(find_style_dupes())
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/pack_log"):
                    try:
                        self._json({"ok": True, "log": pack_log_brief()})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/data_storage"):
                    try:
                        self._json(data_storage_status())
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/img_origins"):
                    # 원격 캐시는 **주소 해시**로 파일을 만든다. 주소가 달라도 같은 그림이면
                    # 두 벌이 남는데, 내려받을 때 적어 둔 **내용 해시**로 그걸 찾아낸다.
                    try:
                        self._json(image_origin_stats())
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/local_image_integrity"):
                    try:
                        self._json(local_image_integrity())
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/compare_runs"):
                    try:
                        self._json(comparison_runs(server.cfg))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/compare_progress"):
                    try:
                        self._json(comparison_progress_summary(server.cfg))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/combos"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        res = search_combos(
                            q.get("q", [""])[0], int(q.get("limit", ["40"])[0]),
                            int(q.get("offset", ["0"])[0]),
                            tab=q.get("tab", [""])[0], source=q.get("source", [""])[0],
                            sort=q.get("sort", [""])[0], seeded=q.get("seeded", [""])[0],
                            rating=q.get("rating", [""])[0])
                        # 카드의 <img loading="lazy">가 보이는 것만 요청한다.
                        # 여기서 결과 50~200장을 모두 선다운로드하면 브라우저 요청과
                        # 겹쳐 네트워크·디스크·WebP 디코딩이 몰리고 모달이 멈춘다.
                        self._json({"ok": True, **res})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/recipes"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        res = search_recipes(
                            q.get("q", [""])[0], q.get("axis", [""])[0],
                            int(q.get("limit", ["60"])[0]), int(q.get("offset", ["0"])[0]))
                        prewarm_images(res.get("items"), n=60)
                        self._json({"ok": True, **res})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/diag"):
                    # 진단 — raw 로그는 절대 내보내지 않고 redacted 구조화 이벤트만 돌려준다.
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        n = max(10, min(2000, int(q.get("n", ["300"])[0])))
                    except (TypeError, ValueError):
                        n = 300
                    err_only = q.get("err", [""])[0] in ("1", "true")
                    try:
                        if not LOG_FILE.exists():
                            self._json({
                                "ok": True, "schema": "nais-diagnostics/v1",
                                "lines": [], "events": [], "errors": 0,
                            }); return
                        raw = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
                        events = parse_diagnostic_lines(raw)
                        errs = sum(
                            1 for event in events
                            if event["level"] in ("WARNING", "ERROR", "CRITICAL")
                        )
                        if err_only:
                            events = [
                                event for event in events
                                if event["level"] in ("WARNING", "ERROR", "CRITICAL")
                            ]
                        events = events[-n:]
                        self._json({
                            "ok": True,
                            "schema": "nais-diagnostics/v1",
                            "lines": [diagnostic_event_line(event) for event in events],
                            "events": events,
                            "errors": errs,
                        })
                    except Exception as e:
                        self._json({
                            "ok": False,
                            "error": redact_diagnostic_text(e),
                        })
                elif self.path.startswith("/api/ac"):
                    from urllib.parse import urlparse, parse_qs, unquote
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        self._json({"ok": True, "items": autocomplete_tags(
                            server.spec, unquote(q.get("q", [""])[0]),
                            int(q.get("limit", ["12"])[0]))})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/tags"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        res = search_tags(server.spec,
                                          (q.get("kind", ["char"])[0]),
                                          (q.get("slot", [""])[0]),
                                          (q.get("q", [""])[0]),
                                          int(q.get("limit", ["60"])[0]))
                        self._json({"ok": True, "tags": res})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/scenes"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    ids = [x for x in (q.get("ids", [""])[0]).split(",") if x.strip().isdigit()]
                    try:
                        ac = load_asset_config(server.cfg)
                        out = []
                        for i in ids:
                            sc = ac["scenes"].get(i)
                            if sc:
                                out.append({"id": int(i), "name": sc.get("name", ""),
                                            "female_prompt": sc.get("female_prompt", ""),
                                            "male_prompt": sc.get("male_prompt", ""),
                                            "partner_prompt": sc.get("partner_prompt", ""),
                                            "base_tags": sc.get("base_tags", ""),
                                            "pair": sc.get("pair", "")})
                        self._json({"ok": True, "scenes": out})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/status.json"):
                    self._json(server.live.snapshot())
                elif self.path.startswith("/latest.webp"):
                    data = server.live.image()
                    if data is None:
                        self.send_response(404); self.end_headers(); return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/webp")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path == "/" or self.path.startswith("/?"):
                    body = render_page().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404); self.end_headers()

            def do_POST(self):
                if not self._trusted_post():
                    self._json({"ok": False, "error": "허용되지 않은 요청 출처입니다."}, status=403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    self._json({"ok": False, "error": "잘못된 Content-Length입니다."}, status=400)
                    return
                # 이미지 업로드를 허용하되 무제한 메모리 할당은 막는다.
                if length < 0 or length > 128 * 1024 * 1024:
                    self._json({"ok": False, "error": "요청 본문이 너무 큽니다."}, status=413)
                    return
                body = self.rfile.read(length) if length else b""
                if self.path.startswith("/api/backup_preview"):
                    try:
                        self._json(preview_user_backup(body))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/backup_restore"):
                    try:
                        result = restore_user_backup(
                            body, self.headers.get("X-Backup-SHA256", ""))
                        if result.get("ok"):
                            fresh = load_json_recover(SETTINGS_FILE)
                            merged = dict(DEFAULT_CONFIG)
                            merged.update(fresh if isinstance(fresh, dict) else {})
                            migrate_legacy_selections(merged)
                            migrate_char_slots(merged)
                            server.cfg.clear()
                            server.cfg.update(merged)
                            server.spec = load_spec()
                            OPTIONS.clear()
                            OPTIONS.update(load_options())
                            server.config_revision += 1
                        self._json(result)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/backup_rollback"):
                    try:
                        data = json.loads(body or b"{}")
                        result = rollback_user_backup(data.get("id"))
                        if result.get("ok"):
                            fresh = load_json_recover(SETTINGS_FILE)
                            merged = dict(DEFAULT_CONFIG)
                            merged.update(fresh if isinstance(fresh, dict) else {})
                            migrate_legacy_selections(merged)
                            migrate_char_slots(merged)
                            server.cfg.clear()
                            server.cfg.update(merged)
                            server.spec = load_spec()
                            OPTIONS.clear()
                            OPTIONS.update(load_options())
                            server.config_revision += 1
                        self._json(result)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/local_image_normalize"):
                    try:
                        data = json.loads(body or b"{}")
                        self._json(normalize_local_image_refs(
                            data.get("fingerprint", "")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/local_image_rollback"):
                    try:
                        data = json.loads(body or b"{}")
                        self._json(rollback_local_image_normalize(
                            data.get("id", "")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/data_index_rebuild"):
                    try:
                        index = rebuild_data_index()
                        self._json({
                            "ok": True,
                            "files": index["files"],
                            "bytes": index["bytes"],
                            "fingerprint": index["fingerprint"],
                        })
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/save"):
                    self._json(server.handle_save(body))
                elif self.path.startswith("/api/compare_activate"):
                    try:
                        data = json.loads(body or b"{}")
                        self._json(activate_comparison_run(
                            server.cfg, data.get("folder")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/compare_recipe"):
                    try:
                        data = json.loads(body or b"{}")
                        self._json(comparison_recipe_for_output(
                            server.cfg, data.get("path")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/compare_promote"):
                    self._json(server.handle_compare_promote(body))
                elif self.path.startswith("/api/compare_preview"):
                    self._json(server.handle_compare_preview(body))
                elif self.path.startswith("/api/compare_run"):
                    self._json(server.handle_compare_run(body))
                elif self.path.startswith("/api/start"):
                    self._json(server.handle_start())
                elif self.path.startswith("/api/style_save"):
                    self._json(server.handle_style_save(body))
                elif self.path.startswith("/api/norm_save"):
                    self._json(server.handle_norm_save(body))
                elif self.path.startswith("/api/verify_tags"):
                    try:
                        d = json.loads(body) if body else {}
                        self._json(verify_tags(d.get("text") or ""))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/scene_save"):
                    self._json(server.handle_scene_save(body))
                elif self.path.startswith("/api/option_item"):
                    self._json(server.handle_option_item(body))
                elif self.path.startswith("/api/role_save"):
                    self._json(server.handle_role_save(body))
                elif self.path.startswith("/api/generate_one"):
                    self._json(server.handle_generate_one())
                elif self.path.startswith("/api/sceneset_save"):
                    self._json(server.handle_sceneset_save(body))
                elif self.path.startswith("/api/scene_preview"):
                    # 씬 번호 → NAI 로 실제 나갈 값을 그대로 조립해서 보여준다.
                    # 565장 돌리기 전에 옵션 조합 실수를 여기서 잡는다.
                    try:
                        d = json.loads(body or b"{}")
                        num = int(d.get("num"))
                        cfg = server.cfg
                        acfg = load_asset_config(cfg)
                        scene = acfg["scenes"].get(str(num))
                        if not scene:
                            self._json({"ok": False, "error": f"{num}번 씬이 없습니다."}); return
                        cast = None
                        for c in (setting_state(cfg, scene.get("_setting", "")).get("cast") or []):
                            if strip_comment_lines(c.get("prompt") or "").strip():
                                cast = {"name": c.get("name") or "전용 캐스트",
                                        "female": c.get("prompt"), "negative": c.get("negative", "")}
                                break
                        if cast is None:
                            slots = [s for s in (cfg.get("char_slots") or [])
                                     if slot_prompt(s).strip()]
                            cast = ({"name": slots[0].get("name") or "캐릭터 1",
                                     "female": slot_prompt(slots[0]),
                                     "negative": slots[0].get("negative", "")}
                                    if slots else {"name": "(캐릭터 없음)", "female": "", "negative": ""})
                        base, fem, male, cneg, mneg, w, h = build_scene(acfg, cast, cfg, num)
                        seed = seed_for(cfg, load_state()["seeds"].get(
                            f"{int(cfg.get('seed', 1) or 1):02d}", 0), num)
                        self._json({"ok": True, "num": num, "name": scene.get("name", ""),
                                    "setting": scene.get("_setting", ""),
                                    "mode": scene.get("_mode", ""),
                                    "cast": cast["name"],
                                    "base": normalize_prompt(base),
                                    "female": normalize_prompt(fem),
                                    "male": normalize_prompt(male),
                                    # 미리보기도 씬 전용 네거티브를 합쳐 보여준다
                                    # (안 그러면 실제 전송값과 어긋난다)
                                    "negative": normalize_prompt(_join_tags(
                                        acfg["base"].get("nsfw_negative_prompt",
                                                         acfg["base"]["negative_prompt"]),
                                        (scene.get("negative") or "").strip())),
                                    "char_negative": normalize_prompt(cneg),
                                    "male_negative": normalize_prompt(mneg),
                                    "width": w, "height": h, "seed": seed,
                                    "tokens": {"base": nai_tokens(base),
                                               "female": nai_tokens(fem),
                                               "male": nai_tokens(male)}})
                    except Exception as e:
                        log.warning(f"씬 미리보기 실패: {traceback.format_exc()}")
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/anlas"):
                    try:
                        d = json.loads(body or b"{}")
                        token = str(server.cfg.get("token") or "")
                        token_key = hashlib.sha256(token.encode("utf-8")).hexdigest() \
                            if token else None
                        with server.config_lock:
                            if token_key != server.anlas_balance_token_key:
                                server.anlas_balance_cache = None
                                server.anlas_balance_token_key = token_key
                        fresh_balance = fetch_anlas_balance(token) \
                            if d.get("balance") else None
                        with server.config_lock:
                            # 조회 중 사용자가 토큰을 바꿨다면 이전 계정 응답을 캐시하지 않는다.
                            if (fresh_balance
                                    and token_key == server.anlas_balance_token_key):
                                server.anlas_balance_cache = fresh_balance
                            known_balance = (server.anlas_balance_cache
                                             if token_key == server.anlas_balance_token_key
                                             else None)
                        opus = bool(known_balance and known_balance.get("opus"))
                        cfg = server.cfg
                        # 켜진 캐릭터 레퍼런스 수 — Opus 무료 생성은 유지되고 장당 +5만 별도 과금
                        refs = sum(1 for r in cfg.get("char_refs", []) if r.get("enabled"))
                        # 아직 인코딩 안 된 바이브 — 처음 한 번만 2 Anlas
                        vibe_new = 0
                        for v in cfg.get("vibes", []):
                            if not v.get("enabled"):
                                continue
                            _, ep = vibe_paths(v.get("id", ""))
                            ie = float(v.get("info_extracted", 0.7))
                            if (not ep.exists()) or abs(float(
                                    v.get("encoded_ie", -1) or -1) - ie) > 1e-9:
                                vibe_new += 1
                        if d.get("batch"):
                            # 일괄 생성은 씬마다 해상도가 달라서 씬별로 더해야 정확하다
                            # (예: 체위 세팅은 1024²·832×1216·1216×832 이 섞여 있다)
                            acfg = load_asset_config(cfg)
                            pend = compute_pending(cfg, acfg, {}, set())
                            total = 0
                            eligible_all = True
                            generation_free_all = True
                            for _, _, num, _ in pend:
                                sc = acfg["scenes"].get(str(num)) or {}
                                e1 = anlas_estimate(cfg, 1, sc.get("width"), sc.get("height"),
                                                    opus=opus, char_refs=refs)
                                total += e1["total"]
                                eligible_all = eligible_all and e1["free_eligible"]
                                generation_free_all = (
                                    generation_free_all and e1["generation_free"])
                            total += 2 * vibe_new        # 바이브 첫 인코딩 (한 번만)
                            if total == 0:
                                batch_why = "Opus 무료 (모든 씬이 1024² 이하 · 28스텝 이하)"
                            elif eligible_all:
                                parts = []
                                if known_balance is None:
                                    parts.append("무료 크기·스텝 범위 · Opus 등급 미확인")
                                elif not opus:
                                    parts.append("무료 크기·스텝 범위 · 비Opus 등급")
                                else:
                                    parts.append("Opus 무료 생성")
                                if refs:
                                    parts.append(
                                        f"캐릭터 레퍼런스 {refs}개 장당 {5*refs} Anlas")
                                if vibe_new:
                                    parts.append(
                                        f"새 바이브 {vibe_new}개 인코딩 {2*vibe_new} Anlas")
                                batch_why = " + ".join(parts)
                            else:
                                batch_why = (
                                    f"{cfg.get('steps')}스텝 / 일부 씬 해상도가 무료 조건"
                                    f"(1024² 이하·28스텝 이하)을 넘습니다")
                            est = {"per_image": None, "total": total, "count": len(pend),
                                   "free": total == 0,
                                   "free_eligible": eligible_all,
                                   "generation_free": generation_free_all,
                                   "batch": True,
                                   "width": None, "height": None,
                                   "steps": int(cfg.get("steps", 28)),
                                   "vibe_encode": 2 * vibe_new, "char_refs": refs,
                                   "why": batch_why}
                        else:
                            # mode 를 받아 img2img·인페인트면 Opus 무료를 빼고 센다 (CQA-008)
                            est = anlas_estimate(cfg, int(d.get("count") or 1),
                                                 width=d.get("width"), height=d.get("height"),
                                                 opus=opus, char_refs=refs,
                                                 mode=(d.get("mode") or "t2i"),
                                                 strength=float(d.get("strength") or 1.0))
                            est["total"] += 2 * vibe_new
                            est["vibe_encode"] = 2 * vibe_new
                        est["subscription_known"] = known_balance is not None
                        est["opus"] = (bool(known_balance.get("opus"))
                                       if known_balance is not None else None)
                        self._json({
                            "ok": True,
                            "est": est,
                            # 잔액 숫자는 사용자가 조회 버튼을 눌렀을 때만 보낸다.
                            "balance": fresh_balance if d.get("balance") else None,
                        })
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/stop"):
                    # 중지 — 취소 **플래그**만 세운다 (CQA-001: running 을 직접 끄면
                    # 옛 작업이 마저 도는 동안 새 작업이 실행권을 얻어 겹친다).
                    self._json({"ok": server.live.request_stop()})
                elif self.path.startswith("/api/rate"):
                    # 작가 평가 — 별점·즐겨찾기·차단·메모 (rater 의 ratings 를 우리 구조로)
                    try:
                        if len(body or b"") > 64 * 1024:      # 입력 상한 (R4-01)
                            self._json({"ok": False, "error": "요청이 너무 큽니다."}); return
                        d = json.loads(body or b"{}")
                        if not isinstance(d, dict):
                            self._json({"ok": False, "error": "잘못된 형식"}); return
                        if not d.get("list") and len(str(d.get("artist", ""))) > 200:
                            self._json({"ok": False, "error": "작가 이름이 너무 깁니다."}); return
                        if d.get("list"):
                            self._json({"ok": True, "ratings": load_ratings()})
                        else:
                            cur = rate_artist(d.get("artist", ""),
                                              **{k: d[k] for k in ("score", "fav", "block", "memo")
                                                 if k in d})
                            self._json({"ok": True, "artist": (d.get("artist") or "").lower(),
                                        "rating": cur})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/tokens"):
                    try:
                        d = json.loads(body or b"{}")
                        if d.get("finalize"):
                            final = finalized_token_texts(
                                d.get("base", ""), d.get("negative", ""),
                                d.get("chars") or [], d.get("char_negatives") or [],
                                server.cfg)
                        else:
                            final = {
                                "base": d.get("base", ""),
                                "negative": d.get("negative", ""),
                                "chars": d.get("chars") or [],
                                "char_negatives": d.get("char_negatives") or [],
                            }
                        base = nai_tokens(final["base"])
                        chars = [nai_tokens(c) for c in final["chars"]]
                        neg = nai_tokens(final["negative"])
                        cnegs = [nai_tokens(c) for c in final["char_negatives"]]
                        self._json({"ok": True, "exact": tokens_exact(), "base": base,
                                    "negative": neg,
                                    "chars": chars, "char_negatives": cnegs,
                                    "shared": base + sum(chars),
                                    "shared_negative": neg + sum(cnegs), "limit": 512,
                                    "finalized": bool(d.get("finalize"))})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/picks_save"):
                    try:
                        d = json.loads(body or b"{}")
                        # load→merge→save 전체가 한 transaction이어야 다른 탭의 선별을 덮지 않는다.
                        with _JSON_IO_LOCK:
                            cur = load_picks()
                            for k in (
                                "picked", "fav", "folders", "ranks",
                                "ratings", "tags",
                            ):
                                if k in d:
                                    cur[k] = d[k]
                            saved = save_picks(cur)
                        self._json({"ok": True, "picks": saved})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/picks_del"):
                    # 선별 안 된 것 지우기 — 즉시 삭제하지 않고 출력 폴더 휴지통으로 옮긴다.
                    try:
                        d = json.loads(body or b"{}")
                        keep = set(d.get("keep") or [])
                        targets = [str(x) for x in (d.get("targets") or [])
                                   if str(x) not in keep]
                        result = trash_output_files(server.cfg, targets, keep)
                        if result["deleted"]:
                            # 파일이 이미 없어졌거나 경로 검사를 통과하지 못한 요청은 이름표를
                            # 유지한다. 실제 휴지통으로 옮긴 경로만 선별 기록에서 뺀다.
                            gone = set(result.get("paths") or [])
                            with _JSON_IO_LOCK:
                                picks = load_picks()
                                picks["picked"] = [
                                    x for x in picks.get("picked", []) if x not in gone]
                                picks["fav"] = [
                                    x for x in picks.get("fav", []) if x not in gone]
                                picks["ranks"] = {
                                    k: v for k, v in picks.get("ranks", {}).items()
                                    if k not in gone}
                                picks["ratings"] = {
                                    k: v for k, v in picks.get("ratings", {}).items()
                                    if k not in gone}
                                picks["tags"] = {
                                    k: v for k, v in picks.get("tags", {}).items()
                                    if k not in gone}
                                picks["folders"] = {
                                    name: [x for x in paths if x not in gone]
                                    for name, paths in picks.get("folders", {}).items()}
                                save_picks(picks)
                        self._json({"ok": True, **result})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/picks_restore"):
                    try:
                        d = json.loads(body or b"{}")
                        result = restore_trash_batch(server.cfg, d.get("batch_id"))
                        self._json({"ok": True, **result})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/mosaic_save"):
                    # 모자이크는 브라우저에서 이미 칠해 왔다. 우리는 저장만 한다.
                    try:
                        d = out_sub(server.cfg, "모자이크")
                        d.mkdir(parents=True, exist_ok=True)
                        n = len(list(d.glob("*.png"))) + 1
                        f = d / f"{n:04d}.png"
                        _atomic_write_bytes(f, body, keep_backup=False)
                        self._json({"ok": True, "file": f.name, "bytes": len(body)})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/strip_meta"):
                    from urllib.parse import unquote
                    try:
                        self._json(strip_and_save(
                            body, unquote(self.headers.get("X-Filename", "image.png")),
                            max_side=int(self.headers.get("X-MaxSide", "0") or 0),
                            quality=int(self.headers.get("X-Quality", "95") or 95),
                            force_webp=self.headers.get("X-ForceWebp") == "1",
                            cfg=server.cfg))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/scenes_save"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json({"ok": True, "scenes": save_scenes(d.get("scenes") or [])})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/i2i"):
                    self._json(server.handle_i2i(body))
                elif self.path.startswith("/api/regen"):
                    self._json(server.handle_regen(body))
                elif self.path.startswith("/api/scenes_run"):
                    self._json(server.handle_scene_run())
                elif self.path.startswith("/api/frag_save"):
                    try:
                        d = json.loads(body or b"{}")
                        old = (d.get("old") or "").strip()
                        name = save_fragment(d.get("name", ""), d.get("lines") or [])
                        if old and old != name:
                            old_path = FRAG_DIR / f"{old}.txt"
                            if old_path.exists():
                                recoverable_remove(old_path, label="이름변경")
                        self._json({"ok": True, "name": name,
                                    "fragments": list_fragments()})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/frag_del"):
                    try:
                        d = json.loads(body or b"{}")
                        path = FRAG_DIR / f"{Path(d.get('name','')).name}.txt"
                        if path.exists():
                            recoverable_remove(path)
                        self._json({"ok": True, "fragments": list_fragments()})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/frag_reset"):
                    # 순차(<*이름>) 순번을 0 으로
                    try:
                        st = load_state()
                        st["frag_seq"] = {}
                        save_state(st)
                        server.cfg["_frag_counters"] = st["frag_seq"]
                        self._json({"ok": True})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/frag_import"):
                    from urllib.parse import unquote
                    try:
                        self._json(import_fragments_bytes(
                            body, unquote(self.headers.get("X-Filename", ""))))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/frag_try"):
                    # 미리보기 — 실제 순번은 건드리지 않는다
                    try:
                        d = json.loads(body or b"{}")
                        outs, _ = resolve_fragments([d.get("text", "")],
                                                    counters=dict(load_state().get("frag_seq", {})))
                        self._json({"ok": True, "text": outs[0]})
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/sb_new"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json(new_setting(d.get("name", ""), d.get("mode", "단독"),
                                               d.get("stages")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/sb_addset"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json(setting_add_set(
                            d.get("name", ""), d.get("label", ""), d.get("category", ""),
                            int(d.get("width") or 832), int(d.get("height") or 1216),
                            d.get("stages")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/sb_meta"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json(setting_meta_save(d.get("name", ""), d.get("patch") or {}))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/sb_renumber"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json(setting_renumber(d.get("name", ""), d.get("start")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/sb_del"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json(setting_delete(d.get("name", "")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/setting_import"):
                    from urllib.parse import unquote
                    try:
                        r = import_settings_bytes(
                            body, unquote(self.headers.get("X-Filename", "")))
                        # 세팅은 list_settings() 가 매번 파일을 다시 읽으므로
                        # 따로 되불러올 것이 없다. 화면만 새로 그리면 된다.
                        self._json(r)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/pack_import"):
                    # 자료팩(수집물)은 배포본에 넣지 않는다. 따로 받아 여기서 합친다.
                    from urllib.parse import unquote
                    try:
                        r = import_datapack_bytes(
                            body, unquote(self.headers.get("X-Filename", "")),
                            overwrite="overwrite=1" in self.path)
                        if r.get("ok"):
                            # 그림체·레시피·태그색인은 한 번 읽고 메모리에 두므로
                            # 깃발을 내려 줘야 새로 들어온 자료가 화면에 나온다.
                            forget_collection_caches()
                            # 기본 자료팩에는 규격·옵션도 있다. 서버를 껐다 켜지 않아도
                            # 가져오기 직후 빌더와 새 세팅에 반영되게 메모리 사본도 갱신한다.
                            self.spec = load_spec()
                            OPTIONS.clear()
                            OPTIONS.update(load_options())
                        self._json(r)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/pack_undo"):
                    # 넣고 나서 아니다 싶으면 통째로 물린다 (그때 들어온 것만).
                    try:
                        d = json.loads(body or b"{}")
                        r = undo_datapack(d.get("id"))
                        if r.get("ok"):
                            self.spec = load_spec()
                            OPTIONS.clear()
                            OPTIONS.update(load_options())
                        self._json(r)
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/style_del"):
                    # 몇천 건을 넣고 나면 지울 수 있어야 정리가 된다.
                    try:
                        d = json.loads(body or b"{}")
                        self._json(delete_styles(d.get("ids")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/style_restore"):
                    try:
                        d = json.loads(body or b"{}")
                        self._json(restore_styles(d.get("ids")))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                # ⚠ style_dupes · pack_log 는 **읽기라 GET 분기**에 있다.
                #    여기(POST)에 두면 화면의 fetch(기본 GET)가 빈 응답을 받는다.
                elif self.path.startswith("/api/setting_dup"):
                    try:
                        d = json.loads(body or b"{}")
                        # 씬 번호가 없거나 숫자가 아니면 파이썬 오류 대신 사람 말로 (세팅 빌더 점검)
                        try:
                            sid = int(d.get("id"))
                        except (TypeError, ValueError):
                            self._json({"ok": False, "error": "복제할 세트의 씬 번호(id)가 필요합니다."})
                            return
                        self._json(duplicate_setting_group(d.get("name", ""), sid))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e)})
                elif self.path.startswith("/api/ref_add"):
                    from urllib.parse import unquote
                    self._json(server.handle_ref_add(
                        body, self.headers.get("X-Kind", "vibe"),
                        self.headers.get("X-Filename", "")))
                elif self.path.startswith("/api/ref_save"):
                    self._json(server.handle_ref_save(body))
                elif self.path.startswith("/api/director"):
                    # 이미지 원본을 그대로 POST 받고, 옵션은 헤더로
                    from urllib.parse import unquote
                    self._json(server.handle_director(
                        body, self.headers.get("X-Tool", ""),
                        unquote(self.headers.get("X-Prompt", "") or ""),
                        self.headers.get("X-Defry", "0"),
                        self.headers.get("X-Scale", "4"),
                        unquote(self.headers.get("X-Filename", "") or "")))
                elif self.path.startswith("/api/inspect"):
                    self._json(server.handle_inspect(
                        body, self.headers.get("X-Filename", ""),
                        self.headers.get("X-Save", "")))
                else:
                    self.send_response(404); self.end_headers()

        # ⚠ 윈도우에서는 `allow_reuse_address`(HTTPServer 기본 켬) 때문에
        #   **이미 듣고 있는 포트에도 두 번째 바인딩이 성공한다.** 그러면 두 인스턴스가
        #   같은 포트를 잡은 셈이 되어 뒤에 뜬 쪽이 응답을 못 한다.
        #   프로필을 나눠 계정 2개를 나란히 돌리려면 이걸 꼭 꺼야 한다.
        class ExclusiveServer(ThreadingHTTPServer):
            allow_reuse_address = False

        for port in PREVIEW_PORT_RANGE:
            try:
                self.httpd = ExclusiveServer(("127.0.0.1", port), Handler)
            except OSError:
                continue
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
            self.url = f"http://127.0.0.1:{port}/"
            log.info(f"🖼  설정 / 실시간 미리보기: {self.url}")
            if open_browser:
                try:
                    webbrowser.open(self.url)
                except Exception:
                    pass
            return self.url
        log.error("서버용 포트를 찾지 못했습니다 (8787~8796 모두 사용 중).")
        return None


def char_folder_id(char):
    cid = char.get("id") or ""
    name = char.get("name") or "character"
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-")) or cid or "character"
    return safe.lower()[:40]


# ═══════════════ 메인 ═══════════════

def generation_context_fingerprint(cfg, acfg):
    """Stable digest of inputs that can change a batch image.

    Secrets and display-only settings are excluded. Private runtime keys such
    as fragment counters are also excluded so finishing one image does not
    invalidate every earlier image in the same run.
    """
    ignored = {"token", "booru_keys", "ui"}
    clean_cfg = {
        k: v for k, v in (cfg or {}).items()
        if not str(k).startswith("_") and k not in ignored
    }
    raw = json.dumps(
        {"config": clean_cfg, "assets": acfg}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generation_task_fingerprint(context_fingerprint, char, cid, num, copy):
    raw = json.dumps(
        {"context": context_fingerprint, "char": char, "cid": cid,
         "scene": int(num), "copy": int(copy)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_progress_record(cfg, num, copy, saved_path, fingerprint):
    root = out_root(cfg).resolve()
    path = Path(saved_path).resolve()
    try:
        stored = path.relative_to(root).as_posix()
    except ValueError:
        stored = str(path)
    return {"scene": int(num), "copy": int(copy), "path": stored,
            "bytes": path.stat().st_size, "fingerprint": fingerprint}


def progress_item_key(item):
    try:
        if isinstance(item, dict):
            return int(item["scene"]), int(item.get("copy", 1))
        if isinstance(item, (list, tuple)) and len(item) == 2:
            return int(item[0]), int(item[1])
        return int(item), 1
    except (KeyError, TypeError, ValueError):
        return None

def progress_record_valid(record, cfg, expected_fingerprint):
    if not isinstance(record, dict):
        return False
    if record.get("fingerprint") != expected_fingerprint:
        return False
    value = record.get("path")
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    if not path.is_absolute():
        path = out_root(cfg).resolve() / path
    try:
        return (path.is_file() and path.stat().st_size > 0
                and path.stat().st_size == int(record.get("bytes", -1)))
    except (OSError, TypeError, ValueError):
        return False

def compute_pending(cfg, acfg, done_this_run, skip_set):
    """세팅별 선택(setting_state)을 기준으로 작업 목록 계산. 사용 꺼진 세팅은 제외."""
    allowed = set()
    for name, ctx in acfg.get("_settings", {}).items():
        state = setting_state(cfg, name)
        if state.get("use") is False:
            continue
        selected = set(state.get("selected", []))
        if not selected:
            continue
        scenes_of = {k: sc for k, sc in acfg["scenes"].items() if sc.get("_setting") == name}
        # 단계 선택 — "전 체위의 사정 컷만" 처럼 세트를 가로로 자른다.
        # 비어 있으면 전 단계. 저장값은 1부터 센 사람 기준 번호다.
        stages = {int(x) for x in (state.get("stages") or []) if str(x).isdigit()}
        for g in derive_setting_catalog(scenes_of):
            if g["id"] not in selected:
                continue
            if stages:
                allowed.update(sn for i, sn in enumerate(g["ids"], 1) if i in stages)
            else:
                allowed.update(g["ids"])

    scene_nums = sorted(n for n in (int(x) for x in acfg.get("scenes", {}) if str(x).isdigit())
                        if n in allowed)

    # 주인공: 씬이 속한 세팅의 전용 캐스트 → 없으면 ① 설정의 캐릭터 슬롯 (설정을 강제하지 않음)
    # 켠 인물만 (칸은 6명 넘게 둬도 된다)
    slots = [s for s in cfg.get("char_slots", [])
             if slot_prompt(s).strip() and s.get("enabled") is not False]
    # 씬 번호 → 예약 매수 (세트별로 '몇 벌' 뽑을지. 기본 1벌)
    reserve = {}
    for name in acfg.get("_settings", {}):
        rep = (setting_state(cfg, name).get("reserve") or {})
        if not rep:
            continue
        scenes_of = {k: sc for k, sc in acfg["scenes"].items() if sc.get("_setting") == name}
        for g in derive_setting_catalog(scenes_of):
            n = int(rep.get(str(g["id"]), rep.get(g["id"], 1)) or 1)
            if n > 1:
                for sn in g["ids"]:
                    reserve[sn] = n

    pending = []
    for num in scene_nums:
        sc = acfg["scenes"][str(num)]
        sname = sc.get("_setting", "")
        cast = [c for c in setting_state(cfg, sname).get("cast", [])
                if strip_comment_lines(c.get("prompt") or "").strip()]
        # 두 목록의 뜻이 다르다 (UI 문구 그대로):
        #   세팅 전용 캐스트 = "각자 따로 전체 씬 생성" → 인원수만큼 벌이 늘어난다
        #   ① 설정의 캐릭터 칸 = "한 그림에 함께 들어갈 인물" → 늘어나지 않는다.
        #     첫 칸이 주인공, 둘째 칸이 상대역이 된다 (단독 생성과 같은 규칙).
        if cast:
            # 표시 이름이 같아도 각 캐스트는 별개 작업이다. index와 내용 fingerprint를 identity로 쓴다.
            runs = [([c], f"{sname}\0cast\0{i}\0{c.get('id', '')}\0"
                             f"{c.get('prompt', '')}\0{c.get('negative', '')}")
                    for i, c in enumerate(cast)]
        else:
            runs = [(slots, None)] if slots else []
        for i, (group, identity) in enumerate(runs):
            p = group[0]
            partner = group[1] if len(group) > 1 else {}
            char = {"name": p.get("name") or f"인물{i+1}", "female": slot_prompt(p),
                    "negative": p.get("negative", ""),
                    "male_prompt_base": slot_prompt(partner),
                    "partner_negative": partner.get("negative", ""),
                    # 셋째 칸부터는 '추가 인물' 로 그대로 보낸다 (세팅은 주인공+상대역
                    # 2인 구조지만, 캐릭터 칸에 더 넣어 뒀으면 버리지 않는다)
                    "extras": [{"prompt": slot_prompt(x), "negative": x.get("negative", "")}
                               for x in group[2:]]}
            cid = _safe_name(char["name"]).lower() or f"char{i+1}"
            if identity is not None:
                digest = zlib.crc32(identity.encode("utf-8")) & 0xffffffff
                cid = f"{cid[:30]}-{digest:08x}"
            done_set = done_this_run.get(cid, set())
            for copy in range(1, max(1, int(reserve.get(num, 1))) + 1):
                if (num, copy) in done_set or (cid, num, copy) in skip_set:
                    continue
                pending.append((char, cid, num, copy))
    # 캐스트가 여럿이면 **한 사람의 씬을 다 돌고 다음 사람으로** 넘어간다.
    # 위 루프는 씬을 겉돌기 때문에 사람이 번갈아 섞인다 — 폴더가 뒤죽박죽이 되고
    # 중간에 멈췄을 때 누구까지 끝났는지 알 수 없다.
    if cfg.get("per_char_order", True):
        order = {}
        for item in pending:
            order.setdefault(item[1], len(order))
        pending.sort(key=lambda it: (order[it[1]], it[2], it[3]))
    return pending


def _comparison_progress_load():
    if not COMPARE_PROGRESS_FILE.exists():
        return {}
    try:
        data = load_json_recover(COMPARE_PROGRESS_FILE)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.warning(f"비교 생성 진행 기록을 읽지 못했습니다: {e}")
        return {}


def comparison_progress_summary(cfg):
    """최근 비교 실행을 탐색기에서 열 수 있는 최소 정보만 돌려준다."""
    progress = _comparison_progress_load()
    rel = str(progress.get("folder") or "").strip().replace("\\", "/").strip("/")
    if not rel:
        return {"ok": False, "error": "아직 비교 생성 결과가 없습니다."}
    root = out_root(cfg).resolve()
    folder = (root / rel).resolve()
    if not _path_is_inside(folder, root) or not folder.is_dir():
        return {"ok": False, "error": "최근 비교 결과 폴더를 찾지 못했습니다."}
    completed = progress.get("completed")
    completed_n = len(completed) if isinstance(completed, dict) else 0
    plan = progress.get("plan") if isinstance(progress.get("plan"), dict) else {}
    return {
        "ok": True,
        "folder": folder.relative_to(root).as_posix(),
        "status": str(progress.get("status") or ""),
        "completed": completed_n,
        "total": int(plan.get("count") or completed_n),
        "mode_label": str(progress.get("mode_label") or ""),
    }


def comparison_runs(cfg, limit=50):
    """결과 폴더의 manifest를 읽어 최근 비교 실험과 재개 가능 여부를 돌려준다."""
    root = out_root(cfg).resolve()
    runs_root = (root / "비교생성").resolve()
    if not runs_root.is_dir():
        return {"ok": True, "runs": []}
    found = []
    for folder in runs_root.iterdir():
        if not folder.is_dir() or not _path_is_inside(folder, runs_root):
            continue
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            progress = load_json_recover(manifest_path)
        except Exception as e:
            log.warning("비교 실험 기록을 읽지 못했습니다(%s): %s", folder.name, e)
            continue
        if not isinstance(progress, dict):
            continue
        plan = progress.get("plan") if isinstance(progress.get("plan"), dict) else {}
        options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
        completed = progress.get("completed")
        completed_n = len(completed) if isinstance(completed, dict) else 0
        total = int(plan.get("count") or completed_n)
        status = str(progress.get("status") or "")
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0
        found.append({
            "folder": folder.relative_to(root).as_posix(),
            "name": folder.name,
            "status": status,
            "mode_label": str(progress.get("mode_label") or ""),
            "completed": completed_n,
            "total": total,
            "updated_at": str(progress.get("updated_at")
                              or progress.get("created_at") or ""),
            "resumable": bool(
                status != "complete"
                and progress.get("signature")
                and isinstance(completed, dict)
            ),
            "options": options,
            "_mtime": mtime,
        })
    found.sort(key=lambda x: (x["_mtime"], x["name"]), reverse=True)
    for item in found:
        item.pop("_mtime", None)
    return {"ok": True, "runs": found[:max(1, min(int(limit or 50), 200))]}


def activate_comparison_run(cfg, folder):
    """선택한 미완료 manifest를 현재 재개 대상으로 안전하게 활성화한다."""
    root = out_root(cfg).resolve()
    runs_root = (root / "비교생성").resolve()
    rel = str(folder or "").strip().replace("\\", "/").strip("/")
    candidate = (root / rel).resolve()
    if (not rel or not _path_is_inside(candidate, runs_root)
            or not candidate.is_dir()):
        raise ValueError("선택한 비교 실험 폴더를 찾지 못했습니다.")
    manifest_path = candidate / "manifest.json"
    progress = load_json_recover(manifest_path)
    if not isinstance(progress, dict):
        raise ValueError("비교 실험 기록 형식이 올바르지 않습니다.")
    plan = progress.get("plan") if isinstance(progress.get("plan"), dict) else {}
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    completed = progress.get("completed")
    resumable = bool(
        progress.get("status") != "complete"
        and progress.get("signature")
        and isinstance(completed, dict)
    )
    if resumable:
        atomic_write_json(COMPARE_PROGRESS_FILE, progress, indent=1)
    return {
        "ok": True,
        "folder": candidate.relative_to(root).as_posix(),
        "status": str(progress.get("status") or ""),
        "completed": len(completed) if isinstance(completed, dict) else 0,
        "total": int(plan.get("count") or 0),
        "resumable": resumable,
        "options": options,
    }


def comparison_recipe_for_output(cfg, rel):
    """선택한 비교 이미지가 실제로 사용한 원문·설정·캐릭터를 manifest에서 복원한다."""
    image_path = output_file_for_preview(cfg, rel)
    if image_path is None:
        raise ValueError("선택한 비교 결과 파일을 찾지 못했습니다.")
    root = out_root(cfg).resolve()
    runs_root = (root / "비교생성").resolve()
    folder = image_path.parent.resolve()
    if not _path_is_inside(folder, runs_root):
        raise ValueError("비교 생성 결과만 현재 생성에 적용할 수 있습니다.")
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("이 결과의 비교 manifest를 찾지 못했습니다.")
    progress = load_json_recover(manifest_path)
    completed = progress.get("completed")
    if not isinstance(completed, dict):
        raise ValueError("비교 결과 기록 형식이 올바르지 않습니다.")
    wanted = image_path.relative_to(root).as_posix()
    record = next((
        item for item in completed.values()
        if isinstance(item, dict)
        and str(item.get("file") or "").replace("\\", "/") == wanted
    ), None)
    if record is None:
        raise ValueError("manifest에서 선택한 결과의 생성 기록을 찾지 못했습니다.")
    context = progress.get("recipe_context")
    if not isinstance(context, dict):
        raise ValueError(
            "이 결과는 원문 레시피 기록 기능 이전에 만들어져 자동 적용할 수 없습니다.")
    context_cfg = dict(DEFAULT_CONFIG)
    context_cfg.update(
        context.get("config") if isinstance(context.get("config"), dict) else {})
    options = context.get("options")
    if not isinstance(options, dict):
        plan = progress.get("plan") if isinstance(progress.get("plan"), dict) else {}
        options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    styles = context.get("styles") if isinstance(context.get("styles"), list) else []
    chars = (context.get("characters")
             if isinstance(context.get("characters"), list) else [])
    style_id = record.get("style_id")
    character_id = record.get("character_id")
    style = next((
        item for item in styles
        if isinstance(item, dict)
        and str(item.get("id")) == str(style_id)
    ), None) if style_id is not None else None
    character = next((
        item for item in chars
        if isinstance(item, dict)
        and str(item.get("id")) == str(character_id)
    ), None) if character_id is not None else None
    used = comparison_style_config(context_cfg, style, options)
    base = ((style or {}).get("base")
            or context_cfg.get("base_prompt") or "1girl").strip()
    negative = ((style or {}).get("negative")
                if style is not None
                else context_cfg.get("negative_prompt", ""))
    negative = negative or ""
    if character is not None:
        char_slots = [{
            "name": character.get("name") or record.get("character") or "캐릭터",
            "prompt": character.get("female") or "",
            "outfit": character.get("clothed") or "",
            "negative": character.get("negative") or "",
            "enabled": True,
        }]
        char_centers = [{"x": 0.5, "y": 0.5}]
    else:
        char_slots = [
            dict(slot) for slot in (context.get("char_slots") or [])
            if isinstance(slot, dict)
        ]
        char_centers = [
            dict(center) for center in (context.get("char_centers") or [])
            if isinstance(center, dict)
        ]
    include_refs = bool(options.get("include_refs"))
    return {
        "ok": True,
        "file": wanted,
        "recipe": {
            "version": 1,
            "mode": str(progress.get("mode") or options.get("mode") or ""),
            "base_prompt": base,
            "negative_prompt": negative,
            "style_name": ((style or {}).get("name")
                           or context_cfg.get("style_name")
                           or record.get("style") or ""),
            "settings": {
                key: used.get(key) for key in COMPARE_RECIPE_SETTING_KEYS
            },
            "char_slots": char_slots,
            "char_centers": char_centers,
            "nai_seed": int(record.get("seed") or 0),
            "include_refs": include_refs,
            "vibes": context_cfg.get("vibes") or [] if include_refs else [],
            "char_refs": context_cfg.get("char_refs") or [] if include_refs else [],
            "source": {
                "style": (style or {}),
                "character": (character or {}),
            },
        },
    }


def _unique_library_name(directory, requested, fallback, existing_names=()):
    """표시 이름과 안전 파일명이 모두 겹치지 않는 가장 가까운 이름을 고른다."""
    base = str(requested or "").strip() or fallback
    used = {str(name).casefold() for name in existing_names if str(name).strip()}
    candidate = base
    suffix = 2
    while (
        candidate.casefold() in used
        or (directory / f"{_safe_name(candidate)}.json").exists()
    ):
        candidate = f"{base} ({suffix})"
        suffix += 1
    return candidate


def _style_signature(prompt, negative, settings):
    clean_settings = {
        key: value for key, value in (settings or {}).items()
        if key in COMPARE_RECIPE_SETTING_KEYS and value is not None
    }
    return json.dumps(
        {
            "prompt": str(prompt or ""),
            "negative": str(negative or ""),
            "settings": clean_settings,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@serialized_data_write(lambda: BASE_DIR)
def promote_comparison_recipe_assets(cfg, rel, kind, name="", spec=None):
    """선택 결과를 중복·덮어쓰기 없이 기존 그림체 또는 캐릭터 자료로 승격한다.

    세팅은 비교 생성에 사용되지 않고 manifest에도 상태가 없으므로 그림 한 장에서
    역추정하지 않는다. 생성 설정은 그림체의 일부로 함께 저장한다.
    """
    restored = comparison_recipe_for_output(cfg, rel)
    recipe = restored["recipe"]
    kind = str(kind or "").strip().lower()
    if kind == "setting":
        return {
            "ok": False,
            "error": "이 비교 결과에는 세팅 선택 상태가 없습니다. 그림만 보고 세팅을 추정해 저장하지 않습니다.",
        }
    if kind == "style":
        prompt = recipe.get("base_prompt") or ""
        negative = recipe.get("negative_prompt") or ""
        settings = {
            key: value for key, value in (recipe.get("settings") or {}).items()
            if key in COMPARE_RECIPE_SETTING_KEYS and value is not None
        }
        wanted = _style_signature(prompt, negative, settings)
        styles = list_styles(spec or load_spec())
        same = next((
            item for item in styles
            if _style_signature(
                item.get("prompt"), item.get("negative"), item.get("settings")
            ) == wanted
        ), None)
        if same is not None:
            return {
                "ok": True, "kind": "style", "saved": 0, "existing": 1,
                "names": [same.get("name") or "기존 그림체"],
                "styles": styles, "changed_config": False,
            }
        final_name = _unique_library_name(
            STYLE_DIR,
            name or recipe.get("style_name"),
            "비교 결과 그림체",
            (item.get("name") for item in styles),
        )
        save_style_file(
            final_name, prompt=prompt, negative=negative, settings=settings)
        return {
            "ok": True, "kind": "style", "saved": 1, "existing": 0,
            "names": [final_name],
            "styles": list_styles(spec or load_spec()),
            "changed_config": False,
        }
    if kind != "characters":
        return {"ok": False, "error": "저장할 자료 종류가 올바르지 않습니다."}

    slots = [
        slot for slot in (recipe.get("char_slots") or [])
        if isinstance(slot, dict) and slot_prompt(slot).strip()
    ]
    if not slots:
        return {"ok": False, "error": "이 비교 결과에는 저장할 캐릭터가 없습니다."}
    characters = cfg.setdefault("characters", [])
    names, saved, existing = [], 0, 0
    for index, slot in enumerate(slots, 1):
        prompt = str(slot.get("prompt") or "")
        outfit = str(slot.get("outfit") or "")
        negative = str(slot.get("negative") or "")
        same = next((
            item for item in characters
            if str(item.get("female") or "") == prompt
            and str(item.get("clothed") or "") == outfit
            and str(item.get("negative") or "") == negative
        ), None)
        if same is not None:
            names.append(same.get("name") or f"기존 캐릭터 {index}")
            existing += 1
            continue
        requested = slot.get("name") or (
            f"{name} {index}" if name and len(slots) > 1 else name)
        final_name = _unique_library_name(
            CHAR_DIR,
            requested,
            f"비교 결과 캐릭터 {index}",
            (item.get("name") for item in characters),
        )
        characters.append({
            "id": "".join(random.choices(
                string.ascii_lowercase + string.digits, k=8)),
            "name": final_name,
            "female": prompt,
            "clothed": outfit,
            "negative": negative,
            "enabled": True,
            "folder_id": None,
            "subfolder_id": None,
            "source": f"비교 결과: {restored['file']}",
        })
        names.append(final_name)
        saved += 1
    if saved:
        sync_chars_to_files(cfg)
        save_config(cfg)
    return {
        "ok": True, "kind": "characters", "saved": saved, "existing": existing,
        "names": names, "characters": characters,
        "changed_config": bool(saved),
    }


def _comparison_progress_save(progress, folder):
    """재개용 기록과 사람이 읽을 결과 폴더 manifest를 함께 원자 저장한다."""
    atomic_write_json(COMPARE_PROGRESS_FILE, progress, indent=1)
    atomic_write_json(folder / "manifest.json", progress, indent=1)


def _comparison_progress_start(cfg, plan, styles, chars):
    root = out_root(cfg).resolve()
    signature = comparison_signature(cfg, plan, styles, chars)
    old = _comparison_progress_load()
    resumable = (old.get("signature") == signature
                 and old.get("status") not in ("complete",)
                 and isinstance(old.get("completed"), dict))
    folder = None
    if resumable:
        rel = str(old.get("folder") or "")
        candidate = (root / rel).resolve()
        if (_path_is_inside(candidate, root) and candidate.is_dir()):
            folder = candidate
    if folder is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
        folder = out_sub(cfg, "비교생성") / run_id
        folder.mkdir(parents=True, exist_ok=True)
        progress = {
            "version": 1,
            "signature": signature,
            "status": "running",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "folder": folder.relative_to(root).as_posix(),
            "mode": plan["options"]["mode"],
            "mode_label": plan["mode_label"],
            "plan": {k: v for k, v in plan.items()
                     if k not in ("sample_styles", "sample_characters")},
            "base_seed": int(plan["options"].get("seed") or 0)
                         or random.randint(1, 2**32 - 1),
            "recipe_context": comparison_recipe_context(
                cfg, plan, styles, chars),
            "completed": {},
            "errors": {},
        }
    else:
        progress = old
        progress["status"] = "running"
        progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if not isinstance(progress.get("recipe_context"), dict):
            progress["recipe_context"] = comparison_recipe_context(
                cfg, plan, styles, chars)
        log.info("중단된 자료 비교 생성을 이어서 합니다: %s", folder)

    # 기록만 있고 파일이 사라진 항목은 완료로 보지 않는다.
    completed = progress.setdefault("completed", {})
    for key, rec in list(completed.items()):
        rel = rec.get("file") if isinstance(rec, dict) else rec
        path = output_file_for_preview(cfg, rel)
        if path is None or not path.is_file() or path.stat().st_size <= 0:
            completed.pop(key, None)
    _comparison_progress_save(progress, folder)
    return progress, folder


def _run_comparison(server, cfg, plan, styles, chars):
    """자료 비교 큐. 한 번에 한 요청만 보내고 중지·일일 상한·재개를 모두 지킨다."""
    progress, folder = _comparison_progress_start(cfg, plan, styles, chars)
    completed = progress["completed"]
    errors = progress.setdefault("errors", {})
    options = plan["options"]
    token = cfg["token"]
    base_seed = int(progress["base_seed"])
    state = load_state()
    jobs = iter_comparison_jobs(cfg, plan, styles, chars)
    done_n = len(completed)
    server.live.update(
        index=done_n, total=plan["count"], char_name=plan["mode_label"],
        filename="", status_text=(f"자료 비교 생성 준비 중 — {done_n:,}/{plan['count']:,}"),
        daily=daily_count(state), daily_cap=pace(cfg)["daily_cap"],
        completed=done_n, eta_base_completed=done_n)

    final_status = "complete"
    fatal = False
    for job in jobs:
        key = job["key"]
        if key in completed:
            continue
        if server.live.stop_req:
            final_status = "stopped"
            break
        if daily_count(state) >= pace(cfg)["daily_cap"]:
            final_status = "daily_limit"
            server.live.update(status_text="일일 상한 도달 — 내일 같은 계획을 누르면 이어집니다.")
            break

        used, base, negative, people, centers = comparison_job_values(cfg, plan, job)
        seed_index = int(job.get("seed_index") or 0)
        seed = (
            (base_seed + seed_index * 100003) & 0xffffffff
            if options["same_seed"]
            else (base_seed + (job["index"] - 1) * 100003) & 0xffffffff
        )
        seed = seed or 1
        style_label = job["style_name"]
        char_label = job["char_name"]
        seed_suffix = (
            f"_S{seed_index + 1}"
            if int(options.get("seed_count") or 1) > 1 else ""
        )
        stem = (f"{job['index']:06d}_"
                f"{_safe_name(style_label)[:38]}__{_safe_name(char_label)[:32]}"
                f"{seed_suffix}")
        target = available_output_path(folder / f"{stem}.webp", out_format(cfg))
        done_n = len(completed)
        server.live.update(
            index=done_n + 1, total=plan["count"], filename=target.name,
            char_name=f"{style_label} × {char_label}",
            status_text=f"자료 비교 생성 중 — {done_n + 1:,}/{plan['count']:,}",
            seed=seed)
        log.info("[비교 %d/%d] %s × %s · %dx%d · 시드 %d",
                 done_n + 1, plan["count"], style_label, char_label,
                 used["width"], used["height"], seed)

        ok = False
        last_error = ""
        for attempt in range(3):
            if server.live.stop_req:
                final_status = "stopped"
                break
            allowed, why = pace_gate(cfg, server.live, "자료 비교")
            if not allowed:
                last_error = why
                if "일일 상한" in why:
                    final_status = "daily_limit"
                break
            try:
                params = runtime_generation_params(
                    used, token, include_refs=options["include_refs"])
                try:
                    img = call_nai_api(
                        token, base, "", "", negative,
                        int(used.get("width", 832)), int(used.get("height", 1216)),
                        chars=people,
                        scale=used.get("cfg_scale", 5.5),
                        cfg_rescale=used.get("cfg_rescale", 0.56),
                        steps=int(used.get("steps", 28)),
                        sampler=used.get("sampler", "k_euler_ancestral"),
                        scheduler=used.get("scheduler", "karras"),
                        variety=used.get("variety", False),
                        uc_preset=int(used.get("uc_preset", 4)),
                        seed=seed, params=with_centers(params, centers))
                finally:
                    pace_complete()
                saved = save_with_meta(
                    img, target, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                    max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                server.live.set_image(img)
                rel = saved.resolve().relative_to(out_root(cfg).resolve()).as_posix()
                completed[key] = {
                    "index": job["index"], "file": rel,
                    "style": style_label, "character": char_label,
                    "style_id": ((job.get("style") or {}).get("_compare_id")),
                    "character_id": (
                        (job.get("character") or {}).get("_compare_id")),
                    "seed_index": seed_index,
                    "seed": seed, "width": int(used["width"]),
                    "height": int(used["height"]),
                }
                errors.pop(key, None)
                bump_daily(state)
                save_state(state)
                progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _comparison_progress_save(progress, folder)
                server.live.update(daily=daily_count(state))
                ok = True
                break
            except RateLimitError as e:
                last_error = str(e)
                if attempt >= 2:
                    break
                server.live.note_retry(e)
                server.live.update(status_text=f"429 — {e.retry_after:g}초 뒤 재시도")
                if server.live.wait_cancelable(e.retry_after):
                    final_status = "stopped"
                    break
            except (AccountBannedError, AuthError) as e:
                last_error = str(e)
                server.live.update(status_text=f"즉시 중단: {e}")
                final_status, fatal = "fatal", True
                break
            except APIError as e:
                last_error = str(e)
                if not e.retryable:
                    break
                if attempt >= 2:
                    break
                wait = min(5 * (2 ** attempt), 30)
                server.live.note_retry(e)
                server.live.update(status_text=f"서버 오류 — {wait}초 뒤 재시도")
                if server.live.wait_cancelable(wait):
                    final_status = "stopped"
                    break
            except Exception as e:
                last_error = str(e)
                log.error("자료 비교 %s 실패(%d/3): %s", target.name, attempt + 1, e)
                if attempt < 2:
                    server.live.note_retry(e)
                if attempt < 2 and server.live.wait_cancelable(30):
                    final_status = "stopped"
                    break

        if not ok:
            errors[key] = {
                "index": job["index"], "style": style_label,
                "character": char_label, "error": last_error or "중지됨",
            }
            progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _comparison_progress_save(progress, folder)
            if fatal or final_status in ("stopped", "daily_limit"):
                break

    if final_status == "complete" and len(completed) < plan["count"]:
        final_status = "partial" if errors else "stopped"
    progress["status"] = final_status
    progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    progress["completed_count"] = len(completed)
    _comparison_progress_save(progress, folder)

    rel_folder = folder.resolve().relative_to(out_root(cfg).resolve()).as_posix()
    if final_status == "complete":
        text = f"자료 비교 완료 — {len(completed):,}장 · {rel_folder}"
    elif final_status == "partial":
        text = (f"자료 비교 부분 완료 — 성공 {len(completed):,}장 · "
                f"실패 {len(errors):,}장 (같은 계획으로 실패분 재시도)")
    elif final_status == "stopped":
        text = f"자료 비교 중지 — {len(completed):,}/{plan['count']:,}장 (같은 계획으로 이어짐)"
    elif final_status == "daily_limit":
        text = f"일일 상한 도달 — {len(completed):,}/{plan['count']:,}장 (내일 이어짐)"
    else:
        text = f"자료 비교 중단 — {len(completed):,}/{plan['count']:,}장"
    phase = {
        "complete": "completed",
        "partial": "partial",
        "stopped": "stopped",
        "daily_limit": "stopped",
        "fatal": "failed",
    }.get(final_status, "failed")
    server.live.update(
        index=len(completed), total=plan["count"], status_text=text,
        completed=len(completed), failed=len(errors), phase=phase,
        last_error=(next(reversed(errors.values())).get("error", "")
                    if errors else ""),
        can_retry=final_status != "complete")
    log.info(text)


def main():
    cfg = load_or_init_config()

    server = ConfigServer(cfg)
    url = server.start(open_browser="--no-browser" not in sys.argv[1:])
    if not url:
        input("엔터를 누르면 종료...")
        return

    # 태그 사전(22만개) 로드 + 자동완성 색인을 미리 만들어 둔다.
    # 안 하면 **첫 타이핑에서 10초쯤 멈춘 것처럼** 보인다.
    def _warm():
        try:
            _ac_index(server.spec)
        except Exception as e:
            log.info(f"자동완성 예열 건너뜀: {e}")
    threading.Thread(target=_warm, daemon=True).start()

    print()
    print("브라우저에서 설정을 마치고 '생성 시작'을 눌러주세요.")
    print(f"창이 자동으로 열리지 않으면 이 주소를 직접 열어주세요: {url}")
    print("생성이 끝난 뒤에도 설정을 바꿔서 '생성 시작'을 다시 누르면 이어서 새로 만듭니다.")
    print()

    while True:
        server.start_event.wait()  # '생성 시작' 클릭까지 대기
        # 단독 생성 등이 그 틈에 실행권을 가져갔다면 배치를 겹쳐 돌리지 않는다
        tok = server.live.try_claim("세팅 배치 생성", "settings")
        if tok is None:
            server.start_event.clear()
            server.live.update(status_text="다른 생성이 도는 중입니다 — 끝난 뒤 '생성 시작'을 다시 눌러주세요.")
            continue
        try:
            _run_generation(server)
            if server.live.stop_req:
                server.live.update(
                    status_text="중지됨 — '생성 시작'을 누르면 이어서 합니다.",
                    phase="stopped", can_retry=True)
            elif server.live.failed:
                server.live.update(
                    status_text=(
                        f"일부 완료 — 성공 {server.live.completed} · "
                        f"실패 {server.live.failed} (다시 실행하면 실패분 재시도)"
                    ),
                    phase="partial", can_retry=True)
            else:
                log.info("═══ 이번 실행 완료 — 설정을 바꾸고 '생성 시작'을 다시 누르면 계속할 수 있습니다 ═══")
                server.live.update(
                    status_text="완료! 다시 '생성 시작'을 누르면 계속할 수 있습니다.",
                    phase="completed")
        except FatalStopError as e:
            server.live.update(
                status_text=f"즉시 중단: {e}", failed=max(1, server.live.failed),
                last_error=str(e), phase="failed", can_retry=True)
            break
        except Exception as e:
            log.critical(f"예기치 못한 오류로 중단되었습니다: {e}")
            log.critical(traceback.format_exc())
            server.live.update(
                status_text=f"오류로 중단됨: {e}",
                failed=max(1, server.live.failed), last_error=str(e),
                phase="failed", can_retry=True)
            break
        finally:
            server.live.release(tok)
            server.start_event.clear()

    print("프로그램을 종료합니다.")


def _run_generation(server):
    seed_idx = int(server.cfg.get("seed", 1) or 1)
    seed_key = f"{seed_idx:02d}"

    state = load_state()
    if seed_key not in state["seeds"]:
        state["seeds"][seed_key] = random.randint(0, 2**32 - 1)
        save_state(state)
    base_seed = state["seeds"][seed_key]           # 이 회차의 기준 시드
    # 조각 순차(<*이름>) 순번은 배치 내내, 그리고 다음 실행까지 이어진다.
    # cfg 에 실어 두면 call_nai_api 가 장마다 하나씩 올려 준다.
    state.setdefault("frag_seq", {})
    server.cfg["_frag_counters"] = state["frag_seq"]
    server.live.update(seed_key=seed_key)
    if fixed_seed(server.cfg):
        log.info(f"═══ 회차 {seed_key} — NAI 시드 고정 {fixed_seed(server.cfg)} "
                 f"(모든 장이 같은 시드) ═══")
    else:
        log.info(f"═══ 회차 {seed_key} (기준 시드 {base_seed}) — 장마다 '기준+씬번호' 시드. "
                 f"같은 회차를 다시 돌리면 같은 결과 ═══")
    log.info(f"오늘 생성량: {daily_count(state)}/{DAILY_CAP}")

    characters_now = server.cfg.get("characters", [])
    enabled_now = [c for c in characters_now if c.get("enabled", True)]
    sel_summary = " · ".join(
        f"{name} {len(st.get('selected', []))}세트"
        for name, st in (server.cfg.get("setting_state") or {}).items()
        if st.get("use") is not False and st.get("selected"))
    log.info(f"캐릭터 {len(enabled_now)}명 켜짐 (전체 {len(characters_now)}명) · 선택: {sel_summary or '없음'}")
    if not enabled_now:
        log.warning("⚠ 켜진 캐릭터가 없습니다. 브라우저에서 캐릭터를 추가하거나 켜주세요.")

    # 이 회차에서 **이미 끝낸 장**을 상태 파일에서 되살린다 (CQA-010).
    #   예전에는 progress 를 쓰기만 하고 읽지 않아, 중지 후 '생성 시작'을 다시 누르면
    #   끝난 장을 처음부터 다시 만들고 같은 파일을 덮어썼다 (Anlas·시간 재소모).
    #   회차(seed) 를 바꾸면 progress 키가 달라져 자연히 새로 시작한다.
    cfg = server.cfg
    acfg = load_asset_config(cfg)
    context_fingerprint = generation_context_fingerprint(cfg, acfg)
    records = {}
    legacy_records = 0
    for cid, items in (state.get("progress", {}).get(seed_key) or {}).items():
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                legacy_records += 1
                continue
            try:
                key = (str(cid), int(item["scene"]), int(item.get("copy", 1)))
            except (KeyError, TypeError, ValueError):
                continue
            records[key] = item

    done_this_run = {}
    invalid_records = 0
    candidates = compute_pending(cfg, acfg, {}, set())
    for char, cid, num, copy in candidates:
        record = records.get((cid, num, copy))
        if record is None:
            continue
        fingerprint = generation_task_fingerprint(
            context_fingerprint, char, cid, num, copy)
        if progress_record_valid(record, cfg, fingerprint):
            done_this_run.setdefault(cid, set()).add((num, copy))
        else:
            invalid_records += 1
    if done_this_run:
        n_done = sum(len(v) for v in done_this_run.values())
        log.info(f"회차 {seed_key}의 파일·설정이 일치하는 완료 {n_done}장을 건너뜁니다.")
    if legacy_records or invalid_records:
        log.warning("재개 기록 중 파일 또는 설정 근거가 없는 %d건은 다시 생성합니다.",
                    legacy_records + invalid_records)
    skip_set = set()   # 이번 실행에서 계속 실패해 건너뛴 작업 (재실행하면 다시 시도)
    completed = 0

    while True:
        if server.live.stop_req:   # /api/stop — 장 경계에서 멈춘다 (실행권은 finally 가 푼다)
            log.info("■ 중지되었습니다 — '생성 시작'을 다시 누르면 이어서 합니다.")
            server.live.update(
                status_text="중지됨 — '생성 시작'을 누르면 이어서 합니다.",
                phase="stopped", can_retry=True)
            save_state(state)
            return
        cfg = server.cfg  # 매 루프마다 최신 설정을 다시 읽는다 (실시간 반영 핵심)
        acfg = load_asset_config(cfg)
        context_fingerprint = generation_context_fingerprint(cfg, acfg)
        pending = compute_pending(cfg, acfg, done_this_run, skip_set)

        if not pending:
            break

        if daily_count(state) >= pace(cfg)["daily_cap"]:
            log.warning(f"일일 {pace(cfg)['daily_cap']}장 한도 도달. 내일 다시 실행하면 이어서 합니다.")
            server.live.update(
                status_text="일일 한도 도달 — 내일 다시 실행하면 이어집니다.",
                phase="stopped", can_retry=True)
            save_state(state)
            return

        # 쉬는 자리는 **패스 경계**다 — 장 사이에서만 쉬고, 생성 도중엔 안 끊는다
        pc = pace(cfg)
        if pc["cool_every"] and completed > 0 and completed % pc["cool_every"] == 0:
            log.info(f"⏸ {pc['cool_every']}장 완료 — {pc['cool_seconds']}초 쿨다운")
            server.live.update(status_text=f"쿨다운 {pc['cool_seconds']}초...")
            save_state(state)
            # 취소를 존중하는 대기 — 중지되면 다음 장을 시작하지 않고 바로 끝낸다
            if server.live.wait_cancelable(pc["cool_seconds"]):
                continue
        elif pc["soft_every"] and completed > 0 and completed % pc["soft_every"] == 0:
            pause = pc["soft_seconds"] + random.uniform(-5, 10)
            pause = max(1.0, pause)
            log.info(f"⏸ 소프트 휴식 {pause:.0f}초")
            server.live.update(status_text=f"소프트 휴식 {pause:.0f}초...")
            save_state(state)
            if server.live.wait_cancelable(pause):
                continue

        negative = acfg["base"].get("nsfw_negative_prompt", acfg["base"]["negative_prompt"])
        scale = acfg["base"].get("cfg_scale", cfg.get("cfg_scale", 5.5))
        cfg_rescale = acfg["base"].get("cfg_rescale", cfg.get("cfg_rescale", 0.56))
        sampler = acfg["base"].get("sampler", cfg.get("sampler", "k_euler_ancestral"))
        scheduler = acfg["base"].get("scheduler", cfg.get("scheduler", "karras"))
        uc_preset = int(cfg.get("uc_preset", acfg["base"].get("uc_preset", 3)))
        variety = cfg.get("variety", False)
        steps = int(cfg.get("steps", acfg["base"].get("steps", 28)))
        token = cfg["token"]
        # 바이브는 한 번 인코딩하면 캐시되어 이 회차 내내 공짜로 재사용된다
        params = runtime_generation_params(cfg, token)

        char, cid, num, copy = pending[0]
        total_now = completed + len(pending)

        try:
            out_dir = out_sub(cfg, "nsfw_seed") / f"seed_{seed_key}" / cid
            out_dir.mkdir(parents=True, exist_ok=True)

            scene = acfg["scenes"][str(num)]
            char_label = char.get("name") or cid
            suffix = "" if copy == 1 else f"_{copy}벌"
            fname = (f"{num:03d}_{scene['name'].replace(' ', '_').replace('/', '_')}"
                     f"{suffix}.webp")
            base_p, female, male, char_neg, male_neg, w, h = build_scene(acfg, char, cfg, num)
        except Exception as e:
            log.error(f"[{completed+1}/{total_now}] 프롬프트/폴더 준비 중 오류로 이 컷 건너뜀: {e}")
            log.error(traceback.format_exc())
            skip_set.add((cid, num, copy))
            server.live.update(
                status_text=f"오류(건너뜀): {e}", failed=len(skip_set),
                last_error=str(e), can_retry=True)
            if server.live.wait_cancelable(1):
                return
            continue

        # 이 장의 시드 — 씬 번호로 갈라지고, 같은 씬을 여러 벌 뽑으면 벌마다 또 갈라진다
        # (안 그러면 2벌·3벌이 1벌과 똑같은 그림이 된다)
        seed = seed_for(cfg, base_seed, num + (copy - 1) * 100003)
        log.info(f"[{completed+1}/{total_now}] ({char_label}) {fname} "
                 f"시드 {seed} (오늘 {daily_count(state)+1}/{DAILY_CAP})")
        server.live.update(index=completed + 1, total=total_now, filename=fname,
                            char_name=char_label, status_text="생성 중...", seed=seed)

        ok = False
        for attempt in range(3):
            if server.live.stop_req:      # 보내기 직전에도 확인 (CQA-019)
                break
            okp, why = pace_gate(cfg, server.live, "배치")
            if not okp:
                server.live.update(status_text=why)
                break
            try:
                # 씬 전용 네거티브가 있으면 기본 네거티브 뒤에 붙인다
                #   (씬 모드와 같은 규칙 — 세팅 씬도 이제 이 칸을 가진다)
                scene_neg = (acfg["scenes"][str(num)].get("negative") or "").strip()
                neg_now = _join_tags(negative, scene_neg) if scene_neg else negative
                # 주인공 + 상대역 + (있으면) 추가 인물
                people = [{"prompt": female, "negative": char_neg}]
                if male:
                    people.append({"prompt": male, "negative": male_neg})
                people += char.get("extras") or []
                try:
                    img = call_nai_api(token, base_p, "", "", neg_now, w, h,
                                       chars=people,
                                       scale=scale, cfg_rescale=cfg_rescale,
                                       steps=steps, sampler=sampler, scheduler=scheduler, uc_preset=uc_preset,
                                       seed=seed, variety=variety, params=params)
                finally:
                    pace_complete()
                saved_path = save_with_meta(
                    img, out_dir / fname, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                    max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                server.live.set_image(img)
                ok = True
                break
            except RateLimitError as e:
                wait = e.retry_after
                log.warning(f"  429 — 서버 지시대로 {wait:g}초 대기 후 재시도")
                if attempt >= 2:
                    break
                server.live.note_retry(e)
                server.live.update(status_text=f"429 — {wait:g}초 대기 중...")
                if server.live.wait_cancelable(wait):
                    break                      # 중지 — 재시도하지 않는다
            except (AccountBannedError, AuthError) as e:
                log.critical(f"  {e}")
                server.live.update(
                    status_text=f"중단됨: {e}", failed=max(1, len(skip_set)),
                    last_error=str(e), phase="failed", can_retry=True)
                save_state(state)
                raise FatalStopError(str(e))
            except APIError as e:
                log.error(f"  시도 {attempt+1} 실패: {e}")
                if not e.retryable:
                    server.live.update(
                        status_text=f"재시도하지 않는 요청 오류: {e}",
                        last_error=str(e))
                    break
                if attempt >= 2:
                    break
                wait = min(5 * (2 ** attempt), 30)
                server.live.note_retry(e)
                server.live.update(
                    status_text=f"서버 오류 — {wait}초 뒤 재시도 ({attempt+1}/3)")
                if server.live.wait_cancelable(wait):
                    break
            except Exception as e:
                log.error(f"  시도 {attempt+1} 실패: {e}")
                if attempt < 2:
                    server.live.note_retry(e)
                    server.live.update(
                        status_text=f"재시도 중... ({attempt+1}/3)",
                        last_error=str(e))
                if attempt < 2 and server.live.wait_cancelable(30):
                    break                      # 중지 — 재시도하지 않는다

        if ok:
            done_this_run.setdefault(cid, set()).add((num, copy))
            fingerprint = generation_task_fingerprint(
                context_fingerprint, char, cid, num, copy)
            record = make_progress_record(
                cfg, num, copy, saved_path, fingerprint)
            rec = state["progress"].setdefault(seed_key, {}).setdefault(cid, [])
            rec[:] = [item for item in rec if progress_item_key(item) != (num, copy)]
            rec.append(record)
            bump_daily(state)
            completed += 1
            server.live.update(
                daily=daily_count(state), completed=completed,
                failed=len(skip_set))
            # 매 장 저장한다 — 중지·강제 종료 후 재개가 정확해야 하고 파일은 몇 KB 다
            save_state(state)
        else:
            skip_set.add((cid, num, copy))
            server.live.update(
                status_text=f"실패 — 건너뜀: {fname}",
                failed=len(skip_set), can_retry=True)


if __name__ == "__main__":
    main()
