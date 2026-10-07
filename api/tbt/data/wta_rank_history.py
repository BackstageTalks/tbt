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

from .player_identity import load_crosswalk

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

    def __init__(
        self,
        rows: Iterable[dict[str, object]],
        *,
        canonical_to_sackmann: dict[str, str] | None = None,
    ) -> None:
        self._canonical_to_sackmann = {
            str(key): str(value)
            for key, value in (canonical_to_sackmann or {}).items()
            if str(key).strip() and str(value).strip()
        }
        by_player: dict[str, list[tuple]] = defaultdict(list)
        for raw in rows:
            name = _norm_name(raw.get("name"))
            sackmann_id = str(raw.get("sackmann_player_id") or "").strip()
            rank = _positive_int(raw.get("rank"))
            source_date = raw.get("date")
            if rank is None or source_date is None:
                continue
            keys = []
            if sackmann_id:
                keys.append(f"id:{sackmann_id}")
            if name:
                keys.append(f"name:{name}")
            if not keys:
                continue
            for key in keys:
                by_player[key].append(
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
    def from_sackmann(
        cls,
        players_csv: str | Path,
        ranking_csvs: Iterable[str | Path],
        *,
        crosswalk_path: str | Path | None = None,
        canonical_to_sackmann: dict[str, str] | None = None,
        supplement_csvs: Iterable[str | Path] = (),
    ):
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

        def parsed_rows(path):
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    pid = _positive_int(raw.get("player") or raw.get("player_id"))
                    if pid is None or pid not in player_names:
                        continue
                    raw_date = str(
                        raw.get("ranking_date") or raw.get("date") or ""
                    ).strip()
                    try:
                        source_date = datetime.strptime(raw_date, "%Y%m%d").date()
                    except ValueError:
                        try:
                            source_date = datetime.fromisoformat(raw_date).date()
                        except ValueError:
                            continue
                    rank = _positive_int(raw.get("ranking") or raw.get("rank"))
                    if rank is None:
                        continue
                    yield {
                        "date": source_date,
                        "rank": rank,
                        "points": _positive_int(
                            raw.get("ranking_points") or raw.get("points")
                        ),
                        "name": player_names[pid],
                        "sackmann_player_id": str(pid),
                    }

        # Sackmann's pinned mirror ships immutable decade files plus a
        # wta_rankings_current.csv convenience snapshot. The current file
        # intentionally overlaps older dates and can contain retrospective
        # corrections. Historical training must never let that convenience
        # file rewrite an already-pinned decade snapshot.
        paths = [Path(path) for path in ranking_csvs]
        historical_paths = [
            path for path in paths
            if path.name.casefold() != "wta_rankings_current.csv"
        ]
        current_paths = [
            path for path in paths
            if path.name.casefold() == "wta_rankings_current.csv"
        ]

        rows = []
        base_by_key = {}
        ambiguous_historical_keys = set()
        base_max_date = None

        def add_pinned(row, *, source_kind):
            nonlocal base_max_date
            sid = str(row.get("sackmann_player_id") or "").strip()
            source_date = row.get("date")
            if not sid or source_date is None:
                return
            key = (sid, source_date)
            signature = (
                _positive_int(row.get("rank")),
                _positive_int(row.get("points")),
            )
            if key in ambiguous_historical_keys:
                return
            previous = base_by_key.get(key)
            if previous is not None:
                if previous != signature:
                    if source_kind == "historical":
                        # Same pinned source/date/player can contain mutually
                        # inconsistent duplicate evidence. Do not guess which
                        # revision is correct: quarantine the key entirely.
                        ambiguous_historical_keys.add(key)
                        base_by_key.pop(key, None)
                        logger.warning(
                            "Quarantining conflicting pinned WTA historical rank "
                            "row for %s on %s: previous=%s incoming=%s",
                            sid, source_date, previous, signature,
                        )
                        return
                    raise ValueError(
                        f"Conflicting pinned WTA {source_kind} rank row for "
                        f"{sid} on {source_date}: previous={previous}, incoming={signature}"
                    )
                return
            base_by_key[key] = signature
            rows.append(row)
            if base_max_date is None or source_date > base_max_date:
                base_max_date = source_date

        # Non-current decade files are authoritative for their historical range.
        for path in historical_paths:
            for row in parsed_rows(path):
                add_pinned(row, source_kind="historical")

        # Remove every ambiguous pinned key, including the first row that was
        # appended before its conflicting duplicate was observed. This is a
        # fail-closed quarantine: ambiguous rank evidence becomes unavailable.
        if ambiguous_historical_keys:
            rows = [
                row for row in rows
                if (
                    str(row.get("sackmann_player_id") or "").strip(),
                    row.get("date"),
                ) not in ambiguous_historical_keys
            ]
            base_max_date = max(
                (row.get("date") for row in rows if row.get("date") is not None),
                default=None,
            )

        # If current is the only supplied source, it remains a valid pinned
        # archive. Otherwise it is extension-only: rows at/before the immutable
        # historical maximum are ignored rather than allowed to rewrite history.
        historical_max_date = base_max_date
        current_seen = {}
        for path in current_paths:
            for row in parsed_rows(path):
                source_date = row["date"]
                if historical_max_date is not None and source_date <= historical_max_date:
                    continue
                key = (row["sackmann_player_id"], source_date)
                signature = (row["rank"], row["points"])
                previous = current_seen.get(key)
                if previous is not None:
                    if previous != signature:
                        raise ValueError(
                            f"Conflicting pinned WTA current rank row for "
                            f"{key[0]} on {source_date}"
                        )
                    continue
                current_seen[key] = signature
                add_pinned(row, source_kind="current")

        if not historical_paths and not current_paths:
            raise ValueError("No WTA ranking CSVs supplied")

        # Supplemental official WTA rankings may only extend the pinned
        # Sackmann source. They may never overlap/overwrite a pinned weekly
        # snapshot silently: an overlap is either an exact duplicate (ignored)
        # or a hard conflict (refused). This keeps source precedence explicit.

        supplement_seen = {}
        supplement_rows = []
        for path in supplement_csvs:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    ranking_type = str(raw.get("ranking_type") or "singles").strip().lower()
                    if ranking_type != "singles":
                        continue
                    sid = str(raw.get("sackmann_player_id") or "").strip()
                    if not sid:
                        continue
                    raw_date = str(
                        raw.get("ranking_date") or raw.get("date") or ""
                    ).strip()
                    try:
                        source_date = datetime.fromisoformat(raw_date).date()
                    except ValueError:
                        continue
                    rank = _positive_int(raw.get("rank") or raw.get("ranking"))
                    points = _positive_int(raw.get("points") or raw.get("ranking_points"))
                    if rank is None:
                        continue
                    signature = (rank, points)
                    key = (sid, source_date)

                    pinned = base_by_key.get(key)
                    if pinned is not None:
                        if pinned != signature:
                            raise ValueError(
                                f"WTA ranking supplement conflicts with pinned source for "
                                f"{sid} on {source_date}"
                            )
                        continue
                    if base_max_date is not None and source_date <= base_max_date:
                        raise ValueError(
                            "WTA ranking supplement must be strictly later than the "
                            f"pinned source max date {base_max_date}; got {source_date}"
                        )
                    previous = supplement_seen.get(key)
                    if previous is not None:
                        if previous != signature:
                            raise ValueError(
                                f"Conflicting WTA ranking supplement row for "
                                f"{sid} on {source_date}"
                            )
                        continue
                    supplement_seen[key] = signature
                    supplement_rows.append({
                        "date": source_date,
                        "rank": rank,
                        "points": points,
                        "name": str(raw.get("player_name") or "").strip(),
                        "sackmann_player_id": sid,
                    })
        rows.extend(supplement_rows)

        mapping = dict(canonical_to_sackmann or {})
        if crosswalk_path:
            mapping.update(load_crosswalk(crosswalk_path))
        return cls(rows, canonical_to_sackmann=mapping)

    def _lookup_key(self, player_id: object, player_name: object) -> str:
        canonical_id = str(player_id or "").strip()
        sackmann_id = self._canonical_to_sackmann.get(canonical_id)
        if sackmann_id:
            return f"id:{sackmann_id}"
        return f"name:{_norm_name(player_name)}"

    def _snapshot(
        self,
        player_name: object,
        cutoff_date,
        *,
        player_id: object = None,
        max_age_days: int = 14,
    ):
        key = self._lookup_key(player_id, player_name)
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

    def _snapshot_at_or_before(
        self,
        player_name: object,
        cutoff_date,
        *,
        player_id: object = None,
        max_age_days: int = 21,
    ):
        key = self._lookup_key(player_id, player_name)
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
        p1 = self._snapshot(
            getattr(match, "player1_name", ""),
            match_date,
            player_id=getattr(match, "player1_id", None),
        )
        p2 = self._snapshot(
            getattr(match, "player2_name", ""),
            match_date,
            player_id=getattr(match, "player2_id", None),
        )
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
            q1 = self._snapshot_at_or_before(
                getattr(match, "player1_name", ""),
                target,
                player_id=getattr(match, "player1_id", None),
            )
            q2 = self._snapshot_at_or_before(
                getattr(match, "player2_name", ""),
                target,
                player_id=getattr(match, "player2_id", None),
            )
            r1, r2 = self._rank_improvement(p1, q1), self._rank_improvement(p2, q2)
            if r1 is not None and r2 is not None:
                out[f"wta_hist_rank_momentum_{weeks}w_diff"] = r1 - r2
                out[f"wta_hist_momentum_{weeks}w_known_both"] = 1.0
            pts1, pts2 = self._points_improvement(p1, q1), self._points_improvement(p2, q2)
            if pts1 is not None and pts2 is not None:
                out[f"wta_hist_points_momentum_{weeks}w_diff"] = pts1 - pts2
        return out


    def export_state(self, players, *, as_of_date, lookback_days: int = 140) -> dict:
        """Export the recent point-in-time state required by comparator serving."""
        start = as_of_date - timedelta(days=max(120, int(lookback_days)))
        requested = []
        canonical_map = {}
        for row in players:
            if not isinstance(row, dict) or str(row.get("tour") or "").lower() != "wta":
                continue
            player_id = str(row.get("player_id") or "").strip()
            name_key = f"name:{_norm_name(row.get('name'))}"
            sackmann_id = self._canonical_to_sackmann.get(player_id)
            if sackmann_id:
                canonical_map[player_id] = sackmann_id
                requested.append(f"id:{sackmann_id}")
            requested.append(name_key)

        histories = {}
        for key in sorted(set(key for key in requested if key and not key.endswith(":"))):
            dates = self._dates.get(key) or []
            rows = []
            for idx, source_date in enumerate(dates):
                if source_date < start or source_date > as_of_date:
                    continue
                rows.append([
                    source_date.isoformat(),
                    int(self._ranks[key][idx]),
                    self._points[key][idx],
                    int(self._career_best[key][idx]),
                ])
            if rows:
                histories[key] = rows
        return {
            "schema": 1,
            "as_of_date": as_of_date.isoformat(),
            "lookback_days": max(120, int(lookback_days)),
            "canonical_to_sackmann": canonical_map,
            "players": histories,
        }

    @classmethod
    def from_state(cls, state: dict) -> "WTARankHistory":
        if not isinstance(state, dict) or int(state.get("schema") or 0) != 1:
            raise ValueError("Invalid WTA rank-history state")
        obj = cls.__new__(cls)
        obj._canonical_to_sackmann = {
            str(key): str(value)
            for key, value in (state.get("canonical_to_sackmann") or {}).items()
            if str(key).strip() and str(value).strip()
        }
        obj._dates, obj._ranks, obj._points, obj._career_best = {}, {}, {}, {}
        for key, rows in (state.get("players") or {}).items():
            if not isinstance(rows, list):
                raise ValueError("Invalid WTA rank-history player state")
            dates, ranks, points, bests = [], [], [], []
            for row in rows:
                if not isinstance(row, list) or len(row) != 4:
                    raise ValueError("Invalid WTA rank-history snapshot")
                dates.append(datetime.fromisoformat(str(row[0])).date())
                ranks.append(int(row[1]))
                points.append(None if row[2] is None else int(row[2]))
                bests.append(int(row[3]))
            obj._dates[str(key)] = dates
            obj._ranks[str(key)] = ranks
            obj._points[str(key)] = points
            obj._career_best[str(key)] = bests
        return obj


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
