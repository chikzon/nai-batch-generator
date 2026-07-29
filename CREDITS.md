# 크레딧 · 참고한 것들

이 프로그램은 아래 프로젝트의 기능 목적·작업 흐름·실제 NAI 요청 방식을 참고해
현재 앱의 생성 설계도·세팅·자료·실행 계층에 맞게 구현했다. 현재 코드는 Python
진입점과 `src/nai_studio`의 도메인·서비스·실행 모듈로 구성된다.

---

## 기능·설계를 참고한 프로젝트 (직접 코드 사용은 확인 범위에서 미발견)

| 프로젝트 | 참고한 것 |
|---|---|
| [sunanakgo/NAIS3](https://github.com/sunanakgo/NAIS3) | 왼쪽 프롬프트 패널 + 도구 오버레이 구조 · 캐릭터 프롬프트에 위치 지정 · 씬 모드(씬별 프롬프트 저장 → 예약 → 일괄 생성) · 조각(와일드카드) 개념 · 태그 자동완성 |
| [sunanakgo/NAIS2](https://github.com/sunanakgo/NAIS2) | 씬 카드 드래그 정렬 · 씬별 예약 수량 · 스마트툴 묶음(i2i·인페인트·배경제거·모자이크·업스케일) |
| [seotk0319/NAIS3-Custom](https://github.com/seotk0319/NAIS3-Custom) | 멀티 프로필(계정별 데이터 분리) · 씬 선별 작업 화면 · **그림체 복구(메타데이터로 재생성)** 아이디어 · 예약 수량 직접 입력 |
| NAIS2-Custom (README.ko.md) | **메타데이터 제거 저장**(저장 시점 토글) · 선별 외 일괄 삭제 |
| [IZTACIYU/NAIS2-Forge](https://github.com/IZTACIYU/NAIS2-Forge) | 캐릭터 카드의 **의상 칸 분리** · 카드 부분 접기 |
| [JaCha00/nais_blue](https://github.com/JaCha00/nais_blue) | 디자인 토큰을 문서로 먼저 정의하는 방식 · 미출하 기능을 문서에 정직하게 표기하는 방식 · **단부루 `tags.json` 으로 프롬프트 태그를 검증한다는 착안**(태그 개수 제한이 없는 경로) |
| NAIS3-MM 1.1.1 (배포본) | 휴식 스케줄러(밴 예방) · 완료 알림 · 선별/비교함 · 라이브러리 가상 폴더 · **UC 프리셋·퀄리티 태그를 이미지 문구에서 역추적한다는 착안** · 내장 브라우저의 홈이 단부루 **미러 도메인**이라는 힌트 |
| [Dd154663/SDStudio](https://github.com/Dd154663/SDStudio) | 프로젝트·템플릿·캐릭터×세팅·테마 구조 · Reference와 Vibe의 상호 배타 처리 |
| [okawaritsuika/NAImakeArtistGroup](https://github.com/okawaritsuika/NAImakeArtistGroup) | 공개자료 수집·중단·재개·변경 추적 · 작가 가중치·고정 작가·후보 상태 |
| [Rlag1998/novelai-artist-elo](https://github.com/Rlag1998/novelai-artist-elo) | 이름을 가린 비교·ELO·조합 평가 |
| [DEX-1101/NovelAI-Prompt-Tools](https://github.com/DEX-1101/NovelAI-Prompt-Tools) | 프롬프트 가중치·자동완성·부분 편집 흐름 |
| [DNT-LAB/NAIA2.0](https://github.com/DNT-LAB/NAIA2.0/releases) | 생성 Queue·Sequence·실험 축·캐릭터 Variation·Vibe 묶음 |
| [bedovyy/ComfyUI_NAIDGenerator](https://github.com/bedovyy/ComfyUI_NAIDGenerator) | **캐릭터 레퍼런스 참조 이미지를 허용 캔버스로 레터박싱**해야 한다는 결정적 힌트 |
| [raspie10032/ComfyUI_RS_NAI_API_Request](https://github.com/raspie10032/ComfyUI_RS_NAI_API_Request) | 공간 캐릭터·Inpaint 요청 구조 |
| [wattah1002/novelai-batch-image-generator](https://github.com/wattah1002/novelai-batch-image-generator) | 직렬 배치·Seed·반복·결과 기록 |
| [Pan-qwq/NAI-WorldPainter](https://github.com/Pan-qwq/NAI-WorldPainter) | Queue·History·Preset 작업 흐름 |
| [wfjsw/danbooru-diffusion-prompt-builder](https://github.com/wfjsw/danbooru-diffusion-prompt-builder) | 태그 후보·프롬프트 조립 UI |
| [도랑 위키](https://wiki.dorang.uk/webwiki/#/assets) | 레시피 검색·분류·원격 이미지 지연 로드 |

⚠ 기능이 비슷한 것은 **NAI API 를 쓰는 방식이 같아서 자연스럽게 겹치는 부분**도 있다.
위 목록은 "참고한 사실"을 밝히는 것이며, 코드 파생 관계를 주장하는 것이 아니다.

## 아직 없거나 별도 단계인 것

스마트폰 앱·PC 연동 · Outpaint · 자동 업데이트 · 스트리밍 중간 미리보기 ·
blue식 시각적 3-way 충돌 해결 · SDStudio식 프로젝트 계층 편집 ·
MM식 완전한 6칸 Organizer · 범용 조건 DSL · 다국어 UI.

Electron/Tauri/ComfyUI graph, Marketplace·R2·일반 웹브라우저, NAI 밖 생성 백엔드는
현재 독립 Windows NAI 작업실의 목적과 겹치지 않아 제품 구조 자체를 복제하지 않는다.

---

## 자료 출처

무엇이 저장소·배포본에 각각 들어가는지는 README 의 '무엇이 어디에 들어 있나' 표를 보라.

### 저장소에서는 빠지지만 **배포본 ZIP 에는 들어가는 것**

| 자료 | 출처 · 조건 |
|---|---|
| `t5_tokenizer.json` (2.3MB) | `sunanakgo/NAIS3` commit `6bff595`의 `resources/t5_tokenizer.json`. NAIS3의 GPL-3.0을 따른다 |
| `태그/*.csv` (6MB) | `DominikDoom/a1111-sd-webui-tagcomplete` commit `4170882f90b47be130a0ff9314f663c230b9153d`의 태그 CSV와 SHA-256이 같다. MIT 고지와 해시는 `THIRD_PARTY_NOTICES.md`에 보존했다 |

### 저장소·배포본 **어디에도 없는 것** (자료팩으로만 따로 전달)

| 자료 | 출처 · 조건 |
|---|---|
| `수집/그림체.json` · `작가통계.json` · `레시피.json` | 아카라이브 AI 그림 채널 · AI 데이트 채널 · 도랑 위키. 항목마다 원문 주소를 함께 담는다 |
| `수집/이미지캐시/` | 위 그림체의 예시 이미지 (자료팩으로만 전달) |
| 모델 `ntd11_v5.pt` | Civitai 1313556. 자동 검열용 — **이 저장소 밖의 별도 로컬 도구**에서 쓰며, 저장소·배포본 어디에도 포함되지 않는다 |

## 자료 출처 — 저장소에 포함하는 것

| 자료 | 출처 · 조건 |
|---|---|
| `후보사전.json` | 위 태그 목록(단부루·e621 태그명 + 게시물 수)에서 슬롯 규칙으로 뽑아 만든 파생 데이터. [단부루 태그 그룹](https://danbooru.donmai.us/wiki_pages/tag_groups) 분류를 기준으로 짰다. NSFW 슬롯이 포함되어 있다 |
| `옵션.json` · `규격.json` | 이 프로젝트에서 작성한 앱 기본 데이터 |

## 쓰는 외부 서비스

- **NovelAI API** (`image.novelai.net`, `api.novelai.net`) — 이미지 생성·디렉터 툴·업스케일.
  이 프로그램은 NovelAI 의 공식 제품이 아니고 NovelAI 와 아무 관계가 없다.
- **Danbooru / Gelbooru / e621** — 태그 검색(선택 기능)

## 라이선스

이 프로그램의 코드는 **GPL-3.0** 이다 (`LICENSE`).
배포본에 포함되는 제3자 자료의 고지·고정 출처·해시는 `THIRD_PARTY_NOTICES.md`를 보라.
