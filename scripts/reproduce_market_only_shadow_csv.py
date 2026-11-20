#!/usr/bin/env python3
"""Offline selected-only sanity check; NEVER a full-slate or prospective proof.

Usage:
  PYTHONPATH=api python scripts/reproduce_market_only_shadow_csv.py --results results.csv
No model refit, bookmaker API calls, CDB changes, or production offers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from tbt.services.market_only_shadow_research import (
    load_shadow_params, calibrate_market_only,
)

CONF = ROOT / "research/market_only_shadow/params_2026-11-20.json"
FAIR = "src_publikácia.issued_snapshot.betting.fair_implied_probability"
CAP = "src_publikácia.issued_snapshot.betting.captured_at"
ISS = "src_publikácia.issued_at"


def score(y, p):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=int)
    correct = (p >= .5) == y
    return {"n": len(y), "correct": int(correct.sum()),
            "accuracy": float(correct.mean()),
            "log_loss": float((-y*np.log(p)-(1-y)*np.log1p(-p)).mean()),
            "brier": float(((p-y)**2).mean())}


def evaluate(path, params_path=CONF):
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
    df = df.loc[df["Trh"].eq("match_winner") &
                df["Výsledok"].isin(("win", "loss"))].copy()
    if df[["Event_ID", "Výber_ID"]].isna().any().any():
        raise ValueError("Cannot deduplicate without exact event and pick ID")
    df = df.drop_duplicates(["Event_ID", "Výber_ID"])
    total = len(df)
    df["fair"] = pd.to_numeric(df[FAIR], errors="coerce")
    df["p"] = pd.to_numeric(df["Model_pravdepodobnosť_%"], errors="coerce") / 100
    for original, new in (("Dátum_zápasu", "start"), (CAP, "capture"),
                          (ISS, "issued")):
        # Mixed ISO precision is important; naive default pandas parsing
        # incorrectly marks hundreds of actual captures invalid.
        df[new] = pd.to_datetime(df[original], utc=True, errors="coerce",
                                 format="mixed")
    df = df.loc[df["fair"].notna()].copy()
    priced = len(df)
    valid = (df["capture"].lt(df["start"]) &
             df["capture"].le(df["issued"]) &
             df["issued"].lt(df["start"]) &
             df["p"].between(0, 1) & df["fair"].gt(0) & df["fair"].lt(1))
    df = df.loc[valid].copy()
    df["p"] = df["p"].clip(.01, .99)
    df["fair"] = df["fair"].clip(.01, .99)
    df["y"] = df["Výsledok"].eq("win").astype(int)
    params = load_shadow_params(params_path)
    df["shadow"] = [calibrate_market_only(float(f), params) for f in df["fair"]]
    df["gap"] = (df["p"]-df["fair"]).abs()
    df["tour"] = df["Okruh"].astype(str).str.upper().str.strip()
    y = df["y"].to_numpy(int)
    choices = (("blinq", "p"), ("raw_market", "fair"),
               ("market_only_shadow", "shadow"))
    result = {
        "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "unique_settled_match_winner": total,
        "with_fair": priced, "missing_fair": total - priced,
        "valid_prestart_with_fair": len(df),
        "rejected_price_or_probability": priced-len(df),
        "scores": {k: score(y, df[v].to_numpy(float)) for k, v in choices},
        "tour": {tour: {
            k: score(group.y.to_numpy(int), group[v].to_numpy(float))
            for k, v in choices}
            for tour, group in df.groupby("tour")},
        "selected_only_not_full_slate": True,
        "market_source_fit_not_reproduced": True,
        "no_production_modification": True,
        "variants": {},
    }
    masks = {
        "A1_market_rank_veto": df["fair"] >= .5,
        "A2_market_min_0_75": df["fair"] >= .75,
        "A3_gap_0_10": df["gap"] <= .10,
        "A1_A2_A3_combined": (df["fair"] >= .75) & (df["gap"] <= .10),
    }
    for label, mask in masks.items():
        chosen = df.loc[mask]
        benchmark = df.sort_values(["fair", "Event_ID", "Výber_ID"],
                                   ascending=[False, True, True]).head(len(chosen))
        result["variants"][label] = {
            "n": len(chosen),
            "wins": int(chosen["y"].sum()),
            "accuracy": float(chosen["y"].mean()) if len(chosen) else None,
            "same_N_market_baseline_wins": int(benchmark["y"].sum()),
            "same_N_market_baseline_accuracy":
                float(benchmark["y"].mean()) if len(benchmark) else None,
            "not_prospective_evidence": True,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--params", default=CONF, type=Path)
    args = parser.parse_args(argv)
    result = evaluate(args.results, args.params)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False,
                     allow_nan=False))


if __name__ == "__main__":
    main()
