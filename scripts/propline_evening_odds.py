"""Read-only PropLine free tennis ace quotes in the versioned evening quote archive schema.

Only genuine bookmaker N+ ace milestones and complete same-book player O/U
pairs are sportsbook quotes. DFS pick'em multipliers are research-only.
The source is NEVER permission to change issued picks or write canonical CDB.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bratislava")
API = "https://api.prop-line.com/v1"
ODDS_PATH = "/sports/tennis/odds"
QUERY = {"markets": "player_aces,total_aces"}
SOURCE_URL = API + ODDS_PATH + "?" + urlencode(QUERY)
DFS = frozenset(("dabble", "sleeper", "prizepicks", "underdog",
                 "parlayplay", "draftkings_pick6"))
MIN_REMAINING = 150
MAX_RESPONSE = 20_000_000
MILESTONE = re.compile(r"^([1-9][0-9]*)\s*\+\s*aces$", re.I)
MOST = re.compile(r"(?:^|[_\\s-])(most|more|higher|superiority|winner)(?:$|[_\\s-])", re.I)


def _stamp(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _norm(value):
    plain = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", plain.casefold()))


def _price(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        if not math.isfinite(value):
            return None
        if value <= -100:
            decimal = 1.0 + 100.0 / abs(value)
        elif value >= 100:
            decimal = 1.0 + value / 100.0
        elif 1.01 <= value <= 30:
            decimal = value
        else:
            return None
        return round(decimal, 6) if 1.01 <= decimal <= 100 else None
    except (TypeError, ValueError, OverflowError):
        return None


def fetch():
    key = os.environ.get("PROPL")
    if not key:
        raise RuntimeError("existing_prop_line_secret_unavailable")
    req = Request(SOURCE_URL, headers={
        "X-API-Key": key, "Accept": "application/json",
        "User-Agent": "BlinQ-evening-propline-archive/1.0"})
    try:
        with urlopen(req, timeout=30) as response:
            remaining = response.headers.get("X-Daily-Remaining")
            raw = response.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        raise RuntimeError("prop_line_http_" + str(exc.code)) from None
    except (OSError, URLError, TimeoutError):
        raise RuntimeError("prop_line_network_unavailable") from None
    if len(raw) > MAX_RESPONSE:
        raise RuntimeError("prop_line_response_oversized")
    if remaining is None:
        raise RuntimeError("prop_line_daily_quota_header_missing")
    try:
        left = int(remaining)
    except ValueError:
        raise RuntimeError("prop_line_daily_quota_header_invalid") from None
    if left < MIN_REMAINING:
        raise RuntimeError("prop_line_daily_reserve_reached")
    try:
        return json.loads(raw), left
    except ValueError:
        raise RuntimeError("prop_line_invalid_json") from None


def _events(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("events", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("prop_line_missing_event_array")


def _tournament(event):
    value = (event.get("sport_title") or event.get("league") or
             event.get("tournament") or event.get("sport_key") or "")
    return str(value)[:140]


def _single_book_quotes(event, book):
    """One bookmaker market at a time: no cross-book or cross-line joins."""
    name = str(book.get("key") or book.get("title") or "").strip()
    if not name:
        return [], []
    groups = []
    labels = []
    for market in book.get("markets") or []:
        if not isinstance(market, dict):
            continue
        key = str(market.get("key") or "")
        labels.append(key)
        if key not in ("player_aces", "total_aces") and not (
                "ace" in key.lower() and MOST.search(key)):
            continue
        outcomes = market.get("outcomes") or []
        if not isinstance(outcomes, list):
            continue
        market_id = str(market.get("id") or "").strip() or (
            str(event["id"]) + ":" + name + ":" + key)
        if key == "player_aces":
            milestones = []
            groups_ou = defaultdict(list)
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                player = str(outcome.get("description") or "").strip()
                if _norm(player) not in {_norm(event.get("home_team")),
                                         _norm(event.get("away_team"))}:
                    continue
                decimal = _price(outcome.get("price"))
                if decimal is None:
                    continue
                title = str(outcome.get("name") or "").strip()
                hit = MILESTONE.fullmatch(title)
                if hit and name.casefold() not in DFS:
                    threshold = int(hit.group(1))
                    milestones.append({
                        "market_id": market_id, "player": player,
                        "threshold": threshold, "equivalent_over_line": threshold - 0.5,
                        "odds": decimal, "source_selection": title,
                        "raw_american": outcome.get("price"),
                        "bookmaker": name, "last_update": market.get("last_update"),
                        "settlement": "full_match_threshold_research_only",
                    })
                if title.lower() in ("over", "under") and outcome.get("point") is not None:
                    try:
                        line = float(outcome["point"])
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(line) and line >= 0:
                        groups_ou[(player, line)].append((title.lower(), decimal))
            if milestones:
                groups.append({
                    "kind": "player_aces_milestone", "market_name": key,
                    "bookmaker": name, "market_id": market_id,
                    "outcomes_observed": len(outcomes), "verified_pairs": [],
                    "verified_single_prices": milestones,
                    "last_update": market.get("last_update"),
                })
            for (player, line), outcomes_at_line in groups_ou.items():
                sides = {label: value for label, value in outcomes_at_line}
                if (len(outcomes_at_line) != 2 or
                        {label for label, _ in outcomes_at_line} != {"over", "under"}):
                    continue
                pair = {"market_id": market_id, "player": player, "line": line,
                        "over": sides["over"], "under": sides["under"],
                        "bookmaker": name, "last_update": market.get("last_update")}
                kind = ("dfs_pickem_player_aces_ou" if name.casefold() in DFS
                        else "player_aces_ou")
                groups.append({
                    "kind": kind, "market_name": key, "bookmaker": name,
                    "market_id": market_id, "outcomes_observed": len(outcomes),
                    "verified_pairs": [] if kind.startswith("dfs_") else [pair],
                    "research_pairs": [pair] if kind.startswith("dfs_") else [],
                    "last_update": market.get("last_update"),
                })
        elif ("ace" in key.lower() and MOST.search(key)
              and not re.search(r"(?:^|[_\\s-])(set|sets|period|tiebreak|tie_break)(?:$|[_\\s-])", key, re.I)):
            # A confirmed two-way sportsbook price requires two named players.
            named = [o for o in outcomes if isinstance(o, dict)]
            names = {_norm(o.get("name")) for o in named}
            players = {_norm(event.get("home_team")), _norm(event.get("away_team"))}
            if (name.casefold() in DFS or len(named) != 2 or
                    len(players) != 2 or names != players or
                    not all(_price(o.get("price")) for o in named)):
                continue
            groups.append({
                "kind": "most_aces_match", "market_name": key, "bookmaker": name,
                "market_id": market_id, "outcomes_observed": 2,
                "verified_pairs": [{
                    "market_id": market_id,
                    "bookmaker": name,
                    "settlement": "bookmaker_rules_not_yet_verified",
                    "two_way_outcomes": [
                        {"selection": o["name"], "odds": _price(o["price"]),
                         "market_id": market_id}
                        for o in named
                    ],
                }],
                "last_update": market.get("last_update"),
            })
    return groups, labels


def collect(target_day, *, max_events=0, allow_same_day=False,
            now=None, get=fetch):
    now = now or datetime.now(timezone.utc)
    start = datetime.combine(target_day, time(6), TZ).astimezone(timezone.utc)
    end = datetime.combine(target_day + timedelta(days=1), time(6), TZ).astimezone(timezone.utc)
    if now >= end:
        raise ValueError("target betting day already passed")
    if now >= start and not allow_same_day:
        raise ValueError("same day requires explicit research opt-in")
    if max_events < 0:
        raise ValueError("max_events must be >= 0 (0 means all provider events)")
    payload, remaining = get()
    entries = _events(payload)
    valid = [e for e in entries if isinstance(e, dict) and
             str(e.get("id") or "").isdigit() and
             str(e.get("home_team") or "").strip() and
             str(e.get("away_team") or "").strip()]
    # Provider order is preserved so a rerun remains deterministic for fixed data.
    selected = valid if max_events == 0 else valid[:max_events]
    report = {
        "schema": 1, "status": "audited", "source": "propline_free",
        "mode": "read_only_evening_aces",
        "target_betting_day": target_day.isoformat(),
        "captured_at": now.isoformat(), "target_start": start.isoformat(),
        "target_end": end.isoformat(), "candidate_urls": len(valid),
        "catalog_pages_scanned": 0, "catalog_errors": [],
        "coverage_truncated": bool(max_events and len(valid) > max_events),
        "candidate_tournaments": len({_tournament(e) for e in valid if _tournament(e)}),
        "probed_tournaments": len({_tournament(e) for e in selected if _tournament(e)}),
        "probed_urls": len(selected),
        "candidate_events": len(valid), "probed_events": len(selected),
        "provider_remaining": remaining,
        "provider_requests": 1, "provider_paid_calls": 0,
        "events_in_target_window": [],
        "out_of_target_window_events": 0,
        "already_started_target_events": 0,
        "market_labels_observed_sample": [],
        "prematch_aces_market_diagnostics": [],
        "observed_prematch_priced_events": [],
        "observed_prematch_priced_pairs": 0,
        "observed_priced_pairs_outside_target": 0,
        "observed_prematch_priced_singles": 0,
        "observed_priced_singles_outside_target": 0,
        "errors": [], "cdb_writes": 0, "published_picks_changed": 0,
    }
    for event in selected:
        scheduled = _stamp(event.get("commence_time") or event.get("start_time"))
        if scheduled is None:
            report["errors"].append({"event_id": str(event["id"]),
                                     "error": "invalid_event_start"})
            continue
        if _norm(event["home_team"]) == _norm(event["away_team"]):
            report["errors"].append({"event_id": str(event["id"]),
                                     "error": "ambiguous_participants"})
            continue
        future = scheduled > now
        in_target = start <= scheduled < end
        if not future:
            if in_target:
                report["already_started_target_events"] += 1
            else:
                report["out_of_target_window_events"] += 1
            continue
        groups, labels = [], []
        for book in event.get("bookmakers") or []:
            if isinstance(book, dict):
                pieces, names = _single_book_quotes(event, book)
                groups.extend(pieces)
                labels.extend(names)
        observed = report["market_labels_observed_sample"]
        for label in labels:
            if label not in observed and len(observed) < 80:
                observed.append(label)
        raw = json.dumps(event, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        item = {
            "provider": "propline", "event_id": str(event["id"]),
            "players": [str(event["home_team"]), str(event["away_team"])],
            "scheduled_at": scheduled.isoformat(),
            "captured_at": now.isoformat(),
            "source_url": SOURCE_URL,
            "source_sha256": sha256(raw).hexdigest(),
            "market_groups_seen": len(labels),
            "market_group_titles_sample": list(dict.fromkeys(labels))[:80],
            "aces_markets": groups,
            # Preserve native provider evidence for contract review and future
            # parser improvements; never convert into a canonical CDB write.
            "provider_raw_event": event,
        }
        exact = sum(len(m["verified_pairs"]) for m in groups)
        singles = sum(len(m.get("verified_single_prices") or []) for m in groups)
        if exact or singles:
            local = scheduled.astimezone(TZ)
            betting = (local - timedelta(days=1) if local.hour < 6
                       else local).date().isoformat()
            report["observed_prematch_priced_events"].append({
                **item, "event_betting_day": betting,
            })
            report["observed_prematch_priced_pairs"] += exact
            report["observed_prematch_priced_singles"] += singles
            if not in_target:
                report["observed_priced_pairs_outside_target"] += exact
                report["observed_priced_singles_outside_target"] += singles
        if in_target:
            report["events_in_target_window"].append(item)
        else:
            report["out_of_target_window_events"] += 1
    report["exact_aces_pairs"] = sum(
        len(m["verified_pairs"]) for e in report["events_in_target_window"]
        for m in e["aces_markets"])
    report["aces_market_groups"] = sum(
        len(e["aces_markets"]) for e in report["events_in_target_window"])
    report["milestone_quotes"] = sum(
        len(m.get("verified_single_prices") or [])
        for e in report["events_in_target_window"] for m in e["aces_markets"])
    report["dfs_pairs"] = sum(
        len(m.get("research_pairs") or [])
        for e in report["events_in_target_window"] for m in e["aces_markets"])
    if not selected:
        report["status"] = "no_exact_aces_market_available"
    elif not (report["exact_aces_pairs"] or report["milestone_quotes"]):
        report["status"] = "no_exact_aces_market_available"
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-day", type=date.fromisoformat, required=True)
    p.add_argument("--max-events", type=int, default=0,
                   help="0 = all events returned in one API response")
    p.add_argument("--allow-same-day", action="store_true")
    p.add_argument("--out", default="reports/propline-evening/odds.json")
    args = p.parse_args()
    report = collect(args.target_day, max_events=args.max_events,
                     allow_same_day=args.allow_same_day)
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "source", "status", "target_betting_day", "probed_events",
        "events_in_target_window", "milestone_quotes", "exact_aces_pairs",
        "dfs_pairs", "provider_remaining", "cdb_writes") if k !=
        "events_in_target_window"} | {
            "eligible_events": len(report["events_in_target_window"]),
        }, sort_keys=True))


if __name__ == "__main__":
    main()
