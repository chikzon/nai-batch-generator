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
from src.nai_studio.runtime.application_context import (
    PATHS as CONTEXT_PATHS,
    SERVICES as CONTEXT_SERVICES,
    SETTINGS as CONTEXT_SETTINGS,
    STORAGE as CONTEXT_STORAGE,
    WiringRegistry,
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
from src.nai_studio.runtime import file_transaction as _file_transaction
from src.nai_studio.compat import studio_wiring as _studio_wiring
from src.nai_studio.runtime import program_entry as _program_entry
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
    artist_rating_store as _artist_rating_store,
    artist_workspace as _artist_workspace,
    builder_handlers as _builder_handlers,
    catalog_search as _catalog_search,
    character_storage as _character_storage,
    collection_handlers as _collection_handlers,
    comparison_execution as _comparison_execution,
    comparison_handlers as _comparison_handlers,
    comparison_planning as _comparison_planning,
    comparison_promotion as _comparison_promotion,
    comparison_runtime as _comparison_runtime,
    data_inventory as _data_inventory,
    datapack_store as _datapack_store,
    generation_commit as _generation_commit,
    generation_execution as _generation_execution,
    generation_handlers as _generation_handlers,
    generation_pacing as _generation_pacing,
    generation_progress as _generation_progress,
    generation_retry as _generation_retry,
    generation_step as _generation_step,
    fragment_workflow as _fragment_workflow,
    image_tool_handlers as _image_tool_handlers,
    library_catalog as _library_catalog,
    local_image_store as _local_image_store,
    management_state as _management_state,
    metadata_candidate_store as _metadata_candidate_store,
    nai_auxiliary as _nai_auxiliary,
    output_lifecycle as _output_lifecycle,
    program_data_migration as _program_data_migration,
    public_style_import as _public_style_import,
    reference_preparation as _reference_preparation,
    remote_image_cache as _remote_image_cache,
    resource_bridge as _resource_bridge,
    setting_runtime as _setting_runtime,
    setting_store as _setting_store,
    settings_handlers as _settings_handlers,
    style_store as _style_store,
    tag_catalog as _tag_catalog,
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
    finalized_token_texts as _finalized_token_texts,
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
from src.nai_studio.web import (
    app_wiring as _app_wiring,
    page_renderer as _page_renderer,
    server_runtime as _server_runtime,
)
from src.nai_studio.web.http_server import (
    ConfigRequestHandler,
    start_http_server,
)
from src.nai_studio.web.page_template import PAGE_TEMPLATE

sys.stdout.reconfigure(encoding="utf-8")

# 프로그램 파일과 사용자 자료는 생명주기가 다르다. 설치 프로그램을 제거해도 설정·
# 캐릭터·세팅·수집물·생성물이 함께 사라지면 안 된다. 묶인 실행본은 기본적으로
# %LOCALAPPDATA%\NAI배치생성기\데이터 를 쓰고, 코드·CSS·토크나이저는 exe 옆에서 읽는다.
# 소스 실행은 개발 중인 기존 자료 위치를 바꾸지 않도록 예전처럼 소스 폴더를 쓴다.
PROGRAM_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
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


def _build_application_context():
    """현재 프로필의 핵심 의존성을 값과 지연 provider로 구분해 고정한다."""
    registry = WiringRegistry()
    for name, provider in (
        ("program_dir", lambda: PROGRAM_DIR),
        ("data_dir", lambda: BASE_DIR),
        ("profile_dir", lambda: PROFILE_DIR),
        ("settings_file", lambda: SETTINGS_FILE),
        ("default_output_root", lambda: OUTPUT_BASE),
        ("ui_dir", lambda: UI_DIR),
    ):
        registry.bind_provider(
            "application",
            CONTEXT_PATHS,
            name,
            provider,
        )
    registry.bind_provider(
        "application",
        CONTEXT_SETTINGS,
        "profile",
        lambda: PROFILE,
    )
    for name, value in (
        ("load_json", load_json_recover),
        ("atomic_write_json", atomic_write_json),
        ("transaction", shared_data_transaction),
    ):
        registry.bind_value(
            "application",
            CONTEXT_STORAGE,
            name,
            value,
        )
    for name, value in (
        ("setting_store", _setting_store),
        ("nai_request", request_nai_image),
        ("server_runtime", _server_runtime),
    ):
        registry.bind_value(
            "application",
            CONTEXT_SERVICES,
            name,
            value,
        )
    return registry.freeze()


APPLICATION_CONTEXT = _build_application_context()


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
    return APPLICATION_CONTEXT.category("application").path(
        "default_output_root"
    )


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
    return _generation_pacing.normalize_pace(cfg, PACE_DEFAULT)
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
    return _setting_store.list_presets(
        _setting_store_paths(),
        _setting_store_operations(),
    )


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


def _resource_import_paths():
    return _resource_bridge.LegacyResourceImportPaths(
        vibe_dir=VIBE_DIR,
        transaction_root=VIBE_DIR.parent.parent,
    )


def _resource_import_operations():
    return _resource_bridge.LegacyResourceImportOperations(
        transaction=shared_data_transaction,
        atomic_write_bytes=_atomic_write_bytes,
        save_config=save_config,
    )


def _reference_operations():
    """현재 프로필 파일·HTTP·원자 저장을 Reference 서비스에 연결한다."""
    return _reference_preparation.ReferenceOperations(
        vibe_dir=VIBE_DIR,
        settings_file=SETTINGS_FILE,
        default_config=DEFAULT_CONFIG,
        vibe_paths=globals()["vibe_paths"],
        encode_vibe=globals()["encode_vibe"],
        atomic_write_text=globals()["atomic_write_text"],
        transaction=globals()["shared_data_transaction"],
        load_json=globals()["load_json_recover"],
        save_config=globals()["save_config"],
        http_post=globals()["requests"].post,
        warning=globals()["log"].warning,
        info=globals()["log"].info,
    )


def encode_vibe(token, image_bytes, information_extracted=0.7,
                model="nai-diffusion-4-5-full"):
    return _reference_preparation.encode_vibe(
        _reference_operations(),
        ENCODE_VIBE_URL,
        token,
        image_bytes,
        information_extracted,
        model,
    )


def prepare_vibes(cfg, token):
    return _reference_preparation.prepare_vibes(
        _reference_operations(),
        cfg,
        token,
    )


# ★ 캐릭터 레퍼런스 참조 이미지는 **이 세 캔버스 중 하나**여야 한다.
#   다른 크기를 보내면 NAI 가 400 "Error encoding v4 director references" 를 준다.
#   (512·832×1216·1024² 전부 실패했고 이 셋만 통과했다 — 실측)
#   비율을 지켜 넣고 남는 곳은 검게 채운다(레터박스).
CR_CANVAS = _reference_preparation.REFERENCE_CANVASES


def _cr_canvas_for(w, h):
    return _reference_preparation.reference_canvas(w, h)


def letterbox_ref(raw):
    return _reference_preparation.letterbox_reference(raw)


def prepare_char_refs(cfg):
    return _reference_preparation.prepare_character_references(
        _reference_operations(),
        cfg,
        letterbox=globals()["letterbox_ref"],
    )


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
    return _reference_preparation.image_png_base64(
        img_bytes_or_image
    )


def _last_from_zip(content):
    return _nai_auxiliary.last_zip_item(content)


def _auxiliary_operations():
    """보조 NAI 호출의 HTTP·이미지 변환·로그를 늦게 연결한다."""
    return _nai_auxiliary.AuxiliaryOperations(
        http_post=globals()["requests"].post,
        http_get=globals()["requests"].get,
        image_png_base64=globals()["_b64_png"],
        info=globals()["log"].info,
        warning=globals()["log"].warning,
    )


def call_director(token, image_bytes, method, prompt=None, defry=0):
    return _nai_auxiliary.call_director(
        _auxiliary_operations(),
        AUGMENT_URL,
        token,
        image_bytes,
        method,
        prompt,
        defry,
    )


def call_upscale(token, image_bytes, scale=4):
    return _nai_auxiliary.call_upscale(
        _auxiliary_operations(),
        UPSCALE_URLS,
        token,
        image_bytes,
        scale,
    )


def fetch_anlas_balance(token):
    return _nai_auxiliary.fetch_anlas_balance(
        _auxiliary_operations(),
        token,
    )


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
    return _remote_image_cache.trim_remote_cache(
        _remote_image_cache_paths(),
        _remote_image_cache_operations(),
    )


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
    return _remote_image_cache.headers_for(
        url,
        HOST_HEADERS,
        DEFAULT_HEADERS,
    )


def fetch_cached_image(url):
    """예시 이미지를 (bytes, content-type)으로 반환.
    local:파일명 → 수집/이미지캐시 에서 바로 읽음. http(s) → 받아서 캐시."""
    return _remote_image_cache.fetch_cached_image(
        _remote_image_cache_paths(),
        _remote_image_cache_operations(),
        url,
        HOST_HEADERS,
        DEFAULT_HEADERS,
        note_image_origin,
    )


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


def _remote_image_cache_paths():
    """patch 가능한 레거시 경로·상한·MIME 계약을 서비스에 늦게 연결한다."""
    return _remote_image_cache.RemoteImageCachePaths(
        image_cache=IMG_CACHE,
        remote_cache=REMOTE_CACHE,
        origin_file=_img_origin_path(),
        cap_mb=REMOTE_CAP_MB,
        mime=MIME,
    )


def _remote_image_cache_operations():
    """현재 HTTP·원자 저장·복구·로그 의존성을 서비스에 주입한다."""
    return _remote_image_cache.RemoteImageCacheOperations(
        http_get=requests.get,
        load_json=load_json_recover,
        atomic_write_bytes=_atomic_write_bytes,
        atomic_write_json=atomic_write_json,
        warning=log.warning,
        info=log.info,
        origin_lock=_ORIGIN_LOCK,
    )


def load_image_origins():
    return _remote_image_cache.load_image_origins(
        _remote_image_cache_paths(),
        _remote_image_cache_operations(),
    )


def note_image_origin(url, data, pack=""):
    """받아온 그림의 **원본 주소 · 내용 해시 · 저장 이름**을 적어 둔다.
    나중에 원격↔로컬을 되돌리거나, 주소가 달라도 같은 그림을 묶는 근거가 된다."""
    return _remote_image_cache.note_image_origin(
        _remote_image_cache_paths(),
        _remote_image_cache_operations(),
        url,
        data,
        pack,
    )


def image_origin_stats():
    """장부 요약 — 같은 그림을 가리키는 주소가 여럿인 것이 몇 건인가."""
    return _remote_image_cache.image_origin_stats(
        _remote_image_cache_paths(),
        _remote_image_cache_operations(),
    )


_WARM_POOL = None
_WARM_SEEN = set()
_WARM_LOCK = threading.Lock()


def prewarm_images(items, n=48):
    """목록 응답에 딸린 예시 이미지를 미리 받아 캐시에 채운다.
    브라우저가 <img>를 요청할 땐 이미 디스크에 있어 즉시 응답된다."""
    global _WARM_POOL
    from concurrent.futures import ThreadPoolExecutor

    _WARM_POOL = _remote_image_cache.prewarm_images(
        items,
        n,
        seen=_WARM_SEEN,
        pool=_WARM_POOL,
        lock=_WARM_LOCK,
        executor_factory=ThreadPoolExecutor,
        fetch_image=fetch_cached_image,
        trim_cache=trim_remote_cache,
    )


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
        trash_file=_trashed_style_path(),
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
        load_json=load_json_recover,
        deletion_stamp=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
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


def _style_catalog_paths():
    return _library_catalog.StyleCatalogPaths(
        style_file=STYLE_FILE,
        combo_file=COMBO_FILE,
    )


def _style_catalog_operations():
    return _library_catalog.StyleCatalogOperations(
        load_json=load_json_recover,
        info=log.info,
        warning=log.warning,
        lock=_COMBOS_LOCK,
    )


def load_combos():
    return _library_catalog.load_style_catalog(
        _style_catalog_paths(),
        _style_catalog_operations(),
        _COMBOS,
    )


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
    return _style_store.load_styles(
        _style_store_paths(),
        _style_store_operations(),
    )


def _write_styles_raw(rows):
    return _style_store.write_styles(
        _style_store_paths(),
        _style_store_operations(),
        rows,
    )


def delete_styles(ids):
    """고른 그림체를 지운다 → 지운그림체.json 으로 옮긴다."""
    return _style_store.delete_styles(
        _style_store_paths(),
        _style_store_operations(),
        ids,
    )


def _delete_styles_locked(ids):
    return _style_store._delete_styles(
        _style_store_paths(),
        _style_store_operations(),
        ids,
    )


def restore_styles(ids=None):
    """지운 것을 되살린다. ids 가 없으면 **가장 최근에 지운 묶음** 전부."""
    return _style_store.restore_styles(
        _style_store_paths(),
        _style_store_operations(),
        ids,
    )


def _restore_styles_locked(ids=None):
    return _style_store._restore_styles(
        _style_store_paths(),
        _style_store_operations(),
        ids,
    )


def _combo_fingerprint(r):
    """같은 그림체인지 보는 지문 — 작가 조합을 **가중치·순서 빼고** 본다.
    id 는 출처마다 다르게 붙으므로(`arca-3297` · `dorang-…`) id 로는 못 잡는다."""
    return _style_store.combo_fingerprint(r)


def find_style_dupes():
    """같은 작가 조합인데 여러 건인 것을 묶어서 돌려준다.
    출처가 다른 자료를 합치면 반드시 생긴다 — id 가 달라 자동 병합이 못 잡는다."""
    return _style_store.find_style_dupes(
        _style_store_paths(),
        _style_store_operations(),
    )


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
    return _artist_rating_store.artist_key(name)


def _artist_rating_paths():
    return _artist_rating_store.ArtistRatingPaths(
        ratings_file=RATINGS_FILE,
    )


def _artist_rating_state():
    return _artist_rating_store.ArtistRatingState(
        cache=_RATINGS,
        lock=_RATINGS_LOCK,
    )


def _artist_rating_operations():
    """현재 저장 경계와 patch 가능한 조회·저장 함수를 서비스에 늦게 연결한다."""
    return _artist_rating_store.ArtistRatingOperations(
        transaction=shared_data_transaction,
        load_json=load_json_recover,
        atomic_write_json=atomic_write_json,
        parse_artist_combo=parse_artist_combo,
        warning=log.warning,
        current_loader=lambda: globals()["load_ratings"](),
        current_saver=lambda data: globals()["save_ratings"](data),
    )


def load_ratings():
    return _artist_rating_store.load_ratings(
        _artist_rating_paths(),
        _artist_rating_state(),
        _artist_rating_operations(),
    )


def save_ratings(d):
    return _artist_rating_store.save_ratings(
        _artist_rating_paths(),
        _artist_rating_state(),
        _artist_rating_operations(),
        d,
    )


def rate_artist(name, **fields):
    return _artist_rating_store.rate_artist(
        _artist_rating_paths(),
        _artist_rating_state(),
        _artist_rating_operations(),
        name,
        **fields,
    )


def blocked_artists_in(text):
    return _artist_rating_store.blocked_artists_in(
        _artist_rating_paths(),
        _artist_rating_state(),
        _artist_rating_operations(),
        text,
    )


def style_rating(rec, ratings=None):
    return _artist_rating_store.style_rating(
        _artist_rating_paths(),
        _artist_rating_state(),
        _artist_rating_operations(),
        rec,
        ratings,
    )


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
    return _tag_catalog.slot_of_tag(
        tag,
        cat,
        char_rules,
        style_rules,
    )


def _tag_catalog_paths():
    return _tag_catalog.TagCatalogPaths(
        tag_dir=TAG_DIR,
        cache_file=AC_CACHE_FILE,
    )


def _tag_catalog_state():
    return _tag_catalog.TagCatalogState(
        cache=_TAG_CACHE,
        lock=_TAG_LOCK,
        cache_version=AC_CACHE_VER,
    )


def _tag_catalog_operations():
    return _tag_catalog.TagCatalogOperations(
        renamed_tag=nai_renamed_tag,
        info=log.info,
        warning=log.warning,
    )


def load_tag_dict(spec):
    return _tag_catalog.load_tag_dict(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
        spec,
    )


def _load_tag_dict_inner(spec):
    return load_tag_dict(spec)


def _ac_index(spec):
    return _tag_catalog.autocomplete_index(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
        spec,
        cache_loader=lambda: globals()["_ac_cache_load"](),
        cache_saver=lambda rows, buckets, flat: globals()["_ac_cache_save"](
            rows,
            buckets,
            flat,
        ),
    )


AC_CACHE_FILE = BASE_DIR / "수집" / "태그색인.pickle"
AC_CACHE_VER = 3      # 3 = 별칭 색인 + NAI 개명 태그 교정


def _tag_fingerprint():
    return _tag_catalog.tag_fingerprint(
        _tag_catalog_paths(),
    )


def _ac_cache_load():
    return _tag_catalog.cache_load(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
    )


def _ac_cache_save(rows, buckets, flat):
    return _tag_catalog.cache_save(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
        rows,
        buckets,
        flat,
    )


def _ac_index_inner(d):
    return _tag_catalog.build_index(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
        d,
        cache_loader=lambda: globals()["_ac_cache_load"](),
        cache_saver=lambda rows, buckets, flat: globals()["_ac_cache_save"](
            rows,
            buckets,
            flat,
        ),
    )


def autocomplete_tags(spec, q, limit=12):
    return _tag_catalog.autocomplete_tags(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
        spec,
        q,
        limit,
        index=globals()["_ac_index"](spec),
    )


def search_tags(spec, kind, slot, q, limit=60):
    return _tag_catalog.search_tags(
        _tag_catalog_paths(),
        _tag_catalog_state(),
        _tag_catalog_operations(),
        spec,
        kind,
        slot,
        q,
        limit,
    )


def _builder_handler_paths():
    return _builder_handlers.BuilderHandlerPaths(
        builder_file=BUILDER_FILE,
        transaction_root=CHAR_DIR.parent,
    )


def _builder_handler_operations():
    """빌더 저장이 쓰는 기존 저장·잠금·파일 동기화 경계를 늦게 연결한다."""
    return _builder_handlers.BuilderHandlerOperations(
        load_json=globals()["load_json_recover"],
        transaction=globals()["shared_data_transaction"],
        compose_ordered=globals()["_compose_ordered"],
        save_style_file=globals()["save_style_file"],
        list_styles=globals()["list_styles"],
        random_character_id=lambda: "".join(random.choices(
            string.ascii_lowercase + string.digits,
            k=8,
        )),
        sync_chars_to_files=globals()["sync_chars_to_files"],
        save_config=globals()["save_config"],
        warning=globals()["log"].warning,
    )


def load_builder():
    return _builder_handlers.load_builder(
        _builder_handler_paths(),
        _builder_handler_operations(),
    )

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


def _setting_store_paths():
    """세팅 서비스가 현재 프로필 경로를 호출 시점에 읽게 한다."""
    return _setting_store.SettingStorePaths(
        settings_dir=SETTINGS_DIR,
        schema_dir=SCHEMA_DIR,
        preset_dir=SCENESET_DIR,
    )


def _setting_store_operations():
    """원자 저장·잠금·컴파일 규칙을 세팅 저장소에 연결한다."""
    return _setting_store.SettingStoreOperations(
        transaction=_setting_transaction,
        load_json=globals()["load_json_recover"],
        atomic_write_json=globals()["atomic_write_json"],
        recoverable_remove=globals()["recoverable_remove"],
        safe_name=globals()["_safe_name"],
        derive_catalog=globals()["derive_setting_catalog"],
        axis_specs=globals()["axis_specs"],
        ensure_schema_split=globals()["ensure_schema_split"],
        warning=globals()["log"].warning,
        info=globals()["log"].info,
    )


def ensure_settings_migration():
    return _setting_store.ensure_migration(
        _setting_store_paths(),
        _setting_store_operations(),
    )


def list_settings():
    return _setting_store.list_settings(
        _setting_store_paths(),
        _setting_store_operations(),
    )


def used_scene_nums(skip=None):
    return _setting_store.used_scene_nums(
        _setting_store_paths(),
        _setting_store_operations(),
        skip,
    )


def free_scene_block(count, skip=None, step=100):
    return _setting_store.free_scene_block(
        _setting_store_paths(),
        _setting_store_operations(),
        count,
        skip,
        step,
    )


def scene_num_clashes():
    return _setting_store.scene_num_clashes(
        _setting_store_paths(),
        _setting_store_operations(),
    )


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


def duplicate_setting_group(name, gid):
    return _setting_store.duplicate_group(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        gid,
    )


def setting_content_revision(data):
    return _setting_store.content_revision(data)


def duplicate_setting_scene(name, scene_id, expect_revision=""):
    return _setting_store.duplicate_scene(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        scene_id,
        expect_revision,
    )


def undo_duplicate_setting_scene(name, scene_id, scene_sha256,
                                 expect_revision=""):
    return _setting_store.undo_duplicate_scene(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        scene_id,
        scene_sha256,
        expect_revision,
    )


# ══════════════════════════════════════════════════════════════════════
#  세팅 빌더 — 세팅을 앱 안에서 만들고 고친다
#    세트(묶음) = 이름이 같고 단계명만 다른 씬들. 그래서 씬 이름을
#    `<세트이름> <단계명>` 으로 만들면 자동으로 한 묶음이 된다.
#    단계 수는 자유다 (묶음 안의 순서로 단계를 세므로 5장에 묶이지 않는다).
# ══════════════════════════════════════════════════════════════════════
BUILDER_MODES = _setting_store.BUILDER_MODES


def new_setting(name, mode="단독", stages=None):
    return _setting_store.create_setting(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        mode,
        stages,
    )


def setting_add_set(name, label, category="", width=832, height=1216, stages=None):
    return _setting_store.add_set(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        label,
        category,
        width,
        height,
        stages,
    )


def setting_meta_save(name, patch):
    return _setting_store.save_meta(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        patch,
    )


def setting_renumber(name, start=None):
    return _setting_store.renumber(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
        start,
    )


def setting_delete(name):
    return _setting_store.delete_setting(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
    )


def export_settings_zip(names=None):
    return _setting_store.export_settings(
        _setting_store_paths(),
        _setting_store_operations(),
        names,
    )


def import_settings_bytes(data, filename=""):
    return _setting_store.import_settings(
        _setting_store_paths(),
        _setting_store_operations(),
        data,
        filename,
    )


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


def _data_inventory_paths():
    return _data_inventory.DataInventoryPaths(
        base_dir=BASE_DIR,
        program_dir=PROGRAM_DIR,
        index_file=_data_index_path(),
        schema=DATA_INDEX_SCHEMA,
        profile=PROFILE,
    )


def _data_inventory_operations():
    return _data_inventory.DataInventoryOperations(
        load_json=load_json_recover,
        atomic_write_json=atomic_write_json,
        now=datetime.now,
        redact=redact_diagnostic_text,
        folder_queue=folder_inventory_queue,
        folder_summary=folder_inventory_summary,
        summarize_queue=summarize_restore_queue,
    )


def _load_data_index_cached():
    """큰 색인을 요청마다 다시 역직렬화하지 않고 파일 변경 때만 새로 읽는다."""
    return _data_inventory.load_data_index_cached(
        _data_inventory_paths(),
        _data_inventory_operations(),
        _DATA_INDEX_CACHE,
    )


def _iter_indexed_data_files():
    """다시 만들 수 있는 캐시·기록은 빼고 실제 자료 파일만 순회한다."""
    yield from _data_inventory.iter_indexed_data_files(
        _data_inventory_paths(),
    )


def rebuild_data_index():
    """현재 개인 자료를 파일별 SHA-256으로 다시 센다.

    색인은 원본이 아니라 파생 목록이다. 지워져도 원자료를 다시 훑어 만들 수 있다.
    """
    return _data_inventory.rebuild_data_index(
        _data_inventory_paths(),
        _data_inventory_operations(),
        _DATA_INDEX_CACHE,
    )


def data_storage_status():
    """화면용 저장 위치와 마지막 색인 요약. 토큰·프롬프트 내용은 내보내지 않는다."""
    return _data_inventory.data_storage_status(
        _data_inventory_paths(),
        _data_inventory_operations(),
        _DATA_INDEX_CACHE,
        _DATA_MIGRATION,
    )


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
    return _data_inventory.folder_inventory_page(
        _data_inventory_paths(),
        _data_inventory_operations(),
        _DATA_INDEX_CACHE,
        offset,
        limit,
    )


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
        sources=_user_backup_store.UserBackupSourcePaths(
            settings_file=SETTINGS_FILE,
            builder_file=BUILDER_FILE,
            spec_file=SPEC_FILE,
            options_file=OPTIONS_FILE,
            tag_dir=TAG_DIR,
            settings_dir=SETTINGS_DIR,
            schema_dir=SCHEMA_DIR,
            sceneset_dir=SCENESET_DIR,
            style_dir=STYLE_DIR,
            character_dir=CHAR_DIR,
            fragment_dir=FRAG_DIR,
            vibe_dir=VIBE_DIR,
            picks_file=PICKS_FILE,
            scenes_file=SCENES_FILE,
        ),
        profile_name=PROFILE,
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
        warning=log.warning,
        recoverable_remove=recoverable_remove,
        **_studio_wiring.user_backup_baseline_fields(PROFILE_DIR),
    )


