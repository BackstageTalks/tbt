"""Read-only issued TOP / VALUE / doubles audit, excluding Short Odds.

Reports descriptive evidence only. Never infers unissued bets, missing prices,
or causal benefits of changing the production selector. No provider requests.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from _bootstrap import ROOT
from audit_top_reliability import (
    competition, confidence, issued_snapshot, number, summarize, timestamp,
)

PRIMARY = ("top_daily", "value", "doubles")
CONTEXT = ("sets", "games", "ace", "double_faults")


def _semantic_key(row, pub):
    """Deduplicate across historical publication-key migrations."""
    event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
    market = str(pub.get("market") or "").strip().lower()
    scope = str(pub.get("projection_scope") or "").strip().lower()
    metric = str(pub.get("projection_metric") or "").strip().lower()
    selection = str(pub.get("selection_id") or pub.get("selection") or "").strip().lower()
    if event and selection:
        return event, market, scope, metric, selection
    key = str(pub.get("selection_key") or pub.get("publication_key") or "").strip()
    return (key,) if key else None


def _betting_day(issued):
    local = issued.astimezone(ZoneInfo("Europe/Bratislava"))
    if local.hour < 6:
        local -= timedelta(days=1)
    return local.date().isoformat()


def _outcome(pub):
    result = pub.get("result")
    if not isinstance(result, dict):
        return None, "unsettled"
    status = str(result.get("status") or "").strip().lower()
    if status in {"void", "w/o", "walkover"} or result.get("correct") is None:
        return None, "void" if status in {"void", "w/o", "walkover"} else "unsettled"
    if result.get("correct") is True:
        return True, "win"
    if result.get("correct") is False:
        return False, "loss"
    return None, "invalid_result"


def _probability(row, pub):
    if pub.get("section") == "doubles":
        # Doubles is a separate model. This is the issued raw model probability,
        # not necessarily the displayed evidence-adjusted confidence.
        value = number(pub.get("model_probability"))
        return (value, "doubles_issued_model") if value is not None and .5 <= value <= 1 else (None, "unknown")
    exact = issued_snapshot(pub)
    value = confidence(row, pub)
    return value, "exact_displayed" if exact and value is not None else "legacy_verified" if value is not None else "unknown"


def _depth(row, pub):
    snapshot = issued_snapshot(pub)
    if snapshot:
        return number(snapshot.get("data_depth"))
    if pub.get("section") == "doubles":
        return number(pub.get("data_depth"))
    # The first event prediction may not match a later issued market pick.
    original = number(row.get("raw_model_confidence"))
    issued = number(pub.get("model_probability"))
    if original is not None and issued is not None and abs(original - issued) <= .005 and (
        str(pub.get("selection_id") or "") == str(row.get("winner_id") or "")
    ):
        return number(row.get("data_depth"))
    return None


def _depth_band(value):
    if value is None:
        return "unknown"
    return "below_080" if value < .8 else "080_090" if value < .9 else "090_plus"


def _confidence_band(value):
    if value is None:
        return "unknown"
    if value < .65:
        return "below_65"
    if value < .75:
        return "65_75"
    if value < .80:
        return "75_80"
    return "80_plus"


def _gap_band(value):
    if value is None:
        return "unknown"
    if value < 0:
        return "negative"
    if value < .05:
        return "0_05"
    if value < .10:
        return "05_10"
    if value < .15:
        return "10_15"
    return "15_plus"


def _model_version(row, pub):
    snapshot = issued_snapshot(pub)
    if snapshot and str(snapshot.get("model_version") or "").strip():
        return str(snapshot["model_version"]), "exact_at_issuance"
    if pub.get("section") == "doubles":
        return str(pub.get("model_version") or "unverified"), "unverified"
    original = number(row.get("raw_model_confidence"))
    issued = number(pub.get("model_probability"))
    if original is not None and issued is not None and abs(original - issued) <= .005 and (
        str(pub.get("selection_id") or "") == str(row.get("winner_id") or "")
    ):
        return str(row.get("model_version") or "unverified"), "matching_original_event"
    return "unverified", "unverified"


def _selection_name(row, pub):
    selected_id = str(pub.get("selection_id") or "")
    for side in ("player1", "player2"):
        player = row.get(side)
        if isinstance(player, dict) and str(player.get("id") or "") == selected_id:
            return str(player.get("name") or pub.get("selection") or selected_id)
    return str(pub.get("selection") or selected_id)


def _group(entries, field):
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry[field]].append(entry)
    return {name: summarize(rows) for name, rows in sorted(grouped.items())}


def analyze(ledger, *, now=None, window_days=90):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or window_days <= 0:
        raise ValueError("Time must be timezone-aware and window positive")
    now = now.astimezone(timezone.utc)
    start = now - timedelta(days=window_days)
    diagnostics = defaultdict(int)
    candidates = {}
    for row in ledger:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            section = str(pub.get("section") or "").strip()
            if section not in PRIMARY + CONTEXT:
                continue
            if section in PRIMARY and str(pub.get("market") or "").strip().lower() != "match_winner":
                continue
            issued = timestamp(pub.get("issued_at"))
            result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            scheduled = timestamp(result.get("scheduled_at") or row.get("scheduled_at"))
            if issued is None or scheduled is None or not start <= scheduled < now:
                continue
            if issued >= scheduled or pub.get("excluded_reason") or pub.get("publication_status") in {"pending", "expired_unpublished"}:
                diagnostics["excluded_or_late"] += 1
                continue
            key = _semantic_key(row, pub)
            if key is None:
                diagnostics["missing_identity"] += 1
                continue
            old = candidates.get(key)
            if old is not None:
                diagnostics["duplicate_semantic_publication"] += 1
            if old is None or issued < old[2]:
                candidates[key] = (row, pub, issued, scheduled)

    entries = []
    overlaps = defaultdict(list)
    for row, pub, issued, scheduled in candidates.values():
        section = str(pub["section"])
        correct, status = _outcome(pub)
        event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
        common = {"event_id": event, "section": section,
                  "market": str(pub.get("market") or "").strip(),
                  "correct": correct, "status": status}
        if event:
            overlaps[event].append(common)
        if section not in PRIMARY:
            continue
        odds = number(pub.get("odds"))
        if odds is None or odds <= 1:
            odds = None
            diagnostics["primary_missing_real_odds"] += 1
        if status == "invalid_result":
            diagnostics["invalid_result"] += 1
            continue
        probability, probability_source = _probability(row, pub)
        if probability_source == "unknown":
            diagnostics["confidence_unavailable"] += 1
        if probability_source == "exact_displayed":
            diagnostics["exact_displayed_confidence"] += 1
        fair = number(pub.get("fair_implied_probability"))
        implied = fair if fair is not None and 0 < fair < 1 else 1 / odds if odds else None
        implied_source = "both_sides_no_vig" if fair is not None and 0 < fair < 1 else "one_side_raw_with_margin" if odds else "unknown"
        gap = probability - implied if probability is not None and implied is not None else None
        depth = _depth(row, pub)
        version, version_source = _model_version(row, pub)
        bet_day = _betting_day(issued)
        entries.append({
            "event_id": event, "section": section, "status": status,
            "correct": correct, "odds": odds, "probability": probability,
            "probability_source": probability_source, "implied_probability": implied,
            "implied_source": implied_source, "probability_market_gap": gap,
            "odds_gap_band": _gap_band(gap), "confidence_band": _confidence_band(probability),
            "data_depth_band": _depth_band(depth), "competition": competition(row),
            "model_version": version, "model_version_source": version_source,
            "betting_day": bet_day, "issued_at": issued.isoformat(),
            "scheduled_at": scheduled.isoformat(),
            "selection": _selection_name(row, pub),
        })

    by_section = {section: [e for e in entries if e["section"] == section] for section in PRIMARY}
    section_reports = {}
    for section, rows in by_section.items():
        daily = _group(rows, "betting_day")
        section_reports[section] = {
            "overall": summarize(rows),
            "by_competition": _group(rows, "competition"),
            "by_confidence": _group(rows, "confidence_band"),
            "by_odds_gap": _group(rows, "odds_gap_band"),
            "by_data_depth": _group(rows, "data_depth_band"),
            "by_model_version": _group(rows, "model_version"),
            "daily": daily,
            "active_days": len(daily),
            "days_with_at_least_5_publications": sum(x["published"] >= 5 for x in daily.values()),
            "mean_published_per_active_day": len(rows) / len(daily) if daily else None,
            "exact_probability_snapshots": sum(e["probability_source"] == "exact_displayed" for e in rows),
            "unverified_model_versions": sum(e["model_version_source"] == "unverified" for e in rows),
        }

    high_confidence_losses = sorted(
        [{
            "event_id": e["event_id"], "selection": e["selection"], "competition": e["competition"],
            "section": e["section"], "probability": e["probability"],
            "probability_source": e["probability_source"], "odds": e["odds"],
            "fair_or_raw_implied_probability": e["implied_probability"],
            "implied_source": e["implied_source"], "probability_market_gap": e["probability_market_gap"],
            "data_depth_band": e["data_depth_band"], "issued_at": e["issued_at"],
            "model_version": e["model_version"],
        } for e in by_section["top_daily"]
          if e["correct"] is False and e["probability"] is not None and e["probability"] >= .80],
        key=lambda item: (-item["probability"], item["event_id"]),
    )
    gap_flags = sorted(
        [{"event_id": e["event_id"], "section": e["section"], "selection": e["selection"],
          "probability": e["probability"], "implied": e["implied_probability"],
          "implied_source": e["implied_source"], "gap": e["probability_market_gap"],
          "odds": e["odds"], "status": e["status"], "model_version": e["model_version"]}
         for e in entries if e["probability_market_gap"] is not None and e["probability_market_gap"] >= .15],
        key=lambda item: (-item["gap"], item["event_id"]),
    )
    concentration = []
    for event, published in overlaps.items():
        primary = [p for p in published if p["section"] in PRIMARY]
        context = [p for p in published if p["section"] in CONTEXT]
        if not primary or len(published) < 2:
            continue
        # All outcomes stay individually published. Pairing is descriptive,
        # not evidence of statistical independence or doubled bet ROI.
        combos = [
            {"primary": a["section"], "other": b["section"], "other_market": b["market"],
             "primary_result": a["status"], "other_result": b["status"]}
            for a in primary for b in published if a is not b
        ]
        concentration.append({
            "event_id": event, "primary_count": len(primary), "context_count": len(context),
            "published_sections": sorted({p["section"] for p in published}),
            "both_loss_pairs": sum(c["primary_result"] == "loss" and c["other_result"] == "loss" for c in combos),
            "pairs": combos,
        })
    concentration.sort(key=lambda e: (-e["both_loss_pairs"], -e["context_count"], e["event_id"]))

    return {
        "schema": 1, "window_days": window_days, "start": start.isoformat(), "end": now.isoformat(),
        "selection_scope": list(PRIMARY), "excluded_from_independent_betting_analysis": ["prime", "short_odds"],
        "sections": section_reports,
        "diagnostics": dict(sorted(diagnostics.items())),
        "high_confidence_top_losses": {
            "total": len(high_confidence_losses), "examples": high_confidence_losses[:30],
        },
        "probability_market_discrepancies": {
            "threshold": .15, "total": len(gap_flags), "examples": gap_flags[:40],
            "meaning": "QA candidates, not proof that the bookmaker or model is wrong.",
        },
        "same_event_exposure": {
            "events_with_multiple_non_short_odds_publications": len(concentration),
            "events_with_top_and_other_market": sum(
                any(p["primary"] == "top_daily" and p["other_market"] != "match_winner" for p in e["pairs"])
                for e in concentration
            ),
            "examples": concentration[:40],
        },
        "limits": [
            "Only confirmed pre-match issued publications in the canonical ledger are evaluated.",
            "TOP, VALUE and doubles are separate historical populations; their observed rates do not establish a causal selector comparison.",
            "Short Odds/Prime are excluded: they are used for combinations and LIVE comebacks, not stand-alone yield.",
            "Sets/games/ace/DF appear only as same-match exposure context and are not counted as independent betting returns.",
            "Historical alternatives cannot be replayed without timestamped pre-match odds and features for unissued candidates.",
            "Missing public confidence or model provenance remains unknown, never reconstructed from match outcomes.",
            "A few high-confidence losses and subgroup differences cannot establish miscalibration or profitability.",
            "Active-day averages omit days with zero or missing publication evidence.",
            "Confidence in doubles is its own issued raw model probability, not the singles BlinQ display adjustment.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--out", default=str(ROOT / ".cache/tbt/market-quality/audit.json"))
    parser.add_argument("--markdown", default=str(ROOT / ".cache/tbt/market-quality/audit.md"))
    args = parser.parse_args()
    if args.window_days <= 0:
        parser.error("window-days must be positive")
    from audit_top_reliability import download
    cache = ROOT / ".cache/tbt/market-quality/input"
    ledger = download(args.data_repository, "tbt-predictions-v1", "ledger.json", cache)
    if not isinstance(ledger, list):
        raise ValueError("Invalid private ledger")
    report = analyze(ledger, window_days=args.window_days)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# BlinQ market reliability: TOP, VALUE, doubles", "",
             "Read-only canonical issued pre-match bets. Short Odds excluded.", ""]
    for section in PRIMARY:
        data = report["sections"][section]
        overall = data["overall"]
        rate = overall["hit_rate"]
        yield_ = overall["yield_flat_stake"]
        lines.extend([
            f"## {section}",
            f"Published: {overall['published']} · settled: {overall['settled']} · wins: {overall['wins']} · losses: {overall['losses']}",
            f"Hit rate: {rate:.1%}" if rate is not None else "Hit rate: unavailable",
            f"Flat-1u yield: {yield_:.1%} (priced n={overall['priced']})" if yield_ is not None else "Flat-1u yield: unavailable",
            f"Public confidence evidence: {overall['calibration_n']} settled records",
            f"Active betting days: {data['active_days']} · days with 5+ published: {data['days_with_at_least_5_publications']}",
            "",
        ])
    lines.extend([
        "## Diagnostic candidates",
        f"High-confidence TOP losses (>=80%): {report['high_confidence_top_losses']['total']}",
        f"Public-probability versus fair/raw implied gap >=15pp: {report['probability_market_discrepancies']['total']}",
        f"Non-Short-Odds events with multiple publications: {report['same_event_exposure']['events_with_multiple_non_short_odds_publications']}",
        "", "Descriptive only. No unissued bets or nonhistorical prices reconstructed.",
    ])
    md = Path(args.markdown)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "markdown": str(md),
                      "sections": {s: report["sections"][s]["overall"] for s in PRIMARY},
                      "overlap_events": report["same_event_exposure"]["events_with_multiple_non_short_odds_publications"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
