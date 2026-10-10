"""One-year exact-cell Wimbledon 2023 add-only CDB writer and independent readback.

No remote writes: workflow owns lock, immutable backup, release publication and audit.
Source observation contract must be freshly rebuilt against checksum-pinned CDB.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest
from tbt.data.offline_odds import norm_text
from audit_wimbledon_2023_cdb_stage import SOURCE_SHA, SIDECAR_SHA

YEAR = 2023
ALLOWED = {"p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults"}
PROVEN_SOURCE = "figshare_wimbledon_2023_momentum"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_stage(path, report):
    entries = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if report.get("status") != "read_only_classified" or report.get("production_mutated") is not False:
        raise ValueError("Unverified source stage report")
    if report.get("write_authorized") is not False or report.get("model_promoted") is not False:
        raise ValueError("Unexpected source audit permissions")
    if report.get("source_sha256") != SOURCE_SHA or report.get("sidecar_sha256") != SIDECAR_SHA:
        raise ValueError("Source bytes changed since audit")
    if len(entries) != 20 or report.get("observation_rows") != 20:
        raise ValueError("Incomplete Wimbledon pilot stage")
    if int(report.get("counts", {}).get("linked_matches_compared", -1)) != 5:
        raise ValueError("Inadequate canonical links")
    if int(report.get("counts", {}).get("tape_complete_matches", -1)) != 5:
        raise ValueError("Unproven full-match point tapes")
    if (int(report["counts"].get("READY_MISSING", -1)) != 12
            or int(report["counts"].get("ALREADY_PRESENT", -1)) != 8
            or int(report["counts"].get("CONFLICT", 0)) != 0
            or int(report["counts"].get("UNRESOLVED", 0)) != 0):
        raise ValueError("Pilot no longer agrees with positively verified 12-field stage")
    keys = [(str(v.get("canonical_match_id")), str(v.get("field"))) for v in entries]
    if len(set(keys)) != 20 or len({x[0] for x in keys}) != 5:
        raise ValueError("Duplicate/ambiguous source-cell identity")
    return entries


def _rankless_count(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Invalid integer count")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite count")
    numeric = float(value)
    if not numeric.is_integer() or numeric < 0 or numeric > 200:
        raise ValueError("Unexpected source count")
    return int(numeric)


def patch(frame, stage, cdb_sha):
    required = ("match_id", "tour", "scheduled_at", "tournament",
                "player1_name", "player2_name", "player1_id", "player2_id", "stats_json")
    if any(col not in frame.columns for col in required):
        raise ValueError("Canonical schema lacks match identity")
    ids = frame["match_id"].astype(str)
    if ids.duplicated().any() or (ids == "").any():
        raise ValueError("Duplicate/empty canonical match ID")
    by_id = dict(zip(ids, frame.index))
    out = frame.copy(deep=True)
    delta = {}
    all_ready = set()
    for obs in stage:
        mid = str(obs.get("canonical_match_id") or "")
        field = obs.get("field")
        if mid not in by_id or field not in ALLOWED:
            raise ValueError("Unexpected canonical identity or statistic")
        if obs.get("contract_version") != "1.0.0" or obs.get("source_id") != PROVEN_SOURCE:
            raise ValueError("Untrusted observation version/family")
        version = obs.get("source_version") or {}
        provenance = obs.get("provenance") or {}
        validation = obs.get("validation") or {}
        orientation = obs.get("player_orientation") or {}
        original = obs.get("source_identity") or {}
        evidence = obs.get("match_evidence") or {}
        if (version.get("content_sha256") != SOURCE_SHA or provenance.get("raw_content_sha256") != SOURCE_SHA
            or not str(provenance.get("license_basis", "")).startswith("CC BY 4.0")
            or validation.get("validated_against_cdb_sha256") != cdb_sha
            or evidence.get("ambiguity_candidates") != 1
            or obs.get("unit") != "count" or obs.get("scope") != "whole_match"
            or obs.get("available_at") is not None or obs.get("model_eligibility") not in
            ("postmatch_only_for_future_matches", "research_only")):
            raise ValueError("Source provenance or point-in-time scope unverified")
        ix = by_id[mid]
        row = frame.loc[ix]
        time = pd.Timestamp(row["scheduled_at"])
        if time.tzinfo is None or time.tz_convert("UTC").year != YEAR:
            raise ValueError("Canonical match UTC year mismatch")
        if str(row["tour"]).lower() != "wta" or "wimbledon" not in norm_text(row["tournament"]):
            raise ValueError("Canonical event/tour mismatch")
        left, right = norm_text(row["player1_name"]), norm_text(row["player2_name"])
        source_left = norm_text(original.get("original_player1"))
        source_right = norm_text(original.get("original_player2"))
        is_swapped = (source_left, source_right) == (right, left)
        same = (source_left, source_right) == (left, right)
        if not (same or is_swapped) or orientation.get("swapped") is not is_swapped:
            raise ValueError("Source/canonical order changed")
        if orientation.get("relation") != ("reversed" if is_swapped else "same"):
            raise ValueError("Incorrect source side relation")
        if original.get("tour") != "WTA":
            raise ValueError("Source tour not WTA")
        side = 1 if field.startswith("p1_") else 2
        name = str(row["player1_name"] if side == 1 else row["player2_name"])
        if norm_text(orientation.get("canonical_subject")) != norm_text(name):
            raise ValueError("Canonical player subject mismatch")
        raw = row["stats_json"]
        if not isinstance(raw, str):
            raise ValueError("Corrupt canonical stats cell")
        stats = json.loads(raw)
        if not isinstance(stats, dict):
            raise ValueError("Non-object canonical stats")
        existing = stats.get(field)
        observed = _rankless_count(obs.get("value"))
        state = validation.get("state")
        if state == "READY_MISSING":
            if (existing is not None or validation.get("expected_original_value") is not None
                or obs.get("import_eligibility") != "candidate_after_package_review"):
                raise ValueError("Canonical source cell no longer missing")
            ready = (mid, field)
            if ready in all_ready:
                raise ValueError("Repeated candidate cell")
            all_ready.add(ready)
            delta.setdefault(mid, {})[field] = observed
            stats[field] = observed
            out.at[ix, "stats_json"] = json.dumps(stats, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"), allow_nan=False)
        elif state == "ALREADY_PRESENT":
            if _rankless_count(existing) != observed or validation.get("expected_original_value") != existing:
                raise ValueError("Previously populated cell differs")
        else:
            raise ValueError("Import forbids unresolved/conflicting cells")
    if len(all_ready) != 12 or len(delta) != 3:
        raise ValueError("Expected three Wimbledon matches / twelve new values")
    other_columns = list(frame.columns.drop("stats_json"))
    pd.testing.assert_frame_equal(frame[other_columns], out[other_columns], check_dtype=True)
    modified_indices = {by_id[x] for x in delta}
    untouched = ~frame.index.isin(modified_indices)
    pd.testing.assert_series_equal(frame.loc[untouched, "stats_json"],
                                   out.loc[untouched, "stats_json"])
    for mid in delta:
        i = by_id[mid]
        before = json.loads(frame.at[i, "stats_json"])
        after = json.loads(out.at[i, "stats_json"])
        expected = dict(before)
        expected.update(delta[mid])
        if after != expected:
            raise ValueError("Unplanned stats_json changes")
    return out, {"changed_matches": len(delta), "added_values": len(all_ready),
                 "existing_values_overwritten": 0, "canonical_rows": len(frame)}


def run(mode: str, before_dir: Path, after_dir: Path, stage_file: Path, stage_report: Path):
    before_path = before_dir / "history-2023.parquet"
    before_meta = load_manifest(before_dir).get("years", {}).get("2023", {})
    if before_meta.get("asset") != before_path.name or before_meta.get("sha256") != sha256(before_path):
        raise ValueError("CDB history-2023 Parquet does not match manifest")
    stage_summary = json.loads(stage_report.read_text())
    if stage_summary.get("cdb_partition_sha256") != before_meta["sha256"]:
        raise ValueError("Stale stage / CDB mismatch")
    rows = read_stage(stage_file, stage_summary)
    frame = pd.read_parquet(before_path, engine="pyarrow")
    if before_meta.get("rows") != len(frame):
        raise ValueError("Stale year row count")
    expected, counts = patch(frame, rows, before_meta["sha256"])
    if mode == "write":
        after_dir.mkdir(parents=True, exist_ok=True)
        dest = after_dir / before_path.name
        if dest.resolve() == before_path.resolve():
            raise ValueError("In-place CDB changes prohibited")
        temp = dest.with_name(dest.name + ".local.tmp")
        try:
            expected.to_parquet(temp, compression="zstd", engine="pyarrow", index=False)
            persisted = pd.read_parquet(temp, engine="pyarrow")
            pd.testing.assert_frame_equal(persisted, expected, check_dtype=True)
            temp.replace(dest)
        finally:
            if temp.exists():
                temp.unlink()
        update_year_manifest(after_dir, YEAR, {
            "sha256": sha256(dest), "bytes": dest.stat().st_size,
            "rows": len(expected),
        })
    elif mode == "verify":
        after_file = after_dir / before_path.name
        if load_manifest(after_dir).get("years", {}).get("2023", {}).get("sha256") != sha256(after_file):
            raise ValueError("Persisted year manifest not updated")
        actual = pd.read_parquet(after_file, engine="pyarrow")
        pd.testing.assert_frame_equal(actual, expected, check_dtype=True)
    elif mode != "dry-run":
        raise ValueError("Unrecognized import mode")
    return {"schema": 1, "status": "verified" if mode == "verify" else "verified_" + mode,
            "mode": mode, "year": YEAR, **counts, "before_sha256": before_meta["sha256"],
            "after_sha256": (sha256(after_dir / before_path.name) if mode != "dry-run" else None),
            "stage_sha256": sha256(stage_file), "stage_report_sha256": sha256(stage_report),
            "production_mutated": False, "model_promoted": False, "provider_api_requests": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("dry-run", "write", "verify"))
    for field in ("before_dir", "after_dir", "stage_file", "stage_report", "report"):
        parser.add_argument("--" + field.replace("_", "-"), required=True, type=Path)
    args = parser.parse_args()
    result = run(args.mode, args.before_dir, args.after_dir, args.stage_file, args.stage_report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
