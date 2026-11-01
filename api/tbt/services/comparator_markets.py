"""Read-only, point-in-time Aces/DF evidence for Match Comparator.

Uses exactly the pre-cutoff canonical replay already audited for the champion.
No provider calls, canonical writes, or new betting/odds model.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Mapping

from .ace_selection import _projection

MARKETS = ("aces", "double_faults")
MAX_SAMPLES_PER_PLAYER = 160


def _count(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def build_market_state(replay, allowed_keys: set[str], cutoff: datetime) -> dict:
    if cutoff.tzinfo is None:
        raise ValueError("market cutoff must be timezone-aware")
    cutoff = cutoff.astimezone(timezone.utc)
    rows = defaultdict(list)
    totals = defaultdict(list)
    complete = 0
    # Stable ordering, even if provider partitions were loaded in a different order.
    for match in sorted(replay, key=lambda x: (x.scheduled_at, str(x.match_id))):
        if match.scheduled_at >= cutoff or str(match.status).lower() != "completed":
            continue
        tour = str(match.tour or "").lower()
        if tour not in ("atp", "wta"):
            continue
        raw = match.stats if isinstance(match.stats, dict) else {}
        values = {field: (_count(raw.get("p1_" + field)), _count(raw.get("p2_" + field)))
                  for field in MARKETS}
        if all(v is None for pair in values.values() for v in pair):
            continue
        complete += 1
        for field, pair in values.items():
            totals[(tour, field)].extend(v for v in pair if v is not None)
        common = {
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
            "surface": str(match.surface or "unknown").lower(),
            "best_of": match.best_of,
        }
        for idx, player_id in enumerate((match.player1_id, match.player2_id)):
            key = f"{tour}:{player_id}"
            if key not in allowed_keys:
                continue
            record = dict(common)
            for field, pair in values.items():
                record["own_" + field] = pair[idx]
                record["opponent_" + field] = pair[1 - idx]
            rows[key].append(record)
    players = {}
    for key in sorted(allowed_keys):
        samples = rows.get(key, [])[-MAX_SAMPLES_PER_PLAYER:]
        players[key] = {
            "samples": samples,
            "sample_window": MAX_SAMPLES_PER_PLAYER,
            "last_stat_match": samples[-1]["scheduled_at"] if samples else None,
        }
    baselines = {
        tour: {field: (sum(totals[(tour, field)]) / len(totals[(tour, field)])
                       if totals[(tour, field)] else None) for field in MARKETS}
        for tour in ("atp", "wta")
    }
    return {
        "schema": 1,
        "cutoff_utc": cutoff.isoformat(),
        "baselines": baselines,
        "players": players,
        "canonical_stat_matches": complete,
        "provider_requests": 0,
    }


def project_market_state(state: Mapping | None, *, left_key: str, right_key: str,
                         tour: str, surface: str, best_of: int, now: datetime,
                         cutoff: datetime) -> dict:
    """Unavailable stays NULL; no cross-tour borrowing or synthetic match sample."""
    unavailable = {"aces": None, "double_faults": None}
    if not isinstance(state, Mapping) or state.get("schema") != 1:
        return unavailable
    if str(state.get("cutoff_utc")) != cutoff.isoformat():
        return unavailable
    if str(state.get("provider_requests")) != "0":
        return unavailable
    players = state.get("players")
    baselines = state.get("baselines")
    if not isinstance(players, Mapping) or not isinstance(baselines, Mapping):
        return unavailable
    tour_base = baselines.get(tour)
    if not isinstance(tour_base, Mapping):
        return unavailable

    histories = {}
    for key in (left_key, right_key):
        value = players.get(key)
        if not isinstance(value, Mapping) or not isinstance(value.get("samples"), list):
            return unavailable
        parsed = []
        for row in value["samples"]:
            if not isinstance(row, Mapping):
                return unavailable
            try:
                moment = datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00"))
                if moment.tzinfo is None or not moment < cutoff:
                    return unavailable
            except (KeyError, ValueError, TypeError):
                return unavailable
            parsed.append({**row, "scheduled_at": moment.astimezone(timezone.utc)})
        histories[key] = parsed

    result = {}
    for market in MARKETS:
        baseline = _count(tour_base.get(market))
        if baseline is None:
            result[market] = None
            continue
        a = _projection(left_key, right_key, market, histories, baseline,
                        now, surface=surface, best_of=best_of)
        b = _projection(right_key, left_key, market, histories, baseline,
                        now, surface=surface, best_of=best_of)
        def summary(item):
            if item is None:
                return None
            return {
                "estimate": round(float(item["estimate"]), 2),
                "samples": int(item["samples"]),
                "surface_samples": int(item["surface_samples"]),
                "format_samples": int(item["best_of_samples"]),
                "opponent_samples": int(item["opponent_allowance_samples"]),
                "predictive_sd": round(math.sqrt(max(
                    1.44, float(item["variance"]), float(item["estimate"]) * (
                        0.9 if market == "aces" else 1.1))), 2),
            }
        result[market] = {
            "player1": summary(a),
            "player2": summary(b),
            "total_estimate": round(float(a["estimate"] + b["estimate"]), 2)
                if a is not None and b is not None else None,
            "method": "canonical_recent_decay_shrunk_opponent_adjusted",
            "not_betting_odds": True,
            "cutoff_utc": cutoff.isoformat(),
            "data_quality": "available" if a is not None and b is not None else "partial",
        }
    return result
