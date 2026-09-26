from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from download_tennis_history import read_json, write_json
from history_download_budget import LocalRequestBudget, reserve_allocation
from release_store import ReleaseStore
from tbt.config import settings
from tbt.data.history_snapshot import (
    load_partitions,
    sync_year_partition,
    _provider_event_id,
)
from tbt.data.history_safety import sanitize_history_identities, merge_trusted_history_batch
from tbt.models.artifact import load_model, save_model
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.engine import predict, reconcile_ledger, serving_feed
from tbt.services.publication import (
    validate_market_publication_candidate,
    restore_published_market_snapshots,
    carry_forward_betting_day_market_rows,
    build_daily_offer_snapshot,
    validate_publication_candidate,
)
from tbt.services.ace_selection import select_ace_picks
from tbt.services.sg_selection import select_sg_picks
from tbt.services.projection_odds import (
    enrich_projection_odds, prefetch_projection_market_board,
    extract_match_total_odds,
)
from tbt.services.indicative_odds import annotate_feed_indicative_odds
from tbt.services.doubles_selection import (
    build_predictions as build_doubles_predictions,
    select_picks as select_doubles_picks,
    merge_history as merge_doubles_history,
    history_report as doubles_history_report,
    walk_forward_validation as validate_doubles_history,
)
from tbt.services.comeback_projection import annotate_live_second_set_projections
from tbt.services.market_selection import (
    annotate_market_publication_candidates,
    attach_market_sections_to_feed,
    enrich_current_betting_day_odds,
)
from tbt.services.training import train_from_matches
from tbt.services.backtest_service import walk_forward_backtest


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value



def _promotion_metric_gate(report):
    """Predeclared probabilistic gate against Elo on the same untouched holdout.

    Lower is better for log loss, Brier and ECE. Accuracy must not regress.
    At least one probabilistic metric must improve strictly.
    """
    holdout = report.get("holdout") or {}
    delta = report.get("delta_vs_elo") or {}

    required = (
        "accuracy",
        "log_loss",
        "brier_score",
        "ece_10",
    )
    if int(holdout.get("n") or 0) < 200:
        return False, ["holdout_n_below_200"]

    missing = [
        key
        for key in required
        if delta.get(key) is None
        or not math.isfinite(float(delta.get(key)))
    ]
    if missing:
        return False, ["missing_or_nonfinite_" + key for key in missing]

    reasons = []
    if float(delta["accuracy"]) < 0.0:
        reasons.append("accuracy_worse_than_elo")
    if float(delta["log_loss"]) > 0.0:
        reasons.append("log_loss_worse_than_elo")
    if float(delta["brier_score"]) > 0.0:
        reasons.append("brier_worse_than_elo")
    if float(delta["ece_10"]) > 0.0:
        reasons.append("ece_worse_than_elo")

    probabilistic_improvement = any(
        float(delta[key]) < 0.0
        for key in (
            "log_loss",
            "brier_score",
            "ece_10",
        )
    )
    if not probabilistic_improvement:
        reasons.append("no_probabilistic_improvement_vs_elo")

    governance = report.get("evaluation_governance") or {}
    if governance.get("eligibility_reason"):
        reasons.append(governance["eligibility_reason"])
    if governance.get("production_present"):
        champion_delta = report.get("delta_vs_production") or {}
        if int((report.get("production_holdout") or {}).get("n") or 0) != int(holdout["n"]):
            reasons.append("production_evaluation_set_mismatch")
        for key in required:
            value = champion_delta.get(key)
            if value is None or not math.isfinite(float(value)):
                reasons.append("missing_production_" + key)
            elif (float(value) < 0 if key == "accuracy" else float(value) > 0):
                reasons.append(key + "_worse_than_production")
        if not any(champion_delta.get(key) is not None and float(champion_delta[key]) < 0
                   for key in ("log_loss", "brier_score", "ece_10")):
            reasons.append("no_probabilistic_improvement_vs_production")
    return not reasons, reasons


