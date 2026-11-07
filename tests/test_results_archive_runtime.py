"""Durability regressions: verified hourly outcomes survive betting-day rollover."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tbt.services import results_archive
from tbt.services.results_archive import (
    settled_archive_candidates, save_settled_results_archive,
    load_settled_results_archive, merge_settled_results,
)


class VersionConflict(Exception):
    status_code = 412


class Table:
    def __init__(self):
        self.items = {}
        self.versions = {}
        self.upsert_calls = 0

    def get_entity(self, *, partition_key, row_key):
        from tbt.services.admin_storage import _VersionedStorageEntity
        key = (partition_key, row_key)
        if key not in self.items:
            raise KeyError(row_key)
        return _VersionedStorageEntity(deepcopy(self.items[key]), self.versions[key])

    def create_entity(self, entity):
        key = entity["PartitionKey"], entity["RowKey"]
        if key in self.items:
            raise VersionConflict()
        self.items[key] = deepcopy(entity)
        self.versions[key] = 1

    def update_entity(self, entity, *, mode, etag, match_condition):
        from azure.core import MatchConditions
        assert mode == "merge"
        assert match_condition == MatchConditions.IfNotModified
        key = entity["PartitionKey"], entity["RowKey"]
        if key not in self.items or self.versions[key] != etag:
            raise VersionConflict()
        self.items[key].update(deepcopy(entity))
        self.versions[key] += 1

    def upsert_entity(self, entity, mode=None):
        # This shared fake is also used by Admin exclusions and Match Status,
        # whose separate storage paths legitimately require upsert in tests.
        # The Results CAS tests assert the archive itself never calls here.
        self.upsert_calls += 1
        key = entity["PartitionKey"], entity["RowKey"]
        self.items[key] = deepcopy(entity)
        self.versions[key] = self.versions.get(key, 0) + 1

    def query_entities(self, query_filter):
        partition = query_filter.split("'", 2)[1]
        return [deepcopy(row) for (pk, _), row in self.items.items() if pk == partition]


def _offer(event="100", section="top_daily", issued_at=None):
    scheduled = "2026-10-08T12:00:00+00:00"
    row = {
        "event_id": event, "scheduled_at": scheduled,
        "tour": "ATP", "tournament": "Fixture Cup", "surface": "hard",
        "winner_id": "11",
        "player1": {"id": "11", "name": "Alpha", "country_code": "SK", "private_test_field": "discard"},
        "player2": {"id": "22", "name": "Beta"},
        "betting": {"selection_id": "11", "odds": 1.75, "model_probability": 0.71},
    }
    if issued_at:
        row["issued_at"] = issued_at
    return row


def _feed(event="100", section="top_daily", generated="2026-10-08T04:02:00Z"):
    key = {"top_daily": "top_daily_picks", "prime": "prime_picks", "value": "value_picks", "doubles": "doubles_picks"}[section]
    return {"generated_at": generated, key: [_offer(event, section)], "results": []}


def _status(event="100", outcome="win", provider_status="finished ended"):
    return {event: {
        "status": outcome,
        "checked_at": "2026-10-08T14:00:00+00:00",
        "winner_id": "11" if outcome == "win" else "22",
        "provider_status": provider_status,
    }}


def test_archive_is_durable_across_rollover_and_idempotent(monkeypatch):
    table = Table()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    feed = _feed()
    candidates = settled_archive_candidates(feed, _status())
    assert len(candidates) == 1
    pub = candidates[0]["market_publications"][0]
    assert pub["result"]["correct"] is True
    assert pub["odds"] == 1.75
    assert pub["result"]["profit_units"] == .75
    assert "private_test_field" not in candidates[0]["player1"]
    first = save_settled_results_archive(candidates)
    assert first == {"eligible": 1, "added": 1, "updated": 0, "verified": True}
    second = save_settled_results_archive(candidates)
    assert second["added"] == 0
    assert len(table.items) == 1
    # 09 Oct 06:00: new daily board no longer contains yesterday's event.
    next_day = {"generated_at": "2026-10-09T04:10:00Z", "top_daily_picks": [], "results": []}
    recovered = merge_settled_results(next_day, load_settled_results_archive())
    assert len(recovered["results"]) == 1
    assert recovered["results"][0]["event_id"] == "100"
    assert recovered["results"][0]["market_publications"][0]["result"]["correct"] is True
    assert recovered["results"][0]["market_publications"][0]["odds"] == 1.75


def test_archive_rejects_live_wrongly_terminal_and_late_publications():
    assert settled_archive_candidates(_feed(), _status(provider_status="inprogress 2nd set")) == []
    assert settled_archive_candidates(_feed(generated="2026-10-08T13:00:00Z"), _status()) == []
    late = _feed()
    late["top_daily_picks"][0]["issued_at"] = "2026-10-08T13:00:00Z"
    assert settled_archive_candidates(late, _status()) == []
    assert settled_archive_candidates(_feed(), {}) == []


def test_archive_preserves_outcomes_voids_and_dedupes_against_canonical(monkeypatch):
    table = Table()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    loss = settled_archive_candidates(_feed("101"), _status("101", "loss"))
    void = settled_archive_candidates(_feed("102"), _status("102", "void", "finished walkover"))
    assert loss[0]["market_publications"][0]["result"]["profit_units"] == -1
    assert void[0]["market_publications"][0]["result"]["void"] is True
    saved = save_settled_results_archive(loss + void)
    assert saved["added"] == 2
    archive = load_settled_results_archive()
    result = merge_settled_results({"results": deepcopy(archive)}, archive)
    assert len(result["results"]) == 2


def test_existing_canonical_outcome_has_precedence():
    rows = settled_archive_candidates(_feed(), _status())
    incumbent = deepcopy(rows[0])
    incumbent["market_publications"][0]["result"] = {
        "correct": False, "profit_units": -1.0, "settled_at": "2026-10-08T19:00:00Z",
    }
    merged = merge_settled_results({"results": [incumbent]}, rows)
    assert len(merged["results"]) == 1
    assert merged["results"][0]["market_publications"][0]["result"]["profit_units"] == -1.0


def test_archive_only_persists_public_issued_markets():
    other = _feed()
    other["top200_picks"] = [other.pop("top_daily_picks")[0]]
    assert settled_archive_candidates(other, _status()) == []
    feed = _feed()
    feed["top_daily_picks"][0]["excluded_reason"] = "not_qualified"
    assert settled_archive_candidates(feed, _status()) == []


def test_multi_day_archive_does_not_erase_prior_day(monkeypatch):
    table = Table()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    first = settled_archive_candidates(_feed(), _status())
    save_settled_results_archive(first)
    second = deepcopy(first)
    second[0]["event_id"] = "103"
    second[0]["scheduled_at"] = "2026-10-09T13:00:00+00:00"
    second[0]["market_publications"][0]["result"]["settled_at"] = "2026-10-09T15:00:00Z"
    save_settled_results_archive(second)
    assert {x["event_id"] for x in load_settled_results_archive()} == {"100", "103"}


def test_readback_regrades_verified_ou_win_to_loss_without_mutating_archive():
    original = _offer()
    original["scheduled_at"] = "2026-11-02T11:10:00+00:00"
    original["market_publications"] = [{
        "section": "ace", "market": "aces", "selection_id": "11",
        "price_contract": "player_total_ou", "ou_side": "over",
        "market_line": 10.5, "odds": 1.8,
        "price_status": "priced_projection", "issued_at": "2026-11-02T06:00:00Z",
        "result": {"status": "hit", "correct": True,
                   "actual_count": 9, "opponent_actual_count": 5,
                   "profit_units": 0.8, "staked_units": 1.0,
                   "runtime_source": "match_status_snapshot"},
    }]
    frozen = deepcopy(original)
    merged = merge_settled_results({"results": [original]}, [])
    pub = merged["results"][0]["market_publications"][0]
    assert pub["result"]["correct"] is False
    assert pub["result"]["profit_units"] == -1.0
    assert pub["result"]["ou_readback_regraded"] is True
    assert original == frozen  # Immutable evidence has not been overwritten.


def test_readback_quarantines_new_aces_without_exact_frozen_ou_contract():
    original = _offer()
    original["scheduled_at"] = "2026-11-02T11:10:00+00:00"
    original["market_publications"] = [{
        "section": "ace", "market": "aces", "selection_id": "11",
        "market_line": 10.5, "ou_side": "over",
        "issued_at": "2026-11-02T06:00:00Z",
        "result": {"correct": True, "actual_count": 9,
                   "opponent_actual_count": 5},
    }]
    assert merge_settled_results({"results": [original]}, [])["results"] == []
    assert merge_settled_results({"results": []}, [original])["results"] == []


def test_verified_winner_same_original_contract_upgrades_legacy_result_provenance():
    """A correct legacy result must not hide the verified native source on web."""
    verified = settled_archive_candidates(_feed(), _status())
    original = deepcopy(verified[0])
    publication = original["market_publications"][0]
    publication["result"] = {"correct": True, "void": False, "status": "hit"}
    frozen = deepcopy(original)
    merged = merge_settled_results({"results": [original]}, verified)
    assert len(merged["results"]) == 1
    out = merged["results"][0]["market_publications"][0]
    assert out["result"]["correct"] is True
    assert out["result"]["runtime_source"] == "match_status_snapshot"
    assert out["odds"] == verified[0]["market_publications"][0]["odds"]
    assert original == frozen


def test_verified_winner_does_not_replace_conflicting_legacy_quote():
    verified = settled_archive_candidates(_feed(), _status())
    original = deepcopy(verified[0])
    publication = original["market_publications"][0]
    publication["result"] = {"correct": True, "void": False, "status": "hit"}
    publication["odds"] = 9.99
    merged = merge_settled_results({"results": [original]}, verified)
    out = merged["results"][0]["market_publications"][0]
    assert out["result"].get("runtime_source") is None
    assert out["odds"] == 9.99



def _historical_ace_for_readback(*, day="2026-10-31"):
    """Frozen historic bet fixture: local issued quote is never calculated."""
    return {
        "event_id": "ace-historical-1",
        "scheduled_at": day + "T12:00:00+00:00",
        "player1": {"id": "p1", "name": "One"},
        "player2": {"id": "p2", "name": "Two"},
        "market_publications": [{
            "section": "ace", "market": "aces",
            "selection_id": "p1",
            "publication_key": "ace:historical:contract:under:4.5",
            "market_line": 4.5, "ou_side": "under",
            "price_contract": "player_total_ou",
            "price_basis": None,
            "odds": 1.72, "projection": 3.2,
            "issued_at": day + "T05:30:00+00:00",
            "price_status": "priced_projection",
            "result": {"correct": True, "void": False, "actual_count": 3,
                       "runtime_source": "match_status_snapshot"},
        }],
    }


def test_verified_historic_aces_readback_updates_provenance_not_local_pricing():
    for day in ("2026-10-31", "2026-11-01"):
        frozen=_historical_ace_for_readback(day=day)
        legacy=deepcopy(frozen)
        legacy["market_publications"][0]["result"].pop("runtime_source")
        legacy_copy=deepcopy(legacy)
        archive_copy=deepcopy(frozen)
        merged=merge_settled_results({"results":[legacy]}, [frozen])
        assert len(merged["results"])==1
        result=merged["results"][0]["market_publications"][0]
        assert result["result"]["runtime_source"]=="match_status_snapshot"
        assert result["result"]["correct"] is True
        assert result["result"]["actual_count"]==3
        for field in ("publication_key","market_line","ou_side","odds","projection","price_basis","issued_at"):
            assert result[field]==legacy_copy["market_publications"][0][field]
        assert legacy==legacy_copy  # read-only, no original change
        assert frozen==archive_copy  # archive remains authoritative/immutable


def test_verified_aces_overlay_rejects_conflicting_quotes_lines_and_outcomes():
    frozen=_historical_ace_for_readback()
    for field,bad in (("odds",9.99),("market_line",5.5),("ou_side","over"),
                      ("publication_key","ace:unrelated:under:4.5")):
        legacy=deepcopy(frozen)
        legacy["market_publications"][0]["result"].pop("runtime_source")
        legacy["market_publications"][0][field]=bad
        merged=merge_settled_results({"results":[legacy]},[frozen])
        target=[p for row in merged["results"] for p in row.get("market_publications") or []
                if p.get(field)==bad]
        assert target and target[0]["result"].get("runtime_source") is None
        assert legacy["market_publications"][0][field]==bad
    legacy=deepcopy(frozen)
    legacy["market_publications"][0]["result"]["correct"]=False
    legacy["market_publications"][0]["result"].pop("runtime_source")
    merged=merge_settled_results({"results":[legacy]},[frozen])
    assert merged["results"][0]["market_publications"][0]["result"]["correct"] is False
    assert merged["results"][0]["market_publications"][0]["result"].get("runtime_source") is None
