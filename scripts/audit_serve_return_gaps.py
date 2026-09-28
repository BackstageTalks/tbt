"""Read-only gap triage for historical serve+return statistics; ZERO provider calls."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from audit_environment_release import download_committed_history
from audit_statistics_inventory import _quality_ready
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities


def analyze(matches):
    overall = Counter()
    by_year = defaultdict(Counter)
    by_tour = defaultdict(Counter)
    candidates = []
    for m in matches:
        if not m.is_completed:
            continue
        stats = m.stats if isinstance(m.stats, dict) else {}
        p1 = _quality_ready(stats, "p1")
        p2 = _quality_ready(stats, "p2")
        populated = sum(v is not None for v in stats.values())
        if p1 and p2:
            category = "both_ready"
        elif p1 or p2:
            category = "one_player_ready"
        elif populated:
            category = "partial_no_player_ready"
        else:
            category = "no_statistics"
        overall["completed"] += 1
        overall[category] += 1
        if populated:
            overall["any_stats"] += 1
        by_year[str(m.scheduled_at.year)][category] += 1
        by_tour[str(m.tour or "unknown").lower()][category] += 1
        by_year[str(m.scheduled_at.year)]["completed"] += 1
        by_tour[str(m.tour or "unknown").lower()]["completed"] += 1
        if category != "both_ready":
            candidates.append({
                "match_id": str(m.match_id), "year": m.scheduled_at.year,
                "tour": str(m.tour or "unknown"), "category": category,
                "existing_fields": populated, "p1_ready": p1, "p2_ready": p2,
            })
    total = overall["completed"]
    candidates.sort(key=lambda x: (
        {"one_player_ready": 0, "partial_no_player_ready": 1, "no_statistics": 2}[x["category"]],
        -x["existing_fields"], -x["year"], x["match_id"]))
    return {
        "schema": 1, "read_only": True, "paid_provider_calls": 0,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": dict(overall),
        "any_stats_rate": round(overall["any_stats"] / max(1, total), 6),
        "both_ready_rate": round(overall["both_ready"] / max(1, total), 6),
        "gap_to_30pct": max(0, (30 * total + 99) // 100 - overall["both_ready"]),
        "gap_to_40pct": max(0, (40 * total + 99) // 100 - overall["both_ready"]),
        "by_year": {k: dict(v) for k, v in sorted(by_year.items())},
        "by_tour": {k: dict(v) for k, v in sorted(by_tour.items())},
        "candidate_counts": dict(Counter(x["category"] for x in candidates)),
        "candidate_sample": candidates[:300],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    ap.add_argument("--history-dir", default=str(ROOT / ".cache/tbt/serve-return-triage/history"))
    ap.add_argument("--out", default=str(ROOT / ".cache/tbt/serve-return-triage/report.json"))
    args = ap.parse_args()
    directory = Path(args.history_dir)
    store = ReleaseStore(args.data_repository, "tbt-data-v1", directory)
    download_committed_history(store, directory)
    matches, safety = sanitize_history_identities(load_partitions(directory))
    report = analyze(matches)
    report["identity_safety"] = safety
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("overall", "any_stats_rate", "both_ready_rate", "gap_to_30pct", "gap_to_40pct", "candidate_counts")}, indent=2))


if __name__ == "__main__":
    main()
