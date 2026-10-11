"""Add-only local 2024 WTA score patch with complete partition reread.

Never uploads canonical data; protected workflow owns global lock, backup,
current baseline compare-and-swap, remote publication and independent readback.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from numbers import Integral

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest
from stage_txe_wta2024_scores import FIELD_NAMES, SOURCE_SHA, YEAR, TOUR, sha256


def read_stage(path, report_path, before_sha):
    report = json.loads(Path(report_path).read_text())
    if (report.get("schema") != 1 or report.get("status") != "read_only_score_delta"
            or report.get("cdb_sha256") != before_sha
            or report.get("source_sha256") != SOURCE_SHA or report.get("year") != YEAR
            or report.get("stage_sha256") != sha256(path)
            or report.get("production_mutated") is not False
            or report.get("model_trained") is not False):
        raise ValueError("Stale/unverified WTA 2024 stage")
    items = [json.loads(row) for row in Path(path).read_text().splitlines() if row.strip()]
    if (len(items) != report.get("counts", {}).get("staged_matches", 0)
            or sum(len(r.get("additions", {})) for r in items)
            != report.get("counts", {}).get("staged_fields", 0)):
        raise ValueError("Score stage cardinality changed")
    used = set()
    for r in items:
        values = r.get("additions")
        match_id = str(r.get("match_id") or "")
        if (not match_id or match_id in used or r.get("schema") != 1
                or r.get("source") != f"tennisexplorer_{TOUR}{YEAR}_complete_match_results"
                or r.get("source_sha256") != SOURCE_SHA or r.get("cdb_sha256") != before_sha
                or r.get("year") != YEAR or not isinstance(values, dict) or not values
                or not set(values).issubset(FIELD_NAMES)
                or r.get("expected_original_null_fields") != sorted(values)
                or r.get("model_eligibility") != "historical_postmatch_only"
                or r.get("available_at") is not None
                or r.get("source_player_anchor_status") != "two_unique_fullname_attested_player_slugs"
                or len(r.get("source_player_slugs", [])) != 2
                or not isinstance(r.get("expected_identity"), dict)
                or r["expected_identity"].get("match_id") != match_id):
            raise ValueError("Invalid source stage claim")
        for k, v in values.items():
            if isinstance(v, bool) or not isinstance(v, Integral) or not 0 <= v <= 70:
                raise ValueError("Invalid historical result statistic: " + k)
        used.add(match_id)
    return items, report


def frame_from(directory):
    directory = Path(directory)
    file = directory / f"history-{YEAR}.parquet"
    m = load_manifest(directory).get("years", {}).get(str(YEAR)) or {}
    if m.get("asset") != file.name or m.get("sha256") != sha256(file):
        raise ValueError("Canonical year source/manifest mismatch")
    df = pd.read_parquet(file)
    if len(df) != m.get("rows") or df.match_id.astype(str).duplicated().any():
        raise ValueError("Changed canonical row cardinality/identity")
    return df, m


def patch(df, entries):
    original = df.copy(deep=True)
    ids = dict(zip(df.match_id.astype(str), df.index))
    changed = {}
    for r in entries:
        mid = r["match_id"]
        if mid not in ids:
            raise ValueError("Canonical match absent")
        ix = ids[mid]
        before = df.loc[ix]
        for key, val in r["expected_identity"].items():
            if key not in df.columns or str(before[key]) != val:
                raise ValueError("Staged identity changed: " + mid + "/" + key)
        stats = json.loads(before["stats_json"])
        if not isinstance(stats, dict):
            raise ValueError("Stats JSON malformed")
        stats = dict(stats)
        for key, val in r["additions"].items():
            if key in stats and stats[key] is not None:
                raise ValueError("Forbidden overwrite of existing " + key)
            stats[key] = val
        original.at[ix, "stats_json"] = json.dumps(
            stats, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        )
        changed[mid] = r["additions"]
    nonstats = [x for x in df.columns if x != "stats_json"]
    pd.testing.assert_frame_equal(original[nonstats], df[nonstats])
    keep = ~df.index.isin([ids[x] for x in changed])
    pd.testing.assert_series_equal(df.loc[keep, "stats_json"], original.loc[keep, "stats_json"])
    return original, changed


def replay(mode, before_dir, after_dir, stage_path, report_path):
    before, meta = frame_from(before_dir)
    stage, _ = read_stage(stage_path, report_path, meta["sha256"])
    expected, delta = patch(before, stage)
    dest = Path(after_dir)
    path = dest / f"history-{YEAR}.parquet"
    if mode == "write":
        if not delta or Path(before_dir).resolve() == dest.resolve():
            raise ValueError("No-op or in-place writer forbidden")
        dest.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        try:
            expected.to_parquet(temp, engine="pyarrow", compression="zstd", index=False)
            pd.testing.assert_frame_equal(pd.read_parquet(temp), expected)
            temp.replace(path)
            update_year_manifest(dest, YEAR, {"sha256": sha256(path), "rows": len(expected),
                                               "bytes": path.stat().st_size})
        finally:
            if temp.exists():
                temp.unlink()
    if mode == "verify":
        actual, _ = frame_from(dest)
        pd.testing.assert_frame_equal(actual, expected)
    return {"schema": 1, "status": "verified" if mode == "verify" else "verified_" + mode,
            "changed_matches": len(delta), "added_values": sum(len(x) for x in delta.values()),
            "existing_values_overwritten": 0, "canonical_rows_checked": len(before),
            "year": YEAR, "before_sha256": meta["sha256"],
            "after_sha256": sha256(path) if mode != "dry-run" else None,
            "source_stage_sha256": sha256(stage_path), "production_mutated": False,
            "model_trained": False, "model_promoted": False, "provider_api_requests": 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", required=True, choices=("dry-run", "write", "verify"))
    for name in ("before_dir", "after_dir", "stage_file", "stage_report", "out"):
        p.add_argument("--" + name.replace("_", "-"), required=True, type=Path)
    args = p.parse_args()
    outcome = replay(args.mode, args.before_dir, args.after_dir, args.stage_file, args.stage_report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(outcome, sort_keys=True, indent=2) + "\n")
    print(json.dumps(outcome, sort_keys=True))


if __name__ == "__main__":
    main()
