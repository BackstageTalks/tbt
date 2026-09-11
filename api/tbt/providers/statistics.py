"""Conservative normalisation of whole-match TennisApi statistics.

Only an unambiguous ``ALL`` period is accepted. Rate fields and raw count fields
are kept separate so an integer such as ``8`` aces can never be mistaken for an
800% rate. Unknown shapes still fail closed.
"""
from __future__ import annotations

import math
import re

from ..errors import ProviderError


class NoSupportedStatisticsError(ProviderError):
    """Valid statistics payload that contains none of the fields we consume."""

from ..utils import normalize_rate


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def _fraction(item, side):
    """Prefer counts, then explicit fractions/percentages; never guess count units."""
    won, total = _number(item.get(side + "Value")), _number(item.get(side + "Total"))
    if won is not None and total is not None and total > 0 and won <= total:
        return won / total, won, total
    text = str(item.get(side, "")).strip()
    ratio = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if ratio:
        won, total = map(float, ratio.groups())
        if total > 0 and won <= total:
            return won / total, won, total
    percent = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent:
        value = normalize_rate(percent.group(0))
        if value is not None:
            return value, None, None
    return None, None, None


def _count(item, side):
    """Extract a raw non-negative whole-match count without inventing units."""
    # SofaScore-like payloads commonly expose the raw number either directly in
    # ``home``/``away`` or in ``homeValue``/``awayValue``. Do not use *Total
    # fields here: for serve ratios those are denominators, not event counts.
    for key in (side + "Value", side):
        raw = item.get(key)
        if isinstance(raw, str):
            text = raw.strip()
            # Reject ratios/percentages for a count statistic.
            if not text or "/" in text or "%" in text:
                continue
        value = _number(raw)
        if value is not None:
            return value
    return None


RATE_ALIASES = {
    "firstservepoints": "first_serve_win", "firstservepointswon": "first_serve_win",
    "1stservepointswon": "first_serve_win", "1stservepoints": "first_serve_win",
    "secondservepoints": "second_serve_win", "secondservepointswon": "second_serve_win",
    "2ndservepointswon": "second_serve_win", "2ndservepoints": "second_serve_win",
    "servicepointswon": "service_points_won", "servicepoints": "service_points_won",
    "returnpointswon": "return_points_won", "returnpoints": "return_points_won",
    "breakpointsconverted": "break_points_won",
}

COUNT_ALIASES = {
    "ace": "aces",
    "aces": "aces",
    "doublefault": "double_faults",
    "doublefaults": "double_faults",
    "doublefaulterrors": "double_faults",
}


def parse_statistics(payload: dict, *, home_is_player1: bool) -> dict[str, float]:
    if payload == {} or payload.get("statistics") == []:
        return {}
    periods = payload.get("statistics")
    if not isinstance(periods, list):
        raise ProviderError("Unsupported statistics envelope; preserve sample and update adapter")
    whole = [p for p in periods if isinstance(p, dict) and str(p.get("period", "")).upper() == "ALL"]
    if len(whole) != 1 or not isinstance(whole[0].get("groups"), list):
        raise ProviderError("Missing unambiguous ALL period in statistics")

    values: dict[str, float] = {}
    rate_counts = {}
    for group in whole[0]["groups"]:
        if not isinstance(group, dict):
            continue
        for item in group.get("statisticsItems", []):
            if not isinstance(item, dict):
                continue
            key = re.sub(r"[^a-z0-9]", "", str(item.get("key") or item.get("name") or "").lower())
            rate_name = RATE_ALIASES.get(key)
            count_name = COUNT_ALIASES.get(key)
            if not rate_name and not count_name:
                continue

            for side in ("home", "away"):
                prefix = "p1" if (side == "home") == home_is_player1 else "p2"
                if count_name:
                    count = _count(item, side)
                    if count is None:
                        continue
                    field = f"{prefix}_{count_name}"
                    if field in values and abs(values[field] - count) > 1e-6:
                        raise ProviderError(f"Conflicting whole-match statistic: {field}")
                    values[field] = count
                    continue

                value, won, total = _fraction(item, side)
                if value is None:
                    continue
                field = f"{prefix}_{rate_name}"
                if field in values and abs(values[field] - value) > 1e-6:
                    raise ProviderError(f"Conflicting whole-match statistic: {field}")
                values[field] = value
                if total is not None:
                    rate_counts[field] = (won, total)

    for prefix, opponent in (("p1", "p2"), ("p2", "p1")):
        first, second = (rate_counts.get(f"{prefix}_{kind}_serve_win") for kind in ("first", "second"))
        if first is not None and second is not None and first[1] + second[1] > 0:
            service = (first[0] + second[0]) / (first[1] + second[1])
            values.setdefault(f"{prefix}_service_points_won", service)
            values.setdefault(f"{opponent}_return_points_won", 1 - service)

    if not values:
        raise NoSupportedStatisticsError("Statistics contain no supported rate/count fields; no imputation performed")
    return values
