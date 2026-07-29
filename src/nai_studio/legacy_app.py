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
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path

import requests
from PIL import Image
from src.nai_studio.collection import arca as arca_public
from src.nai_studio.domain.blueprint import (
    canonical_blueprint,
    fingerprint_blueprint,
)
from src.nai_studio.domain.project_inheritance import (
    blueprint_common,
    local_overrides,
    normalize_link,
    normalize_projects,
    project_by_id,
    resolve_inheritance,
)
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
    fixed_seed,
    image_to_image_fields,
    is_v4_model,
    reference_fields,
    seed_for,
    variety_sigma,
    variety_sigma_value,
)
from src.nai_studio.domain.positioning import (
    normalize_scene_centers,
    normalize_position_mode,
    position_mode_uses_coords,
    spread_centers,
    with_centers,
    with_position_mode,
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
from src.nai_studio.runtime.errors import FatalStopError
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
from src.nai_studio.services.evaluation_workflow import (
    apply_evaluation_action_workflow,
    normalize_picks,
)
from src.nai_studio.services.experiment_bridge import (
    expand_legacy_experiment_cells,
)
from src.nai_studio.services import (
    artist_workspace as _artist_workspace,
    catalog_search as _catalog_search,
    character_storage as _character_storage,
    collection_handlers as _collection_handlers,
    comparison_execution as _comparison_execution,
    comparison_handlers as _comparison_handlers,
    comparison_planning as _comparison_planning,
    comparison_promotion as _comparison_promotion,
    comparison_runtime as _comparison_runtime,
    datapack_store as _datapack_store,
    generation_commit as _generation_commit,
    generation_execution as _generation_execution,
    generation_handlers as _generation_handlers,
    generation_retry as _generation_retry,
    generation_step as _generation_step,
    image_tool_handlers as _image_tool_handlers,
    library_catalog as _library_catalog,
    local_image_store as _local_image_store,
    metadata_candidate_store as _metadata_candidate_store,
    output_lifecycle as _output_lifecycle,
    program_data_migration as _program_data_migration,
    public_style_import as _public_style_import,
    setting_runtime as _setting_runtime,
    settings_handlers as _settings_handlers,
    style_store as _style_store,
    user_backup_store as _user_backup_store,
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
from src.nai_studio.services.character_runtime import (
    active_people,
    character_run_from_group,
    slot_bundle_identity,
    slot_prompt,
)
from src.nai_studio.services.config_validation import (
    NUMERIC_RULES as _NUMERIC_RULES,
    PACE_RULES as _PACE_RULES,
    bounded_number as _bounded_number,
    normalize_cast_presets,
    normalize_resolution,
    validate_config_value as _validate_config_value,
)
from src.nai_studio.services.generation_blueprint import (
    BLUEPRINT_GENERATION_KEYS,
    generation_blueprint,
)
from src.nai_studio.services.generation_runtime import (
    runtime_generation_params as _prepare_runtime_references,
)
from src.nai_studio.services.nai_client import (
    APIError,
    AccountBannedError,
    AuthError,
    RateLimitError,
    request_nai_image,
    retry_after_seconds,
)
from src.nai_studio.services.result_store import (
    _atomic_save_image,
    _ocargs,
    available_output_path,
    out_clean,
    out_format,
    save_with_meta,
)
from src.nai_studio.services.prompt_bridge import (
    legacy_sequence_text,
    reroll_legacy_components,
    resolve_legacy_fragments,
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
from src.nai_studio.services.setting_compiler import (
    AXIS_SHAPES,
    AXIS_TARGETS,
    LEGACY_AXES,
    _build_std,
    _build_yuri,
    _guess_shape,
    _join_tags,
    _strip_subject_prefix,
    apply_axes,
    axis_specs,
    build_scene,
    clean_char_prompt,
    load_asset_config as _compile_asset_config,
    remove_prompt_tags,
    setting_scene_people,
    setting_state,
)
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
    paths = _program_data_migration.ProgramDataMigrationPaths(
        program_dir=Path(program_dir),
        data_dir=Path(data_dir),
        user_files=globals()["_LEGACY_USER_FILES"],
        user_dirs=globals()["_LEGACY_USER_DIRS"],
    )
    operations = _program_data_migration.ProgramDataMigrationOperations(
        copy_file=globals()["shutil"].copy2,
        replace_file=globals()["os"].replace,
        process_id=globals()["os"].getpid,
        thread_id=globals()["threading"].get_ident,
        now=lambda: globals()["datetime"].now(),
    )
    return _program_data_migration.migrate_legacy_program_data(
        paths,
        operations,
    )


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
    return _character_storage.migrate_legacy_selections(
        cfg,
        _character_storage_operations(),
    )

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
    """기존 호출 이름을 유지하면서 전송 직전 레퍼런스 조립을 위임한다."""
    return _prepare_runtime_references(
        cfg,
        token,
        include_refs=include_refs,
        prepare_vibes=prepare_vibes,
        prepare_char_refs=prepare_char_refs,
        info=log.info,
        warn=log.warning,
    )


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
BOORUS = _catalog_search.BOORUS
DANBOORU_MIRRORS = _catalog_search.DANBOORU_MIRRORS
DANBOORU_SFW_MIRROR = _catalog_search.DANBOORU_SFW_MIRROR
BOORU_AUTH_HELP = _catalog_search.BOORU_AUTH_HELP
NAI_RENAMED_TAGS = _catalog_search.NAI_RENAMED_TAGS

# 검색 간격과 판정 캐시는 프로세스에서 공유하되, 저장·통신 의존성은 호출 때 연결한다.
_BOORU_KEYS = {}
_BOORU_LAST = [0.0]
_BOORU_LOCK = threading.Lock()
_TAGV_CACHE = {}


def _catalog_search_paths():
    return _catalog_search.CatalogSearchPaths(settings_file=SETTINGS_FILE)


def _catalog_search_state():
    return _catalog_search.CatalogSearchState(
        booru_keys=_BOORU_KEYS,
        booru_last=_BOORU_LAST,
        booru_lock=_BOORU_LOCK,
        tag_cache=_TAGV_CACHE,
    )


def _catalog_search_operations():
    """현재 HTTP·시간·로그 객체를 주입해 기존 APP monkeypatch 계약을 보존한다."""
    return _catalog_search.CatalogSearchOperations(
        request_get=requests.get,
        request_errors=(requests.exceptions.RequestException,),
        clock=time.time,
        sleep=time.sleep,
        log_info=log.info,
        log_warning=log.warning,
        user_agent=BOORU_UA,
    )


def booru_creds(site):
    return _catalog_search.booru_creds(
        _catalog_search_paths(),
        _catalog_search_state(),
        site,
    )


def _booru_throttle(gap=1.0):
    return _catalog_search.booru_throttle(
        _catalog_search_state(),
        _catalog_search_operations(),
        gap,
    )


def search_booru(site="danbooru", tags="", page=1, limit=40):
    return _catalog_search.search_booru(
        _catalog_search_paths(),
        _catalog_search_state(),
        _catalog_search_operations(),
        site,
        tags,
        page,
        limit,
        credentials=booru_creds,
        throttle=_booru_throttle,
    )


def _nai_tag_key(raw):
    return _catalog_search.nai_tag_key(raw)


def nai_renamed_tag(raw):
    return _catalog_search.nai_renamed_tag(raw)


def _tagv_norm(raw):
    return _catalog_search.tagv_norm(raw)


def _tags_json_at(endpoint, params):
    return _catalog_search.tags_json_at(
        _catalog_search_state(),
        _catalog_search_operations(),
        endpoint,
        params,
        throttle=_booru_throttle,
    )


def _tags_json(params):
    return _catalog_search.tags_json(
        _catalog_search_state(),
        _catalog_search_operations(),
        params,
        fetch_at=_tags_json_at,
    )


def verify_tags(text, low=100):
    return _catalog_search.verify_tags(
        _catalog_search_state(),
        _catalog_search_operations(),
        text,
        low,
        fetch_tags=_tags_json,
        fetch_at=_tags_json_at,
    )

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
STYLE_BUNDLE_SETTING_KEYS = _style_store.STYLE_SETTING_KEYS


def _style_value(record, *names):
    for name in names:
        if record.get(name) is not None:
            return record.get(name)
    return None


def _style_store_paths():
    return _style_store.StyleStorePaths(
        style_file=STYLE_FILE,
        transaction_root=STYLE_FILE.parent.parent,
    )


def _style_store_operations():
    """현재 저장·모델·Undo 경계를 호출 때 주입해 기존 patch 계약을 보존한다."""
    return _style_store.StyleStoreOperations(
        transaction=shared_data_transaction,
        lock=_STYLE_TX_LOCK,
        load_rows=load_combos,
        atomic_write_json=atomic_write_json,
        normalize_model=model_id_from_metadata,
        forget_caches=forget_collection_caches,
        record_import_batch=record_import_batch,
    )


def canonical_style_settings(record):
    return _style_store.canonical_style_settings(
        _style_store_operations(),
        record,
    )


def style_bundle_signature(record):
    return _style_store.style_bundle_signature(
        _style_store_operations(),
        record,
    )

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
    return _style_store.merge_style_evidence(existing, incoming)

# 작가 태그는 낱개가 아니라 묶음이 기본이다. `1.7::artist:a::` `.9::artist:b::`
# `0.6::artist:a, artist:b::`(한 가중치가 여럿에 걸림) 모두 순서·가중치를 지켜 읽는다.
def _artist_workspace_operations():
    """현재 난수·태그 결합 함수를 주입해 seed와 APP patch 계약을 보존한다."""
    return _artist_workspace.ArtistWorkspaceOperations(
        seeded_random=random.Random,
        system_random=random.SystemRandom,
        join_tags=_join_tags,
    )


def parse_artist_combo(text):
    return _artist_workspace.parse_artist_combo(text)


def compose_artist_workspace(rows, mode="custom", curve_start=1.2,
                             curve_end=0.8, seed=""):
    return _artist_workspace.compose_artist_workspace(
        _artist_workspace_operations(),
        rows,
        mode,
        curve_start,
        curve_end,
        seed,
    )


def artist_workspace_request(data):
    return _artist_workspace.artist_workspace_request(
        _artist_workspace_operations(),
        data,
    )

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


def add_style(rec, import_info=None, return_detail=False):
    return _style_store.add_style(
        _style_store_paths(),
        _style_store_operations(),
        rec,
        import_info,
        return_detail,
    )

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


LIBRARY_REVIEW_FILE = BASE_DIR / "수집" / "자료정리.json"
_LIBRARY_REVIEW_LOCK = threading.RLock()
LIBRARY_REVIEW_STATUSES = {"pending", "reviewed", "hold"}


def _library_catalog_paths():
    return _library_catalog.LibraryCatalogPaths(
        review_file=LIBRARY_REVIEW_FILE,
        review_schema="nais-library-review/v1",
        review_statuses=frozenset(LIBRARY_REVIEW_STATUSES),
    )


def _library_catalog_state():
    return _library_catalog.LibraryCatalogState(
        combo_cache=_COMBOS,
        style_sorts=STYLE_SORTS,
    )


def _library_catalog_operations():
    """현재 자료 공급자와 저장 경계를 호출 때 주입해 기존 patch 계약을 보존한다."""
    return _library_catalog.LibraryCatalogOperations(
        load_combos=load_combos,
        load_ratings=load_ratings,
        style_rating=style_rating,
        list_settings=list_settings,
        list_styles=list_styles,
        load_recipes=load_recipes,
        comparison_runs=comparison_runs,
        load_json=load_json_recover,
        atomic_write_json=atomic_write_json,
        now=datetime.now,
        review_lock=_LIBRARY_REVIEW_LOCK,
        warning=log.warning,
    )


def search_combos(q="", limit=40, offset=0, tab="", source="", sort="", seeded="",
                  rating=""):
    return _library_catalog.search_combos(
        _library_catalog_state(),
        _library_catalog_operations(),
        q,
        limit,
        offset,
        tab,
        source,
        sort,
        seeded,
        rating,
    )


def load_library_review(strict=False):
    return _library_catalog.load_library_review(
        _library_catalog_paths(),
        _library_catalog_operations(),
        strict,
    )


def library_review_revision(data):
    return _library_catalog.library_review_revision(data)


def normalize_library_labels(value):
    return _library_catalog.normalize_library_labels(value)


def organize_library_items(request):
    return _library_catalog.organize_library_items(
        _library_catalog_paths(),
        _library_catalog_operations(),
        request,
    )


def search_library(cfg, spec, q="", kind="", source="", limit=100, offset=0,
                   review="", label=""):
    return _library_catalog.search_library(
        _library_catalog_paths(),
        _library_catalog_operations(),
        cfg,
        spec,
        q,
        kind,
        source,
        limit,
        offset,
        review,
        label,
    )

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
def _datapack_paths():
    """자료팩 서비스가 쓸 현재 프로필 경로를 호출 시점에 조립한다."""
    return _datapack_store.DatapackPaths(
        base_dir=BASE_DIR,
        style_file=STYLE_FILE,
        recipe_file=RECIPE_FILE,
        combo_file=COMBO_FILE,
        image_cache=IMG_CACHE,
        tag_dir=TAG_DIR,
        builder_file=BUILDER_FILE,
        spec_file=SPEC_FILE,
        options_file=OPTIONS_FILE,
        settings_dir=SETTINGS_DIR,
        character_dir=CHAR_DIR,
    )


def _datapack_operations():
    """원자 저장과 캐릭터 동기화를 현재 전역 구현에 늦게 연결한다."""
    return _datapack_store.DatapackOperations(
        transaction=shared_data_transaction,
        atomic_write_bytes=globals()["_atomic_write_bytes"],
        atomic_write_json=globals()["atomic_write_json"],
        load_json=globals()["load_json_recover"],
        recoverable_remove=globals()["recoverable_remove"],
        row_digest=globals()["_style_row_digest"],
        character_signature=globals()["character_bundle_signature"],
        delete_character_files=globals()["delete_char_files"],
        sync_character_files=globals()["sync_chars_to_files"],
        save_config=globals()["save_config"],
        forget_caches=globals()["forget_collection_caches"],
        pack_queue=globals()["pack_import_queue"],
        summarize_queue=globals()["summarize_restore_queue"],
        warning=log.warning,
    )


def _datapack_lists():
    return _datapack_store.datapack_lists(_datapack_paths())


def _datapack_dirs():
    return _datapack_store.datapack_dirs(_datapack_paths())


def _datapack_whole_files():
    return _datapack_store.datapack_whole_files(_datapack_paths())


def _pack_rel(name):
    return _datapack_store.pack_rel(name)


def _read_rows(raw):
    return _datapack_store.read_rows(raw)


def _row_key(item, key):
    return _datapack_store.row_key(item, key)


def _datapack_match_key(item, primary):
    return _datapack_store.datapack_match_key(item, primary)


def _merge_list_json(path, incoming, key, overwrite=False, replace_keys=None):
    return _datapack_store.merge_list_json(
        _datapack_operations(), path, incoming, key,
        overwrite=overwrite, replace_keys=replace_keys)


def _say_counts(counts):
    return _datapack_store.say_counts(counts)


def _content_image_name(name, raw):
    return _datapack_store.content_image_name(name, raw)


def _rewrite_local_image_refs(value, renamed):
    return _datapack_store.rewrite_local_image_refs(value, renamed)

_LOCAL_IMAGE_LOCK = threading.RLock()
_LOCAL_IMAGE_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}


def _local_image_paths():
    return _local_image_store.LocalImagePaths(
        base_dir=BASE_DIR,
        image_cache=IMG_CACHE,
        image_suffixes=tuple(sorted(_LOCAL_IMAGE_SUFFIXES)),
        record_dir_name="이미지무결성기록",
        journal_schema="nais-local-image-normalize/v1",
    )


def _local_image_operations():
    """현재 원자 저장·트랜잭션·시간 함수를 주입해 기존 patch 계약을 보존한다."""
    return _local_image_store.LocalImageOperations(
        transaction=shared_data_transaction,
        lock=_LOCAL_IMAGE_LOCK,
        atomic_write_bytes=_atomic_write_bytes,
        atomic_write_json=atomic_write_json,
        forget_caches=forget_collection_caches,
        now=datetime.now,
        unix_time=time.time,
        random_bytes=os.urandom,
        replace_file=os.replace,
    )


def _collect_local_refs(value, found):
    return _local_image_store.collect_local_refs(value, found)


def _local_image_audit(include_private=False):
    return _local_image_store._local_image_audit(
        _local_image_paths(),
        include_private,
    )


def local_image_integrity():
    return _local_image_store.local_image_integrity(
        _local_image_paths(),
    )


def _local_image_record_dir(batch):
    return _local_image_store.local_image_record_dir(
        _local_image_paths(),
        batch,
    )


def normalize_local_image_refs(expected_fingerprint=""):
    return _local_image_store.normalize_local_image_refs(
        _local_image_paths(),
        _local_image_operations(),
        expected_fingerprint,
    )


def rollback_local_image_normalize(batch):
    return _local_image_store.rollback_local_image_normalize(
        _local_image_paths(),
        _local_image_operations(),
        batch,
    )

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
    return _datapack_store.pack_log_path(_datapack_paths())


def load_pack_log():
    return _datapack_store.load_pack_log(
        _datapack_paths(), _datapack_operations())


def save_pack_log(rows):
    return _datapack_store.save_pack_log(
        _datapack_paths(), _datapack_operations(), rows)


def record_import_batch(batch):
    return _datapack_store.record_import_batch(
        _datapack_paths(), _datapack_operations(), batch)

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


def _metadata_candidate_paths():
    return _metadata_candidate_store.MetadataCandidatePaths(
        base_dir=BASE_DIR,
    )


def _metadata_candidate_operations():
    """현재 감사 singleton과 복원·그림체 저장 경계를 호출 때 주입해 patch를 보존한다."""
    return _metadata_candidate_store.MetadataCandidateOperations(
        adapter_for_paths=lambda _paths: metadata_audit_adapter(),
        extract_nai_metadata=extract_nai_metadata,
        nai_json_metadata=_nai_json_metadata,
        prompt_parts=_prompt_parts,
        param_keys=tuple(PARAM_KEYS),
        image_inspect_queue=image_inspect_queue,
        redact_diagnostic_text=redact_diagnostic_text,
        parse_artist_combo=parse_artist_combo,
        style_asset_from_record=style_asset_from_record,
        add_style=add_style,
    )


def metadata_audit_candidate(body, *, include_raw=False):
    return _metadata_candidate_store.metadata_audit_candidate(
        _metadata_candidate_paths(),
        _metadata_candidate_operations(),
        body,
        include_raw=include_raw,
    )


def metadata_audit_save_candidate(body):
    return _metadata_candidate_store.metadata_audit_save_candidate(
        _metadata_candidate_paths(),
        _metadata_candidate_operations(),
        body,
    )

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
    return _datapack_store.validate_datapack_manifest(
        _datapack_paths(), archive, schema=DATAPACK_SCHEMA)


def _datapack_conflict_id(archive_sha, logical, key, current, incoming):
    return _datapack_store.datapack_conflict_id(
        _datapack_operations(), archive_sha, logical, key,
        current, incoming)


def _datapack_character_destination(raw, fallback):
    return _datapack_store.datapack_character_destination(
        _datapack_paths(), _datapack_operations(), raw, fallback)


def preview_datapack_bytes(data, filename=""):
    return _datapack_store.preview_datapack_bytes(
        _datapack_paths(), _datapack_operations(), data, filename,
        schema=DATAPACK_SCHEMA)


def import_datapack_bytes(
    data, filename="", overwrite=False, selected_conflicts=None,
    expected_diff="",
):
    return _datapack_store.import_datapack_bytes(
        _datapack_paths(), _datapack_operations(), data, filename,
        overwrite, selected_conflicts, expected_diff,
        schema=DATAPACK_SCHEMA)


def pack_log_brief():
    return _datapack_store.pack_log_brief(
        _datapack_paths(), _datapack_operations())


def undo_datapack(batch_id, cfg=None):
    return _datapack_store.undo_datapack(
        _datapack_paths(), _datapack_operations(), batch_id, cfg)

# ══ 내 자료 전체 백업 ═════════════════════════════════════════════════
BACKUP_SCHEMA = "nais-user-backup/v1"
BACKUP_SECRET_KEYS = {"token", "booru_keys", "out_dir"}


def _user_backup_paths():
    return _user_backup_store.UserBackupPaths(
        base_dir=BASE_DIR,
        profile_dir=PROFILE_DIR,
        schema=BACKUP_SCHEMA,
        journal_schema="nais-restore-journal/v1",
        journal_dir_name="복원기록",
    )


def _user_backup_operations():
    """현재 복원·원자 저장 경계를 호출 때 주입해 기존 patch와 롤백 순서를 보존한다."""
    return _user_backup_store.UserBackupOperations(
        transaction=shared_data_transaction,
        atomic_write_bytes=_atomic_write_bytes,
        atomic_write_json=atomic_write_json,
        load_settings=load_settings_recover,
        rollback=rollback_user_backup,
        after_restore=forget_collection_caches,
        now=datetime.now,
        random_bytes=os.urandom,
    )


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


def _backup_diff_plan(blob):
    return _user_backup_store.backup_diff_plan(
        _user_backup_paths(),
        _user_backup_operations(),
        blob,
    )

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


def restore_user_backup(blob, expected_sha="", selected=None, expected_diff=""):
    return _user_backup_store.restore_user_backup(
        _user_backup_paths(),
        _user_backup_operations(),
        blob,
        expected_sha,
        selected,
        expected_diff,
    )

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
COMPARE_MODE_LABELS = _comparison_planning.COMPARE_MODE_LABELS
COMPARE_MAX_JOBS = _comparison_planning.COMPARE_MAX_JOBS
COMPARE_SELECTED_AXES = _comparison_planning.COMPARE_SELECTED_AXES
COMPARE_RECIPE_SETTING_KEYS = STYLE_BUNDLE_SETTING_KEYS


def _comparison_operations():
    """비교 계획이 쓰는 저장·세팅 경계를 호출 시점의 구현에 연결한다."""
    return _comparison_planning.ComparisonPlanningOperations(
        load_combos=globals()["load_combos"],
        load_spec=globals()["load_spec"],
        list_styles=globals()["list_styles"],
        style_bundle_signature=globals()["style_bundle_signature"],
        load_asset_config=globals()["load_asset_config"],
        compute_pending=globals()["compute_pending"],
        setting_reference_config=globals()["setting_reference_config"],
        character_resource_config=globals()["character_resource_config"],
        characters_resource_config=globals()["characters_resource_config"],
        inherited_blueprint=globals()["inherited_blueprint"],
        recipe_setting_keys=COMPARE_RECIPE_SETTING_KEYS,
        max_characters=MAX_CHARS,
    )


def _comparison_id(prefix, *parts):
    return _comparison_planning.legacy_comparison_id(prefix, *parts)


def comparison_styles(spec=None):
    return _comparison_planning.comparison_styles(
        _comparison_operations(), spec)


def _comparison_character_prompt(item):
    return _comparison_planning._comparison_character_prompt(item)


def comparison_characters(cfg):
    return _comparison_planning.comparison_characters(cfg)


def _setting_runtime_operations():
    """현재 세팅·캐릭터·이름 경계를 호출 때 주입해 APP patch를 보존한다."""
    return _setting_runtime.SettingRuntimeOperations(
        comparison_characters=globals()["comparison_characters"],
        derive_catalog=globals()["derive_setting_catalog"],
        safe_name=globals()["_safe_name"],
        setting_state=globals()["setting_state"],
    )


def setting_cast_members(cfg, state):
    return _setting_runtime.setting_cast_members(
        _setting_runtime_operations(),
        cfg,
        state,
    )



def _compare_bool(value, default=False):
    return _comparison_planning._compare_bool(value, default)


def normalize_comparison_selection(value):
    return _comparison_planning.normalize_comparison_selection(value)


def normalize_comparison_options(raw, cfg):
    return _comparison_planning.normalize_comparison_options(raw, cfg)


def comparison_style_config(cfg, style, options):
    return _comparison_planning.comparison_style_config(cfg, style, options)


def comparison_sources(cfg, spec=None):
    return _comparison_planning.comparison_sources(
        _comparison_operations(), cfg, spec)


def comparison_settings(cfg):
    return _comparison_planning.comparison_settings(cfg)


def comparison_catalog(cfg, spec=None):
    return _comparison_planning.comparison_catalog(
        _comparison_operations(), cfg, spec)


def _comparison_selected_sources(styles, characters, settings, selection):
    return _comparison_planning._comparison_selected_sources(
        styles, characters, settings, selection)


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
    return _comparison_planning._comparison_selected_cfg(
        _comparison_operations(), cfg, material)


def _selected_comparison_leaf_seed(
    options, runtime_base_seed, seed_index, leaf_index, canonical_seed,
):
    return _comparison_planning._selected_comparison_leaf_seed(
        options, runtime_base_seed, seed_index, leaf_index, canonical_seed)


def iter_selected_comparison_jobs(
    cfg, plan, styles, chars, settings=None, runtime_base_seed=None,
):
    return _comparison_planning.iter_selected_comparison_jobs(
        _comparison_operations(), cfg, plan, styles, chars,
        settings=settings, runtime_base_seed=runtime_base_seed)


def comparison_selected_job_values(cfg, plan, job):
    return _comparison_planning.comparison_selected_job_values(
        _comparison_operations(), cfg, plan, job)


def comparison_selected_plan(
    cfg, options, styles, chars, settings, opus=None,
):
    return _comparison_planning.comparison_selected_plan(
        _comparison_operations(), cfg, options, styles, chars, settings,
        opus=opus, job_values=globals()["comparison_selected_job_values"])


def _comparison_character_setting_slot(character):
    return _comparison_planning._comparison_character_setting_slot(character)


def _comparison_character_setting_cfg(cfg, setting, character):
    return _comparison_planning._comparison_character_setting_cfg(
        cfg, setting, character)


def _comparison_character_setting_scene_character(character):
    return _comparison_planning._comparison_character_setting_scene_character(
        character)


def iter_character_setting_jobs(cfg, plan, chars, settings=None):
    return _comparison_planning.iter_character_setting_jobs(
        _comparison_operations(), cfg, plan, chars, settings=settings)


def comparison_character_setting_job_values(cfg, plan, job):
    return _comparison_planning.comparison_character_setting_job_values(
        _comparison_operations(), cfg, plan, job)


def comparison_character_setting_plan(cfg, options, chars, opus=None):
    return _comparison_planning.comparison_character_setting_plan(
        _comparison_operations(), cfg, options, chars, opus=opus,
        job_values=globals()["comparison_character_setting_job_values"])


def comparison_plan(cfg, raw, spec=None, opus=None):
    return _comparison_planning.comparison_plan(
        _comparison_operations(), cfg, raw, spec=spec, opus=opus,
        selected_job_values=globals()["comparison_selected_job_values"],
        character_setting_job_values=(
            globals()["comparison_character_setting_job_values"]),
    )


def comparison_signature(cfg, plan, styles, chars):
    return _comparison_planning.comparison_signature(
        _comparison_operations(), cfg, plan, styles, chars)


def iter_comparison_jobs(cfg, plan, styles, chars):
    return _comparison_planning.iter_comparison_jobs(
        cfg, plan, styles, chars)


def comparison_job_values(cfg, plan, job):
    return _comparison_planning.comparison_job_values(
        _comparison_operations(), cfg, plan, job,
        selected_job_values=globals()["comparison_selected_job_values"],
        character_setting_job_values=(
            globals()["comparison_character_setting_job_values"]),
    )


def comparison_job_recipe_snapshot(
    cfg, plan, job, used, base, negative, people, centers, seed,
):
    return _comparison_planning.comparison_job_recipe_snapshot(
        _comparison_operations(), cfg, plan, job, used, base, negative,
        people, centers, seed)


def comparison_recipe_context(cfg, plan, styles, chars):
    return _comparison_planning.comparison_recipe_context(
        _comparison_operations(), cfg, plan, styles, chars)

def _generation_execution_operations():
    """세팅 생성의 계산·재시도·저장 의존성을 호출 시점에 연결한다."""
    step = _generation_step.GenerationStepOperations(
        character_resource_config=globals()["character_resource_config"],
        setting_reference_config=globals()["setting_reference_config"],
        build_scene=globals()["build_scene"],
        seed_for=globals()["seed_for"],
        join_tags=globals()["_join_tags"],
        setting_scene_people=globals()["setting_scene_people"],
        with_position_mode=globals()["with_position_mode"],
        with_centers=globals()["with_centers"],
    )
    retry = _generation_retry.GenerationRetryOperations(
        pace_gate=globals()["pace_gate"],
        pace_complete=globals()["pace_complete"],
        call_nai_api=globals()["call_nai_api"],
        warning=globals()["log"].warning,
        error=globals()["log"].error,
        critical=globals()["log"].critical,
    )
    commit = _generation_commit.GenerationCommitOperations(
        save_image=globals()["save_with_meta"],
        output_format=globals()["out_format"],
        output_clean_args=globals()["_ocargs"],
        output_clean=globals()["out_clean"],
        task_fingerprint=globals()["generation_task_fingerprint"],
        record_job_result=globals()["record_job_result"],
        output_root=globals()["out_root"],
        make_progress_record=globals()["make_progress_record"],
        progress_item_key=globals()["progress_item_key"],
        bump_daily=globals()["bump_daily"],
        daily_count=globals()["daily_count"],
        save_state=globals()["save_state"],
        warning=globals()["log"].warning,
    )
    return _generation_execution.GenerationExecutionOperations(
        step=step,
        retry=retry,
        commit=commit,
        load_state=globals()["load_state"],
        save_state=globals()["save_state"],
        fixed_seed=globals()["fixed_seed"],
        daily_count=globals()["daily_count"],
        daily_cap=DAILY_CAP,
        load_asset_config=globals()["load_asset_config"],
        context_fingerprint=globals()["generation_context_fingerprint"],
        compute_pending=globals()["compute_pending"],
        progress_record_valid=globals()["progress_record_valid"],
        progress_record_path=globals()["progress_record_path"],
        pace=globals()["pace"],
        output_sub=globals()["out_sub"],
        runtime_params=globals()["runtime_generation_params"],
        random_seed=lambda: globals()["random"].randint(0, 2**32 - 1),
        random_uniform=globals()["random"].uniform,
        info=globals()["log"].info,
        warning=globals()["log"].warning,
        error=globals()["log"].error,
    )


def _generation_handler_operations():
    """생성 HTTP handler의 Job·NAI·저장 의존성을 호출 시점에 연결한다."""
    return _generation_handlers.GenerationHandlerOperations(
        common_job_store=globals()["common_job_store"],
        make_job_command=globals()["make_job_command"],
        transition_job=globals()["transition_job"],
        activate_comparison_run=globals()["activate_comparison_run"],
        retry_job=globals()["retry_job"],
        reconcile_job=globals()["reconcile_job"],
        inherited_blueprint=globals()["inherited_blueprint"],
        single_generation_material=globals()[
            "single_generation_legacy_material"
        ],
        characters_resource_config=globals()["characters_resource_config"],
        pace_gate=globals()["pace_gate"],
        runtime_generation_params=globals()["runtime_generation_params"],
        load_state=globals()["load_state"],
        call_nai_api=globals()["call_nai_api"],
        with_centers=globals()["with_centers"],
        pace_complete=globals()["pace_complete"],
        output_subdir=globals()["out_sub"],
        output_format=globals()["out_format"],
        output_clean_args=globals()["out_clean"],
        save_with_meta=globals()["save_with_meta"],
        output_root=globals()["out_root"],
        record_job_result=globals()["record_job_result"],
        bump_daily=globals()["bump_daily"],
        save_state=globals()["save_state"],
        start_daemon=lambda target: globals()["threading"].Thread(
            target=target, daemon=True
        ).start(),
        error=globals()["log"].error,
        random_seed=globals()["random"].randint,
        reference_inset_canvas=globals()["reference_inset_canvas"],
        character_asset_from_record=globals()[
            "character_asset_from_legacy_record"
        ],
        variation_plan_material=globals()[
            "variation_plan_to_legacy_payload_material"
        ],
        slot_prompt=globals()["slot_prompt"],
        active_people=globals()["active_people"],
        now=lambda: globals()["datetime"].now(),
        extract_metadata=globals()["extract_nai_metadata"],
        model_id_from_metadata=globals()["model_id_from_metadata"],
        normalize_position_mode=globals()["normalize_position_mode"],
        scene_mode_pending=globals()["scene_mode_pending"],
        daily_count=globals()["daily_count"],
        safe_name=globals()["_safe_name"],
        progress_record_path=globals()["progress_record_path"],
        join_tags=globals()["_join_tags"],
        seed_for=globals()["seed_for"],
        available_output_path=globals()["available_output_path"],
        warning=globals()["log"].warning,
    )


def _image_tool_operations():
    """이미지 도구의 저장·NAI·계보 의존성을 호출 시점에 연결한다."""
    return _image_tool_handlers.ImageToolOperations(
        vibe_dir=globals()["VIBE_DIR"],
        shared_data_transaction=globals()["shared_data_transaction"],
        vibe_paths=globals()["vibe_paths"],
        save_config=globals()["save_config"],
        prepare_vibes=globals()["prepare_vibes"],
        recoverable_remove=globals()["recoverable_remove"],
        director_tools=globals()["DIRECTOR_TOOLS"],
        call_upscale=globals()["call_upscale"],
        call_director=globals()["call_director"],
        inherited_blueprint=globals()["inherited_blueprint"],
        output_sub=globals()["out_sub"],
        record_job_result=globals()["record_job_result"],
        output_root=globals()["out_root"],
        info=globals()["log"].info,
        warning=globals()["log"].warning,
    )


def _collection_handler_operations():
    """단건 복원·변형 저장의 기존 데이터 경계를 호출 시점에 연결한다."""
    return _collection_handlers.CollectionHandlerOperations(
        output_root=globals()["out_root"],
        character_asset_from_legacy_record=globals()[
            "character_asset_from_legacy_record"
        ],
        accept_variation=globals()["accept_variation"],
        approved_variation_candidates=globals()[
            "approved_proposal_to_legacy_candidates"
        ],
        apply_variation_candidates=globals()[
            "apply_character_variation_candidates"
        ],
        local_import_image=globals()["_local_import_image"],
        sync_chars_to_files=globals()["sync_chars_to_files"],
        save_config=globals()["save_config"],
        extract_nai_metadata=globals()["extract_nai_metadata"],
        parse_artist_combo=globals()["parse_artist_combo"],
        model_id_from_metadata=globals()["model_id_from_metadata"],
        split_uc_preset=globals()["split_uc_preset"],
        restore_quality_prompt=globals()["restore_quality_prompt"],
        image_cache=globals()["IMG_CACHE"],
        atomic_write_bytes=globals()["_atomic_write_bytes"],
        evidence_from_image_record=globals()["evidence_from_image_record"],
        style_asset_from_record=globals()["style_asset_from_record"],
        add_style=globals()["add_style"],
        image_inspect_queue=globals()["image_inspect_queue"],
        summarize_restore_queue=globals()["summarize_restore_queue"],
        warning=globals()["log"].warning,
    )


def _setting_transaction():
    """기존 세팅 파일의 프로세스·스레드 잠금을 같은 순서로 묶는다."""
    stack = ExitStack()
    stack.enter_context(
        globals()["shared_data_transaction"](
            globals()["SETTINGS_DIR"].parent
        )
    )
    stack.enter_context(globals()["_SETTING_TX_LOCK"])
    return stack


def _settings_handler_operations():
    """프로젝트·설정·씬 저장 의존성을 호출 시점에 연결한다."""
    return _settings_handlers.SettingsHandlerOperations(
        config_transaction=lambda: globals()["shared_data_transaction"](
            globals()["CHAR_DIR"].parent
        ),
        setting_transaction=_setting_transaction,
        default_config=globals()["DEFAULT_CONFIG"],
        normalize_projects=globals()["normalize_projects"],
        normalize_link=globals()["normalize_link"],
        project_by_id=globals()["project_by_id"],
        generation_blueprint=globals()["generation_blueprint"],
        blueprint_common=globals()["blueprint_common"],
        fingerprint_blueprint=globals()["fingerprint_blueprint"],
        resolve_inheritance=globals()["resolve_inheritance"],
        materialize_blueprint=globals()[
            "materialize_blueprint_into_config"
        ],
        save_config=globals()["save_config"],
        validate_config_value=globals()["validate_config_value"],
        sync_chars_to_files=globals()["sync_chars_to_files"],
        sync_blueprint_overrides=globals()[
            "sync_blueprint_local_overrides"
        ],
        delete_char_files=globals()["delete_char_files"],
        setting_path=globals()["setting_path"],
        load_json=globals()["load_json_recover"],
        setting_revision=globals()["setting_content_revision"],
        normalize_resolution=globals()["normalize_resolution"],
        normalize_centers=globals()["normalize_scene_centers"],
        normalize_reference_ids=globals()[
            "normalize_scene_reference_ids"
        ],
        atomic_write_json=globals()["atomic_write_json"],
        warning=globals()["log"].warning,
        info=globals()["log"].info,
    )


def _comparison_handler_operations():
    """비교 실행·승격의 기존 계획·계보·worker 의존성을 연결한다."""
    return _comparison_handlers.ComparisonHandlerOperations(
        result_promotion_records=globals()["_result_promotion_records"],
        legacy_lineage_unavailable=globals()[
            "LegacyPromotionLineageUnavailable"
        ],
        promote_assets=globals()["promote_comparison_recipe_assets"],
        append_promotion_ledger=globals()[
            "_append_result_promotion_ledger"
        ],
        redact_diagnostic_text=globals()["redact_diagnostic_text"],
        comparison_plan=globals()["comparison_plan"],
        inherited_blueprint=globals()["inherited_blueprint"],
        comparison_characters=globals()["comparison_characters"],
        comparison_sources=globals()["comparison_sources"],
        run_comparison=globals()["_run_comparison"],
        start_daemon=lambda target: globals()["threading"].Thread(
            target=target,
            daemon=True,
        ).start(),
        error=globals()["log"].error,
    )


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
    return _character_storage.migrate_legacy(
        _character_storage_paths(),
        _character_storage_operations(),
        cfg,
        light_preset=LIGHT_PRESET,
        positions=POSITIONS,
    )

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
GROUP_ORDER = list(_character_storage.GROUP_ORDER)
CHARACTER_ASSET_OPTIONAL_FIELDS = _character_storage.CHARACTER_ASSET_OPTIONAL_FIELDS


def _character_storage_paths():
    return _character_storage.CharacterStoragePaths(
        legacy_settings_file=LEGACY_SETTINGS_FILE,
        settings_file=SETTINGS_FILE,
        character_dir=CHAR_DIR,
    )


def _character_random_id():
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=8)
    )