def _backup_clean_settings(raw):
    return _user_backup_store.clean_settings(raw)


def _backup_sources(cfg):
    """토큰·생성물·재생성 가능한 캐시를 빼고 사용자 원본만 모은다."""
    return _user_backup_store.backup_sources(
        _user_backup_paths(),
        _user_backup_operations(),
        cfg,
    )


def export_user_backup(cfg):
    return _user_backup_store.export_user_backup(
        _user_backup_paths(),
        _user_backup_operations(),
        cfg,
    )


def _backup_safe_logical(value):
    return _user_backup_store.safe_logical(value)


def _backup_destination(logical):
    return _user_backup_store.destination(
        _user_backup_paths(),
        logical,
    )


def _backup_merge_secrets(logical, raw, target):
    return _user_backup_store.merge_secrets(
        _user_backup_operations(),
        logical,
        raw,
        target,
    )


def _backup_diff_plan(blob):
    return _user_backup_store.backup_diff_plan(
        _user_backup_paths(),
        _user_backup_operations(),
        blob,
    )

def _backup_change_public(change):
    return _user_backup_store.backup_change_public(change)


def preview_user_backup(blob):
    return _user_backup_store.preview_user_backup(
        _user_backup_paths(),
        _user_backup_operations(),
        blob,
    )


