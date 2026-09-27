'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/app.js', 'utf8');
const start = source.indexOf('  function adminSystemHealthView(');
const end = source.indexOf('  function renderAdminLevels(){', start);
assert.ok(start > 0 && end > start, 'Admin-only health functions must exist');
const renderer = source.slice(start, end);

function render(diagnostics, loading = false) {
  const context = {
    state: {
      adminDiagnostics: diagnostics,
      adminDiagnosticsLoading: loading,
      feed: { model: { version: 'test-model' } },
    },
    escapeHtml: value => String(value ?? '').replace(/[&<>'"]/g, ch =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[ch]),
    fmtDate: () => '27.09.2026',
    fmtTime: () => '12:37',
    systemState: (ok, warning = false) => ok ? 'ok' : warning ? 'warning' : 'error',
  };
  return vm.runInNewContext(renderer + '\nrenderAdminSystem();', context);
}

const healthy = {
  checked_at: 1790505470,
  accounts_ready: true,
  auth_provider: 'firebase',
  admin_storage: 'azure',
  content_storage_ready: true,
  storage: {
    backend: 'azure',
    azure_connection_source: 'BLINQ_STORAGE_CONNECTION_STRING',
    services: { premium_info: true, live_alert_history: true, admin_config: true },
  },
  assets: {
    player_images: { ok: true, provider_or_proxy_refs: 139, total: 139, fallback_needed: 0 },
    tournament_logos: { ok: true, provider_or_proxy_refs: 147, total: 147, fallback_needed: 0 },
  },
  services: { info_storage: true, live_data: true },
  live_worker: { configured: true, healthy: true, age_seconds: 55 },
  account_inactivity: {
    policy: { enabled: true },
    worker: { configured: true, healthy: true },
    smtp: { configured: true, admin_recipient_configured: true, admin_recipient_count: 1 },
  },
  provider: { configured: true },
  feed: {
    ready: true, stale: false, generated_at: '2026-09-27T10:32:00Z',
    model_version: 'v201', upcoming: 489, results: 711,
  },
  ops: { available: true, counts: { error: 0 }, items: [] },
};

const allGood = render(healthy);
assert.match(allGood, /Všetky kontroly v poriadku/);
assert.match(allGood, /<b>11<\/b> v poriadku/);
assert.match(allGood, /admin-health-ok-details" open/);
assert.ok(!allGood.includes('Treba skontrolovať'));

const warnings = structuredClone(healthy);
warnings.assets.tournament_logos = { ok: false, provider_or_proxy_refs: 104, total: 147, fallback_needed: 43 };
warnings.live_worker = { configured: true, healthy: false, age_seconds: 500 };
const degraded = render(warnings);
assert.match(degraded, /Funguje s upozorneniami/);
assert.match(degraded, /<b>9<\/b> v poriadku/);
assert.match(degraded, /<b>2<\/b> na kontrolu/);
assert.match(degraded, /Treba skontrolovať/);
assert.match(degraded, /Chýbajúce logá majú náhradný obrázok/);
assert.match(degraded, /Over externý cron, zhodný GitHub Secret/);
assert.match(degraded, /<details class="admin-health-ok-details">/);
assert.ok(!degraded.includes('TBT_LIVE_RADAR_ENABLED'), 'obsolete internal GitHub timers must not be recommended');

const unavailableJournal = structuredClone(healthy);
unavailableJournal.ops = { available: false, counts: { error: 0 }, items: [] };
const unavailable = render(unavailableJournal);
assert.match(unavailable, /Prevádzkový journal nie je dostupný/);
assert.match(unavailable, /NEDOSTUPNÉ/);
assert.ok(!unavailable.includes('Za posledných 24 hodín nie sú zaznamenané žiadne'));

const authError = render({ ok: false, error: 'unauthorized <img onerror=alert(1)>', status: 401 });
assert.match(authError, /Diagnostiku sa nepodarilo načítať/);
assert.match(authError, /HTTP 401/);
assert.ok(!authError.includes('<img onerror='));
assert.ok(!authError.includes('admin-system-card is-error'), 'API failure is not eleven failed checks');

const pending = render(null, true);
assert.match(pending, /Načítavam diagnostiku/);
assert.ok(!pending.includes('admin-system-card is-error'), 'unloaded data is never red');

console.log('PASS: admin health summary, triage, honest journal and diagnostic errors');
