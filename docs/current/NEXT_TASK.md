# 현재 작업

## 목적

프롬프트 조각 POST 라우트를
`src/nai_studio/web/routes/fragments_post.py`로 옮긴다.

## 구현 범위

- 조각 저장·이름 변경·삭제·초기화
- ZIP 임포트
- 무작위·순차 조각 미리보기와 선택 재추첨
- 실제 순차 카운터를 건드리지 않는 미리보기 계약 유지
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- fragment POST 분기가 레거시 handler에서 제거됨
- 저장 파일·복구 삭제·순차 카운터와 응답 schema 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

fragment POST 분리 뒤 세팅·generation POST 기능군을 순서대로 이동한다.
