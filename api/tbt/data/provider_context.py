from __future__ import annotations

import math
from typing import Any


_TERMINATION_ALIASES = (
    ("retir", "retired"), ("walkover", "walkover"), ("walk over", "walkover"), ("w/o", "walkover"),
    ("abandon", "abandoned"), ("interrupt", "interrupted"), ("suspend", "suspended"),
    ("postpon", "postponed"), ("cancel", "cancelled"),
)

def _compact_termination(payload: Any) -> dict[str, Any] | None:
    """Preserve only non-standard match termination evidence from provider payloads."""
    if not isinstance(payload, dict):
        return None
    values: list[str] = []
    status = payload.get("status")
    if isinstance(status, dict):
        for key in ("type", "name", "description", "reason", "status", "state"):
            if status.get(key) not in (None, ""):
                values.append(str(status.get(key)))
    elif status not in (None, ""):
        values.append(str(status))
    for key in ("state", "reason", "statusDescription", "status_description", "endReason", "end_reason", "termination", "terminationReason", "termination_reason"):
        if payload.get(key) not in (None, ""):
            values.append(str(payload.get(key)))
    marker = payload.get("_tbt_termination")
    if isinstance(marker, dict):
        for key in ("reason", "raw"):
            if marker.get(key) not in (None, ""):
                values.append(str(marker.get(key)))
    text = " | ".join(values).lower().replace("_", " ")
    reason = ""
    for token, canonical in _TERMINATION_ALIASES:
        if token in text:
            reason = canonical
            break
    if not reason:
        return None
    return {"schema": 1, "reason": reason, "raw": " | ".join(values)[:240]}


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