def _character_storage_operations():
    """현재 파일·복구·ID 경계를 호출 때 주입해 기존 patch와 저장 순서를 보존한다."""
    return _character_storage.CharacterStorageOperations(
        read_legacy_settings=_read_legacy_txt,
        setting_path=setting_path,
        load_json=load_json_recover,
        atomic_write_json=atomic_write_json,
        recoverable_remove=recoverable_remove,
        random_id=_character_random_id,
        log_info=log.info,
        log_warning=log.warning,
    )


def _safe_name(name):
    return _character_storage.safe_name(name)


def _compose_from_groups(groups):
    return _character_storage.compose_from_groups(groups)


def _folder_by_name(cfg, name, parent_id=None):
    return _character_storage.folder_by_name(
        cfg,
        _character_storage_operations(),
        name,
        parent_id,
    )


def _read_char_documents(paths):
    return _character_storage.read_character_documents(
        _character_storage_operations(),
        paths,
    )


def import_char_files(cfg):
    return _character_storage.import_char_files(
        _character_storage_paths(),
        _character_storage_operations(),
        cfg,
    )


def sync_chars_to_files(cfg):
    return _character_storage.sync_chars_to_files(
        _character_storage_paths(),
        _character_storage_operations(),
        cfg,
    )

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


def load_asset_config(cfg):
    """레거시 세팅 저장소와 순수 compiler를 연결한다."""
    return _compile_asset_config(
        cfg,
        list_settings=list_settings,
        derive_catalog=derive_setting_catalog,
        warn=log.warning,
    )


