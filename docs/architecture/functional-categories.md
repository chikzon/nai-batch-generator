# 기능 분류·구조 최적화 색인

기준: `6b7b2bf` 이후 작업 트리. 이 문서는 완료 선언이 아니라 누락 방지 색인이다.

## 전수 범위

| 대상 | 실측 | 분류 상태 |
|---|---:|---|
| 제품 Python | 75파일 · 1,100개 함수·클래스 | 디렉터리·모듈 소유권으로 전부 배정 |
| 50줄 이상 제품 정의 | 151개 | 별도 소유 모듈 81개, `legacy_app.py` 잔존 70개 |
| HTTP | GET 40 · POST 74 | 생성·세팅·자료·빌더·관리·공통에 전부 배정, 누락·중복 0 |
| 정적 DOM id | 518개 | 생성 216 · 세팅 80 · 자료 113 · 빌더 5 · 관리 78 · 공통 26 |
| UI JavaScript | `studio-core.js` 공통 상태·helper + `studio.js` 8,488줄 | 첫 공통 경계 분리 완료, 기능별 파일 분리는 미완료 |

## 범주와 현재 소유권

| 범주 | 내부 기능 | 현재 주 소유 모듈 |
|---|---|---|
| 생성 | 설계도, 모델·비용·토큰, 캐릭터·위치, payload, NAI 통신, 결과 저장, 단일·img2img·Director·비교 실행 | `domain/{blueprint,costs,model_presets,nai_payload,positioning,tokenization}.py`, `services/{generation_blueprint,generation_runtime,character_runtime,nai_client,result_store}.py`, generation/runtime route |
| 세팅 | 옵션 축, 장면 프롬프트, 캐스트, 씬 미리보기, 상속, 순서·실험 계획 | `domain/{project_inheritance,sequence,experiment}.py`, `services/{setting_compiler,scene_catalog,scene_preview,experiment_bridge,experiment_execution_bridge}.py`, settings route |
| 자료 | 이미지 증거·메타 복원, 공개자료, 자료팩, 백업, 평가·승격, 휴지통·출력 목록 | `collection/arca.py`, `domain/{evidence,image_metadata,knowledge,resources,restoration,evaluation}.py`, collection/catalog/recovery/evaluation 서비스·route |
| 빌더 | 그림체·캐릭터·작가 조합, 프롬프트 조각, 태그 검증 | `services/{character_bench,character_runtime,fragment_workflow,prompt_bridge,variation_bridge}.py`, fragments/catalog route; 태그·작가 핵심 일부는 레거시 잔존 |
| 관리 | HTTP 보안, 실행 상태·Job, 진단·로그, 백업·복구, UI·빌드 | `runtime/*.py`, `web/{http_server,page_template}.py`, 관리 route, `tools/build/*.py` |
| 공통 기반 | 원자 저장, ID·fingerprint, 호환 bridge, 앱 조립 | `runtime/data_files.py`, `domain/blueprint.py`, `services/*_bridge.py`, `legacy_app.py` |

`domain`은 저장·HTTP를 모르고, `services`는 domain을 조립하며, `web/routes`는
주입된 Operations만 호출한다. `legacy_app.py`는 아직 완전한 조립·호환 계층이 아니다.

## `legacy_app.py`에 남은 큰 정의 70개

아래 이름은 50줄 이상 정의를 한 번씩만 배정한 목록이다.

| 범주 | 잔존 정의 |
|---|---|
| 생성 | `comparison_styles`, `normalize_comparison_selection`, `iter_selected_comparison_jobs`, `comparison_selected_plan`, `iter_character_setting_jobs`, `comparison_character_setting_plan`, `comparison_plan`, `comparison_signature`, `iter_comparison_jobs`, `comparison_job_recipe_snapshot`, `comparison_recipe_context`, `compute_pending`, `_comparison_progress_start`, `_rerun_selected_comparison`, `_run_comparison`, `_run_generation`, `handle_job_command`, `handle_generate_one`, `handle_i2i`, `handle_regen`, `handle_scene_run`, `handle_compare_run`, `handle_director`, 중첩 생성 `run` 4개 |
| 세팅 | `migrate_legacy_selections`, `_migrate_legacy`, `import_char_files`, `sync_chars_to_files`, `handle_blueprint_project`, `handle_save`, `handle_scene_save` |
| 자료 | `search_booru`, `add_style`, `search_combos`, `organize_library_items`, `search_library`, `_merge_list_json`, `_local_image_audit`, `normalize_local_image_refs`, `rollback_local_image_normalize`, `metadata_audit_candidate`, `metadata_audit_save_candidate`, `_validate_datapack_manifest`, `preview_datapack_bytes`, `import_datapack_bytes`, `undo_datapack`, `_backup_diff_plan`, `restore_user_backup`, `trash_output_files`, `restore_trash_batch`, `list_output`, `_style_record_from_public_image`, `handle_character_variation_save`, `comparison_runs`, `comparison_recipe_for_output`, `_result_promotion_records`, `promote_comparison_recipe_assets`, `handle_compare_promote`, `handle_inspect`, `handle_ref_add`, `handle_ref_save` |
| 빌더 | `verify_tags`, `compose_artist_workspace` |
| 관리 | `migrate_legacy_program_data`, `ConfigServer`, `ConfigServer.start`, `main` |

## 이미 정리한 경계

- route dispatch: GET·POST 전부 작은 route 모듈
- 비용·토큰, 세팅 미리보기, 프롬프트 조각, 평가, 백업·자료팩 route workflow
- 위치 방식·좌표 검증·자동 분산
- 세팅 옵션 축·장면 프롬프트 compiler
- 캐릭터 슬롯·Variant·Cast 실행 투영
- 현재 설정의 단일 생성 설계도
- NAI HTTP·오류·ZIP 응답
- 결과 포맷·원자 저장·NAI 메타데이터
- 숨은 UI의 지연 초기화와 출력 탐색기 observer 수명
- UI 공통 상태·DOM helper의 `studio-core.js` 첫 분리와 로드·배포 순서 계약
- 빌드 필수 정적 자산 검증

## 남은 단계와 완료 판정

1. 비교 planning을 한 서비스로 모으고 별도 `legacy_blueprint_from_config` 투영을 통합
2. 단일·img2img·재생성·씬·비교·세팅 worker를 공통 실행 골격으로 이동
3. 자료팩·백업·휴지통·평가 transaction 전체를 route workflow 아래 서비스로 이동
4. 태그·작가·자료실 검색과 세팅 저장소를 범주 서비스로 이동
5. `ConfigServer`를 상태·의존성 조립과 얇은 호환 메서드만 남도록 축소
6. `studio.js`를 `core → generation → settings → library → builder → admin → bootstrap` 순으로 분리
7. 범주별 기존 시험 후 마지막 전체 무과금 회귀·localhost·빌드 경계 검증

70개 잔존 정의와 `studio.js` 분리가 남아 있으므로 구조 최적화는 **진행 중**이다.
