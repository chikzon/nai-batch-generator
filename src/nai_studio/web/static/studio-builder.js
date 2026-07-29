/* 태그·조각·작가 조합·그림체·캐릭터 지식을 만드는 builder 화면.
   core·generation·settings·library 뒤, 관리 기능 및 bootstrap보다 먼저 읽는다. */

/* ── 태그 자동완성 ──────────────────────────────────────────────────
   프롬프트 칸에서 마지막 콤마 뒤의 토막을 사전에서 찾아 띄운다.
   ↑↓ 로 고르고 Enter/Tab 으로 넣고 Esc 로 닫는다.
   가중치 표기(`1.4::`)와 조각(`<이름>`)은 건드리지 않는다. */
let AC = {box:null, items:[], sel:-1, target:null, from:0, to:0, timer:null};

function acClose(){
  if(AC.box) AC.box.remove();
  AC = {box:null, items:[], sel:-1, target:null, from:0, to:0, timer:AC.timer};
}
/* 캐럿 앞의 '쓰고 있는 토막' 을 찾는다 — 콤마·줄바꿈·`::`·`<>` 가 경계다 */
function acFragment(el){
  /* 캐럿 앞의 '쓰고 있는 토막' 을 찾는다.
     경계는 콤마·줄바꿈·`:`·`<>{}[]` 다. 정규식에 줄바꿈 이스케이프를 쓰면
     문자열로 심을 때 실제 줄바꿈으로 바뀌어 깨지므로 문자 비교로 찾는다. */
  const pos = el.selectionStart ?? 0;
  const left = el.value.slice(0, pos);
  const NL = String.fromCharCode(10);
  const BOUND = ',' + NL + String.fromCharCode(13) + ':<>{}[]';
  let a = pos;
  while(a > 0 && BOUND.indexOf(left[a-1]) < 0) a--;
  const frag = left.slice(a);
  const trimmed = frag.replace(/^ +/, '');
  return {text: trimmed, from: pos - trimmed.length, to: pos};
}

async function acQuery(el){
  const f = acFragment(el);
  if(!f || f.text.trim().length < 2){ acClose(); return; }
  const q = f.text.trim();
  let r;
  try{ r = await (await fetch('/api/ac?q=' + encodeURIComponent(q) + '&limit=12')).json(); }
  catch(e){ return; }
  if(!r.ok || !r.items.length){ acClose(); return; }
  /* 요청 도중에 다른 칸으로 옮겼거나 글자가 바뀌었으면 버린다 */
  const now = acFragment(el);
  if(document.activeElement !== el || !now || now.text.trim() !== q) return;
  acShow(el, r.items, now);
}
function acShow(el, items, f){
  acClose();
  AC.target = el; AC.items = items; AC.sel = 0; AC.from = f.from; AC.to = f.to;
  const box = document.createElement('div');
  box.className = 'acbox';
  box.innerHTML = items.map((it, i) =>
    `<div class="acrow${i === 0 ? ' on' : ''}" data-ac="${i}">
       <span class="t">${esc(it.tag)}</span>
       <span class="n">${it.count >= 1000 ? Math.round(it.count/1000) + 'k' : it.count}</span>
     </div>`).join('');
  document.body.appendChild(box);
  AC.box = box;
  /* 칸 아래에 붙인다 (화면 밖으로 나가면 위로) */
  const r = el.getBoundingClientRect();
  const h = Math.min(items.length * 24 + 8, 260);
  const below = window.innerHeight - r.bottom > h + 8;
  box.style.left = Math.min(r.left, window.innerWidth - 250) + 'px';
  box.style.top = (below ? r.bottom + 3 : r.top - h - 3) + 'px';
  box.style.width = Math.max(200, Math.min(r.width, 330)) + 'px';
  box.querySelectorAll('[data-ac]').forEach(row =>
    row.addEventListener('mousedown', e => { e.preventDefault(); acPick(+row.dataset.ac); }));
}
function acMove(d){
  if(!AC.box) return;
  AC.sel = (AC.sel + d + AC.items.length) % AC.items.length;
  AC.box.querySelectorAll('.acrow').forEach((r, i) => r.classList.toggle('on', i === AC.sel));
  const on = AC.box.querySelector('.acrow.on');
  if(on) on.scrollIntoView({block:'nearest'});
}
function acPick(i){
  const el = AC.target, it = AC.items[i ?? AC.sel];
  if(!el || !it) return acClose();
  const before = el.value.slice(0, AC.from), after = el.value.slice(AC.to);
  /* 뒤에 이미 콤마/줄바꿈이 있으면 또 붙이지 않는다 (이스케이프 없이 문자 비교) */
  const nx = after.replace(/^ +/, '')[0] || '';
  const tail = (nx === ',' || nx === String.fromCharCode(10) || nx === '') ? '' : ', ';
  el.value = before + it.tag + tail + after;
  const caret = (before + it.tag + tail).length;
  acClose();
  el.focus(); el.selectionStart = el.selectionEnd = caret;
  el.dispatchEvent(new Event('input', {bubbles:true}));
}
/* 프롬프트 성격의 칸에만 붙인다 */
function acAttach(el){
  if(!el || el._ac) return;
  el._ac = true;
  el.addEventListener('input', () => {
    clearTimeout(AC.timer);
    AC.timer = setTimeout(() => acQuery(el), 160);
  });
  el.addEventListener('keydown', e => {
    if(!AC.box || AC.target !== el) return;
    if(e.key === 'ArrowDown'){ e.preventDefault(); acMove(1); }
    else if(e.key === 'ArrowUp'){ e.preventDefault(); acMove(-1); }
    else if(e.key === 'Enter' || e.key === 'Tab'){ e.preventDefault(); acPick(); }
    else if(e.key === 'Escape'){ e.preventDefault(); acClose(); }
  });
  el.addEventListener('blur', () => setTimeout(acClose, 120));
}
/* 지금 있는 것 + 나중에 그려지는 것 모두 (세팅·씬·캐릭터 칸은 다시 그려진다) */
function acScan(root){
  (root || document).querySelectorAll(
    '#basePrompt, #negPrompt, [data-s3], [data-sf="prompt"], [data-sf="outfit"], ' +
    '[data-sf="negative"], [data-cf="prompt"], [data-cf="negative"], ' +
    '[data-sc="prompt"], [data-sc="char1"], [data-sc="char2"], ' +
    '[data-role], [data-flines], #fragTry'
  ).forEach(acAttach);
}
new MutationObserver(() => acScan(document)).observe(document.body, {childList:true, subtree:true});

/* ── 프롬프트 3분할 (고정 / 가변 / 디테일) ─────────────────────────
   보내는 값은 여전히 basePrompt 하나다. 세 칸을 이어 붙여 거기에 써 넣으므로
   생성·토큰 계산·그림체 저장 등 아랫단은 아무것도 안 바뀐다. */
function split3On(){ return !!(STATE.ui && STATE.ui.split3); }
function joinSplit3(){
  const v = ['baseFixed','baseVar','baseDetail']
    .map(id => ($(id).value || '').trim().replace(/,\s*$/, ''))
    .filter(Boolean);
  STATE.base_fixed = $('baseFixed').value;
  STATE.base_var = $('baseVar').value;
  STATE.base_detail = $('baseDetail').value;
  $('basePrompt').value = v.join(', ');
  STATE.base_prompt = $('basePrompt').value;
  clearActiveStyle();
}
function applySplit3(){
  const on = split3On();
  $('split3').classList.toggle('hidden', !on);
  $('basePrompt').classList.toggle('hidden', on);
  $('split3Btn').style.color = on ? 'var(--accent)' : '';
  if(on){
    /* 처음 켤 때 — 기존 프롬프트를 통째로 '고정' 에 넣는다. 내용이 사라지면 안 된다 */
    if(!(STATE.base_fixed || STATE.base_var || STATE.base_detail))
      STATE.base_fixed = STATE.base_prompt || '';
    $('baseFixed').value = STATE.base_fixed || '';
    $('baseVar').value = STATE.base_var || '';
    $('baseDetail').value = STATE.base_detail || '';
    joinSplit3();
  }
}
if($('findRepBtn')) $('findRepBtn').addEventListener('click', openFindReplace);
$('split3Btn').addEventListener('click', () => {
  STATE.ui = STATE.ui || {};
  STATE.ui.split3 = !split3On();
  applySplit3(); tokens(); save();
});
document.querySelectorAll('[data-s3]').forEach(t => t.addEventListener('input', () => {
  joinSplit3(); tokens(); save();
}));

/* ── 조각 (와일드카드) ─────────────────────────────────────────────
   조각/*.txt 가 원본이다. 앱은 그 파일을 읽고 쓴다. */
