import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from propline_clv_report import evaluate


def _snapshot(captured, price, *, priority=True):
    return {
        "api_calls": 1,
        "events": [{
            "event_id": "evt",
            "commence_time": "2026-09-30T14:00:00+00:00",
            "captured_at": captured,
            "blinq_priority": priority,
            "bookmakers": [{
                "key": "book",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [{
                        "name": "Player A",
                        "description": "",
                        "point": None,
                        "price": price,
                    }],
                }],
            }],
        }],
    }


def test_report_separates_blinq_priority_movement():
    snapshots = [
        _snapshot("2026-09-30T10:00:00+00:00", 2.00),
        _snapshot("2026-09-30T13:00:00+00:00", 1.80),
    ]
    report = evaluate(snapshots)
    assert report["blinq_priority_events"] == 1
    assert report["comparable_series"] == 1
    assert report["blinq_comparable_series"] == 1
    assert report["blinq_by_market"]["h2h"]["comparable_selections"] == 1
    assert report["blinq_examples"][0]["blinq_priority"] is True
    assert report["blinq_examples"][0]["observed_clv_percent"] > 0


def _player_market_snapshot(captured, market, player, point, price, *,
                            book="book", outcome="Over"):
    return {
        "api_calls": 0,
        "events": [{
            "event_id": "evt",
            "commence_time": "2026-09-30T14:00:00+00:00",
            "captured_at": captured,
            "blinq_priority": True,
            "bookmakers": [{"key": book, "markets": [{
                "key": market,
                "outcomes": [{
                    "name": outcome,
                    "description": player,
                    "point": point,
                    "price": price,
                }],
            }]}],
        }],
    }


def test_report_tracks_specific_aces_and_double_faults_clv_without_new_calls():
    snapshots = []
    for market in ("player_aces", "player_double_faults"):
        snapshots.append(_player_market_snapshot(
            "2026-09-30T10:00:00+00:00", market, "Player A", 4.5, -110))
        snapshots.append(_player_market_snapshot(
            "2026-09-30T13:30:00+00:00", market, "Player A", 4.5, -135))
    result = evaluate(snapshots)
    assert result["comparable_series"] == 2
    assert result["archived_api_calls"] == 0
    assert result["by_market"]["player_aces"]["comparable_selections"] == 1
    assert result["by_market"]["player_double_faults"]["comparable_selections"] == 1


def test_report_never_merges_different_player_line_or_book_for_clv():
    first = _player_market_snapshot(
        "2026-09-30T10:00:00+00:00", "player_aces", "Player A", 3.5, -110)
    different = [
        _player_market_snapshot(
            "2026-09-30T13:30:00+00:00", "player_aces", "Player A", 4.5, -135),
        _player_market_snapshot(
            "2026-09-30T13:30:00+00:00", "player_aces", "Player B", 3.5, -135),
        _player_market_snapshot(
            "2026-09-30T13:30:00+00:00", "player_aces", "Player A", 3.5, -135,
            book="different-book"),
    ]
    assert evaluate([first, *different])["comparable_series"] == 0


def test_report_tracks_break_points_and_games_won_only_for_exact_lines():
    snapshots = []
    for market in ("player_break_points_won", "player_games_won", "total_aces"):
        snapshots.append(_player_market_snapshot(
            "2026-09-30T10:00:00+00:00", market, "Player A", 2.5, 1.9))
        snapshots.append(_player_market_snapshot(
            "2026-09-30T13:30:00+00:00", market, "Player A", 2.5, 1.8))
    data = evaluate(snapshots)
    assert data["comparable_series"] == 3
    assert set(data["by_market"]) == {
        "player_break_points_won", "player_games_won", "total_aces"
    }
