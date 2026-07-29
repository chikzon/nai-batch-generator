/* 세팅 선택·Cast·씬·옵션·비교 실험을 구성하는 화면 기능.
   core와 generation 뒤, 자료·빌더·관리 기능 및 bootstrap보다 먼저 읽는다. */

/* ── 자료 비교 생성 ───────────────────────────────────────────────────
   그림체 전체 / 캐릭터 전체 / 직교 조합을 같은 크기·시드로 한 장씩 본다.
   실제 장수는 서버가 자료 파일을 다시 세어 확정하며, 확인한 수와 달라지면 시작을 거부한다. */
let CMP_PLAN = null, CMP_TIMER = null, CMP_RUNS = [], CMP_CATALOG = null;
let CMP_SELECTION_PENDING = null;
function comparisonSelectedValues(id){
  const el = $(id);
  return el ? [...el.selectedOptions].map(option => option.value) : [];
}
function comparisonAxisValues(id, numeric=false){
  const text = String(($(id) || {}).value || '');
  const out = [];
  text.split(',').forEach(raw => {
    const value = raw.trim();
    if(!value) return;
    const parsed = numeric ? Number(value) : value;
    if(numeric && !Number.isFinite(parsed)) return;
    if(!out.some(item => item === parsed)) out.push(parsed);
  });
  return out;
}
function comparisonSelectionRead(){
  const axes = {};
  const cfg = comparisonAxisValues('cmpAxisCfg', true);
  const steps = comparisonAxisValues('cmpAxisSteps', true)
    .map(value => Math.trunc(value));
  const sampler = comparisonAxisValues('cmpAxisSampler');
  if(cfg.length) axes['generation.cfg_scale'] = cfg;
  if(steps.length) axes['generation.steps'] = steps;
  if(sampler.length) axes['generation.sampler'] = sampler;
  return {
    styles: comparisonSelectedValues('cmpSelectStyles'),
    characters: comparisonSelectedValues('cmpSelectCharacters'),
    settings: comparisonSelectedValues('cmpSelectSettings'),
    axes
  };
}
function comparisonApplySelection(value){
  const selection = value || {};
  CMP_SELECTION_PENDING = JSON.parse(JSON.stringify(selection));
  if(!CMP_CATALOG) return;
  [
    ['cmpSelectStyles', selection.styles || []],
    ['cmpSelectCharacters', selection.characters || []],
    ['cmpSelectSettings', selection.settings || []]
  ].forEach(([id, values]) => {
    const wanted = new Set(values.map(String));
    [...$(id).options].forEach(option => {
      option.selected = wanted.has(option.value);
    });
  });
  const axes = selection.axes || {};
  $('cmpAxisCfg').value = (axes['generation.cfg_scale'] || []).join(', ');
  $('cmpAxisSteps').value = (axes['generation.steps'] || []).join(', ');
  $('cmpAxisSampler').value = (axes['generation.sampler'] || []).join(', ');
  CMP_SELECTION_PENDING = null;
}
async function comparisonCatalogLoad(){
  try{
    const result = await (await fetch('/api/compare_catalog', {cache:'no-store'})).json();
    if(!result.ok) throw new Error(result.error || '선택 자료 목록을 읽지 못했습니다.');
    CMP_CATALOG = result;
    [
      ['cmpSelectStyles', result.styles || []],
      ['cmpSelectCharacters', result.characters || []],
      ['cmpSelectSettings', result.settings || []]
    ].forEach(([id, rows]) => {
      $(id).innerHTML = rows.map(row =>
        `<option value="${escA(row.id)}">${esc(row.name)}</option>`).join('');
    });
    $('cmpSelectedMsg').textContent =
      `그림체 ${(result.styles||[]).length.toLocaleString()} · 캐릭터 ${(result.characters||[]).length.toLocaleString()} · 세팅 ${(result.settings||[]).length.toLocaleString()}`;
    comparisonApplySelection(
      CMP_SELECTION_PENDING || (((STATE.ui||{}).comparison||{}).selection) || {});
  }catch(error){
    CMP_CATALOG = null;
    $('cmpSelectedMsg').textContent = String(error);
  }
}
function comparisonRead(){
  const mode = (document.querySelector('input[name="cmpMode"]:checked') || {}).value || 'styles';
  let w = Number($('cmpW').value) || Number(STATE.width) || 832;
  let h = Number($('cmpH').value) || Number(STATE.height) || 1216;
  if($('cmpRes').value !== 'custom'){
    const parts = $('cmpRes').value.split('x').map(Number);
    if(parts.length === 2 && parts.every(Number.isFinite)){ w = parts[0]; h = parts[1]; }
  }
  return {
    mode,
    fixed_size: $('cmpFix').checked,
    width: w, height: h,
    same_seed: $('cmpSameSeed').checked,
    seed: Math.max(0, Math.trunc(Number($('cmpSeed').value) || 0)),
    seed_count: Math.max(1, Math.min(4,
      Math.trunc(Number($('cmpSeedCount').value) || 1))),
    limit: Math.max(0, Math.trunc(Number($('cmpLimit').value) || 0)),
    include_refs: $('cmpRefs').checked,
    selection: comparisonSelectionRead()
  };
}
function comparisonStore(opts){
  STATE.ui = STATE.ui || {};
  STATE.ui.comparison = Object.assign({}, opts);
  save();
}
function comparisonApply(saved){
  saved = saved || {};
  const mode = ['styles','characters','both','character_setting','selected'].includes(saved.mode)
    ? saved.mode : 'styles';
  const radio = document.querySelector(`input[name="cmpMode"][value="${mode}"]`);
  if(radio) radio.checked = true;
  const w = Number(saved.width || STATE.width || 832);
  const h = Number(saved.height || STATE.height || 1216);
  const res = `${w}x${h}`;
  $('cmpRes').value = [...$('cmpRes').options].some(o => o.value === res) ? res : 'custom';
  $('cmpW').value = w; $('cmpH').value = h;
  $('cmpFix').checked = saved.fixed_size !== false;
  $('cmpSameSeed').checked = saved.same_seed !== false;
  $('cmpSeed').value = Number(saved.seed) || 0;
  $('cmpSeedCount').value = String(Math.max(1, Math.min(4,
    Math.trunc(Number(saved.seed_count) || 1))));
  $('cmpLimit').value = Number(saved.limit) || 0;
  $('cmpRefs').checked = saved.include_refs === true;
  comparisonApplySelection(saved.selection || {});
  comparisonPaintControls();
}
function comparisonRestore(){
  comparisonApply(((STATE.ui || {}).comparison) || {});
}
function comparisonPaintControls(){
  const mode = (document.querySelector('input[name="cmpMode"]:checked') || {}).value || 'styles';
  const custom = $('cmpRes').value === 'custom';
  $('cmpCustom').classList.toggle('hidden', !custom);
  $('cmpRes').disabled = !$('cmpFix').checked;
  $('cmpW').disabled = !$('cmpFix').checked;
  $('cmpH').disabled = !$('cmpFix').checked;
  $('cmpSelected').classList.toggle('hidden', mode !== 'selected');
  $('cmpCharacterSettingPlan').classList.toggle(
    'hidden', mode !== 'character_setting');
}
function comparisonRunSelected(){
  const folder = ($('cmpRuns') || {}).value || '';
  return CMP_RUNS.find(x => x.folder === folder) || null;
}
async function comparisonRunsLoad(){
  const select = $('cmpRuns'); if(!select) return;
  select.innerHTML = '<option value="">실험 기록을 불러오는 중...</option>';
  try{
    const r = await (await fetch('/api/compare_runs')).json();
    if(!r.ok) throw new Error(r.error || '실험 기록을 읽지 못했습니다.');
    CMP_RUNS = r.runs || [];
    if(!CMP_RUNS.length){
      select.innerHTML = '<option value="">아직 비교 실험이 없습니다.</option>';
      $('cmpRunMsg').textContent = '비교 생성이 시작되면 각 결과 폴더의 기록이 여기에 남습니다.';
      return;
    }
    const statusName = {
      complete:'완료', stopped:'중지', daily_limit:'일일 상한',
      partial:'일부 실패', fatal:'오류', running:'진행 기록'
    };
    select.innerHTML = CMP_RUNS.map((run, i) => {
      const state = statusName[run.status] || run.status || '상태 미상';
      const date = run.updated_at ? ` · ${run.updated_at}` : '';
      return `<option value="${escA(run.folder)}"${i===0?' selected':''}>`
        + `${esc(run.mode_label || run.name)} · ${state} · `
        + `${Number(run.completed||0).toLocaleString()}/${Number(run.total||0).toLocaleString()}장`
        + `${esc(date)}</option>`;
    }).join('');
    $('cmpRunMsg').textContent =
      '중단된 실험은 계획을 불러온 뒤 현재 자료 수·비용을 다시 확인하면 이어집니다.';
  }catch(e){
    CMP_RUNS = [];
    select.innerHTML = '<option value="">실험 기록을 읽지 못했습니다.</option>';
    $('cmpRunMsg').textContent = String(e);
  }
}
async function openComparisonFolder(folder, message='비교 결과를 선별하세요.'){
  if(!folder) return;
  STATE.ui = STATE.ui || {};
  STATE.ui.library_work = 'results';
  setMode('library');
  arrangeStudioWorkspace();
  await expLoad(folder);
  $('expStat').textContent = message;
  $('expGrid').scrollIntoView({behavior:'smooth', block:'start'});
}
async function comparisonPreview(){
  const opts = comparisonRead();
  comparisonStore(opts);
  CMP_PLAN = null;
  $('cmpConfirm').checked = false;
  $('cmpStart').disabled = true;
  $('cmpSummary').textContent = '자료 수와 생성 장수를 계산하는 중입니다.';
  try{
    const r = await (await fetch('/api/compare_preview', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(opts)})).json();
    CMP_PLAN = r;
    $('cmpCounts').textContent = `그림체 ${Number(r.styles||0).toLocaleString()} · 캐릭터 ${Number(r.characters||0).toLocaleString()}`
      + (['character_setting','selected'].includes(opts.mode)
        ? ` · 세팅 ${Number(r.settings||0).toLocaleString()}` : '')
      + (opts.mode === 'selected'
        ? ` · 축 ${Number(r.axes||0).toLocaleString()}` : '');
    if(!r.ok){
      $('cmpSummary').innerHTML = `<span style="color:var(--danger)">${esc((r.errors||[r.error||'계산 실패']).join(' '))}</span>`;
      return;
    }
    let formula = '';
    if(opts.mode === 'styles'){
      formula = `그림체 ${r.styles.toLocaleString()}개 × 현재 캐릭터 묶음 1개`
        + ` (${r.current_slots.toLocaleString()}명 함께)`;
    }else if(opts.mode === 'characters'){
      formula = `현재 그림체 1개 × 캐릭터 ${r.characters.toLocaleString()}개`;
    }else if(opts.mode === 'both'){
      formula = `그림체 ${r.styles.toLocaleString()}개 × 캐릭터 ${r.characters.toLocaleString()}개`;
    }else if(opts.mode === 'character_setting'){
      formula = `캐릭터 ${r.characters.toLocaleString()}개 × 선택 세팅 ${Number(r.settings||0).toLocaleString()}개`
        + ` · 실제 선택 씬·단계·예약 매수`;
    }else{
      const parts = [];
      if(Number(r.styles||0)) parts.push(`그림체 ${Number(r.styles).toLocaleString()}개`);
      if(Number(r.characters||0)) parts.push(`캐릭터 ${Number(r.characters).toLocaleString()}개`);
      if(Number(r.settings||0)) parts.push(`세팅 ${Number(r.settings).toLocaleString()}개`);
      if(Number(r.axes||0)) parts.push(`생성 설정 축 ${Number(r.axes).toLocaleString()}개`);
      formula = parts.join(' × ');
    }
    if(Number(r.seed_count || 1) > 1){
      formula += ` × 시드 ${Number(r.seed_count).toLocaleString()}개`;
    }
    const cap = r.limited ? ` · 전체 ${r.total.toLocaleString()}장 중 앞 ${r.count.toLocaleString()}장` : '';
    let cost = '';
    if(r.subscription_known){
      cost = ` · 현재 구독 기준 예상 ${Number(r.expected_anlas||0).toLocaleString()} Anlas`;
    }else{
      cost = ` · 예상 범위 ${Number(r.opus_anlas||0).toLocaleString()}~${Number(r.paid_anlas_max||0).toLocaleString()} Anlas`
        + ' (구독 확인 전)';
    }
    const free = r.free_eligible === r.count
      ? ' · 전부 Opus 무료 크기·스텝 범위'
      : ` · 무료 조건 범위 ${Number(r.free_eligible||0).toLocaleString()}/${r.count.toLocaleString()}장`;
    const ref = opts.include_refs ? ' · 레퍼런스 포함(추가 과금 가능)' : ' · 레퍼런스 제외';
    $('cmpSummary').innerHTML = `<b>${esc(formula)} = ${r.count.toLocaleString()}장</b>${esc(cap + cost + free + ref)}
      <div class="hint" style="margin-top:4px;">중지하거나 일일 상한에 닿아도 같은 계획으로 다시 누르면 이어집니다.
      그림체 원본 시드는 쓰지 않고 비교 시드 규칙을 적용합니다.</div>`;
    $('cmpConfirmText').textContent = `${r.count.toLocaleString()}번의 순차 API 호출과 저장을 확인했습니다.`;
    $('cmpStart').disabled = !$('cmpConfirm').checked;
  }catch(e){
    $('cmpSummary').textContent = '계산 실패: ' + e;
  }
}
function comparisonSchedule(){
  comparisonPaintControls();
  clearTimeout(CMP_TIMER);
  CMP_TIMER = setTimeout(comparisonPreview, 180);
}
function bindComparison(){
  if(!$('compareCard') || $('compareCard')._bound) return;
  $('compareCard')._bound = true;
  comparisonRestore();
  comparisonCatalogLoad();
  $('cmpPlanAllChars').addEventListener('click', () => {
    const characters = comparisonCharacterChoices();
    const targets = SETTINGS.filter(setting => {
      const state = stState(setting.name);
      return state.use !== false && (state.selected || []).length;
    });
    if(!characters.length){
      $('cmpPlanMsg').textContent = '사용할 캐릭터 자료가 없습니다.';
      return;
    }
    if(!targets.length){
      $('cmpPlanMsg').textContent = '먼저 씬 고르기에서 사용할 세팅과 세트를 켜세요.';
      return;
    }
    targets.forEach(setting => {
      const state = stState(setting.name);
      state.cast_source = 'all_characters';
      state.cast_mode = 'sequence';
    });
    save(); renderSettings(); counts();
    STATE.ui = STATE.ui || {}; STATE.ui.settings_work = 'select';
    arrangeStudioWorkspace(); save();
    $('cmpPlanMsg').textContent =
      `${characters.length}명 × ${targets.length}개 선택 세팅 계획을 적용했습니다. 직접 캐스트 원문은 보존됩니다.`;
  });
  $('cmpPlanManual').addEventListener('click', () => {
    let changed = 0;
    SETTINGS.forEach(setting => {
      const state = stState(setting.name);
      if(state.cast_source === 'all_characters'){
        state.cast_source = 'manual'; changed++;
      }
    });
    save(); renderSettings(); counts();
    $('cmpPlanMsg').textContent =
      changed ? `${changed}개 세팅을 기존 직접 캐스트로 돌렸습니다.` : '전 캐릭터 계획이 적용된 세팅이 없습니다.';
  });
  document.querySelectorAll('input[name="cmpMode"]').forEach(x => x.addEventListener('change', comparisonSchedule));
  ['cmpRes','cmpFix','cmpSameSeed','cmpSeed','cmpSeedCount',
   'cmpLimit','cmpRefs','cmpW','cmpH',
   'cmpSelectStyles','cmpSelectCharacters','cmpSelectSettings',
   'cmpAxisCfg','cmpAxisSteps','cmpAxisSampler'].forEach(id => {
    const el = $(id); if(!el) return;
    el.addEventListener('change', comparisonSchedule);
    if(['cmpSeed','cmpLimit','cmpW','cmpH','cmpAxisCfg',
        'cmpAxisSteps','cmpAxisSampler'].includes(id)){
      el.addEventListener('input', comparisonSchedule);
    }
  });
  $('cmpConfirm').addEventListener('change', () => {
    $('cmpStart').disabled = !(CMP_PLAN && CMP_PLAN.ok && CMP_PLAN.count && $('cmpConfirm').checked);
  });
  $('cmpRunRefresh').addEventListener('click', comparisonRunsLoad);
  $('cmpRunOpen').addEventListener('click', async () => {
    const run = comparisonRunSelected();
    if(!run){ $('cmpRunMsg').textContent = '열 비교 실험을 선택해주세요.'; return; }
    await openComparisonFolder(
      run.folder,
      `${run.mode_label || run.name} · ${Number(run.completed||0).toLocaleString()}/${Number(run.total||0).toLocaleString()}장`,
    );
  });
  $('cmpRunLoad').addEventListener('click', async () => {
    const run = comparisonRunSelected();
    if(!run){ $('cmpRunMsg').textContent = '불러올 비교 실험을 선택해주세요.'; return; }
    const r = await (await fetch('/api/compare_activate', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({folder:run.folder})})).json();
    if(!r.ok){ $('cmpRunMsg').textContent = r.error || '계획을 불러오지 못했습니다.'; return; }
    comparisonApply(r.options || {});
    $('cmpRunMsg').textContent = r.resumable
      ? `중단 지점 ${Number(r.completed||0).toLocaleString()}/${Number(r.total||0).toLocaleString()}장을 활성화했습니다. 아래 장수와 비용을 다시 확인해주세요.`
      : '완료된 실험의 조건을 새 계획으로 불러왔습니다. 기존 결과는 덮어쓰지 않습니다.';
    comparisonSchedule();
  });
  $('cmpOpenResults').addEventListener('click', async () => {
    const r = await (await fetch('/api/compare_progress')).json();
    if(!r.ok){
      $('cmpSummary').textContent = r.error || '아직 선별할 비교 결과가 없습니다.';
      return;
    }
    const done = Number(r.completed || 0).toLocaleString();
    const total = Number(r.total || 0).toLocaleString();
    await openComparisonFolder(
      r.folder, `최근 비교 결과 ${done}/${total}장 · 선별을 시작하세요.`);
  });
  $('cmpStart').addEventListener('click', async () => {
    if(!(CMP_PLAN && CMP_PLAN.ok && $('cmpConfirm').checked)) return;
    const opts = comparisonRead();
    $('cmpStart').disabled = true;
    const r = await (await fetch('/api/compare_run', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Object.assign(opts, {
        confirmed:true, confirmed_count:CMP_PLAN.count
      }))})).json();
    if(!r.ok){
      alert(r.error || '비교 생성을 시작하지 못했습니다.');
      comparisonSchedule();
      return;
    }
    setMode('preview');
  });
  comparisonRunsLoad();
  comparisonPreview();
}

