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
from tbt.data.history_snapshot import load_partitions
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


def _inconsistent_observed_pair(stats):
    """Never derive from a record with contradictory service/return evidence."""
    import math
    for serve, ret in (("p1_service_points_won", "p2_return_points_won"),
                       ("p2_service_points_won", "p1_return_points_won")):
        a, b = stats.get(serve), stats.get(ret)
        if a is None or b is None:
            continue
        if (isinstance(a, bool) or isinstance(b, bool) or
                not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or
                not math.isfinite(a) or not math.isfinite(b) or
                not 0 <= a <= 1 or not 0 <= b <= 1 or
                abs(float(a) + float(b) - 1.0) > 0.000001):
            return True
    return False


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
        if _inconsistent_observed_pair(stats):
            summary["contradictory_observed_rates"] += 1
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
        if _inconsistent_observed_pair(before):
            raise ValueError("Conflicting observed service/return evidence")
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



def write_exact_stats_partition(history_dir: Path, year: int, staged: list[dict]) -> None:
    """Persist only staged stats_json cells; never reserialize unrelated matches.

    All rows are compared against the original entire year via the standard
    strict readback verifier before replacing any local partition.
    """
    import pandas as pd
    from tbt.data.history_snapshot import (
        load_snapshot, load_manifest, partition_path, update_year_manifest,
    )

    candidates = [row for row in staged if int(row["utc_year"]) == int(year)]
    if not candidates:
        raise ValueError("No staged statistics for requested partition")
    path = partition_path(history_dir, year)
    if not path.is_file():
        raise FileNotFoundError("Canonical year partition missing")
    original = load_snapshot(path)
    by_id = _index(original)
    frame = pd.read_parquet(path, engine="pyarrow")
    if not {"match_id", "stats_json", "scheduled_at"}.issubset(frame.columns):
        raise ValueError("Invalid canonical Parquet statistic schema")
    keys = frame["match_id"].astype(str)
    if keys.duplicated().any() or len(frame) != len(original):
        raise ValueError("Canonical year identity collision")
    offsets = dict(zip(keys, frame.index))
    other_columns = frame.drop(columns=["stats_json"]).copy(deep=True)
    original_stats_column = frame["stats_json"].copy(deep=True)
    touched = set()
    for row in candidates:
        mid = str(row.get("match_id") or "")
        record = by_id.get(mid)
        if record is None or mid not in offsets:
            raise ValueError("Staged canonical match not present in original partition")
        if row.get("schema") != 1 or row.get("policy") != POLICY:
            raise ValueError("Unverified staged complement schema")
        if _sha(_storage(record)) != row["prewrite_hash"]:
            raise ValueError("Canonical match changed before Parquet patch")
        if _sha(record.stats or {}) != row["source_stats_hash"]:
            raise ValueError("Source statistics changed before Parquet patch")
        index = offsets[mid]
        raw = frame.at[index, "stats_json"]
        if not isinstance(raw, str):
            raise ValueError("Invalid original Parquet statistics JSON")
        stats = json.loads(raw)
        if not isinstance(stats, dict):
            raise ValueError("Original statistics must be a JSON object")
        computed = dict(record.stats or {})
        if _inconsistent_observed_pair(computed):
            raise ValueError("Conflicting observed complement source")
        complete_opponent_service_rates(computed)
        expected = {k: computed[k] for k in sorted(RECOVERABLE)
                    if (record.stats or {}).get(k) is None and computed.get(k) is not None}
        if expected != row.get("additions") or not expected:
            raise ValueError("Complement no longer reproducible")
        for key, value in expected.items():
            if stats.get(key) is not None:
                raise ValueError("Refusing existing statistic overwrite")
            stats[key] = value
        frame.at[index, "stats_json"] = json.dumps(
            stats, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        touched.add(index)
    if len(touched) != len(candidates):
        raise ValueError("Duplicate staged match in Parquet patch")
    pd.testing.assert_frame_equal(
        frame.drop(columns=["stats_json"]), other_columns, check_dtype=True,
    )
    untouched = ~frame.index.isin(touched)
    if not frame.loc[untouched, "stats_json"].equals(original_stats_column.loc[untouched]):
        raise ValueError("Unstaged statistics mutated before write")
    temporary = path.with_name(path.name + ".service-exact.tmp")
    try:
        frame.to_parquet(temporary, engine="pyarrow", compression="zstd", index=False)
        comparison = verify_readback(original, load_snapshot(temporary), candidates)
        if comparison["enriched_matches"] != len(candidates):
            raise ValueError("Local exact-stat readback count mismatch")
        meta = load_manifest(history_dir).get("years", {}).get(str(year))
        if not isinstance(meta, dict) or int(meta.get("rows", -1)) != len(frame):
            raise ValueError("Canonical manifest partition row count mismatch")
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        size = temporary.stat().st_size
        if size <= 0:
            raise ValueError("Empty patched canonical partition")
        temporary.replace(path)
        update_year_manifest(history_dir, year, {
            "sha256": digest, "bytes": size, "rows": len(frame),
        })
    finally:
        if temporary.exists():
            temporary.unlink()


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
                write_exact_stats_partition(a.history_dir, year, staged)
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
