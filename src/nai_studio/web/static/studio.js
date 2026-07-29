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
