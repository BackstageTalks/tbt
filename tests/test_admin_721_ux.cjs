// Admin 7.2.1 production/shadow rendering: deterministic offline contract.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const src = fs.readFileSync('web/app.js', 'utf8');
const escapeHtml = value => String(value).replaceAll('&','&amp;')
  .replaceAll('<','&lt;').replaceAll('>','&gt;')
  .replaceAll('"','&quot;').replaceAll("'",'&#39;');
const state = {
  adminCalibration: {
    production_version: 'v7.2.1-v201-20261022T134742452543Z',
    shadow_pair_state: 'awaiting_new_pair',
    historical_shadow_pair: {
      production_version: 'v201-20260925T204608601094Z',
      candidate_version: 'v7.2.1-v201-20261022T134742452543Z',
    },
    candidate_version: null, candidate_active: false,
    source_generated_at: '2026-10-26T06:25:00Z',
    updated_at: '2026-10-26T06:25:06Z', stale: false,
    shadow: {
      captured: 0, settled: 0, pending: 0, settled_utc_days: 0,
      target_for_tracking: 1000, remaining_to_target: 1000,
      minimum_for_review: 200, production: {}, candidate: {}, gate: {},
    },
    unseen: {
      available: true, eligible_rows: 10446, remaining_to_target: 0,
      remaining_to_review: 0, target_for_retrain: 1000,
      minimum_for_review: 200,
    },
    last_decision: {status:'operator_calibration_override',same_pair:false},
  },
  adminModelLab: {
    can_start: true, champion_sha256: 'c'.repeat(64),
    candidates: [], active_sha256:'a'.repeat(64),
  },
  adminTraining: {can_start:true,runs:[],candidates:[]},
};
const ctx = {state, escapeHtml};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('  function renderAdminTrainingProfile('),src.indexOf('  function renderAdminTraining()')),ctx);
const renderCalibrationStart = src.indexOf('  function renderAdminCalibration(){');
const renderCalibrationEnd = src.indexOf('  function adminTestFilter(){', renderCalibrationStart);
assert(renderCalibrationStart > 0 && renderCalibrationEnd > renderCalibrationStart);
vm.runInContext(src.slice(renderCalibrationStart,renderCalibrationEnd),ctx);
let html=ctx.renderAdminCalibration();
assert.match(html,/BlinQ 7\.2\.1/);
assert.match(html,/Nemenné ID: v7\.2\.1-v201-20261022T134742452543Z/);
assert.match(html,/Staré shadow metriky/);
assert.match(html,/Pre nový produkčný model zatiaľ neexistuje porovnateľná shadow vzorka/);
assert.match(html,/10\s*446/);
assert.match(html,/Ďalší model · čaká na vyhodnotenie/);
assert.doesNotMatch(html,/Model 7\.1\.1 · čaká na tréning/);
assert.doesNotMatch(html,/Vyhodnotenie rovnakých 0 historických zápasov/);
assert.doesNotMatch(html,/<tbody><tr><th scope="row">Úspešnosť/);

// A truly current challenger shows a real comparison, never the waiting card.
state.adminCalibration.shadow_pair_state='current';
state.adminCalibration.historical_shadow_pair=null;
state.adminCalibration.candidate_version='new-shadow-candidate';
state.adminCalibration.candidate_active=true;
state.adminCalibration.shadow.settled=6;
state.adminCalibration.shadow.captured=8;
state.adminCalibration.shadow.pending=2;
state.adminCalibration.shadow.production={accuracy:.6};
state.adminCalibration.shadow.candidate={accuracy:.7};
html=ctx.renderAdminCalibration();
assert.match(html,/new-shadow-candidate/);
assert.match(html,/70\.0 %/);
assert.doesNotMatch(html,/Staré shadow metriky/);

// Model Factory banner is derived from the Azure calibration snapshot and
// current Model Lab release digest, not a hard-coded 7.2.1 rollout claim.
const renderLabStart = src.indexOf('  function renderAdminModelLab(){');
const renderLabEnd = src.indexOf('  async function loadAdminModelLab(',renderLabStart);
assert(renderLabStart>0 && renderLabEnd>renderLabStart);
vm.runInContext(src.slice(renderLabStart,renderLabEnd),ctx);
state.adminCalibration.shadow_pair_state='awaiting_new_pair';
html=ctx.renderAdminModelLab();
assert.match(html,/PRODUKČNÝ CHAMPION · MODEL LAB/);
assert.match(html,/BlinQ 7\.2\.1/);
assert.match(html,/Produkčný SHA-256: <code>c{64}<\/code>/);
assert.match(html,/Staré shadow výsledky zostávajú iba v histórii/);
state.adminCalibration.stale=true;
html=ctx.renderAdminModelLab();
assert.match(html,/Údaje vyžadujú obnovenie/);
state.adminCalibration.production_version='different-version';
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html.split('class="admin-model-production-side"')[0],/BlinQ 7\.2\.1/);
assert.match(html,/different-version/);
assert.match(src,/productionSelect\.value=productionSelected/);
assert.match(src,/workarea\.scrollTop=workareaScroll/);

console.log('Admin 7.2.1 production identity, stale shadow, safe empty state and polling selection: PASS');