# ═══════════════ NAI API ═══════════════

def _ref_fields(p):
    """이전 단일 파일 호출부를 위한 호환 어댑터."""
    return reference_fields(p)


def _variety_sigma_value(model, width, height, variety, p):
    """이전 단일 파일 호출부를 위한 호환 어댑터."""
    return variety_sigma_value(
        model, width, height, variety, p, warn=log.warning)


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


def _i2i_fields(i2i, action, seed):
    """이전 단일 파일 호출부를 위한 호환 어댑터."""
    return image_to_image_fields(i2i, action, seed)


def call_nai_api(
    token,
    base_prompt,
    negative,
    width,
    height,
    *,
    scale=5.5,
    cfg_rescale=0.56,
    steps=28,
    sampler="k_euler_ancestral",
    scheduler="karras",
    uc_preset=3,
    seed=None,
    variety=False,
    params=None,
    chars=None,
):
    """기존 호출 계약을 유지하며 NAI 통신 서비스에 런타임 의존성을 연결한다."""
    return request_nai_image(
        token,
        base_prompt,
        negative,
        width,
        height,
        scale=scale,
        cfg_rescale=cfg_rescale,
        steps=steps,
        sampler=sampler,
        scheduler=scheduler,
        uc_preset=uc_preset,
        seed=seed,
        variety=variety,
        params=params,
        chars=chars,
        fragment_resolver=resolve_fragments,
        blocked_artist_finder=blocked_artists_in,
        endpoint=NAI_API_URL,
        max_characters=MAX_CHARS,
    )


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


