#!/usr/bin/env python3
"""Research-only PropLine closeout (external dispatch, no cron).

Collection contract:
  1) All future tennis events with complete numeric IDs; no identity guessing.
  2) Discover markets per event; pull exactly one all-relevant-markets odds snapshot.
  3) Prioritize niche priced tennis props not covered as such by Tennis API PRO.
     Retain the existing double-fault/ace/regular markets as fallback.
  4) Preserve unmodified provider payload + UTC capture time + provider event ID.
  5) Flush immutable batches every 25 attempted requests; read back blob SHA/size.
  6) Recover final recent score-linked stats first; then historical player
     logs for actual 2026 CDB gaps. Preserve ≥50 calls for existing niche odds.
  7) Separate exact-linking, single-writer, full-year independent readback
     authorizes additive CDB imports in the SAME nighttime workflow.
  8) Never train, promote or touch daytime CLV workflows.
"""
import base64
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from tbt.data.offline_odds import norm_text

API = "https://api.prop-line.com/v1"
REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
ROOT = "research/propline_closeout"
KEY = os.getenv("PROPL", "")
TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "")
MAX_CALLS = min(750, max(0, int(os.getenv("CLOSEOUT_MAX_REQUESTS", "750"))))
BATCH_SIZE = 25
# Night-only research: additional priced player and match totals, which
# Tennis API PRO's historical match stats do not supply as bookmaker lines.
# Market discovery must advertise a key before any odds request includes it.
SPECIAL_MARKETS = ("player_break_points_won", "total_tiebreaks", "total_aces",
                   "player_games_won")
MARKETS = SPECIAL_MARKETS + ("player_double_faults", "player_aces", "h2h",
                             "total_games", "totals", "total_sets", "spreads")


def odds_priority(market_keys):
    """Use scarce night closeout odds requests on rarer priced props first."""
    priority = (
        *SPECIAL_MARKETS, "player_double_faults", "player_aces",
        "h2h", "total_games", "totals", "total_sets", "spreads",
    )
    for index, key in enumerate(priority):
        if key in market_keys:
            return index
    return len(priority)

# Only the 23:00 closeout probes player game logs; daytime CLV is separate.
# The 2026 API PRO audit left many matches unavailable, especially Aces/DF.
# PropLine advertises up to 100 finished player games in a single FREE call,
# but tennis serve-detail coverage is explicitly thin. Research first; only
# an independent exact CDB gap comparison may authorize later import.
PLAYER_GAMES_PROBE_MAX = 16  # Offline compatibility; active night reads exact CDB gaps
NIGHTLY_GAP_PLAYER_MAX = 600
NIGHTLY_ODDS_RESERVE = 50
PLAYER_GAMES_LIMIT = 100
PLAYER_STATS_FOCUS = ("aces", "dblfaults", "breakpts", "breakpts_w",
                      "tiebreaks", "tiebreaks_w", "total_games", "sets_won",
                      "games_w", "sets_w", "matches_w", "opp_aces",
                      "opp_dblfaults", "opp_breakpts", "opp_breakpts_w",
                      "set_1_games", "set_2_games", "set_3_games",
                      "set_4_games", "set_5_games")
RECENT_SCORES_DAYS = 3


class OptionalStatsAccessUnavailable(Exception):
    """Optional free-player-game endpoint unavailable; continue normal odds."""


def select_player_game_targets(future, limit=PLAYER_GAMES_PROBE_MAX):
    """Distinct single-player names from already-fetched upcoming ATP/WTA slate."""
    seen = set()
    selected = []
    for _kickoff, event in future:
        tour = str(event.get("tour") or "").strip().upper()
        if tour not in {"ATP", "WTA"}:
            continue
        # A doubles fixture can contain one pair and one misleading plain name.
        # Skip the whole fixture rather than querying a pseudo-player.
        if any(marker in str(event.get(side) or "")
               for side in ("home_team", "away_team")
               for marker in ("/", " & ", " + ")):
            continue
        for field in ("home_team", "away_team"):
            name = str(event.get(field) or "").strip()
            # Do not look up doubles pairs or guessed/corrupted player identities.
            if (len(name) < 5 or len(name) > 100 or "/" in name
                    or " & " in name or " + " in name or "," in name):
                continue
            norm = " ".join(name.casefold().split())
            if norm not in seen:
                seen.add(norm)
                selected.append(name)
            if len(selected) >= limit:
                return selected
    return selected


