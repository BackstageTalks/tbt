from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.collect_livetennisapi_paid_history import (
    _canonical_index,
    _derive_rates,
    _resolve_match,
    _stage_row,
    _plan_blocked,
)


def _canonical(stats=None):
    return SimpleNamespace(
        match_id="m1",
        scheduled_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
        player1_id="1",
        player1_name="Alpha Player",
        player2_id="2",
        player2_name="Beta Player",
        tour="wta",
        surface="hard",
        tournament="Test Open",
        round_name="R32",
        winner_id="1",
        stats={} if stats is None else stats,
    )


def _tape():
    rows = []
    rows += [{"server": 1, "winner": 1} for _ in range(30)]
    rows += [{"server": 1, "winner": 2} for _ in range(10)]
    rows += [{"server": 2, "winner": 2} for _ in range(24)]
    rows += [{"server": 2, "winner": 1} for _ in range(16)]
    return rows


def _payload(*, complete=True):
    return {
        "match": {
            "id": 55,
            "scheduled_time": "2026-09-01T14:00:00Z",
            "tour": "wta",
            "surface": "hard",
            "tournament": "Test Open",
            "players": {
                "p1": {"name": "Alpha Player"},
                "p2": {"name": "Beta Player"},
            },
            "winner": 1,
        },
        "meta": {"points": {"available_complete": complete}},
        "tape": _tape(),
    }


def test_derive_rates_uses_only_explicit_server_and_winner():
    rates, audit = _derive_rates(_tape())
    assert audit["usable_points"] == 80
    assert rates[1]["service_points_won"] == 0.75
    assert rates[1]["return_points_won"] == 0.4
    assert rates[2]["service_points_won"] == 0.6
    assert rates[2]["return_points_won"] == 0.25


def test_missing_server_fails_closed():
    tape = _tape() + [{"server": None, "winner": 2}]
    rates, audit = _derive_rates(tape)
    assert rates is None
    assert audit["point_rows_missing_server"] == 1


def test_canonical_resolution_requires_exact_day_pair_and_unique_match():
    match = _canonical()
    index = _canonical_index([match])
    resolved, reason = _resolve_match(_payload()["match"], index)
    assert reason == ""
    assert resolved is match

    ambiguous = _canonical_index([match, _canonical()])
    resolved, reason = _resolve_match(_payload()["match"], ambiguous)
    assert resolved is None
    assert reason == "ambiguous"


def test_stage_requires_explicit_complete_tape_and_preserves_orientation():
    match = _canonical()
    staged, reason, audit = _stage_row(_payload(), match)
    assert reason == ""
    assert audit["usable_points"] == 80
    assert staged["match_id"] == "m1"
    assert staged["incoming_stats"]["p1_service_points_won"] == 0.75
    assert staged["incoming_stats"]["p1_return_points_won"] == 0.4
    assert staged["incoming_stats"]["p2_service_points_won"] == 0.6
    assert staged["incoming_stats"]["p2_return_points_won"] == 0.25

    staged, reason, _ = _stage_row(_payload(complete=False), match)
    assert staged is None
    assert reason == "complete_basis_not_explicit"


def test_provider_plan_block_is_terminal_but_not_a_data_error():
    assert _plan_blocked(RuntimeError("Live Tennis API plan does not allow /history/matches/1"))
    assert _plan_blocked(RuntimeError('403 {"error":"upgrade_required"}'))
    assert not _plan_blocked(RuntimeError("temporary provider timeout"))
