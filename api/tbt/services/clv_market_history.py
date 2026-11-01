"""Verified, presentation-only CLV observations for issued TOP / VALUE match-winner picks.

PropLine research samples never rewrite the original issued quote, selection,
ledger, CDB or model. Provider-native event IDs are matched by BOTH players and
scheduled start; ambiguous matches fail closed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import unicodedata

from .admin_storage import AdminStorageUnavailable, _table

TABLE = "BlinQClvQuotes"
SECTIONS = ("top_daily_picks", "daily_picks", "value_picks")
MAX_QUOTES_PER_EVENT = 64


def _time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _name(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in
                    value.encode("ascii", "ignore").decode("ascii").lower()).split())


def _pair(first, second):
    a, b = _name(first), _name(second)
    return tuple(sorted((a, b))) if a and b and a != b else None


def _price(value):
    """Normalize the provider-native h2h price into decimal odds.

    PropLine research archives use American moneyline prices (+150, -222).
    This is the same conversion as the existing propline_clv_report.decimal,
    not a synthetic, model-derived or placeholder price. Already-decimal
    provider values (1.001..10) are preserved without double conversion.
    """
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    if not (n == n and abs(n) < 1000000):
        return None
    if n >= 10:
        decimal = 1 + n / 100
    elif n <= -10:
        decimal = 1 + 100 / abs(n)
    else:
        decimal = n
    return round(decimal, 4) if 1.001 <= decimal < 100 else None


def _offer_rows(feed):
    """Deduplicate TOP aliases; never index markets outside the approved scope."""
    indexed = {}
    for key in SECTIONS:
        for row in feed.get(key) or []:
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("event_id") or "").strip()
            first = row.get("player1") or {}
            second = row.get("player2") or {}
            if not isinstance(first, dict) or not isinstance(second, dict):
                continue
            pair = _pair(first.get("name"), second.get("name"))
            kickoff = _time(row.get("scheduled_at"))
            if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", event_id)
                    or not pair or not kickoff):
                continue
            indexed[(event_id, pair)] = (kickoff, first.get("name"), second.get("name"))
    return indexed


def extract_verified_quotes(payload, feed, *, now=None):
    """Map raw research observations to uniquely matched issued matches."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("Invalid CLV research snapshot schema")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 40:
        raise ValueError("Invalid CLV events")
    offer = _offer_rows(feed)
    output = {}
    rejected = 0
    for event in events:
        if not isinstance(event, dict):
            rejected += 1
            continue
        pair = _pair(event.get("home_team"), event.get("away_team"))
        kickoff = _time(event.get("commence_time"))
        captured = _time(event.get("captured_at"))
        source_id = str(event.get("event_id") or "").strip()
        if (not pair or not kickoff or not captured
                or not re.fullmatch(r"[0-9]{1,32}", source_id)
                or captured >= kickoff or captured > now + timedelta(minutes=2)
                or now - captured > timedelta(hours=50)):
            rejected += 1
            continue
        matches = [(eid, offer_kickoff, p1, p2) for (eid, offered_pair),
                   (offer_kickoff, p1, p2) in offer.items()
                   if pair == offered_pair and
                   abs((offer_kickoff - kickoff).total_seconds()) <= 2 * 3600]
        # Multiple BlinQ events with identical player pair/time cannot be linked.
        event_ids = {item[0] for item in matches}
        if len(event_ids) != 1:
            rejected += 1
            continue
        event_id, target_start, p1, p2 = matches[0]
        if captured >= target_start:
            rejected += 1
            continue
        books = event.get("bookmakers")
        if not isinstance(books, list):
            rejected += 1
            continue
        for book in books[:12]:
            if not isinstance(book, dict):
                continue
            book_id = str(book.get("key") or book.get("title") or book.get("name") or "").strip()
            if not book_id or len(book_id) > 96:
                continue
            markets = book.get("markets")
            if not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, dict) or market.get("key") != "h2h":
                    continue
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list) or len(outcomes) != 2:
                    continue
                parsed = {_name(o.get("name")): _price(o.get("price"))
                          for o in outcomes if isinstance(o, dict)}
                if len(parsed) != 2:
                    continue
                odds1, odds2 = parsed.get(_name(p1)), parsed.get(_name(p2))
                if odds1 is None or odds2 is None:
                    continue
                record = {
                    "event_id": event_id,
                    "source_event_id": source_id,
                    "bookmaker": book_id,
                    "provider": "propline",
                    "market": "h2h",
                    "captured_at": captured.isoformat(),
                    "odds1": odds1,
                    "odds2": odds2,
                }
                digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                output[digest] = record
    return list(output.values()), rejected


