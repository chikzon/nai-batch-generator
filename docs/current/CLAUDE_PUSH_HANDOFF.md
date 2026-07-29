# Claude push 인계

이 문서를 포함한 최신 `main`이 데스크톱 릴리스 후보다. 기능을 다시 고치거나 외부 앱
조사를 반복하지 말고 push와 원격 CI 확인만 한다.

## 최종 구현

- 단건·자료팩·공개 수집·보유 폴더 감사를 복원 후보/증거 흐름으로 연결
- 외형·착의·negative·variant·Reference·Vibe·좌표의 무손실 캐릭터 경로
- 순회/동시 출연 캐스트, 캐릭터×세팅과 사용자 선택 실험
- 클릭 시점 생성 snapshot, 직렬 실행, Job 저장·중단·재개·재실행
- 실제 payload/이미지 SHA/request ID/blueprint 지문을 결과와 승격 장부에 연결
- 50건 이후 메타데이터 후보 UI, strict 키가 하나라도 있는 손상 결과의 구형 fallback
  차단. strict 식별자가 전혀 없는 진짜 구형 결과만 자산 저장 호환·장부 미기록

대표 커밋:

- `3e379fa` 실행 설계도와 결과 계보의 손실 경계를 닫는다
- `e277461` 승격 장부에서 서로 다른 캐릭터 내용을 보존한다
- `523750d` 생성 설계도와 증거 감사를 실제 화면에 잇는다
- `a0e1a7d` 선택 실험 leaf의 seed와 캐스트 계보를 고정한다

## 검증 결과

- `python 검증.py`: 컴파일·계약·아키텍처·무과금 회귀 **165/165 통과**
- 최신 소스와 최종 EXE: `/`, `/api/blueprint`, `/api/jobs`,
  `/api/metadata_audit_status` HTTP 200
- 설치본: 격리 설치 → 설치된 EXE 기동/HTTP 200 → 제거 → 레지스트리 정리
- 개인 토큰 정규식 검사: 배포 폴더 0건. 저장소의 일치 문자열은 계약 시험용 가짜 값뿐
- 실제 NAI 유료 호출: 이번 결함 검증에는 불필요해 사용하지 않음
- 브라우저 자동 연결 도구는 로컬 자산 오류로 최신 스크린샷 재촬영 불가. 이를 성공으로
  바꾸어 적지 않는다. 기존 1440·1280·390 화면 증거와 최신 JS/HTTP 검증을 사용했다.

## 로컬 산출물

- `dist/NAI-batch-generator-1.0.0-portable-win-x64.zip`
- `dist/NAI-batch-generator-1.0.0-datapack.zip`
- `dist/NAI-batch-generator-1.0.0-setup.exe`
- `dist/SHA256SUMS.txt`

SHA-256:

```text
37d2bdb32f87253947e7e48bd820cc451d4789c36381f25e2a7cd39f55cb4699  NAI-batch-generator-1.0.0-portable-win-x64.zip
6533054f44d5858d62977f59322de393e5cea10723356f9a92d359dc8a63283e  NAI-batch-generator-1.0.0-datapack.zip
e39c0823232d713d9a23c2892526455540d474b9678a9729b325bf3dde24f20c  NAI-batch-generator-1.0.0-setup.exe
```

## Claude가 할 일

1. `git status --short`가 비어 있는지 확인
2. 최신 문서 커밋과 위 구현 커밋 확인
3. 토큰·개인 설정·캐릭터·그림체·생성물이 추적되지 않았는지 읽기 검사
4. 변경 없이 `git push origin main`
5. 원격 HEAD 일치와 smoke CI 결과 보고

## 하지 않을 일

- 기능·테스트·문서 추가 수정
- 검증 약화 또는 실패 정상 처리
- Release·태그·산출물 게시
- 사용자 자료 이동·변환·삭제
- 저장소 밖의 `성향 표`와 `로그 편집기` 접근
