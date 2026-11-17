"""Small, authenticated serving snapshot. No database or ML dependency."""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


MAX_FEED_BYTES = 32 * 1024 * 1024  # Guarded headroom for verified 21,728,761-byte 2026-10-25 release
MAX_ACES_PLAYER_RANK = 1000  # Both players, ATP/WTA active Aces / Most Aces only
# Forward-only cutoff. Preserve the finalized, previously published 17 Nov
# daily offer across a same-day deployment. 18 Nov 06:00 local (CET) starts
# the first betting day under the new WTA250+ selection rule.
WTA_GRADE_GATE_EFFECTIVE_UTC = datetime(2026, 11, 18, 5, 0, tzinfo=timezone.utc)


def _legacy_wta_offer(row):
    """Only events from betting days before the explicit activation cutoff."""
    raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
    if not raw:
        return False  # unknown event clock cannot grandfather into new offers
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError):
        return False
    return (stamp.tzinfo is not None and
            stamp.astimezone(timezone.utc) < WTA_GRADE_GATE_EFFECTIVE_UTC)


def _wta_aces_level_reason(row):
    """Fail closed unless the women's event is verified WTA 250+ or a Slam.

    The generic WTA gender/tour label is not proof of tournament grade.
    Missing classification must not silently admit WTA 125 or ITF.
    """
    fields = ("tournament", "tournament_name", "tournament_type",
              "competition", "competition_type", "tour_level",
              "tournament_level", "category")
    labels = [str(row.get(field) or "").strip().casefold() for field in fields]
    tour = str(row.get("tour") or "").strip().casefold()
    labels.append(tour)
    if any(re.search(r"\bwta[\s_-]*(?:125|challenger)\b", label)
           or re.search(r"\b(?:juniors?|wheelchair|exhibition)\b", label)
           for label in labels):
        return "excluded_wta_below_250"
    if any(re.search(r"\bwta[\s_-]*(?:250|500|1000|finals)\b", label)
           or re.search(r"\bgrand\s+slams?\b", label)
           for label in labels):
        return "eligible"
    tournament = str(row.get("tournament") or row.get("tournament_name") or "").casefold()
    if re.search(r"\b(?:australian open|roland garros|french open|wimbledon|us open)\b",
                 tournament):
        return "eligible"
    return "unverified_wta_level"


def ace_eligibility_reason(row):
    """Explain the active singles ESÁ/Viac Es gate, without changing thresholds.

    ATP main-tour/Challenger remain eligible with both players TOP-1000;
    WTA requires positive evidence of WTA 250/500/1000, Finals or Grand Slam.
    WTA 125, ITF/Futures and unknown WTA grades are excluded.
    Existing historical issued Results are not regraded.
    """
    if not isinstance(row, dict):
        return "unsupported_tour"
    tour = str(row.get("tour") or "").strip().casefold()
    atp_tours = {"atp", "atp tour", "atp challenger"}
    wta_tours = {"wta", "wta tour", "wta challenger", "wta 125", "wta125",
                 "wta-125", "wta 250", "wta250", "wta 500", "wta500",
                 "wta 1000", "wta1000", "wta finals"}
    if tour not in atp_tours | wta_tours:
        return "unsupported_tour"
    for field in ("tournament", "tournament_name", "tournament_type",
                  "competition", "competition_type", "tour_level",
                  "tournament_level", "category"):
        label = str(row.get(field) or "").strip().casefold()
        if any(tag in label for tag in ("itf", "futures")):
            return "excluded_itf_futures"
    if tour in wta_tours and not _legacy_wta_offer(row):
        level_reason = _wta_aces_level_reason(row)
        if level_reason != "eligible":
            return level_reason
    for side in ("player1", "player2"):
        player = row.get(side)
        if not isinstance(player, dict) or player.get("rank") in (None, ""):
            return "missing_player_rank"
        value = player.get("rank")
        if isinstance(value, bool):
            return "invalid_player_rank"
        try:
            rank = float(value)
        except (TypeError, ValueError, OverflowError):
            return "invalid_player_rank"
        if not math.isfinite(rank) or not rank.is_integer() or rank < 1:
            return "invalid_player_rank"
        if rank > MAX_ACES_PLAYER_RANK:
            return "outside_top1000"
    return "eligible"


def main_tour_aces(row):
    """Compatibility gate for active ESÁ and Viac Es selection/presentation."""
    return ace_eligibility_reason(row) == "eligible"