def summarize_player_games(payload):
    """Diagnostic only: counts raw useful tennis stats, NOT new CDB cells."""
    games = payload.get("games") if isinstance(payload, dict) else None
    if not isinstance(games, list):
        return {"response_shape_valid": False, "games": 0,
                "completed_with_focus": 0, "focus_fields": {}}
    field_counts = {key: 0 for key in PLAYER_STATS_FOCUS}
    completed = 0
    for item in games:
        if not isinstance(item, dict) or item.get("status") != "final":
            continue
        stats = item.get("stats")
        if not isinstance(stats, dict):
            continue
        found = False
        for key in PLAYER_STATS_FOCUS:
            value = stats.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                field_counts[key] += 1
                found = True
        if found:
            completed += 1
    return {"response_shape_valid": True, "games": len(games),
            "completed_with_focus": completed,
            "focus_fields": {k: n for k, n in field_counts.items() if n}}


def _targeted_player_names(day=None):
    """Fail closed on bad gap indexes; rotate verified players between nights."""
    path = os.getenv("CLOSEOUT_GAP_TARGETS", "").strip()
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if (raw.get("schema") != 1 or raw.get("source") != "canonical_cdb_2026"
            or not isinstance(raw.get("targets"), list)
            or not isinstance(raw.get("partition_sha256"), str)
            or len(raw["partition_sha256"]) != 64):
        raise RuntimeError("Invalid canonical CDB gap index")
    names, seen = [], set()
    buckets = {tier: [] for tier in range(4)}
    for item in raw["targets"][:NIGHTLY_GAP_PLAYER_MAX]:
        name = str(item.get("player_name") or "").strip() if isinstance(item, dict) else ""
        norm = " ".join(name.casefold().split())
        if (len(name) < 5 or len(name) > 100 or len(name.split()) < 2
                or any(c in name for c in ("/", ",", " & ", " + "))
                or norm in seen):
            raise RuntimeError("Ambiguous or duplicate canonical target")
        seen.add(norm)
        tier = item.get("api_pro_priority", 3) if isinstance(item, dict) else 3
        if not isinstance(tier, int) or isinstance(tier, bool) or tier not in buckets:
            raise RuntimeError("Invalid canonical API PRO priority")
        names.append(name)
        buckets[tier].append(name)
    if day is None:
        return names
    # If thirty probes have no detailed stats, try a different block tomorrow.
    # Rotation stays within API PRO priority tiers and never alters the index.
    ordinal = date.fromisoformat(day).toordinal()
    rotated = []
    for tier in sorted(buckets):
        group = buckets[tier]
        if group:
            shift = (ordinal * 30) % len(group)
            rotated.extend(group[shift:] + group[:shift])
    return rotated


