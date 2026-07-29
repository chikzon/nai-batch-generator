# 현재 작업

## 목적

route 의존성의 실행 시점 교체 가능성을 복원하고
NAI 호출의 사용하지 않는 레거시 인자를 제거한다.

## 구현 범위

- 서버 기동 뒤 monkeypatch·구현 교체도 기존처럼 route 호출에 반영
- route별 global callback을 한 late-bound adapter로 통일
- `call_nai_api`의 실제로 읽지 않는 레거시 인자 제거
- 남은 인자는 keyword-only 또는 요청 객체로 오호출 방지
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- 기존 route 동작과 테스트 patch 계약 유지
- 단일·세팅·비교 생성 payload와 직렬 호출 테스트 통과
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

호출 계약 정리 뒤 구조 상한 계약을 추가하고 최종 회귀·기동 검증을 실행한다.
