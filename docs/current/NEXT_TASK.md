# 현재 작업

## 다음 작업 (단계 4 시작)

계획서 단계 4 — 실제 생성 검증·UI 2차 개선. 순서:

1. **relay 사용자 연결 마감(소품)**: 관리 또는 자료 탭에 pairing code 발급
   버튼 + arca.live에서 쓸 bookmarklet/userscript 문안 표시(복사 버튼).
   서버 쪽(`/api/public_collection_pairing`·`_relay`)은 완성 상태다.
2. **캐릭터 Bench 실제 NAI 검증**: Character Reference·Reference inset을
   현재 생성 요청 사본으로 실검증. 저장 설정 불변, 비용 preview 후 실행,
   **총 예산 최대 20 Anlas**. 결과 PNG·payload hash·request ID·예상/실제
   비용·원본 무변경 확인. ⚠ 실제 과금 — 실행 직전 비용을 보고하고 진행.
3. **UI 2차**: 자료 충돌·증거 병합·수집 진행을 자료 탭 하나의 검토 흐름으로
   배치(이미 완성된 merge/relay/archive endpoint 소비). 상단 순서
   `생성→세팅→자료→빌더→관리` 유지, 기존 테마·DOM id·endpoint 보존.
   목표: 초기 1초, 탭 전환 200ms, 작가 조합 첫 열기 200ms, 390px 가로 넘침 0,
   반복 진입 DOM 증가 0.

## 완료 조각 3 — arca.live browser relay (이 커밋)

- `services/collection_relay.py`: RelayPairing(매 발급마다 이전 code 무효,
  hmac 비교) + 전달 자료 검증(Origin=arca.live·HTML 4MB·이미지 40개·
  각 64MB·content-type↔magic 일치)
- `PublicCollectionManager.relay_article` — 네트워크 없이 기존 수집 계약
  (`_ingest_image_bytes` 공유)으로 투입, 진행·중복 판정·증거 기록 동일
- transport 최소 예외: `_trusted_post`가 relay 경로+arca Origin만 통과,
  `do_OPTIONS` preflight(CORS·Private Network Access)는 relay 경로 전용,
  응답 ACAO는 relay 요청에만. pairing 발급은 localhost 전용 유지
- 시험 10개: pairing 재발급 무효·왕복 unchanged 수렴·Origin/code 거부·
  비허용 URL·magic 불일치·개수 상한·transport 3종

## 금지 범위

- 쿠키·비밀번호 저장, relay Origin 확대, 기존 태그·Release·push
