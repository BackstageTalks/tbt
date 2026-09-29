"""Strict importer for linked historical opening/closing market data.

Default is dry-run. The importer never changes MatchRecord.stats, ranks, or
prediction features; it only writes audited provider_payload market history.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.offline_market_history import clean_market_history_marker, market_history_equivalent


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

    by_id = {str(match.match_id): match for match in matches}
    rows = _read(args.stage)
    counts = Counter()
    review = []
    changed_years = set()
    seen = set()

    for row in rows:
        if row.get("schema") != 1 or row.get("import_ready") is not True:
            raise ValueError("Unexpected offline market-history stage trust marker")
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Missing or duplicate staged match ID")
        seen.add(mid)
        match = by_id.get(mid)
        if match is None:
            counts["identity_missing"] += 1
            review.append({"match_id": mid, "reason": "identity_missing"})
            continue
        if row.get("canonical") != _signature(match):
            counts["identity_changed"] += 1
            review.append({"match_id": mid, "reason": "identity_changed"})
            continue

        marker = clean_market_history_marker(row.get("incoming_market_history"))
        if marker is None:
            counts["invalid_market_history"] += 1
            review.append({"match_id": mid, "reason": "invalid_market_history"})
            continue

        payload = dict(match.provider_payload or {})
        existing = payload.get("_tbt_market_history")
        if existing:
            if market_history_equivalent(existing, marker):
                counts["already_present"] += 1
            else:
                counts["market_conflicts"] += 1
                review.append({"match_id": mid, "reason": "market_conflict"})
            continue

        payload["_tbt_market_history"] = marker
        match.provider_payload = payload
        counts["updated"] += 1
        changed_years.add(int(match.scheduled_at.year))

    target = Path(args.write_history_dir) if args.write_history_dir else out / "history"
    if args.write_partitions:
        for year in sorted(changed_years):
            write_year_partition(
                matches,
                target,
                year,
                extra_manifest={"coverage_status": "offline_market_history_open_close"},
            )

    report = {
        "schema": 1,
        "stage_rows": len(rows),
        "counts": dict(counts),
        "changed_years": sorted(changed_years),
        "production_mutated": False,
        "local_partitions_written": bool(args.write_partitions and changed_years),
        "api_requests": 0,
        "model_feature_policy": "closing_validation_only",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / "review.jsonl").open("w", encoding="utf-8") as handle:
        for item in review:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
