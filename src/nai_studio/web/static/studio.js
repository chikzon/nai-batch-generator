let STATE = null, SAVED_STATE = null, SETTINGS = [], STYLES = [], SPEC = {}, BUILDER = {}, SCENE_PRESETS = [], HIST = [];
let LAST_STUDIO_LAYOUT = null;
let BLUEPRINT_INHERITANCE = {};
let FRAGS = {};
const RES_PRESETS = window.NAI_STUDIO_BOOTSTRAP.resolutions;   // 해상도 프리셋 (파이썬 RESOLUTIONS 와 같은 목록)

function genId(){ return Math.random().toString(36).slice(2,10); }
function esc(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function escA(s){ return esc(s).replace(/"/g,'&quot;'); }
function $(id){ return document.getElementById(id); }

function showStartupRecovery(notice){
  const bar = $('startupRecovery');
  if(!bar || !notice) return;
  bar.style.display = 'flex';
  $('startupRecoveryDetail').textContent =
    `원본 ${Number((notice.files||[]).length).toLocaleString()}개를 ${notice.folder || '복구보관 폴더'}에 보존했습니다.`
    + ' 아무 자료도 영구 삭제하지 않았습니다.';
  $('startupRecoveryClose').addEventListener('click', () => bar.style.display = 'none');
  $('startupRecoveryBackup').addEventListener('click', () => {
    bar.style.display = 'none';
    setMode('system');
    setTimeout(() => $('backupCard') && $('backupCard').scrollIntoView({behavior:'smooth'}), 0);
  });
}

async function loadBlueprint(){
  const host = $('blueprintPlan');
  if(!host) return;
  $('blueprintSummary').textContent = '현재 저장값을 생성 설계도로 해석하는 중입니다.';
  try{
    const result = await (await fetch('/api/blueprint')).json();
    if(!result.ok) throw new Error(result.error || '설계도를 만들지 못했습니다.');
    const bp = result.blueprint || {};
    const inheritance = result.inheritance || {};
    BLUEPRINT_INHERITANCE = inheritance;
    const s = bp.summary || {};
    const size = s.width && s.height ? `${s.width}×${s.height}` : '크기 미정';
    $('blueprintSummary').textContent =
      `${s.model || '모델 미정'} · ${size} · 캐릭터 ${Number(s.characters||0)}명`
      + ` · 바이브 ${Number(s.vibes||0)} · 레퍼런스 ${Number(s.references||0)}`
      + ` · ${s.experiment_mode || 'single'} · 지문 ${(s.fingerprint||'').slice(0,12)}`;
    const select = $('blueprintProjectSelect');
    const oldSelection = select.value;
    select.innerHTML = '<option value="">프로젝트 없음</option>'
      + (inheritance.projects || []).map(project =>
        `<option value="${escA(project.id)}">${esc(project.name)} · ${(project.fingerprint||'').slice(0,8)}</option>`
      ).join('');
    select.value = inheritance.id || oldSelection || '';
    const active = !!inheritance.active;
    const changed = !!inheritance.parent_changed;
    $('blueprintProjectBadge').textContent = active
      ? `${inheritance.name || '프로젝트'}${changed ? ' · 갱신 확인 필요' : ' · 연결됨'}`
      : '';
    $('blueprintProjectAccept').classList.toggle('hidden', !changed);
    $('blueprintProjectDisconnect').classList.toggle('hidden', !active);
    $('blueprintProjectState').textContent = active
      ? `${inheritance.name || '이름 없는 프로젝트'} 연결 · 물려받은 값 ${Number(inheritance.inherited_paths||0)}개`
        + ` · 현재·세팅 변경 ${Number(inheritance.override_paths||0)}개`
        + (inheritance.missing ? ' · 원본 없음(승인 사본은 유지)' : '')
        + (changed ? ' · 새 공통판 있음 — 적용 전까지 기존 판 유지' : ' · 승인 판과 일치')
      : '프로젝트를 쓰지 않음 · 지금까지의 생성 흐름 그대로';
    $('blueprintLayers').textContent = active
      ? '우선순위: 프로젝트 공통값 → 세팅·실험 → 현재 변경값 → 최종 전송값'
      : '현재 생성값 → 최종 전송값';
    const conflicts = inheritance.conflicts || [];
    $('blueprintConflicts').textContent = conflicts.length
      ? `충돌 ${conflicts.length}개 · ${conflicts.slice(0,6).map(item => item.path).join(' · ')}`
      : '충돌 없음';
    $('blueprintJson').textContent = JSON.stringify({
      resolved: bp,
      provenance: inheritance.provenance || {},
      conflicts,
    }, null, 2);
  }catch(error){
    $('blueprintSummary').textContent = String(error);
    $('blueprintJson').textContent = '';
  }
}

async function blueprintProjectAction(action){
  const select = $('blueprintProjectSelect');
  const name = ($('blueprintProjectName').value || '').trim();
  const body = {action, id: select.value || '', name};
  if(action === 'accept') body.fingerprint =
    BLUEPRINT_INHERITANCE.current_fingerprint || '';
  if((action === 'create' || action === 'update') && !name){
    flash('공통 설계도 이름을 적어주세요.'); return;
  }
  if((action === 'update' || action === 'activate') && !body.id){
    flash('프로젝트를 먼저 골라주세요.'); return;
  }
  try{
    const result = await (await fetch('/api/blueprint_project', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    })).json();
    if(!result.ok) throw new Error(result.error || '프로젝트 작업에 실패했습니다.');
    location.reload();
  }catch(error){
    flash(String(error));
  }
}

function bindBlueprintProjects(){
  const bindings = {
    blueprintProjectCreate:'create',
    blueprintProjectUpdate:'update',
    blueprintProjectActivate:'activate',
    blueprintProjectAccept:'accept',
    blueprintProjectDisconnect:'disconnect',
  };
  Object.entries(bindings).forEach(([id, action]) => {
    const button = $(id);
    if(button && !button._bound){
      button._bound = true;
      button.addEventListener('click', () => blueprintProjectAction(action));
    }
  });
  const select = $('blueprintProjectSelect');
  if(select && !select._bound){
    select._bound = true;
    select.addEventListener('change', () => {
      const project = (BLUEPRINT_INHERITANCE.projects || [])
        .find(item => item.id === select.value);
      if(project) $('blueprintProjectName').value = project.name || '';
    });
  }
}

async function init(){
  const d = await (await fetch('/api/config')).json();
  STATE = d.config;
  SAVED_STATE = JSON.parse(JSON.stringify(STATE));
  const savedOutpaint = ((STATE.ui || {}).outpaint) || {};
  for(const [id, key, fallback] of [
    ['outpaintLeft','left',256], ['outpaintRight','right',256],
    ['outpaintTop','top',0], ['outpaintBottom','bottom',0]
  ]){
    if($(id)) $(id).value = String(Number.isFinite(Number(savedOutpaint[key]))
      ? Number(savedOutpaint[key]) : fallback);
  }
  SETTINGS = d.settings || [];
  STYLES = d.styles || [];
  SPEC = d.spec || {};
  BUILDER = d.builder || {};
  SCENE_PRESETS = d.scene_presets || [];
  FRAGS = d.fragments || {};
  CLASHES = d.scene_clashes || {};
  SCENES = d.scenes || [];
  showStartupRecovery(d.startup_recovery);
  paint();
  bindDropZone($('generateInspectDrop'), $('generateInspectFile'));
  bindTagSearch(document);
  if($('blueprintPlan') && !$('blueprintPlan')._bound){
    $('blueprintPlan')._bound = true;
    $('blueprintPlan').addEventListener('toggle', loadBlueprint);
  }
  bindBlueprintProjects();
  loadBlueprint();
}

/* 세팅 파일이 디스크에서 바뀐 뒤 목록만 다시 받는다.
   STATE 는 건드리지 않는다 — 저장 안 된 편집이 날아가면 안 된다. */
async function reloadConfig(){
  const d = await (await fetch('/api/config')).json();
  SETTINGS = d.settings || [];
  CLASHES = d.scene_clashes || {};
  renderSettings(); tokens(); counts(); sbPickList(); paintClash();
  if($('setThumbs') && $('setThumbs').checked) loadSetThumbs();
}

function paint(){
  $('basePrompt').value = STATE.base_prompt || '';
  $('negPrompt').value = STATE.negative_prompt || '';
  $('token').value = STATE.token || '';
  const BK = [['bkDanUser','danbooru','user'],['bkDanKey','danbooru','key'],['bkGelUser','gelbooru','user'],['bkGelKey','gelbooru','key'],['bkE6User','e621','user'],['bkE6Key','e621','key']];
  BK.forEach(([id, site, f]) => { const e=$(id); if(e) e.value = ((STATE.booru_keys||{})[site]||{})[f] || ''; });
  $('pScale').value = STATE.cfg_scale ?? 5.5;
  $('pRescale').value = STATE.cfg_rescale ?? 0.56;
  $('pSteps').value = STATE.steps ?? 28;
  $('pSeed').value = STATE.seed ?? 1;
  $('pNaiSeed').value = STATE.nai_seed ?? 0;
  $('pSampler').value = STATE.sampler || 'k_euler_ancestral';
  $('pSched').value = STATE.scheduler || 'karras';
  $('pVariety').value = STATE.variety ? 'on' : 'off';
  paintParams();
  renderPresets(); renderSlots(); renderSettings(); renderLibrary(); renderScenePresets();
  bindComparison(); bindUserBackup(); bindTrashCenter(); bindLocalImageIntegrity();
  renderFrags(); renderScenes(); applySplit3(); paintPace(); acScan(document);
  sbPickList(); paintClash();
  if($('expGrid')) expLoad('');
  bindWelcome(); refreshWelcome();
  setupHL(); bindHLToggle(); bindDirector(); bindRefs(); bindUseCoords(); bindBooru();
  if(!$('anlasBal')._bound){
    $('anlasBal')._bound = true;
    $('anlasBal').addEventListener('click', () => anlasRefresh(true));
    ['qty','qtyM','qtyP'].forEach(id => $(id) &&
      $(id).addEventListener('click', () => anlasRefresh(false)));
    $('qty').addEventListener('input', () => anlasRefresh(false));
  }
  anlasRefresh(false);
  /* 레시피 6,388건은 자료 탭에서 그 영역을 실제로 볼 때 읽는다.
     첫 화면에서 미리 읽고 이미지 60장을 예열하면, 사용자가 먼저 누른
     작가 조합 빌더와 디스크·네트워크 작업이 겹쳐 화면이 멈춘다. */
  bindRecipes();
  applyUI(); renderUIChips();
  if($('notifySound')) $('notifySound').checked = !!(STATE.ui||{}).notify_sound;
  if($('notifySystem')) $('notifySystem').checked = !!(STATE.ui||{}).notify_system;
  tokens();
}

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

/* ── 내 자료 전체 백업 ─────────────────────────────────────────────── */
let BACKUP_FILE = null, BACKUP_SHA = '', BACKUP_BATCH = '',
  BACKUP_DIFF = '', BACKUP_CHANGES = [], BACKUP_SHOW = 0;
function backupValue(value, exists){
  if(!exists) return '<span class="hint">없음</span>';
  let text;
  try{ text = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  catch(e){ text = String(value); }
  return `<pre style="max-height:190px;overflow:auto;white-space:pre-wrap;word-break:break-word;margin:4px 0 0;">${esc(text)}</pre>`;
}
function backupSelection(){
  return BACKUP_CHANGES.filter(change => change.selected).map(change => change.id);
}
function backupSelectionPaint(){
  const selected = backupSelection().length;
  $('backupSelectedCount').textContent = `${selected.toLocaleString()}개 선택`;
  $('backupRestore').disabled = !BACKUP_FILE || !BACKUP_SHA || !selected;
}
function backupDiffPaint(reset=false){
  if(reset){ BACKUP_SHOW = 0; $('backupDiffList').innerHTML = ''; }
  const start = BACKUP_SHOW;
  const end = Math.min(BACKUP_CHANGES.length, start + 120);
  for(let i=start; i<end; i++){
    const change = BACKUP_CHANGES[i];
    const card = document.createElement('label');
    card.className = 'row';
    card.style.cssText = 'display:block;margin:0;cursor:pointer;';
    card.innerHTML = `<div class="bar">
      <input type="checkbox" data-backup-change="${escA(change.id)}" style="width:auto;flex:none;"
        ${change.selected?'checked':''}>
      <b>${esc(change.logical)}</b><span class="tag">${esc(change.action)}</span></div>
      <div class="hint">${esc(change.pointer)} · ${esc(change.file_status)}`
      + (change.base_available
        ? ` · 공통 기준 ${esc(String(change.base_sha256).slice(0,12))}`
        : ' · 공통 기준 미제공') + `</div>
      <details><summary>현재값</summary>${backupValue(change.current, change.current_exists)}</details>
      <details><summary>들어오는 값</summary>${backupValue(change.incoming, change.incoming_exists)}</details>`;
    card.querySelector('input').addEventListener('change', event => {
      change.selected = event.target.checked; backupSelectionPaint();
    });
    $('backupDiffList').appendChild(card);
  }
  BACKUP_SHOW = end;
  $('backupDiffMore').classList.toggle('hidden', end >= BACKUP_CHANGES.length);
  $('backupDiffMore').textContent =
    `더 보기 (${Math.max(0, BACKUP_CHANGES.length-end).toLocaleString()}개 남음)`;
  backupSelectionPaint();
}
function bindUserBackup(){
  if(!$('backupCard') || $('backupCard')._bound) return;
  $('backupCard')._bound = true;
  BACKUP_BATCH = sessionStorage.getItem('naisBackupRollback') || '';
  if(BACKUP_BATCH){
    $('backupRollback').classList.remove('hidden');
    $('backupMsg').textContent = '방금 복원한 자료가 적용되었습니다. 문제가 있으면 복원 전 상태로 되돌릴 수 있습니다.';
  }
  $('backupExport').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = '/api/backup_export';
    a.download = 'NAI배치생성기-내자료백업.zip';
    document.body.appendChild(a); a.click(); a.remove();
    $('backupMsg').textContent = '백업 ZIP을 만드는 중입니다. 다운로드가 시작될 때까지 기다려주세요.';
  });
  $('backupChoose').addEventListener('click', () => $('backupFile').click());
  $('backupFile').addEventListener('change', async () => {
    const file = $('backupFile').files[0];
    $('backupFile').value = '';
    if(!file) return;
    BACKUP_FILE = file; BACKUP_SHA = ''; BACKUP_DIFF = ''; BACKUP_CHANGES = [];
    $('backupRestore').disabled = true;
    $('backupDiff').classList.add('hidden');
    $('backupMsg').textContent = '백업의 경로·크기·내용 해시를 검사하는 중입니다.';
    try{
      const r = await (await fetch('/api/backup_preview', {method:'POST',
        headers:{'X-Filename':encodeURIComponent(file.name)},
        body:await file.arrayBuffer()})).json();
      if(!r.ok){ $('backupMsg').textContent = r.error || '백업 검사 실패'; return; }
      BACKUP_SHA = r.sha256;
      BACKUP_DIFF = r.diff_fingerprint || '';
      BACKUP_CHANGES = (r.changes || []).map(change =>
        Object.assign({selected:false}, change));
      const c = r.counts || {};
      $('backupMsg').innerHTML =
        `<b>${Number(r.files||0).toLocaleString()}개 · ${(Number(r.bytes||0)/1048576).toFixed(1)}MB</b>`
        + ` — 새 파일 ${Number(c['새 파일']||0).toLocaleString()} · 바뀔 파일 ${Number(c['바뀔 파일']||0).toLocaleString()}`
        + ` · 같은 파일 ${Number(c['같은 파일']||0).toLocaleString()}`
        + `<br>충돌 조각 ${BACKUP_CHANGES.length.toLocaleString()}개 · 백업 시점 ${esc(r.created_at||'?')}`
        + ` · 토큰·생성물·원격 캐시는 복원하지 않습니다.`;
      $('backupDiff').classList.toggle('hidden', !BACKUP_CHANGES.length);
      backupDiffPaint(true);
    }catch(e){ $('backupMsg').textContent = '백업 검사 실패: ' + e; }
  });
  $('backupRestore').addEventListener('click', async () => {
    const selected = backupSelection();
    if(!BACKUP_FILE || !BACKUP_SHA || !selected.length) return;
    if(!confirm(`선택한 ${selected.length}개 변경만 적용할까요?\\n현재 파일은 복원 기록에 보존되며 바로 되돌릴 수 있습니다.`)) return;
    $('backupRestore').disabled = true;
    $('backupMsg').textContent = '기존 파일을 복원 기록에 보존한 뒤 적용하는 중입니다.';
    try{
      const r = await (await fetch('/api/backup_restore', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({sha256:BACKUP_SHA, diff_fingerprint:BACKUP_DIFF,
          selected})})).json();
      if(!r.ok){ $('backupMsg').textContent = r.error || '복원 실패'; $('backupRestore').disabled=false; return; }
      BACKUP_BATCH = r.batch || '';
      if(BACKUP_BATCH) sessionStorage.setItem('naisBackupRollback', BACKUP_BATCH);
      $('backupMsg').textContent = `${r.changed}개 파일 복원 완료 · 토큰과 출력 폴더 설정은 현재 값을 유지했습니다. 화면을 안전하게 다시 불러옵니다.`;
      $('backupRollback').classList.toggle('hidden', !BACKUP_BATCH);
      setTimeout(() => location.reload(), 700);
    }catch(e){ $('backupMsg').textContent = '복원 실패: ' + e; $('backupRestore').disabled=false; }
  });
  $('backupSelectAll').addEventListener('click', () => {
    BACKUP_CHANGES.forEach(change => { change.selected = true; });
    backupDiffPaint(true);
  });
  $('backupSelectNone').addEventListener('click', () => {
    BACKUP_CHANGES.forEach(change => { change.selected = false; });
    backupDiffPaint(true);
  });
  $('backupDiffMore').addEventListener('click', () => backupDiffPaint(false));
  $('backupRollback').addEventListener('click', async () => {
    if(!BACKUP_BATCH) return;
    const r = await (await fetch('/api/backup_rollback', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:BACKUP_BATCH})})).json();
    const skipped = Number(r.skipped || 0);
    $('backupMsg').textContent = r.ok
      ? `${r.restored}개 파일을 복원 전 상태로 되돌렸습니다.`
        + (skipped ? ` 복원 뒤 다시 바뀐 ${skipped}개 파일은 덮어쓰지 않았습니다.` : '')
      : (r.error || '되돌리기 실패');
    if(r.ok){
      BACKUP_BATCH='';
      sessionStorage.removeItem('naisBackupRollback');
      $('backupRollback').classList.add('hidden');
      setTimeout(() => location.reload(), 700);
    }
  });
}

/* ── 생성물 휴지통 센터 ───────────────────────────────────────────── */
async function trashCenterLoad(){
  const box = $('trashList');
  if(!box) return;
  box.textContent = '휴지통 묶음을 확인하는 중입니다.';
  try{
    const r = await (await fetch('/api/trash', {cache:'no-store'})).json();
    if(!r.ok){ box.textContent = r.error || '휴지통 확인 실패'; return; }
    const rows = r.batches || [];
    if(!rows.length){
      box.innerHTML = '<span class="n">휴지통이 비어 있습니다.</span>';
      return;
    }
    box.innerHTML = `<div class="bar" style="margin-bottom:7px;">
      <b>${Number(r.total_files||0).toLocaleString()}개 복원 가능</b>
      <span>${(Number(r.total_bytes||0)/1048576).toFixed(1)}MB</span></div>`
      + rows.map(row => `<div class="row" style="display:flex;align-items:center;gap:8px;">
        <div style="flex:1;min-width:0;"><b>${esc(row.created_at || row.batch_id)}</b>
          <div class="hint">${Number(row.available||0).toLocaleString()} / ${Number(row.total||0).toLocaleString()}개 남음
          · ${(Number(row.bytes||0)/1048576).toFixed(1)}MB</div></div>
        <button type="button" data-trash-restore="${escA(row.batch_id)}"
          ${Number(row.available||0) ? '' : 'disabled'}>↶ 이 묶음 복원</button></div>`).join('');
  }catch(e){
    box.textContent = '휴지통 확인 실패: ' + e;
  }
}
function bindTrashCenter(){
  if(!$('trashCard') || $('trashCard')._bound) return;
  $('trashCard')._bound = true;
  $('trashRefresh').addEventListener('click', trashCenterLoad);
  $('trashList').addEventListener('click', async event => {
    const button = event.target.closest('[data-trash-restore]');
    if(!button || button.disabled) return;
    if(!confirm('이 묶음을 원래 위치로 복원할까요?\\n같은 이름의 새 파일은 덮어쓰지 않습니다.')) return;
    button.disabled = true;
    const r = await (await fetch('/api/picks_restore', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({batch_id:button.dataset.trashRestore})})).json();
    if(!r.ok) alert(r.error || '복원 실패');
    else if($('expGrid')) await expLoad(EXP.dir || '');
    await trashCenterLoad();
  });
  trashCenterLoad();
}

/* ── 자료 이미지 무결성 ────────────────────────────────────────────── */
let LOCAL_IMAGE_FINGERPRINT = '', LOCAL_IMAGE_BATCH = '';
function bindLocalImageIntegrity(){
  if(!$('localImageCard') || $('localImageCard')._bound) return;
  $('localImageCard')._bound = true;
  LOCAL_IMAGE_BATCH = sessionStorage.getItem('naisLocalImageRollback') || '';
  if(LOCAL_IMAGE_BATCH){
    $('localImageRollback').classList.remove('hidden');
    $('localImageMsg').textContent = '방금 정리한 참조를 원래 이름으로 되돌릴 수 있습니다.';
  }
  $('localImageScan').addEventListener('click', async () => {
    $('localImageScan').disabled = true;
    $('localImageNormalize').disabled = true;
    $('localImageMsg').textContent = '자료 JSON과 실제 이미지 바이트를 읽어 대조하는 중입니다.';
    try{
      const r = await (await fetch('/api/local_image_integrity')).json();
      if(!r.ok && (r.invalid_json||[]).length){
        $('localImageMsg').textContent = `읽지 못한 자료 JSON ${r.invalid_json.length}개가 있어 먼저 복구해야 합니다.`;
        return;
      }
      LOCAL_IMAGE_FINGERPRINT = r.fingerprint || '';
      const n = r.normalization || {};
      const danger = Number(r.missing||0) + Number(r.unreadable_references||0);
      $('localImageMsg').innerHTML =
        `<b>참조 ${Number(r.unique_references||0).toLocaleString()}개</b> — `
        + `누락 ${Number(r.missing||0).toLocaleString()} · 열기 실패 ${Number(r.unreadable_references||0).toLocaleString()}`
        + ` · 과거 이름 ${Number(r.referenced_legacy_names||0).toLocaleString()}`
        + ` · 현재 자료에서 미사용 ${Number(r.unreferenced||0).toLocaleString()}`
        + `<br>${danger ? '<b style="color:var(--danger);">손상 가능성이 있어 자동 정리를 막았습니다.</b>' :
          `표시 가능한 참조는 모두 있습니다. 안전 정리 시 JSON ${Number(n.documents_to_change||0)}개에서 `
          + `${Number(n.references_to_change||0).toLocaleString()}개 참조를 바꾸고 `
          + `${(Number(n.copy_bytes||0)/1048576).toFixed(1)}MB를 복사합니다.`}`
        + '<br>옛 파일과 미사용 후보는 지우지 않습니다.';
      $('localImageNormalize').disabled =
        !!n.blocked || !Number(n.references_to_change||0);
    }catch(e){
      $('localImageMsg').textContent = '이미지 검사 실패: ' + e;
    }finally{
      $('localImageScan').disabled = false;
    }
  });
  $('localImageNormalize').addEventListener('click', async () => {
    if(!LOCAL_IMAGE_FINGERPRINT) return;
    if(!confirm('검사한 참조를 실제 이미지 내용 해시 이름으로 정리할까요?\\n옛 파일은 지우지 않고 JSON 원본도 별도 기록에 보존합니다.')) return;
    $('localImageNormalize').disabled = true;
    $('localImageMsg').textContent = '새 이름 복사본과 JSON 원본 기록을 만든 뒤 참조를 바꾸는 중입니다.';
    try{
      const r = await (await fetch('/api/local_image_normalize', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({fingerprint:LOCAL_IMAGE_FINGERPRINT})
      })).json();
      if(!r.ok){ $('localImageMsg').textContent = r.error || '이미지 정리 실패'; return; }
      LOCAL_IMAGE_BATCH = r.batch || '';
      if(LOCAL_IMAGE_BATCH){
        sessionStorage.setItem('naisLocalImageRollback', LOCAL_IMAGE_BATCH);
        $('localImageRollback').classList.remove('hidden');
      }
      $('localImageMsg').textContent =
        `${Number(r.changed_references||0).toLocaleString()}개 참조를 안전 정리했습니다. `
        + `옛 이름 파일 ${Number(r.kept_legacy_files||0).toLocaleString()}개는 그대로 보존했습니다.`;
      LOCAL_IMAGE_FINGERPRINT = '';
    }catch(e){ $('localImageMsg').textContent = '이미지 정리 실패: ' + e; }
  });
  $('localImageRollback').addEventListener('click', async () => {
    if(!LOCAL_IMAGE_BATCH) return;
    const r = await (await fetch('/api/local_image_rollback', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:LOCAL_IMAGE_BATCH})
    })).json();
    $('localImageMsg').textContent = r.ok
      ? `자료 JSON ${Number(r.restored||0)}개를 정리 전으로 되돌렸습니다.`
        + (Number(r.skipped||0) ? ` 이후 다시 편집된 ${r.skipped}개는 덮어쓰지 않았습니다.` : '')
      : (r.error || '되돌리기 실패');
    if(r.ok){
      LOCAL_IMAGE_BATCH = '';
      sessionStorage.removeItem('naisLocalImageRollback');
      $('localImageRollback').classList.add('hidden');
      LOCAL_IMAGE_FINGERPRINT = '';
    }
  });
}