function renderFrags(){
  const host = $('fragList'); if(!host) return;
  host.innerHTML = '';
  const names = Object.keys(FRAGS).sort();
  $('bgFrags').textContent = names.length;
  $('bgFrags').style.display = names.length ? 'flex' : 'none';
  if(!names.length){
    host.innerHTML = '<p class="hint">아직 조각이 없습니다. [+ 새 조각] 을 누르거나 TXT 를 가져오세요.</p>';
    return;
  }
  names.forEach(n => {
    const lines = FRAGS[n] || [];
    const el = document.createElement('div'); el.className = 'slot';
    el.innerHTML = `<div class="r1">
        <input type="text" data-fname value="${escA(n)}" data-old="${escA(n)}" style="flex:1;">
        <span class="tag">${lines.length}줄${lines.length===1?' · 고정':''}</span>
        <button data-fins="${escA(n)}" title="프롬프트 칸에 &lt;${escA(n)}&gt; 넣기">＜＞</button>
        <button data-finsq="${escA(n)}" title="차례대로 쓰기 — &lt;*${escA(n)}&gt; 넣기">＜*＞</button>
        <button class="danger" data-fdel="${escA(n)}">✕</button></div>
      <textarea data-flines style="min-height:64px;" placeholder="한 줄에 하나씩">${esc(lines.join('\\n'))}</textarea>`;
    host.appendChild(el);
  });
  host.querySelectorAll('[data-flines]').forEach(t => t.addEventListener('change', async () => {
    const slot = t.closest('.slot'), inp = slot.querySelector('[data-fname]');
    await fragSave(inp.dataset.old, inp.value, t.value.split('\n'));
  }));
  host.querySelectorAll('[data-fname]').forEach(i => i.addEventListener('change', async () => {
    const slot = i.closest('.slot');
    await fragSave(i.dataset.old, i.value, slot.querySelector('[data-flines]').value.split('\n'));
  }));
  host.querySelectorAll('[data-fdel]').forEach(b => b.addEventListener('click', async () => {
    if(!confirm(`조각 '${b.dataset.fdel}' 을 지울까요? (조각/${b.dataset.fdel}.txt 파일이 지워집니다)`)) return;
    const r = await (await fetch('/api/frag_del', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: b.dataset.fdel})})).json();
    if(r.ok){ FRAGS = r.fragments; renderFrags(); $('fragMsg').textContent = '지웠습니다'; }
  }));
  host.querySelectorAll('[data-fins]').forEach(b => b.addEventListener('click',
    () => insertAtPrompt('<' + b.dataset.fins + '>')));
  host.querySelectorAll('[data-finsq]').forEach(b => b.addEventListener('click',
    () => insertAtPrompt('<*' + b.dataset.finsq + '>')));
}
/* 마지막으로 만졌던 프롬프트 칸에 끼워 넣는다 */
let LAST_PROMPT = null;
['basePrompt','negPrompt'].forEach(id => {
  const e = $(id); if(e) e.addEventListener('focus', () => LAST_PROMPT = e);
});
function insertAtPrompt(txt){
  const t = LAST_PROMPT || $('basePrompt');
  const a = t.selectionStart ?? t.value.length, b = t.selectionEnd ?? a;
  const need = a > 0 && !/[\s,]$/.test(t.value.slice(0, a));
  const ins = (need ? ', ' : '') + txt;
  t.value = t.value.slice(0, a) + ins + t.value.slice(b);
  t.focus(); t.selectionStart = t.selectionEnd = a + ins.length;
  t.dispatchEvent(new Event('input', {bubbles:true}));
  $('fragMsg').textContent = txt + ' 넣음';
}
async function fragSave(old, name, lines){
  const r = await (await fetch('/api/frag_save', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({old, name, lines})})).json();
  if(r.ok){ FRAGS = r.fragments; renderFrags(); $('fragMsg').textContent = `'${r.name}' 저장 ✓`; }
  else $('fragMsg').textContent = r.error || '저장 실패';
}
$('fragNew').addEventListener('click', async () => {
  const n = prompt('조각 이름 (프롬프트에서 <이름> 으로 씁니다):'); if(!n) return;
  await fragSave('', n, ['첫 줄', '둘째 줄']);
});
$('fragExport').addEventListener('click', () => {
  $('fragMsg').textContent = '내보내는 중...';
  window.location.href = '/api/frag_export';
  setTimeout(() => { $('fragMsg').textContent = '내보냄 ✓'; }, 800);
});
$('fragImport').addEventListener('click', () => $('fragImportFile').click());
$('fragImportFile').addEventListener('change', async () => {
  const files = [...$('fragImportFile').files]; if(!files.length) return;
  const added = [], skipped = [];
  for(const f of files){
    $('fragMsg').textContent = `${f.name} 넣는 중...`;
    const r = await (await fetch('/api/frag_import', {method:'POST',
      headers:{'X-Filename': encodeURIComponent(f.name)}, body: f})).json();
    (r.added||[]).forEach(x => added.push(x));
    (r.skipped||[]).forEach(x => skipped.push(x));
    if(r.fragments) FRAGS = r.fragments;
  }
  $('fragImportFile').value = '';
  renderFrags();
  $('fragMsg').textContent = (added.length ? `${added.length}개 들어옴` : '들어온 것 없음')
    + (skipped.length ? ` · 건너뜀: ${skipped[0]}` : '');
});
$('fragReset').addEventListener('click', async () => {
  const r = await (await fetch('/api/frag_reset', {method:'POST'})).json();
  $('fragMsg').textContent = r.ok ? '순번을 처음으로 돌렸습니다' : (r.error || '실패');
});
let fragTryT = null, FRAG_TRY_RESULT = null, FRAG_TRY_SEED = 0;
function paintFragTry(r){
  FRAG_TRY_RESULT = r && r.ok ? (r.result || null) : null;
  $('fragTryOut').textContent = r && r.ok ? '→ ' + r.text : ((r && r.error) || '');
  const host = $('fragTryChoices');
  host.innerHTML = '';
  ((r && r.ui_state && r.ui_state.components) || []).forEach(c => {
    const label = document.createElement('label');
    label.className = 'hint';
    label.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;';
    const value = ((c.choice || {}).value ?? '');
    label.innerHTML = `<input type="checkbox" data-frag-component="${escA(c.id)}">
      <span>${esc(c.expression || c.fragment || c.kind)} → <b>${esc(value)}</b></span>`;
    host.appendChild(label);
  });
}
async function runFragTry(selected){
  const text = $('fragTry').value;
  if(!text){ paintFragTry({ok:true,text:'',ui_state:{components:[]}}); return; }
  FRAG_TRY_SEED += 1;
  const payload = {text, seed:FRAG_TRY_SEED};
  if(selected && FRAG_TRY_RESULT){
    payload.previous = FRAG_TRY_RESULT;
    payload.reroll_ids = [...$('fragTryChoices').querySelectorAll(
      '[data-frag-component]:checked')].map(x => x.dataset.fragComponent);
    if(!payload.reroll_ids.length){
      $('fragTryOut').textContent = '다시 뽑을 선택지를 먼저 고르세요.';
      return;
    }
  }
  const r = await (await fetch('/api/frag_try', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})).json();
  paintFragTry(r);
}
$('fragTry').addEventListener('input', () => {
  clearTimeout(fragTryT);
  FRAG_TRY_RESULT = null;
  fragTryT = setTimeout(() => runFragTry(false), 300);
});
$('fragTryAgain').addEventListener('click', () => {
  FRAG_TRY_RESULT = null;
  runFragTry(false);
});
$('fragTrySelected').addEventListener('click', () => runFragTry(true));

/* ── 그림체 라이브러리 ──────────────────────────────────────────────
   한 그림체 = 작가 조합 + 베이스 + 네거티브 + 생성 설정값 전부(시드·CFG·
   리스케일·스텝·샘플러·스케줄러·해상도·Variety+). 셋이 합쳐져야 그림체다. */
let comboOffset = 0, comboT = null, COMBO_RETURN = null, WELCOME_COUNT_TIMER = null;
let comboLoadSeq = 0, comboLoadAbort = null, comboLoading = false;
let artistDraftT = null;
const CARD_PX = {small: 74, medium: 116, large: 190};
function cq(){ return {
  q: ($('comboQ')||{}).value || '', tab: ($('comboTab')||{}).value || '',
  source: ($('comboSrc')||{}).value || '', sort: ($('comboSort')||{}).value || '',
  seeded: ($('comboSeeded')||{}).checked ? '1' : '',
  rating: ($('comboRate')||{}).value || '',
  size: +(($('comboSize')||{}).value || 50) }; }

