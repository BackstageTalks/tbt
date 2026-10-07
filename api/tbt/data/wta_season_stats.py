from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable

WTA_METRICS = {
    "first_serve_pct": "first_serve_percent",
    "first_serve_points_won_pct": "first_serve_won_percent",
    "second_serve_points_won_pct": "second_serve_won_percent",
    "service_points_won_pct": "service_points_won_percent",
    "service_games_won_pct": "service_games_won_percent",
    "break_points_saved_pct": "breakpoint_saved_percent",
    "first_serve_return_points_won_pct": "first_return_percent",
    "second_serve_return_points_won_pct": "second_return_percent",
    "return_games_won_pct": "return_games_won_percent",
    "break_points_converted_pct": "breakpoint_converted_percent",
    "return_points_won_pct": "return_points_won_percent",
    "total_points_won_pct": "total_points_won_percent",
    "aces_per_match": "__aces_per_match__",
    "double_faults_per_match": "__double_faults_per_match__",
}

WTA_SEASON_FEATURE_NAMES = (
    [f"wta_{name}_diff" for name in WTA_METRICS]
    + ["wta_season_stats_known_both"]
)


def _norm_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def _initial_surname_key(value: object) -> str:
    parts = _norm_name(value).split()
    if len(parts) < 2:
        return ""
    return f"{parts[0][0]} {parts[-1]}"


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class WTASeasonPriors:
    """Leakage-safe WTA season serve/return priors.

    Historical and upcoming matches both use only the previous completed
    calendar season. Same-season aggregate rows are deliberately never used,
    because they contain information from matches occurring later in that year.
    Identity linkage is fail-closed on unique normalized names.
    """

    def __init__(self, rows: Iterable[dict[str, object]]) -> None:
        materialized: list[tuple[int, str, str, dict[str, object]]] = []
        full_ids: dict[str, set[str]] = defaultdict(set)
        initial_ids: dict[str, set[str]] = defaultdict(set)

        for raw in rows:
            row = dict(raw)
            try:
                season = int(row.get("season") or row.get("tourn_year") or 0)
            except (TypeError, ValueError):
                continue
            player_id = str(row.get("PlayerNbr") or "").strip()
            full_name = f"{row.get('First_Name') or ''} {row.get('Last_Name') or ''}".strip()
            full_key = _norm_name(full_name)
            initial_key = _initial_surname_key(full_name)
            if season <= 0 or not player_id or not full_key:
                continue
            materialized.append((season, player_id, full_key, row))
            full_ids[full_key].add(player_id)
            if initial_key:
                initial_ids[initial_key].add(player_id)

        full_unique = {key for key, ids in full_ids.items() if len(ids) == 1}
        initial_unique = {key for key, ids in initial_ids.items() if len(ids) == 1}
        self._player_key_by_full: dict[str, str] = {}
        self._player_key_by_initial: dict[str, str] = {}
        self._by_key: dict[tuple[int, str], dict[str, object]] = {}

        for season, player_id, full_key, row in materialized:
            canonical = f"id:{player_id}"
            if full_key in full_unique:
                self._player_key_by_full[full_key] = canonical
            initial_key = _initial_surname_key(
                f"{row.get('First_Name') or ''} {row.get('Last_Name') or ''}"
            )
            if initial_key and initial_key in initial_unique:
                self._player_key_by_initial[initial_key] = canonical
            self._by_key[(season, canonical)] = row


    def export_state(self) -> dict:
        return {
            "schema": 1,
            "full": dict(self._player_key_by_full),
            "initial": dict(self._player_key_by_initial),
            "rows": [
                {"season": season, "player_key": player_key, "row": row}
                for (season, player_key), row in sorted(self._by_key.items())
            ],
        }

    @classmethod
    def from_state(cls, payload: dict | None) -> "WTASeasonPriors":
        obj = cls([])
        if not isinstance(payload, dict) or int(payload.get("schema") or 0) != 1:
            return obj
        obj._player_key_by_full = {
            str(k): str(v) for k, v in (payload.get("full") or {}).items()
        }
        obj._player_key_by_initial = {
            str(k): str(v) for k, v in (payload.get("initial") or {}).items()
        }
        obj._by_key = {}
        for item in payload.get("rows") or []:
            if not isinstance(item, dict) or not isinstance(item.get("row"), dict):
                continue
            try:
                season = int(item.get("season"))
            except (TypeError, ValueError):
                continue
            player_key = str(item.get("player_key") or "")
            if player_key:
                obj._by_key[(season, player_key)] = dict(item["row"])
        return obj

    @classmethod
    def from_csv(cls, path: str | Path) -> "WTASeasonPriors":
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            return cls(csv.DictReader(handle))

    def _player_key(self, name: object) -> str | None:
        full = _norm_name(name)
        if full in self._player_key_by_full:
            return self._player_key_by_full[full]
        short = _initial_surname_key(name)
        if short in self._player_key_by_initial:
            return self._player_key_by_initial[short]
        return None

    def player_snapshot(self, player_name: object, *, season: int) -> dict[str, float | None]:
        key = self._player_key(player_name)
        row = self._by_key.get((season, key)) if key is not None else None
        out: dict[str, float | None] = {}
        for metric, field in WTA_METRICS.items():
            if row is None:
                out[metric] = None
            elif field == "__aces_per_match__":
                count = _number(row.get("MatchCount"))
                aces = _number(row.get("Aces"))
                out[metric] = (aces / count) if aces is not None and count and count > 0 else None
            elif field == "__double_faults_per_match__":
                count = _number(row.get("MatchCount"))
                dfs = _number(row.get("Double_Faults"))
                out[metric] = (dfs / count) if dfs is not None and count and count > 0 else None
            else:
                out[metric] = _number(row.get(field))
        return out

    def features_for_match(self, match, *, current: bool = False) -> dict[str, float]:
        neutral = {name: 0.0 for name in WTA_SEASON_FEATURE_NAMES}
        if str(getattr(match, "tour", "") or "").lower() != "wta":
            return neutral
        season = int(match.scheduled_at.year) - 1
        p1 = self.player_snapshot(getattr(match, "player1_name", ""), season=season)
        p2 = self.player_snapshot(getattr(match, "player2_name", ""), season=season)
        known = True
        for metric in WTA_METRICS:
            left = p1.get(metric)
            right = p2.get(metric)
            if left is None or right is None:
                known = False
                continue
            neutral[f"wta_{metric}_diff"] = float(left) - float(right)
        neutral["wta_season_stats_known_both"] = float(known)
        return neutral


def coverage_summary(rows: Iterable[dict[str, float]]) -> dict[str, float | int]:
    materialized = list(rows)
    count = len(materialized)
    return {
        "rows": count,
        "known_both_rate": (
            sum(float(row.get("wta_season_stats_known_both", 0.0)) for row in materialized)
            / count
            if count
            else 0.0
        ),
    }