def probe_recent_event_stats(day, runid):
    """Fetch documented FREE /scores -> final /stats for *exact* CDB gaps.

    Raw provider responses are archived unchanged. Importing them is a
    separate strict exact-day/full-pair, single-writer operation; stats alone
    never authorize a speculative match or source ID.
    """
    path = os.getenv("CLOSEOUT_GAP_TARGETS", "").strip()
    if not path:
        return
    index = json.loads(Path(path).read_text(encoding="utf-8"))
    if (index.get("schema") != 1 or index.get("source") != "canonical_cdb_2026"
            or not isinstance(index.get("partition_sha256"), str)
            or len(index["partition_sha256"]) != 64):
        raise RuntimeError("Invalid recent CDB score target index")
    wanted = set()
    for item in index.get("recent_event_targets", []):
        if not isinstance(item, dict) or not isinstance(item.get("players"), list):
            raise RuntimeError("Bad canonical score target")
        players = item["players"]
        date_text = item.get("date_utc")
        if (len(players) != 2 or any(not isinstance(p, str) or not p for p in players)
                or not isinstance(date_text, str)):
            raise RuntimeError("Bad canonical score target identity")
        try:
            date.fromisoformat(date_text)
        except ValueError:
            raise RuntimeError("Bad canonical score target date") from None
        wanted.add((date_text, tuple(sorted(norm_text(p) for p in players))))
    if not wanted:
        return
    # One board call is needed to discover final event IDs. No fixed event-ID
    # guessing and no optional stats traffic after reserve is reached.
    if (STATE["reason"] or STATE["calls"] >= MAX_CALLS - NIGHTLY_ODDS_RESERVE
            or STATE["remaining"] is not None
            and STATE["remaining"] <= NIGHTLY_ODDS_RESERVE):
        return
    try:
        board = request("/sports/tennis/scores", {"days_from": RECENT_SCORES_DAYS},
                        allow_not_found=True, optional_stats=True)
    except OptionalStatsAccessUnavailable:
        print(json.dumps({"recent_event_stats": "scores_not_entitled"}), flush=True)
        return
    if board is None:
        return
    try:
        events = unpack(board, ("scores", "events", "data", "results"))
    except ValueError:
        print(json.dumps({"recent_event_stats": "scores_unrecognized_shape"}), flush=True)
        return
    selected = []
    seen_ids = set()
    for item in events:
        if not isinstance(item, dict) or item.get("status") != "final":
            continue
        eid = str(item.get("id") or "")
        if not eid.isdigit() or eid in seen_ids:
            continue
        try:
            started = datetime.fromisoformat(str(item.get("commence_time") or "").replace("Z", "+00:00"))
            if started.tzinfo is None or started > now():
                continue
        except ValueError:
            continue
        home, away = item.get("home_team"), item.get("away_team")
        if not isinstance(home, str) or not isinstance(away, str):
            continue
        pair = tuple(sorted((norm_text(home), norm_text(away))))
        if (started.date().isoformat(), pair) not in wanted:
            continue
        seen_ids.add(eid)
        selected.append((started, eid))
    selected.sort()
    fetched, useful, raw_fields = 0, 0, {}
    for _started, eid in selected:
        if (STATE["reason"] or STATE["calls"] >= MAX_CALLS - NIGHTLY_ODDS_RESERVE
                or STATE["remaining"] is not None
                and STATE["remaining"] <= NIGHTLY_ODDS_RESERVE):
            break
        try:
            payload = request(f"/sports/tennis/events/{eid}/stats",
                              allow_not_found=True, optional_stats=True)
        except OptionalStatsAccessUnavailable:
            break
        if not isinstance(payload, dict) or payload.get("status") != "final":
            continue
        if str(payload.get("id") or "") != eid or not isinstance(payload.get("stats"), list):
            continue
        # Trust only the exact event scope already checked on the score board.
        score = next((e for e in events if isinstance(e, dict)
                      and str(e.get("id") or "") == eid), None)
        if (score is None or str(payload.get("commence_time") or "") !=
                str(score.get("commence_time") or "")
                or {norm_text(payload.get("home_team")), norm_text(payload.get("away_team"))}
                != {norm_text(score.get("home_team")), norm_text(score.get("away_team"))}):
            continue
        fields = {}
        for row in payload["stats"]:
            if not isinstance(row, dict):
                continue
            key = row.get("stat_type")
            value = row.get("stat_value")
            if (key in PLAYER_STATS_FOCUS and isinstance(value, (int, float))
                    and not isinstance(value, bool)):
                fields[key] = fields.get(key, 0) + 1
        for key, count in fields.items():
            raw_fields[key] = raw_fields.get(key, 0) + count
        useful += bool(fields)
        DATA.append({"stage": "event_stats_probe", "captured_at_utc": now().isoformat(),
                     "event_id": eid, "payload": payload, "research_only": True})
        fetched += 1
        flush_if_needed(day, runid)
    print(json.dumps({"recent_event_stats": {"scores_eligible": len(selected),
                      "final_events_archived": fetched, "events_with_supported_stats": useful,
                      "available_fields": dict(sorted(raw_fields.items()))}}), flush=True)