function openCombos(target){
  cancelComboWork();
  if(WELCOME_COUNT_TIMER){
    clearTimeout(WELCOME_COUNT_TIMER);
    WELCOME_COUNT_TIMER = null;
  }
  /* 빌더 안에서 열면 기존 빌더 DOM을 지우지 않고 잠시 떼어 둔다.
     예전에는 innerHTML로 빌더를 지운 뒤 이미 사라진 select를 target으로 들고 있어,
     '이 조합 쓰기'를 눌러도 아무 일도 하지 못했다. */
  if(target && document.body.contains(target)){
    const saved = document.createDocumentFragment();
    while($('modalBody').firstChild) saved.appendChild($('modalBody').firstChild);
    COMBO_RETURN = {
      body:saved, target, mode:window._mm,
      title:$('modalTitle').textContent, flash:$('modalFlash').textContent,
      saveDisplay:$('modalSave').style.display,
    };
  }else{
    COMBO_RETURN = null;
    target = null;
  }
  window._mm = 'combo';
  window._comboTarget = target || null;   // 빌더 슬롯이면 select, 아니면 설정에 적용
  $('modalSave').style.display = 'none';
  $('modalTitle').textContent = '🎨 그림체 — 프롬프트·네거티브·설정값 한 세트';
  $('modalBody').innerHTML = `
    ${COMBO_RETURN ? '<div class="bar"><button type="button" id="comboBack">← 빌더로 돌아가기</button></div>' : ''}
    <p class="hint">작가 조합만이 아니라 <b>베이스 + 네거티브 + 설정값(CFG·리스케일·스텝·샘플러·시드)</b>이
    합쳐진 한 세트입니다. <b>쪼개지 않고 통째로만</b> 적용합니다 —
    일부만 가져오면 원래 그림이 재현되지 않기 때문입니다.</p>
    <details id="comboComposer" class="row" style="margin-bottom:10px;">
      <summary style="cursor:pointer;font-weight:700;">작가 조합 직접 만들기 · 고정 작가 · 범위 · 곡선</summary>
      <p class="hint">행 순서가 실제 프롬프트 순서입니다. 고정한 작가는 다른 방식을 골라도
      그 가중치를 지키고, 무작위는 각 행의 최소~최대 안에서만 뽑습니다.</p>
      <div class="filterbar">
        <select id="comboWeightMode" style="width:auto;">
          <option value="custom">직접 가중치</option><option value="balanced">균형 1.0</option>
          <option value="curve">순서대로 곡선</option><option value="random">행별 범위 무작위</option>
        </select>
        <label class="hint">곡선 시작 <input type="number" id="comboCurveStart" value="1.2" step="0.05" style="width:68px;"></label>
        <label class="hint">끝 <input type="number" id="comboCurveEnd" value="0.8" step="0.05" style="width:68px;"></label>
        <label class="hint">무작위 시드 <input type="text" id="comboWeightSeed" placeholder="비우면 매번 새로" style="width:112px;"></label>
        <button type="button" id="comboLoadCurrent">현재 프롬프트에서 읽기</button>
      </div>
      <div id="comboArtistRows"></div>
      <div class="bar">
        <button type="button" id="comboArtistAdd">+ 작가</button>
        <button type="button" id="comboArtistPreview">가중치 조합 미리보기</button>
        <button type="button" class="primary" id="comboArtistApply">${window._comboTarget ? '빌더 칸에 넣기' : '베이스의 작가 조합으로 적용'}</button>
      </div>
      <div class="field"><label>실제 들어갈 작가 프롬프트</label>
        <textarea id="comboArtistPrompt" readonly style="min-height:58px;"></textarea></div>
      <div id="comboArtistMsg" class="hint"></div>
    </details>
    <div class="filterbar">
      <input type="text" id="comboQ" placeholder="🔍 작가·제목·프롬프트 검색 (띄어쓰기로 여러 단어)">
      <select id="comboSort" title="정렬">
        <option value="default">기본순</option><option value="recommend">추천순</option>
        <option value="views">조회순</option><option value="newest">최신순</option>
        <option value="oldest">오래된순</option><option value="artists">작가 많은순</option>
      </select>
      <select id="comboTab" title="게시판"><option value="all">전체 판</option>
        <option value="NAI">NAI</option><option value="R18_NAI">🔞 NAI</option></select>
      <select id="comboSrc" title="출처"><option value="all">전체 출처</option></select>
      <select id="comboSize" title="표시 개수">
        <option selected>20</option><option>50</option><option>100</option><option>200</option></select>
      <select id="comboCard" title="카드 크기">
        <option value="small">작게</option><option value="medium" selected>보통</option>
        <option value="large">크게</option></select>
      <label class="hint"><input type="checkbox" id="comboSeeded"> 설정값만</label>
      <select id="comboRate" title="작가 평가 필터">
        <option value="">평가 전체</option><option value="fav">💛 즐겨찾기만</option>
        <option value="rated">★ 별점 매긴 것만</option><option value="hideblock">⛔ 차단 숨기기</option></select>
      <span class="n" id="comboStat"></span>
    </div>
    <div id="comboDrop" class="row" style="text-align:center;padding:14px;border-style:dashed;cursor:pointer;">
      <b>＋ 이미지에서 그림체 뽑기</b>
      <div class="hint" style="margin-top:4px;">NAI로 만든 PNG/WebP를 여기에 끌어다 놓거나 눌러서 고르세요.
      프롬프트·네거티브·설정값을 통째로 읽어옵니다. (novelai.net/inspect 와 같은 데이터)</div>
      <input type="file" id="comboFile" accept="image/png,image/webp" multiple style="display:none;"></div>
    <div class="filterbar" style="gap:8px;flex-wrap:wrap;">
      <label class="hint" style="display:flex;align-items:center;gap:4px;white-space:nowrap;">
        <input type="checkbox" id="comboTidy" style="width:auto;flex:none;"> 🧹 정리하기</label>
      <span id="comboTidyBar" class="hidden" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
        <button id="comboAll" class="mini">보이는 것 전부</button>
        <button id="comboNone" class="mini">고르기 해제</button>
        <button id="comboDupes" class="mini">🔁 겹친 것 찾기</button>
        <button id="comboDel" class="mini" style="color:var(--bad);">고른 것 지우기</button>
        <button id="comboUndo" class="mini">↩ 되살리기</button>
        <span id="comboPickN" class="hint"></span>
      </span>
    </div>
    <div id="comboTidyMsg" class="hint"></div>
    <div id="comboList"></div>
    <div class="bar"><button id="comboMore" style="flex:1;">더 보기 ▾</button></div>`;
  if($('comboBack')) $('comboBack').addEventListener('click', () => returnToBuilder());
  const composer = $('comboComposer');
  composer.addEventListener('toggle', () => {
    if(composer.open) setupArtistWorkspace();
  });
  bindTidy();
  bindComboListActions();
  $('comboQ').addEventListener('input', () => { clearTimeout(comboT); comboT = setTimeout(() => loadCombos(false), 300); });
  ['comboSort','comboTab','comboSrc','comboSize','comboSeeded','comboRate'].forEach(id =>
    $(id).addEventListener('change', () => loadCombos(false)));
  $('comboCard').addEventListener('change', () => {
    const px = CARD_PX[$('comboCard').value] || 116;
    $('comboList').style.setProperty('--combo-thumb', px+'px');
  });
  $('comboMore').addEventListener('click', () => loadCombos(true));
  setupInspectDrop();
  loadCombos(false);
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
}

function returnToBuilder(comboValue){
  const back = COMBO_RETURN;
  if(!back) return false;
  cancelComboWork();
  $('modalBody').replaceChildren(back.body);
  $('modalTitle').textContent = back.title;
  window._mm = back.mode;
  $('modalSave').style.display = back.saveDisplay;
  window._comboTarget = null;
  COMBO_RETURN = null;
  const target = back.target;
  if(comboValue != null && document.body.contains(target)){
    if(![...target.options].some(o => o.value === comboValue)){
      const option = document.createElement('option');
      option.value = comboValue;
      option.textContent = comboValue.slice(0, 60) + (comboValue.length > 60 ? '…' : '');
      target.insertBefore(option, target.options[1] || null);
    }
    target.value = comboValue;
    if(window._bldRefresh) window._bldRefresh();
    $('modalFlash').textContent = '작가 조합을 넣고 빌더로 돌아왔습니다 ✓';
  }else{
    $('modalFlash').textContent = back.flash || '';
  }
  return true;
}

function discardComboReturn(){
  stashArtistWorkspaceDraft(true);
  cancelComboWork();
  COMBO_RETURN = null;
  window._comboTarget = null;
  $('modalSave').style.display = '';
}

