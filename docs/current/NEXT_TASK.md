# 현재 작업

## 목적

백업·자료팩 충돌 검토를 하나의 공통 merge plan 표면으로 통합하는
`/api/merge_preview` · `/api/merge_apply` · `/api/merge_undo` endpoint를 만든다.
기존 preview·apply·undo 엔진(백업 workflow · 자료팩 workflow)에 위임하고,
행 모양만 통일한다({id, source, kind, label, decision, base/current/incoming,
recoverable}). 백업 쪽은 3-way 판정(3f63f15)이 그대로 실리고 자료팩 쪽은
아직 no-base(2-way)다.

잔여 계획 단계 1 다섯째 조각. 기존 `/api/backup_*`·`/api/pack_*`는 그대로 둔다.

## 단계

1. `services/merge_workflow.py` — 행 투영·응답 조립(순수).
2. `web/routes/merge_post.py` — `handle_merge_post(request, application,
   recovery_ops, collection_ops, body)`. 새 Operations dataclass 없이 기존
   두 세트를 재사용 → 새 바인딩·legacy 변경 0줄.
3. `server_runtime._dispatch_post` 맨 앞에 merge 그룹 추가
   (`/api/merge_` 접두는 기존과 충돌 없음).
4. UI: 기존 백업 검사 목록(studio-admin `backupDiffPaint`)에 3-way 판정
   배지 표시 (선택 기본값은 바꾸지 않는다 — 통합 검토 화면은 단계 4에서).
5. 새 계약 시험: 두 소스 preview 행 통일 · apply→undo 핸들 왕복 ·
   잘못된 source 거부 · 비관할 경로 통과.

## 완료 조건

- 기존 backup·pack 회귀 통과 (기존 endpoint 무변경).
- do_GET/do_POST ≤40줄·legacy_surface ≤5,500줄 경계 유지 (legacy 변경 0).
- merge_apply는 preview와 같은 원문·같은 diff 지문일 때만 적용(기존 가드 재사용).

## 진행 상태

- [x] `services/merge_workflow.py` (순수 투영) · `web/routes/merge_post.py`
- [x] `_dispatch_post` 맨 앞 merge 그룹 — 새 바인딩 0 · legacy 변경 0줄
- [x] 백업 검사 목록에 3-way 판정 배지 + 기준값 접기 (기본 선택값 불변)
- [x] 새 계약 시험 6개 · JS 구문 · 경계 5/5 · 관련 회귀 4/4

## 금지 범위

- 자료팩 3-way(다음), 통합 검토 화면 재배치(단계 4), 기존 endpoint 제거·변경,
  push·태그·Release
