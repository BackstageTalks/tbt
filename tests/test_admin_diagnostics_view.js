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
    player_images: { ok: true, deployed_assets: 139, provider_or_proxy_refs: 139, total: 139, fallback_needed: 0 },
    tournament_logos: { ok: true, deployed_assets: 147, provider_or_proxy_refs: 147, total: 147, fallback_needed: 0 },
    market_odds: {
      required: {
        ok: true, total: 20, priced: 20, missing: 0,
        sections: {
          short_odds: { total: 5, priced: 5, missing: 0 },
          top: { total: 5, priced: 5, missing: 0 },
          value: { total: 5, priced: 5, missing: 0 },
          doubles: { total: 5, priced: 5, missing: 0 },
        },
      },
      projections: {
        total: 12, priced: 7, missing: 5,
        sections: {
          aces: { total: 3, priced: 2, missing: 1 },
          double_faults: { total: 3, priced: 1, missing: 2 },
          games: { total: 3, priced: 2, missing: 1 },
          sets: { total: 3, priced: 2, missing: 1 },
        },
      },
    },
  },
  services: { info_storage: true, live_data: true, match_status_worker: true },
  live_worker: { configured: true, healthy: true, age_seconds: 55, scheduler_owner: 'external', expected_cadence_seconds: 300 },
  match_status_worker: { configured: true, healthy: true, age_seconds: 65, scheduler_owner: 'external', expected_cadence_seconds: 1800 },
  account_inactivity: {
    policy: { enabled: true },
    worker: { configured: true, healthy: true },
    smtp: { configured: true, admin_recipient_configured: true, admin_recipient_count: 1 },
  },
  provider: { configured: true },
  api_budget: {
    available: true, window: 'provider_day_19_10_europe_bratislava',
    global_spent: 18, global_limit: 13500, global_remaining: 13482,
    reserved_provider_headroom: 1500,
    next_reset_utc: '2026-09-27T17:10:00+00:00',
    purpose_limits: { live: 3000, match: 2500, refresh: 5500, history: 13500 },
    spent: { live: 6, match: 12, refresh: 0, history: 0 },
    remaining: { live: 2994, match: 2488, refresh: 5500, history: 13482 },
  },
  feed: {
    ready: true, stale: false, generated_at: '2026-09-27T10:32:00Z',
    model_version: 'v201', upcoming: 489, results: 711,
  },
  ops: { available: true, counts: { error: 0 }, items: [] },
};

const allGood = render(healthy);
assert.match(allGood, /Všetky kontroly v poriadku/);
assert.match(allGood, /<b>13<\/b> v poriadku/);
assert.match(allGood, /admin-health-ok-details" open/);
assert.match(allGood, /API ROZPOČET · PROVIDER DEŇ/);
assert.match(allGood, /LIVE využité/);
assert.match(allGood, /6 \/ 3\s?000/);
assert.match(allGood, /Spolu rezervované/);
assert.match(allGood, /Provider rezerva/);
assert.match(allGood, /MATCH STATUS/);
assert.match(allGood, /30m cadence/);
assert.match(allGood, /Obnoviť diagnostiku/);
assert.match(allGood, /PREZENTAČNÁ COVERAGE · FOTO & KURZY/);
assert.match(allGood, /20\/20 priced · 0 missing/);
assert.match(allGood, /12\/7|7\/12 priced · 5 missing/);
assert.ok(!allGood.includes('Treba skontrolovať'));

const warnings = structuredClone(healthy);
warnings.assets.tournament_logos = { ok: false, deployed_assets: 104, provider_or_proxy_refs: 147, total: 147, fallback_needed: 43 };
warnings.live_worker = { configured: true, healthy: false, age_seconds: 500 };
warnings.match_status_worker = { configured: true, healthy: false, age_seconds: 4000 };
const degraded = render(warnings);
assert.match(degraded, /Funguje s upozorneniami/);
assert.match(degraded, /<b>9<\/b> v poriadku/);
assert.match(degraded, /<b>3<\/b> na kontrolu/);
assert.match(degraded, /Treba skontrolovať/);
assert.match(degraded, /Chýbajúce logá majú náhradný obrázok/);
const missingOdds = structuredClone(healthy);
missingOdds.assets.market_odds.required = {
  ...missingOdds.assets.market_odds.required,
  ok: false, total: 20, priced: 18, missing: 2,
};
const oddsWarning = render(missingOdds);
assert.match(oddsWarning, /BETTING ODDS/);
assert.match(oddsWarning, /18\/20 priced · 2 missing/);
assert.match(oddsWarning, /market refresh/);

assert.match(degraded, /Over externý cron, zhodný GitHub Secret/);
assert.match(degraded, /Over externý 30-minútový cron/);
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
const loading = render(healthy, true);
assert.match(loading, /Obnovuje sa…/);
assert.match(loading, /aria-busy="true"/);
const noBudget = structuredClone(healthy);
delete noBudget.api_budget;
assert.match(render(noBudget), /Údaje o spoločnej API kvóte nie sú dostupné/);
assert.ok(!pending.includes('admin-system-card is-error'), 'unloaded data is never red');

console.log('PASS: admin health summary, triage, honest journal and diagnostic errors');
