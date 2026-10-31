const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const src=fs.readFileSync('web/app.js','utf8');
const begin=src.indexOf('  function renderAdminModelLab(){');
const end=src.indexOf('  async function loadAdminModelLab(',begin);
assert(begin>0&&end>begin,'Model Factory UI must exist');
const state={};
const escapeHtml=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')
  .replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const ctx={state,escapeHtml,fmtStamp:s=>String(s)};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('  function renderAdminTrainingProfile('),src.indexOf('  function renderAdminTraining()')),ctx);
vm.runInContext(src.slice(begin,end),ctx);

let html=ctx.renderAdminModelLab();
assert.match(html,/MODEL FACTORY · 3 FÁZY/);
for(const phrase of ['1 · Pripraviť dáta','2 · Natrénovať a aktivovať kandidáta','3 · Nasadiť do produkcie']){
  assert(html.includes(phrase));
}
assert.match(html,/data-model-lab-operation="prepare_inputs" disabled/);
assert.match(html,/data-model-lab-operation="refresh_champion_inputs" disabled/);
assert.match(html,/data-admin-action="training-start" disabled/);
assert.match(html,/data-admin-action="model-factory-promote" disabled/);
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
state.adminTraining={can_start:true,runs:[],candidates:[{tag:'blinq-candidate-frozen-123-1'}]};
state.adminModelLab={can_start:true,reason:'Pripravené',active_sha256:'a'.repeat(64),
  candidates:[{tag:'blinq-candidate-frozen-123-1',sha256:'b'.repeat(64)},
              {tag:'bad<script>',sha256:'a'.repeat(64)}],
  operation:null,last_operation:null};
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-model-lab-operation="prepare_inputs" disabled/);
assert.match(html,/data-model-lab-operation="refresh_champion_inputs" disabled/);
state.adminModelLab.feed_sha256='f'.repeat(64);
state.adminModelLab.feed_updated_at=new Date().toISOString();
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-model-lab-operation="refresh_champion_inputs" disabled/);
assert.match(html,/bez tréningu/i);
assert.match(html,/automaticky prepočítava/i);
assert.match(html,/data-admin-action="training-start" disabled/);
state.adminModelLab.last_preflight={
  state:'WORKFLOW_VERIFIED', verified_at:new Date().toISOString(),
  run:{id:123,html_url:'https://github.com/BackstageTalks/tbt/actions/runs/123',
       conclusion:'success',artifact_verified:true,
       preflight_report:{eligible_rows:600000,tours:{
         atp:{eligible_matches:350000,coverage_counts:{rank_pair:290000,serve:120000,return:115000,break_points:64000}},
         wta:{eligible_matches:250000,coverage_counts:{rank_pair:205000,serve:105000,return:103000,break_points:58000}}
       }}},
};
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-admin-action="training-start" disabled/);
assert.match(html,/Audit dát overený/);
assert.match(html,/ATP: 350/);
assert.match(html,/WTA: 250/);
assert.match(html,/Finálne zmrazenie a zálohovanie vstupov/);
state.adminModelLab.last_preflight.run.artifact_verified=false;
html=ctx.renderAdminModelLab();
assert.match(html,/data-admin-action="training-start" disabled/);
state.adminModelLab.last_preflight.run.artifact_verified=true;
state.adminTraining.runs=[{id:123,status:'in_progress',html_url:'https://github.com/BackstageTalks/tbt/actions/runs/123'}];
state.adminTraining.active_steps=['Fit separate candidate only if immutable backup gate passed'];
html=ctx.renderAdminModelLab();
assert.match(html,/Aktuálna fáza/);
assert.match(html,/data-admin-action="training-start" disabled/);
state.adminTraining.runs=[];
state.adminTraining.active_steps=[];
state.adminCalibration={production_version:'v201',
  offline_candidate:{status:'evaluated_not_deployed',
  evaluation_type:'untouched_offline_holdout',production_version:'v201',
  candidate_release_tag:'blinq-candidate-frozen-123-1',candidate_sha256:'b'.repeat(64),
  n:312,champion:{accuracy:.64,log_loss:.64,brier_score:.22,ece_10:.07},
  candidate:{accuracy:.66,log_loss:.63,brier_score:.21,ece_10:.06}}};
