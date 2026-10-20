#!/usr/bin/env python3
"""Read-only, SHA-pinned chunking for oversized ATP/WTA serve/return CSVs.

This stages raw records, NOT canonical match-linked statistics. No column may
be interpreted as a match ID, no CDB writer is imported, and no checkpoint is
advanced. An immutable, full-source digest is mandatory; no partial stage may
be considered complete without the final manifest.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

MAX_SOURCE_BYTES = 4 * 1024 * 1024 * 1024
MAX_ROWS = 8_000_000
MAX_COLUMNS = 256
MAX_CHUNK_ROWS = 200_000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stage(source: Path, output: Path, kind: str, expected_sha256: str,
          chunk_rows: int = MAX_CHUNK_ROWS) -> dict:
    if kind not in {"serve", "return"}:
        raise ValueError("Unknown large-source kind")
    if not isinstance(chunk_rows, int) or isinstance(chunk_rows, bool) or not 1 <= chunk_rows <= MAX_CHUNK_ROWS:
        raise ValueError("Unbounded chunk size")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in expected_sha256):
        raise ValueError("Expected immutable SHA-256 is required")
    if not source.is_file() or source.suffix.lower() != ".csv":
        raise ValueError("Large source must be a local CSV")
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds bounded stage size")
    if sha256(source) != expected_sha256:
        raise ValueError("Pinned source SHA-256 mismatch")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output stage must be empty; refusing to overwrite")
    csv.field_size_limit(1024 * 1024)
    shards = []
    writer = None
    handle = None
    shard_path = None
    count = 0
    in_shard = 0
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as src:
            reader = csv.DictReader(src)
            fields = reader.fieldnames
            if not fields or any(not x or not x.strip() for x in fields):
                raise ValueError("Missing CSV headers")
            if len(fields) > MAX_COLUMNS or len(set(fields)) != len(fields):
                raise ValueError("Duplicate or unbounded CSV headers")
            for row in reader:
                if count >= MAX_ROWS:
                    raise ValueError("Source exceeds bounded row count")
                if None in row or any(x is None for x in row.values()):
                    raise ValueError("Malformed CSV field count")
                if writer is None or in_shard == chunk_rows:
                    if handle is not None:
                        handle.close()
                        shards.append({"file": shard_path.name, "rows": in_shard,
                                       "sha256": sha256(shard_path)})
                    shard_path = output / f"{kind}-{len(shards):05d}.csv"
                    handle = shard_path.open("w", encoding="utf-8", newline="")
                    writer = csv.DictWriter(handle, fieldnames=fields,
                                            extrasaction="raise")
                    writer.writeheader()
                    in_shard = 0
                writer.writerow(row)
                in_shard += 1
                count += 1
        if handle is not None:
            handle.close()
            handle = None
            shards.append({"file": shard_path.name, "rows": in_shard,
                           "sha256": sha256(shard_path)})
    finally:
        if handle is not None:
            handle.close()
    if sha256(source) != expected_sha256:
        raise ValueError("Source changed during chunking; stage is untrusted")
    report = {
        "schema": 1,
        "state": "SOURCE_ONLY_NEEDS_EXACT_IDENTITY_MAPPING",
        "production_mutated": False,
        "api_requests": 0,
        "cdb_eligible_matches": 0,
        "kind": kind,
        "source_sha256": expected_sha256,
        "source_bytes": source.stat().st_size,
        "rows": count,
        "columns": len(fields),
        "requires_schema_review": True,
        "requires_independent_match_identity": True,
        "shards": shards,
    }
    (output / "manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--kind", choices=("serve", "return"), required=True)
    ap.add_argument("--expected-sha256", required=True)
    ap.add_argument("--chunk-rows", type=int, default=MAX_CHUNK_ROWS)
    args = ap.parse_args()
    print(json.dumps(stage(args.source, args.output, args.kind,
                           args.expected_sha256, args.chunk_rows),
                     sort_keys=True))


if __name__ == "__main__":
    main()
