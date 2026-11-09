"""Attach strictly matched overnight Fortuna SK ace prices without changing BlinQ picks.

No UI/selection/model/CDB mutations. A missing, stale or ambiguous quote leaves
the existing approved statistical fallback fully in charge.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import math
import re
import subprocess
import unicodedata
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bratislava")
DATA_REPO = "BackstageTalks/tbt-data"
FORTUNA_PROVIDER_ID = 4
FORTUNA_SOURCE = "fortuna_sk"


def _stamp(value):
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def _tokens(value):
    clean = "".join(c for c in unicodedata.normalize("NFKD", str(value or "").casefold())
                    if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", clean)


def _same_person(bookmaker, player):
    """Full names or surname + exact given-name initials (no surname-only matches)."""
    book, model = _tokens(bookmaker), _tokens(player)
    if not book or not model or len(model) < 2:
        return False
    if book == model:
        return True
    if len(book) < 2:
        return False
    surname = model[-1]
    if book[0] == surname:
        first = book[1:]
    elif book[-1] == surname:
        first = book[:-1]
    else:
        return False
    given = model[:-1]
    return len(first) == len(given) and all(
        b == m or (len(b) == 1 and b == m[0])
        for b, m in zip(first, given)
    )


def _event_identity(event, card):
    book = event.get("players")
    p1, p2 = card.get("player1"), card.get("player2")
    if (not isinstance(book, list) or len(book) != 2
            or not isinstance(p1, dict) or not isinstance(p2, dict)
            or not all(str(p.get("id") or "").strip() and str(p.get("name") or "").strip()
                       for p in (p1, p2))):
        return None
    board = (p1["name"], p2["name"])
    orders = []
    for a, b in ((0, 1), (1, 0)):
        if _same_person(book[0], board[a]) and _same_person(book[1], board[b]):
            orders.append({0: a, 1: b})
    if len(orders) != 1:
        return None
    observed = _stamp(event.get("scheduled_at"))
    scheduled = _stamp(card.get("scheduled_at"))
    if not observed or not scheduled or abs((observed - scheduled).total_seconds()) > 30 * 60:
        return None
    return orders[0]


def _valid_price(value):
    if isinstance(value, bool):
        return False
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(price) and 1.01 <= price <= 100.0


def _date_for_morning(now):
    return now.astimezone(TZ).date().isoformat()


def validated_events(report, *, betting_day, now):
    """Require a same-betting-day pre-start observation; no newer/mixed-day rows."""
    if (not isinstance(report, dict) or report.get("schema") != 1
            or report.get("target_betting_day") != betting_day
            or report.get("source") != "public_fortuna_sk"
            or report.get("status") not in ("audited", "no_exact_aces_market_available")
            or report.get("cdb_writes") != 0 or report.get("published_picks_changed") != 0):
        return []
    captured = _stamp(report.get("captured_at"))
    if not captured or captured > now or now - captured > timedelta(hours=24):
        return []
    accepted = []
    events = report.get("events_in_target_window")
    if not isinstance(events, list) or len(events) > 60:
        return []
    for e in events:
        if not isinstance(e, dict) or e.get("provider") != "fortuna_sk":
            continue
        seen = _stamp(e.get("captured_at"))
        scheduled = _stamp(e.get("scheduled_at"))
        if not seen or not scheduled or seen > now or seen >= scheduled:
            continue
        if now - seen > timedelta(hours=24):
            continue
        local_start = scheduled.astimezone(TZ)
        scheduled_day = (local_start - timedelta(days=1) if local_start.hour < 6
                         else local_start).date().isoformat()
        if scheduled_day != betting_day:
            continue
        if not str(e.get("event_id") or "").startswith("ufo:mtch:"):
            continue
        if not isinstance(e.get("aces_markets"), list):
            continue
        accepted.append(e)
    return accepted


def load_evening_report(*, betting_day, now, repo=DATA_REPO, runner=None):
    """Optional private read; no paid API calls and never a publication blocker."""
    if repo != DATA_REPO or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", betting_day):
        return None, "invalid_source"
    runner = runner or (lambda args: subprocess.check_output(args, timeout=20))
    path = f"repos/{repo}/contents/research/skcz-evening-odds/{betting_day}"
    try:
        index = json.loads(runner(["gh", "api", path]))
        if not isinstance(index, list) or len(index) > 40:
            return None, "missing_or_oversized_directory"
        candidates = [x for x in index if isinstance(x, dict)
                      and re.fullmatch(r"fortuna-\d+\.json", str(x.get("name") or ""))
                      and x.get("type") == "file"]
        # Latest verified run by filename number; same-day files are create-only.
        candidates.sort(key=lambda x: int(x["name"][8:-5]), reverse=True)
        for item in candidates[:5]:
            obj = json.loads(runner(["gh", "api", path + "/" + item["name"]]))
            raw = base64.b64decode(str(obj.get("content") or ""), validate=False)
            if len(raw) > 1_000_000:
                continue
            report = json.loads(raw)
            if validated_events(report, betting_day=betting_day, now=now) or (
                isinstance(report, dict) and report.get("events_in_target_window") == []
                and report.get("status") == "no_exact_aces_market_available"
                and report.get("target_betting_day") == betting_day
                and report.get("source") == "public_fortuna_sk"
                and report.get("cdb_writes") == 0
                and report.get("published_picks_changed") == 0
                and _stamp(report.get("captured_at")) is not None
                and timedelta(0) <= now - _stamp(report.get("captured_at")) <= timedelta(hours=24)
            ):
                return report, "loaded"
        return None, "no_valid_evening_snapshot"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return None, "unavailable:" + type(exc).__name__


def _unique_event(events, card):
    matches = [(e, _event_identity(e, card)) for e in events]
    matches = [(e, order) for e, order in matches if order is not None]
    return matches[0] if len(matches) == 1 else (None, None)


def _bookmaker_fields(card, event, market, price):
    result = deepcopy(card)
    result.update(
        odds=round(float(price), 3),
        price_status="priced_projection",
        provider_id=FORTUNA_PROVIDER_ID,
        captured_at=event["captured_at"],
        odds_source=FORTUNA_SOURCE,
        odds_bookmaker="Fortuna SK",
        odds_provider_event_id=event["event_id"],
        odds_market_name=market["market_name"],
        odds_contract_version="ace_df_real_api_v1"
            if card.get("market") == "aces" else "most_aces_fortuna_v1",
    )
    return result


def attach_prices(ace_picks, most_picks, report, *, now=None, betting_day=None):
    """Price only already selected cards; no new cards or synthetic market lines."""
    now = now or datetime.now(timezone.utc)
    day = betting_day or _date_for_morning(now)
    events = validated_events(report, betting_day=day, now=now)
    from ace_working_odds import local_player_aces_ou
    aces, most = [], []
    matched = {"aces": 0, "most_aces": 0, "eligible_events": len(events),
               "source": "fortuna_sk", "skipped_ambiguous_or_unavailable": 0}
    for row in ace_picks:
        original = deepcopy(row)
        if (not isinstance(row, dict) or row.get("market") != "aces"
                or row.get("odds") is not None or row.get("price_status") != "projection_only"):
            aces.append(original)
            continue
        local = local_player_aces_ou(row)
        event, order = _unique_event(events, row)
        selected = str(row.get("selection_id") or "")
        if not local or event is None or not order or selected not in {
            str((row.get("player1") or {}).get("id") or ""),
            str((row.get("player2") or {}).get("id") or ""),
        }:
            aces.append(original)
            continue
        slot = 0 if str(row["player1"]["id"]) == selected else 1
        source_player = event["players"][next(i for i, s in order.items() if s == slot)]
        matches = []
        for market in event["aces_markets"]:
            if not isinstance(market, dict) or market.get("kind") != "player_aces_ou":
                continue
            for p in market.get("verified_pairs") or []:
                if (isinstance(p, dict) and _same_person(p.get("player"), source_player)
                        and _same_person(p.get("player"), row[f"player{slot+1}"]["name"])
                        and p.get("line") is not None
                        and float(p["line"]) == float(local["market_line"])
                        and _valid_price(p.get("over")) and _valid_price(p.get("under"))):
                    matches.append((market, p))
        if len(matches) == 1:
            market, pair = matches[0]
            updated = _bookmaker_fields(local, event, market, pair["over"])
            aces.append(updated)
            matched["aces"] += 1
        else:
            aces.append(original)
            if matches:
                matched["skipped_ambiguous_or_unavailable"] += 1
    for row in most_picks:
        original = deepcopy(row)
        if (not isinstance(row, dict) or row.get("market") != "most_aces"
                or row.get("price_status") != "projection_only" or row.get("odds") is not None
                or row.get("issued_at") or row.get("publication_status") == "published"
                or row.get("ace_winner_source") == "issued_aces_signal_only"
                or row.get("ace_winner_issued") is False):
            most.append(original)
            continue
        event, order = _unique_event(events, row)
        if event is None or not order:
            most.append(original)
            continue
        selected_id = str(row.get("selection_id") or "")
        slot = (0 if str(row["player1"]["id"]) == selected_id else
                1 if str(row["player2"]["id"]) == selected_id else None)
        if slot is None:
            most.append(original)
            continue
        matches = []
        for market in event["aces_markets"]:
            if not isinstance(market, dict) or market.get("kind") != "most_aces_match":
                continue
            for p in market.get("verified_pairs") or []:
                if not isinstance(p, dict) or p.get("settlement") != "bookmaker_rules_not_yet_verified":
                    continue
                outcomes = p.get("two_way_outcomes")
                if not isinstance(outcomes, list) or len(outcomes) != 2:
                    continue
                if not all(isinstance(o, dict) and _valid_price(o.get("odds")) for o in outcomes):
                    continue
                if not all(_same_person(outcomes[i]["selection"], event["players"][i])
                           for i in (0, 1)):
                    # Bookmaker outcome order is not guaranteed. Try reversed.
                    if not all(_same_person(outcomes[1-i]["selection"], event["players"][i])
                               for i in (0, 1)):
                        continue
                target = [o for o in outcomes if _same_person(o["selection"], row[f"player{slot+1}"]["name"])]
                if len(target) == 1:
                    matches.append((market, target[0]))
        if len(matches) == 1:
            market, choice = matches[0]
            most.append(_bookmaker_fields(original, event, market, choice["odds"]))
            matched["most_aces"] += 1
        else:
            most.append(original)
            if matches:
                matched["skipped_ambiguous_or_unavailable"] += 1
    return aces, most, matched