/* 실제 NAI 토큰 수 — 서버의 T5 토크나이저에 물어본다 (입력이 멈추면 한 번) */
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
let saveT = null, saveBusy = false, saveQueued = false, reloadAfterSave = false;
function stateSavePatch(){
  const patch = {_revision: STATE._revision, _base:{}};
  for(const [key, value] of Object.entries(STATE || {})){
    if(key.startsWith('_')) continue;
    const before = SAVED_STATE ? SAVED_STATE[key] : undefined;
    if(JSON.stringify(value) === JSON.stringify(before)) continue;
    patch[key] = value;
    patch._base[key] = before;
  }
  return patch;
}
function rememberSavedKeys(keys){
  SAVED_STATE = SAVED_STATE || {};
  (keys || []).forEach(key => {
    if(key in STATE) SAVED_STATE[key] = JSON.parse(JSON.stringify(STATE[key]));
  });
  SAVED_STATE._revision = STATE._revision;
}
function save(){
  clearTimeout(saveT);
  saveState('busy', '저장 대기…');
  /* 자동완성은 160ms 뒤 시작하며 첫 색인은 22만 태그를 읽는다.
     저장을 그보다 먼저 보내 새 설치의 첫 입력도 색인 예열 뒤로 밀리지 않게 한다. */
  saveT = setTimeout(doSave, 100);
}
function saveState(kind, text, detail=''){
  const el = $('saveState'); if(!el) return;
  el.className = 'save-state' + (kind ? ' ' + kind : '');
  el.textContent = text;
  el.title = detail || '설정.json 자동저장 상태';
}
async function doSave(){
  saveT = null;
  /* 앞 요청보다 옛 STATE가 늦게 도착해 새 값을 덮지 않도록 한 번에 하나만 보낸다. */
  if(saveBusy){ saveQueued = true; return; }
  saveBusy = true;
  saveState('busy', '저장 중…');
  try{
    const patch = stateSavePatch();
    const changed = Object.keys(patch).filter(key => !key.startsWith('_'));
    if(!changed.length){ saveState('', '저장됨 ✓'); return; }
    const r = await (await fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(patch)})).json();
    if(r && r.conflict){
      const msg = r.error || '다른 화면에서 설정이 변경됐습니다. 새로고침해주세요.';
      saveState('fail', '저장 충돌 ⚠', msg); flash(msg); return;
    }
    if(r && r.revision != null) STATE._revision = r.revision;
    const f = (r && r.fixed) || {};
    const ids = {width:'pWidth',height:'pHeight',steps:'pSteps',cfg_scale:'pScale',
      cfg_rescale:'pRescale',save_quality:'pSaveQ',seed:'pSeed',nai_seed:'pNaiSeed',
      uncond_scale:'pUncond',controlnet_strength:'pCtrl'};
    Object.entries(f).forEach(([k, v]) => {
      if(k.startsWith('pace.')){
        const pk = k.slice(5); STATE.pace = STATE.pace || {}; STATE.pace[pk] = v.used;
        const pe = Object.entries(PACE_FIELDS).find(([,key]) => key === pk);
        if(pe && $(pe[0])) $(pe[0]).value = v.used;
      }else if(ids[k]){
        STATE[k] = v.used; if($(ids[k])) $(ids[k]).value = v.used;
      }
    });
    const wh = ['width','height'].filter(k => f[k]);
    const note = $('pResNote');
    if(note) note.textContent = wh.length
      ? `⚠ NAI 규격(64 배수·64~2048)으로 맞췄습니다: ${wh.map(k => `${k==='width'?'가로':'세로'} ${f[k].sent}→${f[k].used}`).join(' · ')}` : '';
    if(r && r.rejected && r.rejected.length) flash(`저장하지 않은 잘못된 값: ${r.rejected.join(', ')}`);
    rememberSavedKeys((r && r.accepted) || changed);
    /* 최종 생성 설계도를 열어 둔 동안에는 저장된 현재 작업과 같은 화면을 보여 준다. */
    if($('blueprintPlan') && $('blueprintPlan').open) loadBlueprint();
    if(r && r.external_changes && r.external_changes.length){
      reloadAfterSave = true;
      flash(`다른 실행본의 변경 ${r.external_changes.length}개도 반영했습니다. 화면을 맞추는 중입니다.`);
    }
    saveState('', '저장됨 ✓');
  }catch(e){
    console.warn('설정 저장 실패', e);
    saveState('fail', '저장 실패 ⚠',
      '설정.json에 저장하지 못했습니다. 앱을 닫지 말고 연결 상태와 생성.log를 확인하세요.');
  }
  finally{
    saveBusy = false;
    if(saveQueued){ saveQueued = false; doSave(); }
    else if(reloadAfterSave){
      const pending = Object.keys(stateSavePatch()).some(key => !key.startsWith('_'));
      if(pending){
        if(!saveT) save();
      }else{
        reloadAfterSave = false;
        location.reload();
      }
    }
  }
}
/* 입력 직후 100ms 안에 탭을 닫아도 마지막 변경을 서버에 넘긴다.
   입력 원문은 그대로 보내며 길이 제한을 두지 않는다. */
window.addEventListener('pagehide', () => {
  if(!saveT || saveBusy || !navigator.sendBeacon) return;
  clearTimeout(saveT); saveT = null;
  const patch = stateSavePatch();
  if(!Object.keys(patch).some(key => !key.startsWith('_'))) return;
  navigator.sendBeacon('/api/save',
    new Blob([JSON.stringify(patch)], {type:'application/json'}));
});
['basePrompt','negPrompt','token','pScale','pRescale','pSteps','pSeed','pNaiSeed','pSampler','pSched','pVariety'].forEach(id => {
  const el = $(id);
  const h = () => {
    STATE.base_prompt = $('basePrompt').value;
    STATE.negative_prompt = $('negPrompt').value;
    STATE.token = $('token').value;
    STATE.cfg_scale = Number($('pScale').value) || 5.5;
    STATE.cfg_rescale = Number($('pRescale').value) || 0.56;
    STATE.steps = Number($('pSteps').value) || 28;
    STATE.seed = Number($('pSeed').value) || 1;
    STATE.nai_seed = Number($('pNaiSeed').value) || 0;
    STATE.sampler = $('pSampler').value || 'k_euler_ancestral';
    STATE.scheduler = $('pSched').value || 'karras';
    STATE.variety = $('pVariety').value === 'on';
    if(STYLE_PARAM_IDS.has(id)) clearActiveStyle();
    tokens(); refreshWelcome(); save();
  };
  el.addEventListener('input', h); el.addEventListener('change', h);
});
$('tokenShow').addEventListener('click', () => {
  const input = $('token'), show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  $('tokenShow').textContent = show ? '숨기기' : '보기';
  $('tokenShow').setAttribute('aria-pressed', show ? 'true' : 'false');
});
/* 부루 계정 — 다른 파라미터 저장 훅과 섞으면 서로 덮어쓰므로 따로 둔다 */
[['bkDanUser','danbooru','user'],['bkDanKey','danbooru','key'],['bkGelUser','gelbooru','user'],['bkGelKey','gelbooru','key'],['bkE6User','e621','user'],['bkE6Key','e621','key']].forEach(([id, site, f]) => {
  const el = $(id); if(!el) return;
  const h = () => {
    STATE.booru_keys = STATE.booru_keys || {};
    STATE.booru_keys[site] = STATE.booru_keys[site] || {};
    STATE.booru_keys[site][f] = el.value.trim();
    save();
  };
  el.addEventListener('input', h); el.addEventListener('change', h);
});
if($('bkTest')) $('bkTest').addEventListener('click', async () => {
  const m = $('bkMsg'); m.textContent = '확인 중...';
  const out = [];
  for(const site of ['danbooru','gelbooru','e621']){
    try{
      const r = await (await fetch('/api/booru?site='+site+'&q=1girl&limit=1')).json();
      out.push((site==='danbooru'?'단부루':site==='gelbooru'?'겔부루':'e621')
        + ': ' + (r.ok ? (r.items||[]).length+'건 OK' : '실패'));
      if(!r.ok) console.log(site, r.error);
    }catch(e){ out.push(site+': 오류'); }
  }
  m.textContent = out.join(' · ') + ' (실패 이유는 검색 화면에 나옵니다)';
});

