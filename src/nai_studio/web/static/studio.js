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
const ACTIVE_MODES = new Set(['preview']);
function activateMode(mode){
  if(ACTIVE_MODES.has(mode)) return;
  ACTIVE_MODES.add(mode);
  if(mode === 'settings'){
    renderSettings(); renderScenePresets(); renderScenes();
    sbPickList(); paintClash(); bindComparison();
  }else if(mode === 'library'){
    renderLibrary(); bindBooru(); bindRecipes();
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
