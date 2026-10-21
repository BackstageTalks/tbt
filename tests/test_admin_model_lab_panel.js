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
assert.match(html,/Model Lab/);
assert.match(html,/data-model-lab-operation="import_drive" disabled/);
assert.match(html,/data-model-lab-operation="activate_shadow" disabled/);
state.adminModelLab={
  can_start:true,reason:'Pripravené',
  active_sha256:'a'.repeat(64),
  candidates:[{tag:'blinq-candidate-frozen-123-1',sha256:'b'.repeat(64)},
              {tag:'bad<script>',sha256:'a'.repeat(64)}],
  operation:null,last_operation:null,
};
html=ctx.renderAdminModelLab();
assert.match(html,/data-model-lab-operation="import_drive"/);
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
assert.match(src,/if\(action==='model-lab-start'\)/);
assert.match(src,/if\(action==='model-lab-acknowledge'\)/);
console.log('Model Lab UI: disabled, ready, unsafe-input, ongoing and confirm-path states passed');
