"""Fail-closed issued-only authority for member-facing prediction offers.

The packaged feed is a candidate, not an issuance receipt. Only immutable
commitments acknowledged by the post-deploy ledger confirmation may be offered.
This module never rewrites the feed, the ledger, odds, or settled Results.
"""
from __future__ import annotations

import base64
import binascii
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
MAX_KEYS = 700  # Daily public board + distinct market contracts; storage remains size-gated.
MAX_DAILY_KEYS = 7000  # Bounded union of successive issued generations, never truncated.


def _decode_entity(row):
    """Atomic multi-property receipt; legacy one-property receipts remain readable."""
    from .admin_storage import _decode_runtime_ui_payload
    header = _decode_runtime_ui_payload(row["manifest_json"])
    if not isinstance(header, dict) or "keys_shards_v1" not in header:
        return _decode_stored_authority(row["manifest_json"])
    import hashlib
    shards = header["keys_shards_v1"]
    if (header.get("schema") != 1 or header.get("confirmed_only") is not True
            or not isinstance(shards, list) or not 1 <= len(shards) <= MAX_DAILY_KEYS // MAX_KEYS):
        raise ValueError("Invalid issued authority shard inventory")
    keys = []
    for index, digest in enumerate(shards):
        encoded = row[f"keys_{index:03d}"]
        if not isinstance(encoded, str) or hashlib.sha256(encoded.encode()).hexdigest() != digest:
            raise ValueError("Issued authority shard checksum mismatch")
        part = _decode_stored_authority(encoded)
        if (not isinstance(part, dict) or part.get("betting_day") != header.get("betting_day")
                or part.get("confirmed_only") is not True or not isinstance(part.get("keys"), list)):
            raise ValueError("Issued authority shard identity mismatch")
        keys.extend(part["keys"])
    if len(keys) != header.get("key_count") or len(keys) != len(set(keys)) or len(keys) > MAX_DAILY_KEYS:
        raise ValueError("Invalid issued authority union")
    return {"schema": 1, "confirmed_only": True, "betting_day": header["betting_day"], "keys": keys}


def _decode_stored_authority(value: object) -> dict | None:
    """Read legacy plain/gzip manifests and compact exact SHA-256 receipts."""
    from .admin_storage import _decode_runtime_ui_payload

    payload = _decode_runtime_ui_payload(value)
    if not isinstance(payload, dict) or "keys_packed_v1" not in payload:
        return payload
    encoded = payload["keys_packed_v1"]
    if not isinstance(encoded, str) or "keys" in payload:
        raise ValueError("Malformed packed issued authority")
    try:
        binary = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("Invalid packed issued authority") from exc
    if len(binary) % 32 or len(binary) // 32 > MAX_KEYS:
        raise ValueError("Invalid packed issued authority size")
    return {
        **{key: item for key, item in payload.items() if key != "keys_packed_v1"},
        "keys": [binary[index:index + 32].hex() for index in range(0, len(binary), 32)],
    }


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


def offer_contract_readback(feed: dict) -> dict:
    """Worker-only exact hashes of the issued board, not merely section counts."""
    from .entitlements import _daily_rows
    sources = {"top": ("top_daily_picks", _daily_rows(feed)),
               "value": ("value_picks", feed.get("value_picks") or []),
               "aces": ("ace_picks", feed.get("ace_picks") or [])}
    return {category: sorted({row_authority_key(row, key) for row in rows
                              if isinstance(row, dict)})
            for category, (key, rows) in sources.items()}


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
        result = _decode_entity(row)
        if (not isinstance(result, dict) or result.get("betting_day") != day
                or result.get("schema") != 1 or result.get("confirmed_only") is not True
                or not isinstance(result.get("keys"), list)):
            raise ValueError("Malformed issued publication authority")
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise AdminStorageUnavailable("Corrupt issued publication authority") from exc


def persist_authority(manifest: dict) -> dict:
    """Merge only previously confirmed keys using ETag CAS; never revoke history."""
    from .admin_storage import (
        _table, _encode_runtime_ui_payload,
        AdminStorageUnavailable,
    )
    from azure.core import MatchConditions

    day = manifest["betting_day"]
    incoming = set(manifest["keys"])
    if (len(manifest["keys"]) > MAX_KEYS or len(incoming) != len(manifest["keys"])
            or any(not isinstance(key, str) or len(key) != 64
                   or any(c not in "0123456789abcdef" for c in key) for key in incoming)):
        raise ValueError("Issued authority exceeds bounded daily size or has invalid keys")
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
                previous = _decode_entity(existing)
                if (not isinstance(previous, dict) or previous.get("schema") != 1 or previous.get("betting_day") != day
                        or previous.get("confirmed_only") is not True):
                    raise ValueError("Invalid prior authority")
                prior = set(previous["keys"])
            except (ValueError, TypeError, KeyError) as exc:
                raise AdminStorageUnavailable("Corrupt previous authority") from exc
        keys = sorted(prior | incoming)
        if len(keys) > MAX_DAILY_KEYS:
            raise ValueError("Issued authority exceeds bounded daily size")
        updated = {
            "schema": 1, "confirmed_only": True, "betting_day": day, "keys": keys,
        }
        # Keep all exact SHA-256 identities while packing each to 32 bytes
        # before the existing gzip codec. Plain hex JSON exceeds Azure's 64 KiB
        # UTF-16 property cap on today's full slate; neither drop nor reissue rows.
        packed = {
            "schema": 1, "confirmed_only": True, "betting_day": day,
            "keys_packed_v1": base64.b64encode(
                b"".join(bytes.fromhex(key) for key in keys)
            ).decode("ascii"),
        }
        shards = {}
        if len(keys) > MAX_KEYS:
            import hashlib
            digests = []
            for index, start in enumerate(range(0, len(keys), MAX_KEYS)):
                part = {**packed, "keys_packed_v1": base64.b64encode(
                    b"".join(bytes.fromhex(key) for key in keys[start:start + MAX_KEYS])
                ).decode("ascii")}
                encoded = _encode_runtime_ui_payload(part)
                if len(encoded.encode("utf-16-le")) > 65536:
                    raise ValueError("Issued authority shard exceeds Azure Table string limit")
                shards[f"keys_{index:03d}"] = encoded
                digests.append(hashlib.sha256(encoded.encode()).hexdigest())
            packed = {"schema": 1, "confirmed_only": True, "betting_day": day,
                      "keys_shards_v1": digests, "key_count": len(keys)}
        stored_json = _encode_runtime_ui_payload(packed)
        if len(stored_json.encode("utf-16-le")) > 65536:
            raise ValueError("Issued authority exceeds Azure Table string limit")
        entity = {
            "PartitionKey": PARTITION,
            "RowKey": day,
            "manifest_json": stored_json,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **shards,
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
            if not observed or not set(keys).issubset(observed["keys"]):
                raise AdminStorageUnavailable("Issued authority readback mismatch")
            return observed
        except Exception as exc:
            if getattr(exc, "status_code", None) in (409, 412):
                continue
            raise
    raise AdminStorageUnavailable("Concurrent authority updates did not converge")
