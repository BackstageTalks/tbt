#!/usr/bin/env python3
"""Real-data, SHA-pinned 2025 Sackmann vs canonical CDB read-only shadow.

This is a bounded research comparison, not an import preflight: a positive
candidate IS NOT an independently verified provider event or player ID.
No provider API, writer, canonical release mutation, model, or GitHub upload.
Aggregate-only output (no player/event rows). Uses a deterministic SHA sample.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from scripts.research import identity_v2 as ident
from scripts.research import shadow_identity_v2 as shadow

# Source bytes audited separately; pin to exactly that independent read-only run.
SOURCE_SHA = {
    "atp/atp_matches_2025.csv":"78c356ef9328b89ae58a17564d61c02cdad2a3a007f6b8af5cfc17992b11bb2d",
    "atp/atp_matches_futures_2025.csv":"54dd4611505feccd4976e42564f4d9d0796ebd86f64ad195a3ffc0ae0e9da294",
    "atp/atp_matches_qual_chall_2025.csv":"7690c576689d9cafc28d1b9f3293173e87220573db5fd2c47e3097f2ab505ec0",
    "wta/wta_matches_2025.csv":"e4eb002bc6d828b0bd21e04ed286e68722ddc8ccbbb27ea980bf62e938377f96",
    "wta/wta_matches_qual_itf_2025.csv":"af1b439684a55ae0f7cb42ed5da2b11985f08dac50ac68c06da4faa3ffe19da7",
}
CDB_SHA = "3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58"
CDB_ROWS = 90571


def _sha(path: Path):
    h=sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576),b""):
            h.update(block)
    return h.hexdigest()


def _date(value):
    if value is None:
        return ""
    if hasattr(value,"isoformat"):
        return value.date().isoformat() if hasattr(value,"date") else value.isoformat()
    return str(value)[:10]


def source_events(root: Path, *, sample_mod: int):
    counts=Counter()
    events=[]
    for rel, digest in SOURCE_SHA.items():
        path=root/rel
        if not path.is_file() or _sha(path)!=digest:
            raise ValueError("PINNED_SOURCE_SHA_MISMATCH:"+rel)
        tour="atp" if rel.startswith("atp/") else "wta"
        namespace="sackmann_2025_"+rel.replace("/","_")
        with path.open(encoding="utf-8-sig",newline="") as f:
            for lineno,row in enumerate(csv.DictReader(f),2):
                counts["source_rows"]+=1
                winner=str(row.get("winner_id") or "").strip()
                loser=str(row.get("loser_id") or "").strip()
                if not all((winner,loser,row.get("winner_name"),row.get("loser_name"))) or winner==loser:
                    counts["missing_native_identity"]+=1
                    continue
                day=str(row.get("tourney_date") or "")
                try:
                    played=datetime.strptime(day,"%Y%m%d").date().isoformat()
                except ValueError:
                    counts["missing_or_bad_start_date"]+=1
                    continue
                source_id=namespace+"|"+str(lineno)+"|"+str(row.get("tourney_id") or "")
                if int(sha256(source_id.encode()).hexdigest()[:12],16)%sample_mod:
                    continue
                p1=ident.Player(namespace,tour,winner,str(row["winner_name"]))
                p2=ident.Player(namespace,tour,loser,str(row["loser_name"]))
                try:
                    event=ident.Event(
                        namespace,source_id,tour,"singles",(p1,p2),
                        played,"tournament_start",str(row.get("tourney_name") or ""),
                        str(row.get("round") or ""),str(row.get("score") or ""),
                        winner,draw=("qual" if ("qual_" in rel or "_qual_" in rel) else ""),
                    )
                except ValueError:
                    counts["source_schema_quarantine"]+=1
                    continue
                events.append((rel,event))
                counts["sample_"+("atp" if tour=="atp" else "wta")]+=1
                counts["sample_"+rel]+=1
    if counts["source_rows"] != 56889:
        raise ValueError("PINNED_SOURCE_ROW_COUNT_MISMATCH:"+str(counts["source_rows"]))
    if not events:
        raise ValueError("Zero sample events")
    return events,counts


def canonical_events(path: Path):
    import pandas as pd
    if _sha(path)!=CDB_SHA:
        raise ValueError("PINNED_CDB_SHA_MISMATCH")
    cols=["match_id","tour","scheduled_at","player1_id","player2_id",
          "player1_name","player2_name","winner_id","tournament","round_name"]
    frame=pd.read_parquet(path,columns=cols)
    if len(frame)!=CDB_ROWS:
        raise ValueError("PINNED_CDB_ROW_COUNT_MISMATCH")
    output=[]
    counts=Counter()
    seen=set()
    for row in frame.itertuples(index=False,name=None):
        mid,tour,stamp,pid1,pid2,name1,name2,winner,tournament,round_name=row
        tour=str(tour or "").lower().strip()
        if tour not in ("atp","wta"):
            counts["other_tour"]+=1;continue
        if str(mid) in seen:
            raise ValueError("Duplicate CDB canonical event ID")
        seen.add(str(mid))
        if not all((str(pid1),str(pid2),str(name1),str(name2))) or str(pid1)==str(pid2):
            counts["invalid_cdb_pair"]+=1;continue
        when=_date(stamp)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",when):
            counts["invalid_cdb_time"]+=1;continue
        namespace="CDB_CANONICAL"
        try:
            players=(ident.Player(namespace,tour,str(pid1),str(name1)),
                     ident.Player(namespace,tour,str(pid2),str(name2)))
            x=ident.Event(namespace,str(mid),tour,"singles",players,when,
                "scheduled",str(tournament or ""),str(round_name or ""),
                winner_native_id=str(winner or ""))
        except ValueError:
            counts["invalid_cdb_schema"]+=1;continue
        output.append(x)
    counts["canonical_total_rows"]=len(frame)
    counts["canonical_usable_rows"]=len(output)
    return output,counts


def event_keys(event):
    # The source has player IDs in its *own namespace*. Candidate lookup only.
    a,b=event.players
    return a.names(),b.names()


def _query_keys(keys):
    # Broad search uses the same normalized/abbreviated aliases as identity_v2.
    # Avoid one-character-only name keys with global collisions.
    return [key for key in keys if key.startswith(("exact:","initials:","translit:"))
            and len(key)>=9]


def compare(source_rows, cdb, *, max_review_matches: int=1000):
    index=defaultdict(set)
    for i,event in enumerate(cdb):
        for p in event.players:
            for key in _query_keys(p.names()):
                index[(event.tour,key)].add(i)
    metrics=Counter()
    by_family=defaultdict(Counter)
    for family,source in source_rows:
        metrics["sample_events"]+=1
        keys_a,keys_b=event_keys(source)
        a=set().union(*(index.get((source.tour,key),()) for key in _query_keys(keys_a)))
        b=set().union(*(index.get((source.tour,key),()) for key in _query_keys(keys_b)))
        intersection=sorted(a & b)
        metrics["candidate_index_possible"]+=bool(intersection)
        metrics["candidate_index_size_total"]+=len(intersection)
        if len(intersection)>max_review_matches:
            metrics["too_many_context_candidates"]+=1
            continue
        context=[cdb[i] for i in intersection]
        old=[x for x in context if shadow.proxy_old_match(source,x)]
        new=ident.discover_events(source,context)
        if not ident.no_write_contract(new):
            raise AssertionError("Research linker claims independent proof/write")
        old_ids={x.event_id for x in old}
        new_ids={x.canonical_event_id for x in new}
        strong_ids={x.canonical_event_id for x in new
                    if x.context_tier=="edition_context_strong"}
        r=by_family[family]
        classification = (
            "old_none_new_unique" if not old_ids and len(new_ids)==1 else
            "old_none_new_ambiguous" if not old_ids and len(new_ids)>1 else
            "old_unique_new_none" if len(old_ids)==1 and not new_ids else
            "old_unique_new_ambiguous" if len(old_ids)==1 and len(new_ids)>1 else
            "old_unique_new_different" if len(old_ids)==len(new_ids)==1 and old_ids!=new_ids else
            "old_ambiguous_new_unique" if len(old_ids)>1 and len(new_ids)==1 else
            "old_ambiguous_new_none" if len(old_ids)>1 and not new_ids else
            "other_candidate_set_difference" if old_ids and new_ids and old_ids!=new_ids else
            "candidate_sets_same"
        )
        metrics[classification]+=1
        r[classification]+=1
        for entry in new:
            for evidence in set(entry.evidence):
                metrics["research_evidence_"+evidence]+=1
        for k,v in (
            ("source_events",1),("old_any",bool(old)),("new_any",bool(new)),
            ("old_unique",len(old_ids)==1),("new_unique",len(new_ids)==1),
            ("new_ambiguous",len(new_ids)>1),
            ("new_strong_context_any",bool(strong_ids)),
            ("new_strong_context_unique",len(strong_ids)==1),
            ("new_strong_context_ambiguous",len(strong_ids)>1),
            ("new_weak_context_only",bool(new_ids) and not strong_ids),
            ("old_unique_now_strong_unique",len(old_ids)==1 and len(strong_ids)==1),
            ("old_unique_now_strong_none",len(old_ids)==1 and not strong_ids),
            ("old_unique_now_strong_ambiguous",len(old_ids)==1 and len(strong_ids)>1),
            ("new_only_strong_unique",not old_ids and len(strong_ids)==1),
            ("new_only",bool(new_ids) and not bool(old_ids)),
            ("old_only",bool(old_ids) and not bool(new_ids)),
            ("same_unique",len(old_ids)==len(new_ids)==1 and old_ids==new_ids),
            ("sets_disagree",bool(old_ids) and bool(new_ids) and old_ids!=new_ids),
        ):
            metrics[k]+=v
            r[k]+=v
    return {
        "schema":"BLINQ_IDENTITY_V2_SACKMANN2025_REAL_DATA_SHADOW_V1",
        "baseline":"normalized_names_plus_tour_round_plus_tournament_start_window_proxy",
        "source_family_hashes":SOURCE_SHA,
        "cdb_sha256":CDB_SHA,
        "counts":dict(sorted(metrics.items())),
        "per_source_family":{k:dict(sorted(v.items())) for k,v in sorted(by_family.items())},
        "independent_canonical_event_witnesses":0,
        "independent_canonical_player_witnesses":0,
        "CDB_approved_cells":0,
        "CDB_writes":0,
        "notes":"Candidate discovery only. No source rights/PIT or native event-to-CDB witness is attested. This baseline is only a strict normalized-name proxy, not all legacy importers.",
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir",type=Path,required=True)
    parser.add_argument("--cdb-parquet",type=Path,required=True)
    parser.add_argument("--sample-mod",type=int,default=13)
    args=parser.parse_args(argv)
    if not 1<=args.sample_mod<=1000:
        parser.error("--sample-mod must be 1..1000")
    sources,sc=source_events(args.source_dir,sample_mod=args.sample_mod)
    canonical,cc=canonical_events(args.cdb_parquet)
    data=compare(sources,canonical)
    data["sample_mod"]=args.sample_mod
    data["source_counts"]=dict(sorted(sc.items()))
    data["canonical_counts"]=dict(sorted(cc.items()))
    print("BLINQ_IDENTITY_V2_REAL_SHADOW "+json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False))


if __name__=="__main__":
    main()
