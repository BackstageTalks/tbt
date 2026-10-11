"""Reconstruct operator's private ATP Futures source exactly, without any CDB write."""
import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

FOLDER = "research/offline-sources/blinq-import-2026-10-07/chunks"
FILENAME = "blinq_atp_futures_quali_2018_2026.csv"
SOURCE_SHA = "410e0b7a4c08f05aebd54de90d8f8029a514d8c0df41c251c5979e5b06e488d5"


def fetch_private(path):
    if not path.startswith(FOLDER + "/"):
        raise ValueError("Out-of-scope private source path")
    return subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw+json",
         "repos/BackstageTalks/tbt-data/contents/" + path + "?ref=main"],
        capture_output=True, check=True,
    ).stdout


def reconstruct(manifest, fetch):
    if manifest.get("schema") != 1 or manifest.get("compression") != "gzip":
        raise ValueError("Unrecognized source manifest")
    entry = manifest["files"][FILENAME]
    if entry.get("sha256") != SOURCE_SHA:
        raise ValueError("Unexpected original source SHA")
    parts = entry.get("parts") or []
    if (len(parts) != 9 or parts != sorted(set(parts))
            or any(not re.fullmatch(r"blinq_atp_futures_quali_2018_2026\.csv\.gz\.b64\.part\d{3}\.txt", p)
                   for p in parts)):
        raise ValueError("Untrusted part inventory")
    gz = base64.b64decode(b"".join(fetch(part).strip() for part in parts), validate=True)
    if len(gz) != entry["compressed_bytes"]:
        raise ValueError("Compressed source byte count mismatch")
    raw = gzip.decompress(gz)
    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError("Original source SHA/length mismatch")
    return raw, hashlib.sha256(gz).hexdigest()


def audit(raw, compressed_sha):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    cols = reader.fieldnames or []
    if len(cols) != 64 or len(set(cols)) != 64:
        raise ValueError("Unexpected source schema")
    populated = Counter()
    n = 0
    for row in reader:
        n += 1
        for key, value in row.items():
            if value is not None and str(value).strip():
                populated[key] += 1
        if n > 130689:
            raise ValueError("Source unexpectedly exceeds audited row count")
    if n != 130689:
        raise ValueError("Source row count mismatch")
    return {"schema": 1, "status": "VERIFIED_PRIVATE_SOURCE_ONLY",
            "filename": FILENAME, "original_sha256": SOURCE_SHA,
            "compressed_sha256": compressed_sha, "source_rows": n,
            "source_columns": cols, "populated_column_counts": dict(populated),
            "candidate_id_columns": [x for x in cols if "id" in x.lower()],
            "candidate_date_columns": [x for x in cols if "date" in x.lower()],
            "current_cdb_cell_diff": None, "source_license_cleared_for_write": False,
            "approved_missing_cdb_cells": 0, "canonical_mutated": False,
            "model_trained": False, "provider_api_requests": 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    manifest = json.loads(fetch_private(FOLDER + "/manifest.json"))
    raw, compressed_sha = reconstruct(manifest, lambda name: fetch_private(FOLDER + "/" + name))
    report = audit(raw, compressed_sha)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("PRIVATE_FUTURES_RECONSTRUCTION_VERIFIED",
          json.dumps({"rows": report["source_rows"],
                      "original_sha256": report["original_sha256"],
                      "date_columns": report["candidate_date_columns"],
                      "id_columns": report["candidate_id_columns"]}, sort_keys=True))


if __name__ == "__main__":
    main()
