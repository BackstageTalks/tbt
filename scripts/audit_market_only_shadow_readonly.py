#!/usr/bin/env python3
"""B2: read-only sealed prospective full-slate winner comparison.

Requires true after-freeze model & two-way price evidence and independently
settled canonical winners. Before 400 valid new matches, report COUNTS ONLY.
Never writes CDB, model, offers, providers or a new shadow ledger.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from tbt.services.market_only_shadow_research import (
    _utc, load_shadow_params, calibrate_market_only,
)

PARAMS = ROOT / "research/market_only_shadow/params_2026-11-20.json"
NBOOT = 2000


def _json_rows(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Require a JSON array of privately captured full-slate rows")
    return data


def eligible(snapshots, settlements, freeze):
    """No name matching, same-day odds backfill, or post-start price repair."""
    completed = {}
    for row in settlements:
        if not isinstance(row, dict):
            raise ValueError("Invalid canonical outcome object")
        key = str(row.get("event_id") or "").strip()
        if not key or key in completed:
            raise ValueError("Duplicate or missing settlement event ID")
        completed[key] = row
    seen = set()
    rows = []
    counts = {"staged": len(snapshots), "post_freeze_prematch": 0,
              "valid_two_way_prestart_settled": 0, "missing_market_or_time": 0,
              "pending_or_void": 0, "pre_freeze_or_bad_model": 0}
    for row in snapshots:
        if not isinstance(row, dict):
            raise ValueError("Invalid private full-slate snapshot")
        event = str(row.get("event_id") or "").strip()
        if not event or event in seen:
            raise ValueError("Duplicate/blank frozen snapshot identity")
        seen.add(event)
        a, b = str(row.get("player1_id") or ""), str(row.get("player2_id") or "")
        if not a or not b or a == b or row.get("schema") != 1:
            raise ValueError("Invalid exact canonical player pair")
        start = _utc(row.get("scheduled_at"))
        model_at = _utc(row.get("model_captured_at"))
        if (start is None or model_at is None
                or not (freeze < model_at < start and freeze < start)):
            counts["pre_freeze_or_bad_model"] += 1
            continue
        try:
            p = float(row.get("model_player1_probability"))
        except (TypeError, ValueError):
            counts["pre_freeze_or_bad_model"] += 1
            continue
        if not (np.isfinite(p) and 0 < p < 1):
            counts["pre_freeze_or_bad_model"] += 1
            continue
        counts["post_freeze_prematch"] += 1
        if row.get("shadow_market_missing") is not False:
            counts["missing_market_or_time"] += 1
            continue
        quote = _utc(row.get("market_captured_at"))
        issued = _utc(row.get("issued_at"))
        if quote is None or issued is None or not (freeze < quote <= issued < start):
            counts["missing_market_or_time"] += 1
            continue
        try:
            fair1, fair2 = float(row.get("fair_player1")), float(row.get("fair_player2"))
        except (TypeError, ValueError):
            counts["missing_market_or_time"] += 1
            continue
        if (not np.isfinite(fair1) or not np.isfinite(fair2)
                or not 0 < fair1 < 1 or not 0 < fair2 < 1
                or abs(fair1 + fair2 - 1) > .0001
                or not str(row.get("bookmaker") or "").strip()):
            counts["missing_market_or_time"] += 1
            continue
        settlement = completed.get(event)
        if not settlement or settlement.get("status") in ("void", "excluded", "pending"):
            counts["pending_or_void"] += 1
            continue
        if settlement.get("status") != "settled":
            raise ValueError("Unexpected canonical settlement status")
        settled_at = _utc(settlement.get("settled_at"))
        if settled_at is None or not start < settled_at:
            raise ValueError("Canonical outcome timestamp precedes fixture start")
        winner = str(settlement.get("winner_id") or "")
        if winner not in (a, b):
            raise ValueError("Canonical settled winner identity conflict")
        rows.append({
            "event_id": event, "y": int(winner == a), "p": p, "fair": fair1,
            "tour": str(row.get("tour") or "").upper(),
            "category": str(row.get("category_at_capture") or ""),
            "day": start.date().isoformat(),
        })
        counts["valid_two_way_prestart_settled"] += 1
    return rows, counts


def scores(y, p):
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    if not len(y) or len(y) != len(p) or not np.isfinite(p).all():
        raise ValueError("Invalid equal-match score sample")
    p = np.clip(p, .01, .99)
    bins = np.minimum((p*10).astype(int), 9)
    ece = sum(float((bins == i).mean() *
                    abs(p[bins == i].mean()-y[bins == i].mean()))
              for i in range(10) if (bins == i).any())
    correct = (p >= .5) == y
    return {"n": len(y), "correct": int(correct.sum()),
            "accuracy": float(correct.mean()),
            "log_loss": float((-y*np.log(p)-(1-y)*np.log1p(-p)).mean()),
            "brier": float(((p-y)**2).mean()), "ece10": ece}


def paired(y, new, old, *, seed):
    y = np.asarray(y, dtype=int)
    new, old = np.clip(np.asarray(new, dtype=float), .01, .99), np.clip(np.asarray(old, dtype=float), .01, .99)
    a, b = (new >= .5) == y, (old >= .5) == y
    only_new, only_old = int((a & ~b).sum()), int((b & ~a).sum())
    components = {
        "log_loss": -y*np.log(new)-(1-y)*np.log1p(-new) +
                    y*np.log(old)+(1-y)*np.log1p(-old),
        "brier": (new-y)**2-(old-y)**2,
    }
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(y), size=(NBOOT, len(y)))
    return {"new_only_correct": only_new, "old_only_correct": only_old,
            "mcnemar_exact_p": float(binomtest(only_new, only_new+only_old, .5).pvalue)
            if only_new+only_old else 1.,
            "bootstrap": {
                k: {"delta": float(d.mean()),
                    "mean": float(d[idx].mean(axis=1).mean()),
                    "ci95": [float(x) for x in np.quantile(d[idx].mean(axis=1), (.025, .975))]}
                for k, d in components.items(),
            }}


def compare(rows, params, *, seed=20261120):
    y = np.array([r["y"] for r in rows], dtype=int)
    p = np.array([r["p"] for r in rows], dtype=float)
    market = np.array([r["fair"] for r in rows], dtype=float)
    q = np.array([calibrate_market_only(float(x), params) for x in market])
    return {
        "n": len(rows), "unreliable_n_lt_80": len(rows) < 80,
        "probabilities": {
            "BlinQ": scores(y, p), "Market": scores(y, market),
            "MarketCalibratedShadow": scores(y, q),
        },
        "paired": {
            "vs_BlinQ": paired(y, q, p, seed=seed),
            "vs_Market": paired(y, q, market, seed=seed+1),
        },
    }


def evaluate(snapshots, settlements, params=PARAMS):
    conf = load_shadow_params(params)
    freeze = _utc(conf["prospective"]["freeze_after_utc"])
    if (freeze is None or conf["prospective"].get("minimum_new_valid_matches") != 400
            or conf["prospective"].get("no_refit") is not True):
        raise ValueError("Frozen prospective policy changed or removed")
    rows, counts = eligible(snapshots, settlements, freeze)
    output = {
        "status": "WAIT_FOR_400_NEW_MATCHES",
        "counts": counts,
        "parameter_sha256": hashlib.sha256(Path(params).read_bytes()).hexdigest(),
        "no_refit": True, "no_production_write": True,
        "provider_requests": 0, "wta_historical_slope_unverified": True,
    }
    if counts["valid_two_way_prestart_settled"] < 400:
        return output
    overall = compare(rows, conf)
    groups = {}
    for i, (label, field, value) in enumerate((
        ("ATP", "tour", "ATP"), ("WTA", "tour", "WTA"),
        ("TOP", "category", "TOP"), ("Value", "category", "Value"),
        ("ACCA", "category", "ACCA"),
    )):
        group = [row for row in rows if row[field] == value]
        if group:
            groups[label] = compare(group, conf, seed=20261120+i*101)
    # A positive-slope market-only adapter does not change market ranks.
    original_order = sorted(rows, key=lambda r: (-r["fair"], r["event_id"]))
    adapted_order = sorted(rows, key=lambda r: (
        -calibrate_market_only(r["fair"], conf), r["event_id"]))
    if [r["event_id"] for r in original_order] != [
            r["event_id"] for r in adapted_order]:
        raise ValueError("Monotone market transform must preserve same-slate ranking")
    # Score the raw market as well; no green claim from market-only sorting.
    return {
        **output, "status": "REVIEW_ONLY_NO_AUTO_ACTIVATION",
        "overall": overall, "groups": groups,
        "same_N_market_baseline": {
            "n": len(rows), "identical_market_calibrated_order": True,
            "market_correct": overall["probabilities"]["Market"]["correct"],
            "shadow_correct": overall["probabilities"]["MarketCalibratedShadow"]["correct"],
        },
        "decision": "REVIEW_ONLY_NEVER_AUTO_PROMOTE",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", required=True, type=Path)
    parser.add_argument("--settlements", required=True, type=Path)
    parser.add_argument("--params", default=PARAMS, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = evaluate(_json_rows(args.snapshots), _json_rows(args.settlements), args.params)
    data = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(data, encoding="utf-8")
    print(data, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