/* ── 접기/오버레이/모드 ── */
document.querySelectorAll('[data-fold]').forEach(h => h.addEventListener('click', () => {
  h.classList.toggle('closed'); $(h.dataset.fold).classList.toggle('hidden');
}));
document.querySelectorAll('[data-ovl]').forEach(b => b.addEventListener('click', () => {
  // data-ovl="refs" → #ovlRefs. 오버레이를 늘려도 여기 손대지 않아도 된다
  const k = b.dataset.ovl;
  const id = 'ovl' + k.charAt(0).toUpperCase() + k.slice(1);
  const target = $(id);
  if(!target){ console.warn('오버레이 없음:', id); return; }
  const wasOpen = !target.classList.contains('hidden');
  document.querySelectorAll('.ovl').forEach(o => o.classList.add('hidden'));
  if(!wasOpen) target.classList.remove('hidden');   // 같은 버튼을 다시 누르면 닫힘
}));
document.querySelectorAll('[data-ovl-close]').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.ovl').forEach(o => o.classList.add('hidden'));
}));

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
async function loadJobCenter(){
  const host = $('jobCenterList'); if(!host) return;
  host.innerHTML = '<div class="row hint">작업 상태를 확인하는 중입니다.</div>';
  try{
    const [live, ledger, comparisons, collection] = await Promise.all([
      fetch('/status.json', {cache:'no-store'}).then(r => r.json()),
      fetch('/api/jobs', {cache:'no-store'}).then(r => r.json()),
      fetch('/api/compare_runs', {cache:'no-store'}).then(r => r.json()),
      fetch('/api/public_collection', {cache:'no-store'}).then(r => r.json()),
    ]);
    const unfinished = (comparisons.runs || []).filter(run => run.resumable);
    const liveState = live.running
      ? `${live.operation || '생성'} · ${Number(live.completed||0)}/${Number(live.total||0)}`
      : `대기 · 최근 ${live.phase || 'idle'}`;
    const collectState = collection.status || 'idle';
    const recent = (ledger.jobs || []).slice(0, 5);
    const activeContracts = ledger.active_contracts || [];
    const contracts = new Map(
      (ledger.contracts || []).map(job => [String(job.id || ''), job])
    );
    const jobActions = job => {
      if(!contracts.has(String(job.id || ''))) return [];
      const phase = String(job.phase || '');
      if(['preparing','sending','receiving'].includes(phase)){
        return [['pause','일시정지'],['cancel','취소']];
      }
      if(phase === 'paused') return [['resume','이어가기'],['cancel','취소']];
      if(phase === 'failed') return [['retry','재시도 준비']];
      if(phase === 'queued') return [['cancel','취소']];
      return [];
    };
    const activeRows = activeContracts.length
      ? activeContracts.map(job => {
          const progress = job.progress || {};
          const actions = jobActions(job).map(([action,label]) =>
            `<button type="button" data-job-action="${action}" data-job-id="${escA(job.id||'')}">${label}</button>`
          ).join('');
          return `<div class="row"><div style="flex:1;min-width:0;"><b>${esc(job.kind||'작업')}</b>
            <div class="hint">${esc(job.phase||'')} · ${Number(progress.completed||0)}/${Number(progress.total||0)}
            · 요청 ${esc(String(job.request_id||'').slice(0,18))}</div></div>${actions}</div>`;
        }).join('')
      : '<div class="row hint">현재 투영된 실행 작업이 없습니다.</div>';
    host.innerHTML = `
      <div class="row"><div><b>현재 생성 실행권</b><div class="hint">${esc(liveState)}</div>
        <div class="hint">${esc(live.status_text || '')}</div></div>
        <button type="button" data-job-go="preview">생성으로</button></div>
      <div class="row"><div><b>비교 실험</b><div class="hint">이어갈 기록 ${unfinished.length}개 · 전체 ${(comparisons.runs||[]).length}개</div></div>
        <button type="button" data-job-go="compare">비교 실험으로</button></div>
      <div class="row"><div><b>공개자료 수집</b><div class="hint">${esc(collectState)}
        · ${Number(collection.cursor||0)}/${Number((collection.queue||[]).length||collection.found_posts||0)}</div></div>
        <button type="button" data-job-go="library">자료 수집으로</button></div>
      <div style="grid-column:1/-1;display:grid;gap:7px;"><b>실행 가능한 공통 작업</b>
        ${activeRows}</div>
      <div class="row" style="grid-column:1/-1;display:block;"><b>최근 실행 기록</b>
        <div class="hint" style="margin-top:5px;">${recent.length ? recent.map(job =>
          {
            const contract = contracts.get(String(job.id || '')) || {};
            const phase = contract.phase && contract.phase !== 'invalid'
              ? contract.phase : (job.status || '');
            const request = contract.request_id
              ? ` · 요청 ${esc(String(contract.request_id).slice(0,18))}` : '';
            return `${esc(job.operation || job.kind)} · ${esc(phase)}${request}`
          + ` · 성공 ${Number(job.completed||0)} / 실패 ${Number(job.failed||0)}`
          + `${job.can_resume ? ' · 재개 기록 있음' : ''}`;
          }
        ).join('<br>') : '아직 기록이 없습니다.'}</div></div>`;
    host.querySelectorAll('[data-job-go]').forEach(button => button.addEventListener('click', () => {
      const target = button.dataset.jobGo;
      if(target === 'compare'){
        STATE.ui = STATE.ui || {}; STATE.ui.settings_work = 'compare';
        setMode('settings'); arrangeStudioWorkspace(); comparisonRunsLoad();
      }else setMode(target);
    }));
    host.querySelectorAll('[data-job-action]').forEach(button => button.addEventListener('click', async () => {
      button.disabled = true;
      const r = await (await fetch('/api/job_command', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          job_id:button.dataset.jobId,
          action:button.dataset.jobAction
        })
      })).json();
      if(!r.ok){
        alert(r.error || '작업 명령을 적용하지 못했습니다.');
        button.disabled = false; return;
      }
      if(r.navigation === 'compare'){
        STATE.ui = STATE.ui || {}; STATE.ui.settings_work = 'compare';
        setMode('settings'); arrangeStudioWorkspace(); comparisonRunsLoad();
      }else if(r.navigation){
        setMode(r.navigation);
      }
      if(r.message) alert(r.message);
      loadJobCenter();
    }));
  }catch(error){
    host.innerHTML = `<div class="row" style="color:var(--danger);">${esc(String(error))}</div>`;
  }
}
function bindStudioManageNav(){
  const nav = $('studioManageNav');
  if(!nav || nav._bound) return;
  nav._bound = true;
  nav.querySelectorAll('[data-manage-work]').forEach(button => {
    button.addEventListener('click', () => {
      STATE.ui = STATE.ui || {};
      STATE.ui.manage_work = button.dataset.manageWork;
      arrangeStudioWorkspace(); save();
      if(button.dataset.manageWork === 'jobs') loadJobCenter();
    });
  });
  if($('jobCenterRefresh')) $('jobCenterRefresh').addEventListener('click', loadJobCenter);
}
function bindStudioLibraryNav(){
  const nav = $('studioLibraryNav');
  if(!nav || nav._bound) return;
  nav._bound = true;
  nav.querySelectorAll('[data-library-work]').forEach(button => {
    button.addEventListener('click', () => {
      STATE.ui = STATE.ui || {};
      STATE.ui.library_work = button.dataset.libraryWork;
      arrangeStudioWorkspace();
      save();
    });
  });
}
function activeResultTool(){
  const tool = String(((STATE || {}).ui || {}).result_tool || '');
  return ['i2i','director','mosaic'].includes(tool) ? tool : '';
}
function bindResultToolSwitcher(){
  const host = $('resultToolSwitcher');
  if(!host || host._bound) return;
  host._bound = true;
  host.querySelectorAll('[data-result-tool]').forEach(button => {
    button.addEventListener('click', () => {
      STATE.ui = STATE.ui || {};
      STATE.ui.result_tool = activeResultTool() === button.dataset.resultTool
        ? '' : button.dataset.resultTool;
      arrangeResultTools((STATE.ui || {}).layout !== 'classic');
      save();
    });
  });
}
function arrangeResultTools(studio){
  bindResultToolSwitcher();
  const host = $('resultToolSwitcher');
  const tool = activeResultTool();
  if(host) host.classList.toggle('hidden', !studio);
  document.querySelectorAll('[data-result-tool-panel]').forEach(panel => {
    panel.classList.toggle('hidden', studio && panel.dataset.resultToolPanel !== tool);
  });
  const mosaic = $('mosaicCard');
  if(mosaic) mosaic.classList.toggle('hidden', studio && tool !== 'mosaic');
  if(host){
    host.querySelectorAll('[data-result-tool]').forEach(button => {
      const on = studio && button.dataset.resultTool === tool;
      button.classList.toggle('on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
}
function arrangeStudioWorkspace(){
  if(!STATE) return;
  bindStudioSettingsNav();
  bindStudioLibraryNav();
  bindStudioManageNav();
  const studio = (STATE.ui || {}).layout !== 'classic';
  const layoutChanged = LAST_STUDIO_LAYOUT !== studio;
  const importCard = $('generateImportCard');
  const outputSettings = $('pOutputSettings');
  if(layoutChanged){
    if(importCard) importCard.open = !studio;
    if(outputSettings) outputSettings.open = !studio;
    LAST_STUDIO_LAYOUT = studio;
  }

  const mosaicCard = $('mosaicCard');
  const mosaicHome = studio ? $('mosaicGenerateHome') : $('mosaicClassicHome');
  if(mosaicCard && mosaicHome && mosaicHome.nextElementSibling !== mosaicCard){
    mosaicHome.insertAdjacentElement('afterend', mosaicCard);
  }

  const card = $('compareCard');
  const classicHome = $('compareClassicHome');
  if(card && classicHome && classicHome.nextElementSibling !== card){
    classicHome.insertAdjacentElement('afterend', card);
  }

  const settingsNav = $('studioSettingsNav');
  const settingsCards = {
    select: $('settingSelectCard'),
    quick: $('sceneQuickCard'),
    build: $('settingBuilderCard'),
    compare: card,
  };
  if(settingsNav && Object.values(settingsCards).every(Boolean)){
    const savedSettingsWork = (STATE.ui || {}).settings_work;
    const settingsWork = ['select','quick','build','compare'].includes(savedSettingsWork)
      ? savedSettingsWork : 'select';
    settingsNav.classList.toggle('hidden', !studio);
    Object.entries(settingsCards).forEach(([key, settingsCard]) => {
      settingsCard.classList.toggle('hidden', studio && key !== settingsWork);
    });
    settingsNav.querySelectorAll('[data-settings-work]').forEach(button => {
      const on = button.dataset.settingsWork === settingsWork;
      button.classList.toggle('on', on);
      button.setAttribute('aria-selected', on ? 'true' : 'false');
      button.tabIndex = on ? 0 : -1;
    });
  }

  const libraryNav = $('studioLibraryNav');
  const libraryWork = ['input','catalog','results'].includes(
    (STATE.ui || {}).library_work) ? STATE.ui.library_work : 'input';
  if(libraryNav){
    libraryNav.classList.toggle('hidden', !studio);
    document.querySelectorAll('[data-library-panel]').forEach(panel => {
      panel.classList.toggle(
        'hidden', studio && panel.dataset.libraryPanel !== libraryWork);
    });
    libraryNav.querySelectorAll('[data-library-work]').forEach(button => {
      const on = button.dataset.libraryWork === libraryWork;
      button.classList.toggle('on', on);
      button.setAttribute('aria-selected', on ? 'true' : 'false');
      button.tabIndex = on ? 0 : -1;
    });
  }

  const manageNav = $('studioManageNav');
  const manageWork = ['environment','safety','jobs','tools'].includes(
    (STATE.ui || {}).manage_work) ? STATE.ui.manage_work : 'jobs';
  if(manageNav){
    manageNav.classList.toggle('hidden', !studio);
    document.querySelectorAll('[data-manage-panel]').forEach(panel => {
      panel.classList.toggle(
        'hidden', studio && panel.dataset.managePanel !== manageWork);
    });
    manageNav.querySelectorAll('[data-manage-work]').forEach(button => {
      const on = button.dataset.manageWork === manageWork;
      button.classList.toggle('on', on);
      button.setAttribute('aria-selected', on ? 'true' : 'false');
      button.tabIndex = on ? 0 : -1;
    });
  }
  arrangeResultTools(studio);
}
const MODE_CONTEXT = {
  preview: ['01 · 생성', '생성', '프롬프트, 캐릭터, 생성 설정을 확인하고 결과를 만듭니다.'],
  settings: ['02 · 세팅', '세팅', '씬, 캐스트, 단계와 비교 실험을 한 생성 계획으로 설계합니다.'],
  library: ['03 · 자료', '자료', '공개 자료와 내 자료를 수집하고, 큰 묶음 그대로 찾고 정리합니다.'],
  builder: ['04 · 빌더', '빌더', '근거가 있는 그림체·캐릭터·작가 조합을 만들고 바로 사용합니다.'],
  system: ['05 · 관리', '관리', '작업 큐, 출력, 백업·복구와 앱 환경을 관리합니다.'],
};
function setMode(m){
  document.body.dataset.mode = m;
  document.querySelectorAll('#modes button').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
  ['preview','settings','builder','library','system'].forEach(x =>
    $('v' + x[0].toUpperCase() + x.slice(1)).style.display = (x === m ? '' : 'none'));
  const context = MODE_CONTEXT[m] || MODE_CONTEXT.preview;
  if($('workspaceStep')) $('workspaceStep').textContent = context[0];
  if($('workspaceTitle')) $('workspaceTitle').textContent = context[1];
  if($('workspaceDesc')) $('workspaceDesc').textContent = context[2];
  arrangeStudioWorkspace();
  if(m === 'system' && (STATE.ui || {}).manage_work === 'jobs') loadJobCenter();
}
document.querySelectorAll('#modes button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
document.querySelectorAll('[data-mode-jump]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.modeJump)));
/* Alt+1~5 로 탭 이동. Alt 를 쓰는 이유 — 프롬프트 칸에서 숫자를 칠 수 있어야 한다 */
window.addEventListener('keydown', e => {
  if(!e.altKey || e.ctrlKey || e.metaKey) return;
  const i = ['1','2','3','4','5'].indexOf(e.key);
  if(i < 0) return;
  const b = document.querySelectorAll('#modes button')[i];
  if(b){ e.preventDefault(); setMode(b.dataset.mode); }
});

/* ── 베이스 프리셋 (그림체 파일) ── */
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
let DIAG_LAST = null;
async function diagLoad(){
  const box = $('diagOut'); if(!box) return;
  box.textContent = '읽는 중...';
  try{
    const r = await (await fetch('/api/diag?n=' + (($('diagN')||{}).value || 300)
      + (($('diagErrOnly')||{}).checked ? '&err=1' : ''))).json();
    if(!r.ok){ DIAG_LAST = null; box.textContent = r.error || '못 읽음'; return; }
    DIAG_LAST = r;
    box.textContent = r.lines.join(String.fromCharCode(10)) || '(기록 없음)';
    $('diagStat').textContent = `${r.events.length}건` + (r.errors != null ? ` · 오류/경고 ${r.errors}` : '');
    box.scrollTop = box.scrollHeight;
  }catch(e){ DIAG_LAST = null; box.textContent = String(e); }
}
if($('diagLoad')){
  $('diagLoad').addEventListener('click', diagLoad);
  ['diagErrOnly','diagN'].forEach(id => $(id) && $(id).addEventListener('change', diagLoad));
  $('diagCopy').addEventListener('click', () => {
    navigator.clipboard.writeText($('diagOut').textContent || '')
      .then(() => $('diagStat').textContent = '복사됨 ✓');
  });
  $('diagExport').addEventListener('click', () => {
    if(!DIAG_LAST){ $('diagStat').textContent = '먼저 불러오세요'; return; }
    const now = new Date();
    const pad2 = n => String(n).padStart(2, '0');
    const localDay = `${now.getFullYear()}-${pad2(now.getMonth()+1)}-${pad2(now.getDate())}`;
    const safe = {
      schema: DIAG_LAST.schema,
      exported_at: now.toISOString(),
      errors: DIAG_LAST.errors,
      events: DIAG_LAST.events
    };
    const blob = new Blob([JSON.stringify(safe, null, 2)], {type:'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nais-diagnostics-${localDay}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    $('diagStat').textContent = '안전 JSON 저장됨 ✓';
  });
}

/* 인물 칸 일괄 손질 (NAIS3 의 캐릭터 다중 선택·일괄 편집을 우리 구조로).
   칸이 여럿일 때 하나씩 누르는 수고를 줄인다. 켬/끔은 '보낼지'만 정하고 칸은 남는다. */
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

/* ── 생성물 탐색기 · 선별 · 비교함 ──────────────────────────────────
   원본 파일은 옮기지 않는다. 선별·즐겨찾기는 경로에 붙는 이름표(선별.json)다. */
const EXP_CHUNK = 120;
let EXP = {dir:'', files:[], dirs:[], total:0, loading:false,
  loadSeq:0, picked:new Set(), fav:new Set(), cmp:new Set(), open:-1,
  folders:{}, ranks:{}, ratings:{}, elo:{}, elo_matches:{}, tags:{},
  memos:{}, review_states:{}};
function expListUrl(dir, offset=0){
  const q = new URLSearchParams({
    dir: dir ?? EXP.dir, limit: String(EXP_CHUNK), offset: String(offset)
  });
  if($('expOnlyPick').checked) q.set('only_pick', '1');
  if($('expOnlyFav').checked) q.set('only_fav', '1');
  return '/api/out_list?' + q.toString();
}
async function expLoad(dir){
  /* 폴더·필터를 빨리 바꾸면 이전의 느린 응답이 나중 상태를 덮을 수 있다.
     요청 세대를 올려 **마지막 선택의 응답만** 적용한다. */
  const seq = ++EXP.loadSeq;
  EXP.loading = true;
  let r;
  try{
    r = await (await fetch(expListUrl(dir ?? EXP.dir, 0))).json();
  }catch(e){
    if(seq === EXP.loadSeq){ EXP.loading = false; $('expStat').textContent = String(e); }
    return;
  }
  if(seq !== EXP.loadSeq) return;
  EXP.loading = false;
  if(!r.ok){ $('expStat').textContent = r.error || '못 읽음'; return; }
  EXP.dir = r.dir; EXP.files = r.files; EXP.dirs = r.dirs;
  EXP.total = Number.isFinite(r.total) ? r.total : r.files.length;
  EXP.picked = new Set(r.picked); EXP.fav = new Set(r.fav); EXP.ranks = r.ranks || {};
  EXP.folders = r.folders || {}; EXP.ratings = r.ratings || {};
  EXP.elo = r.elo || {}; EXP.elo_matches = r.elo_matches || {}; EXP.tags = r.tags || {};
  EXP.memos = r.memos || {}; EXP.review_states = r.review_states || {};
  $('expPath').textContent = 'output/' + (r.dir ? r.dir + '/' : '');
  /* 최상위에서는 위로 갈 곳이 없다 — 눌려도 아무 일 없으면 고장으로 보인다 */
  const up = $('expUp');
  if(up){ up.disabled = !r.dir; up.title = r.dir ? '상위 폴더' : '이미 최상위입니다'; }
  expDraw();
}
async function expFetchMore(draw=true){
  if(EXP.loading || EXP.files.length >= EXP.total) return false;
  const seq = EXP.loadSeq;
  EXP.loading = true;
  let r;
  try{
    r = await (await fetch(expListUrl(EXP.dir, EXP.files.length))).json();
  }catch(e){
    if(seq === EXP.loadSeq){ EXP.loading = false; $('expStat').textContent = String(e); }
    return false;
  }
  if(seq !== EXP.loadSeq) return false;
  EXP.loading = false;
  if(!r.ok){ $('expStat').textContent = r.error || '못 읽음'; return false; }
  const seen = new Set(EXP.files.map(f => f.path));
  const added = (r.files || []).filter(f => !seen.has(f.path));
  EXP.files.push(...added);
  EXP.total = Number.isFinite(r.total) ? r.total : EXP.files.length;
  EXP.vis = expVisible();
  if(draw) expChunk();
  return added.length > 0;
}
async function expEnsureAll(){
  while(EXP.files.length < EXP.total){
    const before = EXP.files.length;
    if(!await expFetchMore(false) || EXP.files.length === before) break;
  }
  EXP.vis = expVisible();
  return EXP.vis;
}
function expVisible(){
  let f = EXP.files;
  if($('expOnlyPick').checked) f = f.filter(x => EXP.picked.has(x.path));
  if($('expOnlyFav').checked) f = f.filter(x => EXP.fav.has(x.path));
  const group = ($('expGroupFilter') || {}).value || '';
  if(group){
    const members = new Set(EXP.folders[group] || []);
    f = f.filter(x => members.has(x.path));
  }
  return f;
}
function expPaintGroups(){
  const select = $('expGroupFilter'); if(!select) return;
  const before = select.value;
  const names = Object.keys(EXP.folders || {}).sort((a,b) => a.localeCompare(b));
  select.innerHTML = '<option value="">전체 보기</option>'
    + names.map(name => `<option value="${escA(name)}">${esc(name)}`
      + ` (${(EXP.folders[name] || []).length.toLocaleString()})</option>`).join('');
  select.value = names.includes(before) ? before : '';
}
function expDraw(){
  const dh = $('expDirs'); dh.innerHTML = '';
  EXP.dirs.forEach(d => {
    const b = document.createElement('button');
    b.textContent = `📁 ${d.name} (${d.count})`;
    b.addEventListener('click', () => expLoad(d.path));
    dh.appendChild(b);
  });
  const g = $('expGrid'); g.innerHTML = '';
  g.style.setProperty('--ecard', $('expSize').value + 'px');
  expPaintGroups();
  const vis = expVisible();
  $('expCount').textContent = `${EXP.total}장`;
  $('expStat').textContent = `${vis.length}/${EXP.total}장 불러옴 · 선별 ${EXP.picked.size}`
    + ` · 즐겨찾기 ${EXP.fav.size} · 평가 ${Object.keys(EXP.ratings||{}).length}`
    + ` · ELO ${Object.keys(EXP.elo||{}).length}`;
  $('expCmpN').textContent = EXP.cmp.size;
  /* 수천 장을 한 번에 그리면 초기 로딩·메모리가 터진다 (Custom 의 페이지 분할 참고).
     120장씩 그리고, '더 보기'가 화면에 가까워지면 자동으로 다음 묶음. */
  EXP.vis = vis; EXP.shown = 0;
  expChunk();
}
function expChunk(){
  const g = $('expGrid');
  const vis = EXP.vis || [];
  const end = Math.min(vis.length, EXP.shown + EXP_CHUNK);
  for(let i = EXP.shown; i < end; i++){
    const f = vis[i];
    const score = Number((EXP.ratings || {})[f.path] || 0);
    const elo = Number((EXP.elo || {})[f.path] || 0);
    const tags = (EXP.tags || {})[f.path] || [];
    const el = document.createElement('div');
    el.style.cssText = 'position:relative;cursor:pointer;';
    el.innerHTML = `<img src="/setout?p=${encodeURIComponent(f.path)}" alt="" loading="lazy"
        style="width:100%;aspect-ratio:1/1;object-fit:cover;display:block;
        border:2px solid ${EXP.picked.has(f.path)?'var(--good)':'var(--line)'};
        border-radius:var(--radius);${EXP.cmp.has(f.path)?'outline:2px dashed var(--accent);outline-offset:1px;':''}">
      <div style="position:absolute;top:2px;right:3px;font-size:var(--fs-sm);text-shadow:0 0 3px #000;">
        ${EXP.fav.has(f.path)?'⭐':''}${EXP.picked.has(f.path)?'✔':''}</div>
      ${((EXP.ranks||{})[f.path] || score || elo) ? `<div style="position:absolute;top:2px;left:3px;font-size:var(--fs-2xs);
        background:#000a;color:#ffd76e;padding:1px 4px;border-radius:var(--radius-pill);">
        ${(EXP.ranks||{})[f.path] ? `🏆${EXP.ranks[f.path]}` : ''}${score ? ` ${'★'.repeat(score)}` : ''}${elo ? ` ⚖${Math.round(elo)}` : ''}</div>` : ''}
      <div class="tag" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(f.name)}</div>
      ${tags.length ? `<div class="hint" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(tags.slice(0,3).join(' · '))}</div>` : ''}`;
    el.addEventListener('click', () => expOpen(i));
    g.appendChild(el);
  }
  EXP.shown = end;
  let more = $('expMore');
  if(!more){
    more = document.createElement('button');
    more.id = 'expMore';
    more.style.cssText = 'grid-column:1/-1;padding:8px 0;';
    more.addEventListener('click', () =>
      EXP.shown < (EXP.vis || []).length ? expChunk() : expFetchMore());
    /* 화면에 가까워지면 자동 로딩 — 탭이 숨어 있으면 안 돌므로 안전하다 */
    new IntersectionObserver(es => es.forEach(e => {
      if(!e.isIntersecting) return;
      if(EXP.shown < (EXP.vis || []).length) expChunk();
      else if(EXP.files.length < EXP.total) expFetchMore();
    }), {rootMargin: '600px'}).observe(more);
  }
  g.appendChild(more);   // 항상 그리드 맨 끝
  more.textContent = `더 보기 (${Math.max(0, EXP.total - EXP.shown)}장 남음)`;
  more.classList.toggle('hidden', EXP.shown >= EXP.total);
}
/* ── 🏆 이미지 월드컵 (SDStudio 의 토너먼트를 우리 탐색기에) ──────────────
   보이는 그림을 무작위로 짝지어 1:1 로 이긴 쪽만 다음 판에 올린다.
   판마다 진 쪽은 그 라운드의 등수를 받는다 → 마지막에 순위가 나온다.
   순위는 선별.json 의 ranks 에 저장되어 카드에 배지로 남는다.
   조작: ←/→ 또는 클릭으로 승자 · Space 무승부(둘 다 진출) · Esc 중단 */
let CUP = null;
async function cupStart(){
  const vis = await expEnsureAll();
  if(vis.length < 2){ $('expStat').textContent = '월드컵은 그림이 2장 이상일 때 할 수 있습니다.'; return; }
  const pool = vis.map(f => f.path);
  for(let i = pool.length - 1; i > 0; i--){          // 섞기
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  CUP = {round: pool, next: [], i: 0, ranks: {}, place: pool.length, total: pool.length, matches: 0};
  cupDraw();
}
function cupFinish(){
  const el = $('cupBg'); if(el) el.remove();
  const ranked = Object.entries(CUP.ranks).sort((a, b) => a[1] - b[1]);
  Object.assign(EXP.ranks, CUP.ranks);
  picksSave();
  $('expStat').textContent = `🏆 월드컵 끝 — ${CUP.matches}판, 1등 ${ranked.length ? ranked[0][0].split('/').pop() : '?'}`;
  CUP = null;
  expDraw();
}
function cupDraw(){
  if(!CUP) return;
  /* 이번 라운드가 끝났으면 다음 라운드로 */
  if(CUP.i >= CUP.round.length){
    if(CUP.next.length <= 1){
      if(CUP.next.length === 1) CUP.ranks[CUP.next[0]] = 1;   // 우승
      cupFinish(); return;
    }
    /* 모두 '둘 다'를 고른 라운드는 참가 수가 줄지 않는다. 전원 공동 1위로 종료한다. */
    if(CUP.next.length === CUP.round.length){
      CUP.next.forEach(p => { CUP.ranks[p] = 1; });
      cupFinish(); return;
    }
    CUP.round = CUP.next; CUP.next = []; CUP.i = 0;
  }
  /* 홀수로 남은 마지막 한 장은 부전승 */
  if(CUP.i === CUP.round.length - 1){
    CUP.next.push(CUP.round[CUP.i]); CUP.i++;
    cupDraw(); return;
  }
  const a = CUP.round[CUP.i], b = CUP.round[CUP.i + 1];
  let ov = $('cupBg');
  if(!ov){
    ov = document.createElement('div'); ov.id = 'cupBg';
    ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:#000d;display:flex;'
      + 'flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:12px;';
    document.body.appendChild(ov);
  }
  const left = Math.max(0, CUP.round.length - CUP.i) + CUP.next.length;
  ov.innerHTML = `<div style="color:#eee;font-size:var(--fs-sm);">
      🏆 이미지 월드컵 — ${CUP.total}장 중 ${left}장 남음 · ${CUP.matches + 1}번째 판
      <span style="opacity:.7;margin-left:10px;">←/→ 또는 클릭으로 승자 · Space 둘 다 · Esc 중단</span></div>
    <div style="display:flex;gap:12px;align-items:center;justify-content:center;max-height:78vh;">
      <img data-cup="L" src="/setout?p=${encodeURIComponent(a)}" style="max-width:46vw;max-height:74vh;object-fit:contain;cursor:pointer;border:3px solid transparent;border-radius:var(--radius);">
      <img data-cup="R" src="/setout?p=${encodeURIComponent(b)}" style="max-width:46vw;max-height:74vh;object-fit:contain;cursor:pointer;border:3px solid transparent;border-radius:var(--radius);">
    </div>
    <div style="color:#aaa;font-size:var(--fs-2xs);">${esc(a.split('/').pop())} vs ${esc(b.split('/').pop())}</div>`;
  ov.querySelectorAll('[data-cup]').forEach(im => {
    im.addEventListener('mouseenter', () => im.style.borderColor = 'var(--accent)');
    im.addEventListener('mouseleave', () => im.style.borderColor = 'transparent');
    im.addEventListener('click', () => cupPick(im.dataset.cup === 'L' ? 'a' : 'b'));
  });
}
function cupPick(which){
  if(!CUP) return;
  const a = CUP.round[CUP.i], b = CUP.round[CUP.i + 1];
  CUP.matches++;
  if(which === 'both'){ CUP.next.push(a, b); }
  else {
    const win = which === 'a' ? a : b, lose = which === 'a' ? b : a;
    CUP.next.push(win);
    CUP.ranks[lose] = CUP.place--;          // 진 쪽은 남은 등수 중 가장 낮은 자리
  }
  CUP.i += 2;
  cupDraw();
}
/* ── 블라인드 ELO ─────────────────────────────────────────────────────
   파일명·기존 점수·출처를 가린 채 같은 후보군 안에서 반복 비교한다.
   별점과 월드컵 순위는 다른 판단 축이므로 덮지 않고 ELO와 판수만 따로 누적한다. */
let ELO = null;
async function eloStart(){
  const vis = await expEnsureAll();
  if(vis.length < 2){
    $('expStat').textContent = '블라인드 ELO는 그림이 2장 이상일 때 할 수 있습니다.';
    return;
  }
  const pool = vis.map(file => file.path);
  for(let i = pool.length - 1; i > 0; i--){
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  ELO = {pool, target:3, played:0, pair:null, busy:false, decision:''};
  eloNext();
}
function eloNext(){
  if(!ELO) return;
  const ordered = [...ELO.pool].sort((a,b) => {
    const diff = Number(EXP.elo_matches[a] || 0) - Number(EXP.elo_matches[b] || 0);
    return diff || Math.random() - .5;
  });
  const least = Number(EXP.elo_matches[ordered[0]] || 0);
  if(least >= ELO.target){
    const el = $('eloBg'); if(el) el.remove();
    $('expStat').textContent = `⚖ 블라인드 ELO 완료 — ${ELO.played}판 · 각 후보 누적 ${ELO.target}판 이상`;
    ELO = null; expDraw(); return;
  }
  const a = ordered[0];
  const aScore = Number(EXP.elo[a] || 1000);
  const opponents = ordered.slice(1).sort((x,y) =>
    Math.abs(Number(EXP.elo[x] || 1000) - aScore)
      - Math.abs(Number(EXP.elo[y] || 1000) - aScore));
  const b = opponents[0];
  ELO.pair = [a,b];
  ELO.decision = (globalThis.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `elo-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let ov = $('eloBg');
  if(!ov){
    ov = document.createElement('div'); ov.id = 'eloBg';
    ov.style.cssText = 'position:fixed;inset:0;z-index:100;background:#000e;display:flex;'
      + 'flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:14px;';
    document.body.appendChild(ov);
  }
  ov.innerHTML = `<div style="color:#eee;font-size:var(--fs-sm);">
      ⚖ 블라인드 ELO · ${ELO.played + 1}번째 판
      <span style="opacity:.7;margin-left:10px;">←/→ 또는 클릭 · Space 무승부 · Esc 저장 후 종료</span></div>
    <div style="display:flex;gap:12px;align-items:center;justify-content:center;max-height:78vh;">
      <img data-elo="a" alt="후보 A" src="/setout?p=${encodeURIComponent(a)}"
        style="max-width:46vw;max-height:74vh;object-fit:contain;cursor:pointer;border:3px solid transparent;border-radius:var(--radius);">
      <img data-elo="b" alt="후보 B" src="/setout?p=${encodeURIComponent(b)}"
        style="max-width:46vw;max-height:74vh;object-fit:contain;cursor:pointer;border:3px solid transparent;border-radius:var(--radius);">
    </div><div style="color:#aaa;font-size:var(--fs-2xs);">A와 B 중 더 나은 결과만 고르세요. 이름과 기존 평가는 숨겨집니다.</div>`;
  ov.querySelectorAll('[data-elo]').forEach(image => {
    image.addEventListener('mouseenter', () => image.style.borderColor = 'var(--accent)');
    image.addEventListener('mouseleave', () => image.style.borderColor = 'transparent');
    image.addEventListener('click', () => eloPick(image.dataset.elo));
  });
}
async function eloPick(which){
  if(!ELO || !ELO.pair || ELO.busy) return;
  const session = ELO;
  session.busy = true;
  const [a,b] = session.pair;
  let r;
  try{
    r = await (await fetch('/api/evaluation_action', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        action:'blind-match', paths:[a,b],
        outcome:which === 'a' ? 'first' : (which === 'b' ? 'second' : 'tie'),
        decision_id:session.decision
      })
    })).json();
  }catch(error){
    r = {ok:false, error:String(error)};
  }
  if(!r.ok){
    $('expStat').textContent = r.error || '블라인드 평가를 저장하지 못했습니다.';
    const el = $('eloBg'); if(el) el.remove();
    ELO = null; return;
  }
  EXP.elo = Object.assign({}, EXP.elo || {}, (r.picks || {}).elo || {});
  EXP.elo_matches = Object.assign(
    {}, EXP.elo_matches || {}, (r.picks || {}).elo_matches || {});
  session.played++;
  session.busy = false;
  eloNext();
}
async function picksSave(){
  await fetch('/api/picks_save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      picked:[...EXP.picked], fav:[...EXP.fav],
      folders:EXP.folders || {}, ranks:EXP.ranks || {},
      ratings:EXP.ratings || {}, elo:EXP.elo || {},
      elo_matches:EXP.elo_matches || {}, tags:EXP.tags || {},
      memos:EXP.memos || {}, review_states:EXP.review_states || {}
    })});
}
let EXP_RECIPE_UNDO = null;
let EXP_APPLIED_RECIPE = null;
let EXP_APPLIED_PATH = '';
const EXP_RECIPE_KEYS = [
  'base_prompt','negative_prompt','style_name','nai_seed','char_slots','char_centers',
  'vibes','char_refs','model','width','height','cfg_scale','cfg_rescale','steps',
  'sampler','scheduler','variety','uc_preset','quality_toggle','smea','smea_dyn',
  'dynamic_thresholding','uncond_scale','controlnet_strength','prefer_brownian',
  'deliberate_euler_ancestral_bug','legacy_v3_extend','use_coords','position_mode'
];
function comparisonRecipeSnapshot(){
  const out = {};
  EXP_RECIPE_KEYS.forEach(key => {
    out[key] = JSON.parse(JSON.stringify(STATE[key] === undefined ? null : STATE[key]));
  });
  return out;
}
function comparisonRecipePaint(){
  $('basePrompt').value = STATE.base_prompt || '';
  $('negPrompt').value = STATE.negative_prompt || '';
  paintParams();
  renderSlots();
  renderRefs();
  tokens();
  save();
}
function expRecipeActions(message){
  if(!EXP_APPLIED_RECIPE) return;
  const hasCharacters = (EXP_APPLIED_RECIPE.char_slots || []).length > 0;
  $('expStat').innerHTML = `${esc(message)}`
    + ` <button type="button" id="expGoGenerate" class="primary">생성 화면으로</button>`
    + ` <button type="button" id="expPromoteStyle">그림체 묶음으로 저장</button>`
    + (hasCharacters
      ? ` <button type="button" id="expPromoteChars">캐릭터를 각각 저장</button>` : '')
    + ` <button type="button" id="expUndoRecipe">적용 전으로 되돌리기</button>`
    + ` <span class="hint">세팅은 이 비교에 포함되지 않아 그림에서 추정해 저장하지 않습니다.</span>`;
  $('expGoGenerate').addEventListener('click', () => setMode('preview'));
  $('expPromoteStyle').addEventListener('click', async () => {
    const suggested = EXP_APPLIED_RECIPE.style_name || '비교 결과 그림체';
    const name = prompt(
      '그림체 이름 (베이스+네거티브+생성 설정을 한 묶음으로 저장):',
      suggested
    );
    if(!name) return;
    const r = await (await fetch('/api/compare_promote', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:EXP_APPLIED_PATH, kind:'style', name})
    })).json();
    if(!r.ok){ expRecipeActions(r.error || '그림체를 저장하지 못했습니다.'); return; }
    if(r.styles) STYLES = r.styles;
    renderPresets(); renderLibrary();
    const lineage = r.lineage && r.lineage.verified
      ? ' · 결과 SHA·요청·설계도 계보 확인'
      : (r.lineage && r.lineage.warning ? ' · 구형 결과라 엄격한 계보 없음' : '');
    expRecipeActions((r.saved
      ? `그림체 '${r.names[0]}'에 베이스·네거티브·생성 설정을 함께 저장했습니다.`
      : `같은 내용의 그림체 '${r.names[0]}'가 있어 중복 저장하지 않았습니다.`)
      + lineage);
  });
  if(hasCharacters) $('expPromoteChars').addEventListener('click', async () => {
    const count = EXP_APPLIED_RECIPE.char_slots.length;
    if(!confirm(
      `이 결과의 캐릭터 ${count}명을 각각 전체 프롬프트로 저장할까요?\n`
      + '같은 외형·착의·네거티브가 이미 있으면 중복 저장하지 않습니다.'
    )) return;
    const r = await (await fetch('/api/compare_promote', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:EXP_APPLIED_PATH, kind:'characters'})
    })).json();
    if(!r.ok){ expRecipeActions(r.error || '캐릭터를 저장하지 못했습니다.'); return; }
    if(r.characters) STATE.characters = r.characters;
    if(r.revision != null) STATE._revision = r.revision;
    renderLibrary();
    const lineage = r.lineage && r.lineage.verified
      ? ' · 결과 SHA·요청·설계도 계보 확인'
      : (r.lineage && r.lineage.warning ? ' · 구형 결과라 엄격한 계보 없음' : '');
    expRecipeActions(
      `캐릭터 ${r.saved}명 저장`
      + (r.existing ? ` · 같은 내용 ${r.existing}명은 중복 생략` : '')
      + ` (${(r.names || []).join(', ')})`
      + lineage
    );
  });
  $('expUndoRecipe').addEventListener('click', () => {
    if(!EXP_RECIPE_UNDO) return;
    Object.entries(EXP_RECIPE_UNDO).forEach(([key, value]) => {
      STATE[key] = JSON.parse(JSON.stringify(value));
    });
    EXP_RECIPE_UNDO = null;
    EXP_APPLIED_RECIPE = null;
    EXP_APPLIED_PATH = '';
    comparisonRecipePaint();
    $('expStat').textContent = '비교 결과를 적용하기 전 설정으로 되돌렸습니다.';
  });
}
async function expApplyPickedRecipe(){
  const visible = await expEnsureAll();
  const chosen = visible.filter(file => EXP.picked.has(file.path));
  if(chosen.length !== 1){
    $('expStat').textContent = chosen.length
      ? `이 폴더에서 선별한 ${chosen.length}장 중 적용할 한 장만 남겨주세요.`
      : '이 폴더에서 비교 결과 한 장을 먼저 선별해주세요.';
    return;
  }
  const r = await (await fetch('/api/compare_recipe', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:chosen[0].path})})).json();
  if(!r.ok){ $('expStat').textContent = r.error || '원문 레시피를 읽지 못했습니다.'; return; }
  const recipe = r.recipe || {};
  const people = (recipe.char_slots || []).length;
  if(!confirm(
    `선택한 결과의 그림체·네거티브·생성 설정·시드·캐릭터 ${people}명을 현재 생성에 적용할까요?\n`
    + '적용 직후 이 화면에서 되돌릴 수 있습니다.'
  )) return;
  EXP_RECIPE_UNDO = comparisonRecipeSnapshot();
  EXP_APPLIED_RECIPE = JSON.parse(JSON.stringify(recipe));
  EXP_APPLIED_PATH = chosen[0].path;
  STATE.base_prompt = recipe.base_prompt || '';
  STATE.negative_prompt = recipe.negative_prompt || '';
  STATE.style_name = recipe.style_name || '';
  STATE.nai_seed = Number(recipe.nai_seed) || 0;
  STATE.char_slots = JSON.parse(JSON.stringify(recipe.char_slots || []));
  STATE.char_centers = JSON.parse(JSON.stringify(recipe.char_centers || []));
  if(recipe.include_refs){
    STATE.vibes = JSON.parse(JSON.stringify(recipe.vibes || []));
    STATE.char_refs = JSON.parse(JSON.stringify(recipe.char_refs || []));
  }else{
    STATE.vibes = (STATE.vibes || []).map(item => Object.assign({}, item, {enabled:false}));
    STATE.char_refs = (STATE.char_refs || []).map(item => Object.assign({}, item, {enabled:false}));
  }
  Object.entries(recipe.settings || {}).forEach(([key, value]) => {
    if(EXP_RECIPE_KEYS.includes(key) && value !== null && value !== undefined){
      STATE[key] = value;
    }
  });
  comparisonRecipePaint();
  expRecipeActions('선별 결과 원문을 현재 생성에 적용했습니다.');
}
/* 크게 보기 — 여기서 ←→ F C Esc 가 먹는다 */
function expOpen(i){
  const vis = expVisible();
  if(i < 0 || i >= vis.length) return;
  EXP.open = i;
  const f = vis[i];
  let ov = $('expViewer');
  if(!ov){
    ov = document.createElement('div'); ov.id = 'expViewer';
    ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:#000c;display:flex;'
      + 'flex-direction:column;align-items:center;justify-content:center;gap:8px;padding:14px;';
    ov.addEventListener('click', e => { if(e.target === ov) expClose(); });
    document.body.appendChild(ov);
  }
  const score = Number((EXP.ratings || {})[f.path] || 0);
  const elo = Number((EXP.elo || {})[f.path] || 0);
  const eloMatches = Number((EXP.elo_matches || {})[f.path] || 0);
  const tags = (EXP.tags || {})[f.path] || [];
  const memo = (EXP.memos || {})[f.path] || '';
  const reviewState = (EXP.review_states || {})[f.path] || 'candidate';
  ov.innerHTML = `<img src="/setout?p=${encodeURIComponent(f.path)}" alt=""
      style="max-width:96vw;max-height:82vh;object-fit:contain;border-radius:var(--radius);">
    <div class="bar" style="background:var(--paper);padding:7px 11px;border-radius:var(--radius);flex-wrap:wrap;">
      <span class="n">${i+1} / ${vis.length}</span>
      <b style="font-size:var(--fs-xs);">${esc(f.name)}</b>
      <span class="tag">${EXP.picked.has(f.path)?'✔ 선별됨':'F = 선별'}</span>
      <span class="tag">${EXP.cmp.has(f.path)?'비교함에 있음':'C = 비교함'}</span>
      <span class="tag">${EXP.fav.has(f.path)?'⭐':'S = 즐겨찾기'}</span>
      ${elo ? `<span class="tag">⚖ ELO ${Math.round(elo)} · ${eloMatches}판</span>` : ''}
      <select id="expRate" aria-label="이 그림 별점" style="width:auto;">
        <option value="0"${score===0?' selected':''}>별점 없음</option>
        ${[1,2,3,4,5].map(n => `<option value="${n}"${score===n?' selected':''}>${'★'.repeat(n)}</option>`).join('')}
      </select>
      <input type="text" id="expTagInput" value="${escA(tags.join(', '))}"
        placeholder="판단 태그 (쉼표로 구분)" style="width:220px;">
      <button type="button" id="expTagSave">태그 저장</button>
      <span class="hint">←→ 넘기기 · Esc 닫기</span>
    </div>
    <div class="bar" style="max-width:96vw;width:min(920px,96vw);background:var(--paper);
      padding:7px 11px;border-radius:var(--radius);align-items:flex-start;">
      <textarea id="expMemo" rows="2" placeholder="이 결과에서 확인한 점"
        style="flex:1;min-width:220px;resize:vertical;">${esc(memo)}</textarea>
      <select id="expLifecycle" aria-label="결과 검토 상태" style="width:auto;">
        <option value="candidate"${reviewState==='candidate'?' selected':''}>후보</option>
        <option value="confirmed"${reviewState==='confirmed'?' selected':''}>확정</option>
        <option value="shared"${reviewState==='shared'?' selected':''}>공유</option>
        <option value="archived"${reviewState==='archived'?' selected':''}>보관</option>
      </select>
      <button type="button" id="expEvaluationSave">메모·상태 저장</button>
    </div>
    <div class="result-actions" style="max-width:96vw;background:var(--paper);padding:7px 11px;
      margin:0;border:0;border-radius:var(--radius);">
      <span class="label">이 결과로</span>
      <button type="button" data-exp-result="vibe">바이브</button>
      <button type="button" data-exp-result="cref">캐릭터 레퍼런스</button>
      <button type="button" data-exp-result="i2i">img2img·인페인트</button>
      <button type="button" data-exp-result="outpaint">Outpaint</button>
      <button type="button" id="expRerunCell"
        title="직접 고른 자료·축 비교 결과만 같은 seed로 한 장 더 만듭니다">이 셀 다시 생성</button>
      <span class="result-action-msg" id="expResultMsg"></span>
    </div>`;
  $('expRate').addEventListener('change', async () => {
    const value = Number($('expRate').value) || 0;
    if(value) EXP.ratings[f.path] = value;
    else delete EXP.ratings[f.path];
    await picksSave(); expDraw(); expOpen(EXP.open);
  });
  $('expTagSave').addEventListener('click', async () => {
    const values = [...new Set(
      $('expTagInput').value.split(',').map(x => x.trim().slice(0,40)).filter(Boolean)
    )].slice(0,12);
    if(values.length) EXP.tags[f.path] = values;
    else delete EXP.tags[f.path];
    await picksSave(); expDraw(); expOpen(EXP.open);
  });
  $('expEvaluationSave').addEventListener('click', async () => {
    const nextMemo = $('expMemo').value;
    const nextState = $('expLifecycle').value;
    if(nextMemo) EXP.memos[f.path] = nextMemo;
    else delete EXP.memos[f.path];
    await picksSave();
    if(nextState !== reviewState){
      const r = await (await fetch('/api/evaluation_action', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          action:'lifecycle', paths:[f.path], state:nextState
        })
      })).json();
      if(!r.ok){ alert(r.error || '검토 상태를 저장하지 못했습니다.'); return; }
      EXP.review_states = Object.assign(
        {}, EXP.review_states || {}, (r.picks || {}).review_states || {});
    }
    $('expEvaluationSave').textContent = '저장됨';
  });
  ov.querySelectorAll('[data-exp-result]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.expResult;
    const url = '/setout?p=' + encodeURIComponent(f.path);
    const msg = $('expResultMsg');
    if(action === 'i2i') await resultToI2I(url, f.name, msg);
    else if(action === 'outpaint') await resultToI2I(url, f.name, msg, null, 'outpaint');
    else {
      const done = await resultToReference(url, f.name, action, msg);
      if(done) expClose();
    }
  }));
  $('expRerunCell').addEventListener('click', async () => {
    if(!confirm('이 선택 실험 셀을 같은 seed로 한 장 더 생성할까요?')) return;
    const result = await (await fetch('/api/compare_rerun', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:f.path})
    })).json();
    $('expStat').textContent = result.ok
      ? '한 셀 재실행을 시작했습니다. 완료되면 이 폴더에 새 결과가 추가됩니다.'
      : (result.error || '한 셀 재실행을 시작하지 못했습니다.');
  });
}
function expClose(){ const o = $('expViewer'); if(o) o.remove(); EXP.open = -1; }
window.addEventListener('keydown', async e => {
  if(ELO){
    if(e.key === 'ArrowLeft'){ e.preventDefault(); eloPick('a'); return; }
    if(e.key === 'ArrowRight'){ e.preventDefault(); eloPick('b'); return; }
    if(e.key === ' '){ e.preventDefault(); eloPick('both'); return; }
    if(e.key === 'Escape'){
      e.preventDefault(); const el = $('eloBg'); if(el) el.remove();
      $('expStat').textContent = `⚖ 블라인드 ELO 중단 — 이번 세션 ${ELO.played}판은 저장됨`;
      ELO = null; expDraw(); return;
    }
    return;
  }
  /* 월드컵이 열려 있으면 그쪽이 키를 먼저 먹는다 */
  if(CUP){
    if(e.key === 'ArrowLeft'){ e.preventDefault(); cupPick('a'); return; }
    if(e.key === 'ArrowRight'){ e.preventDefault(); cupPick('b'); return; }
    if(e.key === ' '){ e.preventDefault(); cupPick('both'); return; }
    if(e.key === 'Escape'){ e.preventDefault(); const el = $('cupBg'); if(el) el.remove(); CUP = null; return; }
    return;
  }
  if(EXP.open < 0) return;
  const vis = expVisible(); const f = vis[EXP.open]; if(!f) return;
  const k = e.key.toLowerCase();
  if(e.key === 'Escape'){ expClose(); return; }
  if(e.key === 'ArrowRight'){
    e.preventDefault();
    if(EXP.open >= vis.length-1 && EXP.files.length < EXP.total) await expFetchMore(false);
    expOpen(Math.min(EXP.open+1, expVisible().length-1)); return;
  }
  if(e.key === 'ArrowLeft'){ e.preventDefault(); expOpen(Math.max(EXP.open-1, 0)); return; }
  if(k === 'f'){ e.preventDefault();
    EXP.picked.has(f.path) ? EXP.picked.delete(f.path) : EXP.picked.add(f.path);
    await picksSave(); expDraw(); expOpen(EXP.open); return; }
  if(k === 's'){ e.preventDefault();
    EXP.fav.has(f.path) ? EXP.fav.delete(f.path) : EXP.fav.add(f.path);
    await picksSave(); expDraw(); expOpen(EXP.open); return; }
  if(k === 'c'){ e.preventDefault();
    EXP.cmp.has(f.path) ? EXP.cmp.delete(f.path) : EXP.cmp.add(f.path);
    expDraw(); expOpen(EXP.open); return; }
});
if($('expUp')){
  $('expUp').addEventListener('click', () => expLoad(EXP.dir.includes('/')
    ? EXP.dir.slice(0, EXP.dir.lastIndexOf('/')) : ''));
  $('expReload').addEventListener('click', () => expLoad());
  ['expOnlyPick','expOnlyFav'].forEach(id => $(id).addEventListener('change', () => expLoad(EXP.dir)));
  $('expSize').addEventListener('change', expDraw);
  $('expGroupFilter').addEventListener('change', expDraw);
  $('expGroupSave').addEventListener('click', async () => {
    const name = $('expGroupName').value.trim().slice(0,40);
    if(!name){ $('expStat').textContent = '후보군 이름을 입력해주세요.'; return; }
    const visible = await expEnsureAll();
    const chosen = visible.map(file => file.path).filter(path => EXP.picked.has(path));
    if(!chosen.length){ $('expStat').textContent = '이 폴더에서 후보군에 넣을 그림을 먼저 선별해주세요.'; return; }
    const r = await (await fetch('/api/evaluation_action', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        action:'fixed-board', paths:chosen, board:name, member:true
      })
    })).json();
    if(!r.ok){ $('expStat').textContent = r.error || '후보군 저장 실패'; return; }
    EXP.folders = (r.picks || {}).folders || EXP.folders;
    expPaintGroups(); $('expGroupFilter').value = name; expDraw();
    $('expStat').textContent = `'${name}' 후보군에 선별 ${chosen.length}장을 이름표로 연결했습니다.`;
  });
  $('expGroupDelete').addEventListener('click', async () => {
    const name = $('expGroupFilter').value;
    if(!name){ $('expStat').textContent = '삭제할 후보군 이름표를 선택해주세요.'; return; }
    if(!confirm(`후보군 '${name}' 이름표를 지울까요? 원본 그림과 선별 표시는 그대로 남습니다.`)) return;
    const members = [...(EXP.folders[name] || [])];
    const r = members.length ? await (await fetch('/api/evaluation_action', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        action:'fixed-board', paths:members, board:name, member:false
      })
    })).json() : {ok:true, picks:{folders:EXP.folders}};
    if(!r.ok){ $('expStat').textContent = r.error || '후보군 삭제 실패'; return; }
    EXP.folders = (r.picks || {}).folders || EXP.folders;
    delete EXP.folders[name];
    await picksSave(); expPaintGroups(); expDraw();
    $('expStat').textContent = `'${name}' 후보군 이름표만 지웠습니다.`;
  });
  $('expCmpClear').addEventListener('click', () => { EXP.cmp.clear(); expDraw(); });
  if($('expCup')) $('expCup').addEventListener('click', cupStart);
  if($('expElo')) $('expElo').addEventListener('click', eloStart);
  if($('expApplyPicked')) $('expApplyPicked').addEventListener(
    'click', expApplyPickedRecipe);
  $('expCompare').addEventListener('click', () => {
    if(!EXP.cmp.size){ $('expStat').textContent = '비교함이 비어 있습니다 (그림을 열고 C)'; return; }
    let ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:#000d;display:flex;'
      + 'align-items:center;gap:6px;overflow:auto;padding:14px;';
    ov.innerHTML = [...EXP.cmp].map(p => `<img src="/setout?p=${encodeURIComponent(p)}"
      style="max-height:88vh;object-fit:contain;border-radius:var(--radius);">`).join('')
      + '<div class="hint" style="position:fixed;left:14px;bottom:10px;color:#fff;">아무 데나 눌러 닫기</div>';
    ov.addEventListener('click', () => ov.remove());
    document.body.appendChild(ov);
  });
  const regen = async (paths) => {
    if(!paths.length){ $('expStat').textContent = '복구할 그림을 먼저 고르세요.'; return; }
    const r = await (await fetch('/api/regen', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({paths, mode: $('regenMode').value,
                            strength: Number($('regenStrength').value)})})).json();
    $('expStat').textContent = r.ok
      ? `${r.count}장 복구 시작 (${r.mode === 'img2img' ? 'img2img' : '같은 설정'}) — 생성 탭 미리보기에 나옵니다`
      : (r.error || '실패');
  };
  $('regenPicked').addEventListener('click', async () => {
    const vis = await expEnsureAll();
    regen(vis.map(f => f.path).filter(p => EXP.picked.has(p)));
  });
  $('regenAll').addEventListener('click', async () => {
    const paths = (await expEnsureAll()).map(f => f.path);
    if(paths.length > 20 && !confirm(`${paths.length}장을 복구합니다. 시간이 오래 걸립니다. 계속할까요?`)) return;
    regen(paths);
  });
  $('expDelUnpicked').addEventListener('click', async () => {
    const vis = await expEnsureAll();
    const targets = vis.map(f => f.path).filter(p => !EXP.picked.has(p));
    if(!targets.length){ $('expStat').textContent = '지울 것이 없습니다 (전부 선별됨)'; return; }
    if(!confirm(`선별 안 된 ${targets.length}장을 휴지통으로 옮길까요?\n바로 다음 안내에서 되돌릴 수 있습니다.`)) return;
    const r = await (await fetch('/api/picks_del', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({targets, keep:[...EXP.picked]})})).json();
    if(!r.ok){ $('expStat').textContent = r.error || '실패'; return; }
    $('expStat').innerHTML = `${r.deleted}장 휴지통으로 이동`
      + (r.batch_id ? ` <button id="expUndoDelete" class="primary">되돌리기</button>` : '');
    if(r.batch_id) $('expUndoDelete').addEventListener('click', async () => {
      const rr = await (await fetch('/api/picks_restore', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({batch_id:r.batch_id})})).json();
      $('expStat').textContent = rr.ok ? `${rr.restored}장 복원됨` : (rr.error || '복원 실패');
      expLoad();
    });
    expLoad();
  });
}

/* ── 알림 (다 끝났을 때) ────────────────────────────────────────────
   565장은 몇 시간이 걸린다. 자리를 떠도 끝난 걸 알 수 있어야 한다.
   소리는 WebAudio 로 직접 만든다 — 음원 파일을 배포본에 넣지 않으려고. */
function beep(){
  try{
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    [880, 1180, 1480].forEach((f, i) => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sine'; o.frequency.value = f;
      o.connect(g); g.connect(ac.destination);
      const t = ac.currentTime + i * 0.18;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.22, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.17);
      o.start(t); o.stop(t + 0.18);
    });
    setTimeout(() => ac.close(), 900);
  }catch(e){}
}
function notifyDone(text){
  const u = STATE.ui || {};
  if(u.notify_sound) beep();
  if(u.notify_system){
    if(Notification.permission === 'granted') new Notification('NAI 배치 생성기', {body: text});
    else if(Notification.permission !== 'denied')
      Notification.requestPermission().then(p => {
        if(p === 'granted') new Notification('NAI 배치 생성기', {body: text});
      });
  }
}
if($('notifySound')){
  ['notifySound','notifySystem'].forEach(id => {
    const key = id === 'notifySound' ? 'notify_sound' : 'notify_system';
    const e = $(id);
    e.addEventListener('change', () => {
      STATE.ui = STATE.ui || {}; STATE.ui[key] = e.checked;
      if(e.checked && key === 'notify_system' && Notification.permission === 'default')
        Notification.requestPermission();
      save();
    });
  });
  $('notifyTest').addEventListener('click', () => {
    notifyDone('알림 시험입니다 — 이렇게 알려 드립니다.');
    $('notifyMsg').textContent = '보냈습니다 (소리·알림 중 켜 둔 것)';
  });
}

/* ── 모자이크 칠하기 (내 컴퓨터에서 · 공짜) ─────────────────────────
   칠한 자리만 블록 평균색으로 덮는다. 원본 픽셀을 따로 들고 있다가
   '처음으로' 를 누르면 되돌린다. */
let MOS = {img:null, painting:false};
function mosLoad(file){
  const fr = new FileReader();
  fr.onload = () => {
    const im = new Image();
    im.onload = () => {
      MOS.img = im;
      const c = $('mosCanvas');
      c.width = im.width; c.height = im.height;
      c.getContext('2d').drawImage(im, 0, 0);
      $('mosStage').classList.remove('hidden');
      $('mosMsg').textContent = `${im.width}×${im.height} — 가릴 곳을 칠하세요`;
    };
    im.src = fr.result;
  };
  fr.readAsDataURL(file);
}
function mosDab(x, y){
  const c = $('mosCanvas'), ctx = c.getContext('2d');
  const bs = Number($('mosBlock').value), r = Number($('mosBrush').value) / 2;
  const x0 = Math.max(0, Math.floor((x - r) / bs) * bs);
  const y0 = Math.max(0, Math.floor((y - r) / bs) * bs);
  const x1 = Math.min(c.width, Math.ceil((x + r) / bs) * bs);
  const y1 = Math.min(c.height, Math.ceil((y + r) / bs) * bs);
  if(x1 <= x0 || y1 <= y0) return;
  const img = ctx.getImageData(x0, y0, x1 - x0, y1 - y0);
  const d = img.data, w = x1 - x0;
  for(let by = 0; by < y1 - y0; by += bs){
    for(let bx = 0; bx < w; bx += bs){
      /* 이 블록의 중심이 붓 원 안에 있을 때만 */
      const cx = x0 + bx + bs / 2, cy = y0 + by + bs / 2;
      if((cx - x) ** 2 + (cy - y) ** 2 > r * r) continue;
      let sr = 0, sg = 0, sb = 0, n = 0;
      for(let yy = by; yy < Math.min(by + bs, y1 - y0); yy++){
        for(let xx = bx; xx < Math.min(bx + bs, w); xx++){
          const i = (yy * w + xx) * 4;
          sr += d[i]; sg += d[i+1]; sb += d[i+2]; n++;
        }
      }
      if(!n) continue;
      sr = sr / n | 0; sg = sg / n | 0; sb = sb / n | 0;
      for(let yy = by; yy < Math.min(by + bs, y1 - y0); yy++){
        for(let xx = bx; xx < Math.min(bx + bs, w); xx++){
          const i = (yy * w + xx) * 4;
          d[i] = sr; d[i+1] = sg; d[i+2] = sb;
        }
      }
    }
  }
  ctx.putImageData(img, x0, y0);
}
if($('mosDrop')){
  const c = $('mosCanvas');
  const at = e => {
    const r = c.getBoundingClientRect();
    return [(e.clientX - r.left) * (c.width / r.width), (e.clientY - r.top) * (c.height / r.height)];
  };
  c.addEventListener('pointerdown', e => { MOS.painting = true; c.setPointerCapture(e.pointerId); mosDab(...at(e)); });
  c.addEventListener('pointermove', e => { if(MOS.painting) mosDab(...at(e)); });
  ['pointerup','pointercancel','pointerleave'].forEach(ev =>
    c.addEventListener(ev, () => MOS.painting = false));
  $('mosBlock').addEventListener('input', () => $('mosBlockN').textContent = $('mosBlock').value + 'px');
  $('mosDrop').addEventListener('click', () => $('mosFile').click());
  $('mosFile').addEventListener('change', () => {
    if($('mosFile').files[0]) mosLoad($('mosFile').files[0]);
    $('mosFile').value = '';
  });
  ['dragover','dragenter'].forEach(ev => $('mosDrop').addEventListener(ev, e => {
    e.preventDefault(); $('mosDrop').style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => $('mosDrop').addEventListener(ev, e => {
    e.preventDefault(); $('mosDrop').style.borderColor = ''; }));
  $('mosDrop').addEventListener('drop', e => {
    const f = [...(e.dataTransfer.files || [])].find(x => /image\/(png|webp)/.test(x.type));
    if(f) mosLoad(f);
  });
  $('mosReset').addEventListener('click', () => {
    if(!MOS.img) return;
    $('mosCanvas').getContext('2d').drawImage(MOS.img, 0, 0);
    $('mosMsg').textContent = '되돌렸습니다';
  });
  $('mosSave').addEventListener('click', async () => {
    if(!MOS.img){ $('mosMsg').textContent = '먼저 그림을 넣어주세요.'; return; }
    const blob = await new Promise(r => $('mosCanvas').toBlob(r, 'image/png'));
    const r = await (await fetch('/api/mosaic_save', {method:'POST',
      headers:{'X-Filename': encodeURIComponent('mosaic.png')}, body: blob})).json();
    $('mosMsg').textContent = r.ok ? `저장됨 → output/모자이크/${r.file}` : (r.error || '실패');
  });
}

/* ── 밴 예방 · 속도 ────────────────────────────────────────────────── */
const PACE_FIELDS = {paceDmin:'delay_min', paceDmax:'delay_max', paceDaily:'daily_cap',
  paceSoftEvery:'soft_every', paceSoftSec:'soft_seconds',
  paceCoolEvery:'cool_every', paceCoolSec:'cool_seconds'};
const PACE_DEF = {delay_min:5.5, delay_max:11.5, daily_cap:7000,
  soft_every:350, soft_seconds:30, cool_every:3000, cool_seconds:300};
function paintPace(){
  const p = Object.assign({}, PACE_DEF, STATE.pace || {});
  Object.entries(PACE_FIELDS).forEach(([id, k]) => { if($(id)) $(id).value = p[k]; });
  paceCalc();
}
function paceCalc(){
  const p = Object.assign({}, PACE_DEF, STATE.pace || {});
  const avg = (Number(p.delay_min) + Number(p.delay_max)) / 2;
  const per100 = avg * 100
    + (p.soft_every ? Math.floor(100 / p.soft_every) * Number(p.soft_seconds) : 0)
    + (p.cool_every ? Math.floor(100 / p.cool_every) * Number(p.cool_seconds) : 0);
  const m = Math.round(per100 / 60);
  $('paceCalc').textContent = `지금 값이면 100장에 대략 ${m}분 `
    + `(장당 평균 ${avg.toFixed(1)}초 + 쉬는 시간). 하루 ${p.daily_cap}장까지.`;
}
Object.entries(PACE_FIELDS).forEach(([id, k]) => {
  const e = $(id); if(!e) return;
  e.addEventListener('change', () => {
    STATE.pace = Object.assign({}, PACE_DEF, STATE.pace || {});
    STATE.pace[k] = Number(e.value);
    if(STATE.pace.delay_max < STATE.pace.delay_min){
      STATE.pace.delay_max = STATE.pace.delay_min;
      $('paceDmax').value = STATE.pace.delay_max;
    }
    paceCalc(); save();
  });
});

/* ── 메타데이터 제거 ────────────────────────────────────────────────── */
async function stripFiles(files){
  const ok = [], bad = [];
  for(const f of files){
    $('stripMsg').textContent = `${f.name} 지우는 중...`;
    try{
      const r = await (await fetch('/api/strip_meta', {method:'POST',
        headers:{'X-Filename': encodeURIComponent(f.name),
                 'X-MaxSide': $('stripSide').value,
                 'X-Quality': $('stripQ').value,
                 'X-ForceWebp': $('stripWebp').checked ? '1' : '0'}, body: f})).json();
      if(r.ok) ok.push(r.file + ` (${Math.round(r.before/1024)}→${Math.round(r.bytes/1024)}KB)`
        + (r['남은메타'] ? ' ⚠남은 메타 있음' : ''));
      else bad.push(f.name + ': ' + (r.error || '실패'));
    }catch(e){ bad.push(f.name + ': ' + e); }
  }
  $('stripMsg').textContent = (ok.length ? `${ok.length}장 완료 → output/메타제거/ (${ok[0]}${ok.length>1?' 외':''})` : '')
    + (bad.length ? ` · 실패 ${bad.length}건: ${bad[0]}` : '');
}
if($('stripDrop')){
  $('stripDrop').addEventListener('click', () => $('stripFile').click());
  $('stripFile').addEventListener('change', () => {
    stripFiles([...$('stripFile').files]); $('stripFile').value = '';
  });
  ['dragover','dragenter'].forEach(ev => $('stripDrop').addEventListener(ev, e => {
    e.preventDefault(); $('stripDrop').style.borderColor = 'var(--accent)';
  }));
  ['dragleave','drop'].forEach(ev => $('stripDrop').addEventListener(ev, e => {
    e.preventDefault(); $('stripDrop').style.borderColor = '';
  }));
  $('stripDrop').addEventListener('drop', e => {
    const fs = [...(e.dataTransfer.files || [])].filter(f => /image\/(png|webp)/.test(f.type));
    if(fs.length) stripFiles(fs);
  });
}

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

/* ── 세팅 내보내기 / 가져오기 / 세트 대표 그림 ────────────────────
   세팅은 '세팅/ 폴더의 파일' 이므로 주고받기는 파일 단위로 한다. */
$('setExport').addEventListener('click', () => {
  /* 켜 둔 세팅만 내보낸다. 하나도 안 켜 뒀으면 전부 */
  const on = SETTINGS.filter(st => stState(st.name).use !== false).map(st => st.name);
  const q = (on.length && on.length < SETTINGS.length)
    ? on.map(n => 'name=' + encodeURIComponent(n)).join('&') : '';
  $('setMsg').textContent = (q ? `${on.length}개` : '전체') + ' 내보내는 중...';
  window.location.href = '/api/setting_export' + (q ? '?' + q : '');
  setTimeout(() => { $('setMsg').textContent = '내보냄 ✓'; }, 800);
});
/* ── 자료팩 넣기 ───────────────────────────────────────────────────
   배포본에 수집물을 넣지 않으므로 여기로 받는다. 서버가 합쳐 주고(덮어쓰지 않음)
   무엇이 몇 건 들어왔는지 그대로 보여 준다. */
function esc(s){ return String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

/* 가져온 기록 — 넣고 나서 정리하려면 '이번에 무엇이 들어왔나' 를 볼 수 있어야 한다.
   되돌리기는 **그때 새로 들어온 것만** 뺀다 (원래 갖고 있던 자료는 안 건드린다). */
function renderPackLog(log){
  const host = $('packLog'); if(!host) return;
  if(!log || !log.length){ host.innerHTML = ''; return; }
  host.innerHTML = '<div class="hint" style="margin-bottom:4px;">장착한 자료팩</div>' +
    log.map(b => `<div class="bar" style="gap:8px;align-items:flex-start;
        padding:6px 0;border-top:1px solid var(--line);">
      <div style="flex:1;min-width:0;">
        <div style="font-size:var(--fs-sm);">${esc(b.at)} · ${esc(b.pack_name || b.file)}
          <b>새로 ${b['새로']||0}</b></div>
        <div class="hint" style="font-size:var(--fs-2xs);">${esc(b['요약']||'')}
          ${b.content_sha256 ? ` · SHA-256 ${esc(b.content_sha256.slice(0,12))}` : ''}</div>
      </div>
      <button data-undo="${esc(b.id)}" title="이 팩으로 새로 들어온 것만 뺍니다">해제</button>
    </div>`).join('');
  host.querySelectorAll('[data-undo]').forEach(btn => btn.addEventListener('click', async () => {
    if(!confirm('이 자료팩으로 새로 들어온 것만 뺍니다. 개인 자료는 그대로 둡니다. 해제할까요?')) return;
    btn.disabled = true;
    const r = await (await fetch('/api/pack_undo', {method:'POST',
      body: JSON.stringify({id: btn.dataset.undo})})).json();
    $('packMsg').innerHTML = r.error ? esc(r.error) : (r.report||[]).map(esc).join('<br>');
    renderPackLog(r.log); await reloadConfig();
  }));
}

async function loadDataStorageStatus(){
  const host = $('dataStorageStatus'); if(!host) return;
  try{
    const r = await (await fetch('/api/data_storage')).json();
    if(!r.ok){ host.textContent = r.error || '자료 저장 위치를 확인하지 못했습니다.'; return; }
    const where = r.separated ? '<b>프로그램과 분리됨</b>' : '<b>소스·휴대 모드</b>';
    const idx = r.index
      ? ` · 마지막 색인 ${Number(r.index.files||0).toLocaleString()}개`
        + ` / ${(Number(r.index.bytes||0)/1024/1024).toFixed(1)}MB`
        + ` · ${esc(r.index.generated_at||'')}`
      : ' · 아직 만든 색인 없음';
    const moved = r.migration && Number(r.migration.copied||0)
      ? ` · 옛 설치 자료 ${Number(r.migration.copied).toLocaleString()}개를 원본을 남긴 채 복사함`
      : '';
    host.innerHTML = `<div>${where}${idx}</div>
      <div style="margin-top:3px;">개인 자료 폴더
        <span style="font-family:var(--mono);word-break:break-all;">${esc(r.data_dir)}</span>
        ${moved}</div>`;
  }catch(e){ host.textContent = '자료 저장 위치 확인 실패: ' + e; }
}

if($('dataIndexBuild')) $('dataIndexBuild').addEventListener('click', async () => {
  const btn = $('dataIndexBuild');
  btn.disabled = true;
  $('dataStorageStatus').textContent = '원본을 바꾸지 않고 파일별 SHA-256 색인을 만드는 중입니다...';
  try{
    const r = await (await fetch('/api/data_index_rebuild', {method:'POST', body:'{}'})).json();
    if(!r.ok){ $('dataStorageStatus').textContent = r.error || '자료 색인 생성 실패'; return; }
    await loadDataStorageStatus();
  }catch(e){ $('dataStorageStatus').textContent = '자료 색인 생성 실패: ' + e; }
  finally{ btn.disabled = false; }
});
if($('dataOriginsShow')) $('dataOriginsShow').addEventListener('click', async () => {
  const host = $('dataOriginsStatus');
  host.classList.remove('hidden');
  host.textContent = '이미지 내용 해시와 원문 주소 장부를 확인하는 중입니다.';
  try{
    const r = await (await fetch('/api/img_origins', {cache:'no-store'})).json();
    if(!r.ok){ host.textContent = r.error || '출처 장부를 읽지 못했습니다.'; return; }
    const examples = (r['예시'] || []).slice(0,5).map(item =>
      `${esc(item.sha256)} · 주소 ${(item.urls||[]).length}개`).join('<br>');
    host.innerHTML = `<b>내용이 확인된 그림 ${Number(r['그림']||0).toLocaleString()}개</b>`
      + ` · 같은 그림을 가리키는 주소가 여러 개인 항목 ${Number(r['주소여럿']||0).toLocaleString()}개`
      + ` · 중복 주소 ${Number(r['낭비주소']||0).toLocaleString()}개`
      + (examples ? `<div style="margin-top:4px;">${examples}</div>` : '');
  }catch(error){ host.textContent = '출처 장부 확인 실패: ' + error; }
});
var DATA_INVENTORY_OFFSET = 0;
if($('dataInventoryShow')) $('dataInventoryShow').addEventListener('click', async () => {
  const button = $('dataInventoryShow');
  const host = $('dataInventoryStatus');
  host.classList.remove('hidden');
  host.textContent = '보유 폴더 색인을 복원 대기 목록으로 여는 중입니다.';
  try{
    const r = await (await fetch(
      '/api/folder_inventory?offset=' + DATA_INVENTORY_OFFSET + '&limit=20',
      {cache:'no-store'})).json();
    if(!r.ok){ host.textContent = r.error || '보유 폴더 목록을 읽지 못했습니다.'; return; }
    if(r.empty){ host.textContent = '색인이 없습니다. 먼저 자료 색인을 만들어주세요.'; return; }
    window.LAST_RESTORATION_BATCH = r.restoration_queue;
    host.innerHTML = `<b>${Number(r.total||0).toLocaleString()}개 파일</b> · `
      + `원본을 옮기거나 읽어 들이지 않은 복원 대기 목록`
      + `<div style="margin-top:4px;font-family:var(--mono);">`
      + (r.items||[]).map(item =>
        `${esc(item.name)} · ${(Number(item.size||0)/1024).toFixed(1)}KB`).join('<br>')
      + `</div>`;
    DATA_INVENTORY_OFFSET = r.more ? Number(r.next_offset||0) : 0;
    button.textContent = r.more ? '보유 폴더 다음 목록' : '보유 폴더 처음부터';
  }catch(error){ host.textContent = '보유 폴더 목록 확인 실패: ' + error; }
});

var METADATA_AUDIT_OFFSET = 0;
function renderMetadataAudit(r, append=false){
  const host = $('metadataAuditStatus');
  const found = $('metadataAuditFound');
  const more = $('metadataAuditMore');
  if(!host || !found) return;
  if(!r || !r.ok){
    host.textContent = (r && r.error) || '메타데이터 감사 기록을 읽지 못했습니다.';
    found.innerHTML = '';
    if(more) more.classList.add('hidden');
    return;
  }
  if(r.empty){
    host.textContent = '아직 감사 기록이 없습니다. 자료 색인을 만든 뒤 처음부터 확인하세요.';
    found.innerHTML = '';
    if(more) more.classList.add('hidden');
    return;
  }
  const s = r.summary || {};
  const c = s.status_counts || {};
  const labels = {
    pending:'대기', running:'확인 중', paused:'다음 묶음 대기',
    completed:'완료', partial:'일부 오류',
  };
  host.textContent = `${labels[s.status] || s.status || '대기'} · `
    + `${Number(s.cursor||0).toLocaleString()}/${Number(s.total||0).toLocaleString()}`
    + ` · 복원 후보 ${Number(c.found||0).toLocaleString()}`
    + ` · 메타 없음 ${Number(c.none||0).toLocaleString()}`
    + ` · 오류 ${Number(c.error||0).toLocaleString()}`;
  const buttons = (r.found || []).map(item =>
    `<button type="button" data-audit-candidate="${escA(item.path)}"
      data-audit-sha="${escA(item.sha256)}" title="원본을 다시 SHA 검증한 뒤 읽기 전용으로 확인">
      ${esc(item.path)}</button>`).join('');
  if(append) found.insertAdjacentHTML('beforeend', buttons);
  else found.innerHTML = buttons;
  METADATA_AUDIT_OFFSET = Number(r.found_offset||0) + (r.found||[]).length;
  if(more) more.classList.toggle('hidden', !r.found_more);
  found.querySelectorAll('[data-audit-candidate]').forEach(button => {
    button.onclick = async () => {
      button.disabled = true;
      try{
        const response = await fetch('/api/metadata_audit_candidate', {
          method:'POST',
          body:JSON.stringify({
            path:button.dataset.auditCandidate,
            sha256:button.dataset.auditSha,
          }),
        });
        const value = await response.json();
        if(!value.ok) throw new Error(value.error || '복원 후보를 열지 못했습니다.');
        value.candidate._audit = {
          path:value.path,
          sha256:value.sha256,
        };
        openApplyPicker(value.candidate);
      }catch(error){
        alert(error.message || String(error));
      }finally{
        button.disabled = false;
      }
    };
  });
}
async function loadMetadataAudit(offset=0, append=false){
  try{
    renderMetadataAudit(await (await fetch(
      '/api/metadata_audit_status?offset=' + Number(offset||0)
        + '&limit=50', {cache:'no-store'})).json(), append);
  }catch(error){
    renderMetadataAudit({ok:false,error:'메타데이터 감사 기록 확인 실패: ' + error});
  }
}
async function metadataAuditAction(action){
  const buttons = [
    $('metadataAuditStart'), $('metadataAuditContinue'), $('metadataAuditRetry')
  ].filter(Boolean);
  buttons.forEach(button => button.disabled = true);
  try{
    const r = await (await fetch('/api/metadata_audit_control', {
      method:'POST', body:JSON.stringify({action}),
    })).json();
    METADATA_AUDIT_OFFSET = 0;
    renderMetadataAudit(r, false);
  }catch(error){
    renderMetadataAudit({ok:false,error:'메타데이터 감사 실행 실패: ' + error});
  }finally{
    buttons.forEach(button => button.disabled = false);
  }
}
if($('metadataAuditStart')) $('metadataAuditStart').addEventListener(
  'click', () => metadataAuditAction('start'));
if($('metadataAuditContinue')) $('metadataAuditContinue').addEventListener(
  'click', () => metadataAuditAction('continue'));
if($('metadataAuditRetry')) $('metadataAuditRetry').addEventListener(
  'click', () => metadataAuditAction('retry'));
if($('metadataAuditMore')) $('metadataAuditMore').addEventListener(
  'click', () => loadMetadataAudit(METADATA_AUDIT_OFFSET, true));
loadMetadataAudit();

let PUBLIC_COLLECT_TIMER = null;
function renderPublicCollection(r){
  const host = $('publicCollectStatus'); if(!host) return;
  if(!r || !r.ok){ host.textContent = (r && r.error) || '수집 기록을 읽지 못했습니다.'; return; }
  const labels = {
    idle:'대기', searching:'검색 중', downloading:'게시글·이미지 확인 중',
    paused:'일시정지', interrupted:'앱 종료로 중단됨', stopping:'중지 중',
    stopped:'중지됨', failed:'실패', partial:'일부 실패', completed:'완료'
  };
  const total = Number((r.queue||[]).length || r.found_posts || 0);
  const done = Number(r.scanned_posts||0);
  const bits = [
    `${labels[r.stage] || labels[r.status] || r.status} · 게시글 ${done}/${total}`,
    `이미지 ${Number(r.scanned_images||0)}장 확인 · NAI 메타 ${Number(r.metadata_images||0)}장`,
    `새 글 ${Number(r.new_posts||0)} · 변경 ${Number(r.changed_posts||0)} · 그대로 ${Number(r.unchanged_posts||0)}`,
    `새 묶음 ${Number(r.added||0)} · 기존 묶음에 근거 추가 ${Number(r.updated||0)} · 이미 있음 ${Number(r.existing||0)}`
  ];
  if(r.current) bits.push(`현재: ${r.current}`);
  if((r.errors||[]).length) bits.push(`최근 오류: ${r.errors[r.errors.length-1]}`);
  host.textContent = bits.join('\n');
  const active = ['running','paused','stopping'].includes(r.status);
  if($('publicCollectStart')) $('publicCollectStart').disabled = active;
  if($('publicCollectPause')) $('publicCollectPause').disabled = r.status !== 'running';
  if($('publicCollectResume')) $('publicCollectResume').disabled = !r.can_resume && r.status !== 'paused';
  if($('publicCollectStop')) $('publicCollectStop').disabled = !active;
  const failedHost = $('publicCollectFailures'), failedList = $('publicCollectFailureList');
  const failedItems = (r.failed_items||[]).filter(item => item && item.url);
  if(failedHost && failedList){
    failedHost.classList.toggle('hidden', !failedItems.length);
    failedList.innerHTML = failedItems.map(item => `<label class="row"
        style="display:flex;gap:8px;align-items:flex-start;margin:4px 0;">
      <input type="checkbox" data-public-retry="${escA(item.url)}" checked
        style="width:auto;min-height:0;margin-top:3px;">
      <span style="min-width:0;"><b>${esc(item.title||('게시글 '+(item.article_id||'')))}</b>
        <span class="hint" style="display:block;word-break:break-all;">
          ${esc(item.error||'확인 실패')} · ${Number(item.attempts||1)}회
        </span></span>
    </label>`).join('');
  }
  if($('publicCollectRetry')){
    $('publicCollectRetry').disabled = active || !failedItems.length;
  }
  if(['completed','partial','stopped','failed'].includes(r.status)) reloadConfig().catch(()=>{});
}
async function loadPublicCollection(){
  if(!$('publicCollectStatus')) return;
  try{
    renderPublicCollection(await (await fetch('/api/public_collection')).json());
  }catch(e){ renderPublicCollection({ok:false,error:String(e)}); }
}
async function publicCollectionPost(path, payload){
  const r = await (await fetch(path, {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload||{})})).json();
  renderPublicCollection(r);
  return r;
}
if($('publicCollectStart')){
  $('publicCollectStart').addEventListener('click', () => publicCollectionPost(
    '/api/public_collection_start', {
      urls:$('publicCollectUrls').value,
      keyword:$('publicCollectKeyword').value,
      pages:Number($('publicCollectPages').value||0),
      max_posts:Number($('publicCollectMax').value||100)
    }));
  $('publicCollectPause').addEventListener('click', () =>
    publicCollectionPost('/api/public_collection_control', {action:'pause'}));
  $('publicCollectResume').addEventListener('click', () =>
    publicCollectionPost('/api/public_collection_control', {action:'resume'}));
  $('publicCollectStop').addEventListener('click', () =>
    publicCollectionPost('/api/public_collection_control', {action:'stop'}));
  $('publicCollectRetry').addEventListener('click', () => {
    const urls = [...document.querySelectorAll('[data-public-retry]:checked')]
      .map(box => box.dataset.publicRetry);
    if(!urls.length){
      $('publicCollectStatus').textContent = '재시도할 실패 게시글을 먼저 고르세요.';
      return;
    }
    publicCollectionPost('/api/public_collection_retry', {urls});
  });
  loadPublicCollection();
  PUBLIC_COLLECT_TIMER = setInterval(loadPublicCollection, 2000);
}

let PACK_FILES = [], PACK_ACTIVE = null, PACK_CHANGES = [], PACK_SHOW = 0,
  PACK_SHA = '', PACK_DIFF = '', PACK_LINES = [], PACK_LOG = null;
function packValue(value){
  let text;
  try{ text = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  catch(e){ text = String(value); }
  return `<pre style="max-height:190px;overflow:auto;white-space:pre-wrap;
    word-break:break-word;margin:4px 0 0;">${esc(text)}</pre>`;
}
function packSelected(){
  return PACK_CHANGES.filter(change => change.selected).map(change => change.id);
}
function packSelectionPaint(){
  $('packSelectedCount').textContent =
    `${packSelected().length.toLocaleString()}개 선택 / 충돌 ${PACK_CHANGES.length.toLocaleString()}개`;
}
function packDiffPaint(reset=false){
  if(reset){ PACK_SHOW = 0; $('packDiffList').innerHTML = ''; }
  const start = PACK_SHOW, end = Math.min(PACK_CHANGES.length, start + 80);
  for(let i=start; i<end; i++){
    const change = PACK_CHANGES[i];
    const card = document.createElement('label');
    card.className = 'row';
    card.style.cssText = 'display:block;margin:0;cursor:pointer;';
    card.innerHTML = `<div class="bar">
      <input type="checkbox" data-pack-change="${escA(change.id)}"
        style="width:auto;flex:none;" ${change.selected?'checked':''}>
      <b>${esc(change.logical)}</b><span class="tag">${esc(change.kind)}</span></div>
      <div class="hint">열쇠 ${esc(change.key)}</div>
      <details><summary>현재 자산</summary>${packValue(change.current)}</details>
      <details><summary>들어오는 자산</summary>${packValue(change.incoming)}</details>`;
    card.querySelector('input').addEventListener('change', event => {
      change.selected = event.target.checked; packSelectionPaint();
    });
    $('packDiffList').appendChild(card);
  }
  PACK_SHOW = end;
  $('packDiffMore').classList.toggle('hidden', end >= PACK_CHANGES.length);
  $('packDiffMore').textContent =
    `더 보기 (${Math.max(0,PACK_CHANGES.length-end).toLocaleString()}개 남음)`;
  packSelectionPaint();
}
function packFinishMessage(){
  $('packMsg').innerHTML = PACK_LINES.map(esc).join('<br>') || '들어온 것 없음';
  if(PACK_LOG) renderPackLog(PACK_LOG);
}
async function applyCurrentPack(selected){
  if(!PACK_ACTIVE) return;
  $('packApply').disabled = true;
  $('packCancel').disabled = true;
  $('packMsg').textContent =
    `${PACK_ACTIVE.name} — 새 항목과 고른 충돌만 넣는 중입니다.`;
  let r;
  try{
    r = await (await fetch('/api/pack_import', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sha256:PACK_SHA,diff_fingerprint:PACK_DIFF,selected})})).json();
  }catch(e){ r = {ok:false,error:String(e)}; }
  if(r.error) PACK_LINES.push(PACK_ACTIVE.name + ': ' + r.error);
  else (r.report||[]).forEach(line => PACK_LINES.push(line));
  if(r.log) PACK_LOG = r.log;
  PACK_ACTIVE = null; PACK_CHANGES = []; PACK_SHA = ''; PACK_DIFF = '';
  $('packDiff').classList.add('hidden');
  $('packApply').disabled = false;
  $('packCancel').disabled = false;
  await nextPack();
}
async function nextPack(){
  if(PACK_ACTIVE) return;
  const file = PACK_FILES.shift();
  if(!file){
    packFinishMessage();
    await reloadConfig();
    return;
  }
  PACK_ACTIVE = file;
  $('packMsg').textContent = `${file.name} 검사 중... (아직 아무 자료도 바꾸지 않습니다)`;
  let r;
  try{
    r = await (await fetch('/api/pack_preview', {method:'POST',
      headers:{'X-Filename':encodeURIComponent(file.name)},body:file})).json();
  }catch(e){ r = {ok:false,error:String(e)}; }
  if(!r.ok){
    PACK_LINES.push(file.name + ': ' + (r.error || '검사 실패'));
    PACK_ACTIVE = null;
    await nextPack();
    return;
  }
  PACK_SHA = r.sha256 || '';
  PACK_DIFF = r.diff_fingerprint || '';
  PACK_CHANGES = (r.conflicts || []).map(change =>
    Object.assign({selected:false},change));
  if(!PACK_CHANGES.length){
    await applyCurrentPack([]);
    return;
  }
  $('packMsg').textContent =
    `${file.name} — 새 항목은 안전하게 추가됩니다. 충돌 ${PACK_CHANGES.length.toLocaleString()}개만 고르세요.`;
  $('packDiff').classList.remove('hidden');
  packDiffPaint(true);
}
async function sendPack(files){
  if(!files.length) return;
  PACK_FILES.push(...files);
  if(!PACK_ACTIVE) await nextPack();
}
if($('packDrop')){
  $('packSelectAll').addEventListener('click', () => {
    PACK_CHANGES.forEach(change => { change.selected = true; });
    packDiffPaint(true);
  });
  $('packSelectNone').addEventListener('click', () => {
    PACK_CHANGES.forEach(change => { change.selected = false; });
    packDiffPaint(true);
  });
  $('packDiffMore').addEventListener('click', () => packDiffPaint(false));
  $('packApply').addEventListener('click', () => applyCurrentPack(packSelected()));
  $('packCancel').addEventListener('click', async () => {
    if(PACK_ACTIVE) PACK_LINES.push(PACK_ACTIVE.name + ': 사용자가 건너뜀');
    fetch('/api/pack_preview_cancel', {method:'POST',body:'{}'}).catch(()=>{});
    PACK_ACTIVE = null; PACK_CHANGES = []; PACK_SHA = ''; PACK_DIFF = '';
    $('packDiff').classList.add('hidden');
    await nextPack();
  });
  $('packDrop').addEventListener('click', () => $('packFile').click());
  $('packFile').addEventListener('change', async () => {
    const fs = [...$('packFile').files]; $('packFile').value = '';
    await sendPack(fs);
  });
  $('packDrop').addEventListener('dragover', e => {
    e.preventDefault(); $('packDrop').style.borderColor = 'var(--accent)';
  });
  $('packDrop').addEventListener('dragleave', () => {
    $('packDrop').style.borderColor = '';
  });
  $('packDrop').addEventListener('drop', async e => {
    e.preventDefault(); $('packDrop').style.borderColor = '';
    await sendPack([...(e.dataTransfer.files || [])]);
  });
  /* 화면을 처음 열 때 지난 기록을 보여 준다 (앱을 껐다 켜도 남아 있다) */
  fetch('/api/pack_log').then(r => r.json())
    .then(r => renderPackLog(r.log)).catch(() => {});
  loadDataStorageStatus();
}

$('setImport').addEventListener('click', () => $('setImportFile').click());
$('setImportFile').addEventListener('change', async () => {
  const files = [...$('setImportFile').files];
  if(!files.length) return;
  const added = [], skipped = [];
  for(const f of files){
    $('setMsg').textContent = `${f.name} 넣는 중...`;
    const r = await (await fetch('/api/setting_import', {method:'POST',
      headers:{'X-Filename': encodeURIComponent(f.name)}, body: f})).json();
    (r.added || []).forEach(x => added.push(x));
    (r.skipped || []).forEach(x => skipped.push(x));
    if(r.error) skipped.push(f.name + ': ' + r.error);
  }
  $('setImportFile').value = '';
  await reloadConfig();
  $('setMsg').textContent = (added.length ? `${added.length}개 들어옴 (${added.join(', ')})` : '들어온 것 없음')
    + (skipped.length ? ` · 건너뜀 ${skipped.length}개: ${skipped[0]}` : '');
});
async function loadSetThumbs(){
  for(const st of SETTINGS){
    const r = await (await fetch('/api/setting_thumbs?name=' + encodeURIComponent(st.name))).json();
    if(!r.ok) continue;
    Object.entries(r.thumbs).forEach(([gid, rel]) => {
      const box = document.querySelector(`[data-ssel="${CSS.escape(st.name)}"][data-id="${gid}"]`);
      if(!box) return;
      const item = box.closest('.item');
      if(!item || item.querySelector('.setthumb')) return;
      const im = document.createElement('img');
      /* 26px 짜리 로컬 파일이라 지연 로딩은 이득이 없다.
         오히려 접힌 구획 안에서는 관찰자가 안 돌아 영영 안 뜬다. */
      im.className = 'setthumb';
      im.src = '/setout?p=' + encodeURIComponent(rel);
      im.title = rel;
      item.insertBefore(im, box.nextSibling);
    });
  }
}
$('setThumbs').addEventListener('change', () => {
  if($('setThumbs').checked){ $('setMsg').textContent = '대표 그림 찾는 중...';
    loadSetThumbs().then(() => { $('setMsg').textContent = '대표 그림 표시 ✓'; }); }
  else { document.querySelectorAll('.setthumb').forEach(e => e.remove());
    $('setMsg').textContent = ''; }
});

/* ── 라이브러리 ── */
var LIB_OFFSET = 0, LIB_PAGE_SIZE = 100, LIB_REQUEST_SEQ = 0, CHAR_EDIT_LIMIT = 24;
var LIB_FILTER_TIMER = null, CHAR_FILTER_TIMER = null;
var LIB_REVISION = '';
var LIB_UNDO = null, LIB_VISIBLE_IDS = [];
const LIB_SELECTED = new Set();
const LIB_REVIEW_LABELS = {pending:'미검토', reviewed:'검토 완료', hold:'보류'};
function libraryNeedle(value){
  return String(value || '').normalize('NFKC').toLocaleLowerCase();
}
function updateLibrarySelection(){
  document.querySelectorAll('[data-libpick]').forEach(box => {
    box.checked = LIB_SELECTED.has(box.dataset.libpick);
  });
  const selected = LIB_SELECTED.size;
  if($('libSelectedN')) $('libSelectedN').textContent = `${selected.toLocaleString()}개 선택`;
  if($('libBulkApply')) $('libBulkApply').disabled = !selected;
  if($('libClearSelection')) $('libClearSelection').disabled = !selected;
  if($('libBulkUndo')) $('libBulkUndo').disabled = !LIB_UNDO;
  const page = LIB_VISIBLE_IDS.length;
  if($('libSelectPage')){
    const picked = LIB_VISIBLE_IDS.filter(id => LIB_SELECTED.has(id)).length;
    $('libSelectPage').checked = !!page && picked === page;
    $('libSelectPage').indeterminate = picked > 0 && picked < page;
  }
}
async function renderLibrary(append=false){
  const g = $('libGrid'); if(!g) return;
  if(!append){ LIB_OFFSET = 0; g.innerHTML = '<div class="row hint">자료를 찾는 중입니다.</div>'; }
  const request = ++LIB_REQUEST_SEQ;
  const query = ($('libFilter')||{}).value || '';
  const kind = ($('libType')||{}).value || '';
  const source = ($('libSource')||{}).value || '';
  const review = ($('libReview')||{}).value || '';
  const label = ($('libLabel')||{}).value || '';
  const url = `/api/library?q=${encodeURIComponent(query)}&kind=${encodeURIComponent(kind)}`
    + `&source=${encodeURIComponent(source)}&review=${encodeURIComponent(review)}`
    + `&label=${encodeURIComponent(label)}&limit=${LIB_PAGE_SIZE}&offset=${LIB_OFFSET}`;
  let result;
  try{ result = await (await fetch(url)).json(); }
  catch(e){ result = {ok:false,error:String(e)}; }
  if(request !== LIB_REQUEST_SEQ) return;
  if(!result.ok){ g.innerHTML = `<div class="row hint">${esc(result.error||'자료를 읽지 못했습니다.')}</div>`; return; }
  LIB_REVISION = result.revision || '';
  if(!append) g.innerHTML = '';
  const sourceSelect = $('libSource');
  if(sourceSelect && !append){
    const selectedSource = sourceSelect.value;
    sourceSelect.innerHTML = '<option value="">모든 출처</option>';
    Object.entries(result.sources||{}).sort((a,b)=>b[1]-a[1]).forEach(([name,count]) => {
      const option = document.createElement('option');
      option.value = name; option.textContent = `${name} (${Number(count).toLocaleString()})`;
      sourceSelect.appendChild(option);
    });
    if([...sourceSelect.options].some(option => option.value === selectedSource)){
      sourceSelect.value = selectedSource;
    }
  }
  const labelSelect = $('libLabel');
  if(labelSelect && !append){
    const selectedLabel = labelSelect.value;
    labelSelect.innerHTML = '<option value="">모든 이름표</option>';
    Object.entries(result.labels||{}).sort((a,b)=>b[1]-a[1] || a[0].localeCompare(b[0]))
      .forEach(([name,count]) => {
        const option = document.createElement('option');
        option.value = name; option.textContent = `${name} (${Number(count).toLocaleString()})`;
        labelSelect.appendChild(option);
      });
    if([...labelSelect.options].some(option => option.value === selectedLabel)){
      labelSelect.value = selectedLabel;
    }
  }
  const fragment = document.createDocumentFragment();
  (result.items||[]).forEach(it => {
    const el = document.createElement('div');
    el.className = 'row combo-card'; el.style.cursor = 'pointer'; el.style.margin = '0';
    el.dataset.libcard = it.id;
    el._libraryItem = it;
    const status = LIB_REVIEW_LABELS[it.review_status] || '미검토';
    const labelTags = (it.labels||[]).map(value =>
      `<span class="tag" style="font-size:var(--fs-2xs);">${esc(value)}</span>`).join('');
    el.innerHTML = `<div class="bar" style="gap:6px;">
        <label class="hint" title="이 자료 선택"><input type="checkbox"
          data-libpick="${escA(it.id)}" ${LIB_SELECTED.has(it.id)?'checked':''}></label>
        <span class="tag">${esc(it.kind)} · ${esc(it.source||'출처 없음')}</span>
        <span class="tag" style="margin-left:auto;">${esc(status)}</span>
      </div>
      <div style="display:flex;gap:8px;align-items:flex-start;">
        ${(it.images&&it.images[0])?`<img src="/img?u=${encodeURIComponent(it.images[0])}"
          loading="lazy" decoding="async" alt="" style="width:54px;height:54px;object-fit:cover;
          border-radius:var(--radius);border:1px solid var(--line);flex:none;">`:''}
        <div style="min-width:0;"><b style="font-size:var(--fs-xs);">${esc(it.name)}</b>
          <div style="font-size:var(--fs-2xs);color:var(--muted);margin-top:4px;
          max-height:44px;overflow:hidden;">${esc(String(it.prompt||'').slice(0,100))}</div>
          ${labelTags?`<div class="bar" style="gap:4px;margin-top:5px;flex-wrap:wrap;">${labelTags}</div>`:''}
        </div>
      </div>`;
    el.querySelector('[data-libpick]').addEventListener('click', event => event.stopPropagation());
    el.querySelector('[data-libpick]').addEventListener('change', event => {
      if(event.target.checked) LIB_SELECTED.add(it.id);
      else LIB_SELECTED.delete(it.id);
      updateLibrarySelection();
    });
    el.addEventListener('click', event => {
      if(!event.target.closest('[data-libpick]')) openLib(it);
    });
    fragment.appendChild(el);
  });
  g.appendChild(fragment);
  LIB_VISIBLE_IDS = [...g.querySelectorAll('[data-libcard]')].map(el => el.dataset.libcard);
  LIB_OFFSET += (result.items||[]).length;
  if(!LIB_OFFSET){
    g.innerHTML = '<div class="row hint">조건에 맞는 자료가 없습니다.</div>';
  }
  if($('libCount')) $('libCount').textContent =
    `${LIB_OFFSET.toLocaleString()} / ${Number(result.matched||0).toLocaleString()}개`
    + ` · 전체 ${Number(result.total||0).toLocaleString()}개`
    + ` · 완료 ${Number((result.review_counts||{}).reviewed||0).toLocaleString()}`
    + ` · 보류 ${Number((result.review_counts||{}).hold||0).toLocaleString()}`;
  if($('libMore')){
    $('libMore').style.display = LIB_OFFSET < Number(result.matched||0) ? '' : 'none';
    $('libMore').textContent =
      `더 보기 · 남은 ${(Number(result.matched||0) - LIB_OFFSET).toLocaleString()}개 ▾`;
  }
  updateLibrarySelection();
  renderCharCards();
}
async function organizeSelectedLibrary(payload, undo=false){
  const button = undo ? $('libBulkUndo') : $('libBulkApply');
  if(button) button.disabled = true;
  if($('libBulkMsg')) $('libBulkMsg').textContent =
    undo ? '방금 정리를 되돌리는 중입니다.' : '선택 자료를 정리하는 중입니다.';
  let result;
  try{
    result = await (await fetch('/api/library_organize', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    })).json();
  }catch(error){ result = {ok:false,error:String(error)}; }
  if(!result.ok){
    if($('libBulkMsg')) $('libBulkMsg').textContent =
      result.error || '자료 정리를 저장하지 못했습니다.';
    if(result.conflict) await renderLibrary(false);
    updateLibrarySelection();
    return false;
  }
  LIB_REVISION = result.revision || LIB_REVISION;
  if($('libBulkMsg')) $('libBulkMsg').textContent =
    `${Number(result.changed||0).toLocaleString()}개 ${undo?'되돌림':'정리 완료'} · 원본 자료는 그대로입니다.`;
  return result;
}
if($('libSelectPage')) $('libSelectPage').addEventListener('change', event => {
  LIB_VISIBLE_IDS.forEach(id => {
    if(event.target.checked) LIB_SELECTED.add(id);
    else LIB_SELECTED.delete(id);
  });
  updateLibrarySelection();
});
if($('libClearSelection')) $('libClearSelection').addEventListener('click', () => {
  LIB_SELECTED.clear();
  updateLibrarySelection();
});
if($('libBulkApply')) $('libBulkApply').addEventListener('click', async () => {
  const ids = [...LIB_SELECTED];
  const status = $('libBulkStatus').value;
  const labels = $('libBulkLabels').value;
  const labelMode = $('libLabelMode').value;
  if(!status && !labels.trim() && labelMode !== 'clear'){
    $('libBulkMsg').textContent = '바꿀 상태나 이름표를 먼저 적으세요.';
    return;
  }
  const result = await organizeSelectedLibrary({
    action:'apply', ids, status, labels, label_mode:labelMode,
    expect_revision:LIB_REVISION,
  });
  if(!result) return;
  LIB_UNDO = {ids, records:result.before};
  LIB_SELECTED.clear();
  await renderLibrary(false);
});
if($('libBulkUndo')) $('libBulkUndo').addEventListener('click', async () => {
  if(!LIB_UNDO) return;
  const undo = LIB_UNDO;
  const result = await organizeSelectedLibrary({
    action:'restore', ids:undo.ids, records:undo.records,
    expect_revision:LIB_REVISION,
  }, true);
  if(!result) return;
  LIB_UNDO = null;
  await renderLibrary(false);
});
function updateLibraryManage(){
  const button = $('libManage');
  if(!button) return;
  const kind = ($('libType')||{}).value || '';
  const labels = {
    '캐릭터':'캐릭터 상세 편집',
    '그림체':'그림체 중복·삭제·복구',
    '레시피':'레시피 상세 보기',
    '세팅':'세팅 편집기로 이동',
    '생성 기록':'비교 결과·재개 관리',
  };
  button.disabled = !labels[kind];
  button.textContent = labels[kind] || '종류를 고르면 정리할 수 있습니다';
}
async function manageLibraryKind(){
  const kind = ($('libType')||{}).value || '';
  if(kind === '그림체'){
    openCombos();
    return;
  }
  if(kind === '캐릭터'){
    $('charEditorCard').scrollIntoView({behavior:'smooth', block:'start'});
    $('charFilter').focus();
    return;
  }
  if(kind === '레시피'){
    const query = ($('libFilter')||{}).value || '';
    if(query) $('recQ').value = query;
    await ensureRecipes();
    $('recipeLibraryCard').scrollIntoView({behavior:'smooth', block:'start'});
    $('recQ').focus();
    return;
  }
  if(kind === '세팅'){
    STATE.ui = STATE.ui || {};
    STATE.ui.settings_work = 'build';
    setMode('settings');
    arrangeStudioWorkspace();
    sbPickList();
    save();
    $('settingBuilderCard').scrollIntoView({behavior:'smooth', block:'start'});
    return;
  }
  if(kind === '생성 기록'){
    STATE.ui = STATE.ui || {};
    STATE.ui.settings_work = 'compare';
    setMode('settings');
    arrangeStudioWorkspace();
    await comparisonRunsLoad();
    $('compareCard').scrollIntoView({behavior:'smooth', block:'start'});
    save();
  }
}
if($('libFilter')) $('libFilter').addEventListener('input', () => {
  clearTimeout(LIB_FILTER_TIMER);
  LIB_FILTER_TIMER = setTimeout(() => {
    renderLibrary(false);
  }, 100);
});
if($('libType')) $('libType').addEventListener('change', () => {
  updateLibraryManage();
  renderLibrary(false);
});
if($('libSource')) $('libSource').addEventListener('change', () => renderLibrary(false));
if($('libReview')) $('libReview').addEventListener('change', () => renderLibrary(false));
if($('libLabel')) $('libLabel').addEventListener('change', () => renderLibrary(false));
if($('libManage')) $('libManage').addEventListener('click', manageLibraryKind);
if($('libMore')) $('libMore').addEventListener('click', () => {
  renderLibrary(true);
});
updateLibraryManage();
if($('charFilter')) $('charFilter').addEventListener('input', () => {
  clearTimeout(CHAR_FILTER_TIMER);
  CHAR_FILTER_TIMER = setTimeout(() => {
    CHAR_EDIT_LIMIT = 24;
    renderCharCards();
  }, 100);
});
if($('charMore')) $('charMore').addEventListener('click', () => {
  CHAR_EDIT_LIMIT += 24;
  renderCharCards();
});
const DELETED_CHARS = [];
function updateCharUndo(){
  const button = $('charUndo'), message = $('charEditMsg');
  if(!button || !message) return;
  button.classList.toggle('hidden', !DELETED_CHARS.length);
  if(DELETED_CHARS.length){
    const last = DELETED_CHARS[DELETED_CHARS.length - 1].character;
    message.textContent = `'${last.name || '캐릭터'}' 삭제됨 · 이 화면에서 되돌릴 수 있습니다.`;
  }else{
    message.textContent = '복제로 의상·예술적 변형을 나누고, 삭제한 항목은 이 화면을 닫기 전 되돌릴 수 있습니다.';
  }
}
function renderCharCards(){
  const h = $('charList'); if(!h) return;
  h.innerHTML = '';
  CHAR_EDIT_LIMIT = Number(CHAR_EDIT_LIMIT) || 24;
  const query = libraryNeedle(($('charFilter')||{}).value);
  const filtered = (STATE.characters||[]).filter(c => !query || libraryNeedle([
    c.name, c.female, c.clothed, c.negative, c.source,
    (c.variant||{}).group, (c.variant||{}).name,
  ].join(' ')).includes(query));
  const shown = filtered.slice(0, CHAR_EDIT_LIMIT);
  shown.forEach(c => {
    const variant = c.variant && typeof c.variant === 'object' ? c.variant : {};
    const assetImages = [
      c.representative,
      ...(Array.isArray(c.images) ? c.images : []),
      ...(Array.isArray(c.evidence_images) ? c.evidence_images : []),
      ...(Array.isArray(c.variation_images) ? c.variation_images : [])
    ].filter((value,index,rows) => typeof value === 'string' && value && rows.indexOf(value) === index);
    const el = document.createElement('div'); el.className = 'slot';
    el.innerHTML = `<div class="r1"><input type="text" data-xc="${c.id}" data-xf="name" value="${escA(c.name)}" placeholder="이름">
      <button data-xdup="${c.id}" title="이 캐릭터를 복사해 의상·변형만 바꿉니다">복제</button>
      <button class="danger" data-xdel="${c.id}">삭제</button></div>
      <textarea data-xc="${c.id}" data-xf="female" placeholder="girl, ...">${esc(c.female)}</textarea>
      <input type="text" data-xc="${c.id}" data-xf="clothed" placeholder="착의 (선택)" value="${escA(c.clothed)}" style="margin-top:4px;">
      <input type="text" data-xc="${c.id}" data-xf="negative" placeholder="전용 네거티브" value="${escA(c.negative)}" style="margin-top:4px;">
      ${assetImages.length ? `<div class="bar" style="margin-top:6px;">
        <img src="/img?u=${encodeURIComponent(assetImages[0])}" alt="${escA(c.name||'캐릭터')} 대표·근거"
          loading="lazy" style="width:72px;height:72px;object-fit:cover;border-radius:var(--radius);">
        <span class="hint">대표·근거 ${assetImages.length}장 · 저장 variation ${(c.variants||[]).length}개</span>
        <button type="button" data-xbench="${c.id}" data-ximage="${escA(assetImages[0])}">이미지 시험·변형</button>
      </div>` : `<p class="hint">근거 이미지를 자료실에서 열어 ‘이 증거 그림으로 캐릭터 변형’을 누르면 이미지 작업대를 시작할 수 있습니다.</p>`}
      <details class="cast-advanced"${variant.group ? ' open' : ''}>
        <summary>같은 캐릭터의 변형 묶음${variant.group ? ` · ${esc(variant.name || '기본 변형')}` : ''}</summary>
        <div class="grid3" style="margin-top:7px;">
          <div class="field"><label>묶음 ID</label>
            <input type="text" data-xv="group" data-xci="${c.id}" value="${escA(variant.group||'')}" placeholder="비우면 독립 캐릭터"></div>
          <div class="field"><label>변형 이름</label>
            <input type="text" data-xv="name" data-xci="${c.id}" value="${escA(variant.name||'')}" placeholder="기본·교복·시대극 등"></div>
          <label class="field"><span>전수 비교·fallback 후보</span>
            <select data-xv="enabled" data-xci="${c.id}"><option value="on"${variant.enabled===false?'':' selected'}>사용</option>
              <option value="off"${variant.enabled===false?' selected':''}>제외</option></select></label>
        </div>
        <p class="hint">같은 묶음에서 사용 가능한 변형이 하나도 없으면 첫 항목을 안전하게 사용합니다.</p>
      </details>`;
    h.appendChild(el);
  });
  if(!shown.length){
    h.innerHTML = '<div class="row hint">조건에 맞는 캐릭터가 없습니다.</div>';
  }
  if($('charCount')) $('charCount').textContent =
    `${shown.length.toLocaleString()} / ${filtered.length.toLocaleString()}명`;
  if($('charMore')){
    $('charMore').style.display = shown.length < filtered.length ? '' : 'none';
    $('charMore').textContent =
      `편집할 캐릭터 더 보기 · 남은 ${(filtered.length - shown.length).toLocaleString()}명 ▾`;
  }
  h.querySelectorAll('[data-xc]').forEach(el => el.addEventListener('input', () => {
    const c = (STATE.characters||[]).find(x => x.id === el.dataset.xc);
    if(c){ c[el.dataset.xf] = el.value; save(); }
  }));
  h.querySelectorAll('[data-xv]').forEach(el => el.addEventListener('change', () => {
    const c = (STATE.characters||[]).find(x => x.id === el.dataset.xci);
    if(!c) return;
    const variant = c.variant && typeof c.variant === 'object' ? c.variant : {};
    if(el.dataset.xv === 'enabled') variant.enabled = el.value !== 'off';
    else variant[el.dataset.xv] = el.value;
    if(!String(variant.group || '').trim() && !String(variant.name || '').trim()){
      delete c.variant;
    }else{
      c.variant = variant;
    }
    renderSlots(); save();
  }));
  h.querySelectorAll('[data-xdup]').forEach(b => b.addEventListener('click', () => {
    const chars = STATE.characters || [];
    const at = chars.findIndex(x => x.id === b.dataset.xdup);
    if(at < 0) return;
    // 최신 화면 값을 그대로 깊은 복사한다. groups·폴더·전용 네거티브도 보존하되
    // 파일 동기화에서 원본을 덮지 않도록 id와 이름만 새로 만든다.
    const cloned = JSON.parse(JSON.stringify(chars[at]));
    const names = new Set(chars.map(x => String(x.name || '').trim().toLocaleLowerCase()));
    const root = `${String(chars[at].name || '캐릭터').trim() || '캐릭터'} 복사본`;
    let name = root, serial = 2;
    while(names.has(name.toLocaleLowerCase())) name = `${root} ${serial++}`;
    cloned.id = genId();
    cloned.name = name;
    const originalVariant = chars[at].variant && typeof chars[at].variant === 'object'
      ? chars[at].variant : {};
    const group = String(originalVariant.group || '').trim() || `variant-${chars[at].id || genId()}`;
    chars[at].variant = Object.assign({}, originalVariant, {
      group, name:String(originalVariant.name || '').trim() || '기본', enabled:originalVariant.enabled !== false
    });
    const siblings = chars.filter(item =>
      String(((item.variant||{}).group)||'').trim() === group).length;
    cloned.variant = Object.assign({}, cloned.variant || {}, {
      group, name:`변형 ${siblings + 1}`, enabled:true
    });
    chars.splice(at + 1, 0, cloned);
    renderLibrary(); renderSlots(); save();
    const input = document.querySelector(`[data-xc="${cloned.id}"][data-xf="name"]`);
    if(input){ input.focus(); input.select(); }
    flash(`'${name}' 복제됨 — 이름·의상·예술적 변형을 바꿔 저장하세요.`);
  }));
  h.querySelectorAll('[data-xbench]').forEach(button => button.addEventListener('click', async () => {
    const character = (STATE.characters||[]).find(item => item.id === button.dataset.xbench);
    if(!character) return;
    const msg = $('charEditMsg');
    await resultToI2I(
      `/img?u=${encodeURIComponent(button.dataset.ximage)}`,
      `${character.name || '캐릭터'} 근거.webp`,
      msg,
      characterBundle(character, false));
  }));
  h.querySelectorAll('[data-xdel]').forEach(b => b.addEventListener('click', () => {
    const chars = STATE.characters || [];
    const at = chars.findIndex(x => x.id === b.dataset.xdel);
    if(at < 0) return;
    const character = chars[at];
    if(!confirm(`'${character.name || '캐릭터'}'을 삭제할까요? 이 화면을 닫기 전에는 되돌릴 수 있습니다.`)) return;
    DELETED_CHARS.push({character:JSON.parse(JSON.stringify(character)), index:at});
    chars.splice(at, 1);
    renderLibrary(); renderSlots(); updateCharUndo(); save();
  }));
}
$('charUndo').addEventListener('click', () => {
  const deleted = DELETED_CHARS.pop();
  if(!deleted) return;
  const chars = STATE.characters || (STATE.characters = []);
  const restored = deleted.character;
  if(chars.some(x => x.id === restored.id)) restored.id = genId();
  const names = new Set(chars.map(x => String(x.name || '').trim().toLocaleLowerCase()));
  if(names.has(String(restored.name || '').trim().toLocaleLowerCase())){
    const root = `${String(restored.name || '캐릭터').trim() || '캐릭터'} 복구본`;
    let name = root, serial = 2;
    while(names.has(name.toLocaleLowerCase())) name = `${root} ${serial++}`;
    restored.name = name;
  }
  chars.splice(Math.min(deleted.index, chars.length), 0, restored);
  renderLibrary(); renderSlots(); updateCharUndo(); save();
  const input = document.querySelector(`[data-xc="${restored.id}"][data-xf="name"]`);
  if(input) input.focus();
});
$('libAddChar').addEventListener('click', () => {
  (STATE.characters = STATE.characters||[]).push({id:genId(), name:'새 캐릭터', female:'', clothed:'', negative:'', enabled:true});
  if($('libFilter')) $('libFilter').value = '';
  if($('charFilter')) $('charFilter').value = '새 캐릭터';
  LIB_OFFSET = 0; CHAR_EDIT_LIMIT = 24;
  renderLibrary(); save();
});
$('libAddFolder').addEventListener('click', () => {
  (STATE.character_folders = STATE.character_folders||[]).push({id:genId(), name:'새 폴더', parent_id:null});
  save(); alert('폴더 추가됨 (캐릭터 파일이 이 폴더로 저장됩니다)');
});
function openLib(it){
  if(it.store === 'recipe'){
    openRecipe(it.ref || {});
    return;
  }
  window._mm = 'lib';
  $('modalTitle').textContent = `${it.kind} · ${it.name}`;
  const b = $('modalBody'); b.innerHTML = `<div class="tag">${esc(it.source||'출처 없음')}</div>`;
  if(it.images && it.images[0]){
    b.insertAdjacentHTML('beforeend', `<img src="/img?u=${encodeURIComponent(it.images[0])}"
      alt="" style="display:block;max-width:min(100%,420px);max-height:360px;object-fit:contain;
      margin:8px auto;border-radius:var(--radius);background:#000;">`);
  }
  const groups = it.groups || (it.ref&&it.ref.groups) || {};
  if(Object.keys(groups).length){
    Object.entries(groups).forEach(([k,v]) => b.insertAdjacentHTML('beforeend',
      `<div class="row"><div class="tag">${esc(k)}</div><div style="font-size:var(--fs-xs);">${esc(String(v))}</div></div>`));
  }
  const readonly = (label,value) => value ? `<div class="field"><label>${label}</label>
    <textarea readonly style="min-height:64px;">${esc(value)}</textarea></div>` : '';
  b.insertAdjacentHTML('beforeend', readonly('포지티브 전체', it.prompt||'')
    + readonly('착의·변형', it.outfit||'') + readonly('네거티브 전체', it.negative||''));
  const settings = it.settings || {};
  if(Object.keys(settings).length){
    b.insertAdjacentHTML('beforeend', `<div class="row"><div class="tag">생성 설정</div>
      <div style="font-family:var(--mono);font-size:var(--fs-2xs);white-space:pre-wrap;">
      ${esc(Object.entries(settings).map(([k,v])=>`${k}: ${v}`).join('\n'))}</div></div>`);
  }
  const meta = it.meta || {};
  if(it.store === 'setting'){
    b.insertAdjacentHTML('beforeend', `<div class="row"><div class="tag">세팅 구성</div>
      <div style="font-size:var(--fs-xs);">
        방식 ${esc(meta.mode||'단독')} · 씬 ${Number(meta.scenes||0).toLocaleString()}개
        ${meta.stages&&meta.stages.length?`<br>단계: ${esc(meta.stages.join(' → '))}`:''}
        ${meta.options&&meta.options.length?`<br>옵션: ${esc(meta.options.join(', '))}`:''}
      </div></div>
      <div class="bar"><button class="primary" id="libOpenSetting">세팅 편집기로 이동</button></div>`);
    $('libOpenSetting').addEventListener('click', () => {
      $('modalBg').style.display = 'none';
      STATE.ui = STATE.ui || {};
      STATE.ui.settings_work = 'build';
      setMode('settings');
      arrangeStudioWorkspace();
      sbPickList();
      $('sbPick').value = (it.ref||{}).name || it.name;
      sbLoad($('sbPick').value);
      save();
      $('settingBuilderCard').scrollIntoView({behavior:'smooth', block:'start'});
    });
    $('modalFlash').textContent = '';
    $('modalBg').style.display = 'flex';
    return;
  }
  if(it.store === 'generation'){
    b.insertAdjacentHTML('beforeend', `<div class="row"><div class="tag">생성 상태</div>
      <div style="font-size:var(--fs-xs);">
        ${esc(meta.status||'상태 미확인')} · ${Number(meta.completed||0).toLocaleString()}
        / ${Number(meta.total||0).toLocaleString()}장
        ${meta.updated_at?`<br>최근 기록: ${esc(meta.updated_at)}`:''}
        ${meta.resumable?'<br>중단 지점에서 이어서 생성할 수 있습니다.':''}
      </div></div>
      <div class="bar"><button class="primary" id="libOpenGeneration">결과와 생성 기록 열기</button></div>`);
    $('libOpenGeneration').addEventListener('click', async () => {
      $('modalBg').style.display = 'none';
      await openComparisonFolder((it.ref||{}).folder || '', '선택한 생성 기록을 열었습니다.');
    });
    $('modalFlash').textContent = '';
    $('modalBg').style.display = 'flex';
    return;
  }
  const sourceUrl = it.ref && it.ref.url;
  b.insertAdjacentHTML('beforeend', `<div class="bar"><button class="primary" id="libTake">
    ${it.kind==='캐릭터'?'캐릭터 칸에 추가':'그림체 통째로 적용'}</button>
    ${it.store==='character' && it.images && it.images[0]
      ? '<button id="libVary">이 증거 그림으로 캐릭터 변형</button>' : ''}
    ${sourceUrl?`<a href="${escA(sourceUrl)}" target="_blank">원본 게시글 ↗</a>`:''}</div>`);
  $('libTake').addEventListener('click', () => {
    if(it.kind === '캐릭터'){
      (STATE.char_slots = STATE.char_slots||[]).push(characterBundle(it.ref||{}, true));
      autoCoordsOnSecond();
      renderSlots(); tokens(); save();
      $('modalFlash').textContent = '왼쪽 캐릭터 칸에 추가됨 ✓';
    } else {
      const style = it.store === 'collected' ? it.ref : {
        id:it.id, title:it.name, base:it.prompt||'', negative:it.negative||'',
        params:it.settings||{}
      };
      applyStyle(style);
      $('modalFlash').textContent = '베이스 + 네거티브 + 생성 설정 적용됨 ✓';
    }
  });
  if($('libVary')) $('libVary').addEventListener('click', async () => {
    const ref = it.ref || {};
    const ok = await resultToI2I(
      `/img?u=${encodeURIComponent(it.images[0])}`,
      `${it.name || '캐릭터'} 증거.webp`,
      $('modalFlash'),
      characterBundle(Object.assign({}, ref, {
        id:ref.id || it.id, name:it.name || ref.name || '캐릭터'
      }), false));
    if(ok) $('i2iMsg').textContent =
      `'${it.name}' 자산의 외형·착의·네거티브·Reference·Vibe를 임시 계획으로 사용합니다.`;
  });
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
}

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

/* ── 이미지 → 그림체 추출 (novelai.net/inspect 를 로컬에서) ──
   드롭존은 세 곳: 첫 화면 안내 · 그림체 모달 · 창 아무 데나 */
function bindDropZone(zone, file){
  if(!zone) return;
  if(file){
    zone.addEventListener('click', () => file.click());
    file.addEventListener('change', () => { inspectImages([...file.files]); file.value = ''; });
  }
  ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = 'var(--accent)'; }));
  ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.style.borderColor = ''; }));
  zone.addEventListener('drop', e => {
    e.stopPropagation();
    inspectImages([...(e.dataTransfer.files || [])]);
  });
}
function setupInspectDrop(){ bindDropZone($('comboDrop'), $('comboFile')); }

async function inspectImages(files){
  const imgs = files.filter(f => /\.(png|webp)$/i.test(f.name));
  if(!imgs.length){ flash('PNG 또는 WebP 파일을 넣어주세요.'); return 0; }
  let ok = 0, fail = 0, last = null, restored = [];
  for(const f of imgs){
    flash(`읽는 중... ${f.name}`);
    try{
      const r = await (await fetch('/api/inspect', {method:'POST',
        headers:{'X-Filename': encodeURIComponent(f.name), 'X-Save':'1'},
        body: await f.arrayBuffer()})).json();
      restored.push(Object.assign({filename:f.name}, r));
      if(r.ok){ ok++; last = r.style; } else fail++;
    }catch(e){
      fail++;
      restored.push({ok:false, filename:f.name, error:String(e)});
    }
  }
  if(restored.length > 1){
    try{
      const batch = await (await fetch('/api/restoration_batch', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({items:restored, cursor:restored.length,
          status:fail ? (ok ? 'partial' : 'failed') : 'completed'})})).json();
      if(batch.ok) window.LAST_RESTORATION_BATCH = batch.restoration_queue;
    }catch(e){
      console.warn('다중 이미지 복원 큐를 합치지 못했습니다.', e);
    }
  }
  flash(`${ok}개 추출 완료${fail ? `, ${fail}개는 생성 정보가 없었습니다` : ''}`);
  if(ok){
    if($('comboList')){ $('comboQ').value = ''; $('comboSrc').value = '내 이미지'; await loadCombos(false); }
    /* 한 장이면 **읽은 내용을 보여 준 뒤** 넣고, 여러 장은 자료로만 수집한다.
       ⚠ 예전 주석은 "무엇을 가져올지 고르게 한다(SDStudio 의 항목별 적용)" 였는데
         **지금은 고르는 길이 없다.** 그림체는 베이스+네거티브+생성 설정이 한 덩어리라
         쪼개 넣으면 원래 그림이 재현되지 않아서다(`29cf044` 에서 없앴다).
         `openApplyPicker` 는 **읽기 전용 요약 + `통째로 적용` 단추 하나**뿐이다
         (실측: 항목별 체크박스 0개 · 단추 1개). 낡은 설명이 남아 있어 바로잡는다. */
    if(last && imgs.length === 1) openApplyPicker(last);
    if(imgs.length > 1){
      flash(`${ok}개를 자료실에 정리했습니다${fail ? ` · ${fail}개 미인식` : ''} · 현재 생성 설정은 바꾸지 않았습니다.`);
    }
  }
  return ok;
}

/* 창 아무 데나 그림을 떨어뜨려도 추출 */
(function(){
  const ov = document.createElement('div');
  ov.id = 'dropOverlay';
  ov.textContent = '🖼️ 놓으면 이 그림의 프롬프트·설정값을 가져옵니다';
  document.body.appendChild(ov);
  let depth = 0;
  const hasFiles = e => [...((e.dataTransfer || {}).types || [])].includes('Files');
  document.addEventListener('dragenter', e => {
    if(!hasFiles(e)) return;
    depth++; ov.classList.add('on');
  });
  document.addEventListener('dragover', e => { if(hasFiles(e)) e.preventDefault(); });
  document.addEventListener('dragleave', () => { if(--depth <= 0){ depth = 0; ov.classList.remove('on'); } });
  document.addEventListener('drop', e => {
    if(!hasFiles(e)) return;
    e.preventDefault(); depth = 0; ov.classList.remove('on');
    inspectImages([...(e.dataTransfer.files || [])]);
  });
})();

/* ── 첫 실행 안내 ── */
function refreshWelcome(){
  const w = $('welcome');
  if(!w) return;
  const tokenReady = /^pst-\S+/.test((STATE.token || '').trim());
  const promptReady = !!(STATE.base_prompt || '').trim();
  const dismissed = (STATE.ui || {}).welcome_off === true;
  const show = !(tokenReady && (promptReady || dismissed));
  w.classList.toggle('hidden', !show);
  document.body.dataset.onboarding = show ? '1' : '0';
  const api = $('welcomeApiStatus');
  if(api) api.textContent = tokenReady
    ? '연결 정보가 저장되어 있습니다. 생성 전에 잔액 확인으로 점검할 수 있습니다.'
    : '아직 토큰이 없습니다. 토큰 없이는 유료·무료 생성 요청을 보내지 않습니다.';
  const steps = [...(BUILDER['캐릭터단계'] || []), ...(BUILDER['베이스단계'] || [])];
  const data = $('welcomeDataStatus');
  if(data) data.textContent = steps.length
    ? `기본 후보 ${steps.length}단계가 준비되어 있습니다.`
    : '본체만 설치된 상태입니다. 생성은 가능하고, 빌더·태그 자동완성은 자료팩을 넣으면 열립니다.';
}
function bindWelcome(){
  if(window._welcomeBound) return;
  window._welcomeBound = true;
  bindDropZone($('welcomeDrop'), $('welcomeFile'));
  $('welcomeApi').addEventListener('click', () => {
    setMode('system');
    const token = $('token');
    if(token){ token.scrollIntoView({behavior:'smooth', block:'center'}); token.focus(); }
  });
  $('welcomePack').addEventListener('click', () => {
    STATE.ui = STATE.ui || {};
    STATE.ui.library_work = 'input';
    setMode('library');
    const pack = $('packDrop');
    if(pack) pack.scrollIntoView({behavior:'smooth', block:'center'});
  });
  $('welcomeLib').addEventListener('click', () => {
    const b = document.querySelector('[data-mode="library"]');
    if(b) b.click();
    openCombos(null);
  });
  $('welcomeSkip').addEventListener('click', () => {
    STATE.ui = STATE.ui || {}; STATE.ui.welcome_off = true;
    save(); refreshWelcome(); $('basePrompt').focus();
  });
  const loadWelcomeCount = () => fetch('/api/combos?limit=0').then(r => r.json()).then(r => {
    if(r.ok && $('welcomeCount')) $('welcomeCount').textContent = r.total.toLocaleString();
  }).catch(() => {});
  /* requestIdleCallback은 첫 페인트 직후 곧바로 실행될 수 있어 사용자가 누른
     조합 요청보다 먼저 같은 파일을 잡았다. 숫자는 기능이 아니므로 2.5초 뒤로
     미루고, 사용자가 조합 창을 먼저 열면 취소한다. */
  WELCOME_COUNT_TIMER = setTimeout(() => {
    WELCOME_COUNT_TIMER = null;
    loadWelcomeCount();
  }, 2500);
}


/* ── 단부루 검색 ──────────────────────────────────────────────────────
   태그로 실제 그림을 찾아 ① 태그 가져오기 ② 바이브·캐릭레퍼 등록
   ③ NAI 그림이면 그림체까지 추출. 썸네일은 /img 프록시로 받는다. */
let booruPage = 1;
const BCARD = {small: '110px', medium: '150px', large: '220px'};
async function booruSearch(next){
  const q = ($('booruQ').value || '').trim();
  const site = $('booruSite').value, limit = $('booruLimit').value;
  booruPage = next ? booruPage + 1 : 1;
  $('booruStat').textContent = '찾는 중...';
  const r = await (await fetch(`/api/booru?site=${site}&q=${encodeURIComponent(q)}`
    + `&page=${booruPage}&limit=${limit}`)).json();
  if(!r.ok){ $('booruStat').textContent = r.error || '검색 실패'; return; }
  $('booruStat').textContent = `${r.name} · ${r.count}장 (${booruPage}쪽)`
    + (r.note ? ' — ' + r.note : '');
  window._booruUrl = r.search_url;
  const g = $('booruGrid');
  if(!next) g.innerHTML = '';
  g.style.setProperty('--bcard', BCARD[$('booruCard').value] || '150px');
  r.items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'row'; el.style.margin = '0'; el.style.padding = '0'; el.style.overflow = 'hidden';
    const who = [it.artist, it.character, it.copyright].filter(Boolean).join(' · ').slice(0, 60);
    /* 부루 CDN 은 Cloudflare 챌린지 때문에 서버(프록시)로는 못 받는다.
       브라우저는 직접 받을 수 있으니 원본 주소를 그대로 쓰고, 실패하면 프록시로. */
    el.innerHTML = `<img src="${escA(it.thumb)}" loading="lazy" alt="" referrerpolicy="no-referrer"
        onerror="if(!this.dataset.retry){this.dataset.retry=1;
                 this.src='/img?u='+encodeURIComponent(this.dataset.src);}
                 else this.style.display='none';"
        data-src="${escA(it.thumb)}"
        style="width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#0004;">
      <div style="padding:6px 8px;">
        <div class="tag" style="margin-bottom:4px;">${it.score != null ? '★' + it.score : ''}
          ${it.rating ? ' · ' + esc(String(it.rating)) : ''}${who ? ' · ' + esc(who) : ''}</div>
        <div class="bar" style="flex-wrap:wrap;gap:4px;">
          <button data-btags="${escA(it.tags)}">태그</button>
          <button data-bref="${escA(it.full || it.thumb)}|vibe">바이브</button>
          <button data-bref="${escA(it.full || it.thumb)}|cref">캐릭레퍼</button>
          <button data-bstyle="${escA(it.full || it.thumb)}">그림체</button>
          <a href="${escA(it.url)}" target="_blank" style="font-size:var(--fs-xs);color:var(--muted);">원본↗</a>
        </div></div>`;
    g.appendChild(el);
  });
  g.querySelectorAll('[data-btags]').forEach(b => b.addEventListener('click', () => {
    const tags = b.dataset.btags.split(/\s+/).filter(Boolean).map(t => t.replace(/_/g, ' ')).join(', ');
    const cur = $('basePrompt').value.trim().replace(/,$/, '');
    STATE.base_prompt = cur ? cur + ', ' + tags : tags;
    $('basePrompt').value = STATE.base_prompt; clearActiveStyle(); tokens(); save();
    $('booruStat').textContent = '태그를 베이스에 붙였습니다 ✓';
  }));
  g.querySelectorAll('[data-bref]').forEach(b => b.addEventListener('click', async () => {
    const [url, kind] = b.dataset.bref.split('|');
    $('booruStat').textContent = '받아서 등록 중...';
    try{
      const blob = await (await fetch('/img?u=' + encodeURIComponent(url))).blob();
      const f = new File([blob], `booru_${Date.now()}.png`, {type: 'image/png'});
      await addRefs([f], kind);
      $('booruStat').textContent = (kind === 'vibe' ? '바이브' : '캐릭레퍼') + ' 등록 ✓';
    }catch(e){ $('booruStat').textContent = String(e); }
  }));
  g.querySelectorAll('[data-bstyle]').forEach(b => b.addEventListener('click', async () => {
    $('booruStat').textContent = '그림체 추출 중...';
    try{
      const blob = await (await fetch('/img?u=' + encodeURIComponent(b.dataset.bstyle))).blob();
      const f = new File([blob], `booru_${Date.now()}.png`, {type: 'image/png'});
      const n = await inspectImages([f]);
      if(!n) $('booruStat').textContent = 'NAI 로 만든 그림이 아니라 생성 정보가 없습니다.';
    }catch(e){ $('booruStat').textContent = String(e); }
  }));
  $('booruMore').style.display = r.count >= Number(limit) ? '' : 'none';
}
function bindBooru(){
  if(!$('booruGo') || $('booruGo')._bound) return;
  $('booruGo')._bound = true;
  $('booruGo').addEventListener('click', () => booruSearch(false));
  $('booruQ').addEventListener('keydown', e => { if(e.key === 'Enter') booruSearch(false); });
  ['booruSite','booruLimit'].forEach(id => $(id).addEventListener('change', () => booruSearch(false)));
  $('booruCard').addEventListener('change', () =>
    $('booruGrid').style.setProperty('--bcard', BCARD[$('booruCard').value] || '150px'));
  $('booruMore').addEventListener('click', () => booruSearch(true));
  /* 검색 전에는 고른 사이트의 첫 화면으로 (예전엔 늘 단부루로 갔다) */
  const HOMES = {danbooru:'https://danbooru.donmai.us/posts',
                 gelbooru:'https://gelbooru.com/index.php?page=post&s=list',
                 e621:'https://e621.net/posts'};
  $('booruOpen').addEventListener('click', () =>
    window.open(window._booruUrl || HOMES[$('booruSite').value] || HOMES.danbooru, '_blank'));
}

