from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_results_desktop_names_wrap_instead_of_ellipsis():
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    block = css.split(
        "body#blinqPremium.blinq-route .result-match strong,",
        1,
    )[1].split("}", 1)[0]
    assert "white-space:normal!important" in block
    assert "overflow-wrap:anywhere!important" in block
    assert "text-overflow:clip!important" in block


def test_short_odds_comeback_badge_is_fail_closed():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function resultComebackIcon(publication,outcome)" in app
    assert "section!=='prime'" in app
    assert "first_set_outcome||''" in app
    assert "result-comeback-icon" in app
    assert "↻" in app


def test_player_fallback_handles_itf_women_and_is_eager():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "womenEvent=" in app
    assert "w(?:15|25|35|50|75|100)" in app
    assert "row?.tournament" in app
    assert 'class="player-avatar-fallback"' in app
    assert 'loading="eager"' in app
