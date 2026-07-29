# 현재 작업

## 목적

구조 상한 계약을 추가하고 최종 회귀·기동 검증을 실행한다.

## 구현 범위

- `do_GET`·`do_POST`가 다시 비대해지지 않게 architecture 계약 갱신
- 정적 자산과 route 모듈이 빌드에 포함되는지 확인
- Python compile·JavaScript syntax·전체 회귀 1회
- localhost 실제 기동과 HTML·CSS·JavaScript 응답 확인
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- 전체 회귀 통과
- 앱 기동·핵심 정적 응답 통과
- 추적 작업 트리 깨끗, 사용자 미추적 파일 보존
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

최종 검증 뒤 결과와 남은 비차단 후속만 현재 문서에 기록한다.
