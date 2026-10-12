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

# SHA-pinned, opt-in original source-only QA for historical years outside the guarded 2022–25
# writer contract. Defaults and writer-supported YEAR_BLOBS stay unchanged.
OPTIONAL_YEAR_BLOBS = {
    1987: "a899da932402e5a44071ad44bb0f6d74897bd571",
    1988: "b5cc74c973d70eff55a2d07fa909bdbf02cb8177",
    1989: "92d27f0702d015d3dac6d59f8497ee743c1945b9",
    1990: "b6d5b188d2c2c668b97dfbdcae6d441a715b2ab7",
    1991: "fc121a545659831718cda02ca7a5d805fb12c9f3",
    1992: "5a8c4e03457f8b0e428d99f4854fd8fe4a9c06ad",
    1993: "c663e31d38296df704d2b8b0ac6819e7705829e1",
    1994: "dabd32e2f8d694809d104070ec818fc2e6c2ae51",
    1995: "78daf479225257c071d07ab83f2cb2e36f478c34",
    1996: "1fa08e8eeceac6a5b07278ab796467e96f145ba9",
    1997: "c70bf6b7b0f904f48d568f88dcf0fff4dc013e58",
    1998: "8dbc8b130ea717679182519f5aab36d07e170dc0",
    1999: "ca8ee0f930823a0245b0979c051f9e8035165b8a",
    2000: "bbe66a82015430166e6a7d45aaf09b1ba5fccd98",
    2001: "6bbae8af7b894aa0eb2684185e9373a83d25a3a4",
    2002: "240adc2a4b3eef73aca79a584f30b77d9823cffe",
    2003: "e1f8985c9e38ffa4e44e0627963499afac874ce0",
    2004: "01ba136cd875e4e4341453ddcfd8bb6d39389ba8",
    2005: "4ca2674aacb7e22663d3b4ce23782021dc28a0ca",
    2006: "23d500db297d9ca0414f70222ab432497af45474",
    2007: "22f26df7dbf9b0e217a0cff5b541e95d7ce36161",
    2008: "90db8f4ca43b60a97e0d4806d10f0edcfa8e665c",
    2009: "623abf68f9b5c2f37d27c6589e6a5b5fff7a97d7",
    2010: "869e16018241c2bf8e6b68a316157d0eb4ef39d1",
    2011: "d877cbda486c752fd2ffd241430b056fd00ea351",
    2012: "49a4c4d93c4ccb1255bf1065a4f6409eec672bb9",
    2013: "a025418f2edaff54d273c209985352134e28ff61",
    2014: "ea3226ebe6b78aad0cc8c698b445d2cc11181b0b",
    2015: "97b09b910a207855ea71fc475e6d4d4b901fd814",
    2016: "e911c48f099081a3682099cb627c1b420a5b6842",
    2017: "951e68d3ec4a3f5f4fdb276b3824f746a8c1633f",
    2018: "01b9806660796d3169a8335f238077c94d4ce58f",
    2019: "b6d793cb413efe0fc060a3d85a1c75fa4e9162c6",
    2020: "50fa843751a4394d314e2959d62aeac92588182b",
    2021: "2bd4eaf4eb28a09b42ab4ecd5830a8f3ad068faa",
    2026: "8b2c58c563002e7baef091654ec8bf2abb6b81e6",
}

STATS = tuple(f"{p}_{k}" for p in ("w","l") for k in
 ("ace","df","svpt","1stIn","1stWon","2ndWon","SvGms","bpSaved","bpFaced"))
ID = re.compile(r"[A-Za-z0-9]+\Z")

def blob_sha1(raw: bytes):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

_SET_SCORE = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?$")


