#!/usr/bin/env python3
"""Fail-closed Flashscore native-event bridge to BlinQ canonical NULL-only stage.

A historical accepted name/date link is never a sufficient identity proof.
Requires pinned exact Flashscore event ID, two independently corroborated
player sides, three-way exact UTC/tour, canonical winner, full completed
two-set score, all FOUR existing canonical ace/DF cells equal and no other
non-NULL conflicts. No canonical mutation or model feature activation here.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import gzip,hashlib,json,math,re,unicodedata
from pathlib import Path


INDEX_SHA = "328f9c36c0f4021c745ca7119ea904a4ae7cadb66cee17cc63f2ca6f5774a952"
SOURCE_SHA = "e66e6de58d70801fe2dca7b049f75f442237516a7e5042947b892d63daa1dae8"
PROOF = "flashscore_exact_event_clock_four_counts_full_two_set_score"


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def norm(value):
    v=unicodedata.normalize("NFKD",str(value or "").lower())
    v="".join(ch for ch in v if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+",v))


def short_matches(canonical,short):
    a=norm(canonical).split();b=norm(short).split()
    if not a or not b:return False
    if a==b:return True
    if len(b)<2 or len(a)<2 or len(a)!=len(b) or len(b[-1])!=1:return False
    # Source "Carreno-Busta P." -> canonical "Pablo Carreno Busta".
    return a[0][0]==b[-1] and a[-len(b)+1:]==b[:-1]


def utc(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if d.tzinfo is None:return None
        return d.astimezone(timezone.utc).replace(microsecond=0)
    except (ValueError,TypeError):return None


def read_gzip(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():yield json.loads(line)


def score_two_sets(score):
    tokens=str(score or "").split()
    if len(tokens)!=2:return None
    result=[]
    for token in tokens:
        m=re.fullmatch(r"(\d+)-(\d+)",token)
        if not m:return None
        w,l=int(m[1]),int(m[2])
        if not ((w==6 and 0<=l<=4) or (w==7 and l in (5,6))):
            return None
        result.append((w,l))
    return result


def signature(m):
    from import_offline_linked_serve_return import _signature
    return _signature(m)


def run(source_path,index_path,history_dir,out):
    from tbt.data.history_snapshot import load_snapshot
    from import_offline_linked_serve_return import ALLOWED
    from collections import defaultdict
    import pandas as pd
    source_path=Path(source_path);index_path=Path(index_path);history_dir=Path(history_dir)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if sha(source_path)!=SOURCE_SHA or sha(index_path)!=INDEX_SHA:
        raise ValueError("Pinned source or independent Flashscore event index digest mismatch")
    bundle=json.loads((history_dir/"_tbt_bundle_manifest.json").read_text())["files"]
    manifest=json.loads((history_dir/"history_manifest.json").read_text())["years"]
    by_id={};checks={}
    for year in (2024,2025,2026):
        path=history_dir/f"history-{year}.parquet"
        digest=sha(path)
        if digest!=bundle[path.name]["sha256"] or digest!=manifest[str(year)]["sha256"]:
            raise ValueError("Canonical CDB SHA mismatch")
        checks[path.name]=digest
        for match in load_snapshot(path):
            mid=str(match.match_id)
            if mid in by_id:raise ValueError("Duplicate current canonical match ID")
            by_id[mid]=match
    idx=defaultdict(list)
    for row in read_gzip(index_path):
        if isinstance(row,dict) and row.get("event_id"):
            idx[str(row["event_id"])].append(row)
    counts=Counter();stage=[];review=[];targets=set();source_keys=set()
    for src in read_gzip(source_path):
        counts["source_rows"]+=1
        event=str(src.get("source_match_id") or "")
        key=str(src.get("source_key") or "")
        if not event or not key or key in source_keys:raise ValueError("Bad duplicate source key")
        source_keys.add(key)
        ix=idx.get(event,[])
        if len(ix)!=1:
            counts["index_absent_or_ambiguous"]+=1;continue
        index=ix[0]
        if not index.get("canonical_match_id"):
            counts["index_without_canonical_id"]+=1;continue
        link=index.get("link")
        if not isinstance(link,dict) or link.get("accepted") is not True or link.get("orientation") not in ("direct","swapped"):
            counts["index_link_not_supported"]+=1;continue
        mid=str(index["canonical_match_id"])
        m=by_id.get(mid)
        if m is None:
            counts["index_target_not_in_current_cdb"]+=1;continue
        # Source and index are both original Flashscore-native observations,
        # CDB is a separate persisted canonical partition.
        if (str(index.get("tour") or "").upper()!=src.get("source_tour")
                or str(m.tour).upper()!=src.get("source_tour")
                or utc(index.get("start_utc")) is None
                or not (utc(index.get("start_utc"))==utc(src.get("scheduled_at_utc"))==utc(m.scheduled_at))):
            counts["event_tour_or_exact_utc_disagreement"]+=1;continue
        if str(m.status).lower() not in ("finished","completed","ended"):
            counts["canonical_not_finished"]+=1;continue
        left,right=norm(index.get("player1_source")),norm(index.get("player2_source"))
        winner,loser=norm(src.get("source_winner_name")),norm(src.get("source_loser_name"))
        if {left,right}!={winner,loser} or left==right:
            counts["index_source_names_not_identical"]+=1;continue
        winner_index_first=(left==winner)
        winner_is_p1=(winner_index_first if link["orientation"]=="direct" else not winner_index_first)
        cw=m.player1_name if winner_is_p1 else m.player2_name
        cl=m.player2_name if winner_is_p1 else m.player1_name
        if not short_matches(cw,src["source_winner_name"]) or not short_matches(cl,src["source_loser_name"]):
            counts["canonical_full_player_identity_names_not_corrob"]+=1;continue
        if str(m.winner_id)!=str(m.player1_id if winner_is_p1 else m.player2_id):
            counts["canonical_winner_id_disagreement"]+=1;continue
        if str(m.surface).lower()!=str(src["source_surface"]).lower():
            counts["surface_disagreement"]+=1;continue
        if m.best_of is None or int(m.best_of)!=3 or int(src["source_best_of"])!=3:
            counts["format_disagreement"]+=1;continue
        # Tournament exact equality, allowing only a trailing country in
        # canonical display format; not a fuzzy or substring name join.
        src_tournament=norm(src["source_tournament_name"])
        index_tournament=norm(index.get("tournament"))
        canonical_tournament=norm(m.tournament)
        if not src_tournament or src_tournament!=index_tournament or not (
                canonical_tournament==src_tournament
                or canonical_tournament.startswith(src_tournament+" ")):
            counts["tournament_disagreement"]+=1;continue
        results=score_two_sets(src["source_score"])
        if not results:
            counts["incomplete_or_nonstandard_source_score"]+=1;continue
        existing=dict(m.stats or {})
        score_ok=True
        for set_no,(w,l) in enumerate(results,1):
            for side,games in (("p1",w if winner_is_p1 else l),
                               ("p2",l if winner_is_p1 else w)):
                score_key=f"{side}_set{set_no}_games"
                if existing.get(score_key) is None or float(existing[score_key])!=games:
                    score_ok=False
        if not score_ok:
            counts["no_independent_full_two_set_score"]+=1;continue
        seen={}
        for who,values in (("winner",src["winner_stats"]),("loser",src["loser_stats"])):
            side="p1" if (who=="winner")==winner_is_p1 else "p2"
            for field,value in values.items():
                name=side+"_"+field
                if name not in ALLOWED or isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
                    raise ValueError("Unapproved or invalid source statistic")
                seen[name]=value
        exact=("p1_aces","p2_aces","p1_double_faults","p2_double_faults")
        if not all(key in seen and existing.get(key) is not None and
                   float(existing[key])==float(seen[key]) for key in exact):
            counts["independent_four_count_corroboration_missing"]+=1;continue
        counts["verified_four_counts_and_two_sets"]+=1
        if any(existing.get(k) is not None and
               abs(float(existing[k])-float(value))>1e-6 for k,value in seen.items()):
            counts["other_stats_conflict"]+=1;continue
        additions={k:float(value) for k,value in seen.items() if existing.get(k) is None}
        if not additions:
            counts["already_complete"]+=1;continue
        if mid in targets:
            counts["duplicate_canonical_target"]+=1;continue
        targets.add(mid)
        if not set(additions)<=ALLOWED:raise ValueError("Unapproved new CDB stat name")
        stage.append({"schema":1,"match_id":mid,"canonical":signature(m),
             "incoming_stats":additions,"import_ready":True,
             "source":{"source_key":key,"source_sha256":src["source_sha256"],
                       "flashscore_index_sha256":INDEX_SHA,
                       "verification":PROOF,
                       "proof":{"three_way_exact_utc":True,"native_event_exact":True,
                                "full_two_set_score":True,"four_existing_stat_counts":True,
                                "canonical_winner_id":True,
                                "two_player_sides":True}}})
        counts["staged_new_canonical_null_cells"]+=len(additions)
    destination=out/"cdb_import_stage_EXACT_DIRECT_ONLY.jsonl"
    with destination.open("w",encoding="utf-8") as f:
        for row in stage:f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n")
    report={"schema":1,"status":"READ_ONLY_FLASH_ID_AND_INDEPENDENT_STATS_PROOF",
        "counts":dict(counts),"stage_rows":len(stage),
        "source_sha256":sha(source_path),"index_sha256":sha(index_path),
        "canonical_sha256":checks,"stage_sha256":sha(destination),
        "canonical_writes":0,"writer_executed":False}
    (out/"direct_link_report.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"source_rows":counts["source_rows"],"stage_rows":len(stage),
        "new_null_cells":counts["staged_new_canonical_null_cells"],
        "proven_matches":counts["verified_four_counts_and_two_sets"],
        "rejected":{k:v for k,v in counts.items() if k not in
           ("source_rows","staged_new_canonical_null_cells")}},sort_keys=True))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source-stage",required=True)
    p.add_argument("--flashscore-index",required=True)
    p.add_argument("--history-dir",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args();run(a.source_stage,a.flashscore_index,a.history_dir,a.out)
