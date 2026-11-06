"""Read-only production serving-feed evidence; no member data or provider calls.

The public health endpoint checks worker startup, not whether the packaged,
authenticated feed is still current. This diagnostic exposes only an exact
packaged-file digest, timestamps and aggregate counts to the existing signed
internal-worker identity. It cannot grant account entitlements.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .feed import read_feed, visible_feed

SERVING_COUNT_KEYS = (
    "upcoming",
    "top_daily_picks",
    "prime_picks",
    "value_picks",
    "ace_picks",
    "doubles_picks",
    "sg_picks",
    "results",
)


def serving_feed_readback(path: Path, *, now: datetime | None = None) -> dict:
    target = Path(path)
    # read_feed() permits absent local files as a bootstrap convenience; a
    # protected production readback must never report an absent file as healthy.
    if not target.is_file():
        raise ValueError("Packaged serving feed missing")
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("Serving readback requires a timezone-aware clock")
    raw = read_feed(target)
    view = visible_feed(raw, now=moment)

    def counts(rows: dict) -> dict[str, int]:
        result = {}
        for key in SERVING_COUNT_KEYS:
            group = rows.get(key, [])
            if not isinstance(group, list):
                raise ValueError("Invalid serving feed market array: " + key)
            result[key] = len(group)
        return result

    source_counts = counts(raw)
    visible_counts = counts(view)
    ready = raw.get("ready") is True
    stale = view.get("stale") is True
    return {
        "schema": 1,
        "ok": ready and not stale,
        "ready": ready,
        "stale": stale,
        "feed_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "generated_at": raw.get("generated_at"),
        "observed_at_utc": moment.astimezone(timezone.utc).isoformat(),
        "betting_day": view["daily_offer_day"],
        "source_counts": source_counts,
        "visible_counts": visible_counts,
    }