function artistWorkspaceRows(){
  return [...($('comboArtistRows')||document).querySelectorAll('[data-artist-row]')].map(row => ({
    name:(row.querySelector('[data-aw="name"]')||{}).value || '',
    weight:(row.querySelector('[data-aw="weight"]')||{}).value || '1',
    min:(row.querySelector('[data-aw="min"]')||{}).value || '0.7',
    max:(row.querySelector('[data-aw="max"]')||{}).value || '1.3',
    locked:!!(row.querySelector('[data-aw="locked"]')||{}).checked,
  }));
}
function drawArtistWorkspace(rows){
  const host = $('comboArtistRows'); if(!host) return;
  const list = (rows&&rows.length) ? rows : [{
    name:'', weight:1, min:0.7, max:1.3, locked:false,
  }];
  host.innerHTML = list.map((row,index) => `<div class="filterbar" data-artist-row="${index}"
      style="margin:5px 0;padding:6px;border:1px solid var(--line);border-radius:var(--radius);">
    <span class="n" style="min-width:20px;text-align:center;">${index+1}</span>
    <input type="text" data-aw="name" value="${escA(row.name||'')}" placeholder="작가 이름" style="flex:1;min-width:180px;">
    <label class="hint">값 <input type="number" data-aw="weight" value="${escA(String(row.weight??1))}" step="0.05" style="width:66px;"></label>
    <label class="hint">범위 <input type="number" data-aw="min" value="${escA(String(row.min??0.7))}" step="0.05" style="width:66px;"></label>
    <span>~</span><input type="number" data-aw="max" value="${escA(String(row.max??1.3))}" step="0.05" style="width:66px;">
    <label class="hint"><input type="checkbox" data-aw="locked" ${row.locked?'checked':''}
      style="width:auto;"> 고정</label>
    <button type="button" data-aw-up title="프롬프트에서 앞으로">↑</button>
    <button type="button" data-aw-down title="프롬프트에서 뒤로">↓</button>
    <button type="button" data-aw-del class="danger" title="이 행 빼기">×</button>
  </div>`).join('');
}
function stashArtistWorkspaceDraft(persist=false){
  const host = $('comboArtistRows');
  if(window._comboTarget || !host || host.dataset.ready !== '1') return;
  const payload = artistWorkspacePayload();
  STATE.ui = STATE.ui || {};
  STATE.ui.artist_composer = {
    mode:payload.mode, curve_start:payload.curve_start,
    curve_end:payload.curve_end, seed:payload.seed, rows:payload.rows,
  };
  if(persist) save();
}
function scheduleArtistDraft(){
  clearTimeout(artistDraftT);
  artistDraftT = setTimeout(() => stashArtistWorkspaceDraft(true), 300);
}
async function parseArtistWorkspace(){
  const source = window._comboTarget ? (window._comboTarget.value||'') : (STATE.base_prompt||'');
  try{
    const r = await (await fetch('/api/artist_workspace', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'parse',base:source})})).json();
    if(!r.ok) throw new Error(r.error||'작가 조합을 읽지 못했습니다.');
    drawArtistWorkspace(r.rows);
    $('comboArtistMsg').textContent = r.rows.length
      ? `현재 프롬프트에서 작가 ${r.rows.length}명을 읽었습니다.`
      : '현재 프롬프트에 작가가 없어 빈 행으로 시작합니다.';
  }catch(e){ $('comboArtistMsg').textContent = String(e); }
}
function artistWorkspacePayload(){
  return {
    action:'compose',
    base:window._comboTarget ? (window._comboTarget.value||'') : (STATE.base_prompt||''),
    mode:$('comboWeightMode').value,
    curve_start:$('comboCurveStart').value,
    curve_end:$('comboCurveEnd').value,
    seed:$('comboWeightSeed').value,
    rows:artistWorkspaceRows(),
  };
}
async function composeArtistWorkspace(apply=false){
  const payload = artistWorkspacePayload();
  $('comboArtistMsg').textContent = '조합하는 중...';
  try{
    const r = await (await fetch('/api/artist_workspace', {method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
    if(!r.ok) throw new Error(r.error||'작가 조합 실패');
    drawArtistWorkspace(r.rows);
    $('comboArtistPrompt').value = r.combo || '';
    STATE.ui = STATE.ui || {};
    STATE.ui.artist_composer = {
      mode:payload.mode, curve_start:payload.curve_start,
      curve_end:payload.curve_end, seed:payload.seed, rows:r.rows,
    };
    save();
    if(!apply){
      $('comboArtistMsg').textContent = `작가 ${r.rows.length}명 · 실제 순서와 가중치를 확인하세요.`;
      return;
    }
    if(window._comboTarget){
      returnToBuilder(r.combo || '');
      return;
    }
    STATE.base_prompt = r.prompt || '';
    $('basePrompt').value = STATE.base_prompt;
    clearActiveStyle(); tokens(); save();
    $('comboArtistMsg').textContent = '기존 비작가 태그는 지키고 작가 조합만 바꿨습니다 ✓';
  }catch(e){ $('comboArtistMsg').textContent = String(e); }
}
function setupArtistWorkspace(){
  const host = $('comboArtistRows'); if(!host) return;
  if(host.dataset.ready === '1') return;
  host.dataset.ready = '1';
  const saved = !window._comboTarget && ((STATE.ui||{}).artist_composer||{});
  if(saved.mode) $('comboWeightMode').value = saved.mode;
  if(saved.curve_start != null) $('comboCurveStart').value = saved.curve_start;
  if(saved.curve_end != null) $('comboCurveEnd').value = saved.curve_end;
  if(saved.seed != null) $('comboWeightSeed').value = saved.seed;
  if(saved.rows&&saved.rows.length) drawArtistWorkspace(saved.rows);
  else parseArtistWorkspace();
  $('comboLoadCurrent').addEventListener('click', parseArtistWorkspace);
  $('comboArtistAdd').addEventListener('click', () => {
    const rows = artistWorkspaceRows();
    rows.push({name:'',weight:1,min:0.7,max:1.3,locked:false});
    drawArtistWorkspace(rows);
    scheduleArtistDraft();
    host.querySelector('[data-artist-row]:last-child [data-aw="name"]').focus();
  });
  host.addEventListener('click', event => {
    const row = event.target.closest('[data-artist-row]'); if(!row) return;
    const rows = artistWorkspaceRows(), index = Number(row.dataset.artistRow);
    if(event.target.closest('[data-aw-del]')) rows.splice(index,1);
    else if(event.target.closest('[data-aw-up]') && index>0)
      [rows[index-1],rows[index]]=[rows[index],rows[index-1]];
    else if(event.target.closest('[data-aw-down]') && index<rows.length-1)
      [rows[index+1],rows[index]]=[rows[index],rows[index+1]];
    else return;
    drawArtistWorkspace(rows);
    scheduleArtistDraft();
  });
  $('comboComposer').addEventListener('input', scheduleArtistDraft);
  $('comboComposer').addEventListener('change', scheduleArtistDraft);
  $('comboArtistPreview').addEventListener('click', () => composeArtistWorkspace(false));
  $('comboArtistApply').addEventListener('click', () => composeArtistWorkspace(true));
}

/* ── 그림에서 읽은 그림체 보여 주기 ────────────────────────────────
   ★ 그림체는 `베이스 + 네거티브 + NAI 생성 설정 전체` 가 **분리 불가능한 한 덩어리**다.
     화면에서 읽기 좋게 나눠 보여줄 수는 있어도 **적용은 언제나 통째로** 한다.
   예전에는 항목마다 체크박스를 두어 골라 넣게 했는데(`applyStyle(c, pick)`),
   그렇게 섞으면 베이스는 이 그림 것인데 설정값은 남의 것인 잡종이 되어
   **원래 그림이 재현되지 않는다.** 그래서 고르는 길을 없앴다. */
function openApplyPicker(c){
  const p = c.params || {};
  const rows = [
    ['프롬프트(베이스)', c.base ? c.base.slice(0, 90) : '', !!c.base],
    ['네거티브', (c.negative || (c.negative_full != null ? '(비움)' : '')).slice(0, 90),
      !!(c.negative || c.negative_full != null)],
    ['설정값 (CFG·리스케일·스텝·샘플러·스케줄)',
      [p.scale != null ? `CFG ${p.scale}` : '', p.cfg_rescale != null ? `리스케일 ${p.cfg_rescale}` : '',
       p.steps ? `${p.steps}스텝` : '', p.sampler || '', p.noise_schedule || ''].filter(Boolean).join(' · '),
      p.scale != null || p.steps != null || !!p.sampler],
    ['해상도', (p.width && p.height) ? `${p.width}×${p.height}` : '', !!(p.width && p.height)],
    ['UC 프리셋 · 퀄리티 태그',
      [p.uc_preset != null ? `UC ${p.uc_preset}` : '', p.quality_toggle != null ? (p.quality_toggle ? '퀄리티 켬' : '퀄리티 끔') : ''].filter(Boolean).join(' · '),
      p.uc_preset != null || p.quality_toggle != null],
    ['시드', p.seed ? String(p.seed) : '', !!p.seed],
  ].filter(r => r[2]);
  $('modalTitle').textContent = '🖼 그림에서 읽은 그림체';
  $('modalBody').innerHTML = `
    <p class="hint">그림체는 <b>베이스·네거티브·생성 설정이 한 덩어리</b>입니다.
    쪼개서 넣으면 원래 그림이 재현되지 않으므로 <b>통째로만</b> 넣습니다.</p>
    ${rows.map(([label, val]) => `<div class="row">
      <b>${esc(label)}</b>
      ${val ? `<div class="hint" style="font-family:var(--mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(val)}</div>` : ''}</div>`).join('')}
    <div class="bar"><button class="primary" id="impAll">그림체 통째로 적용</button>
      ${c._audit ? '<button type="button" id="impSaveCandidate">자료실 후보로 저장</button>' : ''}
    </div>
    ${c._audit ? '<div class="hint">원본 파일은 이동하거나 바꾸지 않습니다. 저장을 눌러야 자료실 후보가 생깁니다.</div>' : ''}`;
  $('modalBg').style.display = 'flex';
  $('impAll').addEventListener('click', () => {
    applyStyle(c);
    $('modalBg').style.display = 'none';
  });
  if($('impSaveCandidate')) $('impSaveCandidate').addEventListener('click', async () => {
    const button = $('impSaveCandidate');
    button.disabled = true;
    try{
      const response = await fetch('/api/metadata_audit_save', {
        method:'POST',
        body:JSON.stringify(c._audit),
      });
      const value = await response.json();
      if(!value.ok) throw new Error(value.error || '자료실 후보를 저장하지 못했습니다.');
      button.textContent = value.import && value.import.action === 'existing'
        ? '이미 같은 후보가 있습니다' : '자료실 후보 저장됨 ✓';
      if($('comboList')) await loadCombos(false);
    }catch(error){
      button.disabled = false;
      alert(error.message || String(error));
    }
  });
}

/* ── ⇄ 찾아 바꾸기 (SDStudio 의 FindReplaceDialog) ─────────────────────
   프롬프트·네거티브·3분할·캐릭터 칸(외형·의상·전용 네거티브)을 한꺼번에.
   작가를 통째로 갈아끼우거나 오타를 한 번에 고칠 때 쓴다. 미리보기 후 적용. */
function openFindReplace(){
  $('modalTitle').textContent = '⇄ 찾아 바꾸기';
  $('modalBody').innerHTML = `
    <p class="hint">프롬프트·네거티브·캐릭터 칸에서 한꺼번에 바꿉니다. 먼저 <b>몇 군데인지</b> 보여 주고,
    <b>바꾸기</b>를 눌러야 실제로 바뀝니다.</p>
    <div class="bar"><input type="text" id="frFind" placeholder="찾을 말 (예: artist:wanke)" style="flex:1;">
      <input type="text" id="frRepl" placeholder="바꿀 말 (비우면 지움)" style="flex:1;"></div>
    <div class="bar" style="flex-wrap:wrap;">
      <label class="hint"><input type="checkbox" id="frCase"> 대소문자 구분</label>
      <label class="hint"><input type="checkbox" id="frWord"> 태그 통째로만 (콤마 경계)</label>
      <span class="n" id="frStat" style="margin-left:auto;"></span></div>
    <div id="frPrev" class="hint" style="max-height:200px;overflow:auto;font-family:var(--mono);"></div>
    <div class="bar"><button class="primary" id="frGo">바꾸기</button></div>`;
  $('modalBg').style.display = 'flex';
  const targets = () => {
    const list = [
      ['프롬프트', () => $('basePrompt').value, v => { $('basePrompt').value = v; STATE.base_prompt = v; }],
      ['네거티브', () => $('negPrompt').value, v => { $('negPrompt').value = v; STATE.negative_prompt = v; }],
    ];
    ['baseFixed','baseVar','baseDetail'].forEach((id, i) => {
      if($(id)) list.push([['고정','가변','디테일'][i], () => $(id).value,
        v => { $(id).value = v; STATE[['base_fixed','base_var','base_detail'][i]] = v; }]);
    });
    (STATE.char_slots || []).forEach((s, i) => {
      ['prompt','outfit','negative'].forEach(k => {
        list.push([`인물${i+1}·${{prompt:'외형',outfit:'의상',negative:'네거'}[k]}`,
          () => STATE.char_slots[i][k] || '', v => { STATE.char_slots[i][k] = v; }]);
      });
    });
    return list;
  };
  const build = () => {
    const find = $('frFind').value;
    if(!find){ $('frStat').textContent = ''; $('frPrev').innerHTML = ''; return []; }
    const flags = $('frCase').checked ? 'g' : 'gi';
    const esc2 = find.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp($('frWord').checked ? `(^|,)\\s*${esc2}\\s*(?=,|$)` : esc2, flags);
    const hits = [];
    targets().forEach(([name, get, set]) => {
      const cur = get();
      if(cur && re.test(cur)){
        re.lastIndex = 0;
        const n = (cur.match(re) || []).length;
        hits.push({name, get, set, n, re});
      }
      re.lastIndex = 0;
    });
    const total = hits.reduce((a, h) => a + h.n, 0);
    $('frStat').textContent = total ? `${hits.length}칸 · ${total}군데` : '없음';
    $('frPrev').innerHTML = hits.map(h => `<div>· ${esc(h.name)} — ${h.n}군데</div>`).join('');
    return hits;
  };
  ['frFind','frRepl','frCase','frWord'].forEach(id => $(id).addEventListener('input', build));
  ['frCase','frWord'].forEach(id => $(id).addEventListener('change', build));
  $('frGo').addEventListener('click', () => {
    const hits = build();
    if(!hits.length){ $('frStat').textContent = '바꿀 것이 없습니다.'; return; }
    const repl = $('frRepl').value;
    let n = 0;
    hits.forEach(h => {
      const cur = h.get();
      h.re.lastIndex = 0;
      let out = $('frWord').checked
        ? cur.replace(h.re, (m, p1) => (repl ? `${p1 || ''}${p1 ? ' ' : ''}${repl}` : (p1 || '')))
        : cur.replace(h.re, repl);
      /* 통째로 삭제할 때 `a,, b`나 선두 콤마를 남기지 않는다. */
      if($('frWord').checked) out = out.split(',').map(x => x.trim()).filter(Boolean).join(', ');
      h.set(out); n += h.n;
    });
    if(hits.some(h => ['프롬프트','네거티브','고정','가변','디테일'].includes(h.name))){
      clearActiveStyle();
    }
    if(window.renderSlots) renderSlots();
    tokens(); save();
    $('frStat').textContent = `${n}군데 바꿨습니다 ✓`;
    build();
  });
}

/* 작가 평가 배지 — 별점·즐겨찾기·차단을 한눈에 (rater 의 ratings 를 우리 식으로) */
function rateBadge(r){
  r = r || {};
  if(r.block) return '⛔ 차단됨';
  const s = r.score ? '★'.repeat(Math.round(r.score)) + `${r.score}` : '☆ 평가';
  return (r.fav ? '💛 ' : '') + s;
}
/* 작가 평가 모달 — 조합 안의 작가마다 별점·즐겨찾기·차단·메모 */
async function openRate(artists){
  const cur = await (await fetch('/api/rate', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({list:true})})).json();
  const R = (cur.ok && cur.ratings) || {};
  const rows = artists.map(a => {
    const k = String(a).toLowerCase(), v = R[k] || {};
    return `<div class="row" data-art="${escA(k)}" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
      <b style="min-width:150px;font-family:var(--mono);font-size:var(--fs-xs);">${esc(a)}</b>
      <span>${[0,1,2,3,4,5].map(n => `<button data-star="${n}" style="padding:2px 5px;${(v.score||0)===n?'background:var(--accent);color:#fff;':''}">${n===0?'—':'★'+n}</button>`).join('')}</span>
      <label style="display:flex;gap:3px;align-items:center;"><input type="checkbox" data-fav ${v.fav?'checked':''}>즐겨찾기</label>
      <label style="display:flex;gap:3px;align-items:center;"><input type="checkbox" data-block ${v.block?'checked':''}>차단</label>
      <input type="text" data-memo placeholder="메모" value="${escA(v.memo||'')}" style="flex:1;min-width:120px;">
    </div>`;
  }).join('');
  $('modalTitle').textContent = '⭐ 작가 평가';
  $('modalBody').innerHTML = `<p class="hint">별점·즐겨찾기는 그림체 목록의 필터로 쓰이고, 차단한 작가가
    프롬프트에 있으면 생성 전에 알려 줍니다. 저장은 즉시 됩니다 (수집/작가평가.json).</p>${rows}`;
  $('modalBg').style.display = 'flex';
  const send = async (el, body) => {
    const art = el.closest('[data-art]').dataset.art;
    await fetch('/api/rate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Object.assign({artist: art}, body))});
  };
  document.querySelectorAll('#modalBody [data-star]').forEach(b => b.addEventListener('click', async () => {
    await send(b, {score: Number(b.dataset.star)});
    b.parentElement.querySelectorAll('[data-star]').forEach(x => x.style.background = '');
    b.style.background = 'var(--accent)'; b.style.color = '#fff';
  }));
  document.querySelectorAll('#modalBody [data-fav]').forEach(c2 => c2.addEventListener('change', () => send(c2, {fav: c2.checked})));
  document.querySelectorAll('#modalBody [data-block]').forEach(c2 => c2.addEventListener('change', () => send(c2, {block: c2.checked})));
  document.querySelectorAll('#modalBody [data-memo]').forEach(t => t.addEventListener('change', () => send(t, {memo: t.value})));
}

function styleCard(c){
  const p = c.params || {};
  const px = CARD_PX[($('comboCard')||{}).value || 'medium'];
  const bits = [];
  if(p.steps) bits.push(`스텝 ${p.steps}`);
  if(p.scale != null) bits.push(`CFG ${p.scale}`);
  if(p.cfg_rescale != null) bits.push(`리스케일 ${p.cfg_rescale}`);
  if(p.sampler) bits.push(String(p.sampler).replace('k_',''));
  if(p.noise_schedule) bits.push(p.noise_schedule);
  if(p.width && p.height) bits.push(`${p.width}×${p.height}`);
  if(p.variety_plus) bits.push('Variety+');
  if(p.seed) bits.push(`시드 ${p.seed}`);
  const meta = [];
  if(c.recommend != null) meta.push(`추천 ${c.recommend}`);
  if(c.views != null) meta.push(`조회 ${c.views}`);
  if(c.posted_at) meta.push(c.posted_at);
  const el = document.createElement('div');
  el.className = 'row combo-card';
  // 전체 레코드를 data-* 문자열로 버튼마다 복제하지 않는다.
  // 긴 프롬프트·메타데이터가 있는 50개 카드에서 HTML이 수백 KB로 불어나고,
  // 파싱·속성 디코딩·JSON 재파싱이 메인 스레드를 막았다.
  el._comboRecord = c;
  el.innerHTML = `<div class="tag">${esc(c.source||'도랑')}${c.tab ? ' · '+esc(c.tab) : ''} · 작가 ${c.count}명${c.title ? ' · '+esc(c.title.slice(0,34)) : ''}${meta.length ? ' · '+esc(meta.join(' · ')) : ''}</div>
    <div style="display:flex;gap:9px;">
      ${(c.images && c.images[0]) ? `<img src="/img?u=${encodeURIComponent(c.images[0])}" loading="lazy" decoding="async" fetchpriority="low" alt="" onerror="this.style.display='none'" style="width:var(--combo-thumb,${px}px);height:var(--combo-thumb,${px}px);object-fit:cover;border-radius:var(--radius);border:1px solid var(--line);flex:none;background:#0004;">` : ''}
      <div style="flex:1;min-width:0;">
        <div style="font-family:var(--mono);font-size:var(--fs-xs);line-height:1.5;max-height:66px;overflow:auto;">${esc(c.combo || '(작가 태그 없음)')}</div>
        ${bits.length ? `<div class="hint" style="margin-top:5px;">⚙ ${esc(bits.join(' · '))}</div>` : ''}
        <div class="bar" style="margin:6px 0 0;flex-wrap:wrap;">
          ${window._comboTarget ? `<button data-cuse
            title="빌더의 작가 조합 칸에 이 값을 넣습니다">이 조합 쓰기</button>` : ''}
          <button class="primary" data-cfull>그림체 통째로 적용</button>
          <button data-csave>내 프리셋으로 저장</button>
          <button data-crate
            title="이 조합의 작가들에게 별점·즐겨찾기·차단을 매깁니다">${rateBadge(c._rate)}</button>
          ${c.url ? `<a href="${escA(c.url)}" target="_blank" style="font-size:var(--fs-xs);color:var(--muted);">원본 ↗</a>` : ''}
        </div>
      </div>
    </div>`;
  return el;
}

function cancelComboWork(){
  comboLoadSeq += 1;
  comboLoading = false;
  if(comboLoadAbort){
    comboLoadAbort.abort();
    comboLoadAbort = null;
  }
  clearTimeout(comboT);
  clearTimeout(artistDraftT);
  artistDraftT = null;
}

function bindComboListActions(){
  const host = $('comboList'); if(!host || host.dataset.bound === '1') return;
  host.dataset.bound = '1';
  host.addEventListener('click', async event => {
    const button = event.target.closest('button');
    const card = event.target.closest('.combo-card');
    if(!button || !card) return;
    const c = card._comboRecord || {};
    if(button.matches('[data-cuse]')){
      returnToBuilder(c.combo || '');
      return;
    }
    if(button.matches('[data-cfull]')){
      applyStyle(c);
      return;
    }
    if(button.matches('[data-crate]')){
      const arts = c.artists || [];
      if(!arts.length){ flash('이 조합에는 작가 태그가 없습니다.'); return; }
      openRate(arts);
      return;
    }
    if(!button.matches('[data-csave]')) return;
    const name = prompt('프리셋 이름:', (c.title || '그림체').slice(0, 30));
    if(!name) return;
    const p = c.params || {};
    const res = await (await fetch('/api/style_save', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, prompt: c.base || c.combo, negative: c.negative || '',
        settings: {cfg_scale: p.scale, cfg_rescale: p.cfg_rescale, steps: p.steps,
          sampler: p.sampler, scheduler: p.noise_schedule, variety: !!p.variety_plus,
          width: p.width, height: p.height,
          uc_preset: (p.uc_preset != null ? p.uc_preset : STATE.uc_preset),
          quality_toggle: (p.quality_toggle != null ? p.quality_toggle : STATE.quality_toggle)}})})).json();
    if(res.ok){
      STYLES = res.styles; renderPresets(); renderLibrary();
      $('modalFlash').textContent = `프리셋 "${name}" 저장됨 ✓`;
    }else $('modalFlash').textContent = res.error || '저장 실패';
  });
}

