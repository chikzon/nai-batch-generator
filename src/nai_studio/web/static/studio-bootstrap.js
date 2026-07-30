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
  if(ACTIVE_MODES.has('settings')){
    renderSettings(); sbPickList(); paintClash();
  }
  tokens(); counts();
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
  renderPresets(); renderSlots();
  renderFrags(); applySplit3(); paintPace(); acScan(document);
  bindWelcome(); refreshWelcome();
  setupHL(); bindHLToggle(); bindDirector(); bindRefs(); bindUseCoords();
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
  applyUI(); renderUIChips();
  if($('notifySound')) $('notifySound').checked = !!(STATE.ui||{}).notify_sound;
  if($('notifySystem')) $('notifySystem').checked = !!(STATE.ui||{}).notify_system;
  tokens();
}



/* 실제 NAI 토큰 수 — 서버의 T5 토크나이저에 물어본다 (입력이 멈추면 한 번) */
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
  const libraryWork = ['input','review','catalog','results'].includes(
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
const ACTIVE_MODES = new Set(['preview']);
function activateMode(mode){
  if(ACTIVE_MODES.has(mode)) return;
  ACTIVE_MODES.add(mode);
  if(mode === 'settings'){
    renderSettings(); renderScenePresets(); renderScenes();
    sbPickList(); paintClash(); bindComparison();
  }else if(mode === 'library'){
    renderLibrary(); bindBooru(); bindRecipes(); bindLibraryReview();
    if($('expGrid')) expLoad('');
  }else if(mode === 'builder'){
    renderScenes();
  }else if(mode === 'system'){
    bindUserBackup(); bindTrashCenter(); bindLocalImageIntegrity();
  }
}
function setMode(m){
  activateMode(m);
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

/* 모든 기능 선언과 영구 바인딩이 준비된 뒤 한 번만 시작한다. 기능별 화면은 첫 진입 때
   activateMode()가 초기화해 첫 생성 화면에서 자료·휴지통 조회가 경쟁하지 않게 한다. */
init();
bindLatestResultActions();
poll();
