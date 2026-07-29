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
import hashlib
import base64
import copy
import functools
import io
import json
import math
import os
import random
import re
import shutil
import string
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
import uuid
import webbrowser
import zipfile
import zlib
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from PIL import Image
from src.nai_studio.collection import arca as arca_public
from src.nai_studio.domain.blueprint import (
    canonical_blueprint,
    canonical_generation_plan,
    fingerprint_blueprint,
    summarize_blueprint,
)
from src.nai_studio.domain.project_inheritance import (
    blueprint_common,
    local_overrides,
    normalize_link,
    normalize_projects,
    project_by_id,
    resolve_inheritance,
)
from src.nai_studio.domain.experiment import canonical_experiment_rule
from src.nai_studio.domain.image_metadata import (
    GENERATION_KEYS,
    PARAM_KEYS,
    TEXT_KEYS,
    _prompt_parts,
    extract_nai_metadata,
    normalize_prompt,
    png_text_chunks,
    read_stealth_info,
    strip_comment_lines,
)
from src.nai_studio.domain.costs import (
    ANLAS_A,
    ANLAS_B,
    OPUS_FREE_PX,
    OPUS_FREE_STEPS,
    anlas_estimate,
    anlas_per_image,
)
from src.nai_studio.domain.model_presets import (
    MODELS,
    QUALITY_SUFFIX,
    QUALITY_SUFFIX_TEXT,
    UC_PRESETS,
    UC_PRESET_TEXT,
    merge_quality_suffix,
    merge_uc_preset,
    model_id_from_metadata,
    quality_suffix_text,
    restore_quality_prompt,
    split_quality_suffix,
    split_uc_preset,
    uc_preset_text,
)
from src.nai_studio.domain.nai_payload import (
    NOISE_SCHEDULES,
    RESOLUTIONS,
    SAMPLERS,
    V3_ONLY,
    V4_ONLY,
    annotate_nai_comment,
    build_nai_payload,
    fixed_seed,
    image_to_image_fields,
    is_v4_model,
    reference_fields,
    seed_for,
    variety_sigma,
    variety_sigma_value,
)
from src.nai_studio.domain.positioning import (
    normalize_position_mode,
    position_mode_uses_coords,
)
from src.nai_studio.domain.restoration import summarize_restore_queue
from src.nai_studio.domain.tokenization import (
    METASPACE,
    _BRACKET,
    _STATE,
    _WEIGHT,
    _viterbi,
    count_tokens,
    load_vocab,
)
from src.nai_studio.runtime import (
    JobStore,
    add_result,
    fingerprint_payload,
    from_legacy_job_record,
    new_job,
    reconcile_job,
    retry_job,
    transition_job,
    update_progress,
)
from src.nai_studio.runtime.diagnostics import (
    diagnostic_category,
    diagnostic_event_line,
    diagnostic_snapshot,
    parse_diagnostic_lines,
    redact_diagnostic_text,
)
from src.nai_studio.runtime.logging_config import (
    close_application_logging,
    configure_application_logging,
    resolve_application_log_path,
)
from src.nai_studio.runtime.data_files import (
    _atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    load_json_recover,
    load_settings_recover,
    quarantine_corrupt_settings,
    recoverable_remove,
    serialized_data_write,
    shared_data_transaction,
)
from src.nai_studio.runtime.live_state import LiveState as RuntimeLiveState
from src.nai_studio.services.legacy_bridge import (
    evidence_from_image_record,
    knowledge_assets_from_config,
    sequence_plan_from_setting,
    style_asset_from_record,
)
from src.nai_studio.services.evaluation_bridge import (
    append_evaluation_events,
    blind_match_event,
    fixed_board_event,
    lifecycle_event,
    project_legacy_evaluations,
    promotion_event,
)
from src.nai_studio.services.experiment_bridge import (
    expand_legacy_experiment_cells,
)
from src.nai_studio.services.experiment_execution_bridge import (
    legacy_execution_material,
    regenerate_legacy_execution_material,
)
from src.nai_studio.services.blueprint_execution_bridge import (
    single_generation_legacy_material,
)
from src.nai_studio.services.job_bridge import (
    make_job_command,
    project_comparison_progress,
    project_live_state,
)
from src.nai_studio.services.metadata_audit_adapter import (
    MetadataAuditAdapter,
    MetadataAuditLedgerError,
)
from src.nai_studio.services.character_bench import (
    apply_character_variation_candidates,
    reference_inset_canvas,
)
from src.nai_studio.services.prompt_bridge import (
    legacy_sequence_text,
    reroll_legacy_components,
    resolve_legacy_prompt,
)
from src.nai_studio.services.public_collection import (
    PublicCollectionManager as _PublicCollectionManager,
)
from src.nai_studio.services.resource_bridge import (
    export_legacy_resources,
    legacy_resource_import_plan,
)
from src.nai_studio.services.restoration_inputs import (
    folder_inventory_queue,
    folder_inventory_summary,
    image_batch_queue,
    image_inspect_queue,
    pack_import_queue,
)
from src.nai_studio.services.scene_catalog import scene_catalog
from src.nai_studio.services.result_promotion import (
    append_promotion_events,
    build_result_promotion,
    new_promotion_ledger,
)
from src.nai_studio.services.variation_bridge import (
    approved_proposal_to_legacy_candidates,
    character_asset_from_legacy_record,
    selected_variation_values,
    variation_plan_to_legacy_payload_material,
)
from src.nai_studio.domain.variations import accept_variation
from src.nai_studio.web.http_server import (
    ConfigRequestHandler,
    start_http_server,
)
from src.nai_studio.web.page_template import PAGE_TEMPLATE
from src.nai_studio.web.routes.assets import (
    AssetGetOperations,
    handle_asset_get,
)
from src.nai_studio.web.routes.catalog import (
    CatalogGetOperations,
    handle_catalog_get,
)
from src.nai_studio.web.routes.catalog_post import (
    CatalogPostOperations,
    handle_catalog_post,
)
from src.nai_studio.web.routes.collection_post import (
    CollectionPostOperations,
    handle_collection_post,
)
from src.nai_studio.web.routes.evaluation_post import (
    EvaluationPostOperations,
    handle_evaluation_post,
)
from src.nai_studio.web.routes.fragments_post import (
    FragmentPostOperations,
    handle_fragment_post,
)
from src.nai_studio.web.routes.generation import (
    GenerationGetOperations,
    handle_generation_get,
)
from src.nai_studio.web.routes.generation_post import (
    GenerationPostOperations,
    handle_generation_post,
)
from src.nai_studio.web.routes.recovery import (
    RecoveryGetOperations,
    handle_recovery_get,
)
from src.nai_studio.web.routes.recovery_post import (
    RecoveryPostOperations,
    handle_recovery_post,
)
from src.nai_studio.web.routes.settings_post import (
    SettingsPostOperations,
    handle_settings_post,
)
from src.nai_studio.web.routes.runtime import handle_runtime_get
from src.nai_studio.web.routes.runtime_post import (
    RuntimePostOperations,
    handle_runtime_post,
)

sys.stdout.reconfigure(encoding="utf-8")

# 프로그램 파일과 사용자 자료는 생명주기가 다르다. 설치 프로그램을 제거해도 설정·
# 캐릭터·세팅·수집물·생성물이 함께 사라지면 안 된다. 묶인 실행본은 기본적으로
# %LOCALAPPDATA%\NAI배치생성기\데이터 를 쓰고, 코드·CSS·토크나이저는 exe 옆에서 읽는다.
# 소스 실행은 개발 중인 기존 자료 위치를 바꾸지 않도록 예전처럼 소스 폴더를 쓴다.
PROGRAM_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)


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
UI_DIR = PROGRAM_DIR / "src" / "nai_studio" / "web" / "static"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

LEGACY_SETTINGS_FILE = BASE_DIR / "설정.txt"          # 원본 대조본은 공용
SETTINGS_FILE = PROFILE_DIR / "설정.json"
CONFIG_FILE = BASE_DIR / "asset_config.json"
STATE_FILE = PROFILE_DIR / "nsfw_seed_state.json"
COMPARE_PROGRESS_FILE = PROFILE_DIR / "비교생성-진행.json"
OUTPUT_BASE = PROFILE_DIR / "output"
LOG_FILE = resolve_application_log_path(PROFILE_DIR / "생성.log")
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

# 밴 예방 기본값. 전부 설정.json 의 `pace` 로 덮어쓸 수 있다 (관리 탭에서 조절).
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

log = configure_application_logging(LOG_FILE, stream=sys.stdout)


_JSON_IO_LOCK = threading.RLock()

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
    # ""는 구형 설정 호환 상태다. 읽을 때 use_coords로 파생하고 사용자가 세 모드 중
    # 하나를 직접 고른 뒤에만 ai/grid/coordinate를 저장한다.
    "position_mode": "",
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
    "cast_presets": [],         # 세팅 사이에서 재사용하는 캐릭터 조합: [{id, name, members}]
    # 프로젝트 공통 설계도는 기존 생성값을 대체하는 새 저장소가 아니다. 사용자가
    # 명시적으로 연결한 경우에만 승인 사본을 물려받고, 이후 현재 변경은 별도로 남긴다.
    "blueprint_projects": [],
    "blueprint_inheritance": {},
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



# 이미지 메타데이터 복원은 domain.image_metadata가 소유한다.


IMG_CACHE = BASE_DIR / "수집" / "이미지캐시"


# T5 토큰 계산은 domain.tokenization이 소유한다.


TOKENIZER_FILE = PROGRAM_DIR / "t5_tokenizer.json"


# Anlas 비용과 Opus 무료 조건은 domain.costs가 소유한다.


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


def resource_file_index(cfg):
    """명시적으로 내보낼 때만 현재 Vibe·Reference 재료를 읽는다."""
    files = {}
    for item in cfg.get("vibes", []):
        rid = Path(str(item.get("id") or "")).name
        if not rid:
            continue
        for suffix in (".png", ".vibe"):
            path = VIBE_DIR / f"{rid}{suffix}"
            if path.is_file():
                files[path.name] = (
                    path.read_text(encoding="ascii")
                    if suffix == ".vibe" else path.read_bytes()
                )
    for item in cfg.get("char_refs", []):
        rid = Path(str(item.get("id") or "")).name
        if not rid:
            continue
        path = VIBE_DIR / f"{rid}.ref.png"
        if path.is_file():
            files[path.name] = path.read_bytes()
    return files


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
        raw = r.get("_image_bytes")
        p = VIBE_DIR / f"{r.get('id','')}.ref.png"
        if raw is None:
            if not p.exists():
                if r.get("_required"):
                    raise ValueError("시험용 Character Reference 원본을 찾지 못했습니다.")
                continue
            raw = p.read_bytes()
        try:
            b64, cv = letterbox_ref(raw)
        except Exception as e:
            if r.get("_required"):
                raise ValueError(
                    f"시험용 Character Reference를 준비하지 못했습니다: {e}"
                ) from e
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
    active_vibes = [
        item for item in (cfg.get("vibes") or [])
        if isinstance(item, dict) and item.get("enabled")
    ]
    active_char_refs = [
        item for item in (cfg.get("char_refs") or [])
        if isinstance(item, dict) and item.get("enabled")
    ]
    if active_vibes and active_char_refs:
        raise ValueError(
            "NAI에서는 바이브와 캐릭터 레퍼런스를 동시에 사용할 수 없습니다. "
            "둘 중 하나를 꺼주세요."
        )
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
        if any(
            item.get("enabled") and item.get("_required")
            for item in (cfg.get("char_refs") or [])
            if isinstance(item, dict)
        ):
            raise
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
                    + ("" if cap > 2 else " (관리 → API 에 단부루 계정을 넣으면 6개까지)"))
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
                         "관리 → API 의 '부루 계정' 에 user_id 와 api_key 를 넣어 주세요."}
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
                    "error": f"{cfg['name']} 인증 실패({r.status_code}) — 관리 → API 의 "
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
_COMBOS = {
    "loaded": False, "rows": [], "search": [],
    "sources": {}, "tabs": {}, "seeded": 0,
}
_COMBOS_LOCK = threading.Lock()
_STYLE_TX_LOCK = threading.RLock()

# 그림체는 저장 위치나 입력 경로가 달라도 아래 생성 설정까지 포함한 한 묶음이다.
# 수집 JSON의 NAI 메타 이름(scale/noise_schedule)과 사용자 그림체 파일의 화면 설정
# 이름(cfg_scale/scheduler)을 같은 열쇠로 맞춘다.
STYLE_BUNDLE_SETTING_KEYS = (
    "model", "width", "height", "cfg_scale", "cfg_rescale", "steps",
    "sampler", "scheduler", "variety", "uc_preset", "quality_toggle",
    "smea", "smea_dyn", "dynamic_thresholding", "uncond_scale",
    "controlnet_strength", "prefer_brownian",
    "deliberate_euler_ancestral_bug", "legacy_v3_extend", "use_coords",
    "position_mode",
)
_STYLE_SETTING_ALIASES = {
    "cfg_scale": ("cfg_scale", "scale"),
    "scheduler": ("scheduler", "noise_schedule"),
    "variety": ("variety", "variety_plus", "skip_cfg_above_sigma"),
    "smea": ("smea", "sm"),
    "smea_dyn": ("smea_dyn", "sm_dyn"),
}
_STYLE_INT_SETTINGS = {"width", "height", "steps", "uc_preset"}
_STYLE_FLOAT_SETTINGS = {
    "cfg_scale", "cfg_rescale", "uncond_scale", "controlnet_strength",
}
_STYLE_BOOL_SETTINGS = {
    "variety", "quality_toggle", "smea", "smea_dyn",
    "dynamic_thresholding", "prefer_brownian",
    "deliberate_euler_ancestral_bug", "legacy_v3_extend", "use_coords",
}


def _style_value(record, *names):
    for name in names:
        if record.get(name) is not None:
            return record.get(name)
    return None


def canonical_style_settings(record):
    """수집 메타·사용자 그림체·비교 레시피의 설정 이름을 한 규격으로 맞춘다."""
    record = record if isinstance(record, dict) else {}
    raw = (_style_value(record, "settings", "설정", "params") or {})
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in STYLE_BUNDLE_SETTING_KEYS:
        names = _STYLE_SETTING_ALIASES.get(key, (key,))
        value = next((raw[name] for name in names
                      if name in raw and raw[name] is not None), None)
        if value is None:
            continue
        try:
            if key in _STYLE_INT_SETTINGS:
                value = int(value)
            elif key in _STYLE_FLOAT_SETTINGS:
                value = float(value)
            elif key in _STYLE_BOOL_SETTINGS:
                value = (value.strip().lower() in ("1", "true", "yes", "on")
                         if isinstance(value, str) else bool(value))
            elif key == "model":
                value = model_id_from_metadata(
                    value, str(value or "nai-diffusion-4-5-full"))
            else:
                value = str(value)
        except (TypeError, ValueError, OverflowError):
            value = str(value)
        out[key] = value
    return out


def style_bundle_signature(record):
    """그림체의 베이스+네거티브+생성 설정 불가분 묶음을 식별한다."""
    record = record if isinstance(record, dict) else {}
    prompt = _style_value(record, "base", "prompt", "프롬프트")
    if prompt in (None, ""):
        prompt = record.get("combo") or ""
    negative = _style_value(record, "negative", "네거티브") or ""
    settings = canonical_style_settings(record)
    if not (str(prompt or "") or str(negative or "") or settings):
        fallback = {
            "artists": record.get("artists") or [],
            "combo": record.get("combo") or "",
            "seed": (record.get("params") or {}).get("seed")
                if isinstance(record.get("params"), dict) else None,
        }
        return json.dumps(
            {"legacy": fallback}, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str)
    return json.dumps(
        {"prompt": str(prompt or ""), "negative": str(negative or ""),
         "settings": settings},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def character_bundle_signature(record):
    """캐릭터 전체 프롬프트와 변형·참조 자원을 한 묶음으로 식별한다."""
    record = record if isinstance(record, dict) else {}
    return json.dumps({
        "prompt": str(_style_value(record, "female", "prompt", "외형") or ""),
        "outfit": str(_style_value(record, "clothed", "outfit", "착의") or ""),
        "negative": str(_style_value(record, "negative", "네거티브") or ""),
        "variant": copy.deepcopy(record.get("variant") or {}),
        "variants": copy.deepcopy(record.get("variants") or []),
        "reference_ids": copy.deepcopy(
            record.get("reference_ids") or record.get("reference_refs") or []),
        "vibe_ids": copy.deepcopy(
            record.get("vibe_ids") or record.get("vibe_refs") or []),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _style_row_digest(row):
    return hashlib.sha256(json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")).hexdigest()


def _merge_style_evidence(existing, incoming):
    """같은 묶음의 새 이미지·출처만 더하고 기존 원문과 설정은 덮지 않는다."""
    merged = copy.deepcopy(existing)
    old_images = list(merged.get("images") or [])
    for image in incoming.get("images") or []:
        if image not in old_images:
            old_images.append(image)
    if old_images:
        merged["images"] = old_images
    evidence = list(merged.get("evidence") or [])
    item = {
        key: copy.deepcopy(incoming.get(key))
        for key in ("title", "source", "url", "posted_at", "images")
        if incoming.get(key) not in (None, "", [])
    }
    if item:
        marker = json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str)
        known = {
            json.dumps(x, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), default=str)
            for x in evidence if isinstance(x, dict)
        }
        if marker not in known:
            evidence.append(item)
    if evidence:
        merged["evidence"] = evidence
    evidence_records = list(merged.get("evidence_records") or [])
    known_records = {
        str(item.get("id") or "")
        for item in evidence_records if isinstance(item, dict)
    }
    for record in incoming.get("evidence_records") or []:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or "")
        if record_id and record_id not in known_records:
            evidence_records.append(copy.deepcopy(record))
            known_records.add(record_id)
    if evidence_records:
        merged["evidence_records"] = evidence_records
    return merged

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


def compose_artist_workspace(rows, mode="custom", curve_start=1.2,
                             curve_end=0.8, seed=""):
    """작가 조합 작업공간의 행을 NAI 가중치 prompt로 만든다.

    순서는 사용자가 정한 실제 prompt 순서다. ``locked`` 행은 균형·곡선·무작위
    모드에서도 고정하고, 무작위는 행별 min/max 안에서만 뽑는다.
    """
    if not isinstance(rows, list):
        raise ValueError("작가 목록 형식이 올바르지 않습니다.")
    mode = str(mode or "custom").strip().lower()
    if mode not in {"custom", "balanced", "curve", "random"}:
        raise ValueError("알 수 없는 가중치 방식입니다.")
    cleaned, seen = [], set()

    def number(value, fallback=1.0):
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = float(fallback)
        if not math.isfinite(result):
            raise ValueError("가중치는 유한한 숫자여야 합니다.")
        return result

    for raw in rows[:20]:
        if not isinstance(raw, dict):
            continue
        name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()
        if not name:
            continue
        if len(name) > 60 or any(mark in name for mark in (",", "\n", "\r", "::")):
            raise ValueError(f"작가 이름 형식이 올바르지 않습니다: {name[:30]}")
        key = name.casefold()
        if key in seen:
            raise ValueError(f"같은 작가가 두 번 들어 있습니다: {name}")
        seen.add(key)
        weight = number(raw.get("weight"), 1.0)
        low = number(raw.get("min"), weight)
        high = number(raw.get("max"), weight)
        if low > high:
            low, high = high, low
        cleaned.append({
            "name": name, "weight": weight, "min": low, "max": high,
            "locked": bool(raw.get("locked")),
        })
    if not cleaned:
        return {"rows": [], "combo": ""}

    unlocked = [row for row in cleaned if not row["locked"]]
    if mode == "balanced":
        for row in unlocked:
            row["weight"] = 1.0
    elif mode == "curve":
        start, end = number(curve_start, 1.2), number(curve_end, 0.8)
        for index, row in enumerate(unlocked):
            ratio = index / max(1, len(unlocked) - 1)
            row["weight"] = start + (end - start) * ratio
    elif mode == "random":
        rng = random.Random(str(seed)) if str(seed) else random.SystemRandom()
        for row in unlocked:
            row["weight"] = rng.uniform(row["min"], row["max"])

    def weight_text(value):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return "0" if text in {"-0", ""} else text

    combo = ", ".join(
        f"{weight_text(row['weight'])}::artist:{row['name']}::"
        for row in cleaned
    )
    return {"rows": cleaned, "combo": combo}


def artist_workspace_request(data):
    """작가 조합 UI의 parse/compose를 한 규칙으로 처리한다."""
    if not isinstance(data, dict):
        raise ValueError("잘못된 요청 형식입니다.")
    action = str(data.get("action") or "compose")
    base = str(data.get("base") or "")
    if action == "parse":
        artists, _ = parse_artist_combo(base)
        rows = [{
            "name": name, "weight": weight if weight is not None else 1.0,
            "min": weight if weight is not None else 0.7,
            "max": weight if weight is not None else 1.3,
            "locked": False,
        } for weight, name in artists]
        return {"ok": True, "rows": rows}
    result = compose_artist_workspace(
        data.get("rows") or [], mode=data.get("mode"),
        curve_start=data.get("curve_start"), curve_end=data.get("curve_end"),
        seed=data.get("seed"),
    )
    _, rest = parse_artist_combo(base)
    prompt = _join_tags(result["combo"], ", ".join(rest))
    return {"ok": True, **result, "prompt": prompt}


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
        search = []
        sources, tabs, seeded_count = {}, {}, 0
        for row in rows:
            if not isinstance(row, dict):
                search.append("")
                continue
            search.append((
                str(row.get("combo") or "") + " "
                + str(row.get("title") or "") + " "
                + str(row.get("source") or "") + " "
                + str(row.get("rest") or "") + " "
                + str(row.get("negative") or "")
            ).casefold())
            source = row.get("source") or "도랑"
            sources[source] = sources.get(source, 0) + 1
            tab = row.get("tab") or ""
            if tab:
                tabs[tab] = tabs.get(tab, 0) + 1
            if (row.get("params") or {}).get("seed"):
                seeded_count += 1
        _COMBOS.update({
            "loaded": True, "rows": rows, "search": search,
            "sources": sources, "tabs": tabs, "seeded": seeded_count,
        })
    return _COMBOS["rows"]


@serialized_data_write(lambda: STYLE_FILE.parent.parent)
def add_style(rec, import_info=None, return_detail=False):
    """큰 그림체 묶음을 비파괴 임포트한다.

    같은 묶음은 기존 레코드를 갈아치우지 않고 새 이미지·출처 근거만 더한다.
    import_info가 있으면 단건 이미지도 자료팩처럼 독립적으로 되돌릴 판을 남긴다.
    """
    with _STYLE_TX_LOCK:
        # 다른 실행본이 먼저 저장했을 수 있으므로 프로세스 잠금을 얻은 뒤 캐시가
        # 아니라 디스크 최신판에서 시작한다.
        forget_collection_caches()
        rows = list(load_combos())
        wanted = style_bundle_signature(rec)
        action, changed, before, row_key = "added", True, None, ""
        for i, r in enumerate(rows):
            if not isinstance(r, dict) or style_bundle_signature(r) != wanted:
                continue
            before = copy.deepcopy(r)
            merged = _merge_style_evidence(r, rec)
            changed = merged != r
            if changed:
                rows[i] = merged
                action = "updated"
            else:
                action = "existing"
            row_key, _ = _row_key(r, "id")
            rec = rows[i]
            break
        else:
            rec = copy.deepcopy(rec)
            if not rec.get("id"):
                rec["id"] = "style-" + hashlib.sha256(
                    wanted.encode("utf-8")).hexdigest()[:20]
            row_key, _ = _row_key(rec, "id")
            rows.insert(0, rec)

        if changed:
            STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(STYLE_FILE, rows, indent=None)
        batch_id = None
        if changed and isinstance(import_info, dict):
            batch = {
                "kind": str(import_info.get("kind") or "import"),
                "file": str(import_info.get("file") or "자료"),
                "lists": {}, "files": copy.deepcopy(import_info.get("files") or {}),
                "installed": [], "list_updates": [], "요약": "",
            }
            if before is None:
                batch["lists"] = {"그림체.json": [row_key]}
                batch["요약"] = "그림체: 새 묶음 1건"
            else:
                batch["list_updates"] = [{
                    "stem": "그림체.json", "key": row_key,
                    "before": before, "after_sha256": _style_row_digest(rec),
                }]
                batch["요약"] = "그림체: 같은 묶음에 새 근거를 더함"
            batch_id = record_import_batch(batch)
        if changed:
            forget_collection_caches()
        detail = {
            "total": len(rows), "action": action, "changed": changed,
            "id": rec.get("id"), "batch": batch_id,
        }
        return detail if return_detail else len(rows)


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
    q = (q or "").strip().casefold()
    hit = rows
    if q:
        terms = [t for t in q.split() if t]
        cached = (_COMBOS.get("search") or []) if rows is _COMBOS.get("rows") else []
        if len(cached) != len(rows):
            cached = [(
                str(r.get("combo") or "") + " "
                + str(r.get("title") or "") + " "
                + str(r.get("source") or "") + " "
                + str(r.get("rest") or "") + " "
                + str(r.get("negative") or "")
            ).casefold() for r in rows]
        hit = [r for r, text in zip(rows, cached)
               if all(term in text for term in terms)]
    if tab and tab != "all":
        hit = [r for r in hit if (r.get("tab") or "") == tab]
    if source and source != "all":
        hit = [r for r in hit if (r.get("source") or "") == source]
    if seeded in ("1", "true", True):
        hit = [r for r in hit if (r.get("params") or {}).get("seed")]
    # 평가 필터 — fav(즐겨찾기만) · rated(별점 매긴 것만) · hideblock(차단 숨김)
    rating_cache = {}

    def rating_for(row):
        key = id(row)
        if key not in rating_cache:
            rating_cache[key] = style_rating(row, ratings)
        return rating_cache[key]

    if rating:
        if rating == "fav":
            hit = [r for r in hit if rating_for(r)["fav"]]
        elif rating == "rated":
            hit = [r for r in hit if rating_for(r)["score"]]
        elif rating == "hideblock":
            hit = [r for r in hit if not rating_for(r)["block"]]
    if sort in STYLE_SORTS and sort != "default":
        rev = sort in {"newest"}
        hit = sorted(hit, key=STYLE_SORTS[sort], reverse=rev)

    def tally(key, default=""):
        if rows is _COMBOS.get("rows"):
            if key == "source" and _COMBOS.get("sources") is not None:
                return dict(_COMBOS["sources"])
            if key == "tab" and _COMBOS.get("tabs") is not None:
                return dict(_COMBOS["tabs"])
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
        item["_rate"] = rating_for(r)
        items.append(item)
    seeded_total = (
        int(_COMBOS.get("seeded") or 0)
        if rows is _COMBOS.get("rows")
        else sum(1 for r in rows if (r.get("params") or {}).get("seed"))
    )
    return {"total": len(rows), "matched": len(hit),
            "sources": tally("source", "도랑"), "tabs": tally("tab"),
            "seeded": seeded_total,
            "items": items, "offset": offset}


LIBRARY_REVIEW_FILE = BASE_DIR / "수집" / "자료정리.json"
_LIBRARY_REVIEW_LOCK = threading.RLock()
LIBRARY_REVIEW_STATUSES = {"pending", "reviewed", "hold"}


def load_library_review(strict=False):
    if not LIBRARY_REVIEW_FILE.is_file():
        return {"schema": "nais-library-review/v1", "items": {}}
    try:
        data = load_json_recover(LIBRARY_REVIEW_FILE)
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            raise ValueError("자료 정리 장부 형식이 올바르지 않습니다.")
        return data
    except Exception as e:
        log.warning(f"자료 정리 장부를 읽지 못했습니다: {e}")
        # 보기 화면은 원본 자료를 계속 보여 주되, 쓰기에서는 손상된 장부를 빈 장부로
        # 오인해 덮지 않는다. .bak도 못 살렸다면 사용자가 복구할 증거를 그대로 남긴다.
        if strict:
            raise ValueError(
                "자료 정리 장부가 손상되어 저장을 멈췄습니다. "
                "자료정리.json과 .bak을 확인하세요.") from e
        return {"schema": "nais-library-review/v1", "items": {}}


def library_review_revision(data):
    raw = json.dumps(
        data or {}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_library_labels(value):
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("자료 이름표는 문자열 또는 목록이어야 합니다.")
    out = []
    for label in value:
        label = unicodedata.normalize("NFKC", str(label or "")).strip()
        if not label:
            continue
        if len(label) > 40:
            raise ValueError("자료 이름표는 40자 이하여야 합니다.")
        if label not in out:
            out.append(label)
        if len(out) >= 20:
            break
    return out


def organize_library_items(request):
    """큰 묶음 원문을 건드리지 않고 검토 상태·이름표 장부만 원자 저장한다."""
    if not isinstance(request, dict):
        raise ValueError("자료 정리 요청 형식이 올바르지 않습니다.")
    ids = request.get("ids") or []
    if not isinstance(ids, list):
        raise ValueError("정리할 자료 id는 목록이어야 합니다.")
    ids = list(dict.fromkeys(str(value or "").strip() for value in ids))
    ids = [value for value in ids if value]
    if not ids:
        raise ValueError("정리할 자료를 먼저 고르세요.")
    if len(ids) > 500:
        raise ValueError("한 번에 정리할 자료는 500개까지입니다.")
    if any(len(value) > 240 or ":" not in value for value in ids):
        raise ValueError("자료 id 형식이 올바르지 않습니다.")
    action = str(request.get("action") or "apply")
    with _LIBRARY_REVIEW_LOCK:
        data = load_library_review(strict=True)
        revision = library_review_revision(data)
        expected = str(request.get("expect_revision") or "")
        if expected and expected != revision:
            return {
                "ok": False, "conflict": True, "revision": revision,
                "error": "다른 화면에서 자료 정리가 먼저 바뀌었습니다. 목록을 새로 불러와 다시 적용하세요.",
            }
        items = data.setdefault("items", {})
        before = {item_id: copy.deepcopy(items.get(item_id)) for item_id in ids}
        if action == "restore":
            restore = request.get("records")
            if not isinstance(restore, dict):
                raise ValueError("되돌릴 자료 정리 기록이 없습니다.")
            for item_id in ids:
                old = restore.get(item_id)
                if isinstance(old, dict):
                    items[item_id] = copy.deepcopy(old)
                else:
                    items.pop(item_id, None)
        elif action == "apply":
            raw_status = request.get("status")
            status = str(raw_status or "").strip()
            if status and status not in LIBRARY_REVIEW_STATUSES:
                raise ValueError("알 수 없는 검토 상태입니다.")
            labels = normalize_library_labels(request.get("labels"))
            label_mode = str(request.get("label_mode") or "add")
            if label_mode not in {"add", "replace", "clear"}:
                raise ValueError("알 수 없는 이름표 적용 방식입니다.")
            for item_id in ids:
                record = copy.deepcopy(items.get(item_id) or {})
                if status:
                    record["status"] = status
                if label_mode == "clear":
                    record["labels"] = []
                elif label_mode == "replace":
                    record["labels"] = labels
                elif labels:
                    record["labels"] = normalize_library_labels(
                        list(record.get("labels") or []) + labels)
                record["updated_at"] = datetime.now().isoformat(timespec="seconds")
                if (record.get("status", "pending") == "pending"
                        and not record.get("labels")):
                    items.pop(item_id, None)
                else:
                    items[item_id] = record
        else:
            raise ValueError("알 수 없는 자료 정리 동작입니다.")
        data["schema"] = "nais-library-review/v1"
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(LIBRARY_REVIEW_FILE, data)
        return {
            "ok": True, "changed": len(ids), "before": before,
            "revision": library_review_revision(data),
        }


def search_library(cfg, spec, q="", kind="", source="", limit=100, offset=0,
                   review="", label=""):
    """입력 경로와 저장 위치가 다른 큰 묶음을 한 자료실 규격으로 검색한다.

    전체 레코드는 서버 안에서만 검색하고 현재 페이지의 적용 필드만 보낸다. 수천 건의
    긴 프롬프트·raw metadata를 브라우저 STATE에 복제하지 않아 자료 탭을 여는 비용이
    자료 수에 비례해 폭증하지 않는다.
    """
    try:
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit, offset = 100, 0
    rows = []
    for char in (cfg or {}).get("characters", []):
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or "(무명)")
        character_images = []
        for image_ref in [
            char.get("representative"),
            char.get("representative_image"),
            *(char.get("images") if isinstance(char.get("images"), list) else []),
            *(char.get("evidence_images")
              if isinstance(char.get("evidence_images"), list) else []),
            *(char.get("variation_images")
              if isinstance(char.get("variation_images"), list) else []),
        ]:
            if isinstance(image_ref, str) and image_ref and image_ref not in character_images:
                character_images.append(image_ref)
        rows.append({
            "id": "character:" + str(char.get("id") or name),
            "kind": "캐릭터", "store": "character", "name": name,
            "prompt": str(char.get("female") or ""),
            "negative": str(char.get("negative") or ""),
            "outfit": str(char.get("clothed") or ""),
            "source": str(char.get("source") or "내 캐릭터"),
            "groups": char.get("groups") if isinstance(char.get("groups"), dict) else {},
            "images": character_images,
            "evidence": copy.deepcopy(char.get("evidence"))
            if "evidence" in char else None,
            "ref": {
                key: copy.deepcopy(char.get(key))
                for key in (
                    "id", "name", "female", "clothed", "negative", "groups",
                    "source", "folder_id", "subfolder_id",
                    "variant", "variants", "reference_ids", "vibe_ids",
                    "selected_variant_id", "representative", "images",
                    "evidence", "evidence_ids", "evidence_refs",
                    "evidence_images", "variation_images",
                ) if key in char
            },
        })
    for index, style in enumerate(list_styles(spec or {})):
        name = str(style.get("name") or f"그림체 {index + 1}")
        rows.append({
            "id": "preset:" + name, "kind": "그림체", "store": "preset",
            "name": name, "prompt": str(style.get("prompt") or ""),
            "negative": str(style.get("negative") or ""),
            "source": "내 프리셋", "settings": copy.deepcopy(style.get("settings") or {}),
            "images": [], "ref": copy.deepcopy(style),
        })
    card_fields = (
        "id", "title", "source", "tab", "posted_at", "recommend", "views",
        "url", "count", "combo", "artists", "base", "negative",
        "negative_full", "params", "images",
    )
    for index, style in enumerate(load_combos()):
        if not isinstance(style, dict):
            continue
        compact = {key: copy.deepcopy(style[key]) for key in card_fields if key in style}
        if isinstance(compact.get("images"), list):
            compact["images"] = compact["images"][:1]
        name = str(
            style.get("title") or style.get("combo")
            or f"수집 그림체 {index + 1}")
        # 예전 자료에는 id가 없다. 목록 순번은 자료팩 병합 때 바뀌므로 검토 장부의
        # 열쇠로 쓰면 안 된다. 실제 카드 내용으로 만든 지문은 재시작·재정렬 뒤에도 같다.
        fallback_id = hashlib.sha256(json.dumps(
            compact, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:20]
        rows.append({
            "id": "collected:" + str(style.get("id") or fallback_id),
            "kind": "그림체", "store": "collected", "name": name,
            "prompt": str(style.get("base") or style.get("combo") or ""),
            "negative": str(style.get("negative") or ""),
            "source": str(style.get("source") or "수집 자료"),
            "settings": copy.deepcopy(style.get("params") or {}),
            "images": list(style.get("images") or [])[:1],
            "ref": compact,
        })
    for index, recipe in enumerate(load_recipes()):
        if not isinstance(recipe, dict):
            continue
        compact = {
            key: copy.deepcopy(recipe[key])
            for key in (
                "id", "title", "axis", "concept", "concept_ko", "domain",
                "tags", "positive", "negative", "url", "images",
            ) if key in recipe
        }
        if isinstance(compact.get("images"), list):
            compact["images"] = compact["images"][:2]
        fallback_id = hashlib.sha256(json.dumps(
            compact, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:20]
        rows.append({
            "id": "recipe:" + str(recipe.get("id") or fallback_id),
            "kind": "레시피", "store": "recipe",
            "name": str(recipe.get("title") or recipe.get("concept_ko")
                        or f"레시피 {index + 1}"),
            "prompt": str(recipe.get("positive") or ""),
            "negative": str(recipe.get("negative") or ""),
            "source": "공유 레시피",
            "images": list(recipe.get("images") or [])[:1],
            "ref": compact,
        })
    for setting in list_settings():
        data = setting.get("data") if isinstance(setting.get("data"), dict) else {}
        scenes = data.get("씬") if isinstance(data.get("씬"), dict) else {}
        scene_names = [
            str(scene.get("name") or scene.get("이름") or "")
            for scene in scenes.values() if isinstance(scene, dict)
        ]
        rows.append({
            "id": "setting:" + str(setting.get("file") or setting.get("name")),
            "kind": "세팅", "store": "setting",
            "name": str(setting.get("name") or "(이름 없는 세팅)"),
            "prompt": ", ".join(scene_names),
            "negative": str(data.get("네거티브") or ""),
            "source": "내 세팅",
            "meta": {
                "mode": str(setting.get("mode") or "단독"),
                "scenes": len(scenes),
                "stages": list(data.get("단계명") or []),
                "options": list((data.get("옵션") or {}).keys())
                if isinstance(data.get("옵션"), dict) else [],
            },
            "ref": {
                "name": str(setting.get("name") or ""),
                "file": str(setting.get("file") or ""),
            },
        })
    for run in comparison_runs(cfg, limit=200).get("runs", []):
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "상태 미확인")
        completed = int(run.get("completed") or 0)
        total = int(run.get("total") or completed)
        rows.append({
            "id": "generation:" + str(run.get("folder") or run.get("name")),
            "kind": "생성 기록", "store": "generation",
            "name": str(run.get("mode_label") or run.get("name") or "비교 생성"),
            "prompt": f"{status} · {completed}/{total}장",
            "negative": "", "source": "비교 생성",
            "meta": {
                "status": status, "completed": completed, "total": total,
                "updated_at": str(run.get("updated_at") or ""),
                "resumable": bool(run.get("resumable")),
            },
            "ref": copy.deepcopy(run),
        })

    review_data = load_library_review()
    review_items = review_data.get("items") or {}
    review_counts = {"pending": 0, "reviewed": 0, "hold": 0}
    all_labels = {}
    for row in rows:
        record = review_items.get(row["id"])
        if not isinstance(record, dict):
            record = {}
        status = str(record.get("status") or "pending")
        if status not in LIBRARY_REVIEW_STATUSES:
            status = "pending"
        try:
            labels = normalize_library_labels(record.get("labels"))
        except ValueError:
            # 한 항목의 낡거나 손상된 이름표 때문에 수천 건 자료실 전체를 막지 않는다.
            labels = []
        row["review_status"] = status
        row["labels"] = labels
        review_counts[status] += 1
        for value in labels:
            all_labels[value] = all_labels.get(value, 0) + 1

    all_sources = {}
    all_kinds = {}
    for row in rows:
        all_sources[row["source"]] = all_sources.get(row["source"], 0) + 1
        all_kinds[row["kind"]] = all_kinds.get(row["kind"], 0) + 1
    terms = [
        part for part in re.split(
            r"\s+", unicodedata.normalize("NFKC", str(q or "")).strip().casefold())
        if part
    ]
    matched = []
    for row in rows:
        if kind and kind not in {"all", row["kind"]}:
            continue
        if source and source not in {"all", row["source"]}:
            continue
        if review and review not in {"all", row["review_status"]}:
            continue
        if label and label not in row["labels"]:
            continue
        if terms:
            haystack = unicodedata.normalize("NFKC", " ".join([
                row.get("name", ""), row.get("prompt", ""), row.get("negative", ""),
                row.get("outfit", ""), row.get("source", ""),
                " ".join(row.get("labels") or []), row.get("review_status", ""),
                json.dumps(row.get("meta") or {}, ensure_ascii=False),
            ])).casefold()
            if not all(term in haystack for term in terms):
                continue
        matched.append(row)
    page = matched[offset:offset + limit]
    return {
        "ok": True, "total": len(rows), "matched": len(matched),
        "offset": offset, "items": page, "sources": all_sources,
        "kinds": all_kinds, "review_counts": review_counts,
        "labels": all_labels, "revision": library_review_revision(review_data),
    }


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


def setting_content_revision(data):
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


@serialized_setting_write
def duplicate_setting_scene(name, scene_id, expect_revision=""):
    """장면 하나의 모든 필드를 복제한다. 아직 저장하지 않은 화면 값은 대상이 아니다."""
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅 파일을 찾을 수 없습니다."}
    pack = load_json_recover(p)
    revision = setting_content_revision(pack)
    if expect_revision and str(expect_revision) != revision:
        return {
            "ok": False, "conflict": True,
            "error": "다른 저장이 먼저 반영되어 장면을 복제하지 않았습니다. 다시 열어 확인해주세요.",
        }
    scenes = pack.get("씬") or {}
    scene_id = str(scene_id)
    source = scenes.get(scene_id)
    if not isinstance(source, dict):
        return {"ok": False, "error": f"{scene_id}번 장면을 찾을 수 없습니다."}
    used = set(used_scene_nums())
    try:
        candidate = int(scene_id) + 1
    except ValueError:
        candidate = max(used, default=99) + 1
    while candidate in used:
        candidate += 1
    clone = copy.deepcopy(source)
    root = str(clone.get("name") or "장면").strip() + " 사본"
    names = {
        str(scene.get("name") or "").casefold()
        for scene in scenes.values() if isinstance(scene, dict)
    }
    clone_name = root
    serial = 2
    while clone_name.casefold() in names:
        clone_name = f"{root} {serial}"
        serial += 1
    clone["name"] = clone_name
    new_id = str(candidate)
    scenes[new_id] = clone
    pack["씬"] = scenes
    atomic_write_json(p, pack, indent=1)
    return {
        "ok": True, "setting": name, "new_id": new_id,
        "name": clone_name, "scene_sha256": setting_content_revision(clone),
        "revision": setting_content_revision(pack),
    }


@serialized_setting_write
def undo_duplicate_setting_scene(name, scene_id, scene_sha256,
                                 expect_revision=""):
    """방금 복제한 장면이 그대로일 때만 제거한다."""
    p = setting_path(name)
    if not p:
        return {"ok": False, "error": "세팅 파일을 찾을 수 없습니다."}
    pack = load_json_recover(p)
    revision = setting_content_revision(pack)
    if expect_revision and str(expect_revision) != revision:
        return {
            "ok": False, "conflict": True,
            "error": "복제 뒤 다른 저장이 반영되어 자동으로 취소하지 않았습니다.",
        }
    scene_id = str(scene_id)
    scene = (pack.get("씬") or {}).get(scene_id)
    if not isinstance(scene, dict):
        return {"ok": False, "error": "취소할 복제 장면을 찾을 수 없습니다."}
    if not scene_sha256 or setting_content_revision(scene) != str(scene_sha256):
        return {
            "ok": False, "conflict": True,
            "error": "복제한 장면이 이미 수정되어 자동으로 지우지 않았습니다.",
        }
    pack["씬"].pop(scene_id, None)
    atomic_write_json(p, pack, indent=1)
    return {
        "ok": True, "setting": name, "removed_id": scene_id,
        "revision": setting_content_revision(pack),
    }


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
# 수집물(그림체·레시피·작가통계·예시 그림)은 양이 커서 프로그램 본체와 나눠
# 별도 자료팩으로 다룬다.
# 받는 쪽은 `배포준비.py --자료팩` 결과를 여기로 넣는다.
#
# ⚠ **덮어쓰지 않고 없는 것만 더한다.** 받는 사람이 이미 자기 자료를 갖고 있을 수 있고
#   (사용자는 그림체 1,600건을 따로 정리 중이다), 가져온 팩이 그걸 지우면 안 된다.
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
        if p in ("수집", "태그", "세팅", "캐릭터"):
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


def _datapack_match_key(item, primary):
    """자료팩 충돌 판정은 id/tag를 우선하고, 없을 때만 사람이 보는 이름을 쓴다."""
    value = item.get(primary)
    if value not in (None, ""):
        return str(value)
    for field in ("id", "이름", "name", "title", "tag"):
        value = item.get(field)
        if value not in (None, ""):
            return f"{field}={value}"
    return _row_key(item, primary)[0]


def _merge_list_json(path, incoming, key, overwrite=False, replace_keys=None):
    """열쇠 기준으로 합친다 → 무슨 일이 있었는지 세어서 돌려준다.

    ⚠ **'못 넣음' 을 '이미 있음' 으로 뭉뚱그리지 않는다.** 예전엔 열쇠 없는 항목이
      조용히 버려지면서 '이미 있음' 으로 세어져, 아무것도 안 들어왔는데 중복인 것처럼
      보였다 (실제로 겪은 거짓 보고다)."""
    old = []
    if path.exists():
        try:
            got = load_json_recover(path)
            if not isinstance(got, list):
                raise ValueError(f"{path.name}이 목록이 아니라 가져오기를 중단했습니다.")
            old = got
        except Exception:
            # 주 파일과 백업을 둘 다 못 읽으면 빈 목록으로 덮어쓰지 않는다.
            # 사용자가 가진 자료 전체를 "새 파일"로 오인해 날리는 것보다 가져오기를
            # 실패시키는 편이 안전하다.
            raise ValueError(f"{path.name}과 백업을 읽지 못해 가져오기를 중단했습니다.")
    idx = {}
    for i, x in enumerate(old):
        if isinstance(x, dict):
            kk = _datapack_match_key(x, key)
            idx.setdefault(kk, i)
    n = {"새로": 0, "같음": 0, "다름": 0, "열쇠없음": 0, "항목아님": 0, "덮어씀": 0}
    added_keys, updates = [], []
    replace_keys = set(map(str, replace_keys or ()))
    for x in incoming:
        if not isinstance(x, dict):
            n["항목아님"] += 1
            continue
        raw_key, made = _row_key(x, key)
        kk = _datapack_match_key(x, key)
        made = made and kk.startswith("가져옴-")
        if made:
            n["열쇠없음"] += 1           # 버리진 않는다 — 내용 열쇠로 넣는다
        if kk in idx:
            same = old[idx[kk]] == x
            if same:
                n["같음"] += 1
            elif overwrite or kk in replace_keys:
                before = copy.deepcopy(old[idx[kk]])
                old[idx[kk]] = x
                n["덮어씀"] += 1
                updates.append({
                    "key": kk,
                    "match_key": True,
                    "before": before,
                    "after_sha256": _style_row_digest(x),
                })
            else:
                n["다름"] += 1           # 기존 것을 지킨다. 몇 건인지는 알려 준다
            continue
        idx[kk] = len(old)
        old.append(x)
        # 신규 제거 장부는 옛 undo와 호환되는 원래 _row_key를 계속 쓴다.
        added_keys.append(raw_key)
        n["새로"] += 1
    added = n["새로"] + n["덮어씀"]
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, old, indent=None)
    return n, added_keys, updates


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


def record_import_batch(batch):
    """입력 경로와 무관한 한 번의 임포트를 기존 장착·undo 장부에 남긴다."""
    batch = copy.deepcopy(batch) if isinstance(batch, dict) else {}
    changed = any(batch.get(key) for key in (
        "lists", "files", "installed", "list_updates", "characters"))
    if not changed:
        return None
    batch.setdefault("id", f"{int(time.time())}-{os.urandom(4).hex()}")
    batch.setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
    batch.setdefault("file", "자료")
    batch.setdefault("kind", "datapack")
    batch.setdefault("lists", {})
    batch.setdefault("files", {})
    batch.setdefault("installed", [])
    batch.setdefault("list_updates", [])
    batch.setdefault("characters", [])
    batch.setdefault("새로", (
        sum(len(v) for v in batch["lists"].values())
        + sum(len(v) for v in batch["files"].values())
        + len(batch["installed"])
        + len(batch["characters"])
    ))
    rows = load_pack_log()
    rows.append(batch)
    save_pack_log(rows)
    return batch["id"]


DATAPACK_SCHEMA = "nais-datapack/v1"
DATA_INDEX_SCHEMA = "nais-data-index/v1"
_DATA_INDEX_CACHE = {"path": None, "mtime_ns": None, "value": None}


def _data_index_path():
    return BASE_DIR / "수집" / "자료색인.json"


def _load_data_index_cached():
    """큰 색인을 요청마다 다시 역직렬화하지 않고 파일 변경 때만 새로 읽는다."""
    path = _data_index_path()
    if not path.is_file():
        return None
    stamp = path.stat().st_mtime_ns
    key = str(path.resolve())
    if (
        _DATA_INDEX_CACHE["path"] == key
        and _DATA_INDEX_CACHE["mtime_ns"] == stamp
        and isinstance(_DATA_INDEX_CACHE["value"], dict)
    ):
        return _DATA_INDEX_CACHE["value"]
    value = load_json_recover(path)
    _DATA_INDEX_CACHE.update(
        {"path": key, "mtime_ns": stamp, "value": value})
    return value


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
    _DATA_INDEX_CACHE.update({
        "path": str(_data_index_path().resolve()),
        "mtime_ns": _data_index_path().stat().st_mtime_ns,
        "value": index,
    })
    return index


def data_storage_status():
    """화면용 저장 위치와 마지막 색인 요약. 토큰·프롬프트 내용은 내보내지 않는다."""
    index = None
    restoration = None
    path = _data_index_path()
    if path.is_file():
        try:
            loaded = _load_data_index_cached()
            if isinstance(loaded, dict) and loaded.get("schema") == DATA_INDEX_SCHEMA:
                restoration = folder_inventory_summary(loaded)
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
        "restoration": restoration,
    }