/* ── 레시피 라이브러리 ── */
const AXIS_KO = {artist:'작가', style:'화풍', camera:'카메라', background:'배경', effect:'효과',
  hair:'머리', outfit:'의상', body:'신체', body_state:'신체상태', expression:'표정',
  pose:'포즈', action:'행동', sexual_action:'성행위', character:'캐릭터', unknown:'기타'};
let recT = null, recOffset = 0;
let RECIPES_READY = false, RECIPES_LOADING = false, RECIPES_OBSERVER = null;

function bindRecipes(){
  const q = $('recQ'), grid = $('recGrid');
  if(!q || !grid || q._bound) return;
  q._bound = true;
  const request = () => {
    clearTimeout(recT);
    recT = setTimeout(() => RECIPES_READY ? loadRecipes(false) : ensureRecipes(), 300);
  };
  q.addEventListener('input', request);
  $('recAxis').addEventListener('change', () =>
    RECIPES_READY ? loadRecipes(false) : ensureRecipes());
  $('recMore').addEventListener('click', () => loadRecipes(true));
  const target = grid.closest('.card') || grid;
  if('IntersectionObserver' in window){
    RECIPES_OBSERVER = new IntersectionObserver(entries => {
      if(entries.some(entry => entry.isIntersecting)){
        RECIPES_OBSERVER.disconnect();
        RECIPES_OBSERVER = null;
        ensureRecipes();
      }
    }, {rootMargin:'240px 0px'});
    RECIPES_OBSERVER.observe(target);
  }else{
    /* 구형 브라우저에서도 첫 화면과 겹치지 않게 충분히 뒤로 미룬다. */
    setTimeout(ensureRecipes, 2500);
  }
}

