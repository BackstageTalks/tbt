"""Date provenance must not turn a tournament start into a match-day claim."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.cdb_inbox_adapter import normalize
from scripts.cdb_inbox_stage import _strict_source_evidence
from scripts.link_offline_serve_return import OfflineMatch, _candidate_score, _sackmann_rows


def candidate(day: int, *, tournament="Vienna", round_name="QF", surface="hard"):
    return SimpleNamespace(
        tour="atp", scheduled_at=datetime(2026, 10, day, 12, tzinfo=timezone.utc),
        player1_id="c1", player2_id="c2",
        player1_name="Alpha One", player2_name="Beta Two",
        winner_id="c1", tournament=tournament, round_name=round_name,
        surface=surface, best_of=3,
    )


def source(*, day=17, kind="tournament_start", tournament="Vienna",
           round_name="QF", surface="hard", best_of=3):
    return OfflineMatch(
        source="sackmann:atp_native_2026.csv", source_match_id="raw:1",
        tour="atp", event_date=date(2026, 10, day),
        player_a="Alpha One", player_b="Beta Two", winner="Alpha One",
        tournament=tournament, round_name=round_name, surface=surface,
        best_of=best_of, stats_a={"aces": 5.0}, stats_b={"aces": 2.0},
        source_player_a_id="100", source_player_b_id="200",
        source_id_namespace="sackmann", source_date_kind=kind,
    )


@pytest.mark.parametrize("delta", [0, 1, 5, 16])
def test_tournament_start_never_claims_exact_match_day(delta):
    score, evidence, accepted = _candidate_score(source(day=17), candidate(17 + delta)
        if delta <= 14 else SimpleNamespace(**{
            **vars(candidate(17)), "scheduled_at": datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        }))
    assert score >= 8
    assert accepted
    assert "date_tournament_window" in evidence
    assert "date_exact" not in evidence
    assert _strict_source_evidence({"evidence": evidence})


@pytest.mark.parametrize(("changed", "value"), [
    ("tournament", "Different City"),
    ("round_name", "SF"),
    ("surface", "clay"),
    ("best_of", None),
])
def test_start_window_needs_all_independent_discriminators(changed, value):
    overrides = {changed: value}
    item = source(day=16, **overrides)
    _, evidence, accepted = _candidate_score(item, candidate(17))
    assert not (accepted and _strict_source_evidence({"evidence": evidence}))


def test_exact_date_remains_exact_only_from_provenance():
    _, evidence, accepted = _candidate_score(source(day=17, kind="match_exact"), candidate(17))
    assert accepted
    assert "date_exact" in evidence
    assert "date_tournament_window" not in evidence
    _, evidence, _ = _candidate_score(source(day=16, kind="match_exact"), candidate(17))
    assert "date_plusminus_1" in evidence
    assert not _strict_source_evidence({"evidence": evidence})


def test_negative_tournament_window_rejected():
    _, evidence, accepted = _candidate_score(source(day=18), candidate(17))
    assert not accepted
    assert evidence == ["date_mismatch"]


def test_source_cannot_spoof_date_kind_via_csv_metadata():
    base = dict(
        league="atp", tourney_date="20261016", tourney_name="Vienna",
        winner_name="Alpha One", loser_name="Beta Two",
        surface="hard", round="QF", best_of="3", w_ace="5",
        source_date_kind="match_exact",
    )
    normalized, error = normalize(base, "atp_test.csv", 1)
    assert not error
    assert normalized["source_date_kind"] == "tournament_start"
    precise, error = normalize(dict(base, match_date="2026-10-17"), "atp_test.csv", 1)
    assert not error
    assert precise["source_date_kind"] == "match_exact"
    assert precise["tourney_date"] == "20261017"


def test_native_sackmann_day_is_only_tournament_start(tmp_path):
    path = tmp_path / "atp_matches_2026.csv"
    row = dict(
        league="atp", tourney_date="20261017", tourney_name="Vienna",
        winner_name="Alpha One", loser_name="Beta Two",
        surface="Hard", round="QF", best_of="3", w_ace="5",
        winner_id="100", loser_id="200", source_date_kind="match_exact",
    )
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    item, = list(_sackmann_rows([str(path)]))
    assert item.source_date_kind == "tournament_start"
    assert item.source_id_namespace == "sackmann"
