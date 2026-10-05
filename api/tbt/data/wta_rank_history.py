from __future__ import annotations

import bisect
import csv
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

WTA_RANK_HISTORY_FEATURE_NAMES = [
    "wta_hist_rank_advantage",
    "wta_hist_points_advantage",
    "wta_hist_rank_momentum_4w_diff",
    "wta_hist_rank_momentum_12w_diff",
    "wta_hist_points_momentum_4w_diff",
    "wta_hist_points_momentum_12w_diff",
    "wta_hist_career_best_distance_diff",
    "wta_hist_known_both",
    "wta_hist_momentum_4w_known_both",
    "wta_hist_momentum_12w_known_both",
]


def _norm_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _positive_int(value):
    if value in (None, "", "-"):
        return None
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class WTARankHistory:
    """Leakage-safe WTA weekly rankings built from Sackmann player IDs.

    Rankings are joined to the Sackmann player master first, then matched to
    canonical BlinQ names. Only source dates strictly before the match date are
    eligible so same-day publication timing can never leak.
    """

    def __init__(self, rows: Iterable[dict[str, object]]) -> None:
        by_player: dict[str, list[tuple]] = defaultdict(list)
        for raw in rows:
            name = _norm_name(raw.get("name"))
            rank = _positive_int(raw.get("rank"))
            source_date = raw.get("date")
            if not name or rank is None or source_date is None:
                continue
            by_player[name].append(
                (source_date, rank, _positive_int(raw.get("points")))
            )

        self._dates = {}
        self._ranks = {}
        self._points = {}
        self._career_best = {}
        for name, values in by_player.items():
            values.sort(key=lambda item: item[0])
            dates, ranks, points, bests = [], [], [], []
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
    def from_sackmann(cls, players_csv: str | Path, ranking_csvs: Iterable[str | Path]):
        player_names: dict[int, str] = {}
        with Path(players_csv).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pid = _positive_int(row.get("player_id"))
                if pid is None:
                    continue
                first = str(row.get("name_first") or row.get("first_name") or "").strip()
                last = str(row.get("name_last") or row.get("last_name") or "").strip()
                name = " ".join(part for part in (first, last) if part).strip()
                if name:
                    player_names[pid] = name

        rows = []
        for path in ranking_csvs:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    pid = _positive_int(row.get("player") or row.get("player_id"))
                    if pid is None or pid not in player_names:
                        continue
                    raw_date = str(row.get("ranking_date") or row.get("date") or "").strip()
                    try:
                        source_date = datetime.strptime(raw_date, "%Y%m%d").date()
                    except ValueError:
                        try:
                            source_date = datetime.fromisoformat(raw_date).date()
                        except ValueError:
                            continue
                    rows.append({
                        "date": source_date,
                        "rank": row.get("ranking") or row.get("rank"),
                        "points": row.get("ranking_points") or row.get("points"),
                        "name": player_names[pid],
                    })
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
    def _rank_improvement(current, previous):
        if current is None or previous is None:
            return None
        return math.log1p(previous["rank"]) - math.log1p(current["rank"])

    @staticmethod
    def _points_improvement(current, previous):
        if (
            current is None or previous is None
            or current.get("points") is None or previous.get("points") is None
        ):
            return None
        return math.log1p(current["points"]) - math.log1p(previous["points"])

    def features_for_match(self, match) -> dict[str, float]:
        out = {name: 0.0 for name in WTA_RANK_HISTORY_FEATURE_NAMES}
        if str(getattr(match, "tour", "") or "").lower() != "wta":
            return out

        match_date = match.scheduled_at.date()
        p1 = self._snapshot(getattr(match, "player1_name", ""), match_date)
        p2 = self._snapshot(getattr(match, "player2_name", ""), match_date)
        if p1 is None or p2 is None:
            return out

        out["wta_hist_known_both"] = 1.0
        out["wta_hist_rank_advantage"] = math.log1p(p2["rank"]) - math.log1p(p1["rank"])
        if p1.get("points") is not None and p2.get("points") is not None:
            out["wta_hist_points_advantage"] = (
                math.log1p(p1["points"]) - math.log1p(p2["points"])
            )

        out["wta_hist_career_best_distance_diff"] = (
            math.log1p(max(p2["rank"] - p2["career_best_rank"], 0))
            - math.log1p(max(p1["rank"] - p1["career_best_rank"], 0))
        )

        for weeks in (4, 12):
            target = p1["date"] - timedelta(weeks=weeks)
            q1 = self._snapshot_at_or_before(getattr(match, "player1_name", ""), target)
            q2 = self._snapshot_at_or_before(getattr(match, "player2_name", ""), target)
            r1, r2 = self._rank_improvement(p1, q1), self._rank_improvement(p2, q2)
            if r1 is not None and r2 is not None:
                out[f"wta_hist_rank_momentum_{weeks}w_diff"] = r1 - r2
                out[f"wta_hist_momentum_{weeks}w_known_both"] = 1.0
            pts1, pts2 = self._points_improvement(p1, q1), self._points_improvement(p2, q2)
            if pts1 is not None and pts2 is not None:
                out[f"wta_hist_points_momentum_{weeks}w_diff"] = pts1 - pts2
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
        "known_both_rate": sum(float(r.get("wta_hist_known_both", 0.0)) for r in materialized) / count,
        "momentum_4w_known_both_rate": sum(float(r.get("wta_hist_momentum_4w_known_both", 0.0)) for r in materialized) / count,
        "momentum_12w_known_both_rate": sum(float(r.get("wta_hist_momentum_12w_known_both", 0.0)) for r in materialized) / count,
    }
