# 현재 작업

## 목적

설계도·설정 저장·비용·토큰 POST 라우트를
`src/nai_studio/web/routes/runtime_post.py`로 옮긴다.

## 구현 범위

- 설계도 프로젝트 저장
- 설정 저장
- Anlas 비용·잔액 계산과 토큰별 캐시 격리
- Base·Negative·캐릭터별 토큰 계산
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- `do_POST`가 기능 구현 없이 route 위임만 수행
- 비용·토큰 응답과 설정 revision 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

POST 분리 완료 뒤 정적 CSS·JavaScript를 `ui/` 파일로 이동한다.
