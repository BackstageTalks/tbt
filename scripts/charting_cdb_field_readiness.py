#!/usr/bin/env python3
"""Read-only, fail-closed Match Charting to current CDB NULL audit. No production writer."""
import argparse,collections,gzip,hashlib,json,math,pathlib
import pyarrow.parquet as pq

def digest(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for chunk in iter(lambda:f.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def number(v):
    if v is None or v=="" or isinstance(v,bool):return None
    try:
        f=float(v)
        return f if math.isfinite(f) and f>=0 else None
    except (ValueError,TypeError):return None

def overview(row):
    raw=row.get("stats") or {}
    v={k:number(raw.get(k)) for k in ("aces","dfs","serve_pts","first_in","first_won","second_in","second_won","return_pts","return_pts_won")}
    required=("serve_pts","first_in","first_won","second_in","second_won","return_pts","return_pts_won")
    if any(v[k] is None for k in required) or any(x!=int(x) for x in v.values() if x is not None):return None
    if not v["serve_pts"] or not v["return_pts"] or v["first_in"]+v["second_in"]!=v["serve_pts"]:return None
    if v["first_won"]>v["first_in"] or v["second_won"]>v["second_in"] or v["return_pts_won"]>v["return_pts"]:return None
    s={}
    if v["aces"] is not None:s["aces"]=v["aces"]
    if v["dfs"] is not None:s["double_faults"]=v["dfs"]
    if v["first_in"]:s["first_serve_win"]=v["first_won"]/v["first_in"]
    if v["second_in"]:s["second_serve_win"]=v["second_won"]/v["second_in"]
    s["service_points_won"]=(v["first_won"]+v["second_won"])/v["serve_pts"]
    s["return_points_won"]=v["return_pts_won"]/v["return_pts"]
    return s,v

def evaluate(root,out):
    root=pathlib.Path(root);out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True)
    src=pathlib.Path("private-data/tennis/charting"); croot=root/"crosswalk";history=root/"history"
    rep=json.loads((croot/"crosswalk_report.json").read_text())
    assert digest(src/"matches.json.gz")==rep["source_sha256"]
    with gzip.open(src/"matches.json.gz","rt") as f:source=json.load(f)
    with gzip.open(croot/"crosswalk_candidates.jsonl.gz","rt") as f:
        candidates=[json.loads(x) for x in f if x.strip()]
    candidates=[x for x in candidates if x.get("status")=="CANDIDATE_COMPOUND_ONLY"]
    assert len(candidates)==rep["candidate_links"]==1153
    parts={p.name:p for p in history.glob("history-*.parquet")}
    assert set(parts)==set(rep["canonical_partition_sha256"])
    for name,p in parts.items():assert digest(p)==rep["canonical_partition_sha256"][name]
    ids={str(c["canonical_match_id_candidate"]) for c in candidates}
    hits={}
    fields=["match_id","tour","scheduled_at","player1_id","player2_id","player1_name","player2_name","winner_id","status","stats_json","provider_context_json"]
    for p in parts.values():
        reader=pq.ParquetFile(p)
        assert set(fields)<=set(reader.schema.names)
        for chunk in reader.iter_batches(batch_size=8192,columns=fields):
            for row in chunk.to_pylist():
                mid=str(row["match_id"])
                if mid in ids:
                    assert mid not in hits
                    hits[mid]=row
    players=collections.defaultdict(list)
    for row in json.loads((src/"players.json").read_text()):
        players[(row["tour"],row["name"])].append(row["path"])
    result=collections.Counter();review=[];complete=[]
    for candidate in candidates:
        sid=candidate["source_match_id"];mid=candidate["canonical_match_id_candidate"]
        sr=source.get(sid);m=hits.get(mid);reason=None;observed={}
        if not sr or not m:reason="missing_source_or_cdb"
        elif candidate["canonical_player_ids_candidate"] != [str(m["player1_id"]),str(m["player2_id"])]:reason="id_changed"
        else:
            for i,name in enumerate(sr["players"]):
                paths=players[(sr["tour"],name)]
                if len(paths)!=1:reason="ambiguous_player_profile";break
                file=src/paths[0]
                assert file.is_file() and file.resolve().is_relative_to(src.resolve())
                with gzip.open(file,"rt") as f:p=json.load(f)
                if p.get("name")!=name or p.get("tour")!=sr["tour"] or sid not in p.get("match_ids",[]):reason="profile_inconsistent";break
                rows=[z for z in p.get("overview_by_match",[]) if z.get("match_id")==sid]
                if len(rows)!=1:reason="overview_missing_or_duplicate";break
                v=overview(rows[0])
                if v is None:reason="incomplete_overview_counts";break
                observed["p"+str(candidate["source_side_to_canonical_side"][i])]=v
        if reason is None:
            if set(observed)!={"p1","p2"}:reason="side_identity_conflict"
            elif observed["p1"][1]["serve_pts"]!=observed["p2"][1]["return_pts"] or observed["p2"][1]["serve_pts"]!=observed["p1"][1]["return_pts"]:reason="inconsistent_return_serves"
        if reason is None:
            stats={s+"_"+k:v for s,(obs,_) in observed.items() for k,v in obs.items()}
            old=json.loads(m["stats_json"])
            if not isinstance(old,dict):reason="bad_cdb_stats"
        if reason is None:
            overlap={k:(float(old[k]),v) for k,v in stats.items() if old.get(k) is not None}
            if any(abs(a-b)>0.000001 for a,b in overlap.values()):reason="canonical_stats_conflict"
        if reason is None:
            result["consistent_stat_matches"]+=1
            delta={k:v for k,v in stats.items() if old.get(k) is None}
            result["null_cells_in_consistent_matches"]+=len(delta)
            if not delta:
                reason="already_complete"
                complete.append({"canonical_match_id":mid,"source_match_id":sid,"source_player_side_map":candidate["source_side_to_canonical_side"],"canonical_player_ids":[str(m["player1_id"]),str(m["player2_id"])],"corroborating_fields":sorted(overlap),"source_sha256":rep["source_sha256"],"canonical_raw_stats_sha256":hashlib.sha256(m["stats_json"].encode()).hexdigest(),"import_approved":False})
            elif len(overlap)<4 or {k[:2] for k in overlap}!={"p1","p2"} or {k[:2] for k in overlap if k.endswith(("aces","double_faults"))}!={"p1","p2"}:
                reason="insufficient_two_sided_canonical_stats"
        if reason is None:
            if not m["winner_id"] or str(m["winner_id"]) not in {str(m["player1_id"]),str(m["player2_id"])}:reason="missing_winner"
            elif str(m.get("status") or "").lower() not in ("completed","finished"):reason="not_completed"
        result[reason or "strong_stat_agreement_requires_independent_identity_review"]+=1
        if reason is None:
            review.append({"canonical_match_id":mid,"source_match_id":sid,"missing_values":delta,"overlap_fields":sorted(overlap),"import_approved":False})
    noncategories={"consistent_stat_matches","null_cells_in_consistent_matches"}
    assert sum(v for k,v in result.items() if k not in noncategories)==len(candidates)
    with (out/"review.jsonl").open("w") as f:
        for r in review:f.write(json.dumps(r,sort_keys=True)+"\n")
    with (out/"already_present_verified.jsonl").open("w") as f:
        for r in complete:f.write(json.dumps(r,sort_keys=True)+"\n")
    report={"status":"READ_ONLY_NO_PRODUCTION_WRITES","candidate_links":len(candidates),"consistent_already_present_rows":len(complete),"cdb_rows":rep["counts"]["cdb_rows"],"counts":dict(result),"possible_review_matches":len(review),"possible_review_cells":sum(len(x["missing_values"]) for x in review),"approved_production_cells":0,"written_production_cells":0,"next_gate":"Verify independent event and both-player identity, stats whole-match completeness, immutable backup, single writer lock, NULL-only CAS and full persisted readback"}
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print("CHARTING_FIELD_GATE",json.dumps(report,sort_keys=True))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",required=True);p.add_argument("--out",required=True);a=p.parse_args();evaluate(a.root,a.out)