/* 상태 메시지 — 모달이 열려 있으면 모달에, 아니면 첫 화면 안내에 */
function flash(msg, extraBtn){
  const inModal = $('modalBg').style.display === 'flex';
  const el = inModal ? $('modalFlash') : $('welcomeMsg');
  if(!el) return;
  el.textContent = msg;
  if(extraBtn) el.appendChild(extraBtn);
}

/* ★ 그림체 적용 — 언제나 통째로.
   그림체의 최소 단위는 `베이스 + 네거티브 + NAI 생성 설정 전체` 한 덩어리다.
   쪼개서 넣으면 베이스는 이 그림 것인데 설정값은 남의 것인 잡종이 되어
   **원래 그림이 재현되지 않는다.** 그래서 '무엇을 넣을지 고르는' 인자를 없앴다 —
   경고로 막는 대신 **애초에 부분 적용이 불가능한 모양**으로 둔다. */
function applyStyle(c){
  const p = c.params || {};
  if(Object.prototype.hasOwnProperty.call(c, 'base')){
    STATE.base_prompt = c.base || ''; $('basePrompt').value = STATE.base_prompt;
  }
  /* negative_full 이 있으면 프리셋을 떼어낸 결과라 빈 문자열도 뜻이 있다 (그대로 비운다) */
  const hasNegative = Object.prototype.hasOwnProperty.call(c, 'negative')
    || c.negative_full != null;
  if(hasNegative){
    const nv = c.negative || '';
    STATE.negative_prompt = nv; $('negPrompt').value = nv;
  }
  applyStyleSettings(p);
  STATE.style_name = c.title || c.name || c.id || '가져온 그림체';
  paintActiveStyle(); tokens(); save();
  const bits = [];
  if(Object.prototype.hasOwnProperty.call(c, 'base')) bits.push('베이스');
  if(hasNegative) bits.push('네거티브');
  if(Object.keys(p).length) bits.push('설정값');
  refreshWelcome();
  let msg = bits.join(' + ') + ' 적용됨 ✓';
  /* NAI 는 UC 프리셋·퀄리티 태그를 메타에 안 남긴다 — 문구로 되짚은 것이라 밝혀 둔다 */
  if(p.uc_preset_guessed || p.quality_toggle_guessed){
    const g = [];
    if(p.uc_preset_guessed) g.push('UC 프리셋');
    if(p.quality_toggle_guessed) g.push('퀄리티 태그');
    msg += ` (${g.join('·')}은 문구로 되짚음)`;
  }
  if(p.seed){
    const el = document.createElement('button');
    el.textContent = `시드 ${p.seed} 고정하기`;
    el.style.marginLeft = '8px';
    el.addEventListener('click', () => {
      STATE.nai_seed = Number(p.seed) || 0;
      if($('pNaiSeed')) $('pNaiSeed').value = STATE.nai_seed;
      save();
      flash(`NAI 시드 ${p.seed} 고정 ✓ (원본과 같은 그림이 나옵니다)`);
    });
    flash(msg + ` — 원본 시드 ${p.seed}`, el);
    return;
  }
  flash(msg);
}

