import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_v6515_flexible_admin_access_and_ordering():
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    assert tuple(map(int,cfg['ui_revision'].split('.'))) >= (6,5,15)
    assert cfg['header_cta']['slot_count'] <= 3
    assert cfg['hero_banner']['slot_count'] <= 5
    assert 'HERO_BANNER_5' in cfg['elements']
    for key,section in cfg['dashboard']['sections'].items():
        for plan in ('expired','trial','rookie','pro','elite','legend','goat'):
            ent=section['plans'][plan]
            assert ent['visible_picks']=='ALL' or 0 <= ent['visible_picks'] <= 20
            assert 1 <= ent['order'] <= 20
            assert isinstance(ent['blur_remaining'],bool)
            assert isinstance(ent['see_all'],bool)

def test_v6515_banner_visibility_and_click_access_are_independent():
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    for key in ('HEADER_BANNER_1','HEADER_BANNER_2','HEADER_BANNER_3','HERO_BANNER_1','HERO_BANNER_5'):
        item=cfg['elements'][key]
        assert 'access' in item and 'click_access' in item
        for plan in ('expired','trial','rookie','pro','elite','legend','goat'):
            assert isinstance(item['click_access'][plan],bool)

def test_v6515_admin_is_simplified_and_runtime_uses_plan_order():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    assert "['layout','Layout & access'" in app
    assert "['plans','Plans'" in app
    assert "['accounts','Accounts'" in app
    assert "['campaigns','Banner campaigns'" not in app
    assert "['performance','Model Quality'" not in app
    assert 'function orderedDashboardKeys' in app
    assert 'data-dashboard-matrix-field="visible_picks"' in app
    assert 'data-dashboard-matrix-field="order"' in app
    assert 'data-banner-click-plan' in app
    assert 'data-banner-visible-plan' in app
