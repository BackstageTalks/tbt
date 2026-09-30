#!/usr/bin/env python3
"""Private point-in-time Match Winner market snapshots from The Odds API.

Research/data collection only. It never changes predictions, selections, ROI or
production model inputs. One h2h market in one region keeps each sport-key
request bounded while capturing all matches in that tennis tournament at once.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore

API = "https://api.the-odds-api.com/v4"
DATA_REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
ROOT_PATH = "research/the_odds_clv"
KEY = os.getenv("THE_ODDS_API_KEY", "").strip()
GH_TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "").strip()
DAILY_CAP = max(1, min(900, int(os.getenv("CLV_DAILY_CREDIT_CAP", "300"))))
MAX_SPORTS = max(1, min(50, int(os.getenv("CLV_MAX_SPORTS_PER_RUN", "8"))))
PROVIDER_RESERVE = max(0, int(os.getenv("CLV_PROVIDER_RESERVE", "100")))
REASON = os.getenv("CLV_CAPTURE_REASON", "hourly").strip() or "hourly"


def _int_header(headers, name):
    try:
        return int(headers.get(name))
    except (TypeError, ValueError):
        return None


def _get(path, params, *, opener=urllib.request.urlopen):
    url = API + path + "?" + urllib.parse.urlencode(params)
    try:
        with opener(
            urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "BlinQ-CLV/1.0"},
            ),
            timeout=25,
        ) as response:
            payload = json.load(response)
            quota = {
                "remaining": _int_header(response.headers, "x-requests-remaining"),
                "used": _int_header(response.headers, "x-requests-used"),
                "last": _int_header(response.headers, "x-requests-last"),
            }
            return payload, quota
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"The Odds API HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("The Odds API request failed") from None


def _gh(path, method="GET", data=None, missing_ok=False):
    url = "https://api.github.com/repos/" + DATA_REPO + "/contents/" + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + GH_TOKEN,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise RuntimeError(f"GitHub archive HTTP {exc.code}") from None


def _norm(value):
    ascii_text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _priority_terms():
    """Best-effort tournament hints from the current private prediction ledger."""
    directory = ROOT / ".cache" / "tbt" / "clv-predictions"
    try:
        store = ReleaseStore(DATA_REPO, "tbt-predictions-v1", directory)
        if "ledger.json" not in store._asset_names():
            return []
        store.download(extra_names=("ledger.json",), required_names=("ledger.json",))
        rows = json.loads((directory / "ledger.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    terms = []
    for row in rows if isinstance(rows, list) else []:
        try:
            start = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if start.tzinfo is None or not (now < start and (start - now).total_seconds() <= 48 * 3600):
            continue
        term = _norm(row.get("tournament"))
        if len(term) >= 4 and term not in terms:
            terms.append(term)
    return terms


def _sport_rank(sport, priority_terms):
    key = _norm(sport.get("key"))
    title = _norm(sport.get("title"))
    blob = key + " " + title
    priority = 0 if any(term in blob or blob in term for term in priority_terms) else 1
    tour = 0 if "atp" in blob else 1 if "wta" in blob else 2
    return priority, tour, blob


def _active_tennis_sports(sports, priority_terms):
    active = [
        s for s in sports if isinstance(s, dict)
        and s.get("active")
        and str(s.get("group") or "").lower() == "tennis"
        and not s.get("has_outrights")
    ]
    return sorted(active, key=lambda s: _sport_rank(s, priority_terms))


def _decimal(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if 1.001 <= value < 100 else None


def _normalize_events(events, sport):
    rows = []
    for event in events if isinstance(events, list) else []:
        event_id = str(event.get("id") or "")
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        start = str(event.get("commence_time") or "").strip()
        if not event_id or not home or not away or not start:
            continue
        books = []
        for book in event.get("bookmakers") or []:
            markets = []
            for market in book.get("markets") or []:
                if market.get("key") != "h2h":
                    continue
                outcomes = []
                for outcome in market.get("outcomes") or []:
                    price = _decimal(outcome.get("price"))
                    name = str(outcome.get("name") or "").strip()
                    if price is not None and name:
                        outcomes.append({"name": name, "price": price})
                if len(outcomes) == 2:
                    markets.append({
                        "key": "h2h",
                        "last_update": market.get("last_update"),
                        "outcomes": outcomes,
                    })
            if markets:
                books.append({
                    "key": book.get("key"),
                    "title": book.get("title"),
                    "last_update": book.get("last_update"),
                    "markets": markets,
                })
        if books:
            rows.append({
                "event_id": event_id,
                "sport_key": sport.get("key"),
                "sport_title": sport.get("title"),
                "commence_time": start,
                "home_team": home,
                "away_team": away,
                "bookmakers": books,
            })
    return rows


def collect(*, key, available_credits, now=None, max_sports=MAX_SPORTS,
            provider_reserve=PROVIDER_RESERVE, priority_terms=(), opener=urllib.request.urlopen):
    now = now or datetime.now(timezone.utc)
    report = {
        "schema": 1,
        "captured_at": now.isoformat(),
        "reason": REASON,
        "source": "the-odds-api",
        "region": "eu",
        "market": "h2h",
        "odds_format": "decimal",
        "research_only": True,
        "production_mutated": False,
        "model_feature_enabled": False,
        "credits_spent": 0,
        "credits_available_local": int(available_credits),
        "provider_remaining": None,
        "sports_checked": [],
        "events": [],
        "status": "ok",
    }
    if not key or available_credits <= 0:
        report["status"] = "skipped_no_key_or_local_budget"
        return report

    sports, quota = _get("/sports/", {"apiKey": key}, opener=opener)
    report["provider_remaining"] = quota["remaining"]
    if quota["remaining"] is None:
        report["status"] = "unknown_provider_quota_stop"
        return report
    if quota["remaining"] <= provider_reserve:
        report["status"] = "provider_reserve_reached"
        return report
    active = _active_tennis_sports(sports, list(priority_terms))
    report["active_tennis_sports"] = len(active)

    call_cap = min(int(available_credits), int(max_sports), len(active))
    for sport in active[:call_cap]:
        if report["provider_remaining"] is not None and report["provider_remaining"] <= provider_reserve:
            report["status"] = "provider_reserve_reached"
            break
        events, q = _get(
            f"/sports/{sport['key']}/odds/",
            {
                "apiKey": key,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            opener=opener,
        )
        cost = q["last"] if q["last"] is not None else 1
        if cost < 0 or cost > 1:
            report["status"] = "unexpected_request_cost"
            break
        report["credits_spent"] += cost
        report["provider_remaining"] = q["remaining"]
        normalized = _normalize_events(events, sport)
        report["sports_checked"].append({
            "sport_key": sport.get("key"),
            "title": sport.get("title"),
            "events": len(normalized),
            "credits": cost,
        })
        report["events"].extend(normalized)
        if q["remaining"] is None:
            report["status"] = "unknown_provider_quota_stop"
            break
        if q["remaining"] <= provider_reserve:
            report["status"] = "provider_reserve_reached"
            break
    return report


def _today_usage(folder):
    entries = _gh(folder, missing_ok=True) or []
    if not isinstance(entries, list):
        raise ValueError("Unexpected CLV archive folder")
    total = 0
    for entry in entries:
        name = str(entry.get("name") or "")
        if "-credits-" not in name or not name.endswith(".json.gz"):
            continue
        try:
            total += int(name.split("-credits-", 1)[1].split(".", 1)[0])
        except ValueError:
            raise RuntimeError("Unrecognized CLV archive filename") from None
    return total


def _save(folder, report):
    now = datetime.now(timezone.utc)
    run_id = os.getenv("GITHUB_RUN_ID") or str(int(time.time()))
    credits = int(report.get("credits_spent") or 0)
    name = now.strftime("%H%M%S") + "-" + run_id + "-credits-" + str(credits) + ".json.gz"
    payload = gzip.compress(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    path = folder + "/" + name
    _gh(path, method="PUT", data={
        "message": "research: archive The Odds API tennis CLV snapshot",
        "content": base64.b64encode(payload).decode("ascii"),
    })
    return path


def main():
    if not KEY or not GH_TOKEN:
        raise SystemExit("Missing THE_ODDS_API_KEY or TBT_DATA_GH_TOKEN")
    now = datetime.now(timezone.utc)
    folder = ROOT_PATH + "/" + now.date().isoformat()
    used = _today_usage(folder)
    available = max(0, DAILY_CAP - used)
    report = collect(
        key=KEY,
        available_credits=available,
        now=now,
        priority_terms=_priority_terms(),
    )
    report["credits_used_before_run"] = used
    report["daily_credit_cap"] = DAILY_CAP
    report["credits_used_after_run"] = used + int(report.get("credits_spent") or 0)
    report["local_daily_remaining"] = max(0, DAILY_CAP - report["credits_used_after_run"])

    Path("reports").mkdir(exist_ok=True)
    Path("reports/the_odds_clv_snapshot.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    path = _save(folder, report)
    print(
        f"The Odds CLV: {len(report['events'])} events, "
        f"{report['credits_spent']} credits, "
        f"daily={report['credits_used_after_run']}/{DAILY_CAP}, archived={path}"
    )


if __name__ == "__main__":
    main()
