const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const source=fs.readFileSync('web/app.js','utf8');
const render=source.slice(source.indexOf('  function renderAdminTraining(){'),source.indexOf('  async function loadAdminTraining('));
const ctx={state:{},escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function renderAdminTrainingProfile('),source.indexOf('  function renderAdminTraining()')),ctx);vm.runInContext(render,ctx);
assert.match(ctx.renderAdminTraining(),/data-admin-action="training-start" disabled/);
ctx.state.adminTraining={can_start:true,runs:[],candidates:[]};
assert.doesNotMatch(ctx.renderAdminTraining(),/data-admin-action="training-start" disabled/);
ctx.state.adminTrainingBusy=true;
assert.match(ctx.renderAdminTraining(),/data-admin-action="training-start" disabled/);
ctx.state.adminTrainingBusy=false;
ctx.state.adminTraining.candidates=[{tag:'<script>',url:'javascript:alert(1)',label:'Nedokončený tréning'}];
const html=ctx.renderAdminTraining();
assert(!html.includes('javascript:'));assert(!html.includes('<script>'));assert(html.includes('&lt;script>'));
console.log('Admin training panel: unavailable, ready, busy and unsafe-link states passed');

assert.match(ctx.renderAdminTrainingProfile(), /value="accuracy-7.2.2" selected/);
ctx.state.adminTrainingProfile="top-7.2.1";
assert.match(ctx.renderAdminTrainingProfile(), /value="top-7.2.1" selected/);

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