async function ensureRecipes(){
  if(RECIPES_READY || RECIPES_LOADING) return;
  RECIPES_LOADING = true;
  if($('recStat')) $('recStat').textContent = '레시피를 불러오는 중...';
  try{
    await loadRecipes(false);
    RECIPES_READY = true;
  }catch(e){
    if($('recStat')) $('recStat').textContent = '레시피를 불러오지 못했습니다. 검색하면 다시 시도합니다.';
  }finally{
    RECIPES_LOADING = false;
  }
}

async function loadRecipes(append){
  const q = ($('recQ') || {}).value || '';
  const ax = ($('recAxis') || {}).value || '';
  if(!append) recOffset = 0;
  const r = await (await fetch(`/api/recipes?q=${encodeURIComponent(q)}&axis=${encodeURIComponent(ax)}&limit=60&offset=${recOffset}`)).json();
  if(!r.ok) throw new Error(r.error || '레시피 불러오기 실패');
  $('recStat').textContent = `${r.matched.toLocaleString()} / ${r.total.toLocaleString()}건`;
  const sel = $('recAxis');
  if(sel.options.length <= 1){
    Object.entries(r.axes).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => {
      const o = document.createElement('option');
      o.value = k; o.textContent = `${AXIS_KO[k]||k} (${v})`;
      sel.appendChild(o);
    });
  }
  const g = $('recGrid');
  if(!append) g.innerHTML = '';
  r.items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'row'; el.style.cursor = 'pointer'; el.style.margin = '0'; el.style.padding = '0';
    el.style.overflow = 'hidden';
    const img = (it.images && it.images[0]) ? `<img src="/img?u=${encodeURIComponent(it.images[0])}" loading="lazy"
      onerror="this.style.display='none'" alt=""
      style="width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#0004;">` : '';
    el.innerHTML = `${img}<div style="padding:8px 10px;">
      <div class="tag" style="margin-bottom:4px;">${esc(AXIS_KO[it.axis]||it.axis)}${it.concept_ko ? ' · ' + esc(it.concept_ko) : ''}</div>
      <b style="font-size:var(--fs-2xs);line-height:1.35;display:block;">${esc((it.title||'(제목 없음)').slice(0,48))}</b></div>`;
    el.addEventListener('click', () => openRecipe(it));
    g.appendChild(el);
  });
  recOffset += r.items.length;
  $('recMore').style.display = (recOffset < r.matched) ? '' : 'none';
  $('recMore').textContent = `더 보기 ▾ (${recOffset.toLocaleString()} / ${r.matched.toLocaleString()})`;
}
function openRecipe(it){
  window._mm = 'recipe';
  $('modalTitle').textContent = `${AXIS_KO[it.axis]||it.axis} · ${it.title || '레시피'}`;
  const b = $('modalBody');
  b.innerHTML = `
    ${(it.images && it.images.length) ? `<div class="grid2" style="margin-bottom:10px;">
      ${it.images.map(u => `<img src="/img?u=${encodeURIComponent(u)}" style="width:100%;border-radius:var(--radius);border:1px solid var(--line);">`).join('')}</div>` : ''}
    <div class="row"><div class="tag">태그 ${it.tags.length}개</div>
      <div>${it.tags.map(x => `<span class="chip" data-rt="${escA(x)}">${esc(x)}</span>`).join('')}</div></div>
    ${it.positive ? `<div class="field"><label>포지티브</label><textarea readonly style="min-height:70px;">${esc(it.positive)}</textarea></div>` : ''}
    ${it.negative ? `<div class="field"><label>네거티브</label><textarea readonly style="min-height:52px;">${esc(it.negative)}</textarea></div>` : ''}
    <div class="bar">
      <button class="primary" id="recToBase">베이스 프롬프트로</button>
      <button id="recAppend">베이스에 이어붙이기</button>
      <button id="recToChar">캐릭터 칸에 추가</button>
      ${it.negative ? '<button id="recToNeg">네거티브로</button>' : ''}
      ${it.url ? `<a href="${escA(it.url)}" target="_blank" style="font-size:var(--fs-xs);color:var(--muted);margin-left:auto;">원본 보기 ↗</a>` : ''}
    </div>`;
  const body = it.positive || it.tags.join(', ');
  $('recToBase').addEventListener('click', () => {
    STATE.base_prompt = body; $('basePrompt').value = body; clearActiveStyle();
    tokens(); save(); $('modalFlash').textContent = '베이스로 적용됨 ✓';
  });
  $('recAppend').addEventListener('click', () => {
    const cur = $('basePrompt').value.trim().replace(/,$/, '');
    const v = cur ? cur + ', ' + body : body;
    STATE.base_prompt = v; $('basePrompt').value = v; clearActiveStyle();
    tokens(); save(); $('modalFlash').textContent = '이어붙였습니다 ✓';
  });
  $('recToChar').addEventListener('click', () => {
    (STATE.char_slots = STATE.char_slots || []).push({name: it.title.slice(0,20) || '레시피', prompt: body, negative: ''});
    renderSlots(); tokens(); save(); $('modalFlash').textContent = '캐릭터 칸에 추가됨 ✓';
  });
  if($('recToNeg')) $('recToNeg').addEventListener('click', () => {
    STATE.negative_prompt = it.negative; $('negPrompt').value = it.negative;
    clearActiveStyle(); tokens(); save(); $('modalFlash').textContent = '네거티브로 적용됨 ✓';
  });
  b.querySelectorAll('[data-rt]').forEach(c => c.addEventListener('click', () => {
    const cur = $('basePrompt').value.trim().replace(/,$/, '');
    const v = cur ? cur + ', ' + c.dataset.rt : c.dataset.rt;
    STATE.base_prompt = v; $('basePrompt').value = v; clearActiveStyle(); tokens(); save();
    c.classList.add('on');
  }));
  $('modalFlash').textContent = '';
  $('modalBg').style.display = 'flex';
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

/* ── 모달 저장/닫기 ── */
$('modalClose').addEventListener('click', () => {
  if(window._mm === 'combo') discardComboReturn();
  $('modalBg').style.display = 'none';
  $('modalBody').closest('.modal').classList.remove('builder-modal');
});
$('modalBg').addEventListener('click', e => {
  if(e.target.id === 'modalBg'){
    if(window._mm === 'combo') discardComboReturn();
    $('modalBg').style.display = 'none';
    $('modalBody').closest('.modal').classList.remove('builder-modal');
  }
});
$('modalSave').addEventListener('click', async () => {
  const m = window._mm;
  if(m === 'lib' || m === 'opts' || m === 'recipe' || m === 'combo'){
    if(m === 'combo') discardComboReturn();
    $('modalBg').style.display = 'none';
    return;
  }
  if(m === 'scene'){
    const u = {};
    /* 프롬프트·해상도와 씬 전용 위치를 한 요청으로 저장한다. */
    $('modalBody').querySelectorAll('[data-sid]').forEach(t => {
      if(t.dataset.sk === '_res') return;
      (u[t.dataset.sid] = u[t.dataset.sid]||{})[t.dataset.sk] = t.value;
    });
    $('modalBody').querySelectorAll('[data-posuse]').forEach(box => {
      const sid = box.dataset.posuse;
      const centers = [];
      if(box.checked){
        $('modalBody').querySelectorAll(`[data-scenter="${sid}"]`).forEach(input => {
          const i = Number(input.dataset.ci);
          centers[i] = centers[i] || {};
          centers[i][input.dataset.axis] = Number(input.value);
        });
      }
      (u[sid] = u[sid] || {}).char_centers = centers;
    });
    $('modalBody').querySelectorAll('[data-refuse]').forEach(box => {
      const sid = box.dataset.refuse;
      const refs = [];
      $('modalBody').querySelectorAll(`[data-sref="${sid}"]`).forEach(select => {
        refs[Number(select.dataset.ri)] = select.value;
      });
      const fields = (u[sid] = u[sid] || {});
      fields.use_character_refs = box.checked;
      fields.character_refs = refs;
    });
    const r = await (await fetch('/api/scene_save', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({
        setting:window._sceneSetting, updates:u
      })})).json();
    if(r.ok){
      window._sceneUndo = {setting:r.setting, before:r.before, revision:r.revision};
      window._sceneRevision = r.revision || window._sceneRevision;
      if($('sceneUndo')) $('sceneUndo').disabled = !r.fields;
      $('modalFlash').textContent = `저장됨 ✓ ${r.updated}씬 · ${r.fields}항목`;
    } else $('modalFlash').textContent = r.error || '실패';
    return;
  }
  if(m === 'style' || m === 'char'){
    const name = ($('bldName') || {value:''}).value.trim();
    if(!name){ alert('이름을 입력해주세요.'); return; }
    const composed = window._comp ? window._comp() : '';
    const negative = window._compNeg ? window._compNeg() : (($('bldNeg') || {value:''}).value || '');
    if(!composed){ alert('선택된 태그가 없습니다.'); return; }
    const groups = {};
    $('modalBody').querySelectorAll('.sec').forEach(sec => {
      const step = sec.querySelector('.nm').textContent;
      sec.querySelectorAll('[data-slot]').forEach(f => {
        const lb = f.querySelector('.slot-name');
        const vals = Array.from(f.querySelectorAll('select')).map(s => s.value).filter(Boolean);
        if(vals.length && lb) groups[`${step}·${lb.textContent}`] = vals.join(', ');
      });
    });
    const ex = ($('bldExtra') || {}).value;
    if(ex && ex.trim()) groups['추가'] = ex.trim();
    if(m === 'style'){
      const r = await (await fetch('/api/style_save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name, prompt: composed, groups,
          negative, settings:styleSettingsFromUI()})})).json();
      if(r.ok){ STYLES = r.styles; renderPresets(); renderLibrary(); $('modalFlash').textContent = `그림체/${name}.json 저장됨 ✓`; }
      else $('modalFlash').textContent = r.error;
    } else {
      const r = await (await fetch('/api/norm_save', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({type:'char', name, negative,
          groups:{'조합': composed}, builder_groups: groups})})).json();
      if(r.ok){
        STATE.characters = r.characters;
        let used = false;
        if(($('bldUseNow') || {}).checked){
          const c = r.characters[r.characters.length - 1] || {};
          (STATE.char_slots = STATE.char_slots || []).push(characterBundle(
            Object.assign({name, female:composed, negative}, c), true));
          autoCoordsOnSecond();
          used = true;
          save();
        }
        renderLibrary(); renderSlots(); tokens();
        $('modalFlash').textContent = `캐릭터 '${name}' 저장됨 ✓` + (used ? ' · 캐릭터 칸에 추가됨' : '');
      }
      else $('modalFlash').textContent = r.error;
    }
    return;
  }
  if(m === 'norm'){
    const name = $('nmName').value.trim();
    if(!name){ alert('이름을 입력해주세요.'); return; }
    const groups = {};
    $('modalBody').querySelectorAll('[data-ng]').forEach(t => { if(t.value.trim()) groups[t.dataset.ng] = t.value.trim(); });
    const isS = $('nmType').value === 'style';
    const r = await (await fetch('/api/norm_save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({type: isS?'style':'char', name, groups})})).json();
    if(r.ok){
      if(isS){ STYLES = r.styles; renderPresets(); } else { STATE.characters = r.characters; renderSlots(); }
      renderLibrary();
      $('modalFlash').textContent = `'${name}' 저장됨 ✓`;
    } else $('modalFlash').textContent = r.error;
  }
});

