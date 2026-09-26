"""Capture genuinely available pre-match O/U quotes for calibration research.

Reads the private published feed, fetches only its current selected events, and
appends raw *complete, two-sided* GAMES/SETS markets to a dedicated PRIVATE
GitHub release. No production feed, ledger or model is modified. Snapshots use
provider event IDs and real provider prices; estimates never enter this corpus.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.projection_odds import extract_match_total_odds

RELEASE_TAG = "tbt-market-odds-v1"
MARKETS = {"games", "sets"}


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def upcoming_projections(feed: dict, now: datetime) -> dict[str, list[dict]]:
    """Only genuine provider IDs on published, not-yet-started SG cards."""
    result = {}
    for item in feed.get("sg_picks", []) or []:
        if not isinstance(item, dict):
            continue
        market = str(item.get("market") or "").strip().lower()
        event_id = str(item.get("event_id") or "").strip()
        starts = parse_time(item.get("scheduled_at") or item.get("date"))
        if market not in MARKETS or not event_id.isdigit() or not starts or starts <= now:
            continue
        projection = item.get("projection")
        try:
            projection = float(projection)
        except (ValueError, TypeError):
            continue
        if not 0 < projection < 100:
            continue
        record = {
            "event_id": event_id,
            "market": market,
            "starts_at_utc": starts.isoformat(),
            "projection": projection,
            "projection_confidence": item.get("projection_confidence"),
            "reference_projection_not_bookmaker_line": item.get("reference_projection"),
            "direction": item.get("projection_direction"),
            "selection_id": item.get("selection_id"),
            "best_of": item.get("best_of"),
            "tour": item.get("tour"),
            "surface": item.get("surface"),
        }
        if record not in result.setdefault(event_id, []):
            result[event_id].append(record)
    return result


def snapshot_quotes(projections: dict[str, list[dict]], provider, now: datetime, *,
                    max_events: int, provider_id: int = 1):
    """One provider call per event, no inferred prices, no past-match calls."""
    rows, errors = [], []
    for event_id, cards in list(projections.items())[:max_events]:
        if all((parse_time(card["starts_at_utc"]) or now) <= now for card in cards):
            continue
        try:
            payload = provider.event_odds(event_id, provider_id=provider_id)
        except Exception as exc:
            errors.append({"event_id": event_id, "error_type": type(exc).__name__})
            continue
        observed = {card["market"] for card in cards}
        for market in sorted(observed):
            for quote in extract_match_total_odds(payload, market):
                line = float(quote["line"])
                over, under = float(quote["over"]), float(quote["under"])
                if not (1 < over <= 100 and 1 < under <= 100):
                    continue
                rows.append({
                    "event_id": event_id, "market": market,
                    "line": line, "over_odds": over, "under_odds": under,
                    "provider_id": provider_id,
                    "market_name": str(quote.get("market_name") or "")[:120],
                    "captured_at_utc": now.isoformat(),
                    "starts_at_utc": cards[0]["starts_at_utc"],
                    "models": [card for card in cards if card["market"] == market],
                    "source": "rapid_tennis_event_odds_exact_two_sided",
                })
    return rows, errors


def append_unique(old: list[dict], new: list[dict]) -> list[dict]:
    seen, result = set(), []
    for row in old + new:
        key = (str(row["event_id"]), row["market"], float(row["line"]),
               int(row["provider_id"]), row["captured_at_utc"])
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return sorted(result, key=lambda x: (x["captured_at_utc"], x["event_id"], x["market"], x["line"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-events", type=int, default=30)
    p.add_argument("--max-requests", type=int, default=35)
    p.add_argument("--provider-id", type=int, default=1)
    p.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    args = p.parse_args()
    if not (1 <= args.max_events <= args.max_requests <= 80):
        p.error("Require 1 <= max-events <= max-requests <= 80")
    if args.provider_id < 1:
        p.error("Invalid provider ID")
    now = datetime.now(timezone.utc)
    published = ReleaseStore(args.data_repository, "tbt-predictions-v1",
                             ROOT / ".cache/tbt/market-odds/published")
    published.download(extra_names=("feed.json",), required_names=("feed.json",),
                       require_bundle_manifest=True)
    feed = json.loads((published.directory / "feed.json").read_text(encoding="utf-8"))
    if not isinstance(feed, dict):
        raise ValueError("Invalid published feed")
    projections = upcoming_projections(feed, now)
    client = RapidTennisClient(request_budget=None)
    client.request_limit = args.max_requests
    captured, errors = snapshot_quotes(projections, client, now, max_events=args.max_events,
                                       provider_id=args.provider_id)
    archive = ReleaseStore(args.data_repository, RELEASE_TAG,
                           ROOT / ".cache/tbt/market-odds/archive")
    filename = f"market_odds_{now:%Y%m}.json"
    existing = archive._asset_names()
    if filename in existing:
        archive.download(extra_names=(filename,), required_names=(filename,),
                         require_bundle_manifest=True)
        old = json.loads((archive.directory / filename).read_text(encoding="utf-8"))
        if not isinstance(old, list):
            raise ValueError("Invalid archived market observations")
    else:
        old = []
    combined = append_unique(old, captured)
    # Never upload a report with no newly captured real prices.
    if len(combined) > len(old):
        path = archive.directory / filename
        path.write_text(json.dumps(combined, ensure_ascii=False, indent=2, allow_nan=False),
                        encoding="utf-8")
        archive.upload_bundle([path])
    report = {
        "schema": 1, "captured_at_utc": now.isoformat(),
        "read_only_production": True, "release": RELEASE_TAG,
        "eligible_upcoming_events": len(projections),
        "events_requested": min(args.max_events, len(projections)),
        "provider_id": args.provider_id, "max_requests": args.max_requests,
        "new_complete_two_sided_quotes": len(captured),
        "unique_monthly_quotes": len(combined),
        "fetch_errors": errors,
        "by_market": dict(Counter(q["market"] for q in captured)),
        "no_derived_bookmaker_prices": True,
        "historical_prices_not_backfilled": True,
    }
    out = ROOT / ".cache/tbt/market-odds/report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