function bindStudioSettingsNav(){
  const nav = $('studioSettingsNav');
  if(!nav || nav._bound) return;
  nav._bound = true;
  nav.querySelectorAll('[data-settings-work]').forEach(button => {
    button.addEventListener('click', () => {
      const next = button.dataset.settingsWork;
      if(!['select','quick','build','compare'].includes(next)) return;
      STATE.ui = STATE.ui || {};
      STATE.ui.settings_work = next;
      arrangeStudioWorkspace();
      save();
    });
  });
}

/* ── 세팅 ── */
function stState(name){
  STATE.setting_state = STATE.setting_state || {};
  const s = STATE.setting_state[name] = STATE.setting_state[name] || {use:true, selected:[], opts:{}, cast:[]};
  s.opts = s.opts || {}; s.selected = s.selected || []; s.cast = s.cast || [];
  return s;
}
function castPresets(){
  STATE.cast_presets = Array.isArray(STATE.cast_presets) ? STATE.cast_presets : [];
  return STATE.cast_presets;
}
function castMode(state){
  return state && state.cast_mode === 'together' ? 'together' : 'sequence';
}
function castPositionMode(state){
  const mode = String((state || {}).position_mode || '').toLowerCase();
  if(POSITION_MODES.has(mode)) return mode;
  return ((state || {}).cast || []).some(member =>
    member && member.position && member.position.x != null)
    ? 'coordinate' : 'ai';
}
function castPresetId(){
  const tail = (globalThis.crypto && crypto.randomUUID)
    ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `cast-${tail}`;
}
function castPresetOptions(){
  return castPresets().map(p => `<option value="${escA(p.id)}">${esc(p.name)} · ${(p.members||[]).length}명</option>`).join('');
}
/* 어느 세팅이 펼쳐져 있었는지 기억한다 — 단계 칩 하나 눌렀다고 다시 접히면
   자리를 잃는다 (대표 그림도 숨은 채라 안 뜬다). */
