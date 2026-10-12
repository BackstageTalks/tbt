#!/usr/bin/env python3
"""Night-only PropLine history gap targeting and guarded 2026 CDB import.

Only truly missing aces/double faults are eligible for additive canonical writes.
No CLV code, model training, score guessing, or rate-field inference.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_snapshot
from tbt.data.offline_odds import norm_text
from import_offline_linked_serve_return import _signature
from offline_exact_cdb_write import write_exact_stats_partition, verify_persisted
from release_store import ReleaseStore
from cdb_global_writer_lock import acquire, release

REPOSITORY = "BackstageTalks/tbt-data"
RELEASE = "tbt-data-v1"
YEAR = 2026
ASSET = "history-2026.parquet"
MANIFEST = "history_manifest.json"
BUNDLE = "_tbt_bundle_manifest.json"
STAT_FIELDS = ("aces", "double_faults")
PLAYER_LOG_LIMIT = 600


def fetch_current(directory: Path):
    """Fetch ONLY the canonical 2026 partition and both signed inventory files."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in (ASSET, MANIFEST, BUNDLE):
        subprocess.run(
            ["gh", "release", "download", RELEASE, "--repo", REPOSITORY,
             "--dir", str(directory), "--pattern", name, "--clobber"],
            check=True, capture_output=True, text=True,
        )
    bundle = json.loads((directory / BUNDLE).read_text(encoding="utf-8"))
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    files = bundle.get("files") or {}
    for name in (ASSET, MANIFEST):
        meta = files.get(name)
        if not isinstance(meta, dict) or not meta.get("sha256"):
            raise RuntimeError("Missing committed canonical SHA for " + name)
        b = (directory / name).read_bytes()
        if hashlib.sha256(b).hexdigest() != meta["sha256"] or len(b) != meta["bytes"]:
            raise RuntimeError("Canonical release bundle checksum mismatch " + name)
    year = (manifest.get("years") or {}).get(str(YEAR))
    if not isinstance(year, dict) or year.get("asset", ASSET) != ASSET:
        raise RuntimeError("Canonical history manifest does not identify 2026 partition")
    if year.get("sha256") != files[ASSET]["sha256"]:
        raise RuntimeError("Canonical manifest and bundle partition digest disagree")
    return load_snapshot(directory / ASSET), files[ASSET]["sha256"]


def _valid_name(value):
    name = str(value or "").strip()
    return (
        5 <= len(name) <= 100 and len(norm_text(name).split()) >= 2
        and not any(s in name for s in ("/", " & ", " + ", ","))
        and norm_text(name) not in {"atp shanghai", "wta wuhan", "atp paris", "wta finals"}
    )


def _is_target(match, now):
    return (
        match.is_completed and str(match.tour or "").lower() in {"atp", "wta"}
        and datetime(2026, 4, 1, tzinfo=timezone.utc) <= match.scheduled_at <= now
        and _valid_name(match.player1_name) and _valid_name(match.player2_name)
        and any((match.stats or {}).get(f"{side}_{field}") is None
                for side in ("p1", "p2") for field in STAT_FIELDS)
    )


def plan_targets(matches, now, *, max_names=PLAYER_LOG_LIMIT):
    """High-yield unique full player names; prioritize actual *missing* CDB cells."""
    scores = defaultdict(float)
    labels = {}
    by_day_pair = defaultdict(set)
    for m in matches:
        if str(m.tour or "").lower() not in {"atp", "wta"} or not m.is_completed:
            continue
        key = (m.scheduled_at.date().isoformat(),
               tuple(sorted((norm_text(m.player1_name), norm_text(m.player2_name)))))
        by_day_pair[key].add(str(m.match_id))
    for m in matches:
        if not _is_target(m, now):
            continue
        key = (m.scheduled_at.date().isoformat(),
               tuple(sorted((norm_text(m.player1_name), norm_text(m.player2_name)))))
        if len(by_day_pair[key]) != 1:
            continue
        age = max(0, (now.date() - m.scheduled_at.date()).days)
        recent = 3.0 if age <= 60 else 2.0 if age <= 120 else 1.0
        for side, name in (("p1", m.player1_name), ("p2", m.player2_name)):
            missing = sum((m.stats or {}).get(f"{side}_{field}") is None for field in STAT_FIELDS)
            if not missing:
                continue
            norm = norm_text(name)
            scores[norm] += missing * recent
            labels.setdefault(norm, name)
    order = sorted(scores, key=lambda name: (-scores[name], name))[:max_names]
    return [{"player_name": labels[key], "score": round(scores[key], 2)}
            for key in order]


