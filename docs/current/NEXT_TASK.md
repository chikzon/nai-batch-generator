# 현재 작업

## 목적

세팅·장면 편집 POST 라우트를
`src/nai_studio/web/routes/settings_post.py`로 옮긴다.

## 구현 범위

- 장면 복제·복제 되돌리기·저장·미리보기
- 옵션·상대역·씬 묶음 저장
- 세팅 생성·세트 추가·메타·번호 변경·삭제·그룹 복제
- 세팅 파일 revision·캐릭터 좌표·캐스트 조립 유지
- 기존 서비스 호출 순서와 응답 schema 유지
- 충돌하는 prefix는 긴 경로를 먼저 판정

## 완료 조건

- settings POST 분기가 레거시 handler에서 제거됨
- 세팅 저장·미리보기와 응답 schema 유지
- 관련 기존 회귀 테스트 통과

## 금지 범위

- 저장 schema·사용자 파일 변경
- 세팅·generation POST 라우트 이동
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

settings POST 분리 뒤 generation·runtime POST 기능군을 순서대로 이동한다.
