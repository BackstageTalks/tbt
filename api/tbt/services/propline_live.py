"""Conservative, bounded PropLine fallback for real pre-match tennis props.

Read-only. No hidden external calls: callers must supply the existing PROPL
secret and an explicit per-refresh event budget. Outcomes from DIFFERENT
bookmakers are never combined into a synthetic two-sided market.
"""
from __future__ import annotations

import math
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone
from typing import Any

from tbt.services.projection_odds import (
    extract_match_total_odds, extract_player_total_ou,
)

BASE = "https://api.prop-line.com/v1"
KEYS = ("totals", "total_games", "total_sets", "player_aces", "player_double_faults")
METRIC = {"totals": "games", "total_games": "games", "total_sets": "sets",
          "player_aces": "aces", "player_double_faults": "double_faults"}
# Shared 1000/day PROPL: four refreshes x (1 board + 2x75) <= 604 calls.
# CLV pilot is capped at 250/day; reserve >=146 for variable/manual demand.
MAX_EVENTS_PER_REFRESH = 75
MIN_PROVIDER_REMAINING = 150


def _name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _when(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _players(row: dict) -> tuple[str, str]:
    p1 = row.get("player1") or {}
    p2 = row.get("player2") or {}
    return str(p1.get("name") or ""), str(p2.get("name") or "")


def _events(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("events", "data", "results"):
            if isinstance(data.get(key), list):
                return _events(data[key])
    raise ValueError("Invalid PropLine events response")


def _markets(data: Any) -> set[str]:
    if isinstance(data, list):
        return {str(m["key"]) for m in data if isinstance(m, dict) and m.get("key")}
    if isinstance(data, dict):
        for key in ("markets", "data", "results"):
            if isinstance(data.get(key), list):
                return _markets(data[key])
    raise ValueError("Invalid PropLine market-list response")


def _price(value: Any) -> float | None:
    """PropLine defaults to AMERICAN odds, unlike Tennis RapidAPI decimals."""
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n):
        return None
    if n <= -100:
        result = 1 + 100 / abs(n)
    elif n >= 100:
        result = 1 + n / 100
    elif 1.01 <= n <= 30:
        result = n  # explicit decimal-format response
    else:
        return None
    return round(result, 6) if 1.01 <= result <= 30 else None


class PropLineClient:
    def __init__(self, key: str, *, max_calls: int, min_remaining: int = MIN_PROVIDER_REMAINING):
        if not key:
            raise ValueError("PROPL secret is absent")
        self.key = key
        self.max_calls = max(0, int(max_calls))
        self.min_remaining = min_remaining
        self.calls = 0
        self.remaining: int | None = None

    def get(self, path: str, params: dict | None = None) -> Any:
        if self.calls >= self.max_calls:
            raise RuntimeError("PropLine local request cap reached")
        if self.remaining is not None and self.remaining < self.min_remaining:
            raise RuntimeError("PropLine daily quota reserve reached")
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={
            "X-API-Key": self.key, "Accept": "application/json",
            "User-Agent": "BlinQ-odds-first/1.0",
        })
        # Count attempted requests, including rejected ones. Never log the key.
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                remaining = response.headers.get("X-Daily-Remaining")
                if remaining is not None:
                    self.remaining = int(remaining)
                return json.load(response)
        except urllib.error.HTTPError as exc:
            remaining = exc.headers.get("X-Daily-Remaining")
            if remaining is not None:
                self.remaining = int(remaining)
            raise RuntimeError(f"PropLine HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise RuntimeError("PropLine request failed") from None


def _initial_last(name: str) -> tuple[str, str] | None:
    """Conservative abbreviated tennis name: 'N. Djokovic' == 'Novak Djokovic'.

    An initial and a surname alone are never enough to match an event: the
    opposing player and tightly compatible scheduled time must also agree.
    """
    words = _name(name).split()
    if len(words) < 2 or len(words[-1]) < 3:
        return None
    if words[0] in {"tbd", "unknown", "winner", "qualifier"}:
        return None
    return words[0][0], words[-1]


def _pair_key(names: tuple[str, str], *, abbreviated: bool = False) -> frozenset | None:
    clean = tuple(_initial_last(name) if abbreviated else _name(name) for name in names)
    if any(not key for key in clean) or clean[0] == clean[1]:
        return None
    return frozenset(clean)


def _match_board_with_diagnostics(
    predictions: list[dict], board: list[dict], now: datetime,
) -> tuple[list[tuple[dict, dict]], dict]:
    """One-to-one, two-player and time-constrained fixture matching.

    Exact full-name matches take precedence. The only fallback is a shared
    initial+last-name key for BOTH players, with a tighter 45-minute start
    tolerance. Ambiguous records on EITHER feed are dropped rather than
    guessed. No bookmaker event can be assigned to two RapidAPI matches.
    """
    singles = []
    for row in predictions:
        p1, p2 = _players(row)
        start = _when(row.get("scheduled_at") or row.get("date"))
        exact = _pair_key((p1, p2))
        if not row.get("event_id") or not exact or not start or start <= now:
            continue
        singles.append((row, exact, _pair_key((p1, p2), abbreviated=True), start))
    targets = []
    invalid = 0
    seen_identical = set()
    for prop in board:
        eid = str(prop.get("id") or "")
        start = _when(prop.get("commence_time"))
        pnames = (str(prop.get("home_team") or ""), str(prop.get("away_team") or ""))
        exact = _pair_key(pnames)
        if not eid.isdigit() or not start or start <= now or not exact:
            invalid += 1
            continue
        signature = (eid, start, exact)
        if signature in seen_identical:
            continue
        seen_identical.add(signature)
        targets.append((prop, exact, _pair_key(pnames, abbreviated=True), start))
    # Resolve against all candidates first so a duplicated event on either
    # provider cannot be accepted based on input order.
    proposals = []
    ambiguous = 0
    unmatched = 0
    matched_full = 0
    matched_abbrev = 0
    for prop, exact, abbreviated, start in targets:
        full = [(row, when) for row, key, _short, when in singles
                if key == exact and abs((start - when).total_seconds()) <= 7200]
        if full:
            candidates = full
            method = "full"
        else:
            candidates = [(row, when) for row, _key, short, when in singles
                          if abbreviated is not None and short == abbreviated
                          and abs((start - when).total_seconds()) <= 2700]
            method = "abbreviated"
        identities = {str(row["event_id"]) for row, _when in candidates}
        if len(identities) != 1:
            if identities:
                ambiguous += 1
            else:
                unmatched += 1
            continue
        row = candidates[0][0]
        proposals.append((row, prop, method))
    rapid_counts: dict[str, int] = {}
    prop_counts: dict[str, int] = {}
    for row, prop, _ in proposals:
        rapid = str(row["event_id"])
        prop_id = str(prop["id"])
        rapid_counts[rapid] = rapid_counts.get(rapid, 0) + 1
        prop_counts[prop_id] = prop_counts.get(prop_id, 0) + 1
    chosen = []
    for row, prop, method in proposals:
        if rapid_counts[str(row["event_id"])] != 1 or prop_counts[str(prop["id"])] != 1:
            ambiguous += 1
            continue
        chosen.append((row, prop))
        if method == "full":
            matched_full += 1
        else:
            matched_abbrev += 1
    chosen.sort(key=lambda pair: (
        0 if str(pair[0].get("tour") or "").upper() in ("ATP", "WTA") else 1,
        _when(pair[0].get("scheduled_at") or pair[0].get("date")),
    ))
    return chosen, {
        "model_upcoming": len(singles), "provider_future_events": len(targets),
        "unusable_provider_events": invalid, "matched_exact": matched_full,
        "matched_abbreviated": matched_abbrev, "unmatched_provider": unmatched,
        "ambiguous_rejected": ambiguous,
    }


def _match_board(predictions: list[dict], board: list[dict], now: datetime) -> list[tuple[dict, dict]]:
    return _match_board_with_diagnostics(predictions, board, now)[0]


def _normalize_book(book: dict, row: dict, missing: set[str]) -> dict[str, dict]:
    """Only full two-way quotes from ONE bookmaker at ONE matching line."""
    result: dict[str, dict] = {}
    p1, p2 = _players(row)
    for market in book.get("markets") or []:
        if not isinstance(market, dict):
            continue
        key = str(market.get("key") or "")
        metric = METRIC.get(key)
        if metric not in missing:
            continue
        groups: dict[tuple[str, float], dict] = {}
        for outcome in market.get("outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            direction = _name(outcome.get("name"))
            if direction not in ("over", "under"):
                continue
            try:
                line = float(outcome.get("point"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(line):
                continue
            price = _price(outcome.get("price"))
            if price is None:
                continue
            player = ""
            if metric in ("aces", "double_faults"):
                subject = _name(outcome.get("description"))
                if subject == _name(p1):
                    player = p1
                elif subject == _name(p2):
                    player = p2
                else:
                    continue
            elif metric == "games" and not 8 <= line <= 80:
                continue
            elif metric == "sets" and not 1.5 <= line <= 5.5:
                continue
            group = groups.setdefault((player, line), {})
            group.setdefault(direction, {"choiceName": direction.title(),
                                         "line": line, "decimalOdds": price,
                                         "playerName": player})
        for (player, line), sides in groups.items():
            if set(sides) != {"over", "under"}:
                continue
            market_name = (
                f"{player} {'Aces' if metric == 'aces' else 'Double Faults'} Total"
                if player else "Total games" if metric == "games" else "Total sets"
            )
            payload = result.setdefault(metric, {"markets": []})
            payload["markets"].append({"name": market_name, "choices": list(sides.values())})
    # Require the SAME bookmaker to offer a complete two-sided exact line.
    for metric, payload in list(result.items()):
        if metric in ("games", "sets") and not extract_match_total_odds(payload, metric):
            result.pop(metric)
        elif metric in ("aces", "double_faults") and not (
            extract_player_total_ou(payload, metric, p1, player_slot=1)
            or extract_player_total_ou(payload, metric, p2, player_slot=2)
        ):
            result.pop(metric)
    return result


def discover_propline_fallback(
    client: PropLineClient, predictions: list[dict], existing: dict[str, set[str]], *,
    now: datetime, max_events: int = MAX_EVENTS_PER_REFRESH,
) -> tuple[dict[str, dict[str, dict]], dict]:
    """Map PropLine event IDs safely to RapidAPI fixtures; return parsed payloads.

    Caller only merges valid missing categories, never PropLine's generic h2h
    into the existing Match Winner cache. API failures fail closed.
    """
    report: dict[str, Any] = {"enabled": True, "calls": 0, "matched_events": 0,
                              "events_queried": 0, "priced_by_market": {
                                  "aces": 0, "double_faults": 0, "sets": 0, "games": 0},
                              "missing_secret": False, "errors": 0,
                              "events_on_board": 0, "events_skipped_no_target_market": 0,
                              "events_with_any_target_market": 0,
                              "advertised_market_keys": {}, "markets_advertised_by_type": {
                                  "aces": 0, "double_faults": 0, "sets": 0, "games": 0},
                              "odds_payload_events": 0, "bookmakers_with_target_market": 0,
                              "events_limited_out": 0,
                              "bookmakers_priced_by_market": {
                                  "aces": {}, "double_faults": {}, "sets": {}, "games": {}},
                              "sample_offers": {
                                  "aces": [], "double_faults": [], "sets": [], "games": []}}
    fetched: dict[str, dict[str, dict]] = {}
    try:
        board = _events(client.get("/sports/tennis/events"))
    except (RuntimeError, ValueError):
        report["errors"] += 1
        report["calls"] = client.calls
        return {}, report
    report["events_on_board"] = len(board)
    matched, match_diagnostics = _match_board_with_diagnostics(predictions, board, now)
    report["matched_events"] = len(matched)
    report["fixture_match_diagnostics"] = match_diagnostics
    report["events_limited_out"] = max(0, len(matched) - max(0, min(MAX_EVENTS_PER_REFRESH, int(max_events))))
    for row, event in matched[:max(0, min(MAX_EVENTS_PER_REFRESH, int(max_events)))]:
        rapid_id, prop_id = str(row["event_id"]), str(event["id"])
        missing = set(("aces", "double_faults", "games", "sets")) - existing.get(rapid_id, set())
        if not missing or client.calls + 2 > client.max_calls:
            continue
        report["events_queried"] += 1
        try:
            available = _markets(client.get(f"/sports/tennis/events/{prop_id}/markets"))
            for market_key in available:
                report["advertised_market_keys"][market_key] = (
                    report["advertised_market_keys"].get(market_key, 0) + 1
                )
            advertised = {METRIC[key] for key in KEYS if key in available and METRIC[key] in missing}
            for market_name in advertised:
                report["markets_advertised_by_type"][market_name] += 1
            wanted = [key for key in KEYS if key in available and METRIC[key] in missing]
            if not wanted:
                report["events_skipped_no_target_market"] += 1
                continue
            report["events_with_any_target_market"] += 1
            payload = client.get(f"/sports/tennis/events/{prop_id}/odds",
                                 {"markets": ",".join(wanted)})
            if not isinstance(payload, dict):
                continue
            report["odds_payload_events"] += 1
            for book in payload.get("bookmakers") or []:
                if not isinstance(book, dict):
                    continue
                parsed = _normalize_book(book, row, missing)
                if parsed:
                    report["bookmakers_with_target_market"] += 1
                for metric, normalized in parsed.items():
                    if metric in fetched.get(rapid_id, {}):
                        continue
                    fetched.setdefault(rapid_id, {})[metric] = {
                        "payload": normalized, "provider_id": 2,
                        "source": "propline", "bookmaker": str(book.get("title") or
                            book.get("key") or book.get("name") or "")[:90],
                        "provider_event_id": prop_id,
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                    }
                    report["priced_by_market"][metric] += 1
                    book_name = fetched[rapid_id][metric]["bookmaker"]
                    by_book = report["bookmakers_priced_by_market"][metric]
                    by_book[book_name] = by_book.get(book_name, 0) + 1
                    samples = report["sample_offers"][metric]
                    if len(samples) < 8:
                        p1, p2 = _players(row)
                        offers = (extract_match_total_odds(normalized, metric)
                                  if metric in ("games", "sets") else
                                  extract_player_total_ou(normalized, metric, p1, player_slot=1)
                                  + extract_player_total_ou(normalized, metric, p2, player_slot=2))
                        if offers:
                            offer = offers[0]
                            samples.append({
                                "provider_event_id": prop_id, "bookmaker": book_name,
                                "player": offer.get("player_name"),
                                "line": offer["line"], "over": offer["over"],
                                "under": offer["under"],
                            })
        except (RuntimeError, ValueError):
            report["errors"] += 1
        if client.remaining is not None and client.remaining < client.min_remaining:
            report["stopped_on_quota_reserve"] = True
            break
    report["calls"] = client.calls
    report["remaining"] = client.remaining
    return fetched, report
