#!/usr/bin/env python3
"""Grand Slam Sackmann point observations, research-only, not canonical stats.

A point tape has no independent full-match coverage attestation. Observed
serve/return points are never automatically full-match CDB statistics.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re

NAME = re.compile(r"^(20\d\d)-(ausopen|frenchopen|wimbledon|usopen)-points\.csv$")
REQUIRED_POINTS = {"match_id", "SetNo", "GameNo", "PointNumber", "PointWinner", "PointServer"}
REQUIRED_MATCHES = {"match_id", "player1", "player2"}
CAP_ROWS = 220_000


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _positive_int(value: object) -> int | None:
    try:
        x = int(str(value or "").strip())
    except ValueError:
        return None
    return x if x > 0 else None


def _metadata(path: Path) -> tuple[dict[str, dict], set[str]]:
    accepted = {}
    conflicts = set()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED_MATCHES.issubset(reader.fieldnames or []):
            raise ValueError(f"Unsupported Slam match schema: {path.name}")
        for row in reader:
            mid = str(row.get("match_id") or "").strip()
            if not mid:
                continue
            if mid in accepted:
                conflicts.add(mid)
            else:
                accepted[mid] = {
                    "player1": str(row.get("player1") or "").strip(),
                    "player2": str(row.get("player2") or "").strip(),
                    "point_source_player1_id": str(row.get("player1id") or "").strip(),
                    "point_source_player2_id": str(row.get("player2id") or "").strip(),
                }
    return accepted, conflicts


def prepare(root: Path, out_dir: Path, start_year: int = 2016,
            end_year: int = 2026) -> dict:
    if not root.is_dir() or not 2011 <= start_year <= end_year <= 2026:
        raise ValueError("Invalid Slam extraction or year window")
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "point_observations.jsonl"
    counters = Counter()
    files = []
    with output.open("w", encoding="utf-8") as dest:
        for path in sorted(root.rglob("*-points.csv")):
            match = NAME.fullmatch(path.name)
            if not match:
                continue
            year, slam = int(match.group(1)), match.group(2)
            if not start_year <= year <= end_year:
                continue
            peer = path.with_name(path.name.replace("-points.csv", "-matches.csv"))
            if not peer.is_file():
                counters["missing_match_metadata_files"] += 1
                continue
            metadata, conflicts = _metadata(peer)
            sha, match_sha = _sha(path), _sha(peer)
            rows = defaultdict(lambda: {"seen_keys": {}, "observed": [0, 0],
                                        "served_won": [0, 0], "point_rows": 0,
                                        "invalid": 0, "conflicting": False})
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not REQUIRED_POINTS.issubset(reader.fieldnames or []):
                    raise ValueError(f"Unsupported Slam point schema: {path.name}")
                for index, item in enumerate(reader, 2):
                    if index > CAP_ROWS + 1:
                        raise ValueError("Point file exceeds bounded cap")
                    counters["point_source_rows"] += 1
                    mid = str(item.get("match_id") or "").strip()
                    if not mid:
                        counters["point_rows_no_match_id"] += 1
                        continue
                    info = rows[mid]
                    info["point_rows"] += 1
                    s, g, n = (_positive_int(item.get(k)) for k in ("SetNo", "GameNo", "PointNumber"))
                    if s is None or g is None or n is None:
                        info["invalid"] += 1
                        continue
                    key = (s, g, n)
                    winner = str(item.get("PointWinner") or "").strip()
                    server = str(item.get("PointServer") or "").strip()
                    if key in info["seen_keys"]:
                        if info["seen_keys"][key] != (server, winner):
                            info["conflicting"] = True
                        counters["duplicate_point_keys"] += 1
                        continue
                    info["seen_keys"][key] = (server, winner)
                    if server not in {"1", "2"} or winner not in {"1", "2"}:
                        info["invalid"] += 1
                        continue
                    side = int(server) - 1
                    info["observed"][side] += 1
                    info["served_won"][side] += int(winner == server)
            emitted = 0
            for mid, tally in rows.items():
                record = metadata.get(mid) or {}
                no_match = not record.get("player1") or not record.get("player2")
                issue = mid in conflicts or no_match or tally["conflicting"]
                if issue:
                    counters["quarantined_match_observations"] += 1
                elif not any(tally["observed"]):
                    counters["no_usable_points_matches"] += 1
                else:
                    counters["research_match_observations"] += 1
                left, right = tally["observed"]
                entry = {
                    "schema": "SLAM_OBSERVED_POINTS_V1",
                    "state": "QUARANTINE" if issue else "RESEARCH_ONLY",
                    "import_ready": False, "full_match_coverage_verified": False,
                    "source_id_namespace": "sackmann-slam-pbp",
                    "point_source_sha256": sha, "match_source_sha256": match_sha,
                    "source_match_id": mid, "year": year, "slam": slam,
                    "source_player1_id": record.get("point_source_player1_id", ""),
                    "source_player2_id": record.get("point_source_player2_id", ""),
                    "player1_name": record.get("player1", ""),
                    "player2_name": record.get("player2", ""),
                    "observed_point_rows": tally["point_rows"],
                    "valid_server_winner_points": left + right,
                    "unusable_points": tally["invalid"],
                    "conflicting_point_key": tally["conflicting"],
                    "p1_observed_serve_points": left, "p2_observed_serve_points": right,
                    "p1_observed_serve_won": tally["served_won"][0],
                    "p2_observed_serve_won": tally["served_won"][1],
                    "p1_observed_service_win_rate": tally["served_won"][0] / left if left else None,
                    "p2_observed_service_win_rate": tally["served_won"][1] / right if right else None,
                    "p1_observed_return_win_rate": (right - tally["served_won"][1]) / right if right else None,
                    "p2_observed_return_win_rate": (left - tally["served_won"][0]) / left if left else None,
                }
                dest.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                emitted += 1
            files.append({"points_file": path.name, "points_sha256": sha,
                          "matches_sha256": match_sha, "match_observations": emitted})
            counters["source_pairs"] += 1
    report = {
        "schema": "BLINQ_SACKMANN_SLAM_POINT_RESEARCH_V1",
        "state": "RESEARCH_ONLY", "production_mutated": False,
        "api_requests": 0, "canonical_write_authorized": False,
        "crosswalk_promotion_authorized": False,
        "full_match_coverage_verified": False,
        "source_license": "CC BY-NC-SA 4.0 (noncommercial; reuse requires rights check)",
        "observations_path": str(output.resolve()), "observations_sha256": _sha(output),
        "counts": dict(sorted(counters.items())), "files": files,
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False,
                                                    indent=2, sort_keys=True) + "\n")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2026)
    a = p.parse_args()
    report = prepare(a.source_root, a.out_dir, a.start_year, a.end_year)
    print(json.dumps({"state": report["state"], "counts": report["counts"]}))


if __name__ == "__main__":
    main()
