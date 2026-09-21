"""Tennis match-format normalization.

The format pipeline deliberately separates *facts* from *inference*:

* completed historical matches use provider ``bestOf`` when present, otherwise
  the final structured set score proves BO3/BO5 exactly;
* upcoming matches may use a small, auditable ruleset only for conventional
  singles formats;
* ambiguous/non-standard formats fail closed instead of being guessed.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


_GRAND_SLAM_TOKENS = (
    "grand slam",
    "australian open",
    "roland garros",
    "french open",
    "wimbledon",
    "us open",
    "u.s. open",
)

_NON_MAIN_DRAW_TOKENS = (
    "qualif",
    "qualification",
    "qualifying",
    "junior",
    "juniors",
    "boys",
    "girls",
    "wheelchair",
)

_UNSUPPORTED_FORMAT_TOKENS = (
    "next gen",
    "fast4",
    "ultimate tennis showdown",
    "uts ",
    "doubles",
    "double",
    "mixed",
)


def _int(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or abs(number - round(number)) > 1e-9:
        return None
    return int(round(number))


def exact_best_of_from_score_stats(stats: Mapping[str, Any] | None) -> tuple[int | None, str]:
    """Derive BO3/BO5 from a *finished structured score* without guessing.

    In a conventional completed singles match the winner must have exactly two
    set wins (BO3) or three set wins (BO5).  We additionally require
    ``total_sets == p1_sets_won + p2_sets_won`` so partial/contradictory rows are
    rejected.  This is a fact derived from the stored final score, not a tour
    heuristic.
    """
    if not isinstance(stats, Mapping):
        return None, "score_unavailable"
    p1 = _int(stats.get("p1_sets_won"))
    p2 = _int(stats.get("p2_sets_won"))
    total = _int(stats.get("total_sets"))
    if p1 is None or p2 is None or total is None:
        return None, "score_unavailable"
    if p1 < 0 or p2 < 0 or total < 2 or p1 == p2 or p1 + p2 != total:
        return None, "score_inconsistent"
    winner_sets = max(p1, p2)
    if winner_sets == 2:
        return 3, "structured_finished_score"
    if winner_sets == 3:
        return 5, "structured_finished_score"
    return None, "score_unsupported"


def explicit_best_of_from_event(event: Mapping[str, Any] | None) -> int | None:
    """Read only explicit provider format fields from an event payload.

    Provider detail responses are sometimes wrapped as ``{"event": {...}}``.
    We inspect that wrapper and the event object, but never infer a value from
    tournament naming here.
    """
    if not isinstance(event, Mapping):
        return None
    candidates: list[Mapping[str, Any]] = [event]
    nested = event.get("event")
    if isinstance(nested, Mapping):
        candidates.insert(0, nested)
    for candidate in candidates:
        for key in ("bestOf", "best_of", "setsToPlay", "sets_to_play"):
            value = _int(candidate.get(key))
            if value in {3, 5}:
                return value
    return None


def provider_best_of_from_context(payload: Mapping[str, Any] | None) -> int | None:
    """Recover an explicitly provider-sourced BO3/BO5 from compact history context."""
    if not isinstance(payload, Mapping):
        return None
    direct = explicit_best_of_from_event(payload)
    if direct in {3, 5}:
        return direct
    marker = payload.get("_tbt_match_format")
    if isinstance(marker, Mapping):
        if str(marker.get("source") or "") in {"provider", "provider_payload", "provider_detail"}:
            value = _int(marker.get("best_of"))
            if value in {3, 5}:
                return value
        # Preserve the explicit provider side of a recorded conflict so callers
        # can continue to fail closed after compact-history round trips.
        value = _int(marker.get("provider_best_of"))
        if value in {3, 5}:
            return value
    score_marker = payload.get("_tbt_score")
    if isinstance(score_marker, Mapping) and str(score_marker.get("best_of_source") or "") in {"provider", "provider_payload", "provider_detail"}:
        value = _int(score_marker.get("best_of"))
        if value in {3, 5}:
            return value
    return None


def infer_best_of(
    *,
    explicit: Any = None,
    tour: Any = "",
    tournament: Any = "",
    tournament_level: Any = "",
    round_name: Any = "",
    total_sets: Any = None,
) -> tuple[int | None, str]:
    """Return ``(best_of, source)`` using conservative pre-match rules.

    This helper is for rows where a final structured score is not available
    (notably upcoming fixtures).  Completed history should prefer
    :func:`exact_best_of_from_score_stats`.
    """
    value = _int(explicit)
    if value in {3, 5}:
        return value, "provider"

    sets_value = _int(total_sets)
    if sets_value is not None and sets_value >= 4:
        return 5, "structured_score_minimum"

    tour_text = _text(tour)
    tournament_text = _text(tournament)
    level_text = _text(tournament_level)
    round_text = _text(round_name)
    context = " ".join(part for part in (tournament_text, level_text, round_text) if part)

    if any(token in f" {context} " for token in _UNSUPPORTED_FORMAT_TOKENS):
        return None, "unsupported_format"

    non_main_draw = any(token in context for token in _NON_MAIN_DRAW_TOKENS)
    is_slam = any(token in context for token in _GRAND_SLAM_TOKENS)

    if tour_text.startswith("wta"):
        return 3, "inferred_wta_standard"
    if tour_text.startswith("itf"):
        return 3, "inferred_itf_standard"
    if "challenger" in tour_text or "challenger" in level_text:
        return 3, "inferred_challenger_standard"
    if tour_text.startswith("atp"):
        if is_slam and not non_main_draw:
            return 5, "inferred_atp_grand_slam_main"
        return 3, "inferred_atp_standard"

    return None, "unknown"
