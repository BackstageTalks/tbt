"""A provider-ID conflict must not score the wrong players or stop safe rows."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tbt.services.engine import reconcile_ledger, serving_feed


NOW = datetime(2025, 1, 5, tzinfo=timezone.utc)


def row(event="123", result=None):
    return {"event_id": event, "scheduled_at": "2025-01-03T12:00:00+00:00",
            "issued_at": "2025-01-02T12:00:00+00:00", "winner_id": "A",
            "player1": {"id": "A", "probability": .7},
            "player2": {"id": "B", "probability": .3},
            "tour": "atp", "surface": "hard", "result": result}


def completed(factory, p1="A", p2="B", winner="A", event="123"):
    return replace(factory("history-" + event, p1, p2, winner, day=3),
                   provider_payload={"id": event})


def test_conflict_is_quarantined_while_other_match_settles(match_factory, capsys):
    ledger = [row(), row("456")]
    original = deepcopy(ledger)
    records = reconcile_ledger(ledger, [], [
        completed(match_factory, "C", "D", "C"),
        completed(match_factory, event="456"),
    ], NOW)
    assert ledger == original
    assert records[0]["result"] is None
    assert records[0]["settlement_quarantine"]["reason"] == "player_identity_mismatch"
    assert records[1]["result"]["correct"] is True
    assert '"event_id": "123"' in capsys.readouterr().out


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_provider_id_never_uses_last_candidate(match_factory, reverse):
    history = [completed(match_factory), completed(match_factory, "C", "D", "C")]
    records = reconcile_ledger([row()], [], history[::-1] if reverse else history, NOW)
    assert records[0]["result"] is None
    assert records[0]["settlement_quarantine"]


def test_conflicting_winners_quarantined_but_swapped_duplicate_is_safe(match_factory):
    match = completed(match_factory)
    conflict = reconcile_ledger([row()], [], [match, replace(match, winner_id="B")], NOW)
    assert conflict[0]["result"] is None
    assert conflict[0]["settlement_quarantine"]["reason"] == "conflicting_completed_results"
    safe = reconcile_ledger([row()], [], [match, match.swapped()], NOW)
    assert safe[0]["result"]["correct"] is True


def test_quarantined_result_preserved_but_not_scored_and_can_recover(match_factory):
    previous = {"winner_id": "A", "correct": True, "settled_at": NOW.isoformat()}
    records = reconcile_ledger([row(result=previous)], [],
                               [completed(match_factory, "C", "D", "C")], NOW)
    assert records[0]["result"] == previous
    feed = serving_feed(records, SimpleNamespace(version="test"), [], {}, [], NOW)
    assert feed["results"] == []
    assert feed["performance"] == {}
    unchanged = reconcile_ledger(records, [], [], NOW)
    assert unchanged[0]["settlement_quarantine"]  # No evidence is not a resolution.
    recovered = reconcile_ledger(records, [], [completed(match_factory).swapped()], NOW)
    assert "settlement_quarantine" not in recovered[0]
    assert recovered[0]["result"]["correct"] is True
    assert recovered[0]["player1"]["probability"] == .7
    assert recovered[0]["issued_at"] == row()["issued_at"]
