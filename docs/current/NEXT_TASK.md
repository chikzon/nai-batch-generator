# 현재 작업

## 목적

남은 raw image·export·root·진단 GET 응답을
`src/nai_studio/web/routes/assets.py`와 runtime route로 옮긴다.

## 구현 범위

- refimg·setout·img·latest-compatible bytes 응답
- out list·setting thumbnails
- Reference·backup·fragment·setting export
- diagnostics·root HTML
- 고정 경로 검증·MIME·Content-Disposition·Cache-Control 유지

## 완료 조건

- `do_GET`가 기능 구현 없이 route 위임만 수행
- 경로 탈출 차단과 휴지통 출력 차단 유지
- export 파일명·MIME·본문 유지
- root·진단·raw 응답 관련 기존 테스트 통과

## 금지 범위

- POST 라우트 이동
- export schema·사용자 파일 변경
- 전체 회귀·빌드·Release·push
- 저장소 밖의 `성향 표`와 `로그 편집기`

## 다음 경계

GET 분리 완료 뒤 POST 기능군을 recovery·catalog·generation 순으로 이동한다.
