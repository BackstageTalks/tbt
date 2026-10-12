#!/usr/bin/env python3
"""Source-native 335-column Charting observations: CDB sidecars, never whole-match stats."""
from __future__ import annotations
import argparse,base64,csv,gzip,hashlib,io,json,pathlib,re
from collections import Counter

SOURCES={"atp":("92d6975a09ebc0f5bf42d68a34e57087152e9219d8430d7794faa68b0c5630f8",15129),
         "wta":("cf1ec57c55cda20cd43a2848e30369b4c829486f618605c9a369a22fa3fdd315",8506)}
MATCH_SHA="edb00bd1ba98ed937ed2aac575676e4f4656c5e8fd7ae4530cb802edad3e1478"
CORE=pathlib.Path("research/offline-sources/blinq-import-2026-10-07/chunks")
MANIFEST="charting-observations-manifest-v1.json"
def sha(data):return hashlib.sha256(data).hexdigest()
def reconstruct(root,tour):
    paths=sorted((root/CORE).glob(f"blinq_charting_{tour}_core_features.csv.gz.b64.part*.txt"))
    if not paths or [p.name[-11:] for p in paths]!=[f"part{i:03d}.txt" for i in range(len(paths))]:
        raise ValueError("Missing or noncontiguous source chunks")
    encoded=b"".join(p.read_bytes().strip() for p in paths)
    if len(encoded)>64_000_000:raise ValueError("Archive cap exceeded")
    zipped=base64.b64decode(encoded,validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(zipped)) as f:raw=f.read(220_000_001)
    if len(raw)>220_000_000 or sha(raw)!=SOURCES[tour][0]:
        raise ValueError("Pinned original wide CSV changed or too large")
    return raw,[p.name for p in paths]
def records(data):
    reader=csv.DictReader(io.StringIO(data.decode("utf-8-sig"),newline=""))
    header=reader.fieldnames
    if not header or len(header)!=335 or len(set(header))!=335 or not {"match_id","player","opponent","date","surface","round"}<=set(header):
        raise ValueError("Rich source schema drift")
    for line,row in enumerate(reader,2):
        if None in row or any(v is None for v in row.values()):
            raise ValueError("Malformed source CSV line "+str(line))
        yield line,row,header
def day(v):
    s=str(v or "").strip()
    return s.replace("-","") if re.fullmatch(r"\d{4}-\d{2}-\d{2}",s) else s if re.fullmatch(r"\d{8}",s) else ""
def classify(tour,r,matches,invalid,owners):
    mid=r.get("match_id","");player=r.get("player","");opponent=r.get("opponent","")
    ev=matches.get(mid);problems=[]
    if not mid or not isinstance(ev,dict):problems.append("MISSING_SOURCE_EVENT")
    else:
        names=ev.get("players")
        if ev.get("tour")!=tour or not isinstance(names,list) or len(names)!=2:
            problems.append("BAD_SOURCE_IDENTITY")
        elif not all(isinstance(n,str) and len(n.strip())>1 for n in names) or names[0]==names[1] or {player,opponent}!=set(names) or player==opponent:
            problems.append("PLAYER_PAIR_CONFLICT")
        if r.get("date") and day(r["date"])!=day(ev.get("date")):
            problems.append("DATE_CONFLICT")
        if r.get("surface") and str(r["surface"]).strip().casefold()!=str(ev.get("surface") or "").strip().casefold():
            problems.append("SURFACE_CONFLICT")
    if mid in invalid:problems.append("SOURCE_PREFLIGHT_QUARANTINE")
    if owners[(mid,player)]!=1:problems.append("DUPLICATE_SOURCE_PLAYER_ROW")
    if not player or not opponent:problems.append("EMPTY_PLAYER")
    return sorted(set(problems)),ev
