'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const app = fs.readFileSync('web/app.js','utf8');
const css = fs.readFileSync('web/blinq-app.css','utf8');
const html = fs.readFileSync('web/index.html','utf8');
const tiers = JSON.parse(fs.readFileSync('web/config/membership-tiers.json','utf8'));
const loader = fs.readFileSync('web/assets/blinq_loading_r29.svg','utf8');

// Loading: animated rally remains present and both loader + normal app have watermark contracts.
assert.match(html,/blinq_loading_r29\.svg\?v=7360\&p=34/);
assert.match(loader,/<animateTransform/);
assert.equal(loader.includes('data:image/webp;base64,'),false);
assert.ok(fs.existsSync('web/assets/blinq_background.webp'));
assert.match(css,/blinq_background\.webp/);
assert.match(css,/boot-splash\.boot-splash-tennis::after/);
assert.match(css,/app-shell:not\(\[hidden\]\)::after/);

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

// Admin health cards expose the concrete runtime checks requested for launch.
for (const label of ['PLAYER IMAGES','TOURNAMENT LOGOS','INFO STORAGE','LIVE DATA']) assert.ok(app.includes(label), label);

const patch = html.match(/<meta name="blinq-web-patch" content="736-r(\d+)"/);
assert.ok(patch);
console.log(`PASS: BlinQ 7.3.6-r${patch[1]} UI regression contract`);
