"""Strict importer for output of link_offline_serve_return.py.

Default is dry-run. It verifies that the canonical identity recorded by the
linker still exactly matches current private history before any stats can be
applied. No release upload occurs here.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder

RATE_FIELDS = {
    "first_serve_win",
    "second_serve_win",
    "service_points_won",
    "return_points_won",
    "first_strike_serve_win",
    "return_in_play_rate",
    "return_deep_rate",
    "break_point_serve_win",
    "break_point_return_win",
    "net_points_win",
    "attacking_points_rate",
    "unforced_error_rate",
}
COUNT_FIELDS = {"aces", "double_faults"}
ALLOWED = {f"{side}_{field}" for side in ("p1", "p2") for field in RATE_FIELDS | COUNT_FIELDS}


def _quality(stats):
    return all(
        FeatureBuilder._extract_quality(stats or {}, side)[0] is not None
        and FeatureBuilder._extract_quality(stats or {}, side)[1] is not None
        for side in ("p1", "p2")
    )


def _signature(match) -> dict[str, str]:
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _read(path: str) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Stage line {number} is not an object")
            rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write-partitions", action="store_true")
    ap.add_argument("--write-history-dir", default="")
    args = ap.parse_args()
    if args.write_history_dir and not args.write_partitions:
        ap.error("--write-history-dir requires --write-partitions")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    by_id = {str(m.match_id): m for m in matches}
    rows = _read(args.stage)
    seen = set()
    counts = Counter()
    review = []
    changed_years = set()
    before = sum(1 for m in matches if _quality(m.stats or {}))

    for row in rows:
        if row.get("schema") != 1 or row.get("import_ready") is not True:
            raise ValueError("Unexpected offline stage trust marker")
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Missing or duplicate staged match ID")
        seen.add(mid)
        match = by_id.get(mid)
        if match is None:
            counts["identity_missing"] += 1
            review.append({"match_id": mid, "reason": "identity_missing"})
            continue

        recorded = row.get("canonical")
        if not isinstance(recorded, dict) or recorded != _signature(match):
            counts["identity_changed"] += 1
            review.append({"match_id": mid, "reason": "identity_changed"})
            continue

        incoming = row.get("incoming_stats")
        if not isinstance(incoming, dict) or not incoming:
            counts["no_stats"] += 1
            continue
        clean = {}
        invalid = []
        for key, value in incoming.items():
            if key not in ALLOWED or isinstance(value, bool):
                invalid.append(key)
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                invalid.append(key)
                continue
            if not math.isfinite(numeric):
                invalid.append(key)
                continue
            field = key.split("_", 1)[1]
            if field in RATE_FIELDS and not 0 <= numeric <= 1:
                invalid.append(key)
                continue
            if field in COUNT_FIELDS and (numeric < 0 or not numeric.is_integer()):
                invalid.append(key)
                continue
            clean[key] = numeric
        if invalid:
            counts["invalid_stats"] += 1
            review.append({"match_id": mid, "reason": "invalid_stats", "keys": invalid})
            continue

        existing = dict(match.stats or {})
        conflicts = [
            key for key, value in clean.items()
            if existing.get(key) is not None and abs(float(existing[key]) - value) > 1e-6
        ]
        if conflicts:
            counts["stat_conflicts"] += 1
            review.append({"match_id": mid, "reason": "stat_conflicts", "keys": conflicts})
            continue

        new_stats = dict(existing)
        new_stats.update({key: value for key, value in clean.items() if new_stats.get(key) is None})
        if new_stats == existing:
            counts["already_present"] += 1
            continue
        match.stats = new_stats
        counts["updated"] += 1
        changed_years.add(match.scheduled_at.year)

    after = sum(1 for m in matches if _quality(m.stats or {}))
    target = Path(args.write_history_dir) if args.write_history_dir else out / "history"
    if args.write_partitions:
        for year in sorted(changed_years):
            write_year_partition(
                matches,
                target,
                year,
                extra_manifest={"coverage_status": "offline_serve_return_import_pending_review"},
            )

    report = {
        "schema": 1,
        "stage_rows": len(rows),
        "counts": dict(counts),
        "changed_years": sorted(changed_years),
        "quality_ready_before": before,
        "quality_ready_after": after,
        "quality_ready_added": after - before,
        "production_mutated": False,
        "local_partitions_written": bool(args.write_partitions and changed_years),
        "api_requests": 0,
        "note": "Importer never uploads a release; publish only after review and full history integrity validation.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / "review.jsonl").open("w", encoding="utf-8") as handle:
        for item in review:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
