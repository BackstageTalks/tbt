from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_v6524_theme_assets_and_toggle():
    html=(ROOT/'web/index.html').read_text()
    css=(ROOT/'web/premium-theme.css').read_text()
    js=(ROOT/'web/theme.js').read_text()
    cfg=json.loads((ROOT/'web/ui-config.json').read_text())
    assert cfg['ui_revision'] in {'6.5.24','6.5.25','6.5.26'}
    assert any(v in html for v in ('/premium-theme.css?v=v6524','/premium-theme.css?v=v6525','/premium-theme.css?v=v6526'))
    assert any(v in html for v in ('/theme.js?v=v6524','/theme.js?v=v6525','/theme.js?v=v6526'))
    assert 'id="themeToggle"' in html
    assert 'data-theme="dark"' in css
    assert 'blinq_theme_v1' in js
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in css
    assert '@media(max-width:760px)' in css
