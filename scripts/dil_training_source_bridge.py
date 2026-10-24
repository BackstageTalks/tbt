"""Ephemeral read-only export of training table from private SHA-verified release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

TAG = "tbt-training-table-v1"
REQUIRED = ("training_table.parquet", "training_table_report.json", "leakage_audit_report.json")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args()
    if not os.getenv("GH_TOKEN"):
        raise SystemExit("No private release credential")
    from release_store import ReleaseStore
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ReleaseStore(args.repository, TAG, args.out_dir).download(
        extra_names=REQUIRED, required_names=REQUIRED, require_bundle_manifest=True
    )
    report = json.loads((args.out_dir / "training_table_report.json").read_text())
    leakage = json.loads((args.out_dir / "leakage_audit_report.json").read_text())
    if str(leakage.get("status", "")).lower() not in ("pass", "passed", "verified"):
        raise SystemExit("Training leakage audit not PASS")
    expected = int(report.get("rows") or report.get("total_rows") or 0)
    if expected <= 0:
        raise SystemExit("Missing training table rows in source report")
    files = {}
    for name in REQUIRED:
        f = args.out_dir / name
        h = hashlib.sha256()
        with f.open("rb") as inp:
            for chunk in iter(lambda: inp.read(8 * 1024 * 1024), b""):
                h.update(chunk)
        files[name] = {"bytes": f.stat().st_size, "sha256": h.hexdigest()}
    (args.out_dir / "dil_training_source_receipt.json").write_text(json.dumps({
        "schema": 1,
        "status": "source_export_only_not_imported",
        "repository": args.repository,
        "source_release": TAG,
        "expected_rows": expected,
        "source_leakage_audit": leakage["status"],
        "files": files,
        "canonical_cdb_modified": False
    }, indent=2))
    print(json.dumps({"status": "private_release_verified", "expected_rows": expected,
                      "source_sha256": files["training_table.parquet"]["sha256"]}))


if __name__ == "__main__":
    main()
