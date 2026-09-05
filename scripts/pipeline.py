from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from download_tennis_history import read_json, write_json, merge_match
from history_download_budget import LocalRequestBudget, reserve_allocation
from release_store import ReleaseStore
from tbt.config import settings
from tbt.data.history_snapshot import load_partitions, write_year_partition
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


def main():
    parser = argparse.ArgumentParser(description="Offline BlinQ training and prediction publication")
    parser.add_argument("mode", choices=["train", "refresh", "backtest"])
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--max-requests", type=int, default=750)
    parser.add_argument("--promote", action="store_true")
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
        result = train_from_matches(matches)
        report = clean(result.report)
        candidate = ReleaseStore(args.data_repository, "tbt-model-candidate-v1", model_dir)
        save_model(result.model, str(model_dir / "model.joblib"))
        write_json(model_dir / "training_report.json", report)
        candidate.upload([model_dir / "model.joblib", model_dir / "training_report.json"])
        delta = report["delta_vs_elo"]
        eligible = (report["holdout"]["n"] >= 200 and delta["log_loss"] <= .01
                    and delta["accuracy"] >= -.01)
        print(json.dumps({"candidate": result.model.version, "promotion_gate": eligible,
                          "holdout": report["holdout"], "delta_vs_elo": delta}, indent=2))
        if args.promote:
            if not eligible:
                raise SystemExit("Candidate saved. Promotion refused by holdout gate; current champion unchanged.")
            production = ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir)
            production.upload([model_dir / "model.joblib", model_dir / "training_report.json"])
        return
    if not settings.rapidapi_key:
        parser.error("RAPIDAPI_KEY is required")
    model_store = ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir)
    model_store.download(extra_names=("model.joblib", "training_report.json"))
    model = load_model(str(model_dir / "model.joblib"))
    report = read_json(model_dir / "training_report.json", {})
    prediction_dir = cache / "predictions"
    prediction_store = ReleaseStore(args.data_repository, "tbt-predictions-v1", prediction_dir)
    prediction_store.download(extra_names=("ledger.json",))
    budget_path = history_dir / "request_budget.json"
    ledger, allowance = reserve_allocation(read_json(budget_path, {}), args.max_requests,
        run_id=os.getenv("GITHUB_RUN_ID", "manual"), purpose="refresh")
    if not allowance:
        raise SystemExit("Refresh budget exhausted; previously deployed feed stays available with its timestamp")
    write_json(budget_path, ledger)
    history_store.upload([budget_path])
    budget = LocalRequestBudget(history_dir / "local_request_budget.sqlite", duration_seconds=1800)
    provider = RapidTennisClient(request_budget=budget)
    provider.request_limit = allowance
    now = datetime.now(timezone.utc)
    by_id = {m.match_id: m for m in matches}
    try:
        upcoming = []
        for tour in ("atp", "wta"):
            for match in provider.historical_period(tour, now.date() - timedelta(days=7), now.date()):
                by_id[match.match_id] = merge_match(by_id.get(match.match_id), match)
            upcoming.extend(provider.upcoming(tour, now.date(), now.date() + timedelta(days=3)))
    finally:
        provider.client.close()
        budget.close()
    matches = list(by_id.values())
    changed_years = {(now - timedelta(days=d)).year for d in range(8)}
    for year in changed_years:
        if any(m.scheduled_at.year == year for m in matches):
            write_year_partition(matches, history_dir, year)
    history_store.upload([history_dir / f"history-{y}.parquet" for y in changed_years])
    history_store.upload([history_dir / "history_manifest.json"])
    predictions = predict(model, matches, upcoming, now)
    records = reconcile_ledger(read_json(prediction_dir / "ledger.json", []), predictions, matches, now)
    write_json(prediction_dir / "ledger.json", records)
    feed = clean(serving_feed(records, model, matches, report, upcoming, now))
    write_json(prediction_dir / "feed.json", feed)
    prediction_store.upload([prediction_dir / "ledger.json", prediction_dir / "feed.json"])
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, feed)
    print(json.dumps({"requests": provider.request_count, "upcoming": len(feed["upcoming"]),
                      "settled": len(feed["results"]), "model": model.version}))


if __name__ == "__main__":
    main()
