/* 모든 화면이 공유하는 상태와 작은 DOM helper.
   bootstrap 설정 뒤, 기능별 스크립트보다 먼저 classic script로 읽는다. */
let STATE = null, SAVED_STATE = null, SETTINGS = [], STYLES = [], SPEC = {}, BUILDER = {}, SCENE_PRESETS = [], HIST = [];
let LAST_STUDIO_LAYOUT = null;
let BLUEPRINT_INHERITANCE = {};
let FRAGS = {};
const RES_PRESETS = window.NAI_STUDIO_BOOTSTRAP.resolutions;

function genId(){ return Math.random().toString(36).slice(2,10); }
function esc(s){ return String(s||'').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function escA(s){ return esc(s).replace(/"/g,'&quot;'); }
function $(id){ return document.getElementById(id); }
