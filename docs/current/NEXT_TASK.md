# 현재 작업

## 목적

잔여 계획 단계 2 첫 조각 — 증거·지식 정제 작업면의 공통 병합 서비스.
기존 `merge_style_evidence`(style_store) · `merge_evaluations`(domain/evaluation) ·
`merge_resources`(domain/resources)를 한 병합 서비스에서 쓰도록 묶고,
자료실의 중복 후보(find_style_dupes 결과)를 나란히 비교하는 데 필요한
자료(원본 이미지·출처·메타데이터·생성 설정·평가)를 한 응답으로 투영한다.

## 원칙 (계획서 단계 2)

- 사용자가 대표 자산을 선택하거나 증거만 합친다. 원본 자산 자동 삭제 금지.
- weighted prompt는 원문 그대로 유지, 공통·좌측 전용·우측 전용 구간만 비교
  표시. 자동 의미 병합·prompt 재작성 금지. 최종 원문은 사용자가 확정.
- 기존 caret 가중치 버튼·무손실 저장 유지.
- parser tree·hover-wheel·범용 DSL은 구현하지 않는다 (결함 근거 없음).

## 참고 (단계 1 완료 상태 — 커밋 9470efd·3c36d5c·56ee240·3f63f15·5e9eb93)

- 파일 트랜잭션 journal 경계 + 자료팩 staging + 백업 복원 기동 복구
- 3-way 기준값 (백업 왕복) + `/api/merge_preview·apply·undo` 공통 표면
- 남긴 것: 자료팩 쪽 3-way(기준값 장부 연계), 통합 검토 화면 배치(단계 4),
  가져온백업/트랜잭션 backup 이중 보관 정리(후보)
- ⚠ legacy_surface 5,494/5,500줄 — 새 배선은 전부 `compat/studio_wiring.py`에

## 진행 상태

- [x] `services/evidence_merge.py` — 가중치 그룹 보존 구간 분리
      (`prompt_segments`), 공통·좌/우 전용 diff(원문·순서 보존, 가중치 다르면
      공통 아님), 나란히 비교 투영, 대표 자산 증거 병합(원본 비삭제)
- [x] `/api/merge_preview·apply·undo`에 `source="library"` 추가 —
      병합은 기존 자료팩 Undo 장부(list_updates)로 한 판 되돌리기
- [x] `MergePostOperations` + app_wiring `merge_post` 그룹, 바인딩은
      `studio_wiring.extra_route_bindings` (legacy +1줄, 5,495/5,500)
- [x] 새 계약 시험 9+1개 · 경계 5/5 · 서버 기동 포함 회귀 3/3

## 남긴 것

- 나란히 비교·증거 병합의 화면 배치는 계획서 단계 4(자료 탭 통합 검토 흐름)
  에서 연결한다. endpoint·자료 투영은 완성 상태.
- merge_evaluations·merge_resources 연계는 캐릭터 자산 중복 검토가 생기는
  시점(같은 단계 후속)에 이 서비스로 붙인다 — 지금은 호출처가 없다(YAGNI).

## 금지 범위

- 원본 자산 자동 삭제·의미 병합, prompt 재작성, 기존 저장 schema 변경,
  push·태그·Release
