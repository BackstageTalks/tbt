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


def test_comeback_arrow_removed_from_results():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    assert "function resultComebackIcon" not in app
    assert "result-comeback-icon" not in app
    assert "result-comeback-icon" not in css


def test_player_fallback_handles_itf_women_and_is_eager():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "womenEvent=" in app
    assert "w(?:15|25|35|50|75|100)" in app
    assert "row?.tournament" in app
    assert 'class="player-avatar-fallback"' in app
    assert 'loading="eager"' in app


def test_results_live_max_odds_only_for_confirmed_comeback_below_price():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    block = app.split("function resultLiveMaxOddsHtml(publication,publishedOdds,outcome){", 1)[1].split("  function renderResults(){", 1)[0]
    assert "outcome?.kind!=='win'" in block
    assert "result.first_set_outcome||''" in block
    assert "toLowerCase()!=='loss'" in block
    assert "result.max_live_odds" in block
    assert "peak<=base+0.005" in block
    assert "ROI uses the published pre-match price" in block
    assert "resultLiveMaxOddsHtml(publication,odds,outcome)" in app
    css_block = css.split("body#blinqPremium .result-live-max{", 1)[1].split("}", 1)[0]
    assert "display:block!important" in css_block
    assert "margin:3px 0 0!important" in css_block
    assert "color:#ff8a2a!important" in css_block
