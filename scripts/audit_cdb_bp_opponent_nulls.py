#!/usr/bin/env python3
"""Read-only audit of EXACT opponent break-point save/conversion complements.

Same break point: one player saves it OR the opponent converts it. Source
rates are canonical observed whole-match proportions, not inferred counts.
A valid interior source rate (0 < p < 1) with a NULL counterpart is a
research candidate, NOT a production write authorization. Boundary 0/1
rates need separate source-denominator provenance before any import.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

PAIRS = (
    ("p1_break_point_serve_win", "p2_break_point_return_win"),
    ("p2_break_point_serve_win", "p1_break_point_return_win"),
)


def valid_rate(x):
    return (isinstance(x, (float, int)) and not isinstance(x, bool)
            and math.isfinite(x) and 0 <= x <= 1)


def classify(stats):
    """Fail closed for any invalid or conflicting BP pair in the match."""
    if not isinstance(stats, dict):
        return "invalid_stats", {}, 0
    missing = {}
    boundary = 0
    for save, conversion in PAIRS:
        a, b = stats.get(save), stats.get(conversion)
        if any(v is not None and not valid_rate(v) for v in (a, b)):
            return "invalid_bp_rate", {}, 0
        if a is not None and b is not None:
            if abs(float(a) + float(b) - 1.0) > 1e-6:
                return "contradictory_bp_pair", {}, 0
            continue
        if a is None and b is None:
            continue
        observed = b if a is None else a
        if not 0.0 < float(observed) < 1.0:
            boundary += 1
            continue
        missing[save if a is None else conversion] = 1.0 - float(observed)
    if missing:
        return "interior_null_complement_candidate", missing, boundary
    if boundary:
        return "boundary_requires_denominator_witness", {}, boundary
    return "no_bp_complement_gap", {}, 0


def add_record(counts, status, stats):
    counts["examined"] += 1
    if str(status or "").lower() not in ("finished", "completed", "ended"):
        counts["not_completed"] += 1
        return
    try:
        obj = json.loads(stats) if isinstance(stats, str) else stats
    except (TypeError, ValueError):
        counts["unparseable_stats"] += 1
        return
    code, candidates, boundary = classify(obj)
    counts[code] += 1
    counts["boundary_pairs_to_review"] += boundary
    if candidates:
        counts["possible_new_null_bp_values"] += len(candidates)
        for key in candidates:
            counts["candidate_" + key] += 1


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def audit(root, out, *, years=range(2016, 2027)):
    import pyarrow.parquet as pq

    manifests = json.loads((root / "history_manifest.json").read_text())["years"]
    bundle = json.loads((root / "_tbt_bundle_manifest.json").read_text())["files"]
    by_cohort = {}
    total = Counter()
    for year in years:
        name = f"history-{year}.parquet"
        path = root / name
        if (not path.is_file() or digest(path) != manifests[str(year)]["sha256"]
                or digest(path) != bundle[name]["sha256"]):
            raise ValueError("Canonical history SHA/manifest mismatch: " + name)
        pf = pq.ParquetFile(path)
        cols = ("tour", "status", "stats_json")
        if not set(cols).issubset(pf.schema_arrow.names):
            raise ValueError("Canonical Parquet lacks expected fields: " + name)
        for batch in pf.iter_batches(batch_size=4096, columns=list(cols)):
            data = batch.to_pydict()
            for tour, status, stats in zip(data["tour"], data["status"], data["stats_json"]):
                label = str(tour or "").lower()
                if label not in ("atp", "wta"):
                    continue
                counts = by_cohort.setdefault(f"{year}:{label}", Counter())
                add_record(counts, status, stats)
    for counter in by_cohort.values():
        total.update(counter)
    report = {
        "schema": 1,
        "status": "READ_ONLY_BP_OPPONENT_COMPLEMENT_NULL_AUDIT",
        "years": list(years),
        "totals": dict(sorted(total.items())),
        "by_year_tour": {k: dict(sorted(v.items())) for k, v in sorted(by_cohort.items())},
        "quarantine_policy": "invalid/conflicting match, incomplete match, or boundary source rate",
        "provider_requests": 0,
        "production_mutated": False,
        "native_dryrun_executed": False,
        "write_authorized": False,
        "proof_warning": "Potential candidates require original denominator/provenance verification and native writer dry-run before NULL-only publish.",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("CDB_BP_OPPONENT_READONLY_AUDIT", json.dumps({
        "totals": report["totals"], "years": report["years"],
    }, sort_keys=True), flush=True)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    audit(args.history_dir, args.out)


if __name__ == "__main__":
    main()
