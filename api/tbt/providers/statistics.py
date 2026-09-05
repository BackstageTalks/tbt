"""Conservative normalisation of whole-match statistics; unknown shapes fail closed.

The public RapidAPI example is empty. Supported grouped payloads must still be
smoke-tested against the subscribed feed before enabling scheduled enrichment.
"""
from __future__ import annotations

import math
import re

from ..errors import ProviderError
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


ALIASES = {
    "firstservepoints": "first_serve_win", "firstservepointswon": "first_serve_win",
    "1stservepointswon": "first_serve_win", "1stservepoints": "first_serve_win",
    "secondservepoints": "second_serve_win", "secondservepointswon": "second_serve_win",
    "2ndservepointswon": "second_serve_win", "2ndservepoints": "second_serve_win",
    "servicepointswon": "service_points_won", "servicepoints": "service_points_won",
    "returnpointswon": "return_points_won", "returnpoints": "return_points_won",
    "breakpointsconverted": "break_points_won",
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
    values, counts = {}, {}
    for group in whole[0]["groups"]:
        if not isinstance(group, dict):
            continue
        for item in group.get("statisticsItems", []):
            if not isinstance(item, dict):
                continue
            key = re.sub(r"[^a-z0-9]", "", str(item.get("key") or item.get("name") or "").lower())
            canonical = ALIASES.get(key)
            if not canonical:
                continue
            for side in ("home", "away"):
                value, won, total = _fraction(item, side)
                if value is None:
                    continue
                prefix = "p1" if (side == "home") == home_is_player1 else "p2"
                field = f"{prefix}_{canonical}"
                if field in values and abs(values[field] - value) > 1e-6:
                    raise ProviderError(f"Conflicting whole-match statistic: {field}")
                values[field] = value
                if total is not None:
                    counts[field] = (won, total)
    for prefix, opponent in (("p1", "p2"), ("p2", "p1")):
        first, second = (counts.get(f"{prefix}_{kind}_serve_win") for kind in ("first", "second"))
        if first is not None and second is not None:
            service = (first[0] + second[0]) / (first[1] + second[1])
            values.setdefault(f"{prefix}_service_points_won", service)
            values.setdefault(f"{opponent}_return_points_won", 1 - service)
    if not values:
        raise ProviderError("Statistics contain no supported rate fields; no imputation performed")
    return values