const SET_OPEN = new Set();
function renderSettings(){
  const host = $('setList');
  host.querySelectorAll('[data-sb]').forEach(el => {
    if(!el.classList.contains('hidden')) SET_OPEN.add(el.dataset.sb);
    else SET_OPEN.delete(el.dataset.sb);
  });
  host.innerHTML = '';
  $('setCount').textContent = `${SETTINGS.length}개`;
  if(!SETTINGS.length){
    host.innerHTML = `<div class="row" style="padding:18px;text-align:center;">
      <b>아직 넣은 세팅이 없습니다.</b>
      <p class="hint" style="margin:7px 0 10px;">본체와 자료는 분리되어 있습니다.
      기본자료팩을 자료 탭에 넣거나, 위의 새 세팅으로 직접 만드세요.</p>
      <button id="setGoData">기본자료팩 넣으러 가기</button></div>`;
    $('setGoData').addEventListener('click', () => {
      STATE.ui = STATE.ui || {};
      STATE.ui.library_work = 'input';
      setMode('library');
    });
  }
  SETTINGS.forEach(st => {
    const s = stState(st.name);
    const tot = st.groups.reduce((a,g)=>a+g.ids.length,0);
    const sel = new Set(s.selected);
    const sec = document.createElement('div');
    sec.className = 'sec';
    const mb = {'남녀':'👫 남녀','백합':'👭 여×여','단독':'👤 단독'}[st.mode] || st.mode;
    sec.innerHTML = `<div class="sec-head" data-sh="${escA(st.name)}">
        <label class="sw"><input type="checkbox" data-suse="${escA(st.name)}" ${s.use===false?'':'checked'}><span class="sl"></span></label>
        <span class="nm">${esc(st.name)}</span><span class="badge">${mb}</span>
        <span class="sub">${st.groups.length}세트 · ${tot}장</span>
        <span class="cnt" data-scnt="${escA(st.name)}"></span></div>
      <div class="sec-body${SET_OPEN.has(st.name) ? '' : ' hidden'}" data-sb="${escA(st.name)}"></div>`;
    const b = sec.querySelector('.sec-body');

    b.insertAdjacentHTML('beforeend', `<div class="field"><label>전용 캐스트 (비우면 왼쪽 [캐릭터] 사용)</label>
      <div class="filterbar">
        <span class="hint">출연 자료</span>
        <select data-castsource="${escA(st.name)}" style="width:auto;">
          <option value="manual"${s.cast_source==='all_characters'?'':' selected'}>직접 캐스트</option>
          <option value="all_characters"${s.cast_source==='all_characters'?' selected':''}>캐릭터 자료 전체</option>
        </select>
        <span class="hint">실행 방식</span>
        <select data-castmode="${escA(st.name)}" style="width:auto;">
          <option value="sequence"${castMode(s)==='sequence'?' selected':''}>각자 순회 — 한 명씩 전체 씬</option>
          <option value="together"${castMode(s)==='together'?' selected':''}>함께 등장 — 한 장에 여러 명</option>
        </select>
        <span class="hint">${castMode(s)==='together'
          ? '첫째=주인공 · 둘째=상대역 · 이후=추가 인물'
          : (s.cast_source==='all_characters'
            ? `캐릭터 자료 ${comparisonCharacterChoices().length}명 × 선택 씬`
            : '인원수만큼 생성 벌이 늘어납니다')}</span>
      </div>
      <div data-cast="${escA(st.name)}"></div>
      <div class="bar" style="margin:5px 0 0;"><button data-castadd="${escA(st.name)}">+ 직접 입력</button>
      <select data-castlib="${escA(st.name)}" style="flex:1;"><option value="">+ 라이브러리에서...</option></select></div>
      <div class="bar" style="margin:5px 0 0;">
        <select data-castpreset="${escA(st.name)}" style="flex:1;"><option value="">저장한 캐스트 조합...</option>${castPresetOptions()}</select>
        <button data-castload="${escA(st.name)}">불러오기</button>
        <button data-castsave="${escA(st.name)}">현재 조합 저장</button>
        <button class="danger" data-castpresetdel="${escA(st.name)}">삭제</button>
      </div>
      <div class="hint" data-castmsg="${escA(st.name)}">캐릭터 조합만 저장하며 세팅·장면·생성 설정은 바꾸지 않습니다.</div></div>`);

    const role = st.role || {};
    if(st.mode === '남녀' || st.mode === '백합'){
      const t = st.mode === '남녀' ? '상대역(남자)' : '상대역(파트너)';
      b.insertAdjacentHTML('beforeend', `<div class="field"><label>${t} — 이 세팅 파일에 저장됩니다</label>
        <textarea data-role="${escA(st.name)}" data-rf="외형" style="min-height:44px;">${esc(role['외형']||'')}</textarea></div>
        <div class="grid3">
          ${st.mode==='백합' ? `<div class="field"><label>상대역 착의</label><input type="text" data-role="${escA(st.name)}" data-rf="착의" value="${escA(role['착의']||'')}"></div>` : ''}
          <div class="field"><label>상대역 네거티브</label><input type="text" data-role="${escA(st.name)}" data-rf="네거티브" value="${escA(role['네거티브']||'')}"></div>
          ${st.mode==='남녀' ? `<div class="field"><label>상대역 의상</label><input type="text" data-role="${escA(st.name)}" data-rf="의상" value="${escA(role['의상']||'')}"></div>` : ''}
        </div>`);
    }

    const oks = Object.keys(st.options||{}).filter(k=>!k.startsWith('_'));
    const extra = st.mode === '남녀' ? ['남자옷'] : (st.mode === '백합' ? ['옷진행'] : []);
    if(oks.length || extra.length){
      let g = '<div class="grid3">';
      extra.forEach(k => {
        const vals = k === '남자옷' ? ['나체','착의','탈의진행'] : ['진행','나체'];
        g += `<div class="field"><label>${k}</label><select data-sopt="${escA(st.name)}" data-on="${k}">` +
          vals.map(v => `<option${(s.opts[k]||vals[0])===v?' selected':''}>${v}</option>`).join('') + '</select></div>';
      });
      oks.forEach(ok => {
        const names = Object.keys(st.options[ok]||{});
        g += `<div class="field"><label>${esc(ok)}</label><select data-sopt="${escA(st.name)}" data-on="${escA(ok)}">
          <option value="">없음</option>` + names.map(n => `<option${s.opts[ok]===n?' selected':''}>${esc(n)}</option>`).join('') + '</select></div>';
      });
      b.insertAdjacentHTML('beforeend', g + '</div>' +
        (oks.length ? `<div class="bar"><button data-optedit="${escA(st.name)}">옵션 항목 편집 (보기·수정·추가·삭제)</button></div>` : ''));
    }

    const hasMood = st.groups.some(g => g.mood);
    /* 단계 선택 — 세트를 가로로 자른다 ("전 체위의 사정 컷만").
       세트마다 단계 수가 다를 수 있으니 가장 긴 세트를 기준으로 칩을 만든다. */
    const maxStage = st.groups.reduce((a,g) => Math.max(a, g.ids.length), 1);
    const stg = new Set((s.stages || []).map(Number));
    const stageRow = maxStage > 1 ? `<div class="filterbar" style="margin-top:6px;">
        <span class="hint" style="white-space:nowrap;">단계</span>
        ${Array.from({length: maxStage}, (_, i) => `<span class="chip${stg.has(i+1)?' on':''}"
           data-sstage="${escA(st.name)}" data-st="${i+1}">${i+1}</span>`).join('')}
        <span class="hint" data-sstagemsg="${escA(st.name)}">${stg.size
          ? `${[...stg].sort((a,b)=>a-b).join('·')}번 컷만 (세트당 ${stg.size}장)`
          : '전 단계'}</span>
        ${stg.size ? `<button data-sstageall="${escA(st.name)}">전 단계로</button>` : ''}
      </div>` : '';
    b.insertAdjacentHTML('beforeend', `<div class="bar" style="margin-top:6px;">
      <button data-sall="${escA(st.name)}">전체 선택</button><button data-snone="${escA(st.name)}">전체 해제</button>
      ${hasMood ? `<button data-smood="${escA(st.name)}|가벼움">가벼움만</button><button data-smood="${escA(st.name)}|진함">진함만</button>` : ''}</div>
      ${stageRow}
      <div class="filterbar" style="margin-top:6px;">
        <input type="text" data-sfind="${escA(st.name)}" placeholder="🔍 세트 이름으로 찾기 (예: 사우스폴, A01)">
        <label class="hint"><input type="checkbox" data-sonly="${escA(st.name)}"> 켠 것만</label>
        <span class="n" data-sfound="${escA(st.name)}"></span>
      </div>`);

    const byCat = {};
    st.groups.forEach(g => (byCat[g.cat||''] = byCat[g.cat||'']||[]).push(g));
    Object.keys(byCat).sort().forEach(cat => {
      if(cat) b.insertAdjacentHTML('beforeend', `<div class="tag" style="margin:9px 0 3px;">${esc(cat)} · ${esc(((st.category_meta||{})[cat]||{}).name||'')}</div>`);
      const gr = document.createElement('div'); gr.className = 'items';
      byCat[cat].forEach(g => {
        const it = document.createElement('label'); it.className = 'item';
        const rep = (s.reserve || {})[g.id] || 1;
        it.dataset.name = (g.label || '').toLowerCase();
        it.dataset.on = sel.has(g.id) ? '1' : '0';
        it.innerHTML = `<input type="checkbox" data-ssel="${escA(st.name)}" data-id="${g.id}" ${sel.has(g.id)?'checked':''}>
          <span>${esc(g.label)}${g.mood==='진함'?' 🔥':''}${g.ids.length>1?` (${g.ids.length})`:''}</span>
          <input type="number" class="rep" data-srep="${escA(st.name)}" data-id="${g.id}"
            value="${rep}" min="1" max="20" title="이 세트를 몇 벌 뽑을지 (기본 1벌)"
            style="width:34px;padding:2px 3px;font-size:var(--fs-2xs);text-align:center;">
          <span class="ed" data-sedit="${escA(st.name)}" data-ids="${g.ids.join(',')}">✎</span>
          <span class="ed" data-sdup="${escA(st.name)}" data-id="${g.id}"
            title="이 세트를 복제 (씬을 새 번호로 복사)">⧉</span>`;
        gr.appendChild(it);
      });
      b.appendChild(gr);
    });
    host.appendChild(sec);
  });
  bindSettings();
  /* 목록을 다시 그리면 붙여 둔 대표 그림이 날아간다. 켜져 있으면 다시 붙인다. */
  if($('setThumbs') && $('setThumbs').checked) loadSetThumbs();
}

