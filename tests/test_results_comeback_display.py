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
    # MAX value is preserved, only the former explanatory hover text is removed.
    assert "ROI uses the published pre-match price" not in block
    assert 'class="result-live-max">MAX ${peak.toFixed(2)}</small>' in block
    assert "title=" not in block
    assert "resultLiveMaxOddsHtml(publication,odds,outcome)" in app
    css_block = css.split("body#blinqPremium .result-live-max{", 1)[1].split("}", 1)[0]
    assert "display:block!important" in css_block
    assert "margin:3px 0 0!important" in css_block
    assert "color:#ff8a2a!important" in css_block


def test_results_calendar_and_betting_day_helper_copy_without_final_period():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    for text in ("Vyber začiatok obdobia", "Vyber koniec obdobia", "Obdobie je pripravené"):
        assert f"'{text}'" in app
        assert f"'{text}.'" not in app
    tooltip = "Vybrané dátumy sa počítajú od 06:00 do 06:00 Europe/Bratislava"
    assert f"'{tooltip}'" in app
    assert f"'{tooltip}.'" not in app
