"""No real API calls: full-board PropLine audit must cover unmatched fixtures safely."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from propline_full_board_audit import complete_market_pairs, scan_board

NOW = datetime(2026, 9, 26, 9, 0, tzinfo=timezone.utc)
TOMORROW = (NOW + timedelta(hours=20)).isoformat()


def test_same_book_exact_player_and_line_required():
    first = {"key": "player_aces", "outcomes": [
        {"name": "Over", "description": "Jane Doe", "point": 4.5, "price": -110},
        {"name": "Under", "description": "Other Player", "point": 4.5, "price": -110},
        {"name": "Under", "description": "Jane Doe", "point": 5.5, "price": -110},
    ]}
    assert complete_market_pairs({"markets": [first]}, {"player_aces"}) == {}
    first["outcomes"].append(
        {"name": "Under", "description": "Jane Doe", "point": 4.5, "price": 125}
    )
    result = complete_market_pairs({"markets": [first]}, {"player_aces"})
    assert result["player_aces"][0]["player"] == "jane doe"
    assert abs(result["player_aces"][0]["over"] - 1.909091) < .00001
    assert result["player_aces"][0]["under"] == 2.25


class FakeClient:
    def __init__(self, remaining=700, cap=400):
        self.calls = 0
        self.remaining = remaining
        self.min_remaining = 150
        self.max_calls = cap

    def get(self, path, params=None):
        self.calls += 1
        self.remaining -= 1
        if path.endswith("/events"):
            return [
                {"id": "21", "home_team": "A", "away_team": "B",
                 "commence_time": TOMORROW},
                {"id": "22", "home_team": "C", "away_team": "D",
                 "commence_time": TOMORROW},
                {"id": "23", "home_team": "E", "away_team": "F",
                 "commence_time": TOMORROW},
            ]
        if path.endswith("/21/markets"):
            return [{"key": "total_sets"}, {"key": "player_aces"}]
        if path.endswith("/22/markets"):
            return [{"key": "h2h"}]
        if path.endswith("/23/markets"):
            return [{"key": "player_double_faults"}]
        if path.endswith("/21/odds"):
            return {"bookmakers": [{"key": "Bookie", "markets": [
                {"key": "total_sets", "outcomes": [
                    {"name": "Over", "point": 2.5, "price": 140},
                    {"name": "Under", "point": 2.5, "price": -150},
                ]},
                {"key": "player_aces", "outcomes": [
                    {"name": "Over", "description": "A", "point": 4.5, "price": 120},
                    {"name": "Under", "description": "A", "point": 4.5, "price": -120},
                ]},
            ]}]}
        if path.endswith("/23/odds"):
            # Listed prop does NOT mean priced: only one quoted side.
            return {"bookmakers": [{"key": "Bookie", "markets": [
                {"key": "player_double_faults", "outcomes": [
                    {"name": "Over", "description": "E", "point": 2.5, "price": 150},
                ]},
            ]}]}
        raise AssertionError(path)


def test_all_board_includes_fixtures_not_in_current_blinq_feed():
    client = FakeClient()
    predictions = [{"event_id": "rapid-a", "scheduled_at": TOMORROW,
                    "player1": {"name": "A"}, "player2": {"name": "B"}}]
    report = scan_board(client, now=NOW, known_predictions=predictions)
    assert report["eligible_future"] == report["events_on_board"] == 3
    assert report["matched_blinq"] == 1
    assert report["events_queried"] == 3
    assert report["matched_vs_unmatched"] == {
        "matched_blinq": 1, "not_matched_blinq": 2
    }
    assert report["events_without_target_market"] == 1
    assert report["listed"] == {
        "aces": 1, "double_faults": 1, "games": 0, "sets": 1
    }
    assert report["priced"] == {
        "aces": 1, "double_faults": 0, "games": 0, "sets": 1
    }
    assert report["api_calls"] == client.calls == 6
    assert report["provider_remaining"] == 694
    assert report["errors"] == 0


def test_quota_reserve_stops_before_extra_match():
    client = FakeClient(remaining=152)
    result = scan_board(client, now=NOW, known_predictions=[])
    assert result["stopped"] == "provider_quota_reserve"
    assert result["provider_remaining"] >= 150
    assert result["events_queried"] <= 1
    assert result["errors"] == 0
