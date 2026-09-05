from __future__ import annotations

import argparse
import calendar
import json
import logging
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import (
    load_snapshot,
    merge_provider_context,
    minimize_provider_payload,
    write_snapshot,
)
from tbt.providers.rapidapi import RapidTennisClient
from tbt.schemas import MatchRecord

logger = logging.getLogger("tbt.bootstrap_history_release")

COLD_HISTORY_END = date(2025, 1, 1)


def _provider_event_id(match: MatchRecord) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
        "id",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    value = event.get("id")
    return str(value) if value not in (None, "") else None


def _signature(match: MatchRecord) -> tuple[str, str, tuple[str, str], str]:
    return (
        str(match.tour or "").lower(),
        match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
        tuple(sorted((str(match.player1_id or ""), str(match.player2_id or "")))),
        str(match.round_name or "").strip().lower(),
    )


def _stats_score(match: MatchRecord) -> int:
    stats = match.stats if isinstance(match.stats, dict) else {}
    return sum(value not in (None, "") for value in stats.values())


def _richness(match: MatchRecord) -> tuple[int, int, int, int]:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    env = payload.get("_tbt_environment")
    environment_score = 2 if isinstance(env, dict) and env.get("venue_resolved") else int(bool(env))
    normalized = sum(
        value not in (None, "", "unknown")
        for value in (
            match.tournament,
            match.tournament_id,
            match.tournament_level,
            match.round_name,
            match.surface,
            match.status,
            match.best_of,
            match.indoor,
            match.player1_rank,
            match.player2_rank,
        )
    )
    context_score = len(minimize_provider_payload(payload))
    return (environment_score, _stats_score(match), normalized, context_score)


def _merge_stats(existing: MatchRecord, incoming: MatchRecord) -> dict[str, Any]:
    result = dict(existing.stats or {})
    for key, value in (incoming.stats or {}).items():
        if value not in (None, ""):
            result[key] = value
    return result


def _merge_record(existing: MatchRecord, incoming: MatchRecord) -> MatchRecord:
    # Prefer the richer normalized representation, but never throw away an existing
    # resolved environment payload or populated statistics.
    prefer_incoming = _richness(incoming) >= _richness(existing)
    base = deepcopy(incoming if prefer_incoming else existing)
    other = existing if prefer_incoming else incoming

    merged_payload = merge_provider_context(
        existing.provider_payload,
        incoming.provider_payload,
    )
    merged_stats = _merge_stats(existing, incoming)

    # Fill occasional sparse provider fields from the other representation.
    updates: dict[str, Any] = {
        "provider_payload": merged_payload,
        "stats": merged_stats,
    }
    for field in (
        "tournament",
        "tournament_id",
        "tournament_level",
        "round_name",
        "surface",
        "status",
        "player1_rank",
        "player2_rank",
        "best_of",
        "indoor",
    ):
        current = getattr(base, field)
        candidate = getattr(other, field)
        if current in (None, "", "unknown") and candidate not in (None, "", "unknown"):
            updates[field] = candidate

    if not base.winner_id and other.winner_id:
        updates["winner_id"] = other.winner_id

    return replace(base, **updates)


