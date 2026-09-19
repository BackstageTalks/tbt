'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');

const app = fs.readFileSync('web/app.js','utf8');
const auth = fs.readFileSync('web/auth.js','utf8');
const responsive = fs.readFileSync('web/responsive.js','utf8');
const html = fs.readFileSync('web/index.html','utf8');
const ui = JSON.parse(fs.readFileSync('web/ui-config.json','utf8'));
const release = JSON.parse(fs.readFileSync('web/release.json','utf8'));

function declaredNames(source){
  const out = new Set();
  for (const m of source.matchAll(/\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g)) out.add(m[1]);
  for (const m of source.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b/g)) out.add(m[1]);
  return out;
}
function bareObjectNames(body){
  return body.split(',').map(v=>v.trim()).filter(Boolean).map(v=>v.split(':',1)[0].trim()).filter(v=>/^[A-Za-z_$][\w$]*$/.test(v));
}

const authObject = auth.match(/window\.BlinqAuth\s*=\s*\{([\s\S]*?)\n\s*\};/);
assert.ok(authObject, 'BlinqAuth export object missing');
const authExports = new Set(bareObjectNames(authObject[1].replace(/\n/g,' ')));
const authDeclared = declaredNames(auth);
for (const name of authExports) assert.ok(authDeclared.has(name), `BlinqAuth exports undefined identifier ${name}`);
for (const m of app.matchAll(/\bBlinqAuth\.([A-Za-z_$][\w$]*)/g)) assert.ok(authExports.has(m[1]), `app.js calls missing BlinqAuth.${m[1]}`);
for (const name of ['adminSaveUiConfig','adminUploadMedia','feed','insights','liveRadar','adminDiagnostics','adminUsers']) assert.ok(authExports.has(name), `critical auth API missing: ${name}`);

const uiObject = responsive.match(/window\.BlinqUI\s*=\s*Object\.freeze\(\{([^}]*)\}\)/);
assert.ok(uiObject, 'BlinqUI export object missing');
const uiExports = new Set(bareObjectNames(uiObject[1]));
for (const m of app.matchAll(/\bBlinqUI\.([A-Za-z_$][\w$]*)/g)) assert.ok(uiExports.has(m[1]), `app.js calls missing BlinqUI.${m[1]}`);

const patch = html.match(/<meta name="blinq-web-patch" content="736-r(\d+)"/);
assert.ok(patch, 'frontend patch marker missing');
const p = patch[1];
assert.equal(release.patch, `736-r${p}`);
assert.equal(ui.ui_patch, `736-r${p}`);
assert.ok(html.includes(`/auth.js?v=${ui.asset_revision}&p=${p}`));
assert.ok(html.includes(`/responsive.js?v=${ui.asset_revision}&p=${p}`));
assert.ok(html.includes(`/app.js?v=${ui.asset_revision}&p=${p}`));
assert.ok(html.includes(`/blinq-app.css?v=${ui.asset_revision}&p=${p}`));

for (const retired of ['SUPPORT STORAGE','VIP_RAIL','VIP_TELEGRAM','FOOTBALL_ACCESS','BTTS_BONUS_PANEL','renderAdminCampaigns','adminPayments','adminAddPayment','adminBannerAnalytics']) {
  assert.equal(app.includes(retired), false, `retired runtime token returned: ${retired}`);
}

console.log(`frontend runtime contract: PASS (736-r${p})`);
