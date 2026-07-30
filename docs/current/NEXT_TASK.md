# 현재 작업 — 레거시 축소 단계 3: 범주별 wiring 분리

`compat/legacy_surface.py`의 `_*_operations()`/`_*_paths()` 조립을
`runtime/wiring/`으로 옮긴다. wiring 함수는 `app`(레거시 globals())을 받아
호출 시점에 이름을 찾는다 — 기존 `patch.object(APP, …)` monkeypatch 계약과
내부 호출자(레거시 셔틀 함수)가 전부 그대로 산다. 기능 알고리즘은 넣지 않는다.

단계 2(경로·상태 → ApplicationContext)는 wiring이 app 대신 context를 받는
형태로 뒤에 수렴시킨다(가정 명시 — 계약·회귀 무손상 순서 우선).

## 진행 (조각별 커밋)

- [x] 조각 1 — 자료 계열 5쌍 → `runtime/wiring/library.py`
      (datapack · local_image · data_inventory · metadata_candidate ·
      user_backup). legacy_surface 5,495 → **5,386줄** (−109)
      검증: 자료팩·백업·로컬이미지·색인·메타 회귀 16/16 · exports 계약 7 ·
      관련 계약 16 · 경계 5
- [x] 조각 2 — 자료실·수집·빌더 계열 23함수 → wiring/library.py
      (style_store · style_catalog · artist_rating · artist_workspace ·
      library_catalog · tag_catalog · builder_handlers · catalog_search ·
      remote_image_cache · fragment_import · public_style_import)
      5,386 → **5,253줄** (−133). 회귀 18/18 · 계약 28 · 경계 5
- [x] 조각 3 — 생성 계열 13함수 → `wiring/generation.py`
      (reference · auxiliary · pacing · step/retry/commit/execution ·
      handler bindings 3벌 · handler · image_tool · collection)
      5,253 → **5,071줄** (−182). 생성 경로 회귀 16/16 · exports 7 · 경계 5
- [x] 조각 4a — 세팅·캐릭터 저장 7함수 → `wiring/settings.py`,
      비교 계획·핸들러 2함수 → `wiring/management.py`
      5,071 → **4,952줄** (−119). 회귀 12/12 · exports 7 · 경계 5
- [ ] 조각 4b — 관리 잔여(config init/projection · character? · output ·
      job ledger · comparison runtime/execution/promotion · program_entry)
      → `wiring/management.py`, 라우트 바인딩 6벌 → `wiring/routes.py`
- [ ] 조각마다 경계 상한 하향(별도 커밋) — 역증가 차단

## 검증 원칙 (계획서)

- 각 조각: 직접 관련 회귀 + legacy_exports 계약 + payload 기준선
- 시험 seam 변경 없음 — wiring은 app 조회라 patch 의미 동일
- 전체 회귀·빌드는 마지막에만

## 금지 범위

- 기능 알고리즘을 wiring에 넣기, 같은 Operations 재정의, schema 변경,
  성향 표·로그 편집기·사용자 데이터, push·태그·Release
