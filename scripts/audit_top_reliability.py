"""Read-only audit of published BlinQ TOP: evidence, calibration and model freshness.

Uses exact pre-match issued publications. No Tennis API requests and no changes
to selection, model, historical records or production deployment.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

from _bootstrap import ROOT


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def competition(row):
    level = str(row.get("competition") or row.get("tournament_level") or "").lower()
    tournament = str(row.get("tournament") or "").lower()
    tour = str(row.get("tour") or "").lower()
    if "itf" in level or "itf" in tournament:
        return "ITF"
    if "challenger" in level or "challenger" in tournament:
        return "Challenger"
    if "wta" in tour or "wta" in level:
        return "WTA"
    if "atp" in tour or "atp" in level:
        return "ATP"
    return "unknown"


def rank_band(row, selection_id, cutoff=800):
    """Descriptive cohort: never exclude a TOP bet because of ranking."""
    if cutoff not in (500, 800, 1000):
        raise ValueError("Unsupported ranking cutoff")
    players = [row.get("player1") or {}, row.get("player2") or {}]
    if not all(isinstance(p, dict) for p in players):
        return "rank_unknown"
    selected = next((p for p in players if str(p.get("id")) == selection_id), None)
    opponent = next((p for p in players if p is not selected), None) if selected else None
    ranks = [number(p.get("rank")) if p else None for p in (selected, opponent)]
    if any(r is None or r <= 0 for r in ranks):
        return "rank_unknown"
    pick, rival = ranks
    if pick <= cutoff and rival <= cutoff:
        return f"both_top_{cutoff}"
    if pick <= cutoff and rival > cutoff:
        return f"pick_top_{cutoff}_opponent_{cutoff}_plus"
    if pick > cutoff and rival <= cutoff:
        return f"pick_{cutoff}_plus_opponent_top_{cutoff}"
    return f"both_{cutoff}_plus"


def picked_player_rank_band(row, selection_id):
    """Rank of the actual published selection; opponent need not be ranked."""
    players = [row.get("player1") or {}, row.get("player2") or {}]
    selected = next((p for p in players if isinstance(p, dict) and
                     str(p.get("id")) == selection_id), None)
    rank = number(selected.get("rank")) if selected else None
    if rank is None or rank <= 0:
        return "rank_unknown"
    if rank <= 500:
        return "pick_top_500"
    if rank <= 1000:
        return "pick_501_1000"
    return "pick_1000_plus"


def confidence(row, publication):
    """Only claim displayed calibration when the stored prediction agrees.

    Historical publications may use a later model/price than the immutable
    original event row. Those cannot be assigned an invented TOP confidence.
    """
    if str(publication.get("selection_id") or "") != str(row.get("winner_id") or ""):
        return None
    public_p = number(row.get("blinq_probability"))
    original_p = number(row.get("raw_model_confidence"))
    issued_p = number(publication.get("model_probability"))
    if not all(p is not None and 0.5 <= p <= 1 for p in (public_p, original_p, issued_p)):
        return None
    if abs(original_p - issued_p) > 0.005:
        return None
    return public_p


def probability_band(value):
    if value is None:
        return "unknown"
    if value < .68:
        return "below_68"
    if value < .75:
        return "68_75"
    if value < .80:
        return "75_80"
    if value < .85:
        return "80_85"
    return "85_plus"


def observed_stats(row):
    value = row.get("stats_available")
    return "yes" if value is True else "no" if value is False else "unknown"


def summarize(entries):
    settled = [r for r in entries if r["correct"] is not None]
    priced = [r for r in settled if r["odds"] is not None and r["odds"] > 1]
    calibrated = [r for r in settled if r["probability"] is not None]
    wins = sum(r["correct"] is True for r in settled)
    profit = sum((r["odds"] - 1 if r["correct"] else -1) for r in priced)
    result = {
        "published": len(entries),
        "settled": len(settled),
        "wins": wins,
        "losses": len(settled) - wins,
        "void_or_unsettled": len(entries) - len(settled),
        "hit_rate": wins / len(settled) if settled else None,
        "priced": len(priced),
        "average_odds": sum(r["odds"] for r in priced) / len(priced) if priced else None,
        "yield_flat_stake": profit / len(priced) if priced else None,
        "calibration_n": len(calibrated),
        "mean_confidence": sum(r["probability"] for r in calibrated) / len(calibrated) if calibrated else None,
        "observed_minus_predicted": (
            sum((1.0 if r["correct"] else 0.0) - r["probability"] for r in calibrated) / len(calibrated)
            if calibrated else None
        ),
        "brier": (
            sum(((1.0 if r["correct"] else 0.0) - r["probability"]) ** 2 for r in calibrated) / len(calibrated)
            if calibrated else None
        ),
    }
    result["small_sample"] = len(settled) < 100
    return result


def analyze(ledger, *, now=None, window_days=90):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include timezone")
    start = now - timedelta(days=window_days)
    entries, used = [], set()
    daily_publications = defaultdict(int)
    diagnostics = defaultdict(int)
    for row in ledger:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("section") != "top_daily" or pub.get("market") != "match_winner":
                continue
            issued = timestamp(pub.get("issued_at"))
            scheduled = timestamp((pub.get("result") or {}).get("scheduled_at") or row.get("scheduled_at"))
            if not issued or not scheduled or not start <= scheduled < now:
                continue
            key = str(pub.get("publication_key") or "") or ":".join(
                (str(row.get("event_id") or ""), str(pub.get("selection_id") or ""), str(issued))
            )
            if key in used:
                diagnostics["duplicate_publication_skipped"] += 1
                continue
            used.add(key)
            if issued >= scheduled or pub.get("excluded_reason"):
                diagnostics["invalid_or_excluded_publication"] += 1
                continue
            result = pub.get("result")
            if not isinstance(result, dict):
                diagnostics["unsettled"] += 1
                continue
            status = str(result.get("status") or "").lower()
            if status == "void" or result.get("correct") is None:
                correct = None
            elif result.get("correct") in (True, False):
                correct = result["correct"]
            else:
                diagnostics["invalid_result"] += 1
                continue
            odds = number(pub.get("odds"))
            if odds is None or odds <= 1:
                odds = None
                diagnostics["missing_or_invalid_odds"] += 1
            p = confidence(row, pub)
            if p is None:
                diagnostics["confidence_not_reconstructable"] += 1
            quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
            left = quality.get("player1") if isinstance(quality.get("player1"), dict) else {}
            right = quality.get("player2") if isinstance(quality.get("player2"), dict) else {}
            surface = [number(left.get("surface_matches")), number(right.get("surface_matches"))]
            surface_evidence = (
                "both_10_plus" if all(n is not None and n >= 10 for n in surface)
                else "both_5_plus" if all(n is not None and n >= 5 for n in surface)
                else "low_or_unknown"
            )
            selected_id = str(pub.get("selection_id") or "")
            picked_rank = picked_player_rank_band(row, selected_id)
            stats = observed_stats(row)
            # BlinQ betting day begins at 06:00 in Slovakia, including DST.
            betting_day = (issued.astimezone(ZoneInfo("Europe/Bratislava")) -
                           timedelta(hours=6)).date().isoformat()
            daily_publications[betting_day] += 1
            entries.append({
                "correct": correct, "odds": odds, "probability": p,
                "competition": competition(row),
                "ranking": rank_band(row, selected_id),  # legacy 800-band report
                "ranking_500": rank_band(row, selected_id, cutoff=500),
                "ranking_1000": rank_band(row, selected_id, cutoff=1000),
                "picked_rank": picked_rank,
                "stats": stats,
                "rank_and_stats": f"{picked_rank}/{stats}",
                "confidence_band": probability_band(p),
                "surface_evidence": surface_evidence,
                "rank_and_surface": f"{picked_rank}/{surface_evidence}",
                "issued_at": issued.isoformat(),
                "scheduled_at": scheduled.isoformat(),
            })
    report = {"window_days": window_days, "window_start": start.isoformat(),
              "window_end": now.isoformat(), "diagnostics": dict(diagnostics),
              "overall": summarize(entries), "subgroups": {},
              "coverage": {
                  "first_issued_at": min((e["issued_at"] for e in entries), default=None),
                  "last_issued_at": max((e["issued_at"] for e in entries), default=None),
                  "first_match_at": min((e["scheduled_at"] for e in entries), default=None),
                  "last_match_at": max((e["scheduled_at"] for e in entries), default=None),
                  "active_betting_days": len(daily_publications),
                  "days_with_5_plus_published": sum(n >= 5 for n in daily_publications.values()),
                  "days_with_below_5_published": sum(n < 5 for n in daily_publications.values()),
                  "mean_published_per_active_day": (
                      sum(daily_publications.values()) / len(daily_publications)
                      if daily_publications else None
                  ),
                  "betting_day_counts": dict(sorted(daily_publications.items())),
              }}
    for dimension in ("competition", "ranking", "ranking_500", "ranking_1000",
                      "picked_rank", "stats", "rank_and_stats", "confidence_band",
                      "surface_evidence", "rank_and_surface"):
        groups = defaultdict(list)
        for entry in entries:
            groups[entry[dimension]].append(entry)
        report["subgroups"][dimension] = {key: summarize(group) for key, group in sorted(groups.items())}
    return report


def model_freshness(training, history):
    data = training.get("data") if isinstance(training.get("data"), dict) else {}
    years = history.get("years") if isinstance(history.get("years"), dict) else {}
    dates = [timestamp(meta.get("history_end")) for meta in years.values() if isinstance(meta, dict)]
    latest = max((d for d in dates if d), default=None)
    trained_data_end = timestamp(data.get("end"))
    return {
        "training_data_end": trained_data_end.isoformat() if trained_data_end else None,
        "latest_history_match": latest.isoformat() if latest else None,
        "history_manifest_updated": history.get("generated_at"),
        "history_ahead_of_training": (
            latest > trained_data_end if latest and trained_data_end else None
        ),
        "rank_provenance": training.get("rank_provenance"),
        "warning": "A date comparison cannot detect backfilled statistics on older matches.",
    }


def download(repository, tag, filename, directory):
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["gh", "release", "download", tag, "--repo", repository,
         "--pattern", filename, "--dir", str(directory), "--clobber"],
        check=True,
    )
    return json.loads((directory / filename).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--out", default=str(ROOT / ".cache/tbt/top-accuracy/audit.json"))
    args = parser.parse_args()
    if args.window_days <= 0:
        parser.error("window-days must be positive")
    cache = ROOT / ".cache/tbt/top-accuracy/input"
    ledger = download(args.data_repository, "tbt-predictions-v1", "ledger.json", cache / "predictions")
    training = download(args.data_repository, "tbt-model-production-v1", "training_report.json", cache / "model")
    history = download(args.data_repository, "tbt-data-v1", "history_manifest.json", cache / "history")
    if not isinstance(ledger, list) or not isinstance(training, dict) or not isinstance(history, dict):
        raise ValueError("Invalid private release JSON")
    report = analyze(ledger, window_days=args.window_days)
    report["production_model_vs_history"] = model_freshness(training, history)
    report["interpretation_limits"] = [
        "Only genuinely issued TOP predictions before actual match start are evaluated.",
        "Missing or incompatible recorded public confidence is excluded from calibration.",
        "This is a descriptive production audit, not a replay of alternative historical selections.",
        "Subgroups below 100 settled picks are flagged as small samples.",
        "Rank buckets describe stored ledger ranks; point-in-time ranking provenance must be confirmed separately.",
        "Ranking and evidence are observational and may be confounded; no ranking exclusion is recommended by this audit.",
        "Only days with at least one published TOP are counted as active; missing historical publications cannot be reconstructed.",
        "This report makes no automatic deployment or model-promotion decision.",
    ]
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "report": str(path), "settled": report["overall"]["settled"],
        "calibration_n": report["overall"]["calibration_n"],
        "groups": {k: len(v) for k, v in report["subgroups"].items()},
        "active_betting_days": report["coverage"]["active_betting_days"],
        "model_history_gap": report["production_model_vs_history"]["history_ahead_of_training"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
