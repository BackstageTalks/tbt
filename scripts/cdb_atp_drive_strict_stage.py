#!/usr/bin/env python3
"""Read-only ATP 2016-2017 exact tournament-link preflight.

The source uses tournament start date, not guaranteed exact match day; a
forward 16-day window is accepted ONLY when canonical winner, surface, round
and tournament are independently corroborated, with zero conflicts/ties.
Existing linker and importer perform the remaining identity/NULL-only checks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from cdb_wta_strict_stage import load_jsonl

REQUIRED = frozenset(("winner", "tournament_exact", "round", "surface"))
BLOCKED = frozenset(("round_conflict", "surface_conflict", "best_of_conflict",
                     "winner_conflict", "canonical_winner_missing",
                     "winner_id_conflict"))


def filter_atp(link_dir: Path, normalized_report: Path, out_dir: Path) -> dict:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Refusing overwrite of ATP stage")
    source = json.loads(normalized_report.read_text(encoding="utf-8"))
    if source.get("production_mutated") is not False or source.get("api_requests") != 0:
        raise ValueError("Adapter source contract violated")
    parts = source.get("normalized")
    if not isinstance(parts, list) or not parts:
        raise ValueError("No verified ATP source files")
    names = {"sackmann:" + Path(x["path"]).name for x in parts
             if x.get("tour") == "atp"}
    if len(names) != len(parts):
        raise ValueError("Unexpected non-ATP normalized source")
    linked = json.loads((link_dir / "report.json").read_text(encoding="utf-8"))
    if linked.get("production_mutated") is not False or linked.get("api_requests") != 0:
        raise ValueError("Linker source contract violated")
    if linked.get("matching_strategy") != "verified_ids":
        raise ValueError("Matching mode must be verified_ids")
    conflicted = {str(x["match_id"]) for x in load_jsonl(link_dir / "quarantine.jsonl")}
    reasons = Counter()
    accepted = []
    used = set()
    rows = load_jsonl(link_dir / "auto_linked.jsonl")
    for x in rows:
        mid = str(x.get("match_id") or "")
        if not mid or mid in used:
            raise ValueError("Duplicate or missing canonical match")
        used.add(mid)
        if x.get("schema") != 1 or x.get("import_ready") is not True:
            reasons["invalid_linker_stage"] += 1
            continue
        canonical = x.get("canonical")
        if not isinstance(canonical, dict) or canonical.get("tour") != "atp":
            reasons["wrong_tour"] += 1
            continue
        day = str(canonical.get("scheduled_date_utc") or "")
        if not day[:4].isdigit() or int(day[:4]) not in (2016, 2017):
            reasons["wrong_year"] += 1
            continue
        if mid in conflicted:
            reasons["canonical_conflict"] += 1
            continue
        stats = x.get("incoming_stats")
        if not isinstance(stats, dict) or not stats:
            reasons["no_new_values"] += 1
            continue
        proofs = x.get("sources")
        if not isinstance(proofs, list) or not proofs:
            reasons["no_provenance"] += 1
            continue
        good = all(
            isinstance(p, dict)
            and p.get("source") in names
            and isinstance(p.get("evidence"), list)
            and REQUIRED.issubset(set(p["evidence"]))
            and not BLOCKED.intersection(p["evidence"])
            and ("date_exact" in p["evidence"] or "date_tournament_window" in p["evidence"])
            for p in proofs
        )
        if not good:
            reasons["weak_or_conflicting_identity_evidence"] += 1
            continue
        accepted.append(x)

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "eligible.jsonl").open("x", encoding="utf-8") as dest:
        for x in accepted:
            dest.write(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema": 1, "state": "ATP_2016_2017_DRY_RUN_ONLY",
        "production_mutated": False, "api_requests": 0,
        "normalized_files": len(names), "linked_source_rows": linked.get("source_rows", 0),
        "link_counts": linked.get("counts", {}),
        "linked_candidates": len(rows), "quarantined_matches": len(conflicted),
        "eligible_matches": len(accepted),
        "eligible_new_stat_fields": sum(len(x["incoming_stats"]) for x in accepted),
        "reasons": dict(sorted(reasons.items())),
        "license_review_required": True,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--link-dir", type=Path, required=True)
    p.add_argument("--normalized-report", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(filter_atp(args.link_dir, args.normalized_report, args.out_dir),
                     sort_keys=True))


if __name__ == "__main__":
    main()
