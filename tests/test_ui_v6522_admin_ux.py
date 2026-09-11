from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_v6522_admin_is_task_based_and_goat_is_top_tier():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    assert cfg['ui_revision'] in {'6.5.22','6.5.23'}
    assert any(v in html for v in ('v=v6522','v=v6523'))
    assert "const membershipHierarchy = ['rookie','pro','elite','legend','goat']" in app
    assert "const accessContexts = ['expired',...membershipHierarchy]" in app
    assert 'GOAT is always the highest level' in app
    assert 'function renderBannerEditor' in app
    assert 'data-admin-banner-preview-plan' in app
    assert 'data-banner-preset="teaser-pro"' in app
    assert 'Visible to all · link PRO+' in app
    assert 'data-dashboard-route-access' in app
    assert 'All membership levels' in app
    assert '.admin-banner-workspace' in css
    assert '.admin-section-list' in css

def test_v6522_copy_level_copies_section_and_banner_permissions():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    block=app.split("else if(action==='copy-plan')",1)[1].split("else if(action==='preview-demo')",1)[0]
    assert 'item.click_access' in block
    assert 'cfg.plans[target]=clone(cfg.plans[source])' in block
    assert 'item.access.trial=item.access[target]' in block

def test_v6522_plan_order_is_fixed_in_config():
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    assert [cfg['plans'][p]['order'] for p in ('rookie','pro','elite','legend','goat')] == [1,2,3,4,5]
    assert cfg['plans']['goat']['lifetime'] is True

def test_v6522_section_controls_use_plain_language_and_quick_presets():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    assert "['active','OPEN']" in app
    assert "['locked','VISIBLE · LOCKED']" in app
    assert "['hidden','HIDDEN']" in app
    assert 'data-section-preset="full"' in app
    assert 'data-section-preset="teaser"' in app
    assert 'data-section-preset="blurred"' in app
    assert 'data-section-preset="hidden"' in app
    assert "ent.visible_picks=0" in app
    assert '.admin-section-presets' in css