def _promotion_history(path):
    value = read_json(path, [])
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Invalid promotion history; refusing to forget previous decisions")
    return value


def _holdout_already_used(history, fingerprint):
    return any(
        isinstance(row, dict)
        and row.get("holdout_fingerprint") == fingerprint
        for row in history
    )


def _merge_refresh_batch_safely(matches, incoming, *, day, tour):
    """Quarantine only ambiguous incoming identities; preserve canonical history."""
    merged, accepted, safety = merge_trusted_history_batch(matches, incoming)
    if safety.get("quarantined_rows"):
        print(json.dumps({
            "warning": "ambiguous_match_identity_quarantined",
            "day": day.isoformat(),
            "tour": tour,
            "rows_skipped": safety.get("quarantined_rows"),
            "details": safety.get("rows"),
            "collision": safety.get("collision"),
        }, ensure_ascii=False), flush=True)
    return merged, accepted


def _refresh_history(provider, matches, history_dir, history_store, start, end):
    provider_years = {
        provider_id: match.scheduled_at.astimezone(timezone.utc).year
        for match in matches
        if (provider_id := _provider_event_id(match)) is not None
    }
    day = start
    while day <= end:
        for tour in ("atp", "wta"):
            incoming = [
                match
                for match in provider.matches_for_day(
                    tour, day, historical=True
                )
                if match.is_completed
            ]

            matches, accepted_incoming = _merge_refresh_batch_safely(
                matches, incoming, day=day, tour=tour
            )

            affected_years = {
                match.scheduled_at.astimezone(timezone.utc).year
                for match in accepted_incoming
            }
            for match in accepted_incoming:
                provider_id = _provider_event_id(match)
                if provider_id is not None and provider_id in provider_years:
                    affected_years.add(provider_years[provider_id])

            written = []
            removed = []
            for year in sorted(affected_years):
                path, was_removed = sync_year_partition(matches, history_dir, year)
                if path is not None:
                    written.append(path)
                elif was_removed:
                    removed.append(f"history-{year}.parquet")

            if written or removed:
                bundle = written + [history_dir / "history_manifest.json"]
                if removed:
                    history_store.upload_bundle(bundle, remove_names=removed)
                else:
                    history_store.upload_bundle(bundle)

            for match in accepted_incoming:
                provider_id = _provider_event_id(match)
                if provider_id is not None:
                    provider_years[provider_id] = (
                        match.scheduled_at.astimezone(timezone.utc).year
                    )
        day += timedelta(days=1)
    return matches




def _load_prediction_ledger(store):
    """Load a complete prior prediction generation, or bootstrap only if absent.

    An entirely empty prediction release is the only bootstrap state. If either
    feed.json or ledger.json exists, both are required and checksum-verified.
    """
    required = {"feed.json", "ledger.json"}
    assets = store._asset_names()
    present = required & assets
    if not present:
        return []
    if present != required:
        missing = sorted(required - present)
        raise FileNotFoundError(
            "Prediction release is incomplete; missing assets: " + ", ".join(missing)
        )
    optional_snapshot = "daily_offer_snapshot.json" if "daily_offer_snapshot.json" in assets else None
    extra_names = ["feed.json", "ledger.json"]
    if optional_snapshot:
        extra_names.append(optional_snapshot)
    store.download(
        extra_names=tuple(extra_names),
        required_names=("feed.json", "ledger.json"),
    )
    ledger = read_json(store.directory / "ledger.json", None)
    feed = read_json(store.directory / "feed.json", None)
    if not isinstance(ledger, list):
        raise ValueError("Invalid prediction ledger")
    validate_publication_candidate(feed, ledger)
    if (feed.get("market_selection") or {}).get("publication_schema") == 1:
        feed = restore_published_market_snapshots(feed, ledger)
        validate_market_publication_candidate(feed, ledger)
    return ledger

