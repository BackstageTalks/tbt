"""Optional, strictly matched PropLine 23:00 archive prices for new morning ESÁ.

Model selection and already priced/issued rows are immutable. Only the exact
player, fixture, betting day, and full two-sided sportsbook O/U line can
enrich an unissued model-selected Aces card. N+ milestones, fantasy and
unverified Most Aces settlement never become bookmaker O/U quotes.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import subprocess
import unicodedata
from zoneinfo import ZoneInfo

from ace_working_odds import local_player_aces_ou
from propline_evening_odds import _single_book_quotes, SOURCE_URL, event_odds_url

TZ = ZoneInfo("Europe/Bratislava")
DATA_REPO = "BackstageTalks/tbt-data"
ARCHIVE_PREFIX = "research/propline-evening-odds"
MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
FANTASY = frozenset(("dabble", "sleeper", "prizepicks", "underdog",
                     "parlayplay", "draftkings_pick6"))


def _stamp(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def _tokens(value):
    clean = "".join(c for c in unicodedata.normalize(
        "NFKD", str(value or "").casefold()) if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", clean)


def _same_person(bookmaker, player):
    """Full names or surname + exact given initials, never surname alone."""
    book, model = _tokens(bookmaker), _tokens(player)
    if not book or not model or len(model) < 2:
        return False
    if book == model:
        return True
    if len(book) < 2:
        return False
    if book[0] == model[-1]:
        first = book[1:]
    elif book[-1] == model[-1]:
        first = book[:-1]
    else:
        return False
    given = model[:-1]
    return len(first) == len(given) and all(
        b == m or (len(b) == 1 and b == m[0])
        for b, m in zip(first, given)
    )


def _betting_day(scheduled):
    local = scheduled.astimezone(TZ)
    return (local - timedelta(days=1) if local.hour < 6
            else local).date().isoformat()


def _valid_report(report, *, betting_day, now):
    if not isinstance(report, dict) or (
        report.get("schema"), report.get("source"),
        report.get("target_betting_day")
    ) != (1, "propline_free", betting_day):
        return False
    calls = report.get("provider_requests")
    details = report.get("provider_event_requests", 0)
    if (report.get("status") not in ("audited", "no_exact_aces_market_available")
            or report.get("cdb_writes") != 0
            or report.get("published_picks_changed") != 0
            or report.get("provider_paid_calls") != 0
            or not isinstance(calls, int) or isinstance(calls, bool)
            or not isinstance(details, int) or isinstance(details, bool)
            or calls != 1 + details or details < 0
            or details > len(report.get("events_in_target_window") or [])
            or report.get("coverage_truncated") is not False):
        return False
    captured = _stamp(report.get("captured_at"))
    if not captured or not timedelta(0) <= now - captured <= timedelta(hours=24):
        return False
    return isinstance(report.get("events_in_target_window"), list)


def validated_events(report, *, betting_day, now):
    """Use only proven pre-start source rows from one fresh target-day report."""
    if not _valid_report(report, betting_day=betting_day, now=now):
        return []
    accepted = []
    for event in report["events_in_target_window"]:
        if not isinstance(event, dict) or event.get("provider") != "propline":
            continue
        captured = _stamp(event.get("captured_at"))
        scheduled = _stamp(event.get("scheduled_at"))
        if (not captured or not scheduled or not
                timedelta(0) <= now - captured <= timedelta(hours=24)
                or captured >= scheduled or now >= scheduled
                or _betting_day(scheduled) != betting_day):
            continue
        if event.get("source_url") not in {
                SOURCE_URL, event_odds_url(event.get("event_id"))}:
            continue
        raw = event.get("provider_raw_event")
        players = event.get("players")
        if (not isinstance(raw, dict) or
                not isinstance(players, list) or len(players) != 2 or
                str(raw.get("id") or "") != str(event.get("event_id") or "") or
                not str(event.get("event_id") or "").isdigit() or
                players != [raw.get("home_team"), raw.get("away_team")]):
            continue
        raw_stamp = _stamp(raw.get("commence_time") or raw.get("start_time"))
        if raw_stamp != scheduled:
            continue
        digest = hashlib.sha256(json.dumps(
            raw, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        if digest != event.get("source_sha256"):
            continue
        # Reproduce the collector's market parsing from its original provider
        # record rather than trusting an altered or improperly joined quote.
        markets = []
        for book in raw.get("bookmakers") or []:
            if isinstance(book, dict):
                parsed, _ = _single_book_quotes(raw, book)
                markets.extend(parsed)
        if markets != event.get("aces_markets"):
            continue
        accepted.append(event)
    return accepted


def _decode_content(item, runner):
    """GitHub Contents API may omit inline base64 for archives over 1 MiB."""
    if item.get("encoding") == "none" and item.get("sha"):
        item = json.loads(runner([
            "gh", "api", "repos/" + DATA_REPO + "/git/blobs/" + item["sha"]]))
    if item.get("encoding") != "base64" or not item.get("content"):
        return None
    raw = base64.b64decode(item["content"])
    return raw if 0 < len(raw) <= MAX_ARCHIVE_BYTES else None


def load_evening_report(*, betting_day, now, repo=DATA_REPO, runner=None):
    """Optional private read, zero provider API requests, fail closed."""
    if (repo != DATA_REPO or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", betting_day)
            or not isinstance(now, datetime) or now.tzinfo is None):
        return None, "invalid_source"
    runner = runner or (lambda args: subprocess.check_output(args, timeout=20))
    path = "repos/" + repo + "/contents/" + ARCHIVE_PREFIX + "/" + betting_day
    try:
        entries = json.loads(runner(["gh", "api", path]))
        if not isinstance(entries, list):
            return None, "invalid_directory"
        candidates = [
            item for item in entries
            if isinstance(item, dict) and item.get("type") == "file"
            and re.fullmatch(r"propline-\d+\.json", str(item.get("name") or ""))
        ]
        candidates.sort(key=lambda item: int(item["name"][9:-5]), reverse=True)
        for item in candidates[:5]:
            source = json.loads(runner(["gh", "api", path + "/" + item["name"]]))
            raw = _decode_content(source, runner)
            if raw is None:
                continue
            report = json.loads(raw)
            if _valid_report(report, betting_day=betting_day, now=now):
                return report, "loaded"
        return None, "no_valid_evening_snapshot"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return None, "unavailable:" + type(exc).__name__


def _event_identity(event, card):
    book = event.get("players")
    p1, p2 = card.get("player1"), card.get("player2")
    if (not isinstance(book, list) or len(book) != 2
            or not isinstance(p1, dict) or not isinstance(p2, dict)
            or not all(str(p.get("id") or "").strip() and str(p.get("name") or "").strip()
                       for p in (p1, p2))):
        return None
    names = (p1["name"], p2["name"])
    orders = [
        {0: a, 1: b} for a, b in ((0, 1), (1, 0))
        if _same_person(book[0], names[a]) and _same_person(book[1], names[b])
    ]
    scheduled = _stamp(card.get("scheduled_at"))
    observed = _stamp(event.get("scheduled_at"))
    if (len(orders) != 1 or not scheduled or not observed or
            abs((scheduled - observed).total_seconds()) > 30 * 60):
        return None
    return orders[0]


def _price(value):
    try:
        if isinstance(value, bool):
            return None
        result = float(value)
        return result if math.isfinite(result) and 1.01 <= result <= 100 else None
    except (TypeError, ValueError, OverflowError):
        return None


def attach_prices(ace_picks, report, *, now, betting_day):
    """Enrich only original unissued ESÁ picks; preserve list membership/order."""
    events = validated_events(report, betting_day=betting_day, now=now)
    result = []
    stats = {"source": "propline_evening", "eligible_events": len(events),
             "matched_aces": 0, "ambiguous_fixtures": 0,
             "ambiguous_market": 0, "unmatched_aces": 0,
             "unverified_most_aces_attached": 0}
    for row in ace_picks:
        original = deepcopy(row)
        if (not isinstance(row, dict) or row.get("market") != "aces" or
                row.get("price_status") != "projection_only" or
                row.get("odds") is not None or row.get("issued_at") or
                row.get("publication_status") == "published"):
            result.append(original)
            continue
        local = local_player_aces_ou(row)
        if local is None:
            result.append(original)
            stats["unmatched_aces"] += 1
            continue
        # An already explicit model/issuer contract takes precedence over a
        # newly derived local O/U line. Never silently switch its direction.
        if row.get("market_line") is not None or row.get("ou_side"):
            try:
                original_line = float(row.get("market_line"))
            except (ValueError, TypeError, OverflowError):
                original_line = None
            if (original_line != float(local["market_line"])
                    or str(row.get("ou_side") or "over").lower() != "over"):
                result.append(original)
                stats["unmatched_aces"] += 1
                continue
        fixtures = [(event, _event_identity(event, row)) for event in events]
        fixtures = [(event, mapping) for event, mapping in fixtures if mapping is not None]
        if len(fixtures) != 1:
            result.append(original)
            stats["ambiguous_fixtures" if len(fixtures) > 1 else "unmatched_aces"] += 1
            continue
        event, mapping = fixtures[0]
        selected = str(row.get("selection_id") or "")
        p1, p2 = row.get("player1") or {}, row.get("player2") or {}
        slot = 0 if selected and selected == str(p1.get("id")) else (
            1 if selected and selected == str(p2.get("id")) else None)
        if slot is None:
            result.append(original)
            stats["unmatched_aces"] += 1
            continue
        source_player = event["players"][next(index for index, mapped in mapping.items()
                                             if mapped == slot)]
        offered = []
        counts = {}
        for market in event["aces_markets"]:
            if (market.get("kind") != "player_aces_ou"
                    or str(market.get("bookmaker") or "").lower() in FANTASY):
                continue
            for pair in market.get("verified_pairs") or []:
                if (not isinstance(pair, dict) or
                        not _same_person(pair.get("player"), source_player)
                        or not _same_person(pair.get("player"), (p1, p2)[slot]["name"])):
                    continue
                try:
                    line = float(pair["line"])
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
                price = _price(pair.get("over"))
                if (line != float(local["market_line"])
                        or price is None or _price(pair.get("under")) is None
                        or price < 1.50 or price == 2.0
                        or not market.get("market_id")
                        or pair.get("market_id") != market.get("market_id")
                        or pair.get("bookmaker") != market.get("bookmaker")):
                    continue
                book = market["bookmaker"].casefold()
                counts[book] = counts.get(book, 0) + 1
                offered.append((price, book, market))
        if not offered or any(count > 1 for count in counts.values()):
            result.append(original)
            stats["ambiguous_market" if offered else "unmatched_aces"] += 1
            continue
        # For the same exact contract, choose the strongest real bookmaker
        # quote deterministically; this never alters the match or line.
        price, _, market = sorted(offered, key=lambda it: (-it[0], it[1]))[0]
        updated = deepcopy(local)
        updated.update({
            "odds": round(price, 3),
            "price_status": "priced_projection",
            "provider_id": 2,
            "captured_at": event["captured_at"],
            "odds_source": "propline",
            "odds_bookmaker": market["bookmaker"],
            "odds_provider_event_id": event["event_id"],
            "odds_market_name": market["market_name"],
            "odds_market_id": market["market_id"],
            "odds_contract_version": "ace_df_real_api_v1",
        })
        result.append(updated)
        stats["matched_aces"] += 1
    return result, stats
