#!/usr/bin/env python3
"""Strict read-only WTA match stage, quarantine every weak/conflicted identity.

Inputs are ONLY linker outputs from the pinned Kaggle Hwaitt WTA source.
A source's internal numeric IDs are never accepted as canonical IDs.
No writer, HTTP or paid API is imported by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

EVIDENCE = frozenset(("date_exact", "winner", "tournament_exact", "surface"))
BLOCKED = frozenset(("round_conflict", "surface_conflict",
                     "best_of_conflict", "winner_conflict",
                     "canonical_winner_missing", "winner_id_conflict"))


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError("Required linker output missing: " + path.name)
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Non-object JSONL row at {line_no}")
            rows.append(row)
    return rows


def filter_links(link_dir: Path, out_dir: Path,
                 expected_source: str = "kaggle-hwaitt:wta_matches_verified.csv") -> dict:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Refusing overwrite of prior filtered stage")
    linked_report = json.loads((link_dir / "report.json").read_text(encoding="utf-8"))
    if linked_report.get("production_mutated") is not False or linked_report.get("api_requests") != 0:
        raise ValueError("Linker read-only contract violated")
    if not linked_report.get("source_rows") or linked_report.get("matching_strategy") != "verified_ids":
        raise ValueError("Linker source/matching contract unexpected")

    conflicts = {
        str(row["match_id"]) for row in load_jsonl(link_dir / "quarantine.jsonl")
    }
    candidates = load_jsonl(link_dir / "auto_linked.jsonl")
    reasons = Counter()
    accepted = []
    used_matches = set()
    years = set(range(2016, 2021))
    for row in candidates:
        match_id = str(row.get("match_id") or "")
        canonical = row.get("canonical") or {}
        proofs = row.get("sources") or []
        stats = row.get("incoming_stats") or {}
        if not match_id or match_id in used_matches:
            raise ValueError("Missing/duplicate canonical match in linker output")
        used_matches.add(match_id)

        if row.get("schema") != 1 or row.get("import_ready") is not True:
            reasons["invalid_linker_stage"] += 1
            continue
        if not isinstance(canonical, dict) or canonical.get("tour") != "wta":
            reasons["wrong_tour"] += 1
            continue
        day = str(canonical.get("scheduled_date_utc") or "")
        if not day[:4].isdigit() or int(day[:4]) not in years:
            reasons["outside_verified_window"] += 1
            continue
        if match_id in conflicts:
            reasons["conflicted_canonical_stats"] += 1
            continue
        if not isinstance(stats, dict) or not stats:
            reasons["empty_candidate_stats"] += 1
            continue
        if not isinstance(proofs, list) or not proofs:
            reasons["missing_identity_evidence"] += 1
            continue
        if any(not isinstance(proof, dict)
               or proof.get("source") != expected_source
               or not isinstance(proof.get("evidence"), list)
               or not EVIDENCE.issubset(set(proof["evidence"]))
               or BLOCKED.intersection(proof["evidence"])
               for proof in proofs):
            reasons["unconfirmed_source_identity"] += 1
            continue

        accepted.append(row)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "eligible.jsonl").open("x", encoding="utf-8") as out:
        for row in accepted:
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema": 1,
        "state": "STRICT_WTA_CDB_DRY_RUN_ONLY",
        "production_mutated": False,
        "api_requests": 0,
        "linked_source_rows": linked_report["source_rows"],
        "link_counts": linked_report.get("counts", {}),
        "linked_candidates": len(candidates),
        "quarantine_matches": len(conflicts),
        "eligible_matches": len(accepted),
        "eligible_new_stat_fields": sum(len(row["incoming_stats"]) for row in accepted),
        "reasons": dict(sorted(reasons.items())),
        "source": expected_source,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--link-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(filter_links(args.link_dir, args.out_dir), sort_keys=True))


if __name__ == "__main__":
    main()