def _entity(record):
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return {
        "PartitionKey": "event-" + record["event_id"],
        "RowKey": digest,
        "payload": json.dumps(record, ensure_ascii=False, sort_keys=True),
    }


def persist_quotes(quotes):
    """Append-only deterministic rows; independently verify every durable write."""
    table = _table(TABLE)
    written = 0
    reused = 0
    for quote in quotes:
        row = _entity(quote)
        try:
            table.create_entity(row)
            written += 1
        except Exception as exc:
            if getattr(exc, "status_code", None) not in (409, 412) and (
                    "already" not in type(exc).__name__.lower()
                    and "conflict" not in type(exc).__name__.lower()
                    and "storagewriteconflict" not in type(exc).__name__.lower()):
                raise AdminStorageUnavailable("CLV observation write failed") from exc
            reused += 1
        try:
            saved = table.get_entity(
                partition_key=row["PartitionKey"], row_key=row["RowKey"])
        except Exception as exc:
            raise AdminStorageUnavailable("CLV read-back unavailable") from exc
        if saved.get("payload") != row["payload"]:
            raise AdminStorageUnavailable("CLV read-back content mismatch")
    return {"written": written, "already_present": reused, "verified": written + reused}


def _valid_stored_record(raw, event_id, *, now):
    if not isinstance(raw, dict) or raw.get("event_id") != event_id:
        return None
    if raw.get("provider") != "propline" or raw.get("market") != "h2h":
        return None
    if not str(raw.get("bookmaker") or ""):
        return None
    if _price(raw.get("odds1")) is None or _price(raw.get("odds2")) is None:
        return None
    observed = _time(raw.get("captured_at"))
    if observed is None or observed > now + timedelta(minutes=2):
        return None
    return raw


def read_event_history(event_id, *, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        rows = _table(TABLE).query_entities(
            query_filter="PartitionKey eq 'event-" + event_id + "'")
    except Exception as exc:
        raise AdminStorageUnavailable("CLV observation read failed") from exc
    groups = defaultdict(list)
    for row in rows:
        try:
            item = json.loads(str(row.get("payload") or "{}"))
        except (ValueError, TypeError):
            continue
        item = _valid_stored_record(item, event_id, now=now)
        if item:
            groups[item["bookmaker"]].append(item)
    if not groups:
        return None
    # One exact bookmaker and one exact provider only. Prefer actual time-series
    # coverage and recency, not an attractive-looking change percentage.
    book, series = max(groups.items(), key=lambda pair: (
        len({item["captured_at"] for item in pair[1]}),
        max(item["captured_at"] for item in pair[1]),
        pair[0],
    ))
    series = sorted(series, key=lambda item: item["captured_at"])[-MAX_QUOTES_PER_EVENT:]
    return {
        "provider": "propline",
        "bookmaker": book,
        "verified": True,
        "exact_event_id_used": True,  # exact BlinQ identity after unique pair+time mapping
        "history": [dict(item) for item in series],
    }


def attach_offer_clv(feed):
    """Enrich only rows the entitlement filter already allowed into the response."""
    if not isinstance(feed, dict):
        return feed
    cache = {}
    for section in SECTIONS:
        rows = feed.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("event_id") or "").strip()
            if not eid or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", eid):
                continue
            if eid not in cache:
                cache[eid] = read_event_history(eid)
            if cache[eid]:
                previous = row.get("market_movement")
                # Prefer an already verified native-source time-series. The
                # independent PropLine fallback must never downgrade it.
                if isinstance(previous, dict) and (
                        previous.get("verified") is True
                        and len(previous.get("history") or []) >= 2):
                    continue
                row["market_movement"] = cache[eid]
    return feed
