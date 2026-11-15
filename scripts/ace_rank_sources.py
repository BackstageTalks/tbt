"""Read-only, identity-exact current-rank supplement for ESÁ market candidates.

The champion model and Match Winner offer must retain their original feature
snapshot. Only missing Aces/Most Aces presentation ranks may be filled from the
already-published and fresh player asset bundle. No calls to TennisAPI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math


MAX_PROFILE_AGE = timedelta(days=14)


def _valid_rank(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not number.is_integer() or number < 1:
        return None
    return int(number)


def supplement_ace_ranks(predictions, payload, *, now: datetime):
    """Return independent ESÁ rows; never mutate predictions or overwrite ranks."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    report = {
        "source": "tbt-player-assets-v1/player_profiles.json",
        "status": "skipped",
        "matched_missing_player_ids": 0,
        "ranks_filled": 0,
        "unchanged_existing_ranks": 0,
    }
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        report["reason"] = "invalid_profile_schema"
        return predictions, report
    profiles = payload.get("players")
    if not isinstance(profiles, dict):
        report["reason"] = "missing_player_index"
        return predictions, report
    try:
        stamp = datetime.fromisoformat(str(payload.get("generated_at") or "").replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("naive snapshot")
    except (ValueError, TypeError):
        report["reason"] = "unknown_profile_timestamp"
        return predictions, report
    age = now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)
    if age < timedelta(0) or age > MAX_PROFILE_AGE:
        report["reason"] = "profile_snapshot_outside_freshness_window"
        return predictions, report

    report["status"] = "verified_fresh"
    report["generated_at"] = stamp.isoformat()
    rows = list(predictions)
    for index, row in enumerate(predictions):
        if not isinstance(row, dict):
            continue
        updated = None
        for side in ("player1", "player2"):
            player = row.get(side)
            if not isinstance(player, dict):
                continue
            if player.get("rank") not in (None, ""):
                report["unchanged_existing_ranks"] += 1
                continue
            player_id = str(player.get("id") or "").strip()
            source = profiles.get(player_id) if player_id else None
            if not isinstance(source, dict):
                continue
            report["matched_missing_player_ids"] += 1
            verified = _valid_rank(source.get("rank"))
            if verified is None:
                continue
            if updated is None:
                updated = dict(row)
            enriched_player = dict(player)
            enriched_player["rank"] = verified
            enriched_player["rank_source"] = "verified_recent_player_profile"
            enriched_player["rank_source_generated_at"] = stamp.isoformat()
            updated[side] = enriched_player
            report["ranks_filled"] += 1
        if updated is not None:
            rows[index] = updated
    return rows, report
