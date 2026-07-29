# 기능 분류·구조 최적화 색인

기준: 현재 작업 트리. 저장 schema·사용자 자료 경로·HTTP endpoint·생성 payload를
바꾸지 않고 기능 소유권과 조립 경계만 분리한 상태다.

## 전수 범위

| 대상 | 실측 | 분류·분리 상태 |
|---|---:|---|
| 제품 Python | 105파일 · 44,074줄 · 1,500개 함수·클래스 | `domain`·`services`·`runtime`·`web/routes`·호환 조립으로 전부 배정 |
| 50줄 이상 제품 정의 | 173개 | 기능 구현은 소유 모듈에 배정, `legacy_app.py`에는 큰 함수 0개 |
| `legacy_app.py` | 6,647줄 · 390개 정의 | 50줄 이상은 551줄짜리 `ConfigServer` 클래스 1개뿐이며, 내부 32개 메서드는 모두 49줄 이하 |
| HTTP | GET 47 · POST 74 | 기능 GET 37·정적 GET 10·POST 74를 생성·세팅·자료·빌더·관리·공통에 전부 배정 |
| 정적 DOM id | 518개 | 생성 216 · 세팅 80 · 자료 113 · 빌더 5 · 관리 78 · 공통 26 |
| UI JavaScript | 8파일 · 8,533줄 | generation→settings→library→builder→admin→bootstrap 분리 완료, `studio.js`는 1줄 호환 shim |

## 범주와 소유권

| 범주 | 내부 기능 | 주 소유 모듈 |
|---|---|---|
| 생성 | 설계도, 모델·비용·토큰, 캐릭터·위치, payload, NAI 통신, 단일·img2img·Director·Reference·Vibe·비교 실행, 결과 저장 | `domain/{blueprint,costs,model_presets,nai_payload,positioning,tokenization}.py`, `services/{generation_blueprint,generation_runtime,generation_step,generation_retry,generation_commit,generation_execution,generation_handlers,image_tool_handlers,nai_client,result_store}.py` |
| 세팅 | 옵션 축, 장면 프롬프트, 캐스트, 씬 미리보기, 상속, 순서·실험 계획, 저장·복제·undo | `domain/{project_inheritance,sequence,experiment}.py`, `services/{setting_compiler,setting_runtime,scene_catalog,scene_preview,settings_handlers,experiment_bridge,experiment_execution_bridge}.py` |
| 자료 | 이미지 증거·메타 복원, 공개자료, 자료팩, 백업, 평가·승격, 휴지통·출력 목록, 로컬 이미지 무결성 | `collection/arca.py`, `domain/{evidence,image_metadata,knowledge,resources,restoration,evaluation}.py`, `services/{public_collection,public_style_import,datapack_store,user_backup_store,metadata_candidate_store,local_image_store,library_catalog,output_lifecycle,evaluation_workflow}.py` |
| 빌더 | 그림체·캐릭터·작가 조합, 프롬프트 조각, 태그 검증 | `services/{style_store,character_storage,character_bench,character_runtime,artist_workspace,fragment_workflow,prompt_bridge,variation_bridge,catalog_search}.py`, catalog/fragments route |
| 관리 | HTTP 보안, 실행 상태·Job, 진단·로그, 프로그램 자료 이전, 앱 기동·종료, UI·빌드 | `runtime/*.py`, `services/program_data_migration.py`, `web/{http_server,server_runtime,app_wiring,page_template}.py`, `tools/build/*.py` |
| 공통 UI | 화면별 이벤트·상태·DOM 연결, 초기 bootstrap, 호환 로드 순서 | `web/static/studio-{generation,settings,library,builder,admin,bootstrap}.js`, `studio-core.js`, `studio.js` |
| 공통 기반 | 원자 저장, ID·fingerprint, 기능별 Operations 조립, 기존 import·진입점 호환 | `runtime/data_files.py`, `domain/blueprint.py`, `services/*_bridge.py`, `legacy_app.py`, `start.py` |

`domain`은 저장·HTTP를 모르고, `services`는 domain과 저장 경계를 조립하며,
`web/routes`는 주입된 Operations만 호출한다. `legacy_app.py`는 기존 전역 이름과
`ConfigServer` 호출 경로를 유지하는 조립·호환 계층으로 줄이는 중이다.

## 완료한 구조 단계

1. GET·POST route dispatch와 localhost 서버 수명 분리
2. 생성 계산·재시도·저장·handler·이미지 도구·비교 worker 분리
3. 세팅 계산·캐스트·씬 저장 handler 분리
4. 자료팩·백업·휴지통·평가·메타데이터·이미지 무결성·공개자료 분리
5. 그림체·캐릭터·작가·태그·조각·자료실 검색 분리
6. 프로그램 자료 이전, 앱 조립·기동·종료 분리
7. UI를 공통→생성→세팅→자료→빌더→관리→bootstrap 순서로 분리
8. 생성 Operations와 route 의존성 조립을 범주별 작은 함수로 분리

## 남은 완료 판정

- 레거시에 남은 세팅 저장소·이미지 캐시·태그/평가·작업 장부·보조 NAI 호출을 기능 서비스로 이동
- 이동한 대형 서비스의 내부 책임 분할
- ConfigServer를 상태·호환 facade로 축소
- 범주별 기존 회귀
- 전체 무과금 회귀 한 번
- localhost·정적 자산·JavaScript 구문
- 현재 HEAD의 exe·자료팩·설치본 빌드 경계
- 토큰·사용자 자료가 배포 산출물에 들어가지 않았는지 확인

위 검증과 빌드가 끝나기 전에는 전체 완료로 판정하지 않는다.
