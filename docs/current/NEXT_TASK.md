# 현재 작업 — 레거시 축소 단계 4: 서버·실행 수명 이동

## 완료된 단계

- 단계 1 (d778d0e): LEGACY_EXPORTS 247 + endpoint 119·경로·payload 기준선
- 단계 3 (62ec50d~ed18539): wiring 분리 **완료** — 68개 조립 함수 이동
  - `wiring/library.py` 33 (자료팩·백업·자료실·수집·빌더)
  - `wiring/generation.py` 13 (NAI 호출·진행·재시도·저장·이미지 도구)
  - `wiring/settings.py` 7 (세팅 저장·씬·프로젝트·캐릭터 파일)
  - `wiring/management.py` 15 (Job·비교·출력·기동)
  - `wiring/routes.py` 8 (late_bound + 바인딩 6벌 + 합류)
  - legacy_surface **5,495 → 4,551줄 (−944)** · 경계 상한 4,600
  - 시험 seam 변경 0 (app=globals() 호출 시점 조회로 monkeypatch 무손상)
- 단계 2는 계획대로 wiring이 context를 받는 형태로 뒤에 수렴 (가정 명시됨)

## 이 단계에서 할 것 (계획서 단계 4)

1. `ConfigServer` 클래스 본체 → `web/application_server.py`
   - 메서드가 참조하는 레거시 이름들은 생성 시 주입되는 namespace(레거시
     globals())를 통해 해석 — monkeypatch·`_SERVER_MEMBERS` 바인딩 유지
   - legacy_surface에는 `ConfigServer = …` alias만
2. `LiveState`·`PublicCollectionManager` alias 유지 확인 (이미 어댑터 클래스)
3. route 문자열·HTTP 응답 조립이 web/routes 밖으로 안 나왔는지
   ROUTE_BASELINE 계약으로 재확인
4. 검증: 서버 기동 회귀(two_servers·cross-site) · Job·스냅샷 회귀 ·
   exports 계약 · 경계 (do_GET/do_POST ≤40 유지)

## 그 다음 (단계 5)

- legacy_surface = 명시적 export map + 최소 adapter만. 남은 각 구획의
  호환 이유를 legacy_exports.py kind에 반영, 상한 대폭 하향
- 마지막에만 전체 계약·구조·회귀 + JS + localhost + 포터블·설치본 재검증

## 금지 범위

- 기능 삭제·schema 변경·UI 개편 혼합, endpoint 문자열 web 밖 유출,
  성향 표·로그 편집기·사용자 데이터, push·태그·Release
