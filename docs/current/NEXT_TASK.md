# 현재 작업

## 목적

작가 평가·결과 선별 POST 라우트를
`src/nai_studio/web/routes/evaluation_post.py`로 옮긴다.

## 구현 범위

- 작가 작업실·평점·메모·즐겨찾기·차단
- 결과 평가 action·선별 저장·삭제·복구
- 모자이크 저장·메타데이터 제거
- 기존 요청 크기 상한과 원자 저장 유지
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- evaluation POST 분기가 레거시 handler에서 제거됨
- 평가·선별 transaction과 응답 schema 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

evaluation POST 분리 뒤 조각·세팅·generation POST 기능군을 순서대로 이동한다.
