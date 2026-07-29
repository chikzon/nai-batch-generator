/* 생성 화면의 프롬프트·레퍼런스·위치·파라미터·슬롯·이미지 편집 기능.
   studio-core.js 뒤, 나머지 기능과 bootstrap보다 먼저 classic script로 읽는다. */

let tokT = null;
async function naiTokens(){
  clearTimeout(tokT);
  tokT = setTimeout(async () => {
    try{
      /* ⚠ 실제 전송값은 prompt + outfit 이다 — 의상을 빼고 세면 화면은 512 이하인데
         실전송이 넘어 뒷부분이 잘린다 (CQA-009). 캐릭터 네거티브도 함께 센다.
         켠 칸만 세는 것도 전송 규칙과 같다. */
      const clean = x => (x || '').replace(/^[ \t]*#.*$/gm, '').trim();
      const join = (a, b) => [a, b].map(x => clean(x).replace(/^,|,$/g, '').trim())
        .filter(Boolean).join(', ');
      const slots = (STATE.char_slots || []).filter(s => {
        const value = selectedVariationBundle(s);
        return s && s.enabled !== false && clean(join(value.prompt, value.outfit));
      });
      const effective = slots.map(selectedVariationBundle);
      const chars = effective.map(s => join(s.prompt, s.outfit)).filter(Boolean);
      const charNegs = effective.map(s => s.negative || '').filter(Boolean);
      const r = await (await fetch('/api/tokens', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({base: $('basePrompt').value,
                              negative: $('negPrompt').value, chars,
                              char_negatives: charNegs, finalize: true})})).json();
      if(!r.ok) return;
      const over = r.shared > r.limit;
      /* 토크나이저 vocab 이 없으면 어림값이다 — 정확한 값처럼 보여 주면 안 된다 */
      const approx = r.exact === false ? '≈' : '';
      $('posTok').innerHTML = `${approx}${r.base} 토큰`
        + (chars.length ? ` <span style="opacity:.7">+캐릭터 ${r.shared - r.base}</span>` : '')
        + ` <span style="color:${over ? '#e0574e' : 'var(--muted)'}">/ ${r.limit}</span>`
        + (over ? ' <span style="color:#e0574e">⚠ 입력은 보존</span>' : '');
      $('posTok').title = (r.finalized ? '조각·품질·UC 반영값입니다. 무작위 조각은 실제 선택에 따라 달라질 수 있습니다. ' : '')
        + (approx ? 't5_tokenizer.json 이 없어 어림값입니다 (≈). ' : '')
        + (over
          ? `약 512 토큰을 ${r.shared - r.limit} 초과했습니다. 입력·저장·API 전송은 원문 그대로 하지만, `
            + '모델이 참고할 수 있는 문맥은 베이스와 모든 캐릭터를 합쳐 약 512 토큰이라 뒤쪽 영향이 약해지거나 무시될 수 있습니다.'
          : '베이스 + 모든 캐릭터 프롬프트가 약 512 T5 토큰을 함께 씁니다');
      // 네거티브가 부실한데 UC 프리셋이 None 이면 NAI 가 아무것도 안 보태서
      // 그림이 흐릿하고 뭉개진다. 실제로 확인한 조합이라 경고를 띄운다.
      const ucNone = Number((STATE.uc_preset ?? 4)) === 4;
      const weak = r.negative < 25;
      const negShared = r.shared_negative ?? r.negative;
      const negOver = negShared > r.limit;
      $('negTok').innerHTML = `${approx}${r.negative} 토큰`
        + (negShared > r.negative
            ? ` <span style="opacity:.7">+캐릭터 ${negShared - r.negative}</span>` : '')
        + ` <span style="color:${negOver ? '#e0574e' : 'var(--muted)'}">/ ${r.limit}</span>`
        + (negOver ? ' <span style="color:#e0574e">⚠ 입력은 보존</span>' : '')
        + (ucNone && weak ? ' <span style="color:#e0a04e">⚠ UC 프리셋이 None</span>' : '');
      const negNotes = [];
      if(negOver) negNotes.push(
        `약 512 토큰을 ${negShared - r.limit} 초과했습니다. 입력·저장·API 전송은 원문 그대로 하지만, `
        + '네거티브와 캐릭터별 네거티브가 같은 문맥 한도를 쓰므로 뒤쪽 영향이 약해지거나 무시될 수 있습니다.');
      else negNotes.push('네거티브 + 모든 캐릭터별 네거티브가 약 512 T5 토큰을 함께 씁니다.');
      if(ucNone && weak) negNotes.push(
        '네거티브가 너무 짧고 UC 프리셋이 None 입니다 — NAI 가 품질 태그를 하나도 보태지 '
        + '않아 그림이 흐려질 수 있습니다. 네거티브를 채우거나 파라미터에서 UC 프리셋을 '
        + 'Heavy/Human Focus 로 바꾸세요.');
      $('negTok').title = negNotes.join(' ');
    }catch(e){}
  }, 350);
}
function tokens(){
  const t = s => (s||'').split(',').filter(x=>x.trim()).length;
  $('posTok').textContent = t($('basePrompt').value) + '태그';
  $('negTok').textContent = t($('negPrompt').value) + '태그';
  naiTokens();   // 정확한 토큰 수로 곧 갈아치운다
  redrawHL();   // 프롬프트가 바뀔 때마다 하이라이트도 다시 그림
  const n = activeSlotIdx().length;
  $('bgChars').textContent = n;
  $('bgChars').style.display = n ? 'flex' : 'none';
  let sets = 0;
  SETTINGS.forEach(st => { const s = stState(st.name); if(s.use !== false && s.selected.length) sets++; });
  anlasRefresh(false);          // 수량·해상도·스텝이 바뀌면 비용도 다시
  $('bgSets').textContent = sets;
  $('bgSets').style.display = sets ? 'flex' : 'none';
  let total = 0;
  SETTINGS.forEach(st => {
    const s = stState(st.name);
    if(s.use === false || !s.selected.length) return;
    /* 예약 매수(세트마다 몇 벌)와 단계 선택을 함께 반영한다 */
    const rep = s.reserve || {};
    const stg = new Set((s.stages || []).map(Number));
    let shots = 0;
    st.groups.forEach(g => {
      if(!s.selected.includes(g.id)) return;
      const cuts = stg.size ? g.ids.filter((_, i) => stg.has(i + 1)).length : g.ids.length;
      shots += cuts * Math.max(1, Number(rep[g.id]) || 1);
    });
    /* 전용 캐스트만 벌을 늘린다 ("각자 따로 전체 씬 생성").
       ① 설정의 캐릭터 칸은 한 그림에 함께 들어가므로 장수를 곱하지 않는다. */
    const cast = (s.cast||[]).filter(c=>[(c.prompt||''),(c.outfit||'')]
      .some(v=>v.replace(/^[ \t]*#.*$/gm, '').trim())).length;
    total += shots * (cast && castMode(s)==='sequence' ? cast : 1);
  });
  $('topStat').textContent = `캐릭터 ${n} · 세팅 ${sets} · 일괄 ${total}장`;
}

/* ── Highlight Emphasis ────────────────────────────────────────────
   NAI 의 같은 이름 기능. 가중치 표기를 색으로 보여준다.
     1.4::tag::   가중치 묶음 (강하면 따뜻한 색, 약하면 찬 색)
     -3::tag::    음수 = 빼기 (붉은색)
     {tag} [tag]  구형 강조/약화 (겹칠수록 진하게)
*/
function hlClass(w){
  if(w < 0) return 'w-neg';
  if(w >= 2) return 'w-up3';
  if(w >= 1.4) return 'w-up2';
  if(w > 1.0) return 'w-up1';
  if(w >= 0.5) return 'w-dn1';
  return 'w-dn2';
}
function highlightPrompt(text){
  const esc2 = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  let out = '';
  const lines = String(text || '').split('\n');
  lines.forEach((line, li) => {
    if(li) out += '\n';
    // 가중치 묶음: (숫자)::내용:: — 안쪽에 또 묶음이 올 수 있어 가장 짧게 잡는다
    let rest = line, guard = 0;
    while(rest && guard++ < 600){
      const m = rest.match(/(-?(?:\d+\.\d*|\.\d+|\d+))\s*::([\s\S]*?)::/);
      if(!m){ out += esc2(rest); break; }
      out += esc2(rest.slice(0, m.index));
      const w = parseFloat(m[1]);
      out += `<b class="${hlClass(w)}"><span class="w-num">${esc2(m[1])}::</span>`
           + esc2(m[2]) + '<span class="w-num">::</span></b>';
      rest = rest.slice(m.index + m[0].length);
    }
  });
  // 구형 {강조} [약화] — 중첩 깊이만큼 진하게
  out = out.replace(/(\{+)([^{}<]*)(\}+)/g, (s,a,b,c) =>
          `<b class="${a.length>=3?'w-up3':a.length===2?'w-up2':'w-up1'}">${a}${b}${c}</b>`)
           .replace(/(\[+)([^\[\]<]*)(\]+)/g, (s,a,b,c) =>
          `<b class="${a.length>=2?'w-dn2':'w-dn1'}">${a}${b}${c}</b>`);
  return out;
}
function attachHL(ta){
  if(!ta || ta._hl) return;
  const wrap = document.createElement('div');
  wrap.className = 'hlwrap';
  ta.parentNode.insertBefore(wrap, ta);
  const layer = document.createElement('div');
  layer.className = 'hl';
  wrap.appendChild(layer); wrap.appendChild(ta);
  ta._hl = layer;
  const sync = () => {
    // clientWidth/Height 는 textarea 테두리를 뺀 값이다. 거울층에도 같은 1px 테두리를
    // 두므로 양쪽 테두리 2px를 되붙여야 내용 폭·줄바꿈·스크롤 위치가 정확히 같다.
    // 세로 스크롤바가 나타나면 clientWidth가 줄어드는 것도 그대로 따라간다.
    layer.style.width = (ta.clientWidth + 2) + 'px';
    layer.style.height = (ta.clientHeight + 2) + 'px';
    layer.scrollTop = ta.scrollTop;
    layer.scrollLeft = ta.scrollLeft;
  };
  const draw = () => {
    if(!hlOn()){ layer.innerHTML = ''; return; }
    layer.innerHTML = highlightPrompt(ta.value) + '\n';
    sync();
  };
  ta.addEventListener('input', draw);
  ta.addEventListener('scroll', sync);
  window.addEventListener('resize', draw);
  if(window.ResizeObserver) new ResizeObserver(sync).observe(ta);
  ta._hlDraw = draw;
  draw();
}
/* 겹친 거울층은 브라우저·배율에 따라 글자가 번져 보일 수 있다. 기본은 원문 한 층만
   쓰고, 사용자가 관리 → 화면에서 직접 켰을 때만 가중치 배경을 그린다. */
function hlOn(){ return (STATE.ui || {}).highlight === true; }
function redrawHL(){
  document.querySelectorAll('textarea').forEach(t => { if(t._hlDraw) t._hlDraw(); });
}
function setupHL(){
  ['basePrompt','negPrompt'].forEach(id => attachHL($(id)));
  redrawHL();
}
let LAST_WEIGHT_FIELD = 'basePrompt';
function weightField(){
  const ids = ['basePrompt','baseFixed','baseVar','baseDetail'];
  const active = document.activeElement;
  if(active && ids.includes(active.id)) LAST_WEIGHT_FIELD = active.id;
  return $(LAST_WEIGHT_FIELD) || $('basePrompt');
}
function caretWeightRange(ta){
  let start = ta.selectionStart || 0, end = ta.selectionEnd || start;
  if(start !== end) return [start, end];
  /* 가중치 묶음 안에 쉼표가 있어도 묶음 전체를 먼저 찾는다. */
  const groups = [...ta.value.matchAll(/-?(?:\d+\.\d*|\.\d+|\d+)\s*::[\s\S]*?::/g)];
  const group = groups.find(m => m.index <= start && start <= m.index + m[0].length);
  if(group) return [group.index, group.index + group[0].length];
  const left = ta.value.lastIndexOf(',', Math.max(0, start - 1));
  const right = ta.value.indexOf(',', start);
  return [left < 0 ? 0 : left + 1, right < 0 ? ta.value.length : right];
}
function weightText(value){
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? rounded.toFixed(1)
    : String(rounded).replace(/0+$/, '').replace(/\.$/, '');
}
function adjustCaretWeight(delta){
  const ta = weightField();
  if(!ta) return;
  const [start, end] = caretWeightRange(ta);
  const raw = ta.value.slice(start, end);
  const lead = (raw.match(/^\s*/) || [''])[0];
  const tail = (raw.match(/\s*$/) || [''])[0];
  const core = raw.slice(lead.length, raw.length - tail.length);
  if(!core){ ta.focus(); return; }
  const match = core.match(/^(-?(?:\d+\.\d*|\.\d+|\d+))\s*::([\s\S]*)::$/);
  const content = match ? match[2] : core;
  const weight = match ? Number(match[1]) + delta : (delta > 0 ? 1.1 : 0.9);
  const replacement = `${lead}${weightText(weight)}::${content}::${tail}`;
  ta.setRangeText(replacement, start, end, 'select');
  ta.dispatchEvent(new Event('input', {bubbles:true}));
  ta.focus();
}
['basePrompt','baseFixed','baseVar','baseDetail'].forEach(id => {
  const field = $(id);
  if(field) field.addEventListener('focus', () => { LAST_WEIGHT_FIELD = id; });
});
if($('weightDownBtn')) $('weightDownBtn').addEventListener('click', () => adjustCaretWeight(-0.1));
if($('weightUpBtn')) $('weightUpBtn').addEventListener('click', () => adjustCaretWeight(0.1));
function bindHLToggle(){
  const s = $('uiHighlight');
  if(!s || s._bound) return;
  s._bound = true;
  s.value = hlOn() ? 'on' : 'off';
  s.addEventListener('change', () => {
    STATE.ui = STATE.ui || {};
    STATE.ui.highlight = s.value === 'on';
    redrawHL(); save();
  });
}

/* ── 바이브 · 캐릭터 레퍼런스 ────────────────────────────────────────
   바이브는 인코딩 캐시가 핵심이다. 정보추출(information_extracted)을 바꾸면
   캐시가 무효가 되어 다음 생성에서 다시 인코딩(2 Anlas)한다. */
const REF_TYPE_KO = {'character&style':'생김새 + 화풍', 'character':'생김새만', 'style':'화풍만'};
function renderRefs(){
  const rows = (host, list, kind) => {
    const h = $(host); if(!h) return;
    h.innerHTML = '';
    (list || []).forEach((r, i) => {
      const el = document.createElement('div');
      el.className = 'row'; el.style.margin = '6px 0 0';
      const cached = kind === 'vibe' && r.encoded_ie != null;
      const thumb = `/refimg?id=${encodeURIComponent(r.id)}&kind=${kind}`;
      el.innerHTML = `<div class="tag">
          <label class="hint" style="cursor:pointer;"><input type="checkbox" data-ren="${kind}|${i}"
            ${r.enabled ? 'checked' : ''}> ${esc(r.name || '무제')}</label>
          ${kind === 'vibe' ? `<span class="hint" style="margin-left:6px;">${cached ? '인코딩됨 (공짜)' : '미인코딩 (2 Anlas)'}</span>` : ''}
          <button class="danger" data-rdel="${kind}|${i}" style="float:right;">✕</button></div>
        <div style="display:flex;gap:8px;">
        <img src="${thumb}" alt="" loading="lazy" onerror="this.style.display='none'"
          style="width:72px;height:72px;object-fit:cover;border-radius:var(--radius);
                 border:1px solid var(--line);flex:none;background:#0004;">
        <div style="flex:1;min-width:0;">
        <div class="grid2">
          ${kind === 'vibe' ? `
          <!-- 바이브는 공홈처럼 1 초과·0 미만도 받는다 (과하게 밀거나 반대로 밀 때) -->
          <div class="field"><label>강도 <span class="hint">1 넘김·0 미만도 가능</span></label>
            <input type="number" data-rf="vibe|${i}|strength" value="${r.strength ?? 0.6}"
              step="0.05" min="-1" max="2"></div>
          <div class="field"><label>정보 추출 <span class="hint">(바꾸면 재인코딩)</span></label>
            <input type="number" data-rf="vibe|${i}|info_extracted" value="${r.info_extracted ?? 0.7}"
              step="0.05" min="-1" max="2"></div>` : `
          <!-- 캐릭레퍼: 세기·충실도 둘 다 조절된다 (실측 -0.5~2.0 전부 통과).
               정보추출만 NAI 가 1.0 으로 강제하므로 칸을 두지 않는다. -->
          <div class="field"><label>세기 <span class="hint">1 넘김·0 미만도 가능</span></label>
            <input type="number" data-rf="cref|${i}|strength" value="${r.strength ?? 1.0}"
              step="0.05" min="-1" max="2"></div>
          <div class="field"><label>충실도 <span class="hint">높이면 원본을 더 따라갑니다</span></label>
            <input type="number" data-rf="cref|${i}|fidelity" value="${r.fidelity ?? 0.6}"
              step="0.05" min="-1" max="2"></div>` }
        </div>
        ${kind === 'cref' ? `<div class="field"><label>참조 종류</label>
          <select data-rf="cref|${i}|ref_type">${Object.entries(REF_TYPE_KO).map(([v,l]) =>
            `<option value="${v}"${(r.ref_type||'character&style')===v?' selected':''}>${l}</option>`).join('')}</select></div>` : ''}
        </div></div>`;
      h.appendChild(el);
    });
  };
  rows('vibeList', STATE.vibes, 'vibe');
  rows('crefList', STATE.char_refs, 'cref');
  const onV = (STATE.vibes || []).filter(v => v.enabled).length;
  const onC = (STATE.char_refs || []).filter(v => v.enabled).length;
  if($('bgVibe')) $('bgVibe').textContent = onV;
  if($('bgCref')) $('bgCref').textContent = onC;
  const badge = $('bgRefs');
  if(badge){ badge.textContent = onV + onC; badge.style.display = (onV + onC) ? 'flex' : 'none'; }
  const list = k => k === 'vibe' ? (STATE.vibes = STATE.vibes || [])
                                 : (STATE.char_refs = STATE.char_refs || []);
  document.querySelectorAll('[data-ren]').forEach(c => c.addEventListener('change', () => {
    const [k, i] = c.dataset.ren.split('|');
    const other = k === 'vibe' ? 'cref' : 'vibe';
    if(c.checked && list(other).some(item => item && item.enabled)){
      c.checked = false;
      flash('NAI에서는 바이브와 캐릭터 레퍼런스를 동시에 사용할 수 없습니다. 먼저 다른 쪽을 꺼주세요.');
      return;
    }
    list(k)[+i].enabled = c.checked; saveRefs();
  }));
  document.querySelectorAll('[data-rf]').forEach(el => el.addEventListener('change', () => {
    const [k, i, f] = el.dataset.rf.split('|');
    list(k)[+i][f] = (f === 'ref_type') ? el.value : (Number(el.value) || 0);
    saveRefs();
  }));
  document.querySelectorAll('[data-rdel]').forEach(b => b.addEventListener('click', () => {
    const [k, i] = b.dataset.rdel.split('|'); list(k).splice(+i, 1); saveRefs();
  }));
}
async function saveRefs(){
  const changed = ['vibes','char_refs'].filter(key =>
    JSON.stringify((STATE||{})[key] || []) !==
    JSON.stringify((SAVED_STATE||{})[key] || []));
  if(!changed.length) return;
  const payload = {_revision:STATE._revision, _base:{}};
  changed.forEach(key => {
    payload[key] = STATE[key] || [];
    payload._base[key] = (SAVED_STATE||{})[key] || [];
  });
  const r = await (await fetch('/api/ref_save', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)})).json();
  if(r.conflict){ flash(r.error || '참조 목록 저장 충돌'); return; }
  if(r.ok){
    STATE.vibes = r.vibes; STATE.char_refs = r.char_refs;
    if(r.revision != null) STATE._revision = r.revision;
    rememberSavedKeys(changed);
    renderRefs(); anlasRefresh(false);
  }
}
async function addRefs(files, kind){
  const imgs = files.filter(f => /\.(png|webp)$/i.test(f.name));
  if(!imgs.length){ $('refMsg').textContent = 'PNG 또는 WebP 를 넣어주세요.'; return; }
  for(const f of imgs){
    $('refMsg').textContent = `${f.name} 등록 중...`
      + (kind === 'vibe' ? ' (인코딩 2 Anlas)' : '');
    try{
      const r = await (await fetch('/api/ref_add', {method:'POST', headers:{
        'X-Kind': kind, 'X-Filename': encodeURIComponent(f.name)},
        body: await f.arrayBuffer()})).json();
      if(r.ok){
        if(r.vibes) STATE.vibes = r.vibes;
        if(r.char_refs) STATE.char_refs = r.char_refs;
        if(r.revision != null) STATE._revision = r.revision;
        rememberSavedKeys(r.vibes ? ['vibes'] : ['char_refs']);
        $('refMsg').textContent = r.warn || `${f.name} 등록 ✓`;
      } else $('refMsg').textContent = r.error;
    }catch(e){ $('refMsg').textContent = String(e); }
  }
  renderRefs(); anlasRefresh(false);
}
function bindRefs(){
  if(!$('vibeDrop') || $('vibeDrop')._bound) return;
  $('vibeDrop')._bound = true;
  $('refBundleExport').addEventListener('click', () => {
    $('refMsg').textContent = 'Vibe·Reference 묶음을 내보내는 중...';
    window.location.href = '/api/ref_bundle_export';
    setTimeout(() => { $('refMsg').textContent = '묶음 내보냄 ✓'; }, 800);
  });
  $('refBundleImport').addEventListener('click', () => $('refBundleFile').click());
  $('refBundleFile').addEventListener('change', async () => {
    const f = $('refBundleFile').files[0];
    if(!f) return;
    $('refMsg').textContent = `${f.name} 확인 중...`;
    try{
      const r = await (await fetch('/api/ref_bundle_import', {
        method:'POST',
        headers:{'X-Filename':encodeURIComponent(f.name)},
        body:await f.arrayBuffer(),
      })).json();
      if(r.ok){
        STATE.vibes = r.vibes || STATE.vibes || [];
        STATE.char_refs = r.char_refs || STATE.char_refs || [];
        if(r.revision != null) STATE._revision = r.revision;
        rememberSavedKeys(['vibes','char_refs']);
        $('refMsg').textContent =
          `꺼진 상태로 바이브 ${r.added_vibes||0}개 · Reference ${r.added_char_refs||0}개 등록`
          + ((r.skipped||[]).length ? ` · ${r.skipped.length}개 건너뜀` : '');
        renderRefs();
      }else $('refMsg').textContent = r.error || '가져오지 못했습니다.';
    }catch(e){ $('refMsg').textContent = String(e); }
    $('refBundleFile').value = '';
  });
  [['vibeDrop','vibeFile','vibe'], ['crefDrop','crefFile','cref']].forEach(([z, fi, kind]) => {
    const zone = $(z), file = $(fi);
    zone.addEventListener('click', () => file.click());
    file.addEventListener('change', () => { addRefs([...file.files], kind); file.value = ''; });
    ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.style.borderColor = 'var(--accent)'; }));
    ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.style.borderColor = ''; }));
    zone.addEventListener('drop', e => { e.stopPropagation(); addRefs([...(e.dataTransfer.files||[])], kind); });
  });
  document.querySelectorAll('[data-reftab]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-reftab]').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('[data-refpane]').forEach(x =>
      x.classList.toggle('hidden', x.dataset.refpane !== b.dataset.reftab));
  }));
  renderRefs();
}

