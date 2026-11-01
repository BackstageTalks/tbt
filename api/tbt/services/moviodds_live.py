"""Read-only MoviOdds/bet365 prematch tennis odds fallback.

A single filtered snapshot supplements missing API Pro and PropLine contracts.
The provider's historical archive is queried separately when CLV research needs
it: a live quote is never substituted for a pre-match publication price.
No model/CDB writes, and no guesses on ambiguous fixture identities.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from tbt.services.market_selection import extract_match_winner_odds
from tbt.services.projection_odds import extract_match_total_odds, extract_player_total_ou

BASE_URL = "https://moviodds.com/odds"
# 67 is the live main winner group; 83 is the prematch winner group.
# Only prematch fixtures and prematch quotes are ever eligible for publication.
GROUPS = ("83", "67", "130321", "130324", "130018", "130131")
MAX_RESPONSE_BYTES = 3_000_000
MAX_SNAPSHOT_LAG_SECONDS = 120
MAX_MATCH_TIME_DIFFERENCE_SECONDS = 3600


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if result.tzinfo is None:
        return None
    return result.astimezone(timezone.utc)


def _normal(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _pair(first: Any, second: Any) -> frozenset[str] | None:
    a, b = _normal(first), _normal(second)
    return frozenset((a, b)) if a and b and a != b else None


def _price(quote: dict) -> float | None:
    if quote.get("suspended") is True or str(quote.get("sel_id") or "") in ("", "0"):
        return None
    if str(quote.get("phase") or "prematch").lower() != "prematch":
        return None
    try:
        value = float(quote.get("odds_dec"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 1.001 <= value <= 100 else None


def _line(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or abs(number * 2 - round(number * 2)) > 1e-7:
        return None
    return number


def _valid_group(fixture: dict, group: str, server_time: datetime) -> bool:
    status = (fixture.get("group_status") or {}).get(group)
    if not isinstance(status, dict) or status.get("stale") is True:
        return False
    last = _utc(status.get("polled_at"))
    kickoff = _utc(fixture.get("kickoff_utc"))
    if last is None or kickoff is None:
        return False
    # MoviOdds differentiates quote.ts (last price change) from
    # group_status.polled_at (last confirmation of this exact market).
    freshness = 3600 if (kickoff - server_time).total_seconds() > 72 * 3600 else 1800
    age = (server_time - last).total_seconds()
    return -30 <= age <= freshness


def _fetch_board(*, opener=None) -> dict:
    url = BASE_URL + "?" + urllib.parse.urlencode({
        "sport": "tennis", "groups": ",".join(GROUPS),
    })
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "Accept-Encoding": "gzip",
                      "User-Agent": "BlinQ-MoviOdds-Fallback/1.0"},
    )
    with (opener or urllib.request.urlopen)(request, timeout=10) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("MoviOdds response exceeds safety limit")
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("MoviOdds decompressed response too large")
    result = json.loads(body)
    if not isinstance(result, dict) or not isinstance(result.get("matches"), list):
        raise ValueError("MoviOdds response has no match board")
    return result


def _paired_quotes(quotes: list[dict], *, group: str, metric: str,
                   player: str = "") -> list[dict]:
    # Each pair must have the SAME bookmaker, match, player, market and
    # numeric threshold. Do not derive O/U from 1+, 3+, 5+ ace ladders.
    grouped: dict[float, dict[str, float | None]] = {}
    for quote in quotes:
        if str(quote.get("group_id") or "") != group:
            continue
        direction = str(quote.get("side") or "").strip().lower()
        if direction not in ("over", "under"):
            continue
        value = _price(quote)
        threshold = _line(quote.get("handicap") or quote.get("line"))
        if value is None or threshold is None:
            continue
        if metric == "aces" and (quote.get("line") != "Aces" or not 0.5 <= threshold <= 40.5):
            continue
        if metric == "double_faults" and (
            quote.get("line") != "Double Faults" or not 0.5 <= threshold <= 20.5
        ):
            continue
        if metric == "games" and not 8 <= threshold <= 80:
            continue
        if metric == "sets" and not 1.5 <= threshold <= 5.5:
            continue
        slot = grouped.setdefault(threshold, {"over": None, "under": None})
        # Never arbitrate conflicting prices for the same side and line.
        if slot[direction] is None:
            slot[direction] = value
        elif slot[direction] != value:
            slot[direction] = -1.0
    name = (f"{player} {'Aces' if metric == 'aces' else 'Double Faults'} Total"
            if player else "Total games" if metric == "games" else "Total sets")
    return [{
        "name": name,
        "choices": [
            {"choiceName": "Over", "line": line, "decimalOdds": sides["over"],
             "playerName": player},
            {"choiceName": "Under", "line": line, "decimalOdds": sides["under"],
             "playerName": player},
        ],
    } for line, sides in grouped.items()
        if sides["over"] is not None and sides["under"] is not None
        and sides["over"] > 1 and sides["under"] > 1]


def _normalize_fixture(fixture: dict, row: dict, server_time: datetime) -> dict[str, dict]:
    quotes = [q for q in fixture.get("quotes", []) if isinstance(q, dict)]
    p1 = str((row.get("player1") or {}).get("name") or "")
    p2 = str((row.get("player2") or {}).get("name") or "")
    by_metric: dict[str, dict] = {}

    for group in ("83", "67"):
        if not _valid_group(fixture, group, server_time):
            continue
        pair: dict[str, float] = {}
        invalid = False
        for quote in quotes:
            if str(quote.get("group_id") or "") != group:
                continue
            price = _price(quote)
            if price is None:
                continue
            name = _normal(quote.get("side") or quote.get("label"))
            if name not in (_normal(p1), _normal(p2)):
                # Extra selections (e.g. Draw) change the contract; reject it.
                invalid = True
                break
            if name in pair:
                invalid = True
                break
            pair[name] = price
        if invalid or set(pair) != {_normal(p1), _normal(p2)}:
            continue
        payload = {"markets": [{"name": "Match Winner", "choices": [
            {"choiceName": p1, "decimalOdds": pair[_normal(p1)]},
            {"choiceName": p2, "decimalOdds": pair[_normal(p2)]},
        ]}]}
        if extract_match_winner_odds(payload, p1, p2):
            by_metric["match_winner"] = payload
            break

    for group in ("130321", "130324"):
        if not _valid_group(fixture, group, server_time):
            continue
        player_rows: dict[str, list[dict]] = {p1: [], p2: []}
        for q in quotes:
            if str(q.get("group_id") or "") != group:
                continue
            group_name = str(q.get("group_name") or "")
            suffix = " Total Aces/Double Faults"
            if not group_name.endswith(suffix):
                continue
            found = _normal(group_name[:-len(suffix)])
            for name in (p1, p2):
                if _normal(name) == found:
                    player_rows[name].append(q)
        for metric in ("aces", "double_faults"):
            markets = []
            for player, pq in player_rows.items():
                markets.extend(_paired_quotes(pq, group=group, metric=metric, player=player))
            if markets:
                by_metric.setdefault(metric, {"markets": []})["markets"].extend(markets)

    for group, metric in (("130018", "games"), ("130131", "sets")):
        if not _valid_group(fixture, group, server_time):
            continue
        markets = _paired_quotes(quotes, group=group, metric=metric)
        if markets:
            by_metric[metric] = {"markets": markets}

    # Reuse existing strict market parsers as a second independent check.
    for metric, payload in list(by_metric.items()):
        if metric in ("aces", "double_faults") and not (
            extract_player_total_ou(payload, metric, p1, player_slot=1)
            or extract_player_total_ou(payload, metric, p2, player_slot=2)
        ):
            by_metric.pop(metric)
        elif metric in ("games", "sets") and not extract_match_total_odds(payload, metric):
            by_metric.pop(metric)
    return by_metric


def discover_moviodds_fallback(
    predictions: list[dict], existing: dict[str, set[str]], *,
    now: datetime, board: dict | None = None, opener=None,
) -> tuple[dict[str, dict[str, dict]], dict]:
    """Find one-to-one, pre-match quotes for yet-unpriced contracts only.

    `board` is an injected snapshot for deterministic, network-free tests.
    No CDB writes, no live prices, no unverified alias matching.
    """
    report = {
        "enabled": True, "requests": 0, "matches_on_board": 0,
        "matched": 0, "ambiguous": 0, "skipped_stale_or_no_market": 0,
        "priced_by_market": {m: 0 for m in
                            ("match_winner", "aces", "double_faults", "games", "sets")},
        "errors": 0, "source": "moviodds", "bookmaker": "bet365",
        "fallback_order": "api_pro_then_propline_then_moviodds",
    }
    now_utc = _utc(now)
    if now_utc is None:
        report["errors"] += 1
        return {}, report
    if board is None:
        try:
            board = _fetch_board(opener=opener)
            report["requests"] = 1
        except (OSError, ValueError, json.JSONDecodeError, UnicodeError):
            report["errors"] += 1
            return {}, report
    if not isinstance(board, dict) or board.get("warming") is True:
        report["errors"] += 1
        return {}, report
    server = _utc(board.get("server_time") or board.get("generated_at"))
    if server is None or abs((now_utc - server).total_seconds()) > MAX_SNAPSHOT_LAG_SECONDS:
        report["errors"] += 1
        return {}, report

    fixtures = board.get("matches")
    if not isinstance(fixtures, list):
        report["errors"] += 1
        return {}, report
    report["matches_on_board"] = len(fixtures)
    targets: dict[frozenset[str], list[tuple[str, datetime]]] = {}
    for row in predictions:
        if row.get("prediction_family") == "doubles":
            continue
        event_id = str(row.get("event_id") or "")
        p1 = (row.get("player1") or {}).get("name")
        p2 = (row.get("player2") or {}).get("name")
        names = _pair(p1, p2)
        start = _utc(row.get("scheduled_at") or row.get("date"))
        if event_id and names and start and start > now_utc:
            targets.setdefault(names, []).append((event_id, start))

    proposals: list[tuple[str, dict, dict]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict) or fixture.get("in_play") is not False:
            continue
        start = _utc(fixture.get("kickoff_utc"))
        names = _pair(fixture.get("home"), fixture.get("away"))
        if start is None or start <= now_utc or names is None:
            continue
        possible = [(eid, when) for eid, when in targets.get(names, ())
                    if abs((when - start).total_seconds()) <= MAX_MATCH_TIME_DIFFERENCE_SECONDS]
        if len(possible) != 1:
            if possible:
                report["ambiguous"] += 1
            continue
        # Names are orientation-independent; _normalize_fixture checks every
        # outcome against the correct player name before attaching prices.
        eid = possible[0][0]
        row = next((r for r in predictions if str(r.get("event_id") or "") == eid), None)
        if row is not None:
            proposals.append((eid, row, fixture))
    counts: dict[str, int] = {}
    ids: dict[str, int] = {}
    for eid, _row, fixture in proposals:
        counts[eid] = counts.get(eid, 0) + 1
        fid = str(fixture.get("id") or "")
        ids[fid] = ids.get(fid, 0) + 1

    collected: dict[str, dict[str, dict]] = {}
    for eid, row, fixture in proposals:
        fid = str(fixture.get("id") or "")
        if not fid or counts[eid] != 1 or ids[fid] != 1:
            report["ambiguous"] += 1
            continue
        report["matched"] += 1
        source = _normalize_fixture(fixture, row, server)
        missing = source.keys() - existing.get(eid, set())
        if not missing:
            report["skipped_stale_or_no_market"] += 1
        for metric in missing:
            # Exact provenance is part of the published card's immutable price.
            collected.setdefault(eid, {})[metric] = {
                "payload": source[metric], "provider_id": 3,
                "source": "moviodds", "bookmaker": "bet365",
                "provider_event_id": fid,
                "captured_at": now_utc.isoformat(),
            }
            report["priced_by_market"][metric] += 1
    return collected, report