/* ── 그림체 정리 ───────────────────────────────────────────────────
   자료를 몇천 건 넣고 나면 **지울 수 있어야** 정리가 된다.
   지운 것은 지운그림체.json 으로 가므로 되살릴 수 있다. */
const PICKED = new Set();

function tidyOn(){ return $('comboTidy') && $('comboTidy').checked; }

function paintPicks(){
  const host = $('comboList'); if(!host) return;
  host.querySelectorAll('[data-pick]').forEach(b => {
    const on = PICKED.has(b.dataset.pick);
    b.textContent = on ? '☑' : '☐';
    b.closest('.row,.card,div').style.outline = on ? '2px solid var(--accent)' : '';
  });
  if($('comboPickN')) $('comboPickN').textContent = PICKED.size ? PICKED.size + '개 고름' : '';
}

/* 카드마다 고르기 단추를 붙인다. 카드 마크업은 건드리지 않는다 —
   정리를 끌 때 원래 모습으로 정확히 돌아가야 하기 때문이다. */
function addPickBoxes(){
  const host = $('comboList'); if(!host) return;
  host.querySelectorAll('[data-cfull]').forEach(b => {
    const box = b.closest('.row') || b.parentElement;
    if(!box || box.querySelector('[data-pick]')) return;
    const id = String((box._comboRecord || {}).id || '');
    if(!id) return;
    const t = document.createElement('button');
    t.dataset.pick = id; t.className = 'mini'; t.title = '고르기';
    t.style.cssText = 'margin-right:6px;';
    t.addEventListener('click', e => {
      e.stopPropagation();
      PICKED.has(id) ? PICKED.delete(id) : PICKED.add(id);
      paintPicks();
    });
    box.insertBefore(t, box.firstChild);
  });
  paintPicks();
}

function clearPickBoxes(){
  const host = $('comboList'); if(!host) return;
  host.querySelectorAll('[data-pick]').forEach(b => {
    const box = b.closest('.row,.card,div'); if(box) box.style.outline = '';
    b.remove();
  });
}

async function tidyDupes(){
  $('comboTidyMsg').textContent = '겹친 것 찾는 중...';
  const r = await (await fetch('/api/style_dupes')).json();
  if(!r.ok){ $('comboTidyMsg').textContent = r.error || '실패'; return; }
  if(!r['묶음']){ $('comboTidyMsg').textContent = '겹친 것이 없습니다.'; return; }
  /* 각 묶음의 **첫째를 남기고 나머지를 고른다** — 첫째는 설정값이 있고
     정보가 많은 것으로 서버가 정렬해 뒀다. 지우기 전에 눈으로 볼 수 있다. */
  PICKED.clear();
  r['목록'].forEach(g => g['항목'].slice(1).forEach(it => PICKED.add(String(it.id))));
  paintPicks();
  $('comboTidyMsg').innerHTML =
    `같은 작가 조합이 <b>${r['묶음']}종 ${r['겹친항목']}건</b> (전체 ${r['전체']}건). ` +
    `묶음마다 <b>가장 정보가 많은 하나를 남기고</b> ${PICKED.size}건을 골라 뒀습니다. ` +
    `목록에서 확인한 뒤 '고른 것 지우기' 를 누르세요. (지워도 되살릴 수 있습니다)`;
}

function bindTidy(){
  if(!$('comboTidy')) return;
  $('comboTidy').addEventListener('change', () => {
    $('comboTidyBar').classList.toggle('hidden', !tidyOn());
    if(tidyOn()) addPickBoxes();
    else { PICKED.clear(); clearPickBoxes(); $('comboTidyMsg').textContent = ''; }
  });
  $('comboAll').addEventListener('click', () => {
    $('comboList').querySelectorAll('[data-pick]').forEach(b => PICKED.add(b.dataset.pick));
    paintPicks();
  });
  $('comboNone').addEventListener('click', () => { PICKED.clear(); paintPicks(); });
  $('comboDupes').addEventListener('click', tidyDupes);
  $('comboDel').addEventListener('click', async () => {
    if(!PICKED.size){ $('comboTidyMsg').textContent = '고른 것이 없습니다.'; return; }
    if(!confirm(PICKED.size + '개를 지웁니다. (되살릴 수 있습니다)')) return;
    const r = await (await fetch('/api/style_del', {method:'POST',
      body: JSON.stringify({ids:[...PICKED]})})).json();
    $('comboTidyMsg').textContent = r.error ? r.error
      : `${r['지움']}건 지움 · 남은 그림체 ${r['남음']}건 · 되살릴 수 있는 것 ${r['되살릴수있음']}건`;
    PICKED.clear(); await loadCombos(false); if(tidyOn()) addPickBoxes();
  });
    $('comboUndo').addEventListener('click', async () => {
      const r = await (await fetch('/api/style_restore', {method:'POST', body:'{}'})).json();
      $('comboTidyMsg').textContent = r.error ? r.error
      : `${r['되살림']}건 되살림`
        + (r['충돌'] ? ` · 같은 id ${r['충돌']}건은 덮지 않고 휴지통에 보존` : '')
        + ` · 휴지통에 ${r['남은휴지통']}건 남음`;
      await loadCombos(false); if(tidyOn()) addPickBoxes();
    });
}

async function loadCombos(append){
  if(append && comboLoading) return;
  const f = cq();
  if(!append) comboOffset = 0;
  const seq = ++comboLoadSeq;
  if(comboLoadAbort) comboLoadAbort.abort();
  comboLoadAbort = new AbortController();
  comboLoading = true;
  const more = $('comboMore');
  if(more){ more.disabled = true; more.textContent = '불러오는 중…'; }
  const url = `/api/combos?q=${encodeURIComponent(f.q)}&limit=${f.size}&offset=${comboOffset}`
    + `&tab=${encodeURIComponent(f.tab)}&source=${encodeURIComponent(f.source)}`
    + `&sort=${encodeURIComponent(f.sort)}&seeded=${f.seeded}`
    + `&rating=${encodeURIComponent(f.rating || '')}`;
  let r;
  try{
    r = await (await fetch(url, {signal:comboLoadAbort.signal})).json();
  }catch(error){
    if(error && error.name === 'AbortError') return;
    if(seq === comboLoadSeq){
      comboLoading = false;
      if(more) more.disabled = false;
      if($('comboStat')) $('comboStat').textContent = String(error);
    }
    return;
  }finally{
    if(seq === comboLoadSeq) comboLoadAbort = null;
  }
  if(seq !== comboLoadSeq || !r.ok || window._mm !== 'combo') return;
  $('comboStat').textContent = `${r.matched} / ${r.total}개 (설정값 ${r.seeded})`;
  const sel = $('comboSrc');
  if(sel && sel.options.length <= 1 && r.sources){
    Object.entries(r.sources).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => {
      const o = document.createElement('option'); o.value = k; o.textContent = `${k} (${v})`; sel.appendChild(o); });
  }
  const host = $('comboList');
  if(!append) host.innerHTML = '';
  // DocumentFragment로 한 번만 레이아웃한다. 50~200장을 한 장씩 붙이면
  // 모달 높이 계산과 스타일 계산이 카드 수만큼 반복된다.
  /* 첫 20장은 즉시, 사용자가 50~200장을 골랐을 때의 나머지는 프레임 사이에
     나눠 붙인다. 표시 개수 기능은 유지하면서 한 번의 긴 메인 스레드 정지만 막는다. */
  for(let start=0; start<r.items.length; start+=20){
    if(start) await new Promise(resolve => requestAnimationFrame(resolve));
    if(seq !== comboLoadSeq || window._mm !== 'combo') return;
    const fragment = document.createDocumentFragment();
    r.items.slice(start, start+20).forEach(c => fragment.appendChild(styleCard(c)));
    host.appendChild(fragment);
  }
  if(tidyOn()) addPickBoxes();      /* 더 보기로 이어 붙인 카드에도 붙는다 */
  comboOffset += r.items.length;
  if(seq === comboLoadSeq){
    comboLoading = false;
    more.disabled = false;
    more.style.display = (comboOffset < r.matched) ? '' : 'none';
    more.textContent = `더 보기 ▾ (${comboOffset} / ${r.matched})`;
  }
}

