# -*- coding: utf-8 -*-
"""NAI 작업실의 정적 HTML·JavaScript 템플릿.

렌더러가 선택지 placeholder만 치환하며 이 모듈은 파일·설정·HTTP에 접근하지 않는다.
"""

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NAI 배치 생성기__PROFTITLE__</title>
<link rel="stylesheet" href="/ui/base.css">
  <!-- 작업실 화면 구성은 기본 규칙 뒤에 덮어쓰는 별도 자산으로 유지한다. -->
  <link rel="stylesheet" href="/ui/studio.css">
  </head>
<body data-mode="preview">

<div class="titlebar">
  <div class="app">NAI <span>배치 생성기</span>
    <small class="app-sub">자료에서 생성까지 한 작업실</small>__PROFBADGE__
    <span class="save-state" id="saveState" title="설정.json 자동저장 상태">저장됨 ✓</span></div>
  <!-- 실제 작업 순서: 생성 · 세팅 · 자료 · 빌더 · 관리.
       숫자키 1~5 로도 옮긴다. -->
  <div class="modes" id="modes">
    <button data-mode="preview" class="on" title="Alt+1"><span class="navico" aria-hidden="true">01</span><span class="navcopy"><b>생성</b><small>프롬프트와 실행</small></span></button>
    <button data-mode="settings" title="Alt+2"><span class="navico" aria-hidden="true">02</span><span class="navcopy"><b>세팅</b><small>장면·캐스트·비교</small></span></button>
    <button data-mode="library" title="Alt+3"><span class="navico" aria-hidden="true">03</span><span class="navcopy"><b>자료</b><small>수집·검색·정리</small></span></button>
    <button data-mode="builder" title="Alt+4"><span class="navico" aria-hidden="true">04</span><span class="navcopy"><b>빌더</b><small>그림체·캐릭터 조립</small></span></button>
    <button data-mode="system" title="Alt+5"><span class="navico" aria-hidden="true">05</span><span class="navcopy"><b>관리</b><small>작업·복구·환경</small></span></button>
  </div>
  <div class="spacer"></div>
  <div class="stat" id="topStat">-</div>
  <!-- 패널 접기 — Forge 는 타이틀바 우측에 같은 것을 둔다 (`CustomTitleBar.tsx:110-`) -->
  <button class="paneltog" id="togLeft" aria-pressed="false"
    title="프롬프트 패널 접기 / 펴기 (Alt+[)"><span class="panel-symbol">◧</span><span class="panel-label">프롬프트 패널</span></button>
  <button class="paneltog" id="togRight" aria-pressed="false"
    title="최근 생성 패널 접기 / 펴기 (Alt+])"><span class="panel-symbol">◨</span><span class="panel-label">최근 생성 패널</span></button>
</div>

<div id="startupRecovery" role="alert"
  style="position:fixed;z-index:120;left:12px;right:12px;top:54px;padding:11px 13px;
  border:2px solid var(--warn);border-radius:var(--radius);background:var(--card);
  box-shadow:0 8px 28px #0005;display:none;align-items:center;gap:10px;flex-wrap:wrap;">
  <div style="flex:1;min-width:240px;"><b>설정 손상을 안전하게 격리하고 기본 설정으로 시작했습니다.</b>
    <div class="hint" id="startupRecoveryDetail"></div></div>
  <button type="button" id="startupRecoveryBackup">내 자료 백업·복원 열기</button>
  <button type="button" id="startupRecoveryClose">확인</button>
</div>

