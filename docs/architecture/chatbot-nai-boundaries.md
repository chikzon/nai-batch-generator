# 원래 챗봇·NAI 통합 작업실·연결 계약

## 소유권

### 원래 챗봇

- 프롬프트, 로어, 이야기 상태와 장면 선택
- Worker, R2 게시 경로, 챗봇 에셋 ID
- 결과 이미지의 게시·조립·후처리

### NAI 통합 작업실

- NAI 모델·생성 설정·비용·재시도
- 그림체·캐릭터·세팅·씬·Reference·Vibe
- 자료 수집·임포트·검토·비교·복구
- 생성 큐와 재현 정보

## 현재 경계

| 계층 | 책임 | 소유 위치 |
|---|---|---|
| domain | 모델·비용·토큰·위치·payload·메타데이터·증거·지식 규칙 | `src/nai_studio/domain/` |
| services | 생성·세팅·자료·빌더·관리의 실제 workflow와 저장 경계 | `src/nai_studio/services/` |
| runtime | 원자 파일 I/O, 실행 상태·Job, 로그·진단, 프로그램 진입 | `src/nai_studio/runtime/` |
| web/routes | GET·POST 경로 해석과 응답 변환 | `src/nai_studio/web/routes/` |
| web | localhost 보안·서버 수명·앱 조립·HTML·정적 UI | `src/nai_studio/web/` |
| compatibility | 기존 전역 이름·`ConfigServer`·`start.py` 진입점 | `src/nai_studio/legacy_app.py`, `start.py` |

`legacy_app.py`에 50줄 이상 기능 함수는 남아 있지 않다. `ConfigServer`는 32개
호환 메서드와 Operations 조립을 한 객체로 노출하지만, 각 메서드는 49줄 이하이며
실제 기능은 위 소유 모듈로 위임한다. 저장 schema, 사용자 자료 위치, HTTP endpoint,
`start.py`와 `실행.bat` 진입점은 유지한다.

## 연결 계약

- 두 앱이 공유하는 안정된 ID
- 생성 요청과 결과 manifest의 형식
- 계약 버전과 오류 코드

연결 계약은 NAI 토큰, 사용자 프롬프트 원문, 사용자 자료 자체를 소유하지 않는다.

초기 transport는 파일 기반 JSON이다.

1. 챗봇이 `render-request/v1` manifest를 만든다.
2. NAI 작업실이 참조 ID를 해석하고 생성한다.
3. NAI 작업실이 `render-result/v1` manifest를 만든다.
4. 챗봇의 자산 파이프라인이 후처리·게시한다.

같은 계약이 안정된 뒤 localhost API를 transport로 추가할 수 있다.

## 호환 원칙

- 기존 `start.py`, `실행.bat`, Worker URL, 자료 경로를 유지한다.
- 기능 이동 뒤 기존 import 위치에는 호환 어댑터를 둔다.
- 사용자 데이터는 이동하지 않고 경로로 연결한다.
- schema 변경과 모듈 이동을 같은 커밋에 섞지 않는다.
- `ConfigServer` 클래스 자체의 추가 분리는 기능 이득이 생길 때만 한다.
