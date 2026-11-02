"""BlinQ picks Aces/DF independently of bookmaker price availability."""

from pathlib import Path

PIPELINE = (Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py").read_text(
    encoding="utf-8"
)


def test_blinq_selects_aces_before_fetching_any_projection_prices():
    selected = PIPELINE.index("ace_picks, ace_report = select_ace_picks(")
    fetched = PIPELINE.index("prefetch_projection_market_board(", selected)
    attachment = PIPELINE.index("ace_picks, sg_picks, attachment_report = enrich_projection_odds(", fetched)
    assert selected < fetched < attachment
    assert PIPELINE.count("ace_picks, ace_report = select_ace_picks(") == 1
    args = PIPELINE[selected:PIPELINE.index("\n        )", selected)]
    assert "per_market_limit=10, total_limit=20, target_count=10" in args
    assert "available_markets_by_event" not in args


def test_missing_ace_prices_cannot_trigger_substitute_matches():
    assert '"pre_odds_selected"' in PIPELINE
    assert '"selection_policy"] = "blinq_model_first_then_odds_attachment"' in PIPELINE
    assert '"priced_selection_policy": "blinq_model_first_provider_player_ou_then_local_statistical_ou"' in PIPELINE
    assert "for row in ace_picks:" in PIPELINE
    assert "selected_aces.append(row)" in PIPELINE
    assert "selected_aces.append(local)" in PIPELINE
    assert "publishable_api_price(row)" in PIPELINE
    assert "elif eligible_local_ace_projection(row):" in PIPELINE
    assert "local_player_aces_ou(row)" in PIPELINE
    assert 'row.get("price_contract") == "player_total_ou"' in PIPELINE
    assert "publishable_api_price(row) or eligible_local_ace_projection(row)" not in PIPELINE
    # SG odds-first remains unchanged; no locally priced superiority Aces bets.
    assert "sg_picks, sg_report = select_sg_picks(" in PIPELINE
    assert "aces_local_fallback_published" in PIPELINE
