"""Research-only full-batch extraction of source-native TennisApi daily odds.

The daily map can contain hundreds of event keys in ONE billed response.
Decode every entry without a fixed match cap, but never treat its prices as
historic as-of quotes, confirmed CDB identities, or permission to publish.
Raw event identifiers/prices stay in memory; only aggregates leave the probe.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ..errors import ProviderError
from .odds_quality import odds_unavailable
from ..services.market_selection import decimal_odds


def extract_bulk_match_winner_choices(
    payload: Any, *, processed_at: datetime,
) -> dict:
    """Decode two labelled choices per event, failing closed per bad record.

    A returned row is *research only*: endpoint-native event ID is not yet a
    canonical CDB identity, and processing time is not bookmaker quote time.
    """
    if processed_at.tzinfo is None:
        raise ValueError("processed_at must be timezone-aware")
    if not isinstance(payload, dict) or not isinstance(payload.get("odds"), dict):
        raise ProviderError("Unsupported daily odds map")

    raw = payload["odds"]
    excluded: Counter[str] = Counter()
    pairs: list[dict] = []
    valid_native_id_entries = 0
    for key, event in raw.items():
        # Accept only canonical ASCII decimal event IDs. Never merge aliases,
        # infer foreign-provider IDs or coerce scientific notation.
        if (not isinstance(key, str) or not key.isascii()
                or not key.isdecimal() or not key.isdigit()
                or not key or key[0] == "0" or int(key) <= 0):
            excluded["invalid_native_event_key"] += 1
            continue
        valid_native_id_entries += 1
        if not isinstance(event, dict) or odds_unavailable(event):
            excluded["unavailable_event"] += 1
            continue
        choices = event.get("choices")
        if not isinstance(choices, list) or len(choices) != 2:
            excluded["missing_or_nonbinary_choices"] += 1
            continue
        sides: dict[str, dict] = {}
        issue = None
        for choice in choices:
            if not isinstance(choice, dict) or odds_unavailable(choice):
                issue = "unavailable_choice"
                break
            label = str(choice.get("name", "")).strip().casefold()
            side = {"1": "home", "home": "home",
                    "2": "away", "away": "away"}.get(label)
            if side is None or side in sides:
                issue = "ambiguous_choice_side"
                break
            fractional = decimal_odds(choice.get("fractionalValue"))
            supplied_decimal = decimal_odds(choice.get("decimalValue"))
            if (fractional is not None and supplied_decimal is not None
                    and abs(fractional - supplied_decimal) > 1e-9):
                issue = "contradictory_price_fields"
                break
            price = fractional if fractional is not None else supplied_decimal
            if price is None:
                issue = "invalid_latest_price"
                break
            source = choice.get("sourceId", choice.get("source_id"))
            if isinstance(source, bool) or isinstance(source, (dict, list)):
                issue = "invalid_source_id"
                break
            sides[side] = {
                "decimal_odds": price,
                "source_id": None if source in (None, "") else str(source),
            }
        if issue:
            excluded[issue] += 1
            continue
        if set(sides) != {"home", "away"}:
            excluded["incomplete_pair"] += 1
            continue
        home_source = sides["home"]["source_id"]
        away_source = sides["away"]["source_id"]
        if (home_source is None) != (away_source is None) or (
                home_source is not None and home_source != away_source):
            excluded["unmatched_quote_source"] += 1
            continue
        pairs.append({
            "native_event_id": key,
            "home_decimal_odds": sides["home"]["decimal_odds"],
            "away_decimal_odds": sides["away"]["decimal_odds"],
            "source_id": home_source,
            "processed_at_utc": processed_at.astimezone(timezone.utc).isoformat(),
            "provider_quote_timestamp_known": False,
            "pre_match_asof_verified": False,
            "canonical_identity_verified": False,
            "cdb_import_authorized": False,
        })

    return {
        "raw_entry_count": len(raw),
        "valid_native_event_key_count": valid_native_id_entries,
        "decoded_research_pair_count": len(pairs),
        "rejected_by_reason": dict(sorted(excluded.items())),
        "pairs": pairs,  # Private in-memory research rows; never export in report.
        "provider_quote_timestamp_verified": False,
        "cdb_import_authorized": False,
        "policy": "Research-only. No historic price, canonical CDB or live publication authorization.",
    }
