"""Behavioral and accessibility regressions for the compact BlinQ footer."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_compact_footer_has_online_status_and_one_update_field():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    css = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    footer = html.split('<footer class="site-footer site-footer-minimal">', 1)[1].split("</footer>", 1)[0]
    assert 'id="footerHealthLabel">BlinQ —' in footer
    assert 'id="footerFeedUpdate">Aktualizácia —' in footer
    assert 'id="footerLastUpdate"' not in footer
    assert '>Scan —<' not in footer
    assert 'id="footerModelVersion"' not in footer
    assert footer.count('class="footer-system-divider"') == 1
    assert 'footer-system-status is-stale' in footer  # Fail closed until feed loads.
    assert "@keyframes blinqStatusBreath" in css
    assert "animation:blinqStatusBreath" in css
    assert ".footer-system-status.is-stale .footer-system-dot{animation:none" in css
    assert "(prefers-reduced-motion: reduce)" in css
    assert "setInterval(renderSystemFooterStatus,30*1000)" in app
    assert "footer-match-update=1" in html  # Invalidate cached JS.


def test_footer_runtime_uses_match_updater_only_and_thirty_minute_boundary():
    if not shutil.which("node"):
        pytest.skip("Node.js required for JS runtime evaluation")
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/app.js', 'utf8');
const from = source.indexOf('function renderSystemFooterStatus(){');
const until = source.indexOf('function insightTypeLabel(', from);
assert(from >= 0 && until > from);
const fn = source.slice(from, until);
const now = Date.parse('2026-11-01T19:00:00Z');
function run(matchAt, version = '7.2.1+build', feedAt = '2026-11-01T06:20:00Z') {
  const texts = Object.fromEntries(['footerFeedUpdate', 'footerHealthLabel'].map(id => [id, {textContent:''}]));
  const classes = {};
  const host = {classList: {toggle: (name, on) => {classes[name] = on;}}};
  const byId = id => id === 'footerSystemStatus' ? host : texts[id];
  const context = {
    state: {feed: {model: {version}, generated_at: feedAt, match_status_updated_at: matchAt}},
    $: byId, lcopy: (en, sk, cz) => sk,
    fmtTime: s => s.slice(11, 16),
    shortModelVersion: s => String(s || '').split('+')[0],
    Date: {parse: Date.parse, now: () => now}
  };
  vm.runInNewContext(fn + '\nrenderSystemFooterStatus();', context, {timeout: 2000});
  return {texts, classes};
}
const at30 = run('2026-11-01T18:30:00Z');
assert.equal(at30.texts.footerHealthLabel.textContent, 'BlinQ 7.2.1 ONLINE');
assert.equal(at30.texts.footerFeedUpdate.textContent, 'Aktualizácia 18:30');
assert.equal(at30.texts.footerLastUpdate, undefined);
assert.equal(at30.classes['is-stale'], false);
assert.equal(at30.classes['is-delayed'], false);
const older = run('2026-11-01T18:29:59Z');
assert.equal(older.texts.footerHealthLabel.textContent, 'BlinQ 7.2.1 DELAY');
assert.equal(older.texts.footerFeedUpdate.textContent, 'Aktualizácia 18:29');
assert.equal(older.classes['is-stale'], true);
assert.equal(older.classes['is-delayed'], true);
const absent = run('');
assert.equal(absent.texts.footerHealthLabel.textContent, 'BlinQ 7.2.1 NEZNÁMY STAV');
assert.equal(absent.texts.footerFeedUpdate.textContent, 'Aktualizácia —');
assert.equal(absent.classes['is-stale'], true);
const future = run('2026-11-01T19:01:00Z');
assert.equal(future.classes['is-stale'], true);
assert.equal(future.classes['is-delayed'], false);
const noVersion = run('2026-11-01T18:59:00Z', '');
assert.equal(noVersion.texts.footerHealthLabel.textContent, 'BlinQ ONLINE');
"""
    proc = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True,
        timeout=15, check=False
    )
    assert proc.returncode == 0, proc.stderr
