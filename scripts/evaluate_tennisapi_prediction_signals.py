"""Offline chronological ablation for independently linked pre-match signals.

No model artifact, deployment, provider API traffic, canonical writes or
automatic promotion. A post-match source snapshot never supplies pre-match odds.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path


MIN_ROWS = 300
MIN_DAYS = 60


def asof(value):
    if not isinstance(value, str):
        raise ValueError("Explicit timezone-aware timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid timestamp") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Naive timestamp is not point-in-time evidence")
    return dt.astimezone(timezone.utc)


def _probability(value):
    if isinstance(value, bool):
        raise ValueError("Invalid probability")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid probability") from None
    if not math.isfinite(number) or not 0 < number < 1:
        raise ValueError("Out-of-range probability")
    return number


def _load_rows(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Unsafe or oversized research file")
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    elif path.suffix == ".csv":
        import csv
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    else:
        raise ValueError("Only .csv or .jsonl research files accepted")
    if len(rows) > 300_000 or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Invalid bounded research rows")
    return rows


def _oriented_signals(signal: dict, player1_id: str, player2_id: str):
    home_id, away_id = str(signal.get("home_id")), str(signal.get("away_id"))
    if (player1_id, player2_id) == (home_id, away_id):
        forward = True
    elif (player1_id, player2_id) == (away_id, home_id):
        forward = False
    else:
        raise ValueError("Reconciled signal has different native participants")
    # Source data observed only after a match may not be retrospectively
    # treated as an attested pre-match draw. Without source as-of proof
    # use no seed feature, not even a nonzero missingness indicator.
    attested_seed = signal.get("source_prematch_seed_temporal_attestation") is True
    first = (signal.get("home_seed") if forward else signal.get("away_seed")) if attested_seed else None
    second = (signal.get("away_seed") if forward else signal.get("home_seed")) if attested_seed else None
    # Missing seed is distinct from a verified unseeded player.
    known_both = first is not None and second is not None
    seed_difference = second - first if known_both else 0.0
    seeded_only = 1.0 if first is not None and second is None else (
        -1.0 if second is not None and first is None else 0.0)
    # One player's previous matches on another day do not demonstrate
    # complete 7-day historical coverage. Only explicitly certified windows
    # can yield a duration feature (the source audit defaults to False).
    complete = signal.get("historical_duration_window_complete") is True
    duration_known = complete and signal.get("duration_7d_known_both") is True
    delta = signal.get("duration_7d_advantage_home_seconds") if duration_known else None
    if duration_known and (type(delta) not in (int, float)
                           or not math.isfinite(delta) or abs(delta) > 7 * 12 * 3600):
        raise ValueError("Invalid prior-match duration window")
    return [
        float(known_both), float(seed_difference) / 32,
        seeded_only, float(duration_known),
        ((float(delta) if forward else -float(delta)) / 3600)
        if duration_known else 0.0,
    ]


def _metric(y, p):
    import numpy as np
    from sklearn.metrics import brier_score_loss, log_loss
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0, 1, 11)
    calibration = 0.0
    for index in range(10):
        mask = (p >= edges[index]) & (
            p <= edges[index + 1] if index == 9 else p < edges[index + 1])
        if mask.any():
            calibration += mask.mean() * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return {
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 6),
        "brier": round(float(brier_score_loss(y, p)), 6),
        "ece10": round(float(calibration), 6),
        "n": int(len(y)),
    }


def evaluate(baselines, signals):
    """Rows must be independently time-stamped BEFORE each prediction target."""
    if len({str(s.get("canonical_match_id")) for s in signals
            if s.get("canonical_link_status") == "linked"}) != sum(
                s.get("canonical_link_status") == "linked" for s in signals):
        raise ValueError("Duplicate linked candidate identities")
    linked = {str(s["canonical_match_id"]): s for s in signals
              if s.get("canonical_link_status") == "linked"}
    seen = set()
    matched = []
    reasons = Counter()
    valid_market = []
    for row in baselines:
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Missing or duplicate baseline match_id")
        seen.add(mid)
        event_at = asof(row.get("scheduled_at"))
        predicted_at = asof(row.get("prediction_observed_at"))
        if predicted_at >= event_at:
            raise ValueError("Post-start or simultaneous baseline prediction")
        probability = _probability(row.get("baseline_probability"))
        if type(row.get("target")) is bool or str(row.get("target")) not in ("0", "1"):
            raise ValueError("Binary historical target required")
        target = int(row["target"])
        quote = row.get("market_probability")
        if quote not in (None, ""):
            # A snapshot returned after a historical event with no quoted
            # observation time must NOT be used as a market prior.
            quote_at = row.get("market_observed_at")
            certified = row.get("market_asof_verified") in (True, "true", "True")
            if quote_at and certified and asof(quote_at) < event_at:
                valid_market.append((mid, target, _probability(quote)))
            else:
                reasons["unverified_or_postmatch_market"] += 1
        signal = linked.get(mid)
        if signal is None:
            reasons["missing_exact_link"] += 1
            continue
        if not signal.get("point_in_time_day_snapshotted") is True:
            reasons["snapshot_not_verified"] += 1
            continue
        if signal.get("utc_day") != event_at.date().isoformat():
            raise ValueError("Event date drift between baseline and native signal")
        p1, p2 = str(row.get("player1_id") or ""), str(row.get("player2_id") or "")
        if not p1 or not p2:
            raise ValueError("Native oriented IDs required")
        features = _oriented_signals(signal, p1, p2)
        if not any(features[:3]) and not features[3]:
            reasons["no_candidate_signal"] += 1
            continue
        matched.append((event_at.date().isoformat(), mid, target, probability,
                        features, signal.get("source_prematch_seed_temporal_attestation") is True))
    result = {
        "schema": 1, "scope": "read_only_chronological_research",
        "provider_requests": 0, "cdb_writes": 0, "model_artifacts_written": 0,
        "production_model_activated": False,
        "raw_baseline_rows": len(baselines),
        "linked_baseline_with_candidate": len(matched),
        "market_quotes_time_verified": len(valid_market),
        "unmatched_reasons": dict(reasons),
        "promotable": False,
        "model_721_unchanged": True,
    }
    if len(matched) < MIN_ROWS or len({x[0] for x in matched}) < MIN_DAYS:
        result["status"] = "INSUFFICIENT_CHRONOLOGICAL_DATA"
        return result
    matched.sort(key=lambda item: (item[0], item[1]))
    days = sorted({item[0] for item in matched})
    first = days[max(1, int(len(days) * .6)) - 1]
    second = days[max(2, int(len(days) * .8)) - 1]
    train = [r for r in matched if r[0] <= first]
    calibration = [r for r in matched if first < r[0] <= second]
    holdout = [r for r in matched if r[0] > second]
    if (min(map(len, (train, calibration, holdout))) < 50
            or any(len({r[2] for r in chunk}) < 2
                   for chunk in (train, calibration, holdout))):
        result["status"] = "INSUFFICIENT_CHRONOLOGICAL_SPLIT"
        return result
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def design(items, augmented):
        x = []
        for _, _, _, p, signal, _ in items:
            # Both variants receive the same baseline logit; only the
            # research variant gets the seed and prior-match history features.
            base = [math.log(p / (1 - p))]
            x.append(base + (signal if augmented else []))
        return np.asarray(x, dtype=float)

    ytrain = np.asarray([r[2] for r in train], dtype=int)
    ytest = np.asarray([r[2] for r in holdout], dtype=int)
    variants = {}
    for variant, augmented in (("baseline_recalibrated", False),
                               ("baseline_plus_research_signals", True)):
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=.5))
        model.fit(design(train, augmented), ytrain)
        p = model.predict_proba(design(holdout, augmented))[:, 1]
        variants[variant] = _metric(ytest, p)
    result.update({
        "status": "RESEARCH_ABLATION_COMPLETE",
        "train": len(train), "calibration_reserved_unused": len(calibration),
        "holdout": len(holdout),
        "train_end_utc_day": first, "calibration_end_utc_day": second,
        "holdout_start_utc_day": min(r[0] for r in holdout),
        "variants": variants,
        "seed_source_temporally_attested_rows": sum(r[5] for r in matched),
        "note": ("No promotion; private as-of proof, independent source quality "
                 "and prospective unseen holdout remain required."),
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-csv", required=True, type=Path)
    parser.add_argument("--signals-jsonl", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    a = parser.parse_args()
    report = evaluate(_load_rows(a.baseline_csv), _load_rows(a.signals_jsonl))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
