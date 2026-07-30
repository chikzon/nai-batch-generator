# 현재 작업

## 다음 작업 (단계 4 잔여 + 단계 5)

1. **UI 성능·반응 목표 측정**(단계 4): 초기 1초 · 탭 전환 200ms ·
   작가 조합 첫 열기 200ms · 390px 가로 넘침 0 · 반복 진입 DOM 증가 0.
   1600×1000·1280×800·390×844 화면과 키보드 조작 확인.
2. **단계 5**: 업데이트 검사(`/api/update_status·download·install`,
   GitHub Release만·SHA256SUMS 일치 시만·무인 설치 금지) → 내부 감사 기록
   보관·README/스크린샷 정합 → 최종 전체 회귀·재빌드·Claude 인계서 재생성.

## 완료 — 캐릭터 Bench 실제 NAI 검증 (이 커밋)

임시 `--data-dir` + 포트 8788에서 실행. 사용자의 8787 인스턴스와 개인 자료는
건드리지 않았다. 토큰은 임시 폴더에만 있었고 검증 뒤 폴더를 삭제했다.

| 항목 | Reference inset (infill) | Character Reference |
|---|---|---|
| 예상 비용 | 8 Anlas | 5 Anlas |
| 실제 차감 | 8 (1차 실행분·잔액 대조 유실) | **5 (6,956→6,951 실측)** |
| 결과 PNG | `output/Reference inset/0001.webp` 40,274B | `output/단독/0001.webp` 127,860B |
| request ID | `nai-request-5f5019f6…f30152` | `nai-request-bf7958ba…46fb4c` |
| payload hash | `9fc8d3ae…75ccf6fa` | `e6a95156…819a30117` |
| 전송 확인 | 512×768·28스텝·시드 31337 | `director_reference_strengths=[0.6]`·`_information_extracted=[1.0]` |
| 메타데이터 | `ok` (계보 3키 기록됨) | `ok`·시드 424242 복원 |

- 총 지출 13 Anlas (예산 20 이내). 저장 설정·원본 이미지 SHA-256 불변 확인.
- 문서의 "캐릭터 레퍼런스 참조 1개당 장당 5 Anlas + Opus 무료 생성 유지"가
  실측으로 재확인됐다(생성 0 + 참조 5).

## 실검증에서 찾은 제품 결함 2건 (같은 커밋에서 수정)

`bd9b578`부터 있던 결함 — **모든 바이너리 업로드 POST가 500 오류로 죽었다**
(`/api/ref_add`·`/api/pack_preview`·`/api/backup_restore` 원문 업로드 등).
POST 디스패치가 recovery→collection 순서인데 두 그룹이 **경로가 맞지 않아도**
본문을 JSON으로 파싱해, 첫 그룹에서 UnicodeDecodeError가 나고 바깥
try/except가 그것을 응답으로 바꿔 뒤 그룹까지 가지 못했다.

- 고침: 두 그룹 모두 **경로가 맞을 때만** `_json_body(body)`를 호출한다
  (`recovery_post._simple_recovery`·`collection_post._public_collection`).
- 회귀 2개 추가: 바이너리 본문이 recovery 그룹을 통과하고 collection의
  `reference_add`에 원문 그대로 도달하는지 확인.
- 나머지 POST 그룹(catalog·fragments·generation·settings·merge)은 자기
  경로가 맞은 뒤에만 파싱하므로 영향 없음(확인).

## 금지 범위

- 사용자 8787 인스턴스·개인 자료·설정 변경, 토큰 저장, push·태그·Release
