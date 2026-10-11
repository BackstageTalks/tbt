"""Read-only SHA-pinned recovery proof for the five 2023 Wimbledon rows.

Never restore/publish anything: keep all original match identities and any later
2023 rank/score enrichment untouched. The only artifact is aggregate evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from repair_history_data import invalid_reason

REPO = "BackstageTalks/tbt-data"
CURRENT = "tbt-data-v1"
BACKUP = "blinq-wta2023-ranks-prewrite-38129131702-1"
BACKUP_SHA = "f3b94f0aef62bc9a9551e38491d597383cb70f1bf811ee4922bb9ccf5bbb5d89"
TARGET_IDS = frozenset((
    "30a913dc3fa280dbf4838d9d",
    "93e0cf24456ba6f6bb83fe8b",
    "9be0b0ae278ac43da93b6419",
    "5a07b3bb8817fd24d70ececa",
    "d70725c4dace6ab1811b0360",
))
FILES = ("history-2023.parquet", "history_manifest.json", "_tbt_bundle_manifest.json")
IDENTITY = ("match_id", "tour", "scheduled_at", "player1_id", "player2_id", "winner_id")


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True).stdout


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_release(tag, folder):
    """Independently verify release metadata, asset bytes and both manifests."""
    folder.mkdir(parents=True, exist_ok=True)
    meta = json.loads(gh("api", f"repos/{REPO}/releases/tags/{tag}"))
    assets = {item["name"]: item for item in meta["assets"]}
    for name in FILES:
        if name not in assets:
            raise ValueError(f"{tag}: missing {name}")
        item = assets[name]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("digest", ""))):
            raise ValueError(f"{tag}: missing immutable SHA for {name}")
        gh("release", "download", tag, "--repo", REPO,
           "--pattern", name, "--dir", str(folder), "--clobber")
        file = folder / name
        if not file.is_file() or file.stat().st_size != item["size"]:
            raise ValueError(f"{tag}: incomplete {name}")
        if "sha256:" + sha256(file) != item["digest"]:
            raise ValueError(f"{tag}: SHA mismatch for {name}")
    bundle = json.loads((folder / FILES[2]).read_text())
    history = json.loads((folder / FILES[1]).read_text())
    entry = history["years"]["2023"]
    bundle_files = bundle["files"]
    for name in FILES[:2]:
        if bundle_files[name]["sha256"] != sha256(folder / name):
            raise ValueError(f"{tag}: bundle and asset SHA disagreement: {name}")
    if entry["sha256"] != sha256(folder / FILES[0]):
        raise ValueError(f"{tag}: annual manifest SHA disagreement")
    if entry.get("asset", FILES[0]) != FILES[0]:
        raise ValueError(f"{tag}: unexpected annual asset mapping")
    # Asset IDs must not change while downloading a live release.
    refreshed = json.loads(gh("api", f"repos/{REPO}/releases/tags/{tag}"))
    new_assets = {x["name"]: x for x in refreshed["assets"]}
    for name in FILES:
        if name not in new_assets or assets[name]["id"] != new_assets[name]["id"]:
            raise RuntimeError(f"{tag}: release changed during audit")
    return {"sha256": sha256(folder / FILES[0]),
            "manifest_sha256": sha256(folder / FILES[1]),
            "bundle_sha256": sha256(folder / FILES[2]),
            "year_declared_rows": int(entry["rows"])}


def compare_years(original, current, *, target_ids=TARGET_IDS):
    """Only five exact match IDs qualify; no merge or write is possible here."""
    required = set(IDENTITY) | {"player1_name", "player2_name", "tournament", "stats_json"}
    for name, frame in (("backup", original), ("current", current)):
        if not required.issubset(frame.columns):
            raise ValueError(f"{name}: missing canonical fields")
        if frame["match_id"].isna().any() or frame["match_id"].duplicated().any():
            raise ValueError(f"{name}: blank or duplicate match IDs")

    older = original.set_index("match_id", drop=False)
    newer = current.set_index("match_id", drop=False)
    source_ids, current_ids = set(older.index), set(newer.index)
    missing = source_ids - current_ids
    all_target_present_in_backup = target_ids <= source_ids
    missing_target = missing & target_ids
    extra_absent = missing - target_ids
    drift = 0
    for mid in (source_ids & current_ids):
        before, after = older.loc[mid], newer.loc[mid]
        if any(str(before[key]) != str(after[key]) for key in IDENTITY[1:]):
            drift += 1
    good = []
    bad = []
    for mid in sorted(missing_target):
        row = older.loc[mid]
        reason = invalid_reason(row)
        if reason is None:
            good.append(mid)
        else:
            bad.append({"reason": reason})
    ready_to_propose = (
        all_target_present_in_backup
        and len(missing_target) == len(target_ids) == 5
        and not extra_absent
        and not drift
        and len(good) == 5
    )
    return {
        "backup_rows": len(original),
        "current_rows": len(current),
        "shared_rows": len(source_ids & current_ids),
        "current_rows_not_in_backup": len(current_ids - source_ids),
        "backup_rows_not_in_current": len(missing),
        "backup_absent_unrelated_to_five": len(extra_absent),
        "shared_identity_drift": drift,
        "all_five_present_in_backup": all_target_present_in_backup,
        "five_missing_in_current": len(missing_target),
        "five_valid_under_canonical_2023_rule": len(good),
        "five_failed_validation": len(bad),
        "exact_five_can_be_reviewed_for_restoration": ready_to_propose,
    }



def simulate_exact_five_append(backup, current, scratch):
    """Simulate an additive recovery locally, preserving every current field.

    No upload, no production lock, no CDB release mutation. Abort on even one
    changed historical value, schema drift or a failed parquet reread.
    The scratch file is removed whether validation succeeds or fails.
    """
    proof = compare_years(backup, current)
    if not proof["exact_five_can_be_reviewed_for_restoration"]:
        raise ValueError("Five-row recovery must first pass all identity and count gates")
    if list(backup.columns) != list(current.columns):
        raise ValueError("Current vs immutable backup column inventory differs")
    if not backup.dtypes.equals(current.dtypes):
        raise ValueError("Parquet column dtypes changed since immutable source")
    addition = backup.loc[backup["match_id"].isin(TARGET_IDS)].copy()
    if len(addition) != 5:
        raise ValueError("Expected exactly five pinned source rows")
    for _, row in addition.iterrows():
        if invalid_reason(row) is not None:
            raise ValueError("Pinned source row fails canonical quality preflight")

    proposed = pd.concat([current, addition], ignore_index=True)
    if len(proposed) != len(current) + 5 or proposed["match_id"].duplicated().any():
        raise ValueError("Local stage has duplicate or missing IDs")
    if not proposed.dtypes.equals(current.dtypes):
        raise ValueError("Append changed canonical parquet value types")
    local = Path(scratch) / "history-2023-simulation-only.parquet"
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        proposed.to_parquet(local, engine="pyarrow", compression="zstd", index=False)
        reread = pd.read_parquet(local, engine="pyarrow")
        if len(reread) != len(current) + 5:
            raise ValueError("Local reread has wrong row count")
        pd.testing.assert_frame_equal(
            reread.iloc[:len(current)].reset_index(drop=True),
            current.reset_index(drop=True), check_exact=True,
        )
        pd.testing.assert_frame_equal(
            reread.iloc[len(current):].reset_index(drop=True),
            addition.reset_index(drop=True), check_exact=True,
        )
        sha = sha256(local)
        return {
            "status": "LOCAL_APPEND_SIMULATION_VERIFIED_NO_PRODUCTION_WRITE",
            "stage_year": 2023,
            "current_rows_preserved_exact": len(current),
            "five_backup_rows_appended_exact": len(addition),
            "simulated_total_rows": len(reread),
            "current_columns_preserved": len(current.columns),
            "existing_rows_or_cells_overwritten": 0,
            "simulated_parquet_sha256": sha,
            "simulated_parquet_uploaded": False,
            "writer_lease_taken": False,
            "production_cdb_mutated": False,
            "requires_fresh_write_CAS_and_backup": True,
        }
    finally:
        local.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.out / "immutable_backup"
    live = args.out / "current"
    backup_proof = verified_release(BACKUP, source)
    if backup_proof["sha256"] != BACKUP_SHA:
        raise ValueError("Pinned backup 2023 SHA changed")
    current_proof = verified_release(CURRENT, live)
    original = pd.read_parquet(source / FILES[0])
    now = pd.read_parquet(live / FILES[0])
    if len(original) != backup_proof["year_declared_rows"]:
        raise ValueError("Backup row count inconsistent with signed release")
    if len(now) != current_proof["year_declared_rows"]:
        raise ValueError("Current row count inconsistent with signed release")
    local_simulation = simulate_exact_five_append(original, now, args.out / "simulation")
    result = {
        "local_append_simulation": local_simulation,
        "schema": 1,
        "status": "READ_ONLY_WIMBLEDON2023_FIVE_ROW_BACKUP_COMPARISON",
        "private_repo": REPO,
        "backup_release": BACKUP, "backup_proof": backup_proof,
        "current_release": CURRENT, "current_proof": current_proof,
        "counts": compare_years(original, now),
        "write_authorized": False, "production_mutated": False,
        "restoration_executed": False, "provider_requests": 0,
        "model_trained": False, "scheduled_task_created": False,
        "next_gate": "Fresh per-ID CAS and source/PIT rights, preserve every current row and later rank/stat value, single writer, immutable prewrite, independent complete 2023 readback.",
    }
    report = args.out / "aggregate-readonly-report.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("WIMBLEDON2023_BACKUP_READONLY", json.dumps({
        "counts": result["counts"], "write_authorized": False,
        "backup_sha256": backup_proof["sha256"],
        "current_sha256": current_proof["sha256"],
        "simulation": local_simulation,
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
