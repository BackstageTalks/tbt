#!/usr/bin/env python3
"""One-shot verified Oct 12 provider-final tennis outcomes -> private canonical CDB.

Strictly additive: never rewrite an existing match identity/outcome or model label;
never infer a result from scheduled time. A private source release and provider
final score jointly attest each candidate. Only provider IDs already uniquely
crosswalked to canonical player IDs in the current 2026 partition are eligible.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from _bootstrap import ROOT  # noqa: F401
from cdb_global_writer_lock import acquire, release
from propline_nightly_cdb import fetch_current
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_snapshot, write_year_partition
from tbt.data.offline_odds import norm_text
from tbt.providers.rapidapi import RapidTennisClient
from tbt.config import settings
from tbt.services.match_status import (
    prediction_rows, _provider_rows, _provider_event_id,
    classify_finished_event, _verified_final_score_stats, _parse_time,
)

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
YEAR = 2026
DAY = date(2026, 10, 12)
FROZEN_NOW = datetime(2026, 10, 12, 21, 30, tzinfo=timezone.utc)
ASSETS = ("history-2026.parquet", "history_manifest.json", "_tbt_bundle_manifest.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_evidence(feed_path: Path, stage_path: Path) -> tuple[dict, dict, dict]:
    source = json.loads(feed_path.read_text(encoding="utf-8"))
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    if (
        stage.get("schema") != 1 or stage.get("source_date") != DAY.isoformat()
        or stage.get("feed_sha256") != digest(feed_path)
        or stage.get("cdb_canonical_rows_written") != 0
        or stage.get("cdb_import_authorized") is not False
        or not isinstance(stage.get("candidates"), list)
        or len(stage["candidates"]) > 60
    ):
        raise RuntimeError("Frozen source stage does not satisfy no-write SHA contract")
    rows = prediction_rows(source, now=FROZEN_NOW)
    if not rows:
        raise RuntimeError("Frozen private source release has no published fixtures")
    return source, stage, rows


def strict_unique_map(matches):
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    event_ids: dict[str, set[str]] = defaultdict(set)
    days: dict[tuple[str, str, tuple[str, str]], set[str]] = defaultdict(set)
    ids: set[str] = set()
    for m in matches:
        mid = str(m.match_id)
        if not mid or mid in ids:
            raise RuntimeError("Nonunique existing canonical match identity")
        ids.add(mid)
        tour = str(m.tour or "").lower()
        for pid, pname in ((m.player1_id, m.player1_name), (m.player2_id, m.player2_name)):
            if norm_text(pname):
                names[(tour, norm_text(pname))].add(str(pid))
        day_key = m.scheduled_at.astimezone(timezone.utc).date().isoformat()
        pair = tuple(sorted((str(m.player1_id), str(m.player2_id))))
        days[(tour, day_key, pair)].add(mid)
        payload = m.provider_payload if isinstance(m.provider_payload, dict) else {}
        provider = next((str(payload[k]) for k in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId") if payload.get(k)), "")
        if provider:
            event_ids[provider].add(mid)
    return names, event_ids, days, ids


def stage_rows(before, stage, source_rows, provider_rows):
    names, event_ids, days, existing_ids = strict_unique_map(before)
    grouped = defaultdict(list)
    for e in provider_rows:
        if isinstance(e, dict) and _provider_event_id(e):
            grouped[_provider_event_id(e)].append(e)
    reasons = Counter()
    prepared = []
    used = set()

    def reject(reason):
        reasons[reason] += 1

    for evidence in stage["candidates"]:
        if not isinstance(evidence, dict) or evidence.get("source") != "rapidapi_tennisapi_daily_event":
            reject("untrusted_source_stage"); continue
        eid = str(evidence.get("provider_event_id") or "")
        row = source_rows.get(eid)
        if not eid.isdigit() or not row or eid in used:
            reject("missing_or_duplicate_frozen_source"); continue
        used.add(eid)
        events = grouped.get(eid, [])
        if len(events) != 1:
            reject("missing_or_duplicate_live_provider_event"); continue
        event = events[0]
        tour = str(evidence.get("tour") or "").lower()
        if tour not in {"atp", "wta"} or tour != str(row.get("tour") or "").lower():
            reject("tour_conflict"); continue
        if evidence.get("cdb_import_allowed") is not False:
            reject("unexpected_source_import_permission"); continue

        feed_sides = [row.get("player1") or {}, row.get("player2") or {}]
        ids = [str(p.get("id") or "") for p in feed_sides]
        display = [str(p.get("name") or "") for p in feed_sides]
        if (
            not all(ids) or len(set(ids)) != 2 or not all(display)
            or len(set(map(norm_text, display))) != 2
            or set(ids) != {str(evidence.get("player1_provider_id")), str(evidence.get("player2_provider_id"))}
        ):
            reject("frozen_provider_player_disagreement"); continue

        mapped = []
        for pid, pname in zip(ids, display):
            options = names.get((tour, norm_text(pname)), set())
            if options != {pid}:
                break
            mapped.append(pid)
        if len(mapped) != 2:
            reject("canonical_player_crosswalk_not_unique"); continue

        scheduled = _parse_time(row.get("scheduled_at") or row.get("date"))
        if not scheduled or scheduled.date() != DAY or scheduled > FROZEN_NOW:
            reject("frozen_start_day_invalid"); continue
        if eid in event_ids:
            reject("provider_event_already_in_canonical"); continue
        pair_key = (tour, DAY.isoformat(), tuple(sorted(ids)))
        if pair_key in days:
            reject("same_day_canonical_player_pair_exists"); continue

        identity_row = {"event_id": eid, "player1":{"id":ids[0]}, "player2":{"id":ids[1]},
                        "betting":{"selection_id":str(evidence.get("winner_provider_id") or "")}}
        verified = classify_finished_event(identity_row, event, checked_at=FROZEN_NOW)
        score = _verified_final_score_stats(identity_row, event)
        if (
            not verified or verified.get("status") != "win"
            or str(verified.get("winner_id") or "") != str(evidence.get("winner_provider_id") or "")
            or not score or score.get("total_sets") != evidence.get("total_sets")
            or score.get("total_games") != evidence.get("total_games")
        ):
            reject("provider_final_score_or_winner_unverified"); continue

        safe_event = dict(event)
        safe_event["_tbt_provider_event_id"] = eid
        safe_event["_tbt_event_identity"] = {
            "event_id":eid,
            "home":str((event.get("homeTeam") or {}).get("id") or ""),
            "away":str((event.get("awayTeam") or {}).get("id") or ""),
            "status":"finished",
        }
        try:
            item = RapidTennisClient.normalize_match(safe_event, tour=tour, historical=True)
        except (ValueError, TypeError, KeyError) as exc:
            reject("normalization_rejected_" + type(exc).__name__); continue
        if (
            item.scheduled_at.date() != DAY
            or {str(item.player1_id), str(item.player2_id)} != set(ids)
            or str(item.winner_id or "") != str(evidence["winner_provider_id"])
            or str(item.status or "").lower() not in {"finished","completed","ended","ft"}
            or {norm_text(item.player1_name),norm_text(item.player2_name)} != set(map(norm_text,display))
            or str(item.match_id) in existing_ids
            or not item.tournament or not str(item.surface or "").strip()
        ):
            reject("normalized_identity_or_outcome_conflict"); continue
        if item.scheduled_at.isoformat() != scheduled.isoformat():
            reject("provider_scheduled_time_conflict"); continue

        source_surface = str(row.get("surface") or "").lower()
        if source_surface and source_surface != str(item.surface).lower():
            reject("provider_surface_conflict"); continue

        stage_stats = dict(item.stats or {})
        # Every proposed historical score uses strictly the completed event;
        # no odds, current ranking or model projection enters the CDB.
        if str(item.match_id) in {str(v.match_id) for v in prepared}:
            reject("internal_new_match_id_collision"); continue
        prepared.append(item)
        reasons["validated_new_match_rows"] += 1
    return prepared, dict(sorted(reasons.items()))


def independent_compare(before, after, added):
    old = {str(m.match_id):m.to_storage_dict() for m in before}
    new = {str(m.match_id):m.to_storage_dict() for m in after}
    expected = {str(m.match_id):m.to_storage_dict() for m in added}
    if len(old)!=len(before) or len(new)!=len(after) or len(expected)!=len(added):
        raise RuntimeError("Canonical duplicate key in independent comparison")
    if set(new) != set(old) | set(expected) or set(old) & set(expected):
        raise RuntimeError("Canonical row identity replacement/disappearance")
    for mid, value in old.items():
        if new[mid] != value:
            raise RuntimeError("Existing canonical row modified: "+mid)
    for mid,value in expected.items():
        if new[mid] != value:
            raise RuntimeError("Verified new match differs after readback: "+mid)
    return {"existing_rows_unchanged":len(old),"new_rows_verified":len(expected),
            "total_rows_after":len(new),"overwritten_existing_rows":0}


def run(stage_path: Path, feed_path: Path, out_path: Path):
    report={"schema":1,"date":DAY.isoformat(),"status":"STARTED","cdb_updated":False}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    def write():
        out_path.write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
        print("OCT12_CDB_GUARDED_IMPORT "+json.dumps(report,sort_keys=True,ensure_ascii=False),flush=True)
    try:
        if os.environ.get("TBT_DATA_REPOSITORY",REPO) != REPO:
            raise RuntimeError("Wrong canonical repository")
        source,stage,source_rows=load_evidence(feed_path,stage_path)
        report["source_feed_sha256"]=stage["feed_sha256"]
        report["stage_verified_results"]=len(stage["candidates"])
        client=RapidTennisClient(settings)
        client.request_limit=12
        client.retry_attempts=1
        client.client.timeout=6.0
        try:
            daily=client.events_for_status_day(DAY,target_event_ids={
                str(x.get("provider_event_id")) for x in stage["candidates"]
            },max_category_requests=8)
            provider_rows=_provider_rows(daily)
            report["provider_requests"]=client.request_count
        finally:
            client.close()
        local=Path("/tmp/blinq-oct12-import")
        first=local/"initial"
        baseline,original_sha=fetch_current(first)
        prepared,reasons=stage_rows(baseline,stage,source_rows,provider_rows)
        report.update({"original_canonical_sha256":original_sha,
                       "candidate_counts":reasons,"eligible_new_rows":len(prepared)})
        if not prepared:
            report["status"]="NO_SAFE_CANONICAL_CHANGES"
            write();return
        report["proposed_match_ids"]=[str(m.match_id) for m in prepared]
        report["status"]="PREPARED_LOCK_PENDING"
        write()
        lock_state=Path(".cdb-global-writer-lock.json")
        acquire(REPO,lock_state,wait_seconds=900)
        try:
            locked=local/"locked"
            before,fresh_sha=fetch_current(locked)
            restaged,locked_reasons=stage_rows(before,stage,source_rows,provider_rows)
            if not restaged:
                report.update(status="NO_SAFE_NEW_ROWS_AFTER_LOCK",locked_reasons=locked_reasons)
                write();return
            if {str(m.match_id) for m in restaged} != {str(m.match_id) for m in prepared}:
                raise RuntimeError("Preflight identity changed while waiting for canonical writer lock")
            work=local/"work"
            work.mkdir(parents=True,exist_ok=True)
            for name in ASSETS:
                shutil.copy2(locked/name, work/name)
            write_year_partition(before+restaged,work,YEAR)
            after_local=load_snapshot(work/"history-2026.parquet")
            local_readback=independent_compare(before,after_local,restaged)
            if local_readback["new_rows_verified"]!=len(restaged):
                raise RuntimeError("Local whole-partition readback mismatch")
            # Update only two canonical assets; ReleaseStore transactional
            # manifest/bundle publishing preserves all other historical years.
            ReleaseStore(REPO,TAG,work).upload_bundle(
                [work/"history-2026.parquet",work/"history_manifest.json"])
            remote=local/"readback"
            persisted,published_sha=fetch_current(remote)
            verified=independent_compare(before,persisted,restaged)
            if verified != local_readback:
                raise RuntimeError("Remote complete-year readback differs from local preflight")
            report.update(status="VERIFIED_CDB_IMPORT",cdb_updated=True,
                          canonical_source_sha256=fresh_sha,
                          canonical_published_sha256=published_sha,
                          verification=verified,imported_new_rows=len(restaged),
                          eligible_match_ids=[str(x.match_id) for x in restaged])
            write()
        finally:
            release(REPO,lock_state,if_held=True)
    except Exception as exc:
        report["status"]="BLOCKED_SAFE_NO_FURTHER_WRITES"
        report["blocking_error_type"]=type(exc).__name__
        report["blocking_message"]=str(exc)[:180]
        write()
        raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--stage",type=Path,required=True)
    p.add_argument("--feed",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    run(args.stage,args.feed,args.report)

if __name__ == "__main__":
    main()
