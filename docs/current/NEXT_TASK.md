# 현재 작업

## 목적

`legacy_app.py:10191-10688`의 `PublicCollectionManager` 책임만
`src/nai_studio/services/public_collection.py`로 옮긴다.

## 현재 경계

- `src/nai_studio/collection/arca.py`: URL 검증, HTML 해석, 네트워크 요청
- `PublicCollectionManager`: 검색·작업 상태·중지/재개·실패 재시도·공통 임포트 조정
- `legacy_app.py`: 기존 이름, 전역 인스턴스, HTTP endpoint의 호환 연결

`arca.py`를 다시 만들거나 임포트·저장 로직을 복제하지 않는다.

## 구현 범위

- 기존 `PublicCollectionManager`를 서비스 모듈로 이동
- 레거시의 이미지 메타데이터 변환, 로컬 이미지 저장, `add_style` 호출은 얇은
  어댑터나 주입된 기존 함수로 연결
- `legacy_app.PublicCollectionManager`, `PUBLIC_COLLECTION`,
  `/api/public_collection*` 호출 경로 유지
- 진행 파일 schema, 기본값, 상태 전이, 오류 문구, 스레드 이름 유지

## 완료 조건

- `legacy_app.py`에서 관리자 구현 본문이 제거되고 호환 연결만 남음
- 공개자료 검색·직접 URL·중지·재개·실패 재시도·새 글/변경/동일 판정 유지
- 진행 파일 손상 시 원본을 덮어쓰지 않는 동작 유지
- 공통 임포트의 원문 Prompt·Negative·이미지·출처·증거 연결 유지
- Python 구문·import·앱 기동 HTTP 200 통과

## 직접 관련된 기존 테스트

- `tests/architecture/test_module_boundaries.py`
- `RegressionTests.test_public_collection_parser_finds_only_matching_nai_posts_and_original_images`
- `RegressionTests.test_public_collection_keeps_original_nai_image_and_whole_prompt_bundle`
- `RegressionTests.test_public_collection_marks_crashed_job_resumable_without_losing_queue`
- `RegressionTests.test_public_collection_detects_new_changed_unchanged_and_retries_only_failed_posts`
- `RestorationInputsContractTests.test_public_collection_keeps_dates_cursor_pause_and_failure_retry`
- `LegacyBridgeContractTests.test_public_collection_projects_to_restore_queue_without_loss`

## 금지 범위

- 공개자료 수집 기능 변경·확장
- UI·HTTP endpoint·사용자 데이터 schema 변경
- `ConfigServer` 또는 생성 오케스트레이션 분리
- 크롤러 재조사, 새 의존성, 새 테스트
- 전체 회귀, 빌드, Release, push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 종료 기록

구현·직접 검증과 같은 커밋에서 이 문서를 실제 결과와 다음 경계 하나로 갱신한다.
