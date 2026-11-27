"""Aggregate provider attempts without storing URLs, identifiers or response bodies."""
from collections import Counter, defaultdict
import re


class HourlyHttpMetrics:
    def __init__(self):
        self.endpoints = defaultdict(Counter)
        self.rejections = Counter()

    def record(self, path, status, result):
        endpoint = re.sub(r"(?<=/)-?\d+(?=/|$)", "{id}", path.split("?", 1)[0])
        self.endpoints[endpoint][f"{status}_{result}" if status is not None else result] += 1

    def snapshot(self):
        return {
            "endpoints": {endpoint: dict(counts) for endpoint, counts in self.endpoints.items()},
            "rejections": dict(self.rejections),
        }


def usable_payload(path, payload):
    if path.endswith("/statistics"):
        periods = payload.get("statistics") if isinstance(payload, dict) else None
        return isinstance(periods, list) and any(
            isinstance(period, dict) and period.get("period") == "ALL" and period.get("groups")
            for period in periods
        )
    if path.endswith("/point-by-point"):
        sets = payload.get("pointByPoint", payload) if isinstance(payload, dict) else payload
        if isinstance(sets, dict):
            sets = sets.get("sets")
        return isinstance(sets, list) and any(
            isinstance(row, dict) and isinstance(row.get("games"), list) and any(
                isinstance(game, dict) and game.get("points") for game in row["games"]
            ) for row in sets
        )
    if path.endswith("/all"):
        markets = payload.get("markets") if isinstance(payload, dict) else None
        return isinstance(markets, list) and any(
            isinstance(market, dict) and market.get("choices") for market in markets
        )
    return bool(payload)
