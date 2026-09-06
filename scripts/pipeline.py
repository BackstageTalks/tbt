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
from tbt.data.history_snapshot import load_partitions, write_year_partition, merge_matches
from tbt.models.artifact import load_model, save_model
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.engine import predict, reconcile_ledger, serving_feed
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


def _refresh_history(provider, matches, history_dir, history_store, start, end):
    day = start
    while day <= end:
        for tour in ("atp", "wta"):
            incoming = [m for m in provider.matches_for_day(tour, day, historical=True) if m.is_completed]
            matches = merge_matches(matches, incoming)
            ids = [str(match.match_id) for match in matches]
            if len(ids) != len(set(ids)):
                raise ValueError(
                    "Ambiguous match identity collision; refusing to refresh history"
                )
            written = []
            for year in sorted({m.scheduled_at.year for m in incoming}):
                write_year_partition(matches, history_dir, year)
                written.append(history_dir / f"history-{year}.parquet")
            if written:
                history_store.upload_bundle(written + [history_dir / "history_manifest.json"])
        day += timedelta(days=1)
    return matches


def _publish_predictions(store, ledger, predictions, matches, model, report, upcoming):
    # This stage publishes a pending deployment candidate. `issued_at` stays
    # empty until the workflow confirms a successful public Azure deployment.
    now = datetime.now(timezone.utc)
    records = reconcile_ledger(ledger, predictions, matches, now)
    feed = clean(serving_feed(records, model, matches, report, upcoming, now))
    write_json(store.directory / "ledger.json", records)
    write_json(store.directory / "feed.json", feed)
    store.upload_bundle([store.directory / "ledger.json", store.directory / "feed.json"])
    return feed


def main():
    parser = argparse.ArgumentParser(description="Offline BlinQ training and prediction publication")
    parser.add_argument("mode", choices=["train", "refresh", "backtest"])
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--max-requests", type=int, default=750)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--bootstrap-predictions", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 3000:
        parser.error("refresh allowance must be 1..3000")
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
    if args.bootstrap_predictions:
        prediction_store.download(extra_names=("ledger.json",))
    else:
        prediction_store.download(
            extra_names=("ledger.json",),
            required_names=("ledger.json",),
        )
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
    try:
        matches = _refresh_history(provider, matches, history_dir, history_store,
                                   now.date() - timedelta(days=7), now.date())
        for tour in ("atp", "wta"):
            upcoming.extend(provider.upcoming(tour, now.date(), now.date() + timedelta(days=3)))
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
    predictions = predict(model, matches, upcoming)
    feed = _publish_predictions(prediction_store, read_json(prediction_dir / "ledger.json", []),
                                predictions, matches, model, report, upcoming)
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, feed)
    print(json.dumps({"requests": provider.request_count, "upcoming": len(feed["upcoming"]),
                      "settled": len(feed["results"]), "model": model.version}))


if __name__ == "__main__":
    main()