DOUBLES_HISTORY_ASSET = "doubles_history.json"
DOUBLES_REPORT_ASSET = "doubles_history_report.json"


def _load_doubles_history(store):
    assets = store._asset_names()
    if DOUBLES_HISTORY_ASSET not in assets:
        return []
    store.download(extra_names=(DOUBLES_HISTORY_ASSET,), required_names=(DOUBLES_HISTORY_ASSET,))
    payload = read_json(store.directory / DOUBLES_HISTORY_ASSET, {})
    rows = payload.get("matches") if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def _save_doubles_history(store, rows, *, extra_report=None):
    report = {
        **doubles_history_report(rows),
        "validation": validate_doubles_history(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **(extra_report or {}),
    }
    write_json(store.directory / DOUBLES_HISTORY_ASSET, {
        "schema": 1,
        "generated_at": report["generated_at"],
        "matches": rows,
    })
    write_json(store.directory / DOUBLES_REPORT_ASSET, report)
    store.upload_bundle([store.directory / DOUBLES_HISTORY_ASSET, store.directory / DOUBLES_REPORT_ASSET])
    return report


def _projection_presentation_integrity(feed, *, ace_picks=None, sg_picks=None):
    expected = {
        "aces": sum(1 for row in (ace_picks or []) if str(row.get("market") or "").lower() == "aces"),
        "double_faults": sum(1 for row in (ace_picks or []) if str(row.get("market") or "").lower() == "double_faults"),
        "sets": sum(1 for row in (sg_picks or []) if str(row.get("market") or "").lower() == "sets"),
        "games": sum(1 for row in (sg_picks or []) if str(row.get("market") or "").lower() == "games"),
    }
    actual = {
        "aces": sum(1 for row in (feed.get("ace_picks") or []) if str(row.get("market") or "").lower() == "aces"),
        "double_faults": sum(1 for row in (feed.get("ace_picks") or []) if str(row.get("market") or "").lower() == "double_faults"),
        "sets": sum(1 for row in (feed.get("sg_picks") or []) if str(row.get("market") or "").lower() == "sets"),
        "games": sum(1 for row in (feed.get("sg_picks") or []) if str(row.get("market") or "").lower() == "games"),
    }
    mismatches = {market: {"selected": expected[market], "published": actual[market]}
                  for market in expected if expected[market] != actual[market]}
    report = {"ok": not mismatches, "selected": expected, "published": actual, "mismatches": mismatches}
    if mismatches:
        raise RuntimeError(
            "Projection presentation integrity failure: selector output was lost before publication: "
            + json.dumps(mismatches, sort_keys=True)
        )
    return report


def _publish_predictions(
    store, ledger, predictions, matches, model, report, upcoming,
    *, odds_report=None, ace_picks=None, ace_report=None,
    sg_picks=None, sg_report=None, doubles_picks=None, doubles_report=None,
    doubles_matches=None, doubles_upcoming=None, prior_feed=None, prior_snapshot=None, betting_day_start_hour=6,
):
    # This stage publishes a pending deployment candidate. `issued_at` stays
    # empty until the workflow confirms a successful public Azure deployment.
    now = datetime.now(timezone.utc)
    # Betting sections have their own publication lifecycle. The Match Winner
    # probability may already be public before provider odds arrive, so freeze
    # pending Daily / Prime / Value candidates independently and confirm them only
    # after the exact feed is deployed.
    ledger_predictions = list(predictions) + list(doubles_picks or [])
    ledger_predictions = annotate_market_publication_candidates(
        ledger_predictions, ace_picks=ace_picks, sg_picks=sg_picks, doubles_picks=doubles_picks
    )
    settlement_matches = list(matches) + list(doubles_matches or [])
    records = reconcile_ledger(ledger, ledger_predictions, settlement_matches, now)
    feed_upcoming = list(upcoming) + list(doubles_upcoming or [])
    feed = serving_feed(records, model, matches, report, feed_upcoming, now)
    # Market presentation fields are derived from current odds-backed predictions
    # and never alter the immutable Match Winner probability commitment.
    feed = attach_market_sections_to_feed(
        feed, ledger_predictions, odds_report=odds_report,
        ace_picks=ace_picks, ace_report=ace_report,
        sg_picks=sg_picks, sg_report=sg_report,
        doubles_picks=doubles_picks, doubles_report=doubles_report,
    )
    # PRIME remains internal, but its rows carry a separately trained-on-history
    # conditional projection used only after the favourite loses set 1 LIVE.
    feed, comeback_report = annotate_live_second_set_projections(feed, matches, now=now)
    feed["market_selection"] = {
        **(feed.get("market_selection") or {}),
        "live_second_set_projection_report": comeback_report,
    }
    # First validate/restore the *current selector output* before daily carry-forward.
    # The selector integrity contract is exact only at this stage: after the
    # betting-day snapshot is merged, the final public feed is intentionally a
    # superset because already-issued morning rows remain visible after start.
    feed = clean(feed)
    feed = restore_published_market_snapshots(feed, records)
    integrity = _projection_presentation_integrity(feed, ace_picks=ace_picks, sg_picks=sg_picks)
    feed["market_selection"] = {
        **(feed.get("market_selection") or {}),
        "presentation_integrity": integrity,
    }

    # r55 daily offer snapshot: once an exact market row has been successfully
    # deployed/issued during the current BlinQ betting day, keep that immutable
    # row in the public offer even after its event starts. Newly qualifying rows
    # may append, but the morning offer never shrinks or reorders underneath a
    # ROOKIE/PRO user. Do this only after current-selector integrity succeeds;
    # carried rows are expected to make final section counts larger than the
    # current selector counts.
    snapshot_sources = []
    if isinstance(prior_snapshot, dict) and prior_snapshot:
        snapshot_sources.append(prior_snapshot)
    if isinstance(prior_feed, dict) and prior_feed:
        snapshot_sources.append(prior_feed)
    if snapshot_sources:
        feed, daily_snapshot_report = carry_forward_betting_day_market_rows(
            feed,
            snapshot_sources,
            records,
            now=now,
            start_hour=betting_day_start_hour,
        )
        feed["market_selection"] = {
            **(feed.get("market_selection") or {}),
            "daily_offer_snapshot": daily_snapshot_report,
        }

    feed = clean(feed)
    validate_publication_candidate(feed, records)
    validate_market_publication_candidate(feed, records)
    snapshot = build_daily_offer_snapshot(
        feed,
        now=now,
        start_hour=betting_day_start_hour,
    )
    # Decorate only the serving feed, after all immutable issuance checks.
    # Historical ledger, snapshots and REAL betting ROI stay untouched.
    feed, indicative_audit = annotate_feed_indicative_odds(feed)
    feed["indicative_odds_audit"] = indicative_audit
    write_json(store.directory / "ledger.json", records)
    write_json(store.directory / "feed.json", feed)
    write_json(store.directory / "daily_offer_snapshot.json", snapshot)
    store.upload_bundle([
        store.directory / "ledger.json",
        store.directory / "feed.json",
        store.directory / "daily_offer_snapshot.json",
    ])
    return feed


def main():
    parser = argparse.ArgumentParser(description="Offline BlinQ training and prediction publication")
    parser.add_argument("mode", choices=["train", "refresh", "backtest"])
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--max-requests", type=int, default=750)
    parser.add_argument(
        "--market-odds-max-events",
        type=int,
        default=150,
        help="Maximum provider-1 odds calls for the current BlinQ betting day",
    )
    parser.add_argument(
        "--doubles-odds-max-events",
        type=int,
        default=40,
        help="Maximum provider-1 Match Winner odds calls for isolated doubles candidates",
    )
    parser.add_argument(
        "--betting-day-start-hour",
        type=int,
        default=6,
        help="Europe/Bratislava local hour that starts the BlinQ betting day",
    )
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 3000:
        parser.error("refresh allowance must be 1..3000")
    if args.market_odds_max_events < 0:
        parser.error("market-odds-max-events must be >= 0")
    if args.doubles_odds_max_events < 0:
        parser.error("doubles-odds-max-events must be >= 0")
    if not 0 <= args.betting_day_start_hour <= 23:
        parser.error("betting-day-start-hour must be 0..23")
    cache = ROOT / ".cache/tbt"
    history_dir = cache / "history"
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    history_store.download()
    matches = load_partitions(history_dir)
    matches, history_safety = sanitize_history_identities(matches)
    if history_safety.get("changed"):
        print(json.dumps({"history_safety": history_safety}, ensure_ascii=False), flush=True)
    model_dir = cache / "model"
    if args.mode == "backtest":
        report = clean(walk_forward_backtest(matches))
        path = cache / "backtest.json"
        write_json(path, report)
        store = ReleaseStore(args.data_repository, "tbt-reports-v1", cache / "reports")
        store.upload([path])
        print(json.dumps(report.get("overall", report.get("metrics", {})), indent=2))
        return
    if args.mode == "train":
        candidate = ReleaseStore(args.data_repository, "tbt-model-candidate-v1", model_dir)
        candidate_assets = candidate._asset_names()
        candidate.download(
            extra_names=("promotion_history.json",),
            required_names=("promotion_history.json",) if "promotion_history.json" in candidate_assets else (),
        )
        promotion_history_path = model_dir / "promotion_history.json"
        promotion_history = (_promotion_history(promotion_history_path)
                             if "promotion_history.json" in candidate_assets else [])
        production_dir = cache / "production"
        production = ReleaseStore(args.data_repository, "tbt-model-production-v1", production_dir)
        production_assets = production._asset_names()
        champion = None
        if production_assets:
            production.download(
                extra_names=("model.joblib", "training_report.json", "promotion_history.json"),
                required_names=("model.joblib", "training_report.json") +
                    (("promotion_history.json",) if "promotion_history.json" in production_assets else ()),
            )
            champion = load_model(str(production_dir / "model.joblib"))
            for decision in (_promotion_history(production_dir / "promotion_history.json")
                             if "promotion_history.json" in production_assets else []):
                if decision not in promotion_history:
                    promotion_history.append(decision)
        result = train_from_matches(matches, production_model=champion,
                                    promotion_history=promotion_history)
        report = clean(result.report)
        governance = report.get("evaluation_governance") or {}
        fingerprint = str(governance.get("holdout_fingerprint") or "")
        eligible, gate_reasons = _promotion_metric_gate(report)
        if not fingerprint or _holdout_already_used(promotion_history, fingerprint):
            eligible = False
            gate_reasons.append("missing_or_reused_holdout_fingerprint")
        decision = {
            "holdout_fingerprint": fingerprint,
            "candidate_version": result.model.version,
            "production_version": getattr(champion, "version", None),
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "reference": governance.get("promotion_reference"),
            "holdout_period": (report.get("periods") or {}).get("holdout"),
            "holdout_metrics": report.get("holdout"),
            "production_metrics": report.get("production_holdout"),
            "delta_vs_elo": report.get("delta_vs_elo"),
            "delta_vs_production": report.get("delta_vs_production"),
            "eligible": eligible,
            "promotion_requested": args.promote,
            "decision": "approved" if eligible and args.promote else "rejected" if not eligible else "not_requested",
            "reasons": gate_reasons,
        }
        # Persist every holdout-based decision before returning or rejecting,
        # including a gate computed without --promote.
        if fingerprint:
            promotion_history.append(decision)
        save_model(result.model, str(model_dir / "model.joblib"))
        write_json(model_dir / "training_report.json", report)
        write_json(promotion_history_path, promotion_history)
        candidate.upload_bundle([model_dir / "model.joblib", model_dir / "training_report.json",
                                 promotion_history_path])
        print(json.dumps(decision, indent=2))
        if args.promote:
            if not eligible:
                raise SystemExit("Candidate saved. Promotion refused by governance gate; current champion unchanged.")
            production.upload_bundle([model_dir / "model.joblib", model_dir / "training_report.json",
                                      promotion_history_path])
        return
    if not settings.rapidapi_key:
        parser.error("RAPIDAPI_KEY is required")
    model_store = ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir)
    model_store.download(
        extra_names=("model.joblib", "training_report.json"),
        required_names=("model.joblib", "training_report.json"),
    )
    model = load_model(str(model_dir / "model.joblib"))
    report = read_json(model_dir / "training_report.json", {})
    prediction_dir = cache / "predictions"
    prediction_store = ReleaseStore(
        args.data_repository,
        "tbt-predictions-v1",
        prediction_dir,
    )
    prediction_ledger = _load_prediction_ledger(prediction_store)
    # _load_prediction_ledger downloads the complete prior release when one
    # exists. Keep the previously deployed candidate as the source of truth for
    # today's already-issued offer rows.
    prior_feed = read_json(prediction_dir / "feed.json", {})
    if not isinstance(prior_feed, dict):
        prior_feed = {}
    prior_snapshot = read_json(prediction_dir / "daily_offer_snapshot.json", {})
    if not isinstance(prior_snapshot, dict):
        prior_snapshot = {}
    doubles_dir = cache / "doubles"
    doubles_store = ReleaseStore(args.data_repository, "tbt-doubles-data-v1", doubles_dir)
    doubles_history = _load_doubles_history(doubles_store)
    budget_path = history_dir / "request_budget.json"
    ledger, allowance = reserve_allocation(read_json(budget_path, {}), args.max_requests,
        run_id=os.getenv("GITHUB_RUN_ID", "manual"), purpose="refresh")
    if not allowance:
        raise SystemExit("Refresh budget exhausted; previously deployed feed stays available with its timestamp")
    write_json(budget_path, ledger)
    history_store.upload_bundle([budget_path])
    budget = LocalRequestBudget(history_dir / "local_request_budget.sqlite", duration_seconds=1800)
    provider = RapidTennisClient(request_budget=budget)
    provider.request_limit = allowance
    now = datetime.now(timezone.utc)
    refresh_error = None
    upcoming = []
    odds_report = None
    ace_picks = []
    ace_report = None
    sg_picks = []
    sg_report = None
    doubles_picks = []
    doubles_report = None
    doubles_completed = []
    doubles_upcoming = []
    try:
        matches = _refresh_history(provider, matches, history_dir, history_store,
                                   now.date() - timedelta(days=7), now.date())
        for tour in ("atp", "wta"):
            upcoming.extend(provider.upcoming(tour, now.date(), now.date() + timedelta(days=3)))

        # Doubles uses a separate pair/member model. The raw daily event calls are
        # already cached by the singles refresh above, so maintaining the recent
        # doubles history adds very little discovery traffic.
        doubles_day = now.date() - timedelta(days=7)
        while doubles_day <= now.date():
            doubles_completed.extend(
                match for match in provider.doubles_for_day(doubles_day, historical=True)
                if match.is_completed
            )
            doubles_day += timedelta(days=1)
        doubles_history = merge_doubles_history(doubles_history, doubles_completed)
        doubles_history_state = _save_doubles_history(
            doubles_store, doubles_history,
            extra_report={"recent_completed_refreshed": len(doubles_completed)},
        )
        doubles_upcoming = provider.doubles_upcoming(now.date(), now.date() + timedelta(days=3))
        doubles_predictions, doubles_model_report = build_doubles_predictions(
            doubles_history, doubles_upcoming, now=now
        )
        doubles_odds_report = {}
        if args.doubles_odds_max_events and doubles_predictions:
            doubles_predictions, doubles_odds_report = enrich_current_betting_day_odds(
                provider, doubles_predictions, now=now,
                max_events=args.doubles_odds_max_events, provider_id=1,
                timezone_name="Europe/Bratislava", start_hour=args.betting_day_start_hour,
                candidate_min_probability=0.55, candidate_min_data_depth=0.35,
                candidate_min_surface_matches=2,
            )
        doubles_picks, doubles_selection_report = select_doubles_picks(doubles_predictions)
        doubles_report = {
            "history": doubles_history_state,
            "model": doubles_model_report,
            "odds": doubles_odds_report,
            "selection": doubles_selection_report,
        }

        # Odds-first for ACES/DF/GAMES/SETS: obtain actual available offers
        # BEFORE evaluating their projection models. Match Winner continues to
        # use its independent qualification rules and shares cached payloads.
        predictions = predict(model, matches, upcoming)
        projection_odds_cap = max(0, int(args.market_odds_max_events or 0))
        projection_odds_report = {}
        projection_market_cache = {}
        available_projection_markets = {}
        projection_discovery_report = {}
        bookmaker_lines_by_event = {}
        if projection_odds_cap:
            # Respect the *remaining* overall RapidAPI request cap; discovery
            # follows doubles/history enrichment in the same refresh. Leave
            # one request for unrelated match-winner candidates when possible.
            remaining = (max(0, int(provider.request_limit) - int(provider.request_count) - 1)
                         if provider.request_limit is not None else projection_odds_cap)
            available_odds_calls = min(projection_odds_cap, remaining)
            (projection_market_cache, available_projection_markets,
             projection_discovery_report) = prefetch_projection_market_board(
                provider, predictions, now=now, max_events=available_odds_calls,
                provider_id=1,
            )
            projection_discovery_report["remaining_request_budget_at_start"] = remaining
            projection_discovery_report["requested_event_cap"] = projection_odds_cap
            for event_id, markets in available_projection_markets.items():
                payload = projection_market_cache.get(event_id)
                bookmaker_lines_by_event[event_id] = {
                    market: [float(quote["line"]) for quote in
                             extract_match_total_odds(payload, market)]
                    for market in ("sets", "games") if market in markets
                }
            # No re-query for events already visited by odds-first discovery.
            predictions, odds_report = enrich_current_betting_day_odds(
                provider, predictions, now=now,
                max_events=projection_odds_cap, provider_id=1,
                timezone_name="Europe/Bratislava",
                start_hour=args.betting_day_start_hour,
                prefetched_payloads=projection_market_cache,
            )
        # In odds-first mode the projection models operate only on events
        # that have a complete matching market from the provider. Keep an
        # expanded *eligible* pool so publication can independently rank each
        # of the four categories without one consuming the others' slots.
        projection_pool_per_market = (
            max(30, min(200, projection_odds_cap)) if projection_odds_cap else 10
        )
        ace_picks, ace_report = select_ace_picks(
            matches, predictions, now=now,
            per_market_limit=projection_pool_per_market,
            total_limit=2 * projection_pool_per_market,
            target_count=projection_pool_per_market,
            available_markets_by_event=(
                available_projection_markets if projection_odds_cap else None
            ),
        )
        sg_picks, sg_report = select_sg_picks(
            matches, predictions, now=now,
            per_market_limit=projection_pool_per_market,
            total_limit=2 * projection_pool_per_market,
            target_count=projection_pool_per_market,
            available_markets_by_event=(
                available_projection_markets if projection_odds_cap else None
            ),
            bookmaker_lines_by_event=(
                bookmaker_lines_by_event if projection_odds_cap else None
            ),
        )
        projection_odds_report["discovery"] = projection_discovery_report
        if projection_odds_cap and (ace_picks or sg_picks):
            ace_picks, sg_picks, attachment_report = enrich_projection_odds(
                provider, ace_picks, sg_picks,
                max_events=projection_odds_cap, provider_id=1,
                prefetched_payloads=projection_market_cache,
            )
            projection_odds_report.update(attachment_report)
            projection_odds_report["discovery"] = projection_discovery_report
        # Market-first publication is strict: an unmatched card remains an
        # internal model diagnostic, never a bookmaker-looking bet.
        if projection_odds_cap:
            projection_odds_report["unpriced_model_candidates"] = {
                market: sum(row.get("market") == market and
                            row.get("price_status") != "priced_projection"
                            for row in ace_picks + sg_picks)
                for market in ("aces", "double_faults", "games", "sets")
            }
            ace_picks = [row for row in ace_picks
                         if row.get("price_status") == "priced_projection"]
            sg_picks = [row for row in sg_picks
                        if row.get("price_status") == "priced_projection"]
        # Ten per independent category, sorted by validated projection
        # confidence and evidence, NOT simply by the highest bookmaker price.
        def priced_first_ten(rows):
            indexed = list(enumerate(rows))
            chosen = []
            for metric in ("aces", "double_faults", "sets", "games"):
                group = [(i, row) for i, row in indexed if row.get("market") == metric]
                group.sort(key=lambda pair: (
                    str(pair[1].get("price_status") or "") == "priced_projection",
                    -pair[0],
                ), reverse=True)
                chosen.extend(group[:10])
            chosen.sort(key=lambda pair: pair[0])
            return [row for _, row in chosen]

        ace_picks = priced_first_ten(ace_picks)
        sg_picks = priced_first_ten(sg_picks)
        projection_odds_report["published_priced_cards"] = {
            metric: sum(
                row.get("market") == metric
                and row.get("price_status") == "priced_projection"
                for row in ace_picks + sg_picks
            )
            for metric in ("aces", "double_faults", "sets", "games")
        }
        if isinstance(ace_report, dict):
            ace_report = {
                **ace_report, "odds_attachment": projection_odds_report,
                "published_selected": len(ace_picks),
                "priced_selection_policy": "odds_first_exact_market_then_model_independent_top10",
            }
        if isinstance(sg_report, dict):
            sg_report = {
                **sg_report, "odds_attachment": projection_odds_report,
                "published_selected": len(sg_picks),
                "priced_selection_policy": "odds_first_exact_market_then_model_independent_top10",
            }
    except Exception as exc:
        refresh_error = exc
    finally:
        try:
            provider.client.close()
        finally:
            budget.close()

    if refresh_error is not None:
        # Partial completed history is checkpointed, but no new prediction
        # feed is published from an incomplete refresh.
        raise refresh_error
    feed = _publish_predictions(
        prediction_store, prediction_ledger,
        predictions, matches, model, report, upcoming,
        odds_report=odds_report, ace_picks=ace_picks, ace_report=ace_report,
        sg_picks=sg_picks, sg_report=sg_report,
        doubles_picks=doubles_picks, doubles_report=doubles_report,
        doubles_matches=doubles_completed, doubles_upcoming=doubles_upcoming,
        prior_feed=prior_feed, prior_snapshot=prior_snapshot,
        betting_day_start_hour=args.betting_day_start_hour,
    )
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, feed)
    refresh_report = {
        "requests": provider.request_count,
        "upcoming": len(feed["upcoming"]),
        "daily": len(feed.get("top_daily_picks", [])),
        "prime": len(feed.get("prime_picks", [])),
        "value": len(feed.get("value_picks", [])),
        "ace": len(feed.get("ace_picks", [])),
        "ace_projection": ace_report or {},
        "sg": len(feed.get("sg_picks", [])),
        "sg_projection": sg_report or {},
        "doubles": len(feed.get("doubles_picks", [])),
        "doubles_model": doubles_report or {},
        "odds": odds_report or {},
        "settled": len(feed["results"]),
        "model": model.version,
    }
    write_json(prediction_dir / "refresh_report.json", refresh_report)
    print(json.dumps(refresh_report))


if __name__ == "__main__":
    main()
