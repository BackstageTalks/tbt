"""Fail-closed null-only WTA 2021-2024 historical ranking publisher (local bytes only).

A workflow owns remote lock, immutable backup, fresh CAS publication and readback.
Verified canonical WTA rows MUST be byte-semantically identical between the
verified source audit year and the current canonical year partition.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest

YEAR = None
FIELDS = ("player1_rank", "player2_rank")
SOURCE_TAG = SOURCE_RUN = SOURCE_OLD_YEAR_SHA = STAGE_SHA = REPORT_SHA = None
PROVENANCE_KEY = "_tbt_wta_rank_provenance"
EXPECTED_MATCHES = EXPECTED_VALUES = EXPECTED_WTA_ROWS = None


def configure(request):
    """Fail closed on independent audited stage pins and all required safety gates."""
    global YEAR, SOURCE_TAG, SOURCE_RUN, SOURCE_OLD_YEAR_SHA
    global STAGE_SHA, REPORT_SHA, EXPECTED_MATCHES, EXPECTED_VALUES, EXPECTED_WTA_ROWS
    if request.get("schema") != 1 or type(request.get("year")) is not int:
        raise ValueError("Invalid request schema/year")
    year = request["year"]
    if year not in (2021, 2022, 2023, 2024):
        raise ValueError("Only WTA 2021-2024 with individual pre-audited source pins is supported")
    run = str(request.get("source_audit_run") or "")
    tag = str(request.get("source_tag") or "")
    if not run.isdecimal() or tag != f"blinq-wta{year}-id-ranked-null-audit-{run}":
        raise ValueError("Audit source tag/run mismatch")
    import re
    for key in ("source_original_year_sha256", "current_year_sha256",
                "source_stage_sha256", "source_report_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(request.get(key) or "")):
            raise ValueError(f"Invalid pinned hash: {key}")
    if request["source_original_year_sha256"] != request["current_year_sha256"]:
        raise ValueError("Year changed since source audit; re-audit before import")
    m, v = request.get("expected_matches"), request.get("expected_added_values")
    w = request.get("expected_wta_rows")
    if (type(m) is not int or type(v) is not int or type(w) is not int
            or m < 1 or v != m * 2 or w < m):
        raise ValueError("Invalid cardinality pins; only complete two-null ranks")
    for key in ("require_global_lock", "require_immutable_backup", "require_full_year_readback",
                "require_whole_wta_unchanged", "strict_canonical_player_ids", "exact_null_only"):
        if request.get(key) is not True:
            raise ValueError(f"Mandatory writer gate not enabled: {key}")
    for key in ("overwrite_existing_rank", "train_model", "promote_model", "create_cron"):
        if request.get(key) is not False:
            raise ValueError(f"Forbidden mutation requested: {key}")
    if request.get("provider_api_requests") != 0 or request.get("mode") not in ("write", "dry-run"):
        raise ValueError("Unapproved external effect or import mode")
    YEAR, SOURCE_TAG, SOURCE_RUN = year, tag, run
    SOURCE_OLD_YEAR_SHA = request["source_original_year_sha256"]
    STAGE_SHA, REPORT_SHA = request["source_stage_sha256"], request["source_report_sha256"]
    EXPECTED_MATCHES, EXPECTED_VALUES, EXPECTED_WTA_ROWS = m, v, w




def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def is_null(value):
    if value is None:
        return True
    result = pd.isna(value)
    if not isinstance(result, (bool, type(pd.NA))) and not hasattr(result, "item"):
        raise ValueError("Unexpected canonical rank type")
    if result is pd.NA:
        return True
    return bool(result)


def rank_int(value):
    if isinstance(value, bool) or isinstance(value, (dict, list)) or value is None:
        raise ValueError("Rank value not numeric")
    text = str(value)
    if not text.isdecimal():
        raise ValueError("Rank must be positive integer, not a rate or NaN")
    result = int(text)
    if not 1 <= result <= 10000:
        raise ValueError("WTA rank outside audit boundary")
    return result


def read_year(root):
    root = Path(root)
    manifest = load_manifest(root)
    entry = (manifest.get("years") or {}).get(str(YEAR)) or {}
    path = root / f"history-{YEAR}.parquet"
    hash_ = digest(path)
    if entry.get("asset") != path.name or entry.get("sha256") != hash_:
        raise ValueError("Canonical partition/manifest checksum mismatch")
    frame = pd.read_parquet(path)
    if len(frame) != int(entry.get("rows", -1)):
        raise ValueError("Canonical year row count mismatch")
    required = {"match_id", "tour", "scheduled_at", "player1_id", "player2_id",
                "player1_rank", "player2_rank", "provider_context_json"}
    if not required.issubset(frame.columns):
        raise ValueError("Canonical field schema changed")
    ids = frame["match_id"].astype(str)
    if ids.duplicated().any() or (ids == "").any():
        raise ValueError("Duplicate/missing canonical match identity")
    return frame, hash_


def verify_wta_unchanged(original, current):
    """Fail if ATP or any concurrent writer changed ANY WTA canonical cell."""
    if len(original) != len(current):
        raise ValueError("Canonical match row count changed since WTA audit")
    if not original["match_id"].astype(str).equals(current["match_id"].astype(str)):
        raise ValueError("Canonical match order or ID changed")
    orig_wta = original.loc[original["tour"].astype(str).str.lower() == "wta"]
    cur_wta = current.loc[current["tour"].astype(str).str.lower() == "wta"]
    if len(orig_wta) != EXPECTED_WTA_ROWS or len(cur_wta) != EXPECTED_WTA_ROWS:
        raise ValueError("Unexpected source WTA cohort")
    pd.testing.assert_frame_equal(orig_wta.reset_index(drop=True),
                                  cur_wta.reset_index(drop=True), check_dtype=True)
    return len(orig_wta)


def source_stage(stage_path, report_path):
    if digest(stage_path) != STAGE_SHA or digest(report_path) != REPORT_SHA:
        raise ValueError("Original audited WTA source stage/report hash mismatch")
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    c = report.get("counts") or {}
    if (report.get("schema") != 1 or report.get("status") != f"READ_ONLY_WTA{YEAR}_ID_RANK_CDB_GAPS"
            or report.get("canonical_year_sha256") != SOURCE_OLD_YEAR_SHA
            or report.get("stage_sha256") != STAGE_SHA
            or c.get("candidate_matches") != EXPECTED_MATCHES
            or c.get("candidate_rank_cells") != EXPECTED_VALUES
            or c.get("wta_matches") != EXPECTED_WTA_ROWS
            or report.get("canonical_mutated") is not False
            or report.get("provider_api_requests") != 0
            or report.get("model_promoted") is not False):
        raise ValueError("Unrecognized/unsafe WTA source audit report")
    rows = []
    seen = set()
    id_to_source, source_to_id = {}, {}
    with gzip.open(stage_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            mid = str(row.get("canonical_match_id") or "")
            if (row.get("schema") != 1 or not mid or mid in seen
                    or row.get("status") != "CANDIDATE_NOT_WRITER_APPROVED"
                    or row.get("canonical_year") != YEAR
                    or row.get("canonical_year_sha256") != SOURCE_OLD_YEAR_SHA
                    or row.get("temporal_policy") != "source_before_match_1_to_14_days"
                    or set(row.get("add_only_null_fields") or ()) != set(FIELDS)
                    or row.get("expected_player1_rank") is not None
                    or row.get("expected_player2_rank") is not None):
                raise ValueError("Unsafe/malformed staged WTA match or field set")
            seen.add(mid)
            source_ids = []
            for index in (1, 2):
                cid = str(row.get(f"player{index}_id") or "")
                sid = str(row.get(f"source_player{index}_id") or "")
                if not cid or not sid:
                    raise ValueError("Unattested WTA source identity")
                if cid in id_to_source and id_to_source[cid] != sid:
                    raise ValueError("One canonical player maps to several source identities")
                if sid in source_to_id and source_to_id[sid] != cid:
                    raise ValueError("Source identity reused across canonical players")
                id_to_source[cid] = sid
                source_to_id[sid] = cid
                source_ids.append(sid)
            if source_ids[0] == source_ids[1]:
                raise ValueError("Match sides share a WTA source player")
            rows.append(row)
    if len(rows) != EXPECTED_MATCHES:
        raise ValueError("WTA stage cardinality does not match audit")
    return rows, report


def apply(before, rows, expected_matches=None, expected_values=None):
    expected_matches = EXPECTED_MATCHES if expected_matches is None else expected_matches
    expected_values = EXPECTED_VALUES if expected_values is None else expected_values
    out = before.copy(deep=True)
    lookup = dict(zip(before["match_id"].astype(str), before.index))
    counter = Counter()
    changed = set()
    for row in rows:
        mid = str(row["canonical_match_id"])
        if mid not in lookup:
            raise ValueError("WTA staged match not in current canonical year")
        index = lookup[mid]
        original = before.loc[index]
        stamp = pd.Timestamp(row["scheduled_at"])
        real = pd.Timestamp(original["scheduled_at"])
        if stamp.tzinfo is None or real.tzinfo is None:
            raise ValueError("Naive match timestamp")
        stamp, real = stamp.tz_convert("UTC"), real.tz_convert("UTC")
        if (stamp != real or stamp.year != YEAR
                or str(original["tour"]).lower() != "wta"
                or any(str(original[f"player{side}_id"]) != str(row[f"player{side}_id"])
                       for side in (1, 2))):
            raise ValueError("Canonical WTA player identity/time mismatch")
        if row["canonical_match_id"] in changed:
            raise ValueError("Repeated WTA stage match ID")
        values = row["add_only_null_fields"]
        for field in FIELDS:
            if not is_null(original[field]):
                raise ValueError("WTA preexisting rank must never be overwritten")
            rank_int(values[field])
        weeks = []
        for side in (1, 2):
            week = date.fromisoformat(str(row[f"source_week_p{side}"]))
            if not 1 <= (stamp.date() - week).days <= 14:
                raise ValueError("Source rank was not strictly prior/within 14 days")
            weeks.append(week.isoformat())
        raw_context = original["provider_context_json"]
        if not isinstance(raw_context, str):
            raise ValueError("Provider provenance context not structured JSON")
        context = json.loads(raw_context)
        if not isinstance(context, dict) or PROVENANCE_KEY in context:
            raise ValueError("WTA rank provenance preexists/conflicts")
        context[PROVENANCE_KEY] = {
            "source": "sha256_verified_historical_wta_ranking",
            "audit_run_id": SOURCE_RUN,
            "audit_release_tag": SOURCE_TAG,
            "canonical_player_identity_link": "unique_id_to_sackmann_id",
            "source_player1_id": str(row["source_player1_id"]),
            "source_player2_id": str(row["source_player2_id"]),
            "as_of_player1": weeks[0],
            "as_of_player2": weeks[1],
            "point_in_time": True,
            "model_use": "disabled_until_explicit_training",
        }
        out.at[index, "provider_context_json"] = json.dumps(
            context, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        for field in FIELDS:
            out.at[index, field] = rank_int(values[field])
            counter[field + "_filled"] += 1
        counter["updated_matches"] += 1
        changed.add(mid)
    if counter["updated_matches"] != expected_matches or sum(counter[f + "_filled"] for f in FIELDS) != expected_values:
        raise ValueError("Unexpected WTA rank delta; cannot publish")
    other_cols = [c for c in before.columns if c not in {*FIELDS, "provider_context_json"}]
    pd.testing.assert_frame_equal(before[other_cols], out[other_cols], check_dtype=True)
    untouched = ~before["match_id"].astype(str).isin(changed)
    pd.testing.assert_frame_equal(before.loc[untouched], out.loc[untouched], check_dtype=True)
    return out, dict(counter)


def run(mode, current_dir, source_old_dir, stage_file, stage_report, output_dir):
    if mode not in ("dry-run", "write", "verify"):
        raise ValueError("Unsupported WTA rank mode")
    current_dir, source_old_dir, output_dir = map(Path, (current_dir, source_old_dir, output_dir))
    original, original_sha = read_year(source_old_dir)
    current, current_sha = read_year(current_dir)
    if original_sha != SOURCE_OLD_YEAR_SHA:
        raise ValueError("WTA stage original partition is not from immutable prior audit")
    matched_wta = verify_wta_unchanged(original, current)
    rows, report = source_stage(stage_file, stage_report)
    expected, counts = apply(current, rows)
    if mode == "write":
        if current_dir.resolve() == output_dir.resolve() or source_old_dir.resolve() == output_dir.resolve():
            raise ValueError("In-place overwrite forbidden")
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(current_dir / "history_manifest.json", output_dir / "history_manifest.json")
        target = output_dir / f"history-{YEAR}.parquet"
        temporary = target.with_suffix(".parquet.tmp")
        try:
            expected.to_parquet(temporary, engine="pyarrow", compression="zstd", index=False)
            pd.testing.assert_frame_equal(pd.read_parquet(temporary), expected, check_dtype=True)
            temporary.replace(target)
            update_year_manifest(output_dir, YEAR, {
                "sha256": digest(target), "bytes": target.stat().st_size,
                "rows": len(expected)
            }, extra={"coverage_status": f"WTA_{YEAR}_exact_ID_prior_week_rank_add_only"})
        finally:
            temporary.unlink(missing_ok=True)
    elif mode == "verify":
        after, _ = read_year(output_dir)
        pd.testing.assert_frame_equal(after, expected, check_dtype=True)
    return {
        "schema": 1,
        "status": "verified_full_year" if mode == "verify" else "validated_" + mode,
        "mode": mode,
        "matches_checked": len(current), "wta_rows_cross_release_checked": matched_wta,
        "counts": counts,
        "before_sha256": current_sha, "audited_pre_atp_sha256": original_sha,
        "after_sha256": digest(output_dir / f"history-{YEAR}.parquet") if mode != "dry-run" else None,
        "stage_sha256": STAGE_SHA, "source_report_sha256": REPORT_SHA,
        "existing_nonnull_cells_overwritten": 0, "production_modified_by_script": False,
        "provider_api_requests": 0, "model_training": False, "model_promotion": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("dry-run", "write", "verify"), required=True)
    for arg in ("current_dir", "source_old_dir", "stage_file", "stage_report", "output_dir", "out"):
        p.add_argument("--" + arg.replace("_", "-"), type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    a = p.parse_args()
    request = json.loads(a.request.read_text(encoding="utf-8"))
    configure(request)
    if a.mode != request["mode"] and a.mode != "verify" and a.mode != "dry-run":
        raise ValueError("Write mode not authorized by pinned request")
    result = run(a.mode, a.current_dir, a.source_old_dir,
                 a.stage_file, a.stage_report, a.output_dir)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("WTA_OLDER_RANK_REBASED", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
