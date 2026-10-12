#!/usr/bin/env python3
"""Preserve SHA-pinned raw tennis match observations without pretending they are CDB links.

Inputs are already downloaded local CSV files.  No provider APIs, no CDB read/write,
no authentication, and no model training.  All per-match output MUST be kept PRIVATE.
An original source-native event key is never a canonical match/player identifier.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

SHA256 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_PROFILE = {"atp-wta-sackmann", "tennisexplorer-csv"}
DEFAULT_MAP = {
    "event_id": "match_id", "tourney_id": "tourney_id",
    "match_num": "match_num", "date": "tourney_date", "round": "round",
    "winner_id": "winner_id", "loser_id": "loser_id",
    "winner_name": "winner_name", "loser_name": "loser_name",
}
STAT_NAMES = tuple(
    f"{side}_{field}" for side in ("w", "l")
    for field in ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon",
                  "SvGms", "bpSaved", "bpFaced")
)
MAX_SOURCE_BYTES = 550 * 1024 * 1024
MAX_ROWS_PER_SOURCE = 1_000_000


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _checked_source(spec, root):
    if not isinstance(spec, dict):
        raise ValueError("Invalid source specification")
    filename = spec.get("filename")
    namespace = spec.get("namespace")
    digest = spec.get("sha256")
    if (not isinstance(filename, str) or filename != Path(filename).name
            or filename in ("", ".", "..")
            or not isinstance(namespace, str)
            or not re.fullmatch(r"[a-zA-Z0-9_.:-]{4,120}", namespace)
            or not isinstance(digest, str) or not SHA256.fullmatch(digest)
            or spec.get("profile") not in ALLOWED_PROFILE
            or spec.get("tour") not in ("atp", "wta")
            or not isinstance(spec.get("source_ref"), str)
            or not spec["source_ref"]
            or spec.get("source_rights_status") not in ("approved_private_research", "review_needed")):
        raise ValueError("Unpinned/unsupported source or unsafe filename")
    mapping = dict(DEFAULT_MAP)
    explicit = spec.get("columns", {})
    if not isinstance(explicit, dict) or not all(
        k in DEFAULT_MAP and (v is None or isinstance(v, str) and v)
        for k, v in explicit.items()
    ):
        raise ValueError("Invalid identity field mapping")
    mapping.update(explicit)
    path = root / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Source missing, oversized, or linked")
    if sha256_file(path) != digest:
        raise ValueError("Original source SHA-256 mismatch: " + filename)
    return path, mapping


def _records(path, mapping, spec):
    with path.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        header = reader.fieldnames or []
        if (not header or len(header) != len(set(header))
                or any(not isinstance(f, str) or not f for f in header)):
            raise ValueError("Invalid CSV header")
        # Some legitimate exports omit event_id or match_num. Retain them
        # explicitly as source-only observations rather than rejecting the file.
        # Explicit user-provided column names must exist to prevent typos.
        explicit = spec.get("columns", {})
        for logical, col in mapping.items():
            if col and col not in header and logical in explicit:
                raise ValueError("Specified identity column not in source: " + col)
        for i, raw in enumerate(reader, start=2):
            if i > MAX_ROWS_PER_SOURCE + 1:
                raise ValueError("Unbounded source row count")
            # Preserve malformed original shapes as quarantine evidence, with
            # all values, not silently skipping any rows.
            malformed = None in raw or any(x is None for x in raw.values())
            row = {str(k) if k is not None else "__extra_columns__":
                   v for k, v in raw.items()}
            native = {key: str(row.get(col) or "").strip() if col else ""
                      for key, col in mapping.items()}
            named = (native["tourney_id"], native["match_num"])
            # A truly original event ID is useful even where match_num is absent.
            event = native["event_id"]
            if event:
                key = ("provider-event", event)
            elif all(named):
                key = ("tournament-match", *named)
            else:
                key = None
            ids = (native["winner_id"], native["loser_id"])
            two_ids = all(ids) and ids[0] != ids[1]
            values = {k: row[k] for k in STAT_NAMES if k in row and row[k] not in (None, "")}
            content_sha = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()
            item = {
                "schema": 1, "source_namespace": spec["namespace"],
                "source_ref": spec["source_ref"], "source_file": spec["filename"],
                "source_sha256": spec["sha256"], "source_row": i,
                "raw_row_sha256": content_sha, "tour": spec["tour"],
                "source_native_event_key": list(key) if key else None,
                "source_event_id": event or None,
                "source_winner_id": ids[0] or None, "source_loser_id": ids[1] or None,
                "two_original_player_ids": bool(two_ids),
                "source_tourney_id": named[0] or None, "source_match_num": named[1] or None,
                "source_date": native["date"] or None, "source_round": native["round"] or None,
                "source_stats_nonempty": values,
                "raw_columns": row,
                "source_rights_status": spec["source_rights_status"],
                "canonical_match_id": None, "canonical_player1_id": None,
                "canonical_player2_id": None, "canonical_stats_written": False,
                "write_authorized": False, "import_ready": False,
                "model_use": "POSTMATCH_ARCHIVE_UNLINKED_NOT_A_PREMATCH_FEATURE",
                "_malformed": malformed,
            }
            yield item


def build(manifest_path: Path, source_root: Path, output: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1
            or not isinstance(manifest.get("sources"), list)
            or not 1 <= len(manifest["sources"]) <= 50):
        raise ValueError("Invalid source manifest")
    specs = manifest["sources"]
    namespaces, filenames = set(), set()
    pinned = []
    for spec in specs:
        path, mapping = _checked_source(spec, source_root)
        if spec["namespace"] in namespaces or spec["filename"] in filenames:
            raise ValueError("Ambiguous repeated source namespace/file")
        namespaces.add(spec["namespace"]); filenames.add(spec["filename"])
        pinned.append((spec, path, mapping))
    # Count ALL source-native collisions, including both earliest and newest
    # members. Never accidentally promote the first row in an ambiguous group.
    keys = Counter()
    shapes = Counter()
    totals = Counter()
    for spec, path, mapping in pinned:
        for item in _records(path, mapping, spec):
            totals["source_rows"] += 1
            key = item["source_native_event_key"]
            if key:
                keys[(spec["namespace"], tuple(key))] += 1
            if item["_malformed"]:
                shapes[spec["namespace"]] += 1

    output.mkdir(parents=True, exist_ok=True)
    observations = output / "source-observations.jsonl.gz"
    counts = Counter()
    by_source = defaultdict(Counter)
    # gzip mtime=0 means a byte-for-byte reproducible ledger for the same pinned sources.
    with observations.open("wb") as dest:
        with gzip.GzipFile(fileobj=dest, mode="wb", filename="", mtime=0, compresslevel=6) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="\n") as writer:
                for spec, path, mapping in pinned:
                    for item in _records(path, mapping, spec):
                        key = item["source_native_event_key"]
                        collision = bool(key and keys[(spec["namespace"], tuple(key))] > 1)
                        if item.pop("_malformed"):
                            status = "QUARANTINE_MALFORMED_CSV_ROW"
                        elif collision:
                            status = "QUARANTINE_AMBIGUOUS_NATIVE_EVENT_KEY"
                        elif not key or not item["two_original_player_ids"]:
                            status = "SOURCE_UNLINKED_INCOMPLETE_NATIVE_IDENTITY"
                        else:
                            status = "SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT"
                        item["linkage_status"] = status
                        # Preserve the observation even if structurally imperfect.
                        counts[status] += 1
                        by_source[spec["namespace"]][status] += 1
                        by_source[spec["namespace"]]["total"] += 1
                        if item["source_stats_nonempty"]:
                            counts["rows_with_some_standard_boxscore_stats"] += 1
                        writer.write(canonical_json(item) + "\n")
    if sum(v for k, v in counts.items() if k.startswith("SOURCE_") or k.startswith("QUARANTINE_")) != totals["source_rows"]:
        raise ValueError("Output row count differs from input")
    report = {
        "schema": 1, "status": "PRIVATE_RAW_SOURCE_EVIDENCE_RETAINED_NO_CDB_MAPPING",
        "source_count": len(pinned), "source_rows_retained": totals["source_rows"],
        "status_counts": dict(sorted(counts.items())),
        "by_source": {s: dict(sorted(v.items())) for s, v in sorted(by_source.items())},
        "files": [{"filename": spec["filename"], "namespace": spec["namespace"],
                   "source_sha256": spec["sha256"], "source_ref": spec["source_ref"],
                   "tour": spec["tour"], "rights": spec["source_rights_status"]}
                  for spec, _, _ in pinned],
        "observations_sha256": sha256_file(observations),
        "canonical_write_authorized": False,
        "canonical_cells_written": 0, "sport_api_requests": 0,
        "model_trained": False,
        "next_gate": "Separate independently attested event and two-player crosswalk, exact current CDB NULL check, rights, PIT and protected writer",
    }
    (output/"report.json").write_text(json.dumps(report, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    with (output/"SHA256SUMS").open("w", encoding="utf-8") as f:
        for path in (output/"report.json", observations):
            f.write(f"{sha256_file(path)}  {path.name}\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--source-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    report = build(args.manifest, args.source_root, args.out)
    print(json.dumps({k: report[k] for k in (
        "status", "source_count", "source_rows_retained", "status_counts",
        "canonical_cells_written", "sport_api_requests"
    )}, sort_keys=True))


if __name__ == "__main__":
    main()
