"""Build/verify an append-only five-row 2023 Parquet against immutable backup.

This module never publishes anything itself. The workflow must enforce a
global CDB writer lease, immutable prewrite backup, CAS, and remote readback.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from audit_wimbledon2023_recovery_readonly import (
    BACKUP_SHA, TARGET_IDS, sha256, compare_years, invalid_reason,
)

def build(backup_path: Path, current_path: Path, target: Path, *, mode: str):
    if sha256(backup_path) != BACKUP_SHA:
        raise ValueError("Immutable source year checksum changed")
    original = pd.read_parquet(backup_path)
    current = pd.read_parquet(current_path)
    proof = compare_years(original, current)
    if mode == "write" and not proof["exact_five_can_be_reviewed_for_restoration"]:
        raise ValueError("Five missing rows are no longer append-eligible")
    if list(original.columns) != list(current.columns) or not original.dtypes.equals(current.dtypes):
        raise ValueError("Canonical schema/dtypes changed since backup")
    five = original.loc[original.match_id.isin(TARGET_IDS)].copy()
    if len(five) != 5 or any(invalid_reason(r) is not None for _, r in five.iterrows()):
        raise ValueError("Pinned source rows not independently valid")
    if mode == "write":
        expected = pd.concat((current, five), ignore_index=True)
        if expected.match_id.duplicated().any() or len(expected) != len(current) + 5:
            raise ValueError("Output duplicates or loses canonical matches")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() in {backup_path.resolve(), current_path.resolve()}:
            raise ValueError("In-place canonical rewrite prohibited")
        expected.to_parquet(target, compression="zstd", engine="pyarrow", index=False)
    elif mode == "verify":
        expected = pd.concat((current, five), ignore_index=True)
    else:
        raise ValueError("Mode must be write/verify")
    reread = pd.read_parquet(target)
    pd.testing.assert_frame_equal(reread, expected, check_exact=True)
    pd.testing.assert_frame_equal(reread.iloc[:len(current)].reset_index(drop=True),
                                  current.reset_index(drop=True), check_exact=True)
    pd.testing.assert_frame_equal(reread.iloc[len(current):].reset_index(drop=True),
                                  five.reset_index(drop=True), check_exact=True)
    return {"status":"APPEND_ONLY_FULL_YEAR_READBACK_PASS","mode":mode,
            "original_backup_sha256":BACKUP_SHA,
            "prior_year_sha256":sha256(current_path),
            "after_year_sha256":sha256(target),
            "existing_rows_preserved":len(current),
            "new_rows":5,"total_rows":len(reread),
            "overwritten_existing_values":0,"model_trained":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--backup",required=True,type=Path)
    parser.add_argument("--before",required=True,type=Path)
    parser.add_argument("--after",required=True,type=Path)
    parser.add_argument("--mode",required=True,choices=("write","verify"))
    parser.add_argument("--report",required=True,type=Path)
    args=parser.parse_args()
    result=build(args.backup,args.before,args.after,mode=args.mode)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("FIVE_ROW_EXACT_RESTORE",json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