function bindSettings(){
  const h = $('setList');
  h.querySelectorAll('[data-sh]').forEach(x => x.addEventListener('click', e => {
    if(e.target.tagName === 'INPUT' || e.target.closest('.sw')) return;
    const bd = h.querySelector(`[data-sb="${CSS.escape(x.dataset.sh)}"]`);
    bd.classList.toggle('hidden');
    bd.classList.contains('hidden') ? SET_OPEN.delete(x.dataset.sh) : SET_OPEN.add(x.dataset.sh);
    if(!bd.classList.contains('hidden') && $('setThumbs') && $('setThumbs').checked) loadSetThumbs();
  }));
  h.querySelectorAll('[data-suse]').forEach(x => x.addEventListener('change', () => {
    stState(x.dataset.suse).use = x.checked; tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-castmode]').forEach(select => select.addEventListener('change', () => {
    stState(select.dataset.castmode).cast_mode =
      select.value === 'together' ? 'together' : 'sequence';
    save(); renderSettings(); tokens(); counts();
  }));
  h.querySelectorAll('[data-castsource]').forEach(select => select.addEventListener('change', () => {
    stState(select.dataset.castsource).cast_source =
      select.value === 'all_characters' ? 'all_characters' : 'manual';
    save(); renderSettings(); tokens(); counts();
  }));
  h.querySelectorAll('[data-ssel]').forEach(x => x.addEventListener('change', () => {
    const s = stState(x.dataset.ssel), id = +x.dataset.id;
    s.selected = s.selected.filter(v => v !== id);
    if(x.checked) s.selected.push(id);
    tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-sall]').forEach(b => b.addEventListener('click', () => {
    const st = SETTINGS.find(s => s.name === b.dataset.sall);
    stState(st.name).selected = st.groups.map(g => g.id);
    h.querySelectorAll(`[data-ssel="${CSS.escape(st.name)}"]`).forEach(c => c.checked = true);
    tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-snone]').forEach(b => b.addEventListener('click', () => {
    stState(b.dataset.snone).selected = [];
    h.querySelectorAll(`[data-ssel="${CSS.escape(b.dataset.snone)}"]`).forEach(c => c.checked = false);
    tokens(); save(); counts();
  }));
  h.querySelectorAll('[data-smood]').forEach(b => b.addEventListener('click', () => {
    const [n, m] = b.dataset.smood.split('|');
    const st = SETTINGS.find(s => s.name === n);
    const ids = st.groups.filter(g => g.mood === m).map(g => g.id);
    stState(n).selected = ids;
    h.querySelectorAll(`[data-ssel="${CSS.escape(n)}"]`).forEach(c => c.checked = ids.includes(+c.dataset.id));
    tokens(); save(); counts();
  }));
  /* 세트 복제 — 씬을 새 번호로 복사해 세팅 파일에 넣는다 */
  h.querySelectorAll('[data-sdup]').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation(); e.preventDefault();
    const name = b.dataset.sdup;
    const r = await (await fetch('/api/setting_dup', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, id: +b.dataset.id})})).json();
    if(!r.ok){ $('setMsg').textContent = r.error || '복제 실패'; return; }
    $('setMsg').textContent = `세트 복제 ✓ (씬 ${r.count}개 · ${r.new_id}번부터)`;
    await reloadConfig();      // 세팅 파일이 바뀌었으니 목록을 다시 받는다
  }));
  /* 단계 칩 — 켜진 것이 하나도 없으면 '전 단계' 로 돌아간다 */
  h.querySelectorAll('[data-sstage]').forEach(c => c.addEventListener('click', () => {
    const s = stState(c.dataset.sstage), n = +c.dataset.st;
    const cur = new Set((s.stages || []).map(Number));
    cur.has(n) ? cur.delete(n) : cur.add(n);
    s.stages = [...cur].sort((a, b) => a - b);
    save(); renderSettings(); tokens(); counts();
  }));
  h.querySelectorAll('[data-sstageall]').forEach(b => b.addEventListener('click', () => {
    stState(b.dataset.sstageall).stages = [];
    save(); renderSettings(); tokens(); counts();
  }));
  h.querySelectorAll('[data-sopt]').forEach(x => x.addEventListener('change', () => {
    stState(x.dataset.sopt).opts[x.dataset.on] = x.value; save();
  }));
  h.querySelectorAll('[data-role]').forEach(x => x.addEventListener('input', () => {
    const n = x.dataset.role;
    clearTimeout(window['rt_'+n]);
    window['rt_'+n] = setTimeout(async () => {
      const role = {};
      h.querySelectorAll(`[data-role="${CSS.escape(n)}"]`).forEach(y => role[y.dataset.rf] = y.value);
      await fetch('/api/role_save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({setting:n, role})});
    }, 600);
  }));
  h.querySelectorAll('[data-sedit]').forEach(b => b.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation();
    openScene(b.dataset.sedit, b.dataset.ids.split(',').map(Number));
  }));
  /* 세트 이름 찾기 — 565개를 스크롤로 훑지 않아도 되게 */
  h.querySelectorAll('[data-sfind]').forEach(inp => {
    const name = inp.dataset.sfind;
    const apply = () => {
      const q = (inp.value || '').trim().toLowerCase();
      const onlyOn = (h.querySelector(`[data-sonly="${CSS.escape(name)}"]`) || {}).checked;
      const body = h.querySelector(`[data-sb="${CSS.escape(name)}"]`);
      let shown = 0, total = 0;
      body.querySelectorAll('.items > .item').forEach(it => {
        total++;
        const okQ = !q || (it.dataset.name || '').includes(q);
        const okOn = !onlyOn || it.dataset.on === '1';
        const ok = okQ && okOn;
        it.style.display = ok ? '' : 'none';
        if(ok) shown++;
      });
      // 결과가 없는 계열 헤더는 숨긴다
      body.querySelectorAll('.items').forEach(gr => {
        const any = [...gr.children].some(c => c.style.display !== 'none');
        gr.style.display = any ? '' : 'none';
        const head = gr.previousElementSibling;
        if(head && head.classList.contains('tag')) head.style.display = any ? '' : 'none';
      });
      const f = h.querySelector(`[data-sfound="${CSS.escape(name)}"]`);
      if(f) f.textContent = (q || onlyOn) ? `${shown} / ${total}개` : '';
    };
    inp.addEventListener('input', apply);
    const only = h.querySelector(`[data-sonly="${CSS.escape(name)}"]`);
    if(only) only.addEventListener('change', apply);
  });
  /* 세트별 예약 매수 */
  h.querySelectorAll('[data-srep]').forEach(inp => {
    inp.addEventListener('click', e => e.preventDefault());   // 라벨 클릭으로 체크 토글 방지
    inp.addEventListener('input', () => {
      const st = stState(inp.dataset.srep);
      st.reserve = st.reserve || {};
      const v = Math.max(1, Math.min(20, Number(inp.value) || 1));
      if(v === 1) delete st.reserve[inp.dataset.id]; else st.reserve[inp.dataset.id] = v;
      save(); counts();
    });
  });
  h.querySelectorAll('[data-optedit]').forEach(b => b.addEventListener('click', () => openOpts(b.dataset.optedit)));
  h.querySelectorAll('[data-cast]').forEach(el => renderCast(el.dataset.cast));
  h.querySelectorAll('[data-castadd]').forEach(b => b.addEventListener('click', () => {
    stState(b.dataset.castadd).cast.push({name:'', prompt:'', outfit:'', negative:''});
    renderCast(b.dataset.castadd); tokens(); save();
  }));
  h.querySelectorAll('[data-castlib]').forEach(sel => {
    (STATE.characters||[]).forEach(c => {
      const o = document.createElement('option'); o.value = c.id;
      o.textContent = (c.name || '(무명)') + characterVariantLabel(c);
      sel.appendChild(o);
    });
    sel.addEventListener('change', () => {
      const c = (STATE.characters||[]).find(x => x.id === sel.value);
      if(c){ stState(sel.dataset.castlib).cast.push(characterBundle(c, false));
        renderCast(sel.dataset.castlib); tokens(); save(); }
      sel.value = '';
    });
  });
  h.querySelectorAll('[data-castsave]').forEach(b => b.addEventListener('click', () => {
    const setting = b.dataset.castsave;
    const members = stState(setting).cast;
    const msg = h.querySelector(`[data-castmsg="${CSS.escape(setting)}"]`);
    if(!members.length){ msg.textContent = '저장할 캐릭터가 없습니다.'; return; }
    const entered = prompt('캐스트 조합 이름:');
    const name = (entered || '').trim();
    if(!name) return;
    const presets = castPresets();
    const same = presets.find(p => (p.name || '').trim().toLowerCase() === name.toLowerCase());
    if(same && !confirm(`"${name}" 조합을 현재 내용으로 바꿀까요?`)) return;
    const record = {
      id: same ? same.id : castPresetId(),
      name,
      mode: castMode(stState(setting)),
      position_mode: castPositionMode(stState(setting)),
      members: JSON.parse(JSON.stringify(members)),
    };
    if(same) presets[presets.indexOf(same)] = record; else presets.push(record);
    save(); renderSettings();
    const next = h.querySelector(`[data-castpreset="${CSS.escape(setting)}"]`);
    if(next) next.value = record.id;
    const nextMsg = h.querySelector(`[data-castmsg="${CSS.escape(setting)}"]`);
    if(nextMsg) nextMsg.textContent = `"${name}" 조합을 저장했습니다.`;
  }));
  h.querySelectorAll('[data-castload]').forEach(b => b.addEventListener('click', () => {
    const setting = b.dataset.castload;
    const select = h.querySelector(`[data-castpreset="${CSS.escape(setting)}"]`);
    const preset = castPresets().find(p => p.id === (select || {}).value);
    const msg = h.querySelector(`[data-castmsg="${CSS.escape(setting)}"]`);
    if(!preset){ msg.textContent = '불러올 조합을 먼저 고르세요.'; return; }
    const state = stState(setting);
    if(state.cast.length && !confirm('현재 전용 캐스트를 고른 조합으로 바꿀까요?')) return;
    state.cast = JSON.parse(JSON.stringify(preset.members || []));
    state.cast_mode = preset.mode === 'together' ? 'together' : 'sequence';
    state.position_mode = POSITION_MODES.has(preset.position_mode)
      ? preset.position_mode : castPositionMode(state);
    renderCast(setting); tokens(); save();
    msg.textContent = `"${preset.name}" ${state.cast.length}명을 불러왔습니다.`;
  }));
  h.querySelectorAll('[data-castpresetdel]').forEach(b => b.addEventListener('click', () => {
    const setting = b.dataset.castpresetdel;
    const select = h.querySelector(`[data-castpreset="${CSS.escape(setting)}"]`);
    const preset = castPresets().find(p => p.id === (select || {}).value);
    const msg = h.querySelector(`[data-castmsg="${CSS.escape(setting)}"]`);
    if(!preset){ msg.textContent = '삭제할 조합을 먼저 고르세요.'; return; }
    if(!confirm(`"${preset.name}" 저장 조합을 삭제할까요? 현재 세팅의 캐스트는 유지됩니다.`)) return;
    STATE.cast_presets = castPresets().filter(p => p.id !== preset.id);
    save(); renderSettings();
    const nextMsg = h.querySelector(`[data-castmsg="${CSS.escape(setting)}"]`);
    if(nextMsg) nextMsg.textContent = `"${preset.name}" 저장 조합만 삭제했습니다.`;
  }));
  counts();
}
function counts(){
  let selectedSettingScenes = 0;
  SETTINGS.forEach(st => {
    const s = stState(st.name); const sel = new Set(s.selected);
    const rep = s.reserve || {};
    const stg = new Set((s.stages || []).map(Number));
    let im = 0;
    st.groups.forEach(g => {
      if(!sel.has(g.id)) return;
      const cuts = stg.size ? g.ids.filter((_, i) => stg.has(i + 1)).length : g.ids.length;
      im += cuts * (rep[g.id] || 1);
    });
    if(castMode(s) === 'sequence'){
      const castCount = s.cast_source === 'all_characters'
        ? comparisonCharacterChoices().length : (s.cast || []).filter(c =>
          [c.prompt,c.outfit].some(value => String(value || '').trim())).length;
      if(castCount) im *= castCount;
    }
    const el = document.querySelector(`[data-scnt="${CSS.escape(st.name)}"]`);
    if(el) el.textContent = s.selected.length ? `${s.selected.length}세트 · ${im}장` : '';
    if(s.use !== false && s.selected.length) selectedSettingScenes += im;
  });
  const batchRow = $('settingBatchRow');
  if(batchRow) batchRow.classList.toggle('hidden', selectedSettingScenes < 1);
  if($('batchBtn')) $('batchBtn').textContent = selectedSettingScenes > 0
    ? `🎬 선택 세팅 ${selectedSettingScenes.toLocaleString()}장 생성`
    : '🎬 선택 세팅 일괄 생성';
}
function castResourceChoices(memberIndex, field, items, selected, title){
  const chosen = new Set(Array.isArray(selected) ? selected.map(String) : []);
  const available = (items || []).filter(item => item && item.id);
  if(!available.length){
    return `<div class="cast-resource"><b>${title}</b><span class="hint">먼저 생성 화면의 Vibe·Reference에 자료를 넣으세요.</span></div>`;
  }
  return `<div class="cast-resource"><b>${title}</b><div class="cast-resource-list">` +
    available.map(item => `<label class="cast-resource-chip">
      <input type="checkbox" data-cresource="${field}" data-ci="${memberIndex}"
        value="${escA(item.id)}"${chosen.has(String(item.id)) ? ' checked' : ''}>
      <span>${esc(item.name || item.id)}</span></label>`).join('') +
    `</div></div>`;
}
function renderCast(name, openMember=-1){
  const host = document.querySelector(`[data-cast="${CSS.escape(name)}"]`);
  if(!host) return;
  const s = stState(name);
  const mode = castPositionMode(s);
  host.innerHTML = `<div class="cast-position-mode">
    <span class="hint">캐릭터 위치</span>
    <div class="position-mode-picker" role="radiogroup" aria-label="세팅 캐스트 위치 방식">
      ${[['ai','AI 자동'],['grid','위치판'],['coordinate','좌표']].map(([value,label]) =>
        `<button type="button" data-cast-posmode="${value}" role="radio"
          aria-checked="${mode===value?'true':'false'}" class="${mode===value?'on':''}">${label}</button>`).join('')}
    </div>
    <button type="button" data-cast-spread>추천 배치</button>
    <span class="hint">${mode === 'ai' ? 'NAI가 배치 · 저장된 수동 값은 유지' : '이 세팅에서 함께 출연할 때 적용'}</span>
  </div>`;
  s.cast.forEach((c,i) => {
    const position = c.position && typeof c.position === 'object' ? c.position : {};
    const px = Number.isFinite(Number(position.x)) ? Number(position.x) : 0.5;
    const py = Number.isFinite(Number(position.y)) ? Number(position.y) : 0.5;
    const advancedOpen = i === openMember;
    /* 닫힌 고급 영역이나 AI/좌표 모드에서는 25칸 DOM을 만들지 않는다. */
    const board = mode === 'grid' && advancedOpen ? POS_STEPS.map(y => POS_STEPS.map(x =>
      `<button type="button" class="cast-poscell${Math.abs(px-x)<.01&&Math.abs(py-y)<.01?' on':''}"
        data-cgrid="${i}" data-x="${x}" data-y="${y}" title="x ${x} · y ${y}"
        aria-label="${escA(c.name || `캐릭터 ${i+1}`)} 위치 x ${x}, y ${y}"
        aria-pressed="${Math.abs(px-x)<.01&&Math.abs(py-y)<.01?'true':'false'}"
        tabindex="${Math.abs(px-x)<.01&&Math.abs(py-y)<.01?'0':'-1'}"></button>`).join('')).join('') : '';
    const el = document.createElement('div'); el.className = 'slot';
    el.innerHTML = `<div class="r1"><input type="text" data-cf="name" data-ci="${i}" placeholder="이름" value="${escA(c.name)}">
      <button class="danger" data-cdel="${i}">✕</button></div>
      <textarea data-cf="prompt" data-ci="${i}" placeholder="외형·캐릭터 원문">${esc(c.prompt)}</textarea>
      <input type="text" data-cf="outfit" data-ci="${i}" placeholder="착의·예술적 변형" value="${escA(c.outfit||'')}">
      <input type="text" data-cf="negative" data-ci="${i}" placeholder="전용 네거티브" value="${escA(c.negative)}">
      ${(c.variants||[]).length ? `<label class="field"><span>저장한 이미지 variation</span>
        <select data-cast-variation="${i}"><option value="">기본 원문</option>${(c.variants||[]).map(v =>
          `<option value="${escA(v.id||'')}"${String(c.selected_variant_id||'')===String(v.id||'')?' selected':''}>${esc(v.name||'이름 없는 variation')}</option>`
        ).join('')}</select></label>` : ''}
      <details class="cast-advanced" data-cast-advanced="${i}"${advancedOpen?' open':''}>
        <summary>위치 · Vibe · Reference</summary>
        <div class="cast-position">
          <span class="hint${mode==='ai'?'':' hidden'}" data-cast-posai>AI가 배치합니다.</span>
          <div class="cast-posgrid${mode==='grid'?'':' hidden'}" data-cast-posgrid>${board}</div>
          <span class="cast-poscoords${mode==='coordinate'?'':' hidden'}" data-cast-poscoord>
          <label>좌표 X
            <input type="number" data-cpos="x" data-ci="${i}" min="0" max="1" step="0.01"
              value="${escA(px)}">
          </label>
          <label>좌표 Y
            <input type="number" data-cpos="y" data-ci="${i}" min="0" max="1" step="0.01"
              value="${escA(py)}">
          </label>
          </span>
        </div>
        ${castResourceChoices(i, 'reference_ids', STATE.char_refs, c.reference_ids, '캐릭터 Reference')}
        ${castResourceChoices(i, 'vibe_ids', STATE.vibes, c.vibe_ids, 'Vibe')}
      </details>`;
    host.appendChild(el);
  });
  host.querySelectorAll('[data-cast-advanced]').forEach(details =>
    details.addEventListener('toggle', () => {
      if(details.open && mode === 'grid'
          && !details.querySelector('[data-cgrid]')){
        const memberIndex = Number(details.dataset.castAdvanced);
        renderCast(name, memberIndex);
        requestAnimationFrame(() => {
          const next = host.querySelector(
            `[data-cast-advanced="${memberIndex}"] summary`);
          if(next) next.focus();
        });
      }
    }));
  host.querySelectorAll('[data-cast-posmode]').forEach(button =>
    button.addEventListener('click', () => {
      const next = button.dataset.castPosmode;
      s.position_mode = next;
      if(next !== 'ai'){
        const recommended = spreadCenters(Math.max(1, s.cast.length));
        s.cast.forEach((member, index) => {
          if(!(member.position && member.position.x != null && member.position.y != null)){
            member.position = Object.assign({}, recommended[index] || {x:0.5,y:0.5});
          }
        });
      }
      renderCast(name); save();
    }));
  host.querySelectorAll('[data-cast-posmode]').forEach(button => {
    button.tabIndex = button.getAttribute('aria-checked') === 'true' ? 0 : -1;
    button.addEventListener('keydown', event => {
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...host.querySelectorAll('[data-cast-posmode]')];
      const delta = ['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1;
      const nextMode = buttons[
        (buttons.indexOf(button) + delta + buttons.length) % buttons.length
      ].dataset.castPosmode;
      buttons.find(item => item.dataset.castPosmode === nextMode).click();
      requestAnimationFrame(() => {
        const next = host.querySelector(`[data-cast-posmode="${nextMode}"]`);
        if(next) next.focus();
      });
    });
  });
  const spreadButton = host.querySelector('[data-cast-spread]');
  if(spreadButton) spreadButton.addEventListener('click', () => {
    const recommended = spreadCenters(Math.max(1, s.cast.length));
    s.cast.forEach((member, index) =>
      member.position = Object.assign({}, recommended[index] || {x:0.5,y:0.5}));
    s.position_mode = 'grid';
    renderCast(name); save();
  });
  host.querySelectorAll('[data-cgrid]').forEach(button => {
    button.addEventListener('click', () => {
      const member = s.cast[+button.dataset.cgrid];
      member.position = {x:Number(button.dataset.x), y:Number(button.dataset.y)};
      s.position_mode = 'grid';
      renderCast(name, +button.dataset.cgrid); save();
    });
    button.addEventListener('keydown', event => {
      const moves = {
        ArrowLeft:[-1,0], ArrowRight:[1,0],
        ArrowUp:[0,-1], ArrowDown:[0,1],
      };
      const move = moves[event.key];
      if(!move) return;
      event.preventDefault();
      const memberIndex = +button.dataset.cgrid;
      const x = Number(button.dataset.x), y = Number(button.dataset.y);
      const column = Math.max(0, Math.min(
        POS_STEPS.length - 1, POS_STEPS.indexOf(x) + move[0]));
      const row = Math.max(0, Math.min(
        POS_STEPS.length - 1, POS_STEPS.indexOf(y) + move[1]));
      s.cast[memberIndex].position = {
        x: POS_STEPS[column], y: POS_STEPS[row],
      };
      s.position_mode = 'grid';
      renderCast(name, memberIndex); save();
      requestAnimationFrame(() => {
        const next = host.querySelector(
          `[data-cgrid="${memberIndex}"][data-x="${POS_STEPS[column]}"]`
          + `[data-y="${POS_STEPS[row]}"]`);
        if(next) next.focus();
      });
    });
  });
  host.querySelectorAll('[data-cf]').forEach(el => el.addEventListener('input', () => {
    s.cast[+el.dataset.ci][el.dataset.cf] = el.value; tokens(); save();
  }));
  host.querySelectorAll('[data-cast-variation]').forEach(el => el.addEventListener('change', () => {
    s.cast[+el.dataset.castVariation].selected_variant_id = el.value;
    tokens(); save();
  }));
  host.querySelectorAll('[data-cpos]').forEach(el => el.addEventListener('change', () => {
    const member = s.cast[+el.dataset.ci];
    const inputs = host.querySelectorAll(`[data-cpos][data-ci="${el.dataset.ci}"]`);
    const next = {};
    inputs.forEach(input => {
      if(input.value !== ''){
        const number = Number(input.value);
        if(Number.isFinite(number)) next[input.dataset.cpos] = Math.max(0, Math.min(1, number));
      }
    });
    if(next.x != null && next.y != null) member.position = next;
    else delete member.position;
    save();
  }));
  host.querySelectorAll('[data-cresource]').forEach(el => el.addEventListener('change', () => {
    const index = +el.dataset.ci;
    const field = el.dataset.cresource;
    s.cast[index][field] = Array.from(host.querySelectorAll(
      `[data-cresource="${field}"][data-ci="${index}"]:checked`
    )).map(input => input.value);
    save();
  }));
  host.querySelectorAll('[data-cdel]').forEach(b => b.addEventListener('click', () => {
    s.cast.splice(+b.dataset.cdel, 1); renderCast(name); tokens(); save();
  }));
}

