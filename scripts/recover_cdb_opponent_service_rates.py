"""Deterministic, fail-closed recovery of exact opponent serve/return complements.

Only previously observed whole-match service/return proportions are eligible.
No provider calls, inferred counts, fuzzy identity or historical odds.
Stage and local write never publish: release publication needs a separate
immutable backup, single-writer gate and independently downloaded read-back.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.history_safety import sanitize_history_identities
from tbt.providers.statistics import complete_opponent_service_rates

RECOVERABLE = {
    "p1_service_points_won", "p2_service_points_won",
    "p1_return_points_won", "p2_return_points_won",
}
POLICY = "post_match_only_prior_completed_history; exact whole_match_opponent_complement"


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                   allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def _storage(match) -> dict:
    result = match.to_storage_dict()
    if not isinstance(result, dict):
        raise ValueError("Canonical MatchRecord.to_storage_dict is invalid")
    return result


def _index(matches):
    mapping = {}
    for match in matches:
        key = str(match.match_id)
        if not key or key in mapping:
            raise ValueError("Missing or duplicate canonical match_id")
        mapping[key] = match
    return mapping


def stage(matches, *, as_of=None):
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("as_of must be timezone aware")
    result = []
    summary = Counter()
    for match in sorted(matches, key=lambda m: str(m.match_id)):
        summary["examined"] += 1
        # The observations must have occurred before the recovery moment.
        if not match.is_completed or match.scheduled_at >= now:
            summary["noncompleted_or_future"] += 1
            continue
        stats = match.stats
        if not isinstance(stats, dict):
            summary["invalid_stats"] += 1
            continue
        proposed = dict(stats)
        complete_opponent_service_rates(proposed)
        additions = {k: proposed[k] for k in sorted(RECOVERABLE)
                     if stats.get(k) is None and proposed.get(k) is not None}
        if not additions:
            continue
        if any(k in stats and stats[k] is not None for k in additions):
            raise ValueError("Existing canonical statistics would be overwritten")
        result.append({
            "schema": 1, "match_id": str(match.match_id),
            "utc_year": match.scheduled_at.astimezone(timezone.utc).year,
            "prewrite_hash": _sha(_storage(match)),
            "source_stats_hash": _sha(stats),
            "additions": additions,
            "policy": POLICY,
        })
        summary["staged_matches"] += 1
        summary["new_stat_values"] += len(additions)
    return result, dict(summary)


def write_local(matches, staged):
    by_id = _index(matches)
    seen, mutations = set(), []
    # Validate ALL rows before mutating even a local copy.
    for row in staged:
        if not isinstance(row, dict) or row.get("schema") != 1 or row.get("policy") != POLICY:
            raise ValueError("Unverified derived-statistics staging schema")
        key = str(row.get("match_id") or "")
        if key in seen or not key:
            raise ValueError("Duplicate or missing staged match identity")
        seen.add(key)
        match = by_id.get(key)
        if match is None or not match.is_completed:
            raise ValueError("Staged identity missing or match not completed")
        if match.scheduled_at.astimezone(timezone.utc).year != row.get("utc_year"):
            raise ValueError("Staged UTC partition changed")
        if row.get("prewrite_hash") != _sha(_storage(match)):
            raise ValueError("Canonical match changed since dry-run")
        before = match.stats or {}
        if row.get("source_stats_hash") != _sha(before):
            raise ValueError("Source statistics changed since dry-run")
        actual = dict(before)
        complete_opponent_service_rates(actual)
        expected = {k: actual[k] for k in sorted(RECOVERABLE)
                    if before.get(k) is None and actual.get(k) is not None}
        if expected != row.get("additions") or not expected:
            raise ValueError("Staged complement is not reproducible")
        mutations.append((match, expected))
    for match, additions in mutations:
        match.stats = {**(match.stats or {}), **additions}
    return sorted({m.scheduled_at.astimezone(timezone.utc).year for m, _ in mutations})


def verify_readback(before_matches, after_matches, staged):
    before = _index(before_matches)
    after = _index(after_matches)
    if before.keys() != after.keys():
        raise ValueError("Persisted CDB identities differ")
    by_stage = {str(r["match_id"]): r for r in staged}
    if len(by_stage) != len(staged):
        raise ValueError("Duplicate stage identities in read-back")
    for match_id, original in before.items():
        left = _storage(original)
        right = _storage(after[match_id])
        row = by_stage.get(match_id)
        before_stats = left.pop("stats", {}) or {}
        after_stats = right.pop("stats", {}) or {}
        if left != right:
            raise ValueError("Unstaged canonical field changed: " + match_id)
        expected = dict(before_stats)
        if row:
            if row["prewrite_hash"] != _sha(_storage(original)):
                raise ValueError("Original canonical mismatch in read-back")
            if row["source_stats_hash"] != _sha(before_stats):
                raise ValueError("Original statistics mismatch in read-back")
            expected.update(row["additions"])
        if after_stats != expected:
            raise ValueError("Unstaged or missing persisted statistics: " + match_id)
    return {"status": "verified", "canonical_matches": len(before),
            "enriched_matches": len(staged),
            "new_stat_values": sum(len(row["additions"]) for row in staged),
            "existing_values_overwritten": 0, "unverified_identities": 0}


def _load(directory):
    rows, safety = sanitize_history_identities(load_partitions(directory))
    if safety.get("quarantined_rows") or safety.get("changed"):
        raise ValueError("Canonical identity sanitizer changed or quarantined history")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["stage", "write", "verify"], required=True)
    p.add_argument("--history-dir", type=Path)
    p.add_argument("--before-dir", type=Path)
    p.add_argument("--stage-file", type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    a = p.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.mode == "stage":
        if not a.history_dir:
            p.error("--history-dir is required")
        staged, counts = stage(_load(a.history_dir))
        with (a.out_dir / "stage.jsonl").open("w", encoding="utf-8") as fh:
            for row in staged:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        result = {"schema": 1, "mode": "stage", "counts": counts,
                  "changed_years": sorted({r["utc_year"] for r in staged}),
                  "provider_requests": 0, "production_mutated": False}
    else:
        if not a.stage_file or not a.history_dir:
            p.error("--stage-file and --history-dir are required")
        staged = [json.loads(s) for s in a.stage_file.read_text(encoding="utf-8").splitlines()
                  if s.strip()]
        if a.mode == "write":
            matches = _load(a.history_dir)
            years = write_local(matches, staged)
            for year in years:
                write_year_partition(matches, a.history_dir, year)
            result = {"schema": 1, "mode": "write", "changed_years": years,
                      "updated": len(staged), "production_mutated": False, "provider_requests": 0}
        else:
            if not a.before_dir:
                p.error("--before-dir required for independent verification")
            result = verify_readback(_load(a.before_dir), _load(a.history_dir), staged)
    (a.out_dir / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
