"""Read-only paired error diagnosis on actually issued frozen 7.2.1 predictions.

This audit does not rescore historical matches and does not change the model.
No EV, betting odds, value, profit, ROI or promotion decisions.

Scope: exact pinned candidate/champion pair in the private immutable-first
shadow ledger. Segment bins are fixed in advance, not optimized on outcomes.
Near-start (<15m) evidence is quarantined from scored metrics because older
refresh implementations could record an inference-start rather than an exact
wall-clock completed-prediction timestamp.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore
from tbt.models.metrics import evaluate_probabilities, wilson_interval
from tbt.services.frozen_721_research import (
    FROZEN_721_MODEL_SHA256, FROZEN_721_VERSION,
    validate_frozen_evidence, exclude_repeated_events,
)
from frozen_721_shadow_capture import SHADOW_TAG, LEDGER_ASSET, REPORT_ASSET

DATA_REPO = "BackstageTalks/tbt-data"
MIN_CAPTURE_LEAD_SECONDS = 15 * 60
VIP_PROBABILITY_TIERS = (0.80, 0.78, 0.75, 0.70)
MIN_EVIDENCE_FOR_HIT_RATE = 100

def _time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Non-UTC/naive temporal shadow record")
    return result.astimezone(timezone.utc)


def _surface(row):
    raw = str(row.get("surface") or "").strip().lower()
    return {
        "clay": "clay", "grass": "grass", "hard": "hard",
        "indoor_hard": "indoor_hard", "carpet": "carpet",
    }.get(raw, "unknown_or_other")


def _champion_confidence(row):
    p = float(row["production_player1_probability"])
    confidence = max(p, 1 - p)
    if confidence < .60:
        return "50-60"
    if confidence < .70:
        return "60-70"
    if confidence < .80:
        return "70-80"
    return "80-100"


def _round(value):
    if value is None:
        return None
    number = float(value)
    return round(number, 8) if math.isfinite(number) else None


def _model_metrics(rows, probability_field):
    n = len(rows)
    if not n:
        return {"n": 0, "correct": 0, "accuracy": None,
                "accuracy_ci95_wilson": None, "log_loss": None,
                "brier_score": None, "ece_10": None}
    y = [int(r["target_player1_win"]) for r in rows]
    p = [float(r[probability_field]) for r in rows]
    metrics = evaluate_probabilities(y, p)
    correct = sum(int((prob >= .5) == bool(target)) for prob, target in zip(p, y))
    return {
        "n": n, "correct": correct,
        "accuracy": _round(metrics["accuracy"]),
        "accuracy_ci95_wilson": [
            _round(x) for x in wilson_interval(correct, n)
        ],
        "log_loss": _round(metrics["log_loss"]),
        "brier_score": _round(metrics["brier_score"]),
        "ece_10": _round(metrics["ece_10"]),
    }


def _paired_result(rows):
    champion = _model_metrics(rows, "production_player1_probability")
    candidate = _model_metrics(rows, "challenger_player1_probability")
    disagree = 0
    candidate_only = 0
    champion_only = 0
    both_wrong = 0
    for row in rows:
        truth = bool(row["target_player1_win"])
        champ = float(row["production_player1_probability"]) >= .5
        chal = float(row["challenger_player1_probability"]) >= .5
        disagree += int(champ != chal)
        champion_only += int(champ == truth and chal != truth)
        candidate_only += int(chal == truth and champ != truth)
        both_wrong += int(chal != truth and champ != truth)
    return {
        "n": len(rows),
        "champion": champion,
        "candidate_721": candidate,
        "candidate_minus_champion": {
            key: _round(candidate[key] - champion[key])
            if rows else None
            for key in ("accuracy", "log_loss", "brier_score", "ece_10")
        },
        "paired_diagnostics": {
            "winner_disagreement": disagree,
            "champion_only_correct": champion_only,
            "candidate_only_correct": candidate_only,
            "both_wrong": both_wrong,
            "paired_accuracy_difference_ci95": _paired_difference_ci(rows),
        },
        "interpretation": "PRELIMINARY_SMALL_N_NO_AUTOMATIC_MODEL_SELECTION",
    }


def _paired_difference_ci(rows):
    """Conservative normal approximation for paired binary accuracy delta.

    Interval displayed only for >=30 independent, identity-deduplicated rows.
    No false certainty from the first handful of prospective outcomes.
    """
    n = len(rows)
    if n < 30:
        return None
    values = []
    for row in rows:
        target = bool(row["target_player1_win"])
        correct_champion = (float(row["production_player1_probability"]) >= .5) == target
        correct_candidate = (float(row["challenger_player1_probability"]) >= .5) == target
        values.append(int(correct_candidate) - int(correct_champion))
    average = sum(values)/n
    variance = sum((v-average)**2 for v in values)/(n-1)
    radius = 1.959963984540054 * math.sqrt(variance/n)
    return [_round(max(-1., average-radius)), _round(min(1., average+radius))]


def _vip_local_day(row):
    """Same 06:00 Europe/Bratislava betting-day boundary as public TOP."""
    return (_time(row["scheduled_at"]).astimezone(ZoneInfo("Europe/Bratislava"))
            - timedelta(hours=6)).date().isoformat()


def _vip_confidence(row, model="challenger"):
    p = float(row[model + "_player1_probability"])
    return max(p, 1. - p)


def _vip_outcome_metrics(rows, model="challenger"):
    """Always score the side selected BEFORE the outcome was known."""
    settled = [row for row in rows if row["status"] == "settled"]
    wins = sum(
        bool(float(row[model + "_player1_probability"]) >= .5)
        == bool(row["target_player1_win"])
        for row in settled
    )
    n = len(settled)
    interval = [_round(x) for x in wilson_interval(wins, n)] if n else None
    return {
        "offered_before_settlement": len(rows),
        "settled": n, "pending_or_void": len(rows) - n, "wins": wins,
        "hit_rate": _round(wins / n) if n else None,
        "mean_issued_raw_confidence": _round(
            sum(_vip_confidence(row, model) for row in settled) / n) if n else None,
        "hit_rate_ci95_wilson": interval,
        "target_80_evidenced": bool(
            n >= MIN_EVIDENCE_FOR_HIT_RATE and interval is not None
            and interval[0] >= .80),
        "target_87_evidenced": bool(
            n >= MIN_EVIDENCE_FOR_HIT_RATE and interval is not None
            and interval[0] >= .87),
    }


def _vip_prospective_scorecard(all_rows):
    """Outcome-blind daily selector on already issued *raw model* forecasts.

    This is a diagnostic, NOT a VIP price-qualified replay: there is no
    immutable two-way bookmaker price or public data-depth shrinkage in this
    shadow cohort. Select from settled AND pending rows before scoring any wins.
    """
    days = {}
    for row in all_rows:
        days.setdefault(_vip_local_day(row), []).append(row)
    selected = []
    daily = {}
    for day, rows in sorted(days.items()):
        applied = VIP_PROBABILITY_TIERS[-1]
        for tier in VIP_PROBABILITY_TIERS:
            applied = tier
            if sum(_vip_confidence(row) + 1e-12 >= tier for row in rows) >= 3:
                break
        chosen = [row for row in rows if _vip_confidence(row) + 1e-12 >= applied]
        selected.extend(chosen)
        daily[day] = {
            "captured": len(rows), "applied_raw_confidence_floor": applied,
            "selected": len(chosen),
            "below_three": len(chosen) < 3,
            "settled_selected": sum(r["status"] == "settled" for r in chosen),
        }
    bins = [
        ("80_plus", .80, 1.01), ("78_80", .78, .80),
        ("75_78", .75, .78), ("70_75", .70, .75),
    ]
    return {
        "status": "RAW_MODEL_PROSPECTIVE_DIAGNOSTIC_NOT_PRICE_QUALIFIED_VIP",
        "scope": "only exact pinned pre-start frozen candidate/champion pairs, each scheduled local betting day",
        "days_with_captured_cohort": len(daily),
        "days_with_3plus_raw_qualifiers": sum(not x["below_three"] for x in daily.values()),
        "daily": daily,
        "all_selected": _vip_outcome_metrics(selected),
        "core_80_plus": _vip_outcome_metrics([
            r for r in selected if _vip_confidence(r) >= .80]),
        "fallback_below_80": _vip_outcome_metrics([
            r for r in selected if _vip_confidence(r) < .80]),
        "by_tour": {tour: {
            "selected": _vip_outcome_metrics([
                r for r in selected if str(r["tour"]).upper() == tour]),
            "core_80_plus": _vip_outcome_metrics([
                r for r in selected
                if str(r["tour"]).upper() == tour and _vip_confidence(r) >= .80]),
            "fallback_below_80": _vip_outcome_metrics([
                r for r in selected
                if str(r["tour"]).upper() == tour and _vip_confidence(r) < .80]),
        } for tour in ("ATP", "WTA")},
        "by_raw_confidence_band": {
            name: _vip_outcome_metrics([
                r for r in selected if low <= _vip_confidence(r) < high])
            for name, low, high in bins
        },
        "fixed_cumulative_thresholds": {
            str(tier): _vip_outcome_metrics([
                r for r in all_rows if _vip_confidence(r) + 1e-12 >= tier])
            for tier in VIP_PROBABILITY_TIERS
        },
        "minimum_settled_for_hit_rate_evidence": MIN_EVIDENCE_FOR_HIT_RATE,
        "fixed_tiers": list(VIP_PROBABILITY_TIERS),
        "no_model_retrained": True, "model_promoted": False,
        "provider_requests": 0,
        "limitations": [
            "This study uses raw model probabilities, not depth-adjusted published BlinQ confidence.",
            "No verified pre-match bookmaker odds or TOP/Value eligibility gates exist in frozen shadow rows.",
            "Captured fixtures may be only a subset of the full daily tennis board.",
            "Only previously recorded forecast probabilities are scored; pending and void outcomes are never treated as wins or losses.",
            "An 80% probability label does not establish 80% hit rate; no production selection change is authorized.",
        ],
    }


def build_segment_report(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("source"), dict):
        raise ValueError("Private frozen cohort provenance required")
    prod = payload["source"].get("production_version")
    rows, prior_counts = validate_frozen_evidence(payload, production_version=prod)
    rows = exclude_repeated_events(rows)
    _, counts = validate_frozen_evidence(
        {**payload, "rows": rows}, production_version=prod
    )
    if counts["settled"] != prior_counts["settled"]:
        raise ValueError("Deduplication may not silently remove settled outcomes")
    eligible = []
    captured_safe = []
    quarantined = 0
    for row in rows:
        if (_time(row["scheduled_at"]) -
                _time(row["captured_at"])).total_seconds() < MIN_CAPTURE_LEAD_SECONDS:
            if row["status"] == "settled":
                quarantined += 1
            continue
        captured_safe.append(row)
        if row["status"] == "settled":
            eligible.append(row)
    # No fuzzy identity grouping, retrospective probabilities or missing results.
    event_keys = [
        (str(row.get("event_id") or row["match_id"]),
         str(row["production_model_version"]),
         str(row["challenger_model_version"]))
        for row in eligible
    ]
    if len(event_keys) != len(set(event_keys)):
        raise ValueError("Repeated provider event in eligible prospectively scored cohort")

    by_tour = {}
    for tour in ("ATP", "WTA"):
        sample = [r for r in eligible if str(r["tour"]).upper() == tour]
        by_tour[tour] = _paired_result(sample)

    surfaces = sorted({_surface(r) for r in eligible})
    by_surface = {name: _paired_result([
        r for r in eligible if _surface(r) == name
    ]) for name in surfaces}
    by_confidence = {name: _paired_result([
        r for r in eligible if _champion_confidence(r) == name
    ]) for name in ("50-60", "60-70", "70-80", "80-100")}
    by_tour_surface = {}
    for tour in ("ATP", "WTA"):
        for surface in surfaces:
            sample = [r for r in eligible
                      if str(r["tour"]).upper() == tour and _surface(r) == surface]
            if sample:
                by_tour_surface[f"{tour}/{surface}"] = _paired_result(sample)

    days = Counter(_time(r["scheduled_at"]).date().isoformat() for r in eligible)
    return {
        "schema": 1,
        "status": "READ_ONLY_FROZEN_721_PROSPECTIVE_ERROR_DIAGNOSIS",
        "source": "private_frozen_721_ledger_exact_model_pair_only",
        "production_version": prod,
        "candidate_version": FROZEN_721_VERSION,
        "candidate_model_sha256": FROZEN_721_MODEL_SHA256,
        "cohort_status_counts": counts,
        "settled_total": counts["settled"],
        "quarantined_capture_less_than_15m_before_start": quarantined,
        "eligible_settled": len(eligible),
        "eligible_utc_days": len(days),
        "eligible_rows_by_utc_day": dict(sorted(days.items())),
        "overall": _paired_result(eligible),
        "candidate_vip_raw_confidence_scorecard": _vip_prospective_scorecard(captured_safe),
        "by_tour": by_tour,
        "by_surface": by_surface,
        "by_champion_confidence": by_confidence,
        "by_tour_and_surface": by_tour_surface,
        "confidence_stratification": "predeclared champion p>=.5 confidence, not outcome optimized",
        "minimum_30_for_paired_accuracy_interval": True,
        "automatic_model_selection": False,
        "automatic_promotion": False,
        "historical_4544_rescoring_used": False,
        "calibrator_fit_performed": False,
        "production_mutated": False,
        "provider_requests": 0,
    }


def audit(repo=DATA_REPO):
    if repo != DATA_REPO:
        raise ValueError("Unexpected private data repository")
    # Probe tag before constructing store because creation could otherwise
    # occur on a missing tag via a mutable release API.
    from release_store import gh
    gh("api", f"repos/{repo}/releases/tags/{SHADOW_TAG}")
    cache = ROOT / ".cache/tbt/frozen-721-segment-audit"
    store = ReleaseStore(repo, SHADOW_TAG, cache)
    store.download(
        extra_names=(LEDGER_ASSET, REPORT_ASSET),
        required_names=(LEDGER_ASSET, REPORT_ASSET),
        require_bundle_manifest=True,
    )
    payload = json.loads((cache / LEDGER_ASSET).read_text(encoding="utf-8"))
    return build_segment_report(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=os.getenv(
        "TBT_DATA_REPOSITORY", DATA_REPO))
    parser.add_argument("--out", default=".cache/tbt/frozen-721-prospective-segments.json")
    args = parser.parse_args()
    report = audit(args.data_repository)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
