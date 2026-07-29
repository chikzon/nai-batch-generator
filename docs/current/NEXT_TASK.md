# 현재 작업

## 목적

`ConfigServer.do_GET`의 자료 검색·빌더 조회 라우트를
`src/nai_studio/web/routes/catalog.py`로 옮긴다.

## 구현 범위

- booru·style duplicates
- library·combos·recipes
- autocomplete·tags·scenes
- 기존 검색·캐시·정렬 함수를 동적 adapter로 재사용

## 완료 조건

- 대상 JSON GET 구현이 `legacy_app.py`에 중복되지 않음
- query 기본값·상한·오류 형식 유지
- 자료실·작가 조합·태그·씬 관련 기존 테스트 통과
- route 함수 50줄 이하

## 금지 범위

- raw image·export GET 이동
- compare·generation GET 이동
- POST 라우트 이동
- endpoint·schema 변경
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

catalog GET 검증 뒤 generation GET과 남은 raw 응답을 분리한다.
