from datetime import datetime, timedelta, timezone

import pytest

from tbt.services import clv_market_history as clv


START = "2026-11-02T15:00:00Z"
FIRST = "2026-11-02T12:00:00Z"


def offer():
    return {
        "top_daily_picks": [{
            "event_id": "321",
            "scheduled_at": START,
            "player1": {"name": "Karolína Muchová", "id": "1"},
            "player2": {"name": "Rebecca Šramková", "id": "2"},
            "winner_id": "1",
        }],
        "daily_picks": [],
        "value_picks": [{
            "event_id": "654",
            "scheduled_at": START,
            "player1": {"name": "Anna Smith", "id": "11"},
            "player2": {"name": "Sara Jones", "id": "12"},
            "winner_id": "11",
        }],
        "prime_picks": [{
            "event_id": "888",
            "scheduled_at": START,
            "player1": {"name": "Prime A"},
            "player2": {"name": "Prime B"},
        }],
    }


def sample(*, p1="Karolina Muchova", p2="Rebecca Sramkova",
           source_event_id="123456", captured=FIRST, kickoff=START, books=None):
    if books is None:
        books = [{
            "key": "Book A",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": p1, "price": 2.1},
                {"name": p2, "price": 1.8},
            ]}],
        }]
    return {
        "schema": 1, "events": [{
            "event_id": source_event_id, "home_team": p1,
            "away_team": p2, "captured_at": captured,
            "commence_time": kickoff, "bookmakers": books,
        }],
    }


class FakeTable:
    def __init__(self):
        self.rows = {}

    def create_entity(self, row):
        key = row["PartitionKey"], row["RowKey"]
        if key in self.rows:
            class Conflict(Exception):
                status_code = 409
            raise Conflict()
        self.rows[key] = dict(row)

    def get_entity(self, *, partition_key, row_key):
        return self.rows[partition_key, row_key]

    def query_entities(self, query_filter=None):
        partition = query_filter.split("'", 2)[1]
        return [r for (pk, _), r in self.rows.items() if pk == partition]


def test_top_matching_handles_accents_and_preserves_exact_source():
    quotes, rejected = clv.extract_verified_quotes(
        sample(), offer(), now=datetime(2026, 11, 2, 13, tzinfo=timezone.utc))
    assert rejected == 0
    assert len(quotes) == 1
    assert quotes[0]["event_id"] == "321"
    assert quotes[0]["source_event_id"] == "123456"
    assert quotes[0]["provider"] == "propline"


def test_value_is_in_scope_but_prime_is_not():
    now = datetime(2026, 11, 2, 13, tzinfo=timezone.utc)
    v, _ = clv.extract_verified_quotes(
        sample(p1="Anna Smith", p2="Sara Jones"), offer(), now=now)
    p, rejected = clv.extract_verified_quotes(
        sample(p1="Prime A", p2="Prime B"), offer(), now=now)
    assert len(v) == 1 and v[0]["event_id"] == "654"
    assert not p and rejected == 1


def test_wrong_event_time_identity_and_odds_fail_closed():
    now = datetime(2026, 11, 2, 13, tzinfo=timezone.utc)
    for bad in [
        sample(source_event_id="bad"),
        sample(captured="2026-11-02T15:00:00Z"),
        sample(kickoff="2026-11-03T15:00:00Z"),
        sample(books=[{"key": "A", "markets": [{"key": "h2h",
            "outcomes": [{"name": "Karolina Muchova", "price": 2},
                         {"name": "Unmatched", "price": 3}]}]}]),
        sample(books=[{"key": "A", "markets": [{"key": "totals",
            "outcomes": [{"name": "Over", "price": 2},
                         {"name": "Under", "price": 2}]}]}]),
    ]:
        quotes, _ = clv.extract_verified_quotes(bad, offer(), now=now)
        assert not quotes


def test_ambiguous_issued_identity_rejected():
    duplicated = offer()
    duplicated["value_picks"].append({
        "event_id": "777", "scheduled_at": START,
        "player1": {"name": "Karolina Muchova"},
        "player2": {"name": "Rebecca Sramkova"},
    })
    quotes, rejected = clv.extract_verified_quotes(
        sample(), duplicated,
        now=datetime(2026, 11, 2, 13, tzinfo=timezone.utc))
    assert quotes == [] and rejected == 1


def test_append_only_idempotent_verified_and_single_book(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(clv, "_table", lambda *_: table)
    now = datetime(2026, 11, 2, 13, tzinfo=timezone.utc)
    first, _ = clv.extract_verified_quotes(sample(), offer(), now=now)
    result = clv.persist_quotes(first)
    assert result == {"written": 1, "already_present": 0, "verified": 1}
    assert clv.persist_quotes(first)["already_present"] == 1
    second, _ = clv.extract_verified_quotes(
        sample(captured="2026-11-02T12:30:00Z"), offer(), now=now)
    clv.persist_quotes(second)
    different, _ = clv.extract_verified_quotes(sample(
        captured="2026-11-02T12:40:00Z",
        books=[{"key": "Book B", "markets": [{"key": "h2h",
            "outcomes": [{"name": "Karolina Muchova", "price": 2.9},
                         {"name": "Rebecca Sramkova", "price": 1.4}]}]}]),
        offer(), now=now)
    clv.persist_quotes(different)
    history = clv.read_event_history("321", now=now)
    assert history["bookmaker"] == "Book A"
    assert len(history["history"]) == 2
    rendered = clv.attach_offer_clv(offer())
    assert rendered["top_daily_picks"][0]["market_movement"]["verified"]
    assert "market_movement" not in rendered["prime_picks"][0]
    assert "market_movement" not in rendered["value_picks"][0]


def test_detects_mutated_readback(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(clv, "_table", lambda *_: table)
    quotes, _ = clv.extract_verified_quotes(
        sample(), offer(), now=datetime(2026, 11, 2, 13, tzinfo=timezone.utc))
    original = table.get_entity
    def corrupted(**kwargs):
        row = dict(original(**kwargs))
        row["payload"] = "{}"
        return row
    monkeypatch.setattr(table, "get_entity", corrupted)
    with pytest.raises(clv.AdminStorageUnavailable, match="mismatch"):
        clv.persist_quotes(quotes)
