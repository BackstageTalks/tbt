#!/usr/bin/env python3
"""Run the existing offline linker and retain only independently corroborated matches.

The linker is source-specific and may accept tournament-start windows. Generic
Drive imports require exact day, exact tournament, winner, and round/surface;
tournament-start dates require stronger corroboration (winner, exact tournament,
round, surface AND best-of), with a unique canonical match and no conflicts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import subprocess
import sys
from pathlib import Path


def _strict_source_evidence(proof: dict) -> bool:
    if not isinstance(proof, dict):
        return False
    evidence = set(proof.get("evidence") or [])
    if not {"winner", "tournament_exact"}.issubset(evidence):
        return False
    if {"round_conflict", "surface_conflict", "best_of_conflict"} & evidence:
        return False
    if "date_exact" in evidence:
        return bool({"round", "surface"} & evidence)
    # Sackmann-style files commonly contain the tournament start date, not
    # the match date. The read-only linker independently enforces a bounded
    # forward-only window and unique canonical candidate. For this weaker
    # date evidence, insist on every other strong match discriminator.
    return {"date_tournament_window", "round", "surface", "best_of"}.issubset(evidence)


def run(normalized_report: Path, history_dir: Path, out_dir: Path, *, expected_provider_quarantine: int = 0):
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(normalized_report.read_text(encoding="utf-8"))
    paths = [str(Path(row["path"]).resolve()) for row in manifest["normalized"]]
    if any(not Path(p).is_file() for p in paths):
        raise ValueError("Normalized source was lost before link")
    accepted_names = {"sackmann:" + Path(p).name for p in paths}
    result = {"schema": 1, "state": "READ_ONLY_STAGE", "production_mutated": False,
              "api_requests": 0, "source_files": len(paths), "eligible_matches": 0,
              "eligible_new_values": 0, "filtered_matches": 0, "conflict_matches": 0}
    target = out_dir / "eligible.jsonl"
    if not paths:
        target.write_text("")
        (out_dir / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    command = [sys.executable, str(Path(__file__).with_name("link_offline_serve_return.py")),
               "--history-dir", str(history_dir), "--out-dir", str(out_dir / "link")]
    if expected_provider_quarantine:
        command += ["--isolate-provider-collisions",
                    "--expected-provider-quarantine", str(expected_provider_quarantine)]
    for path in paths:
        command += ["--source-csv", path]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True,
                       env=os.environ.copy(), timeout=1800)
    except subprocess.CalledProcessError as exc:
        # Preserve the exact linker error instead of hiding it behind a generic
        # CalledProcessError. Never continue to the writer on a linker failure.
        raise RuntimeError(
            "CDB offline linker rejected source/history: "
            + (exc.stderr or exc.stdout or "no diagnostic")[-4000:]
        ) from exc
    link_dir = out_dir / "link"
    linked = json.loads((link_dir / "report.json").read_text())
    if linked.get("excluded_ambiguous_provider_rows") != expected_provider_quarantine:
        raise ValueError("Unexpected provider collision quarantine in offline linker")
    result["excluded_ambiguous_provider_rows"] = linked["excluded_ambiguous_provider_rows"]
    result["full_canonical_rows"] = linked["full_canonical_rows"]
    if linked.get("production_mutated") is not False or linked.get("api_requests") != 0:
        raise ValueError("Linker violated read-only contract")
    conflicted = {
        str(json.loads(line)["match_id"])
        for line in (link_dir / "quarantine.jsonl").read_text().splitlines() if line.strip()
    }
    staged = []
    rejection_reasons = Counter()
    for line in (link_dir / "auto_linked.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        candidate = json.loads(line)
        proof = candidate.get("sources") or []
        usable = (candidate.get("schema") == 1 and candidate.get("import_ready") is True
                  and isinstance(candidate.get("canonical"), dict)
                  and isinstance(candidate.get("incoming_stats"), dict)
                  and bool(proof) and all(
                      p.get("source") in accepted_names
                      and isinstance(p.get("evidence"), list)
                      and _strict_source_evidence(p)
                      for p in proof
                  ))
        year = str((candidate.get("canonical") or {}).get("scheduled_date_utc") or "")[:4]
        if not year.isdigit() or int(year) not in range(2016, 2027):
            result["filtered_year_matches"] = result.get("filtered_year_matches", 0) + 1
            usable = False
        if candidate.get("match_id") in conflicted:
            result["conflict_matches"] += 1
            usable = False
        if not usable:
            # Audit only; never rescue a candidate or weaken the gate here.
            result["filtered_matches"] += 1
            if candidate.get("schema") != 1 or candidate.get("import_ready") is not True:
                rejection_reasons["invalid_stage_contract"] += 1
            if not isinstance(candidate.get("incoming_stats"), dict) or not candidate.get("incoming_stats"):
                rejection_reasons["no_candidate_stat_values"] += 1
            if not proof:
                rejection_reasons["missing_provenance"] += 1
            for source in proof:
                evidence = set(source.get("evidence") or []) if isinstance(source, dict) else set()
                if "date_exact" not in evidence:
                    rejection_reasons["date_not_exact"] += 1
                if "tournament_exact" not in evidence:
                    rejection_reasons["tournament_not_exact"] += 1
                if not {"round", "surface"} & evidence:
                    rejection_reasons["round_or_surface_unconfirmed"] += 1
                if "winner" not in evidence:
                    rejection_reasons["winner_unconfirmed"] += 1
                if {"round_conflict", "surface_conflict", "best_of_conflict"} & evidence:
                    rejection_reasons["metadata_conflict"] += 1
            if candidate.get("match_id") in conflicted:
                rejection_reasons["canonical_stat_conflict"] += 1
            if not year.isdigit() or int(year) not in range(2016, 2027):
                rejection_reasons["outside_supported_years"] += 1
            continue
        staged.append(candidate)
        if any("date_tournament_window" in (p.get("evidence") or []) for p in proof):
            result["tournament_window_eligible_matches"] = result.get("tournament_window_eligible_matches", 0) + 1
        result["eligible_matches"] += 1
        result["eligible_new_values"] += len(candidate["incoming_stats"])
    with target.open("w", encoding="utf-8") as handle:
        for row in staged:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result["link_counts"] = linked.get("counts", {})
    result["filter_reasons"] = dict(sorted(rejection_reasons.items()))
    result["source_rows"] = linked.get("source_rows", 0)
    result["read_only_linked"] = linked.get("counts", {}).get("identity_linked", 0)
    (out_dir / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--normalized-report", type=Path, required=True)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--expected-provider-quarantine", type=int, default=0)
    a = p.parse_args()
    result = run(a.normalized_report, a.history_dir, a.out_dir,
                 expected_provider_quarantine=a.expected_provider_quarantine)
    print(json.dumps({k: v for k, v in result.items() if k not in {"link_counts"}}))

if __name__ == "__main__":
    main()
