#!/usr/bin/env python3
"""Read-only independent QA for a private ATP Tour source checkpoint tarball.

The auditor does not access provider sites, extract files, or write databases.
It validates the GitHub Release asset SHA-256 and the actual archive contents.
"""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path
from urllib.parse import urlparse

MAX_MEMBERS = 120000
MAX_MEMBER_BYTES = 16_000_000
MAX_TOTAL_BYTES = 900_000_000


def audit(archive_path, year, digest):
    path = Path(archive_path)
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("Missing valid expected Release SHA-256")
    with path.open("rb") as f:
        actual = "sha256:" + hashlib.file_digest(f, "sha256").hexdigest()
    if actual.lower() != digest.lower():
        raise ValueError("Private release asset SHA-256 mismatch")

    archive_prefix = f"data/atptour/archive/{year}/"
    stats_prefix = f"data/atptour/match_stats/{year}/"
    seen = set()
    discovery = None
    tournaments = {}
    stats = {}
    members = 0
    total_bytes = 0
    foreign_files = 0
    with tarfile.open(path, "r:gz") as tf:
        for member in tf:
            members += 1
            if members > MAX_MEMBERS:
                raise ValueError("Unsafe archive: too many members")
            name = member.name
            parts = Path(name).parts
            if (not member.isfile() or member.issym() or member.islnk()
                    or name.startswith("/") or ".." in parts
                    or not name.startswith("data/atptour/")
                    or name in seen or member.size > MAX_MEMBER_BYTES):
                raise ValueError("Unsafe, duplicate or unexpected archive member")
            seen.add(name)
            total_bytes += member.size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Unsafe archive: too much decompressed data")
            if not name.startswith((archive_prefix, stats_prefix)):
                foreign_files += 1
                continue
            fd = tf.extractfile(member)
            if fd is None:
                raise ValueError("Unreadable archive member")
            body = fd.read(MAX_MEMBER_BYTES + 1)
            if len(body) != member.size:
                raise ValueError("Truncated archive member")
            if name == archive_prefix + "_discovery.json":
                discovery = json.loads(body.decode("utf-8"))
            elif name.startswith(archive_prefix) and name.endswith(".jsonl"):
                rows = [json.loads(line) for line in body.decode("utf-8").splitlines()
                        if line.strip()]
                tournaments[name] = rows
            elif name.startswith(stats_prefix) and name.endswith(".json"):
                stats[name] = json.loads(body.decode("utf-8"))

    urls = discovery.get("urls", []) if isinstance(discovery, dict) else []
    if not isinstance(urls, list):
        raise ValueError("Malformed ATP tournament discovery ledger")
    missing_tournaments = 0
    bad_tournament_rows = 0
    match_rows = 0
    required_stats = set()
    for url in urls:
        m = re.fullmatch(
            rf"/en/scores/archive/([^/]+)/(\\d+)/{year}/(?:results|country-results)",
            urlparse(url).path,
        )
        if not m:
            missing_tournaments += 1
            continue
        slug, event_id = m.groups()
        key = archive_prefix + event_id + "-" + slug + ".jsonl"
        records = tournaments.get(key, [])
        if not records:
            missing_tournaments += 1
            continue
        for row in records:
            if (not isinstance(row, dict) or row.get("year") != year
                    or not row.get("source_match_id")):
                bad_tournament_rows += 1
                continue
            match_rows += 1
            for stats_url in row.get("match_stats_urls", []):
                path_part = urlparse(stats_url).path
                mstats = re.fullmatch(
                    rf"/en/scores/match-stats/archive/{year}/([^/]+)/([^/]+)",
                    path_part,
                )
                if mstats:
                    ev, match_id = mstats.groups()
                    required_stats.add((ev, match_id))

    missing_stats = 0
    nonempty_table_stats = 0
    for event_id, match_id in required_stats:
        member_name = stats_prefix + event_id + "/" + match_id + ".json"
        data = stats.get(member_name)
        if (not isinstance(data, dict)
                or data.get("source_match_id") !=
                f"atptour:{year}:{event_id}:{match_id}"):
            missing_stats += 1
        elif data.get("tables") and any(x.get("rows") for x in data["tables"]
                                         if isinstance(x, dict)):
            nonempty_table_stats += 1

    complete = bool(urls and not missing_tournaments
                    and not bad_tournament_rows and not missing_stats)
    return {
        "year": year,
        "sha256_verified": True,
        "member_count": members,
        "other_atptour_files": foreign_files,
        "tournaments_discovered": len(urls),
        "tournaments_found": len(urls) - missing_tournaments,
        "missing_tournaments": missing_tournaments,
        "match_rows": match_rows,
        "bad_tournament_rows": bad_tournament_rows,
        "linked_match_stats": len(required_stats),
        "missing_match_stats": missing_stats,
        "stats_with_nonempty_tables": nonempty_table_stats,
        "source_archive_complete": complete,
        "production_cdb_modified": False,
        "training_db_modified": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--expected-digest", required=True)
    ap.add_argument("--expect", choices=("complete", "incomplete"), required=True)
    args = ap.parse_args()
    report = audit(args.archive, args.year, args.expected_digest)
    print("INDEPENDENT_RELEASE_CHECKPOINT_QA", json.dumps(report, sort_keys=True))
    if report["source_archive_complete"] != (args.expect == "complete"):
        raise SystemExit("Checkpoint completeness did not match independently audited expectation")


if __name__ == "__main__":
    main()
