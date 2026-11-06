"""Private read-only forensics for 2026 ID drift after 1 Nov restoration.

Only aggregate evidence is retained; raw match IDs and cells never leave
the ephemeral CI runner. Reuses existing ReleaseStore-backed stable download
and SHA-pinned backup/identity checks. No canonical writer or paid provider.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from download_stable_cdb import download_stable
from restore_cdb_2026_lossless import (
    BACKUP, OLD_FILE, OLD_MANIFEST, OLD_SHA, OLD_MANIFEST_SHA,
    REPO, TAG, assets, download, index, merge_preserving_live,
    release, sha, stamp, verify_cross_year,
)
from verify_cdb_2026_postrestore import (
    PREWRITE, PREWRITE_MANIFEST_SHA, verify_current_years,
)


def compare_origins(old, before, live, *, expected=(98994, 2927, 1258, 97736, 1669)):
    older = index(old, "pinned_backup")
    prewrite = index(before, "prewrite")
    current = index(live, "current")
    shared = set(older) & set(prewrite)
    old_only = set(older) - set(prewrite)
    prewrite_only = set(prewrite) - set(older)
    if (len(older), len(prewrite), len(shared),
            len(old_only), len(prewrite_only)) != tuple(expected):
        raise ValueError("Original two authoritative 1 Nov CDB cohorts changed")
    prewrite_missing = set(prewrite) - set(current)
    backup_missing = set(older) - set(current)
    prewrite_identity_conflicts = 0
    for mid in set(prewrite) & set(current):
        i, j = prewrite[mid], current[mid]
        if any(before[key][i].as_py() != live[key][j].as_py()
               for key in ("player1_id", "player2_id", "scheduled_at")):
            prewrite_identity_conflicts += 1
    return {
        "backup_ids_missing_now": len(backup_missing),
        "prewrite_ids_missing_now": len(prewrite_missing),
        "original_backup_only_id_count": len(old_only),
        "original_prewrite_only_id_count": len(prewrite_only),
        "original_overlap": len(shared),
        "prewrite_identity_conflicts_now": prewrite_identity_conflicts,
        "prewrite_only_ids_preserved_now": len(prewrite_only - prewrite_missing),
        "baseline_2026_original_row_count": len(older),
        "baseline_2026_prewrite_row_count": len(prewrite),
        "current_2026_rows": len(current),
    }



def classify_identity_drift(old, before, live) -> dict:
    """Aggregate-only, conservative evidence for potential canonical rekeys.

    Classify candidates by identical tour, exact UTC scheduled_at, unordered
    player ID pair and tournament ID (when original has one). A match is only
    a *candidate*, not permission to migrate or suppress any original row.
    """
    from collections import Counter, defaultdict

    original = index(old, "source")
    previous = index(before, "prewrite")
    current = index(live, "current")
    required = {"tour", "tournament_id", "match_id",
                "player1_id", "player2_id", "scheduled_at"}
    if not required.issubset(old.column_names) or not required.issubset(live.column_names):
        raise ValueError("Missing canonical identity evidence for rekey forensics")

    def key(table, i):
        p1, p2 = (str(table[n][i].as_py() or "") for n in ("player1_id", "player2_id"))
        return (
            str(table["tour"][i].as_py() or "").lower(),
            table["scheduled_at"][i].as_py(),
            tuple(sorted((p1, p2))),
            str(table["tournament_id"][i].as_py() or ""),
        )

    # Some source releases have a missing tournament ID while the provider
    # later supplies it. A missing source tournament cannot establish a
    # unique provider identity on its own; report as unresolved, not rekeyed.
    aliases = defaultdict(list)
    near_candidates = defaultdict(list)
    for mid, j in current.items():
        k = key(live, j)
        aliases[k].append(mid)
        near_candidates[(k[0], k[2], k[3])].append((mid, k[1]))

    counts = Counter()
    missing = (set(original) | set(previous)) - set(current)
    for mid in missing:
        source, src_index = (before, previous) if mid in previous else (old, original)
        candidate_key = key(source, src_index[mid])
        if not candidate_key[3]:
            counts["missing_without_source_tournament_id"] += 1
            continue
        targets = [ref for ref in aliases.get(candidate_key, []) if ref != mid]
        if len(targets) == 1:
            counts["missing_with_one_strong_rekey_candidate"] += 1
        elif len(targets) > 1:
            counts["missing_with_ambiguous_rekey_candidates"] += 1
        else:
            counts["missing_without_strong_rekey_candidate"] += 1
            # A corrected kickoff time changes the exact identity key. Keep
            # near-date candidates distinct from verified rekeys: only original
            # source-native ID/provenance and an approved repair can decide.
            dates = near_candidates.get(
                (candidate_key[0], candidate_key[2], candidate_key[3]), [])
            plausible = [
                target for target, when in dates
                if target != mid and when is not None and candidate_key[1] is not None
                and abs((when - candidate_key[1]).total_seconds()) <= 7 * 86400
            ]
            if len(plausible) == 1:
                counts["missing_with_one_7day_time_shift_candidate"] += 1
            elif len(plausible) > 1:
                counts["missing_with_ambiguous_7day_time_shift_candidates"] += 1
            else:
                counts["missing_without_7day_time_shift_candidate"] += 1

    for mid in set(previous) & set(current):
        a, b = previous[mid], current[mid]
        before_pair = (before["player1_id"][a].as_py(),
                       before["player2_id"][a].as_py())
        after_pair = (live["player1_id"][b].as_py(),
                      live["player2_id"][b].as_py())
        changed_pair = before_pair != after_pair
        swapped = (changed_pair and before_pair == after_pair[::-1])
        changed_time = before["scheduled_at"][a].as_py() != live["scheduled_at"][b].as_py()
        if changed_pair or changed_time:
            if changed_time:
                original_at = before["scheduled_at"][a].as_py()
                current_at = live["scheduled_at"][b].as_py()
                if abs((current_at - original_at).total_seconds()) <= 24 * 3600:
                    counts["existing_id_time_shift_under_24h"] += 1
                elif abs((current_at - original_at).total_seconds()) <= 7 * 86400:
                    counts["existing_id_time_shift_1_to_7days"] += 1
                else:
                    counts["existing_id_time_shift_over_7days"] += 1
            counts["existing_id_changed_player_pair"] += int(changed_pair and not swapped)
            counts["existing_id_swapped_orientation"] += int(swapped)
            counts["existing_id_changed_scheduled_at"] += int(changed_time)
            counts["existing_id_player_or_time_conflict"] += 1
    counts["unique_missing_source_ids"] = len(missing)
    # These sums never contain private match identifiers, raw values or hashes.
    return {key: int(counts[key]) for key in (
        "unique_missing_source_ids",
        "missing_with_one_strong_rekey_candidate",
        "missing_with_ambiguous_rekey_candidates",
        "missing_without_strong_rekey_candidate",
        "missing_with_one_7day_time_shift_candidate",
        "missing_with_ambiguous_7day_time_shift_candidates",
        "missing_without_7day_time_shift_candidate",
        "missing_without_source_tournament_id",
        "existing_id_time_shift_under_24h",
        "existing_id_time_shift_1_to_7days",
        "existing_id_time_shift_over_7days",
        "existing_id_player_or_time_conflict",
        "existing_id_changed_player_pair",
        "existing_id_swapped_orientation",
        "existing_id_changed_scheduled_at",
    )}



def classify_missing_native_event_claims(old, before, current) -> dict:
    """Check immutable native provider event IDs without guessing identity.

    Only positive source-native claims from minimized provider context are
    considered. Provider IDs may collide in ITF; same ID is a warning, never
    sufficient evidence to merge, rekey, delete or publish a match.
    """
    from collections import Counter, defaultdict

    cols = {"match_id", "tour", "provider_context_json"}
    if any(not cols.issubset(set(table.column_names)) for table in (old, before, current)):
        raise ValueError("Missing original provider provenance in canonical audit snapshot")

    def evidence(table, i):
        raw = table["provider_context_json"][i].as_py()
        try:
            context = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return None, "malformed"
        if not isinstance(context, dict):
            return None, "malformed"
        found = set()
        for key in ("_tbt_event_identity", "_tbt_statistics"):
            node = context.get(key)
            value = node.get("event_id") if isinstance(node, dict) else None
            if value not in (None, ""):
                found.add(str(value))
        if len(found) > 1:
            return None, "conflict"
        if not found:
            return None, "absent"
        return next(iter(found)), "verified"

    old_idx = index(old, "original")
    pre_idx = index(before, "prewrite")
    cur_idx = index(current, "current")
    used = defaultdict(set)
    for mid, i in cur_idx.items():
        claim, state = evidence(current, i)
        if state == "verified":
            used[(str(current["tour"][i].as_py()).lower(), claim)].add(mid)
    counts = Counter()
    for mid in (set(old_idx) | set(pre_idx)) - set(cur_idx):
        source, original_idx = (before, pre_idx) if mid in pre_idx else (old, old_idx)
        i = original_idx[mid]
        claim, state = evidence(source, i)
        if state != "verified":
            counts["missing_source_native_provider_" + state] += 1
            continue
        counts["missing_source_native_provider_verified"] += 1
        owners = used.get((str(source["tour"][i].as_py()).lower(), claim), set()) - {mid}
        if len(owners) == 0:
            counts["missing_native_provider_id_not_in_current"] += 1
        elif len(owners) == 1:
            counts["missing_native_provider_id_claimed_by_one_other_id"] += 1
        else:
            counts["missing_native_provider_id_ambiguous_multiple_owners"] += 1
    return {key: int(counts[key]) for key in (
        "missing_source_native_provider_verified",
        "missing_source_native_provider_absent",
        "missing_source_native_provider_malformed",
        "missing_source_native_provider_conflict",
        "missing_native_provider_id_not_in_current",
        "missing_native_provider_id_claimed_by_one_other_id",
        "missing_native_provider_id_ambiguous_multiple_owners",
    )}



def _store_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("CDB_2026_DRIFT_FORENSICS " + json.dumps(report, sort_keys=True), flush=True)


def main() -> None:
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true" or not os.getenv("GH_TOKEN"):
        raise RuntimeError("Private GitHub Actions read-only credentials required")
    root = args.out
    root.mkdir(parents=True, exist_ok=False)

    original_release = assets(release(BACKUP))
    if (original_release[OLD_FILE]["digest"] != "sha256:" + OLD_SHA or
            original_release[OLD_MANIFEST]["digest"] != "sha256:" + OLD_MANIFEST_SHA):
        raise RuntimeError("Original Oct 27 backup changed")
    frozen = download(BACKUP, OLD_FILE, root / "frozen", original_release[OLD_FILE])
    frozen_manifest = download(
        BACKUP, OLD_MANIFEST, root / "frozen", original_release[OLD_MANIFEST])
    if json.loads(frozen_manifest.read_text())["years"]["2026"]["sha256"] != OLD_SHA:
        raise RuntimeError("Original backup manifest inconsistent")

    beginning = release(TAG)
    snapshot = download_stable(REPO, TAG, root / "current")
    if snapshot["status"] != "verified" or stamp(beginning) != stamp(release(TAG)):
        raise RuntimeError("Current canonical release moved during stable download")

    older_assets = assets(release(PREWRITE))
    prewrite_manifest_path = download(
        PREWRITE, "history_manifest.json", root / "prewrite",
        older_assets["history_manifest.json"])
    prewrite_file = download(
        PREWRITE, "history-2026.parquet", root / "prewrite",
        older_assets["history-2026.parquet"])
    # The 1 Nov restore report pinned the SHA of the BUNDLE manifest
    # (download_stable.manifest_sha256), not the yearly history_manifest.json.
    # Pin the correct immutable bundle and verify each enclosed asset digest.
    prewrite_bundle = download(
        PREWRITE, "_tbt_bundle_manifest.json", root / "prewrite",
        older_assets["_tbt_bundle_manifest.json"])
    if sha(prewrite_bundle) != PREWRITE_MANIFEST_SHA:
        raise RuntimeError("Pinned 1 Nov prewrite bundle manifest changed")
    covered = json.loads(prewrite_bundle.read_text()).get("files") or {}
    for name in ("history_manifest.json", "history-2026.parquet"):
        path = root / "prewrite" / name
        if not isinstance(covered.get(name), dict) or covered[name].get("sha256") != sha(path):
            raise RuntimeError("Pinned prewrite bundle source checksum mismatch")
    previous = json.loads(prewrite_manifest_path.read_text())
    if previous["years"]["2026"]["sha256"] != sha(prewrite_file):
        raise RuntimeError("Pinned 1 Nov prewrite year manifest/Parquet mismatch")

    current = root / "current"
    cols = ["match_id", "tour", "tournament_id", "player1_id", "player2_id", "scheduled_at", "stats_json", "provider_context_json"]
    old_table = pq.read_table(frozen, columns=cols)
    prewrite_table = pq.read_table(prewrite_file, columns=cols)
    current_table = pq.read_table(current / "history-2026.parquet", columns=cols)
    merged, counts, union = merge_preserving_live(old_table, current_table)
    origins = compare_origins(old_table, prewrite_table, current_table)
    classifications = classify_identity_drift(old_table, prewrite_table, current_table)
    provider_claims = classify_missing_native_event_claims(old_table, prewrite_table, current_table)
    report = {
        "schema": 1, "phase": "read_only_current_snapshot_forensics",
        "state": "UNVERIFIED_UNTIL_COMPLETE",
        "original_persisted_restore_run": 41310504634,
        "source_prewrite_tag": PREWRITE,
        "current_manifest_sha256": snapshot["manifest_sha256"],
        "model_changes": 0, "provider_requests": 0, "cdb_writes": 0,
        "recovery_candidate_not_imported": True,
        "merged_candidate_rows_only_in_memory": merged.num_rows,
        **counts, **origins, **classifications, **provider_claims,
    }
    output = root / "drift-report.json"
    _store_report(output, report)
    # The old/current identity union is checked for collisions even when the
    # original release is incomplete. Nothing is uploaded or published.
    report["other_year_unique_ids"] = verify_cross_year(current, union)
    report.update(verify_current_years(current, previous))
    # Remote CAS-style independent inventory observation after full scan.
    latest = release(TAG)
    if stamp(beginning) != stamp(latest):
        raise RuntimeError("Canonical CDB changed during identity forensics")
    restored_missing = counts["old_only_restored"]
    if restored_missing != origins["backup_ids_missing_now"]:
        raise RuntimeError("Independent identity gap computations disagree")
    report["state"] = (
        "CURRENT_IDENTITY_UNION_VERIFIED"
        if not restored_missing and not origins["prewrite_ids_missing_now"]
        and not origins["prewrite_identity_conflicts_now"]
        else "CURRENT_IDENTITY_REVIEW_REQUIRED"
    )
    _store_report(output, report)
    if report["state"] != "CURRENT_IDENTITY_UNION_VERIFIED":
        raise RuntimeError("Current canonical identity drift detected; review only, no write")


if __name__ == "__main__":
    main()
