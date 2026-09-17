from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq.css").read_text(encoding="utf-8")
LOADER = (ROOT / "web" / "assets" / "blinq_loading_animated_v6.svg").read_text(encoding="utf-8")


def test_loader_is_compact_svg_rally_without_progress_track():
    assert '/assets/blinq_loading_animated_v6.svg' in INDEX
    assert 'boot-tennis-track' not in INDEX
    assert '<animateTransform' in LOADER
    assert 'aria-label="BlinQ loading animation"' in LOADER
    assert 'data:image/webp;base64,' in LOADER


def test_auth_login_hides_signup_only_telegram_field():
    assert 'id="nameLabel" hidden' in INDEX
    assert ".auth-card label[hidden]{display:none!important}" in CSS
    assert "background:linear-gradient(100deg,#35e69c,#47efbd)!important" in CSS


def test_short_odds_public_labels_replace_prime_in_results_and_cards():
    assert "prime:'Short Odds'" in APP
    assert "key==='prime'?'Short Odds Prediction'" in APP
    assert "publicText('Short Odds rule')" in APP
    assert "No Short Odds predictions available yet" in APP
    assert "Načítavam Prime predikcie" not in APP
    assert "Pravidlo Prime" not in APP
    assert "Prime predikcia" not in APP


def test_frontend_cache_bust_for_final_ui_pass():
    cfg = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    cache = str(cfg['asset_revision'])
    for asset in ('blinq.css','redesign-680.css','polish-681.css','polish-683.css','polish-684.css','polish-685.css','app.js'):
        assert f'/{asset}?v={cache}' in INDEX
    assert f'/assets/blinq_loading_animated_v6.svg?v={cache}' in INDEX
