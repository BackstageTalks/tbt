"""One-shot Nov 6 Telegram recovery reuses only independently verified counts."""
from copy import deepcopy

import pytest

from tbt.services import telegram_20261106_recovery as recovery
from tbt.services.results_archive import _identity


def frozen_archive():
    rows = []
    for event, selected, name, clock, line, projection, odds, actual in recovery.FROZEN_ACE_REFS:
        rows.append({
            "event_id": event, "scheduled_at": f"{recovery.DAY}T{clock}:00+00:00",
            "betting_day": recovery.DAY,
            "player1": {"id": selected, "name": name},
            "player2": {"id": "opponent-" + event, "name": "Opponent"},
            "market_publications": [{
                "section": "ace", "market": "aces",
                "selection_id": selected, "publication_status": "published",
                "publication_key": "other-archived-aces-projection:" + event,
                "market_line": line + 2,
                "price_contract": "player_total_ou", "ou_side": "over",
                "result": {
                    "runtime_source": "match_status_snapshot",
                    "correct": actual > line + 2, "void": False,
                    "actual_count": actual, "settled_at": "2026-11-07T04:00:00Z",
                },
            }],
        })
    for event, selected in recovery.FROZEN_TOP_REFS:
        rows.append({
            "event_id": event, "scheduled_at": "2026-11-06T10:00:00+00:00",
            "player1": {"id": selected},
            "player2": {"id": "opp-" + event},
            "market_publications": [{
                "section": "top_daily", "market": "match_winner",
                "selection_id": selected,
                "result": {"runtime_source": "match_status_snapshot", "correct": False},
            }],
        })
    return rows


def test_exact_original_aces_are_graduated_from_same_player_actuals():
    before = frozen_archive()
    untouched = deepcopy(before)
    generated = recovery.exact_candidates(before)
    assert before == untouched
    assert len(generated) == 8
    for row, frozen in zip(generated, recovery.FROZEN_ACE_REFS):
        event, selected, name, clock, line, projection, odds, actual = frozen
        pub = row["market_publications"][0]
        result = pub["result"]
        assert pub["publication_key"] == f"local-aces-ou-v1:{event}:{selected}:over:{line:.1f}"
        assert pub["market_line"] == line
        assert pub["issued_at"] == recovery.ISSUED_AT
        assert pub["odds"] == odds
        assert result["actual_count"] == actual
        assert result["correct"] is True
        assert result["profit_units"] == round(odds - 1, 8)
        assert result["runtime_source"] == "match_status_snapshot"
        assert row["event_id"] == event


@pytest.mark.parametrize("mutation", (
    "wrong_selection", "wrong_schedule", "missing_count", "unverified_source",
    "count_conflict", "duplicate_source", "no_top", "retirement_void",
))
def test_recovery_fails_closed_for_unverified_or_ambiguous_evidence(mutation):
    rows = frozen_archive()
    ace = rows[0]
    pub = ace["market_publications"][0]
    if mutation == "wrong_selection":
        pub["selection_id"] = "different"
    elif mutation == "wrong_schedule":
        ace["scheduled_at"] = "2026-11-07T18:00:00+00:00"
    elif mutation == "missing_count":
        pub["result"].pop("actual_count")
    elif mutation == "unverified_source":
        pub["result"]["runtime_source"] = "model_guess"
    elif mutation == "count_conflict":
        pub["result"]["actual_count"] += 1
    elif mutation == "duplicate_source":
        rows.append(deepcopy(ace))
    elif mutation == "no_top":
        rows = rows[:-1]
    elif mutation == "retirement_void":
        pub["result"]["void"] = True
    with pytest.raises((ValueError, RuntimeError)):
        recovery.exact_candidates(rows)


def test_native_archive_recovery_dryrun_commit_readback_and_idempotent(monkeypatch):
    durable = frozen_archive()
    original = deepcopy(durable)
    changes = []

    monkeypatch.setattr(recovery, "load_settled_results_archive",
                        lambda: deepcopy(durable))

    def append_exact(rows):
        existing = {
            _identity(row, pub)
            for row in durable for pub in row.get("market_publications") or []
        }
        keys = {
            _identity(row, row["market_publications"][0]) for row in rows
        }
        assert keys.isdisjoint(existing)
        durable.extend(deepcopy(rows))
        changes.append(len(rows))
        return {"verified": True, "added": len(rows), "updated": 0}

    monkeypatch.setattr(recovery, "save_settled_results_archive", append_exact)
    dry = recovery.recover(dry_run=True)
    assert dry["status"] == "dry_run"
    assert dry["net_new_aces"] == 8 and dry["top_verified"] == 3
    assert dry["provider_requests"] == 0 and dry["cdb_writes"] == 0
    assert original == durable and not changes

    complete = recovery.recover(dry_run=False)
    assert complete["status"] == "verified"
    assert complete["archived_original_aces"] == 8
    assert changes == [8]
    assert len(durable) == len(original) + 8

    again = recovery.recover(dry_run=False)
    assert again["net_new_aces"] == 0
    assert changes == [8]  # idempotent, no overwrites
