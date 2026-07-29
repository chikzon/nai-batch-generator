# 현재 작업

## 목적

자료 복구·백업·임포트 POST 라우트를
`src/nai_studio/web/routes/recovery_post.py`로 옮긴다.

## 구현 범위

- 휴지통·백업·자료팩·Reference/Vibe 자료 복구 라우트
- 공개자료 수집·임포트·되돌리기 라우트
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- recovery POST 분기가 레거시 handler에서 제거됨
- 저장·복구·되돌리기 응답과 오류 상태 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- catalog·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

recovery POST 분리 뒤 catalog·generation POST 기능군을 순서대로 이동한다.
