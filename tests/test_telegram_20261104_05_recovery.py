"""Frozen exact 4/5 November ACE archive recovery: no source guess or CDB."""
from copy import deepcopy
import pytest
from tbt.services import telegram_20261104_05_recovery as recovery
from tbt.services.results_archive import _identity


def original_verified_archive():
    source = []
    for day, manifest in recovery.ISSUED.items():
        for eid, pid, name, clock, line, projection, odds, actual in manifest["ace"]:
            source.append({
                "event_id": eid, "scheduled_at": f"{day}T{clock}:00+00:00",
                "betting_day": day,
                "player1": {"id": pid, "name": name},
                "player2": {"id": "opponent-" + eid, "name": "Opponent"},
                "market_publications": [{
                    "section": "ace", "market": "aces",
                    "selection_id": pid,
                    "publication_status": "published",
                    "publication_key": "different-existing-projection-" + eid,
                    "price_contract": "player_total_ou",
                    "market_line": line + 2,
                    "ou_side": "over",
                    "result": {
                        "runtime_source": "match_status_snapshot",
                        "correct": actual > line + 2, "void": False,
                        "actual_count": actual, "settled_at": "2026-11-06T01:00:00Z",
                    },
                }],
            })
    return source


@pytest.mark.parametrize("day,n,wins,losses", [
    ("2026-11-04", 5, 3, 2), ("2026-11-05", 7, 5, 2),
])
def test_exact_immutable_local_lines_regraded_only_from_original_same_player_actual(
        day, n, wins, losses):
    source = original_verified_archive()
    pristine = deepcopy(source)
    docs = recovery.exact_candidates(source, day)
    assert source == pristine
    assert len(docs) == n
    manifest = recovery.ISSUED[day]
    assert len({row["event_id"] for row in docs}) == n
    assert sum(row["market_publications"][0]["result"]["correct"] is True for row in docs) == wins
    assert sum(row["market_publications"][0]["result"]["correct"] is False for row in docs) == losses
    for candidate, frozen in zip(docs, manifest["ace"]):
        eid, pid, name, clock, line, projection, odds, actual = frozen
        pub = candidate["market_publications"][0]
        assert pub["publication_key"] == f"local-aces-ou-v1:{eid}:{pid}:over:{line:.1f}"
        assert pub["selection_id"] == pid
        assert pub["issued_at"] == manifest["sent_at"]
        assert pub["odds"] == odds
        assert pub["market_line"] == line
        assert pub["result"]["actual_count"] == actual
        assert pub["result"]["profit_units"] == (round(odds-1,8) if actual > line else -1.0)
        assert pub["result"]["recovery_evidence"] == "existing_verified_exact_player_aces_count_v1"


@pytest.mark.parametrize("bad", ("other_player","other_fixture","missing_count",
                                 "invalid_source","count_conflict","duplicate",
                                 "invalid_void"))
def test_unverified_statistics_never_create_frozen_ace_result(bad):
    rows = original_verified_archive()
    selected = next(x for x in rows if x["event_id"] == recovery.ISSUED["2026-11-04"]["ace"][0][0])
    pub = selected["market_publications"][0]
    if bad == "other_player":
        pub["selection_id"] = "another-player"
    elif bad == "other_fixture":
        selected["scheduled_at"] = "2026-11-05T10:00:00+00:00"
    elif bad == "missing_count":
        pub["result"]["actual_count"] = None
    elif bad == "invalid_source":
        pub["result"]["runtime_source"] = "model_output"
    elif bad == "count_conflict":
        pub["result"]["actual_count"] = 10
    elif bad == "duplicate":
        rows.append(deepcopy(selected))
    elif bad == "invalid_void":
        pub["result"]["void"] = True
    with pytest.raises((ValueError, RuntimeError)):
        recovery.exact_candidates(rows,"2026-11-04")


def test_append_only_two_day_dryrun_readback_idempotency_and_existing_conflict(monkeypatch):
    durable = original_verified_archive()
    initial = deepcopy(durable)
    writes = []
    monkeypatch.setattr(recovery, "load_settled_results_archive",
                        lambda: deepcopy(durable))

    def native_append(rows):
        keys = {
            _identity(row,pub)
            for row in durable for pub in row.get("market_publications") or []
        }
        new_keys = {
            _identity(row,row["market_publications"][0]) for row in rows
        }
        assert not keys.intersection(new_keys)
        durable.extend(deepcopy(rows))
        writes.append(len(rows))
        return {"verified": True, "added": len(rows), "updated": 0}

    monkeypatch.setattr(recovery, "save_settled_results_archive", native_append)
    for day, expected in (("2026-11-04",5),("2026-11-05",7)):
        dry = recovery.recover(day,dry_run=True)
        assert dry["net_new"] == expected
        assert dry["provider_requests"] == dry["cdb_writes"] == 0
        assert dry["telegram_sent"] is False and dry["archive_updated"] == 0
    assert durable == initial and not writes
    for day in recovery.ISSUED:
        done = recovery.recover(day,dry_run=False)
        assert done["status"] == "verified"
        assert done["net_new"] == len(recovery.ISSUED[day]["ace"])
        assert done["archived_exact_original_aces"] == len(recovery.ISSUED[day]["ace"])
        assert recovery.recover(day,dry_run=False)["net_new"] == 0
    assert writes == [5,7]
    original = recovery.ISSUED["2026-11-04"]
    existing = next(row for row in durable if
                    row["market_publications"][0].get("publication_key") ==
                    f"local-aces-ou-v1:{original['ace'][0][0]}:{original['ace'][0][1]}:over:{original['ace'][0][4]:.1f}")
    existing["market_publications"][0]["result"]["correct"] = False
    with pytest.raises(RuntimeError,match="differs"):
        recovery.recover("2026-11-04",dry_run=True)
