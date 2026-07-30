# 현재 작업 — 캐릭터 자산 중복 검토 (단계 2 잔여 ②)

## 이 커밋

- `/api/merge_preview·apply` source="characters" — ids 없으면 중복
  묶음(캐릭터 묶음 지문 기준), ids 주면 나란히 비교(원문·변형·참조·
  증거·prompt diff), apply는 대표에 **더하기만**(원문·원본 캐릭터
  불변, undo 불필요 설계). 평가는 도메인 merge_evaluations로 병합
  (충돌 목록 동반), 내용 같은 자원 참조는 canonical_resource 지문으로
  알려만 준다(자동 통합 금지). 저장은 기존 sync_chars_to_files·
  save_config 경로.

## 직전 완료 — 자료팩 3-way 기준값 (4c18bc6, 단계 2 잔여 ①)

레거시 축소(단계 1~5)와 스크린샷 재촬영은 마감됐다 — 기록은
`CLAUDE_PUSH_HANDOFF.md`(HEAD f69abc1 기준). 이제 미완 목록을 잇는다.

백업이 쓰는 병합 기준값 장부(`프로필/.nai-studio/merge-baseline.json`,
merge_plan)를 자료팩 검사·설치에 연결한다. 구형 자료팩·장부 없음은
지금처럼 2-way(no-base) 그대로다.

## 단계

1. `DatapackOperations`에 선택 필드 `baseline_lookup`·`record_baseline`
   (기본 None — 기존 생성자·시험 무변경).
2. 검사: 충돌 행마다 장부에서 기준값을 찾아 `base`·`decision`
   (take-incoming·keep-current·both-changed·no-base) 부여.
   - 목록 자산: 장부의 파일 값(list)에서 `datapack_match_key`로 행을 찾음
   - 기본 자료(whole): 장부 값 전체와 비교
   - 장부 키는 백업과 같은 logical(`common/<상대경로>`) — 두 경로가 한 장부
3. 설치: 트랜잭션 커밋 뒤 journal의 대상 파일들을 다시 읽어
   `record_baseline`으로 장부 갱신 (실패는 경고만).
4. 배선: `wiring/library.datapack_operations`가
   `studio_wiring.user_backup_baseline_fields`를 재사용 (legacy 0줄).
5. `merge_workflow.merge_rows_from_datapack`이 conflict의 decision·base를
   공통 행으로 전달 — 자료 탭 검토·병합 패널이 그대로 표시.
6. 계약 시험: 3-way 판정 3종 · 장부 없음 no-base 유지 · 설치→장부 갱신 →
   다음 검사 3-way 왕복.

## 진행 상태

- [x] 전 단계 완료 — 자료팩 계약 8/8(신규 3-way 3) · merge endpoints 7 ·
      merge baseline 6 · 자료팩·서버 회귀 6/6 · exports 7 · 경계 5

## 그 다음 미완 (순서)

② 캐릭터 자산 중복 검토(merge_evaluations·merge_resources 연계)
③ arca bookmarklet 문안 ④ 실자료 UI 성능 측정 ⑤ 레거시 이동 후보 8함수

## 금지 범위

- 자료팩 schema·기존 2-way 응답 형식 변경(추가 키만), 구형 장부 자동 변환,
  push·태그·Release
