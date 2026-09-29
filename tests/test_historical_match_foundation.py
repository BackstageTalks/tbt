from datetime import datetime, timezone

from import_historical_match_foundation import (
    SourceRow,
    _crosswalk,
    _historical_player_id,
    _stats,
)
from tbt.schemas import MatchRecord


def _source(year=2021):
    return SourceRow(
        tour="atp",
        source_type="main",
        source_file=f"atp_matches_{year}.csv",
        source_row=2,
        scheduled_at=datetime(year, 1, 4, 12, tzinfo=timezone.utc),
        tourney_id=f"{year}-001",
        tournament="Example Open",
        level="atp tour",
        surface="hard",
        match_num="1",
        round_name="r32",
        best_of=3,
        winner_source_id="1001",
        winner_name="Alpha One",
        loser_source_id="1002",
        loser_name="Beta Two",
        winner_rank=10,
        loser_rank=20,
        stats={},
    )


def test_stats_are_same_match_observations_with_valid_return_rates():
    row = {
        "w_ace": "5",
        "w_df": "2",
        "w_svpt": "60",
        "w_1stIn": "36",
        "w_1stWon": "27",
        "w_2ndWon": "12",
        "l_ace": "3",
        "l_df": "4",
        "l_svpt": "70",
        "l_1stIn": "42",
        "l_1stWon": "25",
        "l_2ndWon": "10",
    }
    out = _stats(row)
    assert out["p1_aces"] == 5.0
    assert out["p2_double_faults"] == 4.0
    assert out["p1_first_serve_win"] == 27 / 36
    assert out["p1_second_serve_win"] == 12 / 24
    assert out["p1_service_points_won"] == 39 / 60
    assert out["p1_return_points_won"] == 1 - (35 / 70)
    assert out["p2_return_points_won"] == 1 - (39 / 60)


def test_crosswalk_requires_overlap_match_evidence():
    canonical = MatchRecord(
        match_id="canon-1",
        tour="atp",
        scheduled_at=datetime(2021, 1, 7, 18, tzinfo=timezone.utc),
        player1_id="provider-a",
        player1_name="Alpha One",
        player2_id="provider-b",
        player2_name="Beta Two",
        surface="hard",
        tournament="Example Open",
        round_name="R32",
        winner_id="provider-a",
        status="completed",
    )
    counts = __import__("collections").Counter()
    mapping, evidence = _crosswalk([_source()], [canonical], counts)
    assert mapping[("atp", "1001")] == "provider-a"
    assert mapping[("atp", "1002")] == "provider-b"
    assert len(evidence) == 1
    assert counts["crosswalk_players_proven"] == 2


def test_conflicting_crosswalk_mapping_fails_closed():
    one = MatchRecord(
        match_id="canon-1",
        tour="atp",
        scheduled_at=datetime(2021, 1, 7, 18, tzinfo=timezone.utc),
        player1_id="provider-a",
        player1_name="Alpha One",
        player2_id="provider-b",
        player2_name="Beta Two",
        tournament="Example Open",
        round_name="R32",
        winner_id="provider-a",
        status="completed",
    )
    source2 = SourceRow(
        **{
            **_source().__dict__,
            "source_row": 3,
            "match_num": "2",
            "tournament": "Second Open",
        }
    )
    two = MatchRecord(
        match_id="canon-2",
        tour="atp",
        scheduled_at=datetime(2021, 1, 8, 18, tzinfo=timezone.utc),
        player1_id="provider-x",
        player1_name="Alpha One",
        player2_id="provider-b",
        player2_name="Beta Two",
        tournament="Second Open",
        round_name="R32",
        winner_id="provider-x",
        status="completed",
    )
    counts = __import__("collections").Counter()
    mapping, _ = _crosswalk([_source(), source2], [one, two], counts)
    assert ("atp", "1001") not in mapping
    assert mapping[("atp", "1002")] == "provider-b"
    assert counts["crosswalk_player_conflicts"] == 1


def test_unproven_player_id_is_source_scoped():
    assert _historical_player_id("wta", "200033", {}) == "hist-js:wta:200033"
