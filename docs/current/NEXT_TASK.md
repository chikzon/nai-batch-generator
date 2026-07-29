# 현재 작업

## 목적

`ConfigServer.do_GET`의 읽기 전용 runtime 라우트를
`src/nai_studio/web/routes/runtime.py`로 옮긴다.

## 구현 범위

- `/api/blueprint`
- `/api/setting_sequence`
- `/api/jobs`
- 기존 `ConfigServer`의 snapshot 메서드 재사용
- 기존 `startswith` 순서·HTTP 200 JSON 오류 형식 유지

## 완료 조건

- 세 라우트 구현이 `legacy_app.py`에 중복되지 않음
- blueprint·sequence·jobs 응답과 오류 변환 유지
- 기존 실제 HTTP transport 시험 통과
- 새 route 모듈 함수 50줄 이하

## 직접 관련된 기존 테스트

- blueprint snapshot·project inheritance 테스트
- setting sequence 저장·검증 테스트
- job snapshot·command 테스트
- `ConfigServer.start` HTTP 테스트

## 금지 범위

- POST 라우트 이동
- 다른 GET 기능군 이동
- endpoint·status·schema 변경
- route dict·exact path 일괄 변경
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

runtime GET 검증 뒤 나머지 읽기 전용 GET을 generation·catalog·recovery 순으로 옮긴다.