/* ── UI 테마 ── */
/* '' = 슬레이트(:root 기본). 밝은 것 먼저, 어두운 것 뒤로 묶어 뒀다 */
/* [값, 이름, 배경, 카드, 강조] — 칩에 그 테마 색을 실제로 보여 준다 */
const THEMES = [
  ['','슬레이트','#f3efe5','#fffdf8','#0f6b62'],
  ['paper','종이','#f3efe5','#fffdf8','#0f6b62'],
  ['sepia','고서','#e9e0ce','#fcf6e9','#6f5b2d'],
  ['sakura','벚꽃','#f3e9e8','#fffaf8','#8a4d5a'],
  ['midnight','미드나잇','#141311','#1c1b18','#62cbbe'],
  ['ocean','오션','#141311','#1c1b18','#62cbbe'],
  ['forest','포레스트','#141311','#1c1b18','#62cbbe'],
  ['terminal','터미널','#141311','#1c1b18','#62cbbe'],
  ['mono','모노크롬','#141311','#1c1b18','#62cbbe'],
  ['wine','와인','#141311','#1c1b18','#62cbbe'],
];
const LAYOUTS = [['studio','작업실'],['classic','기존 호환']];
const ACCENTS = [['','기본'],['blue','파랑'],['violet','보라'],['pink','분홍'],['green','초록'],['amber','앰버'],['cyan','시안'],['red','빨강']];
const FSIZES = [['s','작게'],['','보통'],['l','크게'],['xl','아주 크게']];
const RADII = [['','기본'],['soft','살짝 둥글게'],['round','둥글게']];
function applyUI(){
  const u = STATE.ui || {};
  const r = document.documentElement;
  /* 옛 설정 이관 — 'slate'·'sharp' 는 이제 :root 기본값 자체다.
     그냥 두면 칩 강조가 어긋나므로 빈 값으로 접어 준다. */
  if(u.theme === 'slate') u.theme = '';
  if(u.radius === 'sharp') u.radius = '';
  const layout = u.layout === 'classic' ? 'classic' : 'studio';
  layout === 'studio'
    ? r.setAttribute('data-layout', 'studio')
    : r.removeAttribute('data-layout');
  u.theme ? r.setAttribute('data-theme', u.theme) : r.removeAttribute('data-theme');
  u.accent ? r.setAttribute('data-accent', u.accent) : r.removeAttribute('data-accent');
  u.fs ? r.setAttribute('data-fs', u.fs) : r.removeAttribute('data-fs');
  u.radius ? r.setAttribute('data-radius', u.radius) : r.removeAttribute('data-radius');
  arrangeStudioWorkspace();
}
function renderUIChips(){
  const mk = (host, list, key) => {
    const h = $(host); if(!h) return;
    h.innerHTML = '';
    list.forEach(([v, label, bg, card, accent]) => {
      const c = document.createElement('span');
      const current = key === 'layout'
        ? ((STATE.ui||{}).layout === 'classic' ? 'classic' : 'studio')
        : ((STATE.ui||{})[key]||'');
      c.className = 'chip' + (current === v ? ' on' : '');
      if(bg){
        /* 테마 칩은 그 테마의 배경·카드·강조색을 작은 점으로 미리 보여 준다 */
        c.innerHTML = `<span style="display:inline-flex;gap:2px;vertical-align:-1px;margin-right:5px;">
          <i style="width:8px;height:8px;background:${bg};border:1px solid #8886;display:inline-block;"></i>
          <i style="width:8px;height:8px;background:${card};border:1px solid #8886;display:inline-block;"></i>
          <i style="width:8px;height:8px;background:${accent};border:1px solid #8886;display:inline-block;"></i>
        </span>${label}`;
      } else c.textContent = label;
      c.addEventListener('click', () => {
        STATE.ui = STATE.ui || {};
        STATE.ui[key] = v;
        applyUI(); renderUIChips(); save();
      });
      h.appendChild(c);
    });
  };
  mk('layoutChips', LAYOUTS, 'layout');
  mk('themeChips', THEMES, 'theme');
  mk('accentChips', ACCENTS, 'accent');
  mk('fsChips', FSIZES, 'fs');
  mk('radiusChips', RADII, 'radius');
}

