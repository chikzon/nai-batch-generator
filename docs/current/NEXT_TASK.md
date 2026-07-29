# 현재 작업

## 목적

`page_template.py`의 인라인 CSS·JavaScript를
`src/nai_studio/web/static/` 파일로 옮긴다.

## 구현 범위

- 인라인 `<style>` 본문을 `base.css`로 이동
- 인라인 `<script>` 본문을 `studio.js`로 이동
- 동적 초기값은 안전한 bootstrap 값으로 주입
- 기존 `studio.css` 뒤집어쓰기 순서와 정적 파일 빌드 포함 유지
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- CSS·JavaScript가 인라인 대형 문자열에서 제거됨
- 앱 기동·정적 응답·JavaScript 구문·주요 UI 테스트 통과
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

정적 자산 분리 뒤 데이터 손실 위험 예외 처리 세 곳을 수정한다.
