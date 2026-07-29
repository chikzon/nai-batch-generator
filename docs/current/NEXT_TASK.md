# 현재 작업

## 목적

비교 진행·실행 상태 GET 라우트를
`src/nai_studio/web/routes/generation.py`로 옮긴다.

## 구현 범위

- compare catalog·runs·progress
- `/status.json`
- `/latest.webp`
- config snapshot은 기존 runtime GET에 포함
- 기존 비교 함수와 `LiveState`를 동적 adapter로 재사용

## 완료 조건

- 대상 GET 구현이 `legacy_app.py`에 중복되지 않음
- latest 이미지의 404·MIME·no-store 계약 유지
- 비교 진행·실행 상태 기존 테스트 통과
- route 함수 50줄 이하

## 금지 범위

- 생성 POST 이동
- scenes·raw 자료·export GET 이동
- endpoint·schema 변경
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

generation GET 검증 뒤 raw 자료 응답과 scenes 조회를 각각 분리한다.
