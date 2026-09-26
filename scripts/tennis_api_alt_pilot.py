#!/usr/bin/env python3
"""Bounded read-only pilot of Tennis API - ATP WTA ITF (50/day BASIC).

Use only pre-match/upcoming endpoints documented for the product. No live
Socket.IO routes, no production writes, no schedule. Hard cap: 8 requests.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
BASE = "https://" + HOST + "/tennis/v2"
MAX_REQUESTS = 8
MAX_MATCH_ODDS = 6
RESERVE = 5


class Client:
    def __init__(self, key, limit=MAX_REQUESTS, opener=urllib.request.urlopen):
        self.key = key
        self.limit = min(MAX_REQUESTS, max(0, int(limit)))
        self.opener = opener
        self.count = 0
        self.provider_remaining = None

    def get(self, path, params=None):
        if self.count >= self.limit:
            raise RuntimeError("local_request_limit")
        query = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(BASE + path + query, headers={
            "X-RapidAPI-Key": self.key,
            "X-RapidAPI-Host": HOST,
            "Accept": "application/json",
            "User-Agent": "BlinQ-tennis-api-50day-pilot/2",
        })
        self.count += 1
        try:
            with self.opener(req, timeout=16) as res:
                raw = res.headers.get("x-ratelimit-requests-remaining")
                if raw is not None:
                    try:
                        self.provider_remaining = int(raw)
                    except ValueError:
                        pass
                return json.load(res)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"RapidAPI HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError("RapidAPI network request failed") from None


def _rows(payload):
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for sub in ("data", "results", "matches"):
                if isinstance(value.get(sub), list):
                    return value[sub]
    return []


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _match_contract(row, tour):
    p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    tournament = row.get("tournament") if isinstance(row.get("tournament"), dict) else {}
    return {
        "tour": tour,
        "match_id": _num(row.get("matchId") or row.get("id")),
        "player1_id": _num(row.get("player1Id") or p1.get("id")),
        "player2_id": _num(row.get("player2Id") or p2.get("id")),
        "tournament_id": _num(row.get("tournamentId") or tournament.get("id")),
        "round_id": _num(row.get("roundId")),
        "players": [str(p1.get("name") or row.get("player1Name") or "")[:80],
                    str(p2.get("name") or row.get("player2Name") or "")[:80]],
        "start": row.get("startTime") or row.get("date"),
        "embedded_pre_match_odds": row.get("preMatchOdds"),
    }


def _odds_summary(payload):
    if not isinstance(payload, dict):
        return {"valid": False}
    odds = payload.get("odds")
    if odds is None and isinstance(payload.get("result"), dict):
        odds = payload["result"].get("odds")
    rows = odds if isinstance(odds, list) else []
    samples = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            line = float(item.get("total"))
            over = float(item.get("ktb"))
            under = float(item.get("ktm"))
        except (TypeError, ValueError):
            line = over = under = None
        if line is not None and over and under and 1.01 < over < 100 and 1.01 < under < 100:
            samples.append({
                "bookmaker_id": item.get("id_b_o"),
                "line_games": line, "over": over, "under": under,
            })
    return {
        "valid": True,
        "bookmaker_rows": len(rows),
        "game_total_samples": samples[:6],
        "has_game_total": bool(samples),
    }


def run(client, *, now=None):
    now = now or datetime.now(timezone.utc)
    report = {
        "schema": 2, "captured_at": now.isoformat(), "read_only": True,
        "plan": "BASIC 50 requests/day", "request_cap": client.limit,
        "requests_used": 0, "provider_remaining": None,
        "board": {}, "checked_matches": [], "status": "ok",
    }
    candidates = []
    for tour in ("atp", "wta"):
        if client.provider_remaining is not None and client.provider_remaining <= RESERVE:
            report["status"] = "provider_daily_reserve"
            break
        try:
            payload = client.get(f"/upcoming/matches/{tour}", {
                "group": "singles", "limit": 30, "page": 1,
                "include": "preMatchOdds",
            })
            rows = _rows(payload)
            report["board"][tour] = {
                "rows": len(rows),
                "has_embedded_pre_match_odds": sum(
                    bool(r.get("preMatchOdds")) for r in rows if isinstance(r, dict)
                ),
            }
            candidates.extend(
                _match_contract(row, tour) for row in rows if isinstance(row, dict)
            )
        except RuntimeError as exc:
            report["board"][tour] = {"error": str(exc)}
            if "401" in str(exc) or "403" in str(exc):
                report["status"] = "key_or_plan_not_subscribed"
                break

    # Prefer rows with all exact identifiers needed by /upcoming/matchodds/{tour}.
    valid = [m for m in candidates if all(
        m[k] is not None for k in ("player1_id", "player2_id", "tournament_id", "round_id")
    )]
    valid.sort(key=lambda m: (m["start"] or "", m["tour"], m["match_id"] or 0))
    for match in valid[:MAX_MATCH_ODDS]:
        if client.count >= client.limit:
            break
        if client.provider_remaining is not None and client.provider_remaining <= RESERVE:
            report["status"] = "provider_daily_reserve"
            break
        try:
            payload = client.get(f"/upcoming/matchodds/{match['tour']}", {
                "tournamentId": match["tournament_id"],
                "roundId": match["round_id"],
                "player1Id": match["player1_id"],
                "player2Id": match["player2_id"],
            })
            report["checked_matches"].append({
                **match, "odds": _odds_summary(payload)
            })
        except RuntimeError as exc:
            report["checked_matches"].append({**match, "error": str(exc)})
            if "401" in str(exc) or "403" in str(exc):
                report["status"] = "match_odds_not_in_basic_plan"
                break

    report["requests_used"] = client.count
    report["provider_remaining"] = client.provider_remaining
    report["game_total_matches_found"] = sum(
        bool(row.get("odds", {}).get("has_game_total"))
        for row in report["checked_matches"]
    )
    return report


if __name__ == "__main__":
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not key:
        raise SystemExit("RAPIDAPI_KEY secret missing")
    result = run(Client(key))
    target = Path("reports/tennis_api_alt_50day.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
