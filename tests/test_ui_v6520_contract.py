from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_v6520_banner_manager_and_cache_contract():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    assert tuple(map(int,cfg['ui_revision'].split('.'))) >= (6,5,20)
    assert "['banners','Banners & links'" in app
    assert 'function renderAdminBanners()' in app
    assert 'data-simple-banner-field' in app
    assert 'data-simple-banner-visible' in app
    assert 'data-simple-banner-click' in app
    assert 'HEADER_BANNER_${i}' in app
    assert 'HERO_BANNER_${i}' in app
    assert any(v in html for v in ('v=v6520','v=v6521','v=v6522'))

def test_v6520_dashboard_values_are_structured():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'web'/'responsive.css').read_text(encoding='utf-8')
    assert 'card-metrics-bar' in app
    assert 'card-more-link' in app
    assert 'card-metrics-bar' in html
    assert '.card-metric' in css
    assert '.card-more-link' in css
    assert 'grid-template-columns:118px minmax(0,1fr) 318px' in css
