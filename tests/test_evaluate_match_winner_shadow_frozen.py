"""Read-only prospective gate: synthetic rows only, no remote data or model training."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO=Path(__file__).resolve().parents[1]
SCRIPT=REPO/"scripts/evaluate_match_winner_shadow_frozen.py"
spec=importlib.util.spec_from_file_location("sealed_shadow_gate",SCRIPT)
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
FREEZE=REPO/"research/match_winner_shadow/frozen_params_2026-11-20.json"


def synthetic(n):
    rng=np.random.default_rng(20261120)
    return pd.DataFrame({
        "Event_ID":[f"event_{i}" for i in range(n)],
        "Výber_ID":[f"pick_{i}" for i in range(n)],
        "Trh":["match_winner"]*n,
        "Výsledok":np.where(rng.binomial(1,.70,n)==1,"win","loss"),
        "Dátum_zápasu":["2026-11-21T14:00:00Z"]*n,
        gate.CAPTURED:["2026-11-21T09:00:00Z"]*n,
        gate.ISSUED:["2026-11-21T10:00:00Z"]*n,
        gate.FAIR:rng.uniform(.45,.9,n),
        "Model_pravdepodobnosť_%":rng.uniform(55,95,n),
        "Okruh":["atp" if i%2 else "wta" for i in range(n)],
        "Kategória":["TOP" if i%4==0 else "ACCA" for i in range(n)],
    })


def export(tmp_path,df):
    path=tmp_path/"new.csv"
    df.to_csv(path,sep=";",encoding="utf-8-sig",index=False)
    return path


def test_399_valid_tips_blocks_all_outcome_scores(tmp_path):
    report=gate.evaluate(export(tmp_path,synthetic(399)),FREEZE)
    assert report["status"]=="WAIT_FOR_400_NEW_TIPS"
    assert report["counts"]["new_valid_prestart_with_fair"]==399
    assert "scores" not in report and "groups" not in report
    assert "likelihood_ratio" not in report
    assert report["production_modified"] is False and report["model_refit"] is False


def test_400_new_valid_tips_can_be_scored_without_refit(tmp_path):
    result=gate.evaluate(export(tmp_path,synthetic(400)),FREEZE)
    assert result["n_scored"]==400
    assert result["groups"]["ATP"]["n"]==200
    assert result["groups"]["WTA"]["n"]==200
    assert result["scores"]["n"]==400
    assert all(item["n"]==400 for item in result["scores"]["scores"].values())
    assert result["production_modified"] is False
    assert result["model_refit"] is False


def test_future_or_naive_quote_refused_even_when_400_settled(tmp_path):
    df=synthetic(400)
    df.loc[0,gate.CAPTURED]="2026-11-21T14:01:00Z"
    df.loc[1,gate.CAPTURED]="2026-11-21T09:00:00" # no time zone
    report=gate.evaluate(export(tmp_path,df),FREEZE)
    assert report["status"]=="WAIT_FOR_400_NEW_TIPS"
    assert report["counts"]["new_valid_prestart_with_fair"]==398
    assert "scores" not in report


def test_one_missing_fair_is_not_silently_1_over_odds(tmp_path):
    df=synthetic(400)
    df.loc[0,gate.FAIR]=np.nan
    df["Kurz"]=[1.40]*400
    report=gate.evaluate(export(tmp_path,df),FREEZE)
    assert report["status"]=="WAIT_FOR_400_NEW_TIPS"
    assert report["counts"]["new_rejected_fair_or_model"]==1
    assert report["counts"]["new_valid_prestart_with_fair"]==399


def test_pre_freeze_records_do_not_count(tmp_path):
    df=synthetic(410)
    df["Dátum_zápasu"]="2026-11-20T18:00:00Z"
    df[gate.CAPTURED]="2026-11-20T16:00:00Z"
    df[gate.ISSUED]="2026-11-20T17:00:00Z"
    report=gate.evaluate(export(tmp_path,df),FREEZE)
    assert report["status"]=="WAIT_FOR_400_NEW_TIPS"
    assert report["counts"]["new_settled_match_winner_after_freeze"]==0


def test_pinned_adapter_hash_cannot_change(tmp_path):
    freeze=json.loads(FREEZE.read_text(encoding="utf-8"))
    freeze["adapter_blob_sha1"]="f"*40
    path=tmp_path/"tampered.json"
    path.write_text(json.dumps(freeze),encoding="utf-8")
    with pytest.raises(ValueError,match="SHA mismatch"):
        gate.frozen(path)


def test_prospective_threshold_cannot_be_lowered(tmp_path):
    freeze=json.loads(FREEZE.read_text(encoding="utf-8"))
    freeze["minimum_new_prestart_fair_pairs"]=399
    path=tmp_path/"lowered.json"
    path.write_text(json.dumps(freeze),encoding="utf-8")
    with pytest.raises(ValueError,match="Invalid or relaxed"):
        gate.frozen(path)
