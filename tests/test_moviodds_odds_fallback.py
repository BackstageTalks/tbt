"""Offline contracts for the read-only MoviOdds tennis fallback."""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from tbt.services.moviodds_live import discover_moviodds_fallback


NOW = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
T = NOW.isoformat()


def _quote(group, selection, price, *, side=None, label=None, line=None,
           handicap=None, suspended=False, sel_id=None):
    return {
        "group_id": group, "group_name": (
            "To Win Match" if group == "83" else
            "Alex De Minaur Total Aces/Double Faults" if group == "130321" else
            "Total Games in Match"
        ),
        "sel_id": sel_id or ("s-" + group + "-" + selection),
        "side": side, "label": label, "line": line, "handicap": handicap,
        "odds_dec": price, "suspended": suspended, "ts": T,
    }


def _data():
    p = {
        "event_id": "rapid-101", "scheduled_at": "2026-11-01T10:00:00Z",
        "player1": {"id": "11", "name": "Alex De Minaur"},
        "player2": {"id": "12", "name": "Carlos Alcaraz"},
    }
    fixture = {
        "id": "mov-55", "home": "Carlos Alcaraz", "away": "Alex De Minaur",
        "in_play": False, "kickoff_utc": "2026-11-01T10:00:00Z",
        "group_status": {
            "83": {"polled_at": T},
            "130321": {"polled_at": T},
            "130018": {"polled_at": T},
        },
        "quotes": [
            _quote("83", "p1", 2.6, label="Alex De Minaur"),
            _quote("83", "p2", 1.5, label="Carlos Alcaraz"),
            _quote("130321", "ace-over", 1.8, side="Over", line="Aces", handicap="3.5"),
            _quote("130321", "ace-under", 1.91, side="Under", line="Aces", handicap="3.5"),
            _quote("130018", "games-over", 1.95, side="Over", line="22.5"),
            _quote("130018", "games-under", 1.85, side="Under", line="22.5"),
        ]
    }
    return p, {"server_time": T, "matches": [fixture]}


def test_finds_exact_prematch_winner_aces_and_games():
    prediction, board = _data()
    found, report = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert report["requests"] == 0
    assert report["matched"] == 1
    assert set(found["rapid-101"]) == {"match_winner", "aces", "games"}
    assert found["rapid-101"]["aces"]["bookmaker"] == "bet365"
    assert found["rapid-101"]["aces"]["provider_id"] == 3
    choices = found["rapid-101"]["aces"]["payload"]["markets"][0]["choices"]
    assert {c["line"] for c in choices} == {3.5}
    assert {c["decimalOdds"] for c in choices} == {1.8, 1.91}


def test_never_overwrites_prior_sources():
    prediction, board = _data()
    found, report = discover_moviodds_fallback(
        [prediction], {"rapid-101": {"match_winner", "aces"}}, now=NOW, board=board
    )
    assert set(found["rapid-101"]) == {"games"}
    assert report["priced_by_market"]["aces"] == 0


def test_fails_closed_for_live_fixture_and_live_prices():
    prediction, board = _data()
    board["matches"][0]["in_play"] = True
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert found == {}
    board["matches"][0]["in_play"] = False
    board["matches"][0]["quotes"][0]["phase"] = "inplay"
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert "match_winner" not in found["rapid-101"]


def test_stale_market_and_suspended_side_are_unpriceable():
    prediction, board = _data()
    board["matches"][0]["group_status"]["130321"]["stale"] = True
    board["matches"][0]["quotes"][0]["suspended"] = True
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert set(found["rapid-101"]) == {"games"}
    board["matches"][0]["group_status"]["130018"]["polled_at"] = (
        NOW - timedelta(hours=2)).isoformat()
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert found == {}


def test_wrong_line_and_ace_ladder_never_create_ou():
    prediction, board = _data()
    quotes = board["matches"][0]["quotes"]
    quotes[3]["handicap"] = "4.5"
    quotes.append({
        "group_id": "130440", "group_name": "Ace Totals", "sel_id": "ladder",
        "side": "Alex De Minaur", "line": "5+", "odds_dec": 3.0,
    })
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert "aces" not in found["rapid-101"]


def test_ambiguous_or_weak_identity_never_matches():
    prediction, board = _data()
    twin = copy.deepcopy(board["matches"][0])
    twin["id"] = "mov-56"
    board["matches"].append(twin)
    found, report = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert found == {}
    assert report["ambiguous"] == 2
    board["matches"].pop()
    board["matches"][0]["home"] = "A. Alcaraz"
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert found == {}


def test_old_snapshot_and_wrong_kickoff_rejected():
    prediction, board = _data()
    board["server_time"] = (NOW - timedelta(minutes=3)).isoformat()
    found, report = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert found == {} and report["errors"] == 1
    board["server_time"] = T
    board["matches"][0]["kickoff_utc"] = (NOW + timedelta(hours=4)).isoformat()
    found, _ = discover_moviodds_fallback([prediction], {}, now=NOW, board=board)
    assert found == {}
