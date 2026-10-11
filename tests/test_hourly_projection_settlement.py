"""Regression: same-day projection settlement, exact evidence and archive readback."""
from copy import deepcopy
from datetime import datetime, timezone

from tbt.services.match_status import (
    _verified_final_score_stats, prediction_rows, runtime_settled_results,
    scan_match_statuses,
)
from tbt.services import results_archive
from tbt.services.results_archive import settled_archive_candidates, save_settled_results_archive, load_settled_results_archive
from test_results_archive_runtime import Table

DAY = "2026-10-11T10:00:00+00:00"
ISSUED = "2026-10-11T04:15:00+00:00"
NOW = datetime(2026, 10, 11, 14, tzinfo=timezone.utc)


def _base():
    return {
        "event_id": "100", "scheduled_at": DAY, "winner_id": "11",
        "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
        "best_of": 3,
    }


def _pub(market, selection="11", **extra):
    section = {"aces":"ace", "double_faults":"double_faults", "sets":"sets", "games":"games"}[market]
    return {
        "market": market, "section": section, "selection_id": selection,
        "publication_key": f"{section}:projection:{market}:{selection}",
        "projection_scope": "player" if market in {"aces","double_faults"} else "match_total",
        "projection_metric": market,
        "price_status": "projection_only", "issued_at": ISSUED,
        "publication_status": "published", "result": None,
        **extra,
    }


def _status(**extra):
    return {"100": {
        "status": "win", "winner_id": "11",
        "provider_status": "finished ended",
        "provider_home_id": "11",
        "provider_away_id": "22",
        "projection_stats_p1_id": "11",
        "projection_stats_p2_id": "22",
        "checked_at": "2026-10-11T12:00:00Z",
        **extra,
    }}


def _event():
    return {
        "id": "100", "winnerCode": 1,
        "status": {"type": "finished", "description": "Ended"},
        "homeTeam": {"id":"11"}, "awayTeam": {"id":"22"},
        "homeScore": {"period1": 6, "period2": 4, "period3": 6},
        "awayScore": {"period1": 3, "period2": 6, "period3": 2},
    }


def test_full_verified_final_score_only():
    base = _base()
    result = _verified_final_score_stats(base, _event())
    assert result == {"total_sets": 3, "total_games": 27}
    incomplete = _event()
    incomplete["awayScore"].pop("period3")
    assert _verified_final_score_stats(base, incomplete) == {}
    interrupted = _event()
    interrupted["homeScore"]["period2"] = 5
    assert _verified_final_score_stats(base, interrupted) == {}
    gap = _event()
    gap["homeScore"].pop("period2")
    gap["awayScore"].pop("period2")
    assert _verified_final_score_stats(base, gap) == {}


def test_projection_only_published_rows_enter_daily_worker_without_fake_results():
    row = _base()
    row["market"] = "sets"
    row["selection_id"] = "sets:over:2.5"
    row["market_publications"] = [_pub("sets", "sets:over:2.5")]
    feed = {"top_daily_picks": [], "prime_picks": [], "sg_picks": [row]}
    assert set(prediction_rows(feed, now=NOW)) == {"100"}

    class Provider:
        request_count = 0
        def live_events(self):
            return []
        def previous_player_matches(self, player_id, page=0):
            return {"events": [_event()]}

    snapshot = scan_match_statuses(feed, Provider(), now=NOW)
    assert snapshot["statuses"]["100"]["projection_stats"] == {"total_sets": 3, "total_games": 27}
    settled = runtime_settled_results({**feed, "results":[]}, snapshot["statuses"])
    assert len(settled) == 1
    assert settled[0]["market_publications"][0]["result"]["status"] == "hit"
    assert "profit_units" not in settled[0]["market_publications"][0]["result"]