/* ── 씬 프리셋 ── */
function renderScenePresets(){
  const s = $('scenePreset');
  s.innerHTML = '<option value="">씬 프리셋 불러오기...</option>';
  SCENE_PRESETS.forEach((p,i) => { const o = document.createElement('option'); o.value = i; o.textContent = p.name; s.appendChild(o); });
}
$('scenePreset').addEventListener('change', async () => {
  const i = $('scenePreset').value; if(i === '') return;
  Object.assign(STATE, SCENE_PRESETS[i].data);
  await doSave(); location.reload();
});
$('scenePresetSave').addEventListener('click', async () => {
  const name = prompt('씬 프리셋 이름:'); if(!name) return;
  await doSave();
  const r = await (await fetch('/api/sceneset_save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})})).json();
  if(r.ok){ SCENE_PRESETS = r.scene_presets; renderScenePresets(); alert('저장됨'); } else alert(r.error);
});

/* ── 세팅 빌더 ───────────────────────────────────────────────────────
   세팅 = 세트(묶음)의 모음. 세트 = 단계명마다 씬 하나.
   단계 수가 자유인 이유는 단계를 **묶음 안의 순서**로 세기 때문이다. */
let SB = {name:'', axes:{}}, CLASHES = {};
/* 씬 번호가 세팅끼리 겹치면 나중에 읽힌 쪽이 이겨 조용히 사라진다 — 눈에 띄게 알린다 */
function paintClash(){
  const el = $('sbClash'); if(!el) return;
  const n = Object.keys(CLASHES || {}).length;
  el.textContent = n ? `⚠ 씬 번호 ${n}개가 겹칩니다 — [번호 다시 매기기]를 쓰세요` : '';
}
const NL1 = String.fromCharCode(10);

function sbPickList(){
  const sel = $('sbPick'); if(!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">고칠 세팅 고르기...</option>' +
    SETTINGS.map(st => `<option value="${escA(st.name)}"${st.name===cur?' selected':''}>${esc(st.name)} · ${esc(st.mode)} · ${st.groups.length}세트</option>`).join('');
  const res = $('sbSetRes');
  if(res) res.innerHTML = RES_PRESETS.map(r =>
    `<option value="${r.w}x${r.h}"${r.w===832&&r.h===1216?' selected':''}>${r.label} ${r.w}×${r.h}</option>`).join('');
}
function sbLoad(name){
  const st = SETTINGS.find(x => x.name === name);
  SB.name = name;
  $('sbBody').classList.toggle('hidden', !st);
  if($('sbEmpty')) $('sbEmpty').classList.toggle('hidden', !!st);
  if(!st) return;
  $('sbName').value = st.name;
  $('sbMode').value = st.mode || '단독';
  $('sbStages').value = (st.stages || []).join(', ');
  $('sbCats').value = Object.entries(st.cat_names || {}).map(([k,v]) => k + '=' + v).join(', ');
  const r = st.role || {};
  $('sbRoleLook').value = r['외형'] || ''; $('sbRoleWear').value = r['착의'] || '';
  $('sbRoleOutfit').value = r['의상'] || ''; $('sbRoleNeg').value = r['네거티브'] || '';
  SB.axes = {};
  Object.entries(st.options || {}).forEach(([ax, items]) => {
    const spec = (st.axis_specs || {})[ax] || {};
    SB.axes[ax] = {적용: spec['적용'] || 'base', 방식: spec['방식'] || '고정', 항목: items || {}};
  });
  sbDrawAxes();
  const ns = st.nums || [];
  $('sbMsg').textContent = `씬 ${ns.length}개` + (ns.length ? ` · 번호 ${ns[0]}~${ns[ns.length-1]}` : '');
}
/* 항목 값을 사람이 읽고 쓰기 쉬운 글로 (방식마다 다르다) */
function sbItemToText(shape, v){
  if(shape === '계열별' && v && typeof v === 'object' && !Array.isArray(v))
    return Object.entries(v).map(([k, t]) => k + '=' + t).join(NL1);
  if(shape === '단계별' && Array.isArray(v)) return v.join(NL1);
  return String(v == null ? '' : v);
}
function sbTextToItem(shape, text){
  const lines = String(text || '').split(NL1).map(x => x.replace(/\r$/, '').trim()).filter(Boolean);
  if(shape === '계열별'){
    const o = {};
    lines.forEach(l => { const i = l.indexOf('='); if(i > 0) o[l.slice(0,i).trim()] = l.slice(i+1).trim(); });
    return o;
  }
  if(shape === '단계별') return lines;
  return lines.join(', ');
}
function sbDrawAxes(){
  const h = $('sbAxisList'); if(!h) return;
  h.innerHTML = '';
  Object.entries(SB.axes).forEach(([ax, a]) => {
    const el = document.createElement('div'); el.className = 'slot';
    const hint = a.방식 === '계열별' ? '한 줄에 <b>계열=태그</b> (예: A=sunny, bright)'
      : a.방식 === '단계별' ? '한 줄에 한 단계씩 (위에서부터 1단계)'
      : '태그를 그대로';
    el.innerHTML = `<div class="r1">
        <input type="text" data-axname="${escA(ax)}" value="${escA(ax)}" placeholder="축 이름" style="flex:1;">
        <select data-axtgt="${escA(ax)}">
          ${['base','여자','남자','네거티브'].map(t =>
            `<option value="${t}"${a.적용===t?' selected':''}>${t==='base'?'베이스':t}</option>`).join('')}
        </select>
        <select data-axshape="${escA(ax)}">
          ${['고정','계열별','단계별'].map(t =>
            `<option value="${t}"${a.방식===t?' selected':''}>${t}</option>`).join('')}
        </select>
        <button class="danger" data-axdel="${escA(ax)}">✕</button></div>
      <div class="hint" style="margin:2px 0 4px;">${hint}</div>
      <div data-axitems="${escA(ax)}"></div>
      <div class="bar" style="margin-top:4px;"><button data-axitemadd="${escA(ax)}">+ 선택지</button></div>`;
    h.appendChild(el);
    const box = el.querySelector('[data-axitems]');
    Object.entries(a.항목 || {}).forEach(([pick, val]) => {
      const row = document.createElement('div'); row.className = 'field';
      row.innerHTML = `<label><input type="text" data-axpick="${escA(ax)}" data-old="${escA(pick)}" value="${escA(pick)}" placeholder="선택지 이름" style="width:150px;">
        <button class="danger" data-axpickdel="${escA(ax)}|${escA(pick)}" style="padding:1px 6px;">✕</button></label>
        <textarea data-axval="${escA(ax)}|${escA(pick)}" style="min-height:38px;">${esc(sbItemToText(a.방식, val))}</textarea>`;
      box.appendChild(row);
    });
  });
  h.querySelectorAll('[data-axname]').forEach(x => x.addEventListener('change', () => {
    const old = x.dataset.axname, nw = x.value.trim();
    if(!nw || nw === old) return;
    SB.axes[nw] = SB.axes[old]; delete SB.axes[old]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axtgt]').forEach(x => x.addEventListener('change', () => {
    SB.axes[x.dataset.axtgt].적용 = x.value;
  }));
  h.querySelectorAll('[data-axshape]').forEach(x => x.addEventListener('change', () => {
    const ax = x.dataset.axshape, a = SB.axes[ax];
    /* 방식이 바뀌면 값 모양도 바꿔야 한다 (글로 풀었다가 다시 담는다) */
    const asText = {};
    Object.entries(a.항목 || {}).forEach(([k, v]) => asText[k] = sbItemToText(a.방식, v));
    a.방식 = x.value;
    a.항목 = {};
    Object.entries(asText).forEach(([k, t]) => a.항목[k] = sbTextToItem(a.방식, t));
    sbDrawAxes();
  }));
  h.querySelectorAll('[data-axdel]').forEach(b2 => b2.addEventListener('click', () => {
    if(!confirm(`축 '${b2.dataset.axdel}' 을 지울까요?`)) return;
    delete SB.axes[b2.dataset.axdel]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axitemadd]').forEach(b2 => b2.addEventListener('click', () => {
    const ax = b2.dataset.axitemadd, a = SB.axes[ax];
    let n = 1; while(a.항목[`선택지 ${n}`] !== undefined) n++;
    a.항목[`선택지 ${n}`] = a.방식 === '단계별' ? [] : (a.방식 === '계열별' ? {} : '');
    sbDrawAxes();
  }));
  h.querySelectorAll('[data-axpick]').forEach(x => x.addEventListener('change', () => {
    const ax = x.dataset.axpick, old = x.dataset.old, nw = x.value.trim();
    if(!nw || nw === old) return;
    const a = SB.axes[ax];
    a.항목[nw] = a.항목[old]; delete a.항목[old]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axpickdel]').forEach(b2 => b2.addEventListener('click', () => {
    const parts = b2.dataset.axpickdel.split('|');
    delete SB.axes[parts[0]].항목[parts[1]]; sbDrawAxes();
  }));
  h.querySelectorAll('[data-axval]').forEach(t => t.addEventListener('change', () => {
    const parts = t.dataset.axval.split('|');
    SB.axes[parts[0]].항목[parts[1]] = sbTextToItem(SB.axes[parts[0]].방식, t.value);
  }));
}
if($('sbPick')){
  $('sbPick').addEventListener('change', () => sbLoad($('sbPick').value));
  document.querySelectorAll('[data-sbfold]').forEach(hd => hd.addEventListener('click', () => {
    const b2 = $(hd.dataset.sbfold); if(b2) b2.classList.toggle('hidden');
  }));
  $('sbNew').addEventListener('click', async () => {
    const name = prompt('새 세팅 이름:'); if(!name) return;
    const stages = prompt('단계명 (콤마로 구분 · 세트당 씬 수가 됩니다):', '시작, 중간, 끝');
    if(stages === null) return;
    const r = await (await fetch('/api/sb_new', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name, mode:'단독',
        stages: stages.split(',').map(x=>x.trim()).filter(Boolean)})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    await reloadConfig(); sbPickList();
    $('sbPick').value = r.name; sbLoad(r.name);
    $('sbMsg').textContent = `'${r.name}' 만들었습니다 — 아래 [세트 추가] 로 씬을 만드세요`;
  });
  $('sbAxisAdd').addEventListener('click', () => {
    let n = 1; while(SB.axes[`새 축 ${n}`]) n++;
    SB.axes[`새 축 ${n}`] = {적용:'base', 방식:'고정', 항목:{}};
    sbDrawAxes();
  });
  $('sbSetAdd').addEventListener('click', async () => {
    if(!SB.name){ $('sbMsg').textContent = '세팅을 먼저 고르세요.'; return; }
    const label = $('sbSetLabel').value.trim();
    if(!label){ $('sbMsg').textContent = '세트 이름을 넣으세요.'; return; }
    const wh = ($('sbSetRes').value || '832x1216').split('x').map(Number);
    const stages = $('sbStages').value.split(',').map(x=>x.trim()).filter(Boolean);
    if(!stages.length){ $('sbMsg').textContent = '단계명을 먼저 넣으세요.'; return; }
    /* ★ 단계명 칸을 먼저 저장한다. 안 그러면 화면 값과 파일 값이 어긋나 세트마다
       단계 수가 달라진다 (시험에서 한 세트는 4단계, 다음은 3단계로 갈렸다). */
    await fetch('/api/sb_meta', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name, patch: {'단계명': stages}})});
    const r = await (await fetch('/api/sb_addset', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name, label, category: $('sbSetCat').value.trim(),
                            width: wh[0], height: wh[1], stages})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    $('sbSetLabel').value = '';
    await reloadConfig(); sbPickList(); sbLoad(SB.name);
    $('sbMsg').textContent = `세트 '${label}' 추가 — 씬 ${r.count}개 (${r.start}번부터). 위 목록의 ✎ 로 프롬프트를 채우세요`;
  });
  $('sbSave').addEventListener('click', async () => {
    if(!SB.name) return;
    const cats = {};
    $('sbCats').value.split(',').forEach(t => {
      const i = t.indexOf('='); if(i > 0) cats[t.slice(0,i).trim()] = t.slice(i+1).trim();
    });
    const specs = {}, options = {};
    Object.entries(SB.axes).forEach(([ax, a]) => {
      specs[ax] = {'적용': a.적용, '방식': a.방식};
      options[ax] = a.항목 || {};
    });
    const patch = {
      '이름': $('sbName').value.trim(),
      '방식': $('sbMode').value,
      '단계명': $('sbStages').value.split(',').map(x=>x.trim()).filter(Boolean),
      '계열이름': cats, '옵션규격': specs, '옵션': options,
      '상대역': {'외형': $('sbRoleLook').value, '착의': $('sbRoleWear').value,
                '의상': $('sbRoleOutfit').value, '네거티브': $('sbRoleNeg').value},
    };
    const r = await (await fetch('/api/sb_meta', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name, patch})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    SB.name = r.name;
    await reloadConfig(); sbPickList();
    $('sbPick').value = r.name; sbLoad(r.name);
    $('sbMsg').textContent = '저장했습니다 ✓' + (r.renamed ? ' (파일 이름도 바꿨습니다)' : '');
  });
  $('sbRenum').addEventListener('click', async () => {
    if(!SB.name) return;
    const r = await (await fetch('/api/sb_renumber', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    await reloadConfig(); sbPickList(); sbLoad(SB.name);
    $('sbMsg').textContent = `번호를 ${r.start}번부터 다시 매겼습니다 (씬 ${r.count}개)`;
  });
  $('sbDel').addEventListener('click', async () => {
    if(!SB.name) return;
    if(!confirm(`세팅 '${SB.name}' 을 지울까요? 세팅 폴더의 파일이 지워집니다.`)) return;
    const r = await (await fetch('/api/sb_del', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: SB.name})})).json();
    if(!r.ok){ $('sbMsg').textContent = r.error || '실패'; return; }
    SB.name = ''; $('sbBody').classList.add('hidden');
    await reloadConfig(); sbPickList();
    $('sbMsg').textContent = '지웠습니다';
  });
}

