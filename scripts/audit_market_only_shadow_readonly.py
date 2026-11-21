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
    select_daily_shadow_picks,
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
                for k, d in components.items()
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



def a0_daily_issued_gate(snapshots, conf, freeze, issued_shadow):
    """Verify daily full-slate A0 tiers and independent pre-start issuance receipts.

    This only validates provided evidence: it never creates a receipt, modifies
    a production card or knows whether an unobserved slate day was missing.
    """
    n_min = conf["prospective"]["n_min_daily_shadow"]
    if type(n_min) is not int or n_min != 5:
        raise ValueError("Frozen A0 minimum changed")
    cards = []
    for raw in snapshots:
        start, made = _utc(raw.get("scheduled_at")), _utc(raw.get("model_captured_at"))
        if start is None or made is None or not freeze < made < start:
            continue
        try:
            p = float(raw["model_player1_probability"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(p) or not 0 < p < 1:
            continue
        a, b = str(raw.get("player1_id") or ""), str(raw.get("player2_id") or "")
        if not a or not b or a == b or raw.get("schema") != 1:
            raise ValueError("Invalid canonical full-slate A0 identity")
        pick = a if p >= .5 else b
        quote, issue = _utc(raw.get("market_captured_at")), _utc(raw.get("issued_at"))
        fair = None
        try:
            f1, f2 = float(raw["fair_player1"]), float(raw["fair_player2"])
            if (raw.get("shadow_market_missing") is False
                    and np.isfinite(f1) and np.isfinite(f2)
                    and 0 < f1 < 1 and 0 < f2 < 1
                    and abs(f1 + f2 - 1) <= .0001
                    and quote is not None and issue is not None
                    and freeze < quote <= issue < start
                    and str(raw.get("bookmaker") or "").strip()):
                fair = f1 if p >= .5 else f2
        except (ValueError, TypeError, KeyError):
            pass
        cards.append({
            "event_id": str(raw.get("event_id") or ""),
            "prediction_family": "singles",
            "model_version": str(raw.get("model_version") or ""),
            "tour": str(raw.get("tour") or ""),
            "competition": str(raw.get("competition") or ""),
            "scheduled_at": start.isoformat(),
            "issued_at": issue.isoformat() if fair is not None else None,
            "created_at": made.isoformat(),
            "player1": {"id": a}, "player2": {"id": b},
            "winner_id": pick, "probability": max(p, 1-p),
            "betting": {
                "market": "match_winner", "selection_id": pick,
                "fair_implied_probability": fair,
                "captured_at": quote.isoformat() if fair is not None else None,
            },
        })
    selected = select_daily_shadow_picks(cards, conf, n_min=n_min)
    expected = {}
    daily = {}
    for row in selected:
        day = row["shadow_selection_day_utc"]
        daily[day] = daily.get(day, 0) + 1
        key = (str(row["event_id"]), str(row["betting"]["selection_id"]))
        if key in expected:
            raise ValueError("Duplicate A0 selected fixture/side")
        expected[key] = row
    summary = {
        "minimum_per_observed_day": n_min,
        "observed_days": len(daily),
        "computed_per_day": dict(sorted(daily.items())),
        "shortfall_days": sorted(d for d, n in daily.items() if n < n_min),
        "issued_receipts_verified": False,
        "unobserved_days_not_proven": True,
    }
    if summary["shortfall_days"]:
        return "BLOCKED_A0_DAILY_MINIMUM", summary
    if issued_shadow is None:
        return "BLOCKED_A0_ISSUANCE_NOT_VERIFIED", summary
    actual = {}
    for receipt in issued_shadow:
        if not isinstance(receipt, dict):
            raise ValueError("Malformed shadow issuance evidence")
        key = (str(receipt.get("event_id") or ""),
               str(receipt.get("selection_id") or ""))
        if key not in expected or key in actual:
            raise ValueError("Unknown or duplicate issued shadow event/side")
        row = expected[key]
        issued_at, start = _utc(receipt.get("shadow_issued_at")), _utc(row["scheduled_at"])
        model_time = _utc(row.get("created_at"))
        quote_time = _utc(row["betting"].get("captured_at"))
        price_issued = _utc(row.get("issued_at"))
        first_possible = max(t for t in (model_time, quote_time, price_issued) if t is not None)
        if (issued_at is None or start is None
                or not freeze < issued_at < start or issued_at < first_possible
                or receipt.get("selection_tier") != row["selection_tier"]
                or receipt.get("selection_basis") != row["selection_basis"]
                or receipt.get("day_utc") != row["shadow_selection_day_utc"]
                or not str(receipt.get("receipt_id") or "").strip()):
            raise ValueError("Invalid shadow issuance proof or pre-start timing")
        actual[key] = receipt
    if set(actual) != set(expected):
        summary["issued_per_day"] = {
            day: sum(row["day_utc"] == day for row in actual.values())
            for day in sorted(daily)}
        return "BLOCKED_A0_INCOMPLETE_ISSUANCE", summary
    summary["issued_per_day"] = dict(sorted(daily.items()))
    summary["issued_receipts_verified"] = True
    return "A0_ISSUANCE_VERIFIED_OBSERVED_DAYS", summary


def evaluate(snapshots, settlements, params=PARAMS, *, issued_shadow=None):
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
    a0_state, a0_proof = a0_daily_issued_gate(
        snapshots, conf, freeze, issued_shadow)
    output["a0_daily_issuance"] = a0_proof
    if a0_state != "A0_ISSUANCE_VERIFIED_OBSERVED_DAYS":
        output["status"] = a0_state
        return output  # Seal outcome metrics until every observed day passes.
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
    parser.add_argument("--private-ledger", type=Path,
                        help="Read-only copy of the checksum-verified private A0 release asset")
    parser.add_argument("--snapshots", type=Path)
    parser.add_argument("--settlements", type=Path)
    parser.add_argument("--issued-shadow", type=Path, help="Read-only private shadow issuance receipts")
    parser.add_argument("--params", default=PARAMS, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.private_ledger is not None:
        if args.snapshots or args.settlements or args.issued_shadow:
            parser.error("--private-ledger cannot be mixed with separate inputs")
        ledger = json.loads(args.private_ledger.read_text(encoding="utf-8"))
        if (not isinstance(ledger, dict) or ledger.get("schema") != 1
                or ledger.get("experiment") != "market_only_A0"
                or any(not isinstance(ledger.get(k), list) for k in
                       ("snapshots", "settlements", "issued_shadow"))):
            raise ValueError("Invalid or incomplete private A0 shadow release")
        snapshots, settlements, receipts = (
            ledger["snapshots"], ledger["settlements"], ledger["issued_shadow"])
    else:
        if args.snapshots is None or args.settlements is None:
            parser.error("Provide --private-ledger or both --snapshots/--settlements")
        snapshots, settlements = _json_rows(args.snapshots), _json_rows(args.settlements)
        receipts = _json_rows(args.issued_shadow) if args.issued_shadow else None
    report = evaluate(snapshots, settlements, args.params, issued_shadow=receipts)
    data = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(data, encoding="utf-8")
    print(data, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
