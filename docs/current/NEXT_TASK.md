# 현재 작업 — 레거시 축소 단계 1: 호환 표면 고정

새 작업 지시(레거시 축소 우선 NAI 작업실 최적화)의 첫 단계.
v1.2.0 마감 기록은 `CLAUDE_PUSH_HANDOFF.md`(미추적)에 있다 — 이 커밋부터
HEAD가 f68de15를 지나므로 push 시점에 인계서를 다시 만든다.

## 이 단계에서 하는 것 (계획서 단계 1만)

- [x] 외부 사용 이름 실측: 시험의 `APP.<이름>` + `patch.object(APP, …)` 전수
      → **247개** (사용 199 · patch 82, 계획서의 195에서 늘어난 실측치)
- [x] `compat/legacy_exports.py` — LEGACY_EXPORTS 247개에 kind·owner 배정
      (adapter 149 · alias 44 · 경로 25 · 상수·상태 17 · 모듈 참조 8 ·
      legacy-class 3 · 기타 1). 미사용이 되어도 한 릴리스 동안 삭제 금지.
- [x] 기준선 기록:
      - ROUTE_BASELINE 119개 — endpoint 문자열이 web/routes 밖으로 나오면
        시험이 실패
      - 사용자 저장 경로 이름 9종 꼬리 고정
      - 생성 payload SHA-256 기준선(`legacy_payload_baseline.txt`) —
        이동 중 payload가 바뀌면 실패
- [x] `test_legacy_exports_contract.py` 7시험 — 표면 드리프트 차단

## 다음 단계 예고 (계획서 순서)

2. 경로·상태·캐시 → ApplicationContext·서비스 state (테스트 seam 교체는
   기능 이동과 별도 커밋)
3. `runtime/wiring/` 분리 — legacy_surface의 `_*_operations()` 조립 이동
4. ConfigServer → `web/application_server.py`
5. legacy_surface = export map + 최소 adapter, 경계 상한 하향(역증가 차단)

## 검증 원칙

- 각 이동마다 직접 관련 기존 시험 + legacy_exports 계약만
- payload·자료팩 결과·설정 저장·Job signature는 기준선 해시로 전후 비교
- 성능 20% 악화 금지 (초기 1초·탭 200ms·작가 조합 200ms)
- 전체 회귀·빌드는 마지막에만

## 금지 범위

- 기능 삭제·schema migration·UI 개편을 이동 커밋과 혼합
- 성향 표·로그 편집기·사용자 데이터·기존 태그·Release·push
