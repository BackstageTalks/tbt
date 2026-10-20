#!/usr/bin/env python3
"""Bounded recent ATP/WTA CDB matching gate; source-only and NULL-only dry-run.

Tournament-start dates may lead canonical match dates by at most 16 days in
the existing linker. Evidence must independently show same tournament, both
players, winner, surface and round. Conflicts and ambiguous matches fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

from cdb_wta_strict_stage import load_jsonl

REQUIRED = frozenset(("winner", "tournament_exact", "surface", "round"))
FORBIDDEN = frozenset(("round_conflict", "surface_conflict", "best_of_conflict",
                       "winner_conflict", "canonical_winner_missing",
                       "winner_id_conflict", "tournament_mismatch"))
ALLOWED_YEARS = set(range(2023, 2027))


def filter_links(link_dir: Path, normalized_report: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing overwrite of earlier recent-match stage")
    normalized = json.loads(normalized_report.read_text(encoding="utf-8"))
    sources = normalized.get("normalized")
    if (normalized.get("production_mutated") is not False
            or normalized.get("api_requests") != 0
            or not isinstance(sources, list) or not sources):
        raise ValueError("Normalized source provenance not verified")
    accepted_sources = {}
    for source in sources:
        tour = source.get("tour")
        path = source.get("path")
        if tour not in ("atp", "wta") or not isinstance(path, str):
            raise ValueError("Invalid normalized source")
        name = "sackmann:" + Path(path).name
        if name in accepted_sources:
            raise ValueError("Duplicate normalized source")
        accepted_sources[name] = tour

    linker = json.loads((link_dir / "report.json").read_text(encoding="utf-8"))
    if (linker.get("production_mutated") is not False
            or linker.get("api_requests") != 0
            or linker.get("matching_strategy") != "verified_ids"):
        raise ValueError("Linker read-only/identity contract violated")
    conflicted = {str(x["match_id"]) for x in load_jsonl(link_dir / "quarantine.jsonl")}
    linked = load_jsonl(link_dir / "auto_linked.jsonl")
    reasons, categories, field_counts = Counter(), Counter(), Counter()
    accepted, seen = [], set()
    for row in linked:
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Missing/duplicate canonical stage identity")
        seen.add(mid)
        if row.get("schema") != 1 or row.get("import_ready") is not True:
            reasons["invalid_stage_contract"] += 1
            continue
        identity = row.get("canonical")
        if not isinstance(identity, dict) or identity.get("tour") not in ("atp", "wta"):
            reasons["unsupported_canonical_tour"] += 1
            continue
        day = str(identity.get("scheduled_date_utc") or "")
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            reasons["invalid_canonical_date"] += 1
            continue
        if parsed.isoformat() != day or parsed.year not in ALLOWED_YEARS:
            reasons["outside_2023_2026"] += 1
            continue
        if mid in conflicted:
            reasons["canonical_stats_conflict"] += 1
            continue
        stats = row.get("incoming_stats")
        if not isinstance(stats, dict) or not stats:
            reasons["no_candidate_missing_fields"] += 1
            continue
        proofs = row.get("sources")
        if not isinstance(proofs, list) or not proofs:
            reasons["no_provenance"] += 1
            continue
        valid = all(
            isinstance(p, dict)
            and accepted_sources.get(p.get("source")) == identity["tour"]
            and isinstance(p.get("evidence"), list)
            and REQUIRED.issubset(set(p["evidence"]))
            and not FORBIDDEN.intersection(p["evidence"])
            and ("date_exact" in p["evidence"] or "date_tournament_window" in p["evidence"])
            for p in proofs
        )
        if not valid:
            reasons["insufficient_independent_identity"] += 1
            continue
        accepted.append(row)
        categories[f"{parsed.year}_{identity['tour']}"] += 1
        field_counts.update(stats.keys())

    output.mkdir(parents=True, exist_ok=True)
    with (output / "eligible.jsonl").open("x", encoding="utf-8") as f:
        for row in accepted:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema": 1, "state": "RECENT_MATCH_NULL_ONLY_DRY_RUN",
        "production_mutated": False, "api_requests": 0,
        "normalized_files": len(accepted_sources),
        "source_rows": linker.get("source_rows", 0),
        "link_counts": linker.get("counts", {}),
        "linked_candidates": len(linked),
        "conflict_matches": len(conflicted),
        "eligible_matches": len(accepted),
        "eligible_new_stat_fields": sum(len(x["incoming_stats"]) for x in accepted),
        "eligible_by_year_tour": dict(sorted(categories.items())),
        "eligible_field_counts": dict(sorted(field_counts.items())),
        "reasons": dict(sorted(reasons.items())),
        "license_review_required": True,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--link-dir", type=Path, required=True)
    p.add_argument("--normalized-report", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(filter_links(args.link_dir, args.normalized_report, args.out_dir),
                     sort_keys=True))


if __name__ == "__main__":
    main()