def save_picks(d):
    cleaned = normalize_picks(d)
    atomic_write_json(PICKS_FILE, cleaned, indent=1)
    return cleaned


def apply_evaluation_action(data):
    """레거시 저장 위치를 평가 workflow에 연결하는 호환 어댑터."""
    return apply_evaluation_action_workflow(
        data,
        lock=_JSON_IO_LOCK,
        load_picks=load_picks,
        save_picks=save_picks,
        project_evaluations=project_legacy_evaluations,
        blind_event=blind_match_event,
        fixed_board_event=fixed_board_event,
        lifecycle_event=lifecycle_event,
        promotion_event=promotion_event,
        append_events=append_evaluation_events,
    )


TRASH_DIR_NAME = ".NAI-휴지통"
_DIR_COUNT_CACHE = {}   # 경로 → (재귀 이미지 수, 기록 시각)


def _output_lifecycle_paths():
    """레거시 상수와 서비스의 파일·휴지통 계약을 한곳에서 연결한다."""
    return _output_lifecycle.OutputLifecyclePaths(
        trash_dir_name=TRASH_DIR_NAME,
        image_extensions=IMG_EXT,
        trash_schema="nais-output-trash/v2",
        directory_count_ttl=30.0,
    )


def _output_lifecycle_operations():
    """호출 시점의 저장·시간 의존성을 주입해 기존 monkeypatch 계약을 보존한다."""
    return _output_lifecycle.OutputLifecycleOperations(
        output_root=out_root,
        atomic_write_json=atomic_write_json,
        load_json=load_json_recover,
        load_picks=load_picks,
        save_picks=save_picks,
        picks_lock=_JSON_IO_LOCK,
        project_evaluations=project_legacy_evaluations,
        move_file=shutil.move,
        now=datetime.now,
        uuid4=uuid.uuid4,
        clock=time.time,
        directory_count_cache=_DIR_COUNT_CACHE,
        warning=log.warning,
    )


