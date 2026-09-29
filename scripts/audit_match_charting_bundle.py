from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _members(archive: zipfile.ZipFile) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in archive.namelist():
        base = Path(name).name
        if base.startswith("charting-") and base.endswith(".csv"):
            result[base] = name
    return result


def _rows(archive: zipfile.ZipFile, member: str):
    with archive.open(member) as raw:
        text = (line.decode("utf-8-sig", errors="replace") for line in raw)
        yield from csv.DictReader(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--charting-zip", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repository", default="")
    ap.add_argument("--commit", default="")
    args = ap.parse_args()

    report = {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "repository": args.repository,
            "commit": args.commit,
            "archive": Path(args.charting_zip).name,
        },
        "api_requests": 0,
        "tours": {},
    }

    with zipfile.ZipFile(args.charting_zip) as archive:
        members = _members(archive)
        for code, tour in (("m", "atp"), ("w", "wta")):
            match_file = f"charting-{code}-matches.csv"
            match_member = members.get(match_file)
            if not match_member:
                raise SystemExit(f"Missing {match_file}")

            match_ids: list[str] = []
            dates: list[str] = []
            duplicates: Counter[str] = Counter()
            for row in _rows(archive, match_member):
                mid = str(row.get("match_id") or "").strip()
                if not mid:
                    continue
                match_ids.append(mid)
                duplicates[mid] += 1
                raw_date = "".join(ch for ch in str(row.get("Date") or "") if ch.isdigit())
                if len(raw_date) == 8:
                    dates.append(raw_date)
            unique_matches = set(match_ids)

            point_files = sorted(
                name for name in members
                if name.startswith(f"charting-{code}-points-")
            )
            point_rows = 0
            point_matches: set[str] = set()
            point_winner_values: Counter[str] = Counter()
            for filename in point_files:
                for row in _rows(archive, members[filename]):
                    point_rows += 1
                    mid = str(row.get("match_id") or "").strip()
                    if mid:
                        point_matches.add(mid)
                    winner = str(row.get("PtWinner") or "").strip()
                    if winner:
                        point_winner_values[winner] += 1

            groups: dict[str, dict] = {}
            group_sets: list[set[str]] = []
            prefix = f"charting-{code}-stats-"
            for filename in sorted(members):
                if not filename.startswith(prefix):
                    continue
                group = filename[len(prefix):-4]
                row_count = 0
                mids: set[str] = set()
                rows_seen: Counter[str] = Counter()
                players: defaultdict[str, set[str]] = defaultdict(set)
                for row in _rows(archive, members[filename]):
                    row_count += 1
                    mid = str(row.get("match_id") or "").strip()
                    if not mid:
                        continue
                    mids.add(mid)
                    label = str(row.get("row") or row.get("set") or "").strip()
                    if label:
                        rows_seen[label] += 1
                    player = str(row.get("player") or "").strip()
                    if player:
                        players[mid].add(player)
                both_players = sum(1 for mid in mids if len(players.get(mid, set())) >= 2)
                groups[group] = {
                    "rows": row_count,
                    "matches": len(mids),
                    "match_coverage_pct": round(
                        100.0 * len(mids & unique_matches) / max(1, len(unique_matches)), 3
                    ),
                    "matches_with_two_players": both_players,
                    "common_rows": dict(rows_seen.most_common(12)),
                }
                group_sets.append(mids)

            all_group_matches = set.intersection(*group_sets) if group_sets else set()
            report["tours"][tour] = {
                "match_rows": len(match_ids),
                "unique_matches": len(unique_matches),
                "duplicate_match_rows": sum(
                    count - 1 for count in duplicates.values() if count > 1
                ),
                "date_start": min(dates) if dates else None,
                "date_end": max(dates) if dates else None,
                "point_files": point_files,
                "point_rows": point_rows,
                "matches_with_points": len(point_matches),
                "point_coverage_pct": round(
                    100.0 * len(point_matches & unique_matches) / max(1, len(unique_matches)), 3
                ),
                "point_winner_values": dict(point_winner_values),
                "stat_groups": groups,
                "matches_with_all_stat_groups": len(all_group_matches & unique_matches),
                "all_group_coverage_pct": round(
                    100.0 * len(all_group_matches & unique_matches) / max(1, len(unique_matches)), 3
                ),
            }

    atp = report["tours"].get("atp", {})
    wta = report["tours"].get("wta", {})
    report["totals"] = {
        "unique_matches": int(atp.get("unique_matches", 0))
        + int(wta.get("unique_matches", 0)),
        "point_rows": int(atp.get("point_rows", 0))
        + int(wta.get("point_rows", 0)),
        "matches_with_points": int(atp.get("matches_with_points", 0))
        + int(wta.get("matches_with_points", 0)),
        "api_requests": 0,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
