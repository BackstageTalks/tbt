"""Line-first is isolated from the legacy local Aces fallback.

Synthetic fixtures verify identity, bookmaker ordering and fail-closed gates;
they are NOT historical calibration or claimed betting outcomes.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tbt.services.ace_selection import select_ace_picks
from tbt.services import projection_odds as po


def _history(now):
    result = []
    for i in range(10):
        when = now - timedelta(days=20 + i * 7)
        for player, opponent in (("A", f"X{i}"), ("B", f"Y{i}")):
            result.append(SimpleNamespace(
                scheduled_at=when, status="finished", tour="atp",
                player1_id=player, player2_id=opponent,
                stats={"p1_aces": 5, "p2_aces": 2,
                       "p1_double_faults": 1, "p2_double_faults": 1},
                surface="hard", best_of=3,
            ))
    return result


def _prediction(now):
    return {
        "event_id": "e", "scheduled_at": (now + timedelta(hours=5)).isoformat(),
        "tour": "ATP", "tournament": "ATP 250", "surface": "hard",
        "player1": {"id": "A", "name": "Alpha", "rank": 101},
        "player2": {"id": "B", "name": "Beta", "rank": 102},
    }


def _offer(name, line, over, under):
    return {"markets": [
        {"marketName": f"{name} Total Aces", "choiceName": side,
         "choiceGroup": str(line), "decimalOdds": odds}
        for side, odds in (("Over", over), ("Under", under))
    ]}


def test_line_first_projects_both_players_even_without_most_aces_gap():
    now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
    candidates, report = select_ace_picks(
        _history(now), [_prediction(now)], now=now, line_first_event_ids={"e"},
    )
    assert len(candidates) == 1
    row = candidates[0]
    assert row["selection_tier"] == "line_first"
    assert [p["id"] for p in row["line_first_players"]] == ["A", "B"]
    assert row["price_status"] == "projection_only"
    assert row["odds"] is None
    assert report["candidate_cards"] == 1


def test_line_first_absent_calibration_is_hard_stop(monkeypatch):
    monkeypatch.setattr(po, "_line_first_calibration", lambda: None)
    row = {**_prediction(datetime(2026, 11, 21, 12, tzinfo=timezone.utc)),
           "market": "aces", "selection_tier": "line_first",
           "line_first_players": [
               {"slot": 1, "id": "A", "name": "Alpha", "projection": 6},
               {"slot": 2, "id": "B", "name": "Beta", "projection": 7},
           ]}
    updated, ok, reason = po._attach_ace(
        row, _offer("Beta", 5.5, 1.85, 1.8), "2026-11-21T09:00:00Z", 2,
    )
    assert not ok and reason == "line_first_holdout_unverified"
    assert updated.get("price_status") != "priced_projection"


def test_line_first_picks_best_ev_across_players_lines_books(monkeypatch):
    # Stub calibration is test-only. The live gate requires a reviewed file
    # with >=150 qualified holdout samples per ATP and WTA.
    mock = {"tours": {"ATP": {
        "isotonic_points": [{"max_raw": 1.0, "calibrated": 0.8}],
    }}}
    monkeypatch.setattr(po, "_line_first_calibration", lambda: mock)
    row = {
        "event_id": "e", "tour": "ATP", "market": "aces",
        "selection_tier": "line_first", "price_status": "projection_only",
        "player1": {"id": "A", "name": "Alpha"},
        "player2": {"id": "B", "name": "Beta"},
        "line_first_players": [
            {"slot": 1, "id": "A", "name": "Alpha", "projection": 5.0},
            {"slot": 2, "id": "B", "name": "Beta", "projection": 5.0},
        ],
    }
    class NoRequests:
        def event_odds(self, *args, **kwargs):
            raise AssertionError("prefetch supplied; no paid calls allowed")

    alt = {
        "source": "propline", "bookmaker": "FirstBook",
        "provider_id": 2, "payload": _offer("Alpha", 4.5, 1.55, 1.2),
        "other_books": [{
            "source": "propline", "bookmaker": "SecondBook",
            "provider_id": 2, "payload": _offer("Beta", 6.5, 1.9, 1.7),
        }],
    }
    aces, sg, summary = po.enrich_projection_odds(
        NoRequests(), [row], [], max_events=1,
        prefetched_payloads={"e": None},
        alternate_market_payloads={"e": {"aces": alt}},
    )
    assert not sg
    assert len(aces) == 1
    winner = aces[0]
    assert winner["selection_id"] == "B"
    assert winner["selection_tier"] == "line_first"
    assert winner["odds_bookmaker"] == "SecondBook"
    assert winner["price_contract"] == "player_total_ou"
    assert winner["market_line"] == 6.5
    assert winner["model_probability"] >= .60
    assert winner["expected_value"] >= 0
    assert summary["attached_by_provider"]["propline"] == 1