def _dedupe(matches: list[MatchRecord]) -> list[MatchRecord]:
    by_match: dict[str, MatchRecord] = {}
    for match in matches:
        key = str(match.match_id)
        if key in by_match:
            by_match[key] = _merge_record(by_match[key], match)
        else:
            by_match[key] = deepcopy(match)

    by_provider: dict[str, MatchRecord] = {}
    without_provider: list[MatchRecord] = []
    for match in by_match.values():
        provider_id = _provider_event_id(match)
        if provider_id:
            if provider_id in by_provider:
                by_provider[provider_id] = _merge_record(by_provider[provider_id], match)
            else:
                by_provider[provider_id] = match
        else:
            without_provider.append(match)

    # Conservative fallback for rows where the provider id is absent/different.
    by_signature: dict[tuple[str, str, tuple[str, str], str], MatchRecord] = {}
    for match in list(by_provider.values()) + without_provider:
        sig = _signature(match)
        if sig in by_signature:
            by_signature[sig] = _merge_record(by_signature[sig], match)
        else:
            by_signature[sig] = match

    result = list(by_signature.values())
    result.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))
    return result


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _period(range_start: date, range_end: date):
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    range_end = min(range_end, yesterday, COLD_HISTORY_END - timedelta(days=1))
    current = date(range_start.year, range_start.month, 1)
    while current <= range_end:
        month_start = max(current, range_start)
        month_end = min(
            date(current.year, current.month, calendar.monthrange(current.year, current.month)[1]),
            range_end,
        )
        yield current.year, current.month, month_start, month_end
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _full_month_key(range_start: date, range_end: date) -> str | None:
    if range_start.year != range_end.year or range_start.month != range_end.month:
        return None
    expected_end = date(
        range_start.year,
        range_start.month,
        calendar.monthrange(range_start.year, range_start.month)[1],
    )
    if range_start.day == 1 and range_end == expected_end:
        return f"{range_start.year:04d}-{range_start.month:02d}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch cold tennis history directly from RapidAPI and merge it into the "
            "private GitHub Release snapshot. Supabase is deliberately not used."
        )
    )
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--start-date", help="Inclusive YYYY-MM-DD; preferred for monthly checkpoints")
    parser.add_argument("--end-date", help="Inclusive YYYY-MM-DD; preferred for monthly checkpoints")
    parser.add_argument("--force", action="store_true", help="Re-fetch a month already marked complete")
    parser.add_argument(
        "--snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    parser.add_argument(
        "--meta",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.meta.json"),
    )
    args = parser.parse_args()

    if bool(args.start_date) != bool(args.end_date):
        raise SystemExit("--start-date and --end-date must be provided together")
    if args.start_date:
        range_start = _parse_date(args.start_date)
        range_end = _parse_date(args.end_date)
    else:
        if args.start_year is None or args.end_year is None:
            raise SystemExit("Provide either --start-date/--end-date or --start-year/--end-year")
        if args.start_year > args.end_year:
            raise SystemExit("--start-year must be <= --end-year")
        range_start = date(args.start_year, 1, 1)
        range_end = date(args.end_year, 12, 31)

    if range_end < range_start:
        raise SystemExit("history range end must be >= start")
    if range_end >= COLD_HISTORY_END:
        raise SystemExit(
            "V20.4 safety stop: direct cold-history bootstrap is restricted to 2024 and older. "
            "Keep 2025+ in the Supabase hot tier."
        )

    snapshot_path = Path(args.snapshot)
    meta_path = Path(args.meta)
    if not snapshot_path.is_file():
        raise SystemExit(
            "V20.4 safety stop: the existing GitHub training_snapshot.parquet was not downloaded. "
            "Refusing to build a replacement from a partial provider range."
        )

    previous_meta = _load_meta(meta_path)
    completed_months = {
        str(value)
        for value in previous_meta.get("completed_direct_provider_months", [])
        if value
    }
    full_month_key = _full_month_key(range_start, range_end)
    if full_month_key and full_month_key in completed_months and not args.force:
        print(
            json.dumps(
                {
                    "mode": "provider-direct-cold-history",
                    "supabase_used": False,
                    "skipped": True,
                    "reason": "month already marked complete",
                    "month": full_month_key,
                },
                indent=2,
            )
        )
        return

    existing = load_snapshot(snapshot_path)
    combined = list(existing)
    provider = RapidTennisClient()
    report: dict[str, Any] = {
        "mode": "provider-direct-cold-history",
        "supabase_used": False,
        "start": range_start.isoformat(),
        "end": range_end.isoformat(),
        "existing_rows": len(existing),
        "provider_rows_fetched": 0,
        "months": {},
    }

    try:
        for year, month, month_start, month_end in _period(range_start, range_end):
            month_matches: list[MatchRecord] = []
            month_key = f"{year:04d}-{month:02d}"
            month_report: dict[str, Any] = {"atp": 0, "wta": 0, "deduped": 0}

            for tour in ("atp", "wta"):
                logger.info(
                    "Direct GitHub history fetch %s %s -> %s",
                    tour.upper(),
                    month_start,
                    month_end,
                )
                fetched = provider.historical_period(tour, month_start, month_end)
                completed = [m for m in fetched if m.is_completed and m.winner_id]
                month_report[tour] = len(completed)
                month_matches.extend(completed)

            month_matches = _dedupe(month_matches)
            month_report["deduped"] = len(month_matches)
            report["provider_rows_fetched"] += len(month_matches)
            report["months"][month_key] = month_report

            combined = _dedupe(combined + month_matches)
            logger.info(
                "%s merged %s canonical rows; snapshot now has %s rows",
                month_key,
                len(month_matches),
                len(combined),
            )
    finally:
        report["rapidapi_requests"] = getattr(provider, "request_count", None)
        report["rapidapi_remaining"] = getattr(provider, "rate_limit_remaining", None)
        report["rapidapi_limit"] = getattr(provider, "rate_limit_limit", None)
        provider.close()

    snapshot_meta = write_snapshot(combined, snapshot_path)
    snapshot_meta.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "provider-direct-cold-history",
            "source": "RapidAPI -> normalized private GitHub Release snapshot (Supabase bypassed)",
            "source_updated_at_max": previous_meta.get("source_updated_at_max"),
            "storage_policy": {
                "cold_history_before": COLD_HISTORY_END.isoformat(),
                "cold_history_store": "private GitHub Release",
                "hot_history_from": COLD_HISTORY_END.isoformat(),
                "hot_history_store": "Supabase operational DB + GitHub training snapshot",
            },
            "last_environment_enrichment": previous_meta.get("last_environment_enrichment"),
            "last_direct_provider_backfill": {
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
                "rows_fetched": report["provider_rows_fetched"],
                "rapidapi_requests": report.get("rapidapi_requests"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
    if full_month_key:
        completed_months.add(full_month_key)
    snapshot_meta["completed_direct_provider_months"] = sorted(completed_months)
    meta_path.write_text(
        json.dumps(snapshot_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report["final_rows"] = snapshot_meta["rows"]
    report["snapshot_sha256"] = snapshot_meta["sha256"]
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
