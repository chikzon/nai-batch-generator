# 원래 챗봇·NAI 통합 작업실·연결 계약

## 소유권

| 경계 | 소유 기능 |
|---|---|
| 원래 챗봇 | 프롬프트·로어·이야기 상태·장면 선택, Worker·R2 게시, 결과 조립·후처리 |
| NAI 통합 작업실 | 모델·생성 설정·비용·재시도, 그림체·캐릭터·세팅·Reference·Vibe, 자료 수집·임포트·검토·비교·복구, 생성 Queue와 재현 정보 |
| 연결 계약 | 안정된 자산 ID, `render-request/v1`, `render-result/v1`, 계약 버전·오류 코드 |

연결 계약은 NAI 토큰, 사용자 프롬프트 원문, 사용자 자료를 소유하지 않는다.

## 코드 경계

| 계층 | 책임 | 위치 |
|---|---|---|
| domain | 외부 I/O 없는 모델·비용·토큰·위치·payload·증거·지식 규칙 | `src/nai_studio/domain/` |
| services | 생성·세팅·자료·빌더·관리 workflow와 저장 경계 | `src/nai_studio/services/` |
| runtime | 원자 파일 I/O, 상태·Job, 로그·진단, 프로그램 진입 | `src/nai_studio/runtime/` |
| web/routes | GET·POST 경로 해석과 응답 변환 | `src/nai_studio/web/routes/` |
| web | localhost transport, 앱 조립, HTML renderer, 정적 UI | `src/nai_studio/web/` |
| compatibility | 기존 전역 이름·`ConfigServer`·진입점 | `src/nai_studio/legacy_app.py`, `start.py` |

`legacy_app.py`의 실제 기능·저장 본문은 각 소유 서비스로 이동했다. 현재 남은 것은
기존 monkeypatch·import·HTTP 호출을 깨지 않기 위한 Operations 조립과 호환 facade다.
`ConfigServer`를 더 잘게 나누는 것은 공개 호출 계약 변화 없이 실질 이득이 생기는
후속 작업으로 남기며, 이번 구조 완료를 막는 기능 누락은 아니다.

## 파일 연결 계약

1. 챗봇이 `render-request/v1` manifest를 만든다.
2. NAI 작업실이 참조 ID를 해석하고 생성한다.
3. NAI 작업실이 `render-result/v1` manifest를 만든다.
4. 챗봇 자산 파이프라인이 후처리·게시한다.

파일 JSON 계약이 안정된 뒤에만 localhost API transport를 추가할 수 있다.

## 호환 원칙

- 기존 `start.py`, `실행.bat`, Worker URL, 자료 경로 유지
- 이동한 기존 import 위치에는 호환 adapter 유지
- 사용자 데이터는 이동·자동 변환하지 않고 경로로 연결
- schema 변경과 모듈 이동을 같은 커밋에 섞지 않음
- 기능 추가는 소유 service에서 하고 레거시 분기를 다시 늘리지 않음