def _path_is_inside(path, root):
    return _output_lifecycle.path_is_inside(path, root)


def output_file_for_preview(cfg, rel):
    return _output_lifecycle.output_file_for_preview(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        cfg,
        rel,
    )


def trash_output_files(cfg, targets, keep=()):
    return _output_lifecycle.trash_output_files(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        cfg,
        targets,
        keep,
    )


def restore_trash_batch(cfg, batch_id):
    return _output_lifecycle.restore_trash_batch(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        cfg,
        batch_id,
    )


def list_trash_batches(cfg):
    return _output_lifecycle.list_trash_batches(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        cfg,
    )


def _dir_img_count(p):
    return _output_lifecycle.dir_image_count(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        p,
    )


def comparison_manifests_for_output_dir(cfg, sub):
    return _output_lifecycle.comparison_manifests_for_output_dir(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        cfg,
        sub,
    )


def list_output(sub="", cfg=None, limit=0, offset=0, only_pick=False, only_fav=False):
    return _output_lifecycle.list_output(
        _output_lifecycle_paths(),
        _output_lifecycle_operations(),
        sub,
        cfg,
        limit,
        offset,
        only_pick,
        only_fav,
    )

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
    """레거시 조각 저장소와 공통 prompt bridge를 연결한다."""
    return resolve_legacy_fragments(
        texts,
        list_fragments() if frags is None else frags,
        counters=counters,
        rng=rng,
        max_depth=FRAG_MAX_DEPTH,
    )


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