/* ── 상태 폴링 ── */
let lastFile = '';
let WAS_RUNNING = false;
let LAST_LIVE_STATUS = null;
const LIVE_PHASE_LABEL = {
  idle:'대기', running:'진행 중', stopping:'중지 중', completed:'완료',
  partial:'일부 실패', failed:'실패', stopped:'중지됨'
};
function compactDuration(seconds){
  const n = Math.max(0, Math.round(Number(seconds) || 0));
  if(n < 60) return `${n}초`;
  const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60);
  return h ? `${h}시간 ${m}분` : `${m}분`;
}
if($('pvReturn')) $('pvReturn').addEventListener('click', () => {
  const mode = LAST_LIVE_STATUS && LAST_LIVE_STATUS.retry_mode;
  setMode(['preview','settings','builder','library','system'].includes(mode) ? mode : 'preview');
});
async function poll(){
  try{
    const s = await (await fetch('/status.json', {cache:'no-store'})).json();
    LAST_LIVE_STATUS = s;
    $('pvName').textContent = s.operation || s.char_name || '대기 중';
    $('pvFile').textContent = s.filename || '아직 저장된 파일 없음';
    $('pvStatus').textContent = s.status_text || '-';
    $('pvPhase').dataset.phase = s.phase || 'idle';
    $('pvPhase').textContent = LIVE_PHASE_LABEL[s.phase] || s.phase || '대기';
    $('pvProg').textContent = `${s.index} / ${s.total}`;
    $('pvCounts').textContent = `성공 ${s.completed || 0} · 실패 ${s.failed || 0}`
      + (s.retry_count ? ` · 자동 재시도 ${s.retry_count}` : '');
    $('pvEta').textContent = s.running
      ? (s.eta_seconds == null
          ? `남은 시간 계산 중${s.elapsed_seconds ? ` · 경과 ${compactDuration(s.elapsed_seconds)}` : ''}`
          : `약 ${compactDuration(s.eta_seconds)} 남음 · 경과 ${compactDuration(s.elapsed_seconds)}`)
      : (s.phase === 'completed' && s.elapsed_seconds
          ? `걸린 시간 ${compactDuration(s.elapsed_seconds)}` : '남은 시간 —');
    $('pvDaily').textContent = `오늘 ${s.daily} / ${s.daily_cap}`;
    $('pvReturn').classList.toggle('hidden', !s.can_retry || !!s.running);
    $('pvBar').style.width = (s.total ? Math.round(s.index/s.total*100) : 0) + '%';
    lastSeed = s.seed || 0;
    $('pvSeedRow').style.display = lastSeed ? 'flex' : 'none';
    $('pvSeed').textContent = '시드 ' + lastSeed + (s.seed_key ? ` (회차 ${s.seed_key})` : '');
    if(s.has_image){
      const u = '/latest.webp?t=' + Date.now();
      $('pvImg').innerHTML = `<img src="${u}">`;
      if(s.filename && s.filename !== lastFile){
        lastFile = s.filename;
        HIST.unshift(u); HIST = HIST.slice(0, 12);
        $('hist').innerHTML = HIST.map(x => `<img src="${x}">`).join('');
      }
    }
    $('pvResultActions').classList.toggle('hidden', !s.has_image);
    $('batchBtn').disabled = s.running;
    $('genBtn').disabled = s.running;
    $('genBtn').textContent = s.running ? '생성 중...' : '생성';
    if($('stopBtn')){
      $('stopBtn').classList.toggle('hidden', !s.running);
      $('stopBtn').disabled = !!s.stopping;
      $('stopBtn').textContent = s.stopping ? '중지 중…' : '■ 중지';
    }
    /* 돌던 것이 멈춘 순간에만 한 번 알린다 (계속 울리면 안 된다) */
    if(WAS_RUNNING && !s.running) notifyDone(s.status_text || '생성이 끝났습니다.');
    WAS_RUNNING = s.running;
  }catch(e){}
  setTimeout(poll, 1400);
}

