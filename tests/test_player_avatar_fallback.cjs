'use strict';

/* Functional regression for layered ATP/WTA portraits in predictions/results. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'web/blinq-app.css'), 'utf8');
const start = app.indexOf('const safePhotoUrl =');
const end = app.indexOf('function accountAvatarUrl(', start);
assert.ok(start >= 0 && end > start, 'avatar implementation is present');

const listeners = {};
const ui = {assets: {player_fallback: {
  atp: '/assets/missing_foto_m.webp',
  wta: '/assets/missing_foto_w.webp',
}}};
class MockImage {
  constructor(kind, src, host) {
    this.kind = kind;
    this.src = src;
    this.hidden = false;
    this.dataset = {};
    this.parentElement = host;
  }
  matches(selector) { return selector === '[data-player-' + this.kind + ']'; }
}
function mockHost(tour) {
  const classes = new Set(['layered-player-avatar', 'has-photo', 'player-fallback-' + tour]);
  return {
    classList: {
      add(...names) { for (const name of names) classes.add(name); },
      remove(...names) { for (const name of names) classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
  };
}
const scope = {
  state: {ui},
  document: {
    querySelector: () => ({content: '736-r61'}),
    addEventListener(type, callback, capture) {
      assert.equal(capture, true, 'avatar handlers use capture phase');
      listeners[type] = callback;
    },
  },
  HTMLImageElement: MockImage,
  URL,
  escapeHtml: value => String(value).replace(/&/g, '&amp;'),
  initials: name => String(name).split(/\\s+/).slice(0, 2).map(n => n[0]).join('').toUpperCase(),
};
vm.runInNewContext(app.slice(start, end) +
  '\\n;globalThis.avatarFns={playerAvatarParts,playerAvatarHtml};', scope);
const {playerAvatarParts, playerAvatarHtml} = scope.avatarFns;
assert.equal(typeof listeners.error, 'function');
assert.equal(typeof listeners.load, 'function');

// No source photo must render the actual local portrait, not only initials.
for (const [tour, photo] of [['ATP', 'm'], ['WTA', 'w']]) {
  const parts = playerAvatarParts('', 'Alpha One', tour);
  assert.match(parts.fallback, new RegExp('/assets/missing_foto_' + photo + '\\.webp\\?'));
  assert.equal(parts.actual, '');
  const html = playerAvatarHtml('', 'Alpha One', tour, '', 'hub-avatar');
  assert.match(html, /data-player-fallback/);
  assert.match(html, /layered-player-avatar/);
  const asset = path.join(root, 'web/assets/missing_foto_' + photo + '.webp');
  assert.ok(fs.statSync(asset).size > 1000, 'real ' + photo + ' portrait exists');
  assert.ok(css.includes("background-image:url('/assets/missing_foto_" + photo + ".webp')!important"));
}
assert.ok(css.includes('.layered-player-avatar.has-photo .player-avatar-initials'));

// Source-photo failure must reveal the already-mounted fallback.
const host = mockHost('atp');
const source = new MockImage('photo', '/assets/players/123.webp', host);
listeners.error({target: source});
assert.equal(source.hidden, true);
assert.equal(host.classList.contains('using-fallback'), true);

// Retry even if the *shipped* fallback URL itself was the failed URL.
const fallback = new MockImage('fallback', '/assets/missing_foto_m.webp?p=736-r61&photo-pairs=1', host);
listeners.error({target: fallback});
assert.equal(fallback.dataset.localFallbackRetry, '1');
assert.match(fallback.src, /missing_foto_m\\.webp\\?p=736-r61&photo-pairs=1&retry=1$/);
assert.equal(fallback.hidden, false);
assert.equal(host.classList.contains('using-initials'), false);

// Successful retry recovers even from a stale initial state.
host.classList.add('using-initials');
listeners.load({target: fallback});
assert.equal(host.classList.contains('using-initials'), false);
assert.equal(host.classList.contains('has-photo'), true);
assert.equal(fallback.hidden, false);

// One retry maximum, then honest initials if the actual asset stays broken.
listeners.error({target: fallback});
assert.equal(fallback.hidden, true);
assert.equal(host.classList.contains('using-initials'), true);
assert.equal(host.classList.contains('has-photo'), false);

// A broken configured image also falls back to the real shipped local URL.
const customHost = mockHost('wta');
const broken = new MockImage('fallback', '/assets/deleted-custom.webp', customHost);
listeners.error({target: broken});
assert.match(broken.src, /missing_foto_w\\.webp\\?p=736-r61&photo-pairs=1&retry=1$/);
console.log('player avatar fallbacks: PASS');
