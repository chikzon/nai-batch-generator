# 실제 NAI·앱 동작 검증

검증일: 2026-07-29

## 결론

- 실제 NAI 생성 호출 6회와 Vibe 인코딩 1회를 성공했다.
- 처음 5회+인코딩은 총 예상 27 Anlas와 실제 잔액 감소 27 Anlas가 일치했다.
- Outpaint 1회는 2 Anlas 예상으로 성공했다. 이 호출은 직전·직후 잔액을 따로
  측정하지 않았으므로 실제 감소량 일치로 과장하지 않는다.
- AI 자동과 좌표 위치, 28/29 steps 비용 경계, Vibe, Precise Reference가 실제
  NAI 응답과 PNG 메타데이터로 확인됐다.
- Base·Negative·캐릭터별 Prompt·Negative·좌표·해상도·Seed·Steps·Sampler·CFG
  계열 값은 우리 단건 임포트에서 복원됐다.
- Vibe와 Precise Reference 동시 사용을 허용하던 차이를 발견해 UI와 전송 직전에
  차단했다. 어느 쪽 자료도 자동으로 끄거나 삭제하지 않는다.
- 비교 앱에서 채택한 데스크톱 골격은 상당 부분 통합됐지만 **모든 기능 흡수 완료는
  아니다.** 미구현·후속 항목은 아래에 분리했다.

## 실제 유료·무료 호출

| 시험 | 실제 결과 | 예상/실제 Anlas | 시간 |
|---|---|---:|---:|
| AI 자동, 832×1216, 28 steps | 성공, 두 캐릭터 분리 | 0 / 0 | 6.742초 |
| 좌우 좌표 0.25/0.75, 같은 Seed | 성공, 좌표가 메타데이터에 보존 | 0 / 0 | 5.608초 |
| 좌우 좌표, 29 steps | 성공 | 20 / 20 | 4.448초 |
| Vibe 인코딩+생성 | 인코딩·생성 성공, Vibe 1개 기록 | 2 / 2 | 1.835+7.917초 |
| Precise Reference 1개 | 1024×1536 레터박스·생성 성공 | 5 / 5 | 7.511초 |
| Outpaint 좌우 64px | 256×256 원본 보존, 384×256 바깥 생성 성공 | 예상 2 / 미측정 | 별도 1회 |

증거: `ai-review/live-nai-2026-07-29/metrics.json`,
`ai-review/live-nai-2026-07-29/outpaint-metrics.json`, PNG 6장.

## PNG만으로 복원되는 것과 안 되는 것

복원:

- 최종 Base·Negative
- 캐릭터별 최종 Prompt·Negative·순서·좌표
- Width·Height·Seed·Steps·Scale·CFG Rescale·Sampler·Noise Schedule
- UC Preset·Quality·Variety+·SM·Dynamic Threshold·`use_coords`
- Vibe/Reference 사용 사실과 NAI가 반환한 관련 설정
- Request ID·Payload Hash

PNG만으로는 구분하지 못함:

- 위치판과 자유 좌표는 둘 다 연속 좌표로 전달되므로 `use_coords=true`만 남는다.
- NAI 응답 PNG에 모델명이 없으면 정확한 모델을 이미지 한 장만으로 확정하지 못한다.
- 캐릭터의 외형·착의·예술적 변형이 합쳐지기 전의 편집 칸
- 그림체·캐릭터·세팅의 자산 ID, 단계, 실험 규칙, Job 장부

위 편집 계보는 PNG가 아니라 생성 설계도·Job·결과 manifest가 보존한다.

## 속도·버벅임

| 항목 | 1600×1000 | 390×844 |
|---|---:|---:|
| DOMContentLoaded | 324ms | 336ms |
| 생성 화면 준비 | 673ms | 769ms |
| 상단 화면 전환 | 86~174ms | 103~166ms |
| 작가 조합 첫 열기 | 156ms | 128ms |
| 작가 조합 재열기 | 71~88ms | - |
| 최장 main-thread 멈춤 | 241ms | 283ms |
| 가로 넘침 | 0 | 0 |
| 콘솔·페이지 오류 | 0 | 0 |

치명적인 멈춤은 재현되지 않았다. 첫 실행 때 0.24~0.28초 정도의 짧은 걸림은 남는다.
작가 조합은 첫 응답 약 62KB, 154ms였고 반복 열기에서 DOM이 계속 증가하는 누수는
확인되지 않았다. 결과 목록 API는 백그라운드에서 최대 약 1.33초 걸렸지만 생성 화면
입력은 그 전에 가능했다.

## 비교 기능 통합 판정

현재 통합됨:

- 실제 NAI 생성, 다중 캐릭터, 세 위치 방식, Vibe·Reference,
  img2img·Inpaint·Outpaint, Director, 비용 미리보기
- 단건·다중 이미지 복원, 공개자료 수집, 자료팩·보유 폴더, 500개 단위 메타 감사
- 그림체 묶음, 캐릭터 전체 Prompt, 작가 조합, 조각, Blind ELO·월드컵
- 세팅 단계·옵션·캐스트·순회/동시 출연, 비교 실험, 재개·재시도·한 셀 재생성
- 원자 저장, Job 장부, 결과 계보, 백업·휴지통·자료 분리, 설치본

동등한 큰 엔진에 흡수:

- SceneCast·Composition·Project/Template·Scene Sequence → 생성 설계도와 세팅
- Batch·Rotation·Comparison Group·Tournament → 세팅의 실험 규칙
- Queue·Idempotency·Resume → 공통 Job 실행 계층
- Style Lab·Organizer·ELO·Snapshot → 평가·승격·보존 흐름

아직 미구현·미흡:

- 스마트폰 앱·PC 연동
- blue식 시각적 3-way 충돌 해결과 전체 store snapshot 선택 복원
- SDStudio식 프로젝트 계층·템플릿 상속 편집 화면
- 완성된 캐릭터 이미지 제작 Bench·Reference inset
- 범용 조건 규칙/DSL과 완전한 X/Y 실험 라벨 그리드
- 다중 증거 병합과 weighted prompt 중복 검토 전용 화면
- lossless prompt parser tree·caret 문맥 편집·hover-wheel 미세 조정
- 자동 업데이트·이전 설치 미리보기·확장 API
- 로그인 필요한 공개자료 수집 세션과 대형 archive Range 재개

의도적으로 별도 제품 구조를 복제하지 않음:

- Electron/Tauri/ComfyUI graph 자체
- Marketplace·R2·일반 웹브라우저
- Grok·Gemini·WebUI 등 NAI 밖 생성 백엔드

현재 회귀 통과는 현재 계약의 안정성 증거이지 위 미구현 기능까지 흡수했다는
증거가 아니다.
