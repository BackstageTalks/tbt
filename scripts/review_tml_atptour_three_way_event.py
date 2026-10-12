#!/usr/bin/env python3
"""Three-source TML ↔ official ATP ↔ current CDB match witness review.

Read-only. All source rows remain import_ready=False. Official ATP native
match ID, exact ATP codes, scores, tournament ID, round and full canonical set
tape are required; metadata similarity alone is never a write authorization.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
import tarfile
from urllib.parse import urlparse

from prepare_tml_atp_cdb import select_source, verified_links
from link_offline_serve_return import _norm_round, _norm_text, _norm_surface
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

EXPECTED_ARCHIVES = {
  2022:"b7dbc286b2c6766436e8acacb7f584c850694c857e2458ec9e08a1afc40cee20",
  2023:"bbdb313ea06dd4cef8e4637d3a23c93e17bcb7106adb895e6e9556ed48d50c62",
  2024:"5bbe9756b263dc1cfd8ea7b095b24629fa9ace5ec4e7346e97e7a1dcaafab730",
  2025:"28c9c5924e62c6d07566c4f0815f9ceeac2a2454db6d7c7eb09c711323ab0755",
}
SET = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\((\d{1,2})\))?$")
SCORE = re.compile(r"^\s*(\d{1,2})(?:\s+(\d{1,2}))?\s*$")
EVENT = re.compile(r"^(\d{4})-(\d+)$")
MATCH = re.compile(r"^atptour:(\d{4}):(\d+):([A-Za-z0-9_-]+)$")


def source_score(score: str):
    out=[]
    for token in str(score or "").split():
        m=SET.fullmatch(token)
        if not m:
            return None
        out.append((int(m.group(1)),int(m.group(2)),
                    None if m.group(3) is None else int(m.group(3))))
    return tuple(out) if out else None


def round_key(value):
    return _norm_round(str(value or "").split(" - ",1)[0].strip())


def official_compatible(source: dict, official: dict) -> bool:
    """Exactly equal native ATP tournament, ATP player codes and finished sets."""
    event=EVENT.fullmatch(str(source.get("tourney_id") or ""))
    match=MATCH.fullmatch(str(official.get("source_match_id") or ""))
    if not event or not match or event.group(1)!=match.group(1) or event.group(2)!=match.group(2):
        return False
    if match.group(3).startswith("listing-"):
        return False  # Require ATP's actual match-stats native link, not a listing hash.
    if official.get("source")!="atptour" or str(official.get("source_tournament_id"))!="atptour:tournament:"+match.group(2):
        return False
    url=str(official.get("source_url") or "")
    if urlparse(url).hostname not in {"www.atptour.com","atptour.com"}:
        return False
    if not round_key(source.get("round")) or round_key(source.get("round"))!=round_key(official.get("round")):
        return False
    sides=official.get("sides")
    if not isinstance(sides,list) or len(sides)!=2:
        return False
    codes=[]
    for side in sides:
        players=side.get("players") if isinstance(side,dict) else None
        if not isinstance(players,list) or len(players)!=1:
            return False
        code=str(players[0].get("atp_player_id") or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{2,32}",code):
            return False
        codes.append(code)
    winner=str(source.get("winner_id") or "").upper()
    loser=str(source.get("loser_id") or "").upper()
    if len(set(codes))!=2 or set(codes)!={winner,loser}:
        return False
    marked=[i for i,s in enumerate(sides) if s.get("winner_marker") is True]
    # A source page may omit the decorative winner icon. Reject contradictory
    # icons; otherwise derive the winner independently from the full ATP
    # set-by-set scoreboard, never from the TML winner label alone.
    if len(marked)>1 or (len(marked)==1 and codes[marked[0]]!=winner):
        return False
    tape=source_score(source.get("score"))
    if tape is None:
        return False
    games=[]
    for side in sides:
        cells=side.get("scores")
        if not isinstance(cells,list) or len(cells)!=len(tape):
            return False
        decoded=[SCORE.fullmatch(str(cell)) for cell in cells]
        if any(m is None for m in decoded):
            return False
        games.append([(int(m.group(1)),int(m.group(2)) if m.group(2) is not None else None) for m in decoded])
    independent_winner_idx=codes.index(winner)
    official_win_sets=0
    official_loss_sets=0
    for i,(sw,sl,tb) in enumerate(tape):
        a,b=(games[0][i],games[1][i]) if codes[0]==winner else (games[1][i],games[0][i])
        if (a[0],b[0])!=(sw,sl):
            return False
        official_win_sets+=int(a[0]>b[0])
        official_loss_sets+=int(a[0]<b[0])
        # ATP official score widgets put the TB loser points on the losing side.
        if tb is not None:
            loser_tb=a[1] if sw<sl else b[1]
            if loser_tb!=tb:
                return False
    needed={"3":2,"5":3}.get(str(source.get("best_of")))
    if needed is None or official_win_sets!=needed or official_loss_sets>=needed:
        return False
    return True


def canonical_compatible(source:dict, match, ids:dict) -> bool:
    win=ids.get(str(source.get("winner_id") or "").upper())
    lose=ids.get(str(source.get("loser_id") or "").upper())
    if not win or not lose or win==lose:
        return False
    if str(match.tour).lower()!="atp" or {str(match.player1_id),str(match.player2_id)}!={win,lose}:
        return False
    if str(match.winner_id)!=win:
        return False
    if _norm_text(source.get("tourney_name"))!=_norm_text(match.tournament):
        return False
    if round_key(source.get("round"))!=round_key(match.round_name):
        return False
    if _norm_surface(source.get("surface"))!=_norm_surface(match.surface):
        return False
    if str(source.get("best_of"))!=str(match.best_of):
        return False
    try:
        from datetime import datetime
        first=datetime.strptime(source["tourney_date"],"%Y%m%d").date()
        lag=(match.scheduled_at.date()-first).days
    except (TypeError,ValueError,AttributeError):
        return False
    if not -1<=lag<=16:
        return False
    tape=source_score(source.get("score"))
    if not tape:
        return False
    stats=match.stats or {}
    if not isinstance(stats,dict):
        return False
    for n,(w,l,_) in enumerate(tape,1):
        values=(w,l) if str(match.player1_id)==win else (l,w)
        for ix,val in enumerate(values,1):
            stored=stats.get(f"p{ix}_set{n}_games")
            if isinstance(stored,bool):
                return False
            try:
                if float(stored)!=val:
                    return False
            except (TypeError,ValueError):
                return False
    for n in range(len(tape)+1,6):
        if any(stats.get(f"p{ix}_set{n}_games") not in (None,"") for ix in (1,2)):
            return False
    return True




def native_event_recovery_record(source: dict, official: dict, year: int):
    """Private source-only candidate, NEVER an identity witness or write permission."""
    event=EVENT.fullmatch(str(source.get("tourney_id") or ""))
    match=MATCH.fullmatch(str(official.get("source_match_id") or ""))
    if not event or not match or str(year)!=event.group(1) or str(year)!=match.group(1):
        return None
    if event.group(2)!=match.group(2):
        return None
    if (official.get("source")!="atptour" or
        official.get("source_tournament_id")!="atptour:tournament:"+event.group(2) or
        urlparse(str(official.get("source_url") or "")).hostname not in
        {"atptour.com","www.atptour.com"}):
        return None
    if not round_key(source.get("round")) or round_key(source.get("round"))!=round_key(official.get("round")):
        return None
    sides=official.get("sides")
    if not isinstance(sides,list) or len(sides)!=2:
        return None
    codes=[]
    for side in sides:
        persons=side.get("players") if isinstance(side,dict) else None
        if not isinstance(persons,list) or len(persons)!=1 or not isinstance(persons[0],dict):
            return None
        code=str(persons[0].get("atp_player_id") or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{2,32}",code):
            return None
        codes.append(code)
    original_pair={str(source.get("winner_id") or "").upper(),
                   str(source.get("loser_id") or "").upper()}
    if len(set(codes))!=2 or set(codes)!=original_pair:
        return None
    tape=source_score(source.get("score"))
    if tape is None:
        return None
    if match.group(3).startswith("listing-"):
        reason="SYNTHETIC_LISTING_ID_REQUIRES_OFFICIAL_NATIVE_MATCH"
    elif any(not isinstance(side.get("scores"),list) or len(side["scores"])!=len(tape)
             for side in sides):
        reason="NATIVE_MATCH_ID_OFFICIAL_SET_COUNT_MISMATCH"
    else:
        reason="NATIVE_MATCH_ID_REQUIRES_FULL_INDEPENDENT_SCORE_REVIEW"
    return {
        "schema":1,
        "source_namespace":"tml-atp",
        "source_year":year,
        "source_tourney_id":source["tourney_id"],
        "source_match_num":source["match_num"],
        "source_winner_atp_id":source["winner_id"],
        "source_loser_atp_id":source["loser_id"],
        "source_finished_score":source["score"],
        "source_round":source["round"],
        "official_candidate_match_id":official["source_match_id"],
        "official_tournament_id":official["source_tournament_id"],
        "official_source_url":official["source_url"],
        "official_archive_sha256":EXPECTED_ARCHIVES[year],
        "reason":reason,
        "canonical_match_id":None,
        "official_identity_verified":False,
        "import_ready":False,
        "write_authorized":False,
        "model_feature_allowed":False,
    }


def original_archive(path:Path, year:int):
    h=hashlib.sha256(path.read_bytes()).hexdigest()
    if h!=EXPECTED_ARCHIVES[year]:
        raise ValueError(f"Official ATP archive SHA mismatch: {year}")
    rows=[]
    prefix=f"data/atptour/archive/{year}/"
    with tarfile.open(path,"r:gz") as tar:
        for member in tar:
            if (not member.isfile() or member.issym() or member.islnk()
                or not member.name.startswith(prefix)
                or not member.name.endswith(".jsonl")
                or "/" in member.name[len(prefix):]):
                continue
            with tar.extractfile(member) as stream:
                for line in stream:
                    if line.strip():
                        record=json.loads(line)
                        if not isinstance(record,dict):
                            raise ValueError("Malformed official ATP record")
                        rows.append(record)
    return rows,h


def compare(source_dir:Path, archive_dir:Path, history_dir:Path,
            private_crosswalk:Path, crosswalk_sha:str, out:Path):
    links,_=verified_links(private_crosswalk,crosswalk_sha)
    links={code.upper():cid for code,cid in links.items()}
    archive=defaultdict(list)
    report=Counter()
    for year in EXPECTED_ARCHIVES:
        candidates,_,_,_=select_source(source_dir/f"{year}.csv",year)
        records,_=original_archive(archive_dir/f"official-{year}.tar.gz",year)
        for rec in records:
            m=MATCH.fullmatch(str(rec.get("source_match_id") or ""))
            if m and int(m.group(1))==year:
                archive[(year,m.group(2))].append(rec)
        report["official_archive_records"]+=len(records)
        report["source_p0_rows"]+=len(candidates)
    matches,safety=sanitize_history_identities(load_partitions(history_dir))
    if safety.get("quarantined_rows"):
        raise ValueError("Current canonical identity safety failed")
    index=defaultdict(list)
    for m in matches:
        if str(m.tour).lower()=="atp":
            index[(frozenset((str(m.player1_id),str(m.player2_id))),m.scheduled_at.year)].append(m)
    recovery_queue=[]
    seen_src=defaultdict(list)
    seen_atp=defaultdict(list)
    seen_cdb=defaultdict(list)
    for year in EXPECTED_ARCHIVES:
        source_rows,_,_,_=select_source(source_dir/f"{year}.csv",year)
        for row in source_rows:
            report["source_checked"]+=1
            event=EVENT.fullmatch(str(row.get("tourney_id") or ""))
            win=links.get(str(row.get("winner_id") or "").upper())
            lose=links.get(str(row.get("loser_id") or "").upper())
            if not event or not win or not lose or win==lose:
                report["blocked_tourney_or_two_player_ID"]+=1
                continue
            atptour_rows=archive.get((year,event.group(2)),[])
            if not atptour_rows:
                report["no_official_tournament_archive_records"]+=1
            else:
                report["source_with_official_tournament_archive"]+=1
            original_pair={str(row.get("winner_id") or "").upper(),
                           str(row.get("loser_id") or "").upper()}
            for candidate in atptour_rows:
                if not str(candidate.get("source_match_id") or "").split(":")[-1].startswith("listing-"):
                    report["native_official_match_id_in_same_tournament"]+=1
                sides=candidate.get("sides")
                if not isinstance(sides,list) or len(sides)!=2:
                    continue
                candidate_ids=[]
                for side in sides:
                    persons=side.get("players") if isinstance(side,dict) else None
                    candidate_ids.append(str(persons[0].get("atp_player_id") or "").upper()
                                         if isinstance(persons,list) and len(persons)==1 else "")
                if set(candidate_ids)==original_pair and len(original_pair)==2:
                    report["same_official_atp_player_pair"]+=1
                    if round_key(candidate.get("round"))==round_key(row.get("round")):
                        report["same_official_pair_and_round"]+=1
                    if not any(x.get("winner_marker") is True for x in sides):
                        report["same_official_pair_missing_winner_icon"]+=1
                    if round_key(candidate.get("round"))!=round_key(row.get("round")):
                        continue
                    candidate_recovery=native_event_recovery_record(row,candidate,year)
                    if candidate_recovery is not None:
                        recovery_queue.append(candidate_recovery)
                    if str(candidate.get("source_match_id") or "").split(":")[-1].startswith("listing-"):
                        report["same_official_pair_round_synthetic_id"]+=1
                        continue
                    report["same_official_pair_round_native_id"]+=1
                    tape=source_score(row.get("score"))
                    if tape is None:
                        report["same_official_pair_round_bad_source_score"]+=1
                        continue
                    if any(not isinstance(x.get("scores"),list) or len(x["scores"])!=len(tape) for x in sides):
                        report["same_official_pair_round_set_count_mismatch"]+=1
                        continue
                    report["same_official_pair_round_matching_set_count"]+=1
                    parsed=[[SCORE.fullmatch(str(cell)) for cell in side["scores"]] for side in sides]
                    if any(m is None for side in parsed for m in side):
                        report["same_official_pair_round_unparsed_official_score_cells"]+=1
                        continue
                    report["same_official_pair_round_numeric_score_cells"]+=1
                    src_side=0 if candidate_ids[0]==str(row.get("winner_id") or "").upper() else 1
                    full_equal=all(
                      int(parsed[src_side][n].group(1))==w and
                      int(parsed[1-src_side][n].group(1))==l
                      for n,(w,l,tb) in enumerate(tape))
                    if not full_equal:
                        report["same_official_pair_round_set_game_disagreement"]+=1
                    else:
                        report["same_official_pair_round_full_games_equal"]+=1
                        if official_compatible(row,candidate):
                            report["same_official_pair_round_strict_atp_witness"]+=1
                        else:
                            report["same_official_pair_round_remaining_tiebreak_or_metadata_disagreement"]+=1
            official=[o for o in atptour_rows if official_compatible(row,o)]
            if len(official)!=1:
                report["blocked_official_missing_or_ambiguous"]+=1
                continue
            report["official_match_witnessed"]+=1
            canonical=[m for m in index.get((frozenset((win,lose)),year),[])
                       if canonical_compatible(row,m,links)]
            if len(canonical)!=1:
                report["blocked_canonical_set_tape_or_identity"]+=1
                continue
            m=canonical[0];o=official[0]
            rec={"source_tourney_id":row["tourney_id"],"source_match_num":row["match_num"],
                 "official_atp_match_id":o["source_match_id"],"canonical_match_id":str(m.match_id),
                 "source_year":year,"independent_official_event_corrob":True,
                 "canonical_complete_set_tape_corrob":True,
                 "import_ready":False,"write_authorized":False}
            seen_src[(row["tourney_id"],row["match_num"])].append(rec)
            seen_atp[o["source_match_id"]].append(rec)
            seen_cdb[str(m.match_id)].append(rec)
    accepted=[]
    for group in seen_src.values():
        for rec in group:
            if (len(group)==1 and len(seen_atp[rec["official_atp_match_id"]])==1
                and len(seen_cdb[rec["canonical_match_id"]])==1):
                accepted.append(rec)
            else:
                report["blocked_nonunique_three_way_link"]+=1
    report["three_way_official_review_candidates"]=len(accepted)
    proven={(r["source_tourney_id"],r["source_match_num"],r["official_atp_match_id"])
            for r in accepted}
    pending={}
    for item in recovery_queue:
        key=(item["source_tourney_id"],item["source_match_num"],item["official_candidate_match_id"])
        if key not in proven:
            pending[key]=item
    ordered_recovery=[pending[key] for key in sorted(pending)]
    report["private_native_id_recovery_candidates"]=len(ordered_recovery)
    report["recovery_synthetic_listing_ids"]=sum(
        x["reason"]=="SYNTHETIC_LISTING_ID_REQUIRES_OFFICIAL_NATIVE_MATCH"
        for x in ordered_recovery)
    report["recovery_native_set_count_mismatches"]=sum(
        x["reason"]=="NATIVE_MATCH_ID_OFFICIAL_SET_COUNT_MISMATCH"
        for x in ordered_recovery)
    out.mkdir(parents=True,exist_ok=True)
    recovery_file=out/"private-native-id-recovery-queue.jsonl"
    recovery_file.write_text("".join(json.dumps(x,sort_keys=True)+"\n"
                                    for x in ordered_recovery))
    dest=out/"private-three-way-candidates.jsonl"
    dest.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in accepted))
    summary={"status":"THREE_WAY_OFFICIAL_ATP_READ_ONLY",
       "counts":dict(sorted(report.items())),
       "official_archive_sha256":EXPECTED_ARCHIVES,
       "verified_crosswalk_sha256":crosswalk_sha,
       "private_review_sha256":hashlib.sha256(dest.read_bytes()).hexdigest(),
       "native_id_recovery_queue_sha256":hashlib.sha256(recovery_file.read_bytes()).hexdigest(),
       "source_to_provider_native_id_direct_equality_proven":False,
       "ready_for_cdb_write":0,"cdb_writes":0,"api_requests":0,"model_trained":False}
    (out/"report.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    return summary


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("source-dir","archive-dir","history-dir","verified-crosswalk","out"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--crosswalk-sha256",required=True)
    a=p.parse_args()
    print(json.dumps(compare(a.source_dir,a.archive_dir,a.history_dir,
                             a.verified_crosswalk,a.crosswalk_sha256,a.out),sort_keys=True))
