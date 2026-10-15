"""Bounded post-match TennisApi extras for the existing canonical history writer.

Provider-1 odds opening/latest and PBP coverage are observations, not
historical pre-match prices or point-derived model features.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..errors import ProviderError
from ..providers.tennisapi_extra import normalize_market_snapshot, point_by_point_inventory
from .statistics_gapfill import event_id as resolve_event_id

_MARKET_KEY = "_tbt_tennisapi_markets"
_PBP_KEY = "_tbt_tennisapi_pbp"


def marker_due(marker, event_id: str, now: datetime, *, cooldown_days: int = 30) -> bool:
    if not isinstance(marker, dict) or marker.get("event_id") != event_id or marker.get("schema") != 1:
        return True
    if marker.get("status") == "available":
        return False
    try:
        observed = datetime.fromisoformat(str(marker["observed_at_utc"]).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return True
        return now - observed.astimezone(timezone.utc) >= timedelta(days=cooldown_days)
    except (ValueError, TypeError, KeyError):
        return True


def needs_extras(match, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not match.is_completed or match.scheduled_at >= now:
        return False
    eid = resolve_event_id(match)
    if eid is None:
        return False
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    return (marker_due(raw.get(_MARKET_KEY), str(eid), now)
            or marker_due(raw.get(_PBP_KEY), str(eid), now))


def _verify_finished_identity(match, provider, eid: str) -> dict:
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    identity = raw.get("_tbt_event_identity")
    if (isinstance(identity, dict) and identity.get("event_id") == eid
            and identity.get("status") == "finished"
            and {str(identity.get("home")), str(identity.get("away"))}
            == {str(match.player1_id), str(match.player2_id)}
            and str(identity.get("home")) != str(identity.get("away"))):
        return identity
    detail = provider._get(f"/api/tennis/event/{eid}", enrichment=True)
    event = detail.get("event", detail) if isinstance(detail, dict) else {}
    home = str(event.get("homeTeam", {}).get("id") or "")
    away = str(event.get("awayTeam", {}).get("id") or "")
    actual_id = event.get("id", event.get("eventId"))
    if actual_id not in (None, "") and str(actual_id) != eid:
        raise ProviderError("Extras event ID mismatch")
    if (home == away or not home or not away
            or {home, away} != {str(match.player1_id), str(match.player2_id)}):
        raise ProviderError("Extras event player identity mismatch")
    if (event.get("status") or {}).get("type") != "finished":
        raise ProviderError("Extras event not finished")
    return {"event_id": eid, "home": home, "away": away, "status": "finished"}


def enrich_event_extras(match, provider, *, now: datetime | None = None) -> dict:
    """Collect due markets/PBP with bounded shared quota and explicit evidence.

    Returns endpoint-specific status and changed flag. Never mutates stats,
    predictions, training features, score, or winner.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now requires timezone")
    eid = resolve_event_id(match)
    if eid is None or not match.is_completed or match.scheduled_at >= now:
        return {"status": "ineligible", "changed": False}
    eid = str(eid)
    raw = dict(match.provider_payload or {})
    fetch_markets = marker_due(raw.get(_MARKET_KEY), eid, now)
    fetch_pbp = marker_due(raw.get(_PBP_KEY), eid, now)
    if not (fetch_markets or fetch_pbp):
        return {"status": "cached", "changed": False}

    identity = _verify_finished_identity(match, provider, eid)
    raw["_tbt_event_identity"] = identity
    # Persist identity when calls stop at the shared budget gate; retry the
    # missing endpoint on the next hourly window.
    match.provider_payload = raw
    stamp = now.astimezone(timezone.utc).isoformat()
    outcomes = {"status": "processed", "changed": False, "markets": "cached", "pbp": "cached"}

    if fetch_markets:
        # Reuse the same provider-1 odds route as the Match Winner runtime.
        payload = provider.event_odds(eid, provider_id=1)
        parsed = normalize_market_snapshot(payload, event_id=eid, observed_at=now)
        marker = {
            "schema": 1, "source": "tennisapi1", "event_id": eid,
            "observed_at_utc": stamp,
            "status": "available" if parsed["quotes"] else "unavailable",
            "provider_quote_timestamp_known": False, "pre_match_asof_verified": False,
            "quotes": parsed["quotes"][:64],
        }
        # Keep older positive evidence if a provider temporarily retracts it.
        if raw.get(_MARKET_KEY, {}).get("status") != "available":
            raw[_MARKET_KEY] = marker
            match.provider_payload = dict(raw)
            outcomes["changed"] = True
        outcomes["markets"] = marker["status"]

    if fetch_pbp:
        payload = provider.event_point_by_point(eid)
        parsed = point_by_point_inventory(payload, event_id=eid)
        marker = {
            "schema": 1, "source": "tennisapi1", "event_id": eid,
            "observed_at_utc": stamp,
            "status": "available" if parsed["points"] else "unavailable",
            "sets": parsed["sets"], "games": parsed["games"], "points": parsed["points"],
            "games_with_explicit_server": parsed["games_with_explicit_server"],
            "games_with_explicit_winner": parsed["games_with_explicit_winner"],
            "quality_status": parsed["quality_status"],
            "eligible_for_cdb_point_features": False,
        }
        if raw.get(_PBP_KEY, {}).get("status") != "available":
            raw[_PBP_KEY] = marker
            match.provider_payload = dict(raw)
            outcomes["changed"] = True
        outcomes["pbp"] = marker["status"]
    return outcomes