def write_gzip(path,items):
    with path.open("wb") as target:
        with gzip.GzipFile(filename="",fileobj=target,mode="wb",compresslevel=6,mtime=0) as gz:
            with io.TextIOWrapper(gz,encoding="utf-8",newline="\n") as text:
                for item in items:
                    text.write(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
    return {"sha256":sha(path.read_bytes()),"bytes":path.stat().st_size}
def build(root,out):
    root=pathlib.Path(root);out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True)
    index=root/"tennis/charting/matches.json.gz"
    if sha(index.read_bytes())!=MATCH_SHA:raise ValueError("Source match index SHA drift")
    with gzip.open(index,"rt",encoding="utf-8") as f:matches=json.load(f)
    if not isinstance(matches,dict) or len(matches)!=11822:raise ValueError("Source match count drift")
    audit=json.loads((root/"audit/cross-source/CHARTING-SOURCE-PREFLIGHT-20261012.json").read_text())
    if audit.get("source_sha256")!=MATCH_SHA or audit["counts"]["input_rows"]!=11822:
        raise ValueError("Source preflight evidence drift")
    invalid={r["id"] for r in audit["invalid_rows"]}
    manifests={}
    for tour in ("atp","wta"):
        raw,parts=reconstruct(root,tour)
        owners=Counter();length=0;header=None
        for _,row,fields in records(raw):
            owners[(row.get("match_id"),row.get("player"))]+=1
            length+=1;header=fields
        if length!=SOURCES[tour][1]:raise ValueError("Original source row count drift")
        reasons=Counter();counts=Counter()
        def observations():
            for number,r,_ in records(raw):
                issues,ev=classify(tour,r,matches,invalid,owners)
                fields={key:value for key,value in r.items() if value!=""}
                counts["original_nonempty_fields"]+=len(fields)
                counts["quarantined" if issues else "native"]+=1
                reasons.update(issues)
                names=ev.get("players") if isinstance(ev,dict) else None
                side=names.index(r["player"])+1 if isinstance(names,list) and r["player"] in names else None
                yield {"schema":1,"source_family":"tennis_abstract_charting_core_335",
                       "source_match_id":r.get("match_id") or None,"tour":tour,"csv_row":number,
                       "source_player":r.get("player") or None,"source_opponent":r.get("opponent") or None,
                       "source_player_side":side,"source_match_metadata":ev,
                       "source_csv_sha256":SOURCES[tour][0],"source_fields_nonempty":fields,
                       "observation_scope":"charted_point_sample_unknown_completeness",
                       "available_at":None,"canonical_match_id":None,"canonical_player_id":None,
                       "independent_provider_event_identity":False,
                       "whole_match_stats_eligible":False,"canonical_write_allowed":False,
                       "prediction_training_allowed":False,
                       "status":"QUARANTINE" if issues else "SOURCE_NATIVE_OBSERVATION","issues":issues}
        filename=f"charting-observations-{tour}-v1.jsonl.gz"
        meta=write_gzip(out/filename,observations())
        manifests[tour]={"name":filename,**meta,"rows":length,"source_native_rows":counts["native"],
                         "quarantined_rows":counts["quarantined"],"quarantine_reasons":dict(sorted(reasons.items())),
                         "nonempty_original_cells_preserved":counts["original_nonempty_fields"],
                         "source_csv_sha256":SOURCES[tour][0],"source_chunk_files":parts,"source_columns":header}
    result={"schema":1,"namespace":"charting_observations/v1",
            "upstream_family":"tennis_abstract_match_charting",
            "source_match_index_sha256":MATCH_SHA,"source_total_matches":11822,
            "total_source_rows":sum(v["rows"] for v in manifests.values()),
            "total_source_native_rows":sum(v["source_native_rows"] for v in manifests.values()),
            "total_quarantined_rows":sum(v["quarantined_rows"] for v in manifests.values()),
            "fields_preserved_nonempty":sum(v["nonempty_original_cells_preserved"] for v in manifests.values()),
            "assets":manifests,
            "storage_policy":"source_scoped_sidecar_only_never_replace_whole_match_cdb",
            "canonical_history_partitions_modified":False,"canonical_statistics_changed":False,
            "canonical_event_join_approved":False,"training_model_eligible":False,"provider_api_requests":0}
    (out/MANIFEST).write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument("--source-repo",type=pathlib.Path,required=True)
    p.add_argument("--out",type=pathlib.Path,required=True);a=p.parse_args()
    r=build(a.source_repo,a.out)
    print(json.dumps({"status":"BUILT_SOURCE_NATIVE_SIDECAR",
                      "rows":r["total_source_rows"],"native":r["total_source_native_rows"],
                      "quarantine":r["total_quarantined_rows"],"original_nonempty_fields":r["fields_preserved_nonempty"],
                      "canonical_CDB_stats_writes":0}),flush=True)
if __name__=="__main__":main()
