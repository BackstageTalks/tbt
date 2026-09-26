from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from geonames_fallback import GeoNamesFallback
from tbt.services.countries import normalize_country_code
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.history_safety import sanitize_history_identities
from tbt.services.environment import (
    ENVIRONMENT_RESOLVER_VERSION,
    ENVIRONMENT_SCHEMA_VERSION,
    OpenMeteoBudgetExceeded,
    OpenMeteoClient,
    Venue,
    environment_payload,
    location_candidates,
    venue_learning_keys,
    venue_context_compatible,
    explicit_country_hints,
    strong_location_name_hints,
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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _venue_signature(venue: dict[str, Any]) -> tuple[float, float] | None:
    try:
        latitude = float(venue.get("latitude"))
        longitude = float(venue.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    # City-level geocoding can differ by a few metres between snapshots.  Four
    # decimals is precise enough for environment/weather reuse without creating
    # artificial conflicts from insignificant coordinate drift.
    return (round(latitude, 4), round(longitude, 4))


def _venue_object(value: dict[str, Any]) -> Venue | None:
    sig = _venue_signature(value)
    if sig is None:
        return None
    latitude, longitude = sig
    elevation = value.get("elevation_m")
    try:
        elevation_value = float(elevation) if elevation not in (None, "") else None
    except (TypeError, ValueError):
        elevation_value = None
    return Venue(
        query=str(value.get("query") or value.get("name") or "history-cache"),
        name=str(value.get("name") or value.get("query") or "Resolved venue"),
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation_value,
        timezone=str(value.get("timezone")) if value.get("timezone") else None,
        country=str(value.get("country")) if value.get("country") else None,
    )


class VenueKnowledge:
    """In-memory positive venue cache learned from the private history release.

    No new persistence layer is required: resolved ``_tbt_environment`` records
    are the durable positive cache.  On every run we rebuild a conservative
    index and only reuse a key when historical observations agree strongly.
    """

    def __init__(self) -> None:
        self._counts: dict[str, Counter[tuple[float, float]]] = defaultdict(Counter)
        self._representatives: dict[tuple[str, tuple[float, float]], dict[str, Any]] = {}
        self.observations = 0
        self.rejected_observations = 0
        self.rejected_reasons: Counter[str] = Counter()

    def add(self, match: Any, payload: dict[str, Any], venue: dict[str, Any]) -> None:
        signature = _venue_signature(venue)
        if signature is None:
            return
        compatible, reason = venue_context_compatible(
            payload,
            str(getattr(match, "tournament", "") or ""),
            venue,
        )
        if not compatible:
            self.rejected_observations += 1
            self.rejected_reasons[reason] += 1
            return
        keys = venue_learning_keys(
            payload,
            str(getattr(match, "tournament", "") or ""),
            tour=str(getattr(match, "tour", "") or ""),
            tournament_id=getattr(match, "tournament_id", None),
        )
        if not keys:
            return
        clean_venue = deepcopy(venue)
        for key in keys:
            self._counts[key][signature] += 1
            self._representatives[(key, signature)] = clean_venue
        self.observations += 1

    def lookup(self, match: Any, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        keys = venue_learning_keys(
            payload,
            str(getattr(match, "tournament", "") or ""),
            tour=str(getattr(match, "tour", "") or ""),
            tournament_id=getattr(match, "tournament_id", None),
        )
        for key in keys:
            counts = self._counts.get(key)
            if not counts:
                continue
            total = sum(counts.values())
            top_signature, top_count = counts.most_common(1)[0]
            # One unique historical location is accepted immediately.  Conflicted
            # keys require overwhelming repeated evidence; otherwise we fail closed.
            if len(counts) == 1 or (top_count >= 3 and top_count / max(1, total) >= 0.95):
                venue = self._representatives.get((key, top_signature))
                if venue:
                    compatible, _ = venue_context_compatible(
                        payload,
                        str(getattr(match, "tournament", "") or ""),
                        venue,
                    )
                    if compatible:
                        return deepcopy(venue), key
        return None, None

    @property
    def reusable_keys(self) -> int:
        count = 0
        for values in self._counts.values():
            total = sum(values.values())
            top_count = values.most_common(1)[0][1]
            if len(values) == 1 or (top_count >= 3 and top_count / max(1, total) >= 0.95):
                count += 1
        return count


def _build_venue_knowledge(matches: list[Any]) -> VenueKnowledge:
    knowledge = VenueKnowledge()
    for match in matches:
        payload = dict(getattr(match, "provider_payload", None) or {})
        env = _as_dict(payload.get("_tbt_environment"))
        venue = _as_dict(env.get("venue"))
        if env.get("venue_resolved") is True and venue:
            knowledge.add(match, payload, venue)
    return knowledge


def _learned_environment(
    *,
    client: OpenMeteoClient,
    match: Any,
    payload: dict[str, Any],
    knowledge: VenueKnowledge,
    include_weather: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    venue_dict, cache_key = knowledge.lookup(match, payload)
    if venue_dict is None or cache_key is None:
        return None, None
    venue = _venue_object(venue_dict)
    if venue is None:
        return None, None

    env: dict[str, Any] = {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
        "venue_resolved": True,
        "location_query": f"history-cache:{cache_key}",
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "history-venue-cache",
        "weather_provenance": "historical_archive_posthoc",
        "training_eligible_weather": False,
        "venue": asdict(venue),
    }
    if include_weather:
        env["weather"] = asdict(client.weather_at(venue, match.scheduled_at))
        env["match_hour_utc"] = match.scheduled_at.astimezone(timezone.utc).hour
    return env, cache_key


def _negative_is_cooling_down(
    existing: dict[str, Any],
    *,
    now: datetime,
    negative_retry_hours: int,
) -> bool:
    """Do not spend geocoder requests on recently confirmed negatives.

    Only a negative from this resolver version counts. New resolver versions,
    missing timestamps and explicit zero-hour retries remain eligible.
    """
    if negative_retry_hours <= 0 or existing.get("venue_resolved") is not False:
        return False
    try:
        version = int(existing.get("resolver_version") or 0)
        enriched_at = parse_utc(str(existing.get("enriched_at_utc") or ""))
    except (ValueError, TypeError):
        return False
    return (
        version >= ENVIRONMENT_RESOLVER_VERSION
        and enriched_at <= now
        and now - enriched_at < timedelta(hours=negative_retry_hours)
    )


def _needs_work(
    *,
    match: Any,
    payload: dict[str, Any],
    knowledge: VenueKnowledge,
    force: bool,
    complete_static: bool,
    retry_unresolved: bool,
    now: datetime | None = None,
    negative_retry_hours: int = 72,
) -> tuple[bool, str]:
    existing = _as_dict(payload.get("_tbt_environment"))
    has_existing = bool(existing)

    if force:
        return True, "force"

    if existing.get("venue_resolved") is True:
        stored_venue = _as_dict(existing.get("venue"))
        compatible, _ = venue_context_compatible(
            payload,
            str(getattr(match, "tournament", "") or ""),
            stored_venue,
        )
        if not compatible:
            # A previously "resolved" row that contradicts explicit country/city
            # evidence is unsafe training data. Re-run it even in ordinary resume
            # modes so a poisoned history-cache result can be repaired or cleared.
            return True, "incompatible_resolved"

    now_utc = now or datetime.now(timezone.utc)
    if complete_static:
        if existing.get("venue_resolved") is True:
            return False, "resolved"
        if not has_existing:
            return True, "missing"
        try:
            resolver_version = int(existing.get("resolver_version") or 0)
        except (TypeError, ValueError):
            resolver_version = 0
        if resolver_version < ENVIRONMENT_RESOLVER_VERSION:
            return True, "stale_unresolved"
        # New positive evidence may immediately supersede a failed attempt.
        learned, _ = knowledge.lookup(match, payload)
        if learned is not None:
            return True, "learned_unresolved"
        if not retry_unresolved:
            return False, "unresolved_current_resolver"
        if _negative_is_cooling_down(
            existing, now=now_utc, negative_retry_hours=negative_retry_hours
        ):
            return False, "negative_cooldown"
        return True, "retry_unresolved"

    if retry_unresolved:
        if not has_existing or existing.get("venue_resolved") is True:
            return False, "not_unresolved"
        if _negative_is_cooling_down(
            existing, now=now_utc, negative_retry_hours=negative_retry_hours
        ):
            return False, "negative_cooldown"
        return True, "retry_unresolved"

    if has_existing:
        return False, "already_has_environment"
    return True, "missing"


def _verified_unique_environment(
    client: OpenMeteoClient,
    provider_payload: dict[str, Any],
    tournament: str,
    query: str,
) -> tuple[dict[str, Any] | None, str]:
    """Persist ONLY compatible positive geocodes during bulk mode.

    No result, ambiguity, or a city/country mismatch is NOT a negative venue
    observation. Transient network exceptions propagate so the row is not
    modified and the operator sees the error.
    """
    venue = client.geocode(query)
    if venue is None:
        return None, "no_result"
    compatible, _ = venue_context_compatible(
        provider_payload, tournament, asdict(venue)
    )
    if not compatible:
        return None, "incompatible"
    return {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
        "venue_resolved": True,
        "location_query": query,
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "open-meteo",
        "weather_provenance": "historical_archive_posthoc",
        "training_eligible_weather": False,
        "venue": asdict(venue),
    }, "resolved"


def _verified_geonames_environment(
    fallback: GeoNamesFallback,
    provider_payload: dict[str, Any],
    tournament: str,
    query: str,
) -> tuple[dict[str, Any] | None, str]:
    """Require a unique GeoNames name, a known country and provider compatibility."""
    parts = [part.strip() for part in query.split(",") if part.strip()]
    provider_countries = explicit_country_hints(provider_payload, tournament)
    query_country = normalize_country_code(parts[-1]) if len(parts) > 1 else ""
    if query_country and provider_countries and provider_countries != {query_country}:
        return None, "fallback_country_conflict"
    country = query_country or (
        next(iter(provider_countries)) if len(provider_countries) == 1 else ""
    )
    if not country:
        return None, "fallback_no_country"
    venue = fallback.resolve(query, country)
    if venue is None:
        return None, "fallback_no_result"
    compatible, reason = venue_context_compatible(
        provider_payload, tournament, asdict(venue)
    )
    if not compatible:
        return None, "fallback_" + reason
    return {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
        "venue_resolved": True,
        "location_query": query,
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "geonames-gazetteer",
        "source_attribution": (
            "GeoNames CC BY 4.0; "
            "https://download.geonames.org/export/dump/cities500.zip"
        ),
        "weather_provenance": "not_requested_static_only",
        "training_eligible_weather": False,
        "venue": asdict(venue),
    }, "resolved_geonames"


def _probe_unique_geocoder(client: OpenMeteoClient) -> dict[str, Any]:
    """Verify real provider responses before touching any historical rows.

    The probe shares the SAME Open-Meteo client and request cap with the bulk
    run; failed requests still count. A valid but empty response fails closed.
    """
    venue = client.geocode("Tokyo, JP")
    if venue is None or not (-90 <= venue.latitude <= 90 and -180 <= venue.longitude <= 180):
        raise RuntimeError("Open-Meteo health probe did not resolve Tokyo, JP")
    return {
        "query": "Tokyo, JP",
        "country": venue.country,
        "latitude": venue.latitude,
        "longitude": venue.longitude,
        "requests_used": client.request_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "GitHub-only venue + historical weather enrichment. "
            "Historical archive weather is stored for research/evaluation and is not training-eligible."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True, help="Exclusive UTC end")
    parser.add_argument("--limit", type=int, default=0, help="0 = all rows that actually need work")
    bulk_modes = parser.add_mutually_exclusive_group()
    bulk_modes.add_argument(
        "--cache-only", action="store_true",
        help="Backfill only confidently learned historical venues; NO network geocoding.",
    )
    bulk_modes.add_argument(
        "--unique-geocode", action="store_true",
        help="Geocode just the first preferred candidate for each missing venue; "
             "group repeated queries and reuse verified results.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--static-only", action="store_true",
        help="Resolve venue/coordinates/elevation/timezone only; do not fetch historical weather.",
    )
    parser.add_argument(
        "--complete-static", action="store_true",
        help=(
            "With --static-only, fill missing rows and retry unresolved rows from older resolver versions. "
            "Current-version negative results are skipped unless a positive venue can now be learned from history."
        ),
    )
    parser.add_argument("--max-requests", type=int, default=4000, help="Open-Meteo request cap for a resumable run")
    parser.add_argument(
        "--retry-unresolved",
        action="store_true",
        help=(
            "Explicit second pass: retry rows with venue_resolved=false even when they were attempted "
            "by the current resolver version."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--diagnostics-limit", type=int, default=100)
    parser.add_argument(
        "--checkpoint-every", type=int, default=1000,
        help="Publish each 1000 changed matches instead of rewriting full year parquet every 250 rows.",
    )
    parser.add_argument(
        "--checkpoint-minutes", type=int, default=10,
        help="Also checkpoint dirty data after this many minutes; 0 disables timer.",
    )
    parser.add_argument(
        "--negative-retry-hours", type=int, default=72,
        help="Cooldown for current-version unresolved geocodes in retry mode; 0 forces retry.",
    )
    parser.add_argument(
        "--yield-guard-after-requests", type=int, default=750,
        help="Check geocoder success rate after this many Open-Meteo calls; 0 disables the guard.",
    )
    parser.add_argument(
        "--min-geocoder-success-rate", type=float, default=0.005,
        help="Stop gracefully if new geocoder resolutions/calls fall below this rate.",
    )
    parser.add_argument(
        "--max-runtime-minutes",
        type=int,
        default=0,
        help=(
            "Graceful per-job runtime guard. 0 = unlimited. "
            "Use below the GitHub-hosted 6h hard limit so progress can checkpoint cleanly."
        ),
    )
    parser.add_argument(
        "--stop-at",
        default="",
        help=(
            "Optional absolute UTC/ISO deadline. The run checkpoints and exits cleanly "
            "when this instant is reached."
        ),
    )
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--history-dir",
        default=str(ROOT / ".cache" / "tbt" / "history"),
    )
    args = parser.parse_args()

    if not args.static_only and os.getenv("TBT_WEATHER_RESEARCH") != "true":
        parser.error("Set TBT_WEATHER_RESEARCH=true only when historical weather research is requested")
    if args.complete_static and not args.static_only:
        parser.error("--complete-static requires --static-only")
    if (args.cache_only or args.unique_geocode) and not args.static_only:
        parser.error("Bulk modes require --static-only to prevent weather API requests")
    if (args.cache_only or args.unique_geocode) and args.force:
        parser.error("Bulk modes cannot overwrite existing resolved venues")
    if not 1 <= args.max_requests <= 12000:
        parser.error("--max-requests must be 1..12000")
    if args.limit < 0:
        parser.error("limit must be >= 0")
    if args.max_runtime_minutes < 0:
        parser.error("--max-runtime-minutes must be >= 0")
    if args.checkpoint_every < 1 or args.checkpoint_minutes < 0:
        parser.error("Invalid checkpoint cadence")
    if args.negative_retry_hours < 0 or args.yield_guard_after_requests < 0:
        parser.error("Retry cooldown and yield-guard threshold must be >= 0")
    if not 0 <= args.min_geocoder_success_rate <= 1:
        parser.error("--min-geocoder-success-rate must be in 0..1")
    if args.force and (args.retry_unresolved or args.complete_static):
        parser.error("--force cannot be combined with --retry-unresolved/--complete-static")

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    stop_at = parse_utc(args.stop_at) if args.stop_at.strip() else None
    run_started_monotonic = time.monotonic()
    run_now_utc = datetime.now(timezone.utc)
    if end <= start:
        parser.error("--end must be later than --start")
    if end > datetime.now(timezone.utc):
        parser.error("Historical environment enrichment cannot include future timestamps")

    history_dir = Path(args.history_dir)
    store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    store.download()

    years = range(start.year, end.year + 1)
    matches, identity_safety = sanitize_history_identities(load_partitions(history_dir, years=years))
    in_scope = [
        match
        for match in matches
        if start <= match.scheduled_at.astimezone(timezone.utc) < end
        and match.is_completed
    ]
    in_scope.sort(key=lambda m: (m.scheduled_at, str(m.match_id)))

    # The existing 150k+ resolved rows become our local venue master.  This is
    # rebuilt from the durable history release and therefore survives workflows
    # without introducing a second source of truth.
    knowledge = _build_venue_knowledge(matches)

    report: dict[str, Any] = {
        "target": "private-github-release:tbt-data-v1",
        "identity_safety": identity_safety,
        "supabase_used": False,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "matches_in_scope": len(in_scope),
        "selected_for_run": 0,
        "pending_before_limit": 0,
        "inspected": 0,
        "already_enriched": 0,
        "skipped_current_resolver_unresolved": 0,
        "resolved": 0,
        "resolved_from_history_cache": 0,
        "resolved_from_geocoder": 0,
        "resolved_from_geonames": 0,
        "geonames_archive_downloads": 0,
        "geonames_archive_error": None,
        "geonames_source": "GeoNames cities500.zip, CC BY 4.0; verified small-feature exceptions",
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(args.dry_run),
        "resume_mode": (
            "force_all" if args.force else
            "complete_static" if args.complete_static else
            "retry_unresolved" if args.retry_unresolved else
            "missing_only"
        ),
        "static_only": bool(args.static_only),
        "bulk_mode": "cache_only" if args.cache_only else (
            "unique_geocode" if args.unique_geocode else None
        ),
        "cache_only_candidates": 0,
        "unique_preferred_queries": 0,
        "unique_queries_attempted": 0,
        "geocode_candidate_skipped": 0,
        "geocode_query_errors": 0,
        "geocode_no_result_skipped": 0,
        "geocode_no_result_unique": 0,
        "geocode_diagnostics": [],
        "geocode_health_probe": None,
        "geocode_health_probe_failed": False,
        "positive_only": bool(args.unique_geocode),
        "max_requests": int(args.max_requests),
        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
        "venue_cache_observations": knowledge.observations,
        "venue_cache_rejected_observations": knowledge.rejected_observations,
        "venue_cache_rejected_reasons": dict(knowledge.rejected_reasons),
        "venue_cache_reusable_keys": knowledge.reusable_keys,
        "incompatible_existing_resolved": 0,
        "repaired_incompatible_resolved": 0,
        "invalidated_incompatible_resolved": 0,
        "weather_policy": "not_requested_static_only" if args.static_only else "historical_archive_posthoc_research_only",
        "training_eligible_weather": False,
        "budget_exhausted": False,
        "negative_retry_hours": args.negative_retry_hours,
        "negative_cooldown_skipped": 0,
        "selected_reason_counts": {},
        "yield_guard_after_requests": args.yield_guard_after_requests,
        "min_geocoder_success_rate": args.min_geocoder_success_rate,
        "low_geocoder_yield_stopped": False,
        "runtime_guard_minutes": int(args.max_runtime_minutes),
        "stop_at": stop_at.isoformat() if stop_at else None,
        "runtime_guard_exhausted": False,
        "stop_at_reached": False,
        "stopped_reason": None,
        "resolved_details": [],
        "unresolved_details": [],
        "error_details": [],
    }

    pending: list[Any] = []
    pending_reasons: dict[str, str] = {}
    for match in in_scope:
        payload = dict(match.provider_payload or {})
        needs_work, reason = _needs_work(
            match=match,
            payload=payload,
            knowledge=knowledge,
            force=bool(args.force),
            complete_static=bool(args.complete_static),
            # Bulk positive-only retry revisits the false negatives generated
            # by older bulk runs immediately, without rewriting negatives.
            retry_unresolved=bool(args.retry_unresolved or args.unique_geocode),
            now=run_now_utc,
            negative_retry_hours=0 if args.unique_geocode else args.negative_retry_hours,
        )
        if needs_work:
            pending.append(match)
            pending_reasons[str(match.match_id)] = reason
            if reason == "incompatible_resolved":
                report["incompatible_existing_resolved"] += 1
        else:
            report["already_enriched"] += 1
            if reason == "unresolved_current_resolver":
                report["skipped_current_resolver_unresolved"] += 1
            elif reason == "negative_cooldown":
                report["negative_cooldown_skipped"] += 1

    report["pending_before_limit"] = len(pending)
    # Cache-only recoveries first, then missing rows and stale negatives. Leave
    # repeat geocoding of proven recent negatives until after useful work.
    priority = {
        "learned_unresolved": 0,
        "missing": 1,
        "stale_unresolved": 2,
        "incompatible_resolved": 3,
        "retry_unresolved": 4,
    }
    pending.sort(
        key=lambda match: (
            priority.get(pending_reasons[str(match.match_id)], 5),
            -match.scheduled_at.timestamp(),
            str(match.match_id),
        )
    )
    # Cache-only mode considers every pending row, including older unresolved
    # records. Never attempt a geocoder request for cache misses.
    if args.cache_only:
        pending = [
            match for match in pending
            if _as_dict(_as_dict(match.provider_payload).get("_tbt_environment")).get("venue_resolved") is not True
            and knowledge.lookup(match, dict(match.provider_payload or {}))[0] is not None
        ]
        report["cache_only_candidates"] = len(pending)
    elif args.unique_geocode:
        # Bulk mode never overwrites previously resolved positive venues.
        pending = [
            match for match in pending
            if _as_dict(_as_dict(match.provider_payload).get("_tbt_environment")).get("venue_resolved") is not True
        ]
        # Query groups are sorted by recoverable match count, not chronology.
        # Open-Meteo's positive/negative LRU then performs at most one network
        # geocode for each distinct preferred query during this job.
        preferred = {}
        counts = Counter()
        for match in pending:
            candidates = location_candidates(dict(match.provider_payload or {}), match.tournament)
            key = " ".join(candidates[0].casefold().split()) if candidates else ""
            preferred[str(match.match_id)] = key
            if key:
                counts[key] += 1
        report["unique_preferred_queries"] = len(counts)
        pending.sort(
            key=lambda match: (
                -counts[preferred[str(match.match_id)]]
                if preferred[str(match.match_id)] else 1,
                preferred[str(match.match_id)],
                str(match.match_id),
            )
        )
    if args.limit > 0:
        pending = pending[: args.limit]
    report["selected_for_run"] = len(pending)
    report["selected_reason_counts"] = dict(Counter(
        pending_reasons[str(match.match_id)] for match in pending
    ))

    client = OpenMeteoClient(request_limit=args.max_requests)
    fallback = GeoNamesFallback(wanted_names=set(counts)) if args.unique_geocode else None
    if args.unique_geocode:
        # Stop BEFORE processing history if the provider is unavailable or
        # returns an empty/malformed response to a known unambiguous city.
        try:
            report["geocode_health_probe"] = _probe_unique_geocoder(client)
        except Exception as exc:
            report["geocode_health_probe_failed"] = True
            report["stopped_reason"] = "geocoder_health_probe_failed"
            report["errors"] += 1
            report["error_details"].append({
                "step": "health_probe",
                "error": f"{type(exc).__name__}: {exc}",
            })
            report["open_meteo_requests"] = client.request_count
            _write_report(history_dir / "environment_enrichment_report.json", report)
            client.close()
            raise SystemExit(
                "Geocoder health probe failed: NO history rows changed. "
                "Review the artifact before retrying."
            ) from exc
    attempted_queries: set[str] = set()
    failed_queries: set[str] = set()
    no_result_queries: set[str] = set()
    diagnostic_queries: set[str] = set()
    changed_years: set[int] = set()
    published_years: set[int] = set()
    dirty_since_checkpoint = 0
    last_checkpoint_monotonic = time.monotonic()

    def checkpoint() -> None:
        nonlocal dirty_since_checkpoint, last_checkpoint_monotonic
        if args.dry_run or not changed_years:
            dirty_since_checkpoint = 0
            last_checkpoint_monotonic = time.monotonic()
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
                        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
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
        last_checkpoint_monotonic = time.monotonic()

    try:
        for match in pending:
            elapsed_seconds = time.monotonic() - run_started_monotonic
            if args.max_runtime_minutes and elapsed_seconds >= args.max_runtime_minutes * 60:
                report["runtime_guard_exhausted"] = True
                report["stopped_reason"] = "runtime_guard"
                checkpoint()
                break
            if stop_at is not None and datetime.now(timezone.utc) >= stop_at:
                report["stop_at_reached"] = True
                report["stopped_reason"] = "deadline"
                checkpoint()
                break

            report["inspected"] += 1
            selection_reason = pending_reasons.get(str(match.match_id), "")
            payload = dict(match.provider_payload or {})
            detail = {
                "match_id": match.match_id,
                "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                "tour": match.tour,
                "tournament": match.tournament,
                "location_candidates": location_candidates(payload, match.tournament),
            }

            try:
                env, cache_key = _learned_environment(
                    client=client,
                    match=match,
                    payload=payload,
                    knowledge=knowledge,
                    include_weather=(not args.static_only and match.indoor is not True),
                )
                if env is not None:
                    report["resolved_from_history_cache"] += 1
                    detail["venue_cache_key"] = cache_key
                elif args.cache_only:
                    # A miss is never written as unresolved and NEVER contacts
                    # Open-Meteo. Only positive historical evidence is persisted.
                    continue
                elif args.unique_geocode:
                    # Exactly one preferred candidate per match. Grouping and
                    # OpenMeteoClient.geocode's 65k LRU avoid repeated requests.
                    candidates = detail["location_candidates"]
                    if not candidates:
                        report["geocode_candidate_skipped"] += 1
                        continue
                    query = candidates[0]
                    query_key = " ".join(query.casefold().split())
                    if query_key in failed_queries:
                        report["geocode_candidate_skipped"] += 1
                        continue
                    if query_key in no_result_queries:
                        report["geocode_no_result_skipped"] += 1
                        continue
                    attempted_queries.add(query_key)
                    try:
                        env, outcome = _verified_unique_environment(
                            client, payload, match.tournament, query
                        )
                    except OpenMeteoBudgetExceeded:
                        raise
                    except Exception:
                        failed_queries.add(query_key)
                        report["geocode_query_errors"] += 1
                        raise
                    # An offline country-scoped gazetteer handles Open-Meteo
                    # misses. Keep the same strict positive-only write policy.
                    fallback_outcome = None
                    if outcome == "no_result" and fallback is not None:
                        fallback_env, fallback_outcome = _verified_geonames_environment(
                            fallback, payload, match.tournament, query
                        )
                        if fallback_env is not None:
                            env, outcome = fallback_env, "resolved_geonames"
                            report["resolved_from_geonames"] += 1
                        report["geonames_archive_downloads"] = fallback.archive_downloads
                        report["geonames_archive_error"] = fallback.load_error

                    if query_key not in diagnostic_queries and len(report["geocode_diagnostics"]) < 60:
                        diagnostic_queries.add(query_key)
                        diagnostic = {
                            "query": query,
                            "outcome": outcome,
                            "fallback_outcome": fallback_outcome,
                            "recoverable_matches": counts.get(query_key, 0),
                            "venue": (_as_dict(env.get("venue")).get("name") if env else None),
                        }
                        if outcome == "incompatible":
                            # geocode() is LRU cached: inspect the exact returned
                            # city without another provider request or any writes.
                            rejected = client.geocode(query)
                            if rejected is not None:
                                rejected_data = asdict(rejected)
                                _, mismatch = venue_context_compatible(
                                    payload, match.tournament, rejected_data
                                )
                                diagnostic.update({
                                    "mismatch": mismatch,
                                    "geocoder_name": rejected.name,
                                    "geocoder_country": rejected.country,
                                    "provider_country_hints": sorted(
                                        explicit_country_hints(payload, match.tournament)
                                    ),
                                    "provider_city_hints": sorted(
                                        strong_location_name_hints(payload, match.tournament)
                                    ),
                                })
                        elif outcome == "no_result":
                            diagnostic["alternative_candidates"] = detail["location_candidates"][1:4]
                        report["geocode_diagnostics"].append(diagnostic)
                    if outcome == "no_result":
                        no_result_queries.add(query_key)
                        report["geocode_no_result_unique"] += 1
                        report["geocode_no_result_skipped"] += 1
                        continue
                    if outcome == "incompatible":
                        report["geocode_candidate_skipped"] += 1
                        continue
                    # Only positives can reach the persistence path.
                    assert env is not None and env["venue_resolved"] is True
                    if outcome == "resolved":
                        report["resolved_from_geocoder"] += 1
                else:
                    env = environment_payload(
                        client,
                        payload,
                        match.tournament,
                        match.scheduled_at,
                        include_weather=(not args.static_only and match.indoor is not True),
                    )
                    # Keep the resolver version durable even if an older environment
                    # helper is accidentally imported by a partial deployment.
                    env["resolver_version"] = ENVIRONMENT_RESOLVER_VERSION
                    if env.get("venue_resolved") is True:
                        report["resolved_from_geocoder"] += 1
            except OpenMeteoBudgetExceeded:
                report["budget_exhausted"] = True
                checkpoint()
                break
            except Exception as exc:
                report["errors"] += 1
                if len(report["error_details"]) < args.diagnostics_limit:
                    report["error_details"].append(
                        {**detail, "error": f"{type(exc).__name__}: {exc}"}
                    )
                if args.unique_geocode and report["geocode_query_errors"] >= 3:
                    report["stopped_reason"] = "repeated_geocoder_errors"
                    checkpoint()
                    break
                continue

            payload["_tbt_environment"] = env
            if env.get("venue_resolved") is True:
                report["resolved"] += 1
                if selection_reason == "incompatible_resolved":
                    report["repaired_incompatible_resolved"] += 1
                detail["resolved_query"] = env.get("location_query")
                detail["resolved_venue"] = env.get("venue")
                if len(report["resolved_details"]) < args.diagnostics_limit:
                    report["resolved_details"].append(detail)
                # New successful geocodes immediately help later rows in the same run.
                knowledge.add(match, payload, _as_dict(env.get("venue")))
            else:
                report["unresolved"] += 1
                if selection_reason == "incompatible_resolved":
                    report["invalidated_incompatible_resolved"] += 1
                if len(report["unresolved_details"]) < args.diagnostics_limit:
                    report["unresolved_details"].append(detail)

            if not args.dry_run:
                match.provider_payload = payload
                report["updated"] += 1
                changed_years.add(match.scheduled_at.astimezone(timezone.utc).year)
                dirty_since_checkpoint += 1
                if (
                    dirty_since_checkpoint >= args.checkpoint_every
                    or (
                        args.checkpoint_minutes
                        and time.monotonic() - last_checkpoint_monotonic
                        >= args.checkpoint_minutes * 60
                    )
                ):
                    checkpoint()

            # A low-yield circuit breaker prevents thousands of repeat negative
            # geocodes, while never writing skipped matches as false negatives.
            if (
                args.yield_guard_after_requests
                and args.min_geocoder_success_rate > 0
                and client.request_count >= args.yield_guard_after_requests
                and (
                    (report["resolved_from_geocoder"] + report["resolved_from_geonames"])
                    / max(1, client.request_count) < args.min_geocoder_success_rate
                )
            ):
                report["low_geocoder_yield_stopped"] = True
                report["stopped_reason"] = "low_geocoder_yield"
                checkpoint()
                break

        checkpoint()
    finally:
        client.close()

    report["unique_queries_attempted"] = len(attempted_queries)
    report["open_meteo_requests"] = client.request_count
    geocode_cache = client.geocode.cache_info()
    report["geocode_cache_hits"] = geocode_cache.hits
    report["geocode_cache_misses"] = geocode_cache.misses
    report["geocode_cache_entries"] = geocode_cache.currsize
    report["geocoder_resolutions_per_request"] = round(
        report["resolved_from_geocoder"] / max(1, client.request_count), 6
    )
    report["elapsed_runtime_seconds"] = round(time.monotonic() - run_started_monotonic, 3)
    report["changed_years"] = sorted(published_years | changed_years)
    report["venue_cache_reusable_keys_after_run"] = knowledge.reusable_keys
    report["venue_cache_rejected_observations_after_run"] = knowledge.rejected_observations
    report["venue_cache_rejected_reasons_after_run"] = dict(knowledge.rejected_reasons)
    report_path = history_dir / "environment_enrichment_report.json"
    _write_report(report_path, report)
    if not args.dry_run:
        store.upload_bundle([report_path])
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
