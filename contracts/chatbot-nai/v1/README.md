# Chatbot ↔ NAI contract v1

이 폴더는 원래 챗봇과 NAI 통합 작업실 사이의 연결 형식만 정의한다.

- `render-request.schema.json`: 챗봇이 NAI 작업실에 보내는 생성 요청
- `render-result.schema.json`: NAI 작업실이 돌려주는 상태·결과·재현 정보
- `asset-map.schema.json`: 챗봇 ID와 NAI 자료 ID의 연결
- `fixtures/`: 양쪽 구현이 함께 검증할 정상·오류 예제

## 금지

- NAI API 토큰
- 사용자 프롬프트 원문
- 이미지 바이트나 base64
- 사용자 설정 파일 전체

요청은 안정된 ID를 전달하고, 실제 프롬프트와 생성 설정은 NAI 작업실이 소유한다.

## 로컬 검증

```powershell
python contracts/chatbot-nai/validate_contract.py `
  contracts/chatbot-nai/v1/fixtures/valid-request.json `
  contracts/chatbot-nai/v1/fixtures/valid-result.json `
  contracts/chatbot-nai/v1/fixtures/valid-asset-map.json
```
