"""Private market-only A0 capture using the EXISTING serialized shadow release writer.

Called only from an authorized prediction refresh after the already-budgeted
Match Winner odds enrichment. Never requests additional provider data, changes
offers or fits/promotes a model. Frozen first-capture rows stay immutable.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from release_store import ReleaseStore
from tbt.services.market_only_shadow_research import (
    _utc, prepare_all_singles_shadow_rows, select_daily_shadow_picks,
    load_shadow_params,
)

ASSET = "market_only_a0_shadow.json"
PARAMS = Path(__file__).resolve().parents[1] / "research/market_only_shadow/params_2026-11-20.json"
MIN_LEAD_SECONDS = 600


def staged_full_slate(predictions, *, observed_at, params):
    """Use full pre-match model slate, NOT only issued TOP/Value predictions.

    A bookmaker price is accepted only when the PRIMARY provider supplied a
    complete same-source two-way contract. Because the existing enrichment
    may stamp a synthetic selection_now, observed_at is a conservative
    real-clock observation instant after the provider calls finished.
    """
    now = _utc(observed_at)
    if now is None:
        raise ValueError("A0 capture requires actual timezone-aware clock")
    staged = []
    stats = {"all_prediction_rows": 0, "eligible_today": 0,
             "priced_primary_complete_two_way": 0, "missing_fair_t3": 0,
             "late_or_invalid": 0}
    for p in predictions:
        stats["all_prediction_rows"] += 1
        if not isinstance(p, dict):
            raise ValueError("Unexpected non-dict winner prediction")
        if str(p.get("prediction_family") or "singles").lower() != "singles":
            continue
        schedule, model_time = _utc(p.get("scheduled_at")), _utc(p.get("created_at"))
        if schedule is None or schedule.date() != now.date():
            continue
        if model_time is None or model_time > now or (
                schedule - now).total_seconds() <= MIN_LEAD_SECONDS:
            stats["late_or_invalid"] += 1
            continue
        p1, p2 = p.get("player1") or {}, p.get("player2") or {}
        if not isinstance(p1, dict) or not isinstance(p2, dict):
            raise ValueError("Ambiguous singles player records")
        first, second = str(p1.get("id") or ""), str(p2.get("id") or "")
        event, match_id = str(p.get("event_id") or ""), str(p.get("id") or "")
        tour = str(p.get("tour") or "").strip().upper()
        if (not first or not second or first == second or not event or not match_id
                or tour not in ("ATP", "WTA")):
            raise ValueError("Missing canonical event/player/tour identity")
        try:
            p_first = float(p1["probability"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("Missing original model probability")
        if not 0 < p_first < 1:
            raise ValueError("Invalid original model probability")
        version = str(p.get("model_version") or "")
        if not version:
            raise ValueError("Prediction is missing frozen model version")
        market = p.get("match_winner_market")
        market = market if isinstance(market, dict) else {}
        valid = (
            market.get("source") == "tennisapi_provider_1"
            and market.get("source_id_known") is True
            and str(market.get("source_id") or "").strip()
            and market.get("provider_id") == 1
        )
        f1 = f2 = None
        if valid:
            try:
                f1, f2 = (float(market["player1_implied_probability"]),
                          float(market["player2_implied_probability"]))
                valid = (0 < f1 < 1 and 0 < f2 < 1
                         and abs(f1 + f2 - 1) < .0001)
            except (KeyError, TypeError, ValueError):
                valid = False
        stats["eligible_today"] += 1
        if valid:
            stats["priced_primary_complete_two_way"] += 1
        else:
            stats["missing_fair_t3"] += 1
        staged.append({
            "event_id": event, "match_id": match_id,
            "model_version": version, "tour": tour,
            "prediction_family": "singles",
            "player1_id": first, "player2_id": second,
            "model_player1_probability": p_first,
            "model_captured_at": model_time.isoformat(),
            "scheduled_at": schedule.isoformat(),
            "competition": str(p.get("competition") or ""),
            "surface": str(p.get("surface") or ""),
            "category_at_capture": "",
            "fair_player1": f1 if valid else None,
            "fair_player2": f2 if valid else None,
            "market_captured_at": now.isoformat() if valid else None,
            "issued_at": now.isoformat() if valid else None,
            "bookmaker": ("tennisapi_provider_1:" + str(market["source_id"])) if valid else "",
            "source_provenance": (
                "provider1_two_way_observed_at_shadow_capture_after_enrichment"
                if valid else "unpriced_model_only_T3"),
        })
    # Never let a duplicate silently collapse a canonical fixture.
    stage = prepare_all_singles_shadow_rows(staged, params)
    by_event = {row["event_id"]: row["match_id"] for row in staged}
    for row in stage:
        row["match_id"] = by_event[row["event_id"]]
    return stage, stats


def _cards(snapshots):
    cards = []
    for row in snapshots:
        p = float(row["model_player1_probability"])
        choose_first = p >= .5
        price = (row.get("fair_player1") if choose_first
                 else row.get("fair_player2"))
        pick = row["player1_id"] if choose_first else row["player2_id"]
        cards.append({
            "event_id": row["event_id"],
            "model_version": row["model_version"],
            "tour": row["tour"], "competition": row.get("competition") or "",
            "prediction_family": "singles",
            "scheduled_at": row["scheduled_at"],
            "created_at": row["model_captured_at"],
            "issued_at": row.get("issued_at"),
            "player1": {"id": row["player1_id"]},
            "player2": {"id": row["player2_id"]},
            "winner_id": pick, "probability": max(p, 1-p),
            "betting": {
                "market": "match_winner", "selection_id": pick,
                "fair_implied_probability": price,
                "captured_at": row.get("market_captured_at"),
            },
        })
    return cards


def first_capture_update(previous, stage, completed, *, now, params):
    """Pure append/settlement; no CDB mutations or reselection after first day."""
    clock = _utc(now)
    if clock is None:
        raise ValueError("A0 requires a timezone-aware observation clock")
    if previous is not None and (not isinstance(previous, dict)
                                 or previous.get("schema") != 1):
        raise ValueError("Unrecognized existing private A0 ledger")
    prev = previous or {
        "schema": 1, "experiment": "market_only_A0",
        "snapshots": [], "issued_shadow": [], "settlements": [],
        "frozen_model_version": None,
    }
    snaps = [dict(row) for row in prev["snapshots"]]
    issued = [dict(row) for row in prev["issued_shadow"]]
    settlements = [dict(row) for row in prev["settlements"]]
    existing_events = {}
    for row in snaps:
        event = str(row.get("event_id") or "")
        if not event or event in existing_events:
            raise ValueError("Duplicate/blank prior A0 canonical event identity")
        existing_events[event] = row
    accepted = []
    # A0 selection is fixed by the first daily slate. Later discovered
    # matches remain in the unbiased model/market cohort, but cannot rewrite
    # that day's immutable issued selections.
    issued_days = {str(r.get("day_utc") or "") for r in issued}
    freeze = _utc(params["prospective"]["freeze_after_utc"])
    if freeze is None or clock <= freeze:
        raise ValueError("No snapshots may precede frozen research date")
    version = prev.get("frozen_model_version")
    for row in stage:
        if _utc(row["model_captured_at"]) <= freeze:
            continue
        event = row["event_id"]
        if version is not None and row["model_version"] != version:
            raise ValueError("Champion model changed during immutable A0 cohort")
        if event in existing_events:
            old = existing_events[event]
            for name in ("match_id", "player1_id", "player2_id", "tour",
                         "scheduled_at", "model_version"):
                if row.get(name) != old.get(name):
                    raise ValueError("Canonical A0 event identity changed: " + name)
            continue
        if version is None:
            version = row["model_version"]
        immutable = dict(row)
        day = _utc(row["scheduled_at"]).date().isoformat()
        immutable["a0_first_daily_slate"] = day not in issued_days
        accepted.append(immutable)
        existing_events[event] = immutable
    # First available full-slate capture freezes the daily candidate selection.
    # Later same-day fixtures may be logged, but do not replace issued tips.
    snapshots_after = snaps + accepted
    already_issued_days = {r["day_utc"] for r in issued}
    new_by_day = {}
    for row in accepted:
        day = _utc(row["scheduled_at"]).date().isoformat()
        if row["a0_first_daily_slate"] and day not in already_issued_days:
            new_by_day.setdefault(day, []).append(row)
    for day in sorted(new_by_day):
        ranked = select_daily_shadow_picks(_cards(new_by_day[day]), params, n_min=5)
        for card in ranked:
            if _utc(card["scheduled_at"]) <= clock:
                raise ValueError("Cannot issue shadow after actual scheduled start")
            event, selection = card["event_id"], card["betting"]["selection_id"]
            digest = hashlib.sha256(
                (event + "|" + version + "|" + selection + "|"
                 + clock.isoformat()).encode("utf-8")
            ).hexdigest()
            issued.append({
                "event_id": event, "selection_id": selection,
                "day_utc": day, "selection_tier": card["selection_tier"],
                "selection_basis": card["selection_basis"],
                "shadow_issued_at": clock.isoformat(),
                "receipt_id": digest,
                "research_only": True, "publication_modified": False,
            })
    done_by_match = {}
    for match in completed:
        if not getattr(match, "is_completed", False):
            continue
        ident = str(getattr(match, "match_id", "") or "")
        if ident in done_by_match:
            raise ValueError("Duplicate completed CDB match ID")
        done_by_match[ident] = match
    settled_ids = {r["event_id"] for r in settlements}
    for row in snapshots_after:
        if row["event_id"] in settled_ids:
            continue
        match = done_by_match.get(row["match_id"])
        if match is None:
            continue
        if (getattr(match, "winner_id", None) not in
                {row["player1_id"], row["player2_id"]}):
            raise ValueError("Completed CDB outcome has conflicting players")
        if _utc(match.scheduled_at) != _utc(row["scheduled_at"]):
            # Quarantine changed schedules, never silently backfill outcomes.
            continue
        if clock <= _utc(row["scheduled_at"]):
            continue
        settlements.append({
            "event_id": row["event_id"], "match_id": row["match_id"],
            "status": "settled", "winner_id": match.winner_id,
            "settled_at": clock.isoformat(),
            "outcome_source": "canonical_cdb_match_id_exact",
        })
    updated = {**prev, "snapshots": snapshots_after, "issued_shadow": issued,
               "settlements": settlements, "frozen_model_version": version}
    return updated, {
        "new_captured": len(accepted),
        "new_issued": len(issued)-len(prev["issued_shadow"]),
        "new_settled": len(settlements)-len(prev["settlements"]),
        "total_captured": len(updated["snapshots"]),
        "total_issued": len(updated["issued_shadow"]),
        "total_settled": len(updated["settlements"]),
    }


def capture_using_existing_shadow_store(
    store, predictions, completed, *, observed_at, params_path=PARAMS,
    readback_factory=ReleaseStore,
):
    """Use existing provider-native ReleaseStore and its SINGLE writer/lock.

    This does not make a second workflow or service writer. Fail closed if a
    writer lock is unavailable in GitHub Actions. Independent second store
    checks persisted bytes, not the writer's success message.
    """
    if os.getenv("GITHUB_ACTIONS") == "true":
        from cdb_global_writer_lock import verify
        verify(store.repository, Path(".cdb-global-writer-lock.json"))
    params = load_shadow_params(params_path)
    stage, coverage = staged_full_slate(predictions, observed_at=observed_at, params=params)
    names = store._asset_names()
    if ASSET in names:
        store.download(extra_names=(ASSET,), required_names=(ASSET,),
                       require_bundle_manifest=True)
        prior = json.loads((store.directory / ASSET).read_text("utf-8"))
    else:
        prior = None
    updated, counters = first_capture_update(
        prior, stage, completed, now=observed_at, params=params)
    out = {"coverage": coverage, **counters, "provider_requests": 0,
           "production_modified": False, "writer": "existing_private_shadow_store",
           "schema": 1, "status": "NO_CHANGE"}
    if prior is not None and updated == prior:
        return out
    path = store.directory / ASSET
    path.write_text(json.dumps(updated, indent=2, ensure_ascii=False,
                               sort_keys=True, allow_nan=False)+"\n",
                    encoding="utf-8")
    store.upload_bundle([path])
    # Fresh remote readback after the release store has committed its manifest.
    reader = readback_factory(store.repository, store.tag,
                              store.directory.parent / "market-a0-readback")
    reader.download(extra_names=(ASSET,), required_names=(ASSET,),
                    require_bundle_manifest=True)
    if (reader.directory / ASSET).read_bytes() != path.read_bytes():
        raise RuntimeError("A0 shadow remote readback byte mismatch")
    confirmed = json.loads((reader.directory / ASSET).read_text("utf-8"))
    if confirmed != updated:
        raise RuntimeError("A0 shadow remote semantic readback mismatch")
    return {**out, "status": "PRIVATE_READBACK_VERIFIED",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