def complete_winner_score(score: object, best_of: object) -> bool:
    """Only whole completed winner-oriented singles scores qualify for boxscore staging.

    Reject retirements, walkovers, truncated sets, match tie-break shorthand,
    trailing sets after the winner clinched and scores won by the loser.
    """
    needed = {"3": 2, "5": 3}.get(str(best_of))
    if needed is None or not isinstance(score, str) or not score.strip():
        return False
    tokens = score.strip().split()
    if len(tokens) < needed:
        return False
    wins = losses = 0
    for index, token in enumerate(tokens):
        match = _SET_SCORE.fullmatch(token)
        if match is None:
            return False
        a, b = int(match.group(1)), int(match.group(2))
        hi, lo = max(a, b), min(a, b)
        if not ((hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6))
                or (hi >= 8 and hi - lo == 2)):
            return False
        if a > b:
            wins += 1
        else:
            losses += 1
        if losses >= needed or (wins == needed and index != len(tokens) - 1):
            return False
    return wins == needed and losses < needed


def select_source(path: Path, year: int):
    data = path.read_bytes()
    expected_blob = YEAR_BLOBS.get(year) or OPTIONAL_YEAR_BLOBS.get(year)
    if expected_blob is None or blob_sha1(data) != expected_blob:
        raise ValueError(f"TML original Git blob SHA mismatch: {year}")
    stream = io.StringIO(data.decode("utf-8-sig"), newline="")
    reader = csv.DictReader(stream)
    header = reader.fieldnames or []
    required = set(STATS) | {"tourney_id", "tourney_name", "tourney_date",
          "match_num","winner_id","loser_id","winner_name","loser_name",
          "surface","round","best_of","score"}
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
        if not complete_winner_score(row["score"], row["best_of"]):
            counts["quarantine_incomplete_or_invalid_final_score"] += 1
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


def audit_all_pinned_sources(folder: Path, out: Path, years=None):
    """Source-only inspection. Never produces an import-ready CDB stage."""
    allowed = {**OPTIONAL_YEAR_BLOBS, **YEAR_BLOBS}
    selected = sorted(allowed if years is None else years)
    if not set(selected).issubset(allowed):
        raise ValueError("Unpinned TML year not permitted")
    report = {"schema": 1, "status": "PINNED_SOURCE_ONLY_NO_CDB_ACCESS",
              "source_repo": ORIGIN, "source_git_commit": SOURCE_COMMIT,
              "source_families": 1, "per_year": {}, "cdb_imported": 0,
              "current_cdb_null_delta": None, "independent_cdb_readback": "NOT_RUN",
              "canonical_mutated": False, "model_trained": False,
              "provider_api_requests": 0}
    for year in selected:
        path = folder / f"{year}.csv"
        if year == 2026 and not path.exists():
            # User uploads may rename an exact original without altering bytes.
            path = folder / "2026(1).csv"
        usable, header, counts, sha = select_source(path, year)
        report["per_year"][str(year)] = {
            "file": path.name, "raw_sha256": sha,
            "git_blob_sha1": allowed[year], "raw_rows": counts.get("source_rows", 0),
            "source_native_valid": len(usable),
            "reasons": {k: v for k, v in sorted(counts.items())
                        if k.startswith("quarantine_")},
            "canonical_match_links": None, "new_verified_cdb_null_cells": None}
    out.mkdir(parents=True, exist_ok=True)
    (out / "pinned-source-only-audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-dir",required=True,type=Path)
    p.add_argument("--verified-crosswalk",type=Path)
    p.add_argument("--crosswalk-sha256")
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--source-only-audit",action="store_true",
                   help="Read only all SHA-pinned 1987–2026 originals; no CDB or ID linking")
    a=p.parse_args()
    if a.source_only_audit:
        r=audit_all_pinned_sources(a.source_dir,a.out)
        print(json.dumps({"status":r["status"],"per_year":r["per_year"]},sort_keys=True))
        return
    if a.verified_crosswalk is None or a.crosswalk_sha256 is None:
        p.error("Protected default mode requires both --verified-crosswalk and --crosswalk-sha256")
    r=prepare(a.source_dir,a.verified_crosswalk,a.crosswalk_sha256,a.out)
    print(json.dumps({"status":r["status"],"per_year":r["per_year"],"crosswalk_quality":r["crosswalk_quality"]},sort_keys=True))
if __name__=="__main__":main()
