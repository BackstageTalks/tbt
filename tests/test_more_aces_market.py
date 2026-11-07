"""Regression coverage for the independent VIAC ES market."""
from datetime import datetime, timedelta, timezone

from tbt.schemas import MatchRecord
from tbt.services.ace_selection import select_ace_winner_picks
from tbt.services.match_status import _grade_runtime_projection
from tbt.services.admin_storage import resolve_ui_access_config, validate_ui_config


def _historical(mid, when, p1, p2, a1, a2):
    return MatchRecord(
        match_id=mid, tour="atp", scheduled_at=when,
        player1_id=p1, player1_name=p1, player2_id=p2,
        player2_name=p2, winner_id=p1, status="finished",
        surface="hard", tournament="History",
        stats={"p1_aces": a1, "p2_aces": a2,
               "p1_double_faults": 1, "p2_double_faults": 2},
    )


def test_independent_most_aces_is_not_bookmaker_player_total():
    now = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)
    history = []
    for i in range(12):
        when = now - timedelta(days=20 + i * 7)
        history.append(_historical(f"a{i}", when, "A", f"X{i}", 11, 2))
        history.append(_historical(f"b{i}", when, "B", f"Y{i}", 2, 11))
    fixture = {
        "id": "future", "event_id": "999",
        "scheduled_at": (now + timedelta(hours=4)).isoformat(),
        "tour": "ATP", "surface": "hard",
        "player1": {"id": "A", "name": "Alpha"},
        "player2": {"id": "B", "name": "Beta"},
    }
    picks, report = select_ace_winner_picks(history, [fixture], now=now)
    assert report["most_aces_selected"] == 1
    assert len(picks) == 1
    pick = picks[0]
    assert pick["market"] == "most_aces"
    assert pick["price_contract"] == "player_superiority"
    assert pick["selection_id"] == "A"
    assert pick["projection"] > pick["opponent_projection"]
    assert pick["odds"] is None and pick["probability"] is None


def _grade(first, second, *, include_opponent=True):
    row = {
        "scheduled_at": "2026-11-08T16:00:00+00:00",
        "event_id": "event1",
        "player1": {"id": "A", "name": "Alpha"},
        "player2": {"id": "B", "name": "Beta"},
    }
    publication = {
        "section": "ace_winner", "market": "most_aces",
        "issued_at": "2026-11-08T10:00:00+00:00",
        "selection_id": "A", "selection": "Alpha",
        "price_contract": "player_superiority",
        "price_status": "projection_only", "odds": None,
        "projection": 8, "opponent_projection": 5,
    }
    stats = {"p1_aces": first}
    if include_opponent:
        stats["p2_aces"] = second
    status = {
        "status": "win", "provider_home_id": "A", "provider_away_id": "B",
        "projection_stats_p1_id": "A", "projection_stats_p2_id": "B",
        "projection_stats": stats,
    }
    return _grade_runtime_projection(row, publication, status)


def test_most_aces_success_loss_tie_and_missing_opponent():
    hit, miss, draw = _grade(8, 5), _grade(4, 9), _grade(6, 6)
    assert hit["result"]["status"] == "hit"
    assert miss["result"]["status"] == "miss"
    assert draw["result"]["status"] == "void"
    assert draw["result"]["correct"] is None
    assert hit["result"]["opponent_actual_count"] == 5
    assert "profit_units" not in hit["result"]
    assert _grade(8, 5, include_opponent=False) is None


def test_ui_config_includes_regular_most_aces_tab_and_stats_control():
    config = resolve_ui_access_config(None)
    tabs = config["dashboard"]["daily_hub"]["tabs"]
    assert "ace_winner" in tabs
    assert tabs["ace_winner"]["enabled"] is True
    assert tabs["ace_winner"]["plans"]["elite"]["visible_rows"] == "ALL"
    assert tabs["ace_winner"]["plans"]["rookie"]["visible_rows"] == 0
    assert validate_ui_config(config)
