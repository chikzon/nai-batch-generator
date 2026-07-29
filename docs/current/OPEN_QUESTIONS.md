# 사용자 판단 대기

현재 판단이 필요한 질문은 없다.

## 다음 확정 작업 — 모델·Quality·UC 순수 변환 경계 분리

문서 상태 교정이 끝난 다음 `NEXT_TASK`로 승격한다. 그전에는 코드를 수정하지 않는다.

### 이동 대상

`src/nai_studio/legacy_app.py`에서 다음 순수 값·함수를
`src/nai_studio/domain/model_presets.py`로 옮긴다.

- `MODELS`, `UC_PRESETS`
- `QUALITY_SUFFIX_TEXT`, 호환 상수 `QUALITY_SUFFIX`
- `UC_PRESET_TEXT`
- `model_id_from_metadata`
- `quality_suffix_text`
- `merge_quality_suffix`, `split_quality_suffix`, `restore_quality_prompt`
- `uc_preset_text`, `merge_uc_preset`, `split_uc_preset`

`legacy_app.py`에는 기존 외부 호출과 회귀가 같은 이름을 계속 쓸 수 있도록 명시적
호환 import만 남긴다.

### 이동하지 않을 것

- UI HTML·JavaScript와 저장 형식
- `annotate_nai_comment`와 Request ID·Payload Hash·계보 기록
- sampler·scheduler·해상도·V3 파라미터 정책
- 실제 payload 조립과 HTTP 호출
- 공식 Quality·UC 문구와 모델 표시명

### 완료 조건

- 모델 표시명·Source 문자열 해석 결과가 기존과 동일하다.
- Quality 태그의 합치기·분리·복원 결과가 바이트 동일하다.
- UC 프리셋의 합치기·분리 결과가 바이트 동일하다.
- 기존 `APP.<이름>` 호출과 import가 깨지지 않는다.
- `legacy_app.py`에서 대상 상수·함수 본문만 사라지고 UI·저장·payload diff가 없다.

### 직접 관련 기존 검사

- `test_restore_model_mapping_ignores_source_build_hash_digits`
- `test_quality_and_uc_text_are_model_specific_and_round_trip`
- `test_saved_comment_embeds_quality_and_uc_state_for_exact_restore`
- `tests/architecture/test_module_boundaries.py`
- Python 구문·import와 앱 기동 스모크

새 테스트, 전체 회귀, UI 촬영, 빌드·Release는 하지 않는다.
