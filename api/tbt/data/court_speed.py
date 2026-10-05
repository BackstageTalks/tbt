from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Iterable

from tbt.schemas import MatchRecord


COURT_SPEED_FEATURE_NAMES = [
    "court_speed_prior",
    "court_speed_current",
    "court_speed_delta_vs_venue_history",
    "player_perf_fast_courts",
    "player_perf_slow_courts",
    "court_speed_mismatch_player1",
    "court_speed_mismatch_player2",
    "court_speed_known",
]


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _match_speed_raw(match: MatchRecord) -> float | None:
    stats = match.stats or {}
    serve = [
        _num(stats.get("p1_service_points_won")),
        _num(stats.get("p2_service_points_won")),
    ]
    aces = [
        _num(stats.get("p1_ace_rate")),
        _num(stats.get("p2_ace_rate")),
    ]
    serve = [v for v in serve if v is not None]
    aces = [v for v in aces if v is not None]
    if not serve and not aces:
        return None
    serve_mean = sum(serve) / len(serve) if serve else 0.62
    ace_mean = sum(aces) / len(aces) if aces else 0.0
    # A transparent proxy rather than a copied third-party court-speed formula.
    # Both inputs are available only after a completed historical match.
    return serve_mean + 0.75 * ace_mean


@dataclass(frozen=True)
class _PlayerBuckets:
    fast_wins: float = 0.0
    fast_matches: int = 0
    slow_wins: float = 0.0
    slow_matches: int = 0


class CourtSpeedHistory:
    """Leakage-safe court-speed proxy built only from already completed matches.

    For every historical match, the feature snapshot is calculated before that
    match is ingested. Therefore the target match can never influence its own
    court-speed estimate or player fast/slow-court history.

    Index 100 is the point-in-time same-surface baseline. Current-event estimates
    require at least 3 earlier completed matches. Venue priors require at least 5
    completed matches from other editions/events at the same normalized venue.
    """

    def __init__(self, matches: Iterable[MatchRecord]) -> None:
        self._features: dict[str, dict[str, float]] = {}
        surface_sum = defaultdict(float)
        surface_n = defaultdict(int)
        venue_sum = defaultdict(float)
        venue_n = defaultdict(int)
        event_sum = defaultdict(float)
        event_n = defaultdict(int)
        player = defaultdict(lambda: {
            "fast_wins": 0.0, "fast_matches": 0,
            "slow_wins": 0.0, "slow_matches": 0,
        })

        ordered = sorted(
            [m for m in matches if m.is_completed],
            key=lambda m: (m.scheduled_at, str(m.match_id)),
        )

        for match in ordered:
            surface = _norm(match.surface or "unknown")
            tour = _norm(match.tour)
            venue = (tour, _norm(match.tournament), surface)
            event = (
                *venue,
                str(match.tournament_id or ""),
                int(match.scheduled_at.year),
            )

            baseline = (
                surface_sum[surface] / surface_n[surface]
                if surface_n[surface] >= 20 else None
            )
            event_s = event_sum[event]
            event_c = event_n[event]
            prior_s = venue_sum[venue] - event_s
            prior_c = venue_n[venue] - event_c

            prior_raw = prior_s / prior_c if prior_c >= 5 else None
            current_raw = event_s / event_c if event_c >= 3 else None

            def index(raw):
                if raw is None or baseline is None or baseline <= 0:
                    return None
                return 100.0 * raw / baseline

            prior_idx = index(prior_raw)
            current_idx = index(current_raw)
            effective = current_idx if current_idx is not None else prior_idx

            def wr(pid: str, bucket: str):
                row = player[str(pid)]
                n = row[f"{bucket}_matches"]
                return row[f"{bucket}_wins"] / n if n >= 5 else None

            p1_fast, p2_fast = wr(match.player1_id, "fast"), wr(match.player2_id, "fast")
            p1_slow, p2_slow = wr(match.player1_id, "slow"), wr(match.player2_id, "slow")
            fast_diff = (p1_fast - p2_fast) if p1_fast is not None and p2_fast is not None else 0.0
            slow_diff = (p1_slow - p2_slow) if p1_slow is not None and p2_slow is not None else 0.0

            def mismatch(fast, slow):
                if effective is None or fast is None or slow is None:
                    return 0.0
                preference = fast - slow
                direction = max(-1.0, min(1.0, (effective - 100.0) / 8.0))
                # 0 means profile and court direction align; larger values mean
                # the historical player profile conflicts with current speed.
                return abs(direction - max(-1.0, min(1.0, preference * 2.0))) / 2.0

            self._features[str(match.match_id)] = {
                "court_speed_prior": float(prior_idx or 0.0),
                "court_speed_current": float(current_idx or prior_idx or 0.0),
                "court_speed_delta_vs_venue_history": float(
                    (current_idx - prior_idx)
                    if current_idx is not None and prior_idx is not None else 0.0
                ),
                "player_perf_fast_courts": float(fast_diff),
                "player_perf_slow_courts": float(slow_diff),
                "court_speed_mismatch_player1": float(mismatch(p1_fast, p1_slow)),
                "court_speed_mismatch_player2": float(mismatch(p2_fast, p2_slow)),
                "court_speed_known": float(effective is not None),
            }

            raw = _match_speed_raw(match)
            if raw is None:
                continue

            # Ingest only after snapshot creation: this is the leakage barrier.
            surface_sum[surface] += raw
            surface_n[surface] += 1
            venue_sum[venue] += raw
            venue_n[venue] += 1
            event_sum[event] += raw
            event_n[event] += 1

            if effective is not None:
                bucket = "fast" if effective >= 103.0 else "slow" if effective <= 97.0 else None
                if bucket:
                    for pid in (match.player1_id, match.player2_id):
                        row = player[str(pid)]
                        row[f"{bucket}_matches"] += 1
                        if str(match.winner_id) == str(pid):
                            row[f"{bucket}_wins"] += 1.0

    def features_for_match(self, match: MatchRecord) -> dict[str, float]:
        return dict(
            self._features.get(
                str(match.match_id),
                {name: 0.0 for name in COURT_SPEED_FEATURE_NAMES},
            )
        )


def coverage_summary(rows: Iterable[dict[str, float]]) -> dict[str, float | int]:
    materialized = list(rows)
    n = len(materialized)
    known = sum(float(r.get("court_speed_known", 0.0)) for r in materialized)
    return {
        "rows": n,
        "known_rate": known / n if n else 0.0,
        "known_rows": int(known),
    }