_METADATA_AUDIT_ADAPTER = None
_METADATA_AUDIT_ADAPTER_LOCK = threading.Lock()


def _nai_json_metadata(value):
    """일반 앱 자료 JSON과 NAI 생성 메타데이터 JSON을 좁게 구분한다."""
    if not isinstance(value, dict):
        return None
    candidates = [value]
    for key in ("Comment", "comment", "Description", "description", "metadata"):
        nested = value.get(key)
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        source = " ".join(str(candidate.get(key) or "")
                          for key in ("source", "software", "model")).casefold()
        has_prompt = bool(
            candidate.get("v4_prompt")
            or candidate.get("prompt")
            or candidate.get("description")
        )
        has_generation = (
            any(candidate.get(key) is not None
                for key in ("seed", "steps", "sampler", "scale",
                            "noise_schedule", "ucPreset"))
            and ("novelai" in source or isinstance(candidate.get("v4_prompt"), dict))
        )
        if has_prompt and has_generation:
            return candidate
    return None


def _metadata_audit_inspector(payload, kind, _relative_path):
    if kind in ("png", "webp"):
        return extract_nai_metadata(payload, f"image/{kind}")
    if kind == "json":
        try:
            value = json.loads(bytes(payload).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return {"found": _nai_json_metadata(value) is not None}
    return False


def metadata_audit_adapter():
    global _METADATA_AUDIT_ADAPTER
    if _METADATA_AUDIT_ADAPTER is None:
        with _METADATA_AUDIT_ADAPTER_LOCK:
            if _METADATA_AUDIT_ADAPTER is None:
                _METADATA_AUDIT_ADAPTER = MetadataAuditAdapter(
                    BASE_DIR,
                    metadata_inspector=_metadata_audit_inspector,
                )
    return _METADATA_AUDIT_ADAPTER


def metadata_audit_status(found_offset=0, found_limit=50):
    try:
        result = metadata_audit_adapter().status_light(
            found_offset=max(0, int(found_offset or 0)),
            found_limit=max(1, min(100, int(found_limit or 50))),
        )
        return {"ok": True, **result}
    except MetadataAuditLedgerError:
        return {"ok": True, "empty": True}


def metadata_audit_control(body):
    data = json.loads(body or b"{}")
    action = str(data.get("action") or "").strip().casefold()
    adapter = metadata_audit_adapter()
    if action == "start":
        index = _load_data_index_cached()
        if not isinstance(index, dict):
            raise ValueError("자료 색인이 없습니다. 먼저 자료 색인을 만들어주세요.")
        result = adapter.start_light(index, chunk_size=500)
    elif action in ("continue", "resume"):
        result = adapter.resume_light()
    elif action == "pause":
        result = adapter.pause_light()
    elif action == "retry":
        paths = data.get("paths")
        result = adapter.retry_light(
            paths=paths if isinstance(paths, list) else None)
    else:
        raise ValueError("메타데이터 감사 동작이 올바르지 않습니다.")
    return {"ok": True, **result}


def metadata_audit_candidate(body, *, include_raw=False):
    """사용자가 고른 한 건만 다시 SHA 검증해 읽고, 저장 없이 복원 후보를 보여 준다."""
    data = json.loads(body or b"{}")
    rel = str(data.get("path") or "")
    digest = str(data.get("sha256") or "")
    payload = metadata_audit_adapter().read_verified(rel, digest)
    suffix = Path(rel).suffix.casefold()
    if suffix in (".png", ".webp"):
        meta = extract_nai_metadata(
            payload, "image/png" if suffix == ".png" else "image/webp")
    elif suffix == ".json":
        value = json.loads(payload.decode("utf-8-sig"))
        raw = _nai_json_metadata(value)
        if raw is None:
            raise ValueError("선택한 JSON에서 NAI 생성 메타데이터를 찾지 못했습니다.")
        base, negative, characters = _prompt_parts(raw)
        params = {key: raw[key] for key in PARAM_KEYS
                  if raw.get(key) is not None}
        meta = {
            "metadata_status": "ok",
            "base": base,
            "negative": negative,
            "characters": characters,
            "params": params,
            "raw": raw,
        }
    else:
        raise ValueError("PNG, WebP, JSON 후보만 열 수 있습니다.")
    if meta.get("metadata_status") != "ok":
        raise ValueError("선택한 파일의 NAI 생성 메타데이터가 더 이상 유효하지 않습니다.")
    candidate = {
        "base": str(meta.get("base") or ""),
        "negative": str(meta.get("negative") or ""),
        "negative_full": str(meta.get("negative") or ""),
        "characters": copy.deepcopy(meta.get("characters") or []),
        "params": copy.deepcopy(meta.get("params") or {}),
    }
    safe_preview = image_inspect_queue(
        {
            "ok": True,
            "style": {
                **candidate,
                "metadata_raw": copy.deepcopy(meta.get("raw") or {}),
            },
        },
        filename=redact_diagnostic_text(Path(rel).name),
    )
    safe_actual = (
        safe_preview["items"][0]["result"]["evidence_candidate"]
        .get("actual_generation") or {}
    )
    candidate.update({
        "base": str(safe_actual.get("base") or ""),
        "negative": str(safe_actual.get("negative") or ""),
        "negative_full": str(safe_actual.get("negative") or ""),
        "characters": copy.deepcopy(safe_actual.get("characters") or []),
        "params": copy.deepcopy(safe_actual.get("settings") or {}),
    })
    if include_raw:
        candidate["metadata_raw"] = copy.deepcopy(meta.get("raw") or {})
    return {
        "ok": True,
        "path": rel,
        "sha256": digest.lower(),
        "candidate": candidate,
    }


def metadata_audit_save_candidate(body):
    """검증된 후보 한 건을 사용자가 명시적으로 고른 때만 그림체 자료로 저장한다."""
    result = metadata_audit_candidate(body, include_raw=True)
    candidate = result["candidate"]
    rel = result["path"]
    digest = result["sha256"]
    artists, rest = parse_artist_combo(candidate.get("base") or "")
    record = {
        "id": f"audit-{digest[:20]}",
        "content_sha256": digest,
        "title": f"복원 후보 {digest[:12]}",
        "source": "보유 자료 감사",
        "tab": "",
        "posted_at": "",
        "recommend": None,
        "views": None,
        "url": "",
        "count": len(artists),
        "combo": ", ".join(
            f"{weight:g}::artist:{name}::"
            if weight is not None else f"artist:{name}"
            for weight, name in artists
        ),
        "artists": [name for _, name in artists],
        "weights": {
            name: (weight if weight is not None else 1.0)
            for weight, name in artists
        },
        "base": str(candidate.get("base") or ""),
        "rest": ", ".join(rest),
        "negative": str(candidate.get("negative") or ""),
        "negative_full": str(candidate.get("negative_full") or ""),
        "characters": copy.deepcopy(candidate.get("characters") or []),
        "metadata_raw": copy.deepcopy(candidate.get("metadata_raw") or {}),
        "params": copy.deepcopy(candidate.get("params") or {}),
        "images": [],
    }
    safe_queue = image_inspect_queue(
        {"ok": True, "style": record},
        filename=redact_diagnostic_text(Path(rel).name),
    )
    evidence_record = copy.deepcopy(
        safe_queue["items"][0]["result"]["evidence_candidate"])
    safe_actual = evidence_record.get("actual_generation") or {}
    record["base"] = str(safe_actual.get("base") or "")
    record["negative"] = str(safe_actual.get("negative") or "")
    record["negative_full"] = record["negative"]
    record["characters"] = copy.deepcopy(
        safe_actual.get("characters") or [])
    record["params"] = copy.deepcopy(safe_actual.get("settings") or {})
    safe_artists, safe_rest = parse_artist_combo(record["base"])
    record["combo"] = ", ".join(
        f"{weight:g}::artist:{name}::"
        if weight is not None else f"artist:{name}"
        for weight, name in safe_artists
    )
    record["artists"] = [name for _, name in safe_artists]
    record["weights"] = {
        name: (weight if weight is not None else 1.0)
        for weight, name in safe_artists
    }
    record["count"] = len(safe_artists)
    record["rest"] = ", ".join(safe_rest)
    record["metadata_raw"] = copy.deepcopy(
        evidence_record.get("raw_metadata") or {})
    record["evidence_records"] = [evidence_record]
    record["knowledge_asset"] = style_asset_from_record(
        record,
        evidence_refs=[evidence_record["id"]],
        lifecycle="candidate",
    )
    saved = add_style(
        record,
        import_info={
            "kind": "metadata-audit",
            "file": f"자료색인 후보 {digest[:12]}",
        },
        return_detail=True,
    )
    return {
        "ok": True,
        "sha256": digest,
        "import": {
            key: saved.get(key)
            for key in ("action", "total", "batch", "changed", "id")
        },
    }


def folder_inventory_page(offset=0, limit=50):
    """대형 자료 색인을 한 번에 펼치지 않고 공통 복원 큐 계약으로 나눠 보여 준다."""
    index = _load_data_index_cached()
    if not isinstance(index, dict) or index.get("schema") != DATA_INDEX_SCHEMA:
        return {"ok": True, "empty": True, "items": [], "total": 0}
    entries = index.get("entries") if isinstance(index.get("entries"), list) else []
    start = max(0, int(offset or 0))
    page_size = max(1, min(100, int(limit or 50)))
    page = [
        item for item in entries[start:start + page_size]
        if isinstance(item, dict)
    ]
    safe_rows = [
        {
            "path": f"index-item:{str(item.get('sha256') or '')}",
            "filename": redact_diagnostic_text(
                Path(str(item.get("path") or "")).name),
            "content_sha256": item.get("sha256"),
            "size": item.get("size"),
            "cursor": start + index_no,
            "status": "pending",
        }
        for index_no, item in enumerate(page)
    ]
    queue = folder_inventory_queue(
        safe_rows,
        folder_label="개인 자료",
        cursor=start + len(page),
        status="indexed",
    )
    return {
        "ok": True,
        "empty": not entries,
        "total": len(entries),
        "offset": start,
        "more": min(start + page_size, len(entries)) < len(entries),
        "next_offset": min(start + page_size, len(entries)),
        "restoration_queue": queue,
        "restoration": summarize_restore_queue(queue),
        "items": [
            {
                "name": safe_rows[index_no]["filename"],
                "size": int(item.get("size") or 0),
                "cursor": start + index_no,
            }
            for index_no, item in enumerate(page)
        ],
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
            or rel.startswith((
                "세팅/", "캐릭터/", "태그/", "수집/이미지캐시/",
            ))
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


def _datapack_conflict_id(archive_sha, logical, key, current, incoming):
    current_sha = _style_row_digest(current)
    incoming_sha = _style_row_digest(incoming)
    value = f"{archive_sha}\0{logical}\0{key}\0{current_sha}\0{incoming_sha}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest(), current_sha, incoming_sha


def _datapack_character_destination(raw, fallback):
    """캐릭터 파일명보다 안정적인 id가 같으면 현재 파일을 갱신 대상으로 쓴다."""
    try:
        incoming = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return fallback
    cid = str(incoming.get("id") or "") if isinstance(incoming, dict) else ""
    if not cid or not CHAR_DIR.is_dir():
        return fallback
    for path in CHAR_DIR.rglob("*.json"):
        try:
            current = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(current, dict) and str(current.get("id") or "") == cid:
            return path
    return fallback


def preview_datapack_bytes(data, filename=""):
    """자료를 쓰기 전에 같은 열쇠·다른 내용만 자산 단위로 찾는다."""
    lists, whole = _datapack_lists(), _datapack_whole_files()
    archive_sha = hashlib.sha256(data).hexdigest()
    conflicts, recognized = [], 0

    def add_conflict(logical, key, current, incoming, kind):
        conflict_id, current_sha, incoming_sha = _datapack_conflict_id(
            archive_sha, logical, key, current, incoming)
        conflicts.append({
            "id": conflict_id,
            "logical": logical,
            "key": str(key),
            "kind": kind,
            "current": copy.deepcopy(current),
            "incoming": copy.deepcopy(incoming),
            "current_sha256": current_sha,
            "incoming_sha256": incoming_sha,
        })

    def inspect_list(stem, raw, renamed=None):
        nonlocal recognized
        spot = lists.get(stem)
        if not spot:
            return False
        recognized += 1
        dest, key = spot
        rows, _how = _read_rows(raw)
        if rows is None:
            return True
        if renamed:
            rows = _rewrite_local_image_refs(rows, renamed)
        current = []
        if dest.is_file():
            try:
                got = json.loads(dest.read_text(encoding="utf-8-sig"))
            except Exception as e:
                raise ValueError(
                    f"{dest.name}을 읽지 못해 자료팩을 비교할 수 없습니다: {e}"
                ) from e
            if not isinstance(got, list):
                raise ValueError(f"{dest.name}이 목록이 아니라 자료팩을 비교할 수 없습니다.")
            current = got
        by_key = {}
        for item in current:
            if isinstance(item, dict):
                item_key = _datapack_match_key(item, key)
                by_key.setdefault(item_key, item)
        for item in rows:
            if not isinstance(item, dict):
                continue
            item_key = _datapack_match_key(item, key)
            before = by_key.get(item_key, _BACKUP_MISSING)
            if before is not _BACKUP_MISSING and before != item:
                add_conflict(stem, item_key, before, item, "목록 자산")
        return True

    def inspect_whole(logical, raw, dest, kind):
        nonlocal recognized
        recognized += 1
        try:
            incoming = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            return
        if not isinstance(incoming, dict) or not dest.is_file():
            return
        try:
            current = json.loads(dest.read_text(encoding="utf-8-sig"))
        except Exception as e:
            raise ValueError(
                f"{dest.name}을 읽지 못해 자료팩을 비교할 수 없습니다: {e}"
            ) from e
        if current != incoming:
            add_conflict(logical, logical, current, incoming, kind)

    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = _validate_datapack_manifest(archive)
            renamed = {}
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                rel = _pack_rel(name)
                if rel and rel.startswith("수집/이미지캐시/"):
                    stem = Path(rel).name
                    if Path(stem).suffix.lower() in _datapack_dirs()[
                            "수집/이미지캐시"][1]:
                        renamed[stem] = _content_image_name(stem, archive.read(name))
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                rel = _pack_rel(name)
                if not rel:
                    continue
                stem = Path(rel).name
                raw = archive.read(name)
                if stem in lists:
                    inspect_list(stem, raw, renamed)
                elif stem in whole and not rel.startswith("세팅/"):
                    inspect_whole(stem, raw, whole[stem], "기본 자료")
                elif rel.startswith("세팅/") and stem.lower().endswith(".json"):
                    inspect_whole(rel, raw, SETTINGS_DIR / stem, "세팅")
                elif rel.startswith("캐릭터/") and stem.lower().endswith(".json"):
                    inspect_whole(
                        rel,
                        raw,
                        _datapack_character_destination(
                            raw, CHAR_DIR / Path(rel).relative_to("캐릭터")),
                        "캐릭터",
                    )
            pack_name = (
                (manifest or {}).get("name")
                or (manifest or {}).get("id")
                or Path(filename).name
                or "자료팩"
            )
    else:
        stem = Path(filename).name
        if stem in lists:
            inspect_list(stem, data)
        elif stem in whole:
            inspect_whole(stem, data, whole[stem], "기본 자료")
        else:
            return {"ok": False, "error": f"'{stem}' 은(는) 자료팩이 아닙니다."}
        pack_name = stem

    if not recognized:
        return {"ok": False, "error": "자료팩에서 알아볼 수 있는 자료를 못 찾았습니다."}
    conflicts.sort(key=lambda item: (item["logical"], item["key"]))
    fingerprint = hashlib.sha256(
        "\n".join(item["id"] for item in conflicts).encode("ascii")
    ).hexdigest()
    return {
        "ok": True,
        "name": pack_name,
        "sha256": archive_sha,
        "diff_fingerprint": fingerprint,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
    }


@serialized_data_write(lambda: BASE_DIR)
def import_datapack_bytes(data, filename="", overwrite=False,
                          selected_conflicts=None, expected_diff=""):
    """자료팩 ZIP 이든 낱개 JSON 이든 받아 자료 종류별 제자리에 넣는다.

    무엇이 들어왔는지 `수집/가져온기록.json` 에 남겨 **통째로 되돌릴 수 있게** 한다.
    자료를 넣고 나서 정리하려면 '무엇이 이번에 들어왔나' 를 알아야 하기 때문이다."""
    import io
    import zipfile
    lists, dirs, whole = _datapack_lists(), _datapack_dirs(), _datapack_whole_files()
    selected_list_keys, selected_whole = {}, set()
    if selected_conflicts is not None:
        preview = preview_datapack_bytes(data, filename)
        if not preview.get("ok"):
            return preview
        if expected_diff and expected_diff != preview["diff_fingerprint"]:
            return {
                "ok": False,
                "conflict": True,
                "error": "검사 뒤 현재 자료가 바뀌었습니다. 자료팩을 다시 검사해 주세요.",
            }
        by_id = {item["id"]: item for item in preview["conflicts"]}
        wanted_ids = set(map(str, selected_conflicts))
        if wanted_ids - set(by_id):
            return {
                "ok": False,
                "conflict": True,
                "error": "검사 뒤 충돌 항목이 바뀌었습니다. 자료팩을 다시 검사해 주세요.",
            }
        for item_id in wanted_ids:
            item = by_id[item_id]
            if item["kind"] == "목록 자산":
                selected_list_keys.setdefault(item["logical"], set()).add(
                    item["key"])
            else:
                selected_whole.add(item["logical"])
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
            if not overwrite and label not in selected_whole:
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
        n, keys, updates = _merge_list_json(
            dest,
            rows,
            key,
            overwrite,
            replace_keys=selected_list_keys.get(stem),
        )
        report.append(f"{stem}: {_say_counts(n)}" + (f" ({how})" if how else ""))
        if keys:
            batch["lists"][stem] = keys
        for update in updates:
            batch.setdefault("list_updates", []).append({
                "stem": stem,
                **update,
            })
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
                    take_whole(rel, z.read(n), SETTINGS_DIR / stem)
                    continue
                if rel.startswith("캐릭터/") and stem.lower().endswith(".json"):
                    raw = z.read(n)
                    take_whole(
                        rel,
                        raw,
                        _datapack_character_destination(
                            raw, CHAR_DIR / Path(rel).relative_to("캐릭터")),
                    )
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
    if (batch["lists"] or batch["files"] or batch["installed"]
            or batch.get("list_updates")):
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
    result = {
        "ok": True,
        "added": files,
        "report": report,
        "batch": batch.get("id"),
        "archive_sha256": batch.get("archive_sha256"),
        "log": pack_log_brief(),
    }
    # brief log는 화면용이라 목록 key·설치 파일 계보가 없다. 복원 큐에는 이번 판의
    # 실제 장부를 직접 투영하되, API result 최상위에는 중복으로 싣지 않는다.
    queue = pack_import_queue(
        {**result, "batch_record": copy.deepcopy(batch)},
        filename=filename,
    )
    result["restoration"] = summarize_restore_queue(queue)
    result["restoration_queue"] = queue
    return result


def pack_log_brief():
    """되돌리기 화면용 — 큰 id 목록은 빼고 요약만."""
    return [{"id": b.get("id"), "at": b.get("at"), "file": b.get("file"),
             "kind": b.get("kind", "datapack"),
             "새로": b.get("새로", 0), "요약": b.get("요약", ""),
             "pack_id": (b.get("manifest") or {}).get("id", ""),
             "pack_name": (b.get("manifest") or {}).get("name", ""),
             "content_sha256": (b.get("manifest") or {}).get(
                 "content_sha256", b.get("archive_sha256", ""))}
            for b in reversed(load_pack_log())]


@serialized_data_write(lambda: BASE_DIR)
def undo_datapack(batch_id, cfg=None):
    """어느 입력 경로든 한 번의 임포트를 되돌린다.

    새로 들어온 것은 빼고, 같은 묶음에 근거만 추가한 경우에는 그 직전 행을 복원한다.
    원래 갖고 있던 자료는 건드리지 않는다(열쇠를 그때 기록해 뒀다)."""
    rows = load_pack_log()
    hit = next((b for b in rows if str(b.get("id")) == str(batch_id)), None)
    if not hit:
        return {"ok": False, "error": "그 기록을 못 찾았습니다."}
    lists, dirs = _datapack_lists(), _datapack_dirs()
    said = []
    failures = []
    for update in reversed(hit.get("list_updates") or []):
        stem = str(update.get("stem") or "")
        spot = lists.get(stem)
        before = update.get("before")
        if not spot or not isinstance(before, dict):
            continue
        path, key = spot
        if not path.is_file():
            continue
        try:
            current_rows = load_json_recover(path)
            wanted_key = str(update.get("key") or "")
            index = next((
                i for i, item in enumerate(current_rows)
                if isinstance(item, dict)
                and (
                    _datapack_match_key(item, key)
                    if update.get("match_key")
                    else _row_key(item, key)[0]
                ) == wanted_key
            ), None)
            if index is None:
                said.append(f"{stem}: 바뀐 묶음을 찾지 못해 그대로 둠")
                continue
            if _style_row_digest(current_rows[index]) != update.get("after_sha256"):
                said.append(f"{stem}: 가져온 뒤 수정되어 그대로 둠")
                continue
            current_rows[index] = before
            atomic_write_json(path, current_rows, indent=None)
            said.append(f"{stem}: 임포트 전 묶음으로 복구")
        except Exception as e:
            log.warning(f"임포트 목록 갱신 되돌리기 실패: {e}")
            failures.append(f"{stem}: 목록 갱신 복구 실패")
    for stem, keys in (hit.get("lists") or {}).items():
        spot = lists.get(stem)
        if not spot or not keys:
            continue
        path, key = spot
        if not path.exists():
            continue
        try:
            old = load_json_recover(path)
        except Exception as e:
            log.warning(f"임포트 목록 삭제 되돌리기 실패: {e}")
            failures.append(f"{stem}: 목록 삭제 실패")
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
            except Exception as e:
                log.warning(f"자료팩 파일 되돌리기 실패: {e}")
                failures.append(f"{d}/{nm}: 파일 이동 실패")
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
                    failures.append(f"{rel.as_posix()}: 이전 자료 백업 없음")
            else:
                recoverable_remove(dest, label="자료팩되돌리기")
                said.append(f"{rel.as_posix()}: 가져온 파일 뺌")
        except Exception as e:
            log.warning(f"자료팩 전체파일 되돌리기 실패: {e}")
            failures.append(
                f"{Path(item.get('path', '')).as_posix()}: 전체파일 복구 실패"
            )
    changed_config = False
    char_records = hit.get("characters") or []
    if cfg is not None and char_records:
        wanted = {
            str(item.get("id")): str(item.get("after_signature") or "")
            for item in char_records if isinstance(item, dict) and item.get("id")
        }
        removed_ids = set()
        kept = []
        for char in cfg.get("characters") or []:
            cid = str(char.get("id") or "")
            if cid not in wanted:
                kept.append(char)
                continue
            if wanted[cid] and character_bundle_signature(char) != wanted[cid]:
                kept.append(char)
                said.append(f"캐릭터 {char.get('name') or cid}: 가져온 뒤 수정되어 그대로 둠")
                continue
            removed_ids.add(cid)
        if removed_ids:
            cfg["characters"] = kept
            delete_char_files(cfg, removed_ids)
            sync_chars_to_files(cfg)
            save_config(cfg)
            changed_config = True
            said.append(f"캐릭터: {len(removed_ids)}건 뺌")
    # ⚠ **되돌린 그 판만** 뺀다. 예전에는 id 가 같은 것을 모두 걸러냈는데,
    #   이미 겹쳐 있는 옛 기록(위 참조)에서는 손대지도 않은 판의 기록까지 사라져
    #   그 자료를 **영영 되돌릴 수 없게** 됐다. 객체로 견주면 옛 기록도 한 번에 한 판씩
    #   차례로 되돌릴 수 있다.
    forget_collection_caches()
    if failures:
        return {
            "ok": False,
            "partial": bool(said),
            "error": "일부 항목을 되돌리지 못했습니다. 같은 기록으로 다시 시도할 수 있습니다.",
            "report": said + failures,
            "log": pack_log_brief(),
            "changed_config": changed_config,
        }
    save_pack_log([b for b in rows if b is not hit])
    return {"ok": True, "report": said or ["되돌릴 것이 없었습니다"],
            "log": pack_log_brief(), "changed_config": changed_config}


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
    if not isinstance(incoming, dict):
        raise ValueError("복원할 설정의 최상위 값은 JSON 객체여야 합니다.")
    current = {}
    if target.is_file():
        current = load_settings_recover(target)
    for key in BACKUP_SECRET_KEYS:
        if key in current:
            incoming[key] = current[key]
    return json.dumps(incoming, ensure_ascii=False, indent=1).encode("utf-8")


_BACKUP_MISSING = object()


def _backup_list_key(current, incoming):
    """목록을 통째로 덮지 않고 자산별로 비교할 수 있는 안정 열쇠를 찾는다."""
    lists = [value for value in (current, incoming) if isinstance(value, list)]
    rows = [item for value in lists for item in value]
    if not rows or not all(isinstance(item, dict) for item in rows):
        return ""
    for key in ("id", "이름", "name", "title", "seed"):
        values_by_list = [
            [str(item.get(key, "")).strip() for item in value]
            for value in lists
        ]
        if all(
            all(values) and len(values) == len(set(values))
            for values in values_by_list
        ):
            return key
    return ""


def _backup_pointer(tokens):
    parts = []
    for token in tokens:
        if token[0] == "key":
            parts.append(str(token[1]).replace("~", "~0").replace("/", "~1"))
        else:
            parts.append(
                f"@{token[1]}={str(token[2]).replace('~', '~0').replace('/', '~1')}")
    return "/" + "/".join(parts) if parts else "/"


def _backup_collect_changes(current, incoming, tokens=()):
    if current is not _BACKUP_MISSING and incoming is not _BACKUP_MISSING:
        if current == incoming:
            return []
        if isinstance(current, dict) and isinstance(incoming, dict):
            changes = []
            for key in sorted(set(current) | set(incoming), key=str):
                changes.extend(_backup_collect_changes(
                    current.get(key, _BACKUP_MISSING),
                    incoming.get(key, _BACKUP_MISSING),
                    tokens + (("key", key),),
                ))
            return changes
        if isinstance(current, list) and isinstance(incoming, list):
            key = _backup_list_key(current, incoming)
            if key:
                before = {str(item[key]): item for item in current}
                after = {str(item[key]): item for item in incoming}
                changes = []
                for value in sorted(set(before) | set(after)):
                    changes.extend(_backup_collect_changes(
                        before.get(value, _BACKUP_MISSING),
                        after.get(value, _BACKUP_MISSING),
                        tokens + (("item", key, value),),
                    ))
                return changes
    return [{
        "tokens": tokens,
        "current_exists": current is not _BACKUP_MISSING,
        "incoming_exists": incoming is not _BACKUP_MISSING,
        "current": None if current is _BACKUP_MISSING else copy.deepcopy(current),
        "incoming": None if incoming is _BACKUP_MISSING else copy.deepcopy(incoming),
    }]


def _backup_apply_change(value, change, depth=0):
    """선택한 JSON 조각 하나만 현재값 사본에 적용한다."""
    tokens = change["tokens"]
    exists = change["incoming_exists"]
    incoming = copy.deepcopy(change["incoming"])
    if depth >= len(tokens):
        return incoming if exists else _BACKUP_MISSING
    token = tokens[depth]
    if token[0] == "key":
        obj = copy.deepcopy(value) if isinstance(value, dict) else {}
        key = token[1]
        child = obj.get(key, _BACKUP_MISSING)
        replaced = _backup_apply_change(child, change, depth + 1)
        if replaced is _BACKUP_MISSING:
            obj.pop(key, None)
        else:
            obj[key] = replaced
        return obj
    rows = copy.deepcopy(value) if isinstance(value, list) else []
    field, wanted = token[1], str(token[2])
    index = next((
        i for i, item in enumerate(rows)
        if isinstance(item, dict) and str(item.get(field, "")) == wanted
    ), None)
    child = rows[index] if index is not None else _BACKUP_MISSING
    replaced = _backup_apply_change(child, change, depth + 1)
    if replaced is _BACKUP_MISSING:
        if index is not None:
            rows.pop(index)
    elif index is None:
        rows.append(replaced)
    else:
        rows[index] = replaced
    return rows


def _backup_diff_plan(blob):
    manifest, payloads, archive_sha = _read_user_backup(blob)
    declared = {
        str(item.get("path") or ""): item
        for item in (manifest.get("files") or [])
    }
    plans, counts, total = [], {"새 파일": 0, "바뀔 파일": 0, "같은 파일": 0}, 0
    for logical, raw in sorted(payloads.items()):
        target = _backup_destination(logical)
        wanted = _backup_merge_secrets(logical, raw, target)
        current_raw = target.read_bytes() if target.is_file() else None
        total += len(wanted)
        if current_raw == wanted:
            counts["같은 파일"] += 1
            continue
        status = "새 파일" if current_raw is None else "바뀔 파일"
        counts[status] += 1
        incoming_value = current_value = _BACKUP_MISSING
        json_mode = False
        try:
            incoming_value = json.loads(wanted.decode("utf-8"))
            current_value = (
                json.loads(current_raw.decode("utf-8"))
                if current_raw is not None else _BACKUP_MISSING)
            json_mode = True
        except (UnicodeError, json.JSONDecodeError, AttributeError):
            pass
        changes = (
            _backup_collect_changes(current_value, incoming_value)
            if json_mode and current_raw is not None else [{
                "tokens": (),
                "current_exists": current_raw is not None,
                "incoming_exists": True,
                "current": ({
                    "bytes": len(current_raw),
                    "sha256": hashlib.sha256(current_raw).hexdigest(),
                } if current_raw is not None else None),
                "incoming": {
                    "bytes": len(wanted),
                    "sha256": hashlib.sha256(wanted).hexdigest(),
                },
            }]
        )
        current_sha = hashlib.sha256(current_raw or b"").hexdigest()
        incoming_sha = hashlib.sha256(wanted).hexdigest()
        base_sha = str((declared.get(logical) or {}).get("base_sha256") or "")
        for change in changes:
            pointer = _backup_pointer(change["tokens"])
            change_id = hashlib.sha256(
                f"{archive_sha}\0{logical}\0{pointer}\0{current_sha}\0{incoming_sha}"
                .encode("utf-8")
            ).hexdigest()
            plans.append({
                **change,
                "id": change_id,
                "logical": logical,
                "pointer": pointer,
                "file_status": status,
                "json": json_mode,
                "current_sha256": current_sha,
                "incoming_sha256": incoming_sha,
                "base_sha256": base_sha,
                "target": target,
                "wanted_raw": wanted,
                "current_raw": current_raw,
            })
    fingerprint = hashlib.sha256(
        "\n".join(item["id"] for item in plans).encode("ascii")
    ).hexdigest()
    return manifest, payloads, archive_sha, plans, counts, total, fingerprint


def _backup_change_public(change):
    if change["current_exists"] and change["incoming_exists"]:
        action = "변경"
    elif change["incoming_exists"]:
        action = "추가"
    else:
        action = "제거"
    return {
        key: copy.deepcopy(change[key])
        for key in (
            "id", "logical", "pointer", "file_status", "json",
            "current_exists", "incoming_exists", "current", "incoming",
            "current_sha256", "incoming_sha256", "base_sha256",
        )
    } | {
        "action": action,
        "base_available": bool(change.get("base_sha256")),
    }


def preview_user_backup(blob):
    (manifest, payloads, archive_sha, plans, counts,
     total, fingerprint) = _backup_diff_plan(blob)
    return {"ok": True, "sha256": archive_sha, "files": len(payloads),
            "bytes": total, "counts": counts, "created_at": manifest.get("created_at"),
            "profile": manifest.get("profile"), "excluded": manifest.get("excluded") or [],
            "diff_fingerprint": fingerprint,
            "changes": [_backup_change_public(change) for change in plans]}


@serialized_data_write(lambda: BASE_DIR)
def restore_user_backup(blob, expected_sha="", selected=None, expected_diff=""):
    (manifest, payloads, archive_sha, plans, _counts,
     _total, diff_fingerprint) = _backup_diff_plan(blob)
    if expected_sha and expected_sha != archive_sha:
        return {"ok": False, "error": "미리보기한 백업과 복원할 백업이 다릅니다."}
    if expected_diff and expected_diff != diff_fingerprint:
        return {"ok": False, "conflict": True,
                "error": "검사 뒤 현재 자료가 바뀌었습니다. 백업을 다시 검사해 주세요."}
    selected_ids = None if selected is None else set(map(str, selected))
    by_id = {item["id"]: item for item in plans}
    if selected_ids is not None:
        unknown = selected_ids - set(by_id)
        if unknown:
            return {"ok": False, "conflict": True,
                    "error": "검사 뒤 충돌 항목이 바뀌었습니다. 백업을 다시 검사해 주세요."}
        if not selected_ids:
            return {"ok": True, "batch": "", "changed": 0,
                    "files": len(payloads), "selected": 0}
    chosen = plans if selected_ids is None else [
        by_id[item_id] for item_id in selected_ids]
    grouped = {}
    for change in chosen:
        grouped.setdefault(change["logical"], []).append(change)

    batch = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    journal = PROFILE_DIR / "복원기록" / batch
    operations = []
    for logical, changes in sorted(grouped.items()):
        target = _backup_destination(logical)
        old = target.read_bytes() if target.is_file() else None
        if len(changes) == 1 and not changes[0]["tokens"]:
            wanted = changes[0]["wanted_raw"]
        else:
            try:
                value = json.loads(old.decode("utf-8")) if old is not None else {}
            except (UnicodeError, json.JSONDecodeError) as e:
                return {"ok": False, "error": f"{logical} 현재 JSON을 읽지 못했습니다: {e}"}
            for change in sorted(changes, key=lambda item: item["pointer"]):
                value = _backup_apply_change(value, change)
            if value is _BACKUP_MISSING:
                continue
            wanted = json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")
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
            "files": len(payloads), "selected": len(chosen)}


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
    "character_setting": "캐릭터 × 선택 세팅",
    "selected": "선택 자료·축",
}
COMPARE_MAX_JOBS = 2_000_000
COMPARE_RECIPE_SETTING_KEYS = STYLE_BUNDLE_SETTING_KEYS
COMPARE_SELECTED_AXES = {
    "generation.cfg_scale": ("float", -10.0, 10.0),
    "generation.cfg_rescale": ("float", 0.0, 1.0),
    "generation.steps": ("int", 1, 50),
    "generation.sampler": ("text", None, None),
    "generation.scheduler": ("text", None, None),
    "generation.variety": ("bool", None, None),
}


