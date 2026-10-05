from __future__ import annotations

import bisect
import math
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Iterable

ATP_RANK_HISTORY_FEATURE_NAMES = [
    "atp_hist_rank_advantage",
    "atp_hist_points_advantage",
    "atp_hist_rank_momentum_4w_diff",
    "atp_hist_rank_momentum_12w_diff",
    "atp_hist_points_momentum_4w_diff",
    "atp_hist_points_momentum_12w_diff",
    "atp_hist_career_best_distance_diff",
    "atp_hist_known_both",
    "atp_hist_momentum_4w_known_both",
    "atp_hist_momentum_12w_known_both",
]


def _norm_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _positive_int(value):
    if value in (None, "", "-"):
        return None
    match = re.match(r"^(\d+)", str(value).replace(",", "").strip())
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


class ATPRankHistory:
    """Leakage-safe weekly ATP ranking/points history.

    Historical features use only ranking snapshots with a source date strictly
    before the match date. Same-day ATP ranking releases are intentionally
    excluded because canonical history often has date-only timestamps.
    """

    def __init__(self, rows: Iterable[dict[str, object]]) -> None:
        by_player: dict[str, list[tuple]] = defaultdict(list)
        for raw in rows:
            name = _norm_name(raw.get("name"))
            if not name:
                continue
            rank = _positive_int(raw.get("rank"))
            if rank is None:
                continue
            source_date = raw.get("date")
            if source_date is None:
                continue
            by_player[name].append(
                (
                    source_date,
                    rank,
                    _positive_int(raw.get("points")),
                )
            )

        self._dates: dict[str, list] = {}
        self._ranks: dict[str, list[int]] = {}
        self._points: dict[str, list[int | None]] = {}
        self._career_best: dict[str, list[int]] = {}
        for name, values in by_player.items():
            values.sort(key=lambda item: item[0])
            dates = []
            ranks = []
            points = []
            bests = []
            best = None
            for source_date, rank, pts in values:
                dates.append(source_date)
                ranks.append(rank)
                points.append(pts)
                best = rank if best is None else min(best, rank)
                bests.append(best)
            self._dates[name] = dates
            self._ranks[name] = ranks
            self._points[name] = points
            self._career_best[name] = bests

    @classmethod
    def from_sqlite(cls, path: str | Path) -> "ATPRankHistory":
        conn = sqlite3.connect(str(path))
        rows = []
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            for (table,) in tables:
                try:
                    source_date = __import__("datetime").datetime.strptime(
                        str(table), "%Y-%m-%d"
                    ).date()
                except ValueError:
                    continue
                for rank, name, points in conn.execute(
                    f'SELECT rank,name,points FROM "{table}"'
                ):
                    rows.append(
                        {
                            "date": source_date,
                            "rank": rank,
                            "name": name,
                            "points": points,
                        }
                    )
        finally:
            conn.close()
        return cls(rows)

    def _snapshot(self, player_name: object, cutoff_date, *, max_age_days: int = 14):
        key = _norm_name(player_name)
        dates = self._dates.get(key)
        if not dates:
            return None
        idx = bisect.bisect_left(dates, cutoff_date) - 1
        if idx < 0:
            return None
        source_date = dates[idx]
        if (cutoff_date - source_date).days > max_age_days:
            return None
        return {
            "date": source_date,
            "rank": self._ranks[key][idx],
            "points": self._points[key][idx],
            "career_best_rank": self._career_best[key][idx],
        }

    def _snapshot_at_or_before(self, player_name: object, cutoff_date, *, max_age_days: int = 21):
        key = _norm_name(player_name)
        dates = self._dates.get(key)
        if not dates:
            return None
        idx = bisect.bisect_right(dates, cutoff_date) - 1
        if idx < 0:
            return None
        source_date = dates[idx]
        if (cutoff_date - source_date).days > max_age_days:
            return None
        return {
            "date": source_date,
            "rank": self._ranks[key][idx],
            "points": self._points[key][idx],
            "career_best_rank": self._career_best[key][idx],
        }

    @staticmethod
    def _rank_improvement(current, previous) -> float | None:
        if current is None or previous is None:
            return None
        return math.log1p(previous["rank"]) - math.log1p(current["rank"])

    @staticmethod
    def _points_improvement(current, previous) -> float | None:
        if (
            current is None
            or previous is None
            or current.get("points") is None
            or previous.get("points") is None
        ):
            return None
        return math.log1p(current["points"]) - math.log1p(previous["points"])

    def features_for_match(self, match) -> dict[str, float]:
        out = {name: 0.0 for name in ATP_RANK_HISTORY_FEATURE_NAMES}
        if str(getattr(match, "tour", "") or "").lower() != "atp":
            return out

        match_date = match.scheduled_at.date()
        p1 = self._snapshot(getattr(match, "player1_name", ""), match_date)
        p2 = self._snapshot(getattr(match, "player2_name", ""), match_date)
        if p1 is None or p2 is None:
            return out

        out["atp_hist_known_both"] = 1.0
        out["atp_hist_rank_advantage"] = (
            math.log1p(p2["rank"]) - math.log1p(p1["rank"])
        )
        if p1.get("points") is not None and p2.get("points") is not None:
            out["atp_hist_points_advantage"] = (
                math.log1p(p1["points"]) - math.log1p(p2["points"])
            )

        out["atp_hist_career_best_distance_diff"] = (
            math.log1p(max(p2["rank"] - p2["career_best_rank"], 0))
            - math.log1p(max(p1["rank"] - p1["career_best_rank"], 0))
        )

        for weeks in (4, 12):
            target = p1["date"] - timedelta(weeks=weeks)
            q1 = self._snapshot_at_or_before(
                getattr(match, "player1_name", ""), target
            )
            q2 = self._snapshot_at_or_before(
                getattr(match, "player2_name", ""), target
            )
            r1 = self._rank_improvement(p1, q1)
            r2 = self._rank_improvement(p2, q2)
            if r1 is not None and r2 is not None:
                out[f"atp_hist_rank_momentum_{weeks}w_diff"] = r1 - r2
                out[f"atp_hist_momentum_{weeks}w_known_both"] = 1.0
            pts1 = self._points_improvement(p1, q1)
            pts2 = self._points_improvement(p2, q2)
            if pts1 is not None and pts2 is not None:
                out[f"atp_hist_points_momentum_{weeks}w_diff"] = pts1 - pts2

        return out


def coverage_summary(rows: Iterable[dict[str, float]]) -> dict[str, float | int]:
    materialized = list(rows)
    count = len(materialized)
    if not count:
        return {
            "rows": 0,
            "known_both_rate": 0.0,
            "momentum_4w_known_both_rate": 0.0,
            "momentum_12w_known_both_rate": 0.0,
        }
    return {
        "rows": count,
        "known_both_rate": sum(
            float(row.get("atp_hist_known_both", 0.0)) for row in materialized
        ) / count,
        "momentum_4w_known_both_rate": sum(
            float(row.get("atp_hist_momentum_4w_known_both", 0.0))
            for row in materialized
        ) / count,
        "momentum_12w_known_both_rate": sum(
            float(row.get("atp_hist_momentum_12w_known_both", 0.0))
            for row in materialized
        ) / count,
    }
