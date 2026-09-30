#!/usr/bin/env python3
"""Evaluate archived The Odds API h2h movement and BlinQ issue-to-close CLV."""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import statistics
import urllib.error
import urllib.request
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "").strip()
ROOT = "research/the_odds_clv"


def _gh(path, missing_ok=False):
    if not TOKEN:
        raise RuntimeError("Missing TBT_DATA_GH_TOKEN")
    req = urllib.request.Request(
        "https://api.github.com/repos/" + DATA_REPO + "/contents/" + path,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise RuntimeError(f"GitHub archive HTTP {exc.code}") from None


def _norm(value):
    ascii_text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _time(value):
    try:
        value = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def read_archives(days):
    now = datetime.now(timezone.utc)
    for offset in range(days):
        day = (now - timedelta(days=offset)).date().isoformat()
        entries = _gh(ROOT + "/" + day, missing_ok=True) or []
        for entry in entries if isinstance(entries, list) else []:
            if not str(entry.get("name") or "").endswith(".json.gz"):
                continue
            obj = _gh(entry["path"])
            if obj and obj.get("content"):
                yield json.loads(
                    gzip.decompress(base64.b64decode(obj["content"].replace("\n", "")))
                )


def _book_observations(snapshots):
    rows = []
    for snap in snapshots:
        captured = _time(snap.get("captured_at"))
        if captured is None:
            continue
        for event in snap.get("events") or []:
            kickoff = _time(event.get("commence_time"))
            if kickoff is None or not captured < kickoff:
                continue
            for book in event.get("bookmakers") or []:
                book_id = str(book.get("key") or book.get("title") or "")
                for market in book.get("markets") or []:
                    if market.get("key") != "h2h":
                        continue
                    outcomes = market.get("outcomes") or []
                    if len(outcomes) != 2:
                        continue
                    try:
                        prices = {str(o["name"]): float(o["price"]) for o in outcomes}
                    except (KeyError, TypeError, ValueError):
                        continue
                    if len(prices) != 2 or any(price <= 1 for price in prices.values()):
                        continue
                    implied = {name: 1.0 / price for name, price in prices.items()}
                    margin = sum(implied.values())
                    fair = {name: value / margin for name, value in implied.items()}
                    rows.append({
                        "event_id": str(event.get("event_id") or ""),
                        "sport_key": event.get("sport_key"),
                        "commence_time": kickoff,
                        "captured_at": captured,
                        "home_team": event.get("home_team"),
                        "away_team": event.get("away_team"),
                        "bookmaker": book_id,
                        "prices": prices,
                        "fair": fair,
                    })
    return rows


def evaluate(snapshots, ledger=()):
    observations = _book_observations(snapshots)
    by_series = defaultdict(list)
    for row in observations:
        pair = tuple(sorted((_norm(row["home_team"]), _norm(row["away_team"]))))
        by_series[(row["event_id"], row["bookmaker"], pair)].append(row)

    movement = []
    for (_, bookmaker, pair), series in by_series.items():
        series.sort(key=lambda row: row["captured_at"])
        kickoff = series[0]["commence_time"]
        early = [r for r in series if timedelta(hours=2) <= kickoff-r["captured_at"] <= timedelta(hours=36)]
        late = [r for r in series if timedelta(0) < kickoff-r["captured_at"] <= timedelta(minutes=90)]
        if not early or not late:
            continue
        first, close = early[0], late[-1]
        for selection in first["prices"]:
            if selection not in close["prices"]:
                continue
            movement.append({
                "event_id": first["event_id"],
                "bookmaker": bookmaker,
                "players": list(pair),
                "selection": selection,
                "entry_time": first["captured_at"].isoformat(),
                "close_proxy_time": close["captured_at"].isoformat(),
                "entry_decimal": round(first["prices"][selection], 4),
                "close_proxy_decimal": round(close["prices"][selection], 4),
                "price_clv_pct": round(100*(first["prices"][selection]/close["prices"][selection]-1), 3),
                "fair_probability_move_pp": round(
                    100*(close["fair"][selection]-first["fair"][selection]), 3
                ),
            })

    selected = []
    for pick in ledger if isinstance(ledger, list) else []:
        issued = _time(pick.get("issued_at"))
        kickoff = _time(pick.get("scheduled_at"))
        p1, p2 = pick.get("player1") or {}, pick.get("player2") or {}
        winner = str(pick.get("winner_id") or "")
        if issued is None or kickoff is None or issued >= kickoff:
            continue
        selection = p1.get("name") if str(p1.get("id") or "") == winner else p2.get("name")
        pair = tuple(sorted((_norm(p1.get("name")), _norm(p2.get("name")))))
        if not all(pair) or not selection:
            continue
        candidates = [
            row for row in observations
            if tuple(sorted((_norm(row["home_team"]), _norm(row["away_team"])))) == pair
            and abs((row["commence_time"]-kickoff).total_seconds()) <= 2*3600
        ]
        for bookmaker in sorted({row["bookmaker"] for row in candidates}):
            book = sorted(
                [row for row in candidates if row["bookmaker"] == bookmaker],
                key=lambda row: row["captured_at"],
            )
            issue = [row for row in book if row["captured_at"] <= issued and issued-row["captured_at"] <= timedelta(hours=2)]
            close = [row for row in book if issued < row["captured_at"] < kickoff and kickoff-row["captured_at"] <= timedelta(minutes=90)]
            if not issue or not close:
                continue
            before, final = issue[-1], close[-1]
            actual_name = next((name for name in before["prices"] if _norm(name) == _norm(selection)), None)
            close_name = next((name for name in final["prices"] if _norm(name) == _norm(selection)), None)
            if actual_name is None or close_name is None:
                continue
            selected.append({
                "blinq_event_id": pick.get("event_id"),
                "bookmaker": bookmaker,
                "selection": selection,
                "issued_at": issued.isoformat(),
                "issue_sample_time": before["captured_at"].isoformat(),
                "close_proxy_time": final["captured_at"].isoformat(),
                "issue_decimal": round(before["prices"][actual_name], 4),
                "close_proxy_decimal": round(final["prices"][close_name], 4),
                "price_clv_pct": round(100*(before["prices"][actual_name]/final["prices"][close_name]-1), 3),
                "fair_probability_move_pp": round(
                    100*(final["fair"][close_name]-before["fair"][actual_name]), 3
                ),
            })

    values = [row["price_clv_pct"] for row in selected]
    return {
        "schema": 1,
        "method": "same bookmaker h2h; latest pre-issue sample vs last sample within 90m of start",
        "limits": [
            "Close is an observed pre-start proxy, not an official bookmaker closing line.",
            "Only exact normalized player-pair matches within two hours of scheduled start are linked.",
            "No post-issue value is ever eligible as a feature for that same match.",
        ],
        "archive_files": len(snapshots),
        "observation_rows": len(observations),
        "comparable_board_moves": len(movement),
        "blinq_comparable_bookmaker_series": len(selected),
        "blinq_clv": {
            "median_price_clv_pct": round(statistics.median(values), 3) if values else None,
            "positive_share": round(sum(v > 0 for v in values)/len(values), 3) if values else None,
        },
        "blinq_examples": selected[:100],
        "board_examples": movement[:100],
    }


def main():
    days = max(1, min(int(os.getenv("CLV_LOOKBACK_DAYS", "7")), 30))
    snapshots = list(read_archives(days))

    ledger = []
    try:
        from _bootstrap import ROOT as REPO_ROOT
        from release_store import ReleaseStore
        directory = REPO_ROOT / ".cache" / "tbt" / "clv-report-predictions"
        store = ReleaseStore(DATA_REPO, "tbt-predictions-v1", directory)
        if "ledger.json" in store._asset_names():
            store.download(extra_names=("ledger.json",), required_names=("ledger.json",))
            ledger = json.loads((directory / "ledger.json").read_text(encoding="utf-8"))
    except Exception:
        ledger = []

    result = evaluate(snapshots, ledger)
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    Path("reports").mkdir(exist_ok=True)
    Path("reports/the_odds_clv_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "archive_files": result["archive_files"],
        "observation_rows": result["observation_rows"],
        "blinq_comparable_bookmaker_series": result["blinq_comparable_bookmaker_series"],
        "blinq_clv": result["blinq_clv"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
