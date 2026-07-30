# 현재 작업 — 레거시 축소 단계 5: 최종 호환 facade 마감

## 완료된 단계

- 단계 1 (d778d0e): LEGACY_EXPORTS 247 + endpoint 119·경로·payload 기준선
- 단계 3: wiring 분리 — 조립 74개 이동 (검증에서 누락 3벌 발견 후 보완:
  resource_bridge·file_transaction → library, program_data_migration →
  management). **잔여 조립은 ConfigServer.start 안의 ServerRuntime 2건뿐**
  — 단계 4에서 서버 이동과 함께 처리
  - `wiring/library.py` 33 (자료팩·백업·자료실·수집·빌더)
  - `wiring/generation.py` 13 (NAI 호출·진행·재시도·저장·이미지 도구)
  - `wiring/settings.py` 7 (세팅 저장·씬·프로젝트·캐릭터 파일)
  - `wiring/management.py` 15 (Job·비교·출력·기동)
  - `wiring/routes.py` 8 (late_bound + 바인딩 6벌 + 합류)
  - legacy_surface **5,495 → 4,524줄 (−971)** · 경계 상한 4,600
  - 시험 seam 변경 0 (app=globals() 호출 시점 조회로 monkeypatch 무손상)
- 단계 2는 계획대로 wiring이 context를 받는 형태로 뒤에 수렴 (가정 명시됨)

## 단계 4 진행

- [x] `ConfigServer` 본체 → `web/application_server.py` (namespace 주입,
      서비스는 직접 import·레거시 이름은 호출 시점 조회). legacy에는
      6줄 호환 서브클래스만. `@serialized_data_write`는 같은 잠금 의미의
      with 블록으로 치환. ServerRuntime 조립도 함께 이동 —
      **legacy 잔여 Operations/Paths 조립 0건**
- [x] 4,524 → **4,208줄** (−316). 전체 회귀 171/171 + exports 7 통과
- [x] LiveState·PublicCollectionManager는 계획대로 legacy 어댑터 유지

## 원래 계획 (계획서 단계 4)

1. `ConfigServer` 클래스 본체 → `web/application_server.py`
   - 메서드가 참조하는 레거시 이름들은 생성 시 주입되는 namespace(레거시
     globals())를 통해 해석 — monkeypatch·`_SERVER_MEMBERS` 바인딩 유지
   - legacy_surface에는 `ConfigServer = …` alias만
2. `LiveState`·`PublicCollectionManager` alias 유지 확인 (이미 어댑터 클래스)
3. route 문자열·HTTP 응답 조립이 web/routes 밖으로 안 나왔는지
   ROUTE_BASELINE 계약으로 재확인
4. 검증: 서버 기동 회귀(two_servers·cross-site) · Job·스냅샷 회귀 ·
   exports 계약 · 경계 (do_GET/do_POST ≤40 유지)

## 단계 5 (이 커밋)

- [x] legacy_surface 잔여 구획 색인을 legacy_exports.py에 기록
      (재수출 340줄 · 부트스트랩 280줄 · 셔틀 170개 · adapter ~200개 ·
      클래스 3 · 조립 0건) + **이동 후보 8함수 명시(완료 아님)**
- [x] 상한 4,250 확정 — 줄 압축 없이 역증가만 차단
- 이 커밋이 레거시 축소의 마지막 코드 커밋. 이후: 전체 검증 →
  v1.2.0 재빌드(버전 유지 — 기능 동일·미게시) → 스모크 → 인계서 재생성,
  빌드 뒤 커밋 금지

## 금지 범위

- 기능 삭제·schema 변경·UI 개편 혼합, endpoint 문자열 web 밖 유출,
  성향 표·로그 편집기·사용자 데이터, push·태그·Release