def restore_user_backup(blob, expected_sha="", selected=None, expected_diff=""):
    return _user_backup_store.restore_user_backup(
        _user_backup_paths(),
        _user_backup_operations(),
        blob,
        expected_sha,
        selected,
        expected_diff,
    )

def rollback_user_backup(batch_id):
    return _user_backup_store.rollback_user_backup(
        _user_backup_paths(),
        _user_backup_operations(),
        batch_id,
    )


def setting_path(name):
    return _setting_store.setting_path(
        _setting_store_paths(),
        _setting_store_operations(),
        name,
    )


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

def _generation_step_operations():
    return _generation_step.GenerationStepOperations(
        character_resource_config=globals()["character_resource_config"],
        setting_reference_config=globals()["setting_reference_config"],
        build_scene=globals()["build_scene"],
        seed_for=globals()["seed_for"],
        join_tags=globals()["_join_tags"],
        setting_scene_people=globals()["setting_scene_people"],
        with_position_mode=globals()["with_position_mode"],
        with_centers=globals()["with_centers"],
    )


def _generation_retry_operations():
    return _generation_retry.GenerationRetryOperations(
        pace_gate=globals()["pace_gate"],
        pace_complete=globals()["pace_complete"],
        call_nai_api=globals()["call_nai_api"],
        warning=globals()["log"].warning,
        error=globals()["log"].error,
        critical=globals()["log"].critical,
    )


