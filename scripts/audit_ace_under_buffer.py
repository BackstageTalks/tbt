"""Read-only historical replay of the Aces UNDER *filter*.

Uses only already-issued, settled player-Aces UNDER bets with evidenced real
pre-match bookmaker quotes. It cannot infer alternative historical bookmaker
lines or their prices, so it does not backtest 11.5 -> 12.5 substitutions.
No provider calls, CDB access, mutation, or simulated odds.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from tbt.services.ace_under_buffer import ace_under_eligible, ace_under_preferred


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _real_price(row: dict) -> float | None:
    price = _number(row.get("odds"))
    if price is None or price <= 1 or row.get("price_status") != "priced_projection":
        return None
    if not _timestamp(row.get("captured_at")) or not _timestamp(row.get("issued_at")):
        return None
    provider = _number(row.get("provider_id"))
    source = str(row.get("odds_source") or "").lower()
    bookmaker = bool(row.get("odds_bookmaker"))
    if not ((source == "rapidapi" and provider == 1)
            or (source == "propline" and provider == 2 and bookmaker)
            or (source == "moviodds" and provider == 3 and row.get("odds_bookmaker") == "bet365")):
        return None
    return price


def _rows(payload: Any):
    if isinstance(payload, list):
        yield from (row for row in payload if isinstance(row, dict))
    elif isinstance(payload, dict):
        for key in ("ledger", "results", "predictions", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                yield from (row for row in value if isinstance(row, dict))


def _stats(items: list[dict]) -> dict:
    n = len(items)
    hits = sum(item["hit"] for item in items)
    profit = sum(item["odds"] - 1 if item["hit"] else -1 for item in items)
    return {
        "bets": n, "hits": hits, "misses": n - hits,
        "hit_rate": round(hits / n, 5) if n else None,
        "profit_units": round(profit, 4),
        "roi_per_unit": round(profit / n, 5) if n else None,
    }


def replay(payload: Any) -> dict:
    all_picks = []
    dedup = set()
    candidates = 0
    skipped_no_real_quote_or_result = 0
    for row in _rows(payload):
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            if (str(pub.get("market") or "").lower() != "aces"
                    or pub.get("price_contract") != "player_total_ou"
                    or str(pub.get("ou_side") or "").lower() != "under"):
                continue
            candidates += 1
            key = (str(row.get("event_id") or row.get("match_id") or ""),
                   str(pub.get("publication_key") or ""),
                   str(pub.get("selection_id") or ""))
            if not key[0] or not key[1] or key in dedup:
                continue
            dedup.add(key)
            result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            line = _number(pub.get("market_line"))
            projection = _number(pub.get("projection"))
            count = _number(result.get("actual_count"))
            price = _real_price(pub)
            captured = _timestamp(pub.get("captured_at"))
            issued = _timestamp(pub.get("issued_at"))
            scheduled = _timestamp(result.get("scheduled_at") or row.get("scheduled_at"))
            if (pub.get("publication_status") != "published"
                    or result.get("status") not in {"hit", "miss"}
                    or None in (line, projection, count, price, captured, issued, scheduled)
                    or captured > scheduled or issued > scheduled
                    or bool(result.get("correct")) != (count < line)):
                skipped_no_real_quote_or_result += 1
                continue
            all_picks.append({
                "projection": projection, "line": line, "odds": price,
                "hit": count < line,
            })
    kept = [x for x in all_picks if ace_under_eligible(x["projection"], x["line"])]
    preferred = [x for x in kept if ace_under_preferred(x["projection"], x["line"])]
    return {
        "schema": 1, "scope": "issued_real_odds_player_aces_under_only",
        "historical_projection_count": candidates,
        "real_quote_settled_count": len(all_picks),
        "excluded_no_evidenced_real_quote_or_settlement": skipped_no_real_quote_or_result,
        "before_filter": _stats(all_picks),
        "after_minimum_buffer": _stats(kept),
        "preferred_buffer_existing_offers": _stats(preferred),
        "removed_by_buffer": len(all_picks) - len(kept),
        "alternatives_replayed": False,
        "limitation": "Only filtering historically issued real quotes; unavailable alternative lines cannot be reconstructed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path, help="Local read-only historical ledger JSON")
    args = parser.parse_args()
    output = replay(json.loads(args.ledger.read_text(encoding="utf-8")))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