def probe_player_games(future, day, runid):
    """Night-only CDB-gap-targeted raw historical boxscore acquisition."""
    exact_targets = _targeted_player_names(day)
    targets = exact_targets if exact_targets is not None else select_player_game_targets(future)
    examined = 0
    attempted = 0
    with_stats = 0
    detailed_stat_rows = 0
    raw_fields = {}
    dry_streak = 0
    for name in targets:
        if STATE["reason"] or STATE["calls"] >= MAX_CALLS:
            break
        # Preserve useful nightly odds bandwidth within the same 750 calls.
        if exact_targets is not None and (
            STATE["calls"] >= MAX_CALLS - NIGHTLY_ODDS_RESERVE
            or (STATE["remaining"] is not None and STATE["remaining"] <= NIGHTLY_ODDS_RESERVE)
        ):
            break
        path = "/sports/tennis/players/" + urllib.parse.quote(name, safe="") + "/games"
        attempted += 1
        try:
            result = request(path, {"limit": PLAYER_GAMES_LIMIT}, allow_not_found=True)
        except OptionalStatsAccessUnavailable:
            # Not entitled to this optional endpoint. Do not waste the nightly
            # quota retrying other names; preserve the existing odds closeout.
            print(json.dumps({"player_games_probe": "not_entitled_or_disabled"}), flush=True)
            break
        if result is None:
            if STATE["reason"]:
                break
            dry_streak += 1
            if exact_targets is not None and dry_streak >= 30:
                print(json.dumps({"player_games_gap_stop": "30_consecutive_missing_or_empty"}), flush=True)
                break
            continue
        summary = summarize_player_games(result)
        examined += 1
        # PropLine has much broader tennis box scores than Aces/DF. Never
        # stop a useful stats stream merely because serve detail is absent.
        detailed = sum(summary["focus_fields"].get(key, 0)
                       for key in ("aces", "dblfaults"))
        dry_streak = 0 if summary["completed_with_focus"] else dry_streak + 1
        detailed_stat_rows += summary["focus_fields"].get("aces", 0)
        with_stats += summary["completed_with_focus"]
        for field, count in summary["focus_fields"].items():
            raw_fields[field] = raw_fields.get(field, 0) + count
        DATA.append({"stage": "player_game_stats_probe", "player_name": name,
                     "captured_at_utc": now().isoformat(), "summary": summary,
                     "payload": result, "research_only": True})
        flush_if_needed(day, runid)
        if exact_targets is not None and dry_streak >= 30:
            print(json.dumps({"player_games_gap_stop": "30_consecutive_no_supported_stats"}), flush=True)
            break
    print(json.dumps({"player_games_probe": {"attempted": attempted,
                      "responses": examined, "games_with_relevant_stats": with_stats,
                      "detailed_ace_df_rows": detailed_stat_rows,
                      "available_fields": dict(sorted(raw_fields.items())),
                      "new_cdb_cells_verified": None}}), flush=True)


WAIT = 0.2  # Hard pacing: at most 5 attempted PropLine requests / second
STATE = {"calls": 0, "remaining": None, "reason": "", "batches": 0}
DATA = []


def now():
    return datetime.now(timezone.utc)