<div class="app" id="app">
  <!-- ══ 왼쪽: 프롬프트 패널 ══ -->
  <div class="left"><div id="lwDrag" title="드래그로 패널 폭 조절"></div>
    <div class="preset-bar">
      <select id="presetSel"><option value="">베이스 프리셋 불러오기...</option></select>
      <button id="presetSave" title="현재 프롬프트+네거티브+파라미터를 파일로 저장">저장</button>
    </div>

    <!-- ⚠ 이 1.2 : 1 배분을 건드리기 전에 아래를 읽을 것 (두 번 헛짚었다).
         ① **칸이 커 보인다고 줄이지 말 것.** 빈 화면에서만 커 보인다. `수집/그림체.json`
            732건 실측은 base 중앙값 593자 · negative 중앙값 1,080자(UC 프리셋 문구를
            `split_uc_preset` 으로 뗀 뒤)다. 지금도 1280 에서는 **중앙값 프롬프트가 38%
            잘린다.** 라운드10 이 잘림을 80%→34% 로 줄이려 키운 자리다.
         ② **길이가 길다고 네거티브에 더 주지도 말 것.** 1 : 1.5 로 뒤집어 실측했더니
            두 칸 잘림 **합계가 그대로였다** (1600 317→317px · 1280 521→522px).
            세로는 총량이 정해져 있어 순수 재분배이고, 자주 고치는 프롬프트 칸만
            14%→42% 로 나빠졌다. 네거티브는 그림체에서 통째로 받아 두고 거의 안 고친다.
            그래서 **자주 고치는 쪽에 더 주는 지금 배분을 유지한다.**
         진짜로 나아지려면 총 높이를 늘리거나(접기·오버레이) 칸을 자동으로 키워야 한다. -->
    <div class="psec" style="flex:1.2;">
      <div class="psec-head" data-fold="pPos"><span class="chev">▾</span><span class="t">프롬프트</span>
        <span class="count" id="posTok">0</span>
        <span class="prompt-editors" aria-label="프롬프트 편집 도구">
          <span class="ed" id="weightDownBtn" title="선택 영역이나 커서가 있는 태그의 가중치를 0.1 낮춤">−강조</span>
          <span class="ed" id="weightUpBtn" title="선택 영역이나 커서가 있는 태그의 가중치를 0.1 높임">+강조</span>
          <span class="ed" id="tagVerifyBtn" title="단부루에 실제로 있는 태그인지 확인 (없는 태그는 토큰만 먹는다)">✓태그</span>
          <span class="ed" id="findRepBtn" title="프롬프트·네거티브·캐릭터 칸에서 한꺼번에 찾아 바꾸기 (SDStudio 참고)">⇄바꾸기</span>
          <span class="ed" id="split3Btn" title="고정 / 가변 / 디테일 세 칸으로 나누기">⋮⋮</span>
        </span>
      </div>
      <div class="psec-body" id="pPos">
        <textarea id="basePrompt" placeholder="1girl, artist:..., masterpiece"></textarea>
        <!-- 3분할 — 켜면 아래 세 칸이 위 칸을 대신한다. 보낼 때는 위에서부터 이어 붙인다.
             그림체는 고정에 두고 가변만 굴리는 식으로 쓴다. -->
        <!-- ⚠ 여기 `style="display:flex"` 를 인라인으로 두면 `.hidden{display:none}` 이
             **절대 못 이긴다**(인라인이 항상 위다). 그래서 `⋮⋮` 토글이 클래스를 붙였다 떼도
             3분할이 늘 보였고, 프롬프트 칸이 좌우로 반 토막 나 있었다
             (1600px 실측: 439px 중 206px 만 씀). display 는 CSS 로 옮겼다. -->
        <div id="split3" class="hidden" style="flex-direction:column;gap:5px;flex:1;min-height:0;">
          <textarea id="baseFixed" data-s3 placeholder="고정 — 그림체·작가 조합처럼 늘 들어갈 것" style="flex:1;"></textarea>
          <textarea id="baseVar" data-s3 placeholder="가변 — 매번 바꿔 굴릴 것 (조각 &lt;이름&gt; 쓰기 좋음)" style="flex:1;"></textarea>
          <textarea id="baseDetail" data-s3 placeholder="디테일 — 세부 묘사·마감" style="flex:1;"></textarea>
        </div>
        <div id="tagVerifyOut" class="hidden" style="font-size:var(--fs-2xs);line-height:1.7;padding:6px 2px 0;"></div>
      </div>
    </div>

    <div class="psec" style="flex:1;">
      <div class="psec-head" data-fold="pNeg"><span class="chev">▾</span><span class="t">네거티브</span>
        <span class="count" id="negTok">0</span></div>
      <div class="psec-body" id="pNeg"><textarea id="negPrompt" placeholder="lowres, bad anatomy, ..."></textarea></div>
    </div>

    <!-- 이 줄은 '여기서 바로 여는 것' — 오버레이가 프롬프트 패널 위에 뜬다 -->
    <div class="tools">
      <button class="tool" data-ovl="frags"><span class="ico">🎲</span>조각<span class="badge" id="bgFrags">0</span></button>
      <button class="tool" data-ovl="chars"><span class="ico">👥</span>캐릭터<span class="badge" id="bgChars">0</span></button>
      <button class="tool" data-ovl="refs"><span class="ico">🎨</span>레퍼런스<span class="badge" id="bgRefs">0</span></button>
      <button class="tool" data-ovl="params"><span class="ico">🎚</span>파라미터</button>
    </div>
    <!-- 이 줄은 '다른 탭으로 넘어가는 것'. 같은 모양이면 눌러 보고서야
         알게 되므로 줄을 나누고 ↗ 를 붙였다. -->
    <div class="tools jumps">
      <button class="tool jump" data-mode-jump="settings"><span class="ico">🎬</span>세팅<span class="ar">↗</span><span class="badge" id="bgSets">0</span></button>
      <button class="tool jump" data-mode-jump="builder"><span class="ico">🧰</span>빌더<span class="ar">↗</span></button>
    </div>

    <div class="genrow" id="anlasRow" style="border:none;justify-content:space-between;">
      <span class="hint" id="anlasCost">비용 계산 중...</span>
      <button id="anlasBal" title="NAI 계정의 남은 Anlas 조회">잔액 확인</button>
    </div>
    <div class="genrow">
      <div class="qty">
        <button id="qtyM" title="수량 줄이기">−</button>
        <input id="qty" type="number" value="1" min="1" max="99" step="1"
          inputmode="numeric" aria-label="빠른 생성 수량 (1~99)">
        <button id="qtyP" title="수량 늘리기 (최대 99)">+</button>
      </div>
      <button class="primary go" id="genBtn">생성</button>
      <button class="danger go hidden" id="stopBtn" title="도는 작업을 장 경계에서 멈춥니다 (전송 중인 장은 마저 받음)"
        onclick="fetch('/api/stop',{method:'POST'})">■ 중지</button>
    </div>
    <div class="genrow" id="settingBatchRow" style="border:none;padding-top:0;">
      <button class="go" id="batchBtn" style="flex:1;">🎬 선택 세팅 일괄 생성</button>
    </div>

    <!-- 캐릭터 오버레이 -->
    <div class="ovl hidden" id="ovlChars">
      <div class="ovl-head"><span class="t">👥 캐릭터</span>
        <span class="count" style="font-size:var(--fs-2xs);color:var(--muted);">한 그림에 함께 들어갈 인물 · 보내는 건 켠 것만 (NAI 상한 6명)</span>
        <button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <div class="position-mode-row" style="margin-bottom:8px;">
          <!-- 구형 내부 경로와 설정 호환용. 실제 선택 UI는 아래 세 단추다. -->
          <input type="checkbox" id="chUseCoords" hidden aria-hidden="true">
          <div class="position-mode-picker" id="chPositionMode" role="radiogroup"
               aria-label="캐릭터 위치 방식">
            <button type="button" data-position-mode="ai" role="radio">AI 자동</button>
            <button type="button" data-position-mode="grid" role="radio">위치판</button>
            <button type="button" data-position-mode="coordinate" role="radio">좌표</button>
          </div>
          <button type="button" id="chSpread" title="켠 인물을 겹치지 않는 추천 위치에 놓습니다">추천 배치</button>
          <span class="hint" id="chCoordsNote"></span>
        </div>
        <!-- 좌표를 안 쓰는 AI 자동은 정상 모드다. 경고는 중복 좌표나 6명 초과처럼
             실제로 사용자가 고쳐야 하는 경우에만 보여 준다. -->
        <div class="row hidden" id="chFuseWarn" style="margin:0 0 8px;padding:8px 10px;">
          <div style="font-size:var(--fs-xs);"></div>
        </div>
        <div id="slotList"></div>
        <div class="bar" style="margin-top:8px;">
          <button id="slotAdd">+ 직접 입력</button>
          <select id="slotLib" style="flex:1;"><option value="">+ 라이브러리에서...</option></select>
        </div>
        <!-- 인물 칸 일괄 손질 (NAIS3 의 캐릭터 다중 선택·일괄 편집을 우리 구조로) -->
        <div class="bar" style="margin-top:4px;flex-wrap:wrap;">
          <span class="hint">일괄:</span>
          <button id="slotAllOn" title="모든 칸 켜기">전부 켜기</button>
          <button id="slotAllOff" title="모든 칸 끄기 — 칸은 남습니다">전부 끄기</button>
          <button id="slotBulkAdd" title="켠 칸의 외형 뒤에 같은 태그를 한꺼번에 붙입니다">＋태그 주입</button>
          <button id="slotDupAll" title="켠 칸을 복제합니다">⧉ 복제</button>
          <!-- 되돌릴 수 없는 단추는 만드는 단추 옆에 붙이지 않는다 (자료 탭과 같은 규칙).
               없애지도, 빨간색을 빼지도 않는다 — 자리만 떼어 잘못 눌리는 것을 막는다.
               ⚠ `<span style="flex:1">` 스페이서를 쓰면 안 된다. `.bar` 는 `flex-wrap:wrap`
                 이라 좁은 오버레이에서 스페이서가 남은 자리를 다 먹고 **단추를 다음 줄
                 왼쪽 끝으로 밀어낸다**(실측: x=12 로 감). `margin-left:auto` 는 어느 줄에
                 놓이든 그 줄의 오른쪽 끝으로 간다. -->
          <button class="danger" id="slotDelOff" style="margin-left:auto;"
            title="꺼 둔 칸을 모두 지웁니다">꺼진 칸 정리</button>
        </div>
      </div>
    </div>


    <!-- 레퍼런스 오버레이 (바이브 · 캐릭터 레퍼런스) -->
    <div class="ovl hidden" id="ovlRefs">
      <div class="ovl-head"><span class="t">🎨 레퍼런스</span>
        <span class="count" style="font-size:var(--fs-2xs);color:var(--muted);">그림으로 분위기·생김새를 참조</span>
        <button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <p class="hint"><b>바이브</b>는 그림의 분위기를 옮깁니다. 처음 한 번만 인코딩(2 Anlas)하고
        그 뒤로는 <b>공짜로 계속</b> 쓰입니다 — 배치 생성에 딱 맞습니다.<br>
        <b>캐릭터 레퍼런스</b>는 생김새를 참조합니다. Opus 무료 생성은 유지되며
        <b>레퍼런스 1개당 장당 5 Anlas</b>만 별도로 붙습니다.</p>
        <div class="reftabs">
          <button class="on" data-reftab="vibe">바이브 <span id="bgVibe">0</span></button>
          <button data-reftab="cref">캐릭터 레퍼런스 <span id="bgCref">0</span></button>
        </div>
        <div class="bar" style="margin:7px 0;">
          <button id="refBundleExport" type="button">묶음 내보내기</button>
          <button id="refBundleImport" type="button">Vibe·Reference 묶음 가져오기</button>
          <input type="file" id="refBundleFile"
            accept=".naiv4vibe,.naiv4vibebundle,.json,application/json"
            style="display:none;">
          <span class="hint">가져온 자원은 기존 생성에 끼어들지 않도록 꺼진 상태로 등록합니다.</span>
        </div>
        <div data-refpane="vibe">
          <div id="vibeDrop" class="row" style="text-align:center;padding:16px;border-style:dashed;cursor:pointer;">
            <b>＋ 바이브 그림 추가</b>
            <div class="hint" style="margin-top:3px;">분위기를 가져올 그림 · PNG / WebP</div>
            <input type="file" id="vibeFile" accept="image/png,image/webp" multiple style="display:none;"></div>
          <div id="vibeList"></div>
        </div>
        <div data-refpane="cref" class="hidden">
          <div id="crefDrop" class="row" style="text-align:center;padding:16px;border-style:dashed;cursor:pointer;">
            <b>＋ 캐릭터 레퍼런스 추가</b>
            <div class="hint" style="margin-top:3px;">생김새를 참조할 그림 · 장당 5 Anlas</div>
            <input type="file" id="crefFile" accept="image/png,image/webp" multiple style="display:none;"></div>
          <div id="crefList"></div>
        </div>
        <p class="hint" id="refMsg" style="margin-top:6px;"></p>
      </div>
    </div>

    <!-- 파라미터 오버레이 -->
    <!-- 조각(와일드카드) — 프롬프트 어디서나 쓰는 치환. 세팅·씬을 대체하지 않는다 -->
    <div class="ovl hidden" id="ovlFrags">
      <div class="ovl-head"><span class="t">🎲 조각 (와일드카드)</span><button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <p class="hint">프롬프트 어디에든 <b>&lt;이름&gt;</b> 을 쓰면 그 조각의 한 줄로 바뀝니다.
        <b>&lt;*이름&gt;</b> 은 차례대로(다음 장에 다음 줄), <b>{a|b|c}</b> 는 그 자리에서 셋 중 하나.
        한 줄짜리 조각은 고정 치환이 됩니다. 기본 생성·씬·세팅 <b>어디서나</b> 같습니다.</p>
        <div class="bar">
          <button id="fragNew">+ 새 조각</button>
          <button id="fragExport" title="조각/*.txt 를 ZIP 으로">📤 내보내기</button>
          <button id="fragImport" title="TXT·ZIP 을 조각/ 에 넣기">📥 가져오기</button>
          <input type="file" id="fragImportFile" accept=".txt,.zip" multiple style="display:none;">
          <button id="fragReset" title="&lt;*이름&gt; 의 순번을 처음으로">순번 리셋</button>
          <span class="n" id="fragMsg" style="margin-left:auto;"></span>
        </div>
        <div id="fragList" style="margin-top:8px;"></div>
        <div class="field" style="margin-top:10px;">
          <label>시험해 보기 — 여기 적으면 실제로 어떻게 바뀌는지 보여줍니다 (순번은 안 올라감)</label>
          <input type="text" id="fragTry" placeholder="1girl, <표정>, {smile|serious}">
          <div class="bar" style="margin-top:6px;">
            <button id="fragTryAgain" type="button">전체 다시 뽑기</button>
            <button id="fragTrySelected" type="button">고른 선택만 다시</button>
            <span class="hint">아래 선택지를 고르면 나머지는 그대로 고정합니다.</span>
          </div>
          <div id="fragTryChoices" class="filterbar" style="margin-top:6px;"></div>
          <div class="hint" id="fragTryOut" style="margin-top:5px;font-family:var(--mono);
               white-space:pre-wrap;overflow-wrap:anywhere;"></div>
        </div>
      </div>
    </div>

    <div class="ovl hidden" id="ovlParams">
      <div class="ovl-head"><span class="t">🎚 생성 파라미터</span><button class="x" data-ovl-close>✕</button></div>
      <div class="ovl-body">
        <div class="grid2">
          <div class="field"><label>모델</label><select id="pModel">__MODELS__</select></div>
          <div class="field"><label>해상도 <span class="hint">(세팅 씬은 씬별 값을 씀)</span></label>
            <select id="pRes">__RES__<option value="">직접 입력...</option></select></div>
          <div class="field" id="pWHwrap" style="display:none;"><label>가로 × 세로</label>
            <div class="bar"><input type="number" id="pWidth" step="64" min="64" max="2048" style="flex:1;">
            <input type="number" id="pHeight" step="64" min="64" max="2048" style="flex:1;"></div>
            <span class="hint" id="pResNote"></span></div>
          <div class="field"><label>CFG (Prompt Guidance)</label><input type="number" id="pScale" step="0.1" min="1" max="10"></div>
          <div class="field"><label>리스케일</label><input type="number" id="pRescale" step="0.02" min="0" max="1"></div>
          <div class="field"><label>스텝</label><input type="number" id="pSteps" min="1" max="50"></div>
          <div class="field"><label>샘플러</label><select id="pSampler">__SAMPLERS__</select></div>
          <div class="field"><label>노이즈 스케줄</label><select id="pSched">__SCHEDS__</select></div>
          <div class="field"><label>UC 프리셋 <span class="hint">(네거티브 기본 묶음)</span></label><select id="pUc">__UCP__</select></div>
          <div class="field"><label>퀄리티 태그 <span class="hint">(끝에 자동 추가)</span></label>
            <select id="pQuality"><option value="off">끔</option><option value="on">켬</option></select></div>
          <div class="field"><label>Variety+</label><select id="pVariety"><option value="off">끔</option><option value="on">켬</option></select></div>
          <div class="field"><label>회차 번호 <span class="hint">(같은 번호 = 같은 결과 재현)</span></label>
            <input type="number" id="pSeed"></div>
          <div class="field"><label>NAI 시드 <span class="hint">(0 = 장마다 다름)</span></label>
            <div class="bar"><input type="number" id="pNaiSeed" placeholder="0" style="flex:1;">
              <button id="pSeedRoll" title="새 랜덤 시드">🎲</button>
              <button id="pSeedClear" title="고정 해제 (0)">✕</button></div>
            <p class="hint" id="pSeedNow" style="margin-top:5px;"></p></div>
        </div>
        <details class="output-settings" id="pOutputSettings" style="margin-top:10px;">
          <summary>출력·저장 <span class="hint">포맷·폴더·날짜·메타데이터</span></summary>
          <div class="grid2" style="margin-top:10px;">
            <div class="field"><label>저장 포맷 <span class="hint">(공홈과 같은 선택)</span></label>
              <select id="pFormat">
                <option value="webp">WebP — 용량이 작음 (기본)</option>
                <option value="png">PNG — 무손실 · 투명 지원</option></select></div>
            <!-- 저장 폴더 — 비우면 프로필의 output/. 탐색기도 이 폴더를 본다 -->
            <div class="field"><label>저장 폴더 <span class="hint">(비우면 기본 output)</span></label>
              <input type="text" id="pOutDir" placeholder="예: D:\\NAI결과"></div>
            <div class="field"><label>날짜별로 나누기</label>
              <select id="pOutDate">
                <option value="off">한 폴더에 모으기 (기본)</option>
                <option value="on">모드 폴더 아래 날짜별로</option></select></div>
            <!-- 저장 시점에 메타를 아예 안 넣는 선택. 나중에 따로 지우는 기능(관리 탭)은 그대로 둔다. -->
            <div class="field"><label>메타데이터 <span class="hint">(저장 시점)</span></label>
              <select id="pClean">
                <option value="off">넣기 — 나중에 끌어다 놓아 그림체 복원 가능 (기본)</option>
                <option value="on">지우고 저장 — 공유용 · 복원 불가</option></select></div>
            <div class="field" id="pCleanOpts" style="display:none;"><label>가볍게 — 긴 변
              <span class="hint">품질은 아래 저장 품질</span></label>
              <select id="pMaxSide">
                <option value="0">그대로</option><option value="1536">1536px</option>
                <option value="1024">1024px</option><option value="768">768px</option></select></div>
            <div class="field"><label>저장 품질 <span class="hint">(WebP · 40~100)</span></label>
              <input type="number" id="pSaveQ" min="40" max="100" step="5"></div>
          </div>
        </details>
        <div class="fold closed" id="pAdvHead" data-fold="pAdv" style="margin-top:10px;">고급 (기본값 그대로 두어도 됩니다)</div>
        <div id="pAdv" class="hidden">
          <p class="hint" id="pAdvNote"></p>
          <div class="grid2">
            <div class="field" data-gen="v3"><label>SMEA</label><select id="pSmea"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v3"><label>SMEA DYN</label><select id="pSmeaDyn"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v3"><label>Dynamic Thresholding <span class="hint">(Decrisper)</span></label><select id="pDynThr"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field" data-gen="v3"><label>Uncond Scale <span class="hint">(네거티브 강도)</span></label><input type="number" id="pUncond" step="0.05" min="0" max="1.5"></div>
            <div class="field" data-gen="v3"><label>ControlNet Strength</label><input type="number" id="pCtrl" step="0.1" min="0" max="2"></div>
            <div class="field" data-gen="v4"><label>Prefer Brownian</label><select id="pBrownian"><option value="on">켬</option><option value="off">끔</option></select></div>
            <div class="field" data-gen="v4"><label>Euler Ancestral 버그 재현 <span class="hint">(구버전 그림체 재현용)</span></label>
              <select id="pEulerBug"><option value="off">끔</option><option value="on">켬</option></select></div>
            <div class="field hidden" data-gen="v4" aria-hidden="true"><label>캐릭터 위치 좌표 사용</label>
              <select id="pCoords"><option value="off">끔</option><option value="on">켬</option></select></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ 가운데: 모드 영역 ══ -->
  <div class="center" id="center">
    <header class="workspace-context" id="workspaceContext">
      <div class="workspace-step" id="workspaceStep">01 · 생성</div>
      <div class="workspace-context-copy">
        <h1 id="workspaceTitle">생성</h1>
        <p id="workspaceDesc">프롬프트, 캐릭터, 생성 설정을 확인하고 결과를 만듭니다.</p>
      </div>
    </header>
    <div class="view" id="vPreview">
      <!-- 첫 실행 안내 — 프롬프트가 비어 있을 때만 -->
      <div class="card hidden" id="welcome">
        <h2><span class="n">처음</span>세 가지만 준비하면 바로 생성할 수 있습니다</h2>
        <div class="welcome-steps">
          <div class="welcome-step">
            <span class="welcome-step-no">1</span>
            <div><b>NovelAI 연결</b><p class="hint" id="welcomeApiStatus">토큰을 확인하는 중입니다.</p></div>
            <button class="primary" id="welcomeApi">API 토큰 넣기</button>
          </div>
          <div class="welcome-step">
            <span class="welcome-step-no">2</span>
            <div><b>기본자료팩 넣기 <span class="hint">(선택)</span></b>
              <p class="hint" id="welcomeDataStatus">빌더 후보와 태그 사전 상태를 확인하는 중입니다.</p></div>
            <button id="welcomePack">자료팩 넣기</button>
          </div>
          <div class="welcome-step">
            <span class="welcome-step-no">3</span>
            <div><b>프롬프트 준비</b><p class="hint">직접 쓰거나 NAI 원본 그림에서 그대로 읽어옵니다.</p></div>
            <button id="welcomeSkip">직접 입력</button>
          </div>
        </div>
        <p class="hint">NAI로 만든 PNG/WebP를 넣으면
        <b>프롬프트·네거티브·설정값(CFG·리스케일·스텝·샘플러·시드)</b>을 통째로 읽어옵니다.</p>
        <div id="welcomeDrop" class="row" style="text-align:center;padding:26px 14px;border-style:dashed;cursor:pointer;">
          <div style="font-size:var(--fs);font-weight:600;">🖼️ 여기에 그림을 끌어다 놓으세요</div>
          <div class="hint" style="margin-top:6px;">눌러서 파일을 골라도 됩니다 · PNG / WebP · 여러 장 한꺼번에 가능</div>
          <input type="file" id="welcomeFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
        <p class="hint" style="margin-top:10px;">
          가진 그림이 없다면 <b>[자료]</b>의 그림체 라이브러리(<span id="welcomeCount">…</span>개)에서 골라도 됩니다.
          카톡·디스코드를 거친 그림은 정보가 지워져 있으니 <b>원본 파일</b>을 넣어주세요.</p>
        <div class="bar" style="margin-top:8px;"><button id="welcomeLib">📚 그림체 고르기</button>
          <span class="n" id="welcomeMsg"></span></div>
      </div>
      <div class="pv">
        <div class="pv-img" id="pvImg"><span style="color:var(--muted);font-size:var(--fs-xs);text-align:center;">
          왼쪽에서 프롬프트·캐릭터를 넣고<br>[생성]을 누르면 여기에 표시됩니다.</span></div>
        <div class="pv-meta">
          <div class="bar"><div class="nm" id="pvName">대기 중</div>
            <span class="phase-pill" id="pvPhase" data-phase="idle">대기</span></div>
          <div class="fn" id="pvFile">-</div>
          <div class="pv-status" id="pvStatus">설정을 준비하고 있습니다.</div>
          <div class="bar" style="margin:8px 0 0;"><span class="n" id="pvProg">0 / 0</span>
            <span class="n" id="pvCounts"></span>
            <span style="font-size:var(--fs-2xs);color:var(--muted);" id="pvEta">남은 시간 —</span>
            <span style="font-size:var(--fs-2xs);color:var(--muted);" id="pvDaily"></span>
            <button id="pvReturn" class="hidden">다시 실행할 화면</button></div>
          <div class="bar" id="pvSeedRow" style="margin:6px 0 0;display:none;">
            <span class="n" id="pvSeed" title="이 그림의 NAI 시드"></span>
            <button id="pvSeedCopy" title="시드 복사">복사</button>
            <button id="pvSeedLock" title="이 시드로 고정">고정</button></div>
          <div class="result-actions hidden" id="pvResultActions" aria-label="최근 결과로 다음 작업">
            <span class="label">이 결과로</span>
            <button type="button" data-latest-action="vibe">바이브</button>
            <button type="button" data-latest-action="cref">캐릭터 레퍼런스</button>
            <button type="button" data-latest-action="i2i">img2img·인페인트</button>
            <button type="button" data-latest-action="outpaint">Outpaint</button>
            <span class="result-action-msg" id="pvResultMsg"></span>
          </div>
          <details class="blueprint-plan" id="blueprintPlan">
            <summary>최종 생성 설계도 <span class="hint">Prompt·캐릭터·자료·세팅·실험·출력</span>
              <span class="count" id="blueprintProjectBadge"></span></summary>
            <div class="filterbar" style="margin:8px 0;">
              <select id="blueprintProjectSelect" aria-label="프로젝트 공통 설계도">
                <option value="">프로젝트 없음</option>
              </select>
              <input id="blueprintProjectName" maxlength="120" placeholder="공통 설계도 이름"
                     style="min-width:160px;flex:1;">
              <button type="button" id="blueprintProjectCreate">현재값 새로 저장</button>
              <button type="button" id="blueprintProjectUpdate">선택 공통값 갱신</button>
              <button type="button" id="blueprintProjectActivate" class="primary">연결하고 적용</button>
              <button type="button" id="blueprintProjectAccept" class="hidden">새 공통판 적용</button>
              <button type="button" id="blueprintProjectDisconnect" class="hidden">연결 해제</button>
            </div>
            <div class="hint" id="blueprintProjectState">
              프로젝트를 쓰지 않으면 지금까지의 생성 흐름이 그대로 유지됩니다.
            </div>
            <div class="blueprint-summary" id="blueprintSummary">현재 값을 해석하는 중입니다.</div>
            <div class="hint" id="blueprintLayers"></div>
            <div class="hint" id="blueprintConflicts"></div>
            <pre class="blueprint-json" id="blueprintJson"></pre>
          </details>
          <div class="pbar"><div id="pvBar"></div></div>
        </div>
      </div>
      <details class="card compact-import" id="generateImportCard">
        <summary><span class="n">불러오기</span>이미지에서 현재 생성값 복원
          <span class="count">PNG · WebP · 여러 장</span></summary>
        <p class="hint">원본 이미지의 베이스·네거티브·캐릭터·생성 설정을 읽습니다.
        한 장이면 읽은 묶음을 확인한 뒤 통째로 적용하고, 여러 장이면 자료실에 연속 등록합니다.</p>
        <div id="generateInspectDrop" class="row"
             style="text-align:center;padding:14px;border-style:dashed;cursor:pointer;">
          <b>＋ 생성값을 가져올 이미지를 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">원문은 자르거나 세부 자료로 임의 분해하지 않습니다.</div>
          <input type="file" id="generateInspectFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
      </details>
      <div class="result-tool-switcher" id="resultToolSwitcher" aria-label="이미지 결과 활용">
        <span><b>이미지 결과 활용</b><small>필요한 도구 하나만 펼칩니다</small></span>
        <button type="button" data-result-tool="i2i">고쳐·이어 그리기</button>
        <button type="button" data-result-tool="director">디렉터</button>
        <button type="button" data-result-tool="mosaic">모자이크</button>
      </div>
      <!-- img2img · 인페인트 · Outpaint — 왼쪽 프롬프트·파라미터를 그대로 쓰고 원본만 더한다 -->
      <div class="card" id="resultToolI2I" data-result-tool-panel="i2i">
        <h2><span class="n">고쳐·이어 그리기</span>img2img · 인페인트 · Outpaint
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">왼쪽 프롬프트·파라미터를 그대로 씁니다</span></h2>
        <p class="hint">그림을 넣고 <b>변화 강도</b>만 주면 <b>img2img</b>(전체를 다시 그림),
        칠한 곳이 있으면 <b>인페인트</b>(칠한 곳만 다시 그림), 캔버스를 넓히면
        <b>Outpaint</b>(바깥만 이어 그림)로 나갑니다.
        결과는 <b>output/img2img/</b> · <b>output/인페인트/</b> · <b>output/Outpaint/</b> 에 저장됩니다.</p>
        <div class="filterbar" id="i2iOperation" style="margin-bottom:8px;">
          <span class="hint">작업</span>
          <button type="button" id="i2iEditMode" class="primary">원본 안쪽 고치기</button>
          <button type="button" id="i2iOutpaintMode">바깥 이어 그리기</button>
          <span class="hint" id="i2iOperationHint">붓을 칠하지 않으면 img2img, 칠하면 인페인트</span>
        </div>
        <div class="filterbar hidden" id="outpaintControls" style="margin-bottom:8px;">
          <span class="hint">확장</span>
          <label>왼쪽 <input type="number" id="outpaintLeft" min="0" max="1536" step="64" value="256" style="width:82px;"></label>
          <label>오른쪽 <input type="number" id="outpaintRight" min="0" max="1536" step="64" value="256" style="width:82px;"></label>
          <label>위 <input type="number" id="outpaintTop" min="0" max="1536" step="64" value="0" style="width:82px;"></label>
          <label>아래 <input type="number" id="outpaintBottom" min="0" max="1536" step="64" value="0" style="width:82px;"></label>
          <button type="button" id="outpaintHorizontal">좌우</button>
          <button type="button" id="outpaintVertical">상하</button>
          <span class="n" id="outpaintSize">원본을 넣으면 최종 크기를 계산합니다</span>
        </div>
        <div id="i2iDrop" class="row" style="text-align:center;padding:18px 14px;border-style:dashed;cursor:pointer;">
          <b>🖌️ 고칠 그림을 여기에 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">PNG / WebP · 넣으면 아래에 뜹니다</div>
          <input type="file" id="i2iFile" accept="image/png,image/webp" style="display:none;">
        </div>
        <div id="i2iStage" class="hidden" style="margin-top:8px;">
          <div id="i2iVariationTools" class="row hidden" style="margin-bottom:8px;">
            <div class="bar">
              <b id="i2iVariationName">캐릭터 이미지 시험·변형</b>
              <span class="n">시험용 설정 — 일반 생성 설정에는 반영되지 않음</span>
            </div>
            <div class="grid3" style="margin-top:7px;">
              <label class="field"><span>방식</span><select id="i2iVariationMode">
                <option value="img2img">img2img · 원본 전체 변형</option>
                <option value="inpaint">Inpaint · 칠한 부분 변형</option>
                <option value="character-reference">Character Reference · 새 장면</option>
                <option value="reference-inset">Reference inset · 원본 옆에 생성</option>
              </select></label>
              <label class="field"><span>시험 가로</span><input type="number" id="i2iTrialWidth" min="256" max="2048" step="64"></label>
              <label class="field"><span>시험 세로</span><input type="number" id="i2iTrialHeight" min="256" max="2048" step="64"></label>
            </div>
            <label class="field"><span>시험 장면 Prompt</span>
              <textarea id="i2iTrialScene" placeholder="일반 생성 베이스를 바꾸지 않고 이 시험에만 적용"></textarea></label>
            <div class="grid2">
              <label class="field"><span>캐릭터 외형 원문</span><textarea id="i2iTrialAppearance"></textarea></label>
              <label class="field"><span>착의·예술적 변형</span><textarea id="i2iTrialOutfit"></textarea></label>
            </div>
            <label class="field"><span>캐릭터 전용 Negative</span><textarea id="i2iTrialNegative"></textarea></label>
            <div class="grid3">
              <label class="field"><span>Reference 강도</span><input type="number" id="i2iRefStrength" min="-1" max="2" step="0.05" value="1"></label>
              <label class="field"><span>Reference 충실도</span><input type="number" id="i2iRefFidelity" min="-1" max="2" step="0.05" value="0.6"></label>
              <label class="field"><span>variation 이름</span><input type="text" id="i2iVariationSaveName" placeholder="예: 겨울 코트"></label>
            </div>
            <div class="row" id="i2iVariationPreview"></div>
          </div>
          <!-- 겹쳐 그리려면 두 캔버스의 화면 크기가 정확히 같아야 한다.
               배율은 JS 가 style.width 로 직접 준다 (max-width 로 눌리면 어긋난다). -->
          <div id="i2iWrap" style="overflow:auto;max-height:78vh;border:1px solid var(--line);
               border-radius:var(--radius);background:var(--paper2);">
            <div id="i2iPad" style="position:relative;display:inline-block;">
              <canvas id="i2iBase" style="display:block;"></canvas>
              <canvas id="i2iMask" style="position:absolute;left:0;top:0;cursor:crosshair;opacity:.55;"></canvas>
            </div>
          </div>
          <div class="filterbar" style="margin-top:8px;">
            <span class="hint" style="white-space:nowrap;">변화 강도</span>
            <input type="range" id="i2iStrength" min="0.1" max="1" step="0.01" value="0.7" style="flex:1;"
              title="인페인트는 1.00 까지 · img2img 는 0.99 까지 (1.00 이면 원본을 아예 안 보므로 NAI 가 막습니다)">
            <span class="n" id="i2iStrengthN">0.70</span>
            <span class="hint i2i-brush-tool" style="white-space:nowrap;">붓 굵기</span>
            <input type="range" id="i2iBrush" min="2" max="300" step="1" value="48" style="width:110px;">
            <span class="n" id="i2iBrushN">48px</span>
            <button id="i2iErase" title="지우개로 바꿔 칠한 것을 부분만 지웁니다">🧽 지우개</button>
            <button id="i2iUndo" title="직전 붓질만 되돌립니다 (Ctrl+Z)">↶ 되돌리기</button>
            <button id="i2iClear">전부 지우기</button>
            <span class="hint" style="white-space:nowrap;">화면 크기</span>
            <select id="i2iZoom">
              <option value="0.5">50%</option><option value="0.75">75%</option>
              <option value="1" selected>100%</option><option value="1.5">150%</option>
              <option value="2">200%</option></select>
          </div>
          <div class="bar" style="margin-top:6px;">
            <span class="n" id="i2iMode">칠하지 않음 → img2img</span>
            <span class="hint" id="i2iCost" style="margin-left:auto;"></span>
            <button class="primary" id="i2iGo">▶ 고쳐 그리기</button>
            <button id="i2iDrop2">다른 그림</button>
          </div>
          <p class="hint" id="i2iMsg"></p>
          <div class="bar hidden" id="i2iVariationSave">
            <span class="hint">완료 결과를 확인한 뒤에만 저장</span>
            <button type="button" data-variation-save="representative">대표 이미지로 지정</button>
            <button type="button" data-variation-save="evidence">근거 이미지로 추가</button>
            <button type="button" data-variation-save="variation" class="primary">variation으로 저장</button>
          </div>
        </div>
      </div>

      <div class="card" id="resultToolDirector" data-result-tool-panel="director">
        <h2><span class="n">디렉터</span>NAI 가 그림을 다시 손봐줍니다 <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">배경 제거 · 라인아트 · 스케치 · 색칠 · 표정 · 정리 · 업스케일</span></h2>
        <p class="hint">이미 있는 그림을 넣으면 NAI 가 손봐서 돌려줍니다. 결과는
        <b>output/디렉터/</b> 에 저장되고 미리보기에도 뜹니다.
        배경 제거는 투명 PNG 로, 나머지는 WebP 로 저장됩니다.</p>
        <div id="dirDrop" class="row" style="text-align:center;padding:20px 14px;border-style:dashed;cursor:pointer;">
          <b>🖼️ 손볼 그림을 여기에 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">PNG / WebP · 여러 장이면 차례로 처리합니다</div>
          <input type="file" id="dirFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
        <div class="filterbar" style="margin-top:8px;">
          <select id="dirTool">__DIRTOOLS__<option value="upscale">업스케일 (해상도 올리기)</option></select>
          <select id="dirEmotion" style="display:none;">__EMOTIONS__</select>
          <input type="text" id="dirPrompt" placeholder="색 유도 프롬프트 (선택)" style="display:none;">
          <select id="dirDefry" style="display:none;">
            <option value="0">기본 강도</option><option value="1">강하게 1</option>
            <option value="2">강하게 2</option><option value="3">강하게 3</option>
            <option value="4">강하게 4</option><option value="5">강하게 5</option></select>
          <select id="dirScale" style="display:none;">
            <option value="2">2배</option><option value="4" selected>4배</option></select>
          <span class="n" id="dirMsg"></span>
        </div>
        <p class="hint">디렉터 툴은 Anlas 를 씁니다 — Opus 는 409,600px 까지 대부분 무료(배경 제거는 예외).
        배경 제거는 rembg 같은 로컬 무료 도구로 대신할 수도 있습니다.</p>
      </div>
      <span id="mosaicGenerateHome" hidden aria-hidden="true"></span>

    </div>

    <div class="view" id="vSettings" style="display:none;">
      <div id="studioSettingsNav" class="studio-subnav hidden" aria-label="세팅 작업 선택">
        <div class="studio-subnav-copy">
          <span class="eyebrow">세팅 작업실</span>
          <strong>씬을 고르고 구조를 편집한 뒤, 빠른 변주나 비교 실험으로 이어갑니다</strong>
        </div>
        <div class="studio-subnav-actions" role="tablist" aria-label="세팅 작업">
          <button type="button" data-settings-work="select" role="tab">씬 고르기</button>
          <button type="button" data-settings-work="build" role="tab">세팅 만들기</button>
          <button type="button" data-settings-work="quick" role="tab">빠른 변주</button>
          <button type="button" data-settings-work="compare" role="tab">비교 실험</button>
        </div>
      </div>
      <span id="compareClassicHome" hidden aria-hidden="true"></span>
      <div class="card" id="compareCard">
        <h2><span class="n">비교 생성</span>내 자료를 같은 조건으로 한 장씩 보기
          <span class="count" id="cmpCounts" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">그림체·캐릭터를 손으로 하나씩 바꾸지 않고 같은 조건으로 돌려
        <b>output/비교생성/</b>에 모읍니다. 그림체는 <b>베이스+네거티브+생성 설정값</b>을
        통째로 유지하며, 아래에서 켠 경우에만 비교를 위해 해상도를 하나로 고정합니다.
        <b>그림체×캐릭터</b>는 두 자료 수를 곱하므로 실행 전 장수를 반드시 확인합니다.</p>

        <div class="grid3" role="radiogroup" aria-label="비교할 자료">
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="styles" checked style="width:auto;flex:none;">
            <span><b>그림체 전체</b><br><span class="hint">현재 캐릭터는 고정</span></span></label>
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="characters" style="width:auto;flex:none;">
            <span><b>캐릭터 전체</b><br><span class="hint">현재 그림체는 고정</span></span></label>
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="both" style="width:auto;flex:none;">
            <span><b>둘 다 조합</b><br><span class="hint">그림체 × 캐릭터</span></span></label>
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="character_setting" style="width:auto;flex:none;">
            <span><b>캐릭터 × 선택 세팅</b><br><span class="hint">선택 씬·단계·예약 매수까지</span></span></label>
          <label class="row" style="cursor:pointer;margin:0;">
            <input type="radio" name="cmpMode" value="selected" style="width:auto;flex:none;">
            <span><b>직접 고른 자료·축</b><br><span class="hint">선택한 것만 교차 실험</span></span></label>
        </div>
        <div class="row hidden" id="cmpSelected" style="margin-top:8px;">
          <div style="width:100%;">
            <b>선택 실험 재료</b>
            <div class="hint">Ctrl·Shift로 여러 개를 고릅니다. 비운 자료 종류는 현재 생성값을 유지합니다.
            아래 축은 쉼표로 여러 값을 적은 경우에만 교차됩니다.</div>
            <div class="grid3" style="margin-top:7px;">
              <div class="field"><label>그림체</label>
                <select id="cmpSelectStyles" multiple size="5"></select></div>
              <div class="field"><label>캐릭터</label>
                <select id="cmpSelectCharacters" multiple size="5"></select></div>
              <div class="field"><label>세팅</label>
                <select id="cmpSelectSettings" multiple size="5"></select></div>
            </div>
            <div class="grid3" style="margin-top:7px;">
              <div class="field"><label>CFG 축 <span class="hint">예: 5, 6.5, 8</span></label>
                <input id="cmpAxisCfg" type="text" placeholder="비우면 현재값"></div>
              <div class="field"><label>Steps 축 <span class="hint">예: 20, 28, 35</span></label>
                <input id="cmpAxisSteps" type="text" placeholder="비우면 현재값"></div>
              <div class="field"><label>Sampler 축 <span class="hint">쉼표 구분</span></label>
                <input id="cmpAxisSampler" type="text" placeholder="k_euler_ancestral, k_dpmpp_2m"></div>
            </div>
            <span class="hint" id="cmpSelectedMsg">선택 자료 목록을 읽는 중입니다.</span>
          </div>
        </div>
        <div class="row" id="cmpCharacterSettingPlan" style="margin-top:8px;">
          <div style="flex:1;min-width:220px;"><b>캐릭터 × 선택 세팅 계획</b>
            <div class="hint">캐릭터 자료를 복사하지 않고, 현재 켠 세팅·씬을 캐릭터마다 순회합니다.
            세팅의 직접 입력 캐스트는 보존되어 언제든 돌아갈 수 있습니다.</div></div>
          <button type="button" id="cmpPlanAllChars" class="primary">전 캐릭터 계획 적용</button>
          <button type="button" id="cmpPlanManual">직접 캐스트로 복귀</button>
          <span class="hint" id="cmpPlanMsg"></span>
        </div>

        <div class="grid3" style="margin-top:8px;">
          <div class="field"><label>비교 해상도</label>
            <select id="cmpRes">__RES__<option value="custom">직접 입력</option></select>
            <div class="hidden" id="cmpCustom" style="margin-top:5px;display:grid;
              grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:5px;">
              <input type="number" id="cmpW" min="64" max="2048" step="64" value="832" aria-label="비교 너비">
              <span>×</span>
              <input type="number" id="cmpH" min="64" max="2048" step="64" value="1216" aria-label="비교 높이">
            </div>
            <label class="hint" style="display:flex;align-items:center;gap:5px;margin-top:6px;">
              <input type="checkbox" id="cmpFix" checked style="width:auto;flex:none;"> 모든 결과를 이 크기로 고정</label>
          </div>
          <div class="field"><label>비교 시드</label>
            <input type="number" id="cmpSeed" min="0" max="4294967295" step="1" value="0"
              placeholder="0 = 시작할 때 한 번 정함">
            <label class="hint" style="display:flex;align-items:center;gap:7px;margin-top:6px;">
              자료마다 확인할 시드
              <select id="cmpSeedCount" style="width:auto;">
                <option value="1">1개</option><option value="2">2개</option>
                <option value="3">3개</option><option value="4">4개</option>
              </select>
            </label>
            <label class="hint" style="display:flex;align-items:center;gap:5px;margin-top:6px;">
              <input type="checkbox" id="cmpSameSeed" checked style="width:auto;flex:none;">
              같은 시드 차례끼리 공정하게 비교</label>
          </div>
          <div class="field"><label>시험 상한 <span class="hint">(0 = 전부)</span></label>
            <input type="number" id="cmpLimit" min="0" max="2000000" step="1" value="0">
            <label class="hint" style="display:flex;align-items:center;gap:5px;margin-top:6px;">
              <input type="checkbox" id="cmpRefs" style="width:auto;flex:none;"> 현재 바이브·캐릭터 레퍼런스도 포함</label>
          </div>
        </div>

        <details class="row" id="cmpHistory" style="margin-top:8px;">
          <summary style="cursor:pointer;font-weight:700;">지난 비교 실험 · 중단 작업</summary>
          <div class="bar" style="margin-top:8px;flex-wrap:wrap;">
            <select id="cmpRuns" style="flex:1;min-width:260px;">
              <option value="">실험 기록을 불러오는 중...</option>
            </select>
            <button type="button" id="cmpRunRefresh">새로고침</button>
            <button type="button" id="cmpRunLoad">계획 불러오기</button>
            <button type="button" id="cmpRunOpen">결과 선별</button>
          </div>
          <div class="hint" id="cmpRunMsg" style="margin-top:6px;">
            중단된 실험은 당시 계획을 불러온 뒤 현재 장수와 비용을 다시 확인해야 이어집니다.
          </div>
        </details>
        <div class="row" id="cmpSummary" style="margin-top:8px;line-height:1.6;">
          자료 수와 생성 장수를 계산하는 중입니다.
        </div>
        <div class="bar" style="margin-top:8px;align-items:center;">
          <label style="display:flex;align-items:center;gap:6px;flex:1;">
            <input type="checkbox" id="cmpConfirm" style="width:auto;flex:none;">
            <span id="cmpConfirmText">장수와 API 호출 횟수를 확인했습니다.</span></label>
          <button type="button" id="cmpOpenResults">▦ 최근 결과 선별</button>
          <button class="go" id="cmpStart" disabled>▶ 비교 생성 시작</button>
        </div>
      </div>

      <div class="card" id="settingSelectCard">
        <h2><span class="n">세팅</span>씬 세트 <span class="count" id="setCount" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">세팅 = 씬 모음 + 부속 옵션 + 상대역이 담긴 <b>세팅/ 폴더의 파일</b>. 파일을 넣고 빼면 목록이 바뀝니다.
        각 세팅의 <b>전용 캐스트</b>를 비우면 왼쪽 [캐릭터]의 인물로 생성됩니다.</p>
        <div class="bar" style="margin-bottom:8px;">
          <button id="setExport" title="세팅/ 폴더의 세팅 파일들을 ZIP 으로 내려받습니다">📤 세팅 내보내기 (ZIP)</button>
          <button id="setImport" title="받은 세팅 ZIP·JSON 을 세팅/ 폴더에 넣습니다">📥 세팅 가져오기</button>
          <input type="file" id="setImportFile" accept=".zip,.json" multiple style="display:none;">
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="setThumbs"> 세트 대표 그림 보기</label>
          <span class="n" id="setMsg" style="margin-left:auto;"></span>
        </div>
        <div id="setList"></div>
        <div class="bar" style="margin-top:10px;">
          <select id="scenePreset" style="flex:1;"><option value="">씬 프리셋 불러오기...</option></select>
          <button id="scenePresetSave">현재 구성 저장</button>
        </div>
      </div>

      <!-- 씬 모드 — 세팅과 별도로 병존한다. 세팅을 대체하지 않는다. -->
      <div class="card" id="sceneQuickCard">
        <h2><span class="n">씬</span>씬 모드 (가벼운 낱개 변주)
          <span class="count" id="sceneCount" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">세팅이 <b>5장 묶음 + 문맥에 반응하는 옵션</b>이라면, 씬은 <b>이름·프롬프트·해상도만 있는 낱개</b>입니다.
        즉석에서 변주를 뽑을 때 씁니다. 씬 프롬프트는 왼쪽 그림체 뒤에 붙고, 조각 <b>&lt;이름&gt;</b> 도 그대로 먹습니다.
        <b>예약 매수를 1 이상</b>으로 걸어 둔 씬만 생성합니다. 결과는 <b>output/씬/</b> 에 쌓입니다.</p>
        <div class="bar">
          <button id="sceneAdd">+ 씬 추가</button>
          <button id="sceneRun" class="primary">▶ 예약한 씬 생성</button>
          <span class="n" id="sceneMsg" style="margin-left:auto;"></span>
        </div>
        <div id="sceneList" style="margin-top:8px;"></div>
      </div>

      <!-- 세팅 빌더 — 세팅을 앱 안에서 만들고 고친다 -->
      <div class="card" id="settingBuilderCard">
        <h2><span class="n">빌더</span>세팅 빌더
          <span class="count" id="sbClash" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--danger);"></span></h2>
        <p class="hint">세팅은 <b>세트(묶음)</b>의 모음입니다. 세트는 <b>단계명마다 씬 하나</b>로 이루어지고,
        단계 수는 <b>자유</b>입니다 (3단계든 7단계든). 씬 이름을 <b>「세트이름 단계명」</b>으로 지으면
        자동으로 한 묶음이 됩니다.</p>
        <div class="bar">
          <select id="sbPick" style="flex:1;"><option value="">고칠 세팅 고르기...</option></select>
          <button id="sbNew">+ 새 세팅</button>
          <button id="sbRenum" title="이 세팅의 씬 번호를 겹치지 않는 구간으로 다시 매깁니다">번호 다시 매기기</button>
          <!-- 세팅 삭제는 씬 수백 개가 함께 사라진다. `+ 새 세팅` 바로 옆은 위험하다.
               스페이서 대신 `margin-left:auto` — 위 캐릭터 칸 주석 참조. -->
          <button id="sbDel" class="danger" style="margin-left:auto;">세팅 삭제</button>
        </div>
        <div class="builder-empty-flow" id="sbEmpty">
          <div><b>1 · 세팅 파일</b><span>기존 세팅을 고르거나 새로 만듭니다.</span></div>
          <div><b>2 · 씬 세트</b><span>시작·중간·끝 같은 단계를 한 묶음으로 구성합니다.</span></div>
          <div><b>3 · 장면 내용</b><span>공통 태그, 캐릭터별 태그·네거티브·위치를 채웁니다.</span></div>
        </div>
        <div id="sbBody" class="hidden" style="margin-top:8px;">
          <div class="grid3">
            <div class="field"><label>세팅 이름</label><input type="text" id="sbName"></div>
            <div class="field"><label>방식 <span class="hint">(상대역·조립 규칙이 달라집니다)</span></label>
              <select id="sbMode">
                <option value="단독">단독 — 인물 1명</option>
                <option value="남녀">남녀 — 주인공 + 상대역(남자)</option>
                <option value="백합">백합 — 여×여</option></select></div>
            <div class="field"><label>단계명 <span class="hint">(콤마로 구분 · 세트당 씬 수)</span></label>
              <input type="text" id="sbStages" placeholder="시작, 중간, 끝"></div>
          </div>
          <div class="field"><label>계열 이름표 <span class="hint">(A=이름, B=이름 … 목록 머리글에 뜹니다)</span></label>
            <input type="text" id="sbCats" placeholder="A=바깥 계열, B=실내 계열"></div>

          <div class="sec" style="margin-top:8px;">
            <div class="sec-head" data-sbfold="sbRole"><span class="nm">상대역</span>
              <span class="sub">남녀·백합에서 쓰입니다</span></div>
            <div class="sec-body hidden" id="sbRole">
              <div class="grid2">
                <div class="field"><label>외형</label><textarea id="sbRoleLook" style="min-height:40px;"></textarea></div>
                <div class="field"><label>착의 <span class="hint">(백합)</span></label><textarea id="sbRoleWear" style="min-height:40px;"></textarea></div>
                <div class="field"><label>의상 <span class="hint">(남녀)</span></label><input type="text" id="sbRoleOutfit"></div>
                <div class="field"><label>네거티브</label><input type="text" id="sbRoleNeg"></div>
              </div>
            </div>
          </div>

          <div class="sec">
            <div class="sec-head" data-sbfold="sbAxes"><span class="nm">옵션 축</span>
              <span class="sub">고르는 값에 따라 프롬프트가 달라지는 축</span></div>
            <div class="sec-body hidden" id="sbAxes">
              <p class="hint"><b>적용</b> = 어디에 붙는지 (베이스·여자·남자·네거티브) ·
              <b>방식</b> = 어떻게 붙는지 —
              <b>고정</b>은 그대로, <b>계열별</b>은 씬의 계열(A·B…)에 따라, <b>단계별</b>은 단계 순서에 따라.</p>
              <div id="sbAxisList"></div>
              <div class="bar" style="margin-top:6px;"><button id="sbAxisAdd">+ 축 추가</button></div>
            </div>
          </div>

          <div class="sec">
            <div class="sec-head" data-sbfold="sbSets"><span class="nm">세트 추가</span>
              <span class="sub">단계명마다 씬 하나가 생깁니다</span></div>
            <div class="sec-body hidden" id="sbSets">
              <div class="grid3">
                <div class="field"><label>세트 이름</label><input type="text" id="sbSetLabel" placeholder="예: 카페"></div>
                <div class="field"><label>계열 <span class="hint">(비우면 없음)</span></label><input type="text" id="sbSetCat" placeholder="A"></div>
                <div class="field"><label>해상도</label><select id="sbSetRes"></select></div>
              </div>
              <div class="bar"><button class="primary" id="sbSetAdd">+ 세트 추가</button>
                <span class="hint">추가한 뒤 위 세팅 목록의 ✎ 로 씬 프롬프트를 채우세요</span></div>
            </div>
          </div>
          <div class="bar" style="margin-top:8px;">
            <button class="primary" id="sbSave">머리 정보 저장</button>
            <span class="n" id="sbMsg" style="margin-left:auto;"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="view" id="vBuilder" style="display:none;">
      <div class="card">
        <h2><span class="n">빌더</span>그림체와 캐릭터 만들기</h2>
        <p class="hint">수천 개 태그를 외우지 않아도 됩니다. 만들 대상을 먼저 고른 뒤 필요한 항목만 채우세요.
        결과는 원문을 줄이지 않고 파일과 라이브러리에 저장합니다.</p>
        <div class="builder-entry-grid">
          <div class="builder-entry">
            <span class="eyebrow">Style set</span><strong>🖼️ 그림체 한 세트</strong>
            <p>작가·구도·조명·화풍과 <b>네거티브·생성 설정값</b>을 한 묶음으로 보관합니다.</p>
            <button class="primary" id="bStyle">그림체 만들기</button>
          </div>
          <div class="builder-entry artist">
            <span class="eyebrow">Artist group</span><strong>🎨 작가 조합</strong>
            <p>작가 수·평점·가중치·고정 순서를 정하고 균형·곡선·무작위 조합을 만듭니다.</p>
            <button class="primary" id="bCombo">작가 조합 만들기</button>
          </div>
          <div class="builder-entry char">
            <span class="eyebrow">Character</span><strong>👤 캐릭터 한 명</strong>
            <p>정체·외형·머리·의상·원작과 다른 변형을 고릅니다. 저장 후 캐릭터 칸에 바로 넣을 수 있습니다.</p>
            <button class="primary" id="bChar">캐릭터 만들기</button>
          </div>
        </div>
        <div class="builder-tools">
          <span class="label">프롬프트 보조</span>
          <button id="bFrags">🎲 프롬프트 조각 관리 ↗</button>
          <button id="bNorm">📋 기존 프롬프트 자동 분류</button>
        </div>
      </div>
      <div class="card">
        <h2><span class="n">검색</span>태그 사전</h2>
        <p class="hint">태그/ 폴더의 CSV에서 검색합니다. 클릭하면 복사돼요.</p>
        <div class="bar"><input type="text" data-tagq="char|" placeholder="🔍 태그 검색 (예: kimono, cowgirl, artist 이름)" style="flex:1;"></div>
        <div data-tagres="char|" class="tagres" style="max-height:220px;"></div>
      </div>
    </div>

    <div class="view" id="vLibrary" style="display:none;">
      <div id="studioLibraryNav" class="studio-subnav hidden" aria-label="자료 작업 선택">
        <div class="studio-subnav-copy">
          <span class="eyebrow">자료 작업실</span>
          <strong>가져온 뒤 자료실에서 정리하고, 결과를 선별·복구합니다</strong>
        </div>
        <div class="studio-subnav-actions" role="tablist" aria-label="자료 작업">
          <button type="button" data-library-work="input" role="tab">자료 가져오기</button>
          <button type="button" data-library-work="catalog" role="tab">통합 자료실</button>
          <button type="button" data-library-work="results" role="tab">결과·선별</button>
        </div>
      </div>
      <div id="studioLibraryBrowse">
      <div class="card" id="libraryPublicCard" data-library-panel="input">
        <h2><span class="n">수집</span>공개 그림체 자료 가져오기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">결과는 공통 그림체 자료로 바로 정리</span></h2>
        <p class="hint">아카라이브 AI 그림 채널의 공개 게시글 주소를 넣거나
        <b>그림체 공유</b> 검색 결과를 훑습니다. NAI 메타데이터가 있는 원본만
        <b>베이스+네거티브+생성 설정</b> 한 묶음으로 보관하며, 같은 묶음은 새로
        복제하지 않고 이미지와 출처만 더합니다. 앱을 꺼도 진행 위치가 남습니다.</p>
        <div class="grid3" style="align-items:end;">
          <div class="field" style="grid-column:span 2;">
            <label>공개 게시글 주소 <span class="hint">(여러 개면 줄바꿈)</span></label>
            <textarea id="publicCollectUrls" style="min-height:52px;"
              placeholder="https://arca.live/b/aiart/123456789"></textarea>
          </div>
          <div class="field"><label>검색어</label>
            <input id="publicCollectKeyword" type="text" value="그림체 공유"></div>
          <div class="field"><label>검색 페이지 <span class="hint">(0=주소만)</span></label>
            <input id="publicCollectPages" type="number" value="2" min="0" max="20"></div>
          <div class="field"><label>최대 게시글</label>
            <input id="publicCollectMax" type="number" value="100" min="1" max="1000"></div>
          <div class="bar" style="align-self:end;">
            <button id="publicCollectStart" class="primary">수집 시작</button>
            <button id="publicCollectPause">일시정지</button>
            <button id="publicCollectResume">이어가기</button>
            <button id="publicCollectStop">중지</button>
          </div>
        </div>
        <div id="publicCollectStatus" class="hint" aria-live="polite"
          style="margin-top:9px;white-space:pre-wrap;">수집 기록을 확인하는 중입니다.</div>
        <div id="publicCollectFailures" class="hidden"
          style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line);">
          <div class="bar" style="flex-wrap:wrap;">
            <strong style="font-size:var(--fs-xs);">다시 확인할 게시글</strong>
            <span class="hint">성공한 자료는 건드리지 않고 고른 실패 글만 다시 읽습니다.</span>
            <button type="button" id="publicCollectRetry" style="margin-left:auto;">
              선택 실패 재시도
            </button>
          </div>
          <div id="publicCollectFailureList" style="margin-top:5px;"></div>
        </div>
      </div>

      <!-- 생성물 탐색기 — 선별 · 비교 · 가상 폴더. 파일은 옮기지 않는다 -->
      <div class="card" id="libraryResultsCard" data-library-panel="results">
        <h2><span class="n">생성물</span>탐색기 · 선별
          <span class="count" id="expCount" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-2xs);color:var(--muted);"></span></h2>
        <p class="hint">뽑아 둔 그림을 훑어보고 <b>고르는</b> 곳입니다. 그림을 누르면 크게 보이고,
        <b>←→</b> 로 넘기고 <b>F</b> 로 선별, <b>C</b> 로 비교함에 담고, <b>Esc</b> 로 닫습니다.
        폴더는 <b>이름표</b>일 뿐이라 원본 파일은 제자리에 그대로 둡니다.</p>
        <div class="filterbar">
          <button id="expUp" title="상위 폴더">⬆ 위로</button>
          <span class="n" id="expPath">output/</span>
          <label class="hint"><input type="checkbox" id="expOnlyPick"> 선별한 것만</label>
          <label class="hint"><input type="checkbox" id="expOnlyFav"> 즐겨찾기만</label>
          <select id="expSize"><option value="90">작게</option>
            <option value="130" selected>보통</option><option value="200">크게</option></select>
          <button id="expReload">새로고침</button>
        </div>
        <!-- ⚠ 한 줄에 `margin-left:auto` 를 **둘** 두지 말 것. `.bar .n{margin-left:auto}`
             에 더해 `expCompare` 에도 auto 가 붙어 있어서, 상태글이 줄 한복판에 뜨고
             단추가 좌우로 흩어져 무엇이 한 묶음인지 읽히지 않았다.
             지금은 auto 가 `expStat` 하나뿐이라 [고르는 도구들] … 상태 [지우기] 로 읽힌다.
             파괴적인 `선별 외 삭제` 는 상태글을 사이에 두고 **끝으로 떼어 놨다** — 없애지
             않았고 빨간색도 그대로다(경고는 유지해야 한다). 옆에 붙어 잘못 눌리는 것만 막는다. -->
        <div class="bar" style="margin-top:6px;">
          <button id="expCup" title="보이는 그림들을 1:1 로 붙여 순위를 매깁니다 (SDStudio 의 이미지 월드컵)">🏆 월드컵</button>
          <button id="expElo" title="파일명과 기존 점수를 가리고 반복 비교해 선호 ELO를 누적합니다">⚖ 블라인드 ELO</button>
          <button id="expCompare">🔍 비교함 보기 (<span id="expCmpN">0</span>)</button>
          <button id="expCmpClear">비교함 비우기</button>
          <button id="expApplyPicked" title="이 폴더에서 선별한 비교 결과 한 장의 원문 설정을 생성 화면에 적용합니다">↳ 선별 1장 생성에 적용</button>
          <span class="n" id="expStat"></span>
          <button id="expDelUnpicked" class="danger" title="이 폴더에서 선별 안 된 것을 실제로 지웁니다">선별 외 삭제</button>
        </div>
        <div class="bar" style="margin-top:6px;flex-wrap:wrap;">
          <span class="tag">후보군</span>
          <select id="expGroupFilter" style="width:auto;min-width:150px;">
            <option value="">전체 보기</option>
          </select>
          <input type="text" id="expGroupName"
            placeholder="후보군 이름" style="width:150px;">
          <button id="expGroupSave">선별을 후보군에 추가</button>
          <button id="expGroupDelete">후보군 이름표 삭제</button>
          <span class="hint">원본 파일은 이동하지 않습니다.</span>
        </div>
        <div id="expDirs" class="bar" style="flex-wrap:wrap;margin-top:8px;"></div>
        <div id="expGrid" style="display:grid;gap:6px;margin-top:8px;
          grid-template-columns:repeat(auto-fill,minmax(var(--ecard,130px),1fr));"></div>
      </div>

      <!-- 그림체 복구 — 뽑아 둔 그림의 메타를 읽어 그 설정 그대로 다시 돌린다.
           탐색·선별과는 하는 일이 다르다(고르는 것이 아니라 **새로 뽑는다**. 결과도
           `output/복구/` 라는 다른 자리에 쌓이고 Anlas 도 든다). 한 카드 안에 있을 때는
           선별 도구 사이에 끼어 '이것도 고르는 기능인가' 로 읽혔다. 카드를 갈랐다. -->
      <div class="card" id="libraryRestoreCard" data-library-panel="results">
        <h2><span class="n">복구</span>그림체 복구 — 그 설정 그대로 다시 뽑기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">결과는 output/복구/ 에</span></h2>
        <p class="hint">그림에 박힌 <b>프롬프트·시드·설정값</b>을 읽어 그대로 다시 돌립니다.
        메타가 지워진 그림(카톡·디스코드 경유, 메타 제거본)은 건너뜁니다.</p>
        <div class="filterbar">
          <select id="regenMode">
            <option value="generate">같은 설정으로 다시 뽑기 (시드까지 그대로)</option>
            <option value="img2img">원본을 바탕에 두고 다듬기 (img2img)</option>
          </select>
          <span class="hint" style="white-space:nowrap;">변화 강도</span>
          <input type="number" id="regenStrength" value="0.5" min="0.1" max="0.99" step="0.05" style="width:62px;">
          <button id="regenPicked">선별한 것 복구</button>
          <button id="regenAll">보이는 것 전부 복구</button>
        </div>
      </div>

      <div class="card" id="libraryPackCard" data-library-panel="input">
        <h2><span class="n">자료팩</span>자료 넣기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">후보·태그·세팅·수집물을 한 번에</span></h2>
        <p class="hint">앱 본체에는 <b>후보사전·태그·개인 세팅·수집 자료가 들어 있지 않습니다.</b>
        공개 <b>기본자료팩.zip</b>에는 빌더 후보·규격·옵션·태그만 들어 있습니다.
        개인 자료팩 또는 <b>그림체.json · 레시피.json · 작가통계.json</b>을 넣으면
        세팅·수집물을 포함해 자료 종류별 제자리로 정리됩니다.<br>
        <b>덮어쓰지 않고 없는 것만 더합니다</b> — 이미 갖고 있는 자료는 그대로 둡니다.
        같은 팩을 두 번 넣어도 안전합니다.</p>
        <div id="packDrop" class="drop" style="padding:18px;text-align:center;
          border:2px dashed var(--line);border-radius:var(--radius);cursor:pointer;">
          여기에 <b>자료팩.zip</b> 을 끌어다 놓거나 눌러서 고르세요
        </div>
        <input type="file" id="packFile" accept=".zip,.json" multiple style="display:none;">
        <div id="packMsg" class="hint" style="margin-top:8px;"></div>
        <div id="packDiff" class="hidden" style="margin-top:8px;">
          <div class="bar" style="margin-bottom:7px;">
            <button type="button" id="packSelectAll">들어오는 자산 전부 선택</button>
            <button type="button" id="packSelectNone">현재 자산 전부 유지</button>
            <span class="n" id="packSelectedCount">0개 선택</span>
          </div>
          <div id="packDiffList" class="items"
            style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:7px;"></div>
          <button type="button" id="packDiffMore" class="hidden"
            style="width:100%;margin-top:7px;">더 보기</button>
          <div class="bar" style="margin-top:8px;">
            <button type="button" id="packApply" class="primary">선택대로 넣기</button>
            <button type="button" id="packCancel">이 자료팩 건너뛰기</button>
          </div>
        </div>
        <div id="packLog" style="margin-top:10px;"></div>
        <div class="bar" style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line);
          align-items:flex-start;">
          <div id="dataStorageStatus" class="hint" style="flex:1;min-width:0;">
            자료 저장 위치를 확인하는 중입니다.
          </div>
          <button type="button" id="dataOriginsShow">이미지 출처·중복</button>
          <button type="button" id="dataInventoryShow">보유 폴더 목록</button>
          <button type="button" id="dataIndexBuild">자료 색인 다시 만들기</button>
        </div>
        <div id="dataOriginsStatus" class="hint hidden" style="margin-top:7px;"></div>
        <div id="dataInventoryStatus" class="hint hidden" style="margin-top:7px;"></div>
        <p class="hint" style="margin-top:6px;">색인은 자료 파일의 경로·크기·SHA-256만 다시 세는
        파생 목록입니다. 원본을 옮기거나 지우지 않으며, 대용량 자료에서는 시간이 걸릴 수 있습니다.</p>
        <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--line);">
          <div class="bar" style="flex-wrap:wrap;">
            <strong style="font-size:var(--fs-xs);">보유 자료 메타데이터 감사</strong>
            <span class="hint">색인을 500개씩 읽어 NAI 복원 후보만 찾습니다. 원본과 설정은 바꾸지 않습니다.</span>
            <button type="button" id="metadataAuditStart" style="margin-left:auto;">처음부터 확인</button>
            <button type="button" id="metadataAuditContinue">다음 500개</button>
            <button type="button" id="metadataAuditRetry">실패 재시도</button>
          </div>
          <div id="metadataAuditStatus" class="hint" aria-live="polite"
            style="margin-top:7px;">감사 기록을 확인하는 중입니다.</div>
          <div id="metadataAuditFound" class="bar"
            style="margin-top:7px;flex-wrap:wrap;"></div>
          <button type="button" id="metadataAuditMore" class="hidden"
            style="margin-top:7px;">복원 후보 더 보기</button>
        </div>
      </div>

      <div class="card" id="libraryBooruCard" data-library-panel="input">
        <h2><span class="n">검색</span>단부루에서 찾기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">태그·그림체를 실제 그림에서 가져오기</span></h2>
        <p class="hint">태그로 검색해서 마음에 드는 그림의 <b>태그를 그대로 가져오거나</b>,
        그 그림을 <b>바이브·캐릭터 레퍼런스로 등록</b>할 수 있습니다.
        NAI 로 만든 그림이면 <b>그림체까지</b> 뽑아옵니다.</p>
        <div class="filterbar">
          <input type="text" id="booruQ" placeholder="🔍 태그로 검색 (예: 1girl long_hair smile · 띄어쓰기로 여러 개)">
          <select id="booruSite">__BOORUS__</select>
          <select id="booruLimit"><option>20</option><option selected>40</option>
            <option>60</option><option>100</option></select>
          <select id="booruCard"><option value="small">작게</option>
            <option value="medium" selected>보통</option><option value="large">크게</option></select>
          <button id="booruGo" class="primary">검색</button>
          <button id="booruOpen" title="원본 사이트를 새 창으로">↗ 사이트에서 보기</button>
          <span class="n" id="booruStat"></span>
        </div>
        <div id="booruGrid" class="grid4"></div>
        <div class="bar"><button id="booruMore" style="flex:1;display:none;">다음 쪽 ▾</button></div>
      </div>
      <div class="card" id="libraryCatalogCard" data-library-panel="catalog">
        <h2><span class="n">자료실</span>캐릭터 · 그림체 · 레시피 · 세팅 · 생성 기록</h2>
        <p class="hint">저장 위치가 달라도 모든 큰 묶음을 한곳에서 찾습니다.
        캐릭터·그림체·레시피는 통째로 가져다 쓰고, 세팅은 편집기로,
        생성 기록은 결과와 재개 화면으로 이어집니다. 현재 쪽만 불러와 자료가
        수천 건이어도 긴 프롬프트와 메타데이터를 한꺼번에 그리지 않습니다.</p>
        <div class="filterbar">
          <input type="search" id="libFilter" placeholder="이름·프롬프트·상태를 한 번에 검색">
          <select id="libType" style="width:auto;">
            <option value="">전체 자료</option><option value="캐릭터">캐릭터</option>
            <option value="그림체">그림체</option><option value="레시피">레시피</option>
            <option value="세팅">세팅</option><option value="생성 기록">생성 기록</option>
          </select>
          <select id="libSource" style="width:auto;"><option value="">모든 출처</option></select>
          <select id="libReview" style="width:auto;" aria-label="검토 상태">
            <option value="">모든 검토 상태</option>
            <option value="pending">미검토</option>
            <option value="reviewed">검토 완료</option>
            <option value="hold">보류</option>
          </select>
          <select id="libLabel" style="width:auto;" aria-label="자료 이름표">
            <option value="">모든 이름표</option>
          </select>
          <button type="button" id="libManage" disabled>종류를 고르면 정리할 수 있습니다</button>
          <button id="libAddChar">+ 캐릭터 추가</button>
          <button id="libAddFolder">+ 폴더 추가</button>
          <span class="n" id="libCount" style="margin-left:auto;"></span>
        </div>
        <div class="bar" id="libBulkBar" style="margin:8px 0;flex-wrap:wrap;">
          <label class="hint"><input type="checkbox" id="libSelectPage"> 이 화면 전체</label>
          <span class="tag" id="libSelectedN">0개 선택</span>
          <select id="libBulkStatus" style="width:auto;" aria-label="선택 자료 검토 상태">
            <option value="">상태 유지</option>
            <option value="pending">미검토</option>
            <option value="reviewed">검토 완료</option>
            <option value="hold">보류</option>
          </select>
          <input type="text" id="libBulkLabels" style="width:190px;"
            placeholder="이름표, 쉼표로 여러 개" aria-label="선택 자료 이름표">
          <select id="libLabelMode" style="width:auto;" aria-label="이름표 적용 방식">
            <option value="add">이름표 더하기</option>
            <option value="replace">이름표 바꾸기</option>
            <option value="clear">이름표 비우기</option>
          </select>
          <button type="button" id="libBulkApply" class="primary" disabled>선택 자료 정리</button>
          <button type="button" id="libBulkUndo" disabled>↶ 방금 정리 되돌리기</button>
          <button type="button" id="libClearSelection" disabled>선택 해제</button>
          <span class="hint" id="libBulkMsg" aria-live="polite">원본 자료는 바꾸지 않고 별도 정리 장부에 저장합니다.</span>
        </div>
        <div id="libGrid" class="items" style="grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:7px;"></div>
        <div class="bar"><button type="button" id="libMore" style="flex:1;display:none;">더 보기 ▾</button></div>
      </div>
      <div class="card" id="recipeLibraryCard" data-library-panel="catalog">
        <h2><span class="n">레시피</span>남들의 조합 <span class="n" id="recStat" style="margin-left:auto;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);"></span></h2>
        <p class="hint">도랑위키 등에서 모은 실제 사용 프롬프트입니다. 눌러서 태그·포지티브·네거티브를 보고 내 것으로 가져오세요.</p>
        <div class="bar">
          <input type="text" id="recQ" placeholder="🔍 레시피 검색 (예: 정상위, 작가, 역광)" style="flex:1;">
          <select id="recAxis" style="width:auto;"><option value="">전체 축</option></select>
        </div>
        <div id="recGrid" class="items" style="grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:9px;"></div>
        <div class="bar" style="margin-top:10px;"><button id="recMore" style="flex:1;">더 보기 ▾</button></div>
      </div>

      <div class="card" id="charEditorCard" data-library-panel="catalog">
        <h2><span class="n">편집</span>캐릭터 상세
          <button type="button" id="charUndo" class="hidden" style="margin-left:auto;">↶ 최근 삭제 되돌리기</button></h2>
        <p class="hint" id="charEditMsg">복제로 의상·예술적 변형을 나누고, 삭제한 항목은 이 화면을 닫기 전 되돌릴 수 있습니다.</p>
        <div class="filterbar">
          <input type="search" id="charFilter" placeholder="편집할 캐릭터 이름·프롬프트 검색">
          <span class="n" id="charCount" style="margin-left:auto;"></span>
        </div>
        <div id="charList"></div>
        <div class="bar"><button type="button" id="charMore" style="flex:1;display:none;">편집할 캐릭터 더 보기 ▾</button></div>
        <div id="folderList"></div>
      </div>
      </div>
    </div>

    <div class="view" id="vSystem" style="display:none;">
      <div id="studioManageNav" class="studio-subnav hidden" aria-label="관리 작업 선택">
        <div class="studio-subnav-copy">
          <span class="eyebrow">관리 작업실</span>
          <strong>설정과 안전장치, 진행 작업, 출력 도구를 나눠 봅니다</strong>
        </div>
        <div class="studio-subnav-actions" role="tablist" aria-label="관리 작업">
          <button type="button" data-manage-work="jobs" role="tab">작업·진단</button>
          <button type="button" data-manage-work="environment" role="tab">계정·화면</button>
          <button type="button" data-manage-work="safety" role="tab">백업·복구</button>
          <button type="button" data-manage-work="tools" role="tab">출력 도구</button>
        </div>
      </div>
      <div class="card" data-manage-panel="environment">
        <h2><span class="n">01</span>API</h2>
        <p class="hint">novelai.net → 설정(톱니바퀴) → Account → Get Persistent API Token</p>
        <div class="field"><label>NAI 토큰 (pst-...)</label>
          <div class="bar"><input type="password" id="token" placeholder="pst-..." autocomplete="off" style="flex:1;">
            <button type="button" id="tokenShow" aria-pressed="false">보기</button></div>
        </div>
        <hr style="border:0;border-top:1px solid var(--line);margin:14px 0 10px;">
        <label style="font-weight:600;">부루 계정 <span class="hint">— 자료 탭의 태그 검색에 씁니다 (선택)</span></label>
        <p class="hint" style="margin:4px 0 8px;">
          <b>겔부루</b>는 키가 없으면 아예 검색되지 않습니다.
          <b>단부루</b>는 안 넣어도 되지만 넣으면(골드 이상) 태그 2개 제한이 6개로 풀립니다.
          <b>e621</b>은 한국에서 지역 차단이라 키가 있어도 막힙니다.
        </p>
        <div class="grid2">
          <div class="field"><label>단부루 아이디</label><input type="text" id="bkDanUser" placeholder="로그인 이름"></div>
          <div class="field"><label>단부루 API Key</label><input type="password" id="bkDanKey" placeholder="My Account → API Key"></div>
          <div class="field"><label>겔부루 user_id</label><input type="text" id="bkGelUser" placeholder="숫자"></div>
          <div class="field"><label>겔부루 api_key</label><input type="password" id="bkGelKey" placeholder="Options → API Access Credentials"></div>
          <div class="field"><label>e621 아이디</label><input type="text" id="bkE6User" placeholder="로그인 이름"></div>
          <div class="field"><label>e621 API Key</label><input type="password" id="bkE6Key" placeholder="Manage API Access"></div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
          <button class="btn" id="bkTest">연결 확인</button>
          <span class="hint" id="bkMsg"></span>
        </div>
      </div>
      <div class="card" data-manage-panel="environment">
        <h2><span class="n">02</span>화면 · 디자인</h2>
        <p class="hint">화면 구성과 색 테마·강조색·글씨 크기·모서리를 바꿀 수 있습니다. 즉시 반영되고 저장됩니다.</p>
        <div class="field"><label>화면 구성</label><div id="layoutChips"></div>
          <p class="hint" style="margin-top:5px;">작업실은 기능을 줄이지 않고 탭마다 필요한 작업면을 크게 씁니다. 익숙한 배치가 필요하면 기존 호환으로 돌아갈 수 있습니다.</p>
        </div>
        <div class="field"><label>테마</label><div id="themeChips"></div></div>
        <div class="grid3">
          <div class="field"><label>강조색</label><div id="accentChips"></div></div>
          <div class="field"><label>글씨 크기</label><div id="fsChips"></div></div>
          <div class="field"><label>모서리</label><div id="radiusChips"></div></div>
        </div>
        <div class="field" style="margin-top:8px;">
          <label>가중치 색으로 보기 <span class="hint">— 프롬프트 칸의 강조·약화를 색으로 표시</span></label>
          <select id="uiHighlight"><option value="off">끔 (선명한 원문)</option><option value="on">켬</option></select>
          <p class="hint" style="margin-top:5px;">
            <b style="background:rgba(190,70,70,.42);padding:0 3px;border-radius:3px;">2.0↑ 아주 강함</b>
            <b style="background:rgba(180,74,74,.30);padding:0 3px;border-radius:3px;">1.4~2.0</b>
            <b style="background:rgba(170,80,80,.20);padding:0 3px;border-radius:3px;">1.0~1.4</b>
            <b style="background:rgba(74,124,196,.22);padding:0 3px;border-radius:3px;">0.5~1.0 약함</b>
            <b style="background:rgba(64,108,196,.32);padding:0 3px;border-radius:3px;">0.5↓</b>
            <b style="background:rgba(48,96,204,.46);padding:0 3px;border-radius:3px;">음수 = 빼기</b></p>
          <p class="hint" style="margin-top:4px;">NAI 와 같은 규칙입니다 —
            <b>강조는 붉은색, 약화·음수는 파란색</b>.</p>
        </div>
      </div>

      <div class="card" data-manage-panel="environment">
        <h2><span class="n">03</span>계정 여러 개 (프로필)
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">지금: __PROFNOW__</span></h2>
        <p class="hint">계정을 <b>따로 결제해서 두 대를 동시에</b> 돌릴 때 씁니다.
        프로필마다 <b>토큰·설정·진행상태·생성물</b>이 갈리고, 그림체·태그·후보사전·조각은 <b>함께</b> 씁니다.
        포트도 자동으로 갈립니다 (첫째 8787 · 둘째 8788 …).</p>
        <p class="hint"><b>쓰는 법</b> — 폴더의 <b>실행_둘째계정.bat</b> 을 더블클릭하면 둘째 프로필로 열립니다.
        직접 이름을 정하려면 명령창에서 <b>실행.bat --profile 이름</b>.
        프로필 데이터는 <b>프로필/&lt;이름&gt;/</b> 에 쌓입니다.</p>
        <p class="hint" style="color:var(--danger);">⚠ <b>같은 계정으로 두 대를 돌리지 마세요.</b>
        요청이 겹쳐 제한에 걸릴 위험이 커집니다. 프로필은 계정이 <b>다를 때</b> 쓰는 기능입니다.</p>
      </div>

      <div class="card" id="jobCenterCard" data-manage-panel="jobs">
        <h2><span class="n">작업</span>진행·재개 센터
          <button type="button" id="jobCenterRefresh" style="margin-left:auto;">↻ 새로고침</button></h2>
        <p class="hint">현재 생성 실행권과 앱 재시작 뒤에도 남는 세팅 배치·비교 실험·공개자료 수집 기록을 함께 봅니다.
        각 기능의 원래 저장 구조를 유지하고 이 화면은 상태를 한곳에 모아 보여 줍니다.</p>
        <div id="jobCenterList" class="items" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:7px;">
          <div class="row hint">작업 상태를 확인하는 중입니다.</div>
        </div>
      </div>

      <div class="card" id="backupCard" data-manage-panel="safety">
        <h2><span class="n">안전</span>내 자료 전체 백업</h2>
        <p class="hint">현재 프로필의 설정·선별과 공용 캐릭터·그림체·세팅·조각·자료 원문을
        manifest와 SHA-256 내용 검사로 한 ZIP에 묶습니다.
        <b>API 토큰·output 생성물·로그·원격 이미지 캐시는 넣지 않습니다.</b>
        복원할 때도 기존에만 있는 파일은 지우지 않으며, 먼저 변경 수를 보여 준 뒤 실행합니다.</p>
        <div class="bar" style="flex-wrap:wrap;">
          <button type="button" id="backupExport" class="primary">⬇ 내 자료 백업 만들기</button>
          <button type="button" id="backupChoose">⬆ 백업 파일 검사</button>
          <input type="file" id="backupFile" accept=".zip" style="display:none;">
          <button type="button" id="backupRestore" class="danger" disabled>검사한 백업 복원</button>
          <button type="button" id="backupRollback" class="hidden">↶ 방금 복원 되돌리기</button>
        </div>
        <div id="backupMsg" class="hint" style="margin-top:8px;"></div>
        <div id="backupDiff" class="hidden" style="margin-top:8px;">
          <div class="bar" style="margin-bottom:7px;">
            <button type="button" id="backupSelectAll">들어오는 변경 전부 선택</button>
            <button type="button" id="backupSelectNone">선택 해제</button>
            <span class="n" id="backupSelectedCount">0개 선택</span>
          </div>
          <div id="backupDiffList" class="items"
               style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:7px;"></div>
          <button type="button" id="backupDiffMore" class="hidden" style="width:100%;margin-top:7px;">더 보기</button>
        </div>
      </div>

      <div class="card" id="trashCard" data-manage-panel="safety">
        <h2><span class="n">안전</span>생성물 휴지통
          <button type="button" id="trashRefresh" style="margin-left:auto;">↻ 새로고침</button></h2>
        <p class="hint">생성물 탐색기에서 치운 파일은 영구 삭제되지 않고 묶음별로 남습니다.
        앱을 다시 연 뒤에도 원하는 묶음을 복원할 수 있으며,
        <b>선별·즐겨찾기·후보군·순위·별점·판단 태그</b>도 함께 돌아옵니다.
        자동 만료와 영구 비우기는 하지 않습니다.</p>
        <div id="trashList" class="hint">휴지통을 확인하는 중입니다.</div>
      </div>

      <div class="card" id="localImageCard" data-manage-panel="safety">
        <h2><span class="n">안전</span>자료 이미지 무결성</h2>
        <p class="hint">그림체·레시피 JSON의 <code>local:</code> 참조와 실제 이미지 바이트를 맞춰 봅니다.
        과거 판의 파일명 해시가 현재 WebP 바이트와 다른 것은 곧바로 손상으로 판정하지 않습니다.
        <b>파일 누락과 실제 이미지 열기 실패를 따로 검사</b>하며, 미사용 후보는 자동 삭제하지 않습니다.</p>
        <div class="bar" style="flex-wrap:wrap;">
          <button type="button" id="localImageScan" class="primary">이미지 검사</button>
          <button type="button" id="localImageNormalize" disabled>참조 이름 안전 정리</button>
          <button type="button" id="localImageRollback" class="hidden">↶ 방금 정리 되돌리기</button>
        </div>
        <div id="localImageMsg" class="hint" style="margin-top:8px;"></div>
      </div>

      <div class="card" data-manage-panel="jobs">
        <h2><span class="n">04</span>알림 · 단축키
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">565장은 몇 시간이 걸립니다</span></h2>
        <div class="bar" style="flex-wrap:wrap;">
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="notifySound"> 다 끝나면 소리로 알리기</label>
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="notifySystem"> 시스템 알림 띄우기</label>
          <button id="notifyTest">지금 시험해 보기</button>
          <span class="n" id="notifyMsg"></span>
        </div>
        <p class="hint" style="margin-top:8px;"><b>단축키</b> —
          <b>Alt+1~5</b> 탭 이동 ·
          생성물 탐색기에서 그림을 열면 <b>←→</b> 넘기기 · <b>F</b> 선별 · <b>S</b> 즐겨찾기 ·
          <b>C</b> 비교함 · <b>Esc</b> 닫기</p>
      </div>

      <!-- 진단 — 무엇이 왜 실패했는지 앱 안에서 본다 (nais_blue 의 DiagnosticDrawer) -->
      <div class="card" data-manage-panel="jobs">
        <h2><span class="n">04b</span>진단 · 최근 기록
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">생성.log 를 앱 안에서</span></h2>
        <p class="hint">실패 원인을 파일을 찾아 열지 않고 시간·심각도·종류별로 봅니다.
        토큰·서명·사용자 홈 경로는 서버에서 지운 뒤 표시합니다. <b>오류만</b>을 켜면 경고·오류만 남습니다.</p>
        <div class="bar" style="flex-wrap:wrap;">
          <button id="diagLoad">↻ 불러오기</button>
          <label class="hint"><input type="checkbox" id="diagErrOnly"> 오류만</label>
          <select id="diagN" title="줄 수"><option>100</option><option selected>300</option><option>1000</option></select>
          <button id="diagCopy">📋 복사</button>
          <button id="diagExport">⬇ 안전 JSON</button>
          <span class="n" id="diagStat" style="margin-left:auto;"></span>
        </div>
        <pre id="diagOut" style="max-height:260px;overflow:auto;background:var(--bg);padding:8px;
          font-size:var(--fs-2xs);line-height:1.45;white-space:pre-wrap;word-break:break-all;margin:6px 0 0;"></pre>
      </div>

      <span id="mosaicClassicHome" hidden aria-hidden="true"></span>
      <div class="card" id="mosaicCard" data-manage-panel="tools">
        <h2><span class="n">05</span>모자이크 칠하기
          <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">내 컴퓨터에서 · Anlas 안 듦</span></h2>
        <p class="hint">가릴 곳을 붓으로 칠하면 그 부분만 모자이크로 바꿉니다. NAI 를 거치지 않아 <b>공짜</b>입니다.
        결과는 <b>output/모자이크/</b> 에 저장됩니다.</p>
        <div id="mosDrop" class="row" style="text-align:center;padding:16px 14px;border-style:dashed;cursor:pointer;">
          <b>🟦 가릴 그림을 여기에 놓거나 눌러서 고르세요</b>
          <input type="file" id="mosFile" accept="image/png,image/webp" style="display:none;">
        </div>
        <div id="mosStage" class="hidden" style="margin-top:8px;">
          <canvas id="mosCanvas" style="max-width:100%;display:block;border:1px solid var(--line);
            border-radius:var(--radius);cursor:crosshair;"></canvas>
          <div class="filterbar" style="margin-top:8px;">
            <span class="hint" style="white-space:nowrap;">붓 굵기</span>
            <input type="range" id="mosBrush" min="16" max="200" step="4" value="72" style="width:120px;">
            <span class="hint" style="white-space:nowrap;">모자이크 크기</span>
            <input type="range" id="mosBlock" min="4" max="48" step="2" value="16" style="width:120px;">
            <span class="n" id="mosBlockN">16px</span>
            <button id="mosReset">처음으로</button>
            <button class="primary" id="mosSave">저장</button>
          </div>
          <p class="hint" id="mosMsg"></p>
        </div>
      </div>

      <div class="card" data-manage-panel="jobs">
        <h2><span class="n">06</span>밴 예방 · 속도 <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">쉬는 자리는 장과 장 사이입니다</span></h2>
        <p class="hint">한꺼번에 몰아치면 NAI 가 요청을 막습니다. 장 사이에 쉬고, 일정 장수마다 길게 쉽니다.
        <b>생성 도중에는 절대 끊지 않습니다</b> — 항상 한 장을 끝낸 뒤에 쉽니다.</p>
        <div class="grid3">
          <div class="field"><label>장 사이 간격 — 최소 (초)</label>
            <input type="number" id="paceDmin" step="0.5" min="0" max="120"></div>
          <div class="field"><label>장 사이 간격 — 최대 (초)</label>
            <input type="number" id="paceDmax" step="0.5" min="0" max="300"></div>
          <div class="field"><label>일일 상한 (장)</label>
            <input type="number" id="paceDaily" step="100" min="1" max="100000"></div>
          <div class="field"><label>짧게 쉬기 — 몇 장마다 (0=안 함)</label>
            <input type="number" id="paceSoftEvery" step="10" min="0" max="100000"></div>
          <div class="field"><label>짧게 쉬기 — 몇 초</label>
            <input type="number" id="paceSoftSec" step="5" min="1" max="3600"></div>
          <div class="field"><label>길게 쉬기 — 몇 장마다 (0=안 함)</label>
            <input type="number" id="paceCoolEvery" step="100" min="0" max="100000"></div>
          <div class="field"><label>길게 쉬기 — 몇 초</label>
            <input type="number" id="paceCoolSec" step="30" min="1" max="7200"></div>
        </div>
        <p class="hint" id="paceCalc"></p>
      </div>

      <div class="card" data-manage-panel="tools">
        <h2><span class="n">07</span>메타데이터 제거 <span class="count" style="margin-left:auto;font-size:var(--fs-2xs);color:var(--muted);">남에게 줄 사본 만들기</span></h2>
        <p class="hint">NAI 그림에는 프롬프트가 <b>두 군데</b> 들어 있습니다 —
        파일 정보(EXIF·PNG 텍스트)와 <b>알파 채널에 숨은 스텔스</b>. 앞엣것만 지우면
        novelai.net/inspect 로 뒤엣것이 그대로 읽힙니다. 여기서는 <b>둘 다</b> 지웁니다.
        원본은 그대로 두고 <b>output/메타제거/</b> 에 사본을 만듭니다.</p>
        <div id="stripDrop" class="row" style="text-align:center;padding:20px 14px;border-style:dashed;cursor:pointer;">
          <b>🧹 메타를 지울 그림을 여기에 놓거나 눌러서 고르세요</b>
          <div class="hint" style="margin-top:4px;">PNG / WebP · 여러 장 가능 · 투명 그림은 PNG 로, 나머지는 WebP 로 나옵니다</div>
          <input type="file" id="stripFile" accept="image/png,image/webp" multiple style="display:none;">
        </div>
        <div class="filterbar" style="margin-top:8px;">
          <span class="hint" style="white-space:nowrap;">경량화 — 긴 변</span>
          <select id="stripSide">
            <option value="0" selected>그대로</option><option value="1536">1536px</option>
            <option value="1024">1024px</option><option value="768">768px</option>
            <option value="512">512px</option></select>
          <span class="hint" style="white-space:nowrap;">품질</span>
          <input type="number" id="stripQ" value="95" min="40" max="100" step="5" style="width:60px;">
          <label class="hint" style="display:flex;align-items:center;gap:5px;margin:0;">
            <input type="checkbox" id="stripWebp"> 투명 그림도 WebP 로 (더 작게)</label>
        </div>
        <div class="bar" style="margin-top:6px;"><span class="n" id="stripMsg"></span></div>
      </div>

      <div class="card" data-manage-panel="environment">
        <h2><span class="n">08</span>파일 구조</h2>
        <p class="hint">
        <b>세팅/</b> 씬 세트 · <b>캐릭터/</b> 캐릭터 DB · <b>그림체/</b> 베이스 프리셋 · <b>태그/</b> 태그 사전 CSV<br>
        <b>규격.json</b> 분류 원리 · <b>후보사전.json</b> 빌더 슬롯/후보 · <b>씬프리셋/</b> 조합 저장 · <b>설정.json</b> 현재 상태</p>
      </div>
    </div>
  </div>

  <!-- ══ 오른쪽: 히스토리 ══ -->
  <div class="right">
    <div class="hist-t">최근 생성</div>
    <div class="hist-g" id="hist"></div>
  </div>
