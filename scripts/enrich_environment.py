from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone

from _bootstrap import ROOT  # noqa: F401

from tbt.repositories.supabase import SupabaseRepository
from tbt.services.environment import OpenMeteoClient, environment_payload

logger = logging.getLogger("tbt.enrich_environment")


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
        description="Backfill Open-Meteo weather/elevation into match provider_payload."
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=50)
    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be later than --start")

    repo = SupabaseRepository()
    weather = OpenMeteoClient()
    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "inspected": 0,
        "already_enriched": 0,
        "resolved": 0,
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(args.dry_run),
    }

    try:
        matches = repo.get_matches_between(start, end, completed_only=True)
        if args.limit > 0:
            matches = matches[: args.limit]

        for index, match in enumerate(matches, start=1):
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

            try:
                env = environment_payload(
                    weather,
                    payload,
                    match.tournament,
                    match.scheduled_at,
                )
                payload["_tbt_environment"] = env

                if env.get("venue_resolved"):
                    report["resolved"] += 1
                else:
                    report["unresolved"] += 1

                if not args.dry_run:
                    report["updated"] += repo.update_match_provider_payload(
                        match.match_id,
                        payload,
                    )
            except Exception as exc:
                report["errors"] += 1
                logger.warning(
                    "Environment enrichment failed match=%s tournament=%r: %s",
                    match.match_id,
                    match.tournament,
                    exc,
                )

            if index % 250 == 0:
                logger.info("Progress %s/%s: %s", index, len(matches), report)

            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)
    finally:
        weather.close()

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
