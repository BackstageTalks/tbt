"""Exact-cell local-only canonical WTA PIT ranking writer / full readback.

Only intended 2026 rank columns and provenance JSON cells may change.
Remote CDB writes are exclusively owned by the separately gated workflow.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest

YEAR = 2026
RANK_SOURCE = "wta_official_2026_weekly_verified_independent_crosswalk"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rank(value):
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return None
    if isinstance(value, bool) or not str(value).strip():
        raise ValueError("Invalid stored rank")
    numeric = float(value)
    if not numeric.is_integer() or numeric <= 0 or numeric > 100000:
        raise ValueError("Noninteger or unreasonable rank")
    return int(numeric)


def _utc(value):
    dt = pd.Timestamp(value)
    if dt.tzinfo is None:
        raise ValueError("Naive canonical match time")
    return dt.tz_convert("UTC")


def _read_stage(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [str(r.get("match_id") or "") for r in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate proposed canonical ID")
    return rows


def _patch(frame: pd.DataFrame, stage: list[dict]):
    required = ("match_id", "tour", "scheduled_at", "player1_id", "player2_id",
                "player1_name", "player2_name", "player1_rank", "player2_rank",
                "provider_context_json")
    if any(k not in frame.columns for k in required):
        raise ValueError("Canonical Parquet schema missing required identity fields")
    by_id = frame["match_id"].astype(str)
    if by_id.duplicated().any():
        raise ValueError("Duplicate canonical match IDs")
    indices = dict(zip(by_id, frame.index))
    out = frame.copy(deep=True)
    rank_fields = ("player1_rank", "player2_rank")
    updated = 0
    new_fields = 0
    for row in stage:
        mid = str(row.get("match_id") or "")
        if row.get("schema") != 1 or row.get("candidate_only") is not True or row.get("tour") != "wta":
            raise ValueError("Unapproved proposed ranking stage")
        if mid not in indices:
            raise ValueError("Canonical match identity missing")
        idx = indices[mid]
        actual = frame.loc[idx]
        if str(actual["tour"]).lower() != "wta":
            raise ValueError("Canonical tour mismatch")
        for field in ("player1_id", "player2_id", "player1_name", "player2_name"):
            if str(actual[field]) != str(row.get(field) or ""):
                raise ValueError(f"Canonical identity changed: {mid} / {field}")
        for field in ("sackmann_player1_id", "sackmann_player2_id"):
            source_pid = str(row.get(field) or "").strip()
            if not source_pid.isdigit() or int(source_pid) < 1:
                raise ValueError("Unverified numeric source player identity")
        match_date = _utc(actual["scheduled_at"])
        if int(match_date.year) != YEAR or match_date.isoformat() != _utc(row.get("scheduled_at")).isoformat():
            raise ValueError("Canonical match timestamp changed")
        when = date.fromisoformat(str(row.get("ranking_as_of") or ""))
        gap = (match_date.date() - when).days
        if not 1 <= gap <= 8 or not date(2026, 6, 15) <= when <= date(2026, 9, 21):
            raise ValueError("Rank snapshot not established prior to match")
        old = [_rank(actual[col]) for col in rank_fields]
        if row.get("canonical") != old:
            raise ValueError("Existing rank differs from immutable stage")
        proposed = row.get("proposed")
        if not isinstance(proposed, list) or len(proposed) != 2:
            raise ValueError("Missing exact rank proposal")
        new = [_rank(rank) for rank in proposed]
        if any(x is None for x in new):
            raise ValueError("Invalid missing source ranking")
        if all(value is not None for value in old):
            raise ValueError("Stale stage: canonical ranks already complete")
        if any(value is not None and value != candidate for value, candidate in zip(old, new)):
            raise ValueError("Conflicting populated canonical rank")
        raw = actual["provider_context_json"]
        if not isinstance(raw, str):
            raise ValueError("Invalid provenance JSON cell")
        context = json.loads(raw)
        if not isinstance(context, dict):
            raise ValueError("Invalid provenance JSON object")
        previous_provenance = context.get("_tbt_rank_provenance")
        if previous_provenance is not None:
            if not isinstance(previous_provenance, dict) or previous_provenance.get("point_in_time") is not True:
                raise ValueError("Conflicting rank provenance")
            if not previous_provenance.get("source") or not previous_provenance.get("as_of"):
                raise ValueError("Incomplete prior rank provenance")
            asof = _utc(previous_provenance["as_of"])
            if asof > match_date:
                raise ValueError("Future prior rank provenance")
        else:
            context["_tbt_rank_provenance"] = {
                "point_in_time": True, "source": RANK_SOURCE,
                "as_of": when.isoformat() + "T00:00:00+00:00",
            }
            out.at[idx, "provider_context_json"] = json.dumps(
                context, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
        for j, field in enumerate(rank_fields):
            if old[j] is None:
                out.at[idx, field] = new[j]
                new_fields += 1
        updated += 1

    # Check every physical logical cell, not just the staged match count.
    other = [col for col in frame.columns if col not in (*rank_fields, "provider_context_json")]
    pd.testing.assert_frame_equal(frame[other], out[other], check_dtype=True)
    candidate_indices = {indices[str(row["match_id"])] for row in stage}
    rest = ~frame.index.isin(candidate_indices)
    pd.testing.assert_frame_equal(
        frame.loc[rest], out.loc[rest], check_dtype=True
    )
    if new_fields < updated or new_fields > 2 * updated:
        raise ValueError("Unexpected updated ranking cells")
    return out, {"updated": updated, "rank_fields_added": new_fields,
                 "existing_rank_values_overwritten": 0,
                 "canonical_rows": len(frame), "changed_years": [YEAR] if updated else []}


def _source_partition(directory: Path) -> Path:
    source = directory / f"history-{YEAR}.parquet"
    if not source.is_file():
        raise FileNotFoundError(source)
    meta = load_manifest(directory).get("years", {}).get(str(YEAR), {})
    if not isinstance(meta, dict) or int(meta.get("rows", -1)) <= 0:
        raise ValueError("No authoritative year manifest entry")
    if str(meta.get("sha256")) != _sha256(source):
        raise ValueError("Canonical partition checksum differs from history manifest")
    return source


def run(mode: str, before_dir: Path, stage_file: Path, after_dir: Path):
    before_path = _source_partition(before_dir)
    rows = _read_stage(stage_file)
    before = pd.read_parquet(before_path, engine="pyarrow")
    expected, outcome = _patch(before, rows)
    if outcome["canonical_rows"] != len(before):
        raise ValueError("Changed canonical match count")
    if mode == "verify":
        after = pd.read_parquet(after_dir / before_path.name, engine="pyarrow")
        pd.testing.assert_frame_equal(after, expected, check_dtype=True)
        # Independent before/after full partition diff, including all unstaged rows.
        result = {"status": "verified", **outcome}
    elif mode == "write":
        if outcome["updated"]:
            dest = after_dir / before_path.name
            if dest.resolve() == before_path.resolve():
                raise ValueError("Must not mutate authoritative source snapshot in place")
            after_dir.mkdir(parents=True, exist_ok=True)
            dest_temp = dest.with_name(dest.name + ".verified.tmp")
            try:
                expected.to_parquet(dest_temp, compression="zstd", engine="pyarrow", index=False)
                if dest_temp.stat().st_size <= 0:
                    raise ValueError("Empty 2026 partition")
                persisted = pd.read_parquet(dest_temp, engine="pyarrow")
                pd.testing.assert_frame_equal(persisted, expected, check_dtype=True)
                dest_temp.replace(dest)
            finally:
                if dest_temp.exists():
                    dest_temp.unlink()
            update_year_manifest(after_dir, YEAR, {
                "sha256": _sha256(dest), "bytes": dest.stat().st_size,
                "rows": len(expected),
            })
        result = {"status": "verified_local_write", **outcome}
    elif mode == "dry-run":
        result = {"status": "verified_dry_run", **outcome}
    else:
        raise ValueError("Mode must be dry-run, write or verify")
    result.update({"schema": 1, "mode": mode, "api_requests": 0,
                   "production_mutated": False, "model_promoted": False,
                   "local_partitions_written": mode == "write" and outcome["updated"] > 0})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("dry-run", "write", "verify"), required=True)
    p.add_argument("--before-dir", type=Path, required=True)
    p.add_argument("--after-dir", type=Path, required=True)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    result = run(args.mode, args.before_dir, args.stage, args.after_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