def _compact_team(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    compact: dict[str, Any] = {}
    for key in ("id", "name"):
        if value.get(key) not in (None, ""):
            compact[key] = value.get(key)
    country = _compact_country(value.get("country"))
    if country is not None:
        compact["country"] = country
    for source, target in (
        ("country_code", "country_code"),
        ("countryCode", "countryCode"),
        ("countryAlpha2", "countryAlpha2"),
        ("countryAlpha3", "countryAlpha3"),
    ):
        if value.get(source) not in (None, ""):
            compact[target] = value.get(source)
    return compact or None


def minimize_provider_payload(
    payload: Any,
    *,
    include_environment: bool = True,
) -> dict[str, Any]:
    """Return the tiny provider context TBT needs after normalisation.

    Deliberately drops the raw provider response.  The compact result is safe for
    long-lived GitHub Parquet history and release artifacts. Tennis data is not
    stored in the identity layer; Firebase Auth is reserved for authentication/account data.
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
        # Preserve bounded adapter diagnostics across canonical readback. Without
        # these, unsupported statistics and missing ALL periods become identical
        # cache misses and cannot be triaged without another provider request.
        reason = marker.get("reason")
        if isinstance(reason, str) and reason:
            out["_tbt_statistics"]["reason"] = reason[:128]
        for name, limit in (("unsupported_keys", 40), ("period_labels", 20)):
            values = marker.get(name)
            if isinstance(values, list):
                compact = list(dict.fromkeys(value[:96] for value in values if isinstance(value, str) and value))[:limit]
                if compact:
                    out["_tbt_statistics"][name] = compact
    # Post-match provider-side evidence. Canonical p1/p2 stats and model inputs
    # remain unchanged; these bounded markers survive parquet minimization.
    by_set = raw.get("_tbt_statistics_by_set")
    if (isinstance(by_set, dict) and by_set.get("schema") == 1
            and by_set.get("source") == "tennisapi1"
            and by_set.get("orientation") == "provider_home_away"
            and by_set.get("scope") == "post_match_only"
            and isinstance(by_set.get("sets"), dict)
            and 0 < len(by_set["sets"]) <= 5):
        result = {}
        for n, fields in by_set["sets"].items():
            if str(n) not in {"1", "2", "3", "4", "5"} or not isinstance(fields, dict) or len(fields) > 40:
                result = {}
                break
            clean = {}
            for k, v in fields.items():
                if (not isinstance(k, str) or not k.startswith(("home_", "away_"))
                        or isinstance(v, bool) or not isinstance(v, (int, float))
                        or not math.isfinite(v) or v < 0):
                    clean = None
                    break
                clean[k] = float(v)
            if clean is None:
                result = {}
                break
            result[str(n)] = clean
        if result:
            out["_tbt_statistics_by_set"] = {
                "schema": 1, "source": "tennisapi1",
                "event_id": str(by_set.get("event_id") or "")[:32],
                "orientation": "provider_home_away", "scope": "post_match_only",
                "sets": result,
            }

    odds = raw.get("_tbt_tennisapi_markets")
    if (isinstance(odds, dict) and odds.get("schema") == 1
            and odds.get("source") == "tennisapi1"
            and odds.get("status") in ("available", "unavailable")
            and odds.get("provider_quote_timestamp_known") is False
            and odds.get("pre_match_asof_verified") is False
            and isinstance(odds.get("quotes"), list) and len(odds["quotes"]) <= 64):
        quoted = []
        for q in odds["quotes"]:
            if (not isinstance(q, dict) or q.get("market_id") not in (1, 11, 12, 15)
                    or q.get("selection") not in ("1", "2", "Over", "Under")
                    or not isinstance(q.get("is_live"), bool)
                    or q.get("latest_decimal") is None):
                quoted = []
                break
            nums = (q.get(k) for k in ("line_games", "opening_decimal", "latest_decimal"))
            if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                      or not math.isfinite(v) or v <= 0) for v in nums):
                quoted = []
                break
            quoted.append({k: q.get(k) for k in ("market_id", "market", "is_live",
                            "line_games", "selection", "opening_decimal",
                            "latest_decimal", "settled_winning")})
        if quoted or odds["status"] == "unavailable":
            out["_tbt_tennisapi_markets"] = {
                "schema": 1, "source": "tennisapi1",
                "event_id": str(odds.get("event_id") or "")[:32],
                "observed_at_utc": str(odds.get("observed_at_utc") or "")[:40],
                "status": odds["status"],
                "provider_quote_timestamp_known": False,
                "pre_match_asof_verified": False, "quotes": quoted,
            }

    pbp = raw.get("_tbt_tennisapi_pbp")
    fields = ("sets", "games", "points", "games_with_explicit_server", "games_with_explicit_winner")
    if (isinstance(pbp, dict) and pbp.get("schema") == 1
            and pbp.get("source") == "tennisapi1"
            and pbp.get("status") in ("available", "unavailable")
            and pbp.get("quality_status") in ("structural_only", "unavailable")
            and pbp.get("eligible_for_cdb_point_features") is False
            and all(isinstance(pbp.get(k), int) and not isinstance(pbp[k], bool)
                    and 0 <= pbp[k] <= 100000 for k in fields)):
        out["_tbt_tennisapi_pbp"] = {
            k: pbp[k] for k in ("schema", "source", "event_id",
            "observed_at_utc", "status", *fields, "quality_status",
            "eligible_for_cdb_point_features")
        }
    score_marker = raw.get("_tbt_score")
    if isinstance(score_marker, dict):
        out["_tbt_score"] = {k: score_marker[k] for k in
            ("schema", "event_id", "source", "fetched_at", "status", "best_of", "best_of_source", "identity_verified", "format_verified") if k in score_marker}
    format_marker = raw.get("_tbt_match_format")
    if isinstance(format_marker, dict):
        out["_tbt_match_format"] = {k: format_marker[k] for k in
            ("schema", "status", "best_of", "source", "provider_best_of", "score_best_of") if k in format_marker}
    odds_marker = raw.get("_tbt_match_winner_odds")
    if isinstance(odds_marker, dict):
        out["_tbt_match_winner_odds"] = {
            k: odds_marker[k]
            for k in (
                "schema", "status", "source", "source_match_id",
                "source_file_sha256", "price_kind", "player1_odds",
                "player2_odds", "player1_implied_probability",
                "player2_implied_probability", "raw_overround",
            )
            if k in odds_marker
        }
    market_history = raw.get("_tbt_market_history")
    if isinstance(market_history, dict):
        compact_market_history = {
            k: market_history[k]
            for k in (
                "schema", "status", "source", "source_match_id",
                "source_file_sha256", "price_kind", "closing_semantics",
                "model_feature_policy",
            )
            if k in market_history
        }
        for kind in ("opening", "closing"):
            market = market_history.get(kind)
            if isinstance(market, dict):
                compact_market_history[kind] = {
                    k: market[k]
                    for k in (
                        "player1_odds", "player2_odds",
                        "player1_implied_probability",
                        "player2_implied_probability", "raw_overround",
                    )
                    if k in market
                }
        if compact_market_history:
            out["_tbt_market_history"] = compact_market_history
    pbpx = raw.get("_tbt_pbpx_enrichment")
    if isinstance(pbpx, dict) and pbpx.get("schema") == 1:
        out["_tbt_pbpx_enrichment"] = {
            key: pbpx[key] for key in (
                "schema", "source", "source_file", "source_row",
                "source_ref", "source_date", "score_validated", "stat_keys",
            ) if key in pbpx
        }

    delayed = raw.get("_tbt_pbpx_delayed_observation")
    if isinstance(delayed, dict) and delayed.get("schema") == 1:
        # Private source-dated evidence only: NEVER promote these values to
        # match.stats or to pre-match model features at tournament-start time.
        out["_tbt_pbpx_delayed_observation"] = {
            key: delayed[key] for key in (
                "schema", "source", "source_ref", "source_file",
                "source_row", "source_date", "status",
                "score_validated", "stats",
            ) if key in delayed
        }

    # Limited research-only post-match observations (never exposed as same-match
    # prematch feature inputs). Persist only the pinned verified source schema.
    usopen = raw.get("_tbt_usopen_2024_serve_research")
    if (isinstance(usopen, dict) and usopen.get("schema") == 1
            and usopen.get("source") == "jasnwag/tennis_serve_dataset"
            and usopen.get("source_ref_blob_sha") == "9d0a7a8c013a68d18e437f8c75f8fb7c036f1224"
            and usopen.get("feature_policy") ==
                "research_post_match_only; same-match fields forbidden as pre-match features; eligible only for strictly lagged chronological player-state experiments"):
        compact = {
            key: usopen[key] for key in (
                "schema", "source", "source_ref_blob_sha", "source_event",
                "source_match_id", "license", "feature_policy"
            ) if key in usopen
        }
        allowed = {
            "ace_count", "ace_rate_per_serve_row", "first_serve_speed_kmh_mean",
            "height_cm", "opponent_return_depth_counts", "quality_label_mean",
            "rally_count_mean", "rally_count_median", "second_serve_speed_kmh_mean",
            "serve_depth_counts", "serve_duration_sec_mean",
            "serve_number_1_rows", "serve_number_2_rows", "serve_rows",
            "serve_width_counts", "service_games_observed", "sets_observed",
            "speed_kmh_max", "speed_kmh_mean", "speed_kmh_median",
            "speed_observations"
        }
        sides_ok = True
        for side in ("player1_serve", "player2_serve"):
            values = usopen.get(side)
            if not isinstance(values, dict) or set(values) != allowed:
                sides_ok = False
                break
            compact[side] = {k: values[k] for k in sorted(allowed)}
        if sides_ok:
            out["_tbt_usopen_2024_serve_research"] = compact

    termination = _compact_termination(raw)
    if termination is not None:
        out["_tbt_termination"] = termination

    for key in (
        "_tbt_canonical_match_id",
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

    # Preserve only the tiny player identity/country context required by the
    # presentation player master. This is intentionally not a historical-rank
    # source and therefore cannot leak current ranking into model training.
    for key in ("homeTeam", "awayTeam", "home_team", "away_team"):
        compact_team = _compact_team(raw.get(key))
        if compact_team is not None:
            out[key] = compact_team

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
        if key == "_tbt_statistics_by_set":
            # Do not replace a previous source-native set observation with
            # a partial later re-query during canonical history merge.
            if key not in merged:
                merged[key] = value
        elif key in ("_tbt_tennisapi_markets", "_tbt_tennisapi_pbp"):
            # A missing/late provider response cannot downgrade verified
            # observed coverage. Keep the first positive research snapshot.
            prior = merged.get(key)
            if not isinstance(prior, dict) or prior.get("status") != "available":
                merged[key] = value
        elif key == "_tbt_rank_provenance":
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
