# 현재 작업

## 목적

`ConfigServer.start()` 안의 공통 HTTP transport만
`src/nai_studio/web/http_server.py`로 옮긴다.

## 구현 범위

- JSON 응답 보안 헤더
- Host·Origin·Sec-Fetch-Site 검증
- POST Content-Length 검증과 128MiB 상한
- 고정 정적 자산 응답과 빈 404
- Windows 포트 독점 서버·포트 탐색·브라우저 열기
- `ConfigServer.httpd`, `url`, `start(open_browser=...)` 호환

기존 `do_GET`·`do_POST`의 endpoint 순서와 비즈니스 호출은 이번 단계에서 이동하지
않고 새 transport 기반 클래스를 사용한다.

## 완료 조건

- 공통 HTTP 보안·본문·응답·서버 기동 구현이 `legacy_app.py`에 중복되지 않음
- `/`, `/ui/studio.css` HTTP 200
- 교차 사이트 POST 차단과 CLI POST 허용 유지
- `ConfigServer.start(open_browser=False)`가 브라우저를 열지 않음
- 기존 endpoint, 응답 status, JSON 형식 변경 없음

## 직접 관련된 기존 테스트

- `RegressionTests.test_server_can_start_without_opening_a_browser`
- `/setout` 허용·휴지통 차단 HTTP 테스트
- `/api/diag` redaction HTTP 테스트
- 교차 사이트 POST 차단·CLI 허용 테스트
- Anlas cache와 서버 시작 뒤 동적 patch 테스트

## 금지 범위

- endpoint 기능 변경
- exact path로의 일괄 변경
- route dict·기능군 전체 이동
- 사용자 데이터·설정 schema 변경
- 새 의존성·전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

transport 검증 뒤 읽기 전용 GET 라우트를 ordered matcher로 기능군별 이동한다.
