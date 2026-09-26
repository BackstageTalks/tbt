"""Offline prediction publication with immutable pre-match records."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import json
import math
import numpy as np
import pandas as pd

from ..models.feature_builder import FeatureBuilder, FEATURE_NAMES, stats_surface_key
from ..models.metrics import evaluate_probabilities
from .prediction_quality import coverage, subgroup_report
from .data_quality import audit_history
from .training import _enforce_rank_provenance
from .publication import confirm_publication
from .countries import normalize_country_code


# Public history is reconstructed from immutable issuance evidence rather than
# an arbitrary product reset date. Unissued/offline rows stay private; settled
# selections that were genuinely published remain inspectable for any period.


def event_id(match):
    raw = match.provider_payload or {}
    return str(next((raw.get(k) for k in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id") if raw.get(k)), match.match_id))


_VOID_TERMINATION_ALIASES = (
    ("retir", "retired"),
    ("walkover", "walkover"),
    ("walk over", "walkover"),
    ("w/o", "walkover"),
    ("abandon", "abandoned"),
    ("interrupt", "interrupted"),
    ("suspend", "suspended"),
    ("postpon", "postponed"),
    ("cancel", "cancelled"),
)


def _match_void_reason(match):
    """Return a canonical non-standard termination reason, if provider proves one.

    Tennis providers often expose ``status.type = finished`` while putting the
    real termination in ``status.description``/``reason`` (for example Retired).
    Match-winner settlement must not turn those rows into a normal win/loss.
    """
    values = [str(getattr(match, "status", "") or "")]
    raw = getattr(match, "provider_payload", None)
    if isinstance(raw, dict):
        marker = raw.get("_tbt_termination")
        if isinstance(marker, dict) and str(marker.get("reason") or "").strip():
            return str(marker.get("reason")).strip().lower()
    interesting = {
        "status", "state", "type", "name", "description", "reason",
        "statusdescription", "status_description", "endreason", "end_reason",
        "termination", "terminationreason", "termination_reason",
    }

    def collect(value, depth=0):
        if depth > 4 or value is None:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                key_text = str(key or "").strip().lower().replace("-", "_")
                if key_text in interesting or any(token in key_text for token in ("status", "reason", "retir", "walkover")):
                    if isinstance(nested, (str, int, float)):
                        values.append(str(nested))
                    else:
                        collect(nested, depth + 1)
        elif isinstance(value, (list, tuple)):
            for nested in value[:30]:
                collect(nested, depth + 1)

    collect(raw)
    text = " | ".join(values).lower().replace("_", " ")
    for token, canonical in _VOID_TERMINATION_ALIASES:
        if token in text:
            return canonical

    # Fail closed when a supposedly completed match has structured set totals
    # proving that neither player reached the number of sets required to win.
    # This catches provider rows whose status.type is merely "finished" while
    # the retirement description was unavailable in an older compact snapshot.
    best_of = getattr(match, "best_of", None)
    stats = getattr(match, "stats", None)
    if isinstance(stats, dict) and getattr(match, "winner_id", None):
        try:
            p1_sets = float(stats.get("p1_sets_won"))
            p2_sets = float(stats.get("p2_sets_won"))
        except (TypeError, ValueError):
            p1_sets = p2_sets = float("nan")
        # Any normally completed tennis match requires at least two won sets on
        # one side. BO5 requires three when the format is known. This catches
        # legacy compact rows where the provider's explicit "Retired" text was
        # discarded but the structured final score is necessarily incomplete.
        required = 3 if best_of == 5 else 2
        if np.isfinite(p1_sets) and np.isfinite(p2_sets) and max(p1_sets, p2_sets) < required:
            return "retired_or_incomplete"
    return ""


def _provider_player_country(payload, *, player1):
    """Best-effort ISO-2 country extraction from TennisApi event payload."""
    if not isinstance(payload, dict):
        return ""
    keys = ("homeTeam", "home_team", "player1", "participant1", "player_1") if player1 else ("awayTeam", "away_team", "player2", "participant2", "player_2")
    side = next((payload.get(k) for k in keys if isinstance(payload.get(k), dict)), {})
    candidates = []
    if isinstance(side, dict):
        candidates.extend([
            side.get("country_code"), side.get("countryCode"), side.get("countryAlpha2"),
            side.get("country_code2"), side.get("countryAlpha3"), side.get("country_code3"),
        ])
        country = side.get("country")
        if isinstance(country, dict):
            candidates.extend([
                country.get("alpha2"), country.get("alpha3"), country.get("code"),
                country.get("iso2"), country.get("iso3"), country.get("countryCode"),
            ])
    for value in candidates:
        normalized = normalize_country_code(value)
        if normalized:
            return normalized
    return ""


def _provider_tournament_context(payload):
    """Return explicit provider tournament/venue identity for presentation.

    No geocoding or name guessing happens here. Only fields present in the
    provider payload are exposed so the UI can keep tournament and location
    visually separate.
    """
    if not isinstance(payload, dict):
        return {"country_code": "", "country_name": "", "city": "", "venue_name": ""}
    tournament = payload.get("tournament") if isinstance(payload.get("tournament"), dict) else {}
    unique = tournament.get("uniqueTournament") if isinstance(tournament.get("uniqueTournament"), dict) else {}
    venue = payload.get("venue") if isinstance(payload.get("venue"), dict) else {}

    def country_values(obj):
        country = obj.get("country") if isinstance(obj, dict) and isinstance(obj.get("country"), dict) else {}
        return (
            country.get("alpha2") or country.get("alpha3") or country.get("code") or country.get("countryCode") or "",
            country.get("name") or (obj.get("countryName") if isinstance(obj, dict) else "") or "",
        )

    country_code = ""
    country_name = ""
    for obj in (venue, tournament, unique, payload):
        raw_code, raw_name = country_values(obj)
        normalized = normalize_country_code(raw_code)
        if normalized and not country_code:
            country_code = normalized
        if raw_name and not country_name:
            country_name = str(raw_name).strip()
    city = str(
        venue.get("city") or tournament.get("city") or unique.get("city")
        or payload.get("venueCity") or payload.get("city") or ""
    ).strip()
    venue_name = str(venue.get("name") or "").strip()
    return {"country_code": country_code, "country_name": country_name, "city": city, "venue_name": venue_name}


def _recent_form_summary(state, *, surface=None, limit=10):
    """Point-in-time recent form for presentation only.

    The builder has only been replayed with matches strictly before the prediction
    cutoff, so these summaries cannot include the event being predicted.
    """
    rows = list(state.recent)
    if surface and stats_surface_key(surface) != "unknown":
        surface_key = stats_surface_key(surface)
        rows = [item for item in rows if stats_surface_key(item.surface) == surface_key]
    rows = rows[-max(1, int(limit)):]
    if not rows:
        return {"matches": 0, "wins": 0, "win_pct": None, "sequence": []}
    sequence = ["W" if float(item.won) >= 0.5 else "L" for item in rows]
    wins = sum(1 for value in sequence if value == "W")
    return {
        "matches": len(rows),
        "wins": wins,
        "win_pct": wins / len(rows),
        "sequence": sequence,
    }


def _h2h_record(builder, match):
    key1 = builder.player_key(match.tour, match.player1_id)
    key2 = builder.player_key(match.tour, match.player2_id)
    left, right = sorted((key1, key2))
    wins_left, wins_right = builder.h2h[(left, right)]
    if key1 == left:
        return int(wins_left), int(wins_right)
    return int(wins_right), int(wins_left)


def _presentation_player_profile(builder, match, *, player1):
    state = builder._state(match, player1)
    overall = _recent_form_summary(state, limit=35)
    surface_key = stats_surface_key(match.surface)
    surface = _recent_form_summary(state, surface=surface_key, limit=35)
    current_lat, current_lon, current_alt = builder._venue_values(match)
    travel_km = builder._haversine_km(
        state.last_latitude, state.last_longitude, current_lat, current_lon
    )
    altitude_change_m = (
        abs(float(current_alt) - float(state.last_altitude_m))
        if current_alt is not None and state.last_altitude_m is not None
        else None
    )
    return {
        "history_matches": int(state.matches),
        "surface_history_matches": int(state.surface_matches.get(surface_key, 0)),
        "recent_form": overall,
        "surface_form": surface,
        "context": {
            "rest_days": round(float(builder._rest_days(state, match.scheduled_at)), 2),
            "matches_3d": int(builder._matches_in_window(state, match.scheduled_at, 3.0)),
            "matches_7d": int(builder._matches_in_window(state, match.scheduled_at, 7.0)),
            "travel_km": None if travel_km is None else round(float(travel_km), 1),
            "altitude_change_m": None if altitude_change_m is None else round(float(altitude_change_m), 1),
            "venue_altitude_m": None if current_alt is None else round(float(current_alt), 1),
            "overall_elo": round(float(state.overall_elo), 1),
            "surface_elo": round(float(state.get_surface_elo(surface_key)), 1),
            "surface_matches": int(state.surface_matches.get(surface_key, 0)),
            "point_in_time": True,
        },
        "meaning": "point_in_time_recent_results_and_context_not_model_probability",
    }


def predict(model, history, upcoming, now=None):
    now = now or datetime.now(timezone.utc)
    # Match completion timestamps are unavailable. Use previous UTC days only,
    # matching the conservative whole-day training protocol. Validate the exact
    # replay slice with the same history/ranking policy used by training/backtest.
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    replay_history = [match for match in history if match.scheduled_at < cutoff]
    replay_history, _ = audit_history(replay_history, now=now)
    replay_history, _ = _enforce_rank_provenance(replay_history)
    builder = FeatureBuilder()
    builder.replay(replay_history, before=cutoff)
    future = sorted((m for m in upcoming if not m.is_completed and m.scheduled_at > now
                     and m.status in {"upcoming", "notstarted", "scheduled"}), key=lambda m: (m.scheduled_at, m.match_id))
    if not future:
        return []
    features = [builder.snapshot(m) for m in future]
    # Serving is artifact-schema driven. This keeps an already-deployed legacy
    # champion usable while the repository evolves to a richer feature schema;
    # a newly trained model opts into new features through its persisted list.
    feature_names = list(getattr(model, "feature_names", None) or FEATURE_NAMES)
    missing = [name for name in feature_names if name not in features[0]]
    if missing:
        raise ValueError(f"Model artifact requests unavailable features: {missing}")
    probabilities = model.predict_proba(pd.DataFrame(features, columns=feature_names))
    rows = []
    for match, f, probability in zip(future, features, probabilities):
        p = float(probability)
        if not np.isfinite(p) or not 0 < p < 1:
            raise ValueError("Invalid model probability")
        winner = match.player1_id if p >= .5 else match.player2_id
        factors = [("Sila na povrchu", f["surface_elo_diff"], .12),
                   ("Celková výkonnosť", f["elo_diff"], .12),
                   ("Aktuálna forma", f["recent_form_diff"], .08),
                   ("Servis", f["serve_quality_diff"], .04)]
        signals = [{"label": name, "player_id": match.player1_id if value >= 0 else match.player2_id}
                   for name, value, scale in sorted(factors, key=lambda x: abs(x[1] / x[2]), reverse=True)
                   if abs(value) >= scale][:3]
        tournament_obj = match.provider_payload.get("tournament") if isinstance(match.provider_payload, dict) else None
        unique_tournament = tournament_obj.get("uniqueTournament") if isinstance(tournament_obj, dict) else None
        tournament_logo_id = ""
        if isinstance(unique_tournament, dict):
            tournament_logo_id = str(unique_tournament.get("id") or "").strip()
        tournament_logo_id = tournament_logo_id or str(match.tournament_id or "")
        tournament_context = _provider_tournament_context(match.provider_payload)
        h2h_p1, h2h_p2 = _h2h_record(builder, match)
        profile1 = _presentation_player_profile(builder, match, player1=True)
        profile2 = _presentation_player_profile(builder, match, player1=False)
        profile1["h2h_wins"] = h2h_p1
        profile1["h2h_losses"] = h2h_p2
        profile2["h2h_wins"] = h2h_p2
        profile2["h2h_losses"] = h2h_p1
        provider_custom_id = ""
        match_format = {}
        if isinstance(match.provider_payload, dict):
            provider_custom_id = str(match.provider_payload.get("customId") or match.provider_payload.get("custom_id") or "").strip()
            marker = match.provider_payload.get("_tbt_match_format")
            match_format = marker if isinstance(marker, dict) else {}
        rows.append({"id": match.match_id, "event_id": event_id(match), "custom_id": provider_custom_id, "tour": match.tour.upper(),
            "scheduled_at": match.scheduled_at.isoformat(), "tournament": match.tournament,
            "tournament_id": str(match.tournament_id or ""),
            "tournament_logo_id": tournament_logo_id,
            "tournament_country_code": tournament_context["country_code"],
            "tournament_country": tournament_context["country_name"],
            "tournament_city": tournament_context["city"],
            "venue_name": tournament_context["venue_name"],
            "venue_city": tournament_context["city"],
            "venue_country_code": tournament_context["country_code"],
            "venue_country": tournament_context["country_name"],
            "location": {
                "city": tournament_context["city"],
                "country": tournament_context["country_name"],
                "country_code": tournament_context["country_code"],
                "venue": tournament_context["venue_name"],
            },
            "surface": match.surface, "round": match.round_name,
            "best_of": match.best_of,
            "best_of_source": str(match_format.get("source") or ""),
            "competition": match.tournament_level or "unknown", "quality": coverage(builder, match),
            "player1": {
                "id": match.player1_id, "name": match.player1_name,
                "probability": p, "rank": match.player1_rank,
                "country_code": _provider_player_country(match.provider_payload, player1=True),
                "photo_url": "",  # r40: presentation release attaches cached artwork; public API never spends provider quota
                "presentation": profile1,
            },
            "player2": {
                "id": match.player2_id, "name": match.player2_name,
                "probability": 1 - p, "rank": match.player2_rank,
                "country_code": _provider_player_country(match.provider_payload, player1=False),
                "photo_url": "",  # r40: presentation release attaches cached artwork; public API never spends provider quota
                "presentation": profile2,
            },
            "winner_id": winner, "confidence": max(p, 1 - p),
            "raw_model_confidence": max(p, 1 - p),
            "blinq_probability": 0.5 + (max(p, 1 - p) - 0.5) * float(f["data_depth"]),
            "probability_reliability": float(f["data_depth"]),
            "data_depth": f["data_depth"],
            "stats_available": bool(f["stats_known_both"]), "signals": signals,
            "model_version": model.version, "created_at": now.isoformat(),
            "issued_at": None, "publication_status": "pending", "result": None})
    return rows



def _publication_key(value):
    if not isinstance(value, dict):
        return ""
    return str(value.get("publication_key") or "").strip()


def _merge_market_publication_candidates(existing, candidate_row):
    """Merge independent betting-section publication candidates into a ledger row.

    Issued records are immutable. Pending records may be refreshed before a
    successful deployment, because no public betting commitment exists yet.
    """
    current = [dict(item) for item in existing.get("market_publications", []) if isinstance(item, dict)]
    by_key = {_publication_key(item): item for item in current if _publication_key(item)}
    for source in candidate_row.get("market_publication_candidates", []) or []:
        if not isinstance(source, dict):
            continue
        key = _publication_key(source)
        if not key:
            continue
        prior = by_key.get(key)
        if prior is None:
            item = dict(source)
            current.append(item)
            by_key[key] = item
            continue
        if prior.get("issued_at") or prior.get("publication_status") == "published":
            continue
        # No successful public deployment has committed this section yet, so
        # replace the stale pending snapshot with the current one.
        preserved_result = prior.get("result")
        prior.clear()
        prior.update(dict(source))
        if preserved_result is not None:
            prior["result"] = preserved_result
    existing["market_publications"] = current
    existing.pop("market_publication_candidates", None)


def _settle_match_winner_publications(row, match, now):
    publications = row.get("market_publications")
    if not isinstance(publications, list):
        return
    void_reason = _match_void_reason(match)
    for publication in publications:
        if not isinstance(publication, dict) or publication.get("market") != "match_winner":
            continue
        issued_at = publication.get("issued_at")
        if not issued_at:
            continue
        try:
            issued = datetime.fromisoformat(str(issued_at).replace("Z", "+00:00"))
        except ValueError:
            publication["excluded_reason"] = "invalid_issued_at"
            continue
        if issued.tzinfo is None:
            publication["excluded_reason"] = "invalid_issued_at"
            continue
        if issued >= match.scheduled_at:
            publication["excluded_reason"] = "issued_after_actual_start"
            continue
        publication.pop("excluded_reason", None)
        existing = publication.get("result") if isinstance(publication.get("result"), dict) else None
        if void_reason:
            settled = {
                "status": "void",
                "reason": void_reason,
                "winner_id": match.winner_id,
                "correct": None,
                "staked_units": 0.0,
                "return_units": 0.0,
                "profit_units": 0.0,
                "settled_at": (existing or {}).get("settled_at") or now.isoformat(),
                "scheduled_at": match.scheduled_at.isoformat(),
            }
            if existing is not None and (
                existing.get("status") != "void"
                or existing.get("reason") != void_reason
                or existing.get("correct") is not None
                or abs(float(existing.get("profit_units") or 0.0)) > 1e-12
            ):
                settled["corrected_at"] = now.isoformat()
            publication["result"] = settled
            continue
        selection_id = str(publication.get("selection_id") or "")
        correct = selection_id == str(match.winner_id or "")
        try:
            odds = float(publication.get("odds"))
        except (TypeError, ValueError):
            odds = 0.0
        if not np.isfinite(odds) or odds <= 1:
            publication["excluded_reason"] = "invalid_odds"
            continue
        profit_units = (odds - 1.0) if correct else -1.0
        settled = {
            "winner_id": match.winner_id,
            "correct": correct,
            "staked_units": 1.0,
            "return_units": odds if correct else 0.0,
            "profit_units": profit_units,
            "settled_at": (existing or {}).get("settled_at") or now.isoformat(),
            "scheduled_at": match.scheduled_at.isoformat(),
        }
        if existing is not None and (
            existing.get("status") == "void"
            or existing.get("winner_id") != match.winner_id
            or existing.get("correct") != correct
            or abs(float(existing.get("profit_units", profit_units)) - profit_units) > 1e-12
        ):
            settled["corrected_at"] = now.isoformat()
        publication["result"] = settled




def _projection_price_units(publication, correct):
    """Return flat-1u settlement only when a real provider price was frozen."""
    try:
        odds = float(publication.get("odds"))
    except (TypeError, ValueError):
        odds = float("nan")
    priced = str(publication.get("price_status") or "").strip().lower() == "priced_projection"
    if not priced or not np.isfinite(odds) or odds <= 1 or correct is None:
        return None
    stake = 1.0
    returned = odds if correct else 0.0
    return {"staked_units": stake, "return_units": returned, "profit_units": returned - stake}

def _void_projection_publication(publication, match, now, reason):
    existing = publication.get("result") if isinstance(publication.get("result"), dict) else None
    settled = {
        "status": "void",
        "reason": reason,
        "correct": None,
        "staked_units": 0.0,
        "return_units": 0.0,
        "profit_units": 0.0,
        "settled_at": (existing or {}).get("settled_at") or now.isoformat(),
        "scheduled_at": match.scheduled_at.isoformat(),
    }
    if existing is not None and (
        existing.get("status") != "void"
        or existing.get("reason") != reason
        or existing.get("correct") is not None
    ):
        settled["corrected_at"] = now.isoformat()
    publication["result"] = settled
    publication.pop("excluded_reason", None)


def _settle_projection_publications(row, match, now):
    """Grade projection-only ESA publications without inventing betting ROI.

    Current ESA cards predict which player will record more Aces or Double
    Faults and expose the projected count. They have no bookmaker line/price,
    therefore settlement records HIT/MISS/VOID plus actual counts only.
    """
    publications = row.get("market_publications")
    if not isinstance(publications, list):
        return
    stats = match.stats if isinstance(match.stats, dict) else {}
    sides = {str(match.player1_id): "p1", str(match.player2_id): "p2"}
    void_reason = _match_void_reason(match)
    for publication in publications:
        if not isinstance(publication, dict):
            continue
        market = str(publication.get("market") or "")
        if market not in {"aces", "double_faults"}:
            continue
        issued_at = publication.get("issued_at")
        if not issued_at:
            continue
        try:
            issued = datetime.fromisoformat(str(issued_at).replace("Z", "+00:00"))
        except ValueError:
            publication["excluded_reason"] = "invalid_issued_at"
            continue
        if issued.tzinfo is None or issued >= match.scheduled_at:
            publication["excluded_reason"] = "invalid_issued_at" if issued.tzinfo is None else "issued_after_actual_start"
            continue
        if void_reason:
            _void_projection_publication(publication, match, now, void_reason)
            continue
        selection_id = str(publication.get("selection_id") or "")
        selected_side = sides.get(selection_id)
        if not selected_side:
            publication["excluded_reason"] = "invalid_projection_selection"
            continue
        opponent_side = "p2" if selected_side == "p1" else "p1"
        stat_suffix = "aces" if market == "aces" else "double_faults"
        try:
            actual = float(stats.get(f"{selected_side}_{stat_suffix}"))
        except (TypeError, ValueError):
            publication["excluded_reason"] = "projection_result_unavailable"
            continue
        if not np.isfinite(actual) or actual < 0:
            publication["excluded_reason"] = "projection_result_unavailable"
            continue
        try:
            opponent_actual = float(stats.get(f"{opponent_side}_{stat_suffix}"))
        except (TypeError, ValueError):
            opponent_actual = float("nan")
        contract = str(publication.get("price_contract") or "").strip().lower()
        if contract == "player_total_ou":
            # The new player-total contract is graded against its *published*
            # bookmaker line, never against the opponent's actual count.
            direction = str(publication.get("ou_side") or "").strip().lower()
            try:
                line = float(publication.get("market_line"))
            except (TypeError, ValueError):
                line = float("nan")
            if direction not in {"over", "under"} or not np.isfinite(line) or line < 0:
                publication["excluded_reason"] = "invalid_published_ou_contract"
                continue
            if actual == line:
                status, correct = "void", None
            else:
                correct = (actual > line) if direction == "over" else (actual < line)
                status = "hit" if correct else "miss"
        elif contract in {"", "player_superiority"}:
            if not np.isfinite(opponent_actual) or opponent_actual < 0:
                publication["excluded_reason"] = "projection_result_unavailable"
                continue
            if actual == opponent_actual:
                status, correct = "void", None
            else:
                correct = actual > opponent_actual
                status = "hit" if correct else "miss"
        else:
            publication["excluded_reason"] = "unknown_price_contract"
            continue
        publication.pop("excluded_reason", None)
        existing = publication.get("result") if isinstance(publication.get("result"), dict) else None
        price_units = _projection_price_units(publication, correct)
        settled = {
            "status": status,
            "correct": correct,
            "actual_count": actual,
            "opponent_actual_count": opponent_actual,
            "projection": publication.get("projection"),
            "opponent_projection": publication.get("opponent_projection"),
            "projection_scope": publication.get("projection_scope") or "player",
            "projection_metric": publication.get("projection_metric") or market,
            "data_depth": publication.get("data_depth"),
            "settled_at": (existing or {}).get("settled_at") or now.isoformat(),
            "scheduled_at": match.scheduled_at.isoformat(),
        }
        if price_units:
            settled.update(price_units)
        if existing is not None and (
            existing.get("status") != status
            or existing.get("actual_count") != actual
            or existing.get("opponent_actual_count") != opponent_actual
        ):
            settled["corrected_at"] = now.isoformat()
        publication["result"] = settled


def _settle_sg_projection_publications(row, match, now):
    """Grade published Sets/Games projections against structured final scores."""
    publications = row.get("market_publications")
    if not isinstance(publications, list):
        return
    stats = match.stats if isinstance(match.stats, dict) else {}
    void_reason = _match_void_reason(match)
    for publication in publications:
        if not isinstance(publication, dict):
            continue
        market = str(publication.get("market") or "").strip().lower()
        if market not in {"sets", "games"}:
            continue
        issued_at = publication.get("issued_at")
        if not issued_at:
            continue
        try:
            issued = datetime.fromisoformat(str(issued_at).replace("Z", "+00:00"))
        except ValueError:
            publication["excluded_reason"] = "invalid_issued_at"
            continue
        if issued.tzinfo is None or issued >= match.scheduled_at:
            publication["excluded_reason"] = "invalid_issued_at" if issued.tzinfo is None else "issued_after_actual_start"
            continue
        if void_reason:
            _void_projection_publication(publication, match, now, void_reason)
            continue

        key = "total_sets" if market == "sets" else "total_games"
        try:
            actual = float(stats.get(key))
        except (TypeError, ValueError):
            publication["excluded_reason"] = "projection_result_unavailable"
            continue
        if not np.isfinite(actual) or actual <= 0:
            publication["excluded_reason"] = "projection_result_unavailable"
            continue

        selection_id = str(publication.get("selection_id") or "").strip().lower()
        reference = publication.get("reference_projection")
        try:
            reference = float(reference)
        except (TypeError, ValueError):
            reference = None

        correct = None
        status = "void"
        if market == "sets":
            parts = selection_id.split(":")
            if len(parts) >= 3 and parts[0] == "sets" and parts[1] in {"over", "under"}:
                try:
                    line = float(parts[2])
                except ValueError:
                    line = None
                if line is not None and np.isfinite(line):
                    if actual == line:
                        status, correct = "void", None
                    else:
                        correct = actual > line if parts[1] == "over" else actual < line
                        status = "hit" if correct else "miss"
                    reference = line
        else:
            direction = str(publication.get("projection_direction") or "").strip().lower()
            if not direction and selection_id.startswith("games:"):
                direction = selection_id.split(":", 1)[1]
            if direction in {"high", "low"} and reference is not None and np.isfinite(reference):
                if actual == reference:
                    status, correct = "void", None
                else:
                    correct = actual > reference if direction == "high" else actual < reference
                    status = "hit" if correct else "miss"

        if status == "void" and correct is None and reference is None:
            publication["excluded_reason"] = "projection_result_unavailable"
            continue

        publication.pop("excluded_reason", None)
        existing = publication.get("result") if isinstance(publication.get("result"), dict) else None
        price_units = _projection_price_units(publication, correct)
        settled = {
            "status": status,
            "correct": correct,
            "actual_count": actual,
            "projection": publication.get("projection"),
            "reference_projection": reference,
            "projection_scope": publication.get("projection_scope") or "match_total",
            "projection_metric": publication.get("projection_metric") or market,
            "data_depth": publication.get("data_depth"),
            "settled_at": (existing or {}).get("settled_at") or now.isoformat(),
            "scheduled_at": match.scheduled_at.isoformat(),
        }
        if price_units:
            settled.update(price_units)
        if existing is not None and (
            existing.get("status") != status
            or existing.get("actual_count") != actual
            or existing.get("reference_projection") != reference
        ):
            settled["corrected_at"] = now.isoformat()
        publication["result"] = settled


def _projection_metrics(publications):
    rows = [
        p for p in publications
        if isinstance(p, dict)
        and str(p.get("market") or "").strip().lower() in {"aces", "double_faults", "sets", "games"}
        and isinstance(p.get("result"), dict)
        and not p.get("excluded_reason")
        and p["result"].get("status") in {"hit", "miss", "void"}
    ]
    graded = [p for p in rows if p["result"].get("status") in {"hit", "miss"}]
    hits = sum(1 for p in graded if p["result"].get("status") == "hit")
    return {
        "n": len(graded),
        "hits": hits,
        "misses": len(graded) - hits,
        "voids": len(rows) - len(graded),
        "hit_rate": hits / len(graded) if graded else None,
    }


def _betting_metrics(publications):
    rows = [
        p for p in publications
        if isinstance(p, dict)
        and p.get("price_status") not in {"projection_only", "model_only"}
        and isinstance(p.get("result"), dict)
        and not p.get("excluded_reason")
    ]
    graded = [
        p for p in rows
        if p["result"].get("correct") in {True, False}
        and str(p["result"].get("status") or "").strip().lower() != "void"
    ]
    voids = len(rows) - len(graded)
    if not rows:
        return {
            "n": 0, "wins": 0, "losses": 0, "voids": 0, "hit_rate": None,
            "avg_odds": None, "staked_units": 0.0, "profit_units": 0.0, "roi": None,
        }
    wins = sum(1 for p in graded if p["result"].get("correct") is True)
    losses = sum(1 for p in graded if p["result"].get("correct") is False)
    odds = [float(p.get("odds")) for p in graded if p.get("odds") is not None]
    staked = sum(float(p["result"].get("staked_units") or 0.0) for p in graded)
    profit = sum(float(p["result"].get("profit_units") or 0.0) for p in graded)
    return {
        "n": len(graded),
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "hit_rate": wins / len(graded) if graded else None,
        "avg_odds": sum(odds) / len(odds) if odds else None,
        "staked_units": staked,
        "profit_units": profit,
        "roi": profit / staked if staked > 0 else None,
    }


def _result_publication_semantic_key(row, publication):
    """Stable identity for one public result, independent of lifecycle schema.

    Historical ledgers can contain two publication keys for the same event and
    selection after publication-key schema changes. Metrics and the public
    Results view must count that immutable bet once, not once per bookkeeping key.
    """
    event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
    market = str(publication.get("market") or "match_winner").strip().lower()
    scope = str(publication.get("projection_scope") or "").strip().lower()
    metric = str(publication.get("projection_metric") or "").strip().lower()
    selection = str(publication.get("selection_id") or publication.get("selection") or "").strip().lower()
    if event and selection:
        return (event, market, scope, metric, selection)
    return (str(publication.get("selection_key") or publication.get("publication_key") or ""),)


def _dedupe_result_publications(entries):
    unique = {}
    for row, publication in entries:
        key = _result_publication_semantic_key(row, publication)
        if not any(key):
            continue
        prior = unique.get(key)
        if prior is None or str(publication.get("issued_at") or "") < str(prior[1].get("issued_at") or ""):
            unique[key] = (row, publication)
    return list(unique.values())


def betting_performance(results):
    """Aggregate settled, actually-issued betting selections with flat 1u stakes."""
    entries = []
    for row in results:
        for publication in row.get("market_publications", []) or []:
            if isinstance(publication, dict) and publication.get("issued_at"):
                entries.append((row, publication))

    # Semantic dedupe is intentionally independent of selection_key/publication_key.
    # Those keys changed across historical schemas and can otherwise double-count
    # an identical event/market/selection after a migration.
    canonical_entries = _dedupe_result_publications(entries)
    canonical_publications = [publication for _, publication in canonical_entries]

    sections = {}
    for section in ("top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"):
        section_entries = [(row, p) for row, p in canonical_entries if p.get("section") == section]
        sections[section] = _betting_metrics([p for _, p in section_entries])
    markets = {}
    for market in sorted({str(p.get("market") or "") for _, p in entries if p.get("market")}):
        market_entries = _dedupe_result_publications([(row, p) for row, p in entries if p.get("market") == market])
        markets[market] = _betting_metrics([p for _, p in market_entries])
    projection_entries = _dedupe_result_publications([(row, p) for row, p in entries if str(p.get("market") or "").strip().lower() in {"aces", "double_faults", "sets", "games"}])
    projection_publications = [p for _, p in projection_entries]
    return {
        "schema": 2,
        "stake_model": "flat_1u",
        "overall": _betting_metrics(canonical_publications),
        "sections": sections,
        "markets": markets,
        "projections": {
            "overall": _projection_metrics(projection_publications),
            "aces": _projection_metrics([p for p in projection_publications if p.get("market") == "aces"]),
            "double_faults": _projection_metrics([p for p in projection_publications if p.get("market") == "double_faults"]),
            "sets": _projection_metrics([p for p in projection_publications if p.get("market") == "sets"]),
            "games": _projection_metrics([p for p in projection_publications if p.get("market") == "games"]),
        },
    }

PUBLIC_RESULT_SECTIONS = {"top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}

PERFORMANCE_WINDOWS_DAYS = (3, 7, 10, 14, 30)
PERFORMANCE_BEST_MIN_SAMPLE = 30


def _serving_row_time(row):
    raw = str(row.get("scheduled_at") or row.get("date") or "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _model_performance(rows):
    if not rows:
        return {}
    return evaluate_probabilities(
        [int(r["result"]["winner_id"] == r["player1"]["id"]) for r in rows],
        [r["player1"]["probability"] for r in rows],
    )


def performance_windows(winner_results, public_results, *, now):
    """Transparent rolling result windows used by dashboard and Results.

    The dashboard may highlight the strongest window, but every candidate window
    and its sample size is returned. A minimum sample protects the marketing card
    from choosing a tiny 1-3 match interval merely because it happens to be 100%.
    """
    windows = {}
    for days in PERFORMANCE_WINDOWS_DAYS:
        cutoff = now - timedelta(days=days)
        model_rows = [r for r in winner_results if (_serving_row_time(r) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        result_rows = [r for r in public_results if (_serving_row_time(r) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        model = _model_performance(model_rows)
        windows[str(days)] = {
            "days": days,
            "from": cutoff.isoformat(),
            "to": now.isoformat(),
            "settled_rows": len(result_rows),
            "model": model,
            "betting": betting_performance(result_rows),
        }

    candidates = []
    for days in PERFORMANCE_WINDOWS_DAYS:
        model = windows[str(days)]["model"]
        accuracy = model.get("accuracy") if isinstance(model, dict) else None
        n = int(model.get("n") or 0) if isinstance(model, dict) else 0
        if isinstance(accuracy, (int, float)) and math.isfinite(float(accuracy)):
            candidates.append((days, float(accuracy), n))
    eligible = [item for item in candidates if item[2] >= PERFORMANCE_BEST_MIN_SAMPLE]
    if eligible:
        best_days, best_accuracy, best_n = max(eligible, key=lambda item: (item[1], item[2], -item[0]))
        mode = "best_accuracy_min_sample"
    elif candidates:
        best_days, best_accuracy, best_n = max(candidates, key=lambda item: (item[2], item[1], -item[0]))
        mode = "largest_available_sample"
    else:
        best_days = best_accuracy = best_n = None
        mode = "no_settled_model_results"
    category_map = {
        "top_daily": ("betting", "sections", "top_daily"),
        "prime": ("betting", "sections", "prime"),
        "value": ("betting", "sections", "value"),
        "doubles": ("betting", "sections", "doubles"),
        "ace": ("betting", "projections", "aces"),
        "double_faults": ("betting", "projections", "double_faults"),
        "sets": ("betting", "projections", "sets"),
        "games": ("betting", "projections", "games"),
    }
    category_best = {}
    for category, path in category_map.items():
        category_candidates = []
        for days in PERFORMANCE_WINDOWS_DAYS:
            metric = windows[str(days)]
            for key in path:
                metric = metric.get(key, {}) if isinstance(metric, dict) else {}
            rate = metric.get("hit_rate") if isinstance(metric, dict) else None
            n = int(metric.get("n") or 0) if isinstance(metric, dict) else 0
            if isinstance(rate, (int, float)) and math.isfinite(float(rate)) and n > 0:
                category_candidates.append((days, float(rate), n))
        category_eligible = [item for item in category_candidates if item[2] >= PERFORMANCE_BEST_MIN_SAMPLE]
        if category_eligible:
            c_days, c_rate, c_n = max(category_eligible, key=lambda item: (item[1], item[2], -item[0]))
            c_mode = "best_hit_rate_min_sample"
        elif category_candidates:
            # With young history use the largest sample, never a tiny perfect
            # streak. The UI always displays n and the chosen window.
            c_days, c_rate, c_n = max(category_candidates, key=lambda item: (item[2], item[1], -item[0]))
            c_mode = "largest_available_sample"
        else:
            c_days = c_rate = c_n = None
            c_mode = "no_settled_results"
        category_best[category] = {
            "best_days": c_days, "best_hit_rate": c_rate, "best_n": c_n,
            "selection_mode": c_mode, "minimum_sample_for_best": PERFORMANCE_BEST_MIN_SAMPLE,
        }

    summary = {
        "windows_days": list(PERFORMANCE_WINDOWS_DAYS),
        "minimum_sample_for_best": PERFORMANCE_BEST_MIN_SAMPLE,
        "selection_mode": mode,
        "best_days": best_days,
        "best_accuracy": best_accuracy,
        "best_n": best_n,
        "categories": category_best,
        "transparent_all_windows": True,
    }
    return windows, summary


def reconcile_ledger(ledger, predictions, history, now=None):
    now = now or datetime.now(timezone.utc)
    stored = {row["event_id"]: deepcopy(row) for row in ledger}
    for row in predictions:
        # Freeze the first prediction. Never rewrite history after learning result.
        if datetime.fromisoformat(row["scheduled_at"]) <= now:
            continue
        if row["event_id"] not in stored:
            stored[row["event_id"]] = {
                **row,
                "issued_at": None,
                "publication_status": "pending",
            }
        existing = stored[row["event_id"]]
        if {existing["player1"]["id"], existing["player2"]["id"]} != {row["player1"]["id"], row["player2"]["id"]}:
            raise ValueError("Prediction identity mismatch")
        _merge_market_publication_candidates(existing, row)
        if existing.get("result") is None:
            # Safe fixture metadata may be filled after the original probability
            # commitment. This never changes the published winner probability.
            if existing.get("best_of") in (None, "") and row.get("best_of") in {3, 5}:
                existing["best_of"] = row.get("best_of")
            if not existing.get("best_of_source") and row.get("best_of_source"):
                existing["best_of_source"] = row.get("best_of_source")
            existing.setdefault("original_scheduled_at", existing["scheduled_at"])
            existing["scheduled_at"] = row["scheduled_at"]
    # Provider IDs are not sufficient evidence of identity. Keep all candidates
    # instead of silently accepting whichever history row happens to come last.
    completed = {}
    for match in history:
        if match.is_completed:
            completed.setdefault(event_id(match), []).append(match)
    for key, row in stored.items():
        candidates = completed.get(key, [])
        if not candidates:
            continue
        expected = {row["player1"]["id"], row["player2"]["id"]}
        identities_match = all(
            expected == {match.player1_id, match.player2_id}
            for match in candidates
        )
        outcomes = {(match.winner_id, match.scheduled_at) for match in candidates}
        if not identities_match or len(outcomes) != 1:
            reason = "player_identity_mismatch" if not identities_match else "conflicting_completed_results"
            conflict = {
                "reason": reason,
                "event_id": str(key),
                "expected_player_ids": sorted(expected),
                "candidates": [
                    {"match_id": match.match_id,
                     "player_ids": sorted({match.player1_id, match.player2_id}),
                     "winner_id": match.winner_id,
                     "scheduled_at": match.scheduled_at.isoformat()}
                    for match in candidates
                ],
            }
            row["settlement_quarantine"] = conflict
            print(json.dumps({"warning": "settlement_identity_quarantined", **conflict}), flush=True)
            # Preserve commitments and prior results for audit. Neither these
            # results nor this fixture may enter the public feed while ambiguous.
            continue
        match = candidates[0]
        row.pop("settlement_quarantine", None)

        # The provider may correct the actual start after settlement. Scheduled
        # time is mutable, but the published probability/issuance timestamp is not.
        row.setdefault("original_scheduled_at", row["scheduled_at"])
        row["scheduled_at"] = match.scheduled_at.isoformat()
        _settle_match_winner_publications(row, match, now)
        _settle_projection_publications(row, match, now)
        _settle_sg_projection_publications(row, match, now)
        issued_at = row.get("issued_at")
        if not issued_at:
            # Pending predictions are never scored until a successful public
            # deployment confirms that they were actually available pre-match.
            continue

        existing_result = row.get("result")
        void_reason = _match_void_reason(match)
        corrected_result = None
        if existing_result is not None:
            if void_reason:
                corrected_result = {
                    **existing_result,
                    "status": "void",
                    "reason": void_reason,
                    "winner_id": match.winner_id,
                    "correct": None,
                    "scheduled_at": match.scheduled_at.isoformat(),
                }
                if (
                    existing_result.get("status") != "void"
                    or existing_result.get("reason") != void_reason
                    or existing_result.get("correct") is not None
                ):
                    corrected_result["corrected_at"] = now.isoformat()
            else:
                corrected_result = {
                    **existing_result,
                    "winner_id": match.winner_id,
                    "correct": row["winner_id"] == match.winner_id,
                    "scheduled_at": match.scheduled_at.isoformat(),
                }
                corrected_result.pop("status", None)
                corrected_result.pop("reason", None)
                if (
                    existing_result.get("status") == "void"
                    or existing_result.get("winner_id") != match.winner_id
                    or existing_result.get("correct")
                    != (row["winner_id"] == match.winner_id)
                ):
                    corrected_result["corrected_at"] = now.isoformat()

        if datetime.fromisoformat(issued_at) >= match.scheduled_at:
            row["excluded_reason"] = "issued_after_actual_start"
            if corrected_result is not None:
                row["result"] = corrected_result
            continue

        if row.get("excluded_reason") == "issued_after_actual_start":
            row.pop("excluded_reason", None)

        if corrected_result is not None:
            row["result"] = corrected_result
            continue

        row["result"] = {
            "winner_id": match.winner_id,
            "correct": None if void_reason else row["winner_id"] == match.winner_id,
            "settled_at": now.isoformat(),
            "scheduled_at": match.scheduled_at.isoformat(),
            **({"status": "void", "reason": void_reason} if void_reason else {}),
        }
    return sorted(stored.values(), key=lambda r: r["scheduled_at"])




def serving_feed(ledger, model, history, report, upcoming, now=None):
    now = now or datetime.now(timezone.utc)
    future = {event_id(m) for m in upcoming if m.scheduled_at > now
              and not m.is_completed and m.status in {"upcoming", "notstarted", "scheduled"}}

    def _issued_at(value):
        if not value:
            return None
        try:
            issued = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if issued.tzinfo is None:
            return None
        return issued.astimezone(timezone.utc)

    def public_publications(row):
        publications = []
        for publication in row.get("market_publications", []) or []:
            if not isinstance(publication, dict) or _issued_at(publication.get("issued_at")) is None:
                continue
            if publication.get("excluded_reason") or not isinstance(publication.get("result"), dict):
                continue
            publications.append(deepcopy(publication))
        return publications

    def legacy_match_winner_publication(source):
        """Expose older row-level published winner picks in Results transparently.

        Pre market-publication ledgers stored the immutable public commitment on
        the prediction row itself (issued_at/result) rather than in
        market_publications.  Those rows are real public history, not backfills.
        Represent them as ``model_only`` publications so users can inspect the
        exact result without inventing historical bookmaker odds or ROI.
        """
        if not isinstance(source.get("result"), dict) or _issued_at(source.get("issued_at")) is None:
            return None
        winner_id = str(source.get("winner_id") or "")
        p1 = source.get("player1") if isinstance(source.get("player1"), dict) else {}
        p2 = source.get("player2") if isinstance(source.get("player2"), dict) else {}
        selected = p1 if str(p1.get("id") or "") == winner_id else p2 if str(p2.get("id") or "") == winner_id else {}
        if not selected:
            return None
        result = deepcopy(source["result"])
        # A legacy winner pick was not necessarily a wager.  Do not manufacture
        # stake/profit fields; this keeps betting ROI strictly on priced picks.
        result.pop("staked_units", None)
        result.pop("return_units", None)
        result.pop("profit_units", None)
        return {
            "publication_key": f"legacy_match_winner:{source.get('event_id') or source.get('id') or ''}",
            "section": "model",
            "market": "match_winner",
            "selection_id": selected.get("id"),
            "selection": selected.get("name"),
            "model_probability": selected.get("probability"),
            "odds": None,
            "price_status": "model_only",
            "issued_at": source.get("issued_at"),
            "publication_status": "published",
            "result": result,
        }

    # Never expose offline/backfilled rows merely because they have an outcome.
    # A public Results row must have immutable issuance evidence: either the
    # match-winner commitment itself was issued, or at least one section/market
    # publication was issued and later settled. Unlike the old 2026-09-19 reset,
    # there is no artificial date cutoff, so genuine older public history remains
    # available for transparent 3/7/10/14/30-day and custom-period inspection.
    results = []
    for source in ledger:
        if source.get("excluded_reason") or source.get("settlement_quarantine"):
            continue
        publications = public_publications(source)
        winner_was_issued = (
            isinstance(source.get("result"), dict)
            and _issued_at(source.get("issued_at")) is not None
        )
        if winner_was_issued and not any(str(p.get("market") or "") == "match_winner" for p in publications):
            legacy = legacy_match_winner_publication(source)
            if legacy is not None:
                publications.append(legacy)
        if not publications and not winner_was_issued:
            continue
        row = deepcopy(source)
        row["market_publications"] = publications
        results.append(row)

    # The public Results page is intentionally narrower than the internal model
    # ledger. Only predictions that were actually published in a named BlinQ
    # product category are exposed. Legacy/model-only winner rows stay available
    # to model-quality calculations but never inflate TOP / Short Odds / Value
    # or the "all published" Results table.
    public_results = []
    for row in results:
        publications = [
            deepcopy(p) for p in row.get("market_publications", []) or []
            if isinstance(p, dict) and str(p.get("section") or "").strip().lower() in PUBLIC_RESULT_SECTIONS
        ]
        if publications:
            copy = deepcopy(row)
            copy["market_publications"] = publications
            public_results.append(copy)

    # Model-success KPIs count only match-winner predictions that themselves have
    # immutable issuance evidence. A row published solely for an Aces/DF/S/G
    # projection must not silently enter winner-model accuracy. Legacy row-level
    # publications are represented above as model_only match-winner publications.
    winner_results = [
        r for r in results
        if isinstance(r.get("result"), dict)
        and r["result"].get("correct") in {True, False}
        and str(r["result"].get("status") or "").strip().lower() != "void"
        and _issued_at(r.get("issued_at")) is not None
        and any(str(p.get("market") or "") == "match_winner" for p in r.get("market_publications", []) or [])
        and r.get("prediction_family") != "doubles"
    ]
    metrics = _model_performance(winner_results)
    quality_frame = pd.DataFrame([{'target': int(r['result']['winner_id'] == r['player1']['id']),
        'tour': r['tour'], 'surface': r['surface'], 'competition': r.get('competition', 'unknown'),
        'tournament': r.get('tournament', 'unknown'),
        'history_band': r.get('quality', {}).get('history_band', 'unknown'),
        'surface_history_band': r.get('quality', {}).get('surface_history_band', 'unknown')} for r in winner_results])
    quality_report = subgroup_report(quality_frame, [r['player1']['probability'] for r in winner_results]) if winner_results else {}
    betting = betting_performance(public_results)
    rolling_performance, rolling_summary = performance_windows(winner_results, public_results, now=now)
    # Do not rely on incidental ledger ordering. Recent settled rows must never
    # disappear from the 1000-row public window after a merge/migration.
    result_rows = sorted(
        public_results,
        key=lambda row: datetime.fromisoformat(str(row.get("scheduled_at") or "1970-01-01T00:00:00+00:00").replace("Z", "+00:00")),
        reverse=True,
    )[:1000]
    return {"schema": 1, "ready": True, "generated_at": now.isoformat(),
            "model": {"version": model.version, "report": report, "objective": "accuracy"},
            "upcoming": [r for r in ledger if r["event_id"] in future and r.get("result") is None
                         and datetime.fromisoformat(r["scheduled_at"]) > now
                         and not r.get("excluded_reason") and not r.get("settlement_quarantine")],
            "results": result_rows, "performance": metrics,
            "betting_performance": betting,
            "performance_windows": rolling_performance,
            "performance_window_summary": rolling_summary,
            # Public marketing KPI only. Results/history entitlement rules stay
            # untouched; lower levels receive this single scalar without the
            # underlying rolling-window detail.
            "dashboard_model_success": {
                "accuracy": rolling_summary.get("best_accuracy"),
            },
            "results_meta": {"settled_total": len(public_results), "returned": len(result_rows), "limit": 1000,
                             "history_cutoff": None,
                             "history_reset": False,
                             "history_policy": "all_actually_issued_settled"},
            "performance_subgroups": quality_report,
            "history": {"matches": len(history), "start": min((m.scheduled_at for m in history), default=now).isoformat(),
                        "end": max((m.scheduled_at for m in history), default=now).isoformat()}}
