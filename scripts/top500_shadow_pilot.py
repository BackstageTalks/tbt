"""Read-only seven-day TOP-500 inventory pilot. Never calls Tennis/odds APIs.

This analyzes the existing private production feed and immutable issued ledger.
The hypothetical 90/35/25 ordering concerns *review slots* only: missing
bookmaker prices remain unknown, and NO alternative picks are published.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from _bootstrap import ROOT
from audit_top_reliability import analyze as issued_top_audit
from tbt.services.market_selection import (
    _blinq_probability, _depth, _passes_candidate_gate, _prediction_time,
)

TZ = ZoneInfo("Europe/Bratislava")
START = "2026-09-26"
END = "2026-10-03"  # Seven complete next-day observations plus initial snapshot.
CAPACITY = 150
SLOTS = (("both_500", 90), ("one_500", 35), ("other", 25))


def numeric_rank(value):
    try:
        rank = int(value)
        return rank if rank > 0 else None
    except (TypeError, ValueError):
        return None


def cohort(row, profiles=None):
    """Today's ranks are presentation-only, NEVER historical/ML features."""
    profiles = profiles or {}
    ranks, sources = [], []
    for side in ("player1", "player2"):
        player = row.get(side) if isinstance(row.get(side), dict) else {}
        rank = numeric_rank(player.get("rank") or player.get("ranking"))
        source = "feed" if rank else "unknown"
        if not rank:
            profile = profiles.get(str(player.get("id") or ""))
            if isinstance(profile, dict):
                rank = numeric_rank(profile.get("rank"))
                if rank:
                    source = "current_profile"
        ranks.append(rank)
        sources.append(source)
    if None in ranks:
        return "unknown", ranks, sources
    if ranks[0] <= 500 and ranks[1] <= 500:
        return "both_500", ranks, sources
    if min(ranks) <= 500:
        return "one_500", ranks, sources
    return "other", ranks, sources


def _candidate_rows(feed, now):
    """Current betting-day model candidates, with no new provider requests."""
    zone_now = now.astimezone(TZ)
    local_start = zone_now.replace(hour=6, minute=0, second=0, microsecond=0)
    if zone_now < local_start:
        local_start -= timedelta(days=1)
    start, end = local_start.astimezone(timezone.utc), (local_start + timedelta(days=1)).astimezone(timezone.utc)
    upcoming = feed.get("upcoming")
    indexed = {}
    for row in upcoming if isinstance(upcoming, list) else []:
        if not isinstance(row, dict) or row.get("prediction_family") == "doubles":
            continue
        event_id = str(row.get("event_id") or "")
        when = _prediction_time(row)
        if not event_id or when is None or not start <= when < end:
            continue
        if not _passes_candidate_gate(row, min_probability=.60, min_data_depth=.75, min_surface_matches=3):
            continue
        indexed[event_id] = row
    return indexed, start, end


