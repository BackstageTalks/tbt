"""Odds-first selection contracts: discover real offers before modeling."""
from datetime import datetime, timedelta, timezone

from tbt.services.projection_odds import (
    prefetch_projection_market_board, enrich_projection_odds,
)
from tbt.services.sg_selection import _games_card


NOW = datetime(2026, 9, 26, 8, tzinfo=timezone.utc)


def _prediction(event, hours=4):
    return {
        "event_id": event,
        "scheduled_at": (NOW + timedelta(hours=hours)).isoformat(),
        "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
        "tour": "ATP",
    }


def _payload():
    return {"markets": [
        {"marketName": "Total games won", "choiceName": "Over",
         "choiceGroup": "23.5", "decimalOdds": 1.86},
        {"marketName": "Total games won", "choiceName": "Under",
         "choiceGroup": "23.5", "decimalOdds": 1.95},
        {"marketName": "Total number of sets", "choiceName": "Over",
         "choiceGroup": "2.5", "decimalOdds": 2.12},
        {"marketName": "Total number of sets", "choiceName": "Under",
         "choiceGroup": "2.5", "decimalOdds": 1.70},
        {"marketName": "Most Aces", "choiceName": "Alpha",
         "decimalOdds": 1.68},
        {"marketName": "Most Aces", "choiceName": "Beta",
         "decimalOdds": 2.04},
        {"marketName": "Most Double Faults", "choiceName": "Alpha",
         "decimalOdds": 1.88},
        {"marketName": "Most Double Faults", "choiceName": "Beta",
         "decimalOdds": 1.89},
    ]}


def test_board_discovers_all_four_complete_markets_and_reuses_requests():
    class Provider:
        def __init__(self):
            self.calls = []
        def event_odds(self, event_id, provider_id=1):
            self.calls.append((event_id, provider_id))
            return _payload() if event_id == "100" else {"markets": [
                {"marketName": "Total games won", "choiceName": "Over",
                 "choiceGroup": "23.5", "decimalOdds": 1.8}
            ]}
    provider = Provider()
    future = [_prediction("101", 6), _prediction("100", 3), _prediction("102", -1)]
    cache, eligible, report = prefetch_projection_market_board(
        provider, future, now=NOW, max_events=2
    )
    assert provider.calls == [("100", 1), ("101", 1)]
    assert eligible == {"100": {"aces", "double_faults", "games", "sets"}}
    assert report["events_requested"] == 2
    assert report["complete_markets_by_type"]["games"] == 1

    aces = [{
        "event_id": "100", "market": "aces",
        "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
        "selection_id": "11",
    }]
    sg = [{
        "event_id": "100", "market": "games",
        "projection": 26.0, "reference_projection": 23.5,
        "market_line": 23.5, "projection_direction": "high",
        "selection_id": "games:high",
    }]
    ace_out, sg_out, diagnostics = enrich_projection_odds(
        provider, aces, sg, max_events=2, prefetched_payloads=cache,
    )
    assert provider.calls == [("100", 1), ("101", 1)]
    assert ace_out[0]["odds"] == 1.68
    assert sg_out[0]["odds"] == 1.86
    assert sg_out[0]["market_line"] == 23.5
    assert diagnostics["priced_cards"]["games"] == 1


def test_offered_games_line_is_probability_reference_not_historical_baseline():
    row = _prediction("100")
    p1 = {"estimate": 26.0, "variance": 7.0, "samples": 30, "surface_samples": 10}
    p2 = {"estimate": 27.0, "variance": 8.0, "samples": 30, "surface_samples": 10}
    card = _games_card(row, p1, p2, best_of=3, baseline=22.0, bookmaker_line=23.5)
    assert card is not None
    assert card["reference_projection"] == 23.5
    assert card["market_line"] == 23.5
    assert card["baseline_projection"] == 22.0
    assert card["selection_id"] == "games:high"
    assert card["odds"] is None


def test_small_market_difference_is_not_falsely_called_confident_bet():
    row = _prediction("100")
    p1 = {"estimate": 23.7, "variance": 6, "samples": 30, "surface_samples": 10}
    p2 = {"estimate": 23.7, "variance": 6, "samples": 30, "surface_samples": 10}
    assert _games_card(row, p1, p2, best_of=3, baseline=21.5,
                       bookmaker_line=23.5) is None


def test_unknown_market_or_no_budget_does_not_call_provider():
    class Provider:
        def event_odds(self, event_id, provider_id=1):
            raise AssertionError("No calls expected")
    cache, markets, report = prefetch_projection_market_board(
        Provider(), [_prediction("101")], now=NOW, max_events=0
    )
    assert cache == markets == {}
    assert report["events_requested"] == 0
