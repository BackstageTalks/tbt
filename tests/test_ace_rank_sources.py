from datetime import datetime, timedelta, timezone

from ace_rank_sources import supplement_ace_ranks
from tbt.services.feed import ace_eligibility_reason


NOW = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)


def match(*, r1=None, r2=None, tour="ATP", tournament="Sofia Challenger"):
    return {
        "tour": tour, "tournament": tournament,
        "player1": {"id": "200", "name": "Player One", "rank": r1},
        "player2": {"id": "300", "name": "Player Two", "rank": r2},
    }


def profiles(*, generated_at=None, r1=200, r2=350):
    return {
        "schema": 1,
        "generated_at": (generated_at or NOW - timedelta(hours=3)).isoformat(),
        "players": {"200": {"rank": r1}, "300": {"rank": r2}},
    }


def test_fills_two_missing_ranks_from_fresh_exact_id_profile_without_mutating_model_rows():
    row = match()
    rows, report = supplement_ace_ranks([row], profiles(), now=NOW)
    assert report["status"] == "verified_fresh"
    assert report["ranks_filled"] == 2
    assert row["player1"]["rank"] is None and row["player2"]["rank"] is None
    assert rows[0]["player1"]["rank"] == 200
    assert rows[0]["player1"]["rank_source"] == "verified_recent_player_profile"
    assert ace_eligibility_reason(row) == "missing_player_rank"
    assert ace_eligibility_reason(rows[0]) == "eligible"


def test_never_overwrites_provider_rank_even_when_profile_disagrees():
    row = match(r1=1001)
    rows, report = supplement_ace_ranks([row], profiles(r1=200), now=NOW)
    assert rows[0]["player1"]["rank"] == 1001
    assert report["unchanged_existing_ranks"] == 1
    assert ace_eligibility_reason(rows[0]) == "outside_top1000"


def test_invalid_profile_rank_and_missing_identity_fail_closed():
    row = match()
    rows, report = supplement_ace_ranks([row], profiles(r1=True, r2="NaN"), now=NOW)
    assert rows[0] is row and report["ranks_filled"] == 0
    assert ace_eligibility_reason(rows[0]) == "missing_player_rank"
    row2 = match()
    row2["player1"]["id"] = "unknown-id"
    rows2, report2 = supplement_ace_ranks([row2], profiles(), now=NOW)
    assert rows2[0]["player1"]["rank"] is None
    assert report2["ranks_filled"] == 1


def test_stale_future_and_undated_profiles_never_supplement():
    row = match()
    for snapshot in (
        profiles(generated_at=NOW - timedelta(days=20)),
        profiles(generated_at=NOW + timedelta(minutes=1)),
        {"schema": 1, "players": {"200": {"rank": 200}, "300": {"rank": 350}}},
    ):
        rows, report = supplement_ace_ranks([row], snapshot, now=NOW)
        assert rows[0] is row
        assert report["ranks_filled"] == 0
        assert report["status"] == "skipped"


def test_profile_does_not_grant_itf_or_unknown_tour_eligibility():
    for tour in ("ITF", "unknown"):
        rows, _ = supplement_ace_ranks([match(tour=tour)], profiles(), now=NOW)
        assert ace_eligibility_reason(rows[0]) == "unsupported_tour"


def test_fresh_profiles_restore_real_aces_and_more_aces_shortlists():
    from tbt.schemas import MatchRecord
    from tbt.services.ace_selection import select_ace_picks, select_ace_winner_picks

    history = []
    for i in range(10):
        when = NOW - timedelta(days=20 + i * 7)
        history.extend((
            MatchRecord(
                match_id=f"a{i}", tour="atp", scheduled_at=when,
                player1_id="200", player1_name="Player One",
                player2_id=f"x{i}", player2_name=f"x{i}",
                winner_id="200", status="finished", surface="hard",
                tournament="History",
                stats={"p1_aces": 10, "p2_aces": 3,
                       "p1_double_faults": 1, "p2_double_faults": 2},
            ),
            MatchRecord(
                match_id=f"b{i}", tour="atp", scheduled_at=when,
                player1_id="300", player1_name="Player Two",
                player2_id=f"y{i}", player2_name=f"y{i}",
                winner_id=f"y{i}", status="finished", surface="hard",
                tournament="History",
                stats={"p1_aces": 2, "p2_aces": 9,
                       "p1_double_faults": 4, "p2_double_faults": 2},
            ),
        ))

    future = match()
    future.update({
        "id": "future", "event_id": "future",
        "scheduled_at": (NOW + timedelta(hours=5)).isoformat(),
        "surface": "hard",
    })
    original, _ = select_ace_picks(
        history, [future], now=NOW, allow_local_aces_fallback=True,
    )
    assert not any(row["market"] == "aces" for row in original)

    supplemented, report = supplement_ace_ranks([future], profiles(), now=NOW)
    assert report["ranks_filled"] == 2
    cards, selection = select_ace_picks(
        history, supplemented, now=NOW, allow_local_aces_fallback=True,
    )
    assert selection["aces_gate_counts"]["eligible"] == 1
    assert any(row["market"] == "aces" for row in cards)
    winners, _ = select_ace_winner_picks(history, supplemented, now=NOW)
    assert len(winners) >= 1
    assert future["player1"]["rank"] is None
