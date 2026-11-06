"""Fail-closed issued-only authority for member-facing prediction offers.

The packaged feed is a candidate, not an issuance receipt. Only immutable
commitments acknowledged by the post-deploy ledger confirmation may be offered.
This module never rewrites the feed, the ledger, odds, or settled Results.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .feed import _betting_day_key, visible_feed
from .publication import (
    _evidence_hash,
    _issued_exact_market_row,
    _market_commitment_from_feed_row,
    _market_ledger_index,
    _market_row_section,
    _prediction_commitment,
)

TABLE = "BlinQIssuedServingAuthority"
PARTITION = "issued"
MARKET_KEYS = (
    "top_daily_picks", "prime_picks", "value_picks", "doubles_picks",
    "ace_picks", "sg_picks",
)
ACTIVE_KEYS = ("upcoming", *MARKET_KEYS)
LEGACY_ALIASES = ("daily_picks", "top_daily", "value", "doubles", "aces", "sets_games")
MAX_KEYS = 500


def row_authority_key(row: dict, feed_key: str) -> str:
    """Exact event/section/selection/price/model identity, never only event ID."""
    if not isinstance(row, dict):
        raise ValueError("Invalid publication row")
    if feed_key == "upcoming":
        identity = ("upcoming", _prediction_commitment(row))
    else:
        section = _market_row_section(feed_key, row)
        if not section:
            raise ValueError("Unknown market section")
        identity = (section, _market_commitment_from_feed_row(row, section))
    player1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    player2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    return _evidence_hash((
        "issued-offer-v1",
        identity,
        row.get("scheduled_at"),
        row.get("model_version"),
        row.get("winner_id"),
        str(player1.get("id") or ""),
        str(player2.get("id") or ""),
    ))


def _feed_keys(feed: dict) -> set[str]:
    result = set()
    for key in ACTIVE_KEYS:
        for row in feed.get(key) or []:
            if not isinstance(row, dict):
                continue
            try:
                result.add(row_authority_key(row, key))
            except ValueError:
                continue
    return result


def build_confirmed_authority(feed: dict, ledger: list, *, now=None) -> dict:
    """Construct a bounded allowlist from *confirmed* exact ledger identities."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid confirmation artifacts")
    visible = visible_feed(feed, now=now)
    ledger_index = _market_ledger_index(ledger)
    keys = set()
    for row in visible.get("upcoming") or []:
        if not isinstance(row, dict):
            continue
        stored = ledger_index.get(str(row.get("event_id") or ""))
        if not isinstance(stored, dict):
            continue
        if not stored.get("issued_at") or stored.get("publication_status") != "published":
            continue
        if _prediction_commitment(row) == _prediction_commitment(stored):
            keys.add(row_authority_key(row, "upcoming"))
    for feed_key in MARKET_KEYS:
        for row in visible.get(feed_key) or []:
            if (isinstance(row, dict)
                    and _issued_exact_market_row(row, feed_key, ledger_index)):
                keys.add(row_authority_key(row, feed_key))
    if len(keys) > MAX_KEYS:
        raise ValueError("Issued authority exceeds bounded daily size")
    return {
        "schema": 1,
        "confirmed_only": True,
        "betting_day": visible["daily_offer_day"],
        "keys": sorted(keys),
    }


