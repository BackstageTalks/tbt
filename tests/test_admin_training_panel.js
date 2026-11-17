const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const source=fs.readFileSync('web/app.js','utf8');
// The active Model Lab renderer owns the training button and safe-link guard.
// The retired renderAdminTraining() helper is not an entrypoint.
const modelStart=source.indexOf('  function renderAdminModelLab(){');
const profileStart=source.indexOf('  function renderAdminTrainingProfile(');
const loadStart=source.indexOf('  async function loadAdminTraining(');
const calibrationStart=source.indexOf('  function renderAdminCalibration(){');
assert(modelStart>=0 && modelStart<profileStart && profileStart<loadStart && loadStart<calibrationStart);
const active=source.slice(modelStart,profileStart);
assert.match(active,/const busy=!!state\.adminModelLabBusy\|\|!!state\.adminTrainingBusy/);
assert.match(active,/data-admin-action="training-start"/);
assert.match(active,/\(canTrain\?'':'disabled'\)/);
assert.match(active,/\^https:\\\/\\\/github/);
assert.match(active,/escapeHtml\(url\)/);
assert.match(active,/escapeHtml\(label\)/);
const ctx={state:{},escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')};
vm.createContext(ctx);
vm.runInContext(source.slice(profileStart,loadStart),ctx);
console.log('Active Model Lab training controls and safe-link guard: PASS');

assert.match(ctx.renderAdminTrainingProfile(), /value="top-7.2.1" selected/);
assert.match(ctx.renderAdminTrainingProfile(), /value="accuracy-7.2.2"[^>]*disabled/);
ctx.state.adminTrainingProfile="top-7.2.1";
assert.match(ctx.renderAdminTrainingProfile(), /value="top-7.2.1" selected/);
ctx.state.adminModelLab={champion_sha256:"a".repeat(64),last_promotion:{
  state:"WORKFLOW_VERIFIED",approval:{source_sha256:"a".repeat(64)},run:{conclusion:"success"}}};
assert.doesNotMatch(ctx.renderAdminTrainingProfile(), /value="accuracy-7.2.2"[^>]*disabled/);

// The profile captured before the async confirmation must win over a rerender.
const loader=source.slice(source.indexOf('  async function loadAdminTraining('),source.indexOf('  function renderAdminCalibration(){'));
const calls=[];
Object.assign(ctx,{feedGeneration:1,rerenderAdmin:()=>{},BlinqAuth:{adminModelTraining:async payload=>{calls.push(payload);return {state:'QUEUED'};}}});
vm.runInContext(loader,ctx);
ctx.loadAdminTraining(true,'accuracy-7.2.2').then(()=>{
  assert.equal(calls.length,2);
  assert.equal(calls[0].profile,'accuracy-7.2.2');
  assert.equal(calls[0].auto_shadow,true);
  assert.equal(calls[1],undefined);
  assert.equal(ctx.state.adminTrainingBusy,false);
  console.log('Captured 7.2.2 profile survives confirmation and request readback');
}).catch(error=>{console.error(error);process.exitCode=1;});
