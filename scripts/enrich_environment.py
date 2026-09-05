from __future__ import annotations

import argparse
import json
import os
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from _bootstrap import ROOT  # noqa: F401

from tbt.repositories.supabase import SupabaseRepository
from tbt.services.environment import (
    OpenMeteoClient,
    environment_payload,
    location_candidates,
)

logger = logging.getLogger("tbt.enrich_environment")

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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _provider_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    tournament = _as_dict(payload.get("tournament"))
    unique = _as_dict(tournament.get("uniqueTournament"))
    category = _as_dict(tournament.get("category"))
    venue = _as_dict(payload.get("venue"))
    country = _as_dict(tournament.get("country")) or _as_dict(unique.get("country"))

    return {
        "provider_event_id": payload.get("id"),
        "provider_tournament": tournament.get("name"),
        "provider_tournament_id": tournament.get("id"),
        "provider_unique_tournament": unique.get("name"),
        "provider_unique_tournament_id": unique.get("id"),
        "provider_category": category.get("name"),
        "provider_category_id": category.get("id"),
        "provider_venue": venue.get("name"),
        "provider_city": (
            venue.get("city")
            or tournament.get("city")
            or unique.get("city")
            or payload.get("city")
            or payload.get("venueCity")
        ),
        "provider_country": (
            _as_dict(venue.get("country")).get("name")
            or venue.get("countryName")
            or country.get("name")
            or payload.get("countryName")
            or _as_dict(payload.get("country")).get("name")
        ),
        "tbt_source_category_id": payload.get("_tbt_source_category_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill Open-Meteo weather/elevation into the lean Supabase "
            "match_environment table, with detailed venue-resolution diagnostics."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=50)
    parser.add_argument(
        "--diagnostics-limit",
        type=int,
        default=100,
        help="Maximum unresolved/resolved diagnostic rows included in the final JSON report.",
    )
    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be later than --start")
    if start < _hot_cutoff():
        raise SystemExit(
            "V20.7 safety stop: refusing to enrich data outside the rolling hot buffer in Supabase. "
            "Use the GitHub snapshot route instead."
        )

    repo = SupabaseRepository()
    weather = OpenMeteoClient()
    report: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "inspected": 0,
        "already_enriched": 0,
        "resolved": 0,
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(args.dry_run),
        "unresolved_details": [],
        "resolved_details": [],
        "error_details": [],
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

            candidates = location_candidates(payload, match.tournament)
            provider_diag = _provider_diagnostics(payload)

            try:
                env = environment_payload(
                    weather,
                    payload,
                    match.tournament,
                    match.scheduled_at,
                )
                payload["_tbt_environment"] = env

                detail = {
                    "match_id": match.match_id,
                    "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                    "tour": match.tour,
                    "tournament": match.tournament,
                    "tournament_id": match.tournament_id,
                    "round_name": match.round_name,
                    "player1": match.player1_name,
                    "player2": match.player2_name,
                    "location_candidates": candidates,
                    **provider_diag,
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
                    report["updated"] += repo.upsert_match_environment(
                        match.match_id,
                        match.scheduled_at,
                        env,
                    )

            except Exception as exc:
                report["errors"] += 1
                logger.warning(
                    "Environment enrichment failed match=%s tournament=%r: %s",
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
                            "tournament_id": match.tournament_id,
                            "location_candidates": candidates,
                            "error": f"{type(exc).__name__}: {exc}",
                            **provider_diag,
                        }
                    )

            if index % 250 == 0:
                logger.info(
                    "Progress %s/%s resolved=%s unresolved=%s errors=%s",
                    index,
                    len(matches),
                    report["resolved"],
                    report["unresolved"],
                    report["errors"],
                )

            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)

    finally:
        weather.close()

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
