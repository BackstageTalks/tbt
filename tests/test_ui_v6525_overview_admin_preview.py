import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_overview_is_before_btts_and_has_full_access_rules():
    cfg=json.loads((ROOT/'web/ui-config.json').read_text(encoding='utf-8'))
    elements=cfg['elements']
    assert elements['SIDEBAR_OVERVIEW']['order'] < elements['SIDEBAR_BTTS']['order']
    assert elements['SIDEBAR_OVERVIEW']['order'] > elements['SIDEBAR_RESULTS']['order']
    ov=cfg['dashboard']['sections']['overview']
    for plan in ['expired','rookie','pro','elite','legend','goat']:
        ent=ov['plans'][plan]
        assert 'visible_picks' in ent
        assert 'blur_remaining' in ent
        assert 'see_all' in ent

def test_admin_preview_is_explicit_and_admin_bypass_is_defensive():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    assert 'adminPreviewBar' in html and 'adminPreviewExit' in html
    assert 'syncAdminPreviewBar' in app
    assert "if(isAdminAccount()&&!state.previewPlan)" in app
    assert 'full ADMIN access restored' in app

def test_overview_renders_locked_rows_for_limited_levels():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert "dashboardPlanEntitlement('overview')" in app
    assert "visiblePickCount('overview',rows.length)" in app
    assert 'overviewLockedRow' in app
    assert "firstUnlockPlan('overview',0,true)" in app