init();
bindLatestResultActions();
poll();

/* ── 왼쪽 패널 폭 드래그 조절 — 브라우저별 취향이라 localStorage 에 저장 ── */
(function(){
  const d = $('lwDrag');
  if(!d) return;
  const clamp = w => Math.min(560, Math.max(240, w));
  const apply = w => document.documentElement.style.setProperty('--lw', w + 'px');
  const saved = parseInt(localStorage.getItem('lw') || '', 10);
  if(saved) apply(clamp(saved));
  let on = false;
  d.addEventListener('mousedown', e => { on = true; e.preventDefault(); });
  document.addEventListener('mousemove', e => { if(on) apply(clamp(e.clientX)); });
  document.addEventListener('mouseup', e => {
    if(!on) return;
    on = false;
    localStorage.setItem('lw', clamp(e.clientX));
  });
})();

/* ── 패널 접기 (Forge · blue 둘 다 갖고 있다) ────────────────────────────
   Forge v1.2.11 는 타이틀바에서 좌패널을 감추고(`CustomTitleBar.tsx:110-`),
   blue v2.11.2 는 좌·우 둘 다 감추고 그 상태를 저장한다(`layout-store.ts:6-37`).
   우리는 폭 손잡이만 있어 자료·세팅 탭에서 프롬프트 칸이 차지한 자리를 되찾을 수
   없었다 (1600 에서 좌 440 + 우 300 = 46% 가 그 탭의 일과 무관하게 고정).
   ⚠ 저장은 `--lw` 와 같이 **localStorage** 에 둔다. 브라우저별 취향이고,
     `설정.json` 에 넣으면 옛 설정 파일과 스키마가 갈린다. */
(function(){
  const app = $('app');
  if(!app) return;
  const PANES = [['togLeft', 'lhide', 'panelL'], ['togRight', 'rhide', 'panelR']];
  const paint = (btn, hidden) => {
    if(!btn) return;
    btn.setAttribute('aria-pressed', hidden ? 'true' : 'false');
  };
  PANES.forEach(([id, attr, key]) => {
    const btn = $(id);
    const hidden = localStorage.getItem(key) === '1';
    if(hidden) app.setAttribute('data-' + attr, '1');
    paint(btn, hidden);
    if(!btn) return;
    btn.addEventListener('click', () => {
      const now = app.getAttribute('data-' + attr) === '1';
      if(now) app.removeAttribute('data-' + attr);
      else app.setAttribute('data-' + attr, '1');
      localStorage.setItem(key, now ? '0' : '1');
      paint(btn, !now);
    });
  });
  /* Alt+[ / Alt+] — 탭 전환이 Alt+1~5 라 같은 결로 맞췄다 */
  document.addEventListener('keydown', e => {
    if(!e.altKey || e.ctrlKey || e.metaKey) return;
    if(e.key === '[' && $('togLeft')){ e.preventDefault(); $('togLeft').click(); }
    if(e.key === ']' && $('togRight')){ e.preventDefault(); $('togRight').click(); }
  });
})();

/* ── 태그 검증 ────────────────────────────────────────────────────────
   posts.json 은 비로그인 태그 2개 제한이 있지만 tags.json 은 제한이 없다.
   없는 태그는 그림에 아무 영향 없이 토큰만 먹으므로 찾아낼 값어치가 있다. */
async function runTagVerify(){
  const box = $('tagVerifyOut'), btn = $('tagVerifyBtn');
  if(!box) return;
  const text = [$('basePrompt').value, $('baseFixed') ? $('baseFixed').value : '',
                $('baseVar') ? $('baseVar').value : '',
                $('baseDetail') ? $('baseDetail').value : ''].join(',');
  if(!text.replace(/[,\s]/g, '')){ box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  box.innerHTML = '<span style="color:var(--muted)">확인 중...</span>';
  if(btn) btn.style.opacity = '.4';
  try{
    const r = await (await fetch('/api/verify_tags', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})})).json();
    if(!r.ok){ box.innerHTML = '<span style="color:#e0574e">'+(r.error||'실패')+'</span>'; return; }
    const s = r.summary || {};
    const ghosts = (r.items||[]).filter(x => x.status === 'ghost');
    const lows   = (r.items||[]).filter(x => x.status === 'low');
    const olds   = (r.items||[]).filter(x => x.status === 'old');
    const als    = (r.items||[]).filter(x => x.status === 'alias');
    const nais   = (r.items||[]).filter(x => x.status === 'nai_renamed');
    let html = '<b>있음 '+(s.ok||0)+'</b>'
      + ' · <span style="color:#c9a227">드묾 '+(s.low||0)+'</span>'
      + (s.old ? ' · <span style="color:#4a7cc4">폐지됨 '+s.old+'</span>' : '')
      + (s.alias ? ' · <span style="color:#4a7cc4">이름바뀜 '+s.alias+'</span>' : '')
      + (s.nai_renamed ? ' · <span style="color:#7950a8">NAI 개명 '+s.nai_renamed+'</span>' : '')
      + ' · <span style="color:#e0574e">없음 '+(s.ghost||0)+'</span>'
      + (s.unknown ? ' · <span style="color:var(--muted)">확인못함 '+s.unknown+'</span>' : '')
      + ' <span style="color:var(--muted)">(단부루 기준 · 100장 미만이면 드묾)</span>';
    /* 품질·스타일 낱말은 단부루 태그가 아니다 — '없음' 이 곧 잘못이라는 뜻은 아니라고 알려 준다 */
    if((s.ghost||0) > 0){
      html += '<div style="color:var(--muted);margin-top:3px;">'
        + 'best quality · 8k 처럼 품질·화풍을 가리키는 낱말은 단부루 태그가 아니어서 여기 걸립니다'
        + ' (NAI 는 알아듣기도 합니다).</div>';
    }
    if(ghosts.length){
      html += '<div style="margin-top:5px;">';
      ghosts.forEach(g => {
        html += '<div><span style="color:#e0574e">✗ '+esc(g.raw)+'</span>';
        if((g.suggest||[]).length){
          html += ' <span style="color:var(--muted)">→</span> ' + g.suggest.map(x =>
            '<span class="tvsug" data-old="'+esc(g.raw)+'" data-new="'+esc(x.name)+'" '
            + 'style="cursor:pointer;text-decoration:underline dotted;" '
            + 'title="눌러서 바꾸기">'+esc(x.name)+'<span style="opacity:.6">('+x.count+')</span></span>'
          ).join(', ');
        }
        html += '</div>';
      });
      html += '</div>';
    }
    if(lows.length){
      html += '<div style="margin-top:4px;color:#c9a227">△ '
        + lows.map(x => esc(x.raw)+'('+x.count+')').join(', ') + '</div>';
    }
    /* 폐지된 태그 — 단부루 어휘에는 있지만 더는 쓰지 않는다.
       NAI 는 학습 당시 사전을 쓰므로 대개 알아듣는다. 없는 태그와 구분해서 보여 준다. */
    if(olds.length){
      html += '<div style="margin-top:4px;color:#4a7cc4">↷ 폐지된 태그(NAI 는 대개 알아듣습니다): '
        + olds.map(x => esc(x.raw)).join(', ') + '</div>';
    }
    /* 이름이 바뀐 것 — 새 이름을 눌러서 바로 갈아 끼울 수 있다 */
    if(als.length){
      html += '<div style="margin-top:4px;color:#4a7cc4">↷ 이름 바뀜: ' + als.map(x =>
        esc(x.raw)+' → <span class="tvsug" data-old="'+esc(x.raw)+'" data-new="'+esc(x.alias_to)
        + '" style="cursor:pointer;text-decoration:underline dotted;" title="눌러서 새 이름으로">'
        + esc(x.alias_to)+'</span>').join(', ') + '</div>';
    }
    /* NovelAI가 단부루 원래 이름과 다르게 쓰는 공식 개명 태그 */
    if(nais.length){
      html += '<div style="margin-top:4px;color:#7950a8">◆ NovelAI 권장 이름: ' + nais.map(x =>
        esc(x.raw)+' → <span class="tvsug" data-old="'+esc(x.raw)+'" data-new="'+esc(x.alias_to)
        + '" style="cursor:pointer;text-decoration:underline dotted;" title="눌러서 NovelAI 이름으로">'
        + esc(x.alias_to)+'</span>').join(', ') + '</div>';
    }
    if(r.error) html += '<div style="color:var(--muted);margin-top:4px;">일부 확인 실패: '+esc(r.error)+'</div>';
    box.innerHTML = html;
    /* 후보를 누르면 프롬프트에서 그 태그만 바꿔 준다 */
    box.querySelectorAll('.tvsug').forEach(el => el.addEventListener('click', () => {
      const oldT = el.dataset.old, newT = el.dataset.new;
      ['basePrompt','baseFixed','baseVar','baseDetail'].forEach(id => {
        const t = $(id); if(!t) return;
        const parts = t.value.split(',');
        let hit = false;
        const next = parts.map(x => {
          if(!hit && x.trim() === oldT.trim()){ hit = true; return x.replace(oldT.trim(), newT); }
          return x;
        });
        if(hit){ t.value = next.join(','); t.dispatchEvent(new Event('input')); }
      });
      runTagVerify();
    }));
  }catch(e){
    box.innerHTML = '<span style="color:#e0574e">확인 실패: '+e+'</span>';
  }finally{
    if(btn) btn.style.opacity = '';
  }
}
if($('tagVerifyBtn')) $('tagVerifyBtn').addEventListener('click', (e) => {
  e.stopPropagation();   /* 머리를 누르면 접히므로 막는다 */
  runTagVerify();
});
