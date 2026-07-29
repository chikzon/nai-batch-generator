# 현재 작업

## 목적

`/api/scenes`의 장면 조회·응답 조립을
`src/nai_studio/services/scene_catalog.py`와 catalog route로 옮긴다.

## 구현 범위

- 세팅 파일 또는 기본 asset config에서 선택 장면 조회
- 장면 prompt·negative·관계·Reference·좌표 원문 유지
- 현재 캐릭터 Reference 목록과 세팅 revision 응답 유지
- 기존 설정 경로·복구 로더·정규화 함수를 adapter로 재사용

## 완료 조건

- 68줄 장면 응답 조립이 `legacy_app.py`에 남지 않음
- `/api/scenes` JSON schema와 오류 형식 유지
- 장면·세팅·Reference 관련 기존 테스트 통과
- 서비스·route 함수 50줄 이하

## 금지 범위

- 장면 저장·생성 POST 이동
- 세팅 schema·사용자 파일 변경
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

scenes 조회 검증 뒤 남은 raw/export GET을 분리한다.
