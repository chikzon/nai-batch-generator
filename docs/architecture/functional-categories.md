# 기능 분류·구조 최적화 색인

기준: `0f7e5ed` 이후 현재 작업 트리. 저장 schema·사용자 자료 경로·HTTP endpoint·
응답 형식·생성 payload를 바꾸지 않고 소유권과 내부 단계를 분리했다.

## 전수 범위

| 대상 | 실측 | 결과 |
|---|---:|---|
| 제품 Python (`src/nai_studio`) | 117파일 · 48,230줄 · 1,788개 함수·클래스 | domain·services·runtime·web/routes·호환 조립으로 전부 배정 |
| 50줄 이상 제품 정의 | 187개 | 소유 모듈 안에서 책임 확인 |
| 150줄 이상 제품 함수 | 0개 | 마지막 자료팩 import·undo까지 단계 분리 |
| `legacy_app.py` | 5,395줄 · 408개 정의 | 기능·저장 본문 0개, 호환 facade와 Operations 조립만 유지 |
| HTTP | 기능 GET 37 · 정적 GET 10 · POST 74 | 생성·세팅·자료·빌더·관리·공통으로 전부 배정 |
| 정적 DOM id | 518개 | 생성 216 · 세팅 80 · 자료 113 · 빌더 5 · 관리 78 · 공통 26 |
| UI JavaScript | 8파일 · 8,533줄 | 기능별 6파일+core+1줄 호환 shim |

`ConfigServer`는 327줄짜리 호환 facade다. 내부 handler는 route 모듈로 위임한다.
레거시에 남은 35줄 이상 함수 8개는 Operations·route 의존성 조립 또는 기존 호출
signature를 유지하는 adapter이며 기능·저장 알고리즘이 아니다.

## 범주별 기능과 소유권

| 범주 | 기능 | domain·service 소유 모듈 |
|---|---|---|
| 생성 | 설계도 복원·조립, 모델·토큰·비용, 프롬프트·캐릭터·위치, payload, NAI 호출, 진행·속도·재시도, 단일·배치·img2img·Director·Reference·Vibe, 결과 원자 저장 | `domain/{blueprint,costs,model_presets,nai_payload,positioning,prompt_resolution,tokenization,variations}` · `services/{blueprint_execution_bridge,generation_blueprint,generation_commit,generation_execution,generation_handlers,generation_pacing,generation_progress,generation_retry,generation_runtime,generation_step,image_tool_handlers,nai_auxiliary,nai_client,reference_preparation,result_store,variation_bridge}` |
| 세팅 | 장면·역할·옵션, 캐스트, 위치·관계, prompt compile, 씬 미리보기, 상속, 순서·실험 계획, 저장·복제·undo | `domain/{experiment,project_inheritance,sequence}` · `services/{experiment_bridge,experiment_execution_bridge,scene_catalog,scene_preview,setting_compiler,setting_runtime,setting_store,settings_handlers}` |
| 자료 | 이미지·메타 증거, 공개자료 수집, 자료팩 검사·충돌·import·undo, 통합 자료실 검색·검토, 폴더·저장소 인벤토리, 로컬/원격 이미지, 백업, 복구·휴지통 | `collection/arca` · `domain/{evidence,image_metadata,knowledge,resources,restoration}` · `services/{collection_handlers,data_inventory,datapack_store,datapack_workflow,library_catalog,local_image_store,metadata_audit,metadata_audit_adapter,metadata_candidate_store,output_lifecycle,public_collection,public_style_import,remote_image_cache,resource_bridge,restoration_inputs,user_backup_store,user_backup_workflow}` |
| 빌더 | 그림체, 캐릭터, 작가 조합·평가, 프롬프트 조각, 태그 색인·검증, 규격화 저장 | `services/{artist_rating_store,artist_workspace,builder_handlers,catalog_search,character_bench,character_runtime,character_storage,fragment_workflow,prompt_bridge,style_store,tag_catalog}` |
| 관리 | 설정·상태, Job·계보, 평가·승격, 비교 계획·실행·재개·결과, 진단·로그, 프로그램 자료 이전, 앱 기동·종료, 빌드 | `domain/evaluation` · `services/{comparison_execution,comparison_handlers,comparison_planning,comparison_promotion,comparison_runtime,config_validation,evaluation_bridge,evaluation_workflow,job_bridge,management_state,program_data_migration,result_promotion}` · `runtime/*` · `tools/build/*` |
| 공통 UI | 페이지 renderer, localhost 보안·서버 수명, route dispatch, 화면별 상태·이벤트·bootstrap | `web/{app_wiring,http_server,page_renderer,page_template,server_runtime}` · `web/routes/*` · `web/static/studio-{generation,settings,library,builder,admin,bootstrap}.js` · `studio-core.js` · `studio.js` |
| 호환·연결 | 기존 import·전역 이름·`ConfigServer`·`start.py` 유지, 기능별 Operations 주입 | `services/legacy_bridge.py` · `legacy_app.py` · `start.py` |

## 내부 최적화 단계

1. HTTP GET·POST dispatch와 localhost 서버 수명 분리
2. 생성 payload·호출·진행·재시도·결과 저장 단계 분리
3. 세팅 저장·옵션·씬 compile·미리보기·실험 계획 단계 분리
4. 자료팩 preview·conflict·install·log·조건부 undo 단계 분리
5. 자료실 projection·검색·평가·인벤토리·백업·이미지 cache 단계 분리
6. 빌더의 그림체·캐릭터·작가·태그·조각 책임 분리
7. 비교 계획·signature·recipe·실행·결과·승격 단계 분리
8. 관리 상태·Job·진단·기동·빌드와 공통 page renderer 분리
9. 인라인 UI를 core→generation→settings→library→builder→admin→bootstrap으로 분리
10. 레거시 기능·저장 본문 제거와 감소 전용 5,420줄 상한 고정

## 검증 결과

- Python compileall 통과
- JavaScript 8파일 `node --check` 통과
- 계약 187/187 · 구조 5/5 · 회귀 171/171 통과
- 포터블 exe: `/`, `/ui/base.css`, `/ui/studio.js`, `/api/config` 모두 HTTP 200
- 현재 소스로 exe·기본 자료팩·설치본 빌드 성공
- 프로그램 폴더에 `설정.json`·`상태.json`·`생성.log`·`수집`·`캐릭터`·`프로필`·
  `output` 없음
- 배포 폴더와 산출물에서 실제 `pst-ne-…` 토큰 없음

## 완료 범위

완료는 이번 작업인 **기능 분류·책임 분리·내부 대형 함수 축소·호환 검증·현재 빌드**를
뜻한다. 비교 앱에서 조사된 후속 새 기능, 모바일 앱화, 별도 UI 2차 재설계까지
완료했다는 뜻은 아니다.
