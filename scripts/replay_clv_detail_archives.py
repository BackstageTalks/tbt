#!/usr/bin/env python3
"""One-time, provider-free CLV Detail replay from already archived research.

Runs after exact production deployment. Reads private gzip files, sends only
two-sided Match Winner offers to the authenticated runtime, and checks the
runtime's independent storage read-back counts. No tennis/odds API calls.
"""
import base64
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request

REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "").strip()
WORKER = os.getenv("BLINQ_LIVE_WORKER_TOKEN", "").strip()
BASE = os.getenv("BLINQ_PUBLIC_BASE_URL", "").strip().rstrip("/")
DAYS = max(1, min(2, int(os.getenv("CLV_REPLAY_DAYS", "2"))))
ROOT = "research/propline_clv"


def _github(path):
    url = "https://api.github.com/repos/" + REPO + "/contents/" + path
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError("CLV archive read HTTP " + str(exc.code)) from None


def h2h_events(snapshot):
    """Return only research-observed, priced h2h for strict server-side linking."""
    if not isinstance(snapshot, dict) or snapshot.get("schema") != 1:
        return []
    result = []
    for event in snapshot.get("events") or []:
        if not isinstance(event, dict):
            continue
        books = []
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            markets = [
                m for m in book.get("markets") or []
                if isinstance(m, dict) and m.get("key") == "h2h"
            ]
            if markets:
                books.append({
                    "key": book.get("key"),
                    "title": book.get("title"),
                    "markets": markets,
                })
        if books:
            result.append({
                "event_id": event.get("event_id"),
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "commence_time": event.get("commence_time"),
                "captured_at": event.get("captured_at"),
                "bookmakers": books,
            })
    return result


def send(events):
    if not events:
        return {"ok": True, "accepted": 0, "verified": 0,
                "written": 0, "already_present": 0}
    body = json.dumps({"schema": 1, "events": events}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/v1/internal/clv-snapshot",
        method="POST", data=body, headers={
            "X-Blinq-Worker-Token": WORKER,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            outcome = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("CLV Detail replay HTTP " + str(exc.code)) from None
    if (not isinstance(outcome, dict) or outcome.get("ok") is not True
            or outcome.get("accepted") != outcome.get("verified")):
        raise RuntimeError("CLV Detail replay read-back failed")
    return outcome


def replay():
    if not TOKEN or not WORKER or not BASE.startswith("https://"):
        raise RuntimeError("Missing private archive or CLV Detail worker configuration")
    summary = {
        "archives": 0, "submitted_events": 0,
        "accepted": 0, "written": 0, "already_present": 0, "verified": 0,
        "rejected_events": 0,
    }
    today = datetime.now(timezone.utc).date()
    for offset in range(DAYS):
        folder = ROOT + "/" + (today - timedelta(days=offset)).isoformat()
        names = _github(folder) or []
        if not isinstance(names, list):
            raise RuntimeError("CLV archive listing was malformed")
        # Sorted archive captures preserve time order and avoid false movement.
        files = sorted(
            (x for x in names if isinstance(x, dict)
             and str(x.get("name") or "").endswith(".json.gz")),
            key=lambda x: str(x["name"]),
        )[-24:]
        for item in files:
            encoded = _github(item["path"])
            if not isinstance(encoded, dict) or not encoded.get("content"):
                raise RuntimeError("CLV archive missing encoded gzip")
            try:
                payload = gzip.decompress(base64.b64decode(
                    encoded["content"].replace("\n", "")))
                archive = json.loads(payload)
            except (ValueError, OSError) as exc:
                raise RuntimeError("CLV archive is corrupt") from exc
            events = h2h_events(archive)
            outcome = send(events)
            summary["archives"] += 1
            summary["submitted_events"] += len(events)
            for key in ("accepted", "written", "already_present", "verified", "rejected_events"):
                summary[key] += int(outcome.get(key) or 0)
    if summary["accepted"] != summary["verified"]:
        raise RuntimeError("CLV replay persisted fewer observations than accepted")
    return summary


if __name__ == "__main__":
    print("CLV_DETAIL_REPLAY", json.dumps(replay(), sort_keys=True))
