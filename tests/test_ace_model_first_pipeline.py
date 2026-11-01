"""Protect BlinQ's match-selection authority from external Aces price discovery."""

from pathlib import Path


PIPELINE = (Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py").read_text(
    encoding="utf-8"
)


def test_aces_selection_is_not_gated_by_available_external_ace_markets():
    assert PIPELINE.count("ace_picks, ace_report = select_ace_picks(") == 1
    selected = PIPELINE.index("ace_picks, ace_report = select_ace_picks(")
    first_odds_fetch = PIPELINE.index("prefetch_projection_market_board(", selected)
    final_enrichment = PIPELINE.index("ace_picks, sg_picks, attachment_report = enrich_projection_odds(")
    assert selected < first_odds_fetch < final_enrichment
    selector_call = PIPELINE[selected:PIPELINE.index(")", selected)]
    assert "available_markets_by_event" not in selector_call
    assert "per_market_limit=10, total_limit=20, target_count=10" in selector_call


def test_aces_provider_price_does_not_trigger_substitute_model_selection():
    selected = PIPELINE.index("ace_picks, ace_report = select_ace_picks(")
    remainder = PIPELINE[selected:]
    assert remainder.count("ace_picks, ace_report = select_ace_picks(") == 1
    assert '"priced_selection_policy": "blinq_model_first_then_exact_player_ou_price"' in remainder
    assert '"pre_odds_selected"' in remainder
    assert "ace_picks = [row for row in ace_picks if publishable_api_price(row)]" in remainder