html=ctx.renderAdminModelLab();
assert.doesNotMatch(html,/data-model-lab-operation="activate_shadow" disabled/);
assert.match(html,/Nezávislý offline holdout overený/);
assert.doesNotMatch(html,/data-admin-action="model-factory-promote" disabled/);
state.adminModelLab.operation={
  id:'a'.repeat(24),action:'activate_shadow',state:'RUNNING',
  run:{id:123,html_url:'javascript:alert(1)',status:'in_progress'},
};
html=ctx.renderAdminModelLab();
assert(!html.includes('javascript:alert'));
state.adminModelLab.operation=null;
state.adminModelLab.last_preflight.run.html_url='javascript:alert(1)';
html=ctx.renderAdminModelLab();
assert(!html.includes('javascript:alert'));
state.adminModelLab.can_start=false;
html=ctx.renderAdminModelLab();
assert.match(html,/data-admin-action="training-start" disabled/);
assert.match(html,/data-model-lab-operation="prepare_inputs" disabled/);
assert.match(src,/if\(action==='model-lab-start'\)/);
assert.match(src,/if\(action==='model-lab-acknowledge'\)/);
assert.match(src,/state\.adminTraining=await BlinqAuth\.adminModelTraining\(\);/);
assert.match(src,/loadAdminTraining\(true,profile\)/);
assert.match(html,/id="admin-training-profile"/);
console.log('Model Factory: guarded 3 phases, preflight artifact, training, shadow, production lock, XSS passed');

// Preparation/import/read-only audits must not require an offline candidate.
state.adminModelLab.can_start=true;
state.adminCalibration={};
html=ctx.renderAdminModelLab();
for(const action of ['prepare_inputs','import_drive','audit_shadow','refresh_tests']){
  assert.doesNotMatch(html,new RegExp('data-model-lab-operation="'+action+'" disabled'));
}
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
state.adminModelLab.operation={id:'f'.repeat(24),action:'prepare_inputs',state:'FAILED_NEEDS_REVIEW'};
state.adminModelLab.last_operation={id:'f'.repeat(24),action:'prepare_inputs',state:'VERIFICATION_FAILED'};
html=ctx.renderAdminModelLab();
assert.match(html,/data-admin-action="model-lab-acknowledge"/);
assert.doesNotMatch(html,/Zápis sa mohol vykonať čiastočne/);
state.adminModelLab.operation=null;
state.adminModelLab.last_operation=null;
state.adminTraining.candidates=[{tag:'incomplete',complete:false},{tag:'complete-model',complete:true}];
state.adminTraining.runs=[{id:123,status:'completed',conclusion:'failure'}];
state.adminTraining.failed_steps=['Freeze ALL current source inputs and independently restore champion'];
state.adminTraining.steps=[{name:state.adminTraining.failed_steps[0],status:'completed',conclusion:'failure'}];
state.adminTraining.shadow_outcome={state:'SHADOW_BLOCKED',reasons:['top_market_validation_required','<script>']};
html=ctx.renderAdminModelLab();
assert.match(html,/Zopakovať tréning a kontroly/);
assert.match(html,/Zmrazenie dát a overenie obnovy zálohy/);
assert.match(html,/Model uložený, shadow neaktivovaný/);
assert.match(html,/Chýba nezávislé overenie na predzápasových kurzoch/);
assert.match(html,/Posledný uložený model:<\/strong> complete-model/);
assert(!html.includes('<script>'));
console.log('Model Factory recovery, independent actions, progress and shadow outcome: passed');
state.adminModelLab.operation={id:'e'.repeat(24),action:'prepare_inputs',state:'EXPIRED_UNCLAIMED'};
state.adminModelLab.last_operation=null;
html=ctx.renderAdminModelLab();
assert.match(html,/Zrušiť neodoslanú požiadavku/);
assert.match(html,/data-admin-action="model-lab-acknowledge"/);