def audit(feed, ledger, profiles=None, *, now=None, capacity=CAPACITY):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be offset-aware")
    candidates, start, end = _candidate_rows(feed, now)
    published = {}
    for section in ("top_daily_picks", "value_picks", "prime_picks"):
        rows = feed.get(section)
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("event_id"):
                published.setdefault(str(row["event_id"]), set()).add(section)
    inventory = []
    for event_id, row in candidates.items():
        group, ranks, sources = cohort(row, profiles)
        confidence = _blinq_probability(row)
        inventory.append({
            "event_id": event_id,
            "group": group,
            "ranks": ranks,
            "rank_sources": sources,
            "confidence": confidence,
            "depth": _depth(row),
            "published_sections": sorted(published.get(event_id, ())),
        })
    # Exactly the existing pre-price confidence/depth order, no model changes.
    inventory.sort(key=lambda r: (r["confidence"] or 0, r["depth"], r["event_id"]), reverse=True)
    baseline = inventory[:capacity]
    # Unknown rankings do not consume priority quotas; they remain eligible
    # for spillover review under precisely the same quality constraints.
    selected, selected_ids = [], set()
    for group, quota in SLOTS:
        for item in inventory:
            if item["group"] == group and item["event_id"] not in selected_ids:
                selected.append(item)
                selected_ids.add(item["event_id"])
                if sum(p["group"] == group for p in selected) >= min(quota, capacity):
                    break
    for item in inventory:
        if len(selected) >= capacity:
            break
        if item["event_id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["event_id"])
    selected = selected[:capacity]
    baseline_ids = {r["event_id"] for r in baseline}
    shadow_ids = {r["event_id"] for r in selected}
    extra = [r for r in selected if r["event_id"] not in baseline_ids]
    historical = issued_top_audit(ledger if isinstance(ledger, list) else [], now=now, window_days=7)
    current = Counter(r["group"] for r in inventory)
    base_counts = Counter(r["group"] for r in baseline)
    shadow_counts = Counter(r["group"] for r in selected)
    return {
        "schema": 1,
        "pilot": "top500_shadow_observational",
        "generated_at": now.isoformat(),
        "feed_generated_at": feed.get("generated_at"),
        "betting_window_utc": [start.isoformat(), end.isoformat()],
        "config": {
            "review_capacity": capacity,
            "reserved_slots": dict(SLOTS),
            "publish": False, "train": False, "paid_api_requests": 0,
            "ranking_use": "current presentation only; unknown never treated outside top 500",
        },
        "supply": {
            "upcoming_count": len(feed.get("upcoming") or []),
            "quality_eligible_today": len(inventory),
            "rank_cohorts": dict(current),
            "rank_unknown": current["unknown"],
            "published_section_membership_in_eligible": dict(
                Counter(section for r in inventory for section in r["published_sections"])),
        },
        "comparison": {
            "baseline_reviewed": len(baseline),
            "baseline_groups": dict(base_counts),
            "shadow_reviewed": len(selected),
            "shadow_groups": dict(shadow_counts),
            "additional_events_to_review": len(extra),
            "additional_groups": dict(Counter(r["group"] for r in extra)),
            "additional_already_published": sum(bool(r["published_sections"]) for r in extra),
            "displaced_baseline_count": len(baseline_ids - shadow_ids),
            "shadow_extra_examples": [r["event_id"] for r in extra[:12]],
        },
        "issued_top_last_7_days": {
            "overall": historical["overall"],
            "ranking_500": historical["subgroups"].get("ranking_500", {}),
            "rank_unknown_diagnostic": historical["diagnostics"].get("issued_rank_available", 0),
            "active_betting_days": historical["coverage"]["active_betting_days"],
        },
        "limitations": [
            "This is an inventory audit on an existing snapshot; candidates absent from upcoming cannot be recovered.",
            "No new bookmaker price is requested; additional reviewed events are NOT proven available bets.",
            "Historical rank groups use stored ledger evidence and are descriptive, not a counterfactual backtest.",
            "Today's ranks from current profiles are not point-in-time historical features.",
            "A single current snapshot cannot measure a seven-day uplift or a future win rate.",
        ],
    }


def markdown(report):
    supply, comp = report["supply"], report["comparison"]
    groups = ("both_500", "one_500", "other", "unknown")
    lines = [
        "# BlinQ TOP 500 — shadow pilot (read-only)",
        "",
        f"Run: {report['generated_at']} · feed: {report['feed_generated_at']}",
        "",
        f"- Current upcoming rows: **{supply['upcoming_count']}**",
        f"- Today's quality-eligible candidates in available feed: **{supply['quality_eligible_today']}**",
        f"- Hypothetical extra review events at the SAME review capacity: **{comp['additional_events_to_review']}**",
        f"- Extra events already published in a section: **{comp['additional_already_published']}**",
        "",
        "| Current-rank group | Eligible | Baseline review | Shadow review |",
        "|---|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(f"| {group} | {supply['rank_cohorts'].get(group,0)} | {comp['baseline_groups'].get(group,0)} | {comp['shadow_groups'].get(group,0)} |")
    overall = report["issued_top_last_7_days"]["overall"]
    lines += ["", "## Published TOP (past 7 days, descriptive only)",
              f"Published: {overall.get('published',0)}, settled: {overall.get('settled',0)}, "
              f"wins: {overall.get('wins',0)}, losses: {overall.get('losses',0)}.",
              "", "## Important limits"]
    lines += ["- " + item for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", type=Path, required=True)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--profiles", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / ".cache/tbt/top500-shadow/report.json")
    args = ap.parse_args()
    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    raw = json.loads(args.profiles.read_text(encoding="utf-8")) if args.profiles and args.profiles.is_file() else {}
    profiles = raw.get("players") if isinstance(raw, dict) else {}
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Expected complete production feed and ledger; refusing a fabricated pilot")
    result = audit(feed, ledger, profiles or {})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = args.out.with_suffix(".md")
    summary.write_text(markdown(result), encoding="utf-8")
    print(markdown(result), flush=True)
    print(f"JSON report: {args.out}", flush=True)


if __name__ == "__main__":
    main()