const POSITION_MODES = new Set(['ai','grid','coordinate']);
function positionMode(){
  const value = String(STATE.position_mode || '').toLowerCase();
  if(POSITION_MODES.has(value)) return value;
  /* 구형 설정은 use_coords만 있었다. 읽기 호환만 하고 사용자가 직접 고르기
     전에는 position_mode를 써 넣지 않는다. */
  return STATE.use_coords ? 'coordinate' : 'ai';
}
function setPositionMode(mode, persist=true){
  if(!POSITION_MODES.has(mode)) mode = 'ai';
  STATE.position_mode = mode;
  STATE.use_coords = mode !== 'ai';
  const legacy = $('chUseCoords');
  if(legacy) legacy.checked = STATE.use_coords;
  if($('pCoords')) $('pCoords').value = STATE.use_coords ? 'on' : 'off';
  if(persist) save();
}
function renderPositionEditors(mode=positionMode()){
  document.querySelectorAll('[data-posgrid-wrap]').forEach(el =>
    el.classList.toggle('hidden', mode !== 'grid'));
  document.querySelectorAll('[data-poscoord-wrap]').forEach(el =>
    el.classList.toggle('hidden', mode !== 'coordinate'));
  document.querySelectorAll('[data-posai]').forEach(el =>
    el.classList.toggle('hidden', mode !== 'ai'));
}
/* 위치 방식 하나만 고른다. 위치판과 좌표는 같은 NAI centers를 편집하는 두 UI고,
   AI 자동은 저장된 centers를 지우지 않은 채 이번 요청에서만 적용하지 않는다. */
