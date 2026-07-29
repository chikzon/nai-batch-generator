# Claude push 인계

최신 `main`은 실제 NAI 검증까지 끝난 안정 기준점이지만, 외부 기능 재감사에서
Outpaint 등 남은 데스크톱 항목이 확인됐다. 사용자가 현재 기준점을 먼저 공개하라고
명시하지 않는 한 **아직 push하지 않는다.** 다음 작업은 `NEXT_TASK.md` 한 건씩 진행한다.

## 최종 구현

- 단건·자료팩·공개 수집·보유 폴더 감사를 복원 후보/증거 흐름으로 연결
- 외형·착의·negative·variant·Reference·Vibe·좌표의 무손실 캐릭터 경로
- 순회/동시 출연 캐스트, 캐릭터×세팅과 사용자 선택 실험
- 클릭 시점 생성 snapshot, 직렬 실행, Job 저장·중단·재개·재실행
- 실제 payload/이미지 SHA/request ID/blueprint 지문을 결과와 승격 장부에 연결
- 생성 화면을 프롬프트·네거티브·조각·캐릭터·레퍼런스·생성 설정 순으로 정돈하고
  비용 확인을 생성보다 먼저 배치
- 캐릭터 위치 `AI 자동 / 위치판 / 좌표`를 생성 슬롯·세팅 캐스트·저장·재열기·payload에
  같은 의미로 연결하고 위치판 키보드 조작 지원
- 보유 폴더 페이지 탐색, 메타데이터 감사 후보의 안전한 저장, 결과 도구 단일 열기,
  접힌 출력 설정과 모바일 32px 위치판
- 세팅·씬·비교 완료 파일의 내용 해시 검증과 Job 계보 backfill. 계보·재개 장부가
  실패한 결과를 완료로 오인하거나 같은 유료 요청을 즉시 반복하지 않음
- 50건 이후 메타데이터 후보 UI, strict 키가 하나라도 있는 손상 결과의 구형 fallback
  차단. strict 식별자가 전혀 없는 진짜 구형 결과만 자산 저장 호환·장부 미기록

대표 커밋:

- `0f4917d` 실제 NAI 비용과 레퍼런스 동작을 검증한다
- `9f39a59` 생성 설계도 흐름과 데스크톱 작업실을 완성한다
- `3e379fa` 실행 설계도와 결과 계보의 손실 경계를 닫는다
- `e277461` 승격 장부에서 서로 다른 캐릭터 내용을 보존한다
- `523750d` 생성 설계도와 증거 감사를 실제 화면에 잇는다
- `a0e1a7d` 선택 실험 leaf의 seed와 캐스트 계보를 고정한다

## 검증 결과

- `python 검증.py`: 계약 **10/10**, 모듈 경계 **3/3**, 무과금 회귀
  **168/168 통과**
- 최종 EXE 직접 기동: `/`, `/ui/studio.css` HTTP 200. 최신 위치 UI와
  프롬프트 도구 마크업 포함 확인
- 실제 브라우저: 1600×1000·390×844 가로 넘침 0, 편집 도구 겹침 0,
  위치 모드·키보드 이동·캐스트 지연 렌더·결과 도구·클래식 호환 확인
- 개인 토큰 정규식 검사: 배포 폴더 0건. 저장소의 일치 문자열은 계약 시험용 가짜 값뿐
- 실제 NAI: 생성 5회와 Vibe 인코딩 1회 성공. 예상 27 Anlas와 실제 감소
  27 Anlas 일치. AI 자동·좌표·29 steps·Vibe·Precise Reference 확인
- 앱 내 브라우저 연결은 로컬 자산 경로 오류로 실패했으나 설치된 Playwright로 실제
  Chromium 조작과 최신 1600·390 스크린샷 촬영을 완료

## 로컬 산출물

- `dist/NAI-batch-generator-1.0.0-portable-win-x64.zip`
- `dist/NAI-batch-generator-1.0.0-datapack.zip`
- `dist/NAI-batch-generator-1.0.0-setup.exe`
- `dist/SHA256SUMS.txt`

SHA-256:

```text
48c1397bd2e4df6c3f42fb8a2d51c1a5ba0f8f7ab3919c79727d69052aa70d6b  NAI-batch-generator-1.0.0-portable-win-x64.zip
66f3b98ec1b6ea36435ab2c04131412bce7dc094f536865d89e3ffc3c0ac94a05  NAI-batch-generator-1.0.0-datapack.zip
c7ed6bcc60e3e0496348add02f27ce4abf7353bfb11365304437741407f70360  NAI-batch-generator-1.0.0-setup.exe
```

## Claude가 할 일

1. 지금은 push하지 않고 `docs/current/NEXT_TASK.md`와 실제 NAI 검증 문서를 읽는다.
2. 남은 데스크톱 작업이 끝났거나 사용자가 현재 기준점 공개를 명시했을 때만
   `git status --short`가 비어 있는지 확인한다.
3. 토큰·개인 설정·캐릭터·그림체·생성물이 추적되지 않았는지 읽기 검사한다.
4. 사용자 지시 뒤 변경 없이 `git push origin main`하고 원격 HEAD·smoke CI를 확인한다.

## 하지 않을 일

- 기능·테스트·문서 추가 수정
- 검증 약화 또는 실패 정상 처리
- Release·태그·산출물 게시
- 사용자 자료 이동·변환·삭제
- 저장소 밖의 `성향 표`와 `로그 편집기` 접근
