"""ITF historical gap-fill STAGING (read-only for CDB).

For ITF matches imported from historical sources (match_id 'hist-js:*', no
native RapidAPI ID, no serve/return stats) this job:
  1. scans the RapidAPI daily calendar for the tournament week (7 days, ITF
     categories only) and links a CDB match to a RapidAPI event ONLY when both
     players' normalized surnames match exactly one event that week,
  2. fetches statistics for linked events and parses them with the production
     parser (``parse_statistics``).
Output: JSONL staging rows + report. NO CDB writes. Import into CDB happens
later through the existing guarded canonical writer after owner review.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def norm_last(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    parts = re.sub(r"[^a-z ]", " ", s).split()
    return parts[-1] if parts else ""


def names_agree(a, b):
    def tokens(value):
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
        return re.findall("[a-z]+", text.lower())
    a, b = tokens(a), tokens(b)
    if len(a) < 2 or len(b) < 2 or a[-1] != b[-1]:
        return False
    return a[0] == b[0] or (min(len(a[0]), len(b[0])) == 1 and a[0][0] == b[0][0])


def load_targets(history_dir: str, start: date, end: date) -> dict[date, list[dict]]:
    import pandas as pd
    weeks: dict[date, list[dict]] = defaultdict(list)
    for year in range((start - timedelta(days=6)).year, (end + timedelta(days=6)).year + 1):
        if year < 2016:
            continue
        f = Path(history_dir) / f"history-{year}.parquet"
        d = pd.read_parquet(f, columns=["match_id", "scheduled_at", "player1_name",
                                        "player2_name", "tournament_level", "stats_json"])
        d = d[d.match_id.astype(str).str.startswith("hist-js")
              & d.tournament_level.astype(str).str.lower().str.contains("itf")
              ]
        for mid, t, a, b, stats in zip(d.match_id, d.scheduled_at, d.player1_name, d.player2_name, d.stats_json):
            day = date.fromisoformat(str(t)[:10])
            if start - timedelta(days=6) <= day <= end + timedelta(days=6):
                weeks[day].append({"match_id": mid, "p1": a, "p2": b,
                                   "evidence_only": not start <= day <= end or "p1_service_points_won" in str(stats)})
    return dict(sorted(weeks.items()))


def run(client, weeks: dict, out: Path, max_requests: int, *, range_end=None) -> dict:
    from tbt.providers.statistics import parse_statistics
    client.request_limit = max_requests
    out.mkdir(parents=True, exist_ok=True)
    rep = {"schema": 1, "cdb_writes": 0, "weeks": 0, "targets": 0, "linked": 0,
           "ambiguous": 0, "stats_rows": 0, "stats_with_serve_return": 0}
    owners = defaultdict(list)
    for day, entries in weeks.items():
        for target in entries:
            key = frozenset((norm_last(target["p1"]), norm_last(target["p2"])))
            owners[key].append((day, target["match_id"]))
    fp = gzip.open(out / "staging.jsonl.gz", "wt", encoding="utf-8")
    try:
        for start, targets in sorted(weeks.items()):
            targets = [t for t in targets if not t.get("evidence_only")]
            if not targets:
                continue
            if client.request_count + 80 > max_requests:
                rep["stopped"] = "budget"
                break
            rep["weeks"] += 1
            rep["targets"] += len(targets)
            pending = []
            index: dict[frozenset, list] = defaultdict(list)
            for k in range(7):
                day = start + timedelta(days=k)
                for cat in client.calendar_categories(day):
                    if "itf" not in json.dumps(cat).lower():
                        continue
                    cid = client._category_id(cat)
                    if cid is None:
                        continue
                    for raw in client.category_events(cid, day) or []:
                        h, a = raw.get("homeTeam") or {}, raw.get("awayTeam") or {}
                        key = frozenset((norm_last(h.get("name")), norm_last(a.get("name"))))
                        index[key].append((raw, norm_last(h.get("name"))))
            for t in targets:
                key = frozenset((norm_last(t["p1"]), norm_last(t["p2"])))
                hits = {r[0].get("id"): r for r in index.get(key, []) if r[0].get("id")}
                if not hits:
                    continue
                overlapping = {mid for day, mid in owners[key] if abs((day-start).days) <= 6}
                if len(overlapping) != 1:
                    rep["ambiguous"] += 1
                    continue
                if len(hits) != 1 or len(key) != 2:
                    rep["ambiguous"] += int(len(hits) > 1)
                    continue
                if client.request_count + 1 > max_requests:
                    rep["stopped"] = "budget"
                    break
                eid, (raw, home_last) = next(iter(hits.items()))
                home = (raw.get("homeTeam") or {}).get("name")
                away = (raw.get("awayTeam") or {}).get("name")
                first, second = (home, away) if home_last == norm_last(t["p1"]) else (away, home)
                if not names_agree(t["p1"], first) or not names_agree(t["p2"], second):
                    rep["ambiguous"] += 1
                    continue
                rep["linked"] += 1
                try:
                    payload = client.event_statistics(eid)
                    stats = parse_statistics(payload, home_is_player1=(home_last == norm_last(t["p1"])))
                except Exception as exc:
                    rep.update(stopped="retry", failed_event_id=eid, error=type(exc).__name__)
                    break
                pending.append({"match_id": t["match_id"], "provider_event_id": eid,
                                "week": start.isoformat(), "stats": stats, "raw": payload})
            else:
                for row in pending:
                    stats = row["stats"]
                    rep["stats_rows"] += int(bool(stats))
                    rep["stats_with_serve_return"] += int("p1_service_points_won" in stats)
                    fp.write(json.dumps(row) + "\n")
                rep["last_complete_week"] = start.isoformat()
                continue
            break
        else:
            if range_end is not None:
                rep["last_complete_week"] = range_end.isoformat()
    except Exception as exc:
        rep.update(stopped="retry", error=type(exc).__name__)
    finally:
        fp.close()
    rep["requests"] = client.request_count
    (out / "report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--max-requests", type=int, default=200)
    ap.add_argument("--out", default=".cache/itf-gapfill")
    a = ap.parse_args()
    if not 1 <= a.max_requests <= 10000:
        raise SystemExit("max-requests must be 1..10000")
    from tbt.providers.rapidapi import RapidTennisClient
    weeks = load_targets(a.history_dir, date.fromisoformat(a.start), date.fromisoformat(a.end))
    rep = run(RapidTennisClient(), weeks, Path(a.out), a.max_requests, range_end=date.fromisoformat(a.end))
    print("ITF_GAPFILL_STAGE " + json.dumps(rep))
    return 1 if rep.get("stopped") == "retry" else 0


if __name__ == "__main__":
    raise SystemExit(main())