function bindUseCoords(){
  const c = $('chUseCoords');
  const picker = $('chPositionMode');
  if(!c || !picker || picker._bound) return;
  picker._bound = true;
  c._bound = true;
  const paint = () => {
    const mode = positionMode();
    c.checked = mode !== 'ai';
    picker.querySelectorAll('[data-position-mode]').forEach(button => {
      const on = button.dataset.positionMode === mode;
      button.classList.toggle('on', on);
      button.setAttribute('aria-checked', on ? 'true' : 'false');
      button.tabIndex = on ? 0 : -1;
    });
    const solo = activeSlotIdx().length === 1;
    $('chCoordsNote').textContent = mode === 'ai'
      ? "AI's Choice — NAI가 인물 순서와 프롬프트를 보고 배치합니다."
      : solo
      ? `${mode === 'grid' ? '위치판' : '좌표'} 값은 보존되지만 인물이 1명일 때는 NAI가 무시합니다.`
      : mode === 'grid'
      ? '각 인물 카드에서 5×5 칸을 고릅니다.'
      : '각 인물 카드에서 X·Y를 0~1 연속값으로 입력합니다.';
    /* AI 자동은 정상 선택이다. 수동 모드의 중복 위치와 상한 초과만 경고한다. */
    const n = activeSlotIdx().length;
    const over = n > MAX_CHARS;
    const warn = $('chFuseWarn');
    if(warn){
      const clash = coordsClash();
      warn.classList.toggle('hidden', !(clash || over));
      if(clash || over){
        const w = warn.querySelector('div');
        if(w) w.innerHTML = over
          ? `<b>켠 인물이 ${n}명입니다.</b> NAI는 <b>${MAX_CHARS}명</b>까지만 받습니다 —
             앞 ${MAX_CHARS}명만 보내고 나머지는 칸에 그대로 남습니다.`
          : `<b>인물 ${n}명 중 같은 자리에 겹친 사람이 있습니다.</b>
             위치판이나 좌표를 다르게 고르거나 추천 배치를 사용하세요.`;
      }
    }
    renderPositionEditors(mode);
  };
  picker.querySelectorAll('[data-position-mode]').forEach(button => {
    button.addEventListener('click', () => {
      setPositionMode(button.dataset.positionMode);
      paint();
    });
    button.addEventListener('keydown', event => {
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...picker.querySelectorAll('[data-position-mode]')];
      const delta = ['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1;
      const next = buttons[
        (buttons.indexOf(button) + delta + buttons.length) % buttons.length];
      next.click();
      next.focus();
    });
  });
  const spread = $('chSpread');
  if(spread) spread.addEventListener('click', () => {
    /* 추천 배치는 네 번째 모드가 아니다. 현재 인물에게 겹치지 않는 5×5 칸
       중심값을 채우고 위치판 모드로 전환한다. */
    const idx = activeSlotIdx();
    const n = idx.length || 2;
    const auto = spreadCenters(n);
    const cs = (STATE.char_centers || []).slice();
    while(cs.length < (STATE.char_slots || []).length) cs.push(null);
    idx.forEach((i, k) => { cs[i] = auto[k]; });
    STATE.char_centers = cs;
    setPositionMode('grid', false);
    paint(); drawPosGrids(); save();
    flash(`켠 인물 ${n}명을 ${auto.map(c=>`x${c.x}·y${c.y}`).join(' / ')} 로 배치했습니다.`);
  });
  paint();
  window._paintCoords = paint;
}

/* ── 캐릭터 위치 (centers) ──────────────────────────────────────────
   NAI 는 인물마다 화면 어디에 둘지 좌표를 받는다. 공홈 UI 는 5×5 격자만 보여주지만
   **서버는 0~1 자유값을 받고 격자로 반올림하지 않는다** (라운드01 실측 — 0.05 차이도 반영).
   격자는 빠른 선택용으로 남기고 숫자 칸으로 자유값을 넣는다.
   ⚠ 실측 주의(2026-07 · V4.5 full 기준): **인물이 1명이면 좌표가 통째로 무시된다**
   (12장 픽셀 동일 확인). 좌표는 2명부터 적용되고, 핀 고정이 아니라 느슨한 유도다.
   다른 모델·향후 서버에서는 다를 수 있다 — 모델이 바뀌면 재실측할 것.
   `position_mode=ai`이면 저장된 좌표를 지우지 않고 NAI가 알아서 배치하게 한다. */
const POS_STEPS = [0.1, 0.3, 0.5, 0.7, 0.9];
const MAX_CHARS = 6;      // NAI 가 한 그림에 받는 인물 수 (서버 상수와 같음)
/* 인물 n 명을 겹치지 않게 벌린 좌표 — 서버 spread_centers() 와 같은 규칙.
   한 줄은 5칸까지라 6명부터는 두 줄(y 0.3 / 0.7)로 나눈다. */
function spreadCenters(n){
  if(n <= 1) return [{x:0.5, y:0.5}];
  if(n === 2) return [{x:0.3, y:0.5}, {x:0.7, y:0.5}];
  const rows = n <= 5 ? 1 : 2;
  const per = Math.ceil(n / rows);
  const ys = rows === 1 ? [0.5] : [0.3, 0.7];
  const pick = (k, total) => total === 1 ? POS_STEPS[2]
    : POS_STEPS[Math.min(4, Math.round(k * 4 / (total - 1)))];
  const out = [];
  for(let i = 0; i < n; i++){
    const r = Math.floor(i / per), k = i % per;
    out.push({x: pick(k, Math.min(per, n - r * per)), y: ys[Math.min(r, ys.length - 1)]});
  }
  return out;
}
function slotCenter(i){
  const c = (STATE.char_centers || [])[i];
  return {x: (c && c.x != null) ? c.x : 0.5, y: (c && c.y != null) ? c.y : 0.5};
}
function drawPosGrids(){
  document.querySelectorAll('[data-pos]').forEach(host => {
    const i = +host.dataset.pos;
    const cur = slotCenter(i);
    host.innerHTML = '';
    POS_STEPS.forEach(y => POS_STEPS.forEach(x => {
      const cell = document.createElement('button');
      cell.type = 'button';
      const on = Math.abs(x - cur.x) < 0.01 && Math.abs(y - cur.y) < 0.01;
      cell.className = 'poscell' + (on ? ' on' : '');
      cell.title = `x ${x} · y ${y}`;
      cell.dataset.x = x;
      cell.dataset.y = y;
      cell.setAttribute('aria-label', `캐릭터 ${i + 1} 위치 x ${x}, y ${y}`);
      cell.setAttribute('aria-pressed', on ? 'true' : 'false');
      cell.tabIndex = on ? 0 : -1;
      const choose = (nextX, nextY, focus=false) => {
        STATE.char_centers = STATE.char_centers || [];
        while(STATE.char_centers.length <= i) STATE.char_centers.push({x:0.5, y:0.5});
        STATE.char_centers[i] = {x: nextX, y: nextY};
        drawPosGrids(); save();
        if(positionMode() === 'ai') flash('위치판이나 좌표 모드를 먼저 고르세요.');
        if(focus) requestAnimationFrame(() => {
          const next = host.querySelector(
            `[data-x="${nextX}"][data-y="${nextY}"]`);
          if(next) next.focus();
        });
      };
      cell.addEventListener('click', () => choose(x, y));
      cell.addEventListener('keydown', event => {
        const moves = {
          ArrowLeft:[-1,0], ArrowRight:[1,0],
          ArrowUp:[0,-1], ArrowDown:[0,1],
        };
        const move = moves[event.key];
        if(!move) return;
        event.preventDefault();
        const column = Math.max(0, Math.min(
          POS_STEPS.length - 1, POS_STEPS.indexOf(x) + move[0]));
        const row = Math.max(0, Math.min(
          POS_STEPS.length - 1, POS_STEPS.indexOf(y) + move[1]));
        choose(POS_STEPS[column], POS_STEPS[row], true);
      });
      host.appendChild(cell);
    }));
    /* 숫자 칸도 현재 값으로 (포커스 중인 칸은 건드리지 않는다 — 입력을 지우게 된다) */
    const nx = document.querySelector(`[data-posx="${i}"]`);
    const ny = document.querySelector(`[data-posy="${i}"]`);
    if(nx && document.activeElement !== nx) nx.value = cur.x;
    if(ny && document.activeElement !== ny) ny.value = cur.y;
    const lab = document.querySelector(`[data-poslabel="${i}"]`);
    if(lab) lab.textContent = (cur.x === 0.5 && cur.y === 0.5)
      ? '가운데 (기본)' : `x ${cur.x} · y ${cur.y}`;
  });
}

/* ── 디렉터 툴 ──────────────────────────────────────────────────────
   그림을 넣으면 NAI 가 손봐서 돌려준다. 도구에 따라 필요한 칸만 보인다. */
