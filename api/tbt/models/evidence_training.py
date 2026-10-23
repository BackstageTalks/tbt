"""Research-only, efficient DIL point-in-time feature sidecar for frozen training.

Accepted inputs must already have independently reviewed DIL -> CDB match/player
crosswalk and source availability evidence. This never reads/writes CDB or
activates any existing training profile. Fails closed on identity mismatches.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, time, timezone
from typing import Iterable, Mapping

from .evidence_lab import (
    DIL_FEATURE_NAMES, HistoricalEvidence, _aware, _counts, pair_feature_projection,
    player_features,
)


class FrozenEvidenceIndex:
    """One-time O(N log N) sort and O(log N + bounded history) as-of lookups."""

    def __init__(self, records: Iterable[HistoricalEvidence]):
        groups = defaultdict(list)
        seen = set()
        for r in records:
            if not isinstance(r, HistoricalEvidence):
                raise ValueError("Unexpected DIL evidence record")
            if (r.tour.lower() not in {"atp", "wta"} or not r.player_id
                    or not r.canonical_match_id or r.reviewed_cdb_link is not True):
                raise ValueError("Independent CDB match/player link is mandatory")
            _aware(r.started_at)
            _aware(r.completed_at)
            _aware(r.available_at)
            _aware(r.expected_recorded_at)
            if (r.started_at > r.completed_at or r.available_at < r.completed_at
                    or r.expected_recorded_at >= r.started_at
                    or not isinstance(r.won, bool)):
                raise ValueError("Chronologically invalid pre-match evidence")
            # A match from the same-day outcome must not affect earlier fixtures.
            if not isinstance(r.expected_win, (float, int)) or isinstance(r.expected_win, bool):
                raise ValueError("Missing historical pre-match expectation")
            if not 0 <= r.expected_win <= 1:
                raise ValueError("Invalid opponent expectation")
            _counts(r)
            key = (r.tour.lower(), r.player_id, r.canonical_match_id)
            if key in seen:
                raise ValueError("Duplicate reviewed canonical player/match")
            seen.add(key)
            groups[(r.tour.lower(), r.player_id)].append(r)
        self._rows = {}
        self._times = {}
        for key, rows in groups.items():
            rows.sort(key=lambda row: (row.completed_at, row.canonical_match_id))
            self._rows[key] = rows
            self._times[key] = [row.completed_at.timestamp() for row in rows]
        self.total_evidence_rows = len(seen)

    def snapshot(self, *, tour: str, player_id: str, surface: str,
                 issued_at: datetime, limit: int = 20) -> dict:
        _aware(issued_at)
        if not player_id or tour.lower() not in {"atp", "wta"} or limit <= 0:
            raise ValueError("Invalid canonical player/time/window")
        key = (tour.lower(), player_id)
        cutoff = datetime.combine(issued_at.astimezone(timezone.utc).date(),
                                  time.min, tzinfo=timezone.utc).timestamp()
        rows = self._rows.get(key, [])
        pos = bisect_left(self._times.get(key, []), cutoff)
        eligible = []
        # Historical publication delay is respected independently of completion.
        for idx in range(pos - 1, -1, -1):
            record = rows[idx]
            if record.available_at <= issued_at:
                eligible.append(record)
                if len(eligible) == limit:
                    break
        return player_features(eligible, player_id=player_id, tour=tour,
                               surface=surface, issued_at=issued_at, limit=limit)


def augment_research_training_frame(frame, matches: Iterable, evidence: Iterable[HistoricalEvidence],
                                    *, require_stats_coverage: bool = True):
    """Pair DIL evidence with the *same* frozen canonical rows and target orientation.

    Returns (frame_copy_with_DIL_columns, diagnostics). Importing this function
    has no effect on the production profile, artifact feature schema or model.
    """
    from .feature_builder import FeatureBuilder
    import pandas as pd

    mandatory = {"match_id", "scheduled_at", "tour", "surface"}
    if not mandatory.issubset(frame.columns):
        raise ValueError("Frozen feature frame missing identity/date/surface metadata")
    if frame["match_id"].isna().any() or not frame["match_id"].is_unique:
        raise ValueError("Duplicate or empty frozen match IDs")
    index = FrozenEvidenceIndex(evidence)
    if not index.total_evidence_rows:
        raise ValueError("No independently verified DIL evidence")
    by_match = {}
    for match in matches:
        if match.match_id in by_match:
            raise ValueError("Duplicate canonical CDB match ID")
        by_match[match.match_id] = match
    if set(frame["match_id"]) != set(by_match):
        raise ValueError("Frozen frame does not match exact verified match cohort")

    values = []
    both_serve_return = 0
    both_full_stats = 0
    history_depth = 0
    for record in frame.itertuples(index=False):
        original = by_match[record.match_id]
        _aware(original.scheduled_at)
        if (record.tour != original.tour.lower() or
                pd.Timestamp(record.scheduled_at) != pd.Timestamp(original.scheduled_at) or
                record.surface != original.surface or not original.is_completed):
            raise ValueError("Frozen row mismatches canonical source or pre-match metadata")
        oriented, _ = FeatureBuilder.orient_for_training(original)
        # An immutable, verified actual issuance timestamp takes precedence
        # over the fixture start. Without it, this remains historical
        # pre-match research, not a replay of a published 06:00 selection.
        prediction_at = original.scheduled_at
        if "prediction_as_of" in frame.columns:
            value = pd.Timestamp(record.prediction_as_of)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Prediction as-of must be timezone-aware")
            prediction_at = value.to_pydatetime()
            if prediction_at > oriented.scheduled_at:
                raise ValueError("Prediction as-of is after the fixture start")
        l = index.snapshot(tour=oriented.tour, player_id=oriented.player1_id,
                           surface=oriented.surface, issued_at=prediction_at)
        r = index.snapshot(tour=oriented.tour, player_id=oriented.player2_id,
                           surface=oriented.surface, issued_at=prediction_at)
        pair = pair_feature_projection(l, r)
        values.append([pair[name] for name in DIL_FEATURE_NAMES])
        if (l["covered_matches"]["serve"] and l["covered_matches"]["return"]
                and r["covered_matches"]["serve"] and r["covered_matches"]["return"]):
            both_serve_return += 1
        if pair["dil_stats_known_both"] == 1:
            both_full_stats += 1
        if pair["dil_min_recent_count"] > 0:
            history_depth += 1

    if require_stats_coverage and not both_serve_return:
        raise ValueError("No paired PIT-qualified serve/return evidence on frozen training cohort")
    result = frame.copy()
    for col, cells in zip(DIL_FEATURE_NAMES, zip(*values)):
        if col in result.columns:
            raise ValueError("Frozen frame already contains DIL candidate feature: " + col)
        result[col] = list(cells)
    if len(result) != len(frame) or result["match_id"].tolist() != frame["match_id"].tolist():
        raise ValueError("Research feature augmentation disturbed row identity")
    return result, {
        "rows": len(result), "verified_dil_player_match_rows": index.total_evidence_rows,
        "rows_with_both_serve_return": both_serve_return,
        "rows_with_all_five_dil_rates": both_full_stats,
        "rows_with_two_prior_players": history_depth,
        "training_profile_changed": False, "cdb_v1_writes": 0,
    }
