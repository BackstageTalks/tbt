'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const app = fs.readFileSync('web/app.js','utf8');
const css = fs.readFileSync('web/blinq-app.css','utf8');
const html = fs.readFileSync('web/index.html','utf8');
const tiers = JSON.parse(fs.readFileSync('web/config/membership-tiers.json','utf8'));
const ui = JSON.parse(fs.readFileSync('web/ui-config.json','utf8'));
const loader = fs.readFileSync('web/assets/blinq-loader.webp');
const reduced = fs.readFileSync('web/assets/blinq-loader-static.webp');
const gif = fs.readFileSync('web/assets/blinq-loader.gif');

// Loading: original dark animated WebP, GIF fallback and reduced-motion WebP.
const patchNum = ui.ui_patch.split('r').pop();
for (const file of ['blinq-loader.webp','blinq-loader-static.webp','blinq-loader.gif']) {
  assert.ok(html.includes('/assets/' + file + '?v=' + ui.asset_revision + '&p=' + patchNum), file);
}
assert.match(html,/prefers-reduced-motion: reduce/);
assert.equal(loader.toString('ascii',0,4),'RIFF');
assert.equal(loader.toString('ascii',8,12),'WEBP');
assert.ok(loader.subarray(0,4096).includes(Buffer.from('ANIM')));
assert.equal(reduced.toString('ascii',0,4),'RIFF');
assert.equal(reduced.toString('ascii',8,12),'WEBP');
assert.ok(['GIF87a','GIF89a'].includes(gif.toString('ascii',0,6)));
assert.ok(fs.existsSync('web/assets/blinq_background.webp'));
assert.match(css,/background:#031314!important/);
assert.ok(css.includes('.anti-share-watermarks{display:none!important}'));
assert.ok(css.includes('#dashboardHero::after'));

// Fallbacks: CSP-safe delegated handler, no inline onerror.
assert.match(app,/handleAssetImageError/);
assert.match(app,/data-player-photo/);
assert.match(app,/data-tournament-logo/);
assert.equal(app.includes('onerror='),false);

// Results layout: tournament and match are distinct columns; location is optional explicit metadata.
assert.match(app,/<th>Turnaj<\/th><th>Zápas<\/th>/);
assert.match(app,/tournamentIdentityHtml\(r\)/);
assert.equal(app.includes("if(!location&&rawName.includes(','))"),false);

// Membership: all tier feature copy comes from JSON; generic Upgrade isn't a locked-content prompt.
for (const id of ['rookie','pro','elite','legend','goat']) assert.ok(Array.isArray(tiers.tiers[id].features) && tiers.tiers[id].features.length);
assert.match(app,/showUpgradePrompt\(plan,section\)/);
assert.match(app,/lockedContext/);

// Daily table: professional clean final action cell, no dangling arrow.
const daily = app.split('function dailyHubRow')[1].split('function dailyHubLockedRow')[0];
assert.equal(daily.includes('aria-hidden="true">→</span>'),false);
assert.match(css,/hub-action-cell \.hub-detail/);

// Homepage statuses must stay yellow STARTED; final outcomes belong only in Results.
const homepage = app.split('function dailyHubRow(', 2)[1]?.split('function dailyHubLockedRow(', 1)[0];
assert.ok(homepage, 'daily hub renderer exists');
assert.ok(homepage.includes("lcopy('STARTED','ZAČATÉ','ZAHÁJENO')"));
assert.ok(homepage.includes('hub-offer-status is-started'));
for (const forbidden of ['match_statuses', 'runtimeStatus', 'hub-row-settled', 'is-win', 'is-loss', 'is-retired', 'is-void']) {
  assert.equal(homepage.includes(forbidden), false, 'homepage must not contain settlement state: ' + forbidden);
}
assert.match(html, /\\/app\\.js\\?[^"\\s]*started-only=2/);
assert.match(html, /\\/blinq-app\\.css\\?[^"\\s]*started-only=2/);

// Admin health cards expose the concrete runtime checks requested for launch.
for (const label of ['PLAYER IMAGES','TOURNAMENT LOGOS','INFO STORAGE','LIVE DATA']) assert.ok(app.includes(label), label);

const patch = html.match(/<meta name="blinq-web-patch" content="736-r(\d+)"/);
assert.ok(patch);
console.log(`PASS: BlinQ 7.3.6-r${patch[1]} UI regression contract`);
