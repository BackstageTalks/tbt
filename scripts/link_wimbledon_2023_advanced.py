"""Build a private advanced point-level sidecar from the CC BY 4.0
Figshare Wimbledon 2023 dataset (DOI 10.6084/m9.figshare.25511917).

This source is intentionally NOT written into canonical history. Recent matches
already have overlapping basic statistics and the unique value here is richer
point context (serve speed/placement, return depth, rally length, movement,
winners/errors/net/break points). Exact player-pair + event/year + winner
identity is required; no fuzzy matching is allowed.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text

SOURCE="figshare_wimbledon_2023_momentum"
DOI="10.6084/m9.figshare.25511917"
LICENSE="CC BY 4.0"

REQUIRED={
    "match_id","player1","player2","elapsed_time","set_no","game_no","point_no",
    "p1_sets","p2_sets","p1_games","p2_games","p1_score","p2_score","server",
    "serve_no","point_victor","p1_points_won","p2_points_won","game_victor",
    "set_victor","p1_ace","p2_ace","p1_winner","p2_winner","winner_shot_type",
    "p1_double_fault","p2_double_fault","p1_unf_err","p2_unf_err","p1_net_pt",
    "p2_net_pt","p1_net_pt_won","p2_net_pt_won","p1_break_pt","p2_break_pt",
    "p1_break_pt_won","p2_break_pt_won","p1_break_pt_missed","p2_break_pt_missed",
    "p1_distance_run","p2_distance_run","rally_count","speed_mph",
    "ServeWidth","ServeDepth","ReturnDepth",
}


def _num(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        x=float(value)
    except (TypeError,ValueError):
        return None
    return x if math.isfinite(x) else None


def _int(value):
    x=_num(value)
    if x is None or not x.is_integer():
        return None
    return int(x)


def _safe_rate(num,den):
    if den<=0:
        return None
    x=num/den
    return x if 0<=x<=1 else None


def _winner_from_sets(group: pd.DataFrame) -> int|None:
    counts=Counter(
        x for x in (_int(v) for v in group["set_victor"])
        if x in {1,2}
    )
    if counts[1]==counts[2]:
        return None
    return 1 if counts[1]>counts[2] else 2


def _validate_group(group: pd.DataFrame) -> list[str]:
    issues=[]
    p1={str(v).strip() for v in group["player1"].dropna() if str(v).strip()}
    p2={str(v).strip() for v in group["player2"].dropna() if str(v).strip()}
    if len(p1)!=1 or len(p2)!=1 or p1==p2:
        issues.append("player_identity_not_constant")
    ordered=group.sort_values("point_no",kind="stable")
    point_numbers=[_int(v) for v in ordered["point_no"]]
    if any(v is None for v in point_numbers) or len(set(point_numbers))!=len(point_numbers):
        issues.append("point_number_invalid_or_duplicate")
    prev1=prev2=0
    for _,row in ordered.iterrows():
        no=_int(row["point_no"])
        a=_int(row["p1_points_won"])
        b=_int(row["p2_points_won"])
        victor=_int(row["point_victor"])
        server=_int(row["server"])
        serve_no=_int(row["serve_no"])
        if no is None or a is None or b is None or a+b!=no:
            issues.append("cumulative_points_do_not_equal_point_no")
            break
        if victor not in {1,2} or server not in {1,2} or serve_no not in {1,2}:
            issues.append("invalid_point_actor_or_serve_no")
            break
        if a-prev1 != (1 if victor==1 else 0) or b-prev2 != (1 if victor==2 else 0):
            issues.append("point_victor_cumulative_mismatch")
            break
        prev1,prev2=a,b

        if _int(row["p1_ace"])==1 and server!=1:
            issues.append("p1_ace_when_not_serving"); break
        if _int(row["p2_ace"])==1 and server!=2:
            issues.append("p2_ace_when_not_serving"); break
        if _int(row["p1_double_fault"])==1 and server!=1:
            issues.append("p1_df_when_not_serving"); break
        if _int(row["p2_double_fault"])==1 and server!=2:
            issues.append("p2_df_when_not_serving"); break
        if _int(row["p1_break_pt"])==1 and server!=2:
            issues.append("p1_breakpoint_when_not_returning"); break
        if _int(row["p2_break_pt"])==1 and server!=1:
            issues.append("p2_breakpoint_when_not_returning"); break
    if _winner_from_sets(group) is None:
        issues.append("source_match_winner_unresolved")
    return issues


def _canonical_index(matches):
    index=defaultdict(list)
    for m in matches:
        if int(m.scheduled_at.year)!=2023:
            continue
        if "wimbledon" not in norm_text(m.tournament):
            continue
        pair=tuple(sorted((norm_text(m.player1_name),norm_text(m.player2_name))))
        if not all(pair) or pair[0]==pair[1]:
            continue
        index[pair].append(m)
    return index


def _canonical_winner_side(match)->int|None:
    if str(match.winner_id or "")==str(match.player1_id):
        return 1
    if str(match.winner_id or "")==str(match.player2_id):
        return 2
    return None


def _source_to_canonical_orientation(group: pd.DataFrame, match)->str|None:
    p1=str(group["player1"].iloc[0]).strip()
    p2=str(group["player2"].iloc[0]).strip()
    if norm_text(p1)==norm_text(match.player1_name) and norm_text(p2)==norm_text(match.player2_name):
        return "direct"
    if norm_text(p1)==norm_text(match.player2_name) and norm_text(p2)==norm_text(match.player1_name):
        return "reversed"
    return None


def _aggregate(group: pd.DataFrame, side: int)->dict[str,Any]:
    server_rows=group[pd.to_numeric(group["server"],errors="coerce")==side]
    return_rows=group[pd.to_numeric(group["server"],errors="coerce")!=side]
    victor=pd.to_numeric(group["point_victor"],errors="coerce")
    serve_no=pd.to_numeric(server_rows["serve_no"],errors="coerce")
    first=server_rows[serve_no==1]
    second=server_rows[serve_no==2]

    def won(frame):
        if frame.empty: return None
        return float((pd.to_numeric(frame["point_victor"],errors="coerce")==side).mean())

    prefix=f"p{side}_"
    speeds=[
        float(v) for v in pd.to_numeric(server_rows["speed_mph"],errors="coerce").dropna()
        if 40<=float(v)<=170
    ]
    first_speeds=[
        float(v) for v in pd.to_numeric(first["speed_mph"],errors="coerce").dropna()
        if 40<=float(v)<=170
    ]
    second_speeds=[
        float(v) for v in pd.to_numeric(second["speed_mph"],errors="coerce").dropna()
        if 40<=float(v)<=170
    ]
    bp=int(pd.to_numeric(group[prefix+"break_pt"],errors="coerce").fillna(0).sum())
    bp_won=int(pd.to_numeric(group[prefix+"break_pt_won"],errors="coerce").fillna(0).sum())
    net=int(pd.to_numeric(group[prefix+"net_pt"],errors="coerce").fillna(0).sum())
    net_won=int(pd.to_numeric(group[prefix+"net_pt_won"],errors="coerce").fillna(0).sum())
    points=len(group)
    side_points=int((victor==side).sum())

    def cat_counts(series):
        return {
            str(k):int(v)
            for k,v in Counter(str(x) for x in series.dropna() if str(x).strip()).items()
        }

    return {
        "points_won":side_points,
        "points_played":points,
        "service_points":int(len(server_rows)),
        "return_points":int(len(return_rows)),
        "service_points_won_rate":won(server_rows),
        "return_points_won_rate":won(return_rows),
        "first_serve_point_share":_safe_rate(len(first),len(server_rows)),
        "first_serve_points_won_rate":won(first),
        "second_serve_points_won_rate":won(second),
        "aces":int(pd.to_numeric(group[prefix+"ace"],errors="coerce").fillna(0).sum()),
        "double_faults":int(pd.to_numeric(group[prefix+"double_fault"],errors="coerce").fillna(0).sum()),
        "winners":int(pd.to_numeric(group[prefix+"winner"],errors="coerce").fillna(0).sum()),
        "unforced_errors":int(pd.to_numeric(group[prefix+"unf_err"],errors="coerce").fillna(0).sum()),
        "unforced_error_rate":_safe_rate(
            int(pd.to_numeric(group[prefix+"unf_err"],errors="coerce").fillna(0).sum()),points
        ),
        "net_points":net,
        "net_points_won":net_won,
        "net_points_win_rate":_safe_rate(net_won,net),
        "break_points":bp,
        "break_points_won":bp_won,
        "break_point_return_win_rate":_safe_rate(bp_won,bp),
        "serve_speed_mph_mean":sum(speeds)/len(speeds) if speeds else None,
        "serve_speed_mph_median":median(speeds) if speeds else None,
        "serve_speed_mph_max":max(speeds) if speeds else None,
        "first_serve_speed_mph_mean":sum(first_speeds)/len(first_speeds) if first_speeds else None,
        "second_serve_speed_mph_mean":sum(second_speeds)/len(second_speeds) if second_speeds else None,
        "serve_width_counts":cat_counts(server_rows["ServeWidth"]),
        "serve_depth_counts":cat_counts(server_rows["ServeDepth"]),
        "return_depth_counts":cat_counts(return_rows["ReturnDepth"]),
        "winner_shot_type_counts":cat_counts(group.loc[pd.to_numeric(group[prefix+"winner"],errors="coerce")==1,"winner_shot_type"]),
        "distance_run_total":float(pd.to_numeric(group[prefix+"distance_run"],errors="coerce").fillna(0).sum()),
        "distance_run_mean":float(pd.to_numeric(group[prefix+"distance_run"],errors="coerce").fillna(0).mean()),
        "rally_count_mean":float(pd.to_numeric(group["rally_count"],errors="coerce").fillna(0).mean()),
        "rally_count_median":float(pd.to_numeric(group["rally_count"],errors="coerce").fillna(0).median()),
    }


def _safe_scalar(value):
    try:
        if pd.isna(value): return None
    except Exception:
        pass
    if isinstance(value,(str,bool,int)): return value
    try:
        x=float(value)
        if math.isfinite(x): return int(x) if x.is_integer() else x
    except Exception:
        pass
    return str(value)


def build(*,workbook:Path,history_dir:Path,out_dir:Path)->dict[str,Any]:
    frame=pd.read_excel(workbook,sheet_name=0)
    missing=sorted(REQUIRED-set(map(str,frame.columns)))
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    matches,safety=sanitize_history_identities(load_partitions(history_dir))
    if safety.get("quarantined_rows"):
        raise RuntimeError("canonical identity quarantine is non-empty")
    index=_canonical_index(matches)
    counts=Counter()
    sidecar=[]
    review=[]

    for source_mid,group in frame.groupby("match_id",sort=False):
        counts["source_matches"]+=1
        counts["source_point_rows"]+=len(group)
        issues=_validate_group(group)
        if issues:
            counts["source_integrity_rejected"]+=1
            review.append({"source_match_id":str(source_mid),"reason":"source_integrity","issues":issues})
            continue
        p1=str(group["player1"].iloc[0]).strip()
        p2=str(group["player2"].iloc[0]).strip()
        pair=tuple(sorted((norm_text(p1),norm_text(p2))))
        candidates=list(index.get(pair,[]))
        source_winner=_winner_from_sets(group)

        accepted=[]
        for match in candidates:
            orientation=_source_to_canonical_orientation(group,match)
            cw=_canonical_winner_side(match)
            if orientation is None or cw is None or source_winner is None:
                continue
            source_winner_canonical=source_winner if orientation=="direct" else (2 if source_winner==1 else 1)
            if source_winner_canonical!=cw:
                continue
            accepted.append((match,orientation))
        if len(accepted)!=1:
            counts["unmatched" if not accepted else "ambiguous"]+=1
            review.append({
                "source_match_id":str(source_mid),
                "reason":"unmatched" if not accepted else "ambiguous",
                "players":[p1,p2],
                "candidate_match_ids":[str(m.match_id) for m,_ in accepted],
            })
            continue
        match,orientation=accepted[0]
        src1=_aggregate(group,1)
        src2=_aggregate(group,2)
        c1,c2=(src1,src2) if orientation=="direct" else (src2,src1)

        # Break-point serve win is the complement of the opponent's return BP win.
        c1["break_point_serve_win_rate"]=(
            1-c2["break_point_return_win_rate"]
            if c2["break_point_return_win_rate"] is not None else None
        )
        c2["break_point_serve_win_rate"]=(
            1-c1["break_point_return_win_rate"]
            if c1["break_point_return_win_rate"] is not None else None
        )

        point_rows=[
            {str(k):_safe_scalar(v) for k,v in row.items()}
            for row in group.sort_values("point_no",kind="stable").to_dict(orient="records")
        ]
        sidecar.append({
            "schema":1,
            "match_id":str(match.match_id),
            "source_match_id":str(source_mid),
            "tour":str(match.tour or "").lower(),
            "scheduled_date_utc":match.scheduled_at.date().isoformat(),
            "tournament":str(match.tournament or ""),
            "round":str(match.round_name or ""),
            "player1_id":str(match.player1_id),
            "player1_name":str(match.player1_name),
            "player2_id":str(match.player2_id),
            "player2_name":str(match.player2_name),
            "source_orientation":orientation,
            "player1_advanced":c1,
            "player2_advanced":c2,
            "points":point_rows,
            "source":SOURCE,
            "doi":DOI,
            "license":LICENSE,
            "identity_evidence":"2023+Wimbledon+exact normalized full-name pair+source/canonical winner+unique canonical candidate",
            "feature_policy":"post_match_research_only; any player-state feature must be lagged strictly after match completion",
        })
        counts["linked_matches"]+=1
        counts["linked_point_rows"]+=len(group)

    mids=[r["match_id"] for r in sidecar]
    if len(mids)!=len(set(mids)):
        raise RuntimeError("duplicate canonical links in advanced sidecar")

    out_dir.mkdir(parents=True,exist_ok=True)
    with gzip.open(out_dir/"wimbledon-2023-advanced-points.jsonl.gz","wt",encoding="utf-8") as h:
        for row in sidecar:
            h.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    with (out_dir/"review.jsonl").open("w",encoding="utf-8") as h:
        for row in review:
            h.write(json.dumps(row,ensure_ascii=False)+"\n")
    report={
        "schema":1,
        "status":"verified",
        "source":SOURCE,
        "doi":DOI,
        "license":LICENSE,
        "canonical_rows":len(matches),
        "counts":dict(counts),
        "identity_safety":safety,
        "production_mutated":False,
        "canonical_history_mutated":False,
        "model_promoted":False,
        "link_policy":"2023+Wimbledon+exact normalized full-name pair+source/canonical winner; unique candidate only; no fuzzy match",
        "feature_policy":"private post-match advanced sidecar; future pre-match use only via strictly lagged chronological player state",
    }
    (out_dir/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook",required=True)
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--out-dir",required=True)
    args=ap.parse_args()
    print(json.dumps(build(workbook=Path(args.workbook),history_dir=Path(args.history_dir),out_dir=Path(args.out_dir)),indent=2))


if __name__=="__main__":
    main()
