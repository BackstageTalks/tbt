#!/usr/bin/env python3
"""Apply only uniquely corroborated missing historical stats to existing canonical matches.
No new matches; no odds; no model features; no provider calls. Full private
snapshot/rollback, one-writer lock and persisted after-write verification required.
"""
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

REPO = "BackstageTalks/tbt-data"
ROOT = Path(".cache/tbt/autonomous-safe-existing")
HISTORY = ROOT / "history"
ORIGINAL = ROOT / "original"
AUDIT = runpy.run_path("scripts/research/nightly_private_canonical_gap_scan.py")
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.history_safety import sanitize_history_identities
from import_blinq_offline_bundle import (
    _candidate, _chart_date, _chart_stats, _date, _merge_stats, _name,
    _pair, _round, _source_key, _stats, _surface, tournament_score,
)

def same_release(proof):
    current = AUDIT["release_history"]()
    original = {name: (v["source_id"], v["bytes"], "sha256:" + v["sha256"])
                for name, v in proof["sha256"].items()}
    return current == original

def strict_candidate(source, match):
    if str(match.tour).lower() != "atp":
        return False
    evidence = _candidate(source, match)
    if evidence is None:
        return False
    if _round(source["round"]) != _round(match.round_name):
        return False
    a, b = _surface(source["row"].get("surface")), _surface(match.surface)
    if a not in ("unknown", "") and b not in ("unknown", "") and a != b:
        return False
    score, tournament_evidence, gap = evidence
    # Original linker has both winner and pair agreement; this adds strict round
    # and surface agreement. Tournament name must carry positive source evidence.
    return score >= 8 and gap <= 21 and bool(tournament_evidence)

def source_grouped(rows, matches):
    by_pair = defaultdict(list)
    for match in matches:
        if str(match.tour).lower() == "atp":
            by_pair[_pair(match.player1_name, match.player2_name)].append(match)
    counts = Counter()
    linked = defaultdict(list)
    seen_keys = set()
    for row in rows:
        counts["futures_rows_read"] += 1
        d = _date(row.get("tourney_date"))
        w = str(row.get("winner_name") or "").strip()
        l = str(row.get("loser_name") or "").strip()
        if d is None or not w or not l or _name(w) == _name(l):
            counts["futures_bad_identity"] += 1
            continue
        key = _source_key(row)
        if key in seen_keys:
            counts["futures_duplicate_source_key"] += 1
            continue
        seen_keys.add(key)
        src = {"row": row, "date": d, "pair": _pair(w, l), "winner": w,
               "tournament": str(row.get("tourney_name") or ""),
               "round": str(row.get("round") or "")}
        candidates = [m for m in by_pair.get(src["pair"], []) if strict_candidate(src, m)]
        if len(candidates) != 1:
            counts["futures_no_unique_verified_canonical_link"] += 1
            continue
        linked[str(candidates[0].match_id)].append((candidates[0], row))
        counts["futures_unique_link"] += 1
    return linked, counts

def process_futures(path, matches, updated_before, changed, counts, quarantine):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        grouped, observations = source_grouped(csv.DictReader(f), matches)
    counts.update(observations)
    for match_id, items in grouped.items():
        if len(items) != 1:
            counts["futures_many_sources_one_match"] += 1
            continue
        match, row = items[0]
        stats = _stats(row)
        if not stats:
            counts["futures_no_stats"] += 1
            continue
        before = dict(match.stats or {})
        if any(before.get(k) is not None and abs(float(before[k]) - float(v)) > 1e-6
               for k, v in stats.items()):
            counts["futures_stat_conflict_skipped"] += 1
            continue
        additions = {k: v for k, v in stats.items() if before.get(k) is None}
        if not additions:
            counts["futures_already_present"] += 1
            continue
        updated_before[match_id] = before
        match.stats = {**before, **additions}
        changed.add(match.scheduled_at.year)
        counts["futures_updated_matches"] += 1
        counts["futures_added_values"] += len(additions)

