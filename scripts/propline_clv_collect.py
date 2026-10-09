#!/usr/bin/env python3
"""Read-only PropLine snapshots for a simulated CLV research pilot.

GitHub Actions writes isolated gzip snapshots to the private tbt-data repository.
No orders, bets, predictions, UI updates, or production data mutations.
"""
import base64
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from release_store import ReleaseStore

API = "https://api.prop-line.com/v1"
GH_API = "https://api.github.com"
DATA_REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
ROOT = "research/propline_clv"
PROPL = os.getenv("PROPL", "").strip()
GH_TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "").strip()
MAX_EVENTS = max(1, min(12, int(os.getenv("CLV_EVENTS_PER_RUN", "12"))))
DAILY_LIMIT = 250  # shared 1000/day: reserve up to 604 for 4x75 live refreshes
MIN_PROVIDER_REMAINING = 150
MARKETS = ("h2h", "spreads", "totals", "total_games", "total_sets",
           "total_tiebreaks", "player_aces", "player_double_faults",
           "total_aces", "player_games_won")
if not PROPL or not GH_TOKEN:
    sys.exit("Missing PROPL or TBT_DATA_GH_TOKEN")
quota = {}
api_calls = 0

def request_json(url, headers, method="GET", payload=None, missing_ok=False):
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            for header in ("X-Daily-Limit", "X-Daily-Used", "X-Daily-Remaining"):
                if response.headers.get(header):
                    quota[header] = response.headers[header]
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        # Never log secret-bearing URLs, response bodies or request headers.
        raise RuntimeError(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).path}") from None
    except urllib.error.URLError:
        raise RuntimeError("Provider/network request failed") from None

def prop(path, params=None):
    global api_calls
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        return request_json(url, {"X-API-Key": PROPL, "Accept": "application/json",
                                  "User-Agent": "BlinQ-research-CLV/1.0"})
    finally:
        api_calls += 1

def github(path, method="GET", data=None, missing_ok=False):
    url = GH_API + "/repos/" + DATA_REPO + "/contents/" + path
    return request_json(url, {"Authorization": "Bearer " + GH_TOKEN,
                              "Accept": "application/vnd.github+json",
                              "Content-Type": "application/json",
                              "X-GitHub-Api-Version": "2022-11-28"},
                        method, json.dumps(data).encode() if data is not None else None,
                        missing_ok)

