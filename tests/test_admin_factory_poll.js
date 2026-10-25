const fs=require('fs'), vm=require('vm'), assert=require('assert');
const src=fs.readFileSync('web/app.js','utf8');
const start=src.indexOf('  async function pollAdminModelFactory(){');
const end=src.indexOf('  async function loadAdminDiagnostics(',start);
const state={route:'admin',adminTab:'calibration'}, calls=[];
let renderCount=0;
const ctx={state,feedGeneration:1,navigator:{onLine:true},isAdminAccount:()=>true,
  document:{hidden:false,activeElement:null,querySelector:()=>null,getElementById:()=>null},
  rerenderAdmin:()=>{renderCount++;},
  BlinqAuth:{adminModelTraining:async()=>{calls.push('training');return {can_start:false};},
    adminModelLab:async()=>{calls.push('lab');return {can_start:true};},
    adminModelCalibration:async()=>{calls.push('calibration');return {candidate_active:true};}}};
vm.createContext(ctx);vm.runInContext(src.slice(start,end),ctx);
(async()=>{
  ctx.document.hidden=true;await ctx.pollAdminModelFactory();assert.equal(calls.length,0);
  ctx.document.hidden=false;state.route='predictions';await ctx.pollAdminModelFactory();assert.equal(calls.length,0);
  state.route='admin';await ctx.pollAdminModelFactory();assert.equal(calls.length,3);assert.equal(renderCount,1);
  assert.equal(state.adminTraining.can_start,false);assert.equal(state.adminFactoryPolling,false);
  ctx.BlinqAuth.adminModelTraining=async()=>{throw Error('offline');};
  await ctx.pollAdminModelFactory();assert.equal(state.adminTraining,null);assert.match(state.adminTrainingMessage,/nepodarilo/);
  let finish;
  ctx.BlinqAuth.adminModelTraining=()=>new Promise(resolve=>{finish=resolve;});
  const pending=ctx.pollAdminModelFactory();
  await ctx.pollAdminModelFactory(); // no overlapping read batch
  state.adminFactoryRevision=1;state.adminTraining={newRequest:true};
  finish({oldSnapshot:true});await pending;
  assert.equal(state.adminTraining.newRequest,true,'late polling response overwrote a newer operator request');
  console.log('Model Factory polling: visible admin only, fail closed, no overlapping requests or stale overwrite: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
