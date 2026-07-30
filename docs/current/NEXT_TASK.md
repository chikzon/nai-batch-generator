# 현재 작업

## 목적

여러 파일을 바꾸는 자료 작업(자료팩·백업·병합)이 공유할 재시작 안전 파일 트랜잭션
경계를 만든다. staging에 준비 → 검증 → 파일별 교체로 반영하고, journal에
단계·대상 경로·전후 SHA-256·백업·완료 여부를 남겨 중단 시 다음 기동에서
이어서 완료하거나 전체 되돌린다.

잔여 계획(코덱스 계획서) 단계 1의 첫 조각이다. 자료팩·백업 경로를 이 경계로
옮기는 것과 merge plan·3-way 비교는 다음 작업이다.

## 단계

1. `runtime/file_transaction.py` — begin/stage/commit/rollback/undo/recover.
   다중 파일을 완전 원자로 과장하지 않고, 실패 후 원상 복구 가능한 transaction으로.
2. journal은 `<데이터 루트>/.nai-studio/transactions/<id>/` 아래 journal.json ·
   staging/ · backup/. 대상 경로는 루트 기준 상대경로만 기록하고 토큰·쿠키를 남기지
   않는다.
3. 기동 복구: `load_or_init_config` 진입 시 미완 journal을 검사해
   staged 내용이 전부 검증되면 이어서 완료, 아니면 백업으로 전체 rollback.
   결과는 기존 STARTUP_RECOVERY_NOTICE 배너로 알린다.
4. 새 계약 시험 `tests/contracts/test_file_transaction_contract.py` —
   정상 commit · 파일별 실패 지점 주입 · 재기동 이어서 완료 · staged 손상 시
   rollback · commit 후 한 판 undo · 사용자 수정 파일 보호(충돌 기록).

## 진행 상태

- [x] runtime/file_transaction.py (403줄)
- [x] legacy_surface 배선 + 기동 복구 연결 (`load_or_init_config` 진입 시 복구,
      기존 STARTUP_RECOVERY_NOTICE 배너 재사용, 설정 검역 알림이 우선)
- [x] 계약 시험 11개 (`tests/contracts/test_file_transaction_contract.py`)
- [x] 관련 시험 통과 — 새 계약 11/11 · 설정 검역 회귀 3/3 · 모듈 경계 5/5

## 완료 기록

- `legacy_surface.py` 5,485줄 — 경계 5,500 대비 **여유 15줄뿐**.
  다음 작업부터 새 배선·엔드포인트 연결은 별도 compat 모듈로 뺀다.
- 되돌리기 중단 방향 보존을 위해 journal에 `rolling-back` 상태를 추가했다
  (재기동 시 반영 재개와 되돌리기 재개를 구분).

## 완료 조건

- 중단 지점을 어디에 주입해도 재기동 후 자료가 "전부 반영" 또는 "전부 원상" 중
  하나로 수렴한다 (수렴 불가 항목은 conflict로 기록하고 원본을 보존).
- 기존 저장 schema·endpoint·응답 형식 변경 없음. `legacy_surface.py`는 배선만
  늘고 경계 시험(≤5,500줄)을 넘지 않는다.
- journal·백업에 NAI 토큰이 기록되지 않는다.

## 금지 범위

- 기존 자료팩·백업 경로의 동작 변경(다음 작업에서 연결)
- 사용자 자료 자동 변환·삭제, schema 파괴
- push·태그·Release
