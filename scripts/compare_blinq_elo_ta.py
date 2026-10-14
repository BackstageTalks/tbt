#!/usr/bin/env python3
"""Independent research-only comparison of latest BlinQ Elo with TA leaderboards.

Identity matching is a UNIQUE surname+first-initial HEURISTIC, not a proven
cross-provider ID crosswalk. Report and archive discrepancies, NEVER import
those values to CDB or substitute for production Elo.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


def norm(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    without_marks = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[a-z]+", without_marks.lower())


def identity_hint(name: str, abbreviated: bool) -> tuple[str, str] | None:
    tokens = norm(name)
    if len(tokens) < 2:
        return None
    if abbreviated and len(tokens[-1]) == 1:
        # Example CDB: Sinner J. -> (sinner,j)
        return tokens[-2], tokens[-1]
    # Example TA: Jannik Sinner -> (sinner,j)
    return tokens[-1], tokens[0][:1]


def unique_map(rows: list[dict], *, abbreviated: bool) -> tuple[dict, int]:
    candidates = defaultdict(list)
    for row in rows:
        hint = identity_hint(row.get("name", ""), abbreviated=abbreviated)
        if hint:
            candidates[hint].append(row)
    collisions = sum(len(vals) for vals in candidates.values() if len(vals) > 1)
    return {k: vals[0] for k, vals in candidates.items() if len(vals) == 1}, collisions


def compare(blinq: list[dict], ta: list[dict], tour: str) -> dict:
    subset_b = [r for r in blinq if r["tour"] == tour]
    subset_ta = [r for r in ta if r["tour"] == tour]
    local, collision_b = unique_map(subset_b, abbreviated=True)
    external, collision_ta = unique_map(subset_ta, abbreviated=False)
    matched = []
    for key in sorted(set(local) & set(external)):
        b, t = local[key], external[key]
        try:
            x, y = float(b["elo"]), float(t["elo"])
            if math.isfinite(x) and math.isfinite(y):
                matched.append((x, y, key))
        except (ValueError, TypeError, KeyError):
            continue
    n = len(matched)
    if n >= 2:
        xb = sum(x for x, _, _ in matched) / n
        yb = sum(y for _, y, _ in matched) / n
        numer = sum((x - xb) * (y - yb) for x, y, _ in matched)
        den = math.sqrt(
            sum((x - xb) ** 2 for x, _, _ in matched)
            * sum((y - yb) ** 2 for _, y, _ in matched)
        )
        correlation = numer / den if den > 0 else None
    else:
        correlation = None
    return {
        "tour": tour,
        "blinq_players": len(subset_b),
        "ta_players": len(subset_ta),
        "unique_heuristic_name_matches": n,
        "blinq_name_collisions_excluded": collision_b,
        "ta_name_collisions_excluded": collision_ta,
        "pearson_elo_association": correlation,
        "mean_absolute_rating_difference": (
            sum(abs(x - y) for x, y, _ in matched) / n if n else None
        ),
        "comparison_status": (
            "research_heuristic_only" if n >= 20 else "insufficient_heuristic_overlap"
        ),
        "identity_crosswalk_verified": False,
        "disclaimer": (
            "Different Elo formula, corpus coverage, dates and player eligibility. "
            "Numbers need not match. Surname+initial heuristic is NOT an import witness."
        ),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--current", type=Path, required=True)
    p.add_argument("--ta-atp", type=Path, required=True)
    p.add_argument("--ta-wta", type=Path, required=True)
    p.add_argument("--ta-report", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    def read(path):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    own = [
        {"tour": r["tour"], "name": r["player_name"], "elo": r["overall_elo"]}
        for r in read(a.current)
    ]
    ta = [
        {"tour": r["tour"], "name": r["player"], "elo": r["elo"]}
        for path in (a.ta_atp, a.ta_wta) for r in read(path)
    ]
    official = json.loads(a.ta_report.read_text(encoding="utf-8"))
    result = {
        "schema": 1,
        "source": "Tennis Abstract (independent private research)",
        "ta_snapshot_date": official["snapshot_date"],
        "ta_training_eligible": bool(official["training_eligible"]),
        "canonical_model_mutated": False,
        "canonical_cdb_mutated": False,
        "match_witness_verified": False,
        "comparisons": [compare(own, ta, tour) for tour in ("atp", "wta")],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("TA_VS_OWN_ELO_RESEARCH_CROSSCHECK", json.dumps(result["comparisons"]))


if __name__ == "__main__":
    main()
