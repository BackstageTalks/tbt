from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path): return (ROOT / path).read_text(encoding="utf-8")

def test_web_rebuild_keeps_business_runtime_but_replaces_visual_stack():
    html = read("web/index.html")
    css = read("web/blinq.css")
    app = read("web/app.js")
    assert 'id="appShell"' in html
    assert 'id="dailyHub"' in html
    assert 'id="routePanel"' in html
    assert 'id="matchDialog"' in html
    assert 'id="accountDialog"' in html
    assert 'id="upgradeDialog"' in html
    assert '.runtime-hooks' in css
    assert 'renderDailyHub' in app
    assert 'renderAdminRoute' in app

def test_reference_visual_components_exist():
    html = read("web/index.html")
    css = read("web/blinq.css")
    for token in ('feature-strip','hero-shell','daily-panel','intel-strip','vip-rail','site-footer'):
        assert token in html
    for selector in ('.header-slot','.hero-shell','.daily-hub-table','.intel-strip','.vip-rail','.match-dialog'):
        assert selector in css
