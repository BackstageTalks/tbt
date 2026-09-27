"""Read-only MCP overlap experiment. No production writes or paid API calls."""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from _bootstrap import ROOT
from audit_environment_release import download_committed_history
from audit_statistics_inventory import _quality_ready
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/master/"
ATTRIBUTION = "The Tennis Abstract Match Charting Project; CC BY-NC-SA 4.0"


def normalize(value):
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def get_csv(filename):
    with urlopen(BASE + filename, timeout=90) as response:
        return list(csv.DictReader(io.TextIOWrapper(response, encoding="utf-8-sig")))


def valid_pair(rows):
    if len(rows) != 2:
        return False
    for row in rows:
        try:
            serve = int(row["serve_pts"])
            ret = int(row["return_pts"])
            sw = int(row["first_won"]) + int(row["second_won"])
            rw = int(row["return_pts_won"])
        except (ValueError, TypeError, KeyError):
            return False
        if serve <= 0 or ret <= 0 or not 0 <= sw <= serve or not 0 <= rw <= ret:
            return False
    return True


def run(matches, source):
    by_key = defaultdict(list)
    for m in matches:
        if m.is_completed:
            key = (str(m.tour).lower(), m.scheduled_at.date().isoformat(),
                   frozenset((normalize(m.player1_name), normalize(m.player2_name))))
            by_key[key].append(m)
    counters = Counter()
    by_tour = defaultdict(Counter)
    examples = []
    staged = []
    seen_history_ids = set()
    for tour, gender in (("atp", "m"), ("wta", "w")):
        metadata = get_csv(f"charting-{gender}-matches.csv")
        overview = get_csv(f"charting-{gender}-stats-Overview.csv")
        stats = defaultdict(list)
        for row in overview:
            if row.get("set") == "Total":
                stats[row["match_id"]].append(row)
        for row in metadata:
            match_id = row.get("match_id", "")
            date = match_id[:8]
            if not re.fullmatch(r"\d{8}", date):
                counters["bad_mcp_date"] += 1
                continue
            try:
                date = datetime.strptime(date, "%Y%m%d").date().isoformat()
            except ValueError:
                counters["bad_mcp_date"] += 1
                continue
            names = (normalize(row.get("Player 1", "")), normalize(row.get("Player 2", "")))
            if not all(names) or names[0] == names[1]:
                counters["missing_mcp_names"] += 1
                continue
            counters["mcp_matches"] += 1
            key = (tour, date, frozenset(names))
            candidates = by_key.get(key, [])
            if len(candidates) != 1:
                counters["no_unique_history_match" if not candidates else "ambiguous_history_match"] += 1
                continue
            m = candidates[0]
            if not valid_pair(stats.get(match_id, [])):
                counters["matched_without_complete_overview"] += 1
                continue
            # Reject duplicated MCP entries pointing at one canonical history row.
            if str(m.match_id) in seen_history_ids:
                counters["duplicate_mcp_history_target"] += 1
                continue
            seen_history_ids.add(str(m.match_id))
            counters["matched_complete_overview"] += 1
            by_tour[tour]["matched_complete_overview"] += 1
            already = _quality_ready(m.stats or {}, "p1") and _quality_ready(m.stats or {}, "p2")
            if already:
                counters["already_ready"] += 1
                by_tour[tour]["already_ready"] += 1
            else:
                # Stage source facts only. Do not overwrite or promote model inputs.
                mapped = {}
                for record in stats[match_id]:
                    name = normalize(record.get("player", ""))
                    if name == normalize(m.player1_name):
                        prefix = "p1"
                    elif name == normalize(m.player2_name):
                        prefix = "p2"
                    else:
                        mapped = {}
                        break
                    if prefix in mapped:
                        mapped = {}
                        break
                    mapped[prefix] = {k: int(record[k]) for k in ("serve_pts", "first_won", "second_won", "return_pts", "return_pts_won")}
                if set(mapped) != {"p1", "p2"}:
                    counters["rejected_player_orientation"] += 1
                    continue
                counters["potential_new_complete"] += 1
                staged.append({"history_match_id": str(m.match_id), "mcp_match_id": match_id,
                               "tour": tour, "date": date, "players": mapped,
                               "source": ATTRIBUTION, "status": "research_staging_not_imported"})
                by_tour[tour]["potential_new_complete"] += 1
                if len(examples) < 30:
                    examples.append({"history_match_id": str(m.match_id), "mcp_match_id": match_id,
                                     "tour": tour, "date": date})
    return {"schema": 1, "read_only": True, "paid_api_calls": 0,
            "source": BASE, "attribution": ATTRIBUTION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "counts": dict(counters), "by_tour": {k: dict(v) for k,v in by_tour.items()},
            "potential_new_complete_is_upper_bound": True,
            "matching": "exact normalized player names + exact date + tour; unique matches only",
            "limitations": ["No production import", "Tournament and player ID verification required before import",
                            "CC BY-NC-SA 4.0 attribution and noncommercial terms apply"],
            "examples": examples, "staged_candidates": staged}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--out", default=".cache/tbt/mcp-overlap/report.json")
    args = parser.parse_args()
    directory = ROOT / ".cache/tbt/mcp-overlap/history"
    download_committed_history(ReleaseStore(args.data_repository, "tbt-data-v1", directory), directory)
    matches, safety = sanitize_history_identities(load_partitions(directory))
    report = run(matches, BASE)
    report["identity_safety"] = safety
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = report.pop("staged_candidates")
    stage_path = path.with_name("mcp_staged_candidates.json")
    stage_path.write_text(json.dumps({"source": ATTRIBUTION, "read_only": True, "candidates": staged}, ensure_ascii=False, indent=2), encoding="utf-8")
    report["staged_candidates_count"] = len(staged)
    report["staged_candidates_artifact"] = stage_path.name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
