# 현재 작업

상태: **대기 — 다음 코드 작업**

## 목적

현재 결과 활용 도구에 NovelAI Outpaint를 추가한다.

`생성 결과 → 캔버스 확장 방향·크기 선택 → 바깥 영역만 생성 → 원본과 결과 계보 보존`

## 근거

- 실제 NAI·비교 프로그램 재감사에서 확인된 데스크톱 핵심 미흡 항목
- 현재 img2img·Inpaint·Director와 같은 “결과를 다음 생성으로 보내는 흐름”에 속함
- 별도 상단 기능을 만들지 않고 생성 화면의 결과 활용 도구에 통합

## 완료 조건

- 상·하·좌·우 확장 크기와 최종 해상도를 생성 전에 확인한다.
- 원본 영역은 보존하고 확장 영역만 mask/infill payload로 보낸다.
- 비용 미리보기, 직렬 NAI 호출, 중지·오류, Request ID·Payload Hash·설계도 계보를
  기존 실행 계층으로 처리한다.
- 결과를 다시 img2img·Inpaint·Reference·Vibe·Outpaint에 보낼 수 있다.
- 저장·재열기 뒤 원본과 확장 설정이 유지된다.
- 직접 관련 기존 테스트를 확장하고 실제 소액 호출 1회로 검증한다.

## 금지 범위

- 독립 Outpaint 프로그램 또는 새 상단 탭
- 사용자 이미지·설정 자동 변환
- `legacy_app.py` 대규모 재작성
- 스마트폰 구현
- GitHub push·Release·태그
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 이후 남은 데스크톱 고도화

아래는 이번 한 작업에 섞지 않는다.

- 시각적 3-way 충돌 해결과 전체 snapshot 선택 복원
- 프로젝트 계층·템플릿 상속 편집
- 완전한 6칸 Organizer
- 캐릭터 제작 Bench·Reference inset
- 범용 조건 DSL·완전한 X/Y 라벨 그리드
- 다중 증거 병합·weighted prompt 중복 검토
- 정밀 prompt parser/caret 편집
- 자동 업데이트·이전 설치 미리보기·확장 API
