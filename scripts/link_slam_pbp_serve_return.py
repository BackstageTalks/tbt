"""Audit and stage Grand Slam point-by-point serve/return enrichment.

Source format: Jeff Sackmann tennis_slam_pointbypoint-style matches/points CSVs.
This is read-only against canonical history. It derives only service_points_won
and return_points_won from explicit PointServer/PointWinner columns and emits
the strict offline serve-return stage schema.

Link policy: exact calendar year + Grand Slam identity + exact player pair,
with a unique canonical candidate. No fuzzy player matching.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder
from tbt.data.offline_odds import norm_text


SLAM_ALIASES = {
    "ausopen": ("australian open", "australianopen"),
    "frenchopen": ("roland garros", "french open", "frenchopen"),
    "wimbledon": ("wimbledon",),
    "usopen": ("us open", "u s open", "usopen"),
}


def _slam_from_filename(path: Path) -> str:
    name=path.name.lower()
    for slam in SLAM_ALIASES:
        if f"-{slam}-" in name:
            return slam
    return ""


def _year_from_filename(path: Path) -> int | None:
    m=re.match(r"(\d{4})-", path.name)
    return int(m.group(1)) if m else None


def _is_slam_tournament(name: object, slam: str) -> bool:
    n=norm_text(name)
    return any(alias in n for alias in SLAM_ALIASES[slam])


def _quality(stats: dict) -> bool:
    for side in ("p1","p2"):
        serve, ret = FeatureBuilder._extract_quality(stats or {}, side)
        if serve is None or ret is None:
            return False
    return True


def _signature(match):
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _field(row, names):
    for name in names:
        if name in row and str(row.get(name) or "").strip()!="":
            return row.get(name)
    return None


def _as_side(value):
    text=str(value or "").strip()
    if text in {"1","P1","p1","player1","Player1"}:
        return 1
    if text in {"2","P2","p2","player2","Player2"}:
        return 2
    try:
        x=int(float(text))
        return x if x in (1,2) else None
    except Exception:
        return None


def _point_stats(points_path: Path, counts: Counter):
    per=defaultdict(lambda:{
        1:{"service_points":0,"service_won":0,"return_points":0,"return_won":0},
        2:{"service_points":0,"service_won":0,"return_points":0,"return_won":0},
    })
    with points_path.open("r",encoding="utf-8-sig",newline="") as fh:
        reader=csv.DictReader(fh)
        fields=set(reader.fieldnames or [])
        match_cols=("match_id","MatchID","matchid")
        server_cols=("PointServer","point_server","server","Server")
        winner_cols=("PointWinner","point_winner","winner","Winner")
        if not any(x in fields for x in match_cols):
            raise SystemExit(f"{points_path}: missing match id column; fields={sorted(fields)}")
        if not any(x in fields for x in server_cols):
            raise SystemExit(f"{points_path}: missing point server column; fields={sorted(fields)}")
        if not any(x in fields for x in winner_cols):
            raise SystemExit(f"{points_path}: missing point winner column; fields={sorted(fields)}")
        for row in reader:
            counts["point_rows"] += 1
            mid=str(_field(row,match_cols) or "").strip()
            server=_as_side(_field(row,server_cols))
            winner=_as_side(_field(row,winner_cols))
            if not mid or server not in (1,2) or winner not in (1,2):
                counts["invalid_point_rows"] += 1
                continue
            receiver=3-server
            per[mid][server]["service_points"] += 1
            per[mid][receiver]["return_points"] += 1
            if winner == server:
                per[mid][server]["service_won"] += 1
            else:
                per[mid][receiver]["return_won"] += 1
    out={}
    for mid,sides in per.items():
        if any(sides[s]["service_points"]<=0 or sides[s]["return_points"]<=0 for s in (1,2)):
            counts["point_matches_missing_denominator"] += 1
            continue
        out[mid]={
            1:{
                "service_points_won":sides[1]["service_won"]/sides[1]["service_points"],
                "return_points_won":sides[1]["return_won"]/sides[1]["return_points"],
            },
            2:{
                "service_points_won":sides[2]["service_won"]/sides[2]["service_points"],
                "return_points_won":sides[2]["return_won"]/sides[2]["return_points"],
            },
        }
    counts["point_matches_usable"]=len(out)
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--source-dir",required=True)
    ap.add_argument("--out-dir",required=True)
    args=ap.parse_args()

    out=Path(args.out_dir)
    out.mkdir(parents=True,exist_ok=True)
    matches,safety=sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    # Canonical index by year + slam + exact normalized pair.
    index=defaultdict(list)
    for m in matches:
        year=m.scheduled_at.year
        pair=tuple(sorted((norm_text(m.player1_name),norm_text(m.player2_name))))
        for slam in SLAM_ALIASES:
            if _is_slam_tournament(m.tournament,slam):
                index[(year,slam,pair)].append(m)

    counts=Counter()
    staged=[]
    review=[]
    before=sum(1 for m in matches if _quality(dict(m.stats or {})))
    added=0

    source=Path(args.source_dir)
    files=sorted(source.glob("*-matches.csv"))
    counts["match_files"]=len(files)
    for match_path in files:
        if any(token in match_path.name for token in ("-doubles","-mixed")):
            continue
        year=_year_from_filename(match_path)
        slam=_slam_from_filename(match_path)
        points_path=match_path.with_name(match_path.name.replace("-matches.csv","-points.csv"))
        if year is None or not slam or not points_path.is_file():
            counts["source_file_pairs_skipped"] += 1
            continue
        pstats=_point_stats(points_path,counts)
        with match_path.open("r",encoding="utf-8-sig",newline="") as fh:
            for row in csv.DictReader(fh):
                counts["source_match_rows"] += 1
                mid=str(row.get("match_id") or "").strip()
                p1=str(row.get("player1") or "").strip()
                p2=str(row.get("player2") or "").strip()
                if not mid or not p1 or not p2 or mid not in pstats:
                    counts["source_match_unusable"] += 1
                    continue
                pair=tuple(sorted((norm_text(p1),norm_text(p2))))
                candidates=index.get((year,slam,pair),[])
                if len(candidates)!=1:
                    key="unmatched" if not candidates else "ambiguous"
                    counts[key]+=1
                    if candidates:
                        review.append({"source_match_id":mid,"reason":key,"candidate_match_ids":[str(x.match_id) for x in candidates]})
                    continue
                m=candidates[0]
                mp1,mp2=norm_text(m.player1_name),norm_text(m.player2_name)
                if norm_text(p1)==mp1 and norm_text(p2)==mp2:
                    mapping=((1,"p1"),(2,"p2"))
                elif norm_text(p1)==mp2 and norm_text(p2)==mp1:
                    mapping=((1,"p2"),(2,"p1"))
                else:
                    counts["orientation_failed"]+=1
                    continue
                incoming={}
                for src_side,prefix in mapping:
                    incoming[f"{prefix}_service_points_won"]=pstats[mid][src_side]["service_points_won"]
                    incoming[f"{prefix}_return_points_won"]=pstats[mid][src_side]["return_points_won"]
                existing=dict(m.stats or {})
                conflicts=[
                    k for k,v in incoming.items()
                    if existing.get(k) is not None and abs(float(existing[k])-float(v))>0.02
                ]
                if conflicts:
                    counts["stat_conflict_matches"] += 1
                    review.append({"source_match_id":mid,"reason":"stat_conflicts","match_id":str(m.match_id),"keys":conflicts})
                    continue
                clean={k:v for k,v in incoming.items() if existing.get(k) is None}
                if not clean:
                    counts["already_present"]+=1
                    continue
                projected=dict(existing); projected.update(clean)
                before_ready=_quality(existing)
                after_ready=_quality(projected)
                if after_ready and not before_ready:
                    added+=1
                staged.append({
                    "schema":1,
                    "match_id":str(m.match_id),
                    "canonical":_signature(m),
                    "incoming_stats":clean,
                    "provenance":[{
                        "source":"jeff_sackmann_slam_pointbypoint",
                        "source_match_id":mid,
                        "evidence":["year_exact","grand_slam_exact","player_pair_exact","explicit_point_server_winner"],
                    }],
                    "import_ready":True,
                })
                counts["staged_matches"]+=1

    report={
        "schema":1,
        "canonical_rows":len(matches),
        "quality_ready_before":before,
        "quality_ready_projected_after":before+added,
        "quality_ready_projected_added":added,
        "counts":dict(counts),
        "production_mutated":False,
        "api_requests":0,
        "source_policy":"Jeff Sackmann Grand Slam PBP mirror, CC BY-NC-SA 4.0; server/winner point facts only",
        "link_policy":"exact year + Grand Slam + exact player pair; canonical candidate must be unique",
    }
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    for name,rows in (("auto_linked.jsonl",staged),("review.jsonl",review)):
        with (out/name).open("w",encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row,ensure_ascii=False)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
