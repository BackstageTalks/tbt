'use strict';
// Regression: Admin-published durations, exact UTC term and redacted ELITE slots.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../web/app.js'), 'utf8');

function between(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, 'Expected source function boundaries');
  return source.slice(a, b);
}
const termCode = between('  function planIsUnlimited(', '  function adminLevelChips(');
const adminTermCode = between('  function setAdminPlanDefaults(', '  function decorateAdminMediaUploads(');
function memberFns(state) {
  return new Function('state', termCode + 'return {planIsUnlimited,planDurationDays,planDefaultExpiry,planTermLabel};')(state);
}
const origin = new Date('2026-11-21T12:00:00Z');
const plans = {
  rookie: {duration_days:null, unlimited:true},
  pro: {duration_days:30, unlimited:false},
  elite: {duration_days:30, unlimited:false},
  legend: {duration_days:180, unlimited:false},
  goat: {duration_days:180, unlimited:true, lifetime:true}
};
let state = {ui:{plans}};
let fns = memberFns(state);
for (const [plan, days] of [['pro',30],['elite',30],['legend',180],['goat',180]]) {
  assert.equal(fns.planDurationDays(plan), days, plan);
  assert.equal(fns.planDefaultExpiry(plan, origin).getTime()-origin.getTime(), days*86400000, plan);
}
assert.equal(fns.planDefaultExpiry('rookie', origin), null);
assert.equal(fns.planTermLabel('goat'), '180 dní');
plans.goat.duration_days = null;
assert.equal(fns.planDefaultExpiry('goat', origin), null, 'Missing runtime duration must fail closed');
plans.goat.duration_days = 180;
plans.legend.duration_days = 30;
assert.equal(fns.planDefaultExpiry('legend', origin), null, 'LEGEND cannot grant 30 days');
plans.legend.duration_days = 180;

const pad = value => String(value).padStart(2,'0');
function localInput(value) {
  const d = new Date(value);
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+
    'T'+pad(d.getHours())+':'+pad(d.getMinutes());
}
const expiry = {value:localInput(new Date(Date.now()+40*86400000)), disabled:false};
const inputNodes = {adminUserPlan:{value:'goat'},adminUserExpires:expiry};
const messages = [];
const adminFns = new Function('state','$','userDateValue','showStatus',
  termCode + adminTermCode +
  'return {adminDefaultPlanDays,adminAddDaysToExpiry,setAdminPlanDefaults};'
)(state, key=>inputNodes[key], localInput, message=>messages.push(message));
assert.equal(adminFns.adminDefaultPlanDays(),180);
const before = new Date(expiry.value).getTime();
adminFns.adminAddDaysToExpiry(adminFns.adminDefaultPlanDays());
const after = new Date(expiry.value).getTime();
assert.ok(Math.abs((after-before)-180*86400000)<60000, 'Extend exactly 180 days from existing expiry');
plans.goat.duration_days = null;
const unchanged = expiry.value;
adminFns.adminAddDaysToExpiry(adminFns.adminDefaultPlanDays());
assert.equal(expiry.value, unchanged, 'Invalid duration does not grant access');
assert.ok(messages.length > 0);
plans.goat.duration_days = 180;

const slotStart = '        slotStates.slice(0,limit).forEach((slotState,slotIndex)=>{';
const start = source.indexOf(slotStart), end = source.indexOf('\n        });', start);
assert.ok(start >= 0 && end > start);
const actualSlotLoop = source.slice(start, end+12);
const render = new Function('slotStates','limit','ent','plan','bySlot',
  'const out=[];let dataIndex=0;const unmapped=[];'+
  'const dailyHubLockedRow=(_tab,i)=>"LOCK:"+(i+1);'+
  'const firstDailyHubUnlockPlan=()=> "legend";'+
  'const dailyHubRow=(row,_tab,_active,i)=>"ROW:"+(i+1)+":"+row.name;'+
  'const tab="daily";' + actualSlotLoop + 'return out;'
);
const slots = ['active','hidden','blurred','active','hidden'];
const rows = new Map([[0,{name:'A'}],[3,{name:'B'}]]);
const rules = {row_overrides:{'5':'hidden'}};
assert.deepEqual(render(slots,5,rules,'elite',rows), ['ROW:1:A','LOCK:2','LOCK:3','ROW:4:B'],
  'ELITE retains original numbered slots and explicit Admin HIDE');
assert.deepEqual(render(slots,5,rules,'legend',rows), ['ROW:1:A','LOCK:3','ROW:4:B'],
  'Non-ELITE does not override hidden rows');
console.log('PASS: 4 paid durations, ROOKIE, invalid, extend, ordered ELITE locks and HIDE.');
