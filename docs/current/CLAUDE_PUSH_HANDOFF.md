# Claude 공개 저장소 정리·push 인계

## 목적

현재 프로그램 동작과 README·스크린샷·현재 문서를 일치시킨 뒤, 제품 실행에 필요하지
않은 내부 감사 자료와 과거 증거를 공개 저장소에서 걷어낸다. 자료는 먼저 저장소 밖에
보관하며 사용자 파일을 삭제하지 않는다.

현재 `v1.1.0` 태그와 Release는 이미 게시됐고 CI도 통과했다. 이번 작업은 현재
`main`의 설명과 파일 구성을 정리하는 작업이다. 기존 태그·Release·첨부파일은
수정하거나 다시 만들지 않는다.

## 절대 순서

1. `git status -sb`, `git rev-parse HEAD`, `git rev-parse origin/main`을 기록한다.
2. 추적 파일을 `제품 필수 / 개발·검증 필수 / 내부 작업 기록 / 재생성 산출물 /
   사용자 자료`로 분류한다.
3. 제거 후보는 먼저 저장소 밖의
   `../ai-review/보관/github-public-cleanup-2026-07-29/`에 원본 경로 그대로
   복사하고 파일 수와 SHA-256을 확인한다.
4. 보관이 확인된 내부 기록만 Git 추적에서 제거한다.
5. README와 남기는 문서의 링크·버전·기능명·이미지를 현재 실행 화면과 대조한다.
6. 파일 정리 커밋을 만든 뒤 관련 최소 검증만 실행한다.
7. `main`을 push하고 원격 HEAD 일치와 smoke CI 성공을 확인한다.
8. GitHub 웹의 루트·README·Actions·Releases를 확인해 현재 공개 화면에 내부 기록,
   끊어진 링크, 낡은 이미지가 남지 않았는지 보고한다.

## 정리 기준

### 공개 저장소에 유지

- `.github/` — CI와 Release 자동화
- `src/`, `start.py`, `arca_public_import.py` — 실행 소스
- `tests/`, `contracts/` — 핵심 계약과 회귀 검증
- `tools/`, `빌드.py`, `배포준비.py`, `검증.py` — 개발·배포 도구
- `requirements.txt`, 실행 배치 파일
- `규격.json`, `옵션.json`, `후보사전.json` 등 실행에 필요한 기본 구조 자료
- `README.md`, `LICENSE`, `CREDITS.md`, `THIRD_PARTY_NOTICES.md`
- `docs/product/screenshots/` — README가 실제로 사용하는 현재 화면
- `docs/architecture/` — 현재 구조를 설명하며 소스와 일치하는 문서
- 앱 아이콘 원본

파일 수가 많다는 이유만으로 `tests`, `contracts`, `src` 모듈을 합치거나 삭제하지
않는다. 이는 중복 파일이 아니라 제품과 데이터 보존을 검증하는 책임 단위다.

### 저장소 밖에 보관한 뒤 Git 추적에서 제거할 우선 후보

- `ai-review/**` — 내부 NAI 실측 화면, UI 검증 화면, 성능 측정 JSON
- `docs/evidence/**` — 이미 끝난 이동·분리 과정의 역사 증거
- `docs/current/LIVE_NAI_VERIFICATION_2026-07-29.md`
- `docs/current/WORKSPACE_AND_REFERENCES.md`
- 이 작업이 끝난 뒤의 `docs/current/CLAUDE_PUSH_HANDOFF.md`

`docs/current/INDEX.md`, `NEXT_TASK.md`, `OPEN_QUESTIONS.md`와 `AGENTS.md`는 새
세션 진입점으로 남길 수 있지만, 공개 GitHub에서 열리지 않는 `../ai-review` 링크와
끝난 Release 지시를 제거하고 현재 사실만 짧게 남긴다.

### 절대 추가·삭제하지 않음

- untracked `디자인 시스템.html`
- untracked `출력 테마 디자인 가이드.html`
- `수집/`, `설정.json`, `상태.json`, `프로필/`, `output/`, 개인 캐시와 토큰
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 문서 불일치 수정

- README의 네 화면은 `v1.1.0` 실제 UI여야 한다.
- 첫 실행 이미지는 개인 자료가 들어 있는 화면이 아니라 빈 격리 데이터에서 촬영한다.
- 현재 상단 순서는 `생성 → 세팅 → 자료 → 빌더 → 관리`로 통일한다.
- `v1.1.0` Release가 이미 공개됐다는 사실과 첨부파일 4개를 기준으로 적는다.
- NAIA2 로컬 참고 사본이 없다는 옛 문구를 남기지 않는다.
- `dist`가 낡았거나 Release가 미실행이라는 옛 기록을 현재 상태처럼 남기지 않는다.
- 공개본의 모든 Markdown 링크와 이미지 경로가 저장소 안에서 열리는지 확인한다.

## 검증 범위

문서·이미지·내부 기록 정리이므로 전체 회귀와 새 테스트를 실행하지 않는다.

- `git diff --check`
- README Markdown 이미지 4개 존재·PNG 판독
- 남은 Markdown 상대 링크의 대상 존재 확인
- `git ls-files`에 `dist/`, `build/`, `output/`, `수집/`, 개인 설정·토큰이 없는지 확인
- 앱 소스가 바뀌지 않았음을 `git diff --name-only`로 확인
- push 뒤 기존 smoke workflow 성공 확인

소스나 실행 경로를 건드린 경우에만 Python 구문·관련 테스트·앱 기동 스모크를
추가한다.

## GitHub 정리 범위

- 현재 `main`의 파일 구성과 README를 정리한다.
- 기존 커밋 역사, `v1.0.0`, `v1.1.0` 태그와 Release는 보존한다.
- `git filter-repo`, 강제 push, rebase, reset으로 과거 기록을 지우지 않는다.
- 과거 역사까지 완전히 제거하는 일은 별도 사용자 승인 없이는 하지 않는다.
- 정리 커밋을 일반 push한 뒤 GitHub 기본 화면과 CI만 확인한다.

## 완료 보고

- 정리 전후 추적 파일 수와 저장소 크기
- 보관 위치, 보관 파일 수, SHA-256 확인 결과
- Git 추적에서 빠진 경로
- 유지한 경로와 유지 이유
- 수정한 문서 불일치
- 끊어진 링크 0건 여부
- push한 커밋, 원격 HEAD, smoke CI 결과
- 기존 Release·태그가 변경되지 않았다는 확인
