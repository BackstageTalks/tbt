from datetime import datetime, timedelta, timezone

from tbt.schemas import MatchRecord
from tbt.services.market_selection import select_market_sections
from tbt.services.sg_selection import select_sg_picks


def historical(match_id, when, p1, p2, total_sets, total_games, *, surface="hard", best_of=3):
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
        best_of=best_of,
        tournament="History",
        stats={"total_sets": total_sets, "total_games": total_games},
    )


def prediction(when, *, best_of=3):
    return {
        "id": "future", "event_id": "999", "scheduled_at": when.isoformat(),
        "tour": "ATP", "tournament": "Future Open", "surface": "hard",
        "best_of": best_of,
        "player1": {"id": "A", "name": "Alpha", "probability": .52},
        "player2": {"id": "B", "name": "Beta", "probability": .48},
        "winner_id": "A", "confidence": .52, "data_depth": .8,
    }


def test_sg_projection_publishes_sets_and_games_when_history_signal_is_deep():
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = []
    # A/B are long-match / high-games players, while the tour baseline is kept
    # lower by a broad background sample.
    for i in range(12):
        when = now - timedelta(days=20 + i * 8)
        rows.append(historical(f"a{i}", when, "A", f"X{i}", 3, 31))
        rows.append(historical(f"b{i}", when, "B", f"Y{i}", 3, 30))
    for i in range(60):
        when = now - timedelta(days=30 + i * 3)
        rows.append(historical(f"base{i}", when, f"C{i}", f"D{i}", 2, 20))

    cards, report = select_sg_picks(rows, [prediction(now + timedelta(hours=5))], now=now)
    assert {card["market"] for card in cards} == {"sets", "games"}
    sets = next(card for card in cards if card["market"] == "sets")
    games = next(card for card in cards if card["market"] == "games")
    assert sets["pick"] == "Over 2.5 Sets"
    assert sets["projection_unit"] == "probability"
    assert sets["projection"] >= .60
    assert games["pick"] == "High Total Games"
    assert games["projection_unit"] == "games"
    assert games["projection"] > games["reference_projection"]
    assert report["projection_only"] is True
    assert report["settlement_enabled"] is False


def test_same_utc_day_score_is_excluded():
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = []
    for i in range(8):
        when = now - timedelta(days=10 + i * 8)
        rows.append(historical(f"a{i}", when, "A", f"X{i}", 3, 30))
        rows.append(historical(f"b{i}", when, "B", f"Y{i}", 3, 30))
    for i in range(40):
        rows.append(historical(f"base{i}", now - timedelta(days=20 + i * 4), f"C{i}", f"D{i}", 2, 20))
    # Same-day short matches must not leak into the later upcoming projection.
    rows.append(historical("same-a", now.replace(hour=1), "A", "Z1", 2, 12))
    rows.append(historical("same-b", now.replace(hour=2), "B", "Z2", 2, 12))
    cards, report = select_sg_picks(rows, [prediction(now + timedelta(hours=5))], now=now)
    assert any(card["market"] == "sets" and card["pick"] == "Over 2.5 Sets" for card in cards)
    assert report["cutoff_utc"] == "2026-09-07T00:00:00+00:00"


def test_missing_best_of_does_not_invent_sets_games_market():
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    row = prediction(now + timedelta(hours=5), best_of=3)
    row.pop("best_of")
    cards, report = select_sg_picks([], [row], now=now)
    assert cards == []
    assert report["missing_best_of"] == 1


def test_market_sections_accept_sg_projection_cards_without_turning_them_into_bets():
    card = {"event_id": "x", "market": "games", "price_status": "projection_only", "projection": 24.1}
    sections = select_market_sections([], sg_picks=[card])
    assert sections["sg_picks"] == [card]
    assert "games_projection" in sections["market_selection"]["current_outputs"]
    assert "games_projection" in sections["market_selection"]["projection_only_outputs"]
    assert sections["market_selection"]["odds_backed_outputs"] == ["match_winner"]
    assert "games_odds" in sections["market_selection"]["pending_outputs"]
