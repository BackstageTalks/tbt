"""Fail-closed finished-season surface profile from TennisApi, research only.

Never use a calendar-year summary as a historical in-season snapshot; it can
include matches played after the prediction date. These are player-year
aggregates, not missing statistics of any one canonical match.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..errors import ProviderError


_ALLOWED_SURFACES = {
    "Grass", "Hardcourt indoor", "Hardcourt outdoor",
    "Red clay", "Red clay indoor",
}
_REQUIRED = (
    "matches", "wins", "totalServeAttempts",
    "firstServeTotal", "firstServePointsTotal", "firstServePointsScored",
    "secondServeTotal", "secondServePointsTotal", "secondServePointsScored",
    "doubleFaults", "aces",
    "breakPointsScored", "breakPointsTotal",
    "opponentBreakPointsScored", "opponentBreakPointsTotal",
)
_OPTIONAL = ("winnersTotal", "unforcedErrorsTotal", "tiebreakLosses",
             "tiebreaksWon", "tournamentsWon", "tournamentsPlayed")


def completed_year_surface_profile(payload, *, team_id, year, observed_at):
    """Return explicit cross-checked counts for a past, finished calendar year.

    `team_id` and `year` MUST come from the exact requested API route.
    Neither is reliably encoded in the response. `observed_at` is our own
    download time, not proof of an independently complete provider season.
    """
    if (type(team_id) not in (str, int) or not str(team_id).isascii()
            or not str(team_id).isdecimal() or int(team_id) <= 0):
        raise ValueError("Verified numeric team ID required")
    if (type(year) is not int or not 2010 <= year <= 2100
            or not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.astimezone(timezone.utc).year <= year):
        raise ValueError("Only past completed years may be profiled")
    if not isinstance(payload, dict) or not isinstance(payload.get("statistics"), list):
        raise ProviderError("Unsupported annual tennis statistics envelope")
    data = payload["statistics"]
    if not 0 < len(data) <= len(_ALLOWED_SURFACES):
        raise ProviderError("Empty/duplicate-heavy yearly surface statistics")
    seen = set()
    profiles = {}
    total = {key: 0 for key in _REQUIRED}
    for item in data:
        if not isinstance(item, dict):
            raise ProviderError("Malformed annual surface row")
        surface = item.get("groundType")
        if surface not in _ALLOWED_SURFACES or surface in seen:
            raise ProviderError("Unknown or repeated tennis surface")
        seen.add(surface)
        values = {}
        for key in _REQUIRED:
            value = item.get(key)
            if type(value) is not int or value < 0:
                raise ProviderError(f"Missing/non-integer annual statistic: {key}")
            values[key] = value
            total[key] += value
        for key in _OPTIONAL:
            value = item.get(key)
            if value is None:
                values[key] = None
            elif type(value) is int and value >= 0:
                values[key] = value
            else:
                raise ProviderError(f"Malformed optional annual statistic: {key}")
        if (values["wins"] > values["matches"]
                or values["firstServeTotal"] + values["secondServeTotal"]
                != values["totalServeAttempts"]
                or values["firstServeTotal"] - values["firstServePointsTotal"]
                != values["secondServeTotal"]
                or values["secondServeTotal"] - values["secondServePointsTotal"]
                != values["doubleFaults"]
                or values["firstServePointsScored"] > values["firstServePointsTotal"]
                or values["secondServePointsScored"] > values["secondServePointsTotal"]
                or values["aces"] > values["firstServePointsScored"]
                or values["breakPointsScored"] > values["breakPointsTotal"]
                or values["opponentBreakPointsScored"]
                > values["opponentBreakPointsTotal"]):
            raise ProviderError("Annual surface statistics violate point conservation")
        service_won = values["firstServePointsScored"] + values["secondServePointsScored"]
        service_total = values["firstServeTotal"]
        values["service_points_won_rate"] = (service_won / service_total if service_total else None)
        values["break_point_conversion_rate"] = (
            values["breakPointsScored"] / values["breakPointsTotal"]
            if values["breakPointsTotal"] else None
        )
        values["break_point_save_rate"] = (
            (values["opponentBreakPointsTotal"] - values["opponentBreakPointsScored"])
            / values["opponentBreakPointsTotal"]
            if values["opponentBreakPointsTotal"] else None
        )
        profiles[surface] = values
    service_total = total["firstServeTotal"]
    first_won = total["firstServePointsScored"]
    second_won = total["secondServePointsScored"]
    return {
        "schema": 1, "source": "tennisapi1",
        "requested_team_id": str(team_id), "requested_year": year,
        "observed_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "season_ended_before_observation": True,
        "provider_season_coverage_independently_verified": False,
        "eligible_for_pre_match_features": False,
        "eligible_for_match_level_cdb_fill": False,
        "summary": {
            "matches": total["matches"], "wins": total["wins"],
            "aces": total["aces"], "double_faults": total["doubleFaults"],
            "service_points_won": first_won + second_won,
            "service_points_total": service_total,
            "service_points_won_rate": (first_won + second_won) / service_total if service_total else None,
            "bp_converted": total["breakPointsScored"],
            "bp_chances": total["breakPointsTotal"],
            "bp_saved": total["opponentBreakPointsTotal"] - total["opponentBreakPointsScored"],
            "bp_faced": total["opponentBreakPointsTotal"],
        },
        "by_surface": profiles, "provider_requests": 0, "production_mutated": False,
    }
