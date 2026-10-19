#!/usr/bin/env python3
"""Run the existing offline linker and retain only independently corroborated matches.

The linker is source-specific and may accept tournament-start windows. This
generic Drive inbox is stricter: exact day, exact tournament, winner and
additional round/surface evidence are required for unattended canonical import.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def run(normalized_report: Path, history_dir: Path, out_dir: Path):
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
    for path in paths:
        command += ["--source-csv", path]
    subprocess.run(command, check=True, capture_output=True, text=True,
                   env=os.environ.copy(), timeout=1800)
    link_dir = out_dir / "link"
    linked = json.loads((link_dir / "report.json").read_text())
    if linked.get("production_mutated") is not False or linked.get("api_requests") != 0:
        raise ValueError("Linker violated read-only contract")
    conflicted = {
        str(json.loads(line)["match_id"])
        for line in (link_dir / "quarantine.jsonl").read_text().splitlines() if line.strip()
    }
    staged = []
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
                      and {"date_exact", "winner", "tournament_exact"}.issubset(set(p["evidence"]))
                      and bool({"round", "surface"} & set(p["evidence"]))
                      and not {"round_conflict", "surface_conflict", "best_of_conflict"} & set(p["evidence"])
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
            result["filtered_matches"] += 1
            continue
        staged.append(candidate)
        result["eligible_matches"] += 1
        result["eligible_new_values"] += len(candidate["incoming_stats"])
    with target.open("w", encoding="utf-8") as handle:
        for row in staged:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result["link_counts"] = linked.get("counts", {})
    result["source_rows"] = linked.get("source_rows", 0)
    result["read_only_linked"] = linked.get("counts", {}).get("identity_linked", 0)
    (out_dir / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--normalized-report", type=Path, required=True)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    result = run(a.normalized_report, a.history_dir, a.out_dir)
    print(json.dumps({k: v for k, v in result.items() if k not in {"link_counts"}}))

if __name__ == "__main__":
    main()