def _number(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not float(value).is_integer() or not 0 <= value <= 200):
        return None
    return int(value)


def _games(reports: Path):
    for path in sorted(reports.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            bundle = json.load(stream)
        if bundle.get("research_only") is not True:
            raise ValueError("Unexpected untrusted provider archive")
        for record in bundle.get("records") or []:
            if record.get("stage") == "player_game_stats_probe":
                yield path.name, record


def stage_additions(matches, reports: Path, now):
    """Exact same-day, unique full pair; never overwrite existing canonical facts."""
    counters = Counter()
    index = defaultdict(list)
    for m in matches:
        if m.is_completed and m.scheduled_at.year == YEAR and str(m.tour or "").lower() in {"atp", "wta"}:
            key = (m.scheduled_at.date().isoformat(),
                   tuple(sorted((norm_text(m.player1_name), norm_text(m.player2_name)))))
            index[key].append(m)
    proposals = defaultdict(dict)
    provider_ids = defaultdict(set)
    sources = defaultdict(set)
    rejected = set()
    for filename, record in _games(reports):
        player = norm_text(record.get("player_name"))
        payload = record.get("payload") or {}
        if not isinstance(payload.get("games"), list) or not player:
            counters["invalid_player_response"] += 1
            continue
        for game in payload["games"]:
            if not isinstance(game, dict) or game.get("status") != "final":
                continue
            stats = game.get("stats")
            if not isinstance(stats, dict) or not any(key in stats for key in ("aces", "dblfaults")):
                continue
            try:
                observed = datetime.fromisoformat(str(game.get("commence_time") or "").replace("Z", "+00:00"))
                if observed.tzinfo is None or observed.astimezone(timezone.utc) > now:
                    raise ValueError("Invalid observation")
            except ValueError:
                counters["invalid_observation_date"] += 1
                continue
            home, away = norm_text(game.get("home_team")), norm_text(game.get("away_team"))
            if not home or not away or home == away or player not in {home, away}:
                counters["invalid_source_player_identity"] += 1
                continue
            pair = tuple(sorted((home, away)))
            candidates = index.get((observed.date().isoformat(), pair), [])
            if len(candidates) != 1:
                counters["unmatched" if not candidates else "ambiguous"] += 1
                continue
            match = candidates[0]
            mid = str(match.match_id)
            gid = str(game.get("event_id") or "")
            if not gid.isdigit():
                counters["no_provider_event_id"] += 1
                continue
            provider_ids[mid].add(gid)
            if len(provider_ids[mid]) != 1:
                rejected.add(mid)
                counters["provider_event_id_conflict"] += 1
                continue
            name_to_side = {norm_text(match.player1_name): "p1",
                            norm_text(match.player2_name): "p2"}
            if len(name_to_side) != 2 or set(name_to_side) != {home, away}:
                rejected.add(mid)
                counters["source_pair_disagree"] += 1
                continue
            own, other = name_to_side[player], name_to_side[away if player == home else home]
            candidates = (
                (f"{own}_aces", _number(stats.get("aces"))),
                (f"{own}_double_faults", _number(stats.get("dblfaults"))),
                (f"{other}_aces", _number(stats.get("opp_aces"))),
            )
            for key, val in candidates:
                if val is None:
                    continue
                if key in proposals[mid] and proposals[mid][key] != val:
                    rejected.add(mid)
                    counters["source_stat_conflict"] += 1
                proposals[mid][key] = val
            sources[mid].add(filename)
            counters["detailed_provider_records_matched"] += 1

    byid = {str(m.match_id): m for m in matches}
    stage = []
    for mid, incoming in proposals.items():
        if mid in rejected or len(provider_ids[mid]) != 1:
            counters["quarantined"] += 1
            continue
        match = byid[mid]
        current = dict(match.stats or {})
        if any(current.get(k) is not None and float(current[k]) != float(v)
               for k, v in incoming.items()):
            counters["canonical_stat_conflict"] += 1
            continue
        additions = {k: v for k, v in incoming.items() if current.get(k) is None}
        if not additions:
            counters["already_present"] += 1
            continue
        stage.append({"schema": 1, "import_ready": True, "match_id": mid,
                      "canonical": _signature(match), "incoming_stats": additions,
                      "provenance": [{"source": "propline_nightly_player_games",
                                       "provider_event_id": next(iter(provider_ids[mid])),
                                       "raw_batches": sorted(sources[mid]),
                                       "evidence": ["exact_utc_day", "exact_player_pair",
                                                    "unique_canonical_match", "final_boxscore",
                                                    "nonconflicting_stat_counts"]}]})
        counters["matches_staged"] += 1
        counters["new_stat_cells_staged"] += len(additions)
    stage.sort(key=lambda v: v["match_id"])
    return stage, dict(counters)


def _write_report(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("plan", "publish"))
    p.add_argument("--history-dir", type=Path, default=Path(".cache/tbt/propline-night/history"))
    p.add_argument("--targets", type=Path, default=Path(".cache/tbt/propline-night/gap_targets.json"))
    p.add_argument("--reports", type=Path, default=Path("reports"))
    args = p.parse_args()
    if os.getenv("TBT_DATA_REPOSITORY", REPOSITORY) != REPOSITORY:
        raise SystemExit("Canonical repository must be the private BlinQ CDB")
    if not os.getenv("GH_TOKEN"):
        raise SystemExit("TBT_DATA_GH_TOKEN required")
    now = datetime.now(timezone.utc)
    if args.action == "plan":
        matches, digest = fetch_current(args.history_dir)
        targets = plan_targets(matches, now)
        _write_report(args.targets, {
            "schema": 1, "source": "canonical_cdb_2026", "partition_sha256": digest,
            "generated_at_utc": now.isoformat(), "targets": targets,
            "candidate_players": len(targets), "research_only": True,
        })
        return

    # First stage without touching any canonical release. Never acquire writer
    # lock for a zero-gain collection.
    baseline, digest = fetch_current(args.history_dir)
    preview, counts = stage_additions(baseline, args.reports, now)
    report_path = args.reports / "propline_cdb_gapfill_report.json"
    if not preview:
        _write_report(report_path, {"status": "VERIFIED_NO_NEW_MATCHED_CELLS",
                                    "initial_sha256": digest, "counts": counts,
                                    "cdb_updated": False})
        return
    state = Path(".cdb-global-writer-lock.json")
    acquire(REPOSITORY, state, wait_seconds=1200)
    try:
        # Re-acquire CURRENT canonical under the global writer lock; the
        # preliminary stage may have become stale during the night.
        recent = args.history_dir.parent / "fresh"
        before, source_sha = fetch_current(recent)
        staged, counts = stage_additions(before, args.reports, datetime.now(timezone.utc))
        if not staged:
            _write_report(report_path, {"status": "VERIFIED_NO_NEW_MATCHED_CELLS",
                                        "counts": counts, "cdb_updated": False})
            return
        work = args.history_dir.parent / "write"
        work.mkdir(parents=True, exist_ok=True)
        for name in (ASSET, MANIFEST, BUNDLE):
            shutil.copy2(recent / name, work / name)
        byid = {str(m.match_id): m for m in before}
        for row in staged:
            m = byid[row["match_id"]]
            if _signature(m) != row["canonical"]:
                raise RuntimeError("Canonical match changed during staging")
            m.stats = {**dict(m.stats or {}), **row["incoming_stats"]}
        written = write_exact_stats_partition(work, YEAR, before,
                                              {r["match_id"] for r in staged})
        expected = sum(len(row["incoming_stats"]) for row in staged)
        if written["added_values"] != expected or written["existing_values_overwritten"]:
            raise RuntimeError("Canonical additions count differs from staged input")
        ReleaseStore(REPOSITORY, RELEASE, work).upload_bundle(
            [work / ASSET, work / MANIFEST])
        remote = args.history_dir.parent / "readback"
        persisted, readback_sha = fetch_current(remote)
        verified = verify_persisted(recent, remote, staged, [YEAR])
        if (verified["status"] != "verified" or verified["added_values"] != expected
                or verified["existing_values_overwritten"] != 0
                or len(persisted) != len(before)):
            raise RuntimeError("Persisted independent readback failed")
        _write_report(report_path, {
            "status": "VERIFIED", "source_sha256": source_sha,
            "published_sha256": readback_sha, "counts": counts,
            "readback": verified, "cdb_updated": True,
        })
    finally:
        release(REPOSITORY, state, if_held=True)


if __name__ == "__main__":
    main()
