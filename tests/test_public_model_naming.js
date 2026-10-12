'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/app.js', 'utf8');
const html = fs.readFileSync('web/index.html', 'utf8');
const start = source.indexOf('  function shortModelVersion(value){');
const end = source.indexOf('  function contentActive(content){', start);
assert.ok(start >= 0 && end > start, 'public model label helpers must exist');

const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context, { timeout: 1000 });
const name = context.publicModelName;
assert.equal(typeof name, 'function');
assert.equal(name('v201-20261005T201258172391Z'), 'BlinQ Core v201 · 05.10.2026');
assert.equal(name('v201-20260925T204608601094Z'), 'BlinQ Core v201 · 25.09.2026');
assert.equal(name('v201'), 'BlinQ Core v201');
assert.equal(name(''), '—');
assert.equal(name('demo-preview'), 'demo-preview');

assert.ok(source.includes('escapeHtml(publicModelName(result.model_version))'), 'comparison view must show public model name');
assert.ok(source.includes('publicModelName(feed.model?.version)'), 'model page must show public model name');
assert.ok(source.includes("feed.model_version||state.feed?.model?.version"), 'admin diagnostics must preserve model identifier');
assert.match(html, /\/app\.js\?[^"]*&model-label=core1/, 'updated frontend must invalidate app.js cache');
