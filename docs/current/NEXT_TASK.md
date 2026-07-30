# 현재 작업

## 다음 작업 (단계 5 잔여)

1. 내부 감사 기록을 저장소 밖 보관본에 원본 경로대로 복사(파일 수·SHA-256
   확인) 후 Git 추적에서만 정리 → README·스크린샷·기능 제한·Release 설명을
   실제 최종 화면과 일치.
2. 최종 한 번: 전체 계약·구조·회귀 + JS 구문 + localhost + Python 없는 포터블
   기동 + 설치·제거 + 배포물 토큰/개인 자료 0건 → 재빌드(이후 커밋 금지) →
   Claude push 인계서 재생성.

## 완료 — 업데이트 검사 (이 커밋)

- `services/update_check.py` — `UpdateManager`: 공식 GitHub Release만 확인
  (60초 캐시), status가 새/현재 버전·변경 요약·다운로드 크기를 먼저 표시,
  download는 `SHA256SUMS.txt` 항목과 일치할 때만 완료(강제는 기존
  `archive_download`의 expected_sha256 폐기 규칙), 이미 검증된 파일은 재사용,
  install은 재해시 일치 시에만 installer UI 실행 — 무인 설치 플래그 없음.
  실패·오프라인은 `ok:false + current` 로 현재 버전 유지.
- `/api/update_status·download·install` (runtime_post) + 관리 탭 갱신 카드
  (environment 그룹) + `bindUpdateCard`. 바인딩은 studio_wiring(legacy 0줄).
- `CURRENT_VERSION == tools.build.app.APP_VERSION` 계약 시험으로 고정.
- 새 계약 시험 10개 · 페이지 id 중복·레이아웃 회귀 2/2 · 경계 5/5 ·
  template 91,828/100,000자.

## 완료 — UI 성능·반응 목표 측정 (단계 4 마감, 이 커밋)

빈 사용자 데이터 · `--data-dir` 임시 폴더 · 포트 8788 인스턴스(사용자 8787
불간섭, 측정 후 종료·폴더 삭제). 실브라우저 실측:

| 목표 | 실측 | 판정 |
|---|---|---|
| 초기 화면 준비 ≤ 1초 | load 762ms · DOMContentLoaded 372ms | ✓ |
| 탭 전환 ≤ 200ms | 첫 진입 최대 18.8ms(세팅) · 이후 ≤1ms | ✓ |
| 작가 조합 첫 열기 ≤ 200ms | 4.9ms | ✓* |
| 390×844 가로 넘침 0 | 5개 탭 전부 scrollW==390 | ✓ |
| 반복 진입 DOM 증가 0 | 10사이클×5탭: 1,649 → 1,649 (+0) | ✓ |
| 1280×800 · 1600×1000 넘침 | 0 · 0 | ✓ |
| 키보드 Alt+1~5 | Alt+3→자료, Alt+1→생성 전환 확인 | ✓ |
| 콘솔 오류 | 0건 | ✓ |

\* 한계: 빈 데이터라 작가 조합 목록이 비어 있어 하한값이다. 실자료(수백 건)
에서는 `loadCombos`가 지연·중단 가능 구조라 목록 렌더가 지배 — 실자료 측정은
사용자 환경(8787)에서만 가능해 생략했다.

## 금지 범위

- 사용자 8787 인스턴스·개인 자료 접근, push·태그·Release
