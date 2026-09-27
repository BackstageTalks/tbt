"""Offline recovery of archived BlinQ facts. ZERO Tennis/Open-Meteo API calls.

Sources: already committed match payloads, verified historical venues, and (if
enabled) the freely downloaded GeoNames *static* cities500 ZIP, not a geocoding
API. Never infer a player's pre-match inputs from their own final result.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from geonames_fallback import GeoNamesFallback
from release_store import ReleaseStore
from enrich_environment_snapshot import _build_venue_knowledge, _learned_environment
from tbt.data.history_snapshot import load_partitions, sync_year_partition
from tbt.data.history_safety import sanitize_history_identities
from tbt.errors import ProviderError
from tbt.match_format import exact_best_of_from_score_stats, explicit_best_of_from_event
from tbt.providers.score import parse_event_score
from tbt.services.countries import normalize_country_code
from tbt.services.environment import (
    ENVIRONMENT_RESOLVER_VERSION, ENVIRONMENT_SCHEMA_VERSION,
    explicit_country_hints, location_candidates, venue_context_compatible,
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _direct_indoor(match) -> tuple[bool | None, str]:
    """Only explicit archived labels; unknown or conflicting labels stay unknown."""
    raw = _dict(match.provider_payload)
    event = _dict(raw.get("event"))
    tourney = _dict(raw.get("tournament"))
    venue = _dict(raw.get("venue"))
    court = _dict(tourney.get("court"))
    observations: set[bool] = set()
    evidence: list[str] = []

    def parse(value: Any, *, field: str, allow_surface: bool = False) -> None:
        result = None
        if isinstance(value, bool):
            result = value
        elif isinstance(value, str):
            token = " ".join(value.casefold().replace("_", " ").split())
            if token in {"true", "indoor", "indoors", "inside", "1"}:
                result = True
            elif token in {"false", "outdoor", "outdoors", "outside", "0"}:
                result = False
            elif allow_surface and ("indoor" in token or "outdoor" in token):
                # Only literal, explicit wording; hard/clay/grass alone proves nothing.
                result = "indoor" in token
        if result is not None:
            observations.add(result)
            evidence.append(field)

    if str(match.surface or "").casefold() == "indoor_hard":
        parse(True, field="normalized_surface_indoor_hard")
    for label, source in (("match", raw), ("event", event), ("tournament", tourney),
                          ("venue", venue), ("court", court)):
        for key in ("indoor", "isIndoor", "is_indoor", "outdoor", "isOutdoor"):
            if key in source:
                value = source[key]
                if key.lower().endswith("outdoor"):
                    # An isOutdoor=true flag means indoor=false, including
                    # serialized string booleans. Do not reinterpret unknown text.
                    if isinstance(value, bool):
                        value = not value
                    elif isinstance(value, str) and value.strip().casefold() in {
                        "true", "false", "1", "0"
                    }:
                        value = value.strip().casefold() in {"false", "0"}
                    else:
                        continue
                parse(value, field=f"{label}.{key}")
        for key in ("groundType", "ground_type", "surface", "name", "type"):
            # A venue's name may contain "Indoor Arena" but does NOT prove
            # the court used for the event was indoor: exclude that source.
            if key in source and label in ("match", "event", "court", "tournament"):
                parse(source[key], field=f"{label}.{key}", allow_surface=True)
    if len(observations) > 1:
        return None, "conflicting_explicit_indoor_sources"
    if observations:
        return observations.pop(), "explicit_archived:" + ",".join(evidence[:5])
    return None, "no_explicit_indoor_evidence"


def _score_from_archived_event(match) -> tuple[dict[str, float], int | None, str]:
    """Require a finished event, exact two-player identity and score/winner proof."""
    if not match.is_completed or str(match.status or "").strip().casefold() in {
        "retired", "walkover", "walk over", "cancelled", "canceled",
        "abandoned", "interrupted", "suspended", "postponed",
    }:
        return {}, None, "ineligible"
    raw = _dict(match.provider_payload)
    event = _dict(raw.get("event")) or raw
    if not (_dict(event.get("homeScore")) and _dict(event.get("awayScore"))):
        return {}, None, "no_archived_structured_score"
    marker = _dict(raw.get("_tbt_score"))
    if marker.get("status") in {"identity_mismatch", "format_conflict", "unsupported_format"}:
        return {}, None, "previously_rejected_score"
    home = str(_dict(event.get("homeTeam")).get("id") or "")
    away = str(_dict(event.get("awayTeam")).get("id") or "")
    identity = _dict(raw.get("_tbt_event_identity"))
    if not home or not away:
        # Previously provider-verified identity may be preserved separately.
        if identity.get("status") == "finished":
            home, away = str(identity.get("home") or ""), str(identity.get("away") or "")
    if not home or not away or home == away or {home, away} != {
        str(match.player1_id), str(match.player2_id)
    }:
        return {}, None, "unverified_or_conflicting_identity"
    status = event.get("status")
    status = str(_dict(status).get("type") or _dict(status).get("name")
                 or (status if isinstance(status, str) else "")).casefold()
    if status not in {"finished", "completed", "ended", "ft", "final"}:
        return {}, None, "not_explicitly_finished"
    try:
        stats = parse_event_score(event, home_is_player1=(home == str(match.player1_id)))
        if not stats:
            return {}, None, "unsupported_structured_score"
        exact, origin = exact_best_of_from_score_stats(stats)
        if exact not in {3, 5}:
            return {}, None, "score_cannot_prove_format"
        provider = explicit_best_of_from_event(event)
        if provider in {3, 5} and provider != exact:
            return {}, None, "score_provider_format_conflict"
        full = parse_event_score(event, home_is_player1=(home == str(match.player1_id)),
                                 best_of=exact)
    except (ProviderError, TypeError, ValueError):
        return {}, None, "invalid_structured_score"
    predicted_winner = str(match.player1_id) if full["p1_sets_won"] > full["p2_sets_won"] else str(match.player2_id)
    if predicted_winner != str(match.winner_id):
        return {}, None, "score_winner_conflict"
    existing = _dict(match.stats)
    for key, value in full.items():
        observed = existing.get(key)
        if observed is not None:
            try:
                if abs(float(observed) - float(value)) > 1e-8:
                    return {}, None, "existing_score_conflict"
            except (ValueError, TypeError):
                return {}, None, "invalid_existing_score"
    return full, exact, "archived_event_structured_score:" + origin


def _geo_candidates(match) -> list[str]:
    """Only city + a single provider/ITF-backed country, never countryless guessing."""
    hints = explicit_country_hints(_dict(match.provider_payload), str(match.tournament or ""))
    if len(hints) != 1:
        return []
    code = next(iter(hints))
    out = []
    for query in location_candidates(_dict(match.provider_payload), str(match.tournament or "")):
        parts = [x.strip() for x in query.split(",") if x.strip()]
        if len(parts) < 2 or normalize_country_code(parts[-1]) != code:
            continue
        city = parts[0]
        if len(city) < 2 or len(city) > 65 or any(x.isdigit() for x in city):
            continue
        if query not in out:
            out.append(query)
    return out[:5]


def _verified_archive_venue(fallback: GeoNamesFallback, match, queries: list[str]):
    raw = _dict(match.provider_payload)
    country = next(iter(explicit_country_hints(raw, match.tournament)))
    positives: dict[tuple[float, float], tuple[Any, str]] = {}
    for query in queries:
        venue = fallback.resolve(query, country)
        if venue is None:
            continue
        compatible, _ = venue_context_compatible(raw, match.tournament, asdict(venue))
        if not compatible:
            continue
        signature = round(venue.latitude, 4), round(venue.longitude, 4)
        positives[signature] = venue, query
    # Two distinct cities match the archived text; do not pick the first.
    if len(positives) != 1:
        return None, "ambiguous" if len(positives) > 1 else "not_in_archive"
    venue, query = next(iter(positives.values()))
    return {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
        "venue_resolved": True,
        "location_query": query,
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "geonames-static-archive",
        "source_attribution": "GeoNames CC BY 4.0, https://download.geonames.org/export/dump/cities500.zip",
        "weather_provenance": "not_requested_static_only",
        "training_eligible_weather": False,
        "venue": asdict(venue),
    }, "verified_unique_city_country"


def recover(matches: list, *, use_gazetteer: bool, report: dict) -> set[int]:
    changed_years: set[int] = set()
    counts = Counter()
    complete_before = sum(x.indoor is not None for x in matches)
    venue_before = sum(_dict(_dict(x.provider_payload).get("_tbt_environment")).get("venue_resolved") is True for x in matches)
    score_before = sum(all(_dict(x.stats).get(key) is not None for key in ("total_sets", "total_games", "p1_set1_games", "p2_set1_games")) for x in matches)

    # Stage 1: archived explicit match facts. No request to any outside service.
    for match in matches:
        if match.indoor is None:
            indoor, provenance = _direct_indoor(match)
            if indoor is not None:
                match.indoor = indoor
                changed_years.add(match.scheduled_at.year)
                counts["indoor_explicit_added"] += 1
                counts[provenance] += 1
            elif provenance.startswith("conflicting"):
                counts["indoor_conflict"] += 1
        score, exact, provenance = _score_from_archived_event(match)
        if score:
            old = _dict(match.stats)
            missing = sum(old.get(key) is None for key in score)
            if missing or match.best_of != exact:
                match.stats = {**old, **score}
                raw = dict(_dict(match.provider_payload))
                raw["_tbt_match_format"] = {
                    "schema": 2, "status": "verified", "best_of": exact,
                    "source": "archived_structured_final_score",
                }
                raw["_tbt_score"] = {
                    "schema": 3, "status": "available", "best_of": exact,
                    "best_of_source": "archived_structured_final_score",
                    "identity_verified": True, "format_verified": True,
                    "source": "archived_event_payload_no_requests",
                    "event_id": str(raw.get("_tbt_provider_event_id") or raw.get("event_id") or ""),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                match.provider_payload = raw
                match.best_of = exact
                changed_years.add(match.scheduled_at.year)
                counts["score_rows_repaired"] += 1
                counts["score_new_fields"] += missing
        elif provenance in {"score_winner_conflict", "score_provider_format_conflict",
                            "unverified_or_conflicting_identity", "existing_score_conflict"}:
            counts[provenance] += 1

    # Stage 2: exact, country-scoped city from the free *static* public archive.
    pending: list[tuple[Any, list[str]]] = []
    if use_gazetteer:
        for match in matches:
            env = _dict(_dict(match.provider_payload).get("_tbt_environment"))
            if env.get("venue_resolved") is True:
                continue
            queries = _geo_candidates(match)
            if queries:
                pending.append((match, queries))
        counts["gazetteer_candidates"] = len(pending)
        if pending:
            wanted = {q.split(",", 1)[0].strip() for _, qs in pending for q in qs}
            fallback = GeoNamesFallback(wanted_names=wanted)
            for match, queries in pending:
                env, status = _verified_archive_venue(fallback, match, queries)
                if env:
                    raw = dict(_dict(match.provider_payload))
                    previous = _dict(raw.get("_tbt_environment"))
                    # Never discard prior provenance or weather evidence.
                    raw["_tbt_environment"] = {**previous, **env}
                    match.provider_payload = raw
                    changed_years.add(match.scheduled_at.year)
                    counts["gazetteer_venues_added"] += 1
                elif status == "ambiguous":
                    counts["gazetteer_ambiguous"] += 1
            report["gazetteer"] = {
                "source": "GeoNames static cities500.zip CC BY 4.0; one ZIP GET, ZERO APIs",
                "archive_downloads": fallback.archive_downloads,
                "archive_error": fallback.load_error,
                "unique_requested_names": len(wanted),
            }

    # Stage 3: transitive verified venue recovery from canonical positive cache.
    # Build once after Gazetteer additions; reject country/city contradictions.
    knowledge = _build_venue_knowledge(matches)
    counts["cache_rejected_observations"] = knowledge.rejected_observations
    for match in matches:
        old = _dict(_dict(match.provider_payload).get("_tbt_environment"))
        if old.get("venue_resolved") is True:
            continue
        learned, key = knowledge.lookup(match, _dict(match.provider_payload))
        if learned is None:
            continue
        from enrich_environment_snapshot import _venue_object
        venue = _venue_object(learned)
        if venue is None or not venue_context_compatible(_dict(match.provider_payload),
                                                          match.tournament, asdict(venue))[0]:
            counts["cache_conflict_or_invalid"] += 1
            continue
        raw = dict(_dict(match.provider_payload))
        raw["_tbt_environment"] = {**old,
            "schema_version": ENVIRONMENT_SCHEMA_VERSION,
            "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
            "venue_resolved": True, "venue": asdict(venue),
            "source": "verified-history-venue-cache",
            "location_query": f"history-cache:{key}",
            "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
            "weather_provenance": "not_requested_static_only",
            "training_eligible_weather": False,
        }
        match.provider_payload = raw
        changed_years.add(match.scheduled_at.year)
        counts["history_cache_venues_added"] += 1

    report["counts"] = dict(counts)
    report["before"] = {
        "matches": len(matches), "known_indoor_outdoor": complete_before,
        "verified_venues": venue_before, "structured_scores": score_before,
    }
    report["after"] = {
        "known_indoor_outdoor": sum(x.indoor is not None for x in matches),
        "verified_venues": sum(_dict(_dict(x.provider_payload).get("_tbt_environment")).get("venue_resolved") is True for x in matches),
        "structured_scores": sum(all(_dict(x.stats).get(key) is not None for key in ("total_sets", "total_games", "p1_set1_games", "p2_set1_games")) for x in matches),
    }
    return changed_years


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    ap.add_argument("--apply", action="store_true", help="Write only verified positive improvements to private history")
    ap.add_argument("--no-static-gazetteer", action="store_true", help="For strict air-gapped/zero HTTP mode")
    ap.add_argument("--report", default=".cache/tbt/offline-archive/recovery.json")
    args = ap.parse_args()
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "provider_api_requests": 0, "open_meteo_requests": 0,
        "static_gazetteer_download_allowed": not args.no_static_gazetteer,
        "model_promotion": False, "weather_training_eligible": False,
    }
    store = ReleaseStore(args.data_repository, "tbt-data-v1", ROOT / ".cache/tbt/offline-archive/history")
    store.download()
    matches, identity = sanitize_history_identities(load_partitions(store.directory))
    report["identity_safety"] = identity
    if identity.get("changed"):
        raise RuntimeError("Canonical identity not clean; refusing implicit identity mutation")
    changed = recover(matches, use_gazetteer=not args.no_static_gazetteer, report=report)
    report["changed_years"] = sorted(changed)
    report["writes"] = False
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.apply and changed:
        bundle: list[Path] = []
        for year in sorted(changed):
            part, _ = sync_year_partition(matches, store.directory, year,
                extra_manifest={"coverage_status": "offline_archived_fact_recovery"})
            if part:
                bundle.append(part)
        bundle.append(store.directory / "history_manifest.json")
        store.upload_bundle(bundle)
        report["writes"] = True
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("mode", "counts", "before", "after", "changed_years", "writes", "gazetteer") if k in report},
                     indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
