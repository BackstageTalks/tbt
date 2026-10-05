from datetime import datetime, timedelta, timezone

from tbt.data.court_speed import CourtSpeedHistory, COURT_SPEED_FEATURE_NAMES
from tbt.schemas import MatchRecord


def _match(i, day, tournament, tournament_id, winner="p1", raw=0.70):
    ace = max(0.0, (raw - 0.62) / 0.75)
    return MatchRecord(
        match_id=f"m{i}",
        tour="ATP",
        scheduled_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
        player1_id="p1",
        player1_name="Alpha",
        player2_id="p2",
        player2_name="Beta",
        surface="hard",
        tournament=tournament,
        tournament_id=tournament_id,
        winner_id=winner,
        status="completed",
        stats={
            "p1_service_points_won": 0.62,
            "p2_service_points_won": 0.62,
            "p1_ace_rate": ace,
            "p2_ace_rate": ace,
        },
    )


def test_target_match_never_contributes_to_its_own_court_speed():
    matches = []
    # Build enough same-surface baseline plus previous-edition venue history.
    for i in range(20):
        matches.append(_match(i, i, f"Other {i}", f"o{i}", raw=0.70))
    for i in range(5):
        matches.append(_match(100 + i, 30 + i, "Venue X", "old", raw=0.77))

    early = _match(200, 60, "Venue X", "new", raw=1.40)
    second = _match(201, 61, "Venue X", "new", raw=0.50)
    matches.extend([early, second])

    history = CourtSpeedHistory(matches)
    f1 = history.features_for_match(early)
    f2 = history.features_for_match(second)

    assert f1["court_speed_known"] == 1.0
    assert f1["court_speed_current"] == f1["court_speed_prior"]
    # Only one prior match from the new event exists before second match, so
    # current-event speed still falls back to historical venue prior.
    assert f2["court_speed_current"] == f2["court_speed_prior"]


def test_current_event_estimate_uses_only_completed_previous_matches():
    matches = [_match(i, i, f"Other {i}", f"o{i}", raw=0.70) for i in range(20)]
    matches += [_match(100 + i, 30 + i, "Venue X", "old", raw=0.70) for i in range(5)]
    matches += [
        _match(200, 60, "Venue X", "new", raw=0.82),
        _match(201, 61, "Venue X", "new", raw=0.82),
        _match(202, 62, "Venue X", "new", raw=0.82),
        _match(203, 63, "Venue X", "new", raw=0.20),
    ]

    history = CourtSpeedHistory(matches)
    target = history.features_for_match(matches[-1])
    assert target["court_speed_known"] == 1.0
    assert target["court_speed_current"] > target["court_speed_prior"]
    assert target["court_speed_delta_vs_venue_history"] > 0


def test_missing_stats_fail_closed():
    match = _match(1, 1, "X", "x")
    match.stats = {}
    history = CourtSpeedHistory([match])
    row = history.features_for_match(match)
    assert set(row) == set(COURT_SPEED_FEATURE_NAMES)
    assert row["court_speed_known"] == 0.0
