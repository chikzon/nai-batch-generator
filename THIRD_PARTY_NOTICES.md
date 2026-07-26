# 제3자 자료 고지

이 배포본에는 아래 제3자 자료가 들어간다. 프로그램 코드의 GPL-3.0 고지와 별개로,
각 자료의 출처와 조건을 함께 보존한다.

## Danbooru/e621 태그 CSV

- 파일: `태그/danbooru_e621_merged.csv`
- 출처: `DominikDoom/a1111-sd-webui-tagcomplete`
- 고정 버전: commit `4170882f90b47be130a0ff9314f663c230b9153d`
- 원본 경로: `tags/danbooru_e621_merged.csv`
- SHA-256: `AA9EAB8435562F86D7AC0D81F2F7BEDCBA9F6B93A806010708702406BBA85E18`
- 라이선스: MIT

아래는 원 저장소의 MIT 고지다.

```text
MIT License

Copyright (c) 2022 Dominik Reh

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## T5 토크나이저

- 파일: `t5_tokenizer.json`
- 확인 가능한 직접 출처: `sunanakgo/NAIS3`, commit `6bff595`,
  `resources/t5_tokenizer.json`
- 검증: 배포 파일과 위 파일은 공백·직렬화 표현은 다르지만, JSON 전체를 정규화하면
  의미 구조가 같다(vocab 32,100개).
- 조건: NAIS3 저장소의 GPL-3.0. 이 프로젝트도 GPL-3.0으로 배포하며 본문 `LICENSE`를 포함한다.
- 한계: NAIS3보다 앞선 원출처는 이번 감사에서 확인하지 못했다.