def validate_config_value(key, value, current):
    """레거시 기본 pace 값을 공통 검증 서비스에 연결한다."""
    return _validate_config_value(
        key,
        value,
        current,
        pace_default=PACE_DEFAULT,
    )


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


def _public_style_import_operations():
    """현재 메타·모델·UC·품질·작가 파서를 호출 때 주입해 APP patch를 보존한다."""
    return _public_style_import.PublicStyleImportOperations(
        extract_metadata=extract_nai_metadata,
        model_id=model_id_from_metadata,
        split_uc_preset=split_uc_preset,
        restore_quality_prompt=restore_quality_prompt,
        parse_artist_combo=parse_artist_combo,
    )


def _style_record_from_public_image(data, content_type, article):
    return _public_style_import.style_record_from_public_image(
        _public_style_import_operations(),
        data,
        content_type,
        article,
    )

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

    def handle_blueprint_project(self, body):
        return _settings_handlers.handle_blueprint_project(
            self,
            {"body": body},
            _settings_handler_operations(),
        )

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
        data = json.loads(body or b"{}")
        return _generation_handlers.handle_job_command(
            self, data, _generation_handler_operations())

    def handle_generate_one(self):
        return _generation_handlers.handle_generate_one(
            self, None, _generation_handler_operations())

    def handle_i2i(self, body):
        try:
            data = json.loads(body or b"{}")
        except Exception as error:
            return {"ok": False, "error": str(error)}
        return _generation_handlers.handle_i2i(
            self, data, _generation_handler_operations())

    def handle_character_variation_save(self, body):
        return _collection_handlers.handle_character_variation_save(
            self,
            {"body": body},
            _collection_handler_operations(),
        )

    def handle_regen(self, body):
        try:
            data = json.loads(body or b"{}")
        except Exception as error:
            return {"ok": False, "error": str(error)}
        return _generation_handlers.handle_regen(
            self, data, _generation_handler_operations())

    def handle_scene_run(self):
        return _generation_handlers.handle_scene_run(
            self, None, _generation_handler_operations())

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
        return _comparison_handlers.handle_compare_promote(
            self,
            {"body": body},
            _comparison_handler_operations(),
        )

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
        return _comparison_handlers.handle_compare_run(
            self,
            {"body": body},
            _comparison_handler_operations(),
        )

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
        return _collection_handlers.handle_inspect(
            self,
            {
                "body": body,
                "filename": filename,
                "save_flag": save_flag,
            },
            _collection_handler_operations(),
        )

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
        return _image_tool_handlers.handle_ref_add(
            self,
            {"body": body, "kind": kind, "filename": filename},
            _image_tool_operations(),
        )

    def handle_ref_save(self, body):
        return _image_tool_handlers.handle_ref_save(
            self,
            {"body": body},
            _image_tool_operations(),
        )

    def handle_director(
        self,
        body,
        tool,
        prompt="",
        defry="0",
        scale="4",
        filename="",
    ):
        return _image_tool_handlers.handle_director(
            self,
            {
                "body": body,
                "tool": tool,
                "prompt": prompt,
                "defry": defry,
                "scale": scale,
                "filename": filename,
            },
            _image_tool_operations(),
        )

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

    def handle_save(self, body):
        return _settings_handlers.handle_save(
            self,
            {"body": body},
            _settings_handler_operations(),
        )

    def handle_scene_save(self, body):
        return _settings_handlers.handle_scene_save(
            self,
            {"body": body},
            _settings_handler_operations(),
        )

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

        def late_bound(name):
            return lambda *args, **kwargs: globals()[name](*args, **kwargs)

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
            vibe_dir=lambda: VIBE_DIR,
            mime=lambda: MIME,
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
            preview_backup=late_bound("preview_user_backup"),
            restore_backup=late_bound("restore_user_backup"),
            rollback_backup=late_bound("rollback_user_backup"),
            load_settings=lambda: load_settings_recover(SETTINGS_FILE),
            default_config=lambda: DEFAULT_CONFIG,
            migrate_selections=late_bound("migrate_legacy_selections"),
            migrate_slots=late_bound("migrate_char_slots"),
            load_spec=late_bound("load_spec"),
            options=lambda: OPTIONS,
            load_options=late_bound("load_options"),
            normalize_local_images=late_bound("normalize_local_image_refs"),
            rollback_local_images=late_bound("rollback_local_image_normalize"),
            rebuild_data_index=late_bound("rebuild_data_index"),
            metadata_control=late_bound("metadata_audit_control"),
            metadata_candidate=late_bound("metadata_audit_candidate"),
            metadata_save=late_bound("metadata_audit_save_candidate"),
            image_batch_queue=late_bound("image_batch_queue"),
            summarize_queue=late_bound("summarize_restore_queue"),
        )
        collection_post = CollectionPostOperations(
            preview_pack=late_bound("preview_datapack_bytes"),
            import_pack=late_bound("import_datapack_bytes"),
            pack_queue=late_bound("pack_import_queue"),
            summarize_queue=late_bound("summarize_restore_queue"),
            forget_caches=late_bound("forget_collection_caches"),
            load_spec=late_bound("load_spec"),
            options=lambda: OPTIONS,
            load_options=late_bound("load_options"),
            public_start=lambda payload: PUBLIC_COLLECTION.start(payload),
            public_retry=lambda payload: PUBLIC_COLLECTION.retry_failed(payload),
            public_control=lambda action: PUBLIC_COLLECTION.control(action),
            undo_pack=late_bound("undo_datapack"),
            import_settings=late_bound("import_settings_bytes"),
            resource_import=server.handle_resource_import,
            reference_add=server.handle_ref_add,
            reference_save=server.handle_ref_save,
        )
        catalog_post = CatalogPostOperations(
            style_save=server.handle_style_save,
            normalization_save=server.handle_norm_save,
            verify_tags=late_bound("verify_tags"),
            organize_library=late_bound("organize_library_items"),
            delete_styles=late_bound("delete_styles"),
            restore_styles=late_bound("restore_styles"),
        )
        evaluation_post = EvaluationPostOperations(
            artist_workspace=late_bound("artist_workspace_request"),
            load_ratings=late_bound("load_ratings"),
            rate_artist=late_bound("rate_artist"),
            apply_evaluation=late_bound("apply_evaluation_action"),
            picks_lock=_JSON_IO_LOCK,
            load_picks=late_bound("load_picks"),
            save_picks=late_bound("save_picks"),
            trash_outputs=late_bound("trash_output_files"),
            restore_trash=late_bound("restore_trash_batch"),
            output_subdir=late_bound("out_sub"),
            atomic_write=late_bound("_atomic_write_bytes"),
            strip_and_save=late_bound("strip_and_save"),
        )
        fragment_post = FragmentPostOperations(
            fragment_dir=lambda: FRAG_DIR,
            save_fragment=late_bound("save_fragment"),
            list_fragments=late_bound("list_fragments"),
            recoverable_remove=late_bound("recoverable_remove"),
            load_state=late_bound("load_state"),
            save_state=late_bound("save_state"),
            import_fragments=late_bound("import_fragments_bytes"),
            reroll_components=late_bound("reroll_legacy_components"),
            resolve_prompt=late_bound("resolve_legacy_prompt"),
            sequence_text=late_bound("legacy_sequence_text"),
            resolve_fragments=late_bound("resolve_fragments"),
            random_factory=random.Random,
        )
        settings_post = SettingsPostOperations(
            duplicate_scene_undo=late_bound("undo_duplicate_setting_scene"),
            duplicate_scene=late_bound("duplicate_setting_scene"),
            scene_save=server.handle_scene_save,
            option_item=server.handle_option_item,
            role_save=server.handle_role_save,
            sceneset_save=server.handle_sceneset_save,
            load_asset_config=late_bound("load_asset_config"),
            setting_state=late_bound("setting_state"),
            cast_members=late_bound("setting_cast_members"),
            slot_prompt=late_bound("slot_prompt"),
            character_run=late_bound("character_run_from_group"),
            build_scene=late_bound("build_scene"),
            reference_config=late_bound("setting_reference_config"),
            scene_people=late_bound("setting_scene_people"),
            seed_for=late_bound("seed_for"),
            load_state=late_bound("load_state"),
            normalize_prompt=late_bound("normalize_prompt"),
            join_tags=late_bound("_join_tags"),
            token_count=late_bound("nai_tokens"),
            save_scenes=late_bound("save_scenes"),
            new_setting=late_bound("new_setting"),
            add_set=late_bound("setting_add_set"),
            save_meta=late_bound("setting_meta_save"),
            renumber=late_bound("setting_renumber"),
            delete_setting=late_bound("setting_delete"),
            duplicate_group=late_bound("duplicate_setting_group"),
            log_warning=log.warning,
        )
        generation_post = GenerationPostOperations(
            activate_comparison=late_bound("activate_comparison_run"),
            compare_rerun=server.handle_compare_rerun,
            comparison_recipe=late_bound("comparison_recipe_for_output"),
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
            fetch_balance=late_bound("fetch_anlas_balance"),
            vibe_paths=late_bound("vibe_paths"),
            load_asset_config=late_bound("load_asset_config"),
            compute_pending=late_bound("compute_pending"),
            estimate_anlas=late_bound("anlas_estimate"),
            finalize_tokens=late_bound("finalized_token_texts"),
            token_count=late_bound("nai_tokens"),
            tokens_exact=late_bound("tokens_exact"),
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
    return _setting_runtime.compute_pending(
        _setting_runtime_operations(),
        cfg,
        acfg,
        done_this_run,
        skip_set,
    )


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


def _comparison_runtime_operations():
    """비교 manifest·재실행 의존성을 호출 시점의 APP 경계에 연결한다."""
    return _comparison_runtime.ComparisonRuntimeOperations(
        output_root=globals()["out_root"],
        comparison_signature=globals()["comparison_signature"],
        load_progress=globals()["_comparison_progress_load"],
        load_json=globals()["load_json_recover"],
        path_is_inside=globals()["_path_is_inside"],
        output_file_for_preview=globals()["output_file_for_preview"],
        output_subdir=globals()["out_sub"],
        now=lambda: globals()["datetime"].now(),
        random_bytes=globals()["os"].urandom,
        now_text=lambda: globals()["time"].strftime("%Y-%m-%d %H:%M:%S"),
        random_seed=globals()["random"].randint,
        comparison_recipe_context=globals()["comparison_recipe_context"],
        save_progress=globals()["_comparison_progress_save"],
        info=globals()["log"].info,
        warning=globals()["log"].warning,
        selected_comparison_record=globals()["_selected_comparison_record"],
        regenerate_execution_material=globals()[
            "regenerate_legacy_execution_material"
        ],
        selected_config=globals()["_comparison_selected_cfg"],
        load_asset_config=globals()["load_asset_config"],
        compute_pending=globals()["compute_pending"],
        selected_job_values=globals()["comparison_selected_job_values"],
        generation_blueprint=globals()["generation_blueprint"],
        pace_gate=globals()["pace_gate"],
        runtime_generation_params=globals()["runtime_generation_params"],
        call_nai_api=globals()["call_nai_api"],
        with_centers=globals()["with_centers"],
        pace_complete=globals()["pace_complete"],
        output_format=globals()["out_format"],
        available_output_path=globals()["available_output_path"],
        output_clean_args=globals()["out_clean"],
        save_with_meta=globals()["save_with_meta"],
        record_job_result=globals()["record_job_result"],
        uuid4=globals()["uuid"].uuid4,
        comparison_job_recipe_snapshot=globals()[
            "comparison_job_recipe_snapshot"
        ],
        load_state=globals()["load_state"],
        bump_daily=globals()["bump_daily"],
        save_state=globals()["save_state"],
    )


def _comparison_execution_operations():
    """비교 큐·NAI·결과 저장 의존성을 호출 시점의 APP 경계에 연결한다."""
    return _comparison_execution.ComparisonExecutionOperations(
        progress_start=globals()["_comparison_progress_start"],
        save_progress=globals()["_comparison_progress_save"],
        link_job_ancestor=globals()["link_job_ancestor"],
        record_job_result=globals()["record_job_result"],
        output_file_for_preview=globals()["output_file_for_preview"],
        redact_diagnostic_text=globals()["redact_diagnostic_text"],
        warning=globals()["log"].warning,
        info=globals()["log"].info,
        error=globals()["log"].error,
        iter_character_setting_jobs=globals()[
            "iter_character_setting_jobs"
        ],
        iter_selected_jobs=globals()["iter_selected_comparison_jobs"],
        iter_comparison_jobs=globals()["iter_comparison_jobs"],
        comparison_job_values=globals()["comparison_job_values"],
        comparison_job_recipe_snapshot=globals()[
            "comparison_job_recipe_snapshot"
        ],
        generation_blueprint=globals()["generation_blueprint"],
        safe_name=globals()["_safe_name"],
        available_output_path=globals()["available_output_path"],
        output_format=globals()["out_format"],
        output_root=globals()["out_root"],
        output_clean_args=globals()["out_clean"],
        pace=globals()["pace"],
        pace_gate=globals()["pace_gate"],
        pace_complete=globals()["pace_complete"],
        runtime_generation_params=globals()["runtime_generation_params"],
        call_nai_api=globals()["call_nai_api"],
        with_centers=globals()["with_centers"],
        save_with_meta=globals()["save_with_meta"],
        load_state=globals()["load_state"],
        daily_count=globals()["daily_count"],
        bump_daily=globals()["bump_daily"],
        save_state=globals()["save_state"],
        now_text=lambda: globals()["time"].strftime("%Y-%m-%d %H:%M:%S"),
        rate_limit_error=globals()["RateLimitError"],
        account_errors=(
            globals()["AccountBannedError"],
            globals()["AuthError"],
        ),
        api_error=globals()["APIError"],
    )


def comparison_runs(cfg, limit=50):
    return _comparison_runtime.comparison_runs(
        _comparison_runtime_operations(),
        cfg,
        limit,
    )


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


def _comparison_promotion_paths():
    """현재 프로필의 승격 저장 경로를 호출 시점에 조립한다."""
    return _comparison_promotion.ComparisonPromotionPaths(
        base_dir=BASE_DIR,
        style_dir=STYLE_DIR,
        character_dir=CHAR_DIR,
        settings_file=SETTINGS_FILE,
    )


def _comparison_promotion_operations(include_recipe_adapter=False):
    """현재 비교·평가·저장 경계를 늦게 주입해 APP patch를 보존한다."""
    return _comparison_promotion.ComparisonPromotionOperations(
        transaction=shared_data_transaction,
        comparison_result_context=globals()["_comparison_result_context"],
        default_config=globals()["DEFAULT_CONFIG"],
        comparison_style_config=globals()["comparison_style_config"],
        recipe_setting_keys=COMPARE_RECIPE_SETTING_KEYS,
        slot_prompt=globals()["slot_prompt"],
        comparison_result_evaluation=globals()[
            "_comparison_result_evaluation"
        ],
        build_result_promotion=globals()["build_result_promotion"],
        style_bundle_signature=globals()["style_bundle_signature"],
        character_bundle_signature=globals()[
            "character_bundle_signature"
        ],
        list_styles=globals()["list_styles"],
        load_spec=globals()["load_spec"],
        load_combos=globals()["load_combos"],
        unique_library_name=globals()["_unique_library_name"],
        save_style_file=globals()["save_style_file"],
        safe_name=globals()["_safe_name"],
        record_import_batch=globals()["record_import_batch"],
        sync_characters_to_files=globals()["sync_chars_to_files"],
        save_config=globals()["save_config"],
        random_character_id=lambda: "".join(random.choices(
            string.ascii_lowercase + string.digits, k=8)),
        recipe_for_output=(
            globals()["comparison_recipe_for_output"]
            if include_recipe_adapter
            else None
        ),
    )


def comparison_recipe_for_output(cfg, rel):
    return _comparison_promotion.comparison_recipe_for_output(
        _comparison_promotion_operations(),
        cfg,
        rel,
    )


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


LegacyPromotionLineageUnavailable = (
    _comparison_promotion.LegacyPromotionLineageUnavailable
)


def _result_promotion_records(
    cfg, rel, kind, name="", resolved_names=None,
):
    return _comparison_promotion.result_promotion_records(
        _comparison_promotion_operations(include_recipe_adapter=True),
        cfg,
        rel,
        kind,
        name,
        resolved_names,
    )


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


def promote_comparison_recipe_assets(cfg, rel, kind, name="", spec=None):
    return _comparison_promotion.promote_comparison_recipe_assets(
        _comparison_promotion_paths(),
        _comparison_promotion_operations(include_recipe_adapter=True),
        cfg,
        rel,
        kind,
        name,
        spec,
    )


def _comparison_progress_save(progress, folder):
    """재개용 기록과 사람이 읽을 결과 폴더 manifest를 함께 원자 저장한다."""
    atomic_write_json(COMPARE_PROGRESS_FILE, progress, indent=1)
    atomic_write_json(folder / "manifest.json", progress, indent=1)


def _comparison_progress_start(cfg, plan, styles, chars):
    return _comparison_runtime.comparison_progress_start(
        _comparison_runtime_operations(),
        cfg,
        plan,
        styles,
        chars,
    )


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
    return _comparison_runtime.rerun_selected_comparison(
        _comparison_runtime_operations(),
        server,
        cfg,
        rel,
    )


def _run_comparison(server, cfg, plan, styles, chars):
    return _comparison_execution.run_comparison(
        _comparison_execution_operations(),
        server,
        cfg,
        plan,
        styles,
        chars,
    )

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
    return _generation_execution.run_generation(
        _generation_execution_operations(),
        server,
        cfg_snapshot,
    )

if __name__ == "__main__":
    main()