def validate_authority(manifest: dict, feed: dict, *, now=None) -> dict:
    """The trusted sync must reference only the exact deployed offer bytes."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Invalid issued authority schema")
    if manifest.get("confirmed_only") is not True:
        raise ValueError("Unconfirmed publication authority")
    visible = visible_feed(feed, now=now)
    if manifest.get("betting_day") != visible.get("daily_offer_day"):
        raise ValueError("Issued authority day differs from serving day")
    keys = manifest.get("keys")
    if (not isinstance(keys, list) or len(keys) > MAX_KEYS
            or len(keys) != len(set(map(str, keys)))
            or any(not isinstance(key, str) or len(key) != 64
                   or any(char not in "0123456789abcdef" for char in key)
                   for key in keys)):
        raise ValueError("Invalid issued identity keys")
    if not set(keys).issubset(_feed_keys(visible)):
        raise ValueError("Issued identity absent from exact deployed feed")
    return manifest


def filter_unissued_offers(feed: dict, manifest: dict | None) -> dict:
    """Keep Results untouched; fail closed on every offer if authority is absent."""
    if not isinstance(feed, dict):
        raise ValueError("Invalid serving feed")
    day = str(feed.get("daily_offer_day") or "")
    valid = (
        isinstance(manifest, dict)
        and manifest.get("schema") == 1
        and manifest.get("confirmed_only") is True
        and manifest.get("betting_day") == day
        and isinstance(manifest.get("keys"), list)
    )
    authorized = set(manifest["keys"]) if valid else set()
    result = dict(feed)
    for key in ACTIVE_KEYS:
        rows = feed.get(key)
        if not isinstance(rows, list):
            result[key] = []
            continue
        allowed = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                if row_authority_key(row, key) in authorized:
                    allowed.append(row)
            except ValueError:
                continue
        result[key] = allowed
    # Old section aliases must not provide a second ungated offer surface.
    for key in LEGACY_ALIASES:
        if key in result:
            result[key] = []
    result["publication_authority_status"] = "confirmed" if valid else "unavailable"
    return result


def load_authority(day: str) -> dict | None:
    """Durable independent publication receipt; missing is not permission."""
    from .admin_storage import _table, AdminStorageUnavailable

    try:
        row = _table(TABLE).get_entity(partition_key=PARTITION, row_key=day)
    except Exception as exc:
        if isinstance(exc, KeyError) or getattr(exc, "status_code", None) == 404:
            return None
        raise AdminStorageUnavailable("Issued publication authority unavailable") from exc
    try:
        result = json.loads(str(row["manifest_json"]))
        if (not isinstance(result, dict) or result.get("betting_day") != day
                or result.get("schema") != 1 or result.get("confirmed_only") is not True
                or not isinstance(result.get("keys"), list)):
            raise ValueError("Malformed issued publication authority")
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise AdminStorageUnavailable("Corrupt issued publication authority") from exc


def persist_authority(manifest: dict) -> dict:
    """Merge only previously confirmed keys using ETag CAS; never revoke history."""
    from .admin_storage import _table, AdminStorageUnavailable
    from azure.core import MatchConditions

    day = manifest["betting_day"]
    incoming = set(manifest["keys"])
    client = _table(TABLE)
    for _attempt in range(4):
        try:
            existing = client.get_entity(partition_key=PARTITION, row_key=day)
        except Exception as exc:
            if isinstance(exc, KeyError) or getattr(exc, "status_code", None) == 404:
                existing = None
            else:
                raise AdminStorageUnavailable("Issued publication read unavailable") from exc
        if existing is None:
            prior = set()
        else:
            try:
                previous = json.loads(str(existing["manifest_json"]))
                if (previous.get("schema") != 1 or previous.get("betting_day") != day
                        or previous.get("confirmed_only") is not True):
                    raise ValueError("Invalid prior authority")
                prior = set(previous["keys"])
            except (ValueError, TypeError, KeyError) as exc:
                raise AdminStorageUnavailable("Corrupt previous authority") from exc
        keys = sorted(prior | incoming)
        if len(keys) > MAX_KEYS:
            raise ValueError("Issued authority exceeds bounded daily size")
        updated = {
            "schema": 1, "confirmed_only": True, "betting_day": day, "keys": keys,
        }
        entity = {
            "PartitionKey": PARTITION,
            "RowKey": day,
            "manifest_json": json.dumps(updated, separators=(",", ":")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if existing is None:
                client.create_entity(entity)
            else:
                etag = getattr(existing, "metadata", {}).get("etag")
                if etag is None:
                    raise AdminStorageUnavailable("Missing publication CAS version")
                client.update_entity(
                    entity, mode="merge", etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            # Independent storage readback, not just a successful write response.
            observed = load_authority(day)
            if not observed or not incoming.issubset(observed["keys"]):
                raise AdminStorageUnavailable("Issued authority readback mismatch")
            return observed
        except Exception as exc:
            if getattr(exc, "status_code", None) in (409, 412):
                continue
            raise
    raise AdminStorageUnavailable("Concurrent authority updates did not converge")
