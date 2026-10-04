"""Strict importer for audited ATP weekly ranking fill candidates."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions, write_year_partition


def _signature(match) -> dict[str, str]:
    return {
        "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write-partitions", action="store_true")
    ap.add_argument("--write-history-dir", default="")
    args = ap.parse_args()

    matches, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")
    by_id = {str(match.match_id): match for match in matches}

    rows = [
        json.loads(line)
        for line in Path(args.stage).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    counts = Counter()
    changed_years = set()
    seen = set()

    for row in rows:
        mid = str(row.get("match_id") or "")
        if row.get("schema") != 1 or not mid or mid in seen:
            counts["invalid_or_duplicate_stage_row"] += 1
            continue
        seen.add(mid)
        match = by_id.get(mid)
        if match is None:
            counts["identity_missing"] += 1
            continue
        expected = {
            "scheduled_at": str(row.get("scheduled_at") or ""),
            "player1_id": str(row.get("player1_id") or ""),
            "player1_name": str(row.get("player1_name") or ""),
            "player2_id": str(row.get("player2_id") or ""),
            "player2_name": str(row.get("player2_name") or ""),
        }
        if _signature(match) != expected:
            counts["identity_changed"] += 1
            continue
        if str(match.tour or "").lower() != "atp":
            counts["wrong_tour"] += 1
            continue

        try:
            rank1 = int(row["incoming_player1_rank"])
            rank2 = int(row["incoming_player2_rank"])
            source_week = datetime.strptime(str(row["source_week"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            counts["invalid_incoming"] += 1
            continue
        if rank1 <= 0 or rank2 <= 0:
            counts["invalid_incoming"] += 1
            continue

        scheduled = match.scheduled_at.astimezone(timezone.utc)
        if source_week.date() >= scheduled.date():
            counts["point_in_time_rejected"] += 1
            continue
        age_days = (scheduled.date() - source_week.date()).days
        if age_days > 14:
            counts["stale_snapshot_rejected"] += 1
            continue

        existing1, existing2 = match.player1_rank, match.player2_rank
        if existing1 is not None and int(existing1) != rank1:
            counts["existing_rank_mismatch"] += 1
            continue
        if existing2 is not None and int(existing2) != rank2:
            counts["existing_rank_mismatch"] += 1
            continue
        if existing1 is not None and existing2 is not None:
            counts["rank_already_complete"] += 1
            continue

        if existing1 is None:
            match.player1_rank = rank1
            counts["player1_rank_filled"] += 1
        if existing2 is None:
            match.player2_rank = rank2
            counts["player2_rank_filled"] += 1

        payload = dict(match.provider_payload or {})
        payload["_tbt_rank_provenance"] = {
            "point_in_time": True,
            "source": str(row.get("source") or "atp_rankings_ishanjha_weekly"),
            "as_of": source_week.isoformat(),
        }
        match.provider_payload = payload
        counts["updated"] += 1
        changed_years.add(scheduled.year)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.write_partitions and changed_years:
        target = Path(args.write_history_dir) if args.write_history_dir else out / "history"
        for year in sorted(changed_years):
            write_year_partition(
                matches,
                target,
                year,
                extra_manifest={"coverage_status": "atp_weekly_point_in_time_rank_gapfill"},
            )

    report = {
        "schema": 1,
        "stage_rows": len(rows),
        "counts": dict(counts),
        "changed_years": sorted(changed_years),
        "rapidapi_requests": 0,
        "production_mutated": False,
        "local_partitions_written": bool(args.write_partitions and changed_years),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
