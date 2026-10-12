#!/usr/bin/env python3
"""Pinned TennisMyLife ATP 2022-25 sources -> vetted Sackmann-style CSV and ID witness.

This adapter never writes canonical CDB. It rejects missing/ambiguous source
keys and physically implausible counts; sources stay on a private runner.
Verified Wikidata/ATP sidecar must supply *both* exact ATP Tour player IDs.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, re
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path

ORIGIN = "Tennismylife/TML-Database"
SOURCE_COMMIT = "c5537eed87d8a76f3adb598cdf506d885872923b"
YEAR_BLOBS = {
  2022: "2b6726106fefb22b40c2816e4c703a48e9d312be",
  2023: "5ceb7397e3a217e51f197c9e83ea435faf690eeb",
  2024: "cf513429259b4a15e84e2021206895d9bd4ff772",
  2025: "1aff9b077cf4de7806b665ec0c6d8b4032a040f3",
}
STATS = tuple(f"{p}_{k}" for p in ("w","l") for k in
 ("ace","df","svpt","1stIn","1stWon","2ndWon","SvGms","bpSaved","bpFaced"))
ID = re.compile(r"[A-Za-z0-9]+\Z")

def blob_sha1(raw: bytes):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def select_source(path: Path, year: int):
    data = path.read_bytes()
    if blob_sha1(data) != YEAR_BLOBS[year]:
        raise ValueError(f"TML original Git blob SHA mismatch: {year}")
    stream = io.StringIO(data.decode("utf-8-sig"), newline="")
    reader = csv.DictReader(stream)
    header = reader.fieldnames or []
    required = set(STATS) | {"tourney_id", "tourney_name", "tourney_date",
          "match_num","winner_id","loser_id","winner_name","loser_name",
          "surface","round","best_of"}
    if len(header) != len(set(header)) or not required.issubset(header):
        raise ValueError("Incomplete or duplicate TML CSV headers")
    good = []
    counts = Counter()
    native_keys = defaultdict(list)
    for row in reader:
        counts["source_rows"] += 1
        if None in row or any(v is None for v in row.values()):
            counts["quarantine_csv_shape"] += 1
            continue
        date = row["tourney_date"]
        ids = (row["winner_id"], row["loser_id"])
        if (not re.fullmatch(r"\d{8}", date)
                or int(date[:4]) not in (year, year-1)
                or not row["tourney_id"] or not row["match_num"].isdecimal()
                or any(not ID.fullmatch(v or "") for v in ids) or ids[0] == ids[1]):
            counts["quarantine_missing_original_identity"] += 1
            continue
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError:
            counts["quarantine_missing_original_identity"] += 1
            continue
        key = (row["tourney_id"],row["match_num"])
        native_keys[key].append(row)
    # A duplicated native event key cannot elect its first row as truth.
    # Quarantine *every* occurrence, even when one copy has invalid stats.
    for group in native_keys.values():
        if len(group) != 1:
            counts["quarantine_duplicate_tournament_match_key"] += len(group)
            continue
        row = group[0]
        try:
            values = {k:int(row[k]) for k in STATS if row[k].isascii() and row[k].isdecimal()}
        except (ValueError, TypeError):
            values = {}
        if len(values) != len(STATS):
            counts["quarantine_missing_complete_stats"] += 1
            continue
        unsafe = False
        for side in ("w","l"):
            n = lambda k: values[f"{side}_{k}"]
            if (n("svpt") <= 0 or n("1stIn") > n("svpt")
                    or n("1stWon") > n("1stIn")
                    or n("2ndWon") > n("svpt")-n("1stIn")
                    or n("ace") > n("1stWon") + n("2ndWon")
                    or n("df") > n("svpt") - n("1stIn")
                    or n("bpSaved") > n("bpFaced")):
                unsafe = True
        if unsafe:
            counts["quarantine_impossible_service_counts"] += 1
            continue
        counts["source_native_valid"] += 1
        good.append(row)
    return good, list(header), dict(counts), hashlib.sha256(data).hexdigest()

def verified_links(path: Path, expected_sha256: str):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Private verified player crosswalk SHA-256 mismatch")
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    mappings, ambiguous = defaultdict(set), set()
    for row in rows:
        if (row.get("tour") != "atp" or row.get("source") != "BlinQ verified CDB plus Wikidata CC0"
                or row.get("evidence") != "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb"
                or not row.get("wikidata_qid")):
            continue
        official, canonical = str(row.get("atp_tour_id") or "").strip(), str(row.get("canonical_player_id") or "").strip()
        if not official or not canonical or not ID.fullmatch(official):
            continue
        mappings[official].add(canonical)
    candidates = {}
    for official, vals in mappings.items():
        if len(vals)==1:
            candidates[official] = next(iter(vals))
        else:
            ambiguous.add(official)
    owners = defaultdict(set)
    for source_id, cid in candidates.items():
        owners[cid].add(source_id)
    clean = {sid:cid for sid,cid in candidates.items() if len(owners[cid])==1}
    return clean, {"verified_links":len(clean),"ambiguous_source_ids":len(ambiguous),
                   "canonical_id_collisions":len(candidates)-len(clean)}

def prepare(folder: Path, crosswalk_file: Path, crosswalk_sha: str, out: Path):
    import re
    if not re.fullmatch(r"[a-f0-9]{64}", crosswalk_sha):
        raise ValueError("Crosswalk SHA not pinned")
    links, quality = verified_links(crosswalk_file, crosswalk_sha)
    if not links:
        raise ValueError("Zero independently corroborated ATP player IDs")
    out.mkdir(parents=True,exist_ok=True)
    rows_out, audit, sha = {}, {}, {}
    for year in YEAR_BLOBS:
        candidates, header, counts, digest = select_source(folder / f"{year}.csv", year)
        valid=[]
        for row in candidates:
            if row["winner_id"] not in links or row["loser_id"] not in links:
                counts["quarantine_missing_two_player_witness"] = counts.get("quarantine_missing_two_player_witness",0)+1
            elif links[row["winner_id"]] == links[row["loser_id"]]:
                counts["quarantine_crosswalk_collision"] = counts.get("quarantine_crosswalk_collision",0)+1
            else:
                valid.append(row)
        dest=out/f"atp_matches_{year}.csv"
        with dest.open("w",newline="",encoding="utf-8") as file:
            writer=csv.DictWriter(file,fieldnames=header)
            writer.writeheader()
            writer.writerows(valid)
        audit[str(year)]={**counts,"verified_two_player_rows":len(valid)}
        sha[str(year)]={"original_git_blob_sha1":YEAR_BLOBS[year],"raw_sha256":digest}
        rows_out[year]=dest
    payload={"schema":1,"players":[{
        "source_id_namespace":"sackmann","tour":"atp","source_player_id":sid,
        "canonical_player_id":cid,"evidence_ref":f"verified_atp_tour_id:{sid};sidecar_sha256:{crosswalk_sha}",
        "independently_verified":True} for sid,cid in sorted(links.items())]}
    cross=out/"tml-verified-crosswalk.json"
    cross.write_text(json.dumps(payload,sort_keys=True)+"\n")
    cross_sha=hashlib.sha256(cross.read_bytes()).hexdigest()
    report={"schema":1,"status":"SOURCE_FILTERED_AND_ID_WITNESSES_ONLY_NOT_CANONICAL",
        "source_repo":ORIGIN,"source_git_commit":SOURCE_COMMIT,"source_digests":sha,
        "original_crosswalk_sha256":crosswalk_sha,"generated_crosswalk_sha256":cross_sha,
        "crosswalk_quality":quality,"per_year":audit,"canonical_mutated":False,
        "model_trained":False,"source_api_requests":0}
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-dir",required=True,type=Path)
    p.add_argument("--verified-crosswalk",required=True,type=Path)
    p.add_argument("--crosswalk-sha256",required=True)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    r=prepare(a.source_dir,a.verified_crosswalk,a.crosswalk_sha256,a.out)
    print(json.dumps({"status":r["status"],"per_year":r["per_year"],"crosswalk_quality":r["crosswalk_quality"]},sort_keys=True))
if __name__=="__main__":main()
