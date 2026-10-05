"""Audit public ATP weekly ranking history against canonical BlinQ history.

Preferred mode reads the upstream SQLite archive locally (one download, zero live
API requests). API mode remains available as a fallback. Only snapshots strictly
available before the historical match date are accepted.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import sqlite3
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions

DEFAULT_BASE_URL = "https://atp-rankings.ishanjha.com"
SOURCE = "atp_rankings_ishanjha_weekly"


def _get_json(url: str, timeout: float = 30.0):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BlinQ-noncommercial-ranking-audit/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _positive_int(value):
    if value in (None, "", "-"):
        return None
    text = str(value).replace(",", "").strip()
    match = re.match(r"^(\d+)", text)
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def _source_week_for(match_day: date, weeks: list[date]) -> date | None:
    idx = bisect.bisect_right(weeks, match_day) - 1
    if idx < 0:
        return None
    if weeks[idx] == match_day:
        idx -= 1
    return weeks[idx] if idx >= 0 else None


def _sqlite_weeks(path: Path) -> list[date]:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    weeks = []
    for (name,) in rows:
        try:
            weeks.append(datetime.strptime(str(name), "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(weeks)


def _sqlite_week_rows(conn: sqlite3.Connection, week: date) -> list[dict]:
    table = week.isoformat()
    rows = conn.execute(
        f'SELECT rank, name, points FROM "{table}"'
    ).fetchall()
    return [
        {"rank": row[0], "name": row[1], "points": row[2]}
        for row in rows
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sqlite-db", default="")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--sleep-seconds", type=float, default=0.04)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    sqlite_path = Path(args.sqlite_db) if args.sqlite_db else None
    use_sqlite = bool(sqlite_path and sqlite_path.is_file())
    if use_sqlite:
        weeks = _sqlite_weeks(sqlite_path)
        api_requests = 0
    else:
        raw_weeks = _get_json(f"{args.base_url.rstrip('/')}/api/weeks").get("weeks") or []
        weeks = sorted(datetime.strptime(str(item), "%Y-%m-%d").date() for item in raw_weeks)
        api_requests = 1
    if not weeks:
        raise SystemExit("ATP ranking source returned no weeks")

    atp_matches = [m for m in matches if str(m.tour or "").lower() == "atp"]
    by_week = defaultdict(list)
    counts = Counter()
    for match in atp_matches:
        match_day = match.scheduled_at.astimezone(timezone.utc).date()
        source_week = _source_week_for(match_day, weeks)
        if source_week is None:
            counts["before_source_history"] += 1
            continue
        by_week[source_week].append(match)

    stage = []
    sidecar = []
    review = []
    conn = sqlite3.connect(str(sqlite_path)) if use_sqlite else None
    try:
        for source_week in sorted(by_week):
            if conn is not None:
                rows = _sqlite_week_rows(conn, source_week)
            else:
                url = f"{args.base_url.rstrip('/')}/api/week/{source_week.isoformat()}"
                payload = _get_json(url)
                api_requests += 1
                rows = payload.get("rankings") or []

            index = defaultdict(list)
            for row in rows:
                name = str(row.get("name") or "").strip()
                rank = _positive_int(row.get("rank"))
                if not name or rank is None:
                    continue
                index[_norm(name)].append(
                    {
                        "name": name,
                        "rank": rank,
                        "points": _positive_int(row.get("points")),
                    }
                )

            for match in by_week[source_week]:
                counts["atp_matches_in_source_span"] += 1
                key1, key2 = _norm(match.player1_name), _norm(match.player2_name)
                candidates1, candidates2 = index.get(key1, []), index.get(key2, [])
                if len(candidates1) != 1 or len(candidates2) != 1:
                    counts["name_not_unique_or_missing"] += 1
                    if len(review) < 500:
                        review.append(
                            {
                                "match_id": str(match.match_id),
                                "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                                "player1_name": str(match.player1_name),
                                "player2_name": str(match.player2_name),
                                "source_week": source_week.isoformat(),
                                "player1_candidates": candidates1,
                                "player2_candidates": candidates2,
                            }
                        )
                    continue

                r1, r2 = candidates1[0], candidates2[0]
                counts["identity_linked"] += 1
                existing1, existing2 = match.player1_rank, match.player2_rank

                for existing, incoming in ((existing1, r1["rank"]), (existing2, r2["rank"])):
                    if existing is None:
                        continue
                    counts["existing_rank_values"] += 1
                    if int(existing) == incoming:
                        counts["existing_rank_exact"] += 1
                    elif abs(int(existing) - incoming) <= 2:
                        counts["existing_rank_within2"] += 1
                    else:
                        counts["existing_rank_difference_gt2"] += 1

                sidecar.append(
                    {
                        "schema": 1,
                        "match_id": str(match.match_id),
                        "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                        "player1_rank": r1["rank"],
                        "player2_rank": r2["rank"],
                        "player1_rank_points": r1["points"],
                        "player2_rank_points": r2["points"],
                        "source": SOURCE,
                        "source_week": source_week.isoformat(),
                        "point_in_time": True,
                        "model_feature_policy": "rank_points_sidecar_only_until_ablation",
                    }
                )

                if existing1 is None or existing2 is None:
                    stage.append(
                        {
                            "schema": 1,
                            "match_id": str(match.match_id),
                            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                            "player1_id": str(match.player1_id),
                            "player1_name": str(match.player1_name),
                            "player2_id": str(match.player2_id),
                            "player2_name": str(match.player2_name),
                            "existing_player1_rank": existing1,
                            "existing_player2_rank": existing2,
                            "incoming_player1_rank": r1["rank"],
                            "incoming_player2_rank": r2["rank"],
                            "source_week": source_week.isoformat(),
                            "source": SOURCE,
                        }
                    )
                    counts["strict_fill_candidate"] += 1

            if conn is None and args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)
    finally:
        if conn is not None:
            conn.close()

    existing = counts["existing_rank_values"]
    report = {
        "schema": 1,
        "source": SOURCE,
        "source_mode": "sqlite" if use_sqlite else "api",
        "base_url": args.base_url,
        "source_weeks_available": len(weeks),
        "source_date_range": {"from": weeks[0].isoformat(), "to": weeks[-1].isoformat()},
        "canonical_rows": len(matches),
        "canonical_atp_rows": len(atp_matches),
        "counts": dict(counts),
        "overlap_exact_rate": (counts["existing_rank_exact"] / existing) if existing else 0.0,
        "overlap_within2_rate": (
            (counts["existing_rank_exact"] + counts["existing_rank_within2"]) / existing
            if existing else 0.0
        ),
        "api_requests": api_requests,
        "rapidapi_requests": 0,
        "production_mutated": False,
        "point_in_time_policy": "latest ranking week before match date; same-day ranking snapshot is never used",
        "rank_points_policy": "sidecar_only_until_candidate_ablation",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for filename, rows in (
        ("rank-fill-candidates.jsonl", stage),
        ("rank-points-sidecar.jsonl", sidecar),
        ("review.jsonl", review),
    ):
        with (out / filename).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