def allowed(t):
    # 23:00 Europe/Bratislava = 21:00 UTC (summer) or 22:00 UTC (winter).
    # Conservative latest cutoff 23:55 UTC; never cross midnight quota reset.
    return t.hour in (21, 22) or (t.hour == 23 and t.minute < 55)


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def github(path, method="GET", content=None, optional=False):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{path}", data=content,
        method=method, headers={"Authorization": "Bearer " + TOKEN,
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json"})
    # Retry bounded transient GitHub failures. PUT has a fixed create-only
    # path; on an uncertain result, save() verifies the exact blob digest.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if optional and exc.code == 404:
                return None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise RuntimeError("GitHub persistence HTTP " + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise RuntimeError("GitHub persistence transient network failure") from None
        time.sleep(min(4, 2 ** attempt))
    raise RuntimeError("GitHub persistence retry exhausted")


def save(day, runid):
    if not DATA:
        return
    n = STATE["batches"]
    filename = f"{runid}-batch-{n:04d}.json.gz"
    path = f"{ROOT}/{day}/{filename}"
    record = {"schema": 1, "day_utc": day, "run_id": runid,
              "records": DATA, "attempted_calls_at_save": STATE["calls"],
              "created_at_utc": now().isoformat(), "research_only": True}
    raw = gzip.compress(json.dumps(record, ensure_ascii=False, sort_keys=True).encode())
    Path("reports").mkdir(exist_ok=True)
    local = Path("reports") / filename
    local.write_bytes(raw)
    expected = blob_sha(raw)
    previous = github(path, optional=True)
    if previous is None:
        body = json.dumps({"message": "research: PropLine closeout batch",
                           "content": base64.b64encode(raw).decode()}).encode()
        try:
            github(path, method="PUT", content=body)
        except RuntimeError:
            pass  # Read-back decides whether an uncertain write succeeded.
    # A newly-created GitHub blob can briefly be invisible through Contents
    # API even after PUT succeeded; poll read-back but never accept mismatch.
    for attempt in range(5):
        result = github(path, optional=True)
        if result is not None:
            if result.get("sha") != expected or result.get("size") != len(raw):
                raise RuntimeError("Batch integrity/read-back FAILED: " + path)
            break
        if attempt < 4:
            time.sleep(min(4, attempt + 1))
    else:
        raise RuntimeError("Batch integrity/read-back FAILED: " + path)
    STATE["batches"] += 1
    print(json.dumps({"saved": path, "items": len(DATA),
                      "calls": STATE["calls"]}), flush=True)
    DATA.clear()


def flush_if_needed(day, runid):
    if len(DATA) >= BATCH_SIZE:
        save(day, runid)


def request(path, params=None, *, allow_not_found=False, optional_stats=False):
    if STATE["calls"] >= MAX_CALLS:
        STATE["reason"] = "run_cap"
        return None
    if not allowed(now()):
        STATE["reason"] = "quota_reset_cutoff"
        return None
    if STATE["remaining"] is not None and STATE["remaining"] <= 0:
        STATE["reason"] = "daily_quota_exhausted"
        return None
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    retries = 0
    while True:
        if not allowed(now()) or STATE["calls"] >= MAX_CALLS:
            STATE["reason"] = "cutoff_or_run_cap"
            return None
        STATE["calls"] += 1
        time.sleep(WAIT)
        req = urllib.request.Request(url, headers={
            "X-API-Key": KEY, "Accept": "application/json",
            "User-Agent": "BlinQ-nightly-closeout/1"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                remaining = resp.headers.get("X-Daily-Remaining")
                reset = resp.headers.get("X-Daily-Reset")
                if remaining is None or reset is None:
                    STATE["reason"] = "missing_quota_headers"
                    return None
                STATE["remaining"] = int(remaining)
                # Never allow crossing the provider's own reset time.
                if int(reset) <= int(time.time()):
                    STATE["reason"] = "provider_reset"
                    return None
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            rem = exc.headers.get("X-Daily-Remaining")
            if rem is not None:
                STATE["remaining"] = int(rem)
            # Missing player logs are normal; do not poison unrelated night odds.
            if allow_not_found and exc.code == 404:
                return None
            if allow_not_found and exc.code == 403:
                raise OptionalStatsAccessUnavailable() from None
            if exc.code == 429:
                retry = exc.headers.get("Retry-After", "1")
                try:
                    seconds = float(retry)
                except ValueError:
                    seconds = 2
                if STATE["remaining"] == 0 or seconds > 60:
                    STATE["reason"] = "daily_quota_exhausted"
                    return None
                if retries < 3 and seconds <= 10:
                    retries += 1
                    time.sleep(max(1, seconds))
                    continue
                STATE["reason"] = "burst_throttle"
            elif optional_stats and exc.code in (500, 502, 503, 504):
                return None  # Optional box scores must not block nightly odds.
            else:
                STATE["reason"] = "provider_http_" + str(exc.code)
            return None
        except (urllib.error.URLError, TimeoutError):
            if optional_stats:
                return None
            STATE["reason"] = "provider_network_error"
            return None


def unpack(data, names):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for name in names:
            if isinstance(data.get(name), list):
                return data[name]
    raise ValueError("Invalid provider list shape")


def collect():
    if not KEY or not TOKEN:
        raise RuntimeError("Missing PROPL/TBT_DATA_GH_TOKEN")
    started = now()
    if not allowed(started):
        raise RuntimeError("Outside protected closeout window (21:00-23:55 UTC)")
    day = started.date().isoformat()
    runid = os.getenv("GITHUB_RUN_ID", str(int(started.timestamp())))
    try:
        canonical_gap_mode = bool(os.getenv("CLOSEOUT_GAP_TARGETS", "").strip())
        # Final score-linked stats before sparse player-name logs. Both use
        # one shared budget and leave room for niche offered odds markets.
        if canonical_gap_mode:
            probe_recent_event_stats(day, runid)
            if not STATE["reason"]:
                probe_player_games([], day, runid)
        if STATE["reason"] or STATE["calls"] >= MAX_CALLS:
            return
        board = request("/sports/tennis/events")
        if board is None:
            return
        events = unpack(board, ("events", "data", "results"))
        DATA.append({"stage": "board", "captured_at_utc": now().isoformat(),
                     "payload": board})
        flush_if_needed(day, runid)
        future = []
        for e in events:
            if not isinstance(e, dict) or not str(e.get("id", "")).isdigit():
                continue
            try:
                kickoff = datetime.fromisoformat(str(e.get("commence_time", "")).replace("Z", "+00:00"))
                if kickoff.tzinfo is None:
                    kickoff = kickoff.replace(tzinfo=timezone.utc)
                if kickoff <= started:
                    continue
            except ValueError:
                continue
            # Include up to seven future days; nearer fixtures take precedence.
            if (kickoff-started).total_seconds() <= 7 * 24 * 3600:
                future.append((kickoff, e))
        future.sort(key=lambda item: item[0])
        print(json.dumps({"eligible_events": len(future), "budget": MAX_CALLS, "scope_days": 7}), flush=True)
        # The extra calls are drawn ONLY from the existing nightly 750 cap.
        # They target raw completed-match stats, not offered betting lines.
        if not canonical_gap_mode:
            probe_player_games(future, day, runid)
        discovered = []
        available_calls = max(0, MAX_CALLS - STATE["calls"])
        if STATE["remaining"] is not None:
            available_calls = min(available_calls, max(0, STATE["remaining"]))
        discovery_call_cap = available_calls // 2
        for kickoff, event in future:
            if STATE["reason"] or len(discovered) >= discovery_call_cap:
                break
            eid = str(event["id"])
            markets = request(f"/sports/tennis/events/{eid}/markets")
            if markets is None:
                break
            try:
                keys = set(m.get("key") for m in unpack(markets, ("markets", "data", "results"))
                           if isinstance(m, dict))
            except ValueError:
                STATE["reason"] = "invalid_market_shape"
                break
            wanted = [m for m in MARKETS if m in keys]
            discovered.append((kickoff, event, keys, wanted))
            DATA.append({"stage": "market_discovery", "event_id": eid,
                         "captured_at_utc": now().isoformat(),
                         "event": event, "available_markets_raw": markets})
            flush_if_needed(day, runid)
        # Spend night-only odds calls on specific priced markets first.
        # The available markets are combined into ONE odds request per event.
        discovered.sort(key=lambda x: (odds_priority(x[2]), x[0]))
        for kickoff, event, keys, wanted in discovered:
            if STATE["reason"]:
                break
            eid = str(event["id"])
            # Keep one discovery record even when no desired market is offered.
            snapshot = {"stage": "odds", "event_id": eid, "event": event, "commence_time": kickoff.isoformat(),
                        "captured_at_utc": now().isoformat(),
                        "available_markets": sorted(k for k in keys if isinstance(k, str)),
                        "requested_markets": wanted, "odds": None}
            if wanted and STATE["calls"] < MAX_CALLS:
                snapshot["odds"] = request(f"/sports/tennis/events/{eid}/odds",
                                           {"markets": ",".join(wanted)})
            DATA.append(snapshot)
            flush_if_needed(day, runid)
            if STATE["reason"]:
                break
        if not STATE["reason"]:
            STATE["reason"] = "useful_slate_exhausted"
    finally:
        save(day, runid)
        print(json.dumps({"summary": STATE, "records_pending": len(DATA)}), flush=True)


if __name__ == "__main__":
    collect()
