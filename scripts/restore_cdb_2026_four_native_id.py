"""2026 exact original identity repair using the EXISTING ReleaseStore canonical writer.

Reconciles 4 absent historical IDs as 2 existing ATP aliases and 2 WTA
identifiers of 1 truly absent match. Imports ONE pinned original prewrite
WTA row only after strict fixture/native/stat/winner checks. Zero provider
API or model changes; read-only default, lock/CAS/backup on operator write.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

from cdb_2026_four_identity_triage import (
    cases, clean, missing_cross_source_pair, native_evidence, name_pair, value,
)
from download_stable_cdb import download_stable
from restore_cdb_2026_lossless import (
    BACKUP, OLD_FILE, OLD_MANIFEST, OLD_SHA, OLD_MANIFEST_SHA, REPO, TAG,
    _align_exact_2026_schema, _live_prefix_is_conserved, assets, command,
    download, index, release, sha, stamp, verify_cross_year,
)
from verify_cdb_2026_postrestore import PREWRITE, PREWRITE_MANIFEST_SHA

EXPECTED_START_MANIFEST = "5396eb560146a92094c92d2d14fd52917f4e7ac176c8e4eed048e9b93cdba46c"
OFFICIAL_WINNER = "hannachang"
OFFICIAL_MATCH = frozenset(("joyeechan", "hannachang"))


def winning_player(table, i):
    winner = str(value(table, i, "winner_id") or "")
    a, b = (str(value(table, i, x) or "") for x in ("player1_id", "player2_id"))
    if not winner or a == b:
        return None
    if winner == a:
        return clean(value(table, i, "player1_name"))
    if winner == b:
        return clean(value(table, i, "player2_name"))
    return None


def validate_four(original, prewrite, live):
    """Return precisely one WTA prewrite row index, or fail before any writer.

    ATP source aliases must already have the same native event, exact date,
    names/tournament/round, preserved source stats and winner name in live.
    WTA immutable original/prewrite IDs must describe ONE event with exactly
    the same 33 observed statistics, winner, tour, start and native event ID.
    """
    found = cases(original, prewrite, live)  # guards 98,994/2,927 + 4 missing
    pair = missing_cross_source_pair(original, prewrite, live)
    if len(found) != 4 or len(pair) != 1:
        raise ValueError("Expected 2 ATP aliases and one WTA two-ID pair")
    aliases = [p for p in found if p["native_claim_status"] ==
               "NATIVE_CLAIMED_BY_OTHER_CURRENT_ID"]
    absent = [p for p in found if p["native_claim_status"] ==
              "NATIVE_NOT_FOUND_IN_CURRENT"]
    if (len(aliases) != 2 or len(absent) != 2
            or any(p["original_cohort"] != "backup" for p in aliases)
            or {p["original_cohort"] for p in absent} != {"backup", "prewrite"}):
        raise ValueError("Unexpected source-native alias split")
    for a in aliases:
        if a["original"]["tour"] != "atp" or a["native_owner_count"] != 1:
            raise ValueError("Missing exact existing ATP owner")
        c = a["native_owners"][0]["identity_comparison"]
        if (a["original"]["status"] != "finished"
                or a["native_owners"][0]["current"]["status"] != "finished"
                or not c["same_player_names_unordered"]
                or not c["same_tournament_id"] or not c["same_round"]
                or c["utc_start_delta_minutes"] != 0
                or c["stats_overlapping_differences"] != 0
                or c["stats_overlapping_fields"] != c["source_stats_nonnull"]):
            raise ValueError("ATP source alias not fully independently supported")
    for a in absent:
        if (a["original"]["tour"] != "wta"
                or a["original"]["utc_day"] != "2026-10-23"
                or name_pair_from_names(a["original"]) != OFFICIAL_MATCH
                or a["native_owner_count"] != 0
                or a["native_source_statistics"] != "tennisapi1"
                or a["native_source_status"] != "available"):
            raise ValueError("WTA event is not pinned real Bakersfield quarterfinal")
    p = pair[0]
    d = p["identity_comparison"]
    if (not p["native_id_equal"] or not p["both_native_ids_present"]
            or not d["same_player_names_unordered"] or not d["same_round"]
            or not d["same_tournament_id"] or d["utc_start_delta_minutes"] != 0
            or p["original_nonnull_stats"] != 33
            or p["prewrite_nonnull_stats"] != 33
            or p["same_nonnull_stat_fields"] != 33
            or p["conflicting_nonnull_stat_fields"] != 0
            or p["original_only_nonnull_stat_fields"] != 0
            or p["prewrite_only_nonnull_stat_fields"] != 0
            or not d["same_winner_id"]
            or p["original_statistics_source"] != "tennisapi1"
            or p["prewrite_statistics_source"] != "tennisapi1"):
        raise ValueError("The two absent WTA source IDs are not exact redundant data")

    oi, pi, li = (index(t, name) for t, name in (
        (original, "frozen"), (prewrite, "prewrite"), (live, "live")))
    missed_old = sorted(set(oi) - set(li))
    missed_pre = sorted(set(pi) - set(li))
    if len(missed_old) != 3 or len(missed_pre) != 1:
        raise ValueError("Unrecognized original identity set delta")
    old_wta = [oi[mid] for mid in missed_old
               if name_pair(original, oi[mid]) == tuple(sorted(OFFICIAL_MATCH))]
    if len(old_wta) != 1:
        raise ValueError("Missing uniquely pinned frozen WTA row")
    selected = pi[missed_pre[0]]
    if (name_pair(prewrite, selected) != tuple(sorted(OFFICIAL_MATCH))
            or winning_player(original, old_wta[0]) != OFFICIAL_WINNER
            or winning_player(prewrite, selected) != OFFICIAL_WINNER):
        raise ValueError("Winner not source-attested as Hanna Chang")
    for mid in missed_old:
        oi_row = oi[mid]
        if oi_row == old_wta[0]:
            continue
        event, _ = native_evidence(original, oi_row)
        native_owners = [
            j for j in li.values()
            if str(value(original, oi_row, "tour") or "").lower()
            == str(value(live, j, "tour") or "").lower()
            and native_evidence(live, j)[0] == event
        ]
        if len(native_owners) != 1:
            raise ValueError("Missing exact current ATP source alias owner")
        j = native_owners[0]
        if winning_player(original, oi_row) != winning_player(live, j):
            raise ValueError("Original and current ATP winner diverge")
    return selected, {
        "original_missing_ids_before": 4,
        "verified_existing_atp_aliases": 2,
        "verified_duplicate_wta_old_source_id": 1,
        "wta_source_ids": 2,
        "wta_distinct_real_matches_to_restore": 1,
        "wta_verified_nonnull_stats": 33,
        "source_native_event_and_winner": "verified",
        "source_names_scores_correlated_to_official_itf": True,
        "cdb_rows_removed": 0,
        "existing_values_overwritten": 0,
        "paid_provider_requests": 0,
        "model_changes": 0,
    }


def name_pair_from_names(entry):
    return frozenset((clean(entry.get("p1")), clean(entry.get("p2"))))


def load_three(root: Path):
    """SHA-pin both immutable sources plus a stable live 78-year CDB snapshot."""
    import pyarrow.parquet as pq
    old_release = assets(release(BACKUP))
    if (old_release[OLD_FILE]["digest"] != "sha256:" + OLD_SHA
            or old_release[OLD_MANIFEST]["digest"] != "sha256:" + OLD_MANIFEST_SHA):
        raise ValueError("Original pinned source changed")
    old_file = download(BACKUP, OLD_FILE, root / "frozen", old_release[OLD_FILE])
    manifest = download(BACKUP, OLD_MANIFEST, root / "frozen", old_release[OLD_MANIFEST])
    if json.loads(manifest.read_text())["years"]["2026"]["sha256"] != OLD_SHA:
        raise ValueError("Original annual source manifest mismatch")

    pre_release = assets(release(PREWRITE))
    pre_bundle = download(PREWRITE, "_tbt_bundle_manifest.json",
                          root / "prewrite", pre_release["_tbt_bundle_manifest.json"])
    pre_file = download(PREWRITE, "history-2026.parquet",
                        root / "prewrite", pre_release["history-2026.parquet"])
    if (sha(pre_bundle) != PREWRITE_MANIFEST_SHA
            or json.loads(pre_bundle.read_text()).get("files", {}).get(
                "history-2026.parquet", {}).get("sha256") != sha(pre_file)):
        raise ValueError("Original Nov1 prewrite source changed")
    baseline = stamp(release(TAG))
    snapshot = download_stable(REPO, TAG, root / "current")
    if (snapshot.get("status") != "verified"
            or snapshot["manifest_sha256"] != EXPECTED_START_MANIFEST
            or stamp(release(TAG)) != baseline):
        raise ValueError("Live 78-year CDB changed from pinned independent triage")
    history = root / "current"
    old = pq.read_table(old_file)
    before = pq.read_table(pre_file)
    live = pq.read_table(history / "history-2026.parquet")
    return old, before, live, baseline, snapshot



def align_prewrite_exact_observed_types(pre, live):
    """Only lossless observed Nov1 -> current type widening, zero data changes.

    Int64 best_of values from the immutable backup widen exactly to float64.
    Entirely-null prewrite ranking fields may widen from null to float64.
    No other schema types, value coercions or live field changes are permitted.
    """
    import pyarrow as pa
    if pre.column_names != live.column_names:
        raise ValueError("Prewrite/live annual column identities/order differ")
    fields_a = {f.name: str(f.type) for f in pre.schema}
    fields_b = {f.name: str(f.type) for f in live.schema}
    delta = {k: (fields_a[k], fields_b[k]) for k in fields_a
             if fields_a[k] != fields_b[k]}
    allowed = {
        "best_of": ("int64", "double"),
        "player1_rank": ("null", "double"),
        "player2_rank": ("null", "double"),
    }
    if any(allowed.get(k) != v for k, v in delta.items()):
        raise ValueError("Unapproved prewrite/live schema type difference")
    if any(pre.schema.field(k).nullable != live.schema.field(k).nullable
           for k in fields_a):
        raise ValueError("Source/live nullability changed")
    original = pre
    if "best_of" in delta:
        for n in pre["best_of"].to_pylist():
            if n is not None and (type(n) is not int or n not in (2, 3, 5)):
                raise ValueError("Nonstandard source best_of; exact widen blocked")
        pre = pre.set_column(pre.schema.get_field_index("best_of"),
                             live.schema.field("best_of"),
                             pre["best_of"].cast(pa.float64(), safe=True))
    for name in ("player1_rank", "player2_rank"):
        if name in delta:
            if pre[name].null_count != pre.num_rows:
                raise ValueError("Unrecognized prewrite rank evidence")
            pre = pre.set_column(
                pre.schema.get_field_index(name), live.schema.field(name),
                pa.nulls(pre.num_rows, type=pa.float64()))
    if not pre.schema.equals(live.schema, check_metadata=False):
        raise ValueError("Lossless source/live schema conversion incomplete")
    for name in original.column_names:
        if name not in delta and not original[name].equals(pre[name]):
            raise ValueError("Unexpected prewrite field changed during alignment")
    return pre, live


def build_candidate(original, prewrite, live):
    import pyarrow as pa
    selected, proof = validate_four(original, prewrite, live)
    aligned_pre, aligned_live = align_prewrite_exact_observed_types(prewrite, live)
    if not aligned_pre.schema.equals(aligned_live.schema, check_metadata=False):
        a = {field.name: str(field.type) for field in aligned_pre.schema}
        b = {field.name: str(field.type) for field in aligned_live.schema}
        delta = {
            "prewrite_only": sorted(set(a) - set(b)),
            "live_only": sorted(set(b) - set(a)),
            "type_diffs": {k: [a[k], b[k]] for k in sorted(set(a) & set(b))
                           if a[k] != b[k]},
            "field_order_differs": list(a) != list(b),
            "nullability_diffs": sorted(
                k for k in set(a) & set(b)
                if aligned_pre.schema.field(k).nullable != aligned_live.schema.field(k).nullable),
        }
        raise ValueError("Source/canonical 2026 schemas not strictly compatible: "
                         + json.dumps(delta, sort_keys=True))
    old_ids, live_ids = index(aligned_pre, "prewrite"), index(aligned_live, "live")
    missing = set(old_ids) - set(live_ids)
    if len(missing) != 1 or old_ids[next(iter(missing))] != selected:
        raise ValueError("Expected exactly one absent prewrite row")
    row = aligned_pre.take(pa.array([selected], type=pa.int64()))
    candidate = pa.concat_tables([aligned_live, row], promote_options="none")
    if candidate.num_rows != live.num_rows + 1:
        raise ValueError("Candidate cardinality wrong")
    if not _live_prefix_is_conserved(live, candidate):
        raise ValueError("Live prefix changed by source reconciliation")
    proof.update(
        input_live_2026_rows=live.num_rows,
        staged_2026_rows=candidate.num_rows,
        verified_net_new_real_matches=1,
        source_prewrite_row_preserved_exact=True,
    )
    return candidate, proof


def backup_current(root: Path, history: Path):
    """Existing restore policy: persistent immutable prewrite, then readback."""
    tag = (f'blinq-cdb2026-one-match-prewrite-'
           f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}')
    directory = root / "backup"
    directory.mkdir()
    names = ("history-2026.parquet", "history_manifest.json", "_tbt_bundle_manifest.json")
    for name in names:
        shutil.copy2(history / name, directory / name)
    with (directory / "SHA256SUMS").open("w") as output:
        for name in names:
            output.write(sha(directory / name) + "  " + name + "\n")
    command("release", "create", tag, *sorted(directory.glob("*")), "-R", REPO,
            "--title", "CDB 2026 one-real-match prewrite rollback",
            "--notes", "Immutable verified rollback prior to 2026 WTA single-fixture restoration")
    readback = root / "backup-readback"
    readback.mkdir()
    command("release", "download", tag, "-R", REPO, "-D", readback)
    for name in names:
        if sha(readback / name) != sha(directory / name):
            raise ValueError("Pinned one-match rollback copy readback failed")
    return tag


def main():
    import pyarrow.parquet as pq
    from cdb_global_writer_lock import verify
    from release_store import ReleaseStore
    from tbt.data.history_snapshot import update_year_manifest
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "write"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true" or not os.getenv("GH_TOKEN"):
        raise ValueError("Private GitHub Actions canonical context required")
    if args.mode == "write":
        verify(REPO, Path(".cdb-global-writer-lock.json"))
    args.out.mkdir(parents=True, exist_ok=False)
    original, prewrite, live, baseline, snapshot = load_three(args.out)
    candidate, proof = build_candidate(original, prewrite, live)
    history = args.out / "current"
    proposed_ids = set(index(candidate, "proposal"))
    proof["other_year_unique_ids"] = verify_cross_year(history, proposed_ids)
    local = args.out / "candidate-2026.parquet"
    pq.write_table(candidate, local, compression="snappy")
    if not pq.read_table(local).equals(candidate, check_metadata=False):
        raise ValueError("Full local Parquet candidate readback changed")
    proof.update(
        state="STAGED_NOT_PUBLISHED", mode=args.mode,
        baseline_manifest_sha256=snapshot["manifest_sha256"],
        cdb_writes=0, aliases_recorded_in_immutable_sources=True,
    )
    if args.mode == "write":
        backup_tag = backup_current(args.out, history)
        if stamp(release(TAG)) != baseline:
            raise RuntimeError("Canonical CAS moved after verified immutable rollback")
        shutil.copyfile(local, history / "history-2026.parquet")
        update_year_manifest(history, 2026, {
            "sha256": sha(history / "history-2026.parquet"),
            "bytes": (history / "history-2026.parquet").stat().st_size,
            "rows": candidate.num_rows,
        }, extra={
            "recovery": "single_native_wta_2026_distinct_fixture",
            "recovery_source_prewrite_tag": PREWRITE,
            "recovery_source_frozen_tag": BACKUP,
            "recovery_prewrite_rollback_tag": backup_tag,
        })
        verify(REPO, Path(".cdb-global-writer-lock.json"))
        if stamp(release(TAG)) != baseline:
            raise RuntimeError("Canonical CAS changed during guarded publication")
        store = ReleaseStore(REPO, TAG, history)
        store.upload_bundle([history / "history-2026.parquet",
                             history / "history_manifest.json"])
        remote = download_stable(REPO, TAG, args.out / "persisted")
        persisted = pq.read_table(args.out / "persisted" / "history-2026.parquet")
        if (not persisted.equals(candidate, check_metadata=False)
                or not _live_prefix_is_conserved(live, persisted)):
            raise ValueError("Remote persisted 2026 row identity/stat readback failed")
        for year in range(1949, 2026):
            name = f"history-{year}.parquet"
            if sha(history / name) != sha(args.out / "persisted" / name):
                raise ValueError(f"Unrelated annual data changed during repair: {year}")
        pi = index(prewrite, "source-prewrite")
        current = index(persisted, "remote-canonical")
        if len(set(pi) - set(current)) or persisted.num_rows != live.num_rows + 1:
            raise ValueError("One original prewrite identity not actually conserved")
        proof.update(
            cdb_writes=1, state="REMOTE_PERSISTED_READBACK_VERIFIED",
            prewrite_backup_tag=backup_tag,
            persisted_manifest_sha256=remote["manifest_sha256"],
            published_2026_rows=persisted.num_rows,
            original_prewrite_ids_missing_after=0,
            immutable_original_legacy_aliases_intentionally_not_duplicated=3,
        )
    (args.out / "report.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
    print("CDB_2026_ONE_MATCH_NATIVE_REPAIR " + json.dumps(proof, sort_keys=True),
          flush=True)


if __name__ == "__main__":
    main()