def process_charting(paths, matches, updated_before, changed, counts, quarantine):
    by_pair = defaultdict(list)
    for m in matches:
        by_pair[(str(m.tour).lower(), _pair(m.player1_name, m.player2_name))].append(m)
    accepted = defaultdict(list)
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                counts["charting_rows_read"] += 1
                tour = str(row.get("sex") or "").lower()
                player, opponent = str(row.get("player") or ""), str(row.get("opponent") or "")
                date = _chart_date(row)
                if tour not in ("atp", "wta") or date is None or not player or not opponent:
                    counts["charting_unreadable"] += 1
                    continue
                # Same match identity must be demonstrable beyond name + date.
                source_tourney = str(row.get("tournament") or row.get("tourney") or "")
                source_round = str(row.get("round") or "")
                if not source_tourney or not source_round:
                    counts["charting_missing_tournament_or_round_provenance"] += 1
                    continue
                options = []
                for m in by_pair.get((tour, _pair(player, opponent)), []):
                    if abs((m.scheduled_at.date() - date.date()).days) > 1:
                        continue
                    if _round(m.round_name) != _round(source_round):
                        continue
                    score, _ = tournament_score(source_tourney, m.tournament)
                    if score <= 0:
                        continue
                    options.append(m)
                if len(options) != 1:
                    counts["charting_unverified_identity"] += 1
                    continue
                m = options[0]
                if _name(player) not in (_name(m.player1_name), _name(m.player2_name)):
                    counts["charting_no_side_orientation"] += 1
                    continue
                prefix = "p1" if _name(player) == _name(m.player1_name) else "p2"
                vals = {prefix + "_" + k: v for k, v in _chart_stats(row).items()}
                if vals:
                    accepted[str(m.match_id)].append((m, vals))
    for mid, entries in accepted.items():
        match = entries[0][0]
        combined = {}
        contradictory = False
        for _, vals in entries:
            for k, v in vals.items():
                if k in combined and abs(float(combined[k]) - float(v)) > 1e-6:
                    contradictory = True
                combined[k] = v
        if contradictory:
            counts["charting_internal_conflict"] += 1
            continue
        before = dict(match.stats or {})
        if any(before.get(k) is not None and abs(float(before[k]) - float(v)) > 1e-6
               for k, v in combined.items()):
            counts["charting_existing_conflict_skipped"] += 1
            continue
        additions = {k: v for k, v in combined.items() if before.get(k) is None}
        if not additions:
            counts["charting_already_present"] += 1
            continue
        updated_before.setdefault(mid, before)
        match.stats = {**before, **additions}
        changed.add(match.scheduled_at.year)
        counts["charting_updated_matches"] += 1
        counts["charting_added_values"] += len(additions)

def verify_local(before_count, original_stats, changed, updated_matches):
    matches, safety = sanitize_history_identities(load_partitions(HISTORY))
    if safety.get("quarantined_rows") or len(matches) != before_count:
        raise ValueError("Local canonical identity or row count changed")
    by_id = {str(m.match_id): m for m in matches}
    for mid, old in original_stats.items():
        updated = by_id[mid].stats or {}
        if any(k not in updated or updated[k] != v for k, v in old.items()):
            raise ValueError("Original non-null historical stats changed")
        if not set(updated).issuperset(set(old)):
            raise ValueError("Historical stat keys disappeared")
    if any(y not in {m.scheduled_at.year for m in matches} for y in changed):
        raise ValueError("Changed year unexpectedly absent")
    del matches, by_id

