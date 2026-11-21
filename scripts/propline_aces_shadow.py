"""Isolated PropLine N+ aces research, never an official BlinQ publication.

Use only immutable pre-match bookmaker evidence and the serving ace COUNT
projection's provisional probability function. No provider, CDB or feed writes.
The existing globally serialized private shadow ReleaseStore owns persistence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path

from tbt.services.ace_selection import _history_index, _projection
from tbt.services.projection_odds import _player_ou_probability
from propline_evening_odds import _single_book_quotes, SOURCE_URL, event_odds_url
from propline_evening_quotes import (
    _valid_report, _stamp, _event_identity, _same_person, TZ, FANTASY,
)
from release_store import ReleaseStore

ASSET = "propline_aces_shadow.json"
EXPERIMENT = "propline_aces_milestone_shadow_v1"
MIN_PROBABILITY = 0.60
MIN_EV = 0.0
MIN_LEAD_SECONDS = 600


def _verified_event(event, *, now, target_day):
    """Verify original native evidence, not just parsed/mutable quote rows."""
    if not isinstance(event, dict) or event.get("provider") != "propline":
        return False
    captured, scheduled = _stamp(event.get("captured_at")), _stamp(event.get("scheduled_at"))
    if (not captured or not scheduled or captured >= scheduled
            or scheduled <= now or (scheduled - now).total_seconds() <= MIN_LEAD_SECONDS
            or captured > now or (now - captured).total_seconds() > 86400
            or scheduled.astimezone(TZ).date().isoformat() != target_day):
        return False
    ident = str(event.get("event_id") or "")
    if not ident.isdecimal() or event.get("source_url") not in {SOURCE_URL, event_odds_url(ident)}:
        return False
    raw = event.get("provider_raw_event")
    if (not isinstance(raw, dict) or str(raw.get("id") or "") != ident
            or event.get("players") != [raw.get("home_team"), raw.get("away_team")]
            or _stamp(raw.get("commence_time") or raw.get("start_time")) != scheduled):
        return False
    evidence = json.dumps(raw, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    if sha256(evidence).hexdigest() != event.get("source_sha256"):
        return False
    parsed = []
    for book in raw.get("bookmakers") or []:
        if isinstance(book, dict):
            groups, _ = _single_book_quotes(raw, book)
            parsed.extend(groups)
    return parsed == event.get("aces_markets")


def _selection_status(probability, ev):
    if probability is None:
        return "no_count_projection"
    if probability < MIN_PROBABILITY:
        return "model_probability_below_60pct"
    if ev < MIN_EV:
        return "negative_ev"
    return "qualified"


def build_snapshot(history, predictions, report, *, now, model_sha256):
    """Full sportsbook-price preview, with at most one model pick per fixture.

    Challenger and WTA125 are research-eligible here ONLY; production
    ATP/WTA250+ gates and published picks are not modified.
    """
    if now.tzinfo is None:
        raise ValueError("Shadow requires a timezone-aware actual observation clock")
    now = now.astimezone(timezone.utc)
    if (not isinstance(report, dict)
            or not _valid_report(report, betting_day=report.get("target_betting_day"), now=now)):
        raise ValueError("Unverified, stale, truncated or partial PropLine archive")
    target_day = report["target_betting_day"]
    if not isinstance(model_sha256, str) or len(model_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in model_sha256):
        raise ValueError("Missing exact serving model artifact SHA256")
    if now.astimezone(TZ).date().isoformat() != target_day:
        raise ValueError("Shadow capture must run on the local target calendar day")

    # Same-UTC-day results never enter pre-match feature computation.
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    histories, baseline, _ = _history_index(history, cutoff)
    source = report.get("observed_prematch_priced_events")
    if not isinstance(source, list):
        raise ValueError("Missing archived bookmaker evidence")
    rows, counts = [], {
        "provider_events": len(source), "valid_target_events": 0,
        "identity_missing": 0, "identity_ambiguous": 0,
        "invalid_event_evidence": 0, "raw_quotes": 0,
        "modelled_quotes": 0, "qualified_quotes": 0, "shadow_picks": 0,
        "incremental_provider_requests": 0,
    }
    seen_events = set()
    for event in source:
        start = _stamp(event.get("scheduled_at")) if isinstance(event, dict) else None
        if not start or start.astimezone(TZ).date().isoformat() != target_day or start <= now:
            continue
        ident = str(event.get("event_id") or "")
        if ident in seen_events:
            counts["identity_ambiguous"] += 1
            continue
        seen_events.add(ident)
        if not _verified_event(event, now=now, target_day=target_day):
            counts["invalid_event_evidence"] += 1
            continue
        counts["valid_target_events"] += 1
        fixtures = [(row, _event_identity(event, row)) for row in predictions]
        fixtures = [(row, mapping) for row, mapping in fixtures if mapping is not None]
        if len(fixtures) > 1:
            counts["identity_ambiguous"] += 1
            # A conflicting provider-to-canonical fixture must never be scored.
            continue
        if not fixtures:
            counts["identity_missing"] += 1
        match, mapping = fixtures[0] if fixtures else (None, None)
        projections = {}
        if match is not None:
            p1, p2 = match["player1"], match["player2"]
            player_ids = (str(p1["id"]), str(p2["id"]))
            surface = str(match.get("surface") or "unknown").lower()
            try:
                best_of = int(match["best_of"]) if match.get("best_of") is not None else None
            except (ValueError, TypeError):
                best_of = None
            for slot in (0, 1):
                projections[slot] = _projection(
                    player_ids[slot], player_ids[1-slot], "aces",
                    histories, baseline["aces"], now,
                    surface=surface, best_of=best_of,
                )
        for market in event["aces_markets"]:
            if (market.get("kind") != "player_aces_milestone"
                    or str(market.get("bookmaker") or "").lower() in FANTASY):
                continue
            for quote in market.get("verified_single_prices") or []:
                counts["raw_quotes"] += 1
                player = str(quote.get("player") or "")
                threshold = quote.get("threshold")
                price = quote.get("odds")
                if (not isinstance(threshold, int) or isinstance(threshold, bool)
                        or not 1 <= threshold <= 60
                        or not isinstance(price, (int, float)) or isinstance(price, bool)
                        or not math.isfinite(price) or not 1.01 <= price <= 100
                        or quote.get("bookmaker") != market.get("bookmaker")
                        or quote.get("market_id") != market.get("market_id")
                        or quote.get("equivalent_over_line") != threshold - .5
                        or quote.get("source_selection") != str(threshold) + "+ Aces"):
                    continue
                updated = _stamp(quote.get("last_update"))
                if updated is not None and (updated > now or updated >= start):
                    continue
                selected_slot = None
                projection = None
                if match is not None:
                    candidates = [
                        slot for idx, slot in mapping.items()
                        if _same_person(player, event["players"][idx])
                        and _same_person(player, match["player1" if slot == 0 else "player2"]["name"])
                    ]
                    if len(candidates) == 1:
                        selected_slot = candidates[0]
                        projection = projections.get(selected_slot)
                mean = float(projection["estimate"]) if projection else None
                prob = (_player_ou_probability(mean, "aces", threshold - 0.5)
                        if mean is not None else None)
                ev = prob * float(price) - 1 if prob is not None else None
                status = _selection_status(prob, ev)
                record = {
                    "event_id": ident, "match_id": str(match.get("id")) if match else None,
                    "scheduled_at": start.isoformat(), "players": list(event["players"]),
                    "tour": (str(event.get("provider_raw_event", {}).get("tour") or "")),
                    "tournament": (str(event.get("provider_raw_event", {}).get("tournament") or "")),
                    "bookmaker": market["bookmaker"], "market_id": quote["market_id"],
                    "player": player, "player_id": (
                        str(match["player1" if selected_slot == 0 else "player2"]["id"])
                        if selected_slot is not None else None),
                    "player_slot": selected_slot,
                    "threshold": threshold, "line": threshold - 0.5,
                    "selection": str(threshold) + "+ Aces",
                    "odds": round(float(price), 6),
                    "projection_mean_aces": round(mean, 4) if mean is not None else None,
                    "model_probability": round(prob, 6) if prob is not None else None,
                    "expected_value": round(ev, 6) if ev is not None else None,
                    "samples": int(projection["samples"]) if projection else None,
                    "opponent_allowance_samples": (
                        int(projection["opponent_allowance_samples"]) if projection else None),
                    "model_version": str(match.get("model_version") or "") if match else None,
                    "model_sha256": model_sha256,
                    "model_method": "ace_count_projection_v4_provisional_normal_tail",
                    "quote_captured_at": event["captured_at"],
                    "quote_updated_at": quote.get("last_update"),
                    "source_sha256": event["source_sha256"],
                    "source_url": event["source_url"],
                    "status": status,
                    "research_only": True, "official_publication": False,
                }
                rows.append(record)
                if prob is not None:
                    counts["modelled_quotes"] += 1
                if status == "qualified":
                    counts["qualified_quotes"] += 1

    # Do not equate alternate bookmaker prices or nearby thresholds with
    # the same wager. ONE explicit best contract may be shadow-picked per match.
    best = {}
    for i, row in enumerate(rows):
        if row["status"] != "qualified" or row["match_id"] is None:
            continue
        key = row["match_id"]
        priority = (row["expected_value"], row["model_probability"], row["odds"],
                    -row["threshold"], row["player"], row["bookmaker"])
        if key not in best or priority > best[key][0]:
            best[key] = (priority, i)
    chosen = {v[1] for v in best.values()}
    for i, row in enumerate(rows):
        if row["status"] == "qualified":
            row["status"] = "shadow_pick" if i in chosen else "qualified_not_selected"
    counts["shadow_picks"] = len(chosen)
    return {
        "schema": 1, "experiment": EXPERIMENT,
        "betting_day": target_day, "observed_at": now.isoformat(),
        "source_snapshot_sha256": sha256(
            json.dumps(report, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest(),
        "serving_model_sha256": model_sha256,
        "model_selection_policy": "one_best_per_match_probability_60pct_ev_nonnegative",
        "odds_minimum": None, "model_probability_calibrated": False,
        "source_provider_requests": report["provider_requests"],
        "incremental_provider_requests": 0,
        "source_capture_at": report["captured_at"], "counts": counts,
        "quotes": rows, "official_results_modified": False, "cdb_writes": 0,
    }


def _settle_research(captures, existing, matches, *, now):
    """Append-only count-based research outcomes; never grade official bets."""
    settled = list(existing)
    known = {(r["betting_day"], r["event_id"]) for r in settled}
    by_id = {}
    for match in matches:
        key = str(getattr(match, "match_id", "") or "")
        if key:
            by_id.setdefault(key, []).append(match)
    for capture in captures:
        for quote in capture.get("quotes", []):
            if quote.get("status") != "shadow_pick":
                continue
            key = (capture["betting_day"], quote["event_id"])
            if key in known:
                continue
            linked = by_id.get(quote["match_id"], [])
            if len(linked) != 1:
                continue
            match = linked[0]
            if (not getattr(match, "is_completed", False)
                    or str(getattr(match, "status", "")).lower() not in {"finished", "completed"}
                    or _stamp(getattr(match, "scheduled_at", None)) != _stamp(quote["scheduled_at"])
                    or now <= _stamp(quote["scheduled_at"])):
                continue
            first, second = str(match.player1_id), str(match.player2_id)
            slot = (1 if quote["player_id"] == first else
                    2 if quote["player_id"] == second else None)
            if slot is None:
                continue
            stat = (match.stats if isinstance(match.stats, dict) else {}).get(f"p{slot}_aces")
            if isinstance(stat, bool) or not isinstance(stat, (float, int)) or stat < 0:
                continue
            is_win = stat >= quote["threshold"]
            settled.append({
                "betting_day": capture["betting_day"], "event_id": quote["event_id"],
                "match_id": quote["match_id"], "player_id": quote["player_id"],
                "actual_aces": int(stat), "threshold": quote["threshold"],
                "status": "win" if is_win else "loss",
                "roi_per_unit": round(quote["odds"] - 1 if is_win else -1, 6),
                "evidence": "canonical_cdb_completed_match_count_research_proxy",
                "settled_at": now.isoformat(),
                "official_results_modified": False,
            })
            known.add(key)
    return settled


def capture_in_existing_store(
    store, history, predictions, report, *, observed_at, model_sha256,
    readback_factory=ReleaseStore,
):
    """Only the existing locked shadow release may write this asset."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        from cdb_global_writer_lock import verify
        verify(store.repository, Path(".cdb-global-writer-lock.json"))
    if report is None:
        return {"status": "NO_VALID_ARCHIVE", "provider_requests": 0,
                "public_modified": False}
    snapshot = build_snapshot(
        history, predictions, report, now=observed_at, model_sha256=model_sha256)
    assets = store._asset_names()
    if ASSET in assets:
        store.download(extra_names=(ASSET,), required_names=(ASSET,),
                       require_bundle_manifest=True)
        previous = json.loads((store.directory / ASSET).read_text("utf-8"))
        if (previous.get("schema") != 1 or previous.get("experiment") != EXPERIMENT
                or not isinstance(previous.get("captures"), list)
                or not isinstance(previous.get("settlements"), list)):
            raise ValueError("Incompatible prior immutable PropLine shadow evidence")
    else:
        previous = {"schema": 1, "experiment": EXPERIMENT, "captures": [], "settlements": []}
    captures = list(previous["captures"])
    if snapshot["betting_day"] not in {c["betting_day"] for c in captures}:
        captures.append(snapshot)
    settled = _settle_research(captures, previous["settlements"], history,
                               now=observed_at.astimezone(timezone.utc))
    updated = {**previous, "captures": captures, "settlements": settled}
    summary = {"status": "UNCHANGED", "shadow_days": len(captures),
               "quotes": sum(len(c["quotes"]) for c in captures),
               "selected": sum(c["counts"]["shadow_picks"] for c in captures),
               "research_settled": len(settled),
               "incremental_provider_requests": 0,
               "official_results_modified": False, "cdb_writes": 0}
    if updated == previous:
        return summary
    path = store.directory / ASSET
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2,
                               sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    store.upload_bundle([path])
    # Independent remote download through a fresh ReleaseStore instance.
    reader = readback_factory(store.repository, store.tag,
                              store.directory.parent / "propline-aces-shadow-readback")
    reader.download(extra_names=(ASSET,), required_names=(ASSET,),
                    require_bundle_manifest=True)
    if (reader.directory / ASSET).read_bytes() != path.read_bytes():
        raise RuntimeError("PropLine shadow release remote byte readback mismatch")
    if json.loads((reader.directory / ASSET).read_text("utf-8")) != updated:
        raise RuntimeError("PropLine shadow remote semantic readback mismatch")
    return {**summary, "status": "PRIVATE_READBACK_VERIFIED",
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "current_day": snapshot["betting_day"],
            "current_day_quotes": len(snapshot["quotes"]),
            "current_day_picks": snapshot["counts"]["shadow_picks"]}
