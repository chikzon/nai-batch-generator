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

순수 모델 해석과 Quality·UC 문자열 변환은
`src/nai_studio/domain/model_presets.py`가 소유한다. 레거시 작업실은 호환 이름을
import해 UI·저장·payload 경로를 그대로 유지한다.

## 현재 분리된 NAI 작업실 경계

| 책임 | 소유 모듈 |
|---|---|
| 모델·Quality·UC 변환 | `domain/model_presets.py` |
| Anlas 비용·Opus 무료 조건 | `domain/costs.py` |
| PNG·WebP·Stealth 메타데이터 복원 | `domain/image_metadata.py` |
| NAI T5 토큰 계산 | `domain/tokenization.py` |
| 캐릭터 위치 방식·좌표 검증·자동 분산 | `domain/positioning.py` |
| 좌표·Reference·img2img를 포함한 NAI payload 조립 | `domain/nai_payload.py` |
| 사용자 자료 잠금·원자 저장·손상 복구 | `runtime/data_files.py` |
| 실행권·중지·진행률·미리보기 상태 | `runtime/live_state.py` |
| 정적 HTML 골격·동적 bootstrap | `web/page_template.py` |
| 화면 CSS·JavaScript 자산 | `web/static/base.css`, `studio.css`, `studio.js` |
| localhost HTTP 보안·본문 제한·정적 응답·포트 기동 | `web/http_server.py` |
| 설계도·순서·작업 상태 GET 라우트 | `web/routes/runtime.py` |
| 자료 복구·보존 상태 GET 라우트 | `web/routes/recovery.py` |
| 자료실·빌더 검색 GET 라우트 | `web/routes/catalog.py` |
| 비교·실시간 생성 상태 GET 라우트 | `web/routes/generation.py` |
| 이미지·내보내기·진단·HTML GET 라우트 | `web/routes/assets.py` |
| 백업·로컬 자료·메타데이터 감사 POST 라우트 | `web/routes/recovery_post.py` |
| 자료팩·공개자료·Reference 임포트 POST 라우트 | `web/routes/collection_post.py` |
| 자료실·그림체 정리 POST 라우트 | `web/routes/catalog_post.py` |
| 작가 평가·결과 선별 POST 라우트 | `web/routes/evaluation_post.py` |
| 프롬프트 조각 POST 라우트 | `web/routes/fragments_post.py` |
| 세팅·장면 편집 POST 라우트 | `web/routes/settings_post.py` |
| 생성·비교·이미지 도구 POST 라우트 | `web/routes/generation_post.py` |
| 설계도·설정·비용·토큰 POST 라우트 | `web/routes/runtime_post.py` |
| 공개자료 검색·재개·임포트 조정 | `services/public_collection.py` |
| 캐릭터 슬롯·Variant·Cast·활성 인물 투영 | `services/character_runtime.py` |
| 현재 설정·자료·출력의 생성 설계도 투영 | `services/generation_blueprint.py` |
| NAI 이미지 HTTP 요청·오류 분류·ZIP 응답 해석 | `services/nai_client.py` |
| 결과 포맷·원자 저장·NAI 메타데이터 보존 | `services/result_store.py` |
| 세팅 옵션 축·장면별 인물 프롬프트 컴파일 | `services/setting_compiler.py` |
| 공개 게시글 URL·HTML·이미지 통신 | `collection/arca.py` |
| 선택 세팅 장면의 UI 조회 투영 | `services/scene_catalog.py` |

`legacy_app.py`는 위 이름을 import하거나 얇은 호환 어댑터로 노출한다. 저장 schema,
사용자 자료 위치, HTTP endpoint와 `start.py` 진입점은 바꾸지 않았다.

## 아직 분리되지 않은 책임

점진 분리는 **완료되지 않았다**. 다음 큰 경계가 `legacy_app.py`에 남아 있다.

- `ConfigServer`: route 의존성 조립과 레거시 호환 메서드
- 자료실 검색·그림체·작가 평가·태그 자동완성
- 세팅·자료팩·전체 백업·휴지통
- 비교 계획·결과 승격·재실행
- 단일·세팅·비교 생성 오케스트레이션

이들은 사용자 데이터와 실행 순서가 얽혀 있으므로 schema 변경 없이 한 경계씩 옮기고,
기존 호출 경로에는 호환 어댑터를 남긴다.

### 연결 계약

- 두 앱이 공유하는 안정된 ID
- 생성 요청과 결과 manifest의 형식
- 계약 버전과 오류 코드

연결 계약은 NAI 토큰, 사용자 프롬프트 원문, 사용자 자료 자체를 소유하지 않는다.

## 초기 연결 방식

초기 transport는 파일 기반 JSON이다.

1. 챗봇이 `render-request/v1` manifest를 만든다.
2. NAI 작업실이 참조 ID를 해석하고 생성한다.
3. NAI 작업실이 `render-result/v1` manifest를 만든다.
4. 챗봇의 자산 파이프라인이 후처리·게시한다.

같은 계약이 안정된 뒤 localhost API를 transport로 추가할 수 있다.

## 호환 원칙

- 기존 `start.py`, `실행.bat`, Worker URL, 자료 경로를 유지한다.
- 기능 이동은 `git mv`로 하고 기존 import 위치에 어댑터를 둔다.
- 사용자 데이터는 이동하지 않고 경로로 연결한다.
- schema 변경과 모듈 이동을 같은 커밋에 섞지 않는다.