function dirSync(){
  const t = $('dirTool').value;
  const show = (id, on) => { $(id).style.display = on ? '' : 'none'; };
  show('dirEmotion', t === 'emotion');
  show('dirPrompt', t === 'colorize' || t === 'emotion');
  show('dirDefry', t === 'colorize' || t === 'emotion');
  show('dirScale', t === 'upscale');
  $('dirPrompt').placeholder = t === 'emotion'
    ? '추가 지시 (선택 — 감정은 왼쪽에서 고름)' : '색 유도 프롬프트 (선택)';
}
async function runDirector(files){
  const imgs = files.filter(f => /\.(png|webp)$/i.test(f.name));
  if(!imgs.length){ $('dirMsg').textContent = 'PNG 또는 WebP 를 넣어주세요.'; return; }
  const tool = $('dirTool').value;
  let prompt = $('dirPrompt').value || '';
  if(tool === 'emotion'){
    prompt = [$('dirEmotion').value, prompt].filter(Boolean).join(', ');
  }
  let ok = 0, fail = [];
  for(let i = 0; i < imgs.length; i++){
    const f = imgs[i];
    $('dirMsg').textContent = `${i+1}/${imgs.length} ${f.name} — ${tool} 처리 중...`;
    try{
      const r = await (await fetch('/api/director', {method:'POST', headers:{
        'X-Tool': tool, 'X-Prompt': encodeURIComponent(prompt),
        'X-Defry': $('dirDefry').value, 'X-Scale': $('dirScale').value,
        'X-Filename': encodeURIComponent(f.name)},
        body: await f.arrayBuffer()})).json();
      if(r.ok){ ok++; $('dirMsg').textContent = `${r.file} (${r.width}×${r.height}) ✓`; }
      else fail.push(r.error);
    }catch(e){ fail.push(String(e)); }
  }
  $('dirMsg').textContent = `${ok}개 완료`
    + (fail.length ? ` · ${fail.length}개 실패: ${fail[0].slice(0,60)}` : ' — output/디렉터/ 에 저장');
}
function bindDirector(){
  if(!$('dirTool') || $('dirTool')._bound) return;
  $('dirTool')._bound = true;
  $('dirTool').addEventListener('change', dirSync);
  dirSync();
  const zone = $('dirDrop'), file = $('dirFile');
  zone.addEventListener('click', () => file.click());
  file.addEventListener('change', () => { runDirector([...file.files]); file.value = ''; });
  ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = ''; }));
  zone.addEventListener('drop', e => {
    e.stopPropagation();               // 전역 그림체 추출로 새지 않게
    runDirector([...(e.dataTransfer.files || [])]);
  });
}

/* ── Anlas 비용 ────────────────────────────────────────────────────
   565장 돌리기 전에 총액을 먼저 보여준다. Opus 무료 조건도 함께. */
let anlasT = null;
function anlasRefresh(withBalance){
  clearTimeout(anlasT);
  anlasT = setTimeout(async () => {
    try{
      // 일괄 생성이면 선택된 세팅의 총 장수, 아니면 수량칸
      const m = ($('topStat').textContent || '').match(/일괄 ([\d,]+)장/);
      const batch = m ? Number(m[1].replace(/,/g,'')) : 0;
      const count = batch || Number($('qty').value) || 1;
      const r = await (await fetch('/api/anlas', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({count, batch: batch > 0, balance: !!withBalance})})).json();
      if(!r.ok) return;
      const e = r.est;
      // '무엇을 몇 장' 인지 먼저 말한다. 숫자만 던지면 뜬금없다.
      const what = e.batch
        ? `🎬 선택한 세팅 ${e.count.toLocaleString()}장`
        : `🖼 지금 설정으로 ${e.count.toLocaleString()}장`;
      let txt;
      if(e.free){
        txt = `${what} — <b>Anlas 0</b>`
            + (e.batch ? ' <span style="opacity:.7">(Opus 무료 범위)</span>'
                       : ` <span style="opacity:.7">(Opus 무료 · ${e.width}×${e.height} · ${e.steps}스텝)</span>`);
      } else if(e.batch){
        txt = `${what} — <b>${e.total.toLocaleString()} Anlas</b>`;
      } else {
        txt = `${what} — 장당 ${e.per_image} × ${e.count.toLocaleString()} = `
            + `<b>${e.total.toLocaleString()} Anlas</b>`;
      }
      if(e.subscription_known === false){
        txt += ' <span style="color:#9a6700">(구독 등급 미확인 · 유료 기준 예상, 잔액 확인을 눌러주세요)</span>';
      }
      if(r.balance){
        const b = r.balance;
        const after = b.total - e.total;
        txt += ` · 잔액 ${b.total.toLocaleString()}`
             + (e.total ? ` → ${after.toLocaleString()}` : '')
             + (b.opus ? ' (Opus)' : ` (tier ${b.tier})`);
        if(after < 0) txt += ' <b style="color:#e0574e">부족!</b>';
      }
      $('anlasCost').innerHTML = txt;
      $('anlasCost').title = e.why;
    }catch(err){}
  }, 400);
}

/* ── 생성 파라미터 ── */
const ONOFF = [['pQuality','quality_toggle'],['pSmea','smea'],['pSmeaDyn','smea_dyn'],
  ['pDynThr','dynamic_thresholding'],['pBrownian','prefer_brownian'],
  ['pEulerBug','deliberate_euler_ancestral_bug'],['pCoords','use_coords']];
const NUMS = [['pUncond','uncond_scale',0],['pCtrl','controlnet_strength',1]];
const STYLE_PARAM_IDS = new Set([
  'basePrompt','negPrompt','pModel','pScale','pRescale','pSteps','pSampler','pSched',
  'pVariety','pQuality','pUc','pRes','pWidth','pHeight','pSmea','pSmeaDyn',
  'pDynThr','pUncond','pCtrl','pBrownian','pEulerBug'
]);

/* ── 시드 ──────────────────────────────────────────────────────────
   NAI 시드 = 0 이면 회차 시드를 쓰고(회차마다 하나 뽑아 상태.json에 저장),
   값이 있으면 그 시드로 고정한다. 생성된 그림의 실제 시드는 미리보기에 나온다. */
let lastSeed = 0;
function seedNote(){
  const v = Number($('pNaiSeed').value) || 0;
  $('pSeedNow').textContent = v
    ? `고정 — 모든 장이 시드 ${v}. 같은 그림을 다시 뽑을 때 씁니다.`
    : (lastSeed
        ? `장마다 다른 시드 (직전 장 ${lastSeed}). 회차 번호가 같으면 같은 결과가 재현됩니다.`
        : '장마다 다른 시드 — NAI 기본 동작. 회차 번호가 같으면 같은 결과가 재현됩니다.');
}
function bindSeed(){
  if(window._seedBound) return;
  window._seedBound = true;
  $('pSeedRoll').addEventListener('click', () => {
    STATE.nai_seed = Math.floor(Math.random() * 4294967295);
    $('pNaiSeed').value = STATE.nai_seed; seedNote(); save();
  });
  $('pSeedClear').addEventListener('click', () => {
    STATE.nai_seed = 0; $('pNaiSeed').value = 0; seedNote(); save();
  });
  $('pNaiSeed').addEventListener('input', seedNote);
  $('pvSeedCopy').addEventListener('click', () => {
    if(!lastSeed) return;
    navigator.clipboard?.writeText(String(lastSeed));
    $('pvSeed').textContent = `시드 ${lastSeed} — 복사됨 ✓`;
  });
  $('pvSeedLock').addEventListener('click', () => {
    if(!lastSeed) return;
    STATE.nai_seed = lastSeed; $('pNaiSeed').value = lastSeed; seedNote(); save();
    $('pvSeed').textContent = `시드 ${lastSeed} — 고정됨 ✓`;
  });
}

let paramsPainted = false;
function paintParams(){
  $('pModel').value = STATE.model || 'nai-diffusion-4-5-full';
  $('pFormat').value = STATE.save_format || 'webp';
  if($('pOutDir')) $('pOutDir').value = STATE.out_dir || '';
  if($('pOutDate')) $('pOutDate').value = STATE.out_by_date ? 'on' : 'off';
  $('pClean').value = STATE.save_clean ? 'on' : 'off';
  $('pMaxSide').value = String(STATE.save_max_side || 0);
  $('pSaveQ').value = STATE.save_quality ?? 92;
  $('pCleanOpts').style.display = STATE.save_clean ? '' : 'none';
  $('pUc').value = String(STATE.uc_preset ?? 3);
  const w = STATE.width || 832, h = STATE.height || 1216;
  $('pWidth').value = w; $('pHeight').value = h;
  const key = `${w}x${h}`;
  const known = [...$('pRes').options].some(o => o.value === key);
  $('pRes').value = known ? key : '';
  $('pWHwrap').style.display = known ? 'none' : '';
  ONOFF.forEach(([id,k]) => { const d = (k==='prefer_brownian'); $(id).value = (STATE[k] ?? d) ? 'on' : 'off'; });
  NUMS.forEach(([id,k,d]) => { $(id).value = STATE[k] ?? d; });
  gateByModel();
  bindSeed(); seedNote();
  paramsPainted = true;
}

/* 모델 세대에 따라 안 쓰이는 파라미터를 잠근다.
   V3 전용을 V4에 켜면 무시되거나 결과가 망가지므로 아예 못 만지게 한다. */
function gateByModel(){
  const v4 = (STATE.model || '').startsWith('nai-diffusion-4');
  document.querySelectorAll('#pAdv [data-gen]').forEach(f => {
    const on = f.dataset.gen === (v4 ? 'v4' : 'v3');
    f.style.opacity = on ? '' : '.42';
    f.querySelectorAll('input,select').forEach(el => { el.disabled = !on; });
    const lab = f.querySelector('label');
    let tag = lab.querySelector('.genTag');
    if(!tag){ tag = document.createElement('span'); tag.className = 'genTag hint'; lab.appendChild(tag); }
    tag.textContent = on ? '' : (f.dataset.gen === 'v3' ? '  — V3 전용' : '  — V4 전용');
  });
  // Variety+ 도 V4 전용
  const vf = $('pVariety');
  if(vf){ vf.disabled = !v4; vf.parentElement.style.opacity = v4 ? '' : '.42'; }
  $('pAdvNote').textContent = v4
    ? '지금 모델은 V4 계열입니다. SMEA·Dynamic Thresholding·Uncond Scale·ControlNet 은 V3 전용이라 잠겨 있습니다.'
    : '지금 모델은 V3 계열입니다. Variety+·캐릭터 좌표·Euler 버그 재현은 V4 전용이라 잠겨 있습니다.';
}
function readParams(){
  // 화면이 아직 설정값으로 채워지기 전이면 읽지 않는다 (기본값으로 덮어쓰기 방지)
  if(!paramsPainted) return;
  STATE.model = $('pModel').value;
  STATE.save_format = $('pFormat').value;
  if($('pOutDir')) STATE.out_dir = $('pOutDir').value.trim();
  if($('pOutDate')) STATE.out_by_date = $('pOutDate').value === 'on';
  STATE.save_clean = $('pClean').value === 'on';
  STATE.save_max_side = Number($('pMaxSide').value) || 0;
  STATE.save_quality = Number($('pSaveQ').value) || 92;
  $('pCleanOpts').style.display = STATE.save_clean ? '' : 'none';
  STATE.uc_preset = Number($('pUc').value);
  const r = $('pRes').value;
  if(r){ const [w,h] = r.split('x').map(Number); STATE.width = w; STATE.height = h;
         $('pWidth').value = w; $('pHeight').value = h; $('pWHwrap').style.display = 'none'; }
  else { STATE.width = Number($('pWidth').value) || 832;
         STATE.height = Number($('pHeight').value) || 1216; $('pWHwrap').style.display = ''; }
  ONOFF.forEach(([id,k]) => { STATE[k] = $(id).value === 'on'; });
  NUMS.forEach(([id,k,d]) => { const v = Number($(id).value); STATE[k] = isNaN(v) ? d : v; });
  gateByModel();
  if(window._paintCoords) window._paintCoords();
  tokens(); save();
}
['pModel','pFormat','pOutDir','pOutDate','pClean','pMaxSide','pSaveQ','pUc','pRes','pWidth','pHeight',...ONOFF.map(x=>x[0]),...NUMS.map(x=>x[0])]
  .forEach(id => { const el = $(id); if(!el) return;
    const changed = () => { readParams(); if(STYLE_PARAM_IDS.has(id)) clearActiveStyle(); };
    el.addEventListener('change', changed); el.addEventListener('input', changed); });

/* ── 저장 ── */

