"""Durability regressions: verified hourly outcomes survive betting-day rollover."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tbt.services import results_archive
from tbt.services.results_archive import (
    settled_archive_candidates, save_settled_results_archive,
    load_settled_results_archive, merge_settled_results,
)


class Table:
    def __init__(self):
        self.items = {}

    def get_entity(self, *, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.items:
            raise KeyError(row_key)
        return deepcopy(self.items[key])

    def upsert_entity(self, entity, mode=None):
        self.items[(entity["PartitionKey"], entity["RowKey"])] = deepcopy(entity)

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
