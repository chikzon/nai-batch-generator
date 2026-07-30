/* 출력 증거·자료팩·자료 감사·통합 라이브러리·공개 자료 검색 화면.
   core·generation·settings 뒤, builder·관리 기능 및 bootstrap보다 먼저 읽는다. */

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

/* ── 생성물 탐색기 · 선별 · 비교함 ──────────────────────────────────
   원본 파일은 옮기지 않는다. 선별·즐겨찾기는 경로에 붙는 이름표(선별.json)다. */
const EXP_CHUNK = 120;
let EXP = {dir:'', files:[], dirs:[], total:0, loading:false,
  loadSeq:0, picked:new Set(), fav:new Set(), cmp:new Set(), open:-1,
  folders:{}, ranks:{}, ratings:{}, elo:{}, elo_matches:{}, tags:{},
  memos:{}, review_states:{}, moreObserver:null};
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
  if(EXP.moreObserver){
    EXP.moreObserver.disconnect();
    EXP.moreObserver = null;
  }
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
    EXP.moreObserver = new IntersectionObserver(es => es.forEach(e => {
      if(!e.isIntersecting) return;
      if(EXP.shown < (EXP.vis || []).length) expChunk();
      else if(EXP.files.length < EXP.total) expFetchMore();
    }), {rootMargin: '600px'});
    EXP.moreObserver.observe(more);
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

// 로그인해야 보이는 글은 브라우저가 직접 넘긴다 — 앱은 쿠키를 갖지 않는다.
// 아래 코드는 arca.live 페이지에서 실행되며 본문 HTML과 이미지 바이트만
// 이 앱(localhost)으로 POST 한다. 서버가 연결 번호와 출처를 다시 검사한다.
function relayScriptText(code){
  const origin = location.origin;
  return "javascript:(async()=>{try{"
    + "if(!location.pathname.startsWith('/b/aiart/'))"
    + "{alert('아카라이브 AI그림 채널 글에서 실행하세요.');return;}"
    + "const html=document.documentElement.outerHTML;"
    + "const box=document.querySelector('.article-content')||document.body;"
    + "const urls=[...box.querySelectorAll('img')].map(i=>i.dataset.originalurl||i.src)"
    + ".filter(Boolean).slice(0,40);"
    + "const images=[];for(const u of urls){const r=await fetch(u.startsWith('//')?'https:'+u:u,"
    + "{credentials:'include'});const b=await r.blob();"
    + "if(b.size>64*1024*1024)continue;"
    + "const d=await new Promise(k=>{const f=new FileReader();"
    + "f.onload=()=>k(String(f.result).split(',')[1]);f.readAsDataURL(b);});"
    + "images.push({type:b.type,data:d});}"
    + "const res=await fetch('" + origin + "/api/public_collection_relay',"
    + "{method:'POST',headers:{'Content-Type':'application/json',"
    + "'X-Pairing-Code':'" + code + "'},"
    + "body:JSON.stringify({url:location.href,html,images})});"
    + "const j=await res.json();"
    + "alert(j.ok?('보냈습니다: 이미지 '+(j.metadata_images||0)+'장 · '+(j.classification||''))"
    + ":('실패: '+(j.error||(j.errors||[]).join(', '))));"
    + "}catch(e){alert('실패: '+e);}})()";
}
if($('relayPairingIssue')){
  $('relayPairingIssue').addEventListener('click', async () => {
    $('relayPairingMsg').textContent = '연결 번호를 발급하는 중입니다.';
    try{
      const r = await (await fetch('/api/public_collection_pairing',
        {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})).json();
      if(!r.ok){ $('relayPairingMsg').textContent = r.error || '발급하지 못했습니다.'; return; }
      $('relayPairingCode').textContent = r.code;
      $('relayPairingScript').value = relayScriptText(r.code);
      $('relayPairingScript').classList.remove('hidden');
      $('relayPairingCopy').classList.remove('hidden');
      $('relayPairingMsg').textContent =
        '전달 코드를 복사해 ' + (r.origin || 'arca.live') + ' 글 주소창에 붙여 실행하세요. '
        + '이전에 발급한 번호는 이제 쓸 수 없습니다.';
    }catch(e){ $('relayPairingMsg').textContent = '발급 실패: ' + e; }
  });
  $('relayPairingCopy').addEventListener('click', async () => {
    const text = $('relayPairingScript').value;
    try{
      await navigator.clipboard.writeText(text);
      $('relayPairingMsg').textContent = '전달 코드를 복사했습니다.';
    }catch(e){
      $('relayPairingScript').select();
      $('relayPairingMsg').textContent = '복사 권한이 없어 코드를 선택했습니다. Ctrl+C로 복사하세요.';
    }
  });
}

