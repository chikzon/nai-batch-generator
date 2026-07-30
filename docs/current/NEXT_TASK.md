# 현재 작업

## 다음 작업 (단계 4 잔여 + 단계 5)

1. **캐릭터 Bench 실제 NAI 검증 — 막힘(사용자 입력 필요)**:
   이 폴더의 설정.json·프로필·설정.txt 어디에도 NAI 토큰이 없어 실호출이
   불가능하다. 사용자가 앱 기타 탭에 토큰을 넣은 뒤(또는 토큰이 있는 프로필
   지정) 재개한다. 예산 최대 20 Anlas, 저장 설정 불변, 결과 PNG·payload
   hash·request ID·예상/실제 비용·원본 무변경 확인. 사용자 승인으로
   비용 보고는 생략 가능.
   ⚠ 포트 8787에 사용자의 구버전 인스턴스가 떠 있다 — 검증은 별도
   `--data-dir` + 뒷포트에서, 그 인스턴스는 건드리지 말 것.
2. **UI 성능·반응 목표 측정**(단계 4): 초기 1초 · 탭 전환 200ms ·
   작가 조합 첫 열기 200ms · 390px 가로 넘침 0 · 반복 진입 DOM 증가 0.
   1600×1000·1280×800·390×844 화면과 키보드 조작 확인.
3. **단계 5**: 업데이트 검사(`/api/update_status·download·install`,
   GitHub Release만·SHA256SUMS 일치 시만·무인 설치 금지) → 내부 감사 기록
   보관·README/스크린샷 정합 → 최종 전체 회귀·재빌드·Claude 인계서 재생성.

## 완료 — 단계 4 조각 1·3 일부 (이 커밋)

- relay 사용자 연결: 자료 탭 수집 카드에 pairing 발급 + arca용 전달 코드
  (bookmarklet) 복사 UI. 실서버 왕복 확인(발급→틀린 code 거부→맞는 code로
  수집 계약 진입→preflight 204+PNA→비허용 Origin 403→일반 endpoint 403 유지).
- 자료 탭 `검토·병합` 패널 신설(data-library-work=review): 겹친 그림체
  찾기(style_dupes)→둘 골라 나란히 비교(merge_preview library)→대표로 근거
  합치기(merge_apply)→한 판 되돌리기(merge_undo) + 큰 자료 받기
  (archive_download_control) + 수집 진행 요약. 기존 카드·DOM id·endpoint
  불변, 새 페이지 91,240자(상한 100,000).
- 빈 데이터 루트 실서버 스모크 + 페이지 JS·중복 id·경계·UI 회귀 4/4 통과.
