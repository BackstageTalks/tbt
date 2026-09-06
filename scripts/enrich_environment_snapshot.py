from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.services.environment import (
    OpenMeteoClient,
    environment_payload,
    location_candidates,
)

logger = logging.getLogger("tbt.enrich_environment_snapshot")


def parse_utc(value: str) -> datetime:
    text = value.strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "GitHub-only venue + historical weather enrichment. "
            "Historical archive weather is stored for research/evaluation and is not training-eligible."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True, help="Exclusive UTC end")
    parser.add_argument("--limit", type=int, default=0, help="0 = all matches in range")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--diagnostics-limit", type=int, default=100)
    parser.add_argument("--checkpoint-every", type=int, default=250)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--history-dir",
        default=str(ROOT / ".cache" / "tbt" / "history"),
    )
    args = parser.parse_args()

    if os.getenv("TBT_WEATHER_RESEARCH") != "true":
        parser.error("Set TBT_WEATHER_RESEARCH=true only for evaluation/noncommercial use")
    if args.limit < 0:
        parser.error("limit must be >= 0")

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        parser.error("--end must be later than --start")
    if end > datetime.now(timezone.utc):
        parser.error("Historical environment enrichment cannot include future timestamps")

    history_dir = Path(args.history_dir)
    store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    store.download()

    years = range(start.year, end.year + 1)
    matches = load_partitions(history_dir, years=years)
    candidates = [
        match
        for match in matches
        if start <= match.scheduled_at.astimezone(timezone.utc) < end
        and match.is_completed
    ]
    candidates.sort(key=lambda m: (m.scheduled_at, str(m.match_id)))
    if args.limit > 0:
        candidates = candidates[: args.limit]

    report: dict[str, Any] = {
        "target": "private-github-release:tbt-data-v1",
        "supabase_used": False,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "matches_in_scope": len(candidates),
        "inspected": 0,
        "already_enriched": 0,
        "resolved": 0,
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(args.dry_run),
        "weather_policy": "historical_archive_posthoc_research_only",
        "training_eligible_weather": False,
        "resolved_details": [],
        "unresolved_details": [],
        "error_details": [],
    }

    client = OpenMeteoClient(request_limit=None)
    changed_years: set[int] = set()
    published_years: set[int] = set()
    dirty_since_checkpoint = 0

    def checkpoint() -> None:
        nonlocal dirty_since_checkpoint
        if args.dry_run or not changed_years:
            dirty_since_checkpoint = 0
            return
        paths: list[Path] = []
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
                        "training_eligible_weather": False,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            paths.append(history_dir / f"history-{year}.parquet")
        paths.append(history_dir / "history_manifest.json")
        store.upload_bundle(paths)
        published_years.update(changed_years)
        changed_years.clear()
        dirty_since_checkpoint = 0

    try:
        for match in candidates:
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

            detail = {
                "match_id": match.match_id,
                "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                "tour": match.tour,
                "tournament": match.tournament,
                "location_candidates": location_candidates(payload, match.tournament),
            }

            try:
                env = environment_payload(
                    client,
                    payload,
                    match.tournament,
                    match.scheduled_at,
                    include_weather=(match.indoor is not True),
                )
            except Exception as exc:
                report["errors"] += 1
                if len(report["error_details"]) < args.diagnostics_limit:
                    report["error_details"].append(
                        {**detail, "error": f"{type(exc).__name__}: {exc}"}
                    )
                continue

            payload["_tbt_environment"] = env
            if env.get("venue_resolved") is True:
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
                dirty_since_checkpoint += 1
                if dirty_since_checkpoint >= args.checkpoint_every:
                    checkpoint()

        checkpoint()
    finally:
        client.close()

    report["open_meteo_requests"] = client.request_count
    report["changed_years"] = sorted(published_years | changed_years)
    report_path = history_dir / "environment_enrichment_report.json"
    _write_report(report_path, report)
    if not args.dry_run:
        store.upload_bundle([report_path])
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
