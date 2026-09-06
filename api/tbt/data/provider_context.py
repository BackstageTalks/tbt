from __future__ import annotations

from typing import Any


def _compact_country(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        compact = {
            key: value.get(key)
            for key in ("id", "name", "alpha2", "alpha3")
            if value.get(key) not in (None, "")
        }
        return compact or None
    if value not in (None, ""):
        return {"name": str(value)}
    return None


def minimize_provider_payload(
    payload: Any,
    *,
    include_environment: bool = True,
) -> dict[str, Any]:
    """Return the tiny provider context TBT needs after normalisation.

    Deliberately drops the raw provider response.  The compact result is safe for
    long-lived GitHub Parquet history and release artifacts. Tennis data is not
    stored in Supabase; Supabase is reserved for authentication/account data.
    """
    raw = payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = {}
    identity = raw.get("_tbt_event_identity")
    if isinstance(identity, dict):
        out["_tbt_event_identity"] = {k: identity[k] for k in
            ("event_id", "home", "away", "status") if k in identity}
    provenance = raw.get("_tbt_rank_provenance")
    if isinstance(provenance, dict):
        out["_tbt_rank_provenance"] = {
            key: provenance[key] for key in ("point_in_time", "source", "as_of")
            if key in provenance
        }
    marker = raw.get("_tbt_statistics")
    if isinstance(marker, dict):
        out["_tbt_statistics"] = {k: marker[k] for k in
            ("schema", "event_id", "source", "fetched_at", "status") if k in marker}

    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
        "id",
        "_tbt_source_category_id",
        "_tbt_source_category_name",
    ):
        if raw.get(key) not in (None, ""):
            out[key] = raw.get(key)

    event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    if event.get("id") not in (None, ""):
        out["event"] = {"id": event.get("id")}

    tournament = raw.get("tournament") if isinstance(raw.get("tournament"), dict) else {}
    unique = (
        tournament.get("uniqueTournament")
        if isinstance(tournament.get("uniqueTournament"), dict)
        else {}
    )

    compact_tournament: dict[str, Any] = {}
    for key in ("id", "name", "city"):
        if tournament.get(key) not in (None, ""):
            compact_tournament[key] = tournament.get(key)
    tournament_country = _compact_country(tournament.get("country"))
    if tournament_country is not None:
        compact_tournament["country"] = tournament_country

    compact_unique: dict[str, Any] = {}
    for key in ("id", "name", "city"):
        if unique.get(key) not in (None, ""):
            compact_unique[key] = unique.get(key)
    unique_country = _compact_country(unique.get("country"))
    if unique_country is not None:
        compact_unique["country"] = unique_country
    if compact_unique:
        compact_tournament["uniqueTournament"] = compact_unique
    if compact_tournament:
        out["tournament"] = compact_tournament

    venue = raw.get("venue") if isinstance(raw.get("venue"), dict) else {}
    compact_venue: dict[str, Any] = {}
    for key in ("id", "name", "city"):
        if venue.get(key) not in (None, ""):
            compact_venue[key] = venue.get(key)
    venue_country = _compact_country(venue.get("country"))
    if venue_country is not None:
        compact_venue["country"] = venue_country
    if venue.get("countryName") not in (None, ""):
        compact_venue["countryName"] = venue.get("countryName")
    if compact_venue:
        out["venue"] = compact_venue

    for key in ("city", "venueCity", "countryName"):
        if raw.get(key) not in (None, ""):
            out[key] = raw.get(key)
    raw_country = _compact_country(raw.get("country"))
    if raw_country is not None:
        out["country"] = raw_country

    if include_environment:
        environment = raw.get("_tbt_environment")
        if isinstance(environment, dict) and environment:
            out["_tbt_environment"] = environment

    return out


def merge_provider_context(existing: Any, incoming: Any) -> dict[str, Any]:
    """Merge compact provider contexts without losing resolved environment."""
    left = minimize_provider_payload(existing)
    right = minimize_provider_payload(incoming)
    merged = dict(left)

    for key, value in right.items():
        if key == "_tbt_rank_provenance":
            # A provenance claim is atomic; never assemble one from two sources.
            merged[key] = dict(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        elif value not in (None, "", {}):
            merged[key] = value

    left_env = left.get("_tbt_environment")
    right_env = right.get("_tbt_environment")
    if isinstance(left_env, dict) and left_env.get("venue_resolved") is True:
        merged["_tbt_environment"] = left_env
    elif isinstance(right_env, dict) and right_env:
        merged["_tbt_environment"] = right_env
    elif isinstance(left_env, dict) and left_env:
        merged["_tbt_environment"] = left_env

    return minimize_provider_payload(merged)


def environment_from_payload(payload: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    value = raw.get("_tbt_environment")
    return dict(value) if isinstance(value, dict) else {}