def test_all_projection_categories_grade_only_from_verified_evidence():
    base = _base()
    ace = {**base, "market_publications":[
        _pub("aces", price_contract="player_superiority", odds=None),
        _pub("double_faults", price_contract="player_superiority", odds=None),
    ]}
    sg = {**base, "market_publications":[
        _pub("sets", "sets:over:2.5"),
        _pub("games", "games:high", reference_projection=24, projection_direction="high"),
    ]}
    feed = {"ace_picks":[ace], "sg_picks":[sg], "results":[]}
    evidence = {"total_sets":3, "total_games":27,
                "p1_aces":7.0, "p2_aces":4.0,
                "p1_double_faults":1.0, "p2_double_faults":3.0}
    outcomes = runtime_settled_results(feed, _status(projection_stats=evidence))
    found = {p["market"]:p["result"] for row in outcomes for p in row["market_publications"]}
    assert set(found) == {"aces","double_faults","sets","games"}
    assert [found[x]["status"] for x in ("aces","double_faults","sets","games")] == ["hit","miss","hit","hit"]
    assert all("profit_units" not in result for result in found.values())


def test_missing_statistic_never_becomes_loss():
    base = _base()
    feed = {"ace_picks":[{**base,"market_publications":[_pub("aces")]}], "results":[]}
    assert runtime_settled_results(feed, _status(projection_stats={"p1_aces": 7})) == []
    assert runtime_settled_results(feed, _status()) == []


def test_priced_player_over_under_uses_frozen_line_and_real_odds():
    base = _base()
    p = _pub("aces", price_contract="player_total_ou", ou_side="over",
             market_line=4.5, price_status="priced_projection", odds=1.85)
    rows = runtime_settled_results(
        {"ace_picks":[{**base,"market_publications":[p]}], "results":[]},
        _status(projection_stats={"p1_aces":6.0, "p2_aces":1.0}))
    result = rows[0]["market_publications"][0]["result"]
    assert result["correct"] is True
    assert result["staked_units"] == 1
    assert abs(result["profit_units"] - .85) < 1e-12


def test_retirement_void_and_late_unissued_are_excluded_from_false_bets():
    base = _base()
    p = _pub("sets", "sets:over:2.5")
    feed = {"sg_picks":[{**base,"market_publications":[p]}], "results":[]}
    rows = runtime_settled_results(feed, _status(status="retired", projection_stats={}))
    assert rows[0]["market_publications"][0]["result"]["void"] is True
    assert rows[0]["market_publications"][0]["result"]["staked_units"] == 0.0
    late = deepcopy(feed)
    late["sg_picks"][0]["market_publications"][0]["issued_at"] = "2026-10-11T11:00:00Z"
    assert settled_archive_candidates(late, _status(projection_stats={"total_sets":3})) == []
    unissued = deepcopy(feed)
    unissued["sg_picks"][0]["market_publications"][0]["issued_at"] = None
    assert runtime_settled_results(unissued, _status(projection_stats={"total_sets":3})) == []


def test_projection_archive_readback_rollover_and_exact_ou_contract(monkeypatch):
    table = Table()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    base = _base()
    over = _pub("aces", price_contract="player_total_ou", ou_side="over",
                market_line=4.5, price_status="priced_projection", odds=1.85,
                publication_key="ace:event100:over4.5")
    under = _pub("aces", price_contract="player_total_ou", ou_side="under",
                 market_line=7.5, price_status="priced_projection", odds=1.70,
                 publication_key="ace:event100:under7.5")
    feed = {"generated_at":ISSUED, "ace_picks":[{**base,"market_publications":[over,under]}], "results":[]}
    statuses = _status(projection_stats={"p1_aces":6,"p2_aces":1})
    candidates = settled_archive_candidates(feed, statuses)
    assert len(candidates) == 2
    assert {c["market_publications"][0]["market_line"] for c in candidates} == {4.5, 7.5}
    assert save_settled_results_archive(candidates)["added"] == 2
    assert save_settled_results_archive(candidates)["added"] == 0
    restored = load_settled_results_archive()
    assert len(restored) == 2
    next_day = results_archive.merge_settled_results({"results":[]}, restored)
    assert len(next_day["results"]) == 2
    assert {r["market_publications"][0]["result"]["correct"] for r in restored} == {True}


def test_no_projection_from_winner_status_alone():
    base = _base()
    feed = {"ace_picks":[{**base,"market_publications":[_pub("aces")]}], "results":[]}
    assert runtime_settled_results(feed, _status()) == []
