#!/usr/bin/env python3
"""Count-only, SHA-pinned A/B comparison of strict-name baseline vs identity-v2.

Accepted input: private JSONL records following identity_v2.Event contract.
Never imports production CDB, writes data, accesses network or trains a model.
This is a *baseline proxy* for exact-name import paths, NOT all legacy linkers.
MAX_ROWS protects this simple in-memory research pilot; full CDB requires a
bounded indexed/sharded runner with dedicated resources.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

try:
    from scripts.research import identity_v2 as m
except ModuleNotFoundError:
    import identity_v2 as m


def sha(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_player(row, tour):
    if not isinstance(row, dict) or not all(k in row for k in ("namespace","native_id","name")):
        raise ValueError("Source-scoped player record required")
    aliases = row.get("aliases") or []
    if not isinstance(aliases, list) or not all(isinstance(v,str) for v in aliases):
        raise ValueError("Aliases must be string list")
    return m.Player(row["namespace"],tour,str(row["native_id"]),
                    row["name"],tuple(aliases),row.get("dob") or "",
                    row.get("country") or "")


def parse_event(row):
    if not isinstance(row,dict):
        raise ValueError("Each JSONL line must be an object")
    tour = row["tour"]
    pair = row["players"]
    if not isinstance(pair,list) or len(pair)!=2:
        raise ValueError("Exactly two player sides required")
    return m.Event(namespace=row["namespace"],event_id=str(row["event_id"]),
                   tour=tour,discipline=row["discipline"],
                   players=tuple(parse_player(p,tour) for p in pair),
                   event_date=row.get("event_date") or "",
                   date_kind=row["date_kind"],
                   tournament=row.get("tournament") or "",
                   round_name=row.get("round_name") or "",
                   score=row.get("score") or "",
                   winner_native_id=str(row.get("winner_native_id") or ""),
                   edition_id=str(row.get("edition_id") or ""),
                   draw=row.get("draw") or "")


def read_events(path: Path,max_rows: int):
    rows = []
    with path.open(encoding="utf-8-sig") as stream:
        for line_number,line in enumerate(stream,1):
            if not line.strip():
                continue
            if len(rows) >= max_rows:
                raise ValueError("Input exceeded explicit bounded --max-rows")
            try:
                rows.append(parse_event(json.loads(line,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON constant")))))
            except (TypeError,KeyError,ValueError) as e:
                raise ValueError("Invalid source schema at line %s" % line_number) from e
    if not rows:
        raise ValueError("Empty source")
    return rows


def baseline_pair(event):
    return tuple(sorted(m.exact_name_key(x.name) for x in event.players))


def proxy_old_match(source, target):
    """Exact normalized player pair and tour/day/round semantics."""
    if (source.tour.casefold(),source.discipline.casefold()) != (
            target.tour.casefold(),target.discipline.casefold()):
        return False
    if baseline_pair(source)!=baseline_pair(target):
        return False
    if source.draw and target.draw and source.draw.casefold()!=target.draw.casefold():
        return False
    if source.round_name and target.round_name and (
            m.normalize_round(source.round_name)!=m.normalize_round(target.round_name)):
        return False
    date1=m._day(source.event_date)
    date2=m._day(target.event_date)
    if not date1 or not date2:
        return False
    if source.date_kind=="tournament_start" and target.date_kind in ("scheduled","played"):
        if not 0 <= (date2-date1).days <= 28:
            return False
    elif abs((date2-date1).days)>1:
        return False
    return True


def comparison(sources,targets):
    counts=Counter()
    by_segment=defaultdict(list)
    for t in targets:
        by_segment[(t.tour.casefold(),t.discipline.casefold())].append(t)
    counts["source_rows"]=len(sources)
    counts["comparison_rows"]=len(targets)
    for source in sources:
        options=by_segment.get((source.tour.casefold(),source.discipline.casefold()),[])
        old=[e for e in options if proxy_old_match(source,e)]
        new=m.discover_events(source,options)
        if not m.no_write_contract(new):
            raise AssertionError("Research candidate improperly authorized")
        counts["old_any"]+=bool(old)
        counts["old_unique"]+=len(old)==1
        counts["old_ambiguous"]+=len(old)>1
        counts["new_any"]+=bool(new)
        counts["new_unique"]+=len(new)==1
        counts["new_ambiguous"]+=len(new)>1
        counts["new_only_any"]+=bool(new) and not old
        counts["old_only_any"]+=bool(old) and not new
        if old and new:
            old_ids={e.event_id for e in old}
            new_ids={e.canonical_event_id for e in new}
            counts["overlap_identical_unique"]+=len(old_ids)==len(new_ids)==1 and old_ids==new_ids
            counts["old_new_candidate_sets_disagree"]+=old_ids!=new_ids
    return {
        "schema":"BLINQ_IDENTITY_V2_SHADOW_COUNTS_V1",
        "baseline":"normalized_pair_tour_day_round_proxy__not_entire_legacy_linker",
        "comparison_type":"offline_research_only",
        "counts":dict(sorted(counts.items())),
        "independently_verified_player_links":0,
        "independently_verified_event_links":0,
        "new_CDB_NULL_fields_verified":0,
        "CDB_writes":0,
        "warning":"Numbers are *candidate discovery*, not authoritative identity attestation.",
    }


def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--source",type=Path,required=True,help="Bounded source JSONL (read-only)")
    a.add_argument("--canonical",type=Path,required=True,help="Bounded canonical context JSONL (read-only)")
    a.add_argument("--source-sha256",required=True)
    a.add_argument("--canonical-sha256",required=True)
    a.add_argument("--max-rows",type=int,default=5000)
    args=a.parse_args(argv)
    if not 1<=args.max_rows<=10000:
        a.error("--max-rows must be 1..10000; full-scale sharding is separate")
    for p,expected in ((args.source,args.source_sha256),(args.canonical,args.canonical_sha256)):
        if re.fullmatch(r"[a-f0-9]{64}",expected) is None or sha(p)!=expected:
            raise ValueError("SHA256 input gate failed for "+str(p))
    left=read_events(args.source,args.max_rows)
    right=read_events(args.canonical,args.max_rows)
    report=comparison(left,right)
    report["source_sha256"]=sha(args.source)
    report["canonical_sha256"]=sha(args.canonical)
    print(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
