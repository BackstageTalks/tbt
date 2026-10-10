"""ATP Futures / qualifying uploaded source vs *current* canonical CDB, read-only.

Old 947720-row reference indicated 40333 potentially missing keys, but was
superseded. A tournament-start date is NOT the match start date. Absence
from a strict key does NOT prove a new match may be created. No writes.
"""
from __future__ import annotations
import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest

SOURCE_NAME = "blinq_atp_futures_quali_2018_2026.csv"
SOURCE_SHA256 = "410e0b7a4c08f05aebd54de90d8f8029a514d8c0df41c251c5979e5b06e488d5"
SOURCE_ROWS = 130689
YEARS = tuple(range(2018, 2027))


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def reconstruct(chunks_dir: Path) -> tuple[csv.DictReader, dict, str]:
    manifest = json.loads((chunks_dir / "manifest.json").read_text())
    meta = (manifest.get("files") or {}).get(SOURCE_NAME) or {}
    if meta.get("sha256") != SOURCE_SHA256:
        raise ValueError("Unapproved source content digest")
    parts = meta.get("parts")
    if not isinstance(parts, list) or len(parts) != 9 or len(set(parts)) != len(parts):
        raise ValueError("Invalid source chunk inventory")
    if any((Path(p).name != p or
            not p.startswith("blinq_atp_futures_quali_2018_2026.csv.gz.b64.part"))
           for p in parts):
        raise ValueError("Unsafe source chunk path")
    encoded = "".join("".join((chunks_dir / name).read_text(encoding="ascii").split()) for name in parts)
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != meta.get("compressed_bytes"):
        raise ValueError("Compressed source size mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != meta.get("bytes") or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unverified reconstructed original ATP Futures CSV")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    expected = {"tourney_id", "tourney_date", "winner_id", "loser_id", "match_num"}
    if not reader.fieldnames or not expected.issubset(set(reader.fieldnames)):
        raise ValueError("Missing original stable identity columns")
    return reader, meta, SOURCE_SHA256


def get_date(value: str):
    t = str(value or "").strip()
    try:
        return datetime.strptime(t, "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid source tournament start date") from exc


def key(tourney_id, p1, p2):
    t = str(tourney_id or "").strip()
    ids = [str(p1 or "").strip(), str(p2 or "").strip()]
    if not t or any(not i for i in ids) or ids[0] == ids[1]:
        return None
    return (t, *sorted(ids))


def classify(row, options):
    """Unique ID+event pair, result+date. Never fuzzy and never writes."""
    k = key(row.get("tourney_id"), row.get("winner_id"), row.get("loser_id"))
    if k is None:
        return "SOURCE_IDENTITY_INVALID"
    matches = options.get(k, [])
    if not matches:
        return "UNMATCHED_STRICT_KEY_NOT_PROVEN_NEW"
    if len(matches) != 1:
        return "AMBIGUOUS_CANONICAL_MATCH"
    candidate = matches[0]
    date = get_date(row["tourney_date"])
    elapsed = (candidate["scheduled_at"] - date).days
    if not 0 <= elapsed <= 21:
        return "DATE_WINDOW_CONFLICT"
    if candidate["winner_id"] not in (None, "") and candidate["winner_id"] != str(row.get("winner_id")):
        return "CANONICAL_WINNER_CONFLICT"
    if candidate["winner_id"] in (None, ""):
        return "LINKED_CANONICAL_WINNER_MISSING_NEEDS_SOURCE_REVIEW"
    return "EXACT_IDENTITY_ALREADY_PRESENT"


def audit(source_chunks: Path, history_dir: Path, output: Path):
    reader,meta,source_sha = reconstruct(source_chunks)
    manifest = load_manifest(history_dir)
    index = defaultdict(list)
    by_year = {}
    canonical_ids = set()
    for year in YEARS:
        p = history_dir / f"history-{year}.parquet"
        ymeta = (manifest.get("years") or {}).get(str(year)) or {}
        if ymeta.get("asset") != p.name or ymeta.get("sha256") != file_sha256(p):
            raise ValueError("CDB partition checksum mismatch year " + str(year))
        cols = ["match_id", "tournament_id", "player1_id", "player2_id",
                "winner_id", "scheduled_at", "tour"]
        df = pd.read_parquet(p, columns=cols)
        if len(df) != int(ymeta.get("rows",-1)):
            raise ValueError("Canonical year row count mismatch")
        by_year[str(year)] = {"rows":len(df),"sha256":ymeta["sha256"]}
        for row in df.itertuples(index=False):
            mid=str(row.match_id)
            if not mid or mid in canonical_ids:
                raise ValueError("Duplicate or empty canonical identity")
            canonical_ids.add(mid)
            if str(row.tour or "").lower() not in ("atp", "itf", "challenger"):
                continue
            k=key(row.tournament_id,row.player1_id,row.player2_id)
            if not k: continue
            ts=pd.Timestamp(row.scheduled_at)
            if ts.tzinfo is None:
                raise ValueError("Canonical scheduled_at must be timezone-aware")
            index[k].append({
                "match_id":mid,
                "scheduled_at":ts.date(),
                "winner_id":str(row.winner_id or ""),
            })
    counts=Counter()
    by_year_status=defaultdict(Counter)
    source_keys=set()
    collision_keys=set()
    for row in reader:
        counts["source_rows"]+=1
        source_year=get_date(row["tourney_date"]).year
        if source_year not in YEARS:
            raise ValueError("Source outside pinned year range")
        k=key(row.get("tourney_id"),row.get("winner_id"),row.get("loser_id"))
        if k in source_keys:
            counts["source_repeated_identity_key"]+=1
            collision_keys.add(k)
        source_keys.add(k)
        state=classify(row,index)
        counts[state]+=1
        by_year_status[str(source_year)][state]+=1
    if counts["source_rows"]!=SOURCE_ROWS:
        raise ValueError("Reconstructed source row count diverges")
    report={
        "schema":1, "status":"CURRENT_CANONICAL_ATP_FUTURES_STRICT_IDENTITY_RECONCILIATION_READ_ONLY",
        "source_sha256":source_sha, "source_raw_bytes":meta["bytes"],
        "baseline_reference":"audit/atp-futures-old-reference-comparison-2026-10-08.json",
        "baseline_older_reference_rows":947720,
        "old_snapshot_not_found_keys":40333,
        "current_canonical_years":list(YEARS),
        "current_canonical_rows_2018_2026":len(canonical_ids),
        "canonical_year_digest_verified":by_year,
        "classification":dict(counts),
        "by_source_tourney_year":{k:dict(v) for k,v in sorted(by_year_status.items())},
        "source_duplicate_identity_key_groups":len(collision_keys),
        "matched_keys_without_source_rights_or_independent_id_proof_not_authorized":True,
        "new_canonical_matches_proven_for_import":0,
        "new_canonical_stats_values_proven_for_import":0,
        "unmatched_classification_is_not_an_import_order":True,
        "model_training_performed":False,
        "production_cdb_mutated":False,
        "provider_api_requests":0,
        "limitations":[
            "Source tourney_date is event start, not necessarily individual match timestamp",
            "Only exact tournament/player IDs and canonical result qualify as present; aliases or missing IDs stay unresolved",
            "Unmatched strict keys may already be present under a different canonical ID or event label",
            "Any future write requires rights, source-to-canonical crosswalk, explicit source completeness, single writer, immutable backup, independent persisted readback",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-chunks",type=Path,required=True)
    p.add_argument("--history-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(audit(args.source_chunks,args.history_dir,args.output),sort_keys=True))


if __name__=="__main__":
    main()
