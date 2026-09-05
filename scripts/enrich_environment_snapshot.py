from __future__ import annotations

import argparse
import json
import os
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import (
    ensure_partitions,
    load_manifest,
    load_partitions,
    write_manifest,
    write_year_partition,
)
from tbt.services.environment import OpenMeteoClient, environment_payload, location_candidates

logger = logging.getLogger("tbt.enrich_environment_snapshot")
def _hot_cutoff() -> datetime:
    try:
        days = int(os.getenv("TBT_HOT_RETENTION_DAYS", "60"))
    except ValueError:
        days = 60
    days = min(max(days, 14), 180)
    return datetime.now(timezone.utc) - timedelta(days=days)


def parse_utc(value: str) -> datetime:
    text = value.strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich archived GitHub history partitions; Supabase is deliberately not used"
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=50)
    parser.add_argument("--diagnostics-limit", type=int, default=100)
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument(
        "--legacy-snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be later than --start")
    if end > _hot_cutoff():
        raise SystemExit("V20.7 safety stop: GitHub environment enrichment must stay outside the rolling hot buffer")

    history_dir = Path(args.history_dir)
    ensure_partitions(history_dir, legacy_snapshot=args.legacy_snapshot)
    years = range(start.year, end.year + 1)
    matches = load_partitions(history_dir, years=years)
    candidates = [
        match
        for match in matches
        if start <= match.scheduled_at.astimezone(timezone.utc) < end and match.is_completed
    ]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    weather = OpenMeteoClient()
    changed_years: set[int] = set()
    report: dict[str, Any] = {
        "target": "github-release-year-partitions",
        "supabase_used": False,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "inspected": 0,
        "already_enriched": 0,
        "resolved": 0,
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(args.dry_run),
        "resolved_details": [],
        "unresolved_details": [],
        "error_details": [],
    }

    try:
        for index, match in enumerate(candidates, start=1):
            report["inspected"] += 1
            payload = dict(match.provider_payload or {})
            existing = payload.get("_tbt_environment")
            if (
                not args.force
                and isinstance(existing, dict)
                and existing.get("venue_resolved") is True
            ):
                report["already_enriched"] += 1
                continue

            location_options = location_candidates(payload, match.tournament)
            try:
                env = environment_payload(weather, payload, match.tournament, match.scheduled_at)
                payload["_tbt_environment"] = env
                detail = {
                    "match_id": match.match_id,
                    "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                    "tour": match.tour,
                    "tournament": match.tournament,
                    "location_candidates": location_options,
                }
                if env.get("venue_resolved"):
                    report["resolved"] += 1
                    detail["resolved_query"] = env.get("location_query")
                    detail["resolved_venue"] = env.get("venue")
                    if len(report["resolved_details"]) < args.diagnostics_limit:
                        report["resolved_details"].append(detail)
                else:
                    report["unresolved"] += 1
                    if len(report["unresolved_details"]) < args.diagnostics_limit:
                        report["unresolved_details"].append(detail)

                if not args.dry_run:
                    match.provider_payload = payload
                    report["updated"] += 1
                    changed_years.add(match.scheduled_at.astimezone(timezone.utc).year)
            except Exception as exc:
                report["errors"] += 1
                logger.warning(
                    "Partition environment enrichment failed match=%s tournament=%r: %s",
                    match.match_id,
                    match.tournament,
                    exc,
                )
                if len(report["error_details"]) < args.diagnostics_limit:
                    report["error_details"].append(
                        {
                            "match_id": match.match_id,
                            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                            "tour": match.tour,
                            "tournament": match.tournament,
                            "location_candidates": location_options,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            if index % 250 == 0:
                logger.info(
                    "Progress %s/%s resolved=%s unresolved=%s errors=%s",
                    index,
                    len(candidates),
                    report["resolved"],
                    report["unresolved"],
                    report["errors"],
                )
            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)
    finally:
        weather.close()

    if not args.dry_run and changed_years:
        for year in sorted(changed_years):
            year_matches = [
                match
                for match in matches
                if match.scheduled_at.astimezone(timezone.utc).year == year
            ]
            write_year_partition(
                year_matches,
                history_dir,
                year,
                extra_manifest={
                    "last_environment_enrichment": {
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "updated": sum(
                            1
                            for match in candidates
                            if match.scheduled_at.astimezone(timezone.utc).year == year
                            and isinstance((match.provider_payload or {}).get("_tbt_environment"), dict)
                        ),
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
        manifest = load_manifest(history_dir)
        manifest["last_environment_enrichment"] = {
            "target": "github-release-year-partitions",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "updated": report["updated"],
            "resolved": report["resolved"],
            "unresolved": report["unresolved"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        write_manifest(history_dir, manifest)

    report["changed_years"] = sorted(changed_years)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
