"""Audit which historical match-statistic fields are actually usable for ES.

This is deliberately descriptive: it never imputes or mutates history.  It tells
us whether raw statistics exist and, separately, whether both players have a
pre-match-updatable serve+return quality pair that FeatureBuilder can consume.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.models.feature_builder import FeatureBuilder


def _quality_ready(stats: dict[str, Any], prefix: str) -> bool:
    serve, ret = FeatureBuilder._extract_quality(stats or {}, prefix)
    return serve is not None and ret is not None


def build(matches) -> dict[str, Any]:
    key_counts = Counter()
    rows = 0
    completed = 0
    any_stats = 0
    both_quality = 0
    p1_quality = 0
    p2_quality = 0
    by_year = defaultdict(lambda: Counter())
    by_tour = defaultdict(lambda: Counter())

    for match in matches:
        rows += 1
        if not match.is_completed:
            continue
        completed += 1
        stats = match.stats if isinstance(match.stats, dict) else {}
        year = str(match.scheduled_at.year)
        tour = str(match.tour or "unknown").lower()
        by_year[year]["completed"] += 1
        by_tour[tour]["completed"] += 1
        if stats:
            any_stats += 1
            by_year[year]["any_stats"] += 1
            by_tour[tour]["any_stats"] += 1
            key_counts.update(str(k) for k, v in stats.items() if v is not None)
        q1 = _quality_ready(stats, "p1")
        q2 = _quality_ready(stats, "p2")
        p1_quality += int(q1)
        p2_quality += int(q2)
        both_quality += int(q1 and q2)
        by_year[year]["both_quality"] += int(q1 and q2)
        by_tour[tour]["both_quality"] += int(q1 and q2)

    def segment(counter: Counter) -> dict[str, Any]:
        denom = int(counter.get("completed") or 0)
        return {
            "completed": denom,
            "any_stats": int(counter.get("any_stats") or 0),
            "any_stats_rate": round(counter.get("any_stats", 0) / max(1, denom), 6),
            "both_quality": int(counter.get("both_quality") or 0),
            "both_quality_rate": round(counter.get("both_quality", 0) / max(1, denom), 6),
        }

    return {
        "schema": 1,
        "rows": rows,
        "completed": completed,
        "any_stats_matches": any_stats,
        "any_stats_rate": round(any_stats / max(1, completed), 6),
        "p1_quality_ready": p1_quality,
        "p2_quality_ready": p2_quality,
        "both_players_quality_ready": both_quality,
        "both_players_quality_ready_rate": round(both_quality / max(1, completed), 6),
        "stat_key_counts": dict(key_counts.most_common()),
        "by_year": {k: segment(v) for k, v in sorted(by_year.items())},
        "by_tour": {k: segment(v) for k, v in sorted(by_tour.items())},
        "interpretation": {
            "raw_stats_are_not_es": True,
            "es_requires_both_players_serve_and_return_quality": True,
            "raw_ace_double_fault_counts_are_not_promoted_to_rates_without_denominators": True,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--out", default=".cache/tbt/production/statistics_inventory_report.json")
    args = ap.parse_args()
    report = build(load_partitions(Path(args.history_dir)))
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
