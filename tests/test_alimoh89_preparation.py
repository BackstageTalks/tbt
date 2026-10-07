from pathlib import Path

from scripts.prepare_alimoh89_markets import (
    FORBIDDEN_MODEL_COLUMNS,
    extract_markets,
    infer_tour,
    orient_markets,
)

def test_tour_mapping():
    assert infer_tour("ATP") == "atp"
    assert infer_tour("WTA") == "wta"
    assert infer_tour("ATP Challenger") == "atp"
    assert infer_tour("ITF Women") == "wta"
    assert infer_tour("ITF") is None

def test_market_extraction_and_orientation():
    row = {
        "bet365_odds_a_opening": "1.50",
        "bet365_odds_b_opening": "2.60",
        "bet365_odds_a": "1.40",
        "bet365_odds_b": "2.90",
        "bet365_handicap": "-2.5",
        "bet365_odds_handicap_a_opening": "1.90",
        "bet365_odds_handicap_b_opening": "1.90",
        "bet365_total_games_line": "22.5",
        "bet365_odds_over_opening": "1.85",
        "bet365_odds_under_opening": "1.95",
        "best_odds_a_opening": "1.55",
        "best_odds_b_opening": "2.65",
        "best_odds_a": "1.45",
        "best_odds_b": "2.95",
    }
    markets = extract_markets(row)
    assert markets["bookmakers"]["bet365"]["money_open"]["a"] == 1.5
    oriented = orient_markets(markets, "swapped")
    assert oriented["bookmakers"]["bet365"]["money_open"]["player1"] == 2.6
    assert oriented["bookmakers"]["bet365"]["money_open"]["player2"] == 1.5
    assert oriented["bookmakers"]["bet365"]["handicap_line_recorded"] == -2.5

def test_postmatch_columns_are_explicitly_forbidden():
    assert "completed" in FORBIDDEN_MODEL_COLUMNS
    assert "set1_score_a" in FORBIDDEN_MODEL_COLUMNS
    assert "total_games" in FORBIDDEN_MODEL_COLUMNS