function paintActiveStyle(){
  const s = $('presetSel'); if(!s) return;
  const active = (STATE && STATE.style_name) || '';
  const idx = STYLES.findIndex(x => x.name === active);
  s.options[0].textContent = active && idx < 0
    ? `현재 그림체: ${active}` : '베이스 프리셋 불러오기...';
  s.value = idx >= 0 ? String(idx) : '';
  s.title = active ? `현재 그림체 묶음: ${active}` : '현재 값은 직접 편집한 상태입니다.';
}
function clearActiveStyle(){
  if(!STATE || !STATE.style_name) return;
  STATE.style_name = '';
  paintActiveStyle();
}
function styleSettingsFromUI(){
  return {
    model: $('pModel').value,
    cfg_scale: Number($('pScale').value),
    cfg_rescale: Number($('pRescale').value),
    steps: Number($('pSteps').value),
    sampler: $('pSampler').value,
    scheduler: $('pSched').value,
    variety: $('pVariety').value === 'on',
    width: Number($('pWidth').value) || STATE.width,
    height: Number($('pHeight').value) || STATE.height,
    uc_preset: Number($('pUc').value),
    quality_toggle: $('pQuality').value === 'on',
    smea: $('pSmea').value === 'on',
    smea_dyn: $('pSmeaDyn').value === 'on',
    dynamic_thresholding: $('pDynThr').value === 'on',
    uncond_scale: Number($('pUncond').value),
    controlnet_strength: Number($('pCtrl').value),
    prefer_brownian: $('pBrownian').value === 'on',
    deliberate_euler_ancestral_bug: $('pEulerBug').value === 'on',
    legacy_v3_extend: !!STATE.legacy_v3_extend,
    use_coords: positionMode() !== 'ai',
    position_mode: positionMode()
  };
}
function applyStyleSettings(raw){
  const p = raw || {};
  const first = (...keys) => {
    const key = keys.find(k => Object.prototype.hasOwnProperty.call(p, k));
    return key == null ? undefined : p[key];
  };
  const set = (key, value, cast) => {
    if(value === undefined || value === null || value === '') return;
    STATE[key] = cast ? cast(value) : value;
  };
  set('model', first('model'), String);
  set('cfg_scale', first('cfg_scale', 'scale'), Number);
  set('cfg_rescale', first('cfg_rescale'), Number);
  set('steps', first('steps'), Number);
  set('sampler', first('sampler'), String);
  set('scheduler', first('scheduler', 'noise_schedule'), String);
  set('variety', first('variety', 'variety_plus'), Boolean);
  set('width', first('width'), Number);
  set('height', first('height'), Number);
  set('uc_preset', first('uc_preset', 'ucPreset'), Number);
  set('quality_toggle', first('quality_toggle'), Boolean);
  set('smea', first('smea', 'sm'), Boolean);
  set('smea_dyn', first('smea_dyn', 'sm_dyn'), Boolean);
  set('dynamic_thresholding', first('dynamic_thresholding'), Boolean);
  set('uncond_scale', first('uncond_scale'), Number);
  set('controlnet_strength', first('controlnet_strength'), Number);
  set('prefer_brownian', first('prefer_brownian'), Boolean);
  set('deliberate_euler_ancestral_bug', first('deliberate_euler_ancestral_bug'), Boolean);
  set('legacy_v3_extend', first('legacy_v3_extend'), Boolean);
  const importedUseCoords = first('use_coords');
  const importedPositionMode = first('position_mode');
  if(importedUseCoords !== undefined || importedPositionMode !== undefined){
    const mode = POSITION_MODES.has(String(importedPositionMode || '').toLowerCase())
      ? String(importedPositionMode).toLowerCase()
      : (Boolean(importedUseCoords) ? 'coordinate' : 'ai');
    setPositionMode(mode, false);
  }
  paintParams();
  if(window._paintCoords) window._paintCoords();
}
function renderPresets(){
  const s = $('presetSel');
  s.innerHTML = '<option value="">베이스 프리셋 불러오기...</option>';
  STYLES.forEach((x,i) => { const o = document.createElement('option'); o.value = i; o.textContent = x.name; s.appendChild(o); });
  paintActiveStyle();
}
$('presetSel').addEventListener('change', () => {
  const i = $('presetSel').value;
  if(i === '') return;
  const st = STYLES[i];
  STATE.base_prompt = st.prompt; $('basePrompt').value = st.prompt;
  STATE.negative_prompt = st.negative || ''; $('negPrompt').value = STATE.negative_prompt;
  applyStyleSettings(st.settings);
  STATE.style_name = st.name;
  paintActiveStyle(); tokens(); save();
});
$('presetSave').addEventListener('click', async () => {
  const name = prompt('베이스 프리셋 이름 (프롬프트+네거티브+파라미터가 함께 저장):');
  if(!name) return;
  const r = await fetch('/api/style_save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, prompt: $('basePrompt').value, negative: $('negPrompt').value,
      settings: styleSettingsFromUI()})});
  const res = await r.json();
  if(res.ok){
    STYLES = res.styles; STATE.style_name = name;
    renderPresets(); renderLibrary(); save();
    alert(`그림체/${name}.json 저장됨`);
  }
  else alert(res.error || '저장 실패');
});

/* ── 캐릭터 슬롯 ── */
function characterVariantChoice(character){
  character = character || {};
  const variant = character.variant && typeof character.variant === 'object'
    ? character.variant : {};
  const group = String(variant.group || '').trim();
  if(!group || variant.enabled !== false) return character;
  const same = (STATE.characters || []).filter(item => {
    const value = item && item.variant && typeof item.variant === 'object'
      ? item.variant : {};
    return String(value.group || '').trim() === group && value.enabled !== false;
  });
  return same[0] || character;
}
function characterVariantLabel(character){
  const variant = character && character.variant && typeof character.variant === 'object'
    ? character.variant : {};
  const name = String(variant.name || '').trim();
  const group = String(variant.group || '').trim();
  return group ? ` · ${name || '기본 변형'}${variant.enabled === false ? ' (꺼짐·fallback)' : ''}` : '';
}
function comparisonCharacterChoices(){
  const standalone = [], grouped = new Map();
  (STATE.characters || []).forEach(character => {
    const prompt = [character.female, character.clothed].filter(Boolean).join(', ').trim();
    if(!prompt) return;
    const variant = character.variant && typeof character.variant === 'object'
      ? character.variant : {};
    const group = String(variant.group || '').trim();
    if(!group) standalone.push(character);
    else{
      if(!grouped.has(group)) grouped.set(group, []);
      grouped.get(group).push(character);
    }
  });
  grouped.forEach(members => {
    const active = members.filter(item => (item.variant || {}).enabled !== false);
    standalone.push(...(active.length ? active : members.slice(0,1)));
  });
  return standalone;
}
function selectedVariationBundle(record){
  const variants = Array.isArray((record||{}).variants) ? record.variants : [];
  const selected = variants.find(item =>
    String((item||{}).id||'') === String((record||{}).selected_variant_id||''));
  const pick = (baseKeys, variantKeys=baseKeys) => {
    if(selected){
      for(const key of variantKeys) if(Object.prototype.hasOwnProperty.call(selected,key))
        return selected[key] == null ? '' : String(selected[key]);
    }
    for(const key of baseKeys) if(Object.prototype.hasOwnProperty.call(record||{},key))
      return record[key] == null ? '' : String(record[key]);
    return '';
  };
  return {
    prompt:pick(['prompt','female','appearance']),
    outfit:pick(['outfit','clothed']),
    negative:pick(['negative']),
    selected:selected || null
  };
}
function characterBundle(c, forSlot=true){
  c = characterVariantChoice(c);
  const result = {
    id:c.id||'', name:c.name||'', prompt:c.female||c.prompt||'',
    outfit:c.clothed||c.outfit||'', negative:c.negative||'',
    variant:JSON.parse(JSON.stringify(c.variant||{})),
    variants:JSON.parse(JSON.stringify(c.variants||[])),
    selected_variant_id:c.selected_variant_id||'',
    reference_ids:JSON.parse(JSON.stringify(c.reference_ids||[])),
    vibe_ids:JSON.parse(JSON.stringify(c.vibe_ids||[]))
  };
  if(forSlot) result.enabled = c.enabled !== false;
  return result;
}
function renderSlots(){
  const h = $('slotList'); h.innerHTML = '';
  (STATE.char_slots || []).forEach((s,i) => {
    const el = document.createElement('div');
    el.className = 'slot';
    const on = s.enabled !== false;
    if(!on) el.style.opacity = '.55';
    el.innerHTML = `<div class="r1">
      <label class="sw" title="끄면 이 인물은 보내지 않습니다 (칸은 남습니다)">
        <input type="checkbox" data-sen="${i}" ${on ? 'checked' : ''}><span class="sl"></span></label>
      <input type="text" data-sf="name" data-si="${i}" placeholder="이름" value="${escA(s.name)}">
      <button class="danger" data-sdel="${i}">✕</button></div>
      <textarea data-sf="prompt" data-si="${i}" placeholder="girl, ... (외형 — 잘 안 바꾸는 것)">${esc(s.prompt)}</textarea>
      <!-- 의상을 따로 둔다 (NAIS2-Forge 와 같은 생각) — 외형은 그대로 두고 옷만 갈아입힐 수 있다.
           전송할 때 외형 뒤에 이어 붙는다. -->
      <input type="text" data-sf="outfit" data-si="${i}" placeholder="의상 (비워도 됨 · 외형 뒤에 붙습니다)" value="${escA(s.outfit || '')}">
      <input type="text" data-sf="negative" data-si="${i}" placeholder="이 인물 전용 네거티브" value="${escA(s.negative)}">
      ${(s.variants||[]).length ? `<label class="field" style="margin-top:5px;"><span>저장한 이미지 variation</span>
        <select data-slot-variation="${i}"><option value="">기본 원문</option>${(s.variants||[]).map(v =>
          `<option value="${escA(v.id||'')}"${String(s.selected_variant_id||'')===String(v.id||'')?' selected':''}>${esc(v.name||'이름 없는 variation')}</option>`
        ).join('')}</select></label>` : ''}
      <div class="posrow"><span class="hint">위치</span>
        <span class="hint" data-posai>AI가 배치</span>
        <span data-posgrid-wrap><div class="posgrid" data-pos="${i}"></div></span>
        <span class="poscoords" data-poscoord-wrap>
          <label class="hint">X <input type="number" class="posnum" data-posx="${i}" min="0" max="1" step="0.01" title="가로 위치 0~1 연속값"></label>
          <label class="hint">Y <input type="number" class="posnum" data-posy="${i}" min="0" max="1" step="0.01" title="세로 위치 0~1 연속값"></label>
        </span>
        <span class="hint" data-poslabel="${i}"></span></div>`;
    h.appendChild(el);
  });
  drawPosGrids();
  renderPositionEditors();
  h.querySelectorAll('[data-sf]').forEach(el => el.addEventListener('input', () => {
    STATE.char_slots[+el.dataset.si][el.dataset.sf] = el.value; tokens(); save();
  }));
  h.querySelectorAll('[data-sen]').forEach(x => x.addEventListener('change', () => {
    STATE.char_slots[+x.dataset.sen].enabled = x.checked;
    /* 켠 인물 수가 바뀌면 좌표·경고도 다시 (끈 인물은 보내지 않는다) */
    autoCoordsOnSecond(); renderSlots(); tokens(); save();
  }));
  h.querySelectorAll('[data-slot-variation]').forEach(el => el.addEventListener('change', () => {
    STATE.char_slots[+el.dataset.slotVariation].selected_variant_id = el.value;
    tokens(); save();
  }));
  h.querySelectorAll('[data-sdel]').forEach(b => b.addEventListener('click', () => {
    STATE.char_slots.splice(+b.dataset.sdel, 1);
    (STATE.char_centers || []).splice(+b.dataset.sdel, 1);   // 좌표도 같이 지운다
    autoCoordsOnSecond(); renderSlots(); tokens(); save();
  }));
  /* 좌표 숫자 칸 — 격자(5×5)는 빠른 선택용이고, 여기는 0~1 자유값.
     실측(라운드01): NAI 서버는 좌표를 격자로 반올림하지 않는다 — 0.05 차이도 반영된다.
     'change' 에만 묶는다 (입력 중 다시 그리면 커서를 잃는다). */
  h.querySelectorAll('[data-posx],[data-posy]').forEach(el => el.addEventListener('change', () => {
    const i = +(el.dataset.posx != null ? el.dataset.posx : el.dataset.posy);
    const axis = el.dataset.posx != null ? 'x' : 'y';
    let v = parseFloat(el.value);
    if(!isFinite(v)) v = 0.5;
    v = Math.min(1, Math.max(0, Math.round(v * 100) / 100));
    STATE.char_centers = STATE.char_centers || [];
    while(STATE.char_centers.length <= i) STATE.char_centers.push({x:0.5, y:0.5});
    STATE.char_centers[i] = Object.assign({x:0.5, y:0.5}, STATE.char_centers[i]);
    STATE.char_centers[i][axis] = v;
    /* 보정값을 칸에 바로 되쓴다 — drawPosGrids 는 포커스 중인 칸을 안 건드리는데
       change 는 포커스가 남은 채로도 오므로, 안 쓰면 화면 1.5 / 저장 1 처럼 어긋난다 */
    el.value = String(v);
    drawPosGrids(); save();
    if(positionMode() === 'ai') flash('위치판이나 좌표 모드를 먼저 고르세요.');
  }));
  const lib = $('slotLib');
  lib.innerHTML = '<option value="">+ 라이브러리에서...</option>';
  (STATE.characters||[]).forEach(c => {
    const o = document.createElement('option'); o.value = c.id;
    o.textContent = (c.name || '(무명)') + characterVariantLabel(c);
    lib.appendChild(o);
  });
  if(window._paintCoords) window._paintCoords();   // 인물 수가 바뀌면 몸 붙음 경고도 다시
}
/* 수동 모드를 이미 고른 경우에만 새 인물의 빈 위치값을 채운다.
   AI 자동은 정상 선택이므로 인물이 늘어도 임의로 위치판/좌표로 바꾸지 않는다. */
