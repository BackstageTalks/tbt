"""Read-only per-event intake for the TennisApi daily bulk Match Winner odds map.

One daily API response can contain hundreds of event-keyed selection pairs.
This adapter parses *all* entries in memory and quarantines ambiguous entries
individually. It NEVER attaches an event to CDB, certifies a pre-match quote,
attributes a bookmaker, or replaces the per-event odds source.

Do not serialize candidates in public/audit artifacts: they contain provider
event IDs and price-like values. Only \`summary\` may leave this process.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from ..errors import ProviderError
from ..services.market_selection import decimal_odds


_POSITIVE_ID = re.compile(r"[1-9][0-9]*\Z")
_SELECTION = {"1": "home", "home": "home", "2": "away", "away": "away"}
_PRICE_FIELDS = ("fractionalValue", "decimalValue")
_CLOCK_FIELDS = ("timestamp", "quotedAt", "observedAt", "asOf")


def _source_id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    token = str(value)
    return token if len(token) <= 20 and _POSITIVE_ID.fullmatch(token) else None


def _price(choice: dict) -> float | None:
    """Only the two independently observed, unambiguously price-typed fields.

    Unknown \`value\` / \`change\` fields could be status/market codes. Never
    turn those into an odds quote or silently prefer contradictory prices.
    """
    observed = [decimal_odds(choice[key]) for key in _PRICE_FIELDS
                if choice.get(key) is not None]
    if not observed or any(v is None for v in observed):
        return None
    if len(observed) > 1 and abs(observed[0] - observed[1]) > 1e-9:
        return None
    return observed[0]


def _pair(node: dict) -> tuple[dict | None, str]:
    """Parse an exact two-sided, non-live, unsuspended selection shape."""
    choices = node.get("choices")
    if not isinstance(choices, list) or len(choices) < 2 or len(choices) > 12:
        return None, "missing_or_invalid_choices"
    if "marketId" in node and (
            type(node["marketId"]) not in (int, str)
            or str(node["marketId"]) != "1"):
        return None, "non_match_winner_market"
    name = node.get("marketName")
    if name is not None and str(name).strip().casefold() not in {
            "match winner", "winner", "full time", "fulltime"}:
        return None, "non_match_winner_market"
    for field in ("isLive", "suspended"):
        if field in node and type(node[field]) is not bool:
            return None, "ambiguous_status"
        if node.get(field) is True:
            return None, "live_or_suspended"
    selections: dict[str, dict] = {}
    for choice in choices:
        if not isinstance(choice, dict):
            return None, "malformed_choice"
        for field in ("isLive", "suspended"):
            if field in choice and type(choice[field]) is not bool:
                return None, "ambiguous_status"
            if choice.get(field) is True:
                return None, "live_or_suspended"
        side = _SELECTION.get(str(choice.get("name", "")).strip().casefold())
        if side is None:
            return None, "unknown_selection"
        value = _price(choice)
        if value is None:
            return None, "unparseable_or_ambiguous_price"
        opening = decimal_odds(choice.get("initialFractionalValue"))
        row = {"latest_decimal": value, "opening_decimal": opening}
        if side in selections and selections[side] != row:
            return None, "conflicting_duplicate_selection"
        selections[side] = row
    if set(selections) != {"home", "away"}:
        return None, "missing_side"
    return selections, "parsed"


def normalize_daily_bulk_odds(payload: Any, *, max_events: int = 50_000) -> dict:
    """Read every provider event in a bounded daily response; no external I/O.

    Returned \`candidates\` are a PRIVATE, post-hoc staging surface. Caller
    must not treat them as canonical matches or verified pre-start odds.
    Even if timestamp-looking fields appear, those are not trusted here.
    """
    if not isinstance(payload, dict) or payload.get("error") or payload.get("success") is False:
        raise ProviderError("Invalid daily TennisApi odds envelope")
    odds = payload.get("odds")
    if not isinstance(odds, dict):
        raise ProviderError("Daily TennisApi odds require a native event-keyed map")
    if type(max_events) is not int or max_events < 1 or len(odds) > max_events:
        raise ProviderError("Bulk odds map exceeds explicit safety bound")

    counts = Counter()
    candidates = []
    seen = set()
    counts["raw_event_entries"] = len(odds)
    for event_key, value in odds.items():
        ident = _source_id(event_key)
        if ident is None:
            counts["invalid_event_key"] += 1
            continue
        if ident in seen:
            counts["duplicate_normalized_event_id"] += 1
            continue
        seen.add(ident)
        counts["native_event_key_entries"] += 1
        if not isinstance(value, dict):
            counts["malformed_event_entry"] += 1
            continue
        if any(_source_id(value[key]) != ident for key in ("eventId", "event_id")
               if key in value):
            counts["event_id_mismatch"] += 1
            continue

        # The observed 994-entry bulk payload places \`choices\` directly
        # under each native event key. An alternative fixture has provider-ID
        # nested maps; retain those as separate sources, never mix prices.
        if "choices" in value:
            if any(_source_id(key) is not None and isinstance(child, dict)
                   and "choices" in child for key, child in value.items()):
                counts["ambiguous_nested_and_direct_market"] += 1
                continue
            provider = _source_id(value.get("providerId"))
            if "providerId" in value and provider is None:
                counts["invalid_source_provider_id"] += 1
                continue
            nodes = [(provider, value)]
        else:
            nodes = [(_source_id(key), child) for key, child in value.items()
                     if _source_id(key) is not None and isinstance(child, dict)
                     and "choices" in child]
            if not nodes:
                counts["unsupported_event_market_shape"] += 1
                continue

        valid_in_event = 0
        for provider, node in nodes:
            if (provider is not None and "providerId" in node
                    and _source_id(node["providerId"]) != provider):
                counts["rejected_provider_id_mismatch"] += 1
                continue
            selections, reason = _pair(node)
            if selections is None:
                counts["rejected_" + reason] += 1
                continue
            if any(_source_id(node[key]) != ident for key in ("eventId", "event_id")
                   if key in node):
                counts["rejected_nested_event_id_mismatch"] += 1
                continue
            # Unknown market ID / bookmaker and missing quote-time provenance
            # are not filled from the route name or from later observations.
            has_clock_shape = any(node.get(field) is not None for field in _CLOCK_FIELDS)
            has_clock_shape |= any(choice.get(field) is not None
                                   for choice in node["choices"]
                                   for field in _CLOCK_FIELDS)
            candidates.append({
                "source_event_id": ident,
                "source_provider_id": provider,
                "selections": selections,
                "clock_field_present_unverified": bool(has_clock_shape),
                "event_identity_verified_against_cdb": False,
                "market_id_verified": False,
                "quote_time_verified": False,
                "pre_match_asof_verified": False,
                "eligible_for_cdb_import": False,
                "eligible_to_replace_individual_market_fetch": False,
            })
            valid_in_event += 1
            counts["parseable_two_sided_pairs"] += 1
            counts["pair_with_clock_field_only"] += int(bool(has_clock_shape))
            counts["pairs_without_source_provider_id"] += int(provider is None)
        if valid_in_event:
            counts["native_events_with_parseable_pair"] += 1
        else:
            counts["native_events_without_parseable_pair"] += 1

    # Stable schema: zero is distinct from an unobserved/absent metric.
    # In particular, a provider event without any choices still reports
    # parseable_two_sided_pairs=0 and native_events_with_parseable_pair=0.
    for metric in (
        "raw_event_entries", "native_event_key_entries",
        "native_events_with_parseable_pair",
        "native_events_without_parseable_pair",
        "parseable_two_sided_pairs", "pairs_without_source_provider_id",
        "pair_with_clock_field_only",
        "invalid_event_key", "duplicate_normalized_event_id",
        "malformed_event_entry", "event_id_mismatch",
        "ambiguous_nested_and_direct_market", "invalid_source_provider_id",
        "unsupported_event_market_shape",
    ):
        counts.setdefault(metric, 0)

    # A map key says nothing about CDB match identity, bookmaker, historic
    # quote timestamp, market orientation, or net-new canonical prices.
    summary = {
        "schema": 1,
        "source": "tennisapi1",
        "scope": "research_only_event_index",
        "counts": dict(sorted(counts.items())),
        "raw_events_accounted_for": counts["raw_event_entries"]
        == (counts["invalid_event_key"] + counts["duplicate_normalized_event_id"]
            + counts["malformed_event_entry"] + counts["event_id_mismatch"]
            + counts["ambiguous_nested_and_direct_market"]
            + counts["invalid_source_provider_id"]
            + counts["unsupported_event_market_shape"]
            + counts["native_events_with_parseable_pair"]
            + counts["native_events_without_parseable_pair"]),
        "all_candidate_records_ineligible_for_cdb": True,
        "canonical_new_values": 0,
        "provider_requests": 0,
        "cdb_writes": 0,
    }
    if not summary["raw_events_accounted_for"]:
        raise ProviderError("Bulk odds event accounting mismatch")
    return {"summary": summary, "candidates": candidates}
