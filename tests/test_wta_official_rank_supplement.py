from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tbt.data.wta_rank_history import WTARankHistory


def _write_sources(tmp_path):
    players = tmp_path / "wta_players.csv"
    players.write_text(
        "player_id,name_first,name_last,hand,dob,ioc,height,wikidata_id\n"
        "1,Alpha,One,R,19900101,USA,170,\n"
        "2,Beta,Two,R,19910101,CAN,171,\n",
        encoding="utf-8",
    )
    rankings = tmp_path / "wta_rankings_current.csv"
    rankings.write_text(
        "ranking_date,ranking,player,ranking_points\n"
        "20260608,20,1,1200\n"
        "20260608,40,2,800\n",
        encoding="utf-8",
    )
    supplement = tmp_path / "official.csv"
    supplement.write_text(
        "ranking_date,ranking_type,sackmann_player_id,wta_player_id,player_name,"
        "rank,points,tournaments_played,movement_source,identity_evidence,source\n"
        "2026-06-15,singles,1,101,Alpha One,10,1800,18,-3,exact_name_dob,wta_official\n"
        "2026-06-15,singles,2,102,Beta Two,30,1000,17,2,exact_name_dob,wta_official\n"
        "2026-06-15,doubles,1,101,Alpha One,5,2000,12,1,exact_name_dob,wta_official\n",
        encoding="utf-8",
    )
    return players, rankings, supplement


def _match(day):
    return SimpleNamespace(
        tour="wta",
        scheduled_at=datetime(2026, 6, day, 12, tzinfo=timezone.utc),
        player1_id="c1",
        player1_name="Alpha One",
        player2_id="c2",
        player2_name="Beta Two",
    )


def test_official_supplement_extends_pinned_source_and_ignores_doubles(tmp_path):
    players, rankings, supplement = _write_sources(tmp_path)
    history = WTARankHistory.from_sackmann(
        players,
        [rankings],
        canonical_to_sackmann={"c1": "1", "c2": "2"},
        supplement_csvs=[supplement],
    )

    # The 2026-06-15 official snapshot is eligible for a later match.
    values = history.features_for_match(_match(22))
    assert values["wta_hist_known_both"] == 1.0
    assert values["wta_hist_rank_advantage"] > 0.0
    assert values["wta_hist_points_advantage"] > 0.0

    # Same-day rankings are never eligible; 2026-06-15 still sees 2026-06-08.
    same_day = history.features_for_match(_match(15))
    assert same_day["wta_hist_known_both"] == 1.0
    assert same_day["wta_hist_rank_advantage"] > 0.0


def test_supplement_conflict_with_pinned_snapshot_fails_closed(tmp_path):
    players, rankings, _ = _write_sources(tmp_path)
    supplement = tmp_path / "conflict.csv"
    supplement.write_text(
        "ranking_date,ranking_type,sackmann_player_id,player_name,rank,points\n"
        "2026-06-08,singles,1,Alpha One,19,1200\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicts with pinned source"):
        WTARankHistory.from_sackmann(
            players,
            [rankings],
            supplement_csvs=[supplement],
        )


def test_supplement_cannot_fill_older_holes_before_pinned_max(tmp_path):
    players, rankings, _ = _write_sources(tmp_path)
    supplement = tmp_path / "older.csv"
    supplement.write_text(
        "ranking_date,ranking_type,sackmann_player_id,player_name,rank,points\n"
        "2026-06-01,singles,1,Alpha One,22,1100\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="strictly later"):
        WTARankHistory.from_sackmann(
            players,
            [rankings],
            supplement_csvs=[supplement],
        )


def test_conflicting_duplicate_supplement_key_fails_closed(tmp_path):
    players, rankings, _ = _write_sources(tmp_path)
    supplement = tmp_path / "dupe.csv"
    supplement.write_text(
        "ranking_date,ranking_type,sackmann_player_id,player_name,rank,points\n"
        "2026-06-15,singles,1,Alpha One,10,1800\n"
        "2026-06-15,singles,1,Alpha One,11,1800\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Conflicting WTA ranking supplement"):
        WTARankHistory.from_sackmann(
            players,
            [rankings],
            supplement_csvs=[supplement],
        )