// 검토·병합 — /api/style_dupes 로 겹친 묶음을 찾고, 둘을 골라
// /api/merge_preview(source=library)로 나란히 보고, /api/merge_apply 로 근거만
// 합친다. 되돌리기 손잡이는 /api/merge_undo 가 받는다 (자료팩과 같은 장부).
let REVIEW_PICKED = [], REVIEW_UNDO = '';
function reviewValue(value){
  if(value === null || value === undefined || value === '') return '<i class="hint">없음</i>';
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 1);
  return `<pre style="margin:3px 0;white-space:pre-wrap;font-size:var(--fs-2xs);">${esc(text)}</pre>`;
}
function reviewSegments(title, items){
  if(!items || !items.length) return '';
  return `<div style="margin-top:4px;"><b style="font-size:var(--fs-2xs);">${esc(title)}</b>`
    + `<div class="bar" style="flex-wrap:wrap;gap:3px;margin-top:2px;">`
    + items.map(item => `<span class="tag">${esc(item)}</span>`).join('') + '</div></div>';
}
function reviewPaintCompare(payload){
  const host = $('reviewCompare');
  host.classList.remove('hidden');
  if(!payload.ok){
    host.innerHTML = `<div class="hint">${esc(payload.error || '비교하지 못했습니다.')}</div>`;
    return;
  }
  const rows = payload.rows || [];
  host.innerHTML = `<div class="bar" style="flex-wrap:wrap;">
      <strong style="font-size:var(--fs-xs);">나란히 비교</strong>
      <span class="hint">대표를 고르면 나머지 항목의 근거만 대표에 합칩니다.</span>
    </div>
    <div class="grid2" style="margin-top:6px;gap:8px;">`
    + rows.map((row, index) => `<div class="row" style="display:block;margin:0;">
        <label class="bar" style="cursor:pointer;">
          <input type="radio" name="reviewRep" value="${escA(row.id)}"
            ${index === 0 ? 'checked' : ''} style="width:auto;flex:none;">
          <b>${esc(row.title || row.id)}</b>
          <span class="tag">${esc(row.source || '출처 미상')}</span>
        </label>
        <div class="hint">${esc(row.id)} · 이미지 ${Number(row.images ? row.images.length : 0)}장
          · 근거 ${Number(row.evidence_records || 0)}건${row.raw_metadata_present ? ' · 원본 메타 있음' : ''}</div>
        <details><summary>프롬프트</summary>${reviewValue(row.prompt)}</details>
        <details><summary>네거티브</summary>${reviewValue(row.negative)}</details>
        <details><summary>생성 설정</summary>${reviewValue(row.settings)}</details>
        <details><summary>평가</summary>${reviewValue(row.rating)}</details>
      </div>`).join('')
    + `</div>
    <div style="margin-top:7px;">`
    + reviewSegments('프롬프트 — 같은 구간', (payload.prompt_diff || {}).common)
    + reviewSegments('프롬프트 — 왼쪽만', (payload.prompt_diff || {}).left_only)
    + reviewSegments('프롬프트 — 오른쪽만', (payload.prompt_diff || {}).right_only)
    + reviewSegments('네거티브 — 왼쪽만', (payload.negative_diff || {}).left_only)
    + reviewSegments('네거티브 — 오른쪽만', (payload.negative_diff || {}).right_only)
    + `</div>
    <div class="bar" style="margin-top:8px;">
      <button type="button" id="reviewMergeApply" class="primary">고른 대표로 근거 합치기</button>
      <span class="hint">원본 항목은 지우지 않습니다.</span>
    </div>`;
  $('reviewMergeApply').addEventListener('click', reviewApplyMerge);
}
async function reviewCompareSelected(){
  if(REVIEW_PICKED.length !== 2){
    $('reviewMergeMsg').textContent = '겹친 자료 중 두 개를 고르세요.';
    return;
  }
  $('reviewMergeMsg').textContent = '나란히 비교를 준비하는 중입니다.';
  try{
    const r = await (await fetch('/api/merge_preview', {method:'POST',
      headers:{'Content-Type':'application/json','X-Source':'library'},
      body:JSON.stringify({ids:REVIEW_PICKED})})).json();
    reviewPaintCompare(r);
    $('reviewMergeMsg').textContent = r.ok ? '' : (r.error || '');
  }catch(e){ $('reviewMergeMsg').textContent = '비교 실패: ' + e; }
}
async function reviewApplyMerge(){
  const picked = document.querySelector('input[name="reviewRep"]:checked');
  if(!picked) return;
  const representative = picked.value;
  const others = REVIEW_PICKED.filter(id => id !== representative);
  $('reviewMergeMsg').textContent = '근거를 합치는 중입니다.';
  try{
    const r = await (await fetch('/api/merge_apply', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source:'library', representative, others})})).json();
    const detail = r.detail || {};
    if(!r.ok){
      $('reviewMergeMsg').textContent = detail.error || '합치지 못했습니다.';
      return;
    }
    REVIEW_UNDO = (r.undo || {}).id || '';
    $('reviewMergeUndo').classList.toggle('hidden', !REVIEW_UNDO);
    $('reviewMergeMsg').textContent = detail.changed
      ? '대표에 근거를 합쳤습니다. 원본 항목은 그대로 남아 있습니다.'
      : '합칠 새 근거가 없었습니다.';
    $('reviewCompare').classList.add('hidden');
    REVIEW_PICKED = [];
    reviewLoadDupes();
  }catch(e){ $('reviewMergeMsg').textContent = '합치기 실패: ' + e; }
}
async function reviewLoadDupes(){
  const host = $('reviewDupeList');
  if(!host) return;
  host.innerHTML = '<div class="hint">겹친 자료를 찾는 중입니다.</div>';
  try{
    const r = await (await fetch('/api/style_dupes')).json();
    const groups = r['목록'] || [];
    $('reviewDupeCount').textContent = r.ok
      ? `묶음 ${Number(r['묶음'] || 0).toLocaleString()}개 · 겹친 항목 ${Number(r['겹친항목'] || 0).toLocaleString()}개`
      : (r.error || '');
    if(!groups.length){
      host.innerHTML = '<div class="hint">겹치는 자료가 없습니다.</div>';
      return;
    }
    host.innerHTML = groups.slice(0, 40).map(group => `<details>
      <summary style="cursor:pointer;">${esc(group['지문'] || '작가 묶음')}
        <span class="tag">${Number(group['건수'] || 0)}건</span></summary>
      <div style="margin-top:4px;display:grid;gap:3px;">`
      + (group['항목'] || []).map(item => `<label class="bar" style="cursor:pointer;">
          <input type="checkbox" data-review-pick="${escA(item.id)}" style="width:auto;flex:none;">
          <span>${esc(item.title || item.id)}</span>
          <span class="hint">${esc(item.source || '')}</span>
        </label>`).join('')
      + `</div></details>`).join('');
    host.querySelectorAll('[data-review-pick]').forEach(box => {
      box.addEventListener('change', () => {
        const id = box.dataset.reviewPick;
        REVIEW_PICKED = box.checked
          ? [...REVIEW_PICKED.filter(value => value !== id), id].slice(-2)
          : REVIEW_PICKED.filter(value => value !== id);
        host.querySelectorAll('[data-review-pick]').forEach(other => {
          other.checked = REVIEW_PICKED.includes(other.dataset.reviewPick);
        });
        if(REVIEW_PICKED.length === 2) reviewCompareSelected();
        else $('reviewCompare').classList.add('hidden');
      });
    });
  }catch(e){ host.innerHTML = `<div class="hint">${esc('찾기 실패: ' + e)}</div>`; }
}
async function reviewArchivePost(payload){
  const r = await (await fetch('/api/archive_download_control', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})).json();
  const parts = [];
  if(r.error) parts.push(r.error);
  if(r.running) parts.push('받는 중: ' + (r.url || ''));
  if(r.received !== undefined){
    parts.push(`${Number(r.received).toLocaleString()}`
      + (r.expected_size ? ` / ${Number(r.expected_size).toLocaleString()}` : '') + '바이트');
  }
  if(r.destination) parts.push('저장 위치: ' + r.destination);
  if(r.result) parts.push(r.result.ok ? '완료' : ('멈춤: ' + (r.result.error || '')));
  $('reviewArchiveStatus').textContent = parts.join(' · ') || (r.ok ? '요청했습니다.' : '');
  return r;
}
function bindLibraryReview(){
  if(!$('libraryReviewCard') || $('libraryReviewCard')._bound) return;
  $('libraryReviewCard')._bound = true;
  $('reviewDupeLoad').addEventListener('click', reviewLoadDupes);
  $('reviewMergeUndo').addEventListener('click', async () => {
    if(!REVIEW_UNDO) return;
    const r = await (await fetch('/api/merge_undo', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source:'library', id:REVIEW_UNDO})})).json();
    $('reviewMergeMsg').textContent = r.ok
      ? '병합을 되돌렸습니다.' : ((r.detail || {}).error || '되돌리지 못했습니다.');
    if(r.ok){ REVIEW_UNDO = ''; $('reviewMergeUndo').classList.add('hidden'); reviewLoadDupes(); }
  });
  $('reviewArchiveStart').addEventListener('click', () => reviewArchivePost({
    action:'start', url:$('reviewArchiveUrl').value.trim(),
    sha256:$('reviewArchiveSha').value.trim()
  }));
  $('reviewArchiveStop').addEventListener('click', () => reviewArchivePost({action:'stop'}));
  reviewArchivePost({action:'status'});
  fetch('/api/public_collection').then(r => r.json()).then(state => {
    $('reviewCollectSummary').textContent =
      `공개 자료 수집: ${esc(String(state.status || 'idle'))}`
      + ` · 새 글 ${Number(state.new_posts || 0)} · 바뀐 글 ${Number(state.changed_posts || 0)}`
      + ` · 메타데이터 이미지 ${Number(state.metadata_images || 0)}장`
      + ' — 시작·중지는 “자료 가져오기”에서 합니다.';
  }).catch(() => {});
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