def main():
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("Private credentials unavailable")
    ROOT.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "run_id": os.environ.get("GITHUB_RUN_ID"),
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "status": "running", "backup_tag": AUDIT["BACKUP_TAG"],
              "provider_requests": 0, "production_mutated": False,
              "new_match_rows": 0, "model_promoted": False}
    target = f"audit/autonomous-safe-existing-enrichment-{os.environ['GITHUB_RUN_ID']}.json"
    try:
        proof = AUDIT["verify_backup"]()
        source_report = AUDIT["reconstruct_sources"]()
        report["input_sources"] = source_report
        store = ReleaseStore(REPO, "tbt-data-v1", HISTORY)
        store.download(require_bundle_manifest=True)
        matches, safety = sanitize_history_identities(load_partitions(HISTORY))
        if safety.get("quarantined_rows"):
            raise ValueError("Canonical identities quarantined")
        before_count = len(matches)
        report["canonical_before"] = before_count
        # The in-memory mutation touches only fields that were NULL in an
        # existing, uniquely identified record; it never appends rows.
        updated_before = {}
        changed = set()
        counts = Counter()
        quarantine = []
        src = AUDIT["SOURCE"]
        process_futures(src / "blinq_atp_futures_quali_2018_2026.csv", matches,
                        updated_before, changed, counts, quarantine)
        process_charting([src / "blinq_charting_atp_core_features.csv",
                          src / "blinq_charting_wta_core_features.csv"],
                         matches, updated_before, changed, counts, quarantine)
        report["counts"] = dict(counts)
        report["changed_years"] = sorted(changed)
        report["unique_updated_matches"] = len(updated_before)
        report["canonical_projected_after"] = len(matches)
        if len(matches) != before_count:
            raise ValueError("No new matches allowed in conservative historical stats writer")
        if len(changed) > 40:
            report["status"] = "safely_staged_too_many_years_for_single_run"
            return
        if not changed:
            report["status"] = "nothing_safe_to_add_from_verified_existing_links"
            return
        ORIGINAL.mkdir(parents=True)
        for y in changed:
            shutil.copy2(HISTORY / f"history-{y:04d}.parquet", ORIGINAL)
        shutil.copy2(HISTORY / "history_manifest.json", ORIGINAL)
        for year in sorted(changed):
            write_year_partition(matches, HISTORY, year,
                                 extra_manifest={"coverage_status": "autonomous_strict_source_null_fill"})
        del matches
        verify_local(before_count, updated_before, changed, len(updated_before))
        report["status"] = "local_candidate_verified"
        if not same_release(proof):
            report["status"] = "release_changed_since_backup_publish_blocked"
            return
        paths = [HISTORY / f"history-{y:04d}.parquet" for y in sorted(changed)]
        paths.append(HISTORY / "history_manifest.json")
        publishing = True
        try:
            store.upload_bundle(paths, before_upload=lambda: (
                None if same_release(proof) else (_ for _ in ()).throw(
                    ValueError("Source history release changed before publish"))))
            remote = ROOT / "persisted"
            ReleaseStore(REPO, "tbt-data-v1", remote).download(require_bundle_manifest=True)
            final, final_safety = sanitize_history_identities(load_partitions(remote))
            if final_safety.get("quarantined_rows") or len(final) != before_count:
                raise ValueError("Published canonical failed identity or count readback")
            by_id = {str(m.match_id): m for m in final}
            for mid, before in updated_before.items():
                now = by_id[mid].stats or {}
                if any(now.get(k) != v for k, v in before.items()):
                    raise ValueError("Published canonical overwrote old historical stat")
            report["status"] = "committed_persisted_readback_verified"
            report["production_mutated"] = True
            report["canonical_after"] = len(final)
            report["verified_persisted_matches"] = len(updated_before)
            del by_id, final
        except Exception as exc:
            report["publish_error"] = str(exc)[:900]
            # Restore original partitions (not user data or candidate source) to
            # the same private release if partial upload or readback fails.
            restore = [ORIGINAL / f"history-{y:04d}.parquet" for y in sorted(changed)]
            restore.append(ORIGINAL / "history_manifest.json")
            try:
                store.upload_bundle(restore)
                restored = ROOT / "rollback"
                ReleaseStore(REPO, "tbt-data-v1", restored).download(require_bundle_manifest=True)
                original_rows = load_partitions(restored)
                if len(original_rows) != before_count:
                    raise ValueError("Rollback row count disagrees with canonical baseline")
                report["status"] = "upload_failed_rollback_persisted_verified"
                report["rollback_verified"] = True
            except Exception as restore_exc:
                report["status"] = "critical_rollback_incomplete"
                report["rollback_error"] = str(restore_exc)[:900]
            raise
    except Exception as exc:
        report["error"] = str(exc)[:1300]
        if report["status"] == "running":
            report["status"] = "failed_before_publication"
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        AUDIT["save_private"](target, report)
        print(json.dumps({"status": report["status"],
                          "private_audit": target,
                          "updated_matches": report.get("unique_updated_matches", 0),
                          "production_mutated": report["production_mutated"],
                          "provider_requests": 0}))

if __name__ == "__main__":
    main()