def _generation_commit_operations():
    return _generation_commit.GenerationCommitOperations(
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


def _generation_execution_operations():
    """세팅 생성의 계산·재시도·저장 의존성을 호출 시점에 연결한다."""
    return _generation_execution.GenerationExecutionOperations(
        step=_generation_step_operations(),
        retry=_generation_retry_operations(),
        commit=_generation_commit_operations(),
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


def _generation_handler_run_bindings():
    return {
        "common_job_store": globals()["common_job_store"],
        "make_job_command": globals()["make_job_command"],
        "transition_job": globals()["transition_job"],
        "activate_comparison_run": globals()["activate_comparison_run"],
        "retry_job": globals()["retry_job"],
        "reconcile_job": globals()["reconcile_job"],
        "inherited_blueprint": globals()["inherited_blueprint"],
        "single_generation_material": globals()[
            "single_generation_legacy_material"],
        "characters_resource_config": globals()["characters_resource_config"],
        "start_daemon": lambda target: globals()["threading"].Thread(
            target=target, daemon=True).start(),
        "error": globals()["log"].error,
        "warning": globals()["log"].warning,
    }


def _generation_handler_nai_bindings():
    return {
        "pace_gate": globals()["pace_gate"],
        "runtime_generation_params": globals()["runtime_generation_params"],
        "load_state": globals()["load_state"],
        "call_nai_api": globals()["call_nai_api"],
        "with_centers": globals()["with_centers"],
        "pace_complete": globals()["pace_complete"],
        "output_subdir": globals()["out_sub"],
        "output_format": globals()["out_format"],
        "output_clean_args": globals()["out_clean"],
        "save_with_meta": globals()["save_with_meta"],
        "output_root": globals()["out_root"],
        "record_job_result": globals()["record_job_result"],
        "bump_daily": globals()["bump_daily"],
        "save_state": globals()["save_state"],
        "daily_count": globals()["daily_count"],
        "available_output_path": globals()["available_output_path"],
    }


def _generation_handler_image_bindings():
    return {
        "random_seed": globals()["random"].randint,
        "reference_inset_canvas": globals()["reference_inset_canvas"],
        "character_asset_from_record": globals()[
            "character_asset_from_legacy_record"],
        "variation_plan_material": globals()[
            "variation_plan_to_legacy_payload_material"],
        "slot_prompt": globals()["slot_prompt"],
        "active_people": globals()["active_people"],
        "now": lambda: globals()["datetime"].now(),
        "extract_metadata": globals()["extract_nai_metadata"],
        "model_id_from_metadata": globals()["model_id_from_metadata"],
        "normalize_position_mode": globals()["normalize_position_mode"],
        "scene_mode_pending": globals()["scene_mode_pending"],
        "safe_name": globals()["_safe_name"],
        "progress_record_path": globals()["progress_record_path"],
        "join_tags": globals()["_join_tags"],
        "seed_for": globals()["seed_for"],
    }


def _generation_handler_operations():
    """생성 HTTP handler의 의존성을 기능 묶음별로 늦게 연결한다."""
    return _generation_handlers.GenerationHandlerOperations(
        **_generation_handler_run_bindings(),
        **_generation_handler_nai_bindings(),
        **_generation_handler_image_bindings(),
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
        selected_comparison_record=globals()[
            "_selected_comparison_record"
        ],
        rerun_selected_comparison=globals()[
            "_rerun_selected_comparison"
        ],
        start_daemon=lambda target: globals()["threading"].Thread(
            target=target,
            daemon=True,
        ).start(),
        error=globals()["log"].error,
    )


def _late_bound(name):
    return lambda *args, **kwargs: globals()[name](*args, **kwargs)


def _route_catalog_bindings():
    return {
        "booru": _late_bound("search_booru"),
        "style_duplicates": _late_bound("find_style_dupes"),
        "library": _late_bound("search_library"),
        "combos": _late_bound("search_combos"),
        "recipes": _late_bound("search_recipes"),
        "prewarm": _late_bound("prewarm_images"),
        "autocomplete": _late_bound("autocomplete_tags"),
        "tags": _late_bound("search_tags"),
        "scenes": lambda cfg, ids, setting: globals()["scene_catalog"](
            cfg,
            ids,
            setting,
            setting_path=globals()["setting_path"],
            load_json=globals()["load_json_recover"],
            load_asset_config=globals()["load_asset_config"],
            content_revision=globals()["setting_content_revision"],
            normalize_refs=globals()["normalize_scene_reference_ids"],
            normalize_centers=globals()["normalize_scene_centers"],
        ),
        "comparison_catalog": _late_bound("comparison_catalog"),
        "comparison_runs": _late_bound("comparison_runs"),
        "comparison_progress": _late_bound("comparison_progress_summary"),
    }


def _route_asset_bindings():
    return {
        "vibe_dir": lambda: globals()["VIBE_DIR"],
        "mime": lambda: globals()["MIME"],
        "output_preview": _late_bound("output_file_for_preview"),
        "output_list": _late_bound("list_output"),
        "setting_thumbs": _late_bound("setting_thumbs"),
        "resource_export": lambda cfg: globals()[
            "export_legacy_resources"
        ](
            cfg,
            file_index=globals()["resource_file_index"](cfg),
        ),
        "backup_export": _late_bound("export_user_backup"),
        "fragments_export": _late_bound("export_fragments_zip"),
        "settings_export": _late_bound("export_settings_zip"),
        "cached_image": _late_bound("fetch_cached_image"),
        "diagnostics": lambda limit, errors_only: globals()[
            "diagnostic_snapshot"
        ](
            globals()["LOG_FILE"],
            limit=limit,
            errors_only=errors_only,
        ),
        "render_page": _late_bound("render_page"),
    }


def _route_recovery_bindings():
    return {
        "metadata_audit": lambda offset, limit: globals()[
            "metadata_audit_status"
        ](
            found_offset=offset,
            found_limit=limit,
        ),
        "folder_inventory": _late_bound("folder_inventory_page"),
        "trash": _late_bound("list_trash_batches"),
        "pack_log": lambda: {
            "ok": True,
            "log": globals()["pack_log_brief"](),
        },
        "public_restoration": lambda: globals()[
            "PUBLIC_COLLECTION"
        ].restoration_snapshot(),
        "public_collection": lambda: globals()[
            "PUBLIC_COLLECTION"
        ].snapshot(),
        "data_storage": _late_bound("data_storage_status"),
        "image_origins": _late_bound("image_origin_stats"),
        "local_integrity": _late_bound("local_image_integrity"),
        "preview_backup": _late_bound("preview_user_backup"),
        "restore_backup": _late_bound("restore_user_backup"),
        "rollback_backup": _late_bound("rollback_user_backup"),
        "load_settings": lambda: globals()["load_settings_recover"](
            globals()["SETTINGS_FILE"]
        ),
        "default_config": lambda: globals()["DEFAULT_CONFIG"],
        "migrate_selections": _late_bound("migrate_legacy_selections"),
        "migrate_slots": _late_bound("migrate_char_slots"),
        "load_spec": _late_bound("load_spec"),
        "options": lambda: globals()["OPTIONS"],
        "load_options": _late_bound("load_options"),
        "normalize_local_images": _late_bound(
            "normalize_local_image_refs"
        ),
        "rollback_local_images": _late_bound(
            "rollback_local_image_normalize"
        ),
        "rebuild_data_index": _late_bound("rebuild_data_index"),
        "metadata_control": _late_bound("metadata_audit_control"),
        "metadata_candidate": _late_bound("metadata_audit_candidate"),
        "metadata_save": _late_bound("metadata_audit_save_candidate"),
        "image_batch_queue": _late_bound("image_batch_queue"),
        "summarize_queue": _late_bound("summarize_restore_queue"),
    }


def _route_collection_bindings():
    return {
        "preview_pack": _late_bound("preview_datapack_bytes"),
        "import_pack": _late_bound("import_datapack_bytes"),
        "pack_queue": _late_bound("pack_import_queue"),
        "summarize_queue": _late_bound("summarize_restore_queue"),
        "forget_caches": _late_bound("forget_collection_caches"),
        "public_start": lambda payload: globals()[
            "PUBLIC_COLLECTION"
        ].start(payload),
        "public_retry": lambda payload: globals()[
            "PUBLIC_COLLECTION"
        ].retry_failed(payload),
        "public_control": lambda action: globals()[
            "PUBLIC_COLLECTION"
        ].control(action),
        "undo_pack": _late_bound("undo_datapack"),
        "import_settings": _late_bound("import_settings_bytes"),
        "verify_tags": _late_bound("verify_tags"),
        "organize_library": _late_bound("organize_library_items"),
        "delete_styles": _late_bound("delete_styles"),
        "restore_styles": _late_bound("restore_styles"),
    }


def _route_evaluation_fragment_bindings():
    return {
        "artist_workspace": _late_bound("artist_workspace_request"),
        "load_ratings": _late_bound("load_ratings"),
        "rate_artist": _late_bound("rate_artist"),
        "apply_evaluation": _late_bound("apply_evaluation_action"),
        "picks_lock": globals()["_JSON_IO_LOCK"],
        "load_picks": _late_bound("load_picks"),
        "save_picks": _late_bound("save_picks"),
        "trash_outputs": _late_bound("trash_output_files"),
        "restore_trash": _late_bound("restore_trash_batch"),
        "output_subdir": _late_bound("out_sub"),
        "atomic_write": _late_bound("_atomic_write_bytes"),
        "strip_and_save": _late_bound("strip_and_save"),
        "fragment_dir": lambda: globals()["FRAG_DIR"],
        "save_fragment": _late_bound("save_fragment"),
        "list_fragments": _late_bound("list_fragments"),
        "recoverable_remove": _late_bound("recoverable_remove"),
        "load_state": _late_bound("load_state"),
        "save_state": _late_bound("save_state"),
        "import_fragments": _late_bound("import_fragments_bytes"),
        "reroll_components": _late_bound("reroll_legacy_components"),
        "resolve_prompt": _late_bound("resolve_legacy_prompt"),
        "sequence_text": _late_bound("legacy_sequence_text"),
        "resolve_fragments": _late_bound("resolve_fragments"),
        "random_factory": globals()["random"].Random,
    }


def _route_settings_runtime_bindings():
    return {
        "duplicate_scene_undo": _late_bound(
            "undo_duplicate_setting_scene"
        ),
        "duplicate_scene": _late_bound("duplicate_setting_scene"),
        "load_asset_config": _late_bound("load_asset_config"),
        "setting_state": _late_bound("setting_state"),
        "cast_members": _late_bound("setting_cast_members"),
        "slot_prompt": _late_bound("slot_prompt"),
        "character_run": _late_bound("character_run_from_group"),
        "build_scene": _late_bound("build_scene"),
        "reference_config": _late_bound("setting_reference_config"),
        "scene_people": _late_bound("setting_scene_people"),
        "seed_for": _late_bound("seed_for"),
        "normalize_prompt": _late_bound("normalize_prompt"),
        "join_tags": _late_bound("_join_tags"),
        "token_count": _late_bound("nai_tokens"),
        "save_scenes": _late_bound("save_scenes"),
        "new_setting": _late_bound("new_setting"),
        "add_set": _late_bound("setting_add_set"),
        "save_meta": _late_bound("setting_meta_save"),
        "renumber": _late_bound("setting_renumber"),
        "delete_setting": _late_bound("setting_delete"),
        "duplicate_group": _late_bound("duplicate_setting_group"),
        "log_warning": globals()["log"].warning,
        "activate_comparison": _late_bound("activate_comparison_run"),
        "comparison_recipe": _late_bound("comparison_recipe_for_output"),
        "fetch_balance": _late_bound("fetch_anlas_balance"),
        "vibe_paths": _late_bound("vibe_paths"),
        "compute_pending": _late_bound("compute_pending"),
        "estimate_anlas": _late_bound("anlas_estimate"),
        "finalize_tokens": _late_bound("finalized_token_texts"),
        "tokens_exact": _late_bound("tokens_exact"),
    }


def _route_bindings():
    """라우트 Operations 의존성을 기능 범주별로 합친다."""
    groups = (
        _route_catalog_bindings(),
        _route_asset_bindings(),
        _route_recovery_bindings(),
        _route_collection_bindings(),
        _route_evaluation_fragment_bindings(),
        _route_settings_runtime_bindings(),
    )
    return {key: value for group in groups for key, value in group.items()}


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


def _config_initialization_operations():
    """설정 복구와 캐릭터 동기화의 기존 patch 경계를 늦게 연결한다."""
    return _management_state.ConfigInitializationOperations(
        load_settings=globals()["load_settings_recover"],
        quarantine_corrupt=globals()["quarantine_corrupt_settings"],
        migrate_legacy=globals()["_migrate_legacy"],
        ensure_settings_migration=globals()["ensure_settings_migration"],
        migrate_selections=globals()["migrate_legacy_selections"],
        migrate_char_slots=globals()["migrate_char_slots"],
        import_char_files=globals()["import_char_files"],
        sync_chars_to_files=globals()["sync_chars_to_files"],
        save_config=globals()["save_config"],
        log_critical=globals()["log"].critical,
    )


def _file_transaction_paths():
    return _file_transaction.FileTransactionPaths(root=BASE_DIR)


def _file_transaction_operations():
    return _file_transaction.FileTransactionOperations(
        transaction=globals()["shared_data_transaction"],
        atomic_write_bytes=globals()["_atomic_write_bytes"],
        atomic_write_json=globals()["atomic_write_json"],
        load_json=globals()["load_json_recover"],
        replace=globals()["os"].replace,
        info=log.info,
        warning=log.warning,
    )


def recover_pending_file_transactions():
    """기동 시 미완 파일 트랜잭션·백업 복원을 수렴시킨다."""
    notices = []
    recoveries = (
        ("파일 트랜잭션", lambda: _file_transaction.recover_file_transactions(
            _file_transaction_paths(), _file_transaction_operations())),
        ("백업 복원", lambda: _user_backup_store.recover_unfinished_restores(
            _user_backup_paths(), _user_backup_operations())),
    )
    for label, run in recoveries:
        try:
            notices.extend(run())
        except Exception as exc:  # 복구 실패가 기동을 막으면 안 된다 — journal은 남는다.
            log.warning(f"{label} 복구를 건너뜁니다: {exc}")
    return notices


def load_or_init_config():
    global STARTUP_RECOVERY_NOTICE
    transaction_notices = recover_pending_file_transactions()
    cfg, STARTUP_RECOVERY_NOTICE = _management_state.load_or_init_config(
        SETTINGS_FILE,
        DEFAULT_CONFIG,
        _config_initialization_operations(),
    )
    if STARTUP_RECOVERY_NOTICE is None and transaction_notices:
        STARTUP_RECOVERY_NOTICE = transaction_notices[0]
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


def _fragment_import_operations():
    return _fragment_workflow.FragmentImportOperations(
        fragment_dir=lambda: FRAG_DIR,
        safe_name=_safe_name,
        atomic_write_text=atomic_write_text,
        list_fragments=list_fragments,
    )


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
    return _fragment_workflow.import_fragments_bytes(
        _fragment_import_operations(),
        data,
        filename,
    )


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
    return _finalized_token_texts(
        base,
        negative,
        chars,
        char_negatives,
        cfg,
        strip_comments=globals()["strip_comment_lines"],
        load_state=globals()["load_state"],
        resolve_fragments=globals()["resolve_fragments"],
        normalize_prompt=globals()["normalize_prompt"],
        merge_quality_suffix=globals()["merge_quality_suffix"],
        merge_uc_preset=globals()["merge_uc_preset"],
    )


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


def _pacing_operations():
    """현재 상태 장부와 patch 가능한 시계를 호출 간격 서비스에 연결한다."""
    return _generation_pacing.PacingOperations(
        load_state=globals()["load_state"],
        daily_count=globals()["daily_count"],
        random_uniform=globals()["random"].uniform,
        now=globals()["time"].time,
        sleep=globals()["time"].sleep,
        last_call=globals()["_LAST_CALL"],
    )


def pace_gate(cfg, live=None, label=""):
    del label
    return _generation_pacing.wait_for_slot(
        _pacing_operations(),
        cfg,
        PACE_DEFAULT,
        live,
    )


def pace_complete():
    return _generation_pacing.mark_complete(_pacing_operations())

# ═══════════════ 브라우저 UI (설정 + 실시간 미리보기) ═══════════════

# 정적 HTML·JavaScript는 web.page_template이 소유한다.


def render_page():
    """파라미터 선택지를 파이썬 상수에서 채워 넣는다 (목록을 한 곳에서만 관리)."""
    model = _page_renderer.PageRenderModel(
        profile=PROFILE,
        models=MODELS,
        samplers=SAMPLERS,
        schedules=NOISE_SCHEDULES,
        uc_presets=UC_PRESETS,
        resolutions=RESOLUTIONS,
        director_tools=DIRECTOR_TOOLS,
        emotions=EMOTIONS,
        boorus=BOORUS,
    )
    return _page_renderer.render_page(PAGE_TEMPLATE, model, esc_html)


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


def _job_ledger_paths():
    return _management_state.JobLedgerPaths(
        ledger_file=JOB_LEDGER_FILE,
    )


def _job_ledger_operations():
    """현재 프로필 저장소와 patch 가능한 장부 의존성을 늦게 연결한다."""
    return _management_state.JobLedgerOperations(
        lock=_JSON_IO_LOCK,
        load_json=globals()["load_json_recover"],
        atomic_write_json=globals()["atomic_write_json"],
        common_job_store=lambda: globals()["common_job_store"](),
        now=lambda: datetime.now().isoformat(timespec="seconds"),
        uuid_hex=lambda: uuid.uuid4().hex,
        redact=globals()["redact_diagnostic_text"],
        log_error=globals()["log"].error,
    )


def common_job_store():
    global _COMMON_JOB_STORE, _COMMON_JOB_STORE_ROOT
    _COMMON_JOB_STORE, _COMMON_JOB_STORE_ROOT = (
        _management_state.resolve_common_job_store(
            _job_ledger_paths(),
            _COMMON_JOB_STORE,
            _COMMON_JOB_STORE_ROOT,
            JobStore,
        )
    )
    return _COMMON_JOB_STORE


def _runtime_kind(operation, legacy_kind):
    return _management_state.runtime_kind(operation, legacy_kind)


def load_job_ledger():
    return _management_state.load_job_ledger(
        _job_ledger_paths(),
        _job_ledger_operations(),
    )


def _save_job_ledger(data):
    return _management_state.save_job_ledger(
        _job_ledger_paths(),
        _job_ledger_operations(),
        data,
    )


def recover_job_ledger():
    return _management_state.recover_job_ledger(
        _job_ledger_paths(),
        _job_ledger_operations(),
    )


def start_job_record(operation, kind, *, blueprint=None, payload_identity=None):
    return _management_state.start_job_record(
        _job_ledger_paths(),
        _job_ledger_operations(),
        operation,
        kind,
        blueprint=blueprint,
        payload_identity=payload_identity,
    )


def _finish_durable_job(existing, projected):
    return _management_state.finish_durable_job(
        existing,
        projected,
    )


def finish_job_record(job_id, *, status, completed=0, failed=0,
                      can_resume=False, message=""):
    return _management_state.finish_job_record(
        _job_ledger_paths(),
        _job_ledger_operations(),
        job_id,
        status=status,
        completed=completed,
        failed=failed,
        can_resume=can_resume,
        message=message,
    )


def record_job_result(
    job_id,
    path,
    *,
    artifact="",
    source_result_ids=(),
    result_id="",
):
    return _management_state.record_job_result(
        _job_ledger_operations(),
        job_id,
        path,
        artifact=artifact,
        source_result_ids=source_result_ids,
        result_id=result_id,
    )


def link_job_ancestor(job_id, source_job_id):
    return _management_state.link_job_ancestor(
        _job_ledger_operations(),
        job_id,
        source_job_id,
    )


def job_ledger_summary():
    return _management_state.job_ledger_summary(
        _job_ledger_paths(),
        _job_ledger_operations(),
    )


def _config_projection_operations():
    """ConfigServer의 읽기 전용 설정·Job 투영 의존성을 늦게 연결한다."""
    return _management_state.ConfigProjectionOperations(
        load_settings=globals()["load_settings_recover"],
        migrate_selections=globals()["migrate_legacy_selections"],
        migrate_char_slots=globals()["migrate_char_slots"],
        job_summary=lambda: globals()["job_ledger_summary"](),
        runtime_kind=globals()["_runtime_kind"],
        inherited_blueprint=globals()["inherited_blueprint"],
        project_live_state=globals()["project_live_state"],
        comparison_progress=lambda: globals()["_comparison_progress_load"](),
        project_comparison_progress=globals()["project_comparison_progress"],
        redact=globals()["redact_diagnostic_text"],
    )


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

    def __init__(self, cfg, persist_jobs=False, spec=None):
        self.cfg = cfg
        self.spec = load_spec() if spec is None else spec
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
        return _management_state.latest_config_from_disk(
            self.cfg,
            SETTINGS_FILE,
            DEFAULT_CONFIG,
            _config_projection_operations(),
        )

    def use_latest_config(self):
        merged = self.latest_config_from_disk()
        self.cfg.clear()
        self.cfg.update(merged)
        return merged

    def snapshot_config(self):
        try:
            settings_out = _setting_store.setting_catalog(
                _setting_store_paths(),
                _setting_store_operations(),
                CATEGORY_META,
            )
        except Exception as e:
            log.warning(f"세팅 로드 실패: {e}")
            settings_out = []
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
        return _management_state.snapshot_jobs(
            self,
            _config_projection_operations(),
        )

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
        return _setting_store.save_role(
            _setting_store_paths(),
            _setting_store_operations(),
            body,
        )

    def handle_sceneset_save(self, body):
        return _setting_store.save_preset(
            _setting_store_paths(),
            _setting_store_operations(),
            body,
            self.cfg,
        )

    def handle_option_item(self, body):
        return _setting_store.update_option(
            _setting_store_paths(),
            _setting_store_operations(),
            body,
            self.snapshot_config,
        )

    def handle_style_save(self, body):
        return _builder_handlers.handle_style_save(
            self,
            {"body": body},
            _builder_handler_operations(),
        )

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
        return _comparison_handlers.handle_compare_rerun(
            self,
            {"body": body},
            _comparison_handler_operations(),
        )

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
            return _resource_bridge.import_legacy_resources(
                self,
                _resource_import_paths(),
                _resource_import_operations(),
                body,
                filename,
            )
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

    def handle_norm_save(self, body):
        return _builder_handlers.handle_norm_save(
            self,
            {"body": body},
            _builder_handler_paths(),
            _builder_handler_operations(),
        )

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
        return _generation_handlers.handle_start(
            self,
            None,
            _generation_handler_operations(),
        )

    def start(self, open_browser=True):
        paths = _server_runtime.ServerRuntimePaths(
            static_dir=globals()["UI_DIR"],
            port_range=globals()["PREVIEW_PORT_RANGE"],
        )
        operations = _server_runtime.ServerRuntimeOperations(
            build_operation_sets=_app_wiring.build_route_operation_sets,
            request_handler=globals()["ConfigRequestHandler"],
            start_http=globals()["start_http_server"],
            browser_open=globals()["webbrowser"].open,
            logger=globals()["log"],
        )
        return _server_runtime.start_server_runtime(
            self,
            _route_bindings(),
            paths,
            operations,
            open_browser=open_browser,
        )


def char_folder_id(char):
    cid = char.get("id") or ""
    name = char.get("name") or "character"
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-")) or cid or "character"
    return safe.lower()[:40]


# ═══════════════ 메인 ═══════════════

def generation_context_fingerprint(cfg, acfg):
    return _generation_progress.context_fingerprint(cfg, acfg)


def generation_task_fingerprint(context_fingerprint, char, cid, num, copy):
    return _generation_progress.task_fingerprint(
        context_fingerprint,
        char,
        cid,
        num,
        copy,
    )


def make_progress_record(cfg, num, copy, saved_path, fingerprint):
    return _generation_progress.make_record(
        cfg,
        num,
        copy,
        saved_path,
        fingerprint,
        globals()["out_root"],
    )


def progress_item_key(item):
    return _generation_progress.item_key(item)


def progress_record_path(record, cfg):
    return _generation_progress.record_path(
        record,
        cfg,
        globals()["out_root"],
    )


def progress_record_valid(record, cfg, expected_fingerprint):
    return _generation_progress.record_valid(
        record,
        cfg,
        expected_fingerprint,
        globals()["out_root"],
    )

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


def _program_entry_operations():
    """기존 main의 초기화·서버·batch 경계를 호출 시점에 연결한다."""
    return _program_entry.ProgramEntryOperations(
        prepare_profile=lambda profile: profile,
        initialize_logging=lambda _context: globals()["log"],
        acquire_single_instance=lambda _context: True,
        release_single_instance=lambda _instance: None,
        migrate_program_data=lambda _context: globals()["_DATA_MIGRATION"],
        load_config=lambda _context: globals()["load_or_init_config"](),
        load_options=lambda _context: globals()["OPTIONS"],
        load_spec=lambda _context: globals()["load_spec"](),
        recover_jobs=lambda _context: globals()["recover_job_ledger"](),
        create_server=lambda config, _options, spec, _context: globals()[
            "ConfigServer"
        ](
            config,
            persist_jobs=True,
            spec=spec,
        ),
        start_server=lambda server, open_browser: server.start(
            open_browser=open_browser
        ),
        cleanup_server=lambda _server: None,
        close_logging=lambda _logger: None,
        warm_index=lambda server: globals()["_ac_index"](server.spec),
        start_daemon=lambda target: globals()["threading"].Thread(
            target=target,
            daemon=True,
        ).start(),
        run_generation=lambda server, config: globals()["_run_generation"](
            server,
            config,
        ),
        inherited_blueprint=globals()["inherited_blueprint"],
        fatal_stop_errors=(globals()["FatalStopError"],),
        log_info=globals()["log"].info,
        log_critical=globals()["log"].critical,
        format_traceback=globals()["traceback"].format_exc,
        read_input=lambda prompt: input(prompt),
        write_line=lambda line: print(line),
    )


def main():
    return _program_entry.run_program(
        globals()["sys"].argv[1:],
        _program_entry_operations(),
    )


def _run_generation(server, cfg_snapshot=None):
    return _generation_execution.run_generation(
        _generation_execution_operations(),
        server,
        cfg_snapshot,
    )

if __name__ == "__main__":
    main()
