"""NULL-only, provenance-attested Sackmann historical breakpoint conversion import.

Writes are strictly local. The GitHub Actions workflow owns the global writer
lock, immutable backup, publication CAS and independent remote CDB read-back.

Only TWO rate keys are in scope: p1/p2_break_point_return_win.
Legacy p1/p2_break_points_won are counts and MUST NOT be written here.
All statistics represent completed-match observations, never prematch inputs
for the same match.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from audit_pbp_source_vs_current_cdb import FILES, valid
from import_historical_match_foundation import _round, _source_type, _stats
from recover_cdb_opponent_service_rates import (
    _load, _sha, _storage, verify_readback,
)
from tbt.data.offline_odds import norm_text

FIELDS = frozenset(("p1_break_point_return_win", "p2_break_point_return_win"))
POLICY = "sackmann_hist_js_native_id_exact_source_bp_conversion_null_only_v1"
SOURCE_REVISION = "83733587353df8a41f2fd4f516147d5aa83f5a8d"
SOURCE = "jeff_sackmann_match_snapshot:"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1048576), b""):
            h.update(part)
    return h.hexdigest()


def source_match_id(tour: str, path: Path, row: dict, line_no: int) -> tuple[str, str]:
    """Bit-for-bit historical import key (incl. missing match_num fallback)."""
    kind = _source_type(path, tour)
    pieces = (tour, kind, str(row.get("tourney_id") or "").strip(),
              str(row.get("match_num") or line_no).strip(),
              _round(row.get("round")),
              "|".join(sorted((norm_text(row.get("winner_name")),
                               norm_text(row.get("loser_name"))))))
    key = "|".join(pieces)
    return f"hist-js:{tour}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}", kind


def _valid_cdb_lineage(match, row: dict, tour: str, kind: str, file: Path) -> bool:
    """Require exact native original IDs AND the historical import's provenance."""
    if (str(match.tour).lower() != tour or
            not match.is_completed or
            str(match.status).lower() != "completed" or
            match.scheduled_at >= datetime.now(timezone.utc)):
        return False
    original_date = str(row.get("tourney_date") or "").strip()
    if (not re.fullmatch(r"\d{8}", original_date) or
            match.scheduled_at.strftime("%Y%m%d") != original_date):
        return False
    w, l = str(row.get("winner_id") or "").strip(), str(row.get("loser_id") or "").strip()
    if not w or not l or w == l or not re.fullmatch(r"[A-Za-z0-9_.:-]+", w + l):
        return False
    if (str(match.player1_id) != f"hist-js:{tour}:{w}" or
            str(match.player2_id) != f"hist-js:{tour}:{l}" or
            str(match.winner_id) != str(match.player1_id)):
        return False
    if (norm_text(match.player1_name) != norm_text(row.get("winner_name")) or
            norm_text(match.player2_name) != norm_text(row.get("loser_name"))):
        return False
    ctx = match.provider_payload
    if not isinstance(ctx, dict):
        return False
    evidence = ctx.get("_tbt_statistics")
    return (isinstance(evidence, dict) and
            evidence.get("source") == SOURCE + file.name and
            ctx.get("_tbt_provider_event_id") == str(match.match_id) and
            ctx.get("_tbt_source_category_name") == "historical_" + kind)


def _source_rates(row: dict) -> dict[str, float]:
    """Two independent winner/loser return-side break-point conversion rates."""
    stats = valid(row)  # complete score, all raw counts and sanity constraints
    if stats is None:
        return {}
    result = {}
    if stats["l_bpFaced"] > 0:
        result["p1_break_point_return_win"] = (
            stats["l_bpFaced"] - stats["l_bpSaved"]) / stats["l_bpFaced"]
    if stats["w_bpFaced"] > 0:
        result["p2_break_point_return_win"] = (
            stats["w_bpFaced"] - stats["w_bpSaved"]) / stats["w_bpFaced"]
    return result


def candidate(match, row: dict, tour: str, path: Path, line_no: int,
              file_hash: str) -> tuple[dict | None, str]:
    """Pure per-match eligibility; no fuzzy player match and no mutations."""
    mid, kind = source_match_id(tour, path, row, line_no)
    if str(match.match_id) != mid or not _valid_cdb_lineage(match, row, tour, kind, path):
        return None, "lineage_rejected"
    rates = _source_rates(row)
    if not rates:
        return None, "invalid_or_zero_denominator"
    previous = match.stats
    if not isinstance(previous, dict):
        return None, "invalid_stats"
    # Historical importer used precisely these original counts for its values.
    # Conflicting source revisions or existing values quarantine the entire row.
    known = _stats(row)
    for key, computed in known.items():
        observed = previous.get(key)
        if observed is not None and (
            isinstance(observed, bool) or not isinstance(observed, (int, float)) or
            not math.isfinite(observed) or abs(float(observed) - computed) > 1e-6
        ):
            return None, "source_snapshot_conflict"
    for key, value in rates.items():
        observed = previous.get(key)
        if observed is not None and (
            isinstance(observed, bool) or not isinstance(observed, (int, float)) or
            not math.isfinite(observed) or abs(float(observed) - value) > 1e-6
        ):
            return None, "existing_bp_conflict"
        counterpart = "p2_break_point_serve_win" if key.startswith("p1_") else "p1_break_point_serve_win"
        complement = previous.get(counterpart)
        if complement is not None and (
            isinstance(complement, bool) or not isinstance(complement, (int, float)) or
            not math.isfinite(complement) or abs(float(complement) + value - 1) > 1e-6
        ):
            return None, "counterpart_bp_conflict"
    additions = {key: value for key, value in sorted(rates.items())
                 if previous.get(key) is None}
    if not additions:
        return None, "already_filled"
    assert additions.keys() <= FIELDS
    return {
        "schema": 1, "policy": POLICY, "match_id": mid,
        "utc_year": match.scheduled_at.astimezone(timezone.utc).year,
        "prewrite_hash": _sha(_storage(match)),
        "source_stats_hash": _sha(previous),
        "source": {"commit": SOURCE_REVISION, "file": str(path).replace("\\", "/"),
                   "sha256": file_hash, "csv_line": line_no,
                   "winner_id": str(row["winner_id"]),
                   "loser_id": str(row["loser_id"])},
        "additions": additions,
    }, "staged"


