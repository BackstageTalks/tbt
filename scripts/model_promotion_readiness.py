#!/usr/bin/env python3
"""Report when enough genuinely unseen matches exist for the next promotion test.

No provider/API calls are made. The cutoff mirrors training governance: a whole
UTC day is eligible only if it is later than the production serving history and
all previously consumed promotion-decision holdouts.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.models.artifact import load_model
from tbt.services.data_quality import audit_history
from tbt.services.training import _parse_provenance_datetime


def _decision_cutoff(history) -> datetime | None:
    values = []
    for row in history if isinstance(history, list) else []:
        if not isinstance(row, dict):
            continue
        period = row.get("holdout_period") or {}
        value = _parse_provenance_datetime(period.get("end"))
        if value is not None:
            values.append(value)
    return max(values) if values else None


def build_readiness(
    matches,
    *,
    production_model,
    promotion_history=(),
    minimum_gate_rows: int = 200,
    target_rows: int = 1000,
    minimum_days: int = 3,
) -> dict:
    accepted, quality = audit_history(matches)
    metadata = getattr(production_model, "metadata", {}) or {}
    production_cutoff = _parse_provenance_datetime(metadata.get("history_end"))
    if production_cutoff is None:
        raise ValueError("Production model history_end is missing or invalid")

    decision_cutoff = _decision_cutoff(promotion_history)
    cutoff = max(
        value for value in (production_cutoff, decision_cutoff) if value is not None
    )
    cutoff_day = pd.Timestamp(cutoff).tz_convert("UTC").normalize()

    unseen = [
        match
        for match in accepted
        if pd.Timestamp(match.scheduled_at).tz_convert("UTC").normalize() > cutoff_day
    ]
    unseen.sort(key=lambda match: (match.scheduled_at, str(match.match_id)))
    days = sorted(
        {
            pd.Timestamp(match.scheduled_at).tz_convert("UTC").date().isoformat()
            for match in unseen
        }
    )

    rows = len(unseen)
    distinct_days = len(days)
    return {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_version": getattr(production_model, "version", None),
        "production_history_end": production_cutoff.isoformat(),
        "latest_consumed_decision_end": (
            decision_cutoff.isoformat() if decision_cutoff is not None else None
        ),
        "eligibility_cutoff_day_utc": cutoff_day.date().isoformat(),
        "eligible_unseen_rows": rows,
        "eligible_unseen_days": distinct_days,
        "unseen_period": {
            "start": unseen[0].scheduled_at.isoformat() if unseen else None,
            "end": unseen[-1].scheduled_at.isoformat() if unseen else None,
        },
        "by_tour": dict(Counter(str(match.tour) for match in unseen)),
        "minimum_gate_rows": int(minimum_gate_rows),
        "recommended_target_rows": int(target_rows),
        "recommended_minimum_days": int(minimum_days),
        "ready_for_metric_gate": rows >= minimum_gate_rows and distinct_days >= minimum_days,
        "ready_for_retrain": rows >= target_rows and distinct_days >= minimum_days,
        "remaining_to_gate": max(0, minimum_gate_rows - rows),
        "remaining_to_target": max(0, target_rows - rows),
        "canonical_accepted_rows": int(quality.get("accepted") or 0),
        "policy": (
            "whole UTC days strictly later than production serving history and "
            "all previously consumed promotion-decision holdouts"
        ),
        "provider_requests": 0,
    }


def _load_history(repository: str):
    history_dir = ROOT / ".cache" / "tbt" / "history"
    store = ReleaseStore(repository, "tbt-data-v1", history_dir)
    store.download()
    matches = load_partitions(history_dir)
    matches, safety = sanitize_history_identities(matches)
    if safety.get("quarantined_rows"):
        raise ValueError("Canonical history has unresolved identity quarantine")
    return matches


def _load_governance(repository: str):
    production_dir = ROOT / ".cache" / "tbt" / "readiness-production"
    production = ReleaseStore(repository, "tbt-model-production-v1", production_dir)
    assets = production._asset_names()
    production.download(
        extra_names=("model.joblib", "promotion_history.json"),
        required_names=("model.joblib", "promotion_history.json"),
    )
    model = load_model(str(production_dir / "model.joblib"))
    histories = []
    for tag, directory_name in (
        ("tbt-model-production-v1", "readiness-production-history"),
        ("tbt-model-candidate-v1", "readiness-candidate-history"),
    ):
        directory = ROOT / ".cache" / "tbt" / directory_name
        store = ReleaseStore(repository, tag, directory)
        names = store._asset_names()
        if "promotion_history.json" not in names:
            continue
        store.download(
            extra_names=("promotion_history.json",),
            required_names=("promotion_history.json",),
        )
        try:
            value = json.loads((directory / "promotion_history.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid promotion history") from exc
        if not isinstance(value, list):
            raise ValueError("Invalid promotion history")
        for row in value:
            if row not in histories:
                histories.append(row)
    return model, histories


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument("--minimum-gate-rows", type=int, default=200)
    parser.add_argument("--target-rows", type=int, default=1000)
    parser.add_argument("--minimum-days", type=int, default=3)
    parser.add_argument(
        "--out",
        default=".cache/tbt/model-readiness/readiness.json",
    )
    args = parser.parse_args()

    matches = _load_history(args.data_repository)
    model, history = _load_governance(args.data_repository)
    report = build_readiness(
        matches,
        production_model=model,
        promotion_history=history,
        minimum_gate_rows=args.minimum_gate_rows,
        target_rows=args.target_rows,
        minimum_days=args.minimum_days,
    )
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
