from tbt.providers.score import parse_event_score


def event(home_score, away_score):
    return {
        "homeScore": home_score,
        "awayScore": away_score,
    }


def test_parse_structured_bo3_score_counts_sets_games_and_tiebreaks():
    payload = event(
        {"current": 2, "period1": 6, "period2": 3, "period3": 7},
        {"current": 1, "period1": 4, "period2": 6, "period3": 6},
    )
    stats = parse_event_score(payload, home_is_player1=True, best_of=3)
    assert stats["p1_sets_won"] == 2
    assert stats["p2_sets_won"] == 1
    assert stats["p1_games_won"] == 16
    assert stats["p2_games_won"] == 16
    assert stats["total_sets"] == 3
    assert stats["total_games"] == 32
    assert stats["tiebreak_sets"] == 1
    assert stats["deciding_set"] == 1
    assert stats["straight_sets"] == 0
    assert stats["p1_first_set_won"] == 1


def test_parse_score_respects_canonical_player_orientation():
    payload = event(
        {"current": 0, "period1": 4, "period2": 4},
        {"current": 2, "period1": 6, "period2": 6},
    )
    stats = parse_event_score(payload, home_is_player1=False, best_of=3)
    assert stats["p1_sets_won"] == 2
    assert stats["p2_sets_won"] == 0
    assert stats["p1_games_won"] == 12
    assert stats["p2_games_won"] == 8
    assert stats["p1_first_set_won"] == 1
    assert stats["straight_sets"] == 1


def test_parse_score_returns_empty_without_structured_periods():
    assert parse_event_score({"homeScore": {"current": 2}, "awayScore": {"current": 0}}, home_is_player1=True, best_of=3) == {}
