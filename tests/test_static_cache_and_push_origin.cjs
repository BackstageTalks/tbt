'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const sw = fs.readFileSync('web/blinq-sw.js', 'utf8');
const config = JSON.parse(fs.readFileSync('web/staticwebapp.config.json', 'utf8'));
const cache = Object.fromEntries(config.routes.map(route => [route.route, route.headers?.['Cache-Control'] || '']));

// Public static assets can be revalidated without caching private application data.
for (const path of ['/app.js', '/blinq-app.css']) {
  assert.equal(cache[path], 'public, max-age=0, must-revalidate');
}
for (const path of ['/', '/index.html', '/auth.js', '/ui-config.json', '/release.json', '/deployment.json']) {
  assert.match(cache[path], /no-store/, path);
}
assert.match(fs.readFileSync('scripts/stamp_web_deployment.py', 'utf8'), /&deploy=/);

async function click(url, existingWindow = false) {
  const handlers = {};
  const seen = {closed: 0, focused: 0, navigated: [], opened: []};
  const self = {
    location: {origin: 'https://blinq.example'},
    addEventListener: (name, handler) => { handlers[name] = handler; },
    registration: {showNotification: async () => {}},
  };
  const windowClient = {
    navigate: async target => { seen.navigated.push(target); },
    focus: async () => { seen.focused += 1; },
  };
  const clients = {
    matchAll: async () => existingWindow ? [windowClient] : [],
    openWindow: async target => { seen.opened.push(target); },
  };
  vm.runInNewContext(sw, {self, clients, URL}, {filename: 'blinq-sw.js'});
  assert.equal(typeof handlers.notificationclick, 'function');
  assert.equal(typeof handlers.push, 'function');
  let task;
  handlers.notificationclick({
    notification: {data: {url}, close: () => { seen.closed += 1; }},
    waitUntil: promise => { task = promise; },
  });
  await task;
  assert.equal(seen.closed, 1);
  return seen;
}

(async () => {
  assert.deepEqual((await click('/#results')).opened, ['https://blinq.example/#results']);
  const sameOrigin = await click('https://blinq.example/path?x=1', true);
  assert.deepEqual(sameOrigin.navigated, ['https://blinq.example/path?x=1']);
  assert.equal(sameOrigin.focused, 1);
  for (const bad of [
    'https://evil.example/phishing', '//evil.example/phishing',
    'javascript:alert(1)', 'data:text/html,evil',
    'https://blinq.example@evil.example/path',
    'https://user:password@blinq.example/path',
    'http://blinq.example/insecure', 'http://[invalid',
  ]) {
    assert.deepEqual((await click(bad)).opened, ['https://blinq.example/#predictions'], bad);
  }
  console.log('Same-origin push navigation and safe public asset revalidation: PASS');
})().catch(err => { console.error(err); process.exitCode = 1; });
