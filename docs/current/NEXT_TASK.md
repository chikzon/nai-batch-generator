# 현재 작업

## 목적

중단된 백업 복원을 기동 시 수렴시킨다. 복원 journal(`복원기록/<batch>/journal.json`)
이 `ready`·`applying` 상태로 남아 있으면 다음 기동에서 before/ 백업으로 전체
되돌리고 기존 시작 복구 배너로 알린다. 복원 journal에는 적용할 새 내용이 없어
이어서 완료할 수 없으므로 되돌리기가 유일한 수렴 방향이다.

잔여 계획 단계 1의 셋째 조각 — 이것으로 shared_data_transaction · 자료팩
journal(9470efd·3c36d5c) · 백업 복원 journal이 하나의 기동 crash-recovery
경계에 모인다.

## 단계

1. `user_backup_store.recover_unfinished_restores(paths, operations)` —
   기존 `_rollback_operations` 재사용, `rolled_back`+`startup_recovery` 표시,
   사용자 수정 파일은 기존 규칙대로 보존(skipped).
2. legacy `recover_pending_file_transactions`를 두 복구(파일 트랜잭션 + 백업
   복원)를 도는 루프로 바꾼다. 실패는 경고만 남기고 기동을 막지 않는다.
3. 새 계약 시험: applying 중단 복원 되돌리기 · ready 무적용 수렴 ·
   complete/rolled_back 무간섭 · 사용자 수정 파일 보존.

## 완료 조건

- 기존 백업 복원·롤백 회귀 통과. 복원 journal schema 유지(추가 키만).
- legacy_surface ≤ 5,500줄 유지.

## 진행 상태

- [x] `recover_unfinished_restores` (기존 `_rollback_operations` 재사용)
- [x] legacy 복구 루프 통합 (파일 트랜잭션 + 백업 복원)
- [x] 새 계약 시험 5개 (`test_backup_restore_recovery_contract.py`)
- [x] 백업 회귀 5/5 · legacy_surface 5,492줄 (여유 8줄)

## 다음 배선 경고

**legacy_surface 여유가 8줄뿐이다.** 이후 작업(병합 endpoint·수집·갱신)의
배선·라우트 바인딩은 반드시 새 compat 모듈에 두고 legacy_surface에는
한 줄 연결도 최소화한다.

## 금지 범위

- 복원 로직 재작성, 3-way 병합(다음 작업), push·태그·Release
