from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq.css").read_text(encoding="utf-8")


def test_loader_is_ball_rally_without_progress_track():
    assert 'class="boot-tennis-rally"' in INDEX
    assert 'class="boot-tennis-ball"' in INDEX
    assert 'class="boot-tennis-track"' not in INDEX
    assert "@keyframes blinqRallyBall" in CSS
    assert "animation:blinqRallyBall" in CSS


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
    assert '/blinq.css?v=6806' in INDEX
    assert '/app.js?v=6806' in INDEX
    assert '/assets/blinq_loading_tennis.webp?v=6806' in INDEX
