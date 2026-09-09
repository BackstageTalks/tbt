from datetime import datetime, timedelta, timezone

from tbt.schemas import MatchRecord
from tbt.services.ace_selection import select_ace_picks
from tbt.services.market_selection import select_market_sections


def historical(match_id, when, p1, p2, a1, a2, d1, d2, surface="hard"):
    return MatchRecord(
        match_id=match_id,
        tour="atp",
        scheduled_at=when,
        player1_id=p1,
        player1_name=p1,
        player2_id=p2,
        player2_name=p2,
        winner_id=p1,
        status="finished",
        surface=surface,
        tournament="History",
        stats={
            "p1_aces": a1, "p2_aces": a2,
            "p1_double_faults": d1, "p2_double_faults": d2,
        },
    )


def prediction(when):
    return {
        "id": "future", "event_id": "999", "scheduled_at": when.isoformat(),
        "tour": "ATP", "tournament": "Future Open", "surface": "hard",
        "player1": {"id": "A", "name": "Alpha", "probability": .55},
        "player2": {"id": "B", "name": "Beta", "probability": .45},
        "winner_id": "A", "confidence": .55, "data_depth": .8,
    }


def test_ace_projection_uses_prior_history_and_publishes_both_market_types():
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = []
    for i in range(10):
        when = now - timedelta(days=20 + i * 8)
        rows.append(historical(f"a{i}", when, "A", f"X{i}", 9, 3, 1, 2))
        rows.append(historical(f"b{i}", when, "B", f"Y{i}", 3, 8, 4, 2))
    cards, report = select_ace_picks(rows, [prediction(now + timedelta(hours=5))], now=now)
    assert {card["market"] for card in cards} == {"aces", "double_faults"}
    ace = next(card for card in cards if card["market"] == "aces")
    df = next(card for card in cards if card["market"] == "double_faults")
    assert ace["selection_id"] == "A"
    assert df["selection_id"] == "B"
    assert ace["projection"] > ace["opponent_projection"]
    assert df["projection"] > df["opponent_projection"]
    assert ace["price_status"] == "projection_only"
    assert ace["odds"] is None and ace["probability"] is None
    assert report["odds_backed"] is False


def test_same_utc_day_statistics_are_excluded_from_projection():
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = []
    for i in range(8):
        when = now - timedelta(days=10 + i * 7)
        rows.append(historical(f"a{i}", when, "A", f"X{i}", 10, 2, 1, 2))
        rows.append(historical(f"b{i}", when, "B", f"Y{i}", 2, 9, 4, 2))
    # These extreme rows are scheduled earlier on the same UTC day and must not
    # influence another match because completion timestamps are unavailable.
    rows.append(historical("same-a", now.replace(hour=1), "A", "Z1", 0, 20, 12, 1))
    rows.append(historical("same-b", now.replace(hour=2), "B", "Z2", 20, 0, 0, 12))
    cards, report = select_ace_picks(rows, [prediction(now + timedelta(hours=5))], now=now)
    assert next(card for card in cards if card["market"] == "aces")["selection_id"] == "A"
    assert report["cutoff_utc"] == "2026-09-07T00:00:00+00:00"


def test_small_samples_do_not_create_fake_ace_picks():
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = [
        historical("a", now - timedelta(days=20), "A", "X", 12, 1, 1, 2),
        historical("b", now - timedelta(days=21), "B", "Y", 1, 12, 6, 1),
    ]
    cards, _ = select_ace_picks(rows, [prediction(now + timedelta(hours=5))], now=now)
    assert cards == []


def test_market_sections_accept_projection_cards_without_turning_them_into_bets():
    card = {"event_id": "x", "market": "aces", "price_status": "projection_only", "projection": 7.2}
    sections = select_market_sections([], ace_picks=[card])
    assert sections["ace_picks"] == [card]
    assert "aces_projection" in sections["market_selection"]["current_outputs"]
    assert "aces_odds" in sections["market_selection"]["pending_outputs"]
