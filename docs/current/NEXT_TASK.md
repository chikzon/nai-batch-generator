# 현재 작업 — 레거시 이동 후보 8함수 서비스 이동 (미완 목록 ⑤) — 완료

## 이번 커밋

기능 계산이 섞여 있던 legacy 20줄+ 함수 8개를 기존 서비스로 이동.
legacy에는 같은 이름의 얇은 위임만 남겨 monkeypatch 표면을 보존했다.

| legacy 이름 | 이동처 |
|---|---|
| setting_reference_config·character_resource_config | character_runtime (scene_reference_config·cast_resource_config) |
| save_scenes (정규화부) | settings_handlers.normalize_scene_rows |
| activate_comparison_run·_comparison_result_context | comparison_runtime (동명 + comparison_result_context) |
| _nai_json_metadata | metadata_audit.nai_json_metadata |
| ensure_schema_split·setting_thumbs | setting_store (split_legacy_asset_config·setting_thumbnails) |

- monkeypatch 보존 방식: 위임이 **호출 시점에 모듈 전역을 조회**해 넘긴다 —
  시험이 patch하는 `list_settings`·`derive_setting_catalog`·
  `COMPARE_PROGRESS_FILE`·`SCHEMA_DIR`·`CONFIG_FILE` 전부 확인함.
- ComparisonRuntimeOperations에 선택 필드 `save_resume_progress`
  (기본 None — manifest는 안 쓰는 재개 전용 저장, wiring lambda가
  COMPARE_PROGRESS_FILE을 호출 시점 조회).
- legacy_surface 4,208 → 3,992줄. 경계 상한 4,250 → **4,000** 하향.
- 검증: 회귀 171 · exports 7 · 경계 5 · merge endpoints/datapack/
  evidence merge 계약 전부 OK.

## 직전 완료 — 실자료 UI 성능 측정 (④, 9c11df8)

콜드 첫 열기 314ms → 예열(load_combos) 후 212ms. 나머지 지표 전부 목표 내.

## 남은 것

③ arca bookmarklet 문안 — **사용자 지시로 보류**
묶음 종료 시: v1.2.0 재빌드·스모크·인계서 재생성 (현재 인계서는
f69abc1 기준, HEAD는 그 뒤로 진행됨)

## 금지 범위

- push·태그·Release (사용자 지시 대기)
- legacy_surface에 새 코드 추가 (경계 상한 4,000)
