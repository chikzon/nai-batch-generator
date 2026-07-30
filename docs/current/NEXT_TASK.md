# 현재 작업

## 다음 작업 (단계 3 셋째 조각)

arca.live 전용 browser relay — 로그인 자료를 쿠키·비밀번호 저장 없이
브라우저가 직접 localhost로 전달한다.
- `/api/public_collection_pairing`: 매 실행 1회용 pairing code 발급
- `/api/public_collection_relay`: code + 허용 Origin(arca.live) + 크기 제한 +
  CORS/Private Network Access 검증 후, 사용자가 고른 게시물의 HTML·이미지
  바이트만 수신 → 기존 공개자료 복원 큐·증거 계약으로 투입 (별도 저장 체계
  금지, 기존 `_import_article` 경로 재사용)
- ⚠ http_server의 POST 신뢰 검사(_trusted_post)는 localhost Origin만 허용
  한다 — relay는 브라우저(외부 Origin)에서 오므로 이 두 경로만 pairing code
  검증으로 예외를 열어야 한다. 예외는 최소·명시적으로.

## 완료 조각 2 — /api/archive_download_control (이 커밋)

- `ArchiveDownloadManager` — 한 번에 하나, 시작 전 URL 검증, 중지 시
  resumable, 상태 조회는 sidecar가 진실, 파일명 탈출 거부
- collection_post 라우트 + studio_wiring 바인딩 (legacy 0줄)
- 시험: 매니저 4개 + 라우트 1개. UI는 단계 4 검토 흐름에서.

## 원래 목적 (첫 조각 — 완료 dd9ad41)

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

## 진행 상태

- [x] `services/archive_download.py` — `.part` + sidecar
      (`nais-archive-download/v1`), 이어받기 조건(URL·ETag/Last-Modified·
      크기·부분 SHA-256 전부 일치), checkpoint 초과분 truncate 회수,
      Range 미지원(200)·검증 실패 206은 처음부터, redirect 각 단계
      HTTPS·공인 주소 재검증, 크기 상한, 중지 시 재개 가능 상태 저장,
      완료 시 기대 SHA-256 검증 후 원자 교체
- [x] 새 계약 시험 10개 (정상·중단 재개·ETag 변경·Range 미지원·변조 .part·
      크기 상한·해시 불일치 폐기·주소 차단·redirect 차단·중지)
- 네트워크 예외는 호출자에게 전파 — 다음 조각의
  `/api/archive_download_control`이 잡아 resumable로 보고한다.

## 금지 범위

- 쿠키·비밀번호 저장, HTTP 평문 허용, 기존 수집 흐름 재작성,
  push·태그·Release
