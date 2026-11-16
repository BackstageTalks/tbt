"""Descriptive confidence-vs-results evidence for *originally issued* bets.

Only consumes rows already validated by audit_top_reliability.analyze.
It never fits a calibrator, rewrites published probabilities, selects bets, or
uses bookmaker odds as model inputs. No privately identifying rows are emitted.
"""
from __future__ import annotations

import math


def wilson95(wins: int, n: int):
    """95% Wilson score interval for observed success rate; None if no trials."""
    if n <= 0:
        return None
    z = 1.959963984540054
    p = wins / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return [max(0., center - spread), min(1., center + spread)]


def issued_reliability(entries):
    """Score fixed 5pp bands of settled, original-confidence, exact issued rows.

    'entries' must be the outputs of the strict issued publication audit, NOT
    mutable cards or historical after-the-fact scores. A pending/void outcome
    is never treated as a loss, and unknown percentages are not imputed.
    """
    if not isinstance(entries, list):
        raise ValueError("validated issued entries list required")
    groups = {f"{lo:02d}_{lo+5:02d}": [] for lo in range(50, 100, 5)}
    no_confidence = 0
    pending = 0
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("non-record in validated issuance cohort")
        correct = row.get("correct")
        if correct is not True and correct is not False:
            pending += 1
            continue
        raw = row.get("probability")
        if raw is None or isinstance(raw, bool):
            no_confidence += 1
            continue
        try:
            probability = float(raw)
        except (TypeError, ValueError, OverflowError):
            no_confidence += 1
            continue
        if not math.isfinite(probability) or not .5 <= probability <= 1.:
            no_confidence += 1
            continue
        index = min(int((probability * 100 + 1e-9 - 50) // 5), 9)
        groups[f"{50+5*index:02d}_{55+5*index:02d}"].append((probability, bool(correct)))
    bins = {}
    total = 0
    error = 0.
    for key, observations in groups.items():
        n = len(observations)
        wins = sum(w for _, w in observations)
        mean_p = (sum(p for p, _ in observations) / n) if n else None
        actual = (wins / n) if n else None
        deviation = ((actual - mean_p) if n else None)
        bins[key] = {
            "n": n, "wins": wins, "losses": n - wins,
            "mean_issued_probability": mean_p,
            "observed_hit_rate": actual,
            "observed_minus_issued": deviation,
            "observed_wilson95": wilson95(wins, n),
            "evidence": ("NO_SETTLED_EVIDENCE" if n == 0 else
                         "SMALL_SELECTED_SAMPLE" if n < 100 else
                         "DESCRIPTIVE_SELECTED_SAMPLE_ONLY"),
        }
        if n:
            total += n
            error += n * abs(deviation)
    return {
        "status": "READ_ONLY_SELECTED_ISSUED_RELIABILITY_NOT_MODEL_CALIBRATION",
        "settled_with_original_confidence": total,
        "settled_missing_original_confidence": no_confidence,
        "unsettled_or_void": pending,
        "ece_5pp_descriptive": error / total if total else None,
        "bands": bins,
        "limits": [
            "Intervals quantify sampling uncertainty, not validated model trust.",
            "Published bets are a selected population, not all sports fixtures.",
            "Historical selected outcomes must not fit and then validate the same calibrator.",
            "This does not compare a new 60 percent TOP policy with historical issued 65 percent picks.",
        ],
    }
