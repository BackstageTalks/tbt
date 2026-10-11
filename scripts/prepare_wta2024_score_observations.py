"""Checksum-pinned WTA 2024 TennisExplorer finished-set score observations.

Preserves score facts with source-specific IDs only. Does not invent player IDs,
match links, prematch snapshots, provider authority or canonical writes.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from pathlib import Path

SOURCE_MEMBER = "data/tennisexplorer/results/wta-single/2024.csv"
SOURCE_SHA256 = "27c779c73bcfaf089e362f3480c4201f032e15fefbc3a0fadaa39bfce9f5956b"
EXPECTED_ROWS = 45143

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as inp:
        for block in iter(lambda: inp.read(2 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def score(cell):
    value = str(cell or "").strip().replace(" ", "")
    # TennisExplorer tie-break is displayed as e.g. 7(5) -- five is NOT games.
    m = re.fullmatch(r"([0-7])(?:\(([0-9]{1,2})\))?", value)
    if not m:
        return None
    return int(m.group(1))

def parse_completed(row):
    try:
        wins = (int(row["side1_sets_won"]), int(row["side2_sets_won"]))
    except (KeyError, TypeError, ValueError):
        return None
    if wins not in {(2,0),(2,1),(0,2),(1,2)}:
        return None
    sets = []
    for set_no in range(1, 6):
        a,b = score(row.get(f"set{set_no}_side1")),score(row.get(f"set{set_no}_side2"))
        if a is None and b is None:
            continue
        if a is None or b is None:
            return None
        # Standard set games; super-tiebreak/fifth-set exceptional scoring
        # is not a standard games count. Keep it in source raw, not here.
        winner = (a > b) - (a < b)
        if winner == 0 or max(a,b) < 6 or (max(a,b)==6 and abs(a-b)<2) or max(a,b)>7:
            return None
        if max(a,b)==7 and min(a,b) not in (5,6):
            return None
        sets.append((a,b))
    if len(sets) != sum(wins):
        return None
    counted=(sum(a>b for a,b in sets),sum(b>a for a,b in sets))
    if counted!=wins:
        return None
    return {
        "completed_sets":len(sets),
        "side1_sets":wins[0],"side2_sets":wins[1],
        "side1_games":sum(a for a,_ in sets),
        "side2_games":sum(b for _,b in sets),
        "total_games":sum(a+b for a,b in sets),
        "set_scores":sets,
    }

def extract(archive, expected_sha, output):
    if expected_sha != SOURCE_SHA256 or sha(archive) != expected_sha:
        raise ValueError("Source digest disagrees with pinned WTA archive")
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    counts=Counter()
    ids=set()
    stage=output/"source_score_observations.jsonl"
    with tarfile.open(archive,"r:gz") as tar, stage.open("w",encoding="utf-8") as sink:
        item=tar.getmember(SOURCE_MEMBER)
        if not item.isfile() or item.size>100_000_000:
            raise ValueError("Missing or unsafe WTA source CSV")
        stream=tar.extractfile(item)
        if stream is None:
            raise ValueError("Source member unreadable")
        with stream,io.TextIOWrapper(stream,encoding="utf-8-sig",newline="") as src:
            for row in csv.DictReader(src):
                counts["source_rows"]+=1
                mid=str(row.get("match_id") or "").strip()
                if not mid or mid in ids:
                    raise ValueError("Missing or duplicate WTA source identity")
                ids.add(mid)
                if row.get("category")!="wta-single" or row.get("date","")[:4]!="2024":
                    raise ValueError("Cross-year or cross-discipline contamination")
                result=parse_completed(row)
                if result is None:
                    counts["unverified_complete_scores"]+=1
                    continue
                obs={
                    "schema":1,"source":"TennisExplorer","category":"wta-single",
                    "source_match_id":mid,"source_date":row["date"],
                    "source_tournament":row.get("tournament"),
                    "source_player_sides":[row.get("side1_players_json"),row.get("side2_players_json")],
                    "result":result,"source_archive_sha256":expected_sha,
                    "available_at":None,"model_eligible":False,
                    "canonical_match_id":None,"canonical_link_status":"source_scoped_only",
                }
                sink.write(json.dumps(obs,sort_keys=True,ensure_ascii=False)+"\n")
                counts["parsed_completed_score_rows"]+=1
                counts["source_scoped_games_observations"]+=1
    if counts["source_rows"]!=EXPECTED_ROWS:
        raise ValueError("Wrong source row count")
    out={"schema":1,"status":"SOURCE_SCOPED_SCORES_PREPARED_NOT_CANONICAL",
         "source_sha256":expected_sha,"stage_sha256":sha(stage),
         "counts":dict(counts),"cdb_writes":0,"trained_or_promoted":False,
         "next_step":"Require unique player IDs, exact event ID, date/venue and winner corroboration before canonical null-cell replay"}
    (output/"report.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--source-sha256",default=SOURCE_SHA256)
    p.add_argument("--out",type=Path,required=True)
    print(json.dumps(extract(**vars(p.parse_args())),sort_keys=True))

if __name__=="__main__":
    main()
