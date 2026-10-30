// Reproduce the 7.2.2 Admin snapshot without a backend or provider requests.
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
    candidate_version: 'v7.2.2-v201-20261027T185121317295Z',
    candidate_active: true,
    shadow_pair_state: 'current',
    updated_at: new Date().toISOString(),
    shadow_generated_at: new Date().toISOString(),
    stale: false,
    shadow: {
      captured:190, settled:0, pending:190, settled_utc_days:0,
      target_for_tracking:1000, remaining_to_target:1000,
      minimum_for_review:200, remaining_to_review:200,
      production:{},candidate:{},gate:{},
    },
    unseen:{
      available:true, eligible_rows:1300, eligible_days:3,
      target_for_retrain:1000, remaining_to_target:0,
      minimum_for_review:200, remaining_to_review:0,
      readiness_generated_at:new Date().toISOString(),
    },
    last_decision:{status:'rejected',same_pair:false,candidate_version:'old-version'},
    offline_candidate:null,
  },
};
const ctx = {state,escapeHtml};
vm.createContext(ctx);
const start = src.indexOf('  function renderAdminCalibration(){');
const end = src.indexOf('  function adminTestFilter(){',start);
assert(start>0 && end>start, 'Admin calibration renderer not found');
vm.runInContext(src.slice(start,end),ctx);

let html=ctx.renderAdminCalibration();
assert.match(html,/BlinQ 7\.2\.1/);
assert.match(html,/BlinQ 7\.2\.2/);
assert.match(html,/v7\.2\.2-v201-20261027T185121317295Z/);
assert.match(html,/Shadow aktívny · čaká na výsledky zápasov/);
assert.match(html,/Shadow – zachytené predzápasové páry<\/strong><span>190 \/ 1\s*000/);
assert.match(html,/Shadow – minimum vyhodnotených zápasov<\/strong><span>0 \/ 200/);
assert.match(html,/Nové nezávislé zápasy – ďalší tréning<\/strong><span>1\s*300 \/ 1\s*000/);
assert.match(html,/190 predzápasových snapshotov čaká na výsledok/);
assert.match(html,/BlinQ 7\.2\.2 · offline kvalita zatiaľ neoverená/);
assert.match(html,/čaká na výsledky zápasov/);
assert.match(html,/Čaká na vzorku/);
assert.doesNotMatch(html,/Nové zápasy – minimum na prehodnotenie/);
assert.doesNotMatch(html,/Shadow kandidát – cieľ pre sledovanie/);
assert.doesNotMatch(html,/Nový kandidát sa zobrazí až po nezávislom tréningu/);
assert.match(html,/Tlačidlo Obnoviť načíta uložený stav, nie nové výsledky z GitHubu/);

// A mature exact pair distinguishes failed quality gates from unavailable metrics.
state.adminCalibration.shadow = {
  ...state.adminCalibration.shadow,
  captured:330, settled:215, pending:115, settled_utc_days:3,
  remaining_to_review:0,
  production:{accuracy:.7,log_loss:.56,brier_score:.19,ece_10:.03},
  candidate:{accuracy:.69,log_loss:.59,brier_score:.20,ece_10:.04},
  gate:{
    minimum_matches_met:true, minimum_days_met:true,
    accuracy_not_worse:false, log_loss_better:false,
    brier_better:false, ece_not_worse:false,
  },
};
html=ctx.renderAdminCalibration();
assert.match(html,/Shadow – zachytené predzápasové páry<\/strong><span>330 \/ 1\s*000/);
assert.match(html,/Shadow – minimum vyhodnotených zápasov<\/strong><span>215 \/ 200/);
assert.match(html,/title="Nesplnené"/);
assert.doesNotMatch(html,/čaká na výsledky zápasov/);

// Old GitHub evidence is visibly historical, even if Azure was just read again.
state.adminCalibration.shadow_generated_at='2026-10-29T06:06:00Z';
html=ctx.renderAdminCalibration();
assert.match(html,/Posledný známy stav: shadow testovanie/);
assert.match(html,/Zdrojový shadow report je starší než 8 hodín/);
assert.match(html,/admin-calibration-status is-stale/);

// No candidate must not inherit the current 7.2.2 identity.
state.adminCalibration.candidate_version=null;
state.adminCalibration.candidate_active=false;
state.adminCalibration.shadow_pair_state='awaiting_new_pair';
state.adminCalibration.shadow={...state.adminCalibration.shadow,captured:0,settled:0,pending:0,gate:{},production:{},candidate:{}};
html=ctx.renderAdminCalibration();
assert.match(html,/Produkčný model aktivovaný · čaká sa na nový shadow pár/);
assert.match(html,/Ďalší model · čaká na vyhodnotenie/);
assert.doesNotMatch(html,/BlinQ 7\.2\.2 · offline kvalita zatiaľ neoverená/);

console.log('Admin 7.2.2 captured/settled/training separation, gate and freshness: PASS');
