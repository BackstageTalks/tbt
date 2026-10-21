const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const src=fs.readFileSync('web/app.js','utf8');
const begin=src.indexOf('  function renderAdminModelLab(){');
const end=src.indexOf('  async function loadAdminModelLab(',begin);
assert(begin>0&&end>begin,'Model Lab UI must exist');
const render=src.slice(begin,end);
const state={};
const escapeHtml=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')
  .replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const ctx={state,escapeHtml};
vm.createContext(ctx);
vm.runInContext(render,ctx);
let html=ctx.renderAdminModelLab();
assert.match(html,/BlinQ Model Factory/);
assert.match(html,/data-admin-action="training-start" disabled/);
assert.match(html,/data-model-lab-operation="import_drive" disabled/);
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
state.adminTraining={can_start:true,runs:[],candidates:[{tag:'blinq-candidate-frozen-123-1'}]};
state.adminModelLab={
  can_start:true,reason:'Pripravené',
  active_sha256:'a'.repeat(64),
  candidates:[{tag:'blinq-candidate-frozen-123-1',sha256:'b'.repeat(64)},
              {tag:'bad<script>',sha256:'a'.repeat(64)}],
  operation:null,last_operation:null,
};
html=ctx.renderAdminModelLab();
assert.match(html,/data-model-lab-operation="import_drive"/);
assert.match(html,/data-admin-action="training-start"/);
assert.doesNotMatch(html,/data-admin-action="training-start" disabled/);
assert.match(html,/data-model-lab-operation="activate_shadow"/);
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
assert.match(html,/Aktivácia zostáva zablokovaná/);
state.adminCalibration={
  production_version:'v201',
  offline_candidate:{status:'evaluated_not_deployed',
    evaluation_type:'untouched_offline_holdout',production_version:'v201',
    candidate_release_tag:'blinq-candidate-frozen-123-1',candidate_sha256:'b'.repeat(64),
    n:312,champion:{accuracy:.64,log_loss:.64,brier_score:.22,ece_10:.07},
    candidate:{accuracy:.65,log_loss:.63,brier_score:.21,ece_10:.06}},
};
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-model-lab-operation="activate_shadow" disabled/);
assert.match(html,/Nezávislý offline holdout overený/);
state.adminTraining.runs=[{id:123,status:'in_progress',html_url:'https://github.com/BackstageTalks/tbt/actions/runs/123'}];
state.adminTraining.active_steps=['Fit separate candidate only if immutable backup gate passed'];
html=ctx.renderAdminModelLab();
assert.match(html,/Aktuálna fáza/);
assert.match(html,/Fit separate candidate only if immutable backup gate passed/);
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
state.adminTraining.runs=[];
state.adminTraining.active_steps=[];
state.adminCalibration.offline_candidate.candidate_sha256='c'.repeat(64);
html=ctx.renderAdminModelLab();
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
state.adminCalibration.offline_candidate.candidate_sha256='b'.repeat(64);
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-model-lab-operation="activate_shadow" disabled/);
assert.match(html,/Pokročilé operácie a história/);
assert.match(src,/calibration:\(\)=>renderAdminModelLab\(\)\+renderAdminCalibration\(\)/);
assert.doesNotMatch(html,/data-model-lab-operation="import_drive" disabled/);
assert.match(html,/blinq-candidate-frozen-123-1/);
assert(!html.includes('<script>'));
state.adminModelLab.operation={
  id:'a'.repeat(24),action:'activate_shadow',state:'RUNNING',
  run:{id:123,html_url:'javascript:alert(1)',status:'in_progress'},
};
html=ctx.renderAdminModelLab();
assert(!html.includes('javascript:alert'));
state.adminModelLab.operation=null;
state.adminModelLab.can_start=false;
html=ctx.renderAdminModelLab();
assert.match(html,/data-model-lab-operation="import_drive" disabled/);
assert.match(html,/data-admin-action="training-start" disabled/);
assert.match(src,/if\(action==='model-lab-start'\)/);
assert.match(src,/if\(action==='model-lab-acknowledge'\)/);

state.adminModelLab.operation={
  id:'e'.repeat(24),action:'audit_shadow',state:'COMPLETED_PENDING_VERIFICATION',run:null
};
state.adminModelLab.last_operation={
  id:'e'.repeat(24),action:'audit_shadow',state:'FAILED_NEEDS_REVIEW',
  run:{id:78,status:'completed',conclusion:'failure'}
};
html=ctx.renderAdminModelLab();
assert.match(html,/data-admin-action="model-lab-acknowledge"/);
assert.doesNotMatch(html,/Zápis mohol byť čiastočný/);
state.adminModelLab.operation.action='activate_shadow';
state.adminModelLab.last_operation.action='activate_shadow';
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-admin-action="model-lab-acknowledge"/);
assert.match(html,/Zápis sa mohol vykonať čiastočne/);
assert.match(src,/state\.adminModelLab=await BlinqAuth\.adminModelLab\(\);/);
state.adminModelLab.can_start=true;
state.adminModelLab.operation=null;
state.adminTraining.can_start=false;
html=ctx.renderAdminModelLab();
assert.match(html,/data-admin-action="training-start" disabled/);
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
assert.match(src,/state\.adminTraining=await BlinqAuth\.adminModelTraining\(\);/);
assert.match(src,/Vytvoriť nový nemenný model 7\.2\.1/);
console.log('Model Factory UI: two-step build/test and shadow, safe concurrency, advanced diagnostics passed');
