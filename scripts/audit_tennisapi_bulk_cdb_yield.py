"""Bounded TennisApi bulk/source -> current private CDB overlap, research only.

Reads ONLY SHA-verified local canonical snapshots; provider quota and raw
responses stay inside an ephemeral GitHub runner. Zero remote CDB writes.
Source-native IDs alone are NEVER equivalent to canonical BlinQ match IDs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.tennisapi_bulk import normalize_daily_bulk_odds
from tbt.errors import ProviderError
from audit_tennisapi_prediction_signals import source_event


CORE_FIELDS = ("service_points_won", "return_points_won",
               "aces", "double_faults", "break_point_serve_win",
               "break_point_return_win")
MAX_PAID = 12
TOURS = {"atp", "wta"}


def native_id_claims(match):
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    markers = [
        raw.get("_tbt_provider_event_id"),
        raw.get("event_id"),
        raw.get("eventId"),
        raw.get("id"),
    ]
    for key in ("_tbt_event_identity", "_tbt_statistics", "_tbt_statistics_by_set",
                "_tbt_tennisapi_markets"):
        value = raw.get(key)
        if isinstance(value, dict):
            markers.append(value.get("event_id"))
    claims = set()
    for marker in markers:
        if (type(marker) in (str, int) and str(marker).isascii()
                and str(marker).isdecimal() and int(marker) > 0):
            claims.add(int(marker))
    return claims


def canonical_index(matches):
    ids = defaultdict(list)
    counts = Counter()
    seen = set()
    for match in matches:
        mid = str(match.match_id)
        if not mid or mid in seen:
            raise ValueError("Canonical match_id missing or duplicated")
        seen.add(mid)
        if match.tour not in TOURS or match.scheduled_at.year not in (2023, 2026):
            raise ValueError("Canonical unexpected scope")
        counts["canonical_rows"] += 1
        native = native_id_claims(match)
        if len(native) > 1:
            counts["canonical_conflicting_native_claim_rows"] += 1
            continue
        if not native:
            counts["canonical_without_native_claim"] += 1
            continue
        ids[next(iter(native))].append(match)
        counts["canonical_single_native_claim_rows"] += 1
    return ids, dict(counts)


def exact_link(row, index):
    """Every claimed link must independently agree on exact match identity."""
    candidates = index.get(row["event_id"], [])
    if not candidates:
        return "unlinked_source_id", None
    if len(candidates) != 1:
        return "ambiguous_canonical_native_id", None
    match = candidates[0]
    when = match.scheduled_at.astimezone(timezone.utc).date().isoformat()
    pair = {str(match.player1_id), str(match.player2_id)}
    source_pair = {str(row["home_id"]), str(row["away_id"])}
    if (when != row["utc_day"] or match.tour != row["tour"]
            or pair != source_pair or len(pair) != 2
            or (match.winner_id is not None
                and str(match.winner_id) != str(row["winner_id"]))):
        return "identity_conflict", None
    return "linked_exact_native_id_pair_date_tour_winner", match


def _rows(payload):
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return payload["events"]
    return []


def _digest(payload):
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str).encode()
    return hashlib.sha256(data).hexdigest()


def run(provider, matches, *, max_requests=MAX_PAID):
    if type(max_requests) is not int or not 1 <= max_requests <= MAX_PAID:
        raise ValueError("Audit allowed only 1..12 billed requests")
    provider.retry_attempts = 1
    provider.request_limit = min(provider.request_limit, max_requests)
    idx, cdb_counts = canonical_index(matches)
    meta = {}
    counts = Counter()
    observed: dict[int, dict] = {}
    conflicts = set()
    events_by_route = {}
    reply_status = {}
    http = getattr(provider, "client", None)
    def on_response(response):
        reply_status["status"] = response.status_code
        reply_status["header"] = (
            "x-ratelimit-requests-remaining" in response.headers)
    if hasattr(http, "event_hooks") and isinstance(http.event_hooks, dict):
        http.event_hooks.setdefault("response", []).append(on_response)

    def read(name, path, kind):
        if provider.request_count >= max_requests:
            meta[name] = {"state": "budget_cap", "requests": 0}
            return {}
        before = provider.request_count
        reply_status.clear()
        try:
            payload = provider._get(path, enrichment=True)
        except Exception as exc:
            meta[name] = {"state": "error", "error_type": type(exc).__name__,
                          "http_status": reply_status.get("status"),
                          "requests": provider.request_count-before}
            # A failed/frozen shared budget is authoritative and terminates
            # this audit. Never repeat paid provider failures blindly.
            raise
        meta[name] = {"state": "available" if payload not in (None, {}, []) else "no_content",
                      "http_status": reply_status.get("status"),
                      "quota_header_confirmed": reply_status.get("header"),
                      "requests": provider.request_count-before,
                      "sha256": _digest(payload)}
        if kind == "events":
            rows = _rows(payload)
            meta[name]["raw_rows"] = len(rows)
            ids = [v.get("id") for v in rows
                   if isinstance(v, dict) and type(v.get("id")) is int
                   and v["id"] > 0]
            meta[name]["unique_event_ids"] = len(set(ids))
            meta[name]["duplicate_event_ids"] = len(ids)-len(set(ids))
            events_by_route[name] = set(ids)
            for raw in rows:
                row, why = source_event(raw)
                counts[f"source_{why}"] += 1
                if row is None:
                    continue
                ident = (row["utc_day"], row["tour"],
                         row["unique_tournament_id"], row["home_id"],
                         row["away_id"], row["winner_id"])
                eid = row["event_id"]
                if eid in conflicts:
                    continue
                if eid in observed and observed[eid]["identity"] != ident:
                    counts["quarantine_conflicting_source_native_id"] += 1
                    conflicts.add(eid)
                    del observed[eid]
                elif eid not in observed:
                    observed[eid] = {"row": row, "identity": ident}
                else:
                    counts["same_event_across_routes"] += 1
        return payload

    # Source 2023 Australian Open round; independently documented native IDs.
    prefix = "/api/tennis/tournament/2363/season/48186"
    read("ao_2023_round_32", prefix + "/events/round/32/slug/round-of-64", "events")
    read("ao_2023_season_page_0", prefix + "/events/last/0", "events")
    read("ao_2023_tournament_2023_01_18",
         "/api/tennis/tournament/2363/schedules/18/1/2023", "events")

    # Dynamic 2026 witness must match the source before spending on its
    # tournament. If missing, stop rather than inventing context/IDs.
    detail = read("2026_source_witness", "/api/tennis/event/17449516", "metadata")
    witness = detail.get("event", detail) if isinstance(detail, dict) else {}
    witness_id = witness.get("id") if isinstance(witness, dict) else None
    if witness_id != 17449516:
        raise ValueError("Source event witness mismatched, no 2026 candidate calls")
    tournament = witness.get("tournament")
    season = witness.get("season")
    home = witness.get("homeTeam")
    if (not isinstance(tournament, dict) or
            not isinstance(tournament.get("uniqueTournament"), dict) or
            not isinstance(season, dict) or not isinstance(home, dict)):
        raise ValueError("Missing source-native season/tournament/player")
    tid = tournament["uniqueTournament"].get("id")
    sid = season.get("id")
    player = home.get("id")
    stamp = witness.get("startTimestamp")
    if any(type(v) is not int or v < 1 for v in (tid, sid, player, stamp)):
        raise ValueError("Invalid source-native witness metadata")
    day = datetime.fromtimestamp(stamp, timezone.utc).date()
    if day.year != 2026:
        raise ValueError("Expected witness in 2026")
    meta["witness"] = {"state": "source_context_confirmed", "year": 2026}
    read("2026_tournament_season_page_0",
         f"/api/tennis/tournament/{tid}/season/{sid}/events/last/0", "events")
    read("2026_tournament_day",
         f"/api/tennis/tournament/{tid}/schedules/{day.day}/{day.month}/{day.year}", "events")
    read("2026_player_month",
         f"/api/tennis/player/{player}/events/{day.month:02d}/{day.year}", "events")

    # The daily odds route is a potentially very large price map. Only
    # compare its ID keys against canonical native claims: NO pre-match
    # time validity and NO inferred bookmaker/provider crosswalk.
    odds = read("2026_daily_odds",
                f"/api/tennis/events/odds/{day.day}/{day.month}/{day.year}", "metadata")
    data = odds.get("odds") if isinstance(odds, dict) else None
    valid_keys = []
    if isinstance(data, dict):
        for key in data:
            if isinstance(key, str) and key.isascii() and key.isdecimal() and int(key)>0:
                valid_keys.append(int(key))
        meta["2026_daily_odds"]["raw_native_keys"] = len(data)
        meta["2026_daily_odds"]["valid_native_keys"] = len(valid_keys)
        meta["2026_daily_odds"]["duplicate_native_keys"] = len(valid_keys)-len(set(valid_keys))
        meta["2026_daily_odds"]["native_keys_in_cdb"] = sum(e in idx for e in valid_keys)
        meta["2026_daily_odds"]["native_keys_without_cdb_claim"] = sum(e not in idx for e in valid_keys)
        meta["2026_daily_odds"]["verified_pre_match_quotes"] = 0
        meta["2026_daily_odds"]["canonical_odds_import_authorized"] = False
        # This SAME paid daily response can include 700–1,000 selection pairs.
        # Parse them all and count candidate/native-claim overlap WITHOUT
        # treating event-key overlap as verified bookmaker/market/time identity.
        try:
            intake = normalize_daily_bulk_odds(odds)
        except ProviderError:
            meta["2026_daily_odds"]["bulk_pair_intake_state"] = "unsupported_shape"
        else:
            candidates = intake["candidates"]
            ids = {int(row["source_event_id"]) for row in candidates}
            meta["2026_daily_odds"]["bulk_pair_intake"] = intake["summary"]
            meta["2026_daily_odds"]["candidate_native_events_with_single_cdb_claim"] = sum(
                len(idx.get(ident, [])) == 1 for ident in ids
            )
            meta["2026_daily_odds"]["candidate_native_events_with_ambiguous_cdb_claim"] = sum(
                len(idx.get(ident, [])) > 1 for ident in ids
            )
            meta["2026_daily_odds"]["candidate_native_events_without_cdb_claim"] = sum(
                not idx.get(ident) for ident in ids
            )
            meta["2026_daily_odds"]["candidate_identity_verified_against_cdb"] = 0
            meta["2026_daily_odds"]["validated_historical_quote_pairs"] = 0
            meta["2026_daily_odds"]["cdb_odds_writes"] = 0
    else:
        meta["2026_daily_odds"]["shape_unverified"] = True

    winning = read("2026_witness_winning_odds",
                   "/api/tennis/event/17449516/provider/1/winning-odds", "metadata")
    meta["2026_witness_winning_odds"]["home_away_keys"] = (
        isinstance(winning, dict)
        and isinstance(winning.get("home"), dict)
        and isinstance(winning.get("away"), dict))
    meta["2026_witness_winning_odds"]["verified_pre_match_quotes"] = 0
    # Exact odds/market alternative; one call cannot prove history or timestamp.
    market = read("2026_witness_all_odds",
                  "/api/tennis/event/17449516/odds/1/all", "metadata")
    meta["2026_witness_all_odds"]["markets_list_rows"] = (
        len(market.get("markets")) if isinstance(market, dict)
        and isinstance(market.get("markets"), list) else None)
    meta["2026_witness_all_odds"]["verified_pre_match_quotes"] = 0

    statuses = Counter()
    nulls = Counter()
    for item in observed.values():
        status, match = exact_link(item["row"], idx)
        statuses[status] += 1
        if match is not None:
            stats = match.stats or {}
            for key in CORE_FIELDS:
                for side in ("p1","p2"):
                    if stats.get(f"{side}_{key}") is None:
                        nulls[key] += 1
    cross_routes = {}
    base = events_by_route.get("ao_2023_round_32", set())
    for name, ids in events_by_route.items():
        cross_routes[name] = {
            "unique_event_ids": len(ids),
            "ao_2023_round_intersection": len(base & ids) if name.startswith("ao_2023") else None,
        }
    result = {
        "schema": 1, "scope": "ATP_WTA_2023_2026_CDB_EXACT_READ_ONLY",
        "provider_requests_including_retries": provider.request_count,
        "planned_request_ceiling": max_requests,
        "canonical": cdb_counts,
        "source": {
            "raw_event_rows": sum(v.get("raw_rows",0) for v in meta.values()),
            "unique_eligible_native_event_ids": len(observed),
            "quarantined_native_event_ids": len(conflicts),
            "status_counts": dict(statuses),
            "validation_counts": dict(counts),
            "overlap_by_route": cross_routes,
        },
        "canonical_missing_fields_in_exact_linked_matches": dict(nulls),
        "endpoint": meta,
        "verified_net_new_cdb_matches": 0,  # unlinked != safe net-new
        "verified_net_new_cdb_statistic_values": 0,  # match event list is not a stats endpoint
        "verified_historical_prematch_odds": 0,
        "cdb_writes": 0, "model_changes": 0,
        "production_route_switched": False,
        "note": ("Missing source ID claim does not prove missing CDB match; "
                 "cross-route IDs must pass participant+tour+day+winner and no "
                 "post-match bookmaker odds may become retrospective prices."),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--max-requests", type=int, default=MAX_PAID)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing overwrite of existing audit report")
    matches = load_partitions(args.history_dir)
    client = RapidTennisClient()
    try:
        report = run(client, matches, max_requests=args.max_requests)
    finally:
        client.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":"READ_ONLY_OVERLAP_COMPLETE",
        "requests":report["provider_requests_including_retries"],
        "source":report["source"],
        "cdb_writes":0,
    },sort_keys=True))


if __name__=="__main__":
    main()
