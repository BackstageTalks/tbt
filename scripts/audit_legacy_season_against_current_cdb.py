"""Read-only inventory of legacy 2021-26 season staging versus current CDB.

DO NOT promote rows to canonical: staging lacks independently verified
player/date/event signatures and clear time-of-availability/usage rights.
A match-id equality alone is NOT enough to authorize a CDB write.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

FIELDS = (
    ("p1_service_points_won", True),
    ("p1_return_points_won", True),
    ("p2_service_points_won", True),
    ("p2_return_points_won", True),
    ("p1_aces", False),
    ("p1_double_faults", False),
    ("p2_aces", False),
    ("p2_double_faults", False),
)


def audit(history_dir: Path, stage_csv: Path, manifest_json: Path) -> dict:
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    if manifest.get("rows") != 11689 or manifest.get("schema") != 1:
        raise ValueError("Unapproved old-season stage schema or row count")
    expected = str(manifest.get("stage_sha256") or "")
    observed = hashlib.sha256(stage_csv.read_bytes()).hexdigest()
    if expected != observed:
        raise ValueError("Legacy season CSV checksum mismatch")
    matches, safety = sanitize_history_identities(load_partitions(history_dir))
    if safety.get("quarantined_rows") or safety.get("changed"):
        raise ValueError("Current canonical identity sanitizer mutated/quarantined matches")
    index = {}
    for match in matches:
        mid = str(match.match_id)
        if mid in index:
            raise ValueError("Canonical duplicated match identifier")
        index[mid] = match
    counts = Counter()
    seen = set()
    with stage_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_no, row in enumerate(csv.reader(handle), 1):
            if len(row) != 9:
                raise ValueError(f"Invalid legacy stage width at row {line_no}")
            mid = row[0].strip()
            if not mid or mid in seen:
                raise ValueError(f"Duplicate/empty source match id at row {line_no}")
            seen.add(mid)
            counts["source_rows"] += 1
            match = index.get(mid)
            if match is None:
                counts["unlinked_stage_match_ids"] += 1
                continue
            counts["linked_stage_match_ids"] += 1
            if not 2021 <= match.scheduled_at.year <= 2026:
                counts["out_of_stage_date_range"] += 1
                continue
            old = match.stats or {}
            proposed = {}
            for raw, (key, rate) in zip(row[1:], FIELDS):
                value = raw.strip()
                if not value:
                    continue
                try:
                    number = float(value)
                except ValueError as e:
                    raise ValueError(f"Invalid numeric source field at {line_no}: {key}") from e
                if not math.isfinite(number):
                    raise ValueError("Nonfinite historical source field")
                if rate:
                    if not (0 <= number <= 100):
                        raise ValueError("Historical source rate outside 0-100")
                    number /= 100.0
                elif number < 0 or not number.is_integer():
                    raise ValueError("Invalid historical source count")
                proposed[key] = number
            if not proposed:
                counts["linked_no_source_stats"] += 1
                continue
            all_present = True
            any_missing = False
            conflict = False
            for key, v in proposed.items():
                prior = old.get(key)
                if prior is None:
                    counts["missing_candidate_field_values"] += 1
                    any_missing = True
                    all_present = False
                elif not math.isclose(float(prior), v, abs_tol=1e-5):
                    counts["conflicting_source_field_values"] += 1
                    conflict = True
            if conflict:
                counts["conflicting_matches"] += 1
            elif any_missing:
                counts["candidate_matches_missing_fields"] += 1
            elif all_present:
                counts["already_represented_matches"] += 1
    if counts["source_rows"] != manifest["rows"]:
        raise ValueError("Stage source truncated")
    return {
        "schema": 1, "status": "verified_read_only_no_write",
        "canonical_matches": len(matches), "source_rows": counts["source_rows"],
        "source_sha256": observed,
        "counts": dict(counts),
        "canonical_write_authorized": False,
        "canonical_mutated": False,
        "model_promoted": False,
        "reason": "No source row has independently reverified current event/player/winner signature or point-in-time provenance. Matching old match_id alone cannot authorize write.",
        "next_gate": "Reconstruct date/tour/participants/score source evidence; then exact-match each candidate against the current CDB, quarantine all field conflicts and verify net-new quality-ready delta under single writer.",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--stage-csv", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = audit(a.history_dir, a.stage_csv, a.manifest)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
