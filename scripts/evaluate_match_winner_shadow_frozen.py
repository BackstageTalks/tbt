#!/usr/bin/env python3
"""Read-only, sealed forward match-winner shadow evaluation; never fits a model.

Usage:
  python scripts/evaluate_match_winner_shadow_frozen.py --results NEW.csv --out report.json
Before 400 new paired, settled, pre-start tips: only coverage counters, NO outcomes
or comparative scores. Parameters stay frozen and no prod/CDB/API state is touched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.special import logit
from scipy.stats import binomtest, chi2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from tbt.models.market_shadow_calibration import MarketShadowParams, blend_with_market

FREEZE = ROOT / "research/match_winner_shadow/frozen_params_2026-11-20.json"
FAIR = "src_publikácia.issued_snapshot.betting.fair_implied_probability"
CAPTURED = "src_publikácia.issued_snapshot.betting.captured_at"
ISSUED = "src_publikácia.issued_at"
NBOOT = 2000
SEED = 20261120


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def frozen(path=FREEZE):
    conf = json.loads(Path(path).read_text(encoding="utf-8"))
    if (conf.get("schema") != 1 or conf.get("mode") != "read_only_shadow_no_activation"
            or conf.get("production_activation") is not False
            or conf.get("minimum_new_settled_tips") != 400
            or conf.get("minimum_new_prestart_fair_pairs") != 400
            or conf.get("no_refit_before_400") is not True):
        raise ValueError("Invalid or relaxed frozen release gate")
    stamp = str(conf["frozen_at_utc"])
    if not stamp.endswith("Z"):
        raise ValueError("Freeze requires explicit UTC timestamp")
    instant = pd.to_datetime(stamp, utc=True, errors="raise")
    adapter = (ROOT / "api/tbt/models/market_shadow_calibration.py").read_bytes()
    if git_blob_sha(adapter) != conf["adapter_blob_sha1"]:
        raise ValueError("Frozen probability adapter SHA mismatch")
    return conf, instant, MarketShadowParams(**conf["params"])


def load_new(path, cutoff):
    src = pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
    mandatory = ("Event_ID", "Výber_ID", "Trh", "Výsledok", "Dátum_zápasu",
                 "Model_pravdepodobnosť_%", FAIR, CAPTURED, ISSUED, "Okruh", "Kategória")
    missing = sorted(set(mandatory) - set(src.columns))
    if missing:
        raise ValueError("Missing required columns: " + str(missing))
    raw_n = len(src)
    d = src.loc[src["Trh"].eq("match_winner") &
                src["Výsledok"].isin(("win", "loss"))].copy()
    pre_dedup = len(d)
    if d[["Event_ID", "Výber_ID"]].isna().any().any():
        raise ValueError("Cannot deduplicate without exact event and selection ID")
    d = d.drop_duplicates(["Event_ID", "Výber_ID"]).copy()
    # utc=True alone would silently assume a timezone for naive timestamps.
    zoned = lambda col: d[col].astype("string").str.strip().str.contains(
        r"(?:Z|[+-]\d{2}:\d{2})$", case=False, regex=True, na=False)
    explicit = zoned("Dátum_zápasu") & zoned(CAPTURED) & zoned(ISSUED)
    for orig, name in (("Dátum_zápasu", "start"), (CAPTURED, "captured"),
                       (ISSUED, "issued")):
        d[name] = pd.to_datetime(d[orig], utc=True, errors="coerce", format="mixed")
    d["p0"] = pd.to_numeric(d["Model_pravdepodobnosť_%"], errors="coerce") / 100
    d["fair0"] = pd.to_numeric(d[FAIR], errors="coerce")
    d["tour"] = d["Okruh"].astype("string").str.upper().str.strip()
    d["y"] = d["Výsledok"].eq("win").astype(int)
    new_date = d["start"].notna() & d["start"].gt(cutoff)
    after_freeze = (new_date & explicit & d["captured"].gt(cutoff) &
                    d["issued"].gt(cutoff))
    quote_ok = (d["captured"].lt(d["start"]) & d["issued"].lt(d["start"]) &
                d["captured"].le(d["issued"]) & d["captured"].notna() &
                d["issued"].notna() & d["start"].notna())
    probabilities_ok = d["p0"].between(0, 1) & d["fair0"].gt(0) & d["fair0"].lt(1)
    good = after_freeze & quote_ok & probabilities_ok
    counts = {
        "raw_rows": int(raw_n),
        "settled_match_winner_before_dedup": int(pre_dedup),
        "unique_settled_match_winner": int(len(d)),
        "new_settled_match_winner_after_freeze": int(new_date.sum()),
        "new_issued_captured_timezone_proven_after_freeze": int(after_freeze.sum()),
        "new_valid_prestart_with_fair": int(good.sum()),
        "new_rejected_clock_or_zone": int((new_date & ~after_freeze).sum() +
                                          (after_freeze & ~quote_ok).sum()),
        "new_rejected_fair_or_model": int((after_freeze & quote_ok &
                                            ~probabilities_ok).sum()),
    }
    chosen = d.loc[good].copy().sort_values(["start", "Event_ID", "Výber_ID"])
    chosen["p"] = chosen["p0"].clip(.01, .99)
    chosen["fair"] = chosen["fair0"].clip(.01, .99)
    return chosen, counts


def scoring(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), .01, .99)
    if not len(y) or len(p) != len(y) or not np.isfinite(p).all():
        raise ValueError("Unpaired or non-finite predictions")
    which = np.minimum((p * 10).astype(int), 9)
    ece = sum(float((which == i).mean() * abs(p[which == i].mean() -
                                             y[which == i].mean()))
              for i in range(10) if (which == i).any())
    return {"n": len(y), "correct": int(((p >= .5) == y).sum()),
            "accuracy": float(((p >= .5) == y).mean()),
            "log_loss": float((-y * np.log(p) - (1 - y) * np.log1p(-p)).mean()),
            "brier": float(((p-y)**2).mean()), "ece10": ece}


def paired(y, shadow, other, *, seed):
    y = np.asarray(y, dtype=int)
    x = (shadow >= .5) == y
    z = (other >= .5) == y
    one, two = int((x & ~z).sum()), int((z & ~x).sum())
    rng = np.random.default_rng(seed)
    logdiff = (-y*np.log(shadow) - (1-y)*np.log1p(-shadow) +
                y*np.log(other) + (1-y)*np.log1p(-other))
    bootstrap = np.array([logdiff[rng.integers(0,len(y),len(y))].mean()
                          for _ in range(NBOOT)])
    lo, hi = np.quantile(bootstrap, (.025, .975))
    return {"shadow_only_correct": one, "other_only_correct": two,
            "mcnemar_exact_p": float(binomtest(one, one+two, .5).pvalue)
                                if one+two else 1.,
            "log_loss_delta": float(logdiff.mean()),
            "log_loss_bootstrap_mean": float(bootstrap.mean()),
            "log_loss_ci95": [float(lo), float(hi)],
            "log_loss_proven_better": bool(hi < 0)}


def cohort(d, shadow, seed):
    y = d["y"].to_numpy(dtype=int)
    p, fair = d["p"].to_numpy(float), d["fair"].to_numpy(float)
    return {"n": len(d), "unreliable_n_lt_80": bool(len(d)<80),
            "scores": {"BlinQ": scoring(y,p), "Market": scoring(y,fair),
                       "Shadow": scoring(y,shadow)},
            "paired": {"vs_BlinQ": paired(y,shadow,p,seed=seed),
                       "vs_Market": paired(y,shadow,fair,seed=seed+1)}}


def lr_test(y, p, market):
    import statsmodels.api as sm
    y=np.asarray(y,int)
    xp=logit(p)
    xm=logit(market)
    def fit(x):
        return sm.Logit(y,sm.add_constant(x,has_constant="add")).fit(disp=False,maxiter=250)
    m, b, both = fit(xm), fit(xp), fit(np.column_stack((xm,xp)))
    z1,z2=2*(both.llf-m.llf),2*(both.llf-b.llf)
    return {"n":len(y), "model_coef":float(both.params[2]),
            "market_coef":float(both.params[1]),
            "model_above_market_chi2":float(z1),
            "model_above_market_p":float(chi2.sf(z1,1)),
            "market_above_model_chi2":float(z2),
            "market_above_model_p":float(chi2.sf(z2,1)),
            "note":"descriptive LR on prospective observations; no refit of frozen shadow"}


def evaluate(input_path, manifest_path=FREEZE):
    conf, timestamp, params = frozen(manifest_path)
    d, counts = load_new(input_path, timestamp)
    result = {"status":"WAIT_FOR_400_NEW_TIPS", "counts":counts,
              "frozen_at_utc":conf["frozen_at_utc"],"frozen_params":conf["params"],
              "manifest_sha256":hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
              "input_sha256":hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
              "production_modified":False,"provider_requests":0,"model_refit":False}
    if (counts["new_settled_match_winner_after_freeze"] < 400 or len(d) < 400):
        return result  # No outcome metrics or group evaluation before the sealed gate.
    q, fallback = blend_with_market(
        d.p.to_numpy(float),d.fair.to_numpy(float),params,
        captured_at=d.captured.tolist(), issued_at=d.issued.tolist(),
        scheduled_at=d.start.tolist(), return_fallback_mask=True)
    if fallback.any():
        raise ValueError("Invalid shadow pre-start quote evidence")
    overall=cohort(d,q,SEED)
    groups={}
    for i,(name,mask) in enumerate((
        ("ATP",d.tour.eq("ATP")), ("WTA",d.tour.eq("WTA")),
        ("TOP",d["Kategória"].eq("TOP")), ("Value",d["Kategória"].eq("Value")),
        ("ACCA",d["Kategória"].eq("ACCA")))):
        sub=d.loc[mask].copy()
        if len(sub):
            groups[name]=cohort(sub,q[d.index.get_indexer(sub.index)],SEED+100+i*11)
    opposing=d.loc[(d.p >= .5) & (d.fair < .5)]
    wins=int(opposing.y.sum())
    opp={"n":len(opposing),"wins":wins,
         "win_rate":float(opposing.y.mean()) if len(opposing) else None,
         "binom_p":float(binomtest(wins,len(opposing),.5).pvalue) if len(opposing) else None,
         "underpowered_n_lt_200":bool(len(opposing)<200)}
    better=overall["paired"]["vs_BlinQ"]["log_loss_proven_better"]
    better_market=overall["paired"]["vs_Market"]["log_loss_proven_better"]
    tours_ok=all(k in groups and not groups[k]["unreliable_n_lt_80"] and
        groups[k]["paired"]["vs_BlinQ"]["log_loss_proven_better"] and
        groups[k]["paired"]["vs_Market"]["log_loss_proven_better"]
        for k in ("ATP","WTA"))
    worsens_tour=any(k in groups and groups[k]["scores"]["Shadow"]["log_loss"] >
                     groups[k]["scores"]["BlinQ"]["log_loss"] for k in ("ATP","WTA"))
    ece_delta=overall["scores"]["Shadow"]["ece10"]-overall["scores"]["BlinQ"]["ece10"]
    if not better or worsens_tour:
        decision="RED_NO_ACTIVATION"
    elif better_market and tours_ok and ece_delta <= .01:
        decision="GREEN_REVIEW_EXPLICIT_APPROVAL_REQUIRED"
    else:
        decision="YELLOW_OR_INCONCLUSIVE_NO_ACTIVATION"
    return {**result,"status":decision,"n_scored":len(d),"scores":overall,
            "groups":groups,"opposing_favorite":opp,
            "likelihood_ratio":lr_test(d.y.to_numpy(int),d.p.to_numpy(float),
                                        d.fair.to_numpy(float)),
            "ece_delta_shadow_minus_blinq":float(ece_delta),
            "green_tour_proven":tours_ok,
            "filter_proposal_only_gap":.08 if better and not better_market else None}


def main(argv=None):
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--results",required=True,type=Path)
    arg.add_argument("--freeze",type=Path,default=FREEZE)
    arg.add_argument("--out",type=Path)
    args=arg.parse_args(argv)
    answer=evaluate(args.results,args.freeze)
    encoded=json.dumps(answer,indent=2,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n"
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(encoded,encoding="utf-8")
    print(encoded,end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
