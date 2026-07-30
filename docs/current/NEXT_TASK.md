# 현재 작업

## 목적

3-way 병합의 기준값 계약을 만든다. 새 백업부터 JSON 항목의 공통 기준값을
백업 ZIP에 함께 보존하고(`baseline/<logical>` + manifest `base_sha256`),
복원 미리보기가 항목마다 `기준/현재/들어오는 값`과 판정
(take-incoming · keep-current · both-changed · no-base)을 제공한다.
구형 백업은 자동 변환 없이 현재 2-way(no-base)를 유지한다.
이미지 등 바이너리는 내용 해시로만 비교하고 baseline에 바이트를 중복 저장하지
않는다.

잔여 계획 단계 1 넷째 조각. `/api/merge_*` endpoint와 UI는 다음 작업.

## 단계

1. `services/merge_plan.py` — 기준값 장부
   (`프로필/.nai-studio/merge-baseline.json`) load/record, 포인터 해석,
   `three_way_decision`.
2. `user_backup_store`:
   - export — 장부에 기준값이 있는 파일은 manifest에 `base_sha256`(+크기)를
     적고 JSON 값은 `baseline/<logical>`로 동봉 (스키마 추가 키만 — 구버전은
     무시하고 읽음).
   - `backup_diff_plan` — 동봉 기준값을 검증해 change마다 `base`·`decision`
     부여 (반환 튜플 모양 유지, plan 행에만 추가).
   - 복원 적용 후 `record_baseline`으로 적용된 파일의 기준값 갱신.
   - `UserBackupOperations`에 `baseline_lookup`·`record_baseline` 선택 필드.
3. 새 compat 모듈 `compat/studio_wiring.py` — legacy_surface 줄 예산(8줄)을
   지키기 위해 baseline 배선 필드를 여기서 조립. legacy에는 import 1줄 +
   전개 1줄만.
4. 새 계약 시험: 구형 백업 no-base 유지 · 적용→기준값 기록 → 재내보내기 동봉 ·
   3-way 판정 4종 · 바이너리 해시 전용 · 구버전 판독 호환.

## 완료 조건

- 기존 백업 미리보기·복원·롤백 회귀 통과. 응답은 추가 키만 늘어난다.
- legacy_surface ≤ 5,500줄.
- 기준값 장부·ZIP에 토큰이 들어가지 않는다 (설정은 이미 secrets 제거 후 내보냄).

## 진행 상태

- [x] `services/merge_plan.py` — 장부·포인터 해석·`three_way_decision`·
      `decision_for_hashes`(바이너리 해시 전용)
- [x] export 동봉(`baseline/<logical>` + `base_sha256`/`base_size`) ·
      `backup_diff_plan` 판정 · 복원 후 `record_baseline`(설정은 토큰 제거)
- [x] `compat/studio_wiring.py` 신설 — legacy_surface에는 import 1줄 +
      전개 1줄 (5,494줄, 여유 6줄)
- [x] 새 계약 시험 6개 · 백업 복구 계약 5/5 · 백업 회귀 4/4 · 경계 5/5

## 금지 범위

- `/api/merge_*` endpoint·UI(다음 작업), 자료팩 쪽 3-way(그다음), 구형 백업
  자동 변환, push·태그·Release
