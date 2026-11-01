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
    assert '"priced_selection_policy": "blinq_model_first_api_pro_propline_moviodds_then_local_aces_only"' in PIPELINE
    assert "ace_picks = [row for row in ace_picks if (" in PIPELINE
    assert "publishable_api_price(row) or eligible_local_ace_projection(row)" in PIPELINE
    # The existing SG odds-first and local-Aces price policies are retained.
    assert "sg_picks, sg_report = select_sg_picks(" in PIPELINE
    assert "aces_local_fallback_published" in PIPELINE
