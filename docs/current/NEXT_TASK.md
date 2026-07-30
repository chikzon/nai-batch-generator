# 현재 작업

## 목적

자료팩 설치를 파일 트랜잭션 경계(staging→검증→파일별 교체, journal) 경유로
전환한다. 설치 도중 중단돼도 다음 기동에서 이어서 완료하거나 전체 되돌아간다.
기존 자료팩 미리보기·충돌 선택·가져온백업·pack log·Undo 동작은 그대로 유지한다.

잔여 계획 단계 1의 둘째 조각. (첫째 조각 = 커밋 9470efd 파일 트랜잭션 경계)

## 단계

1. `datapack_store`: 설치 중 대상 파일 쓰기를 staging으로 돌리는 래퍼
   (`_staged_operations`) — base_dir 안 대상만, `수집/가져온백업`·`.nai-studio`는
   즉시 쓰기 유지. 같은 트랜잭션에서 방금 stage한 파일의 재읽기는 staged 내용을
   반환.
2. `_import_datapack_bytes`: begin → 기존 설치 로직(쓰기는 staging) → commit →
   pack log. batch 기록에 `transaction` id를 남긴다(추가 키, schema 유지).
3. `DatapackOperations`에 `replace` 필드(기본 os.replace) 추가 — 실패 주입
   시험용. 기존 생성자는 legacy_surface 한 곳뿐이라 기본값으로 흡수.
4. `merge_list_json`: 디스크 exists() 대신 load 실패(FileNotFoundError)를 빈
   목록으로 처리해 staged 재읽기와 호환 (정상 경로 동작 동일).
5. 새 계약 시험: 자료팩 설치 crash 주입 → 재기동 복구로 전부 반영/전부 원상 수렴,
   커밋 전 실제 파일 무변경, pack log·Undo 왕복 유지.

## 완료 조건

- 기존 자료팩 관련 회귀(미리보기·설치·undo·manifest) 통과, 응답 형식 불변.
- 설치 중단 시 사용자 자료가 절반만 바뀐 채 남지 않는다.
- legacy_surface 추가 줄 0 (배선 불필요 — 주입된 경계 재사용).

## 진행 상태

- [x] `_staged_operations` · `_stage_rel` · `_transaction_boundary`
- [x] `_import_datapack_bytes` staging→commit 전환, batch에 `transaction` id
- [x] `DatapackOperations.replace` 기본값 필드 (생성자 legacy 한 곳 — 변경 없음)
- [x] 새 계약 시험 5개 (`test_datapack_transaction_contract.py`)
- [x] 자료팩 회귀 8/8 통과 · legacy_surface 변경 0줄

## 알려진 비용

- 커밋된 설치의 prior 백업이 `가져온백업/`(pack Undo용)과 트랜잭션 `backup/`
  (journal 복구용) 두 곳에 남는다. 병합 통합 작업에서 하나로 합칠 후보.
- merge_list_json은 디스크 exists() 기준을 유지 — 한 ZIP에 같은 이름 파일이
  두 번 들어간 기형 자료팩은 뒤의 것이 이긴다(주석으로 명시).

## 금지 범위

- 자료팩 schema·HTTP 응답 변경, 백업 경로(다음 작업)·병합 UI(그다음) 선행 구현
- push·태그·Release
