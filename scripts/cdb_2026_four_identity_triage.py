"""Read-only private 2026 four-identity source/native lineage triage.

No canonical writes, provider API, raw IDs in log/artifacts or source mutation.
This diagnostic cannot authorize a merge, rekey or restoration on its own.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timezone
import argparse
import hashlib
import json
from pathlib import Path
import unicodedata

from download_stable_cdb import download_stable
from restore_cdb_2026_lossless import (
    BACKUP, OLD_FILE, OLD_MANIFEST, OLD_SHA, OLD_MANIFEST_SHA,
    REPO, TAG, assets, download, index, release, sha, stamp,
)
from verify_cdb_2026_postrestore import PREWRITE, PREWRITE_MANIFEST_SHA

FIELDS = (
    "match_id", "tour", "scheduled_at", "tournament_id", "tournament",
    "round_name", "player1_id", "player2_id", "player1_name", "player2_name",
    "winner_id", "status", "stats_json", "provider_context_json",
)


def value(table, row, field):
    return table[field][row].as_py()


def context(table, row):
    try:
        payload = json.loads(value(table, row, "provider_context_json") or "{}")
    except (ValueError, TypeError):
        raise ValueError("Malformed pinned provider context")
    if not isinstance(payload, dict):
        raise ValueError("Provider context not an object")
    return payload


def native_evidence(table, row):
    ctx = context(table, row)
    ids = set()
    for key in ("_tbt_event_identity", "_tbt_statistics"):
        node = ctx.get(key)
        event_id = node.get("event_id") if isinstance(node, dict) else None
        if event_id not in (None, ""):
            ids.add(str(event_id))
    if len(ids) != 1:
        return (None, "missing" if not ids else "conflicting")
    identity = ctx.get("_tbt_event_identity")
    stats = ctx.get("_tbt_statistics")
    return (
        next(iter(ids)),
        {
            "home": identity.get("home") if isinstance(identity, dict) else None,
            "away": identity.get("away") if isinstance(identity, dict) else None,
            "stats_source": str(stats.get("source") or "") if isinstance(stats, dict) else "",
            "stats_status": str(stats.get("status") or "") if isinstance(stats, dict) else "",
        },
    )


def clean(s):
    s = unicodedata.normalize("NFKD", str(s or "")).casefold()
    return "".join(ch for ch in s if not unicodedata.combining(ch) and ch.isalnum())


def name_pair(table, row):
    return tuple(sorted((clean(value(table, row, "player1_name")),
                         clean(value(table, row, "player2_name")))))


def player_pair(table, row):
    return tuple(sorted((str(value(table, row, "player1_id")),
                         str(value(table, row, "player2_id")))))


def safe_describe(table, row):
    """Only public tennis event metadata, never canonical/provider/player IDs or stats."""
    at = value(table, row, "scheduled_at")
    return {
        "tour": str(value(table, row, "tour") or ""),
        "utc_day": at.astimezone(timezone.utc).date().isoformat(),
        "tournament": str(value(table, row, "tournament") or "")[:100],
        "round": str(value(table, row, "round_name") or "")[:40],
        "p1": str(value(table, row, "player1_name") or "")[:80],
        "p2": str(value(table, row, "player2_name") or "")[:80],
        "status": str(value(table, row, "status") or "")[:32],
    }


def compare_participants(a_table, a, b_table, b):
    original, current = native_evidence(a_table, a), native_evidence(b_table, b)
    at, bt = value(a_table, a, "scheduled_at"), value(b_table, b, "scheduled_at")
    ea = original[1] if isinstance(original[1], dict) else {}
    eb = current[1] if isinstance(current[1], dict) else {}
    original_stats = json.loads(value(a_table, a, "stats_json") or "{}")
    current_stats = json.loads(value(b_table, b, "stats_json") or "{}")
    if not isinstance(original_stats, dict) or not isinstance(current_stats, dict):
        raise ValueError("Malformed pinned match stats")
    overlapping = [
        k for k, v in original_stats.items()
        if v is not None and current_stats.get(k) is not None
    ]
    return {
        "same_player_ids_unordered": player_pair(a_table, a) == player_pair(b_table, b),
        "same_player_names_unordered": name_pair(a_table, a) == name_pair(b_table, b),
        "same_tournament_id": str(value(a_table, a, "tournament_id") or "")
        == str(value(b_table, b, "tournament_id") or ""),
        "same_round": clean(value(a_table, a, "round_name"))
        == clean(value(b_table, b, "round_name")),
        "utc_start_delta_minutes": int((bt - at).total_seconds() // 60),
        "same_winner_id": str(value(a_table, a, "winner_id") or "")
        == str(value(b_table, b, "winner_id") or ""),
        "both_native_home_away_present": all(
            ea.get(k) is not None and eb.get(k) is not None
            for k in ("home", "away")),
        "native_home_away_exact": all(
            ea.get(k) is not None and ea.get(k) == eb.get(k)
            for k in ("home", "away")),
        "source_stats_nonnull": sum(v is not None for v in original_stats.values()),
        "current_stats_nonnull": sum(v is not None for v in current_stats.values()),
        "stats_overlapping_fields": len(overlapping),
        "stats_overlapping_differences": sum(
            original_stats[k] != current_stats[k] for k in overlapping),
    }


def cases(original, prewrite, live):
    old = index(original, "immutable_backup")
    before = index(prewrite, "prewrite")
    current = index(live, "live")
    if (len(old), len(before)) != (98994, 2927):
        raise ValueError("Pinned original cohorts changed")
    missing = (set(old) | set(before)) - set(current)
    if len(missing) != 4 or len(set(old) - set(current)) != 3 or len(set(before) - set(current)) != 1:
        raise ValueError("Pinned four-case incident changed; do not reuse approval")
    by_native = defaultdict(list)
    by_name = defaultdict(list)
    for mid, row in current.items():
        event, metadata = native_evidence(live, row)
        if event:
            by_native[(str(value(live, row, "tour") or "").lower(), event)].append((mid, row))
        by_name[(str(value(live, row, "tour") or "").lower(), name_pair(live, row))].append(row)

    report = []
    for n, mid in enumerate(sorted(missing), start=1):
        source, where, row = (
            (prewrite, "prewrite", before[mid]) if mid in before
            else (original, "backup", old[mid])
        )
        event, marker = native_evidence(source, row)
        if not event:
            raise ValueError("Missing source-native identity evidence")
        tour = str(value(source, row, "tour") or "").lower()
        matches = [(cid, j) for cid, j in by_native.get((tour, event), []) if cid != mid]
        if len(matches) > 1:
            status = "AMBIGUOUS_NATIVE_MULTI_OWNER"
        elif matches:
            status = "NATIVE_CLAIMED_BY_OTHER_CURRENT_ID"
        else:
            status = "NATIVE_NOT_FOUND_IN_CURRENT"
        original_at = value(source, row, "scheduled_at")
        near = [
            j for j in by_name.get((tour, name_pair(source, row)), [])
            if abs((value(live, j, "scheduled_at") - original_at).total_seconds()) <= 14 * 86400
        ]
        desc = {
            "case": n, "original_cohort": where,
            "original": safe_describe(source, row),
            "native_claim_status": status,
            "native_source_statistics": marker["stats_source"] if isinstance(marker, dict) else "",
            "native_source_status": marker["stats_status"] if isinstance(marker, dict) else "",
            "same_named_players_within_14days": len(near),
            "same_named_players_same_tournament_and_round_within_14days": sum(
                clean(value(source, row, "tournament"))
                == clean(value(live, j, "tournament"))
                and clean(value(source, row, "round_name"))
                == clean(value(live, j, "round_name"))
                for j in near),
            "native_owner_count": len(matches),
            "native_owners": [
                {"current": safe_describe(live, j),
                 "identity_comparison": compare_participants(source, row, live, j)}
                for _, j in matches[:3]
            ],
        }
        report.append(desc)
    return report



def missing_cross_source_pair(original, prewrite, live):
    """Find only independently recognizable same public fixture in both backups.

    A candidate alias is evidence for review, never permission to drop either
    original historical row or to overwrite an existing canonical identity.
    """
    old = index(original, "source")
    before = index(prewrite, "prewrite")
    current = index(live, "current")
    findings = []
    for oid in sorted(set(old) - set(current)):
        oi = old[oid]
        for pid in sorted(set(before) - set(current)):
            if oid == pid:
                continue
            pi = before[pid]
            if (str(value(original, oi, "tour") or "").lower()
                    != str(value(prewrite, pi, "tour") or "").lower()
                    or name_pair(original, oi) != name_pair(prewrite, pi)
                    or clean(value(original, oi, "tournament"))
                    != clean(value(prewrite, pi, "tournament"))
                    or clean(value(original, oi, "round_name"))
                    != clean(value(prewrite, pi, "round_name"))
                    or value(original, oi, "scheduled_at").date()
                    != value(prewrite, pi, "scheduled_at").date()):
                continue
            a_stats = json.loads(value(original, oi, "stats_json") or "{}")
            b_stats = json.loads(value(prewrite, pi, "stats_json") or "{}")
            a_ev, a_marker = native_evidence(original, oi)
            b_ev, b_marker = native_evidence(prewrite, pi)
            same = sum(x is not None and x == b_stats.get(k)
                       for k, x in a_stats.items())
            diff = sum(x is not None and b_stats.get(k) is not None
                       and x != b_stats[k] for k, x in a_stats.items())
            findings.append({
                "original": safe_describe(original, oi),
                "prewrite": safe_describe(prewrite, pi),
                "native_id_equal": a_ev is not None and a_ev == b_ev,
                "both_native_ids_present": a_ev is not None and b_ev is not None,
                "identity_comparison": compare_participants(
                    original, oi, prewrite, pi),
                "original_nonnull_stats": sum(v is not None for v in a_stats.values()),
                "prewrite_nonnull_stats": sum(v is not None for v in b_stats.values()),
                "same_nonnull_stat_fields": same,
                "conflicting_nonnull_stat_fields": diff,
                "original_only_nonnull_stat_fields": sum(
                    v is not None and b_stats.get(k) is None
                    for k, v in a_stats.items()),
                "prewrite_only_nonnull_stat_fields": sum(
                    v is not None and a_stats.get(k) is None
                    for k, v in b_stats.items()),
                "original_statistics_source": a_marker.get("stats_source")
                    if isinstance(a_marker, dict) else None,
                "prewrite_statistics_source": b_marker.get("stats_source")
                    if isinstance(b_marker, dict) else None,
            })
    return findings


def main():
    import pyarrow.parquet as pq
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    import os
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("GH_TOKEN"):
        raise RuntimeError("Private read-only source required")
    a.out.mkdir(parents=True, exist_ok=False)
    frozen_assets = assets(release(BACKUP))
    if (frozen_assets[OLD_FILE]["digest"] != "sha256:" + OLD_SHA
            or frozen_assets[OLD_MANIFEST]["digest"] != "sha256:" + OLD_MANIFEST_SHA):
        raise ValueError("Pinned original source digest changed")
    frozen = download(BACKUP, OLD_FILE, a.out / "original", frozen_assets[OLD_FILE])
    old_manifest = download(BACKUP, OLD_MANIFEST, a.out / "original", frozen_assets[OLD_MANIFEST])
    if json.loads(old_manifest.read_text())["years"]["2026"]["sha256"] != OLD_SHA:
        raise ValueError("Frozen annual manifest inconsistent")
    before_assets = assets(release(PREWRITE))
    prev_bundle = download(PREWRITE, "_tbt_bundle_manifest.json",
                           a.out / "prewrite", before_assets["_tbt_bundle_manifest.json"])
    if sha(prev_bundle) != PREWRITE_MANIFEST_SHA:
        raise ValueError("Nov1 prewrite backup changed")
    prev = download(PREWRITE, "history-2026.parquet",
                    a.out / "prewrite", before_assets["history-2026.parquet"])
    covered = json.loads(prev_bundle.read_text()).get("files") or {}
    if covered.get("history-2026.parquet", {}).get("sha256") != sha(prev):
        raise ValueError("Nov1 prewrite immutable asset checksum mismatch")
    initial = release(TAG)
    snapshot = download_stable(REPO, TAG, a.out / "live")
    if snapshot.get("status") != "verified" or stamp(initial) != stamp(release(TAG)):
        raise ValueError("Live source moved during audit")
    old = pq.read_table(frozen, columns=list(FIELDS))
    before = pq.read_table(prev, columns=list(FIELDS))
    live = pq.read_table(a.out / "live" / "history-2026.parquet", columns=list(FIELDS))
    findings = cases(old, before, live)
    cross_source = missing_cross_source_pair(old, before, live)
    result = {
        "schema": 1, "state": "FOUR_SOURCE_IDENTITIES_REVIEW_ONLY",
        "current_manifest_sha256": snapshot["manifest_sha256"],
        "original_cases": len(findings),
        "cases": findings, "matching_absent_ids_in_original_and_prewrite": cross_source,
        "cdb_writes": 0, "provider_requests": 0,
        "raw_ids_exported": False, "candidate_imported": False,
    }
    # Never serialize source rows or canonical/provider IDs.
    output = a.out / "triage.json"
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print("CDB_FOUR_NATIVE_TRIAGE " + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
