from datetime import datetime, timezone

from tbt.data.wta_season_stats import WTASeasonPriors, WTA_SEASON_FEATURE_NAMES
from tbt.schemas import MatchRecord


def match(year=2026, p1="Iga Swiatek", p2="Aryna Sabalenka", tour="wta"):
    return MatchRecord(
        match_id=f"x-{year}",
        tour=tour,
        tournament="Test",
        scheduled_at=datetime(year, 6, 1, tzinfo=timezone.utc),
        player1_id="1",
        player1_name=p1,
        player2_id="2",
        player2_name=p2,
        winner_id="1",
        completed=True,
    )


def test_previous_completed_season_only_and_orientation():
    priors = WTASeasonPriors([
        {"season": 2025, "PlayerNbr": 1, "First_Name": "Iga", "Last_Name": "Swiatek", "MatchCount": 10, "Aces": 20, "Double_Faults": 10, "first_serve_percent": 70, "first_serve_won_percent": 65, "second_serve_won_percent": 50, "service_points_won_percent": 60, "service_games_won_percent": 80, "breakpoint_saved_percent": 60, "first_return_percent": 40, "second_return_percent": 55, "return_games_won_percent": 45, "breakpoint_converted_percent": 50, "return_points_won_percent": 45, "total_points_won_percent": 53},
        {"season": 2025, "PlayerNbr": 2, "First_Name": "Aryna", "Last_Name": "Sabalenka", "MatchCount": 10, "Aces": 40, "Double_Faults": 20, "first_serve_percent": 65, "first_serve_won_percent": 70, "second_serve_won_percent": 48, "service_points_won_percent": 61, "service_games_won_percent": 82, "breakpoint_saved_percent": 58, "first_return_percent": 38, "second_return_percent": 52, "return_games_won_percent": 42, "breakpoint_converted_percent": 47, "return_points_won_percent": 43, "total_points_won_percent": 52},
        {"season": 2026, "PlayerNbr": 1, "First_Name": "Iga", "Last_Name": "Swiatek", "MatchCount": 1, "Aces": 999, "Double_Faults": 999, "first_serve_percent": 99},
    ])
    values = priors.features_for_match(match())
    assert values["wta_first_serve_pct_diff"] == 5.0
    assert values["wta_aces_per_match_diff"] == -2.0
    assert values["wta_season_stats_known_both"] == 1.0
    assert set(values) == set(WTA_SEASON_FEATURE_NAMES)


def test_non_wta_is_neutral():
    priors = WTASeasonPriors([])
    assert all(value == 0.0 for value in priors.features_for_match(match(tour="atp")).values())
