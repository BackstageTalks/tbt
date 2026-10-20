#!/usr/bin/env python3
"""Pinned read-only WTA Kaggle source intake, never a canonical CDB writer.

Kaggle Hwaitt is licensed CC BY-NC 4.0: do not promote staged observations
to commercial use without verifying that permission separately.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

DRIVE_FILE_ID = "1CMse_IDfurOwAhkWBZ4qRqYf1xzb6E3-"
SOURCE_SHA256 = "1467b2efd02288502f518662fe3ad3e1c9121e7e59a0e65f690f6ec779591548"
MAX_BYTES = 512 * 1024 * 1024
MAX_ROWS = 250_000
FIELDS = ("GameD", "TName", "Name_1", "Name_2", "GRes_CUR_1", "Surface", "ID",
          *(f"{field}_{side}" for side in (1, 2)
            for field in ("Aces", "DoubleFaults", "ServesTotal", "Serve1st",
                          "Serve1stWon", "Serve2ndWon", "ReceivingPointsWon",
                          "ReceivingPointsTotal", "BreakPointsConverted",
                          "BreakPointsTotal")))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_pinned(destination: Path, *, session=None,
                 file_id: str = DRIVE_FILE_ID, expected_sha256: str = SOURCE_SHA256) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,150}", file_id):
        raise ValueError("Invalid Drive ID")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("Expected source SHA-256 required")
    if destination.exists():
        raise ValueError("Refusing to overwrite source")
    if session is None:
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import AuthorizedSession
        secret = os.environ.get("BLINQ_DRIVE_READER_JSON", "")
        if not secret:
            raise ValueError("Private Drive reader unavailable")
        credentials = Credentials.from_service_account_info(
            json.loads(secret), scopes=["https://www.googleapis.com/auth/drive.readonly"])
        session = AuthorizedSession(credentials)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists():
        raise ValueError("Stale partial source; refusing ambiguous resume")
    digest = hashlib.sha256()
    amount = 0
    try:
        with session.get("https://www.googleapis.com/drive/v3/files/" + file_id,
                         params={"alt": "media"}, stream=True, timeout=120) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_BYTES:
                raise ValueError("Drive source is larger than allowed")
            with partial.open("xb") as stream:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    if not block:
                        continue
                    amount += len(block)
                    if amount > MAX_BYTES:
                        raise ValueError("Drive source exceeded byte limit")
                    digest.update(block)
                    stream.write(block)
            if content_length and int(content_length) != amount:
                raise ValueError("Drive response truncated")
        if amount == 0 or digest.hexdigest() != expected_sha256:
            raise ValueError("Pinned WTA source SHA-256 mismatch")
        partial.replace(destination)
    finally:
        if partial.exists():
            partial.unlink()
    return amount


def _norm(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in plain if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _validate(row: dict[str, str], start: int, end: int) -> str:
    day = str(row.get("GameD") or "")
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return "invalid_date"
    if parsed.isoformat() != day:
        return "invalid_date"
    if not start <= parsed.year <= end:
        return "outside_window"
    a, b = str(row.get("Name_1") or "").strip(), str(row.get("Name_2") or "").strip()
    if not a or not b or _norm(a) == _norm(b):
        return "invalid_players"
    if not _norm(str(row.get("TName") or "")):
        return "invalid_tournament"
    try:
        result = float(str(row.get("GRes_CUR_1") or ""))
    except ValueError:
        return "winner_unverified"
    if result not in (0.0, 1.0):
        return "winner_unverified"
    if not any(str(row.get(k) or "").strip() for k in FIELDS[7:]):
        return "no_direct_stats"
    return ""


def _key(row: dict[str, str]) -> tuple[str, str, str, str]:
    pair = sorted((_norm(row["Name_1"]), _norm(row["Name_2"])))
    return row["GameD"], _norm(row["TName"]), pair[0], pair[1]


def normalize(source: Path, destination: Path, *, expected_sha256: str = SOURCE_SHA256,
              start: int = 2016, end: int = 2020) -> dict:
    if not (2016 <= start <= end <= 2026):
        raise ValueError("Unsupported or inverted year window")
    if destination.exists() or source.resolve() == destination.resolve():
        raise ValueError("Normalized source must be new and distinct")
    if source.stat().st_size > MAX_BYTES or sha256(source) != expected_sha256:
        raise ValueError("Pinned source hash or size mismatch")

    csv.field_size_limit(1024 * 1024)
    counts = Counter()
    identities = Counter()

    def rows():
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            header = reader.fieldnames or []
            if (not header or len(header) > 256
                    or any(k not in header for k in FIELDS)
                    or len(set(header)) != len(header)):
                raise ValueError("Unsupported WTA source header")
            # Original source contains exactly one leading blank column.
            if any(not k.strip() for k in header if k != header[0]):
                raise ValueError("Other empty source headers are forbidden")
            for index, row in enumerate(reader, 2):
                if index > MAX_ROWS + 1:
                    raise ValueError("Oversized source row count")
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Malformed WTA CSV row")
                yield index, row

    for index, row in rows():
        counts["source_rows"] += 1
        reason = _validate(row, start, end)
        if reason:
            counts["excluded_" + reason] += 1
        else:
            identities[_key(row)] += 1
            counts["valid_window_rows"] += 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=("source_row", *FIELDS))
        writer.writeheader()
        for index, row in rows():
            if _validate(row, start, end):
                continue
            if identities[_key(row)] != 1:
                counts["quarantined_ambiguous_identity_rows"] += 1
                continue
            writer.writerow({"source_row": index, **{field: row[field] for field in FIELDS}})
            counts["staged_unique_rows"] += 1
    if sha256(source) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ValueError("Source changed while parsing")
    return {
        "schema": 1, "state": "SOURCE_ONLY_NEEDS_CANONICAL_MATCH",
        "production_mutated": False, "api_requests": 0,
        "source_sha256": expected_sha256, "source_bytes": source.stat().st_size,
        "normalized_sha256": sha256(destination),
        "normalized_bytes": destination.stat().st_size,
        "counts": dict(sorted(counts.items())),
        "window": [start, end],
        "license": "CC BY-NC 4.0; permission for intended use must be checked",
        "canonical_matches_confirmed": 0,
        "cdb_fields_imported": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="Local pinned CSV, for offline testing")
    parser.add_argument("--expected-sha256", default=SOURCE_SHA256)
    parser.add_argument("--drive-file-id", default=DRIVE_FILE_ID)
    parser.add_argument("--start", type=int, default=2016)
    parser.add_argument("--end", type=int, default=2020)
    args = parser.parse_args()
    if args.out_dir.exists() and any(args.out_dir.iterdir()):
        raise ValueError("Output directory must be empty")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    src = args.source or args.out_dir / "wta-original.csv"
    if args.source:
        if sha256(src) != args.expected_sha256:
            raise ValueError("Local source SHA-256 mismatch")
    else:
        fetch_pinned(src, file_id=args.drive_file_id, expected_sha256=args.expected_sha256)
    output = args.out_dir / "wta_matches_verified.csv"
    report = normalize(src, output, expected_sha256=args.expected_sha256,
                       start=args.start, end=args.end)
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                               encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
