#!/usr/bin/env python3
"""Zero-request audit for BlinQ Data Model v3 feature source coverage."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.services.feature_builder import stats_surface_key


def _present(stats: dict, keys: tuple[str, ...]) -> bool:
    return all(stats.get(key) is not None for key in keys)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--out", default=".cache/tbt/feature-v3/coverage.json")
    args = ap.parse_args()

    raw = load_partitions(Path(args.history_dir))
    matches, identity = sanitize_history_identities(raw)
    total = len(matches)
    counts = Counter()
    by_surface = Counter()
    by_round = Counter()

    for match in matches:
        stats = match.stats if isinstance(match.stats, dict) else {}
        surface = stats_surface_key(match.surface)
        if surface != "unknown":
            by_surface[surface] += 1
        if str(match.round_name or "").strip():
            by_round[str(match.round_name).strip().lower()] += 1
        if _present(stats, ("p1_service_points_won", "p2_service_points_won", "p1_return_points_won", "p2_return_points_won")):
            counts["serve_return_complete"] += 1
        if _present(stats, ("total_sets", "total_games")):
            counts["structured_score"] += 1
        if _present(stats, ("p1_first_set_won", "p2_first_set_won", "p1_second_set_won", "p2_second_set_won")):
            counts["set1_set2_outcomes"] += 1
        if stats.get("deciding_set") is not None:
            counts["deciding_set"] += 1
        if str(match.tournament_id or "").strip():
            counts["tournament_id"] += 1
        if str(match.round_name or "").strip():
            counts["round"] += 1
        if match.player1_rank is not None and match.player2_rank is not None:
            counts["rank_both"] += 1

    coverage = {
        key: {
            "matches": int(value),
            "rate": (float(value) / total if total else 0.0),
        }
        for key, value in sorted(counts.items())
    }
    payload = {
        "schema": 1,
        "model": "blinq-data-model-v3",
        "zero_request_audit": True,
        "rows": total,
        "identity_safety": identity,
        "coverage": coverage,
        "surface_rows": dict(by_surface.most_common()),
        "round_rows_top25": dict(by_round.most_common(25)),
        "feature_sources": {
            "surface_serve_return": "history.stats + surface",
            "surface_h2h": "chronological history replay",
            "set_game_workload": "structured score totals",
            "deciding_set": "structured score deciding_set",
            "lost_set1_recovery": "set1/set2 outcomes",
            "closing": "first-set outcome + final winner",
            "round_form": "historical round_name",
            "tournament_history": "historical tournament_id/name",
            "pbp_pressure": "reserved canonical enrichment; not enabled until provider path/payload is verified",
            "odds_consensus": "reserved enrichment; existing event odds remain source of current VALUE markets",
        },
    }
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
