"""Prospective selector SHADOW on the existing native prediction release.

No model fitting, new provider requests, second writer, CDB mutations, or
change to live selection. Three policy variants see the SAME real pre-start
singles input slate. First capture per betting day is immutable, paired with
canonical post-match winners only during read-only evaluation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from unittest.mock import patch

from .market_selection import select_market_sections
from .market_anchored_rank import _ts, _num

SCHEMA = 1
MIN_LEAD_SECONDS = 600
SECTIONS = {"top": "top_daily_picks", "prime": "prime_picks", "value": "value_picks"}
VARIANTS = {
    "champion": {"TBT_RANK_SOURCE": "model", "TBT_TOP_REQUIRE_MARKET_SIDE": "false",
                 "TBT_TOP_EMERGENCY_FILL": "false"},
    "market_anchored": {"TBT_RANK_SOURCE": "market_anchored",
                        "TBT_TOP_REQUIRE_MARKET_SIDE": "false",
                        "TBT_TOP_EMERGENCY_FILL": "false"},
    "market_anchored_top_veto": {"TBT_RANK_SOURCE": "market_anchored",
                                "TBT_TOP_REQUIRE_MARKET_SIDE": "true",
                                "TBT_TOP_EMERGENCY_FILL": "false"},
}
POLICY_ID = "rank_80_20_top_veto_2026_11_21"


def _quote_fair(row, now):
    """Prove a complete two-way same-book quote, observed before match start.

    Some production provider adapters synthesize a selection-time timestamp.
    Use the *real clock after odds enrichment* to establish pre-start validity.
    The original capture field remains visible as provenance, not as proof.
    """
    market = row.get("match_winner_market")
    betting = row.get("betting")
    if not isinstance(market, dict) or not isinstance(betting, dict):
        return None
    if betting.get("market") != "match_winner":
        return None
    one = _num(market.get("player1_implied_probability"))
    two = _num(market.get("player2_implied_probability"))
    p1 = (row.get("player1") or {}).get("id")
    p2 = (row.get("player2") or {}).get("id")
    selection = str(betting.get("selection_id") or "")
    if not all((p1, p2, selection)) or str(p1) == str(p2):
        return None
    if not (one is not None and two is not None
            and 0 < one < 1 and 0 < two < 1
            and abs(one + two - 1.0) <= 0.0001):
        return None
    bid, mid = betting.get("provider_id"), market.get("provider_id")
    if str(bid) != str(mid) or str(bid) not in ("1", "2"):
        return None
    if str(bid) == "1":
        source_ok = (market.get("source") == "tennisapi_provider_1"
                     and market.get("source_id_known") is True
                     and bool(str(market.get("source_id") or "").strip()))
    else:
        source_ok = (market.get("source") == "propline"
                     and bool(str(market.get("bookmaker") or "").strip())
                     and bool(str(market.get("provider_event_id") or "").strip()))
    if not source_ok:
        return None
    fair = one if selection == str(p1) else two if selection == str(p2) else None
    betting_fair = _num(betting.get("fair_implied_probability"))
    if fair is None or betting_fair is None or abs(betting_fair - fair) > 0.0001:
        return None
    original_quote_time = _ts(betting.get("captured_at"))
    if original_quote_time is not None and original_quote_time > now:
        return None
    return fair


def build_market_rank_shadow(predictions, *, observed_at, public_offer_day,
                             champion_sha256):
    """Pure from API data: snapshot no published picks, no after-start odds.

    Runs during the existing pending prediction-release assembly, before its
    SINGLE upload_bundle. For consistency, all policy runs operate on copies
    of the same complete model-discovered, pre-start candidate input.
    """
    clock = _ts(observed_at)
    if clock is None:
        raise ValueError("Shadow observation must use real timezone-aware clock")
    if not (isinstance(champion_sha256, str) and len(champion_sha256) == 64
            and all(ch in "0123456789abcdef" for ch in champion_sha256)):
        raise ValueError("Exact champion artifact SHA256 required")
    if not isinstance(public_offer_day, str) or not public_offer_day:
        raise ValueError("Public betting-day key required")
    prepared, eligible = [], {}
    counts = {"all_model_singles": 0, "future_prestart": 0,
              "complete_prestart_fair": 0, "model_fallback": 0,
              "near_start_or_late": 0, "invalid_identity": 0}
    for source in predictions:
        if not isinstance(source, dict) or source.get("prediction_family") == "doubles":
            continue
        counts["all_model_singles"] += 1
        start, created = _ts(source.get("scheduled_at")), _ts(source.get("created_at"))
        if start is None or created is None or created > clock or (
                start - clock).total_seconds() <= MIN_LEAD_SECONDS:
            counts["near_start_or_late"] += 1
            continue
        p1, p2 = source.get("player1"), source.get("player2")
        if not (isinstance(p1, dict) and isinstance(p2, dict)
                and str(p1.get("id") or "") and str(p2.get("id") or "")
                and str(p1.get("id")) != str(p2.get("id"))
                and str(source.get("event_id") or "")
                and str(source.get("id") or "")
                and str(source.get("model_version") or "")):
            counts["invalid_identity"] += 1
            continue
        event = str(source["event_id"])
        if event in eligible:
            raise ValueError("Duplicate canonical event in prospective shadow slate")
        copied = deepcopy(source)
        betting = copied.get("betting")
        if isinstance(betting, dict) and betting.get("market") == "match_winner":
            fair = _quote_fair(source, clock)
            # The observed_at clock, NOT a projected selection time, proves
            # this quote was present before scheduled start.
            betting["source_captured_at"] = betting.get("captured_at")
            betting["captured_at"] = clock.isoformat()
            betting["fair_implied_probability"] = fair
            if fair is not None:
                counts["complete_prestart_fair"] += 1
            else:
                counts["model_fallback"] += 1
        else:
            counts["model_fallback"] += 1
        eligible[event] = copied
        prepared.append(copied)
        counts["future_prestart"] += 1

    if not prepared:
        return None, counts
    variants = {}
    for name, env in VARIANTS.items():
        # No public flags are touched permanently; all mutations are in
        # short-lived deepcopied selector rows of this single-threaded job.
        with patch.dict(os.environ, env):
            result = select_market_sections(
                prepared, public_offer_day=public_offer_day)
        sections = {}
        for section, key in SECTIONS.items():
            receipt_rows = []
            for card in result.get(key, []):
                event = str(card.get("event_id") or "")
                source = eligible.get(event)
                if source is None:
                    raise ValueError("Selector issued fixture not in frozen input slate")
                betting = card.get("betting") or {}
                selection = str(betting.get("selection_id") or "")
                p1 = str(source["player1"]["id"])
                p2 = str(source["player2"]["id"])
                if selection not in (p1, p2):
                    raise ValueError("Shadow selection side not a canonical player")
                receipt = {
                    "event_id": event, "match_id": str(source["id"]),
                    "selected_player_id": selection,
                    "player1_id": p1, "player2_id": p2,
                    "scheduled_at": source["scheduled_at"],
                    "model_version": str(source["model_version"]),
                    "shadow_issued_at": clock.isoformat(),
                    "section": section,
                    "selection_tier": card.get("selection_tier"),
                    "rank_source": card.get("rank_source") or "model",
                    "model_probability": _num(card.get("probability")),
                    "rank_probability": _num(card.get("rank_probability")),
                    "fair_probability": _num(betting.get("fair_implied_probability")),
                    "bookmaker_odds": _num(betting.get("odds")),
                    "quote_observed_at": clock.isoformat(),
                    "source_captured_at": betting.get("source_captured_at"),
                    "research_only": True,
                    "public_issued": False,
                }
                receipt["receipt_id"] = sha256((
                    champion_sha256 + "|" + public_offer_day + "|" + name
                    + "|" + section + "|" + event + "|" + selection
                    + "|" + clock.isoformat()).encode()).hexdigest()
                receipt_rows.append(receipt)
            sections[section] = receipt_rows
        variants[name] = sections
    capture = {
        "schema": SCHEMA, "policy_id": POLICY_ID,
        "status": "PROSPECTIVE_SHADOW_FIRST_CAPTURE",
        "model_sha256": champion_sha256,
        "captured_at": clock.isoformat(), "public_offer_day": public_offer_day,
        "universe": counts,
        "input_event_ids": sorted(eligible),
        "scope_limit": "provider_discovered_fixtures_only_not_proven_complete",
        "variants": variants,
    }
    capture["sha256"] = sha256(json.dumps(
        capture, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return capture, counts


def validate_frozen_capture(capture):
    if not isinstance(capture, dict) or capture.get("schema") != SCHEMA:
        raise ValueError("Invalid prospective shadow schema")
    digest = capture.get("sha256")
    payload = {k: v for k, v in capture.items() if k != "sha256"}
    expected = sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    if digest != expected:
        raise ValueError("Prospective shadow immutable digest mismatch")
    if set(capture.get("variants") or {}) != set(VARIANTS):
        raise ValueError("Missing prospective shadow policy variant")
    return True


def first_day_shadow(history, *, public_offer_day):
    """Fetch original day receipt, never re-rank/reissue after the first capture."""
    found = []
    for snapshot in (history.get("snapshots") or []):
        capture = snapshot.get("market_rank_shadow")
        if capture is None:
            continue
        validate_frozen_capture(capture)
        if capture.get("public_offer_day") == public_offer_day:
            found.append(capture)
    if len(found) > 1:
        raise ValueError("Multiple shadow issuance snapshots for same day")
    return found[0] if found else None


def settled_comparison(history, matches, *, asof):
    """Read-only matching by canonical match ID, exact participants and start.

    Does not mutate immutable receipts; settlement winners come from canonical
    completed match history, NOT the current model prediction or future quote.
    """
    clock = _ts(asof)
    if clock is None:
        raise ValueError("Settlement report clock must be aware")
    by_match = {}
    for match in matches:
        if not getattr(match, "is_completed", False):
            continue
        mid = str(getattr(match, "match_id", "") or "")
        if mid and mid in by_match:
            raise ValueError("Duplicate completed canonical match ID")
        if mid:
            by_match[mid] = match

    captures = []
    for snap in history.get("snapshots", []):
        c = snap.get("market_rank_shadow")
        if c is not None:
            validate_frozen_capture(c)
            captures.append(c)
    seen_days = set()
    totals = {v: {s: {"issued": 0, "settled": 0, "correct": 0,
                       "staked": 0, "gross_return": 0.0}
                  for s in SECTIONS} for v in VARIANTS}
    for c in captures:
        day = c["public_offer_day"]
        if day in seen_days:
            raise ValueError("Duplicate shadow capture betting day in history")
        seen_days.add(day)
        for variant, sections in c["variants"].items():
            for section, receipts in sections.items():
                dest = totals[variant][section]
                for item in receipts:
                    dest["issued"] += 1
                    match = by_match.get(item["match_id"])
                    start = _ts(item.get("scheduled_at"))
                    issued = _ts(item.get("shadow_issued_at"))
                    if (match is None or start is None or issued is None
                        or issued >= start or clock <= start
                        or _ts(match.scheduled_at) != start
                        or {str(match.player1_id), str(match.player2_id)}
                            != {item["player1_id"], item["player2_id"]}
                        or str(match.winner_id) not in
                            {item["player1_id"], item["player2_id"]}):
                        continue
                    dest["settled"] += 1
                    dest["staked"] += 1
                    if str(match.winner_id) == item["selected_player_id"]:
                        dest["correct"] += 1
                        if (_num(item.get("bookmaker_odds")) or 0) > 1:
                            dest["gross_return"] += float(item["bookmaker_odds"])
    for v in totals.values():
        for s in v.values():
            s["hit_rate"] = (s["correct"] / s["settled"]
                             if s["settled"] else None)
            s["flat_stake_roi"] = (s["gross_return"] / s["staked"] - 1.0
                                   if s["staked"] and s["settled"] == s["staked"] else None)
    return {
        "schema": SCHEMA, "status": "DIAGNOSTIC_NOT_A_MODEL_PROMOTION",
        "frozen_days": len(seen_days), "variants": totals,
        "provider_requests": 0, "production_modified": False,
        "limitations": "no guaranteed full-provider universe; no causal or holdout proof",
    }
