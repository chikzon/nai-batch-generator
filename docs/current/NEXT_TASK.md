# 현재 작업

## 목적

생성·비교·이미지 도구 POST 라우트를
`src/nai_studio/web/routes/generation_post.py`로 옮긴다.

## 구현 범위

- 비교 활성화·재실행·레시피·승격·미리보기·실행
- 단일·세팅·재생성·i2i·Director 실행
- 생성 시작·중지·job 명령
- Anlas 비용·잔액 응답과 토큰 계산은 별도 runtime POST로 남김
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- generation POST 분기가 레거시 handler에서 제거됨
- 생성 실행권·중지·비교 상태와 응답 schema 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

generation POST 분리 뒤 runtime POST 기능군을 이동한다.