def _betting_day_key(moment, *, timezone_name="Europe/Bratislava", start_hour=6):
    if moment.tzinfo is None:
        raise ValueError("betting day requires timezone-aware datetime")
    local = moment.astimezone(ZoneInfo(timezone_name))
    boundary = local.replace(hour=int(start_hour), minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.date().isoformat()


def _row_betting_day(row, *, timezone_name="Europe/Bratislava", start_hour=6):
    if not isinstance(row, dict):
        return ""
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    explicit = str(row.get("betting_day") or betting.get("betting_day") or "").strip()
    if explicit:
        return explicit
    raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
    try:
        starts_at = _parse_utc_timestamp(raw, "scheduled_at")
    except ValueError:
        return ""
    return _betting_day_key(starts_at, timezone_name=timezone_name, start_hour=start_hour)

def empty_feed():
    return {
        "schema": 1,
        "generated_at": None,
        "model": None,
        "upcoming": [],
        "top200_picks": [],
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
        "market_selection": {},
        "results": [],
        "performance": {},
        "betting_performance": {},
        "results_meta": {"settled_total": 0, "returned": 0, "limit": 1000},
        "history": {},
        "ready": False,
    }


def _parse_utc_timestamp(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid serving feed timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid serving feed timestamp: {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Naive serving feed timestamp: {field}")
    return parsed.astimezone(timezone.utc)


def _validate_prediction_row(row, *, require_result=False):
    if not isinstance(row, dict):
        raise ValueError("Invalid serving feed row")

    for key in ("event_id", "scheduled_at", "player1", "player2"):
        if key not in row:
            raise ValueError(f"Invalid serving feed row: missing {key}")

    if not str(row.get("event_id") or "").strip():
        raise ValueError("Invalid serving feed row: empty event_id")

    _parse_utc_timestamp(row.get("scheduled_at"), "scheduled_at")

    for player_key in ("player1", "player2"):
        player = row.get(player_key)
        if not isinstance(player, dict):
            raise ValueError(f"Invalid serving feed row: {player_key}")
        if not str(player.get("id") or "").strip():
            raise ValueError(f"Invalid serving feed row: {player_key}.id")

    if require_result:
        result = row.get("result")
        if not isinstance(result, dict):
            raise ValueError("Invalid serving result row")
        if not str(result.get("winner_id") or "").strip():
            raise ValueError("Invalid serving result row: winner_id")


def read_feed(path):
    target = Path(path)
    if not target.is_file():
        return empty_feed()
    if target.stat().st_size > MAX_FEED_BYTES:
        raise ValueError(f"Serving feed exceeds the {MAX_FEED_BYTES // (1024 * 1024)} MB cap")

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid serving feed JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid serving feed root")
    if payload.get("schema") != 1:
        raise ValueError("Unsupported serving schema")

    for key in ("upcoming", "results"):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"Invalid serving feed: {key}")

    stamp = payload.get("generated_at")
    if stamp is not None:
        _parse_utc_timestamp(stamp, "generated_at")

    for row in payload["upcoming"]:
        _validate_prediction_row(row, require_result=False)
    for row in payload["results"]:
        _validate_prediction_row(row, require_result=True)

    return payload


@lru_cache(maxsize=1)
def _validated_serving_source(path: Path, revision: tuple[int, ...]) -> dict:
    """Memoize only the immutable, validated on-disk serving publication.

    Never cache the per-account response, active issued authority, Results
    exclusions, match statuses or runtime UI configuration. The caller must
    use copy-on-write filters and never mutate this shared source object.
    """
    return read_feed(path)


def read_serving_source_cached(path: Path) -> dict:
    """Reuse validated release bytes while rejecting changed or broken files.

    The metadata key catches in-place rewrites and atomic replacements; a
    missing, unreadable or oversized file takes the normal fail-safe path.
    This intentionally returns the SAME read-only source reference, avoiding
    a full 20+ MB deepcopy that benchmarks slower than JSON parsing.
    """
    target = Path(path)
    try:
        stat = target.stat()
    except FileNotFoundError:
        return read_feed(target)
    if not target.is_file() or stat.st_size > MAX_FEED_BYTES:
        return read_feed(target)
    revision = (
        stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
    )
    return _validated_serving_source(target, revision)


def visible_feed(payload, now=None):
    """Serve future discovery and today's public 06:00-to-06:00 offer.

    The internal betting-day interval remains [06:00, next 06:00), with the
    ending 06:00 excluded. Public TOP/ACCA/VALUE/other daily tabs additionally
    show only fixtures dated on the *opening calendar day* in Bratislava.
    After-midnight fixtures in the internal interval stay in the raw snapshot
    but are not displayed as tomorrow's matches on today's page.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid serving feed root")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("visible_feed requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    day = _betting_day_key(now)

    result = dict(payload)
    # Legacy releases may contain TOP200 rows; the public product is retired.
    # Never serve its active picks, while preserving historical settled Results.
    result["top200_picks"] = []

    upcoming = payload.get("upcoming", [])
    if not isinstance(upcoming, list):
        raise ValueError("Invalid serving feed: upcoming")
    future=[]
    for row in upcoming:
        if not isinstance(row, dict):
            continue
        raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
        try:
            starts_at = _parse_utc_timestamp(raw, "scheduled_at")
        except ValueError:
            continue
        if starts_at > now:
            future.append(row)
    result["upcoming"] = future

    # Internal settlement/publication remains 06:00 -> next-day 05:59:59.
    # The public TODAY board must not show rows dated tomorrow, even when the
    # internal betting-day window includes them (e.g. 19 Oct 04:30 and 05:00
    # before the 19 Oct 06:00 rollover). Use actual scheduled_at, not a
    # potentially wrong explicit betting_day, to enforce BOTH conditions.
    # This is presentation filtering only; retain raw history unchanged.
    local_zone = ZoneInfo("Europe/Bratislava")

    def scheduled_for_public_offer_day(row):
        if not isinstance(row, dict):
            return False
        raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
        try:
            scheduled = _parse_utc_timestamp(raw, "scheduled_at")
        except ValueError:
            return False
        local_date = scheduled.astimezone(local_zone).date().isoformat()
        return local_date == day and _betting_day_key(scheduled) == day

    for key in ("top_daily_picks", "prime_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks"):
        rows = payload.get(key, [])
        if not isinstance(rows, list):
            continue
        result[key] = [
            row for row in rows
            if scheduled_for_public_offer_day(row)
            and (key != "ace_picks"
                 or str(row.get("market") or "").strip().lower() not in {"aces", "most_aces"}
                 or main_tour_aces(row))
        ]

    stamp = payload.get("generated_at")
    if not stamp:
        result["stale"] = True
    else:
        generated_at = _parse_utc_timestamp(stamp, "generated_at")
        # The serving offer is refreshed each betting morning. A fixed 12h
        # timer incorrectly flags a healthy 06:00 feed as broken after 18:00.
        # Fail closed after the next 06:00 Bratislava boundary, or when an
        # implausibly future-dated feed indicates clock/deployment corruption.
        result["stale"] = (
            _betting_day_key(generated_at) != day
            or generated_at > now + timedelta(minutes=5)
        )
    result["daily_offer_day"] = day
    return result


# Trusted, bounded public-day category counts; ESÁ O/U and Viac Es remain
# independent even though the historical serving schema shares ace_picks.
_MARKET_FEED_TAGS = {
    "ace": ("ace_picks", "aces"),
    "ace_winner": ("ace_picks", "most_aces"),
    "double_faults": ("ace_picks", "double_faults"),
    "sets": ("sg_picks", "sets"),
    "games": ("sg_picks", "games"),
}


def _offer_market_counts(payload):
    counts = {
        "top_daily": len(payload.get("top_daily_picks") or []),
        "prime": len(payload.get("prime_picks") or []),
        "value": len(payload.get("value_picks") or []),
        "doubles": len(payload.get("doubles_picks") or []),
    }
    for category, (feed_key, market) in _MARKET_FEED_TAGS.items():
        counts[category] = sum(
            isinstance(row, dict) and str(row.get("market") or "").strip().lower() == market
            for row in payload.get(feed_key) or []
        )
    counts["unknown_ace"] = len(payload.get("ace_picks") or []) - sum(
        counts[category] for category in ("ace", "ace_winner", "double_faults")
    )
    counts["unknown_sg"] = len(payload.get("sg_picks") or []) - counts["sets"] - counts["games"]
    return counts


def _offer_surface_counts(payload, *, current_day=False):
    """Count cards eligible for the normal browser surface guard, not tier access.

    The TOP count also applies the server's canonical price integrity filter.
    No claim is made about the signed-in user's Admin-plan overrides.
    """
    source = dict(payload)
    if current_day:
        from .entitlements import _daily_rows
        source["top_daily_picks"] = _daily_rows(source)
    def eligible(row):
        surface = str((row or {}).get("surface") or (row or {}).get("court_surface") or "").strip().lower()
        return bool(surface and surface != "unknown")
    result = dict(source)
    for key in ("top_daily_picks", "prime_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks"):
        result[key] = [row for row in source.get(key, []) if isinstance(row, dict) and eligible(row)]
    return _offer_market_counts(result)


# Worker-token-only diagnostic: never expose row identities, member access
# allocations, selections or odds. This is independent *serving file* evidence,
# not proof of an authenticated customer's plan-specific rendered UI.
_SERVING_COUNT_KEYS = (
    "upcoming", "top_daily_picks", "prime_picks", "value_picks",
    "ace_picks", "sg_picks", "doubles_picks", "results",
)


def serving_artifact_readback(path, *, now=None):
    """Read exact packaged serving bytes and a bounded, public-day projection."""
    target = Path(path)
    blob = target.read_bytes()  # Missing file is an error, not empty_feed().
    payload = read_feed(target)
    for key in _SERVING_COUNT_KEYS:
        if key in payload and not isinstance(payload[key], list):
            raise ValueError("Invalid serving market rows: " + key)
    visible = visible_feed(payload, now=now)
    raw_counts = {key: len(payload.get(key) or []) for key in _SERVING_COUNT_KEYS}
    visible_counts = {key: len(visible.get(key) or []) for key in _SERVING_COUNT_KEYS}
    market_counts = _offer_market_counts(visible)
    surface_counts = _offer_surface_counts(visible, current_day=True)
    return {
        "ok": True,
        "schema": 1,
        "file_sha256": sha256(blob).hexdigest(),
        "bytes": len(blob),
        "ready": payload.get("ready") is True,
        "generated_at": payload.get("generated_at"),
        "betting_day": visible.get("daily_offer_day"),
        "stale": visible.get("stale") is True,
        "raw_counts": raw_counts,
        "visible_counts": visible_counts,
        "visible_market_counts": market_counts,
        "surface_eligible_market_counts": surface_counts,
    }
