from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_v6521_match_card_structure_and_cache():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'web'/'responsive.css').read_text(encoding='utf-8')
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    assert tuple(map(int,cfg['ui_revision'].split('.'))) >= (6,5,21)
    assert 'v=v6521' in html or 'v=v6522' in html
    assert 'match-card-v3' in html
    assert 'match-card-v3' in app
    assert 'pick-score' in app
    assert 'match-kpi-bar' in app
    assert '.match-card-v3 .match-pick-row' in css
    assert '.match-card-v3 .match-kpi-bar' in css
    assert '.metric-negative' in css

def test_v6521_dashboard_has_single_primary_see_more_action():
    css=(ROOT/'web'/'responsive.css').read_text(encoding='utf-8')
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    assert 'section-see-all-card:not([data-upgrade-plan]){display:none!important}' in css
    assert 'data-route="${escapeHtml(key)}"' in app
