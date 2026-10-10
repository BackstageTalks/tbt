"""Research-only, point-in-time WTA doubles ranking supplement.

Never writes canonical match history and is deliberately not wired to a
production doubles selector. Four explicit, stable provider-to-Sackmann IDs
are required: names, team IDs and approximate identifiers are NOT fallbacks.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

OFFICIAL_DOUBLES_SHA256 = "9d1b7e054b1d9d0d046109066082ba0edf5737c6d211ea7d7b27acec088dd42a"
SACKMANN_CUTOFF = date(2026, 6, 8)


@dataclass(frozen=True)
class _RankPoint:
    date: date
    rank: int
    points: int | None


def _integer(value: object, *, allow_zero: bool = False) -> int:
    text = str(value if value is not None else "").strip()
    if not text or not text.isascii() or not text.isdecimal():
        raise ValueError(f"Non-integral ranking field: {value!r}")
    val = int(text)
    if val < 0 or (not allow_zero and val == 0):
        raise ValueError(f"Invalid ranking field: {value!r}")
    return val


class WTADoublesRankHistory:
    """Pinned historical index keyed strictly by Sackmann player ID."""

    def __init__(self, by_id: dict[str, list[_RankPoint]]):
        self._dates: dict[str, list[date]] = {}
        self._entries: dict[str, list[_RankPoint]] = {}
        for player_id, rows in by_id.items():
            ordered = sorted(rows, key=lambda row: row.date)
            if len({row.date for row in ordered}) != len(ordered):
                raise ValueError("Unresolved duplicate doubles ranking snapshot")
            self._dates[player_id] = [row.date for row in ordered]
            self._entries[player_id] = ordered

    @classmethod
    def from_csv_gz(cls, source: str | Path, *, expected_sha256: str = OFFICIAL_DOUBLES_SHA256) -> "WTADoublesRankHistory":
        path = Path(source)
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != expected_sha256:
            raise ValueError("WTA doubles source checksum mismatch")
        seen: dict[tuple[str, date], _RankPoint] = {}
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"ranking_date", "ranking_type", "sackmann_player_id", "rank", "points"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("WTA doubles source missing required columns")
            for line, row in enumerate(reader, start=2):
                if str(row.get("ranking_type") or "").lower().strip() != "doubles":
                    raise ValueError(f"Non-doubles ranking observation on line {line}")
                try:
                    ranked_at = date.fromisoformat(str(row["ranking_date"]))
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Invalid ranking date on line {line}") from exc
                if ranked_at <= SACKMANN_CUTOFF:
                    raise ValueError("Supplement may not replace historical Sackmann ranking")
                player_id = str(row.get("sackmann_player_id") or "").strip()
                if not player_id or not player_id.isascii() or not player_id.isdecimal():
                    raise ValueError(f"Missing stable player ID on line {line}")
                rank = _integer(row.get("rank"))
                points = None if row.get("points") in (None, "") else _integer(row["points"], allow_zero=True)
                entry = _RankPoint(ranked_at, rank, points)
                key = (player_id, ranked_at)
                if key in seen and seen[key] != entry:
                    raise ValueError("Conflicting doubles ranking snapshot")
                seen[key] = entry
        if not seen:
            raise ValueError("Empty WTA doubles source")
        by_id: dict[str, list[_RankPoint]] = {}
        for (pid, _), entry in seen.items():
            by_id.setdefault(pid, []).append(entry)
        return cls(by_id)

    def latest_prior(self, sackmann_id: str, kickoff: datetime) -> _RankPoint | None:
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise ValueError("Kickoff must include timezone")
        match_day = kickoff.astimezone(timezone.utc).date()
        dates = self._dates.get(str(sackmann_id))
        if not dates:
            return None
        idx = bisect.bisect_left(dates, match_day) - 1
        return self._entries[str(sackmann_id)][idx] if idx >= 0 else None

    def research_features(
        self,
        side1_ids: Sequence[str],
        side2_ids: Sequence[str],
        kickoff: datetime,
        *,
        canonical_to_sackmann: Mapping[str, str],
    ) -> dict[str, float | int | None]:
        """No partial/imputed team average, fuzzy name or team ID fallback."""
        unavailable: dict[str, float | int | None] = {
            "wta_doubles_rank_known_four": 0,
            "wta_doubles_rank_advantage": None,
            "wta_doubles_points_advantage": None,
        }
        if len(side1_ids) != 2 or len(side2_ids) != 2:
            return unavailable
        ids = [str(v) for v in (*side1_ids, *side2_ids)]
        if any(not v.strip() for v in ids) or len(set(ids)) != 4:
            return unavailable
        mapped = [str(canonical_to_sackmann.get(v) or "").strip() for v in ids]
        if any(not v for v in mapped) or len(set(mapped)) != 4:
            return unavailable
        rows = [self.latest_prior(pid, kickoff) for pid in mapped]
        if any(row is None for row in rows):
            return unavailable
        complete = [row for row in rows if row is not None]
        return {
            "wta_doubles_rank_known_four": 1,
            "wta_doubles_rank_advantage": (
                complete[2].rank + complete[3].rank - complete[0].rank - complete[1].rank
            ) / 2,
            "wta_doubles_points_advantage": (
                (complete[0].points + complete[1].points - complete[2].points - complete[3].points) / 2
                if all(row.points is not None for row in complete) else None
            ),
        }