def _comparison_id(prefix, *parts):
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:20]}"


def comparison_styles(spec=None):
    """수집 그림체와 사용자가 저장한 그림체 프리셋을 같은 실행 목록으로 합친다."""
    out, seen, bundle_seen = [], set(), set()
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
        bundle_seen.add(style_bundle_signature(item))

    for i, saved in enumerate(list_styles(spec or load_spec())):
        if not isinstance(saved, dict) or not (saved.get("prompt") or "").strip():
            continue
        bundle_signature = style_bundle_signature(saved)
        # 같은 큰 묶음이 수집 JSON과 사용자 그림체 폴더 양쪽에 있어도 전수 비교에서
        # 두 번 생성하지 않는다. 파일은 없애지 않고 수집 자료 쪽의 이미지·출처를 우선한다.
        if bundle_signature in bundle_seen:
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
        bundle_seen.add(bundle_signature)
    return out


def _comparison_character_prompt(item):
    """저장 캐릭터도 일반 캐릭터 칸과 같은 `외형 + 착의` 한 덩어리로 보낸다."""
    return slot_prompt({
        "prompt": (item or {}).get("female", ""),
        "outfit": (item or {}).get("clothed", ""),
        "negative": (item or {}).get("negative", ""),
        "variants": copy.deepcopy((item or {}).get("variants") or []),
        "selected_variant_id": (item or {}).get("selected_variant_id", ""),
    })


def comparison_characters(cfg):
    """라이브러리의 캐릭터 전체.

    변형 묶음은 켜 둔 변형만 비교하고, 전부 꺼져 있으면 첫 항목을 안전한
    fallback으로 쓴다. 묶음이 없는 기존 캐릭터는 과거와 같이 모두 포함한다.
    """
    out, grouped, standalone = [], {}, []
    for i, raw in enumerate((cfg or {}).get("characters") or []):
        if not isinstance(raw, dict):
            continue
        prompt = _comparison_character_prompt(raw)
        if not prompt:
            continue
        item = dict(raw)
        effective = selected_variation_values(item)
        item["female"] = effective["prompt"]
        item["clothed"] = effective["outfit"]
        item["negative"] = effective["negative"]
        item["selected_variant_id"] = effective["selected_variant_id"]
        item["_compare_id"] = str(item.get("id") or _comparison_id(
            "char", item.get("name"), prompt, item.get("negative"), i))
        item["_compare_name"] = (item.get("name") or f"캐릭터 {i + 1}").strip()
        variant = item.get("variant") if isinstance(item.get("variant"), dict) else {}
        group = str(variant.get("group") or "").strip()
        if group:
            grouped.setdefault(group, []).append(item)
        else:
            standalone.append(item)
    out.extend(standalone)
    for members in grouped.values():
        active = [
            item for item in members
            if (item.get("variant") or {}).get("enabled") is not False
        ]
        out.extend(active or members[:1])
    return out


