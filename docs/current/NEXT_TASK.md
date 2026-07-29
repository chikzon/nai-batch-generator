# 현재 작업

## 목적

자료실·그림체·작가 평가 POST 라우트를
`src/nai_studio/web/routes/catalog_post.py`로 옮긴다.

## 구현 범위

- 그림체 저장·삭제·복원·정리 라우트
- 태그 검증·작가 작업실·평가 라우트
- 결과 선별·복구·메타데이터 제거 라우트
- 프롬프트 조각 저장·삭제·초기화·임포트·미리보기
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- catalog POST 분기가 레거시 handler에서 제거됨
- 평가·선별·조각 순번 상태와 응답 schema 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

catalog POST 분리 뒤 세팅·generation POST 기능군을 순서대로 이동한다.
