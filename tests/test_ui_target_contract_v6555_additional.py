from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_player_image_proxy_and_frontend_fallback_present():
    api = read("api/function_app.py")
    js = read("web/app.js")
    assert 'route="v1/player-image/{player_id}"' in api
    assert 'RapidTennisClient(settings).player_image(raw)' in api
    assert '/api/v1/player-image/' in js

def test_target_ui_has_daily_mark_slogan_and_footer_composition():
    html = read("web/index.html")
    css = read("web/final-ui.css")
    assert 'daily-hub-mark' in html
    assert 'intel-slogan' in html
    assert 'footer-composition' in html
    assert '.top-notification' in css
    assert 'grid-template-columns:repeat(4,minmax(0,1fr)) 230px' in css
