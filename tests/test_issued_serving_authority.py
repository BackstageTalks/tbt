"""Regress the 2026-11-06 Safonov leak at the member-serving boundary."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import hashlib
import json

from tbt.services.issued_authority import (
    build_confirmed_authority,
    filter_unissued_offers,
    row_authority_key,
    validate_authority,
)


NOW = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)


def pick(event, *, price=1.75, probability=.82, start="2026-11-06T16:00:00+00:00"):
    return {
        "event_id": event,
        "id": "prediction-" + event,
        "scheduled_at": start,
        "created_at": "2026-11-06T06:20:00+00:00",
        "model_version": "7.2.1",
        "player1": {"id": "p1-" + event, "probability": probability},
        "player2": {"id": "p2-" + event, "probability": 1 - probability},
        "winner_id": "p1-" + event,
        "confidence": probability,
        "betting": {
            "market": "match_winner",
            "selection_id": "p1-" + event,
            "odds": price,
            "model_probability": probability,
            "edge": .10,
            "expected_value": .20,
            "betting_day": "2026-11-06",
        },
    }


def ledger_entry(row, *, issued=True):
    bet = row["betting"]
    issued_at = "2026-11-06T06:27:00+00:00" if issued else None
    publication = {
        "section": "top_daily", "market": "match_winner",
        "selection_id": bet["selection_id"], "odds": bet["odds"],
        "model_probability": bet["model_probability"], "edge": bet["edge"],
        "expected_value": bet["expected_value"], "betting_day": bet["betting_day"],
        "issued_at": issued_at,
        "publication_status": "published" if issued else "expired_unpublished",
    }
    return {
        **{key: deepcopy(row[key]) for key in (
            "event_id", "id", "scheduled_at", "created_at", "model_version",
            "player1", "player2", "winner_id", "confidence",
        )},
        "issued_at": issued_at,
        "publication_status": "published" if issued else "expired_unpublished",
        "market_publications": [publication],
    }


def test_safonov_pending_expires_but_never_becomes_member_top():
    a = pick("van-herck", probability=.902, price=2.18)
    b = pick("nakashima", probability=.765, price=1.77)
    c = pick("sahtali", probability=.755, price=1.65)
    safonov = pick("17497459", probability=.8304140127388535, price=3.70,
                   start="2026-11-06T06:30:00+00:00")
    feed = {
        "schema": 1, "generated_at": "2026-11-06T06:24:57+00:00",
        "upcoming": [a, b, c, safonov],
        "top_daily_picks": [a, b, c, safonov],
        "results": [{"event_id": "prior-settled", "result": {"correct": True}}],
    }
    ledger = [ledger_entry(row) for row in (a, b, c)]
    ledger.append(ledger_entry(safonov, issued=False))
    allowed = build_confirmed_authority(feed, ledger, now=NOW)
    assert allowed["confirmed_only"] is True
    assert len(allowed["keys"]) == 6  # 3 confirmed TOP + 3 confirmed future predictions
    assert row_authority_key(safonov, "top_daily_picks") not in allowed["keys"]

    from tbt.services.feed import visible_feed
    serving = filter_unissued_offers(visible_feed(feed, now=NOW), allowed)
    assert [x["event_id"] for x in serving["top_daily_picks"]] == [
        "van-herck", "nakashima", "sahtali",
    ]
    assert "17497459" not in {x["event_id"] for x in serving["upcoming"]}
    assert serving["results"] == feed["results"]
    assert len(feed["top_daily_picks"]) == 4  # no destructive rewrite
    assert ledger[-1]["market_publications"][0]["issued_at"] is None


def test_no_confirmed_authority_fails_closed_and_preserves_results():
    candidate = pick("candidate")
    feed = {"daily_offer_day": "2026-11-06",
            "top_daily_picks": [candidate],
            "upcoming": [candidate],
            "results": [{"event_id": "historical"}]}
    visible = filter_unissued_offers(feed, None)
    assert visible["top_daily_picks"] == []
    assert visible["upcoming"] == []
    assert visible["results"] == feed["results"]
    assert visible["publication_authority_status"] == "unavailable"


def test_existing_issued_pick_remains_after_start_during_same_day():
    started = pick("issued-earlier", start="2026-11-06T07:30:00+00:00")
    feed = {
        "schema": 1, "generated_at": "2026-11-06T06:20:00+00:00",
        "upcoming": [started], "top_daily_picks": [started],
    }
    manifest = build_confirmed_authority(feed, [ledger_entry(started)], now=NOW)
    from tbt.services.feed import visible_feed
    offered = filter_unissued_offers(visible_feed(feed, now=NOW), manifest)
    assert [r["event_id"] for r in offered["top_daily_picks"]] == ["issued-earlier"]
    assert offered["upcoming"] == []


def test_authority_is_exact_price_side_and_model_not_just_event_id():
    correct = pick("match-1")
    feed = {"schema": 1, "generated_at": "2026-11-06T06:20:00+00:00",
            "upcoming": [], "top_daily_picks": [correct]}
    manifest = build_confirmed_authority(feed, [ledger_entry(correct)], now=NOW)
    changed = deepcopy(correct)
    changed["betting"]["odds"] = 3.70
    changed["model_version"] = "other-model"
    from tbt.services.feed import visible_feed
    offered = filter_unissued_offers(visible_feed({**feed, "top_daily_picks": [changed]}, now=NOW), manifest)
    assert offered["top_daily_picks"] == []
    assert correct["betting"]["odds"] == 1.75


def test_sync_fails_on_forged_authority_or_other_generation():
    row = pick("allowed")
    feed = {"schema": 1, "generated_at": "2026-11-06T06:20:00+00:00",
            "upcoming": [], "top_daily_picks": [row]}
    manifest = build_confirmed_authority(feed, [ledger_entry(row)], now=NOW)
    assert validate_authority(manifest, feed, now=NOW) is manifest
    fake = deepcopy(manifest)
    fake["keys"] = ["a" * 64]
    with pytest.raises(ValueError, match="absent"):
        validate_authority(fake, feed, now=NOW)
    fake = deepcopy(manifest)
    fake["betting_day"] = "2026-11-05"
    with pytest.raises(ValueError, match="day"):
        validate_authority(fake, feed, now=NOW)
    fake = deepcopy(manifest)
    fake["confirmed_only"] = False
    with pytest.raises(ValueError, match="Unconfirmed"):
        validate_authority(fake, feed, now=NOW)


class _Utf16LimitedAuthorityTable:
    """Simulate Azure Table's 64 KiB UTF-16 string-property constraint."""

    def __init__(self):
        self.rows = {}

    def get_entity(self, *, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        class Entity(dict):
            metadata = {"etag": "known-version"}
        return Entity(self.rows[key])

    def _save(self, entity):
        # Exactly the property that was rejected in production: 64-char SHA
        # identifiers can exceed the Azure Edm.String limit as plain JSON.
        assert len(entity["manifest_json"].encode("utf-16-le")) <= 65536
        assert all(len(value.encode("utf-16-le")) <= 65536
                   for value in entity.values() if isinstance(value, str))
        assert sum(len(value.encode("utf-16-le")) for value in entity.values()
                   if isinstance(value, str)) < 1000000
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def create_entity(self, entity):
        self._save(entity)

    def update_entity(self, entity, *, mode, etag, match_condition):
        assert etag == "known-version"
        assert mode == "merge"
        self._save(entity)


def test_issued_authority_large_daily_receipt_survives_azure_string_limit(monkeypatch):
    from tbt.services import admin_storage
    from tbt.services.issued_authority import load_authority, persist_authority

    table = _Utf16LimitedAuthorityTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    day = "2026-11-07"
    keys = sorted(hashlib.sha256(str(i).encode()).hexdigest() for i in range(495))
    manifest = {"schema": 1, "confirmed_only": True, "betting_day": day, "keys": keys}
    # Show that the original uncompressed storage would fail the real limit.
    assert len(json.dumps(manifest, separators=(",", ":")).encode("utf-16-le")) > 65536

    first = persist_authority(manifest)
    assert first["keys"] == keys
    assert load_authority(day)["keys"] == keys
    assert table.rows[("issued", day)]["manifest_json"].startswith("gzip:")

    # Subsequent CAS merge must preserve all issued identities.
    extra = hashlib.sha256(b"one-more-exact-issued-key").hexdigest()
    merged = persist_authority({**manifest, "keys": [extra]})
    assert sorted(merged["keys"]) == sorted(keys + [extra])
    assert load_authority(day)["keys"] == sorted(keys + [extra])


def test_issued_authority_legacy_plain_json_remains_readable_and_migrates(monkeypatch):
    from tbt.services import admin_storage
    from tbt.services.issued_authority import load_authority, persist_authority

    table = _Utf16LimitedAuthorityTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    day = "2026-11-06"
    legacy_key = hashlib.sha256(b"old-identity").hexdigest()
    legacy = {"schema": 1, "confirmed_only": True,
              "betting_day": day, "keys": [legacy_key]}
    table.rows[("issued", day)] = {
        "PartitionKey": "issued", "RowKey": day,
        "manifest_json": json.dumps(legacy),
    }
    assert load_authority(day)["keys"] == [legacy_key]
    new_key = hashlib.sha256(b"new-identity").hexdigest()
    saved = persist_authority({**legacy, "keys": [new_key]})
    assert sorted(saved["keys"]) == sorted([legacy_key, new_key])
    assert table.rows[("issued", day)]["manifest_json"].startswith("gzip:")


def test_issued_authority_650_exact_keys_fit_azure_and_round_trip(monkeypatch):
    """The 8 Nov slate exceeded 500; keep the full issued authority, not a sample."""
    from tbt.services import admin_storage
    from tbt.services.issued_authority import MAX_KEYS, load_authority, persist_authority

    table = _Utf16LimitedAuthorityTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    day = "2026-11-08"
    keys = sorted(hashlib.sha256(str(i).encode()).hexdigest() for i in range(650))
    assert 650 <= MAX_KEYS
    receipt = {"schema": 1, "confirmed_only": True, "betting_day": day, "keys": keys}

    confirmed = persist_authority(receipt)
    assert confirmed["keys"] == keys
    assert load_authority(day)["keys"] == keys
    saved = table.rows[("issued", day)]["manifest_json"]
    assert saved.startswith("gzip:")
    assert len(saved.encode("utf-16-le")) <= 65536
    # Never silently truncate to the old 500-key limit.
    assert len(confirmed["keys"]) == 650

    extra = hashlib.sha256(b"newly-confirmed-market").hexdigest()
    assert len(persist_authority({**receipt, "keys": [extra]})["keys"]) == 651
    assert set(load_authority(day)["keys"]) == set(keys + [extra])


def test_issued_authority_remains_finitely_bounded(monkeypatch):
    from tbt.services import admin_storage
    from tbt.services.issued_authority import MAX_KEYS, persist_authority

    table = _Utf16LimitedAuthorityTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    keys = sorted(hashlib.sha256(str(i).encode()).hexdigest() for i in range(MAX_KEYS + 1))
    with pytest.raises(ValueError, match="bounded daily size"):
        persist_authority({
            "schema": 1, "confirmed_only": True,
            "betting_day": "2026-11-08", "keys": keys,
        })
    assert not table.rows


def test_successive_generations_preserve_more_than_700_keys_atomically(monkeypatch):
    from tbt.services import admin_storage
    from tbt.services.issued_authority import load_authority, persist_authority
    table = _Utf16LimitedAuthorityTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    receipt = {"schema": 1, "confirmed_only": True, "betting_day": "2026-11-08"}
    keys = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(1400)]
    persist_authority({**receipt, "keys": keys[:700]})
    result = persist_authority({**receipt, "keys": keys[700:]})
    assert set(result["keys"]) == set(keys)
    assert set(load_authority(receipt["betting_day"])["keys"]) == set(keys)
    # Corruption of one property cannot silently authorize a partial receipt.
    table.rows[("issued", receipt["betting_day"])]["keys_001"] = "corrupt"
    with pytest.raises(admin_storage.AdminStorageUnavailable, match="Corrupt"):
        load_authority(receipt["betting_day"])
