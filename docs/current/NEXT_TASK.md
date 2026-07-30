# 현재 작업

## 상태 — 잔여 계획(코덱스 계획서) 구현 마감

단계 1(데이터 안전·병합) · 2(증거 정제, 첫 조각) · 3(수집: Range 재개·relay) ·
4(NAI 실검증·UI 성능·검토 흐름 UI) · 5(업데이트 검사·README 정합)을 구현했고,
이 커밋 뒤 전체 무과금 검증과 v1.2.0 재빌드, Claude push 인계서 재생성만 남는다.
**이 커밋이 마지막 코드 커밋이다 — 빌드 뒤에는 커밋하지 않는다.**

## 구현 커밋 (bd9b578 이후)

9470efd 파일 트랜잭션 · 3c36d5c 자료팩 staging · 56ee240 백업 복원 기동 복구 ·
3f63f15 3-way 기준값 · 5e9eb93 병합 표면 · 27b9bd3/2311ab4 인계 ·
b504280 증거 병합 · dd9ad41 Range 재개 · fb92208 다운로드 제어 ·
eb09086 browser relay · 00fe779 자료 탭 검토 흐름 UI · bd4b1c2 바이너리 업로드
디스패치 결함 수정 + NAI 실검증(13 Anlas) · 3a241bc UI 성능 실측 ·
bd2eea1 업데이트 검사 · 66c9322 README·v1.2.0

## 미완 항목 (완료라고 쓰지 않는 것)

- **스크린샷 재촬영**: 자료·관리 탭에 카드가 추가됐으나 화면 표시가 없는
  환경이라 캡처 불가(2회 시도). README에 차이를 명시했다. 다음에 브라우저
  패널이 표시되는 세션에서 `current-library.png`·`current-management.png`
  재촬영 후 README 문구 원복.
- **UI 성능 실자료 측정**: 빈 데이터 실측만 있음(작가 조합 목록 렌더는 하한값).
- **단계 2 잔여**: 캐릭터 자산 중복 검토(merge_evaluations·merge_resources
  연계), 자료팩 쪽 3-way 기준값.
- **relay 브라우저 쪽 스크립트**: pairing UI는 자료 탭에 있으나 arca.live에서
  쓸 bookmarklet/userscript 문안은 안내 텍스트 수준.
- 스마트폰 앱·PC 연동은 계획대로 이번 범위에서 제외.

## 마감 절차 (이 커밋 뒤, 순서 고정)

1. 새 계약 시험 전체 + `python 검증.py` (계약 10 · 경계 5 · 회귀 171)
2. `python 빌드.py --설치본` → 포터블 ZIP·자료팩·설치본·SHA256SUMS (v1.2.0)
3. 산출물 스모크(빈 데이터 기동 HTTP 200 · 토큰/개인 자료 0건)
4. `docs/current/CLAUDE_PUSH_HANDOFF.md`(미추적) 재생성 — push 범위·검증
   수치·산출물 해시·절차. push·태그·Release는 하지 않는다.

## 금지 범위

- 빌드 뒤 커밋, 기존 태그·Release 수정, push, 사용자 자료 접근
