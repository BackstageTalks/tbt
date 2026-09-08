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
    merge_matches,
    sync_year_partition,
    _provider_event_id,
    _canonical_match_id,
)
from tbt.models.artifact import load_model, save_model
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.engine import predict, reconcile_ledger, serving_feed
from tbt.services.publication import (
    validate_market_publication_candidate,
    validate_publication_candidate,
)
from tbt.services.ace_selection import select_ace_picks
from tbt.services.sg_selection import select_sg_picks
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


def _duplicate_match_ids(matches):
    counts = {}
    for match in matches:
        key = str(match.match_id)
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _merge_refresh_batch_safely(matches, incoming, *, day, tour):
    """Merge refresh rows without letting one ambiguous provider collision kill the run.

    History integrity still fails closed: if the existing snapshot is already
    ambiguous we abort.  If a *new* batch creates an unresolved canonical-id
    collision, every incoming row for that canonical id is quarantined and the
    previously stored history is kept unchanged for that identity.
    """
    existing_duplicates = _duplicate_match_ids(matches)
    if existing_duplicates:
        raise ValueError(
            "Existing history contains ambiguous match identity collisions: "
            + ", ".join(sorted(existing_duplicates)[:10])
        )

    merged = merge_matches(matches, incoming)
    collisions = _duplicate_match_ids(merged)
    if not collisions:
        return merged, list(incoming)

    quarantined = [
        match for match in incoming
        if _canonical_match_id(match) in collisions
        or str(match.match_id) in collisions
    ]
    safe_incoming = [match for match in incoming if match not in quarantined]
    merged = merge_matches(matches, safe_incoming)

    remaining = _duplicate_match_ids(merged)
    if remaining:
        raise ValueError(
            "Ambiguous match identity collision remains after quarantine: "
            + ", ".join(sorted(remaining)[:10])
        )

    print(json.dumps({
        "warning": "ambiguous_match_identity_quarantined",
        "day": day.isoformat(),
        "tour": tour,
        "canonical_ids": sorted(collisions),
        "rows_skipped": len(quarantined),
        "provider_event_ids": sorted({
            provider_id
            for match in quarantined
            if (provider_id := _provider_event_id(match)) is not None
        }),
    }), flush=True)
    return merged, safe_incoming


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
    store.download(
        extra_names=("feed.json", "ledger.json"),
        required_names=("feed.json", "ledger.json"),
    )
    ledger = read_json(store.directory / "ledger.json", None)
    feed = read_json(store.directory / "feed.json", None)
    if not isinstance(ledger, list):
        raise ValueError("Invalid prediction ledger")
    validate_publication_candidate(feed, ledger)
    if (feed.get("market_selection") or {}).get("publication_schema") == 1:
        validate_market_publication_candidate(feed, ledger)
    return ledger

def _publish_predictions(
    store, ledger, predictions, matches, model, report, upcoming,
    *, odds_report=None, ace_picks=None, ace_report=None,
    sg_picks=None, sg_report=None,
):
    # This stage publishes a pending deployment candidate. `issued_at` stays
    # empty until the workflow confirms a successful public Azure deployment.
    now = datetime.now(timezone.utc)
    # Betting sections have their own publication lifecycle. The Match Winner
    # probability may already be public before provider odds arrive, so freeze
    # pending Daily / Prime / Value candidates independently and confirm them only
    # after the exact feed is deployed.
    predictions = annotate_market_publication_candidates(predictions)
    records = reconcile_ledger(ledger, predictions, matches, now)
    feed = serving_feed(records, model, matches, report, upcoming, now)
    # Market presentation fields are derived from current odds-backed predictions
    # and never alter the immutable Match Winner probability commitment.
    feed = attach_market_sections_to_feed(
        feed, predictions, odds_report=odds_report,
        ace_picks=ace_picks, ace_report=ace_report,
        sg_picks=sg_picks, sg_report=sg_report,
    )
    feed = clean(feed)
    write_json(store.directory / "ledger.json", records)
    write_json(store.directory / "feed.json", feed)
    store.upload_bundle([store.directory / "ledger.json", store.directory / "feed.json"])
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
    if not 0 <= args.betting_day_start_hour <= 23:
        parser.error("betting-day-start-hour must be 0..23")
    cache = ROOT / ".cache/tbt"
    history_dir = cache / "history"
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    history_store.download()
    matches = load_partitions(history_dir)
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
    try:
        matches = _refresh_history(provider, matches, history_dir, history_store,
                                   now.date() - timedelta(days=7), now.date())
        for tour in ("atp", "wta"):
            upcoming.extend(provider.upcoming(tour, now.date(), now.date() + timedelta(days=3)))

        # Generate the model probabilities first, then spend additional provider
        # calls only on the current BlinQ betting day. The odds layer now powers
        # Prime / Top Bets / Value discovery with mutually exclusive public assignment.
        predictions = predict(model, matches, upcoming)
        if args.market_odds_max_events:
            predictions, odds_report = enrich_current_betting_day_odds(
                provider,
                predictions,
                now=now,
                max_events=args.market_odds_max_events,
                provider_id=1,
                timezone_name="Europe/Bratislava",
                start_hour=args.betting_day_start_hour,
            )
        # Aces / Double Faults use only already-stored historical post-match
        # counts. This consumes no additional provider requests and remains
        # projection-only until a real pre-match price/line source is verified.
        ace_picks, ace_report = select_ace_picks(matches, predictions, now=now)
        # Sets / Games are derived from stored structured historical scores.
        # They remain projection-only until a calibrated price/line layer is
        # separately validated and backtested.
        sg_picks, sg_report = select_sg_picks(matches, predictions, now=now)
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
    )
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, feed)
    print(json.dumps({
        "requests": provider.request_count,
        "upcoming": len(feed["upcoming"]),
        "daily": len(feed.get("top_daily_picks", [])),
        "prime": len(feed.get("prime_picks", [])),
        "value": len(feed.get("value_picks", [])),
        "ace": len(feed.get("ace_picks", [])),
        "ace_projection": ace_report or {},
        "sg": len(feed.get("sg_picks", [])),
        "sg_projection": sg_report or {},
        "odds": odds_report or {},
        "settled": len(feed["results"]),
        "model": model.version,
    }))


if __name__ == "__main__":
    main()