/* ── 씬 모드 ────────────────────────────────────────────────────────
   씬.json 이 원본. 세팅과 별도로 병존한다. */
let SCENES = [];
function renderScenes(){
  const host = $('sceneList'); if(!host) return;
  host.innerHTML = '';
  const booked = SCENES.reduce((a,s) => a + (Number(s.reserve)||0), 0);
  $('sceneCount').textContent = SCENES.length
    ? `${SCENES.length}개 · 예약 ${booked}장` : '';
  if(!SCENES.length){
    host.innerHTML = '<p class="hint">아직 씬이 없습니다. [+ 씬 추가] 를 누르세요.</p>';
    return;
  }
  SCENES.forEach((s, i) => {
    const el = document.createElement('div'); el.className = 'slot';
    el.draggable = true; el.dataset.si = i;
    el.innerHTML = `<div class="r1">
        <span class="ed" title="끌어서 순서 바꾸기" style="cursor:grab;">⠿</span>
        <input type="text" data-sc="name" data-i="${i}" value="${escA(s.name)}" placeholder="씬 이름" style="flex:1;">
        <select data-scres="${i}" title="해상도 — NAI 의 대표 크기들" style="width:132px;">
          ${RES_PRESETS.map(r => `<option value="${r.w}x${r.h}"${(r.w===s.width&&r.h===s.height)?' selected':''}
            >${r.label} ${r.w}×${r.h}</option>`).join('')}
          <option value=""${(!s.custom_res && RES_PRESETS.some(r=>r.w===s.width&&r.h===s.height))?'':' selected'}>직접 입력…</option>
        </select>
        <input type="number" data-sc="width" data-i="${i}" value="${s.width}" min="64" max="2048" step="64"
          title="가로 (직접 입력)" style="width:58px;text-align:center;${(!s.custom_res && RES_PRESETS.some(r=>r.w===s.width&&r.h===s.height))?'display:none;':''}">
        <input type="number" data-sc="height" data-i="${i}" value="${s.height}" min="64" max="2048" step="64"
          title="세로 (직접 입력)" style="width:58px;text-align:center;${(!s.custom_res && RES_PRESETS.some(r=>r.w===s.width&&r.h===s.height))?'display:none;':''}">
        <input type="number" data-sc="reserve" data-i="${i}" value="${s.reserve}" min="0" max="99"
          title="예약 매수 — 0 이면 안 뽑습니다" style="width:44px;text-align:center;">
        <button class="danger" data-scdel="${i}">✕</button></div>
      <textarea data-sc="prompt" data-i="${i}" placeholder="씬 프롬프트 — 배경·구도·분위기 (베이스에 붙습니다)">${esc(s.prompt||'')}</textarea>
      <input type="text" data-sc="negative" data-i="${i}" placeholder="씬 전용 네거티브 (선택)" value="${escA(s.negative||'')}">
      <!-- ★ 인물 묘사는 여기에. 씬 프롬프트에 넣으면 베이스로 가서 왼쪽 캐릭터와 뭉개진다. -->
      <div class="hint" style="margin:5px 0 3px;">인물 칸 — <b>사람 묘사는 여기</b>에 넣으세요
        (비우면 왼쪽 [캐릭터] 그대로 · 둘 다 있으면 이어 붙습니다)</div>
      <div class="grid2">
        <div class="field"><label>인물 1</label>
          <input type="text" data-sc="char1" data-i="${i}" placeholder="예: 1girl, blue hair, smile" value="${escA(s.char1||'')}"></div>
        <div class="field"><label>인물 2</label>
          <input type="text" data-sc="char2" data-i="${i}" placeholder="예: 1boy, black hair" value="${escA(s.char2||'')}"></div>
        <div class="field"><label>인물 1 네거티브</label>
          <input type="text" data-sc="char1_neg" data-i="${i}" value="${escA(s.char1_neg||'')}"></div>
        <div class="field"><label>인물 2 네거티브</label>
          <input type="text" data-sc="char2_neg" data-i="${i}" value="${escA(s.char2_neg||'')}"></div>
      </div>`;
    host.appendChild(el);
  });
  /* 프리셋을 고르면 가로·세로를 채우고 직접 입력 칸을 숨긴다 (직접 입력을 고르면 다시 보인다) */
  host.querySelectorAll('[data-scres]').forEach(sel => sel.addEventListener('change', () => {
    const i = +sel.dataset.scres, s2 = SCENES[i];
    if(sel.value){
      const [w, h] = sel.value.split('x').map(Number);
      s2.width = w; s2.height = h;
      s2.custom_res = false;
      scenesSave(true);
    } else {
      /* '직접 입력' 을 고르면 칸을 보여 주고 **다시 그리지 않는다**.
         다시 그리면 지금 크기가 프리셋과 맞아떨어져 프리셋으로 되돌아가 버린다. */
      s2.custom_res = true;
      const row = sel.closest('.r1');
      row.querySelectorAll('[data-sc="width"], [data-sc="height"]')
         .forEach(x => x.style.display = '');
      scenesSave(false);
    }
  }));
  host.querySelectorAll('[data-sc]').forEach(e => e.addEventListener('change', () => {
    const s = SCENES[+e.dataset.i], k = e.dataset.sc;
    s[k] = (k === 'width' || k === 'height' || k === 'reserve') ? (Number(e.value)||0) : e.value;
    scenesSave();
  }));
  /* 끌어서 순서 바꾸기 — 씬은 순서대로 생성되므로 순서가 곧 작업 순서다 */
  let dragFrom = -1;
  host.querySelectorAll('[data-si]').forEach(el => {
    el.addEventListener('dragstart', e => {
      dragFrom = +el.dataset.si; el.style.opacity = '.4';
      e.dataTransfer.effectAllowed = 'move';
    });
    el.addEventListener('dragend', () => { el.style.opacity = ''; });
    el.addEventListener('dragover', e => {
      e.preventDefault();
      el.style.borderTopColor = 'var(--accent)';
    });
    el.addEventListener('dragleave', () => { el.style.borderTopColor = ''; });
    el.addEventListener('drop', e => {
      e.preventDefault(); el.style.borderTopColor = '';
      const to = +el.dataset.si;
      if(dragFrom < 0 || dragFrom === to) return;
      const [moved] = SCENES.splice(dragFrom, 1);
      SCENES.splice(to, 0, moved);
      dragFrom = -1;
      scenesSave(true);
    });
  });
  host.querySelectorAll('[data-scdel]').forEach(b => b.addEventListener('click', () => {
    if(!confirm(`씬 '${SCENES[+b.dataset.scdel].name}' 을 지울까요?`)) return;
    SCENES.splice(+b.dataset.scdel, 1); scenesSave(true);
  }));
}
async function scenesSave(redraw){
  const r = await (await fetch('/api/scenes_save', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({scenes: SCENES})})).json();
  if(r.ok){ SCENES = r.scenes; if(redraw) renderScenes(); else {
    const booked = SCENES.reduce((a,s)=>a+(Number(s.reserve)||0),0);
    $('sceneCount').textContent = `${SCENES.length}개 · 예약 ${booked}장`;
  } $('sceneMsg').textContent = '저장됨 ✓'; }
  else $('sceneMsg').textContent = r.error || '저장 실패';
}
$('sceneAdd').addEventListener('click', () => {
  SCENES.push({name: `씬 ${SCENES.length+1}`, prompt:'', negative:'',
               char1:'', char2:'', char1_neg:'', char2_neg:'',
               width: Number(STATE.width)||832, height: Number(STATE.height)||1216, reserve: 1});
  scenesSave(true);
});
$('sceneRun').addEventListener('click', async () => {
  const r = await (await fetch('/api/scenes_run', {method:'POST'})).json();
  $('sceneMsg').textContent = r.ok ? `${r.count}장 생성 시작` : (r.error || '실패');
});