def setting_cast_members(cfg, state):
    """세팅 실행용 캐스트를 저장 방식과 무관하게 한 구조로 돌려준다.

    `all_characters`는 캐릭터 자료를 설정 안에 수백 번 복사하지 않고 실행할 때
    참조한다. 사용자가 직접 적은 cast는 그대로 남아 있어 이 계획을 꺼도 복구된다.
    """
    if (state or {}).get("cast_source") == "all_characters":
        return [{
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "prompt": item.get("female", ""),
            "outfit": item.get("clothed", ""),
            "negative": item.get("negative", ""),
            "variant": copy.deepcopy(item.get("variant") or {}),
            "variants": copy.deepcopy(item.get("variants") or []),
            "selected_variant_id": item.get("selected_variant_id", ""),
            "reference_ids": copy.deepcopy(item.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(item.get("vibe_ids") or []),
            "enabled": True,
        } for item in comparison_characters(cfg)]
    return [
        item for item in ((state or {}).get("cast") or [])
        if isinstance(item, dict)
    ]


def _compare_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def normalize_comparison_selection(value):
    """선택 실험 입력을 허용된 자료 id와 생성 설정 축으로만 줄인다."""
    raw = value if isinstance(value, dict) else {}

    def ids(key):
        values = raw.get(key)
        values = values if isinstance(values, list) else []
        out, seen = [], set()
        for item in values[:20_000]:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    axes = {}
    raw_axes = raw.get("axes") if isinstance(raw.get("axes"), dict) else {}
    for path, spec in COMPARE_SELECTED_AXES.items():
        values = raw_axes.get(path)
        if not isinstance(values, list):
            continue
        kind, lower, upper = spec
        normalized, seen = [], set()
        for item in values[:50]:
            try:
                if kind == "int":
                    parsed = max(int(lower), min(int(upper), int(item)))
                elif kind == "float":
                    parsed = max(float(lower), min(float(upper), float(item)))
                elif kind == "bool":
                    parsed = _compare_bool(item)
                else:
                    parsed = str(item or "").strip()[:80]
                    if not parsed:
                        continue
            except (TypeError, ValueError, OverflowError):
                continue
            marker = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(parsed)
        if normalized:
            axes[path] = normalized
    return {
        "styles": ids("styles"),
        "characters": ids("characters"),
        "settings": ids("settings"),
        "axes": axes,
    }


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
        "selection": normalize_comparison_selection(raw.get("selection")),
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


def comparison_settings(cfg):
    """현재 켠 세팅 중 실제 세트가 선택된 것만 실행용 사본으로 돌려준다.

    직접 캐스트를 포함한 원래 상태는 읽기만 한다. character_setting 실행은 이
    사본 위에 캐릭터 한 명을 얹으므로 설정.json과 화면의 직접 캐스트가 바뀌지 않는다.
    """
    rows = []
    for name, raw in (cfg.get("setting_state") or {}).items():
        if not isinstance(raw, dict):
            continue
        state = copy.deepcopy(raw)
        if state.get("use") is False or not state.get("selected"):
            continue
        rows.append({
            "id": str(name),
            "name": str(name),
            "state": state,
        })
    return rows


def comparison_catalog(cfg, spec=None):
    """선택 실험 UI가 쓰는 가벼운 자료 목록. 원문은 실행 요청에 되돌려 보내지 않는다."""
    styles = comparison_styles(spec)
    characters = comparison_characters(cfg)
    settings = comparison_settings(cfg)
    return {
        "ok": True,
        "styles": [{
            "id": item["_compare_id"],
            "name": item["_compare_name"],
        } for item in styles],
        "characters": [{
            "id": item["_compare_id"],
            "name": item["_compare_name"],
        } for item in characters],
        "settings": [{
            "id": item["id"],
            "name": item["name"],
        } for item in settings],
    }


def _comparison_selected_sources(styles, characters, settings, selection):
    wanted_styles = set(selection.get("styles") or [])
    wanted_characters = set(selection.get("characters") or [])
    wanted_settings = set(selection.get("settings") or [])
    return (
        [item for item in styles
         if str(item.get("_compare_id") or "") in wanted_styles],
        [item for item in characters
         if str(item.get("_compare_id") or "") in wanted_characters],
        [item for item in settings
         if str(item.get("id") or "") in wanted_settings],
    )


def _selected_character_from_slot(slot):
    value = slot if isinstance(slot, dict) else {}
    return {
        "id": value.get("id") or "",
        "name": value.get("name") or "캐릭터",
        "female": value.get("prompt") or value.get("female") or "",
        "clothed": value.get("outfit") or value.get("clothed") or "",
        "negative": value.get("negative") or "",
        "variant": copy.deepcopy(
            value.get("variant") or value.get("variants") or {}),
        "reference_ids": copy.deepcopy(value.get("reference_ids") or []),
        "vibe_ids": copy.deepcopy(value.get("vibe_ids") or []),
        "position": copy.deepcopy(value.get("position") or {}),
        "enabled": value.get("enabled") is not False,
    }


def _comparison_selected_cfg(cfg, material):
    """canonical 셀 재료를 사용자 설정을 건드리지 않는 실행 사본으로 바꾼다."""
    scratch = copy.deepcopy(cfg or {})
    scratch.update(copy.deepcopy(material.get("config_overrides") or {}))
    slots = copy.deepcopy(material.get("char_slots") or [])
    centers = copy.deepcopy(material.get("char_centers") or [])
    scratch["char_slots"] = slots
    scratch["char_centers"] = centers
    if material.get("setting_state"):
        scratch["setting_state"] = copy.deepcopy(material["setting_state"])

    selected_character = (material.get("job") or {}).get("character")
    if isinstance(selected_character, dict) and material.get("setting_state"):
        cast = _comparison_character_setting_slot(selected_character)
        for state in scratch["setting_state"].values():
            if not isinstance(state, dict):
                continue
            state["cast_source"] = "manual"
            state["cast_mode"] = "sequence"
            state["cast"] = [cast]

    if material.get("include_references") and isinstance(
            selected_character, dict):
        scratch = character_resource_config(
            scratch, _comparison_character_setting_scene_character(
                selected_character))
    return scratch


def _selected_comparison_leaf_seed(
    options, runtime_base_seed, seed_index, leaf_index, canonical_seed,
):
    """선택 실험의 실제 실행 leaf마다 비교 가능한 결정적 seed를 만든다."""
    if runtime_base_seed is None:
        return canonical_seed
    offset = (
        int(seed_index)
        if options.get("same_seed", True)
        else max(0, int(leaf_index) - 1)
    )
    seed = (int(runtime_base_seed) + offset * 100003) & 0xffffffff
    return seed or 1


def iter_selected_comparison_jobs(
    cfg, plan, styles, chars, settings=None, runtime_base_seed=None,
):
    """선택 자료·축 canonical 셀을 실제 비교/세팅 leaf 작업으로 펼친다."""
    selection = plan.get("selection") or plan["options"].get("selection") or {}
    settings = comparison_settings(cfg) if settings is None else list(settings)
    selected_styles, selected_chars, selected_settings = (
        _comparison_selected_sources(
            styles, chars, settings, selection))
    expanded = expand_legacy_experiment_cells(
        cfg,
        {"options": dict(plan["options"], limit=0), "count": 0},
        styles=selected_styles,
        characters=selected_chars,
        settings=selected_settings,
        selected=selection,
    )
    limit = max(0, int(plan.get("count") or 0))
    made = 0
    for cell in expanded.get("cells") or []:
        material = legacy_execution_material(
            cell, cfg, runtime_base_seed=runtime_base_seed)
        scratch = _comparison_selected_cfg(cfg, material)
        source = material.get("job") or {}
        style = source.get("style")
        character = source.get("character")
        setting = source.get("setting")
        style_name = source.get("style_name") or "현재 그림체"
        char_name = source.get("char_name") or "현재 캐릭터"
        setting_name = source.get("setting_name") or ""
        common = {
            "cell_id": material.get("cell_id"),
            "cell_resume_key": material.get("resume_key"),
            "canonical_cell": copy.deepcopy(cell),
            "material": material,
            "scratch_cfg": scratch,
            "style": style,
            "character": character,
            "setting": setting,
            "style_name": style_name,
            "char_name": char_name,
            "setting_name": setting_name,
            "seed_index": int(
                (material.get("seed_material") or {}).get("seed_index") or 0),
            "seed": material.get("seed"),
        }
        if isinstance(setting, dict):
            acfg = load_asset_config(scratch)
            for derived, cid, scene_num, copy_num in compute_pending(
                    scratch, acfg, {}, set()):
                if limit and made >= limit:
                    return
                made += 1
                yield dict(
                    common,
                    index=made,
                    seed=_selected_comparison_leaf_seed(
                        plan["options"], runtime_base_seed,
                        common["seed_index"], made, common.get("seed")),
                    key=_comparison_id(
                        "job", "selected", material.get("resume_key"),
                        str(cid), int(scene_num), int(copy_num)),
                    cid=str(cid),
                    asset_config=acfg,
                    scene_character=copy.deepcopy(derived),
                    scene_num=int(scene_num),
                    copy=int(copy_num),
                )
        else:
            if limit and made >= limit:
                return
            made += 1
            yield dict(
                common,
                index=made,
                seed=_selected_comparison_leaf_seed(
                    plan["options"], runtime_base_seed,
                    common["seed_index"], made, common.get("seed")),
                key=str(material.get("resume_key") or cell.get("id") or ""),
            )


def comparison_selected_job_values(cfg, plan, job):
    scratch = job["scratch_cfg"]
    material = job["material"]
    if job.get("asset_config") is not None:
        acfg = job["asset_config"]
        scene = acfg["scenes"][str(job["scene_num"])]
        character = copy.deepcopy(job["scene_character"])
        base, female, male, char_negative, male_negative, width, height = (
            build_scene(acfg, character, scratch, int(job["scene_num"])))
        negative = acfg["base"].get(
            "nsfw_negative_prompt", acfg["base"].get("negative_prompt", ""))
        if scene.get("negative"):
            negative = _join_tags(negative, scene["negative"])
        people, centers, use_positions = setting_scene_people(
            scene, female, male, char_negative, male_negative,
            character, scratch)
        used = scratch
        if plan["options"].get("include_refs"):
            used, _, _ = setting_reference_config(used, scene)
        used = with_position_mode(
            used, character.get("position_mode"), use_positions)
    else:
        used = scratch
        base = str(used.get("base_prompt") or "1girl")
        negative = str(used.get("negative_prompt") or "")
        people, centers = active_people(
            material.get("char_slots") or [],
            material.get("char_centers") or [],
        )
        selected_character = (material.get("job") or {}).get("character")
        if isinstance(selected_character, dict) and (
                selected_character.get("position")
                or selected_character.get("center")):
            used = with_position_mode(used, "coordinate", True)
    if plan["options"].get("fixed_size"):
        used["width"] = plan["options"]["width"]
        used["height"] = plan["options"]["height"]
    return used, base, negative, people, centers


def comparison_selected_plan(
    cfg, options, styles, chars, settings, opus=None,
):
    selection = options.get("selection") or {}
    chosen_styles, chosen_chars, chosen_settings = (
        _comparison_selected_sources(
            styles, chars, settings, selection))
    errors = []
    if len(chosen_styles) != len(selection.get("styles") or []):
        errors.append("선택한 그림체 중 현재 찾을 수 없는 항목이 있습니다.")
    if len(chosen_chars) != len(selection.get("characters") or []):
        errors.append("선택한 캐릭터 중 현재 찾을 수 없는 항목이 있습니다.")
    if len(chosen_settings) != len(selection.get("settings") or []):
        errors.append("선택한 세팅 중 현재 찾을 수 없는 항목이 있습니다.")
    if not any((
        chosen_styles, chosen_chars, chosen_settings,
        selection.get("axes"),
    )):
        errors.append("그림체·캐릭터·세팅 또는 바꿀 생성 설정 축을 하나 이상 선택해주세요.")

    probe = {
        "options": options,
        "selection": selection,
        "count": COMPARE_MAX_JOBS + 1,
    }
    total = paid_total = opus_total = eligible = 0
    cost_cap = int(options.get("limit") or 0) or COMPARE_MAX_JOBS
    if not errors:
        for job in iter_selected_comparison_jobs(
                cfg, probe, styles, chars, settings=settings):
            total += 1
            if total <= cost_cap:
                used, _, _, _, _ = comparison_selected_job_values(
                    cfg, probe, job)
                refs = (
                    sum(1 for item in (used.get("char_refs") or [])
                        if item.get("enabled"))
                    if options.get("include_refs") else 0
                )
                paid = anlas_estimate(
                    used, 1, opus=False, char_refs=refs)
                free = anlas_estimate(
                    used, 1, opus=True, char_refs=refs)
                paid_total += paid["per_image"]
                opus_total += free["per_image"]
                eligible += int(bool(free["free_eligible"]))
            if total > COMPARE_MAX_JOBS:
                break
    count = min(total, int(options.get("limit") or total))
    if count > COMPARE_MAX_JOBS:
        errors.append(
            f"한 계획은 최대 {COMPARE_MAX_JOBS:,}장까지 만들 수 있습니다.")
    result = {
        "ok": not errors,
        "errors": errors,
        "options": options,
        "selection": selection,
        "mode_label": COMPARE_MODE_LABELS["selected"],
        "styles": len(chosen_styles),
        "characters": len(chosen_chars),
        "settings": len(chosen_settings),
        "axes": len(selection.get("axes") or {}),
        "current_slots": len([
            slot for slot in (cfg.get("char_slots") or [])
            if isinstance(slot, dict) and slot_prompt(slot).strip()
            and slot.get("enabled") is not False
        ]),
        "combinations": total // max(1, options["seed_count"]),
        "seed_count": options["seed_count"],
        "total": total,
        "count": count,
        "limited": count < total,
        "free_eligible": min(eligible, count),
        "paid_anlas_max": paid_total,
        "opus_anlas": opus_total,
        "expected_anlas": (
            opus_total if opus is True
            else paid_total if opus is False else None),
        "subscription_known": opus is not None,
        "sample_styles": [
            item["_compare_name"] for item in chosen_styles[:3]],
        "sample_characters": [
            item["_compare_name"] for item in chosen_chars[:3]],
        "sample_settings": [
            item["name"] for item in chosen_settings[:3]],
    }
    if not errors:
        experiment = expand_legacy_experiment_cells(
            cfg,
            {"options": dict(options, limit=0), "count": 0},
            styles=chosen_styles,
            characters=chosen_chars,
            settings=chosen_settings,
            selected=selection,
        )
        result["experiment"] = {
            "schema": experiment.get("schema"),
            "id": experiment.get("id"),
            "mode": experiment.get("legacy_mode"),
            "cells": experiment.get("total", 0),
            "total": total,
            "pending": total,
            "completed": 0,
            "cell_ids": [{
                "id": cell.get("id"),
                "resume_key": cell.get("legacy_resume_key"),
            } for cell in (experiment.get("cells") or [])[:10]],
        }
    return result


def _comparison_character_setting_slot(character):
    """라이브러리 캐릭터를 세팅 캐스트 한 명의 무손실 사본으로 바꾼다."""
    item = character if isinstance(character, dict) else {}
    return {
        "id": item.get("id") or item.get("_compare_id") or "",
        "name": item.get("name") or item.get("_compare_name") or "캐릭터",
        "prompt": item.get("female", ""),
        "outfit": item.get("clothed", ""),
        "negative": item.get("negative", ""),
        "variant": copy.deepcopy(item.get("variant") or {}),
        "reference_ids": copy.deepcopy(item.get("reference_ids") or []),
        "vibe_ids": copy.deepcopy(item.get("vibe_ids") or []),
        "position": copy.deepcopy(
            item.get("position") or item.get("center") or {}),
        "enabled": True,
    }


def _comparison_character_setting_cfg(cfg, setting, character):
    """한 캐릭터×세팅 셀만 보이게 만든 비영구 scratch 설정."""
    scratch = copy.deepcopy(cfg or {})
    states = {}
    setting_id = str((setting or {}).get("id") or (setting or {}).get("name") or "")
    for name, raw in (scratch.get("setting_state") or {}).items():
        state = copy.deepcopy(raw) if isinstance(raw, dict) else {}
        state["use"] = False
        states[str(name)] = state
    chosen = copy.deepcopy((setting or {}).get("state") or {})
    chosen["use"] = True
    chosen["cast_source"] = "manual"
    chosen["cast_mode"] = "sequence"
    chosen["cast"] = [_comparison_character_setting_slot(character)]
    states[setting_id] = chosen
    scratch["setting_state"] = states
    return scratch


def _comparison_character_setting_scene_character(character):
    """build_scene이 외형·착의를 단계별로 고를 수 있는 원형 캐릭터."""
    slot = _comparison_character_setting_slot(character)
    center = slot.get("position") if isinstance(slot.get("position"), dict) else {}
    return {
        "name": slot["name"],
        "female": slot["prompt"],
        "clothed": slot["outfit"],
        "negative": slot["negative"],
        "male_prompt_base": "",
        "partner_negative": "",
        "extras": [],
        "centers": [copy.deepcopy(center) if center else None],
        "reference_ids": copy.deepcopy(slot["reference_ids"]),
        "vibe_ids": copy.deepcopy(slot["vibe_ids"]),
    }


def iter_character_setting_jobs(cfg, plan, chars, settings=None):
    """캐릭터×세팅 셀을 선택 씬·단계·예약 매수까지 실제 한 장 단위로 펼친다."""
    options = plan["options"]
    limit = max(0, int(plan.get("count") or 0))
    made = 0
    settings = comparison_settings(cfg) if settings is None else list(settings)
    # canonical cell id와 재개 키를 leaf 작업의 부모 식별자로 쓴다. 비교 상한은
    # leaf 장수 기준이므로 셀 확장 자체에는 limit를 걸지 않는다.
    cell_plan = {
        "options": dict(options, limit=0),
        "count": 0,
    }
    expanded = expand_legacy_experiment_cells(
        cfg, cell_plan, characters=chars, settings=settings)
    cells = {}
    for cell in expanded.get("cells") or []:
        material = cell.get("legacy_material") or {}
        character = material.get("character") or {}
        setting = material.get("setting") or {}
        seed_index = int((cell.get("seed_material") or {}).get("seed_index") or 0)
        cells[(
            str(character.get("_compare_id") or character.get("id") or ""),
            str(setting.get("id") or setting.get("name") or ""),
            seed_index,
        )] = cell

    for character in chars:
        character_id = str(
            character.get("_compare_id") or character.get("id") or "")
        for setting in settings:
            setting_id = str(setting.get("id") or setting.get("name") or "")
            scratch = _comparison_character_setting_cfg(
                cfg, setting, character)
            acfg = load_asset_config(scratch)
            # compute_pending은 선택 세트·stages·reserve를 해석한다. 반환 캐릭터는
            # 기존 캐스트 조립 결과이므로, 착의를 따로 보존한 원형 캐릭터로 교체한다.
            pending = compute_pending(scratch, acfg, {}, set())
            scene_character = _comparison_character_setting_scene_character(
                character)
            for _derived, cid, scene_num, copy_num in pending:
                for seed_index in range(options["seed_count"]):
                    if limit and made >= limit:
                        return
                    cell = cells.get((character_id, setting_id, seed_index))
                    if cell is None:
                        continue
                    parent_key = str(
                        cell.get("legacy_resume_key") or cell.get("id") or "")
                    made += 1
                    yield {
                        "index": made,
                        "key": _comparison_id(
                            "job", "character_setting",
                            (parent_key, cid, int(scene_num), int(copy_num)),
                            int(seed_index),
                        ),
                        "cell_id": cell.get("id"),
                        "cell_resume_key": parent_key,
                        "style": None,
                        "character": character,
                        "setting": setting,
                        "style_name": (
                            str(cfg.get("style_name") or "").strip()
                            or "현재 그림체"
                        ),
                        "char_name": (
                            f"{character.get('_compare_name') or character.get('name') or '캐릭터'}"
                            f" × {setting.get('name') or setting_id}"
                        ),
                        "setting_name": setting.get("name") or setting_id,
                        "seed_index": int(seed_index),
                        "scene_num": int(scene_num),
                        "copy": int(copy_num),
                        "scratch_cfg": scratch,
                        "asset_config": acfg,
                        "scene_character": scene_character,
                    }


def comparison_character_setting_job_values(cfg, plan, job):
    """세팅 배치의 장면 해석을 그대로 써 한 비교 leaf의 NAI 입력을 만든다."""
    scratch = job["scratch_cfg"]
    acfg = job["asset_config"]
    scene_num = int(job["scene_num"])
    scene = acfg["scenes"][str(scene_num)]
    character = copy.deepcopy(job["scene_character"])
    # 일반 세팅은 기존 cast처럼 외형+착의를 한 캐릭터 전송값으로 쓴다.
    # 백합은 탈의 단계가 두 값을 골라야 하므로 분리된 원문을 그대로 넘긴다.
    if scene.get("_mode") != "백합":
        character["female"] = _join_tags(
            character.get("female", ""), character.get("clothed", ""))
    base, female, male, char_negative, male_negative, width, height = (
        build_scene(acfg, character, scratch, scene_num)
    )
    negative = acfg["base"].get(
        "nsfw_negative_prompt", acfg["base"].get("negative_prompt", ""))
    scene_negative = scene.get("negative") or ""
    if scene_negative:
        negative = _join_tags(negative, scene_negative)
    people, centers, use_positions = setting_scene_people(
        scene, female, male, char_negative, male_negative, character, scratch)
    if plan["options"].get("include_refs"):
        used = character_resource_config(scratch, character)
        used, _, _ = setting_reference_config(used, scene)
    else:
        # 원문 id는 manifest에 보존하되 이번 실행 재료에는 붙이지 않는다.
        used = dict(scratch)
    if plan["options"].get("fixed_size"):
        width = plan["options"]["width"]
        height = plan["options"]["height"]
    used["width"], used["height"] = int(width), int(height)
    used = with_position_mode(
        used, character.get("position_mode"), use_positions)
    return used, base, negative, people, centers


def comparison_character_setting_plan(cfg, options, chars, opus=None):
    """캐릭터×선택 세팅의 실제 leaf 장수와 비용을 API 없이 계산한다."""
    settings = comparison_settings(cfg)
    errors = []
    if not chars:
        errors.append("비교할 캐릭터가 없습니다. 캐릭터 라이브러리에 먼저 저장해주세요.")
    if not settings:
        errors.append("선택한 세트가 있는 켜진 세팅이 없습니다.")
    probe = {
        "options": options,
        "count": COMPARE_MAX_JOBS + 1,
    }
    total = paid_total = opus_total = eligible = 0
    cost_cap = int(options.get("limit") or 0) or COMPARE_MAX_JOBS
    if not errors:
        for job in iter_character_setting_jobs(
            cfg, probe, chars, settings=settings
        ):
            total += 1
            if total <= cost_cap:
                used, _, _, _, _ = comparison_character_setting_job_values(
                    cfg, probe, job)
                refs = (
                    sum(1 for item in (used.get("char_refs") or [])
                        if item.get("enabled"))
                    if options.get("include_refs") else 0
                )
                paid = anlas_estimate(
                    used, 1, opus=False, char_refs=refs)
                free = anlas_estimate(
                    used, 1, opus=True, char_refs=refs)
                paid_total += paid["per_image"]
                opus_total += free["per_image"]
                eligible += int(bool(free["free_eligible"]))
            if total > COMPARE_MAX_JOBS:
                break
    count = min(total, int(options.get("limit") or total))
    if count > COMPARE_MAX_JOBS:
        errors.append(f"한 계획은 최대 {COMPARE_MAX_JOBS:,}장까지 만들 수 있습니다.")
    result = {
        "ok": not errors,
        "errors": errors,
        "options": options,
        "mode_label": COMPARE_MODE_LABELS["character_setting"],
        "styles": 1,
        "characters": len(chars),
        "settings": len(settings),
        "current_slots": 0,
        "combinations": len(chars) * len(settings),
        "seed_count": options["seed_count"],
        "total": total,
        "count": count,
        "limited": count < total,
        "free_eligible": min(eligible, count),
        "paid_anlas_max": paid_total,
        "opus_anlas": opus_total,
        "expected_anlas": (
            opus_total if opus is True
            else paid_total if opus is False
            else None
        ),
        "subscription_known": opus is not None,
        "sample_styles": [str(cfg.get("style_name") or "현재 그림체")],
        "sample_characters": [
            item["_compare_name"] for item in chars[:3]
        ],
        "sample_settings": [item["name"] for item in settings[:3]],
    }
    try:
        cell_plan = {
            "options": dict(options, limit=0),
            "count": 0,
        }
        experiment = expand_legacy_experiment_cells(
            cfg, cell_plan, characters=chars, settings=settings)
        result["experiment"] = {
            "schema": experiment.get("schema"),
            "id": experiment.get("id"),
            "mode": experiment.get("legacy_mode"),
            "cells": experiment.get("total", 0),
            "total": total,
            "pending": total,
            "completed": 0,
            "cell_ids": [
                {
                    "id": cell.get("id"),
                    "resume_key": cell.get("legacy_resume_key"),
                }
                for cell in (experiment.get("cells") or [])[:10]
            ],
        }
    except Exception as error:
        result["experiment"] = {
            "ok": False,
            "error": redact_diagnostic_text(error),
        }
    return result


def comparison_plan(cfg, raw, spec=None, opus=None):
    """실행 전에 장수와 과금 범위를 계산한다. API 호출은 하지 않는다."""
    options = normalize_comparison_options(raw, cfg)
    mode = options["mode"]
    if mode == "character_setting":
        styles, chars = [], comparison_characters(cfg)
    else:
        styles, chars = comparison_sources(cfg, spec)
    if mode == "selected":
        return comparison_selected_plan(
            cfg, options, styles, chars, comparison_settings(cfg),
            opus=opus,
        )
    if mode == "character_setting":
        return comparison_character_setting_plan(
            cfg, options, chars, opus=opus)
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
    result = {
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
    # 기존 세 비교 모드의 실제 실행 순서와 재개 키를 공통 실험 셀에서도
    # 똑같이 계산한다. 이 값은 미리보기·진단용이며 NAI 요청은 만들지 않는다.
    try:
        experiment = expand_legacy_experiment_cells(
            cfg, result, styles=styles, characters=chars)
        result["experiment"] = {
            "schema": experiment.get("schema"),
            "id": experiment.get("id"),
            "mode": experiment.get("legacy_mode"),
            "total": experiment.get("total", 0),
            "pending": experiment.get("pending", 0),
            "completed": experiment.get("completed", 0),
            "cell_ids": [
                {
                    "id": cell.get("id"),
                    "resume_key": cell.get("legacy_resume_key"),
                }
                for cell in (experiment.get("cells") or [])[:10]
            ],
        }
    except Exception as error:
        # 기존 비교 기능은 공통 투영의 진단 실패 때문에 막지 않는다.
        result["experiment"] = {
            "ok": False,
            "error": redact_diagnostic_text(error),
        }
    return result


def comparison_signature(cfg, plan, styles, chars):
    options = plan["options"]
    selected_settings = comparison_settings(cfg)
    if options["mode"] == "selected":
        selected_styles, selected_chars, selected_settings = (
            _comparison_selected_sources(
                styles, chars, selected_settings,
                plan.get("selection") or options.get("selection") or {},
            ))
    else:
        selected_styles, selected_chars = styles, chars
    relevant_cfg = {
        k: cfg.get(k) for k in (
            "base_prompt", "negative_prompt", "cfg_scale", "cfg_rescale", "steps",
            "sampler", "scheduler", "variety", "model", "uc_preset",
            "quality_toggle", "smea", "smea_dyn", "dynamic_thresholding",
            "uncond_scale", "controlnet_strength", "prefer_brownian",
            "deliberate_euler_ancestral_bug", "use_coords", "position_mode", "char_slots",
            "char_centers", "vibes", "char_refs", "out_dir", "out_by_date",
        )
    }
    raw = {
        "options": options,
        "selection": (
            plan.get("selection") or options.get("selection") or {}
            if options["mode"] == "selected" else {}
        ),
        "config": relevant_cfg,
        "styles": [
            (x["_compare_id"], x.get("base"), x.get("combo"),
             x.get("negative"), x.get("params")) for x in styles
        ] if options["mode"] in ("styles", "both") else [
            (x["_compare_id"], x.get("base"), x.get("combo"),
             x.get("negative"), x.get("params")) for x in selected_styles
        ] if options["mode"] == "selected" else [],
        "characters": [
            (x["_compare_id"], x.get("female"), x.get("clothed"), x.get("negative"))
            for x in chars
        ] if options["mode"] in ("characters", "both", "character_setting") else [
            (x["_compare_id"], x.get("female"), x.get("clothed"),
             x.get("negative"), x.get("position"),
             x.get("reference_ids"), x.get("vibe_ids"))
            for x in selected_chars
        ] if options["mode"] == "selected" else [],
        "settings": selected_settings
        if options["mode"] in ("character_setting", "selected") else [],
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
    if plan["options"].get("mode") == "character_setting":
        return comparison_character_setting_job_values(cfg, plan, job)
    if plan["options"].get("mode") == "selected":
        return comparison_selected_job_values(cfg, plan, job)
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
        used = character_resource_config(used, char)
        # 캐릭터 자료의 외형+착의를 일반 캐릭터 칸과 같은 한 덩어리로 보낸다.
        people = [{"prompt": _comparison_character_prompt(char),
                   "negative": char.get("negative", "") or ""}]
        centers = [{"x": 0.5, "y": 0.5}]
    else:
        used = characters_resource_config(used, cfg.get("char_slots") or [])
        # active_people가 원래 칸 index로 좌표를 함께 거른다. 슬롯을 먼저 줄이면
        # 꺼진 캐릭터 뒤의 인물이 앞 캐릭터 좌표를 받는다.
        people, centers = active_people(
            cfg.get("char_slots") or [], cfg.get("char_centers"))
    return used, base, negative, people, centers


def comparison_job_recipe_snapshot(
    cfg, plan, job, used, base, negative, people, centers, seed,
):
    """현재 자료가 나중에 바뀌어도 한 결과를 복원할 수 있는 비밀값 없는 사본."""
    character = job.get("character") or {}
    setting = job.get("setting") or {}
    style = job.get("style") or {}
    mode = plan["options"].get("mode")
    if mode == "character_setting":
        slots = [{
            "id": character.get("id") or character.get("_compare_id") or "",
            "name": character.get("name") or character.get("_compare_name") or "",
            "prompt": character.get("female", ""),
            "outfit": character.get("clothed", ""),
            "negative": character.get("negative", ""),
            "variant": copy.deepcopy(character.get("variant") or {}),
            "variants": copy.deepcopy(character.get("variants") or []),
            "reference_ids": copy.deepcopy(character.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(character.get("vibe_ids") or []),
            "enabled": True,
        }]
        position = character.get("position") or character.get("center") or {}
        char_centers = [copy.deepcopy(position)] if position else []
        source_setting = {
            "id": setting.get("id") or setting.get("name") or "",
            "name": setting.get("name") or setting.get("id") or "",
            "state": copy.deepcopy(setting.get("state") or {}),
            "scene": int(job.get("scene_num") or 0),
            "copy": int(job.get("copy") or 1),
        }
    elif mode == "selected":
        material = job.get("material") or {}
        slots = copy.deepcopy(material.get("char_slots") or [])
        char_centers = copy.deepcopy(material.get("char_centers") or [])
        source_setting = {
            "id": setting.get("id") or setting.get("name") or "",
            "name": setting.get("name") or setting.get("id") or "",
            "state": copy.deepcopy(setting.get("state") or {}),
            "cid": str(job.get("cid") or ""),
            "scene": int(job.get("scene_num") or 0),
            "copy": int(job.get("copy") or 1),
        } if setting else {}
    elif character:
        slots = [{
            "id": character.get("id") or character.get("_compare_id") or "",
            "name": character.get("name") or character.get("_compare_name") or "",
            "prompt": character.get("female", ""),
            "outfit": character.get("clothed", ""),
            "negative": character.get("negative", ""),
            "variant": copy.deepcopy(character.get("variant") or {}),
            "variants": copy.deepcopy(character.get("variants") or []),
            "reference_ids": copy.deepcopy(character.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(character.get("vibe_ids") or []),
            "enabled": True,
        }]
        char_centers = [{"x": 0.5, "y": 0.5}]
        source_setting = {}
    else:
        slots = [
            copy.deepcopy(slot) for slot in (cfg.get("char_slots") or [])
            if isinstance(slot, dict)
            and slot.get("enabled") is not False
            and slot_prompt(slot).strip()
        ][:MAX_CHARS]
        _, char_centers = active_people(
            cfg.get("char_slots") or [], cfg.get("char_centers"))
        source_setting = {}
    include_refs = bool(plan["options"].get("include_refs"))
    wanted_vibes = {
        str(value)
        for slot in slots if isinstance(slot, dict)
        for value in (slot.get("vibe_ids") or []) if value
    }
    wanted_refs = {
        str(value)
        for slot in slots if isinstance(slot, dict)
        for value in (slot.get("reference_ids") or []) if value
    }
    saved_vibes = [
        copy.deepcopy(item) for item in (used.get("vibes") or [])
        if include_refs and isinstance(item, dict)
        and (
            str(item.get("id") or "") in wanted_vibes
            or (not wanted_vibes and item.get("enabled"))
        )
    ]
    saved_refs = [
        copy.deepcopy(item) for item in (used.get("char_refs") or [])
        if include_refs and isinstance(item, dict)
        and (
            str(item.get("id") or "") in wanted_refs
            or (not wanted_refs and item.get("enabled"))
        )
    ]
    return {
        "version": 2,
        "mode": plan["options"].get("mode") or "",
        # 이 결과에 실제로 쓰인 원문을 승격·재적용의 주 레시피로 보존한다.
        # 현재 화면 값은 아래 source에 별도로 남아 결과를 덮어쓰지 않는다.
        "base_prompt": base,
        "negative_prompt": negative,
        "style_name": (
            style.get("name") or style.get("title")
            or style.get("_compare_name") or cfg.get("style_name", "")
        ),
        "settings": {
            key: used.get(key) for key in COMPARE_RECIPE_SETTING_KEYS
        },
        "char_slots": slots,
        "char_centers": char_centers,
        "nai_seed": int(seed),
        "include_refs": include_refs,
        "vibes": saved_vibes,
        "char_refs": saved_refs,
        "source": {
            "style": {
                key: copy.deepcopy(style.get(key))
                for key in (
                    "id", "_compare_id", "title", "name", "_compare_name",
                    "base", "combo", "negative", "params",
                )
                if style.get(key) is not None
            },
            "character": {
                key: copy.deepcopy(character.get(key))
                for key in (
                    "id", "_compare_id", "name", "_compare_name",
                    "female", "clothed", "negative", "variant", "variants",
                    "reference_ids", "vibe_ids", "position",
                )
                if character.get(key) is not None
            },
            "setting": source_setting,
            "axes": copy.deepcopy(
                (job.get("material") or {}).get("selected_axes") or {}),
        },
        "resolved": {
            "base_prompt": base,
            "negative_prompt": negative,
            "characters": copy.deepcopy(people),
            "char_centers": copy.deepcopy(centers),
        },
    }


def comparison_recipe_context(cfg, plan, styles, chars):
    """비교 결과가 현재 자료 변경 뒤에도 재현되도록 원문을 한 번만 스냅샷한다."""
    options = plan.get("options") or {}
    context_settings = comparison_settings(cfg)
    if options.get("mode") == "selected":
        styles, chars, context_settings = _comparison_selected_sources(
            styles, chars, context_settings,
            plan.get("selection") or options.get("selection") or {},
        )
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
    context = {
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
            if options.get("mode") in ("styles", "both", "selected")],
        "characters": [{
            "id": item.get("_compare_id"),
            "name": item.get("_compare_name"),
            "female": item.get("female") or "",
            "clothed": item.get("clothed") or "",
            "negative": item.get("negative") or "",
            "source": item.get("source") or "",
        } for item in chars
            if options.get("mode") in (
                "characters", "both", "character_setting", "selected")],
        "settings": context_settings
        if options.get("mode") in ("character_setting", "selected") else [],
        "selection": copy.deepcopy(
            plan.get("selection") or options.get("selection") or {}),
    }
    # 기존 비교 기록 필드는 그대로 두고 같은 내용을 생성 설계도 관점에서도 남긴다.
    # 과거 기록을 읽는 코드는 영향을 받지 않고, 새 화면·챗봇 계약은 한 경계를 사용한다.
    context["blueprint"] = inherited_blueprint(
        cfg,
        source={"kind": "comparison-plan"},
        experiment={
            "mode": options.get("mode") or "single",
            "fixed_size": bool(options.get("fixed_size")),
            "width": options.get("width"),
            "height": options.get("height"),
            "same_seed": bool(options.get("same_seed")),
            "seed": options.get("seed"),
            "seed_count": options.get("seed_count"),
            "limit": options.get("limit"),
            "include_references": bool(options.get("include_refs")),
        },
    )
    return context


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
            cfg = load_settings_recover(SETTINGS_FILE)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
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


CHARACTER_ASSET_OPTIONAL_FIELDS = (
    "variant", "variants", "selected_variant_id",
    "reference_ids", "vibe_ids", "representative", "representative_image",
    "images", "evidence", "evidence_refs", "evidence_images",
    "variation_images", "reference_inset",
    "temporary_generation_overrides", "lineage",
)


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
            for field in CHARACTER_ASSET_OPTIONAL_FIELDS:
                if field in data:
                    current[field] = copy.deepcopy(data[field])
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
        for field in CHARACTER_ASSET_OPTIONAL_FIELDS:
            if field in data:
                new_char[field] = copy.deepcopy(data[field])
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
        for field in CHARACTER_ASSET_OPTIONAL_FIELDS:
            if field in c:
                data[field] = copy.deepcopy(c[field])
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


def remove_prompt_tags(text, removals):
    """쉼표 단위 프롬프트에서 사용자가 지정한 태그를 제외한다."""
    if isinstance(removals, str):
        removals = re.split(r"[,\n]", removals)
    needles = [str(x).strip().lower() for x in (removals or []) if str(x).strip()]
    if not needles:
        return text
    parts = [tag.strip() for tag in (text or "").split(",") if tag.strip()]
    return ", ".join(
        tag for tag in parts
        if not any(needle in tag.lower() for needle in needles)
    )


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
    if scene.get("base_tags"):
        base = _join_tags(base, scene.get("base_tags"))
    if scene.get("relationship_tags"):
        base = _join_tags(base, scene.get("relationship_tags"))

    cleaned_char = remove_prompt_tags(
        cleaned_char, scene.get("remove_char_tags", []))
    char_negative = _join_tags(
        char_negative, scene.get("female_negative", ""))

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
        # 캐릭터 칸/동시 캐스트의 둘째 인물이 있으면 세팅의 기본 상대역보다 우선한다.
        partner_from_cast = char.get("male_prompt_base", "")
        male_base = clean_char_prompt(partner_from_cast or role.get("외형", ""))
        male_base = remove_prompt_tags(
            male_base, scene.get("remove_male_tags", []))
        wear_mode = opts_chosen.get("남자옷", "나체")
        outfit = role.get("의상", "")
        wear = ""
        if partner_from_cast:
            # 둘째 캐릭터의 착의는 slot_prompt에 이미 들어 있다. 세팅 기본 상대역 옷을
            # 다시 붙이면 두 의상이 충돌하므로 캐스트 원문을 그대로 우선한다.
            wear = ""
        elif wear_mode == "착의":
            wear = f"{outfit}, clothed male, clothed sex, open pants"
        elif wear_mode == "탈의진행":
            if stage <= 1:
                wear = f"{outfit}, clothed male, clothed sex, open pants"
            elif stage == 2:
                wear = "topless male, open pants, clothed sex"
        add_m = apply_axes(specs, options, opts_chosen, scene, "남자")
        male_caption = ", ".join(x for x in (male_base, wear, male_caption, add_m) if x)
        male_negative = _join_tags(
            char.get("partner_negative", "") or role.get("네거티브", ""),
            scene.get("male_negative", ""))
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
    effective = selected_variation_values(sl)
    return _join_tags(strip_comment_lines(effective["prompt"]),
                      strip_comment_lines(effective["outfit"]))


def slot_bundle_identity(sl):
    """재개·중복 판정용 캐릭터 묶음.

    화면 표시 이름과 달리 생성 결과를 바꿀 수 있는 원문·참조·변형을 모두 포함한다.
    사용자가 저장한 원문은 정규화하지 않고 JSON 직렬화만 안정적으로 수행한다.
    """
    if not isinstance(sl, dict):
        return ""
    effective = selected_variation_values(sl)
    selected = effective["selected_variant"]
    bundle = {
        "id": sl.get("id", ""),
        "prompt": effective["prompt"],
        "outfit": effective["outfit"],
        "negative": effective["negative"],
        "variant": sl.get("variant") or {},
        "variants": sl.get("variants") or [],
        "selected_variant_id": effective["selected_variant_id"],
        "reference_ids": (
            selected.get("reference_ids")
            if "reference_ids" in selected else sl.get("reference_ids")
        ) or [],
        "vibe_ids": (
            selected.get("vibe_ids")
            if "vibe_ids" in selected else sl.get("vibe_ids")
        ) or [],
        "position": sl.get("position") or {},
    }
    return json.dumps(
        bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    )


def character_run_from_group(group, fallback_index=0, position_mode=None):
    """캐릭터 슬롯/캐스트 여러 명을 한 장의 세팅 입력 구조로 바꾼다."""
    members = [item for item in (group or [])
               if isinstance(item, dict) and slot_prompt(item).strip()]
    if not members:
        return {}
    primary = members[0]
    partner = members[1] if len(members) > 1 else {}
    primary_effective = selected_variation_values(primary)
    partner_effective = selected_variation_values(partner)
    names = [str(item.get("name") or "").strip() for item in members]
    names = [name for name in names if name]
    centers = []
    for item in members:
        center = item.get("position") or item.get("center")
        if isinstance(center, dict) and center.get("x") is not None:
            centers.append(copy.deepcopy(center))
        else:
            centers.append(None)
    return {
        "name": " + ".join(names) or f"인물{fallback_index + 1}",
        "female": slot_prompt(primary),
        "negative": primary_effective["negative"],
        "male_prompt_base": slot_prompt(partner),
        "partner_negative": partner_effective["negative"],
        "extras": [
            {
                "prompt": slot_prompt(item),
                "negative": selected_variation_values(item)["negative"],
                "center": copy.deepcopy(item.get("position") or item.get("center")),
            }
            for item in members[2:]
        ],
        "centers": centers,
        "position_mode": (
            normalize_position_mode(position_mode, bool([c for c in centers if c]))
            if position_mode not in (None, "") else ""),
        "reference_ids": list(dict.fromkeys(
            str(resource_id)
            for item in members for resource_id in (item.get("reference_ids") or [])
            if resource_id)),
        "vibe_ids": list(dict.fromkeys(
            str(resource_id)
            for item in members for resource_id in (item.get("vibe_ids") or [])
            if resource_id)),
    }


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
    if scene.get("relationship_tags"):
        base = _join_tags(base, scene.get("relationship_tags"))
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

    female_text = remove_prompt_tags(
        girl_text(char.get("female", ""), char.get("clothed", ""), u1),
        scene.get("remove_char_tags", []))
    partner_from_cast = char.get("male_prompt_base", "")
    partner_text = remove_prompt_tags(
        (clean_char_prompt(partner_from_cast) if partner_from_cast
         else girl_text(role.get("외형", ""), role.get("착의", ""), u2)),
        scene.get("remove_partner_tags", []))

    female_scene = scene.get("female_prompt", "")
    partner_scene = scene.get("partner_prompt", "")

    female_caption = _join_tags(female_text, female_scene)
    partner_caption = _join_tags(partner_text, partner_scene)

    return (
        base, female_caption, partner_caption,
        _join_tags(char.get("negative", ""), scene.get("female_negative", "")),
        _join_tags(char.get("partner_negative", "") or role.get("네거티브", ""),
                   scene.get("partner_negative", "")),
        scene["width"], scene["height"])


# ═══════════════ NAI API ═══════════════

def _ref_fields(p):
    """이전 단일 파일 호출부를 위한 호환 어댑터."""
    return reference_fields(p)


def _variety_sigma_value(model, width, height, variety, p):
    """이전 단일 파일 호출부를 위한 호환 어댑터."""
    return variety_sigma_value(
        model, width, height, variety, p, warn=log.warning)


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
        effective = selected_variation_values(sl)
        people.append({"prompt": cap, "negative": effective["negative"]})
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


BLUEPRINT_GENERATION_KEYS = (
    "model", "width", "height", "nai_seed", "steps", "cfg_scale",
    "cfg_rescale", "sampler", "scheduler", "uc_preset", "quality_toggle",
    "variety", "smea", "smea_dyn", "dynamic_thresholding",
    "uncond_scale", "controlnet_strength", "prefer_brownian",
    "deliberate_euler_ancestral_bug", "use_coords", "position_mode",
)


def generation_blueprint(cfg, *, source=None, setting=None, experiment=None):
    """현재 여러 저장 구조를 한 번의 실행 가능한 생성 설계도로 해석한다.

    파생 모델만 만들며 설정·캐릭터·세팅 파일에는 아무것도 쓰지 않는다. 화면, 비교,
    챗봇 연결 계약이 같은 값을 읽게 하는 경계다.
    """
    cfg = cfg or {}
    slots = cfg.get("char_slots") or []
    centers = cfg.get("char_centers") or []
    characters = []
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict):
            continue
        effective = selected_variation_values(slot)
        selected = effective["selected_variant"]
        center = (centers[index] if index < len(centers)
                  and isinstance(centers[index], dict) else {"x": 0.5, "y": 0.5})
        characters.append({
            "id": str(slot.get("id") or ""),
            "name": str(slot.get("name") or ""),
            "enabled": slot.get("enabled") is not False,
            "appearance": effective["prompt"],
            "clothed": effective["outfit"],
            "negative": effective["negative"],
            "resolved_prompt": slot_prompt(slot),
            "position": {
                "x": center.get("x", 0.5),
                "y": center.get("y", 0.5),
                "mode": normalize_position_mode(
                    cfg.get("position_mode"), cfg.get("use_coords")),
                "enabled": position_mode_uses_coords(
                    cfg.get("position_mode"), cfg.get("use_coords")),
            },
            "variant": copy.deepcopy(slot.get("variant") or {}),
            "variants": copy.deepcopy(slot.get("variants") or []),
            "selected_variant_id": effective["selected_variant_id"],
            "reference_ids": copy.deepcopy((
                selected.get("reference_ids")
                if "reference_ids" in selected else slot.get("reference_ids")
            ) or []),
            "vibe_ids": copy.deepcopy((
                selected.get("vibe_ids")
                if "vibe_ids" in selected else slot.get("vibe_ids")
            ) or []),
        })

    active_settings = {}
    for name, state in (cfg.get("setting_state") or {}).items():
        if isinstance(state, dict) and state.get("use"):
            active_settings[str(name)] = copy.deepcopy(state)

    generation = {
        key: copy.deepcopy(cfg.get(key))
        for key in BLUEPRINT_GENERATION_KEYS
    }
    generation["seed"] = generation.pop("nai_seed", cfg.get("nai_seed", 0))
    generation["resolution"] = {
        "width": generation.get("width"),
        "height": generation.get("height"),
    }
    generation["settings"] = {
        key: copy.deepcopy(generation.get(key))
        for key in BLUEPRINT_GENERATION_KEYS
        if key not in ("width", "height", "nai_seed")
    }
    generation["final"] = {
        "base_prompt": str(cfg.get("base_prompt") or ""),
        "negative_prompt": str(cfg.get("negative_prompt") or ""),
        "character_prompts": [
            {
                "prompt": item["resolved_prompt"],
                "negative": item["negative"],
                "position": copy.deepcopy(item["position"]),
            }
            for item in characters if item.get("enabled")
        ],
    }
    style_settings = {
        key: copy.deepcopy(cfg.get(key))
        for key in BLUEPRINT_GENERATION_KEYS
        if key not in ("nai_seed", "use_coords", "position_mode")
    }
    blueprint = canonical_generation_plan({
        "source": copy.deepcopy(source or {"kind": "current-config"}),
        "style": {
            "name": str(cfg.get("style_name") or ""),
            "base": str(cfg.get("base_prompt") or ""),
            "negative": str(cfg.get("negative_prompt") or ""),
            "generation_settings": style_settings,
            "parts": {
                "fixed": str(cfg.get("base_fixed") or ""),
                "variable": str(cfg.get("base_var") or ""),
                "detail": str(cfg.get("base_detail") or ""),
            },
        },
        "characters": characters,
        "resources": {
            "vibes": copy.deepcopy(cfg.get("vibes") or []),
            "character_references": copy.deepcopy(cfg.get("char_refs") or []),
        },
        "setting": copy.deepcopy(setting or {
            "name": next(iter(active_settings), ""),
            "active": active_settings,
            "cast_presets": copy.deepcopy(cfg.get("cast_presets") or []),
        }),
        "experiment": canonical_experiment_rule(
            copy.deepcopy(experiment or {"mode": "single"})
        ),
        "generation": generation,
        "output": {
            "format": str(cfg.get("save_format") or "webp"),
            "quality": cfg.get("save_quality", 92),
            "clean_metadata": bool(cfg.get("save_clean")),
            "max_side": cfg.get("save_max_side", 0),
            "directory": str(cfg.get("out_dir") or ""),
            "by_date": bool(cfg.get("out_by_date")),
        },
    })
    blueprint["fingerprint"] = fingerprint_blueprint(blueprint)
    blueprint["summary"] = summarize_blueprint(blueprint)
    return blueprint


def inherited_blueprint_resolution(cfg, *, source=None, setting=None,
                                   experiment=None, runtime=None):
    """현재 cfg를 프로젝트 승인 사본과 합친 생성 전 판정.

    연결이 없으면 기존 ``generation_blueprint``를 그대로 돌려주므로 레거시
    생성·세팅·비교 경로의 값은 달라지지 않는다.
    """
    current = generation_blueprint(
        cfg, source=source, setting=setting, experiment=experiment)
    return resolve_inheritance(
        current,
        cfg.get("blueprint_projects") or [],
        cfg.get("blueprint_inheritance") or {},
        runtime=runtime,
    )


def inherited_blueprint(cfg, *, source=None, setting=None,
                        experiment=None, runtime=None):
    return inherited_blueprint_resolution(
        cfg, source=source, setting=setting, experiment=experiment,
        runtime=runtime,
    )["blueprint"]


def sync_blueprint_local_overrides(cfg):
    """승인 뒤 현재 화면에서 실제로 바꾼 공통값만 연결 계약에 기록한다."""
    link = normalize_link(cfg.get("blueprint_inheritance") or {})
    if not link:
        cfg["blueprint_inheritance"] = {}
        return {}
    link["local_overrides"] = local_overrides(
        generation_blueprint(cfg),
        link.get("accepted_blueprint") or {},
    )
    cfg["blueprint_inheritance"] = link
    return link


def materialize_blueprint_into_config(cfg, blueprint):
    """resolved plan을 기존 실행 설정에 투영하되 원본 cfg는 바꾸지 않는다."""
    result = copy.deepcopy(cfg or {})
    material = single_generation_legacy_material(blueprint)
    result.update(copy.deepcopy(material.get("config_overrides") or {}))
    return result


def with_centers(cfg, ctrs):
    """params 사본에 이 장에 쓸 좌표를 실어 준다 (원본 cfg 는 안 건드린다)."""
    q = dict(cfg or {})
    q["char_centers"] = ctrs
    return q


def with_position_mode(cfg, mode=None, use_positions=False):
    """실행 사본에 위치 방식을 적용한다. 원본 설정과 보존 좌표는 바꾸지 않는다."""
    q = dict(cfg or {})
    raw = str(mode or "").strip().lower()
    if raw in ("ai", "grid", "coordinate"):
        q["position_mode"] = raw
        q["use_coords"] = raw != "ai"
    elif use_positions:
        q["position_mode"] = "coordinate"
        q["use_coords"] = True
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


def normalize_scene_centers(value):
    """씬 파일에 저장할 캐릭터 위치를 검증한다.

    빈 목록은 '이 씬에서는 전역 위치 설정을 따른다'는 뜻이다. 좌표가 켜진
    씬은 NAI가 받는 0..1 범위의 x/y 쌍만 보존하며, 잘못된 자료를 조용히
    일부만 저장하지 않고 요청 전체를 거절한다.
    """
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("캐릭터 위치는 목록이어야 합니다.")
    out = []
    for i, center in enumerate(value[:MAX_CHARS]):
        if not isinstance(center, dict):
            raise ValueError(f"{i + 1}번 캐릭터 위치 형식이 잘못되었습니다.")
        try:
            x = float(center["x"])
            y = float(center["y"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"{i + 1}번 캐릭터 위치는 x/y 숫자가 필요합니다.")
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"{i + 1}번 캐릭터 위치는 유한한 숫자여야 합니다.")
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"{i + 1}번 캐릭터 위치는 0~1 범위여야 합니다.")
        out.append({"x": round(x, 4), "y": round(y, 4)})
    return out


def normalize_scene_reference_ids(value):
    """씬의 캐릭터 순서에 맞춘 Reference id 목록을 검증한다.

    빈 문자열은 해당 인물에 참조를 지정하지 않았다는 뜻이다. NAI 요청에는
    캐릭터와 Reference를 강제로 묶는 별도 필드가 없으므로 순서·선택 근거만
    보존하고, 실제 전송에서는 선택한 참조 목록으로 범위를 좁힌다.
    """
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("씬 캐릭터 레퍼런스는 목록이어야 합니다.")
    out = []
    for i, value in enumerate(value[:MAX_CHARS]):
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"{i + 1}번 캐릭터 레퍼런스 id는 문자열이어야 합니다.")
        value = value.strip()
        if len(value) > 160:
            raise ValueError(f"{i + 1}번 캐릭터 레퍼런스 id가 너무 깁니다.")
        out.append(value)
    return out


def setting_reference_config(cfg, scene):
    """씬 전용 Reference 선택을 현재 설정 위에 안전하게 얹는다.

    `use_character_refs`가 꺼져 있으면 전역 활성 목록을 그대로 쓴다. 켜져 있으면
    인물 순서대로 고른 id만 활성화한다. 같은 id를 여러 인물에 골라도 NAI에는 한 번만
    보내며, 삭제되어 찾을 수 없는 id는 건너뛰고 이름 목록에는 근거를 남긴다.
    """
    if not scene.get("use_character_refs"):
        active = [r.get("name") or r.get("id") or "무제"
                  for r in (cfg.get("char_refs") or []) if r.get("enabled")]
        return cfg, False, active
    chosen = normalize_scene_reference_ids(scene.get("character_refs"))
    by_id = {
        str(item.get("id") or ""): item
        for item in (cfg.get("char_refs") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    scoped = dict(cfg)
    selected, names, seen = [], [], set()
    for rid in chosen:
        if not rid:
            names.append("참조 안 함")
            continue
        item = by_id.get(rid)
        if item is None:
            names.append(f"없어진 참조({rid})")
            continue
        names.append(item.get("name") or rid)
        if rid not in seen:
            selected.append(dict(item, enabled=True))
            seen.add(rid)
    scoped["char_refs"] = selected
    return scoped, True, names


def character_resource_config(cfg, character):
    """저장 캐스트가 가리키는 Vibe·Reference만 이 작업에 활성화한다.

    id 목록이 비어 있으면 기존 전역 선택을 그대로 쓴다. 따라서 과거 캐스트와 설정은
    동작이 바뀌지 않고, 새 출연 구성에서 자료 id를 명시했을 때만 범위를 좁힌다.
    """
    scoped = dict(cfg)
    selected = selected_variation_values(character).get("selected_variant") or {}
    for key, id_key in (("char_refs", "reference_ids"), ("vibes", "vibe_ids")):
        source_ids = (
            selected.get(id_key)
            if id_key in selected else character.get(id_key)
        )
        wanted = [str(value) for value in (source_ids or []) if value]
        if not wanted:
            continue
        by_id = {
            str(item.get("id") or ""): item
            for item in (cfg.get(key) or [])
            if isinstance(item, dict) and item.get("id")
        }
        scoped[key] = [
            dict(by_id[resource_id], enabled=True)
            for resource_id in dict.fromkeys(wanted)
            if resource_id in by_id
        ]
    return scoped


def characters_resource_config(cfg, characters):
    """여러 캐릭터가 명시한 Reference·Vibe를 순서대로 합쳐 한 호출에 적용한다.

    어느 캐릭터도 id를 명시하지 않은 과거 설정은 기존 전역 선택을 그대로 쓴다.
    """
    synthetic = {"reference_ids": [], "vibe_ids": []}
    for character in characters or []:
        if not isinstance(character, dict) or character.get("enabled") is False:
            continue
        for key in ("reference_ids", "vibe_ids"):
            for value in character.get(key) or []:
                value = str(value)
                if value and value not in synthetic[key]:
                    synthetic[key].append(value)
    return character_resource_config(cfg, synthetic)


def setting_scene_people(scene, female, male, char_negative, male_negative,
                         char, cfg):
    """세팅 배치 한 장의 인물과 위치를 같은 순서로 만든다.

    씬 전용 위치가 있으면 그것이 우선이고, 없으면 기존 전역 위치 설정을
    따른다. 추가 인물까지 포함해 NAI 상한에서 함께 자르므로 프롬프트와
    좌표의 인덱스가 어긋나지 않는다.
    """
    people = [{"prompt": female, "negative": char_negative}]
    if male:
        people.append({"prompt": male, "negative": male_negative})
    extras = [e for e in (char.get("extras") or []) if isinstance(e, dict)]
    for extra in extras:
        prompt = strip_comment_lines(extra.get("prompt") or "")
        if prompt.strip():
            people.append({
                "prompt": prompt,
                "negative": strip_comment_lines(extra.get("negative") or ""),
            })
    people = people[:MAX_CHARS]

    explicit = normalize_scene_centers(scene.get("char_centers"))
    raw_cast_centers = char.get("centers") or []
    has_cast_centers = any(
        isinstance(center, dict) and center.get("x") is not None
        for center in raw_cast_centers)
    cast_mode = str(char.get("position_mode") or "").strip().lower()
    cast_mode_known = cast_mode in ("ai", "grid", "coordinate")
    cfg_mode = str(cfg.get("position_mode") or "").strip().lower()
    cfg_mode_known = cfg_mode in ("ai", "grid", "coordinate")
    if cast_mode_known:
        # 사용자가 세팅 캐스트에서 고른 모드가 저장된 옛 좌표보다 우선한다.
        # AI 자동은 좌표를 삭제하지 않되 이번 요청에는 적용하지 않는다.
        use_positions = position_mode_uses_coords(cast_mode)
    elif cfg_mode_known:
        use_positions = position_mode_uses_coords(cfg_mode)
    else:
        # mode 필드가 없던 구형 자료만 좌표 존재 여부와 use_coords로 복원한다.
        use_positions = (
            bool(explicit)
            or has_cast_centers
            or position_mode_uses_coords(None, cfg.get("use_coords"))
        )
    if not use_positions:
        return people, [], False

    defaults = spread_centers(len(people))
    cast_centers = []
    if has_cast_centers:
        for index in range(len(people)):
            center = raw_cast_centers[index] if index < len(raw_cast_centers) else None
            try:
                cast_centers.append(
                    normalize_scene_centers([center])[0]
                    if center else defaults[index])
            except (ValueError, TypeError, IndexError):
                cast_centers.append(defaults[index])
    if explicit:
        centers = list(explicit)
    elif cast_centers:
        centers = list(cast_centers)
    else:
        centers = normalize_scene_centers(cfg.get("char_centers") or [])
    for i in range(len(centers), len(people)):
        extra_index = i - (2 if male else 1)
        extra_center = (
            extras[extra_index].get("center")
            if 0 <= extra_index < len(extras) else None
        )
        try:
            center = normalize_scene_centers([extra_center])[0] if extra_center else defaults[i]
        except ValueError:
            center = defaults[i]
        centers.append(center)
    return people, centers[:len(people)], True


def _i2i_fields(i2i, action, seed):
    """이전 단일 파일 호출부를 위한 호환 어댑터."""
    return image_to_image_fields(i2i, action, seed)


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
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    model = p.get("model") or "nai-diffusion-4-5-full"
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

    # 레거시 입력 모양만 여기서 인물 목록으로 바꾸고, 좌표·Reference·img2img와
    # 최종 JSON 조립은 domain.nai_payload의 공통 계약에 맡긴다.
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
    payload, _payload_context = build_nai_payload(
        base_prompt=base_prompt,
        negative_prompt=negative,
        people=people,
        width=width,
        height=height,
        scale=scale,
        cfg_rescale=cfg_rescale,
        steps=steps,
        sampler=sampler,
        scheduler=scheduler,
        uc_preset=uc_preset,
        seed=seed,
        variety=variety,
        params=p,
        warn=log.warning,
        info=log.info,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/x-zip-compressed",
    }
    request_id = f"nai-request-{uuid.uuid4().hex}"
    payload_hash = fingerprint_payload(payload)
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
    img.nai_request_id = request_id
    img.nai_payload_hash = payload_hash
    img.nai_comment = annotate_nai_comment(
        next((chunks[k] for k in chunks if k.lower() == "comment"), ""),
        p.get("quality_toggle", False),
        uc_preset,
        request_id=request_id,
        payload_hash=payload_hash,
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


def save_with_meta(
    img,
    path,
    quality=92,
    fmt="webp",
    clean=False,
    max_side=0,
    blueprint_fingerprint="",
):
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
    # NAI가 돌려준 원문 Comment는 그대로 두고, 우리 실행 계보 식별값만 같은
    # JSON에 보강한다. clean 저장은 위에서 먼저 반환하므로 사용자가 고른
    # 메타데이터 제거 계약은 바뀌지 않는다.
    try:
        raw_comment = json.loads(str(comment or ""))
        if isinstance(raw_comment, dict):
            request_id = str(getattr(img, "nai_request_id", "") or "")
            payload_hash = str(getattr(img, "nai_payload_hash", "") or "")
            blueprint_id = str(
                blueprint_fingerprint
                or getattr(img, "nai_blueprint_fingerprint", "")
                or ""
            )
            if request_id:
                raw_comment["requestId"] = request_id
            if payload_hash:
                raw_comment["payloadHash"] = payload_hash
            if blueprint_id:
                raw_comment["blueprintFingerprint"] = blueprint_id
            comment = json.dumps(
                raw_comment, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
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
PROMOTION_LEDGER_FILE = BASE_DIR / "수집" / "승격장부.json"
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
                d.setdefault("elo", {})         # 경로 → 블라인드 비교 ELO
                d.setdefault("elo_matches", {}) # 경로 → 누적 비교 횟수
                d.setdefault("tags", {})        # 경로 → [짧은 판단 태그…]
                d.setdefault("memos", {})       # 경로 → 사용자 원문 메모
                d.setdefault("review_states", {}) # 경로 → 후보·확정·공유·보관
                return normalize_picks(d)
        except Exception as e:
            log.warning(f"선별.json 읽기 실패: {e}")
    return {
        "picked": [], "fav": [], "folders": {}, "ranks": {},
        "ratings": {}, "elo": {}, "elo_matches": {}, "tags": {},
        "memos": {}, "review_states": {},
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
    clean_elo = {}
    for path, score in (d.get("elo") or {}).items():
        try:
            number = float(score)
        except (TypeError, ValueError, OverflowError):
            continue
        if str(path).strip() and math.isfinite(number):
            clean_elo[str(path).replace("\\", "/")] = round(
                max(0.0, min(3000.0, number)), 1)
    d["elo"] = clean_elo
    d["elo_matches"] = {
        str(path).replace("\\", "/"): max(0, min(1_000_000, int(count)))
        for path, count in (d.get("elo_matches") or {}).items()
        if str(path).strip() and str(count).isdigit()
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
    d["memos"] = {
        str(path).replace("\\", "/"): str(memo)
        for path, memo in (d.get("memos") or {}).items()
        if str(path).strip() and isinstance(memo, str) and memo
    }
    allowed_states = {"candidate", "confirmed", "shared", "archived"}
    d["review_states"] = {
        str(path).replace("\\", "/"): str(state)
        for path, state in (d.get("review_states") or {}).items()
        if str(path).strip() and str(state) in allowed_states
    }
    return d


def save_picks(d):
    cleaned = normalize_picks(d)
    atomic_write_json(PICKS_FILE, cleaned, indent=1)
    return cleaned


def apply_evaluation_action(data):
    """결과 평가 결정을 기존 선별 장부와 append-only 사건으로 함께 남긴다."""
    data = data if isinstance(data, dict) else {}
    action = str(data.get("action") or "")
    with _JSON_IO_LOCK:
        picks = load_picks()
        decision_id = str(data.get("decision_id") or "").strip()
        prior_decisions = picks.get("evaluation_decision_ids")
        if not isinstance(prior_decisions, list):
            prior_decisions = []
        if action == "blind-match" and not decision_id:
            raise ValueError("블라인드 비교 결정 식별자가 필요합니다.")
        if action == "blind-match" and decision_id in prior_decisions:
            return {
                "ok": True,
                "duplicate": True,
                "appended": [],
                "picks": {
                    "elo": picks.get("elo", {}),
                    "elo_matches": picks.get("elo_matches", {}),
                    "folders": picks.get("folders", {}),
                    "review_states": picks.get("review_states", {}),
                },
            }
        paths = [
            str(value or "").replace("\\", "/")
            for value in (data.get("paths") or [])
            if str(value or "").strip()
        ]
        projection = project_legacy_evaluations(
            picks,
            result_records=[{"path": path} for path in paths],
        )
        by_path = {
            str((item.get("subject") or {}).get("path") or ""): item
            for item in projection["evaluations"]
        }
        events = []
        if action == "blind-match":
            if len(paths) != 2 or paths[0] == paths[1]:
                raise ValueError("블라인드 비교에는 서로 다른 결과 두 개가 필요합니다.")
            events.append(blind_match_event(
                by_path[paths[0]],
                by_path[paths[1]],
                outcome=str(data.get("outcome") or "first"),
                k_factor=24,
            ))
            event = events[0]
            for path, values in (
                event.get("payload", {}).get("legacy_projection") or {}
            ).items():
                picks.setdefault("elo", {})[path] = values["elo"]
                picks.setdefault("elo_matches", {})[path] = values["elo_matches"]
        elif action == "fixed-board":
            if not paths:
                raise ValueError("고정 비교판에는 결과가 필요합니다.")
            board = str(data.get("board") or "").strip()[:40]
            member = bool(data.get("member", True))
            events = [
                fixed_board_event(by_path[path], board, member=member)
                for path in paths
            ]
            members = picks.setdefault("folders", {}).setdefault(board, [])
            if member:
                members[:] = list(dict.fromkeys([*members, *paths]))
            else:
                picks["folders"][board] = [
                    item for item in members if item not in set(paths)]
        elif action == "lifecycle":
            if len(paths) != 1:
                raise ValueError("생명주기 변경에는 결과 한 개가 필요합니다.")
            state = str(data.get("state") or "")
            events.append(lifecycle_event(by_path[paths[0]], state))
            picks.setdefault("review_states", {})[paths[0]] = state
        elif action == "promotion":
            if len(paths) != 1:
                raise ValueError("승격 제안에는 결과 한 개가 필요합니다.")
            events.append(promotion_event(
                by_path[paths[0]], str(data.get("target") or "")))
        else:
            raise ValueError("지원하지 않는 평가 작업입니다.")
        if action == "blind-match" and decision_id:
            picks["evaluation_decision_ids"] = [
                *prior_decisions, decision_id]
        appended = append_evaluation_events(picks, events)
        saved = save_picks(appended["picks"])
    return {
        "ok": True,
        "event": events[0] if len(events) == 1 else None,
        "events": events,
        "appended": appended["appended"],
        "duplicate": bool(appended["duplicates"]),
        "picks": {
            "elo": saved.get("elo", {}),
            "elo_matches": saved.get("elo_matches", {}),
            "folders": saved.get("folders", {}),
            "review_states": saved.get("review_states", {}),
        },
    }


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
    planned = []
    seen = set()
    for rel in targets or ():
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if (not rel or rel in seen or rel in keep
                or rel.startswith(TRASH_DIR_NAME + "/")):
            continue
        source = (root / rel).resolve()
        if not _path_is_inside(source, root) or not source.is_file():
            continue
        # batch id가 정해지기 전에도 목적지는 항상 같은 상대 경로다.
        planned.append({"original": rel})
        seen.add(rel)
    if not planned:
        return {"deleted": 0, "batch_id": None, "paths": []}

    trash_root.mkdir(parents=True, exist_ok=True)
    for _attempt in range(8):
        batch_id = (datetime.now().strftime("%Y%m%d-%H%M%S")
                    + "-" + uuid.uuid4().hex[:12])
        batch_dir = trash_root / batch_id
        try:
            batch_dir.mkdir(parents=False, exist_ok=False)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("고유한 휴지통 묶음 폴더를 만들지 못했습니다.")

    for item in planned:
        dest = (batch_dir / item["original"]).resolve()
        if not _path_is_inside(dest, batch_dir):
            raise ValueError("휴지통 밖을 가리키는 경로가 포함되어 있습니다.")
        item["trashed"] = dest.relative_to(root).as_posix()

    picks = load_picks()
    labels = {}
    for item in planned:
        rel = item["original"]
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
        for key in ("ranks", "ratings", "elo", "elo_matches", "tags"):
            if rel in picks.get(key, {}):
                record[key] = picks[key][rel]
        if record:
            labels[rel] = record

    manifest_path = batch_dir / "manifest.json"
    manifest = {
        "schema": "nais-output-trash/v2",
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "moving",
        "items": planned,
        "labels": labels,
    }
    # 이동보다 장부를 먼저 쓴다. 이후 어느 지점에서 꺼져도 이미 옮긴 파일은
    # 목록에 다시 나타나며, 장부 쓰기 자체가 실패하면 원본은 한 장도 움직이지 않는다.
    atomic_write_json(manifest_path, manifest, indent=2)
    moved = []
    for item in planned:
        source = (root / item["original"]).resolve()
        dest = (root / item["trashed"]).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        moved.append(item)
    manifest["status"] = "ready"
    manifest["moved"] = len(moved)
    atomic_write_json(manifest_path, manifest, indent=2)
    return {
        "deleted": len(moved),
        "batch_id": batch_id,
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
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
        raise ValueError("휴지통 장부 형식이 올바르지 않습니다.")
    items = [item for item in manifest["items"] if isinstance(item, dict)]
    plan = manifest.get("restore_plan")
    if not isinstance(plan, dict):
        plan = {}
    plan_changed = False

    def unused_target(original):
        target = (root / original).resolve()
        if (not _path_is_inside(target, root)
                or _path_is_inside(target, trash_root)):
            return None
        if not target.exists():
            return target
        stem, suffix, serial = target.stem, target.suffix, 2
        while target.exists():
            target = target.with_name(f"{stem}_{serial}{suffix}")
            serial += 1
        return target

    # 모든 복원 목적지를 이동 전에 기록한다. 파일 이동 뒤 이름표 저장이 실패해도
    # 다음 실행은 이 계획으로 이미 복원된 파일을 찾아 이름표만 다시 붙일 수 있다.
    for item in items:
        original = str(item.get("original") or "").replace("\\", "/").lstrip("/")
        source = (root / str(item.get("trashed") or "")).resolve()
        if not original or not _path_is_inside(source, batch):
            continue
        planned_rel = str(plan.get(original) or "").replace("\\", "/").lstrip("/")
        planned = (root / planned_rel).resolve() if planned_rel else None
        if planned is not None and (
                not _path_is_inside(planned, root)
                or _path_is_inside(planned, trash_root)):
            planned = None
        if planned is None and source.is_file():
            planned = unused_target(original)
            if planned is not None:
                plan[original] = planned.relative_to(root).as_posix()
                plan_changed = True
    if plan_changed or manifest.get("restore_plan") != plan:
        manifest["restore_plan"] = plan
        manifest["restore_status"] = "moving"
        atomic_write_json(manifest_path, manifest, indent=2)

    restored = []
    restored_map = {}
    for item in items:
        original = str(item.get("original") or "").replace("\\", "/").lstrip("/")
        planned_rel = str(plan.get(original) or "").replace("\\", "/").lstrip("/")
        if not original or not planned_rel:
            continue
        source = (root / str(item.get("trashed") or "")).resolve()
        target = (root / planned_rel).resolve()
        if (not _path_is_inside(source, batch)
                or not _path_is_inside(target, root)
                or _path_is_inside(target, trash_root)):
            continue
        if source.is_file() and target.exists():
            # 계획 기록 뒤 외부에서 같은 이름을 만들었으면 절대 덮어쓰지 않는다.
            target = unused_target(original)
            if target is None:
                continue
            planned_rel = target.relative_to(root).as_posix()
            plan[original] = planned_rel
            manifest["restore_plan"] = plan
            atomic_write_json(manifest_path, manifest, indent=2)
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        elif not target.is_file():
            continue
        restored.append(planned_rel)
        restored_map[original] = planned_rel
    # 지울 때 함께 보관한 가상 이름표도 실제 복원 경로에 되붙인다.
    # 경로 충돌로 `(2)`가 붙었으면 옛 원래 경로가 아니라 새 파일에 붙여야 한다.
    labels = manifest.get("labels") or {}
    if restored_map and isinstance(labels, dict):
        with _JSON_IO_LOCK:
            picks = load_picks()
            for original, restored_rel in restored_map.items():
                record = labels.get(original) or {}
                if not isinstance(record, dict):
                    record = {}
                # 이동 직후 프로세스가 꺼져 이름표 정리가 끝나지 못한 경우도 있다.
                # 원래 경로의 낡은 이름표를 먼저 떼고 실제 복원된 경로로 옮긴다.
                picks["picked"] = [x for x in picks["picked"] if x != original]
                picks["fav"] = [x for x in picks["fav"] if x != original]
                for paths in picks["folders"].values():
                    paths[:] = [x for x in paths if x != original]
                for key in ("ranks", "ratings", "elo", "elo_matches", "tags"):
                    picks[key].pop(original, None)
                if record.get("picked") and restored_rel not in picks["picked"]:
                    picks["picked"].append(restored_rel)
                if record.get("fav") and restored_rel not in picks["fav"]:
                    picks["fav"].append(restored_rel)
                for name in record.get("folders") or []:
                    paths = picks["folders"].setdefault(str(name)[:40], [])
                    if restored_rel not in paths:
                        paths.append(restored_rel)
                for key in ("ranks", "ratings", "elo", "elo_matches", "tags"):
                    if key in record:
                        picks[key][restored_rel] = record[key]
            save_picks(picks)
    manifest["restored_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["restored"] = restored
    manifest["restore_status"] = "complete"
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
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
            continue
        items = [item for item in manifest["items"] if isinstance(item, dict)]
        available, size = 0, 0
        for item in items:
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
            "total": len(items),
            "bytes": size,
            "status": str(manifest.get("restore_status")
                          or manifest.get("status") or ""),
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


def comparison_manifests_for_output_dir(cfg, sub):
    """현재 출력 폴더를 감싸는 비교 manifest만 안전하게 읽는다."""
    root = out_root(cfg).resolve()
    current = (root / str(sub or "")).resolve()
    if not _path_is_inside(current, root):
        return []
    manifests = []
    while current != root:
        path = current / "manifest.json"
        if path.is_file():
            try:
                value = load_json_recover(path)
                if isinstance(value, dict):
                    value = copy.deepcopy(value)
                    value.setdefault(
                        "folder",
                        current.relative_to(root).as_posix(),
                    )
                    manifests.append(value)
            except Exception as error:
                log.warning(
                    "비교 결과 계보를 읽지 못했습니다(%s): %s",
                    path.name, error,
                )
            break
        current = current.parent
    return manifests


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
    evaluation_projection = project_legacy_evaluations(
        picks,
        comparison_manifests=comparison_manifests_for_output_dir(cfg, sub),
        result_records=[{"path": item["path"]} for item in files],
    )
    return {"ok": True, "dir": sub, "dirs": dirs, "files": files,
            "total": total, "offset": offset,
            "has_more": bool(limit and offset + len(files) < total),
            "picked": picks["picked"], "fav": picks["fav"],
            "folders": picks["folders"], "ranks": picks.get("ranks", {}),
            "ratings": picks.get("ratings", {}),
            "elo": picks.get("elo", {}),
            "elo_matches": picks.get("elo_matches", {}),
            "tags": picks.get("tags", {}),
            "memos": picks.get("memos", {}),
            "review_states": picks.get("review_states", {}),
            "evaluations": evaluation_projection["evaluations"],
            "evaluation_issues": evaluation_projection["issues"],
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

# 정적 HTML·JavaScript는 web.page_template이 소유한다.


def render_page():
    """파라미터 선택지를 파이썬 상수에서 채워 넣는다 (목록을 한 곳에서만 관리)."""
    def opts(pairs):
        return "".join(f'<option value="{v}">{esc_html(l)}</option>' for v, l in pairs)
    profile = esc_html(PROFILE)
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
            .replace("__PROFNOW__", f"프로필 「{profile}」" if profile else "기본 (첫째 계정)")
            .replace("__PROFTITLE__", f" — {profile}" if profile else "")
            .replace("__PROFBADGE__", (f'<span class="badge" style="margin-left:7px;">'
                                       f'프로필 {profile}</span>') if profile else ""))


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


def normalize_cast_presets(value):
    """캐스트 조합의 구조만 검증한다. 프롬프트 원문은 길이 제한 없이 보존한다."""
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError("cast presets must be a list with at most 200 items")
    result, seen_ids, seen_names = [], set(), set()
    for preset in value:
        if not isinstance(preset, dict):
            raise ValueError("cast preset must be an object")
        preset_id = preset.get("id")
        name = preset.get("name")
        mode = preset.get("mode", "sequence")
        position_mode = preset.get("position_mode", "")
        members = preset.get("members")
        if (not isinstance(preset_id, str) or not preset_id
                or len(preset_id) > 120
                or not re.fullmatch(r"[A-Za-z0-9._:-]+", preset_id)):
            raise ValueError("invalid cast preset id")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("invalid cast preset name")
        folded_name = name.strip().casefold()
        if preset_id in seen_ids or folded_name in seen_names:
            raise ValueError("duplicate cast preset")
        if mode not in ("sequence", "together"):
            raise ValueError("invalid cast preset mode")
        if position_mode not in ("", "ai", "grid", "coordinate"):
            raise ValueError("invalid cast preset position mode")
        if not isinstance(members, list) or not members or len(members) > 64:
            raise ValueError("cast preset must contain 1 to 64 members")
        clean_members = []
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("cast member must be an object")
            required_text = ("name", "prompt", "negative")
            optional_text = ("id", "outfit", "source_id")
            list_fields = ("reference_ids", "vibe_ids")
            object_fields = ("variant", "position")
            allowed = set(required_text + optional_text + list_fields + object_fields)
            if set(member) - allowed:
                raise ValueError("unknown cast member fields")
            clean = {}
            for field in required_text:
                text = member.get(field, "")
                if not isinstance(text, str):
                    raise ValueError("cast member fields must be strings")
                clean[field] = text
            for field in optional_text:
                if field not in member:
                    continue
                text = member[field]
                if not isinstance(text, str):
                    raise ValueError("cast member fields must be strings")
                clean[field] = text
            for field in list_fields:
                if field not in member:
                    continue
                items = member[field]
                if not isinstance(items, list) or len(items) > 64:
                    raise ValueError("cast member references must be lists")
                if any(not isinstance(item, str) for item in items):
                    raise ValueError("cast member reference ids must be strings")
                clean[field] = list(items)
            for field in object_fields:
                if field not in member:
                    continue
                item = member[field]
                if not isinstance(item, dict):
                    raise ValueError("cast member variant and position must be objects")
                clean[field] = copy.deepcopy(item)
            clean_members.append(clean)
        clean_preset = {
            "id": preset_id,
            "name": name.strip(),
            "members": clean_members,
        }
        if "mode" in preset:
            clean_preset["mode"] = mode
        if "position_mode" in preset:
            clean_preset["position_mode"] = position_mode
        result.append(clean_preset)
        seen_ids.add(preset_id)
        seen_names.add(folded_name)
    return result


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
        elif key == "cast_presets":
            used = normalize_cast_presets(value)
        elif key == "blueprint_projects":
            used = normalize_projects(value)
        elif key == "blueprint_inheritance":
            used = normalize_link(value)
        elif key == "position_mode":
            used = str(value or "").strip().lower()
            if used not in ("", "ai", "grid", "coordinate"):
                raise ValueError("unsupported position mode")
        else:
            return True, value, fixed
    except (TypeError, ValueError, OverflowError):
        return False, current, fixed
    if used != value:
        fixed[key] = {"sent": value, "used": used}
    return True, used, fixed


PUBLIC_COLLECTION_FILE = BASE_DIR / "수집" / "공개자료수집-진행.json"


def _local_import_image(data, content_type, source_url=""):
    """수집한 NAI 원본을 내용 주소로 보관한다.

    썸네일로 다시 인코딩하지 않아 EXIF/스텔스 메타데이터를 잃지 않는다. 브라우저는
    카드가 화면에 들어올 때만 `/img`를 요청하므로 원본 보관과 지연 표시가 양립한다.
    """
    content_type = str(content_type or "").split(";", 1)[0].lower()
    ext = {"image/png": ".png", "image/webp": ".webp",
           "image/jpeg": ".jpg"}.get(content_type)
    if not ext:
        raise ValueError("PNG/WebP/JPEG 이미지만 보관할 수 있습니다.")
    digest = hashlib.sha256(data).hexdigest()
    name = digest + ext
    path = IMG_CACHE / name
    created = False
    IMG_CACHE.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write_bytes(path, data, keep_backup=False)
        created = True
    if source_url:
        note_image_origin(source_url, data, pack="아카라이브 공개자료")
    return f"local:{name}", created


def _style_record_from_public_image(data, content_type, article):
    """공개 이미지의 NAI 메타를 프롬프트 무손실 그림체 묶음으로 바꾼다."""
    meta = extract_nai_metadata(data, content_type)
    if meta["metadata_status"] != "ok":
        return None
    params = dict(meta.get("params") or {})
    source_model = model_id_from_metadata(
        params.get("model"), "nai-diffusion-4-5-full")
    uc_preset, user_negative = split_uc_preset(
        meta.get("negative") or "", source_model)
    if "uc_preset" not in params and uc_preset is not None:
        params["uc_preset"] = uc_preset
        params["uc_preset_guessed"] = True
    base_prompt, quality_toggle = restore_quality_prompt(
        meta.get("base") or "", source_model, params)
    if "quality_toggle" not in params:
        params["quality_toggle"] = quality_toggle
        params["quality_toggle_guessed"] = True
    artists, rest = parse_artist_combo(base_prompt)
    article_id = str(article.get("article_id") or "")
    image_digest = hashlib.sha256(data).hexdigest()
    return {
        "id": f"arca-{article_id}-{image_digest[:12]}",
        "title": str(article.get("title") or f"아카라이브 {article_id}")[:160],
        "source": "아카라이브",
        "tab": str(article.get("board_tab") or ""),
        "posted_at": str(article.get("posted_at") or ""),
        "recommend": article.get("recommend"),
        "views": article.get("views"),
        "url": str(article.get("source_url") or ""),
        "count": len(artists),
        "combo": ", ".join(
            f"{weight:g}::artist:{name}::" if weight is not None
            else f"artist:{name}" for weight, name in artists),
        "artists": [name for _, name in artists],
        "weights": {
            name: (weight if weight is not None else 1.0)
            for weight, name in artists
        },
        "base": base_prompt,
        "rest": ", ".join(rest),
        "negative": (
            user_negative if uc_preset is not None
            else meta.get("negative") or ""),
        "negative_full": meta.get("negative") or "",
        "characters": copy.deepcopy(meta.get("characters") or []),
        "metadata_raw": copy.deepcopy(meta.get("raw") or {}),
        "params": params,
        "images": [],
    }


class PublicCollectionManager(_PublicCollectionManager):
    """기존 import와 patch 지점을 유지하는 공개자료 서비스 연결."""

    def __init__(self, state_file=None):
        super().__init__(
            state_file or PUBLIC_COLLECTION_FILE,
            style_record_from_image=lambda *args: _style_record_from_public_image(*args),
            local_import_image=lambda *args: _local_import_image(*args),
            add_style_record=lambda *args, **kwargs: add_style(*args, **kwargs),
        )


PUBLIC_COLLECTION = PublicCollectionManager()


JOB_LEDGER_FILE = PROFILE_DIR / "작업대기열.json"
_COMMON_JOB_STORE = None
_COMMON_JOB_STORE_ROOT = None


def common_job_store():
    """현재 프로필의 공통 실행 장부. 테스트의 임시 장부 경로도 그대로 따른다."""
    global _COMMON_JOB_STORE, _COMMON_JOB_STORE_ROOT
    root = (JOB_LEDGER_FILE.parent / "작업기록").resolve()
    if _COMMON_JOB_STORE is None or _COMMON_JOB_STORE_ROOT != root:
        _COMMON_JOB_STORE = JobStore(root)
        _COMMON_JOB_STORE_ROOT = root
    return _COMMON_JOB_STORE


def _runtime_kind(operation, legacy_kind):
    text = f"{operation} {legacy_kind}".casefold()
    if "비교" in text or "comparison" in text:
        return "comparison"
    if "img2img" in text:
        return "img2img"
    if "인페인트" in text or "inpaint" in text:
        return "inpaint"
    if "director" in text or "디렉터" in text:
        return "director"
    if "vibe" in text or "바이브" in text:
        return "vibe_encoding"
    if legacy_kind in ("settings", "generation") or "씬" in text or "세팅" in text:
        return "setting"
    return "single"


def load_job_ledger():
    """모든 생성 경로의 최근 실행 기록. 실제 재개 자료는 각 기능의 기존 장부가 기준이다."""
    if not JOB_LEDGER_FILE.is_file():
        return {"schema": "nais-job-ledger/v1", "jobs": []}
    data = load_json_recover(JOB_LEDGER_FILE)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("작업대기열 기록 형식이 올바르지 않습니다.")
    jobs = [
        dict(item) for item in data["jobs"][-200:]
        if isinstance(item, dict) and item.get("id")
    ]
    return {"schema": "nais-job-ledger/v1", "jobs": jobs}


def _save_job_ledger(data):
    data = {
        "schema": "nais-job-ledger/v1",
        "jobs": list(data.get("jobs") or [])[-200:],
    }
    atomic_write_json(JOB_LEDGER_FILE, data, indent=1)
    return data


def recover_job_ledger():
    """프로세스가 꺼진 채 남은 running 기록만 interrupted로 닫는다."""
    with _JSON_IO_LOCK:
        data = load_job_ledger()
        changed = False
        now = datetime.now().isoformat(timespec="seconds")
        for job in data["jobs"]:
            if job.get("status") in ("running", "stopping"):
                job["status"] = "interrupted"
                job["updated_at"] = now
                job["can_resume"] = job.get("kind") in (
                    "settings", "comparison", "collection", "recovery")
                changed = True
        data = _save_job_ledger(data) if changed else data
        try:
            common_job_store().recover_all()
        except Exception as error:
            # 손상 장부를 초기화하거나 덮지 않는다. 관리 화면의 기존 장부는 계속
            # 열고, 공통 장부 오류는 진단 로그로 남긴다.
            log.error("공통 작업 장부 복구 실패: %s", error)
        return data


def start_job_record(operation, kind, *, blueprint=None, payload_identity=None):
    with _JSON_IO_LOCK:
        data = recover_job_ledger()
        now = datetime.now().isoformat(timespec="seconds")
        record = {
            "id": f"job-{uuid.uuid4().hex}",
            "operation": str(operation or "생성")[:120],
            "kind": str(kind or "preview")[:40],
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "completed": 0,
            "failed": 0,
            "can_resume": False,
        }
        data["jobs"].append(record)
        _save_job_ledger(data)
        blueprint_digest = fingerprint_blueprint(
            blueprint or {"source": {"kind": str(kind or "preview")}}
        )
        payload_digest = fingerprint_payload(
            payload_identity or {
                "operation": str(operation or "생성"),
                "kind": str(kind or "preview"),
                "blueprint_fingerprint": blueprint_digest,
            }
        )
        runtime_job = new_job(
            _runtime_kind(operation, kind),
            blueprint_fingerprint=blueprint_digest,
            payload_hash=payload_digest,
            request_id=record["id"],
            job_id=record["id"],
            metadata={
                "legacy_kind": str(kind or "preview"),
                "operation": str(operation or "생성"),
            },
            now=now,
        )
        runtime_job = transition_job(runtime_job, "preparing", now=now)
        common_job_store().save(runtime_job)
        return record["id"]


def _finish_durable_job(existing, projected):
    """legacy 진행 관찰값만 합치고 시작 때 확정한 durable identity는 보존한다."""
    if not isinstance(existing, dict):
        return projected
    if (
        existing.get("phase") == "cancelled"
        and projected.get("phase") != "cancelled"
    ):
        return existing
    target = str(projected.get("phase") or "")
    progress = copy.deepcopy(projected.get("progress") or {})
    if target == "completed":
        has_verified_result = bool(existing.get("results"))
        merged = reconcile_job(
            existing,
            {
                "progress": progress,
                # 실행 스레드가 완료라고 말해도 저장 뒤 해시를 확인해 장부에
                # 등록한 결과가 하나도 없으면 완료로 닫지 않는다.
                "confirmed_complete": has_verified_result,
                "artifacts_intact": has_verified_result,
            },
            now=str(projected.get("updated_at") or ""),
        )
    else:
        merged = update_progress(
            existing,
            completed=progress.get("completed"),
            failed=progress.get("failed"),
            total=progress.get("total"),
            message=progress.get("message"),
            now=str(projected.get("updated_at") or ""),
        )
        if target in ("paused", "failed", "cancelled"):
            if merged.get("phase") != target:
                merged = transition_job(
                    merged,
                    target,
                    error=(copy.deepcopy(projected.get("error"))
                           if target == "failed" else None),
                    now=str(projected.get("updated_at") or ""),
                )
    return merged


def finish_job_record(job_id, *, status, completed=0, failed=0,
                      can_resume=False, message=""):
    if not job_id:
        return
    with _JSON_IO_LOCK:
        data = load_job_ledger()
        for job in reversed(data["jobs"]):
            if job.get("id") != job_id:
                continue
            job.update({
                "status": str(status or "completed"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "completed": max(0, int(completed or 0)),
                "failed": max(0, int(failed or 0)),
                "can_resume": bool(can_resume),
                "message": str(message or "")[:500],
            })
            projected = from_legacy_job_record(job)
            try:
                existing = common_job_store().get(job_id)
            except Exception:
                existing = None
            common_job_store().save(
                _finish_durable_job(existing, projected))
            break
        _save_job_ledger(data)


def record_job_result(
    job_id,
    path,
    *,
    artifact="",
    source_result_ids=(),
    result_id="",
):
    """저장된 결과 파일을 실행 중인 공통 Job에 연결한다.

    파일 저장이 끝난 뒤에만 호출하며, 절대경로·토큰·프롬프트는 장부에 넣지 않는다.
    기존 기능별 progress/manifest는 그대로 유지하는 호환 투영이다.
    """
    if not job_id:
        return None
    result_path = Path(path)
    if not result_path.is_file():
        raise ValueError("결과 파일을 확인할 수 없어 Job에 완료로 기록하지 않았습니다.")
    content_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
    safe_artifact = str(artifact or result_path.name).replace("\\", "/")
    if Path(safe_artifact).is_absolute() or ".." in Path(safe_artifact).parts:
        safe_artifact = result_path.name
    stable_result_id = str(result_id or "").strip()
    if not stable_result_id:
        stable_result_id = "result-" + hashlib.sha256(
            f"{job_id}\0{safe_artifact}\0{content_hash}".encode("utf-8")
        ).hexdigest()[:32]
    store = common_job_store()
    job = store.get(job_id)
    changed = add_result(
        job,
        stable_result_id,
        artifact=safe_artifact,
        content_hash=content_hash,
        source_result_ids=source_result_ids,
    )
    store.save(changed)
    return next(
        item for item in changed["results"]
        if item.get("id") == stable_result_id)


def link_job_ancestor(job_id, source_job_id):
    """재개 시 이전 실행 Job을 현재 실행의 부모 계보로만 연결한다."""
    current = str(job_id or "")
    source = str(source_job_id or "")
    if not current or not source or current == source:
        return None
    store = common_job_store()
    job = store.get(current)
    ancestry = job.setdefault("lineage", {}).setdefault(
        "source_job_ids", [])
    if source not in ancestry:
        ancestry.append(source)
        store.save(job)
    return job


def job_ledger_summary():
    data = load_job_ledger()
    jobs = list(reversed(data["jobs"]))
    try:
        durable = common_job_store().list()
        durable_by_id = {str(item.get("id") or ""): item for item in durable}
        durable_error = ""
    except Exception as error:
        durable = []
        durable_by_id = {}
        durable_error = redact_diagnostic_text(error)
    contracts = []
    for item in jobs:
        stored = durable_by_id.get(str(item.get("id") or ""))
        if stored:
            contracts.append(stored)
            continue
        try:
            contracts.append(from_legacy_job_record(item))
        except Exception as error:
            contracts.append({
                "schema": "nai-runtime-job/v1",
                "id": str(item.get("id") or ""),
                "phase": "invalid",
                "error": redact_diagnostic_text(error),
            })
    return {
        "ok": True,
        **data,
        "jobs": jobs,
        "contracts": contracts,
        "durable_jobs": list(reversed(durable)),
        "durable_error": durable_error,
    }


class LiveState(RuntimeLiveState):
    """레거시 장부 함수를 새 실행 상태 경계에 연결하는 호환 어댑터."""

    def __init__(self, persist_jobs=False):
        super().__init__(
            persist_jobs=persist_jobs,
            daily_cap=DAILY_CAP,
            start_job=start_job_record,
            finish_job=finish_job_record,
        )


class ConfigServer:
    """설정 편집(실시간 자동저장) + 생성 시작 신호 + 실시간 미리보기를 모두 담당."""

    def __init__(self, cfg, persist_jobs=False):
        self.cfg = cfg
        self.spec = load_spec()
        self.live = LiveState(persist_jobs=persist_jobs)
        self.start_event = threading.Event()
        self.httpd = None
        self.url = None
        self.config_lock = threading.RLock()
        self.config_revision = 0
        self.anlas_balance_cache = None
        self.anlas_balance_token_key = None
        self.pending_batch_config = None
        # 백업 원문은 디스크에 임시 저장하지 않고 마지막 검사본 한 개만 메모리에 둔다.
        # 선택 복원 요청은 SHA와 diff 지문이 모두 맞을 때만 이 바이트를 사용한다.
        self.backup_preview_blob = None
        self.backup_preview_sha256 = ""
        self.pack_preview_blob = None
        self.pack_preview_sha256 = ""
        self.pack_preview_filename = ""
        self.pending_variation = None

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
            latest = load_settings_recover(SETTINGS_FILE)
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

    def snapshot_blueprint(self):
        """현재 화면값의 파생 설계도. 토큰과 전체 사용자 자료는 포함하지 않는다."""
        with self.config_lock:
            resolution = inherited_blueprint_resolution(self.cfg)
            return {
                "ok": True,
                # 기존 소비자는 계속 blueprint 하나만 읽어도 된다.
                "blueprint": resolution["blueprint"],
                "inheritance": {
                    **copy.deepcopy(resolution.get("project") or {}),
                    "projects": [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "fingerprint": item.get("fingerprint"),
                            "updated_at": item.get("updated_at"),
                        }
                        for item in (self.cfg.get("blueprint_projects") or [])
                        if isinstance(item, dict)
                    ],
                    "provenance": copy.deepcopy(
                        resolution.get("provenance") or {}),
                    "conflicts": copy.deepcopy(
                        resolution.get("conflicts") or []),
                },
                "knowledge_assets": knowledge_assets_from_config(self.cfg),
            }

    @serialized_data_write(lambda: CHAR_DIR.parent)
    def handle_blueprint_project(self, body):
        """프로젝트 공통값 저장·연결·갱신은 자동저장과 분리해 명시적으로 처리."""
        try:
            request = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return {"ok": False, "error": "잘못된 프로젝트 요청입니다."}
        action = str(request.get("action") or "").strip().lower()
        if action not in ("create", "update", "activate", "accept", "disconnect"):
            return {"ok": False, "error": "알 수 없는 프로젝트 작업입니다."}
        with self.config_lock:
            cfg = self.latest_config_from_disk()
            projects = normalize_projects(cfg.get("blueprint_projects") or [])
            link = normalize_link(cfg.get("blueprint_inheritance") or {})
            project_id = str(request.get("id") or link.get("project_id") or "")
            current = generation_blueprint(cfg)

            if action in ("create", "update"):
                name = str(request.get("name") or "").strip()
                if not name or len(name) > 120:
                    return {"ok": False, "error": "프로젝트 이름을 1~120자로 적어주세요."}
                if action == "create":
                    project_id = f"project-{uuid.uuid4().hex}"
                existing = project_by_id(projects, project_id)
                if action == "update" and existing is None:
                    return {"ok": False, "error": "갱신할 프로젝트를 찾지 못했습니다."}
                common = blueprint_common(current)
                record = {
                    "id": project_id,
                    "name": name,
                    "blueprint": common,
                    "fingerprint": fingerprint_blueprint(common),
                    "updated_at": datetime.now().astimezone().isoformat(
                        timespec="seconds"),
                }
                projects = [
                    item for item in projects if item.get("id") != project_id
                ] + [record]
                cfg["blueprint_projects"] = normalize_projects(projects)

            elif action == "activate":
                project = project_by_id(projects, project_id)
                if project is None:
                    return {"ok": False, "error": "연결할 프로젝트를 찾지 못했습니다."}
                accepted = blueprint_common(project["blueprint"])
                new_link = {
                    "schema": "nai-blueprint-inheritance/v1",
                    "project_id": project_id,
                    "accepted_fingerprint": project["fingerprint"],
                    "accepted_blueprint": accepted,
                    "local_overrides": {},
                }
                resolution = resolve_inheritance(
                    current, projects, new_link)
                cfg = materialize_blueprint_into_config(
                    cfg, resolution["blueprint"])
                cfg["blueprint_projects"] = projects
                cfg["blueprint_inheritance"] = normalize_link(new_link)

            elif action == "accept":
                if not link:
                    return {"ok": False, "error": "연결된 프로젝트가 없습니다."}
                project = project_by_id(projects, link["project_id"])
                if project is None:
                    return {"ok": False, "error": "프로젝트 원본을 찾지 못했습니다."}
                expected = str(request.get("fingerprint") or "")
                if expected and expected != str(project.get("fingerprint") or ""):
                    return {
                        "ok": False,
                        "conflict": True,
                        "error": "확인 뒤 프로젝트 공통값이 다시 바뀌었습니다. 내용을 다시 확인해 주세요.",
                    }
                new_link = copy.deepcopy(link)
                new_link["accepted_blueprint"] = blueprint_common(
                    project["blueprint"])
                new_link["accepted_fingerprint"] = project["fingerprint"]
                # 명시해 둔 현재 변경만 새 부모보다 위에 유지한다.
                resolution = resolve_inheritance(
                    current, projects, new_link)
                cfg = materialize_blueprint_into_config(
                    cfg, resolution["blueprint"])
                cfg["blueprint_projects"] = projects
                cfg["blueprint_inheritance"] = normalize_link(new_link)

            else:  # disconnect
                cfg["blueprint_inheritance"] = {}

            save_config(cfg)
            self.cfg.clear()
            self.cfg.update(cfg)
            self.config_revision += 1
            snapshot = self.snapshot_blueprint()
            snapshot.update({
                "revision": self.config_revision,
                "project_id": project_id,
            })
            return snapshot

    def snapshot_sequence(self, name=""):
        """기존 세팅 파일을 바꾸지 않고 공통 순서 계획으로 보여 준다."""
        selected = next(
            (item for item in list_settings()
             if str(item.get("name") or "") == str(name or "")),
            None,
        )
        if selected is None:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        plan = sequence_plan_from_setting(selected)
        return {
            "ok": True,
            "sequence": plan,
            "steps": len(plan["steps"]),
        }

    def snapshot_jobs(self):
        """기존 장부와 현재 실행·비교 진행을 공통 Job 계약으로 함께 보여 준다."""
        summary = job_ledger_summary()
        active_contracts = []
        issues = []
        live = self.live.snapshot()
        if live.get("running") or live.get("phase") not in ("", "idle"):
            try:
                frozen_blueprint = self.live.frozen_blueprint()
                active_contracts.append(project_live_state(
                    live,
                    kind=_runtime_kind(
                        live.get("operation"), live.get("retry_mode")),
                    job_id=live.get("job_id") or "",
                    blueprint=(
                        frozen_blueprint or inherited_blueprint(
                            self.cfg,
                            source={"kind": "live-state-projection-fallback"},
                        )
                    ),
                    payload_identity={
                        "operation": live.get("operation"),
                        "seed_key": live.get("seed_key"),
                        "total": live.get("total"),
                    },
                ))
            except Exception as error:
                issues.append({
                    "source": "live-state",
                    "error": redact_diagnostic_text(error),
                })
        progress = _comparison_progress_load()
        live_is_current_comparison = (
            bool(live.get("running"))
            and "비교" in str(live.get("operation") or "")
        )
        if progress.get("signature") and not live_is_current_comparison:
            try:
                active_contracts.append(project_comparison_progress(progress))
            except Exception as error:
                issues.append({
                    "source": "comparison-progress",
                    "error": redact_diagnostic_text(error),
                })
        summary["active_contracts"] = active_contracts
        summary["projection_issues"] = issues
        return summary

    def handle_job_command(self, body):
        """Job 센터 조작을 기존 실행기의 안전한 진입점으로 연결한다."""
        data = json.loads(body or b"{}")
        job_id = str(data.get("job_id") or "")
        action = str(data.get("action") or "")
        if not job_id or action not in (
            "pause", "cancel", "retry", "resume", "reconcile",
        ):
            raise ValueError("작업과 명령을 올바르게 골라주세요.")
        store = common_job_store()
        job = store.get(job_id)
        command = make_job_command(
            job, action, observation=data.get("observation"))
        handler = command.get("handler") or {}
        handled = False
        navigation = ""
        message = ""

        if action in ("pause", "cancel"):
            live = self.live.snapshot()
            if (
                not live.get("running")
                or str(live.get("job_id") or "") != job_id
            ):
                raise ValueError(
                    "이 기록은 현재 NAI 실행권을 가진 작업이 아닙니다. "
                    "무관한 현재 작업은 멈추지 않았습니다.")
            handled = self.live.request_stop()
            updated = transition_job(job, command["next_phase"])
        elif action in ("retry", "resume"):
            if handler.get("target") == "comparison":
                activated = activate_comparison_run(
                    self.cfg, handler.get("folder"))
                if not activated.get("resumable"):
                    raise ValueError(
                        "이 비교 기록은 완료됐거나 재개 근거가 없습니다.")
                handled = True
                navigation = "compare"
                message = (
                    "중단 지점을 활성화했습니다. 장수와 비용을 확인한 뒤 실행하세요."
                )
                updated = (
                    retry_job(job) if action == "retry"
                    else transition_job(job, command["next_phase"])
                )
            else:
                navigation = (
                    "settings" if job.get("kind") == "setting" else "preview")
                message = (
                    "원래 작업 화면으로 이동합니다. 현재 입력과 비용을 확인해 "
                    "실제로 다시 실행할 때까지 작업 상태는 바꾸지 않았습니다."
                )
                updated = job
        else:
            # make_job_command가 whitelist로 정제한 관찰값만 저장한다.
            updated = reconcile_job(job, command.get("observation") or {})
            handled = True
            message = "디스크의 실제 결과와 작업 기록을 대조했습니다."
        store.save(updated)
        return {
            "ok": True,
            "handled": handled,
            "command": command,
            "job": updated,
            "navigation": navigation,
            "message": message,
        }

    def handle_generate_one(self):
        """① 설정만으로 단독 1장 생성 (세팅 무관 — NAI 기본 생성처럼)"""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        # 누른 순간의 설계도를 고정한다. 실행 중 자동 저장이나 화면 편집이 들어와도
        # 이미 시작한 요청의 프롬프트·인물·좌표·출력 설정이 섞이지 않는다.
        with self.config_lock:
            cfg = copy.deepcopy(self.cfg)
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        blueprint = inherited_blueprint(
            cfg, source={"kind": "single-generate"})
        material = single_generation_legacy_material(blueprint)
        job_cfg = copy.deepcopy(cfg)
        job_cfg.update(material.get("config_overrides") or {})
        job_cfg = characters_resource_config(
            job_cfg, blueprint.get("characters") or [])
        call = material["call"]
        tok = self.live.try_claim(
            "단독 생성",
            "preview",
            blueprint=blueprint,
            payload_identity={"kind": "single", "output": "one-image"},
        )
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        def run():
            self.live.update(status_text="단독 생성 중...", char_name="단독 생성",
                             filename="", index=1, total=1)
            try:
                okp, why = pace_gate(job_cfg, self.live, "단독")   # 밴 예방 (CQA-013)
                if not okp:
                    self.live.update(
                        status_text=why, phase="stopped", can_retry=True)
                    return
                style = str(call.get("base_prompt") or "").strip()
                base = style or "1girl"
                people = copy.deepcopy(call.get("characters") or [])
                ctrs = copy.deepcopy(call.get("char_centers") or [])
                params = runtime_generation_params(job_cfg, cfg["token"])
                state = load_state()
                try:
                    img = call_nai_api(
                        cfg["token"], base, "", "",
                        call.get("negative_prompt", ""),
                        int(call.get("width") or 832), int(call.get("height") or 1216),
                        chars=people,
                        scale=job_cfg.get("cfg_scale", 5.5),
                        cfg_rescale=job_cfg.get("cfg_rescale", 0.56),
                        steps=int(job_cfg.get("steps", 28)),
                        sampler=job_cfg.get("sampler", "k_euler_ancestral"),
                        scheduler=job_cfg.get("scheduler", "karras"),
                        variety=job_cfg.get("variety", False),
                        uc_preset=int(job_cfg.get("uc_preset", 3)),
                        seed=call.get("seed") or None,
                        params=with_centers(params, ctrs))
                finally:
                    pace_complete()
                img.nai_blueprint_fingerprint = blueprint["fingerprint"]
                out_dir = out_sub(job_cfg, "단독")
                n = len([x for x in out_dir.iterdir() if x.suffix.lower() in (".webp", ".png")]) + 1
                saved = save_with_meta(
                    img, out_dir / f"{n:04d}.webp",
                    fmt=out_format(job_cfg), clean=_ocargs(job_cfg)[0],
                    max_side=_ocargs(job_cfg)[1], quality=out_clean(job_cfg)[2])
                rel_saved = saved.resolve().relative_to(
                    out_root(job_cfg).resolve()).as_posix()
                record_job_result(
                    self.live.job_id, saved, artifact=rel_saved)
                self.live.set_image(img)
                bump_daily(state)
                save_state(state)
                self.live.update(
                    status_text=(
                        "단독 생성 완료 ✓ ("
                        + rel_saved
                        + ")"
                    ),
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
        """img2img · 인페인트 · Outpaint.
        Outpaint는 넓힌 캔버스와 바깥 마스크를 기존 infill 실행 계층에 태운다.
        body: {image, mask, original?, operation, expansion?, strength, noise, seed}"""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        with self.config_lock:
            cfg = copy.deepcopy(self.cfg)
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        try:
            d = json.loads(body or b"{}")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        variation_mode = str(d.get("variation_mode") or "img2img").strip().lower()
        if variation_mode not in (
            "img2img", "inpaint", "character-reference", "reference-inset"
        ):
            return {"ok": False, "error": "알 수 없는 캐릭터 시험 방식입니다."}
        operation = str(d.get("operation") or "edit").strip().lower()
        if operation not in ("edit", "outpaint"):
            return {"ok": False, "error": "알 수 없는 이미지 편집 작업입니다."}
        img_b64 = (d.get("image") or "").split(",", 1)[-1]
        if not img_b64:
            return {"ok": False, "error": "원본 그림이 없습니다."}
        mask_b64 = (d.get("mask") or "").split(",", 1)[-1] or None
        if operation == "outpaint" and not mask_b64:
            return {"ok": False, "error": "Outpaint 확장 영역 마스크가 없습니다."}
        mode = "Outpaint" if operation == "outpaint" else (
            "Character Reference" if variation_mode == "character-reference"
            else "Reference inset" if variation_mode == "reference-inset"
            else "인페인트" if mask_b64 else "img2img")
        expansion = {}
        for key in ("left", "right", "top", "bottom"):
            try:
                value = int((d.get("expansion") or {}).get(key, 0))
            except (TypeError, ValueError):
                return {"ok": False, "error": f"Outpaint {key} 확장값이 올바르지 않습니다."}
            if value < 0 or value > 1536 or value % 64:
                return {"ok": False, "error": "Outpaint 확장값은 0~1536의 64px 단위여야 합니다."}
            expansion[key] = value
        if operation == "outpaint" and not any(expansion.values()):
            return {"ok": False, "error": "Outpaint 확장 방향과 크기가 없습니다."}
        try:
            raw = base64.b64decode(img_b64)
            original_source_raw = raw
            with Image.open(io.BytesIO(raw)) as im:
                w, h = im.size
            if mask_b64:
                with Image.open(io.BytesIO(base64.b64decode(mask_b64))) as mask:
                    if mask.size != (w, h):
                        return {"ok": False, "error": "원본과 마스크 크기가 다릅니다."}
        except Exception as e:
            return {"ok": False, "error": f"그림을 못 읽었습니다: {e}"}
        if variation_mode in ("character-reference", "reference-inset"):
            try:
                trial_w = int(d.get("trial_width") or cfg.get("width") or w)
                trial_h = int(d.get("trial_height") or cfg.get("height") or h)
            except (TypeError, ValueError):
                return {"ok": False, "error": "시험 해상도가 올바르지 않습니다."}
            trial_w = max(64, min(2048, trial_w // 64 * 64))
            trial_h = max(64, min(2048, trial_h // 64 * 64))
            if variation_mode == "character-reference":
                w, h = trial_w, trial_h
                mask_b64 = None
            else:
                try:
                    inset = reference_inset_canvas(
                        original_source_raw, trial_w, trial_h)
                except Exception as e:
                    return {"ok": False, "error": str(e)}
                raw = inset["image"]
                img_b64 = base64.b64encode(raw).decode("ascii")
                mask_b64 = base64.b64encode(inset["mask"]).decode("ascii")
                w, h = inset["width"], inset["height"]
        # NAI 는 64 의 배수를 원한다
        w, h = max(64, w // 64 * 64), max(64, h // 64 * 64)
        if w > 2048 or h > 2048:
            return {"ok": False, "error": "최종 크기는 가로·세로 2048px를 넘을 수 없습니다."}
        original_b64 = (d.get("original") or "").split(",", 1)[-1] or None
        try:
            source_raw = (
                base64.b64decode(original_b64)
                if original_b64 else original_source_raw
            )
            with Image.open(io.BytesIO(source_raw)) as source:
                source_size = {"width": source.width, "height": source.height}
        except Exception as e:
            return {"ok": False, "error": f"Outpaint 원본을 못 읽었습니다: {e}"}
        source_hash = hashlib.sha256(source_raw).hexdigest()
        seed = int(d.get("seed") or 0) or random.randint(0, 2**32 - 1)
        job_cfg = cfg
        variation_id = str(d.get("variation_character_id") or "").strip()
        variation_name = ""
        variation_plan = None
        transient_reference_bytes = None
        if variation_id:
            record = next(
                (item for item in cfg.get("characters", [])
                 if str(item.get("id") or "") == variation_id),
                None,
            )
            if record is None:
                return {"ok": False, "error": "변형할 캐릭터 자산을 찾지 못했습니다."}
            try:
                asset = character_asset_from_legacy_record(
                    record,
                    char_refs=cfg.get("char_refs") or [],
                    vibes=cfg.get("vibes") or [],
                )
                planned_mode = (
                    variation_mode
                    if variation_mode != "reference-inset" else "inpaint"
                )
                prompt_overrides = {}
                for target, source_key in (
                    ("appearance", "trial_appearance"),
                    ("outfit", "trial_outfit"),
                    ("negative", "trial_negative"),
                ):
                    if source_key in d:
                        prompt_overrides[target] = str(d.get(source_key) or "")
                temporary_settings = {
                    "strength": (
                        1.0 if variation_mode == "reference-inset"
                        else float(d.get("strength", 0.7))
                    ),
                    "noise": (
                        0.0 if variation_mode == "reference-inset"
                        else float(d.get("noise", 0.0))
                    ),
                    "reference_strength": float(
                        d.get("reference_strength", 1.0)),
                    "reference_fidelity": float(
                        d.get("reference_fidelity", 0.6)),
                }
                plan = variation_plan_to_legacy_payload_material(asset, {
                    "mode": planned_mode,
                    "source_image": {
                        "content_hash": hashlib.sha256(raw).hexdigest()},
                    "reference": (
                        {"content_hash": source_hash}
                        if variation_mode == "character-reference" else None
                    ),
                    "mask": ({"content_hash": hashlib.sha256(
                        base64.b64decode(mask_b64)).hexdigest()}
                             if mask_b64 else None),
                    "inset": (
                        {"content_hash": source_hash}
                        if variation_mode == "reference-inset" else None
                    ),
                    "prompt_overrides": prompt_overrides,
                    "seed": seed,
                    "resolution": {"width": w, "height": h},
                    "temporary_settings": temporary_settings,
                })
            except Exception as e:
                return {"ok": False, "error": f"캐릭터 변형 계획을 만들지 못했습니다: {e}"}
            job_cfg = copy.deepcopy(cfg)
            job_cfg["char_slots"] = plan["char_slots"]
            if variation_mode == "character-reference":
                # Character Reference와 Vibe는 NAI에서 동시에 쓸 수 없다. 저장 자산의
                # 연결은 유지하고, 이 요청 한 번에서만 새 Reference를 사용한다.
                job_cfg["char_refs"] = [copy.deepcopy(plan["char_refs"][0])]
                job_cfg["vibes"] = []
                transient_reference_bytes = original_source_raw
            else:
                job_cfg["char_refs"] = plan["char_refs"]
                job_cfg["vibes"] = plan["vibes"]
            if "trial_scene_prompt" in d:
                job_cfg["base_prompt"] = str(d.get("trial_scene_prompt") or "")
            if "trial_base_negative" in d:
                job_cfg["negative_prompt"] = str(
                    d.get("trial_base_negative") or "")
            job_cfg["width"], job_cfg["height"] = w, h
            variation_plan = copy.deepcopy(plan["variation_plan"])
            variation_name = str(record.get("name") or variation_id)
        tok = self.live.try_claim(
            mode,
            "preview",
            blueprint=inherited_blueprint(
                job_cfg,
                source={
                    "kind": "character-variation" if variation_id else (
                        "outpaint" if operation == "outpaint" else "image-edit"),
                    "mode": mode,
                    "character_id": variation_id,
                    "content_hash": source_hash,
                    "source_size": source_size,
                    "expansion": expansion if operation == "outpaint" else None,
                },
            ),
            payload_identity={
                "kind": operation if operation == "outpaint" else (
                    "inpaint" if mask_b64 else "img2img"),
                "width": w,
                "height": h,
                "has_mask": bool(mask_b64),
                "source_hash": source_hash,
                "expansion": expansion if operation == "outpaint" else None,
                "character_id": variation_id,
            },
        )
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}
        if transient_reference_bytes is not None:
            job_cfg["char_refs"][0]["_image_bytes"] = transient_reference_bytes
            job_cfg["char_refs"][0]["_required"] = True
        with self.config_lock:
            self.pending_variation = ({
                "character_id": variation_id,
                "character_name": variation_name,
                "asset_fingerprint": (
                    variation_plan.get("character_asset_fingerprint")
                    if variation_plan else ""),
                "plan": copy.deepcopy(variation_plan),
                "mode": variation_mode,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "result_path": "",
                "job_id": self.live.job_id,
            } if variation_id else None)

        def run():
            label = f"{variation_name} 변형" if variation_name else mode
            self.live.update(status_text=f"{label} 생성 중...",
                             char_name=label, index=1, total=1)
            try:
                okp, why = pace_gate(job_cfg, self.live, mode)     # 밴 예방 (CQA-013)
                if not okp:
                    self.live.update(
                        status_text=why, phase="stopped", can_retry=True)
                    return
                slots = [s for s in job_cfg.get("char_slots", [])
                 if slot_prompt(s).strip() and s.get("enabled") is not False]
                params = runtime_generation_params(job_cfg, job_cfg["token"])
                if variation_mode != "character-reference":
                    params["_i2i"] = {
                        "image": img_b64,
                        "mask": mask_b64,
                        "strength": (
                            1.0 if variation_mode == "reference-inset"
                            else float(d.get("strength", 0.7))
                        ),
                        "noise": (
                            0.0 if variation_mode == "reference-inset"
                            else float(d.get("noise", 0.0))
                        ),
                        "seed": seed,
                    }
                try:
                    img = call_nai_api(
                        job_cfg["token"], job_cfg.get("base_prompt", "") or "1girl", "", "",
                        job_cfg.get("negative_prompt", ""), w, h,
                        chars=active_people(slots, job_cfg.get("char_centers"))[0],
                        scale=job_cfg.get("cfg_scale", 5.5), cfg_rescale=job_cfg.get("cfg_rescale", 0.56),
                        steps=int(job_cfg.get("steps", 28)), sampler=job_cfg.get("sampler", "k_euler_ancestral"),
                        scheduler=job_cfg.get("scheduler", "karras"), variety=job_cfg.get("variety", False),
                        uc_preset=int(job_cfg.get("uc_preset", 3)), seed=seed,
                        params=with_centers(params, active_people(slots, job_cfg.get("char_centers"))[1]))
                finally:
                    pace_complete()
                out_dir = out_sub(job_cfg, "캐릭터 변형" if variation_id else mode)
                n = len([x for x in out_dir.iterdir() if x.suffix.lower() in (".webp", ".png")]) + 1
                frozen = self.live.frozen_blueprint()
                img.nai_blueprint_fingerprint = str(
                    (frozen or {}).get("fingerprint") or "")
                saved = save_with_meta(
                    img, out_dir / f"{n:04d}.webp", fmt=out_format(job_cfg),
                    clean=_ocargs(job_cfg)[0], max_side=_ocargs(job_cfg)[1],
                    quality=out_clean(job_cfg)[2])
                record_job_result(
                    self.live.job_id,
                    saved,
                    artifact=saved.resolve().relative_to(
                        out_root(job_cfg).resolve()).as_posix(),
                )
                if variation_id:
                    with self.config_lock:
                        pending = self.pending_variation
                        if (
                            isinstance(pending, dict)
                            and pending.get("character_id") == variation_id
                            and pending.get("job_id") == self.live.job_id
                        ):
                            pending.update({
                                "result_path": str(saved.resolve()),
                                "result_hash": hashlib.sha256(
                                    saved.read_bytes()).hexdigest(),
                                "seed": seed,
                                "width": w,
                                "height": h,
                                "completed_at": datetime.now().isoformat(
                                    timespec="seconds"),
                            })
                self.live.set_image(img)
                st = load_state(); bump_daily(st); save_state(st)
                self.live.update(
                    status_text=f"{label} 완료 ✓ (output/{out_dir.name}/{saved.name} · 시드 {seed})",
                    seed=seed, completed=1, phase="completed")
            except Exception as e:
                log.error(f"{mode} 실패: {e}")
                self.live.update(
                    status_text=f"{mode} 실패: {e}", failed=1,
                    last_error=str(e), can_retry=True, phase="failed")
            finally:
                self.live.release(tok)

        threading.Thread(target=run, daemon=True).start()
        return {
            "ok": True, "mode": mode, "width": w, "height": h,
            "source_hash": source_hash, "expansion": (
                expansion if operation == "outpaint" else None),
            "variation_character": variation_name,
            "variation_mode": variation_mode if variation_id else "",
            "temporary": bool(variation_id),
            "vibe_suppressed": bool(
                variation_id and variation_mode == "character-reference"
                and plan.get("vibes")),
        }

    @serialized_data_write(lambda: CHAR_DIR.parent)
    def handle_character_variation_save(self, body):
        """완료된 고정 결과를 명시 선택한 캐릭터 자산 항목에만 추가한다."""
        try:
            request = json.loads(body or b"{}")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        save_as = str(request.get("save_as") or "").strip()
        if save_as not in ("representative", "evidence", "variation"):
            return {"ok": False, "error": "대표·근거·variation 중 저장 위치를 골라주세요."}
        with self.config_lock:
            pending = copy.deepcopy(self.pending_variation)
            if not isinstance(pending, dict) or not pending.get("result_path"):
                return {"ok": False, "error": "저장할 완료 결과가 없습니다."}
            result_path = Path(str(pending["result_path"])).resolve()
            latest = self.latest_config_from_disk()
            root = out_root(latest).resolve()
            try:
                inside = result_path.is_relative_to(root)
            except AttributeError:
                inside = str(result_path).startswith(str(root))
            if not inside or not result_path.is_file():
                return {"ok": False, "error": "고정된 생성 결과 파일을 확인할 수 없습니다."}
            actual_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
            if actual_hash != str(pending.get("result_hash") or ""):
                return {"ok": False, "error": "생성 뒤 결과 파일이 바뀌어 저장하지 않았습니다."}
            character = next((
                item for item in (latest.get("characters") or [])
                if str(item.get("id") or "") == str(pending.get("character_id") or "")
            ), None)
            if character is None:
                return {"ok": False, "error": "대상 캐릭터가 없어졌습니다."}
            try:
                asset = character_asset_from_legacy_record(
                    character,
                    char_refs=latest.get("char_refs") or [],
                    vibes=latest.get("vibes") or [],
                )
                proposal = accept_variation(
                    asset,
                    pending.get("plan") or {},
                    {
                        "image_ref": {"content_hash": actual_hash},
                        "name": str(request.get("name") or "").strip(),
                        "metadata": {
                            key: copy.deepcopy(pending.get(key))
                            for key in (
                                "mode", "job_id", "seed", "width", "height",
                                "started_at", "completed_at",
                            )
                        },
                    },
                )
                candidates = approved_proposal_to_legacy_candidates(
                    character, proposal, approved=True)
            except Exception as e:
                return {"ok": False, "conflict": True, "error": str(e)}
            content_type = (
                "image/png" if result_path.suffix.lower() == ".png"
                else "image/webp"
            )
            local_ref, _ = _local_import_image(
                result_path.read_bytes(), content_type)
            updated_character = apply_character_variation_candidates(
                character,
                candidates,
                local_ref=local_ref,
                save_as=save_as,
            )
            character.clear()
            character.update(updated_character)
            self.cfg.clear()
            self.cfg.update(latest)
            sync_chars_to_files(self.cfg)
            save_config(self.cfg)
            self.config_revision += 1
            return {
                "ok": True,
                "save_as": save_as,
                "character": copy.deepcopy(character),
                "revision": self.config_revision,
                "local_ref": local_ref,
            }

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
        tok = self.live.try_claim(
            "그림체 복구",
            "library",
            blueprint=inherited_blueprint(
                cfg,
                source={"kind": "metadata-recovery", "items": len(jobs)},
            ),
            payload_identity={
                "kind": "recovery", "items": len(jobs), "mode": mode},
        )
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
                        "position_mode": normalize_position_mode(
                            "", bool(v4.get("use_coords"))),
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
                    frozen = self.live.frozen_blueprint()
                    img.nai_blueprint_fingerprint = str(
                        (frozen or {}).get("fingerprint") or "")
                    saved = save_with_meta(
                        img, out_dir / f"{f.stem}{tag}.webp",
                        fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                        max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                    record_job_result(
                        self.live.job_id,
                        saved,
                        artifact=saved.resolve().relative_to(
                            out_root(cfg).resolve()).as_posix(),
                    )
                    self.live.set_image(img)
                    bump_daily(state); save_state(state)
                    done += 1
                    self.live.update(
                        completed=done, index=i, daily=daily_count(state))
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
        with self.config_lock:
            cfg = copy.deepcopy(self.cfg)
        if not cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        jobs = scene_mode_pending(cfg)
        if not jobs:
            return {"ok": False, "error": "예약 매수를 1 이상으로 걸어 둔 씬이 없습니다."}
        slots = [s for s in cfg.get("char_slots", [])
                 if slot_prompt(s).strip() and s.get("enabled") is not False]
        run_blueprint = inherited_blueprint(
            cfg,
            source={"kind": "scene-run"},
            setting={"name": "씬 모드", "steps": copy.deepcopy(jobs)},
        )
        tok = self.live.try_claim(
            "씬 모드",
            "settings",
            blueprint=run_blueprint,
            payload_identity={"kind": "setting", "jobs": len(jobs)},
        )
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
            run_fingerprint = hashlib.sha256(
                f"{run_blueprint['fingerprint']}\0{base_seed}".encode("utf-8")
            ).hexdigest()
            scene_progress = state.setdefault(
                "scene_progress", {}).setdefault(run_fingerprint, {})
            style = (cfg.get("base_prompt") or "").strip()
            valid_cells = {}
            lineage_failures = 0
            for i, (scene, copy_no) in enumerate(jobs, 1):
                scene_id = _safe_name(
                    str(scene.get("id") or f"scene-{i}"))
                cell_fingerprint = hashlib.sha256(
                    f"{run_fingerprint}\0{scene_id}\0{copy_no}"
                    .encode("utf-8")
                ).hexdigest()
                cell_id = f"{scene_id}:{int(copy_no)}"
                record = scene_progress.get(cell_id)
                if not isinstance(record, dict):
                    continue
                path = progress_record_path(record, cfg)
                try:
                    valid = (
                        record.get("fingerprint") == cell_fingerprint
                        and path is not None
                        and path.is_file()
                        and path.stat().st_size == int(record.get("bytes", -1))
                        and hashlib.sha256(path.read_bytes()).hexdigest()
                        == str(record.get("content_sha256") or "")
                    )
                except (OSError, TypeError, ValueError):
                    valid = False
                if not valid:
                    continue
                valid_cells[cell_id] = record
                try:
                    record_job_result(
                        self.live.job_id,
                        path,
                        artifact=str(record.get("path") or ""),
                        result_id="result-scene-" + cell_fingerprint[:24],
                    )
                except Exception as error:
                    log.warning("검증된 씬 결과의 Job 계보 연결 실패: %s", error)
                    lineage_failures += 1
            done = len(valid_cells)
            failed = 0
            blocked = False
            self.live.update(
                total=len(jobs), index=done, completed=done,
                eta_base_completed=done, char_name="씬 모드")
            try:
                for i, (sc, copy) in enumerate(jobs, 1):
                    if self.live.stop_req:
                        break
                    scene_id = _safe_name(
                        str(sc.get("id") or f"scene-{i}"))
                    cell_fingerprint = hashlib.sha256(
                        f"{run_fingerprint}\0{scene_id}\0{copy}"
                        .encode("utf-8")
                    ).hexdigest()
                    cell_id = f"{scene_id}:{int(copy)}"
                    if cell_id in valid_cells:
                        self.live.update(
                            index=i,
                            completed=done,
                            filename=Path(str(
                                valid_cells[cell_id].get("path") or "")).name,
                            status_text="확인된 완료 장면 건너뜀",
                        )
                        continue
                    okp, why = pace_gate(cfg, self.live, "씬")   # 밴 예방 (CQA-013)
                    if not okp:
                        self.live.update(status_text=why)
                        blocked = True
                        break
                    suffix = "" if copy == 1 else f"_{copy}벌"
                    seed = seed_for(cfg, base_seed, i + (copy - 1) * 100003)
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
                    # 위치 방식은 사용자가 고른 AI 자동/위치판/좌표를 그대로 따른다.
                    # 인물이 늘었다는 이유로 좌표를 켜거나 값을 다시 배치하지 않는다.
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
                    frozen = self.live.frozen_blueprint()
                    img.nai_blueprint_fingerprint = str(
                        (frozen or {}).get("fingerprint") or "")
                    saved_path = save_with_meta(img, target, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                                                max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                    self.live.update(filename=saved_path.name)
                    self.live.set_image(img)
                    bump_daily(state)
                    rel_saved = saved_path.resolve().relative_to(
                        out_root(cfg).resolve()).as_posix()
                    scene_progress[cell_id] = {
                        "scene": scene_id,
                        "copy": int(copy),
                        "path": rel_saved,
                        "bytes": saved_path.stat().st_size,
                        "content_sha256": hashlib.sha256(
                            saved_path.read_bytes()).hexdigest(),
                        "fingerprint": cell_fingerprint,
                    }
                    # 유료 생성은 이미 끝났다. 재개 기록을 먼저 남기고 Job 계보는
                    # 별도로 연결해, 계보 저장 실패가 같은 장의 유료 재호출로
                    # 이어지지 않게 한다.
                    try:
                        save_state(state)
                    except Exception as error:
                        lineage_failures += 1
                        log.warning(
                            "씬 결과는 저장했지만 재개 장부 저장에 실패: %s",
                            error,
                        )
                    try:
                        record_job_result(
                            self.live.job_id,
                            saved_path,
                            artifact=rel_saved,
                            result_id="result-scene-" + cell_fingerprint[:24],
                        )
                    except Exception as error:
                        lineage_failures += 1
                        log.warning(
                            "씬 결과는 저장했지만 Job 계보 연결에 실패: %s",
                            error,
                        )
                    done += 1
                    self.live.update(
                        completed=done, index=i, daily=daily_count(state))
                if self.live.stop_req:
                    phase = "stopped"
                    text = f"씬 모드 중지 — {done}/{len(jobs)}장 (다시 실행 가능)"
                elif blocked:
                    phase = "stopped"
                    text = self.live.status_text
                elif failed:
                    phase = "partial"
                    text = f"씬 모드 일부 완료 — 성공 {done} · 실패 {failed}"
                elif lineage_failures:
                    phase = "partial"
                    text = (
                        "씬 이미지는 저장했지만 작업 계보·재개 장부 "
                        f"{lineage_failures}건을 확인해야 합니다."
                    )
                else:
                    phase = "completed"
                    text = f"씬 모드 완료 ✓ {done}/{len(jobs)}장 (output/씬/)"
                self.live.update(
                    status_text=text, completed=done,
                    failed=max(failed, lineage_failures), phase=phase,
                    can_retry=bool(
                        failed or lineage_failures or blocked
                        or self.live.stop_req))
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
                promotions = None
                try:
                    promotions = _result_promotion_records(
                        self.cfg,
                        data.get("path"),
                        data.get("kind"),
                        name=data.get("name"),
                    )
                except LegacyPromotionLineageUnavailable:
                    # 구형 비교 결과는 실행 식별자가 없을 수 있다. 자산 저장은 호환
                    # 경로로 허용하되 계보를 꾸며 내지 않고 미확인으로 명시한다.
                    pass
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
                if result.get("ok") and promotions is not None:
                    try:
                        # 이름 충돌 시 실제 저장된 이름으로 엄격 레코드를 다시 만든다.
                        promotions = _result_promotion_records(
                            self.cfg,
                            data.get("path"),
                            data.get("kind"),
                            name=data.get("name"),
                            resolved_names=list(result.get("names") or []),
                        )
                        result["lineage"] = _append_result_promotion_ledger(
                            promotions)
                        result["lineage"]["verified"] = all(
                            item.get("lineage", {})
                            .get("execution", {})
                            .get("manifest_verified") is True
                            for item in promotions
                        )
                    except Exception as error:
                        result["lineage"] = {
                            "error": redact_diagnostic_text(error),
                            "verified": False,
                        }
                elif result.get("ok"):
                    result["lineage"] = {
                        "verified": False,
                        "warning": (
                            "자산은 저장했지만 이 구형 결과에는 엄격한 실행 계보가 "
                            "없어 승격 장부에는 넣지 않았습니다."
                        ),
                    }
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
        try:
            data = json.loads(body or b"{}")
        except Exception as e:
            return {"ok": False, "error": f"잘못된 요청입니다: {e}"}
        # 계획·설계도·worker가 같은 클릭 시점 사본을 사용한다. 실행권을 잡는 사이
        # 자동 저장이 들어와도 계획은 옛 값, 실제 호출은 새 값으로 갈라지지 않는다.
        with self.config_lock:
            run_cfg = copy.deepcopy(self.cfg)
        if not run_cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
        opus = None
        if self.anlas_balance_cache is not None:
            opus = bool(self.anlas_balance_cache.get("opus"))
        plan = comparison_plan(run_cfg, data, self.spec, opus=opus)
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
        tok = self.live.try_claim(
            "자료 비교 생성",
            "library",
            blueprint=inherited_blueprint(
                run_cfg,
                source={"kind": "comparison-plan"},
                experiment={
                    **copy.deepcopy(plan.get("options") or {}),
                    "selection": copy.deepcopy(
                        plan.get("selection")
                        or (plan.get("options") or {}).get("selection")
                        or {}),
                },
            ),
            payload_identity={
                "kind": "comparison",
                "count": plan["count"],
                "mode": (plan.get("options") or {}).get("mode"),
            },
        )
        if tok is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        if plan["options"].get("mode") == "character_setting":
            styles, chars = [], comparison_characters(run_cfg)
        else:
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

    def handle_compare_rerun(self, body):
        """선택 실험 결과 한 장의 canonical 셀만 같은 seed로 다시 실행한다."""
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        try:
            data = json.loads(body or b"{}")
            path = str(data.get("path") or "")
            with self.config_lock:
                run_cfg = copy.deepcopy(self.cfg)
            if not run_cfg.get("token", "").startswith("pst-"):
                return {"ok": False, "error": "NAI 토큰을 입력해주세요."}
            # 실행권을 잡기 전에 manifest와 셀 재료가 실제로 있는지 확인한다.
            _selected_comparison_record(run_cfg, path)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        token = self.live.try_claim(
            "비교 한 셀 재실행",
            "library",
            payload_identity={"kind": "comparison-rerun", "path": path},
        )
        if token is None:
            return {"ok": False, "error": "이미 생성 중입니다."}

        def run():
            try:
                _rerun_selected_comparison(self, run_cfg, path)
            except Exception as error:
                log.error("비교 한 셀 재실행 실패: %s", error)
                self.live.update(
                    status_text=f"비교 한 셀 재실행 실패: {error}",
                    failed=1, last_error=str(error),
                    phase="failed", can_retry=True,
                )
            finally:
                self.live.release(token)

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "path": path}

    def handle_inspect(self, body, filename="", save_flag=""):
        """이미지에서 NAI 메타데이터를 뽑아 그림체 레코드로. (novelai.net/inspect 대체)
        X-Save: 1 이면 그림체 라이브러리에도 넣는다."""
        try:
            from urllib.parse import unquote
            name = Path(unquote(filename or "")).name or "붙여넣은 이미지"
            if not body:
                result = {"ok": False, "error": "이미지가 비어 있습니다."}
                queue = image_inspect_queue(result, filename=name)
                result["restoration"] = summarize_restore_queue(queue)
                result["restoration_queue"] = queue
                return result
            ct = "image/webp" if body[:4] == b"RIFF" else "image/png"
            m = extract_nai_metadata(body, ct)
            if m["metadata_status"] != "ok":
                result = {
                    "ok": False,
                    "error": (
                        "이 이미지에는 NAI 생성 정보가 없습니다. "
                        "(카톡·디스코드 등을 거치면 지워집니다 — 원본 파일을 넣어주세요)"
                    ),
                }
                queue = image_inspect_queue(result, filename=name)
                result["restoration"] = summarize_restore_queue(queue)
                result["restoration_queue"] = queue
                return result
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
                # 파이썬 hash()는 프로세스마다 달라 같은 파일이 재실행 뒤 다른 id가 된다.
                # 전체 원본 바이트의 SHA-256을 써 모든 임포트 경로에서 안정적으로 식별한다.
                "id": f"file-{hashlib.sha256(body).hexdigest()[:20]}",
                "content_sha256": hashlib.sha256(body).hexdigest(),
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
            thumb_created = False
            key = ""
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
                    thumb_created = True
                rec["images"] = [f"local:{key}"]
            except Exception as e:
                log.warning(f"추출 썸네일 실패: {e}")
            # 옛 그림체 레코드는 그대로 읽을 수 있게 유지하고, 새 단건 임포트에는
            # 같은 원본을 증거·지식 자산 계약으로도 함께 보존한다.
            evidence_record = evidence_from_image_record(rec)
            knowledge_asset = style_asset_from_record(
                rec,
                evidence_refs=[evidence_record["id"]],
                lifecycle="candidate",
            )
            rec["evidence_records"] = [evidence_record]
            rec["knowledge_asset"] = knowledge_asset
            saved = None
            if save_flag in ("1", "true"):
                files = ({"수집/이미지캐시": [key]}
                         if thumb_created and key else {})
                saved = add_style(
                    rec,
                    import_info={"kind": "image", "file": name, "files": files},
                    return_detail=True,
                )
            result = {
                "ok": True, "style": rec,
                "saved": saved.get("total") if saved else None,
                "import": saved,
            }
            queue = image_inspect_queue(result, filename=name)
            result["restoration"] = summarize_restore_queue(queue)
            result["restoration_queue"] = queue
            return result
        except Exception as e:
            log.warning(f"메타데이터 추출 실패: {traceback.format_exc()}")
            result = {"ok": False, "error": str(e)}
            queue = image_inspect_queue(
                result,
                filename=Path(str(filename or "")).name,
            )
            result["restoration"] = summarize_restore_queue(queue)
            result["restoration_queue"] = queue
            return result

    def handle_resource_import(self, body, filename=""):
        """Vibe 교환 문서를 기존 저장소에 비활성 자원으로 안전하게 추가."""
        try:
            from urllib.parse import unquote
            if not body:
                return {"ok": False, "error": "가져올 묶음이 비어 있습니다."}
            with shared_data_transaction(VIBE_DIR.parent.parent):
                with self.config_lock:
                    self.use_latest_config()
                    plan = legacy_resource_import_plan(
                        body,
                        filename=unquote(filename or ""),
                        existing_config=self.cfg,
                    )
                    VIBE_DIR.mkdir(parents=True, exist_ok=True)
                    for write in plan["writes"]:
                        name = Path(str(write.get("filename") or "")).name
                        if not name or name != write.get("filename"):
                            raise ValueError("안전하지 않은 자원 파일 이름입니다.")
                        target = VIBE_DIR / name
                        content = write.get("content")
                        raw = (content.encode(write.get("encoding") or "utf-8")
                               if write.get("kind") == "text"
                               else bytes(content or b""))
                        if target.exists():
                            if target.read_bytes() != raw:
                                raise FileExistsError(
                                    f"같은 이름의 다른 자원 파일이 있습니다: {name}")
                            continue
                        _atomic_write_bytes(target, raw, keep_backup=False)
                    self.cfg.setdefault("vibes", []).extend(
                        plan["additions"]["vibes"])
                    self.cfg.setdefault("char_refs", []).extend(
                        plan["additions"]["char_refs"])
                    save_config(self.cfg)
                    self.config_revision += 1
            return {
                "ok": True,
                "added_vibes": len(plan["additions"]["vibes"]),
                "added_char_refs": len(plan["additions"]["char_refs"]),
                "skipped": plan["skipped"],
                "issues": plan["issues"],
                "vibes": self.cfg.get("vibes", []),
                "char_refs": self.cfg.get("char_refs", []),
                "revision": self.config_revision,
            }
        except Exception as e:
            log.warning(f"Vibe·Reference 묶음 가져오기 실패: {e}")
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
        tok = None
        try:
            if not body:
                return {"ok": False, "error": "이미지가 비어 있습니다."}
            token = (self.cfg.get("token") or "").strip()
            if not token:
                return {"ok": False, "error": "시스템에서 NAI 토큰을 먼저 넣어주세요."}
            names = {t for t, _, _ in DIRECTOR_TOOLS} | {"upscale"}
            if tool not in names:
                return {"ok": False, "error": f"알 수 없는 도구: {tool}"}
            tok = self.live.try_claim(
                f"디렉터 · {tool}",
                "director",
                blueprint=inherited_blueprint(
                    self.cfg,
                    source={"kind": "director", "tool": tool},
                ),
                payload_identity={
                    "kind": "director",
                    "tool": tool,
                    "input_sha256": hashlib.sha256(body).hexdigest(),
                },
            )
            if tok is None:
                return {"ok": False, "error": "이미 다른 NAI 작업이 실행 중입니다."}
            self.live.update(
                status_text=f"디렉터 · {tool} 처리 중...",
                char_name=f"디렉터 · {tool}", index=1, total=1)

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
            record_job_result(
                self.live.job_id,
                p,
                artifact=p.resolve().relative_to(
                    out_root(self.cfg).resolve()).as_posix(),
            )
            self.live.set_image(img.convert("RGB"))
            self.live.update(filename=p.name, char_name=f"디렉터 · {tool}",
                             status_text="디렉터 툴 완료", completed=1,
                             phase="completed")
            log.info(f"디렉터 {tool} → {p.name} ({img.width}×{img.height})")
            return {"ok": True, "tool": tool, "file": p.name,
                    "path": str(p), "width": img.width, "height": img.height}
        except Exception as e:
            log.warning(f"디렉터 툴 실패: {traceback.format_exc()}")
            if tok is not None:
                self.live.update(
                    status_text=f"디렉터 툴 실패: {e}", failed=1,
                    last_error=str(e), can_retry=True, phase="failed")
            return {"ok": False, "error": str(e)}
        finally:
            if tok is not None:
                self.live.release(tok)

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
            # 프로젝트 연결 뒤의 일반 편집은 부모 전체를 복제하지 않고 실제로
            # 달라진 leaf만 override로 기록한다.
            sync_blueprint_local_overrides(self.cfg)
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
        """한 세팅의 씬 내부 값을 원자적으로 저장한다.

        씬 번호는 다른 세팅에도 존재할 수 있으므로 이름으로 파일을 먼저
        고정한다. expect_revision은 편집 뒤 다른 저장이 끼어든 상태에서
        되돌리기가 새 내용을 덮는 것을 막는다.
        """
        try:
            data = json.loads(body)
            setting = str(data.get("setting") or "").strip()
            if not setting:
                return {"ok": False, "error": "수정할 세팅 이름이 없습니다."}
            path = setting_path(setting)
            if not path:
                return {"ok": False, "error": f"'{setting}' 세팅을 찾을 수 없습니다."}
            updates = data.get("updates") or {}
            if not isinstance(updates, dict):
                return {"ok": False, "error": "씬 수정 내용의 형식이 잘못되었습니다."}
            allowed = ("female_prompt", "male_prompt", "partner_prompt", "base_tags",
                       "relationship_name", "relationship_tags",
                       "female_negative", "male_negative", "partner_negative",
                       "remove_char_tags", "remove_male_tags", "remove_partner_tags",
                       "negative", "width", "height", "char_centers",
                       "use_character_refs", "character_refs")
            tag_list_fields = ("remove_char_tags", "remove_male_tags",
                               "remove_partner_tags")
            valid_ref_ids = {
                str(ref.get("id") or "")
                for ref in (self.cfg.get("char_refs") or [])
                if isinstance(ref, dict) and ref.get("id")
            }
            pack = load_json_recover(path)
            revision = setting_content_revision(pack)
            expected = str(data.get("expect_revision") or "")
            if expected and expected != revision:
                return {"ok": False, "conflict": True,
                        "error": "다른 저장이 먼저 반영되어 되돌리지 않았습니다. 다시 열어 확인해주세요."}

            scenes = pack.get("씬") or {}
            prepared = {}
            before = {}
            for sid, fields in updates.items():
                sid = str(sid)
                sc = scenes.get(sid)
                if not isinstance(sc, dict) or not isinstance(fields, dict):
                    continue
                clean = {}
                old = {}
                for key in allowed:
                    if key not in fields:
                        continue
                    value = fields[key]
                    if key in ("width", "height"):
                        value = normalize_resolution(value)
                    elif key == "char_centers":
                        value = normalize_scene_centers(value)
                    elif key == "character_refs":
                        value = normalize_scene_reference_ids(value)
                        unknown = [rid for rid in value if rid and rid not in valid_ref_ids]
                        if unknown:
                            raise ValueError(
                                f"찾을 수 없는 캐릭터 레퍼런스입니다: {unknown[0]}")
                    elif key == "use_character_refs":
                        if not isinstance(value, bool):
                            raise ValueError("씬 Reference 사용 여부는 true/false여야 합니다.")
                    elif key in tag_list_fields:
                        if isinstance(value, str):
                            value = [x.strip() for x in re.split(r"[,\n]", value)
                                     if x.strip()]
                        elif isinstance(value, list):
                            value = [str(x).strip() for x in value if str(x).strip()]
                        else:
                            raise ValueError(f"{key} 값은 문자열 또는 목록이어야 합니다.")
                    elif not isinstance(value, str):
                        raise ValueError(f"{key} 값은 문자열이어야 합니다.")
                    clean[key] = value
                    if key == "char_centers":
                        old[key] = normalize_scene_centers(sc.get(key))
                    elif key == "character_refs":
                        old[key] = normalize_scene_reference_ids(
                            sc.get("character_refs"))
                    elif key == "use_character_refs":
                        old[key] = bool(sc.get(key, False))
                    elif key in tag_list_fields:
                        previous = sc.get(key) or []
                        old[key] = (
                            [x.strip() for x in re.split(r"[,\n]", previous) if x.strip()]
                            if isinstance(previous, str)
                            else [str(x).strip() for x in previous if str(x).strip()]
                        )
                    else:
                        old[key] = sc.get(key, "" if key not in ("width", "height") else value)
                if clean:
                    prepared[sid] = clean
                    before[sid] = old

            changed_scenes = 0
            changed_fields = 0
            for sid, fields in prepared.items():
                scene_changed = False
                for key, value in fields.items():
                    empty = (
                        [] if key in ("char_centers", "character_refs")
                        or key in tag_list_fields
                        else False if key == "use_character_refs" else ""
                    )
                    if scenes[sid].get(key, empty) != value:
                        scenes[sid][key] = value
                        changed_fields += 1
                        scene_changed = True
                changed_scenes += int(scene_changed)
            if changed_fields:
                atomic_write_json(path, pack)
            after_revision = setting_content_revision(pack)
            return {"ok": True, "updated": changed_scenes, "fields": changed_fields,
                    "setting": setting, "before": before,
                    "revision": after_revision}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def handle_start(self):
        if self.live.running:
            return {"ok": False, "error": "이미 생성 중입니다."}
        if not self.cfg.get("token", "").startswith("pst-"):
            return {"ok": False, "error": "NAI 토큰을 입력해주세요 (pst-... 형식)."}
        has_slot = any(slot_prompt(s).strip() for s in self.cfg.get("char_slots", []))
        has_cast = any(slot_prompt(c).strip()
                       for st in (self.cfg.get("setting_state") or {}).values()
                       for c in st.get("cast", []))
        if not (has_slot or has_cast):
            return {"ok": False, "error": "설정의 캐릭터 칸 또는 세팅의 캐스트에 인물을 1명 이상 넣어주세요."}
        if not any((st.get("use") is not False and st.get("selected"))
                   for st in (self.cfg.get("setting_state") or {}).values()):
            return {"ok": False, "error": "세팅 탭에서 씬을 1개 이상 선택해주세요."}
        # 시작 버튼을 누른 순간의 계획을 고정한다. 진행 중 화면 저장은 다음 실행에만
        # 반영되어 한 batch 안에서 프롬프트·캐스트·세팅이 섞이지 않는다.
        with self.config_lock:
            self.pending_batch_config = copy.deepcopy(self.cfg)
        self.start_event.set()
        return {"ok": True}

    def start(self, open_browser=True):
        server = self
        catalog_get = CatalogGetOperations(
            booru=lambda *args: search_booru(*args),
            style_duplicates=lambda: find_style_dupes(),
            library=lambda *args, **kwargs: search_library(*args, **kwargs),
            combos=lambda *args, **kwargs: search_combos(*args, **kwargs),
            recipes=lambda *args: search_recipes(*args),
            prewarm=lambda *args, **kwargs: prewarm_images(*args, **kwargs),
            autocomplete=lambda *args: autocomplete_tags(*args),
            tags=lambda *args: search_tags(*args),
            scenes=lambda cfg, ids, setting: scene_catalog(
                cfg,
                ids,
                setting,
                setting_path=setting_path,
                load_json=load_json_recover,
                load_asset_config=load_asset_config,
                content_revision=setting_content_revision,
                normalize_refs=normalize_scene_reference_ids,
                normalize_centers=normalize_scene_centers,
            ),
        )
        generation_get = GenerationGetOperations(
            comparison_catalog=lambda cfg, spec: comparison_catalog(cfg, spec),
            comparison_runs=lambda cfg: comparison_runs(cfg),
            comparison_progress=lambda cfg: comparison_progress_summary(cfg),
        )
        asset_get = AssetGetOperations(
            vibe_dir=VIBE_DIR,
            mime=MIME,
            output_preview=lambda cfg, rel: output_file_for_preview(cfg, rel),
            output_list=lambda *args, **kwargs: list_output(*args, **kwargs),
            setting_thumbs=lambda name, cfg: setting_thumbs(name, cfg),
            resource_export=lambda cfg: export_legacy_resources(
                cfg, file_index=resource_file_index(cfg)
            ),
            backup_export=lambda cfg: export_user_backup(cfg),
            fragments_export=lambda: export_fragments_zip(),
            settings_export=lambda names: export_settings_zip(names),
            cached_image=lambda url: fetch_cached_image(url),
            diagnostics=lambda limit, errors_only: diagnostic_snapshot(
                LOG_FILE, limit=limit, errors_only=errors_only
            ),
            render_page=lambda: render_page(),
        )
        recovery_get = RecoveryGetOperations(
            metadata_audit=lambda offset, limit: metadata_audit_status(
                found_offset=offset, found_limit=limit
            ),
            folder_inventory=lambda offset, limit: folder_inventory_page(
                offset, limit
            ),
            trash=lambda cfg: list_trash_batches(cfg),
            pack_log=lambda: {"ok": True, "log": pack_log_brief()},
            public_restoration=lambda: PUBLIC_COLLECTION.restoration_snapshot(),
            public_collection=lambda: PUBLIC_COLLECTION.snapshot(),
            data_storage=lambda: data_storage_status(),
            image_origins=lambda: image_origin_stats(),
            local_integrity=lambda: local_image_integrity(),
        )
        recovery_post = RecoveryPostOperations(
            preview_backup=preview_user_backup,
            restore_backup=restore_user_backup,
            rollback_backup=rollback_user_backup,
            load_settings=lambda: load_json_recover(SETTINGS_FILE),
            default_config=DEFAULT_CONFIG,
            migrate_selections=migrate_legacy_selections,
            migrate_slots=migrate_char_slots,
            load_spec=load_spec,
            options=OPTIONS,
            load_options=load_options,
            normalize_local_images=normalize_local_image_refs,
            rollback_local_images=rollback_local_image_normalize,
            rebuild_data_index=rebuild_data_index,
            metadata_control=metadata_audit_control,
            metadata_candidate=metadata_audit_candidate,
            metadata_save=metadata_audit_save_candidate,
            image_batch_queue=image_batch_queue,
            summarize_queue=summarize_restore_queue,
        )
        collection_post = CollectionPostOperations(
            preview_pack=preview_datapack_bytes,
            import_pack=import_datapack_bytes,
            pack_queue=pack_import_queue,
            summarize_queue=summarize_restore_queue,
            forget_caches=forget_collection_caches,
            load_spec=load_spec,
            options=OPTIONS,
            load_options=load_options,
            public_start=PUBLIC_COLLECTION.start,
            public_retry=PUBLIC_COLLECTION.retry_failed,
            public_control=PUBLIC_COLLECTION.control,
            undo_pack=undo_datapack,
            import_settings=import_settings_bytes,
            resource_import=server.handle_resource_import,
            reference_add=server.handle_ref_add,
            reference_save=server.handle_ref_save,
        )
        catalog_post = CatalogPostOperations(
            style_save=server.handle_style_save,
            normalization_save=server.handle_norm_save,
            verify_tags=verify_tags,
            organize_library=organize_library_items,
            delete_styles=delete_styles,
            restore_styles=restore_styles,
        )
        evaluation_post = EvaluationPostOperations(
            artist_workspace=artist_workspace_request,
            load_ratings=load_ratings,
            rate_artist=rate_artist,
            apply_evaluation=apply_evaluation_action,
            picks_lock=_JSON_IO_LOCK,
            load_picks=load_picks,
            save_picks=save_picks,
            trash_outputs=trash_output_files,
            restore_trash=restore_trash_batch,
            output_subdir=out_sub,
            atomic_write=_atomic_write_bytes,
            strip_and_save=strip_and_save,
        )
        fragment_post = FragmentPostOperations(
            fragment_dir=FRAG_DIR,
            save_fragment=save_fragment,
            list_fragments=list_fragments,
            recoverable_remove=recoverable_remove,
            load_state=load_state,
            save_state=save_state,
            import_fragments=import_fragments_bytes,
            reroll_components=reroll_legacy_components,
            resolve_prompt=resolve_legacy_prompt,
            sequence_text=legacy_sequence_text,
            resolve_fragments=resolve_fragments,
            random_factory=random.Random,
        )
        settings_post = SettingsPostOperations(
            duplicate_scene_undo=undo_duplicate_setting_scene,
            duplicate_scene=duplicate_setting_scene,
            scene_save=server.handle_scene_save,
            option_item=server.handle_option_item,
            role_save=server.handle_role_save,
            sceneset_save=server.handle_sceneset_save,
            load_asset_config=load_asset_config,
            setting_state=setting_state,
            cast_members=setting_cast_members,
            slot_prompt=slot_prompt,
            character_run=character_run_from_group,
            build_scene=build_scene,
            reference_config=setting_reference_config,
            scene_people=setting_scene_people,
            seed_for=seed_for,
            load_state=load_state,
            normalize_prompt=normalize_prompt,
            join_tags=_join_tags,
            token_count=nai_tokens,
            save_scenes=save_scenes,
            new_setting=new_setting,
            add_set=setting_add_set,
            save_meta=setting_meta_save,
            renumber=setting_renumber,
            delete_setting=setting_delete,
            duplicate_group=duplicate_setting_group,
            log_warning=log.warning,
        )
        generation_post = GenerationPostOperations(
            activate_comparison=activate_comparison_run,
            compare_rerun=server.handle_compare_rerun,
            comparison_recipe=comparison_recipe_for_output,
            compare_promote=server.handle_compare_promote,
            compare_preview=server.handle_compare_preview,
            compare_run=server.handle_compare_run,
            start=server.handle_start,
            generate_one=server.handle_generate_one,
            request_stop=server.live.request_stop,
            job_command=server.handle_job_command,
            image_to_image=server.handle_i2i,
            variation_save=server.handle_character_variation_save,
            regenerate=server.handle_regen,
            scene_run=server.handle_scene_run,
            director=server.handle_director,
            inspect_image=server.handle_inspect,
        )
        runtime_post = RuntimePostOperations(
            blueprint_project=server.handle_blueprint_project,
            save_config=server.handle_save,
            fetch_balance=lambda token: fetch_anlas_balance(token),
            vibe_paths=vibe_paths,
            load_asset_config=load_asset_config,
            compute_pending=compute_pending,
            estimate_anlas=anlas_estimate,
            finalize_tokens=finalized_token_texts,
            token_count=nai_tokens,
            tokens_exact=tokens_exact,
        )

        class Handler(ConfigRequestHandler):

            def do_GET(self):
                if self._serve_static(UI_DIR):
                    return
                if handle_runtime_get(self, server):
                    return
                if handle_recovery_get(self, server, recovery_get):
                    return
                if handle_catalog_get(self, server, catalog_get):
                    return
                if handle_generation_get(self, server, generation_get):
                    return
                if handle_asset_get(self, server, asset_get):
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                body = self._read_post_body()
                if body is None:
                    return
                if handle_recovery_post(self, server, recovery_post, body):
                    return
                if handle_collection_post(self, server, collection_post, body):
                    return
                if handle_catalog_post(self, catalog_post, body):
                    return
                if handle_evaluation_post(self, server, evaluation_post, body):
                    return
                if handle_fragment_post(self, server, fragment_post, body):
                    return
                if handle_settings_post(self, server, settings_post, body):
                    return
                if handle_generation_post(self, server, generation_post, body):
                    return
                if handle_runtime_post(self, server, runtime_post, body):
                    return
                self.send_response(404)
                self.end_headers()

        self.httpd, self.url = start_http_server(
            self,
            Handler,
            port_range=PREVIEW_PORT_RANGE,
            open_browser=open_browser,
            browser_open=webbrowser.open,
            logger=log,
        )
        return self.url


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


def progress_record_path(record, cfg):
    value = record.get("path") if isinstance(record, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else out_root(cfg).resolve() / path


def progress_record_valid(record, cfg, expected_fingerprint):
    if not isinstance(record, dict):
        return False
    if record.get("fingerprint") != expected_fingerprint:
        return False
    path = progress_record_path(record, cfg)
    if path is None:
        return False
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
        scene_setting_state = setting_state(cfg, sname)
        cast = [c for c in setting_cast_members(cfg, scene_setting_state)
                if slot_prompt(c).strip()]
        # 두 목록의 뜻이 다르다 (UI 문구 그대로):
        #   세팅 전용 캐스트 = "각자 따로 전체 씬 생성" → 인원수만큼 벌이 늘어난다
        #   ① 설정의 캐릭터 칸 = "한 그림에 함께 들어갈 인물" → 늘어나지 않는다.
        #     첫 칸이 주인공, 둘째 칸이 상대역이 된다 (단독 생성과 같은 규칙).
        if cast:
            cast_mode = scene_setting_state.get("cast_mode")
            if cast_mode == "together":
                identity = "\0".join(slot_bundle_identity(c) for c in cast)
                runs = [(cast, f"{sname}\0together\0{identity}")]
            else:
                # 표시 이름이 같아도 각 캐스트는 별개 작업이다. index와 내용 fingerprint를 identity로 쓴다.
                runs = [([c], f"{sname}\0sequence\0{i}\0{slot_bundle_identity(c)}")
                        for i, c in enumerate(cast)]
        else:
            runs = [(slots, None)] if slots else []
        for i, (group, identity) in enumerate(runs):
            char = character_run_from_group(
                group, i, scene_setting_state.get("position_mode"))
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


def _comparison_result_context(cfg, rel):
    """비교 결과 한 장의 파일·manifest·정확한 작업 레코드를 함께 찾는다."""
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
    manifest = load_json_recover(manifest_path)
    wanted = image_path.relative_to(root).as_posix()
    for section in ("completed", "reruns"):
        rows = manifest.get(section)
        if not isinstance(rows, dict):
            continue
        for key, record in rows.items():
            if (isinstance(record, dict)
                    and str(record.get("file") or "").replace("\\", "/")
                    == wanted):
                effective = manifest
                if section == "reruns":
                    effective = copy.deepcopy(manifest)
                    effective["completed"] = {str(key): copy.deepcopy(record)}
                return {
                    "image_path": image_path,
                    "file": wanted,
                    "folder": folder,
                    "manifest": effective,
                    "record": copy.deepcopy(record),
                    "job_key": str(key),
                    "section": section,
                }
    raise ValueError("manifest에서 선택한 결과의 생성 기록을 찾지 못했습니다.")


def comparison_recipe_for_output(cfg, rel):
    """선택한 비교 이미지가 실제로 사용한 원문·설정·캐릭터를 manifest에서 복원한다."""
    context_result = _comparison_result_context(cfg, rel)
    progress = context_result["manifest"]
    completed = progress.get("completed")
    if not isinstance(completed, dict):
        raise ValueError("비교 결과 기록 형식이 올바르지 않습니다.")
    wanted = context_result["file"]
    record = context_result["record"]
    if isinstance(record.get("recipe"), dict):
        recipe = copy.deepcopy(record["recipe"])
        recipe["nai_seed"] = int(record.get("seed") or recipe.get("nai_seed") or 0)
        return {
            "ok": True,
            "file": wanted,
            "recipe": recipe,
        }
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
            "variant": copy.deepcopy(character.get("variant") or {}),
            "variants": copy.deepcopy(character.get("variants") or []),
            "reference_ids": copy.deepcopy(
                character.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(character.get("vibe_ids") or []),
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
    return style_bundle_signature({
        "prompt": prompt, "negative": negative, "settings": settings,
    })


def _comparison_result_evaluation(path, manifest, job_key):
    """선별 장부의 현재 평가를 결과 한 장의 공통 평가 계약으로 투영한다."""
    picks = load_picks()
    path = str(path or "").replace("\\", "/")
    review_state = str(
        (picks.get("review_states") or {}).get(path) or "candidate")
    if review_state not in ("candidate", "confirmed", "shared", "archived"):
        review_state = "candidate"
    return {
        "subject": {"kind": "generation-result", "path": path},
        "favorite": path in set(picks.get("fav") or []),
        "rating": (picks.get("ratings") or {}).get(path),
        "memo": str((picks.get("memos") or {}).get(path) or ""),
        "tags": list((picks.get("tags") or {}).get(path) or []),
        "review_state": review_state,
        "evidence_refs": [],
        "result_refs": [f"result:{path}"],
        "asset_refs": [],
        "comparison_lineage": {
            "manifest_signature": str(manifest.get("signature") or ""),
            "manifest_folder": str(manifest.get("folder") or ""),
            "job_key": str(job_key or ""),
            "mode": str(manifest.get("mode") or ""),
        },
    }


class LegacyPromotionLineageUnavailable(ValueError):
    """엄격 실행 식별자가 전혀 없는 구형 비교 결과."""


def _result_promotion_records(
    cfg, rel, kind, name="", resolved_names=None,
):
    """새 비교 결과의 검증 가능한 계보와 명시적 자산 내용을 승격 레코드로 만든다."""
    context = _comparison_result_context(cfg, rel)
    restored = comparison_recipe_for_output(cfg, rel)
    recipe = restored["recipe"]
    record = context["record"]
    strict_keys = (
        "content_sha256", "request_id", "payload_hash",
        "blueprint_fingerprint",
    )
    # 진짜 구형은 키 자체가 없다. 새 형식의 키가 있는데 값이 비었거나 일부만
    # 남은 경우는 손상된 strict 결과이지 구형 호환 대상으로 낮추면 안 된다.
    present = [key for key in strict_keys if key in record]
    if not present:
        raise LegacyPromotionLineageUnavailable(
            "이 비교 결과에는 엄격 실행 식별자가 없습니다.")
    missing = [key for key in strict_keys if not record.get(key)]
    if missing:
        raise ValueError(
            "비교 결과의 엄격 실행 식별자가 일부 빠졌습니다: "
            + ", ".join(missing))
    actual_sha = hashlib.sha256(
        context["image_path"].read_bytes()).hexdigest()
    if actual_sha != str(record.get("content_sha256") or "").lower():
        raise ValueError(
            "저장된 비교 이미지가 manifest 기록 뒤 바뀌어 엄격한 계보로 승격할 수 없습니다.")
    result = {
        "path": context["file"],
        "content_sha256": actual_sha,
        "request_id": record.get("request_id"),
        "payload_hash": record.get("payload_hash"),
        "blueprint_fingerprint": record.get("blueprint_fingerprint"),
    }
    evaluation = _comparison_result_evaluation(
        context["file"], context["manifest"], context["job_key"])
    target = str(kind or "").strip().casefold()
    if target == "style":
        settings = {
            key: value for key, value in (recipe.get("settings") or {}).items()
            if key in COMPARE_RECIPE_SETTING_KEYS and value is not None
        }
        return [build_result_promotion(
            result,
            context["manifest"],
            evaluation,
            target="style",
            name=str(
                ((resolved_names or [""])[0] if resolved_names else "")
                or name or recipe.get("style_name") or ""),
            content={
                "base": str(recipe.get("base_prompt") or ""),
                "negative": str(recipe.get("negative_prompt") or ""),
                "generation_settings": settings,
            },
        )]
    if target != "characters":
        raise ValueError("승격할 자료 종류가 올바르지 않습니다.")
    output = []
    slots = [
        slot for slot in (recipe.get("char_slots") or [])
        if isinstance(slot, dict) and slot_prompt(slot).strip()
    ]
    for index, slot in enumerate(slots, 1):
        variants = copy.deepcopy(slot.get("variants") or [])
        variant = copy.deepcopy(slot.get("variant") or {})
        if variant and variant not in variants:
            variants.insert(0, variant)
        output.append(build_result_promotion(
            result,
            context["manifest"],
            evaluation,
            target="character",
            name=str(
                (
                    resolved_names[index - 1]
                    if resolved_names and index <= len(resolved_names)
                    else ""
                )
                or slot.get("name") or f"비교 결과 캐릭터 {index}"),
            content={
                "prompt": slot_prompt(slot),
                "appearance": str(
                    slot.get("prompt") or slot.get("female") or ""),
                "clothed": str(
                    slot.get("outfit") or slot.get("clothed") or ""),
                "negative": str(slot.get("negative") or ""),
                "variants": variants,
                "reference_refs": list(slot.get("reference_ids") or []),
                "vibe_refs": list(slot.get("vibe_ids") or []),
            },
        ))
    if not output:
        raise ValueError("이 비교 결과에는 승격할 캐릭터가 없습니다.")
    return output


def _append_result_promotion_ledger(records):
    ledger = new_promotion_ledger()
    if PROMOTION_LEDGER_FILE.is_file():
        loaded = load_json_recover(PROMOTION_LEDGER_FILE)
        if isinstance(loaded, dict):
            ledger = loaded
    merged = append_promotion_events(ledger, records)
    atomic_write_json(
        PROMOTION_LEDGER_FILE, merged["ledger"], indent=2, keep_backup=True)
    return {
        "appended": list(merged.get("appended") or []),
        "duplicates": list(merged.get("duplicates") or []),
        "file": PROMOTION_LEDGER_FILE.relative_to(BASE_DIR).as_posix(),
    }


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
        same_collected = next((
            item for item in load_combos()
            if isinstance(item, dict) and style_bundle_signature(item) == wanted
        ), None)
        if same_collected is not None:
            return {
                "ok": True, "kind": "style", "saved": 0, "existing": 1,
                "names": [same_collected.get("title")
                          or same_collected.get("id") or "기존 그림체"],
                "styles": styles, "changed_config": False,
                "existing_store": "수집/그림체.json",
            }
        final_name = _unique_library_name(
            STYLE_DIR,
            name or recipe.get("style_name"),
            "비교 결과 그림체",
            (item.get("name") for item in styles),
        )
        save_style_file(
            final_name, prompt=prompt, negative=negative, settings=settings)
        batch_id = None
        saved_path = STYLE_DIR / f"{_safe_name(final_name)}.json"
        try:
            rel_path = saved_path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
        except (OSError, ValueError):
            rel_path = ""
        if rel_path and saved_path.is_file():
            batch_id = record_import_batch({
                "kind": "comparison", "file": restored["file"],
                "installed": [{
                    "path": rel_path,
                    "sha256": hashlib.sha256(saved_path.read_bytes()).hexdigest(),
                }],
                "요약": "비교 결과: 그림체 묶음 1건 승격",
            })
        return {
            "ok": True, "kind": "style", "saved": 1, "existing": 0,
            "names": [final_name],
            "styles": list_styles(spec or load_spec()),
            "changed_config": False, "batch": batch_id,
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
    names, saved, existing, saved_records = [], 0, 0, []
    for index, slot in enumerate(slots, 1):
        prompt = str(slot.get("prompt") or "")
        outfit = str(slot.get("outfit") or "")
        negative = str(slot.get("negative") or "")
        wanted_character = character_bundle_signature({
            "female": prompt,
            "clothed": outfit,
            "negative": negative,
            "variant": copy.deepcopy(slot.get("variant") or {}),
            "variants": copy.deepcopy(slot.get("variants") or []),
            "reference_ids": copy.deepcopy(slot.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(slot.get("vibe_ids") or []),
        })
        same = next((
            item for item in characters
            if character_bundle_signature(item) == wanted_character
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
        created = {
            "id": "".join(random.choices(
                string.ascii_lowercase + string.digits, k=8)),
            "name": final_name,
            "female": prompt,
            "clothed": outfit,
            "negative": negative,
            "variant": copy.deepcopy(slot.get("variant") or {}),
            "variants": copy.deepcopy(slot.get("variants") or []),
            "reference_ids": copy.deepcopy(slot.get("reference_ids") or []),
            "vibe_ids": copy.deepcopy(slot.get("vibe_ids") or []),
            "enabled": True,
            "folder_id": None,
            "subfolder_id": None,
            "source": f"비교 결과: {restored['file']}",
        }
        characters.append(created)
        saved_records.append(created)
        names.append(final_name)
        saved += 1
    if saved:
        sync_chars_to_files(cfg)
        save_config(cfg)
    batch_id = None
    try:
        settings_inside = (
            SETTINGS_FILE.resolve() == BASE_DIR.resolve()
            or BASE_DIR.resolve() in SETTINGS_FILE.resolve().parents
        )
    except OSError:
        settings_inside = False
    if saved and settings_inside:
        records = [{
            "id": item.get("id"),
            "after_signature": character_bundle_signature(item),
        } for item in saved_records]
        batch_id = record_import_batch({
            "kind": "comparison", "file": restored["file"],
            "characters": records,
            "요약": f"비교 결과: 캐릭터 묶음 {len(records)}건 승격",
        })
    return {
        "ok": True, "kind": "characters", "saved": saved, "existing": existing,
        "names": names, "characters": characters,
        "changed_config": bool(saved), "batch": batch_id,
    }


def _comparison_progress_save(progress, folder):
    """재개용 기록과 사람이 읽을 결과 폴더 manifest를 함께 원자 저장한다."""
    atomic_write_json(COMPARE_PROGRESS_FILE, progress, indent=1)
    atomic_write_json(folder / "manifest.json", progress, indent=1)


def _comparison_progress_start(cfg, plan, styles, chars):
    root = out_root(cfg).resolve()
    signature = comparison_signature(cfg, plan, styles, chars)
    old = _comparison_progress_load()
    same_plan = (
        old.get("signature") == signature
        and isinstance(old.get("completed"), dict)
    )
    folder = None
    old_has_invalid_result = False
    if same_plan:
        rel = str(old.get("folder") or "")
        candidate = (root / rel).resolve()
        if (_path_is_inside(candidate, root) and candidate.is_dir()):
            folder = candidate
            for record in old["completed"].values():
                rel_result = (
                    record.get("file") if isinstance(record, dict) else record
                )
                result_path = output_file_for_preview(cfg, rel_result)
                valid = (
                    result_path is not None
                    and result_path.is_file()
                    and result_path.stat().st_size > 0
                )
                expected_hash = (
                    str(record.get("content_sha256") or "")
                    if isinstance(record, dict) else ""
                )
                if valid and expected_hash:
                    try:
                        valid = (
                            hashlib.sha256(result_path.read_bytes()).hexdigest()
                            == expected_hash
                        )
                    except OSError:
                        valid = False
                if not valid:
                    old_has_invalid_result = True
                    break
    resumable = (
        folder is not None
        and (
            old.get("status") not in ("complete",)
            or old_has_invalid_result
        )
    )
    if not resumable:
        folder = None
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
        valid = path is not None and path.is_file() and path.stat().st_size > 0
        expected_hash = (
            str(rec.get("content_sha256") or "")
            if isinstance(rec, dict) else ""
        )
        if valid and expected_hash:
            try:
                valid = hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
            except OSError:
                valid = False
        if not valid:
            completed.pop(key, None)
    _comparison_progress_save(progress, folder)
    return progress, folder


def _selected_comparison_record(cfg, rel):
    image = output_file_for_preview(cfg, rel)
    if image is None:
        raise ValueError("다시 실행할 비교 결과를 찾지 못했습니다.")
    root = out_root(cfg).resolve()
    folder = image.parent.resolve()
    if not _path_is_inside(folder, (root / "비교생성").resolve()):
        raise ValueError("비교 생성 결과만 한 셀 다시 실행할 수 있습니다.")
    progress = load_json_recover(folder / "manifest.json")
    if not isinstance(progress, dict) or progress.get("mode") != "selected":
        raise ValueError("직접 고른 자료·축 실험 결과만 한 셀 다시 실행할 수 있습니다.")
    wanted = image.relative_to(root).as_posix()
    for section in ("completed", "reruns"):
        rows = progress.get(section)
        if not isinstance(rows, dict):
            continue
        for key, record in rows.items():
            if (isinstance(record, dict)
                    and str(record.get("file") or "").replace("\\", "/")
                    == wanted):
                return progress, folder, str(key), copy.deepcopy(record)
    raise ValueError("manifest에서 선택한 셀 기록을 찾지 못했습니다.")


def _rerun_selected_comparison(server, cfg, rel):
    """선택 실험의 한 canonical 셀만 같은 seed로 다시 실행해 새 결과로 남긴다."""
    progress, folder, source_key, source = _selected_comparison_record(cfg, rel)
    cell = source.get("canonical_cell")
    if not isinstance(cell, dict):
        raise ValueError("이 결과에는 한 셀 재실행 정보가 없습니다.")
    plan = progress.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("이 결과의 선택 실험 계획을 읽지 못했습니다.")
    attempt = max(2, int(source.get("rerun_attempt") or 1) + 1)
    material = regenerate_legacy_execution_material(
        cell, cfg, attempt=attempt,
        runtime_base_seed=int(progress.get("base_seed") or source.get("seed") or 1),
    )
    scratch = _comparison_selected_cfg(cfg, material)
    job = {
        "index": int(source.get("index") or 1),
        "key": source_key,
        "cell_id": material.get("cell_id"),
        "cell_resume_key": material.get("resume_key"),
        "canonical_cell": cell,
        "material": material,
        "scratch_cfg": scratch,
        "style": (material.get("job") or {}).get("style"),
        "character": (material.get("job") or {}).get("character"),
        "setting": (material.get("job") or {}).get("setting"),
        "style_name": source.get("style") or "현재 그림체",
        "char_name": source.get("character") or "현재 캐릭터",
        "setting_name": source.get("setting") or "",
        "seed_index": int(source.get("seed_index") or 0),
        "seed": int(source.get("seed") or material.get("seed") or 1),
        "cid": str(source.get("cid") or source.get("cast_id") or ""),
        "scene_num": int(source.get("scene") or 0),
        "copy": int(source.get("copy") or 1),
    }
    if isinstance(job["setting"], dict) and job["scene_num"]:
        acfg = load_asset_config(scratch)
        matches = [
            (derived, str(cid))
            for derived, cid, scene_num, copy_num in compute_pending(
                scratch, acfg, {}, set())
            if int(scene_num) == job["scene_num"]
            and int(copy_num) == job["copy"]
            and (not job["cid"] or str(cid) == job["cid"])
        ]
        if len(matches) != 1:
            raise ValueError("선택했던 세팅 씬을 현재 자료에서 찾지 못했습니다.")
        job["asset_config"] = acfg
        job["scene_character"] = copy.deepcopy(matches[0][0])
        job["cid"] = matches[0][1]
    used, base, negative, people, centers = comparison_selected_job_values(
        cfg, plan, job)
    execution_cfg = copy.deepcopy(used)
    execution_cfg.update({
        "base_prompt": base,
        "negative_prompt": negative,
        "char_slots": [
            {
                "prompt": str(person.get("prompt") or ""),
                "negative": str(person.get("negative") or ""),
                "enabled": True,
            }
            for person in people if isinstance(person, dict)
        ],
        "char_centers": copy.deepcopy(centers),
        "nai_seed": job["seed"],
    })
    execution_blueprint = generation_blueprint(
        execution_cfg,
        source={
            "kind": "comparison-rerun",
            "cell": source_key,
            "attempt": attempt,
        },
        experiment={"mode": "selected_groups"},
    )
    token = cfg["token"]
    allowed, why = pace_gate(cfg, server.live, "비교 한 셀 재실행")
    if not allowed:
        raise ValueError(why)
    params = runtime_generation_params(
        used, token, include_refs=plan["options"].get("include_refs", False))
    try:
        image = call_nai_api(
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
            seed=job["seed"], params=with_centers(params, centers),
        )
    finally:
        pace_complete()
    source_path = output_file_for_preview(cfg, source["file"])
    stem = (
        source_path.stem if source_path is not None
        else f"{job['index']:06d}_selected")
    target = available_output_path(
        folder / f"{stem}_rerun{attempt}.webp", out_format(cfg))
    image.nai_blueprint_fingerprint = execution_blueprint["fingerprint"]
    saved = save_with_meta(
        image, target, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
        max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
    server.live.set_image(image)
    root = out_root(cfg).resolve()
    rel_saved = saved.resolve().relative_to(root).as_posix()
    record_job_result(
        server.live.job_id, saved, artifact=rel_saved,
        source_result_ids=[source_key],
    )
    rerun_key = f"{source_key}:rerun:{attempt}:{uuid.uuid4().hex[:8]}"
    record = copy.deepcopy(source)
    record.update({
        "file": rel_saved,
        "rerun_of": source_key,
        "rerun_attempt": attempt,
        "content_sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
        "request_id": str(getattr(image, "nai_request_id", "") or ""),
        "payload_hash": str(getattr(image, "nai_payload_hash", "") or ""),
        "blueprint_fingerprint": execution_blueprint["fingerprint"],
        "seed": job["seed"],
        "recipe": comparison_job_recipe_snapshot(
            cfg, plan, job, used, base, negative,
            people, centers, job["seed"]),
    })
    progress.setdefault("reruns", {})[rerun_key] = record
    progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _comparison_progress_save(progress, folder)
    state = load_state()
    bump_daily(state)
    save_state(state)
    server.live.update(
        index=1, total=1, completed=1, failed=0,
        filename=saved.name, seed=job["seed"],
        status_text=f"선택 실험 한 셀 재실행 완료 · {saved.name}",
        phase="completed", can_retry=False,
    )


def _run_comparison(server, cfg, plan, styles, chars):
    """자료 비교 큐. 한 번에 한 요청만 보내고 중지·일일 상한·재개를 모두 지킨다."""
    progress, folder = _comparison_progress_start(cfg, plan, styles, chars)
    previous_job_id = str(progress.get("job_id") or "")
    # 실행권을 잡을 때 만든 durable Job과 비교 manifest가 같은 작업을 가리킨다.
    # 옛 manifest에는 이 필드가 없으므로 새 실행에서만 보강하고 결과는 건드리지 않는다.
    if server.live.job_id and progress.get("job_id") != server.live.job_id:
        if previous_job_id:
            try:
                link_job_ancestor(server.live.job_id, previous_job_id)
            except Exception as error:
                log.warning("이전 비교 Job 계보 연결 실패: %s", error)
        attempts = progress.setdefault("attempt_job_ids", [])
        for identifier in (previous_job_id, server.live.job_id):
            if identifier and identifier not in attempts:
                attempts.append(identifier)
        progress["job_id"] = server.live.job_id
        progress["request_id"] = server.live.job_id
        _comparison_progress_save(progress, folder)
    completed = progress["completed"]
    lineage_errors = progress.setdefault("lineage_errors", {})
    if server.live.job_id:
        for key, record in completed.items():
            if not isinstance(record, dict):
                continue
            path = output_file_for_preview(cfg, record.get("file"))
            if path is None:
                continue
            try:
                record_job_result(
                    server.live.job_id,
                    path,
                    artifact=str(record.get("file") or ""),
                    result_id=(
                        "result-comparison-"
                        + hashlib.sha256(
                            f"{key}\0{record.get('blueprint_fingerprint') or ''}"
                            .encode("utf-8")
                        ).hexdigest()[:24]
                    ),
                )
                lineage_errors.pop(str(key), None)
            except Exception as error:
                log.warning("검증된 비교 결과의 Job 계보 연결 실패: %s", error)
                lineage_errors[str(key)] = redact_diagnostic_text(error)
    errors = progress.setdefault("errors", {})
    options = plan["options"]
    token = cfg["token"]
    base_seed = int(progress["base_seed"])
    state = load_state()
    if options.get("mode") == "character_setting":
        jobs = iter_character_setting_jobs(cfg, plan, chars)
    elif options.get("mode") == "selected":
        jobs = iter_selected_comparison_jobs(
            cfg, plan, styles, chars, runtime_base_seed=base_seed)
    else:
        jobs = iter_comparison_jobs(cfg, plan, styles, chars)
    done_n = len(completed)
    run_failed = set()
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
            int(job.get("seed") or 0)
            if options.get("mode") == "selected"
            else (
                (base_seed + seed_index * 100003) & 0xffffffff
                if options["same_seed"]
                else (base_seed + (job["index"] - 1) * 100003) & 0xffffffff
            )
        )
        seed = seed or 1
        execution_cfg = copy.deepcopy(used)
        execution_cfg.update({
            "base_prompt": base,
            "negative_prompt": negative,
            "char_slots": [
                {
                    "name": f"비교 인물 {index + 1}",
                    "prompt": str(person.get("prompt") or ""),
                    "outfit": "",
                    "negative": str(person.get("negative") or ""),
                    "enabled": True,
                }
                for index, person in enumerate(people)
                if isinstance(person, dict)
            ],
            "char_centers": copy.deepcopy(centers),
            "nai_seed": seed,
        })
        execution_blueprint = generation_blueprint(
            execution_cfg,
            source={
                "kind": "comparison",
                "mode": options.get("mode"),
                "cell": str(job.get("key") or ""),
            },
            experiment={
                "mode": options.get("mode") or "comparison",
            },
        )
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
        done_n = len(completed) + len(run_failed)
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
                img.nai_blueprint_fingerprint = execution_blueprint["fingerprint"]
                saved = save_with_meta(
                    img, target, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                    max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                server.live.set_image(img)
                rel = saved.resolve().relative_to(out_root(cfg).resolve()).as_posix()
                try:
                    record_job_result(
                        server.live.job_id,
                        saved,
                        artifact=rel,
                        result_id=(
                            "result-comparison-"
                            + hashlib.sha256(
                                f"{key}\0{execution_blueprint['fingerprint']}"
                                .encode("utf-8")
                            ).hexdigest()[:24]
                        ),
                    )
                    lineage_errors.pop(str(key), None)
                except Exception as error:
                    lineage_errors[str(key)] = redact_diagnostic_text(error)
                    log.warning(
                        "비교 결과는 저장했지만 Job 계보 연결에 실패: %s",
                        error,
                    )
                completed[key] = {
                    "index": job["index"], "file": rel,
                    "style": style_label, "character": char_label,
                    "style_id": ((job.get("style") or {}).get("_compare_id")),
                    "character_id": (
                        (job.get("character") or {}).get("_compare_id")),
                    "seed_index": seed_index,
                    "seed": seed, "width": int(used["width"]),
                    "height": int(used["height"]),
                    "content_sha256": hashlib.sha256(
                        saved.read_bytes()).hexdigest(),
                    "request_id": str(
                        getattr(img, "nai_request_id", "") or ""),
                    "payload_hash": str(
                        getattr(img, "nai_payload_hash", "") or ""),
                    "blueprint_fingerprint": execution_blueprint["fingerprint"],
                }
                if options.get("mode") in ("character_setting", "selected"):
                    completed[key].update({
                        "cell_id": job.get("cell_id"),
                        "cell_resume_key": job.get("cell_resume_key"),
                        "setting": job.get("setting_name"),
                        "setting_id": (
                            (job.get("setting") or {}).get("id")
                            or (job.get("setting") or {}).get("name")
                        ),
                        "scene": int(job.get("scene_num") or 0),
                        "copy": int(job.get("copy") or 1),
                        "recipe": comparison_job_recipe_snapshot(
                            cfg, plan, job, used, base, negative,
                            people, centers, seed,
                        ),
                    })
                    if options.get("mode") == "selected":
                        cell = job.get("canonical_cell") or {}
                        completed[key]["cid"] = str(job.get("cid") or "")
                        completed[key]["cast_id"] = str(job.get("cid") or "")
                        completed[key]["canonical_cell"] = {
                            name: copy.deepcopy(cell.get(name))
                            for name in (
                                "id", "legacy_resume_key",
                                "legacy_job_key", "seed_material",
                                "legacy_material",
                            )
                            if cell.get(name) is not None
                        }
                        completed[key]["canonical_cell"]["blueprint"] = {
                            "experiment": {
                                "mode": "selected_groups",
                            },
                        }
                errors.pop(key, None)
                bump_daily(state)
                try:
                    save_state(state)
                except Exception as error:
                    lineage_errors[str(key)] = redact_diagnostic_text(error)
                    log.warning(
                        "비교 결과는 저장했지만 생성량 장부 저장에 실패: %s",
                        error,
                    )
                progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                try:
                    _comparison_progress_save(progress, folder)
                except Exception as error:
                    lineage_errors[str(key)] = redact_diagnostic_text(error)
                    log.warning(
                        "비교 결과는 저장했지만 재개 manifest 저장에 실패: %s",
                        error,
                    )
                server.live.update(
                    daily=daily_count(state),
                    completed=len(completed),
                    failed=len(run_failed),
                    index=len(completed) + len(run_failed),
                )
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
            run_failed.add(key)
            server.live.update(
                index=len(completed) + len(run_failed),
                failed=len(run_failed),
                last_error=last_error or "중지됨",
                can_retry=True,
            )
            progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _comparison_progress_save(progress, folder)
            if fatal or final_status in ("stopped", "daily_limit"):
                break

    if final_status == "complete" and lineage_errors:
        final_status = "partial"
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

    recover_job_ledger()
    server = ConfigServer(cfg, persist_jobs=True)
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
        with server.config_lock:
            run_cfg = copy.deepcopy(
                server.pending_batch_config
                if isinstance(server.pending_batch_config, dict)
                else server.cfg
            )
            server.pending_batch_config = None
        # 단독 생성 등이 그 틈에 실행권을 가져갔다면 배치를 겹쳐 돌리지 않는다
        tok = server.live.try_claim(
            "세팅 배치 생성",
            "settings",
            blueprint=inherited_blueprint(
                run_cfg,
                source={"kind": "settings-batch"},
            ),
            payload_identity={
                "kind": "setting", "seed_round": run_cfg.get("seed")},
        )
        if tok is None:
            server.start_event.clear()
            server.live.update(status_text="다른 생성이 도는 중입니다 — 끝난 뒤 '생성 시작'을 다시 눌러주세요.")
            continue
        try:
            _run_generation(server, run_cfg)
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


def _run_generation(server, cfg_snapshot=None):
    cfg = copy.deepcopy(
        cfg_snapshot if isinstance(cfg_snapshot, dict) else server.cfg)
    seed_idx = int(cfg.get("seed", 1) or 1)
    seed_key = f"{seed_idx:02d}"

    state = load_state()
    if seed_key not in state["seeds"]:
        state["seeds"][seed_key] = random.randint(0, 2**32 - 1)
        save_state(state)
    base_seed = state["seeds"][seed_key]           # 이 회차의 기준 시드
    # 조각 순차(<*이름>) 순번은 배치 내내, 그리고 다음 실행까지 이어진다.
    # cfg 에 실어 두면 call_nai_api 가 장마다 하나씩 올려 준다.
    state.setdefault("frag_seq", {})
    cfg["_frag_counters"] = state["frag_seq"]
    server.live.update(seed_key=seed_key)
    if fixed_seed(cfg):
        log.info(f"═══ 회차 {seed_key} — NAI 시드 고정 {fixed_seed(cfg)} "
                 f"(모든 장이 같은 시드) ═══")
    else:
        log.info(f"═══ 회차 {seed_key} (기준 시드 {base_seed}) — 장마다 '기준+씬번호' 시드. "
                 f"같은 회차를 다시 돌리면 같은 결과 ═══")
    log.info(f"오늘 생성량: {daily_count(state)}/{DAILY_CAP}")

    characters_now = cfg.get("characters", [])
    enabled_now = [c for c in characters_now if c.get("enabled", True)]
    sel_summary = " · ".join(
        f"{name} {len(st.get('selected', []))}세트"
        for name, st in (cfg.get("setting_state") or {}).items()
        if st.get("use") is not False and st.get("selected"))
    log.info(f"캐릭터 {len(enabled_now)}명 켜짐 (전체 {len(characters_now)}명) · 선택: {sel_summary or '없음'}")
    if not enabled_now:
        log.warning("⚠ 켜진 캐릭터가 없습니다. 브라우저에서 캐릭터를 추가하거나 켜주세요.")

    # 이 회차에서 **이미 끝낸 장**을 상태 파일에서 되살린다 (CQA-010).
    #   예전에는 progress 를 쓰기만 하고 읽지 않아, 중지 후 '생성 시작'을 다시 누르면
    #   끝난 장을 처음부터 다시 만들고 같은 파일을 덮어썼다 (Anlas·시간 재소모).
    #   회차(seed) 를 바꾸면 progress 키가 달라져 자연히 새로 시작한다.
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
    verified_records = []
    invalid_records = 0
    lineage_failures = 0
    candidates = compute_pending(cfg, acfg, {}, set())
    for char, cid, num, copy_num in candidates:
        record = records.get((cid, num, copy_num))
        if record is None:
            continue
        fingerprint = generation_task_fingerprint(
            context_fingerprint, char, cid, num, copy_num)
        if progress_record_valid(record, cfg, fingerprint):
            done_this_run.setdefault(cid, set()).add((num, copy_num))
            verified_records.append(
                (str(cid), int(num), int(copy_num), record, fingerprint))
        else:
            invalid_records += 1
    n_done = sum(len(v) for v in done_this_run.values())
    if n_done:
        log.info(f"회차 {seed_key}의 파일·설정이 일치하는 완료 {n_done}장을 건너뜁니다.")
        for cid, num, copy_num, record, fingerprint in verified_records:
            try:
                record_job_result(
                    server.live.job_id,
                    progress_record_path(record, cfg),
                    artifact=str(record.get("path") or ""),
                    result_id=(
                        "result-setting-"
                        + hashlib.sha256(
                            f"{seed_key}\0{cid}\0{num}\0{copy_num}\0"
                            f"{fingerprint}".encode("utf-8")
                        ).hexdigest()[:24]
                    ),
                )
            except Exception as error:
                log.warning("검증된 세팅 결과의 Job 계보 연결 실패: %s", error)
                lineage_failures += 1
    if legacy_records or invalid_records:
        log.warning("재개 기록 중 파일 또는 설정 근거가 없는 %d건은 다시 생성합니다.",
                    legacy_records + invalid_records)
    skip_set = set()   # 이번 실행에서 계속 실패해 건너뛴 작업 (재실행하면 다시 시도)
    completed = n_done
    server.live.update(
        completed=completed,
        eta_base_completed=completed,
        total=max(len(candidates), completed),
    )

    while True:
        if server.live.stop_req:   # /api/stop — 장 경계에서 멈춘다 (실행권은 finally 가 푼다)
            log.info("■ 중지되었습니다 — '생성 시작'을 다시 누르면 이어서 합니다.")
            server.live.update(
                status_text="중지됨 — '생성 시작'을 누르면 이어서 합니다.",
                phase="stopped", can_retry=True)
            save_state(state)
            return
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
        char, cid, num, copy_num = pending[0]
        total_now = completed + len(skip_set) + len(pending)

        try:
            out_dir = out_sub(cfg, "nsfw_seed") / f"seed_{seed_key}" / cid
            out_dir.mkdir(parents=True, exist_ok=True)

            scene = acfg["scenes"][str(num)]
            # 씬에서 Reference를 따로 고른 경우에만 전역 활성 목록을 그 선택으로
            # 좁힌다. Vibe는 그대로 유지하고 캐릭터 Reference만 씬 범위를 따른다.
            cast_cfg = character_resource_config(cfg, char)
            reference_cfg, _, _ = setting_reference_config(cast_cfg, scene)
            params = runtime_generation_params(reference_cfg, token)
            char_label = char.get("name") or cid
            suffix = "" if copy_num == 1 else f"_{copy_num}벌"
            fname = (f"{num:03d}_{scene['name'].replace(' ', '_').replace('/', '_')}"
                     f"{suffix}.webp")
            base_p, female, male, char_neg, male_neg, w, h = build_scene(acfg, char, cfg, num)
        except Exception as e:
            log.error(f"[{completed+1}/{total_now}] 프롬프트/폴더 준비 중 오류로 이 컷 건너뜀: {e}")
            log.error(traceback.format_exc())
            skip_set.add((cid, num, copy_num))
            server.live.update(
                status_text=f"오류(건너뜀): {e}", failed=len(skip_set),
                last_error=str(e), can_retry=True)
            if server.live.wait_cancelable(1):
                return
            continue

        # 이 장의 시드 — 씬 번호로 갈라지고, 같은 씬을 여러 벌 뽑으면 벌마다 또 갈라진다
        # (안 그러면 2벌·3벌이 1벌과 똑같은 그림이 된다)
        seed = seed_for(cfg, base_seed, num + (copy_num - 1) * 100003)
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
                # 주인공 + 상대역 + 추가 인물의 프롬프트와 위치를 같은 순서로
                # 만든다. 씬 전용 위치가 있으면 전역 위치보다 우선한다.
                people, centers, use_positions = setting_scene_people(
                    scene, female, male, char_neg, male_neg, char, cfg)
                scene_params = with_position_mode(
                    params, char.get("position_mode"), use_positions)
                if use_positions:
                    scene_params = with_centers(scene_params, centers)
                try:
                    img = call_nai_api(token, base_p, "", "", neg_now, w, h,
                                       chars=people,
                                       scale=scale, cfg_rescale=cfg_rescale,
                                       steps=steps, sampler=sampler, scheduler=scheduler, uc_preset=uc_preset,
                                       seed=seed, variety=variety, params=scene_params)
                finally:
                    pace_complete()
                frozen = server.live.frozen_blueprint()
                img.nai_blueprint_fingerprint = str(
                    (frozen or {}).get("fingerprint") or "")
                saved_path = save_with_meta(
                    img, out_dir / fname, fmt=out_format(cfg), clean=_ocargs(cfg)[0],
                    max_side=_ocargs(cfg)[1], quality=out_clean(cfg)[2])
                fingerprint = generation_task_fingerprint(
                    context_fingerprint, char, cid, num, copy_num)
                try:
                    record_job_result(
                        server.live.job_id,
                        saved_path,
                        artifact=saved_path.resolve().relative_to(
                            out_root(cfg).resolve()).as_posix(),
                        result_id=(
                            "result-setting-"
                            + hashlib.sha256(
                                f"{seed_key}\0{cid}\0{num}\0{copy_num}\0"
                                f"{fingerprint}".encode("utf-8")
                            ).hexdigest()[:24]
                        ),
                    )
                except Exception as error:
                    lineage_failures += 1
                    log.warning(
                        "세팅 결과는 저장했지만 Job 계보 연결에 실패: %s",
                        error,
                    )
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
            done_this_run.setdefault(cid, set()).add((num, copy_num))
            record = make_progress_record(
                cfg, num, copy_num, saved_path, fingerprint)
            rec = state["progress"].setdefault(seed_key, {}).setdefault(cid, [])
            rec[:] = [
                item for item in rec
                if progress_item_key(item) != (num, copy_num)
            ]
            rec.append(record)
            bump_daily(state)
            completed += 1
            server.live.update(
                daily=daily_count(state), completed=completed,
                failed=len(skip_set))
            # 매 장 저장한다 — 중지·강제 종료 후 재개가 정확해야 하고 파일은 몇 KB 다
            try:
                save_state(state)
            except Exception as error:
                lineage_failures += 1
                log.warning(
                    "세팅 결과는 저장했지만 재개 장부 저장에 실패: %s",
                    error,
                )
        else:
            skip_set.add((cid, num, copy_num))
            server.live.update(
                status_text=f"실패 — 건너뜀: {fname}",
                failed=len(skip_set), can_retry=True)

    if lineage_failures:
        server.live.update(
            failed=max(server.live.failed, lineage_failures),
            status_text=(
                "이미지는 저장했지만 작업 계보·재개 장부 일부를 확인해야 합니다."
            ),
            phase="partial",
            can_retry=True,
        )


if __name__ == "__main__":
    main()
