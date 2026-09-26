from datetime import datetime, timedelta, timezone

from tbt.schemas import MatchRecord
from tbt.services.engine import _settle_projection_publications
from tbt.services.projection_odds import (
    enrich_projection_odds, extract_player_total_ou,
)


def _provider_payload():
    return {"markets": [
        {"marketName": "Player A Total Aces", "choiceName": "Over",
         "choiceGroup": "5.5", "decimalOdds": 1.92},
        {"marketName": "Player A Total Aces", "choiceName": "Under",
         "choiceGroup": "5.5", "decimalOdds": 1.88},
        {"marketName": "Player B Total Aces", "choiceName": "Over",
         "choiceGroup": "4.5", "decimalOdds": 1.70},
        {"marketName": "Player B Total Aces", "choiceName": "Under",
         "choiceGroup": "4.5", "decimalOdds": 2.0},
        {"marketName": "Total Aces", "choiceName": "Over 13.5", "decimalOdds": 2.0},
        {"marketName": "Total Aces", "choiceName": "Under 13.5", "decimalOdds": 1.8},
    ]}


def test_player_ou_parser_only_matches_selected_player():
    rows = extract_player_total_ou(_provider_payload(), "aces", "Player A", player_slot=1)
    assert len(rows) == 1
    assert rows[0]["line"] == 5.5
    assert rows[0]["over"] == 1.92
    assert rows[0]["under"] == 1.88


def test_live_projection_uses_tennisapi_real_quote_and_freezes_contract():
    class Provider:
        def event_odds(self, event_id, provider_id=1):
            assert event_id == "123"
            return _provider_payload()

    card = {"event_id": "123", "market": "aces", "projection": 7.2,
            "player1": {"id": "1", "name": "Player A"},
            "player2": {"id": "2", "name": "Player B"},
            "selection_id": "1", "projection_subject": "Player A",
            "selection": "Player A", "price_status": "projection_only"}
    enriched, sg, report = enrich_projection_odds(Provider(), [card], [], max_events=1)
    assert sg == []
    picked = enriched[0]
    assert picked["price_contract"] == "player_total_ou"
    assert picked["ou_side"] == "over"
    assert picked["market_line"] == 5.5
    assert picked["odds"] == 1.92
    assert picked["price_status"] == "priced_projection"
    assert picked["selection_id"] == "1"
    assert report["priced_cards"]["aces"] == 1


def test_player_ou_settlement_uses_line_not_opponent():
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    match = MatchRecord(
        match_id="123", tour="atp", scheduled_at=start,
        player1_id="1", player1_name="Player A",
        player2_id="2", player2_name="Player B",
        winner_id="1", status="finished", best_of=3,
        stats={"p1_aces": 8, "p2_aces": 11},
    )
    pub = {
        "market": "aces", "section": "ace", "selection_id": "1",
        "price_contract": "player_total_ou", "ou_side": "over", "market_line": 5.5,
        "odds": 1.92, "price_status": "priced_projection",
        "issued_at": (start - timedelta(hours=1)).isoformat(),
    }
    row = {"market_publications": [pub]}
    _settle_projection_publications(row, match, datetime.now(timezone.utc))
    result = pub["result"]
    assert result["status"] == "hit"
    assert result["correct"] is True
    assert round(result["profit_units"], 6) == 0.92


def test_legacy_most_aces_grading_unchanged():
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    match = MatchRecord(
        match_id="125", tour="atp", scheduled_at=start,
        player1_id="1", player1_name="Player A",
        player2_id="2", player2_name="Player B",
        winner_id="1", status="finished", best_of=3,
        stats={"p1_aces": 8, "p2_aces": 11},
    )
    pub = {"market": "aces", "section": "ace", "selection_id": "1",
           "price_status": "projection_only",
           "issued_at": (start - timedelta(hours=1)).isoformat()}
    _settle_projection_publications({"market_publications": [pub]}, match,
                                    datetime.now(timezone.utc))
    assert pub["result"]["status"] == "miss"
    assert "profit_units" not in pub["result"]