/* ── 씬/옵션 편집 모달 ── */
async function openScene(setName, ids){
  window._mm = 'scene';
  window._sceneSetting = setName;
  window._sceneUndo = null;
  const st = SETTINGS.find(s => s.name === setName) || {};
  const r = await (await fetch('/api/scenes?setting=' + encodeURIComponent(setName)
    + '&ids=' + ids.join(','))).json();
  if(!r.ok || !r.scenes.length){ alert('불러오기 실패'); return; }
  window._sceneRevision = r.revision || '';
  $('modalTitle').textContent = `${setName} · ${r.scenes[0].name}${ids.length>1?` 외 ${ids.length}단계`:''}`;
  const f = (id,k,l,v) => `<div class="field"><label>${l}</label><textarea data-sid="${id}" data-sk="${k}" style="min-height:42px;">${esc(v||'')}</textarea></div>`;
  const line = (id,k,l,v,placeholder='') => `<div class="field"><label>${l}</label>
    <input type="text" data-sid="${id}" data-sk="${k}" value="${escA(v||'')}" placeholder="${escA(placeholder)}"></div>`;
  const referenceSelect = (s, title, refIndex) => {
    const selected = (s.character_refs || [])[refIndex] || '';
    const known = (r.char_refs || []).some(ref => ref.id === selected);
    const missing = selected && !known
      ? `<option value="${escA(selected)}" selected>없어진 참조 · ${esc(selected)}</option>` : '';
    return `<div class="field"><label>${title} Reference</label>
      <select data-sref="${s.id}" data-ri="${refIndex}"${s.use_character_refs?'':' disabled'}>
        <option value="">참조 안 함</option>${missing}
        ${(r.char_refs || []).map(ref => `<option value="${escA(ref.id)}"${ref.id===selected?' selected':''}>
          ${esc(ref.name)}</option>`).join('')}
      </select></div>`;
  };
  const actor = (s, title, promptKey, removeKey, negativeKey, promptLabel, refIndex) =>
    `<div class="field" style="border-left:3px solid var(--accent);padding:8px 10px;background:var(--paper);">
      <b>${title}</b>
      ${f(s.id, promptKey, promptLabel, s[promptKey])}
      <div class="grid2">
        ${f(s.id, removeKey, '이 캐릭터에서 제외할 태그 (쉼표)', s[removeKey])}
        ${f(s.id, negativeKey, '이 캐릭터에만 적용할 네거티브', s[negativeKey])}
      </div>
      ${referenceSelect(s, title, refIndex)}
    </div>`;
  const refs = s => `<div class="field" style="border:1px solid var(--line);padding:10px;">
      <label style="display:flex;align-items:center;gap:7px;color:var(--text);">
        <input type="checkbox" data-refuse="${s.id}"
          style="width:16px;height:16px;flex:none;accent-color:var(--accent);"${s.use_character_refs?' checked':''}>
        이 씬에서 캐릭터 Reference를 따로 선택</label>
      <div class="hint">끄면 생성 화면에서 켠 전체 Reference를 사용합니다. 켜면 아래 인물 순서의 선택만 보냅니다.
      NAI API는 참조를 특정 인물에 강제로 묶지 않으므로 순서와 범위를 맞추는 방식입니다.</div>
    </div>`;
  const pos = s => {
    const mode = s.mode || st.mode || '단독';
    const count = mode === '단독' ? 1 : 2;
    const saved = Array.isArray(s.char_centers) ? s.char_centers : [];
    const defaults = count === 1
      ? [{x:.5,y:.5}] : [{x:.3,y:.5},{x:.7,y:.5}];
    const labels = mode === '남녀' ? ['여성','남성'] : ['주인공','상대역'];
    const rows = Array.from({length:count}, (_, i) => {
      const c = saved[i] || defaults[i];
      return `<div class="filterbar" style="margin:4px 0 0;">
        <b style="min-width:48px;">${labels[i]}</b>
        <label class="hint">가로 <input type="number" data-scenter="${s.id}" data-ci="${i}"
          data-axis="x" value="${Number(c.x).toFixed(2)}" min="0" max="1" step="0.05"
          style="width:68px;"${saved.length?'':' disabled'}></label>
        <label class="hint">세로 <input type="number" data-scenter="${s.id}" data-ci="${i}"
          data-axis="y" value="${Number(c.y).toFixed(2)}" min="0" max="1" step="0.05"
          style="width:68px;"${saved.length?'':' disabled'}></label>
      </div>`;
    }).join('');
    return `<div class="field" style="border:1px solid var(--line);padding:10px;">
      <label style="display:flex;align-items:center;gap:7px;color:var(--text);">
        <input type="checkbox" data-posuse="${s.id}" style="width:16px;height:16px;flex:none;accent-color:var(--accent);"${saved.length?' checked':''}>
        이 씬에서 캐릭터 위치를 따로 지정</label>
      <div class="hint">끄면 기본 생성 위치를 그대로 쓰며, 켜면 이 씬에만 저장됩니다.</div>
      ${rows}
      <button type="button" data-posspread="${s.id}" style="margin-top:6px;"${saved.length?'':' disabled'}>
        인물을 고르게 배치</button>
    </div>`;
  };
  $('modalBody').innerHTML = r.scenes.map(s => {
    const isPreset = RES_PRESETS.some(r => r.w === s.width && r.h === s.height);
    let x = `<div class="row"><div class="bar" style="margin-bottom:7px;">
      <div class="tag">#${s.id} · ${esc(s.name)}</div>
      <button type="button" data-preview="${s.id}" style="margin-left:auto;">🔍 최종 프롬프트 보기</button>
      <button type="button" data-scenedup="${s.id}"
        title="디스크에 저장된 이 장면의 태그·관계·Reference·위치를 모두 복제합니다">⧉ 저장값 복제</button>
      </div>
      <div class="filterbar" style="margin:0 0 6px;">
        <span class="hint" style="white-space:nowrap;">해상도</span>
        <select data-sid="${s.id}" data-sk="_res" style="width:132px;">
          ${RES_PRESETS.map(r => `<option value="${r.w}x${r.h}"${(isPreset && r.w===s.width && r.h===s.height)?' selected':''}
            >${r.label} ${r.w}×${r.h}</option>`).join('')}
          <option value=""${isPreset?'':' selected'}>직접 입력…</option>
        </select>
        <input type="number" data-sid="${s.id}" data-sk="width" value="${s.width||832}"
          min="64" max="2048" step="64" title="가로" style="width:74px;text-align:center;">
        <input type="number" data-sid="${s.id}" data-sk="height" value="${s.height||1216}"
          min="64" max="2048" step="64" title="세로" style="width:74px;text-align:center;">
      </div>`;
    x += f(s.id, 'base_tags', '장면 공통 태그 (모든 캐릭터 밖의 베이스에 붙습니다)', s.base_tags);
    x += `<div class="grid2">
      ${line(s.id, 'relationship_name', '등장 관계 이름', s.relationship_name, '예: 연인 · 라이벌 · 가족')}
      ${f(s.id, 'relationship_tags', '실제 관계 태그', s.relationship_tags)}
    </div>`;
    x += refs(s);
    if(st.mode === '백합'){
      x += actor(s, '주인공', 'female_prompt', 'remove_char_tags', 'female_negative', '이 장면에서 추가할 태그', 0);
      x += actor(s, '상대역', 'partner_prompt', 'remove_partner_tags', 'partner_negative', '이 장면에서 추가할 태그', 1);
    } else if(st.mode === '단독'){
      x += actor(s, '캐릭터', 'female_prompt', 'remove_char_tags', 'female_negative', '이 장면에서 추가할 태그', 0);
    } else {
      x += actor(s, '여성', 'female_prompt', 'remove_char_tags', 'female_negative', '이 장면에서 추가할 태그', 0);
      x += actor(s, '남성', 'male_prompt', 'remove_male_tags', 'male_negative', '이 장면에서 추가할 태그', 1);
    }
    return x + f(s.id, 'negative', '이 씬 전용 네거티브 (선택 · 기본 네거티브 뒤에 붙습니다)', s.negative)
             + pos(s) + `<div class="hint" id="pv-${s.id}"></div></div>`;
  }).join('') + `<div class="bar"><button type="button" id="sceneUndo" disabled>↶ 방금 저장 되돌리기</button>
    <button type="button" id="sceneCloneUndo"${window._sceneCloneUndo&&window._sceneCloneUndo.setting===setName?'':' disabled'}>↶ 방금 복제 취소</button>
    <span class="hint">세팅 파일은 저장할 때마다 마지막 정상본을 백업합니다.</span></div>`;
  $('modalBody').querySelectorAll('[data-preview]').forEach(b =>
    b.addEventListener('click', () => scenePreview(b.dataset.preview)));
  $('modalBody').querySelectorAll('[data-scenedup]').forEach(button =>
    button.addEventListener('click', async () => {
      button.disabled = true;
      const response = await (await fetch('/api/scene_duplicate', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          setting:setName, id:button.dataset.scenedup,
          expect_revision:window._sceneRevision,
        })
      })).json();
      if(!response.ok){
        $('modalFlash').textContent = response.error || '장면 복제 실패';
        button.disabled = false;
        return;
      }
      window._sceneCloneUndo = {
        setting:setName, id:response.new_id, scene_sha256:response.scene_sha256,
        revision:response.revision, original_ids:[...ids],
      };
      const message =
        `#${response.new_id} '${response.name}' 복제됨 · 저장하지 않은 화면 값은 포함하지 않았습니다.`;
      await openScene(setName, [...ids, Number(response.new_id)]);
      $('modalFlash').textContent = message;
    }));
  /* 해상도 프리셋 → 숫자칸 채우기 (저장은 숫자칸 값으로 나간다) */
  $('modalBody').querySelectorAll('[data-sk="_res"]').forEach(sel =>
    sel.addEventListener('change', () => {
      if(!sel.value) return;
      const [w, h] = sel.value.split('x').map(Number);
      const box = sel.closest('.filterbar');
      box.querySelector('[data-sk="width"]').value = w;
      box.querySelector('[data-sk="height"]').value = h;
    }));
  $('modalBody').querySelectorAll('[data-posuse]').forEach(box =>
    box.addEventListener('change', () => {
      const sid = box.dataset.posuse;
      $('modalBody').querySelectorAll(`[data-scenter="${sid}"],[data-posspread="${sid}"]`)
        .forEach(el => el.disabled = !box.checked);
    }));
  $('modalBody').querySelectorAll('[data-refuse]').forEach(box =>
    box.addEventListener('change', () => {
      const sid = box.dataset.refuse;
      $('modalBody').querySelectorAll(`[data-sref="${sid}"]`)
        .forEach(el => el.disabled = !box.checked);
    }));
  $('modalBody').querySelectorAll('[data-posspread]').forEach(btn =>
    btn.addEventListener('click', () => {
      const sid = btn.dataset.posspread;
      const xs = $('modalBody').querySelectorAll(`[data-scenter="${sid}"][data-axis="x"]`);
      const ys = $('modalBody').querySelectorAll(`[data-scenter="${sid}"][data-axis="y"]`);
      const vals = xs.length === 1 ? [.5] : [.3,.7];
      xs.forEach((el,i) => el.value = vals[i] ?? .5);
      ys.forEach(el => el.value = .5);
    }));
  $('sceneUndo').addEventListener('click', async () => {
    const last = window._sceneUndo;
    if(!last) return;
    const back = await (await fetch('/api/scene_save', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        setting:last.setting, updates:last.before, expect_revision:last.revision
      })})).json();
    if(!back.ok){ $('modalFlash').textContent = back.error || '되돌리기 실패'; return; }
    $('modalFlash').textContent = '방금 저장한 내용을 되돌렸습니다.';
    $('sceneUndo').disabled = true;
    window._sceneUndo = null;
    await openScene(setName, ids);
  });
  $('sceneCloneUndo').addEventListener('click', async () => {
    const last = window._sceneCloneUndo;
    if(!last || last.setting !== setName) return;
    const response = await (await fetch('/api/scene_duplicate_undo', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        setting:last.setting, id:last.id, scene_sha256:last.scene_sha256,
        expect_revision:last.revision,
      })
    })).json();
    if(!response.ok){
      $('modalFlash').textContent = response.error || '복제 취소 실패';
      return;
    }
    const originalIds = last.original_ids || ids.filter(id => String(id) !== String(last.id));
    window._sceneCloneUndo = null;
    await openScene(setName, originalIds);
    $('modalFlash').textContent = `#${last.id} 복제를 취소했습니다.`;
  });
  $('modalFlash').textContent = ''; $('modalBg').style.display = 'flex';
}

