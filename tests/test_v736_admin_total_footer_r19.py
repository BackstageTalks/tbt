from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
    assert "const totalToday=Math.max(Number(dailyEnt?.total)||0,rows.length);" in text
    assert 'String(totalToday)' in text

def test_footer_watermark_explicitly_overrides_legacy_hidden_rule():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    css=(ROOT/'web/blinq-app.css').read_text(encoding='utf-8')
    assert 'class="footer-watermark-logo"' in html
    assert 'runtime patch 7.3.6-r19' in css
    assert 'visibility:visible!important' in css

def test_r19_identity():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    assert 'content="736-r19"' in html
    assert 'p=19' in html