</div>

<div class="modal-bg" id="modalBg" style="display:none;">
  <div class="modal">
    <h3 id="modalTitle"></h3>
    <div id="modalBody"></div>
    <div class="bar" style="margin-top:12px;">
      <button class="primary" id="modalSave">저장</button>
      <button id="modalClose">닫기</button>
      <span class="flash" id="modalFlash"></span>
    </div>
  </div>
</div>
<script>
function showFatalError(reason){
  const message = reason && (reason.message || reason.stack || String(reason));
  let bar = document.getElementById('fatalErrorBar');
  if(!bar){
    bar = document.createElement('div');
    bar.id = 'fatalErrorBar';
    bar.setAttribute('role', 'alert');
    bar.style.cssText = 'position:fixed;z-index:99999;left:12px;right:12px;top:12px;'
      + 'padding:12px 14px;border:2px solid #b42318;border-radius:10px;background:#fff1f0;'
      + 'color:#7a271a;font:14px/1.45 system-ui;box-shadow:0 6px 24px #0004';
    const title = document.createElement('strong');
    title.textContent = '화면 실행 중 오류가 발생했습니다.';
    const detail = document.createElement('div');
    detail.id = 'fatalErrorDetail';
    detail.style.cssText = 'margin-top:4px;white-space:pre-wrap;word-break:break-word';
    const reload = document.createElement('button');
    reload.type = 'button';
    reload.textContent = '새로고침';
    reload.style.cssText = 'margin-top:8px;padding:5px 10px;cursor:pointer';
    reload.addEventListener('click', () => location.reload());
    bar.append(title, detail, reload);
    (document.body || document.documentElement).appendChild(bar);
  }
  const detail = document.getElementById('fatalErrorDetail');
  if(detail) detail.textContent = (message || '알 수 없는 오류') + '\n생성.log의 마지막 오류도 함께 확인해 주세요.';
}
window.addEventListener('error', event => showFatalError(event.error || event.message));
window.addEventListener('unhandledrejection', event => showFatalError(event.reason));
window.NAI_STUDIO_BOOTSTRAP = {resolutions: __RESJSON__};
</script>
<script src="/ui/studio-core.js"></script>
<script src="/ui/studio-generation.js"></script>
<script src="/ui/studio-settings.js"></script>
<script src="/ui/studio-library.js"></script>
<script src="/ui/studio.js"></script>
</body></html>
"""
