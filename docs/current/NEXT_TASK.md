# 현재 작업 — ③ arca bookmarklet 실검증·문안 (미완 목록 마지막) — 완료

## 이번 커밋 (③)

가짜 arca.live Origin(playwright route)으로 bookmarklet 전문을 실행해
CORS·pairing 왕복을 실측 검증. 두 가지를 실측으로 잡아 고쳤다:

1. **이미지 한 장이 전체를 죽이던 결함** — CDN이 CORS를 안 주는 이미지에서
   fetch가 던지면 한 덩어리 try가 전부 삼켜 HTML조차 안 갔다. 이미지별
   try/catch로 바꿔 건너뛴 장수를 알림에 표시("원본 못 받은 이미지 N장").
2. **최신 Chromium의 Local Network Access 권한** — 공개 사이트→127.0.0.1
   fetch는 브라우저 권한 프롬프트를 요구한다(거부·headless면 preflight도
   없이 "Failed to fetch"). 서버 PNA preflight만으로는 부족 — 사용자가
   "허용"을 눌러야 하며, 그 안내를 문안에 넣었다. 검증은
   grant_permissions(["local-network-access"])로 프롬프트 허용을 재현.

문안 정비: 주소창 붙여넣기는 브라우저가 `javascript:`를 지움 → 북마크
저장 방식을 기본 안내로. 실측 왕복: 정상 코드 "보냈습니다 · new" /
틀린 코드 "pairing code가 없거나 틀립니다" / 비채널 경로 가드 동작.
검증: node --check · page_template 93,197자(상한 내) · relay 계약 ·
검증.py(회귀 171) 통과.

## 직전 완료 — 레거시 이동 후보 8함수 (⑤, a2e0ae4)

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
