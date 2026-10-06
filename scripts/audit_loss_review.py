"""Read-only retrospective review of recently issued BlinQ losses.

The audit evaluates only bets that were actually published before match start.
It does not invent unissued alternatives or tune production selectors. Candidate
filters are shadow rules applied to the same issued population so we can measure
how many historical losses they would have removed and how many wins they would
also have sacrificed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

from _bootstrap import ROOT
from audit_market_reliability import (
    PRIMARY,
    _betting_day,
    _depth,
    _model_version,
    _outcome,
    _probability,
    _selection_name,
    _semantic_key,
    competition,
    issued_snapshot,
    number,
    timestamp,
)
from audit_top_reliability import download, summarize


def extract_entries(ledger, *, now=None, window_days=10):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or window_days <= 0:
        raise ValueError("Time must be timezone-aware and window positive")
    now = now.astimezone(timezone.utc)
    start = now - timedelta(days=window_days)

    candidates = {}
    diagnostics = Counter()
    for row in ledger:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            section = str(pub.get("section") or "").strip()
            if section not in PRIMARY:
                continue
            if str(pub.get("market") or "").strip().lower() != "match_winner":
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
    event_counts = Counter()
    staged = []
    for row, pub, issued, scheduled in candidates.values():
        correct, status = _outcome(pub)
        if correct not in (True, False):
            diagnostics["void_or_unsettled"] += 1
            continue
        event_id = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
        if event_id:
            event_counts[event_id] += 1
        staged.append((row, pub, issued, scheduled, correct, status, event_id))

    for row, pub, issued, scheduled, correct, status, event_id in staged:
        probability, probability_source = _probability(row, pub)
        odds = number(pub.get("odds"))
        odds = odds if odds is not None and odds > 1 else None
        fair = number(pub.get("fair_implied_probability"))
        implied = fair if fair is not None and 0 < fair < 1 else (1 / odds if odds else None)
        implied_source = "both_sides_no_vig" if fair is not None and 0 < fair < 1 else "one_side_raw_with_margin" if odds else "unknown"
        gap = probability - implied if probability is not None and implied is not None else None
        public_ev = probability * odds - 1 if probability is not None and odds is not None else None

        snapshot = issued_snapshot(pub)
        quality = snapshot.get("quality") if isinstance(snapshot, dict) and isinstance(snapshot.get("quality"), dict) else {}
        sides = [
            quality.get(side) if isinstance(quality.get(side), dict) else {}
            for side in ("player1", "player2")
        ]
        surface_counts = [number(side.get("surface_matches")) for side in sides]
        min_surface = (
            min(int(value) for value in surface_counts)
            if snapshot is not None and all(value is not None and value >= 0 for value in surface_counts)
            else None
        )
        depth = _depth(row, pub)
        version, version_source = _model_version(row, pub)

        entries.append({
            "event_id": event_id,
            "section": str(pub.get("section") or ""),
            "selection": _selection_name(row, pub),
            "competition": competition(row),
            "correct": correct,
            "status": status,
            "odds": odds,
            "probability": probability,
            "probability_source": probability_source,
            "implied_probability": implied,
            "implied_source": implied_source,
            "probability_market_gap": gap,
            "public_expected_value": public_ev,
            "data_depth": depth,
            "exact_issue_snapshot": snapshot is not None,
            "min_surface_matches_at_issue": min_surface,
            "same_event_primary_count": event_counts.get(event_id, 0),
            "model_version": version,
            "model_version_source": version_source,
            "betting_day": _betting_day(issued),
            "issued_at": issued.isoformat(),
            "scheduled_at": scheduled.isoformat(),
        })

    return entries, dict(sorted(diagnostics.items())), start, now


def _profit(entries):
    priced = [entry for entry in entries if entry.get("odds") is not None and entry["odds"] > 1]
    if not priced:
        return {"priced": 0, "profit_flat_1u": None, "yield_flat_1u": None}
    profit = sum((entry["odds"] - 1) if entry["correct"] else -1 for entry in priced)
    return {
        "priced": len(priced),
        "profit_flat_1u": profit,
        "yield_flat_1u": profit / len(priced),
    }


def _rules():
    return {
        "require_exact_issue_snapshot": (
            "Keep only picks with exact deployed pre-match evidence.",
            lambda e: bool(e["exact_issue_snapshot"]),
        ),
        "require_confidence_68_plus": (
            "Require reconstructable public confidence of at least 68%.",
            lambda e: e["probability"] is not None and e["probability"] >= .68,
        ),
        "require_confidence_72_plus": (
            "Require reconstructable public confidence of at least 72%.",
            lambda e: e["probability"] is not None and e["probability"] >= .72,
        ),
        "require_confidence_75_plus": (
            "Require reconstructable public confidence of at least 75%.",
            lambda e: e["probability"] is not None and e["probability"] >= .75,
        ),
        "require_data_depth_90_plus": (
            "Require reconstructable data depth of at least 0.90.",
            lambda e: e["data_depth"] is not None and e["data_depth"] >= .90,
        ),
        "require_market_edge_05_plus": (
            "Require probability minus pre-match implied probability of at least 5 percentage points.",
            lambda e: e["probability_market_gap"] is not None and e["probability_market_gap"] >= .05,
        ),
        "require_market_edge_10_plus": (
            "Require probability minus pre-match implied probability of at least 10 percentage points.",
            lambda e: e["probability_market_gap"] is not None and e["probability_market_gap"] >= .10,
        ),
        "cap_market_disagreement_15pp": (
            "Reject extreme model-versus-market disagreement of 15 percentage points or more when known.",
            lambda e: e["probability_market_gap"] is None or e["probability_market_gap"] < .15,
        ),
        "reject_nonpositive_public_ev": (
            "Reject picks whose public-confidence expected value is known and non-positive.",
            lambda e: e["public_expected_value"] is None or e["public_expected_value"] > 0,
        ),
        "value_requires_5_surface_matches_each": (
            "For VALUE only, require at least five issued surface matches for both players.",
            lambda e: e["section"] != "value" or (
                e["min_surface_matches_at_issue"] is not None
                and e["min_surface_matches_at_issue"] >= 5
            ),
        ),
        "single_primary_pick_per_event": (
            "Reject events where more than one primary section was published on the same match.",
            lambda e: e["same_event_primary_count"] <= 1,
        ),
        "exclude_challenger": (
            "Exploratory: reject Challenger match-winner publications.",
            lambda e: e["competition"] != "Challenger",
        ),
        "exclude_itf": (
            "Exploratory: reject ITF match-winner publications.",
            lambda e: e["competition"] != "ITF",
        ),
    }


def evaluate_rule(entries, name, description, keep_fn):
    kept = [entry for entry in entries if keep_fn(entry)]
    removed = [entry for entry in entries if not keep_fn(entry)]
    prevented_losses = sum(entry["correct"] is False for entry in removed)
    sacrificed_wins = sum(entry["correct"] is True for entry in removed)
    removed_settled = len(removed)
    baseline_profit = _profit(entries)
    retained_profit = _profit(kept)
    return {
        "rule": name,
        "description": description,
        "issued_population": len(entries),
        "removed_picks": removed_settled,
        "prevented_losses": prevented_losses,
        "sacrificed_wins": sacrificed_wins,
        "net_bad_removed": prevented_losses - sacrificed_wins,
        "removed_loss_share": prevented_losses / removed_settled if removed_settled else None,
        "losses_prevented_per_win_sacrificed": (
            prevented_losses / sacrificed_wins if sacrificed_wins else None
        ),
        "baseline": baseline_profit,
        "retained": retained_profit,
        "yield_delta": (
            retained_profit["yield_flat_1u"] - baseline_profit["yield_flat_1u"]
            if retained_profit["yield_flat_1u"] is not None and baseline_profit["yield_flat_1u"] is not None
            else None
        ),
        "small_sample": len(entries) < 100 or removed_settled < 10,
    }


def analyze_loss_review(ledger, *, now=None, window_days=10):
    entries, diagnostics, start, end = extract_entries(ledger, now=now, window_days=window_days)
    losses = [entry for entry in entries if entry["correct"] is False]
    wins = [entry for entry in entries if entry["correct"] is True]
    rules = _rules()
    simulations = [
        evaluate_rule(entries, name, description, keep_fn)
        for name, (description, keep_fn) in rules.items()
    ]
    simulations.sort(
        key=lambda item: (
            -item["net_bad_removed"],
            -item["prevented_losses"],
            item["sacrificed_wins"],
            item["rule"],
        )
    )

    loss_rows = []
    for entry in sorted(losses, key=lambda item: item["scheduled_at"], reverse=True):
        flags = [
            name for name, (_description, keep_fn) in rules.items()
            if not keep_fn(entry)
        ]
        loss_rows.append({**entry, "shadow_filter_flags": flags})

    by_section = defaultdict(list)
    by_competition = defaultdict(list)
    for entry in entries:
        by_section[entry["section"]].append(entry)
        by_competition[entry["competition"]].append(entry)

    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "scope": "actual issued pre-match TOP/VALUE/doubles match-winner publications only",
        "overall": {
            **summarize(entries),
            **_profit(entries),
            "wins": len(wins),
            "losses": len(losses),
        },
        "by_section": {name: summarize(rows) for name, rows in sorted(by_section.items())},
        "by_competition": {name: summarize(rows) for name, rows in sorted(by_competition.items())},
        "rule_simulations": simulations,
        "losses": loss_rows,
        "diagnostics": diagnostics,
        "interpretation": [
            "Rules are retrospective shadow filters on bets that were actually issued; they are not proof of causal improvement.",
            "A useful rule should prevent materially more losses than wins and remain sensible ex ante.",
            "Small samples are exploratory and must not be auto-promoted into production selection gates.",
            "No provider calls, model retraining, publication changes or production writes are performed.",
        ],
    }
    return report


def _fmt_pct(value):
    return "n/a" if value is None else f"{value:.1%}"


def render_markdown(report):
    overall = report["overall"]
    lines = [
        "# BlinQ Loss Review",
        "",
        f"Window: **{report['window_days']} days** · {report['start']} → {report['end']}",
        f"Issued settled picks: **{overall['settled']}** · W **{overall['wins']}** / L **{overall['losses']}**",
        f"Hit rate: **{_fmt_pct(overall['hit_rate'])}** · flat-1u yield: **{_fmt_pct(overall['yield_flat_1u'])}**",
        "",
        "## Shadow selection rules",
        "",
        "| Rule | Losses avoided | Wins lost | Net bad removed | Retained yield | Small sample |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in report["rule_simulations"]:
        lines.append(
            f"| {item['rule']} | {item['prevented_losses']} | {item['sacrificed_wins']} | "
            f"{item['net_bad_removed']} | {_fmt_pct(item['retained']['yield_flat_1u'])} | "
            f"{'yes' if item['small_sample'] else 'no'} |"
        )
    lines += ["", "## Every loss", ""]
    for loss in report["losses"]:
        flags = ", ".join(loss["shadow_filter_flags"]) or "none"
        probability = "n/a" if loss["probability"] is None else f"{loss['probability']:.1%}"
        odds = "n/a" if loss["odds"] is None else f"{loss['odds']:.2f}"
        lines.append(
            f"- **{loss['selection']}** · {loss['section']} · {loss['competition']} · "
            f"odds {odds} · confidence {probability} · flags: {flags}"
        )
    lines += [
        "",
        "> This is a read-only retrospective audit. Shadow-rule performance is exploratory and is never applied to production automatically.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--window-days", type=int, default=10)
    parser.add_argument("--out", default=str(ROOT / ".cache/tbt/loss-review/report.json"))
    parser.add_argument("--markdown", default=str(ROOT / ".cache/tbt/loss-review/report.md"))
    args = parser.parse_args()
    if args.window_days <= 0:
        parser.error("window-days must be positive")

    cache = ROOT / ".cache/tbt/loss-review/input"
    ledger = download(args.data_repository, "tbt-predictions-v1", "ledger.json", cache)
    if not isinstance(ledger, list):
        raise ValueError("Invalid private ledger")

    report = analyze_loss_review(ledger, window_days=args.window_days)
    out = Path(args.out)
    md = Path(args.markdown)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "markdown": str(md),
        "window_days": report["window_days"],
        "settled": report["overall"]["settled"],
        "wins": report["overall"]["wins"],
        "losses": report["overall"]["losses"],
        "top_rules": [
            {
                "rule": item["rule"],
                "prevented_losses": item["prevented_losses"],
                "sacrificed_wins": item["sacrificed_wins"],
                "retained_yield": item["retained"]["yield_flat_1u"],
                "small_sample": item["small_sample"],
            }
            for item in report["rule_simulations"][:5]
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