def _iter_csv(root: Path):
    for path in sorted(root.rglob("*.csv")):
        rel = path.relative_to(root).as_posix()
        if not any(re.fullmatch(pattern, rel) for pattern in FILES):
            continue
        tour = rel.split("/", 1)[0]
        yield tour, path, rel


def stage(matches, source_root: Path):
    if not source_root.is_dir():
        raise ValueError("Pinned original source directory missing")
    index = {str(m.match_id): m for m in matches if str(m.match_id).startswith("hist-js:")}
    counts = Counter()
    staged = {}
    conflicts = set()
    source_hashes = {}
    for tour, path, rel in _iter_csv(source_root):
        counts["source_files"] += 1
        file_hash = digest(path)
        source_hashes[rel] = file_hash
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for line_no, row in enumerate(csv.DictReader(handle), 2):
                counts["source_rows"] += 1
                if not row.get("tourney_id") or not row.get("winner_name") or not row.get("loser_name"):
                    counts["missing_source_identity"] += 1
                    continue
                mid, _ = source_match_id(tour, path, row, line_no)
                record = index.get(mid)
                if record is None:
                    continue
                counts["matching_cdb_id"] += 1
                if mid in conflicts or mid in staged:
                    conflicts.add(mid)
                    staged.pop(mid, None)
                    counts["duplicate_source_target_quarantined"] += 1
                    continue
                proposed, status = candidate(record, row, tour, path, line_no, file_hash)
                counts[status] += 1
                if proposed is not None:
                    proposed["source"]["file"] = rel
                    staged[mid] = proposed
    if not counts["source_files"]:
        raise ValueError("No original Sackmann CSV files found")
    output = sorted(staged.values(), key=lambda r: r["match_id"])
    counts["staged_matches"] = len(output)
    counts["new_stat_values"] = sum(len(r["additions"]) for r in output)
    return output, dict(counts), source_hashes


def write_local(matches, staged: list[dict], source_root: Path):
    """Full deterministic source replay + baseline CAS BEFORE any local write."""
    expected, _, _ = stage(matches, source_root)
    if expected != staged or len({r["match_id"] for r in staged}) != len(staged):
        raise ValueError("Source, identity, baseline or source SHA changed since stage")
    by_id = {str(m.match_id): m for m in matches}
    for row in staged:
        if row["policy"] != POLICY or set(row["additions"]) - FIELDS:
            raise ValueError("Unapproved or altered breakpoint stage")
        match = by_id[row["match_id"]]
        for key, value in row["additions"].items():
            if match.stats.get(key) is not None:
                raise ValueError("Existing CDB breakpoint value would be overwritten")
            if not isinstance(value, (float, int)) or not (0 <= value <= 1):
                raise ValueError("Invalid breakpoint conversion fraction")
    changed = {int(row["utc_year"]) for row in staged}
    for row in staged:
        by_id[row["match_id"]].stats = {
            **by_id[row["match_id"]].stats, **row["additions"]}
    return sorted(changed)


def write_exact(history_dir: Path, matches, staged):
    """Apply additive changed rows using the generic guarded full-year Parquet patch."""
    from offline_exact_cdb_write import write_exact_stats_partition
    for year in sorted({r["utc_year"] for r in staged}):
        ids = {r["match_id"] for r in staged if r["utc_year"] == year}
        write_exact_stats_partition(history_dir, year, matches, ids)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("stage", "write", "verify"), required=True)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--source-dir", type=Path)
    p.add_argument("--before-dir", type=Path)
    p.add_argument("--stage-file", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "stage":
        if args.source_dir is None:
            p.error("--source-dir required for stage")
        staged, counts, sources = stage(_load(args.history_dir), args.source_dir)
        with (args.out_dir / "stage.jsonl").open("w", encoding="utf-8") as fh:
            for row in staged:
                fh.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        report = {"schema": 1, "mode": "stage", "counts": counts,
                  "source_commit": SOURCE_REVISION, "source_sha256": sources,
                  "changed_years": sorted({r["utc_year"] for r in staged}),
                  "production_mutated": False, "provider_requests": 0}
    elif args.mode == "write":
        if not args.stage_file or not args.source_dir:
            p.error("--stage-file and --source-dir required for write")
        staged = [json.loads(x) for x in args.stage_file.read_text().splitlines() if x.strip()]
        matches = _load(args.history_dir)
        years = write_local(matches, staged, args.source_dir)
        write_exact(args.history_dir, matches, staged)
        report = {"schema": 1, "mode": "write", "updated": len(staged),
                  "new_stat_values": sum(len(x["additions"]) for x in staged),
                  "changed_years": years, "production_mutated": False, "provider_requests": 0}
    else:
        if not args.before_dir or not args.stage_file:
            p.error("--before-dir and --stage-file required for verify")
        staged = [json.loads(x) for x in args.stage_file.read_text().splitlines() if x.strip()]
        report = verify_readback(_load(args.before_dir), _load(args.history_dir), staged)
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