/* ── 태그 사전 검색 ── */
let tt = {};
function bindTagSearch(scope){
  scope.querySelectorAll('[data-tagq]').forEach(inp => {
    if(inp._b) return; inp._b = 1;
    const key = inp.dataset.tagq, [kind, slot] = key.split('|');
    const box = scope.querySelector(`[data-tagres="${CSS.escape(key)}"]`);
    const run = async () => {
      const q = inp.value.trim();
      const r = await (await fetch(`/api/tags?kind=${kind}&slot=${encodeURIComponent(slot)}&q=${encodeURIComponent(q)}&limit=40`)).json();
      box.innerHTML = '';
      if(!r.ok || !r.tags.length){ box.innerHTML = `<span style="font-size:var(--fs-2xs);color:var(--muted);">${q?'결과 없음':''}</span>`; return; }
      r.tags.forEach(t => {
        const c = document.createElement('span'); c.className = 'chip';
        c.innerHTML = `${esc(t.tag)} <span style="font-size:var(--fs-2xs);color:var(--muted)">${t.count>=1000?Math.round(t.count/1000)+'k':t.count}</span>`;
        c.addEventListener('click', () => {
          // 빌더 안이면 그 슬롯 칩 목록에 바로 추가하고 선택 상태로
          const field = inp.closest('[data-slot]');
          const sels = field && field.querySelector('[data-sels]');
          if(sels){
            let target = Array.from(sels.querySelectorAll('select')).find(s => !s.value) || sels.querySelector('select');
            if(!Array.from(target.options).some(o => o.value === t.tag)){
              const o = document.createElement('option');
              o.value = t.tag; o.textContent = t.tag + ' (사전)';
              target.insertBefore(o, target.options[1] || null);
            }
            target.value = t.tag;
            if(window._bldRefresh) window._bldRefresh();
            return;
          }
          const tg = scope.querySelector('#bldExtra');
          if(tg){ tg.value = (tg.value.trim() ? tg.value.trim().replace(/,$/,'') + ', ' : '') + t.tag;
            tg.dispatchEvent(new Event('input', {bubbles:true})); }
          else { navigator.clipboard && navigator.clipboard.writeText(t.tag); c.style.borderColor = 'var(--good)'; }
        });
        box.appendChild(c);
      });
    };
    inp.addEventListener('input', () => { clearTimeout(tt[key]); tt[key] = setTimeout(run, 250); });
    inp.addEventListener('focus', () => { if(!box.innerHTML) run(); });
  });
}