def unpack(data, keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError("Unexpected events/markets response shape")

def parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None

def norm_name(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii").lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


def player_pair(a, b):
    values = sorted((norm_name(a), norm_name(b)))
    return tuple(values) if all(values) else None


def blinq_priority_pairs(now):
    """Read current offer and rank pairs for CLV capture; no provider requests.

    TOP gets first claim on the tiny 12-event CLV sample, followed by Value,
    then Short Odds/other published markets. Lower numeric values are stronger.
    """
    directory = Path(".cache/tbt/propline-clv-predictions")
    try:
        store = ReleaseStore(DATA_REPO, "tbt-predictions-v1", directory)
        if "daily_offer_snapshot.json" not in store._asset_names():
            return {}
        store.download(
            extra_names=("daily_offer_snapshot.json",),
            required_names=("daily_offer_snapshot.json",),
        )
        payload = json.loads(
            (directory / "daily_offer_snapshot.json").read_text(encoding="utf-8")
        )
    except Exception:
        return {}

    pairs = {}
    if not isinstance(payload, dict):
        return pairs
    section_priority = {
        "top_daily_picks": 0,
        "top200_picks": 0,
        "value_picks": 1,
        "prime_picks": 2,
        "doubles_picks": 2,
        "ace_picks": 2,
        "sg_picks": 2,
    }
    for section, rows in payload.items():
        if not isinstance(rows, list):
            continue
        priority = section_priority.get(section, 3)
        for row in rows:
            if not isinstance(row, dict):
                continue
            p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
            p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
            pair = player_pair(p1.get("name"), p2.get("name"))
            kickoff = parse_time(row.get("scheduled_at"))
            if pair is None or kickoff is None:
                continue
            hours = (kickoff - now).total_seconds() / 3600
            if 0 < hours <= 48:
                pairs[pair] = min(priority, pairs.get(pair, priority))
    return pairs


def pick_events(events, now, priority_pairs=()):
    buckets = [[], [], [], []]
    all_items = []
    if isinstance(priority_pairs, dict):
        pair_priority = dict(priority_pairs)
    else:
        pair_priority = {pair: 0 for pair in set(priority_pairs or ())}
    for event in events:
        if not isinstance(event, dict):
            continue
        kickoff = parse_time(event.get("commence_time"))
        event_id = str(event.get("id") or "")
        if kickoff is None or not event_id.isdigit():
            continue
        hours = (kickoff - now).total_seconds() / 3600
        if not 0 < hours <= 48:
            continue
        pair = player_pair(event.get("home_team"), event.get("away_team"))
        priority = pair_priority.get(pair, 4)
        tier = 0 if any(word in str(event).lower() for word in
                        ('"atp"', '"wta"', 'atp ', 'wta ')) else 1
        bucket_idx = 0 if hours <= 3 else 1 if hours <= 12 else 2 if hours <= 24 else 3
        item = (priority, tier, kickoff, event_id, event)
        buckets[bucket_idx].append(item)
        all_items.append(item)

    for bucket in buckets:
        bucket.sort(key=lambda item: (item[0], item[1], item[2]))

    # Published/current BlinQ pairs always get first claim on the bounded budget.
    # Within them, TOP (0) precedes Value (1) and the rest of the offer (2).
    selected = sorted(
        (item for item in all_items if item[0] < 4),
        key=lambda item: (item[0], item[2], item[1]),
    )[:MAX_EVENTS]
    used = {item[3] for item in selected}

    # Then preserve timing diversity so we capture early and near-start prices.
    for bucket in buckets:
        for item in bucket:
            if len(selected) >= MAX_EVENTS:
                break
            if item[3] not in used:
                selected.append(item)
                used.add(item[3])

    if len(selected) < MAX_EVENTS:
        rest = sorted(
            (item for item in all_items if item[3] not in used),
            key=lambda item: (item[0], item[1], item[2]),
        )
        selected.extend(rest[:MAX_EVENTS-len(selected)])
    return selected[:MAX_EVENTS], len(all_items)

def today_usage(folder):
    entries = github(folder, missing_ok=True) or []
    total = 0
    if not isinstance(entries, list):
        raise ValueError("Unexpected GitHub research folder response")
    for entry in entries:
        filename = entry.get("name") or ""
        if filename.endswith(".json.gz"):
            try:
                total += int(filename.split("-calls-")[1].split(".")[0])
            except (IndexError, ValueError):
                raise RuntimeError("Unrecognized existing CLV snapshot filename") from None
    return total

def _git_blob_sha(payload):
    header = f"blob {len(payload)}\\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def save_snapshot(folder, record):
    """Persist once to the private research tree, with an artifact-safe fallback.

    The local gzip is created before the first GitHub mutation. A transient or
    ambiguous 5xx therefore cannot destroy the paid snapshot. After a failed
    PUT, the exact Git blob SHA is read back before retrying, so an ambiguous
    success is never uploaded twice under a different identity.
    """
    now = datetime.now(timezone.utc)
    run_id = os.getenv("GITHUB_RUN_ID") or str(int(time.time()))
    name = now.strftime("%H%M%S") + "-" + run_id + "-calls-" + str(api_calls) + ".json.gz"
    payload = gzip.compress(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    local = Path("reports") / "propline_clv_snapshot.json.gz"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(payload)

    path = folder + "/" + name
    expected_sha = _git_blob_sha(payload)
    encoded = base64.b64encode(payload).decode("ascii")
    last_error = None
    for attempt in range(1, 6):
        try:
            github(
                path,
                method="PUT",
                data={
                    "message": "research: isolated PropLine CLV snapshots",
                    "content": encoded,
                },
            )
            return path, str(local), attempt
        except RuntimeError as exc:
            last_error = exc
            # A gateway may return 5xx after GitHub committed the blob. Verify
            # exact content before retrying rather than creating uncertainty.
            try:
                existing = github(path, missing_ok=True)
            except RuntimeError:
                existing = None
            if (
                isinstance(existing, dict)
                and str(existing.get("sha") or "") == expected_sha
                and int(existing.get("size") or -1) == len(payload)
            ):
                return path, str(local), attempt
            if attempt < 5:
                time.sleep(2 ** attempt)
    raise RuntimeError(
        "GitHub CLV persistence failed after 5 verified attempts; "
        f"local artifact preserved at {local}: {last_error}"
    )

def main():
    now = datetime.now(timezone.utc)
    folder = ROOT + "/" + now.strftime("%Y-%m-%d")
    already = today_usage(folder)
    remaining = DAILY_LIMIT - already
    report = {"schema": 1, "captured_at": now.isoformat(), "api_calls": 0,
              "previous_calls_today": already, "quota": {}, "events": [],
              "window_hours": 48, "research_only": True}
    if remaining < 3:
        report["status"] = "Daily local research budget exhausted"
    else:
        try:
            priority_pairs = blinq_priority_pairs(now)
            events = unpack(prop("/sports/tennis/events"), ("events", "data", "results"))
            selected, eligible = pick_events(events, now, priority_pairs)
            report["board_events"] = len(events)
            report["eligible_upcoming"] = eligible
            report["blinq_priority_pairs"] = len(priority_pairs)
            report["selected_blinq_matches"] = sum(item[0] < 4 for item in selected)
            report["selected_top_matches"] = sum(item[0] == 0 for item in selected)
            report["selected_value_matches"] = sum(item[0] == 1 for item in selected)
            # 2 calls/event for discovery + priced lines. No retries.
            for priority, _, kickoff, event_id, event in selected[:min(MAX_EVENTS, (remaining - api_calls)//2)]:
                if int(quota.get("X-Daily-Remaining", "9999")) < MIN_PROVIDER_REMAINING:
                    report["status"] = "Provider quota reserve reached"
                    break
                row = {"event_id": event_id, "commence_time": kickoff.isoformat(),
                       "blinq_priority": priority == 0,
                       "home_team": event.get("home_team"), "away_team": event.get("away_team"),
                       "tournament": event.get("tournament_name") or event.get("tournament"),
                       "captured_at": datetime.now(timezone.utc).isoformat(),
                       "available_markets": [], "bookmakers": []}
                try:
                    discovery = unpack(prop(f"/sports/tennis/events/{event_id}/markets"),
                                       ("markets", "data", "results"))
                    row["available_markets"] = sorted(
                        {m["key"] for m in discovery if isinstance(m, dict) and m.get("key")})
                    wanted = [name for name in MARKETS if name in row["available_markets"]]
                    if wanted:
                        odds = prop(f"/sports/tennis/events/{event_id}/odds",
                                    {"markets": ",".join(wanted)})
                        row["bookmakers"] = odds.get("bookmakers", []) if isinstance(odds, dict) else []
                except (RuntimeError, ValueError) as exc:
                    row["error"] = str(exc)
                report["events"].append(row)
                time.sleep(0.15)
        except (RuntimeError, ValueError) as exc:
            report["error"] = str(exc)
    report["api_calls"] = api_calls
    report["quota"] = dict(quota)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/propline_clv_snapshot.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # Always create a local gzip before attempting the private permanent write.
    # Actions uploads it even if GitHub Contents is temporarily unavailable.
    try:
        path, local_path, attempts = save_snapshot(folder, report)
        report["persistence"] = {
            "status": "tbt_data_verified",
            "path": path,
            "attempts": attempts,
            "local_artifact": local_path,
        }
    except RuntimeError as exc:
        report["persistence"] = {
            "status": "artifact_only",
            "local_artifact": "reports/propline_clv_snapshot.json.gz",
            "error": str(exc),
        }
        Path("reports/propline_clv_snapshot.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        raise
    Path("reports/propline_clv_snapshot.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"CLV snapshot: {len(report['events'])} events, {api_calls} calls, "
          f"daily local calls={already+api_calls}/{DAILY_LIMIT}; "
          f"status={report.get('status') or 'ok'}, archived {path}")
    if "error" in report:
        raise RuntimeError(report["error"])

if __name__ == "__main__":
    main()
