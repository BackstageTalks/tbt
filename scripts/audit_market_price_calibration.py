"""Read-only time-separated calibration audit of collected REAL market quotes.

Target = de-vigged provider market probability, NOT actual match outcome.
This estimates market pricing behavior rather than betting profitability.
No model is deployed or used in the public feed until sufficient observations
and independent outcome-based validation exist.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error

from _bootstrap import ROOT
from release_store import ReleaseStore


def research_samples(archives: list[dict]) -> list[dict]:
    """Earliest pre-start two-sided quote for each event/market/line/provider."""
    earliest: dict[tuple, dict] = {}
    for item in archives:
        try:
            start = datetime.fromisoformat(item["starts_at_utc"].replace("Z", "+00:00"))
            captured = datetime.fromisoformat(item["captured_at_utc"].replace("Z", "+00:00"))
            if captured >= start:
                continue
            o, u = float(item["over_odds"]), float(item["under_odds"])
            line = float(item["line"])
            if not (1.01 <= o <= 100 and 1.01 <= u <= 100 and 1.5 <= line <= 80):
                continue
            models = item.get("models") or []
            models = [m for m in models if m.get("market") == item["market"]]
            if not models:
                continue
            # Highest supported confidence is only a deterministic choice
            # among SAME-event pre-match model versions, not a target label.
            model = sorted(models, key=lambda r: -(float(r.get("projection_confidence") or 0)))[0]
            projection = float(model["projection"])
            if not np.isfinite(projection):
                continue
            key = (str(item["event_id"]), item["market"], line, int(item["provider_id"]))
            sample = {
                "event_id": str(item["event_id"]), "market": item["market"],
                "line": line, "projection": projection,
                "gap": projection - line, "captured_at": captured,
                "start": start, "provider_id": int(item["provider_id"]),
                "over_odds": o, "under_odds": u,
                "market_over_fair_probability": (1 / o) / (1 / o + 1 / u),
            }
            if key not in earliest or captured < earliest[key]["captured_at"]:
                earliest[key] = sample
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return sorted(earliest.values(), key=lambda x: (x["start"], x["event_id"], x["line"]))


def audit_samples(rows: list[dict], *, min_events: int = 200, min_days: int = 30) -> dict:
    result = {
        "schema": 1, "purpose": "research_market_price_not_outcome_or_roi",
        "samples": len(rows),
        "distinct_events": len({r["event_id"] for r in rows}),
        "distinct_start_days": len({r["start"].date() for r in rows}),
        "by_market": dict(Counter(r["market"] for r in rows)),
        "status": "insufficient_real_price_observations",
        "min_unique_events": min_events, "min_distinct_days": min_days,
        "model_deployed": False,
    }
    if result["distinct_events"] < min_events or result["distinct_start_days"] < min_days:
        return result
    days = sorted({r["start"].date() for r in rows})
    boundary = days[max(1, int(0.8 * len(days))) - 1]
    train = [r for r in rows if r["start"].date() <= boundary]
    test = [r for r in rows if r["start"].date() > boundary]
    if len({r["event_id"] for r in test}) < 40:
        result["status"] = "insufficient_independent_holdout_events"
        return result

    # Separate fits because set totals and game totals have incompatible scales.
    result["segments"] = {}
    for market in ("games", "sets"):
        tr = [r for r in train if r["market"] == market]
        te = [r for r in test if r["market"] == market]
        seg = {"train": len(tr), "test": len(te), "status": "insufficient_segment"}
        if len({r["event_id"] for r in tr}) < 100 or len({r["event_id"] for r in te}) < 25:
            result["segments"][market] = seg
            continue
        features = lambda rs: np.array([[r["gap"], r["line"], r["projection"]]
                                         for r in rs], dtype=float)
        baseline = float(np.mean([r["market_over_fair_probability"] for r in tr]))
        model = Ridge(alpha=25.0).fit(features(tr),
                                      [r["market_over_fair_probability"] for r in tr])
        actual = np.array([r["market_over_fair_probability"] for r in te])
        predicted = np.clip(model.predict(features(te)), 0.03, 0.97)
        seg.update({
            "status": "research_model_evaluated_no_publication",
            "market_price_mae": float(mean_absolute_error(actual, predicted)),
            "baseline_mae": float(mean_absolute_error(actual, np.full(len(te), baseline))),
            "holdout_first_day": str(min(r["start"].date() for r in te)),
            "train_last_day": str(max(r["start"].date() for r in tr)),
            "caveat": "Target is de-vigged bookmaker price, not true win probability",
        })
        result["segments"][market] = seg
    result["status"] = "holdout_research_completed"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    args = parser.parse_args()
    store = ReleaseStore(args.data_repository, "tbt-market-odds-v1",
                         ROOT / ".cache/tbt/market-odds/archive")
    names = sorted(n for n in store._asset_names() if n.startswith("market_odds_") and n.endswith(".json"))
    if names:
        store.download(extra_names=names, required_names=names, require_bundle_manifest=True)
    all_rows = []
    for name in names:
        entries = json.loads((store.directory / name).read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError(f"Invalid quote archive {name}")
        all_rows.extend(entries)
    report = audit_samples(research_samples(all_rows))
    destination = ROOT / ".cache/tbt/market-odds/calibration_audit.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
