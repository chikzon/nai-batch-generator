# 현재 작업

상태: **대기 — NAI 모델·프롬프트 설정의 순수 변환 경계 분리**

## 목적

`legacy_app.py`에 남은 모델 식별, Quality Tags, Undesired Content Preset의
순수 변환을 도메인 모듈로 옮긴다. 화면·저장 형식·payload는 바꾸지 않는다.

## 완료 조건

- 모델 표시명·메타데이터 문자열을 기존과 같은 지원 모델 ID로 해석한다.
- Quality Tags와 UC Preset의 합치기·분리·복원 결과가 기존과 바이트 동일하다.
- 기존 외부 호출과 테스트가 쓰는 이름은 호환 import로 유지한다.
- `legacy_app.py`에서 해당 상수와 순수 함수 본문이 제거된다.
- 직접 관련 기존 검사와 구조 계약을 통과한다.

## 금지 범위

- 화면·저장 형식·payload 변경
- UI·디자인 변경
- 모델·프리셋 문구 수정
- Variety+·Reference 조합 정책 변경
- 새 기능 테스트 추가
- HTTP route·HTML/JS 이동
- 포터블·설치본 빌드
- GitHub push·Release·태그
- 스마트폰 앱화
- 저장소 밖의 `성향 표`와 `로그 편집기`