/* 보낼 인물 = 켠 것 + 내용이 있는 것. 칸은 6명 넘게 둬도 된다. */
function activeSlotIdx(){
  /* 주석(#) 줄만 있는 칸은 '켠 인물'이 아니다 — 서버 slot_prompt 와 같은 규칙 (CQA-003) */
  return (STATE.char_slots || [])
    .map((s, i) => ({s, i}))
    .filter(x => {
      const value = selectedVariationBundle(x.s);
      return x.s.enabled !== false
      && [value.prompt, value.outfit].some(v =>
        Boolean((v || '').replace(/^[ \t]*#.*$/gm, '').trim()))
    })
    .map(x => x.i);
}
function autoCoordsOnSecond(){
  const n = activeSlotIdx().length;
  if(n < 2 || positionMode() === 'ai') return false;
  /* ★ 인물이 늘 때 좌표도 따라가야 한다.
     안 그러면 셋째부터는 기본 0.5/0.5 를 써서 서로 겹치고, 좌표를 켜 둔 게 무의미해진다
     (2명 기준 0.3/0.7 에 멈춰 있던 것을 실측에서 잡았다).
     이미 손으로 고른 자리가 있으면 그건 건드리지 않고 **빈 칸만** 채운다. */
  /* ⚠ 좌표는 **칸 index** 로 저장한다 (껐다 켜도 자리가 유지되게).
     예전에는 `slice(0, n)` 으로 **켠 인물 수**만큼 잘라서, 꺼 둔 칸이 앞에 있으면
     뒤쪽 칸의 좌표가 통째로 날아갔다 (복제 후 좌표 소실 — Codex 재현 04:53).
     자를 게 아니라 **칸 수만큼 유지하고, 켠 칸의 빈 자리만** 채운다. */
  const idx = activeSlotIdx();
  const slots = (STATE.char_slots || []).length;
  const cs = (STATE.char_centers || []).slice(0, Math.max(slots, 0));
  while(cs.length < slots) cs.push(null);
  const auto = spreadCenters(n);
  const taken = new Set(cs.filter(Boolean).map(c => `${c.x},${c.y}`));
  let changed = false;
  idx.forEach((slotI, k) => {
    if(cs[slotI] && cs[slotI].x != null) return;      // 손으로 고른 자리는 보존
    const free = auto.find(a => !taken.has(`${a.x},${a.y}`)) || auto[k] || {x:0.5, y:0.5};
    cs[slotI] = free; taken.add(`${free.x},${free.y}`); changed = true;
  });
  STATE.char_centers = cs.map(c => c || {x:0.5, y:0.5});
  return changed;
}
/* 좌표가 서로 겹치는 인물이 있는지 (겹치면 분리가 안 된다) */
function coordsClash(){
  const idx = activeSlotIdx();
  if(idx.length < 2 || positionMode() === 'ai') return false;
  const seen = new Set();
  for(const i of idx){
    const c = (STATE.char_centers || [])[i] || {x:0.5, y:0.5};
    const k = `${c.x ?? 0.5},${c.y ?? 0.5}`;
    if(seen.has(k)) return true;
    seen.add(k);
  }
  return false;
}
$('slotAdd').addEventListener('click', () => {
  (STATE.char_slots = STATE.char_slots || []).push({name:'', prompt:'', negative:''});
  if(autoCoordsOnSecond()) flash('새 인물의 빈 위치값을 현재 수동 모드에 맞게 채웠습니다.');
  renderSlots(); tokens(); save();
});
/* ── 진단 서랍 — 서버에서 먼저 redaction한 구조화 이벤트만 받는다 ── */

function slotsBulk(fn){
  /* ⚠ 좌표(char_centers)는 **칸 index** 로 짝지어져 있다. 칸 수가 안 바뀌는 동작
     (켜기/끄기·태그 주입)에서 자동 재배치를 부르면 손으로 잡아 둔 자리가 날아간다.
     칸 수가 실제로 바뀐 경우에만 자동 좌표를 손댄다 (Codex 재현 보고 04:53). */
  STATE.char_slots = STATE.char_slots || [];
  const before = STATE.char_slots.length;
  fn(STATE.char_slots);
  if(STATE.char_slots.length !== before) autoCoordsOnSecond();
  renderSlots(); tokens(); save();
}
if($('slotAllOn')) $('slotAllOn').addEventListener('click', () =>
  slotsBulk(ss => ss.forEach(s => s.enabled = true)));
if($('slotAllOff')) $('slotAllOff').addEventListener('click', () =>
  slotsBulk(ss => ss.forEach(s => s.enabled = false)));
if($('slotBulkAdd')) $('slotBulkAdd').addEventListener('click', () => {
  const t = prompt('켠 인물 칸의 외형 뒤에 붙일 태그 (콤마로 여러 개):');
  if(!t || !t.trim()) return;
  slotsBulk(ss => ss.forEach(s => {
    if(s.enabled === false) return;
    const cur = (s.prompt || '').trim().replace(/,$/, '');
    s.prompt = cur ? cur + ', ' + t.trim() : t.trim();
  }));
});
if($('slotDupAll')) $('slotDupAll').addEventListener('click', () => {
  slotsBulk(ss => {
    /* 칸을 복제하면 **좌표도 같은 자리에서 복제**해야 짝이 안 어긋난다.
       (예전엔 칸만 늘어나 뒤쪽 칸의 좌표가 밀렸다 — Codex 가 A/B/C 시퀀스로 잡음) */
    STATE.char_centers = STATE.char_centers || [];
    const copies = [], ctrs = [];
    ss.forEach((s, i) => {
      if(s.enabled === false) return;
      copies.push(Object.assign({}, s, {name: (s.name || '인물') + ' 사본'}));
      ctrs.push(Object.assign({x:0.5, y:0.5}, STATE.char_centers[i] || {}));
    });
    if(!copies.length){ flash('켠 인물 칸이 없습니다.'); return; }
    while(STATE.char_centers.length < ss.length) STATE.char_centers.push({x:0.5, y:0.5});
    ss.push(...copies);
    STATE.char_centers.push(...ctrs);
  });
});
if($('slotDelOff')) $('slotDelOff').addEventListener('click', () => {
  const off = (STATE.char_slots || []).filter(s => s.enabled === false).length;
  if(!off){ flash('꺼 둔 칸이 없습니다.'); return; }
  if(!confirm(`꺼 둔 칸 ${off}개를 지울까요? (좌표도 함께 지웁니다)`)) return;
  slotsBulk(ss => {
    const keep = [], ctrs = [];
    ss.forEach((s, i) => {
      if(s.enabled === false) return;
      keep.push(s); ctrs.push((STATE.char_centers || [])[i] || {x:0.5, y:0.5});
    });
    STATE.char_centers = ctrs;         // 좌표는 칸 index 라 같이 추려야 짝이 안 어긋난다
    ss.length = 0; ss.push(...keep);
  });
});
$('slotLib').addEventListener('change', () => {
  const c = (STATE.characters||[]).find(x => x.id === $('slotLib').value);
  if(c){ (STATE.char_slots = STATE.char_slots || []).push(characterBundle(c, true));
  if(autoCoordsOnSecond()) flash('새 인물의 빈 위치값을 현재 수동 모드에 맞게 채웠습니다.');
    renderSlots(); tokens(); save(); }
  $('slotLib').value = '';
});

/* ── 생성 ── */
const QUICK_QTY_MAX = 99;
function quickQty(value, notify=false){
  const raw = Number(value);
  const clean = Math.min(QUICK_QTY_MAX, Math.max(1, Number.isFinite(raw) ? Math.trunc(raw) : 1));
  if(notify && clean !== raw) flash(`빠른 생성 수량은 1~${QUICK_QTY_MAX}장으로 맞췄습니다.`);
  $('qty').value = clean;
  return clean;
}
$('qtyM').addEventListener('click', () => quickQty((+$('qty').value||1) - 1));
$('qtyP').addEventListener('click', () => quickQty((+$('qty').value||1) + 1, true));
$('qty').addEventListener('change', () => quickQty($('qty').value, true));
$('genBtn').addEventListener('click', async () => {
  await doSave();
  const n = quickQty($('qty').value, true);
  setMode('preview');
  for(let i = 0; i < n; i++){
    const r = await (await fetch('/api/generate_one', {method:'POST'})).json();
    if(!r.ok){ alert(r.error || '생성 실패'); return; }
    await waitIdle();
  }
});
async function waitIdle(){
  for(;;){
    await new Promise(r => setTimeout(r, 900));
    const s = await (await fetch('/status.json', {cache:'no-store'})).json();
    if(!s.running) return;
  }
}
$('batchBtn').addEventListener('click', async () => {
  await doSave();
  const r = await (await fetch('/api/start', {method:'POST'})).json();
  if(!r.ok){ alert(r.error || '시작할 수 없습니다.'); return; }
  setMode('preview');
});

/* ── img2img · 인페인트 · Outpaint ──────────────────────────────────
   마스크는 흰색이 '다시 그릴 곳'. NAI 는 64 배수 크기를 원하므로 맞춰서 보낸다.
   Outpaint도 별도 생성기가 아니라 원본 바깥을 자동 마스킹한 같은 infill 작업이다. */
let I2I = {img:null, painting:false, erase:false, undo:[],
  variationCharacter:null, variationMode:'img2img',
  hasVariationCandidate:false,
  operation:'edit', sourceWidth:0, sourceHeight:0};
function i2iVariationUpdate(){
  const character = I2I.variationCharacter;
  const tools = $('i2iVariationTools'), saves = $('i2iVariationSave');
  if(!tools || !saves) return;
  tools.classList.toggle('hidden', !character);
  saves.classList.toggle(
    'hidden', !character || !I2I.hasVariationCandidate);
  if(!character) return;
  I2I.variationMode = $('i2iVariationMode').value || 'img2img';
  const effectivePrompt = [$('i2iTrialAppearance').value, $('i2iTrialOutfit').value]
    .filter(Boolean).join(', ');
  const reference = I2I.variationMode === 'character-reference'
    ? 'Character Reference 1장 · 저장된 Vibe는 이 시험에서만 제외'
    : I2I.variationMode === 'reference-inset'
    ? '왼쪽 원본 보존 · 오른쪽 자동 마스크 Inpaint'
    : I2I.variationMode === 'inpaint'
    ? '사용자가 칠한 마스크만 Inpaint'
    : '원본 전체 img2img';
  $('i2iVariationPreview').innerHTML =
    `<b>전송 전 확인</b><span>캐릭터 ${esc(effectivePrompt||'(비어 있음)')}</span>`
    + `<span>Negative ${esc($('i2iTrialNegative').value||'(없음)')}</span>`
    + `<span>${esc($('i2iTrialWidth').value)}×${esc($('i2iTrialHeight').value)}</span>`
    + `<span>${esc(reference)}</span>`;
  const manualMask = I2I.variationMode === 'inpaint';
  ['i2iBrush','i2iErase','i2iUndo','i2iClear'].forEach(id => {
    const el = $(id); if(el) el.disabled = !manualMask;
  });
  $('i2iMask').style.pointerEvents = manualMask ? 'auto' : 'none';
  $('i2iMask').style.cursor = manualMask ? 'crosshair' : 'default';
  if(window.i2iCostRefresh) window.i2iCostRefresh();
}
function outpaintValue(id){
  const raw = Math.max(0, Math.min(1536, Number($(id).value) || 0));
  const value = Math.round(raw / 64) * 64;
  $(id).value = String(value);
  return value;
}
function outpaintMargins(){
  return {
    left:outpaintValue('outpaintLeft'), right:outpaintValue('outpaintRight'),
    top:outpaintValue('outpaintTop'), bottom:outpaintValue('outpaintBottom')
  };
}
function i2iSourceCanvas(){
  const t = document.createElement('canvas');
  t.width = I2I.sourceWidth; t.height = I2I.sourceHeight;
  if(I2I.img) t.getContext('2d').drawImage(I2I.img, 0, 0, t.width, t.height);
  return t;
}
function i2iRender(){
  if(!I2I.img) return;
  const margins = outpaintMargins();
  const outpaint = I2I.operation === 'outpaint';
  const w = I2I.sourceWidth + (outpaint ? margins.left + margins.right : 0);
  const h = I2I.sourceHeight + (outpaint ? margins.top + margins.bottom : 0);
  if(w > 2048 || h > 2048){
    $('i2iMsg').textContent = `최종 크기 ${w}×${h}는 2048px 한도를 넘습니다. 확장값을 줄여주세요.`;
    return;
  }
  const b = $('i2iBase'), m = $('i2iMask');
  b.width = m.width = w; b.height = m.height = h;
  const base = b.getContext('2d');
  base.clearRect(0, 0, w, h);
  base.drawImage(I2I.img, outpaint ? margins.left : 0, outpaint ? margins.top : 0,
    I2I.sourceWidth, I2I.sourceHeight);
  const mask = m.getContext('2d');
  mask.clearRect(0, 0, w, h);
  if(outpaint){
    mask.fillStyle = '#fff';
    if(margins.top) mask.fillRect(0, 0, w, margins.top);
    if(margins.bottom) mask.fillRect(0, h - margins.bottom, w, margins.bottom);
    if(margins.left) mask.fillRect(0, margins.top, margins.left, I2I.sourceHeight);
    if(margins.right) mask.fillRect(w - margins.right, margins.top,
      margins.right, I2I.sourceHeight);
  }
  I2I.undo = [];
  $('outpaintSize').textContent = outpaint
    ? `원본 ${I2I.sourceWidth}×${I2I.sourceHeight} → 최종 ${w}×${h}`
    : `원본 ${I2I.sourceWidth}×${I2I.sourceHeight}`;
  i2iZoom(); i2iMode();
}
function setI2IOperation(operation, persist=false){
  I2I.operation = operation === 'outpaint' ? 'outpaint' : 'edit';
  const outpaint = I2I.operation === 'outpaint';
  $('i2iEditMode').classList.toggle('primary', !outpaint);
  $('i2iOutpaintMode').classList.toggle('primary', outpaint);
  $('outpaintControls').classList.toggle('hidden', !outpaint);
  $('i2iOperationHint').textContent = outpaint
    ? '원본은 그대로 두고 넓힌 바깥 영역만 생성'
    : '붓을 칠하지 않으면 img2img, 칠하면 인페인트';
  $('i2iMask').style.cursor = outpaint ? 'default' : 'crosshair';
  $('i2iMask').style.pointerEvents = outpaint ? 'none' : 'auto';
  ['i2iBrush','i2iErase','i2iUndo','i2iClear'].forEach(id => {
    const el = $(id); if(el) el.disabled = outpaint;
  });
  if(I2I.img) i2iRender();
  if(persist && STATE){
    STATE.ui = STATE.ui || {};
    STATE.ui.outpaint = Object.assign({}, outpaintMargins());
    save();
  }
}
function i2iLoad(file){
  const fr = new FileReader();
  fr.onload = () => {
    const im = new Image();
    im.onload = () => {
      I2I.img = im;
      I2I.sourceWidth = Math.max(64, Math.floor(im.width / 64) * 64);
      I2I.sourceHeight = Math.max(64, Math.floor(im.height / 64) * 64);
      $('i2iStage').classList.remove('hidden');
      i2iRender();
      $('i2iMsg').textContent = `${im.width}×${im.height} → ${I2I.sourceWidth}×${I2I.sourceHeight} 원본으로 맞춥니다`
        + (I2I.variationCharacter
          ? ` · '${I2I.variationCharacter.name}' 전체 프롬프트·착의·네거티브로 임시 변형`
          : ' (NAI 는 64 배수만 받습니다)')
        + (I2I.operation === 'outpaint' ? ' · 흰 바깥 영역만 이어 그립니다' : '');
      i2iVariationUpdate();
      if(window.i2iCostRefresh) window.i2iCostRefresh();
    };
    im.src = fr.result;
  };
  fr.readAsDataURL(file);
}
/* 생성 결과를 다시 파일로 내려받아 다음 작업에 넘긴다.
   최근 결과와 탐색기 결과가 Vibe·Reference·img2img 구현을 각각 복제하지 않고
   같은 경계를 쓴다. 다운로드가 실패하면 기존 상태는 하나도 바꾸지 않는다. */
async function resultFile(url, name){
  const r = await fetch(url, {cache:'no-store'});
  if(!r.ok) throw new Error(`결과 그림을 읽지 못했습니다 (HTTP ${r.status}).`);
  const blob = await r.blob();
  if(!blob.type.startsWith('image/')) throw new Error('결과가 이미지 형식이 아닙니다.');
  let safe = String(name || 'result.webp').replace(/[\\/:*?"<>|]/g, '_');
  if(!/\.(png|webp)$/i.test(safe)) safe += '.webp';
  return new File([blob], safe, {type:blob.type || 'image/webp'});
}
async function resultToReference(url, name, kind, msg){
  if(kind === 'vibe' && !confirm(
    '이 결과를 바이브로 등록할까요?\n토큰이 있으면 처음 한 번 인코딩에 2 Anlas가 듭니다.'
  )) return false;
  if(msg) msg.textContent = '결과 그림을 준비하는 중...';
  try{
    const file = await resultFile(url, name);
    await addRefs([file], kind);
    setMode('preview');
    const tab = document.querySelector(`[data-reftab="${kind === 'vibe' ? 'vibe' : 'cref'}"]`);
    const opener = document.querySelector('[data-ovl="refs"]');
    if(opener) opener.click();
    if(tab) tab.click();
    if(msg) msg.textContent = kind === 'vibe'
      ? '바이브에 등록했습니다.' : '캐릭터 레퍼런스에 등록했습니다.';
    return true;
  }catch(e){
    if(msg) msg.textContent = String(e.message || e);
    return false;
  }
}
async function resultToI2I(url, name, msg, variationCharacter=null, operation='edit'){
  if(msg) msg.textContent = '결과 그림을 준비하는 중...';
  try{
    I2I.variationCharacter = variationCharacter;
    if(variationCharacter){
      I2I.hasVariationCandidate = false;
      const effective = selectedVariationBundle(variationCharacter);
      I2I.variationMode = 'img2img';
      $('i2iVariationMode').value = 'img2img';
      $('i2iVariationName').textContent =
        `'${variationCharacter.name || '캐릭터'}' 이미지 시험·변형`;
      $('i2iTrialAppearance').value =
        effective.prompt;
      $('i2iTrialOutfit').value =
        effective.outfit;
      $('i2iTrialNegative').value = effective.negative;
      $('i2iTrialScene').value = STATE.base_prompt || '';
      $('i2iTrialWidth').value = STATE.width || 832;
      $('i2iTrialHeight').value = STATE.height || 1216;
      $('i2iVariationSaveName').value = '';
    }
    setI2IOperation(operation);
    const file = await resultFile(url, name);
    expClose();
    setMode('preview');
    STATE.ui = STATE.ui || {};
    STATE.ui.result_tool = 'i2i';
    arrangeResultTools((STATE.ui || {}).layout !== 'classic');
    i2iLoad(file);
    i2iVariationUpdate();
    if(msg) msg.textContent = operation === 'outpaint'
      ? 'Outpaint에 넣었습니다.' : 'img2img·인페인트에 넣었습니다.';
    setTimeout(() => $('i2iStage').scrollIntoView({behavior:'smooth', block:'start'}), 80);
    return true;
  }catch(e){
    if(msg) msg.textContent = String(e.message || e);
    return false;
  }
}
function bindLatestResultActions(){
  const host = $('pvResultActions');
  if(!host || host._bound) return;
  host._bound = true;
  host.querySelectorAll('[data-latest-action]').forEach(button => button.addEventListener('click', async () => {
    const url = '/latest.webp?t=' + Date.now();
    const name = lastFile || '최근 생성.webp';
    const msg = $('pvResultMsg');
    const action = button.dataset.latestAction;
    if(action === 'i2i') await resultToI2I(url, name, msg);
    else if(action === 'outpaint') await resultToI2I(url, name, msg, null, 'outpaint');
    else await resultToReference(url, name, action, msg);
  }));
}
function i2iPainted(){
  const m = $('i2iMask'); if(!m.width) return false;
  const d = m.getContext('2d').getImageData(0, 0, m.width, m.height).data;
  for(let i = 3; i < d.length; i += 4) if(d[i] > 8) return true;
  return false;
}
function i2iMode(){
  const painted = i2iPainted();
  /* 강도 상한이 모드마다 다르다.
     인페인트는 1.00 까지 쓸 수 있다 (칠한 곳을 완전히 새로 그림).
     img2img 는 0.99 가 끝이다 — 1.00 이면 원본을 아예 안 보게 되어 NAI 가 막는다. */
  const outpaint = I2I.operation === 'outpaint';
  const cap = (painted || outpaint) ? 1 : 0.99;
  const sl = $('i2iStrength');
  sl.max = String(cap);
  /* ⚠ max 를 바꾸면 브라우저가 value 를 **먼저** 잘라낸다.
     그래서 '넘쳤나' 를 따로 재면 안 걸린다 — 표시는 늘 현재 값으로 맞춘다. */
  $('i2iStrengthN').textContent = Number(sl.value).toFixed(2);
  $('i2iMode').textContent = (outpaint
    ? '넓힌 바깥만 이어 그림 → Outpaint (원본 영역 보존)'
    : painted
    ? '칠한 곳만 다시 그림 → 인페인트 (강도 1.00 까지)'
    : '칠하지 않음 → img2img (전체를 다시 그림 · 강도 0.99 까지)');
  if(window.i2iCostRefresh) window.i2iCostRefresh();   // 모드가 바뀌면 비용도 (CQA-008)
}
function i2iZoom(){
  const b = $('i2iBase'), m = $('i2iMask');
  if(!b.width) return;
  const z = Number($('i2iZoom').value) || 1;
  const w = Math.round(b.width * z), h = Math.round(b.height * z);
  b.style.width = m.style.width = w + 'px';
  b.style.height = m.style.height = h + 'px';
}
if($('i2iDrop')){
  const m = $('i2iMask');
  const at = e => {
    const r = m.getBoundingClientRect();
    return [(e.clientX - r.left) * (m.width / r.width), (e.clientY - r.top) * (m.height / r.height)];
  };
  const dab = (x, y) => {
    const c = m.getContext('2d');
    /* 지우개는 합성 모드만 바꾼다 — 칠한 자리를 부분만 파낸다 */
    c.globalCompositeOperation = I2I.erase ? 'destination-out' : 'source-over';
    c.fillStyle = '#fff'; c.beginPath();
    c.arc(x, y, Number($('i2iBrush').value) / 2, 0, Math.PI * 2); c.fill();
    c.globalCompositeOperation = 'source-over';
  };
  /* 붓질 하나를 시작할 때 직전 상태를 쌓아 둔다 → 이어서 고쳐 그릴 수 있다
     (예전엔 지우면 전부 날아가서 처음부터 다시 칠해야 했다) */
  const pushUndo = () => {
    try{
      I2I.undo.push(m.getContext('2d').getImageData(0, 0, m.width, m.height));
      if(I2I.undo.length > 20) I2I.undo.shift();
    }catch(e){}
  };
  m.addEventListener('pointerdown', e => {
    if(I2I.operation === 'outpaint') return;
    pushUndo(); I2I.painting = true; m.setPointerCapture(e.pointerId); dab(...at(e));
  });
  m.addEventListener('pointermove', e => { if(I2I.painting) dab(...at(e)); });
  ['pointerup','pointercancel','pointerleave'].forEach(ev =>
    m.addEventListener(ev, () => { if(I2I.painting){ I2I.painting = false; i2iMode(); } }));
  $('i2iUndo').addEventListener('click', () => {
    const prev = I2I.undo.pop();
    if(!prev){ $('i2iMsg').textContent = '되돌릴 붓질이 없습니다.'; return; }
    m.getContext('2d').putImageData(prev, 0, 0); i2iMode();
  });
  window.addEventListener('keydown', e => {
    if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && $('i2iStage')
       && !$('i2iStage').classList.contains('hidden')
       && !/INPUT|TEXTAREA|SELECT/.test((document.activeElement||{}).tagName || '')){
      e.preventDefault(); $('i2iUndo').click();
    }
  });
  $('i2iErase').addEventListener('click', () => {
    I2I.erase = !I2I.erase;
    $('i2iErase').textContent = I2I.erase ? '🖌️ 붓으로' : '🧽 지우개';
    $('i2iErase').style.borderColor = I2I.erase ? 'var(--accent)' : '';
  });
  $('i2iZoom').addEventListener('change', i2iZoom);
  $('i2iClear').addEventListener('click', () => {
    pushUndo();
    m.getContext('2d').clearRect(0, 0, m.width, m.height); i2iMode();
  });
  $('i2iBrush').addEventListener('input', () => $('i2iBrushN').textContent = $('i2iBrush').value + 'px');
  $('i2iStrength').addEventListener('input', () =>
    $('i2iStrengthN').textContent = Number($('i2iStrength').value).toFixed(2));
  $('i2iEditMode').addEventListener('click', () => setI2IOperation('edit', true));
  $('i2iOutpaintMode').addEventListener('click', () => setI2IOperation('outpaint', true));
  ['outpaintLeft','outpaintRight','outpaintTop','outpaintBottom'].forEach(id =>
    $(id).addEventListener('change', () => {
      if(I2I.img) i2iRender();
      STATE.ui = STATE.ui || {};
      STATE.ui.outpaint = Object.assign({}, outpaintMargins());
      save();
    }));
  $('outpaintHorizontal').addEventListener('click', () => {
    $('outpaintLeft').value = $('outpaintRight').value = '256';
    $('outpaintTop').value = $('outpaintBottom').value = '0';
    if(I2I.img) i2iRender();
  });
  $('outpaintVertical').addEventListener('click', () => {
    $('outpaintLeft').value = $('outpaintRight').value = '0';
    $('outpaintTop').value = $('outpaintBottom').value = '256';
    if(I2I.img) i2iRender();
  });
  $('i2iDrop').addEventListener('click', () => $('i2iFile').click());
  $('i2iDrop2').addEventListener('click', () => $('i2iFile').click());
  $('i2iFile').addEventListener('change', () => {
    if($('i2iFile').files[0]){
      I2I.variationCharacter = null;
      i2iVariationUpdate();
      i2iLoad($('i2iFile').files[0]);
    }
    $('i2iFile').value = '';
  });
  ['dragover','dragenter'].forEach(ev => $('i2iDrop').addEventListener(ev, e => {
    e.preventDefault(); $('i2iDrop').style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => $('i2iDrop').addEventListener(ev, e => {
    e.preventDefault(); $('i2iDrop').style.borderColor = ''; }));
  $('i2iDrop').addEventListener('drop', e => {
    const f = [...(e.dataTransfer.files || [])].find(x => /image\/(png|webp)/.test(x.type));
    if(f){ I2I.variationCharacter = null; i2iVariationUpdate(); i2iLoad(f); }
  });
  [
    'i2iVariationMode','i2iTrialWidth','i2iTrialHeight','i2iTrialScene',
    'i2iTrialAppearance','i2iTrialOutfit','i2iTrialNegative',
    'i2iRefStrength','i2iRefFidelity'
  ].forEach(id => $(id).addEventListener(
    id === 'i2iVariationMode' ? 'change' : 'input', i2iVariationUpdate));
  /* 원본 그림을 쓰는 작업은 Opus 무료가 아니다 — 실행 버튼 옆에 실제 비용을 띄운다 (CQA-008) */
  window.i2iCostRefresh = async () => {
    const el = $('i2iCost');
    if(!el || !I2I.img) return;
    const painted = i2iPainted();
    const outpaint = I2I.operation === 'outpaint';
    const b = $('i2iBase');
    const trialMode = I2I.variationCharacter ? I2I.variationMode : '';
    const w = ['character-reference','reference-inset'].includes(trialMode)
      ? Number($('i2iTrialWidth').value)
      : Math.max(64, Math.floor(b.width / 64) * 64);
    const h = ['character-reference','reference-inset'].includes(trialMode)
      ? Number($('i2iTrialHeight').value)
      : Math.max(64, Math.floor(b.height / 64) * 64);
    const costMode = trialMode === 'character-reference' ? 't2i'
      : ['reference-inset','inpaint'].includes(trialMode) ? 'infill'
      : (painted || outpaint) ? 'infill' : 'img2img';
    try{
      const r = await (await fetch('/api/anlas', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({count:1, mode:costMode, width:w, height:h,
          char_refs:trialMode === 'character-reference' ? 1 : 0,
          strength: Number($('i2iStrength').value)})})).json();
      const label = trialMode === 'character-reference' ? 'Character Reference'
        : trialMode === 'reference-inset' ? 'Reference inset'
        : trialMode === 'inpaint' ? '인페인트'
        : outpaint ? 'Outpaint' : painted ? '인페인트' : 'img2img';
      if(r.ok) el.textContent = r.est.total > 0
        ? `💰 ${r.est.total} Anlas · ${label}`
        : `${label} — ${r.est.why}`;
    }catch(e){}
  };
  if($('i2iStrength')) $('i2iStrength').addEventListener('change', () => window.i2iCostRefresh());
  $('i2iGo').addEventListener('click', async () => {
    if(!I2I.img){ $('i2iMsg').textContent = '먼저 그림을 넣어주세요.'; return; }
    const painted = i2iPainted();
    const outpaint = I2I.operation === 'outpaint';
    const variationMode = I2I.variationCharacter ? I2I.variationMode : 'img2img';
    if(variationMode === 'inpaint' && !painted){
      $('i2iMsg').textContent = 'Inpaint 방식은 바꿀 부분을 먼저 칠해주세요.';
      return;
    }
    const margins = outpaintMargins();
    if(outpaint && !(margins.left || margins.right || margins.top || margins.bottom)){
      $('i2iMsg').textContent = '이어 그릴 방향의 확장 크기를 하나 이상 입력해주세요.';
      return;
    }
    if($('i2iBase').width > 2048 || $('i2iBase').height > 2048){
      $('i2iMsg').textContent = '최종 크기는 가로·세로 2048px를 넘을 수 없습니다.';
      return;
    }
    /* 마스크는 흑백 PNG 로 보낸다 — 칠한 곳이 흰색 */
    let mask = null;
    if(painted){
      const t = document.createElement('canvas');
      t.width = m.width; t.height = m.height;
      const c = t.getContext('2d');
      c.fillStyle = '#000'; c.fillRect(0, 0, t.width, t.height);
      c.drawImage(m, 0, 0);
      mask = t.toDataURL('image/png');
    }
    $('i2iMsg').textContent = (outpaint ? 'Outpaint' : painted ? '인페인트' : 'img2img') + ' 보내는 중...';
    STATE.ui = STATE.ui || {};
    STATE.ui.outpaint = Object.assign({}, margins);
    await doSave();
    const r = await (await fetch('/api/i2i', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({image: $('i2iBase').toDataURL('image/png'), mask,
        original: outpaint ? i2iSourceCanvas().toDataURL('image/png') : null,
        operation: outpaint ? 'outpaint' : 'edit',
        expansion: outpaint ? margins : null,
        strength: Number($('i2iStrength').value),
        variation_mode:variationMode,
        trial_width:Number($('i2iTrialWidth').value),
        trial_height:Number($('i2iTrialHeight').value),
        trial_scene_prompt:$('i2iTrialScene').value,
        trial_appearance:$('i2iTrialAppearance').value,
        trial_outfit:$('i2iTrialOutfit').value,
        trial_negative:$('i2iTrialNegative').value,
        reference_strength:Number($('i2iRefStrength').value),
        reference_fidelity:Number($('i2iRefFidelity').value),
        variation_character_id:(I2I.variationCharacter||{}).id || ''})})).json();
    if(r.ok && I2I.variationCharacter){
      I2I.hasVariationCandidate = true;
      i2iVariationUpdate();
    }
    $('i2iMsg').textContent = r.ok
      ? `${r.mode} 시작 (${r.width}×${r.height}) — 일반 생성 설정은 바뀌지 않습니다`
        + (r.vibe_suppressed ? ' · 저장 Vibe는 이 시험에서만 제외' : '')
      : (r.error || '실패');
  });
  $('i2iVariationSave').querySelectorAll('[data-variation-save]').forEach(button =>
    button.addEventListener('click', async () => {
      button.disabled = true;
      try{
        const r = await (await fetch('/api/character_variation_save', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            save_as:button.dataset.variationSave,
            name:$('i2iVariationSaveName').value
          })
        })).json();
        if(!r.ok) throw new Error(r.error || '저장하지 못했습니다.');
        const at = (STATE.characters||[]).findIndex(item => item.id === r.character.id);
        if(at >= 0) STATE.characters[at] = r.character;
        if(r.revision != null) STATE._revision = r.revision;
        rememberSavedKeys(['characters']);
        renderLibrary(); renderSlots(); renderSettings();
        $('i2iMsg').textContent =
          `${r.character.name || '캐릭터'}에 ${button.textContent.trim()} 완료 ✓`;
      }catch(error){
        $('i2iMsg').textContent = String(error.message || error);
      }finally{
        button.disabled = false;
      }
    }));
}
