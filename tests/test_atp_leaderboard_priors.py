from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tbt.data.atp_leaderboards import (
    ATPLeaderboardPriors,
    ATP_LEADERBOARD_FEATURE_NAMES,
)


def _row(period, surface, board, player_id, name, rating):
    field = {
        "serve": "Stats.ServeRatingSortField",
        "return": "Stats.ReturnRatingSortField",
        "pressure": "Stats.PressureRatingSortField",
    }[board]
    return {
        "period": str(period),
        "surface": surface,
        "board": board,
        "PlayerId": player_id,
        "PlayerName": name,
        field: str(rating),
    }


def _rows():
    rows = []
    values = {
        "2024": {
            "all": {
                "Jannik Sinner": (300, 160, 250),
                "Carlos Alcaraz": (290, 158, 245),
            },
            "hard": {
                "Jannik Sinner": (310, 162, 255),
                "Carlos Alcaraz": (295, 159, 248),
            },
        },
        "2025": {
            "all": {
                "Jannik Sinner": (999, 999, 999),
                "Carlos Alcaraz": (1, 1, 1),
            },
        },
        "52week": {
            "all": {
                "Jannik Sinner": (305, 161, 252),
                "Carlos Alcaraz": (292, 157, 247),
            },
            "hard": {
                "Jannik Sinner": (312, 164, 257),
                "Carlos Alcaraz": (298, 160, 250),
            },
        },
    }
    ids = {"Jannik Sinner": "S0AG", "Carlos Alcaraz": "A0E2"}
    boards = ("serve", "return", "pressure")
    for period, by_surface in values.items():
        for surface, players in by_surface.items():
            for name, metrics in players.items():
                for board, rating in zip(boards, metrics):
                    rows.append(_row(period, surface, board, ids[name], name, rating))
    return rows


def _match(*, year=2025, tour="atp", p1="Jannik Sinner", p2="Carlos Alcaraz"):
    return SimpleNamespace(
        tour=tour,
        scheduled_at=datetime(year, 6, 1, tzinfo=timezone.utc),
        surface="hard",
        player1_name=p1,
        player2_name=p2,
    )


def test_historical_match_uses_previous_completed_season_only():
    priors = ATPLeaderboardPriors(_rows())
    features = priors.features_for_match(_match(year=2025), current=False)

    assert features["atp_serve_rating_diff"] == 10.0
    assert features["atp_return_rating_diff"] == 2.0
    assert features["atp_pressure_rating_diff"] == 5.0
    assert features["atp_surface_serve_rating_diff"] == 15.0
    assert features["atp_leaderboard_known_both"] == 1.0
    assert features["atp_surface_leaderboard_known_both"] == 1.0


def test_current_match_uses_rolling_52week_snapshot():
    priors = ATPLeaderboardPriors(_rows())
    features = priors.features_for_match(_match(year=2026), current=True)

    assert features["atp_serve_rating_diff"] == 13.0
    assert features["atp_surface_serve_rating_diff"] == 14.0
    assert features["atp_pressure_rating_diff"] == 5.0


def test_unique_initial_surname_fallback_is_supported():
    priors = ATPLeaderboardPriors(_rows())
    features = priors.features_for_match(
        _match(p1="J. Sinner", p2="C. Alcaraz"),
        current=True,
    )
    assert features["atp_leaderboard_known_both"] == 1.0
    assert features["atp_serve_rating_diff"] == 13.0


def test_non_atp_match_is_neutral():
    priors = ATPLeaderboardPriors(_rows())
    features = priors.features_for_match(_match(tour="wta"), current=True)
    assert set(features) == set(ATP_LEADERBOARD_FEATURE_NAMES)
    assert all(value == 0.0 for value in features.values())


def test_detailed_serve_return_pressure_metrics_are_exposed():
    rows = _rows()
    for row in rows:
        if row["period"] != "52week":
            continue
        if row["board"] == "serve":
            row["Stats.FirstServePctSortField"] = (
                "67.0" if row["PlayerName"] == "Jannik Sinner" else "63.0"
            )
            row["Stats.AvgAcesPerMatchSortField"] = (
                "9.2" if row["PlayerName"] == "Jannik Sinner" else "7.1"
            )
        elif row["board"] == "return":
            row["Stats.ReturnGamesWonPctSortField"] = (
                "31.0" if row["PlayerName"] == "Jannik Sinner" else "28.5"
            )
        elif row["board"] == "pressure":
            row["Stats.TieBreaksWonPctSortField"] = (
                "70.0" if row["PlayerName"] == "Jannik Sinner" else "62.0"
            )

    priors = ATPLeaderboardPriors(rows)
    features = priors.features_for_match(_match(year=2026), current=True)

    assert features["atp_first_serve_pct_diff"] == 4.0
    assert round(features["atp_avg_aces_per_match_diff"], 6) == 2.1
    assert features["atp_return_games_won_pct_diff"] == 2.5
    assert features["atp_tiebreaks_won_pct_diff"] == 8.0