/* ── 빌더 ── */
/* ── 빌더 (드롭다운 + 잠금 + 랜덤) ── */
function openBuilder(kind){
  window._mm = kind;
  $('modalSave').style.display = '';
  const steps = BUILDER[kind === 'char' ? '캐릭터단계' : '베이스단계'] || [];
  const ko = BUILDER['한글'] || {};
  const isBase = kind !== 'char';
  const nSteps = steps.length;
  const hasPickedNegative = steps.some(st => st['출력'] === 'negative');
  const charCore = new Set(['인물','역할·종족','얼굴 외형','헤어','상반신 신체',
    '하반신 신체','옷 — 부위별','예술적 변형 (원작과 다르게)']);
  $('modalTitle').textContent = (isBase ? '🖼️ 베이스 빌더' : '👤 캐릭터 빌더')
    + (nSteps ? ` (${nSteps}단계)` : '');
  $('modalBody').closest('.modal').classList.add('builder-modal');
  const b = $('modalBody');
  b.innerHTML = `<div class="builder-intro">
      <div class="flow">${isBase
        ? '<b>그림체의 뼈대 → 구도·빛·화풍 → 네거티브</b> 순으로 고릅니다. 네거티브와 생성 설정은 그림체에서 분리하지 않습니다.'
        : '<b>정체 → 외모 → 머리 → 체형 → 의상 → 예술적 변형</b> 순으로 고릅니다. 상황·자세·행동은 필요할 때만 세부 단계에서 더합니다.'}</div>
      <span class="route">${isBase ? '그림체로 저장' : '캐릭터로 저장'}</span>
    </div>
    <div class="builder-toolbar">
      ${isBase ? '' : '<button id="bldCore" aria-pressed="true">모든 세부 단계 보기</button>'}
      <button id="bldOpenAll">보이는 단계 펼치기</button><button id="bldCloseAll">전부 접기</button>
      <button id="bldRnd">${isBase ? '🎲 그림체 초안' : '🎲 캐릭터 초안'}</button>
      <button id="bldClear">선택 비우기</button><span class="n" id="bldStat"></span>
    </div>
    <div class="builder-shell">
      <section class="builder-steps ${isBase ? '' : 'builder-core-only'}" id="bldSteps"></section>
      <aside class="builder-summary">
        <h4>${isBase ? '그림체 묶음' : '캐릭터 한 명'}</h4>
        <p class="summary-note">${isBase
          ? '베이스·네거티브·생성 설정을 함께 저장합니다. 설정값은 현재 생성 화면의 값을 사용합니다.'
          : '이름을 먼저 적고 외형을 고르세요. 의상·예술적 변형도 이 캐릭터 프롬프트에 함께 저장됩니다.'}</p>
        <div class="field"><label>이름</label><input type="text" id="bldName"
          placeholder="${isBase ? '예: 시네마틱 야간' : '예: 레이나'}"></div>
        <div class="builder-progress" id="bldProgress"><span class="empty">아직 고른 단계가 없습니다.</span></div>
        <div class="field"><label>직접 더할 태그</label>
          <textarea id="bldExtra" placeholder="목록에 없는 특징을 원문 그대로 입력"></textarea></div>
        <div class="field"><label>${isBase ? '베이스' : '캐릭터'} 프롬프트 미리보기</label>
          <textarea id="bldPreview" readonly></textarea></div>
        ${hasPickedNegative ? `<div class="field"><label>목록에서 고른 네거티브</label>
          <textarea id="bldNegPick" readonly></textarea></div>` : ''}
        <div class="field"><label>${isBase ? '네거티브 프롬프트' : '캐릭터 전용 네거티브 (선택)'}</label>
          <textarea id="bldNeg" placeholder="${isBase ? '직접 더할 네거티브' : '이 인물에만 적용할 네거티브'}"></textarea>
          ${isBase ? `<div class="bar" style="margin-top:5px;">
            <button id="bldPreQ">추천 퀄리티 넣기</button><button id="bldPreN">추천 네거티브 넣기</button></div>` : ''}
        </div>
        ${isBase ? '' : `<label class="apply-now"><input type="checkbox" id="bldUseNow" checked>
          <span><b>저장 후 캐릭터 칸에 바로 넣기</b><br>라이브러리에서 다시 찾는 단계를 생략합니다.</span></label>`}
      </aside>
    </div>`;
  const stepsBox = $('bldSteps');
  if(!nSteps){
    stepsBox.innerHTML = `<div class="row" style="padding:20px;text-align:center;">
      <b>빌더 후보 자료가 아직 없습니다.</b>
      <p class="hint" style="margin:7px 0 0;">기본자료팩을 자료 탭에 넣으면 후보 단계가 채워집니다.
      지금도 오른쪽의 직접 태그 입력으로 저장할 수 있습니다.</p></div>`;
  }

  /* 접힌 18단계의 후보 3천여 개를 모달을 여는 순간 전부 option으로 만들지 않는다.
     단계 헤더와 후보 수는 즉시 보이고, 실제 선택지는 그 단계를 처음 펼칠 때 채운다. */
  const hydrateSection = sec => {
    if(!sec) return;
    sec.querySelectorAll('select[data-pick]').forEach(select => {
      if(select.dataset.hydrated === '1') return;
      const fragment = document.createDocumentFragment();
      (select._bldCandidates || []).forEach(tag => {
        const option = document.createElement('option');
        option.value = tag;
        option.textContent = tag + (ko[tag] ? ' — ' + ko[tag] : '');
        fragment.appendChild(option);
      });
      select.appendChild(fragment);
      select.dataset.hydrated = '1';
    });
  };

  steps.forEach((st, si) => {
    const output = st['출력'] === 'negative' ? 'negative' : 'positive';
    const essential = !isBase && charCore.has(st['이름']);
    const sec = document.createElement('div');
    sec.className = 'sec' + (essential ? ' essential' : '');
    sec.dataset.output = output;
    sec.dataset.stepName = st['이름'];
    const rows = (st['슬롯'] || []).map((sl, li) => {
      const id = `${si}-${li}`;
      return `<div class="bld-slot" data-slot="${id}">
        <div class="bld-slot-head">
          <span class="slot-name">${esc(sl['라벨'])}</span>
          <span class="slot-count">${(sl['후보']||[]).length}개 후보</span>
          <span class="bld-slot-actions">
            <button data-lock="${id}" title="랜덤에서 제외" style="padding:3px 7px;font-size:var(--fs-xs);">🔓</button>
            <button data-more="${id}" title="같은 항목 하나 더" style="padding:3px 8px;font-size:var(--fs-xs);">＋</button>
            ${sl['조합전용'] ? `<button data-combo="${id}" style="padding:3px 8px;font-size:var(--fs-xs);color:var(--accent);">조합 고르기</button>` : ''}
            <input type="text" data-tagq="${escA(kind + '|' + st['이름'] + '·' + sl['라벨'])}"
              placeholder="🔍 후보 검색" class="bld-search">
          </span>
        </div>
        <div data-tagres="${escA(kind + '|' + st['이름'] + '·' + sl['라벨'])}" class="tagres"></div>
        <div data-sels="${id}" class="bld-selects"><select data-pick="${id}" data-output="${output}">
          <option value="">(선택 안 함)</option></select></div>
      </div>`;
    }).join('');
    sec.innerHTML = `<div class="sec-head" data-bstep="${si}">
        <span class="badge">${esc(st['번호'])}</span><span class="nm">${esc(st['이름'])}</span>
        <span class="sub">${(st['슬롯']||[]).length}항목</span>
        <span class="builder-stage-route ${output}">${output === 'negative' ? '네거티브로' : (isBase ? '베이스로' : '캐릭터로')}</span>
        <span class="cnt" data-bcnt="${si}"></span></div>
      <div class="sec-body ${si < (isBase ? 2 : 1) ? '' : 'hidden'}" data-bbody="${si}">${rows}</div>`;
    sec.querySelectorAll('select[data-pick]').forEach((select, li) => {
      select._bldCandidates = [...(((st['슬롯'] || [])[li] || {})['후보'] || [])];
    });
    stepsBox.appendChild(sec);
    if(!sec.querySelector('.sec-body').classList.contains('hidden')) hydrateSection(sec);
  });

  const composeSelected = output => {
    const parts = [];
    b.querySelectorAll(`select[data-pick][data-output="${output}"]`).forEach(s => {
      if(s.value) parts.push(s.value);
    });
    if(output === 'positive'){
      ($('bldExtra').value || '').split(',').map(x => x.trim()).filter(Boolean).forEach(x => parts.push(x));
    }
    return parts.join(', ');
  };
  const compose = () => composeSelected('positive');
  const composeNegative = () => [composeSelected('negative'), ($('bldNeg').value || '').trim()]
    .filter(Boolean).join(', ');
  window._comp = compose;
  window._compNeg = composeNegative;
  const refresh = () => {
    $('bldPreview').value = compose();
    if($('bldNegPick')) $('bldNegPick').value = composeSelected('negative');
    let pos = 0, neg = 0;
    const activeSteps = [];
    stepsBox.querySelectorAll('.sec').forEach((sec, i) => {
      const n = Array.from(sec.querySelectorAll('select[data-pick]')).filter(s => s.value).length;
      if(sec.dataset.output === 'negative') neg += n; else pos += n;
      const el = sec.querySelector(`[data-bcnt="${i}"]`);
      if(el) el.textContent = n ? `${n}개` : '';
      if(n) activeSteps.push({i, name:sec.dataset.stepName, n});
    });
    $('bldStat').textContent = `${pos}개 선택` + (neg ? ` · 네거티브 ${neg}개` : '');
    $('bldProgress').innerHTML = activeSteps.length
      ? activeSteps.map(x => `<button data-jumpstep="${x.i}">${esc(x.name)} ${x.n}</button>`).join('')
      : '<span class="empty">아직 고른 단계가 없습니다.</span>';
  };
  window._bldRefresh = refresh;

  if(window._bldClick) b.removeEventListener('click', window._bldClick);
  if(window._bldChange) b.removeEventListener('change', window._bldChange);
  if(window._bldInput) b.removeEventListener('input', window._bldInput);
  window._bldClick = e => {
    const jp = e.target.closest('[data-jumpstep]');
    if(jp){
      const head = stepsBox.querySelector(`[data-bstep="${jp.dataset.jumpstep}"]`);
      const sec = head && head.closest('.sec');
      if(sec){
        sec.querySelector('.sec-body').classList.remove('hidden');
        sec.scrollIntoView({behavior:'smooth', block:'start'});
      }
      return;
    }
    const h = e.target.closest('[data-bstep]');
    if(h){
      const body = b.querySelector(`[data-bbody="${h.dataset.bstep}"]`);
      if(body.classList.contains('hidden')) hydrateSection(h.closest('.sec'));
      body.classList.toggle('hidden');
      return;
    }
    const lk = e.target.closest('[data-lock]');
    if(lk){
      const f = b.querySelector(`[data-slot="${CSS.escape(lk.dataset.lock)}"]`);
      const on = f.dataset.locked === '1';
      f.dataset.locked = on ? '' : '1';
      lk.textContent = on ? '🔓' : '🔒';
      lk.style.color = on ? '' : 'var(--good)';
      return;
    }
    const cb = e.target.closest('[data-combo]');
    if(cb){
      const box = b.querySelector(`[data-sels="${CSS.escape(cb.dataset.combo)}"]`);
      openCombos(box.querySelector('select'));
      return;
    }
    const mr = e.target.closest('[data-more]');
    if(mr){
      const box = b.querySelector(`[data-sels="${CSS.escape(mr.dataset.more)}"]`);
      const first = box.querySelector('select');
      const cl = first.cloneNode(true);
      cl.value = '';
      box.appendChild(cl);
      return;
    }
  };
  window._bldChange = () => refresh();
  window._bldInput = () => refresh();
  b.addEventListener('click', window._bldClick);
  b.addEventListener('change', window._bldChange);
  b.addEventListener('input', window._bldInput);

  if($('bldCore')) $('bldCore').addEventListener('click', () => {
    const coreOnly = stepsBox.classList.toggle('builder-core-only');
    $('bldCore').textContent = coreOnly ? '모든 세부 단계 보기' : '핵심 단계만 보기';
    $('bldCore').setAttribute('aria-pressed', coreOnly ? 'true' : 'false');
  });
  $('bldOpenAll').addEventListener('click', () => stepsBox.querySelectorAll('.sec').forEach(sec => {
    if(sec.offsetParent !== null){
      hydrateSection(sec);
      sec.querySelector('.sec-body').classList.remove('hidden');
    }
  }));
  $('bldCloseAll').addEventListener('click', () => stepsBox.querySelectorAll('.sec-body').forEach(x => x.classList.add('hidden')));
  $('bldClear').addEventListener('click', () => {
    stepsBox.querySelectorAll('[data-slot]').forEach(f => {
      if(f.dataset.locked !== '1') f.querySelectorAll('select').forEach(s => s.value = '');
    });
    refresh();
  });
  $('bldRnd').addEventListener('click', () => {
    /* 76개 슬롯을 각각 60%로 채우던 랜덤은 캐릭터를 쉽게 만드는 대신
       서로 충돌하는 태그를 과도하게 만들었다. 핵심 단계에서 한 특징을 중심으로
       가볍게 초안을 만들고, 네거티브는 사용자가 명시적으로 고르게 둔다. */
    stepsBox.querySelectorAll('.sec').forEach(sec => {
      if(sec.dataset.output === 'negative' || (!isBase && !sec.classList.contains('essential'))) return;
      hydrateSection(sec);
      sec.querySelectorAll('[data-slot]').forEach((f, fi) => {
        if(f.dataset.locked === '1') return;
        const s = f.querySelector('select');
        if(!s || s.options.length <= 1) return;
        const chance = !isBase && sec.dataset.stepName === '인물' && fi === 0
          ? 1 : (fi === 0 ? .62 : (isBase ? .24 : .16));
        if(Math.random() < chance) s.selectedIndex = 1 + Math.floor(Math.random() * (s.options.length - 1));
        else s.value = '';
      });
    });
    refresh();
  });
  if(isBase){
    const PR = BUILDER['프리셋'] || {};
    $('bldPreQ').addEventListener('click', () => {
      $('bldExtra').value = ($('bldExtra').value.trim() ? $('bldExtra').value.trim().replace(/,$/,'') + ', ' : '') + (PR['추천 퀄리티'] || '');
      refresh();
    });
    $('bldPreN').addEventListener('click', () => { $('bldNeg').value = PR['추천 네거티브'] || ''; });
  }
  bindTagSearch(b);
  refresh();
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
  setTimeout(() => { const name = $('bldName'); if(name) name.focus(); }, 0);
}
$('bCombo').addEventListener('click', () => openCombos(null));
$('bStyle').addEventListener('click', () => openBuilder('style'));
$('bChar').addEventListener('click', () => openBuilder('char'));
$('bFrags').addEventListener('click', () => {
  setMode('preview');
  const trigger = document.querySelector('[data-ovl="frags"]');
  if(trigger) trigger.click();
});

$('bNorm').addEventListener('click', () => {
  window._mm = 'norm';
  $('modalTitle').textContent = '📋 프롬프트 규격화';
  const b = $('modalBody');
  b.innerHTML = `<p class="hint">아무 데서나 복사한 프롬프트를 붙여넣고 [분류]를 누르면 규격 그룹으로 자동 정리됩니다. 규격은 규격.json에서 수정 가능.</p>
    <div class="field"><label>원본</label><textarea id="nmIn" style="min-height:64px;" placeholder="black hair, school uniform, artist:xxx, masterpiece..."></textarea></div>
    <div class="bar"><select id="nmType" style="width:auto;"><option value="char">캐릭터 규격</option><option value="style">그림체 규격</option></select>
      <button id="nmRun">분류</button><span class="n" id="nmStat"></span></div>
    <div id="nmG"></div>
    <div class="field"><label>이름</label><input type="text" id="nmName" placeholder="저장 이름"></div>`;
  $('nmRun').addEventListener('click', () => {
    const isS = $('nmType').value === 'style';
    const groups = isS ? (SPEC['그림체_그룹']||[]) : (SPEC['캐릭터_그룹']||[]);
    const def = isS ? SPEC['그림체_기본그룹'] : SPEC['캐릭터_기본그룹'];
    const res = {}; groups.forEach(g => res[g['이름']] = []);
    ($('nmIn').value||'').replace(/\n/g,',').split(',').map(x=>x.trim()).filter(Boolean).forEach(tag => {
      const m = tag.match(/^-?[\d.]+::(.*?)::?$/);
      const core = (m ? m[1] : tag).trim().toLowerCase();
      let best = null, bl = 0;
      groups.forEach(g => (g['키워드']||[]).forEach(k => { const kl = k.toLowerCase(); if(kl.length > bl && core.includes(kl)){ best = g['이름']; bl = kl.length; } }));
      res[best || def || groups[groups.length-1]['이름']].push(tag);
    });
    let n = 0;
    $('nmG').innerHTML = groups.map(g => { const v = res[g['이름']]||[]; n += v.length;
      return `<div class="field"><label>[${esc(g['이름'])}] ${v.length}개</label><textarea data-ng="${escA(g['이름'])}" style="min-height:36px;">${esc(v.join(', '))}</textarea></div>`; }).join('');
    $('nmStat').textContent = `${n}개 분류됨`;
  });
  $('modalFlash').textContent = ''; $('modalBg').style.display = 'flex';
});
