from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
RELEASE = json.loads((ROOT/'web'/'release.json').read_text(encoding='utf-8'))
PATCH = str(RELEASE['patch'])
PATCH_NUM = PATCH.rsplit('r',1)[-1]

def test_admin_backend_never_inherits_rookie_runtime_rules():
    text=(ROOT/'api/tbt/services/entitlements.py').read_text(encoding='utf-8')
    assert 'if str(plan or "").strip().lower() == "admin": return None' in text

def test_admin_frontend_never_renders_membership_slot_locks():
    text=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert "if(accountPlan()==='admin'&&!state.previewPlan)" in text
    assert "visible_picks:'ALL'" in text
    assert "slot_states:[]" in text

def test_today_kpi_uses_total_supply_not_authorized_rows():
    text=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert "state.feed?.entitlements?.daily_pick_count" in text
    assert "Number.isSafeInteger(suppliedTotal)" in text
    assert "dailyHubRows('see_all').length" in text
    assert 'String(totalToday)' in text

def test_footer_status_replaces_legacy_watermark_and_matches_current_patch():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    css=(ROOT/'web/blinq-app.css').read_text(encoding='utf-8')
    assert 'id="footerSystemStatus"' in html
    assert 'footer-watermark-logo' not in html
    assert 'Všetky systémy funkčné' in html
    assert f"runtime patch 7.3.6-r{PATCH_NUM}" in css
    assert '@keyframes blinqStatusBreath' in css

def test_current_patch_identity():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    assert f'content="{PATCH}"' in html
    assert f'p={PATCH_NUM}' in html
