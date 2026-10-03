from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ATP_LEADERBOARD_FEATURE_NAMES = [
    "atp_serve_rating_diff",
    "atp_return_rating_diff",
    "atp_pressure_rating_diff",
    "atp_surface_serve_rating_diff",
    "atp_surface_return_rating_diff",
    "atp_surface_pressure_rating_diff",
    "atp_leaderboard_known_both",
    "atp_surface_leaderboard_known_both",
]

_BOARD_RATING_FIELD = {
    "serve": "Stats.ServeRatingSortField",
    "return": "Stats.ReturnRatingSortField",
    "pressure": "Stats.PressureRatingSortField",
}


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
    text = str(value).strip().rstrip("%")
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _surface_key(value: object) -> str:
    text = str(value or "unknown").strip().lower()
    if text == "indoor_hard":
        return "hard"
    return text if text in {"all", "hard", "clay", "grass"} else "all"


class ATPLeaderboardPriors:
    """Leakage-safe lookup over official ATP Serve/Return/Pressure leaderboards.

    Historical matches only use the *previous completed season*.
    Upcoming/current matches use the rolling 52-week snapshot.

    ATP Tour player IDs are not the same identity domain as the canonical
    provider IDs used by BlinQ, so lookup is fail-closed on unique normalized
    player names (with a unique first-initial + surname fallback).
    """

    def __init__(self, rows: Iterable[dict[str, object]]) -> None:
        self._by_key: dict[tuple[str, str, str, str], dict[str, object]] = {}
        full_ids: dict[str, set[str]] = defaultdict(set)
        initial_ids: dict[str, set[str]] = defaultdict(set)

        materialized = []
        for raw in rows:
            row = dict(raw)
            period = str(row.get("period") or "").strip().lower()
            surface = _surface_key(row.get("surface"))
            board = str(row.get("board") or "").strip().lower()
            player_id = str(row.get("PlayerId") or "").strip()
            player_name = str(row.get("PlayerName") or "").strip()
            name_key = _norm_name(player_name)
            initial_key = _initial_surname_key(player_name)
            if not period or not player_id or not name_key or board not in _BOARD_RATING_FIELD:
                continue
            materialized.append((period, surface, board, player_id, name_key, initial_key, row))
            full_ids[name_key].add(player_id)
            if initial_key:
                initial_ids[initial_key].add(player_id)

        self._full_unique = {key for key, ids in full_ids.items() if len(ids) == 1}
        self._initial_unique = {key for key, ids in initial_ids.items() if len(ids) == 1}
        self._player_key_by_full: dict[str, str] = {}
        self._player_key_by_initial: dict[str, str] = {}

        for period, surface, board, player_id, name_key, initial_key, row in materialized:
            canonical = f"id:{player_id}"
            if name_key in self._full_unique:
                self._player_key_by_full[name_key] = canonical
            if initial_key and initial_key in self._initial_unique:
                self._player_key_by_initial[initial_key] = canonical
            self._by_key[(period, surface, board, canonical)] = row

    @classmethod
    def from_csv(cls, path: str | Path) -> "ATPLeaderboardPriors":
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

    @staticmethod
    def _period_for_match(match, *, current: bool) -> str:
        if current:
            return "52week"
        return str(int(match.scheduled_at.year) - 1)

    def _rating(
        self,
        *,
        period: str,
        surface: str,
        board: str,
        player_name: object,
    ) -> float | None:
        player_key = self._player_key(player_name)
        if player_key is None:
            return None
        row = self._by_key.get((period, surface, board, player_key))
        if row is None:
            return None
        return _number(row.get(_BOARD_RATING_FIELD[board]))

    def player_snapshot(
        self,
        player_name: object,
        *,
        period: str,
        surface: str,
    ) -> dict[str, float | None]:
        surface = _surface_key(surface)
        out: dict[str, float | None] = {}
        for board in ("serve", "return", "pressure"):
            out[f"{board}_all"] = self._rating(
                period=period, surface="all", board=board, player_name=player_name
            )
            out[f"{board}_surface"] = (
                self._rating(
                    period=period, surface=surface, board=board, player_name=player_name
                )
                if surface != "all"
                else out[f"{board}_all"]
            )
        return out

    def features_for_match(self, match, *, current: bool = False) -> dict[str, float]:
        neutral = {name: 0.0 for name in ATP_LEADERBOARD_FEATURE_NAMES}
        if str(getattr(match, "tour", "") or "").lower() != "atp":
            return neutral

        period = self._period_for_match(match, current=current)
        surface = _surface_key(getattr(match, "surface", "all"))
        p1 = self.player_snapshot(
            getattr(match, "player1_name", ""), period=period, surface=surface
        )
        p2 = self.player_snapshot(
            getattr(match, "player2_name", ""), period=period, surface=surface
        )

        all_known = all(
            p1.get(f"{board}_all") is not None and p2.get(f"{board}_all") is not None
            for board in ("serve", "return", "pressure")
        )
        surface_known = all(
            p1.get(f"{board}_surface") is not None
            and p2.get(f"{board}_surface") is not None
            for board in ("serve", "return", "pressure")
        )

        for board in ("serve", "return", "pressure"):
            left = p1.get(f"{board}_all")
            right = p2.get(f"{board}_all")
            if left is not None and right is not None:
                neutral[f"atp_{board}_rating_diff"] = float(left) - float(right)

            left_surface = p1.get(f"{board}_surface")
            right_surface = p2.get(f"{board}_surface")
            if left_surface is not None and right_surface is not None:
                neutral[f"atp_surface_{board}_rating_diff"] = (
                    float(left_surface) - float(right_surface)
                )

        neutral["atp_leaderboard_known_both"] = float(all_known)
        neutral["atp_surface_leaderboard_known_both"] = float(surface_known)
        return neutral


def coverage_summary(rows: Iterable[dict[str, float]]) -> dict[str, float | int]:
    materialized = list(rows)
    count = len(materialized)
    if count == 0:
        return {
            "rows": 0,
            "known_both_rate": 0.0,
            "surface_known_both_rate": 0.0,
        }
    return {
        "rows": count,
        "known_both_rate": sum(
            float(row.get("atp_leaderboard_known_both", 0.0)) for row in materialized
        ) / count,
        "surface_known_both_rate": sum(
            float(row.get("atp_surface_leaderboard_known_both", 0.0))
            for row in materialized
        ) / count,
    }
