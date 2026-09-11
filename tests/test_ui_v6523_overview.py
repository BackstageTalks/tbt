import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_overview_route_navigation_and_admin_access_exist():
    cfg=json.loads((ROOT/'web/ui-config.json').read_text(encoding='utf-8'))
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    assert cfg['ui_revision'] in {'6.5.23','6.5.24','6.5.25'}
    assert any(v in html for v in ('v=v6523','v=v6524','v=v6525'))
    assert cfg['elements']['SIDEBAR_OVERVIEW']['content']['route']=='overview'
    assert cfg['elements']['SIDEBAR_OVERVIEW']['access']['rookie']=='locked'
    assert cfg['elements']['SIDEBAR_OVERVIEW']['access']['goat']=='active'
    assert "dashboardPageSectionKeys=['overview','results','btts']" in app
    assert "if(route==='overview') body=renderOverviewPage();" in app
    assert "if(route==='overview')wireOverview();" in app
    assert 'data-route="overview"' in html


def test_overview_uses_all_upcoming_matches_and_real_market_fields():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert "(state.feed?.upcoming||[]).map(normalize)" in app
    assert "m.odds" in app
    assert "m.edge" in app
    assert "m.expectedValue" in app
    assert "overviewDataFacts" in app
    assert "overviewCategoryMap" in app
    assert "openMatch(row)" in app


def test_overview_is_responsive_for_tablet_and_mobile():
    css=(ROOT/'web/responsive.css').read_text(encoding='utf-8')
    styles=(ROOT/'web/styles.css').read_text(encoding='utf-8')
    assert '.overview-table' in styles
    assert '@media (max-width:860px)' in css
    assert '@media (max-width:560px)' in css
    assert '.overview-table tr{display:grid' in css
