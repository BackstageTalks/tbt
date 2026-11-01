"""Autonomous MoviOdds -> canonical history linker regression suite."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "scripts")]

from tbt.schemas import MatchRecord
from moviodds_cdb_format import _digest, format_cdb_archive
from moviodds_cdb_link import link_archive, _result_score


def source(*, home="Alex De Minaur", away="Carlos Alcaraz", league="ATP Paris",
           fixture="203859194", score="6-3,6-4", aces_home=4, kickoff="",
           parts=None):
    parts = [(6, 3), (6, 4)] if parts is None else parts
    payload = {
        "schema": 1, "source": "moviodds", "fixture_id": fixture,
        "home": home, "away": away, "league": league,
        "status": "finished", "kickoff_utc": kickoff,
        "finished_at": "2026-10-31T18:31:00+00:00",
        "observed_at": "2026-10-31T18:30:35+00:00",
        "final_score": score, "periods": [
            {"name": f"Set {n}", "score": f"{p[0]}-{p[1]}"}
            for n, p in enumerate(parts, 1)
        ],
        "stats": {
            "sport": "tennis", "format": "best_of_3", "surface": "Hard",
            "home": {"aces": aces_home, "double_faults": 2,
                     "first_serve_win_pct": 77, "break_point_conversion_pct": 40,
                     "sets": [x[0] for x in parts]},
            "away": {"aces": 7, "double_faults": 1,
                     "first_serve_win_pct": 69, "break_point_conversion_pct": 28,
                     "sets": [x[1] for x in parts]},
        },
    }
    return {"payload": payload, "sha256": _digest(payload)}


def canonical(*, winner="p1", name1="Alex De Minaur", name2="Carlos Alcaraz",
              tournament="Rolex Paris Masters", day="2026-10-31T16:30:00Z",
              surface="Hard", stats=None, tour="atp"):
    return MatchRecord(
        match_id="canonical-1", tour=tour,
        scheduled_at=datetime.fromisoformat(day.replace("Z", "+00:00")),
        player1_id="p1", player1_name=name1,
        player2_id="p2", player2_name=name2,
        surface=surface, tournament=tournament, winner_id=winner,
        status="completed", best_of=3, stats=stats or {},
    )


def batch(*rows):
    return format_cdb_archive({
        "schema": 1, "source": "moviodds", "verified": True,
        "days": ["2026-10-31"], "count": len(rows), "records": list(rows),
    })


def link(data, canon):
    return link_archive(data, canon, archive_sha256="a" * 64)


def test_unique_finished_exact_source_and_cdb_winner_to_import_stage():
    data = batch(source())
    ready, review, report = link(data, [canonical()])
    assert len(ready) == 1 and not review
    assert report["linked"] == 1 and report["new_values_candidates"] == 4
    assert report["actual_cdb_values_written"] == 0
    row = ready[0]
    assert row["import_ready"] is True
    assert row["canonical"]["winner_id"] == "p1"
    assert row["incoming_stats"] == {
        "p1_aces": 4.0, "p1_double_faults": 2.0,
        "p2_aces": 7.0, "p2_double_faults": 1.0,
    }
    assert row["provenance"][0]["source"] == "moviodds"
    assert row["provenance"][0]["score_independently_reproduced"] is False
    assert row["provenance"][0]["source_orientation"] == {"home": "p1", "away": "p2"}


def test_reversed_home_away_correctly_assigns_p1_p2():
    data = batch(source(home="Carlos Alcaraz", away="Alex De Minaur",
                        score="3-6,4-6",parts=[(3,6),(4,6)]))
    row = link(data, [canonical()])[0][0]
    assert row["incoming_stats"]["p2_aces"] == 4
    assert row["incoming_stats"]["p1_aces"] == 7
    assert row["provenance"][0]["source_orientation"] == {"home": "p2", "away": "p1"}


def test_changed_winner_quarantined():
    ready, review, report = link(batch(source()), [canonical(winner="p2")])
    assert not ready and review[0]["reason"] == "winner_conflict"


def test_ambiguous_second_canonical_match_blocks_both():
    a = canonical()
    b = canonical()
    b.match_id = "canonical-2"
    ready, review, report = link(batch(source()), [a,b])
    assert not ready and review[0]["reason"] == "ambiguous_identity"


def test_source_score_mismatch_set_vectors_rejected():
    a = source()
    a["payload"]["stats"]["home"]["sets"][1] = 7
    a["sha256"] = _digest(a["payload"])
    ready, review, report = link(batch(a), [canonical()])
    assert not ready and review[0]["reason"] == "source_set_score_not_verified"


def test_retirement_partial_set_does_not_get_imported():
    a = source(score="6-2,2-3", parts=[(6,2),(2,3)])
    ready, review, report = link(batch(a), [canonical()])
    assert not ready and review[0]["reason"] == "source_set_score_not_verified"


def test_missing_date_tournament_surface_or_player_is_not_guessed():
    for mod in [
        {"day": "2026-10-28T14:00:00Z"},
        {"tournament": "Basel"},
        {"surface": "Clay"},
        {"name1": "A. De Minaur"},
    ]:
        ready, review, report = link(batch(source()), [canonical(**mod)])
        assert not ready and review[0]["reason"] == "unmatched"


def test_prior_stat_conflict_quarantines_whole_row():
    ready, review, report = link(batch(source()), [canonical(stats={"p1_aces": 99})])
    assert not ready and review[0]["reason"] == "cdb_stat_conflict"


def test_equal_existing_stat_null_only_additions_staged():
    ready, review, report = link(batch(source()), [canonical(stats={"p1_aces": 4})])
    assert len(ready) == 1 and not review
    assert report["new_values_candidates"] == 3
    assert ready[0]["incoming_stats"]["p1_aces"] == 4


def test_doubles_and_other_tours_are_always_reviewed():
    results = batch(
        source(home="A/B", away="C/D"),
        source(fixture="203859195", league="UTR Pro Knoxville"),
    )
    ready, review, report = link(results, [canonical()])
    assert not ready and len(review)==2
    assert {r["reason"] for r in review} == {"doubles", "tour_unverified"}


def test_two_source_fixtures_cannot_link_one_cdb_id():
    data = batch(source(),source(fixture="203859195"))
    ready, review, report = link(data, [canonical()])
    assert not ready and len(review) == 2
    assert all(r["reason"] == "duplicate_canonical_id" for r in review)
    assert report["raw"] == 2 and report["rejected"] == 2


def test_fail_closed_tampered_candidate():
    data = batch(source())
    data["records"][0]["cdb_candidate"]["cdb_link"]["import_ready"] = True
    with pytest.raises(ValueError):
        link(data, [canonical()])


def test_preserve_no_write_when_no_canonical_history():
    ready, review, report = link(batch(source()), [])
    assert ready == []
    assert report["actual_cdb_values_written"] == 0
    assert review[0]["reason"] == "unmatched"
