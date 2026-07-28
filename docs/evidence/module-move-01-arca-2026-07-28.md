# 모듈 이동 01 — 공개자료 수집 어댑터

기준 커밋: `885d46a`  
작업일: 2026-07-28

## 이동

- 원본: `arca_public_import.py`
- 새 구현 위치: `src/nai_studio/collection/arca.py`
- 방법: `git mv`
- 호환: 루트 `arca_public_import.py`가 새 구현의 공개·비공개 심볼을 재노출

기능, URL 규칙, 수집 상태, 사용자 데이터 스키마는 바꾸지 않았다.

## 검증

- Python compile: 통과
- 계약 시험: 10/10
- 모듈 경계 호환: 3/3
- 기존 무과금 회귀: 147/147
- 실제 격리 기동: `python start.py --no-browser --data-dir <임시경로>`
- 실제 브라우저:
  - `/` HTTP 200
  - 문서 제목 `NAI 배치 생성기`
  - `/api/public_collection` HTTP 200, `stage=idle`
  - 1280px에서 가로 넘침 0
  - page/console 오류 0
- 시험 서버 종료 및 임시 자료 폴더 제거 확인

## 보호 경계

`성향 표`, `로그 편집기`, 사용자 자료 경로에는 접근·수정·이동이 없었다.

