/* API·작업 Queue·출력 도구·백업·복구·진단·제품 환경 관리 화면.
   기능별 화면 뒤, 공통 onboarding·modal·bootstrap보다 먼저 읽는다. */

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
    const DECISION_KO = {
      'take-incoming': '들어오는 값만 바뀜',
      'keep-current': '내 쪽만 바뀜',
      'both-changed': '양쪽 다 바뀜 — 직접 선택',
      'no-base': '공통 기준 없음(2-way)',
    };
    card.innerHTML = `<div class="bar">
      <input type="checkbox" data-backup-change="${escA(change.id)}" style="width:auto;flex:none;"
        ${change.selected?'checked':''}>
      <b>${esc(change.logical)}</b><span class="tag">${esc(change.action)}</span>`
      + (change.decision && change.decision !== 'no-base'
        ? `<span class="tag">${esc(DECISION_KO[change.decision] || change.decision)}</span>`
        : '') + `</div>
      <div class="hint">${esc(change.pointer)} · ${esc(change.file_status)}`
      + (change.base_available
        ? ` · 공통 기준 ${esc(String(change.base_sha256).slice(0,12))}`
        : ' · 공통 기준 미제공') + `</div>`
      + (change.base_found && change.decision !== 'no-base'
        ? `<details><summary>기준값</summary>${backupValue(change.base, true)}</details>`
        : '') + `
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

$('tokenShow').addEventListener('click', () => {
  const input = $('token'), show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  $('tokenShow').textContent = show ? '숨기기' : '보기';
  $('tokenShow').setAttribute('aria-pressed', show ? 'true' : 'false');
});
/* 제품 갱신 — 공식 GitHub Release만 확인, SHA 일치 시만 완료, 무인 설치 없음 */
let UPDATE_POLL = null;
function bindUpdateCard(){
  const card = $('updateCard');
  if(!card || card._bound) return;
  card._bound = true;
  const msg = $('updateMsg');
  const paint = st => {
    if(!st) return;
    if(!st.ok && !st.downloading){
      msg.textContent = (st.error || '확인 실패')
        + (st.current ? ` · 현재 버전 ${st.current} 유지` : '');
      return;
    }
    let text = st.update_available
      ? `새 버전 ${st.latest} (현재 ${st.current}) · 설치본 `
        + `${((st.download_size||0)/1048576).toFixed(1)}MB`
        + (st.notes ? ` · ${String(st.notes).split('\n')[0].slice(0,80)}` : '')
      : `현재 ${st.current} — 최신입니다.`;
    if(st.update_available) $('updateDownload').classList.remove('hidden');
    if(st.downloading) text += ' · 내려받는 중…';
    if(st.download_result && !st.download_result.ok)
      text += ` · ${st.download_result.error || '내려받기 실패'}`;
    if(st.downloaded && !st.downloading){
      $('updateInstall').classList.remove('hidden');
      text += ` · 준비됨: ${st.downloaded.version}`;
    }
    msg.textContent = text;
  };
  const refresh = async () => {
    try{
      const st = await (await fetch('/api/update_status', {method:'POST'})).json();
      paint(st);
      return st;
    }catch(e){ msg.textContent = `확인 실패: ${e}`; }
  };
  $('updateCheck').addEventListener('click', refresh);
  $('updateDownload').addEventListener('click', async () => {
    const r = await (await fetch('/api/update_download', {method:'POST'})).json();
    if(!r.ok){ msg.textContent = r.error || '내려받기 실패'; return; }
    if(r.reused){ refresh(); return; }
    msg.textContent = '내려받는 중…';
    clearInterval(UPDATE_POLL);
    UPDATE_POLL = setInterval(async () => {
      const st = await refresh();
      if(st && !st.downloading){ clearInterval(UPDATE_POLL); UPDATE_POLL = null; }
    }, 2000);
  });
  $('updateInstall').addEventListener('click', async () => {
    const r = await (await fetch('/api/update_install', {method:'POST'})).json();
    msg.textContent = r.ok
      ? '설치 프로그램을 열었습니다. 화면의 안내에 따라 진행하세요.'
      : (r.error || '실행 실패');
  });
}

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
