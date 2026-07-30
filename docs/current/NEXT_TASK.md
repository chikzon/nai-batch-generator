# 현재 작업

## 목적

잔여 계획 단계 3 첫 조각 — 대형 archive 다운로드의 HTTP Range 재개.
`.part` 파일과 sidecar 상태(JSON)로 중단 지점을 기록하고,
URL·ETag·Last-Modified·받은 크기·예상 크기·SHA-256이 일치할 때만 이어받는다.
서버 내용이 바뀌면 처음부터 다시 받는다.

## 원칙 (계획서 단계 3)

- HTTPS만 허용. loopback·사설망 주소·위험한 redirect 차단.
- sidecar 계약은 versioned download state로 제한 (기존 자산 schema 불변).
- 새 endpoint `/api/archive_download_control`은 이 조각 뒤에 붙인다.
- 로그인 자료 browser relay(`/api/public_collection_pairing`·`_relay`)는
  다음 조각 — pairing code·허용 Origin·크기 제한·CORS 검증 포함.

## 참고 (진행 상태)

- 단계 1 완료: 9470efd·3c36d5c·56ee240·3f63f15·5e9eb93
- 단계 2 첫 조각 완료: b504280 (`/api/merge_*` source=library, evidence_merge)
- 단계 2 남긴 것: 비교·병합 화면 배치(단계 4에서), merge_evaluations·
  merge_resources 연계(캐릭터 중복 검토가 생길 때)
- ⚠ legacy_surface 5,495/5,500줄 — 새 배선은 `compat/studio_wiring.py`
  (`extra_route_bindings`가 이미 라우트 바인딩에 합쳐진다)
- 새 라우트 그룹 추가 절차(선례): routes 모듈 + Operations dataclass →
  app_wiring `_OPERATION_TYPES` → server_runtime dispatch → 바인딩은
  studio_wiring. legacy 변경 0~1줄.

## 검증 (계획서)

- 정상 Range · Range 미지원 서버 · ETag 변경 · 중단 재개 · 잘못된 Origin ·
  대용량 제한. 기존 공개자료 수집 회귀(pause·resume·변경 판정) 유지.

## 금지 범위

- 쿠키·비밀번호 저장, HTTP 평문 허용, 기존 수집 흐름 재작성,
  push·태그·Release