/* 씬 하나가 NAI 로 어떻게 나가는지 그대로 보여준다.
   옵션(장소테마·시간대·표정진행·남자옷)을 곱한 결과라 조합 실수를 여기서 잡는다. */
async function scenePreview(num){
  const host = $('pv-' + num);
  if(!host) return;
  if(host.dataset.open === '1'){ host.innerHTML = ''; host.dataset.open = '0'; return; }
  host.innerHTML = '조립 중...';
  host.dataset.open = '1';
  const r = await (await fetch('/api/scene_preview', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({num: Number(num)})})).json();
  if(!r.ok){ host.innerHTML = `<span style="color:#e0574e">${esc(r.error)}</span>`; return; }
  const box = (label, val, tok) => val ? `<div class="field" style="margin-top:6px;">
      <label>${label}${tok != null ? ` <span class="hint">${tok} 토큰</span>` : ''}</label>
      <textarea readonly style="min-height:44px;">${esc(val)}</textarea></div>` : '';
  const posText = r.use_positions
    ? (r.char_centers || []).map((c,i) => `${i+1}: (${Number(c.x).toFixed(2)}, ${Number(c.y).toFixed(2)})`).join(' · ')
    : '자동 배치';
  const refText = (r.reference_names || []).length
    ? r.reference_names.join(' · ')
    : (r.scene_reference_override ? '이 씬은 Reference 없음' : '전역 활성 Reference 없음');
  host.innerHTML = `<div class="row" style="margin:8px 0 0;background:var(--paper2);">
    <div class="tag">실제 전송값 · ${esc(r.setting)}(${esc(r.mode)}) · 캐스트 ${esc(r.cast)}
      · ${r.width}×${r.height} · 시드 ${r.seed}</div>
    <div class="hint">캐릭터 ${r.people}명 · 위치 ${esc(posText)}
      · 관계 ${esc(r.relationship_name || '미지정')}
      · ${r.scene_reference_override ? '씬 전용 Reference' : '전역 Reference'} ${esc(refText)}</div>
    ${box('베이스 (그림체 + 장소 + 시간대 + 관계)', r.base, r.tokens.base)}
    ${box('캐릭터 1 (주인공 + 씬 + 표정아크)', r.female, r.tokens.female)}
    ${box('캐릭터 2 (상대역 + 옷단계 + 씬)', r.male, r.tokens.male)}
    ${box('네거티브', r.negative)}
    ${box('캐릭터 1 네거티브', r.char_negative)}
    ${box('캐릭터 2 네거티브', r.male_negative)}
  </div>`;
}

function optText(v){
  if(Array.isArray(v)) return v.join('\n');
  if(v && typeof v === 'object') return Object.entries(v).map(([k,x]) => `${k}: ${x}`).join('\n');
  return String(v ?? '');
}
function optVal(name, text){
  text = text.trim();
  if(name === '표정진행') return text.split('\n').map(x=>x.trim()).filter(Boolean);
  if(text.includes('\n') && text.includes(':')){
    const o = {};
    text.split('\n').forEach(l => { const i = l.indexOf(':'); if(i>0) o[l.slice(0,i).trim()] = l.slice(i+1).trim(); });
    return o;
  }
  return text;
}
function openOpts(name){
  window._mm = 'opts'; window._os = name;
  $('modalTitle').textContent = `'${name}' 옵션 항목 — 세팅 파일에 저장`;
  drawOpts();
  $('modalFlash').textContent = ''; $('modalBg').style.display = 'flex';
}
function drawOpts(){
  const st = SETTINGS.find(s => s.name === window._os);
  const b = $('modalBody'); b.innerHTML = '';
  if(!st) return;
  Object.keys(st.options||{}).filter(k=>!k.startsWith('_')).forEach(ok => {
    const opts = st.options[ok]||{};
    let x = `<div class="row"><div class="tag">${esc(ok)}</div>`;
    Object.keys(opts).forEach(n => {
      x += `<div class="bar" style="margin:3px 0;"><span style="min-width:78px;font-size:var(--fs-xs);font-weight:600;">${esc(n)}</span>
        <span style="flex:1;font-size:var(--fs-2xs);color:var(--muted);overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">${esc(optText(opts[n]).replace(/\n/g,' / ').slice(0,64))}</span>
        <button data-ol="${escA(ok)}" data-on="${escA(n)}">수정</button>
        <button class="danger" data-od="${escA(ok)}" data-on="${escA(n)}">삭제</button></div>`;
    });
    x += `<div class="grid2" style="margin-top:7px;"><div class="field"><label>이름</label><input type="text" data-onn="${escA(ok)}"></div>
      <div class="field"><label>내용</label><textarea data-onv="${escA(ok)}" style="min-height:38px;"></textarea></div></div>
      <button data-oa="${escA(ok)}">+ 추가/변경</button></div>`;
    b.insertAdjacentHTML('beforeend', x);
  });
  b.querySelectorAll('[data-od]').forEach(x => x.addEventListener('click', () => optSave(x.dataset.od, 'del', x.dataset.on, null)));
  b.querySelectorAll('[data-ol]').forEach(x => x.addEventListener('click', () => {
    const st2 = SETTINGS.find(s => s.name === window._os);
    b.querySelector(`[data-onn="${CSS.escape(x.dataset.ol)}"]`).value = x.dataset.on;
    b.querySelector(`[data-onv="${CSS.escape(x.dataset.ol)}"]`).value = optText((st2.options[x.dataset.ol]||{})[x.dataset.on]);
  }));
  b.querySelectorAll('[data-oa]').forEach(x => x.addEventListener('click', () => {
    const ok = x.dataset.oa;
    const n = b.querySelector(`[data-onn="${CSS.escape(ok)}"]`).value.trim();
    const v = b.querySelector(`[data-onv="${CSS.escape(ok)}"]`).value;
    if(!n){ alert('이름을 입력해주세요.'); return; }
    optSave(ok, 'set', n, optVal(ok, v));
  }));
}
async function optSave(option, op, name, value){
  const r = await (await fetch('/api/option_item', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({setting: window._os, option, op, name, value})})).json();
  if(r.ok){ SETTINGS = r.snapshot.settings || []; drawOpts(); renderSettings();
    $('modalFlash').textContent = `${option} '${name}' ${op==='del'?'삭제':'저장'}됨 ✓`; }
  else $('modalFlash').textContent = r.error || '실패';
}
