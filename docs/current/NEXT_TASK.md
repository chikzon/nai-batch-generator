# 현재 작업

## 목적

`ConfigServer.do_GET`의 자료 복구·보존 조회 라우트를
`src/nai_studio/web/routes/recovery.py`로 옮긴다.

## 구현 범위

- metadata audit·folder inventory·trash
- pack log·public collection·data storage
- image origins·local image integrity
- 기존 서비스와 `ConfigServer` 상태를 재구현하지 않고 동적 adapter로 연결
- `/api/public_collection_restoration`을 `/api/public_collection`보다 먼저 유지

## 완료 조건

- 대상 GET 구현이 `legacy_app.py`에 중복되지 않음
- 기존 JSON·오류·prefix 우선순위 유지
- 공개자료 복원·자료 저장·무결성 조회 테스트 통과
- route 함수 50줄 이하

## 금지 범위

- POST 라우트 이동
- export·raw image 응답 이동
- endpoint·schema 변경
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

recovery GET 검증 뒤 catalog와 generation GET을 각각 이동한다.
