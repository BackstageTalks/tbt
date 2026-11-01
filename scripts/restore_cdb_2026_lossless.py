"""Restore old-only 2026 matches; preserve current 2026 rows exactly.
Only existing ReleaseStore, global CDB lock, CAS, SHA-verified immutable backup.
No provider API, rekeying, model change or overwrite of live fields.
"""
from __future__ import annotations
import argparse
from datetime import timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
BACKUP = "blinq-full-training-backup-40554915730-1"
OLD_FILE = "frozen__history__history-2026.parquet"
OLD_MANIFEST = "frozen__history__history_manifest.json"
OLD_SHA = "b1d91433808b3c5c6bc0fec36098a92c68a17f7b25da582e462d67f9a8d97d7c"
OLD_MANIFEST_SHA = "669d25b8d42204686453303bf5262d14210142bb1807db608dc0b90ed2ec3cb4"


def command(*args):
    p = subprocess.run(["gh", *map(str, args)], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError("Private GitHub operation failed: " + p.stderr[:300])
    return p.stdout


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def release(tag):
    return json.loads(command("api", f"repos/{REPO}/releases/tags/{tag}"))


def assets(raw):
    items = [a for a in raw["assets"] if a.get("state") == "uploaded"]
    result = {a["name"]: a for a in items}
    if len(result) != len(items):
        raise ValueError("Duplicate release asset names")
    return result


def download(tag, name, directory, meta):
    directory.mkdir(parents=True, exist_ok=True)
    command("release", "download", tag, "-R", REPO, "-p", name, "-D", directory)
    p = directory / name
    if (not p.is_file() or sha(p) != meta["digest"].removeprefix("sha256:")
            or p.stat().st_size != meta["size"]):
        raise ValueError("Bad immutable asset SHA/size: " + name)
    return p


def stamp(raw):
    inventory = assets(raw)
    return tuple(
        (name, inventory[name]["id"], inventory[name]["digest"], inventory[name]["size"])
        for name in ("_tbt_bundle_manifest.json", "history_manifest.json", "history-2026.parquet")
    )


def index(table, source):
    found = {}
    names = ("match_id", "player1_id", "player2_id", "scheduled_at")
    if not set(names).issubset(table.column_names):
        raise ValueError("Missing canonical identity columns")
    for i, (mid, p1, p2, when) in enumerate(zip(
            *(table.column(k).to_pylist() for k in names))):
        if (not mid or not p1 or not p2 or p1 == p2 or mid in found
                or when is None or when.astimezone(timezone.utc).year != 2026):
            raise ValueError(f"Invalid or duplicate 2026 canonical identity: {source}")
        found[str(mid)] = i
    return found


def _align_exact_2026_schema(old, live):
    """Only reconcile observed type drift with exact, non-lossy guards.

    2026 backup stored best_of as float64; present CDB uses int64.
    The current rank columns are entirely null-typed; preserve historical
    float64 rank values by widening those empty current columns to float64.
    Other schema changes always fail closed.
    """
    import math
    import pyarrow as pa
    a = {f.name: str(f.type) for f in old.schema}
    b = {f.name: str(f.type) for f in live.schema}
    if old.column_names != live.column_names:
        return old, live
    changes = {name: (a[name], b[name]) for name in a if a[name] != b[name]}
    allowed = {
        "best_of": ("double", "int64"),
        "player1_rank": ("double", "null"),
        "player2_rank": ("double", "null"),
    }
    if any(allowed.get(name) != delta for name, delta in changes.items()):
        return old, live
    if any(old.schema.field(name).nullable != live.schema.field(name).nullable
           for name in a):
        return old, live
    if "best_of" in changes:
        # Prevent silent float truncation, NaN/inf, or out-of-domain values.
        for value in old.column("best_of").to_pylist():
            if value is not None and (not math.isfinite(value)
                    or not value.is_integer() or not 1 <= value <= 5):
                raise ValueError("Unsafe backup best_of; refusing type conversion")
        old = old.set_column(old.schema.get_field_index("best_of"),
                             live.schema.field("best_of"),
                             old.column("best_of").cast(pa.int64(), safe=True))
    for name in ("player1_rank", "player2_rank"):
        if name in changes:
            # Null current columns contain no ranked values to overwrite.
            if live.column(name).null_count != live.num_rows:
                raise ValueError("Current rank field is not entirely null")
            for value in old.column(name).to_pylist():
                if value is not None and not math.isfinite(value):
                    raise ValueError("Unsafe backup rank; refusing conversion")
            live = live.set_column(live.schema.get_field_index(name),
                                   old.schema.field(name),
                                   pa.nulls(live.num_rows, type=pa.float64()))
    return old, live


def _live_prefix_is_conserved(before, candidate):
    """Verify each old live field is unchanged, including zero vs NULL.

    A null-typed current rank column may become typed float64, but all its
    existing cells must remain NULL. No other live-column conversion allowed.
    """
    import pyarrow as pa
    if (before.column_names != candidate.column_names
            or before.num_rows > candidate.num_rows):
        return False
    for name in before.column_names:
        a, b = before.column(name), candidate.column(name).slice(0, before.num_rows)
        if (name in ("player1_rank", "player2_rank")
                and pa.types.is_null(a.type) and pa.types.is_float64(b.type)):
            if a.null_count != before.num_rows or b.null_count != before.num_rows:
                return False
        elif not a.equals(b):
            return False
    return True


def merge_preserving_live(old, live):
    import pyarrow as pa
    original_live = live
    old, live = _align_exact_2026_schema(old, live)
    if not old.schema.equals(live.schema, check_metadata=False):
        # Diagnostics are column names/types only: no canonical identities,
        # player information, row contents or private raw values in CI logs.
        def fields(table):
            return {field.name: str(field.type) for field in table.schema}
        a, b = fields(old), fields(live)
        schema_delta = {
            "backup_only": {k: a[k] for k in sorted(a.keys() - b.keys())},
            "current_only": {k: b[k] for k in sorted(b.keys() - a.keys())},
            "type_differences": {
                k: {"backup": a[k], "current": b[k]}
                for k in sorted(a.keys() & b.keys()) if a[k] != b[k]
            },
            "field_order_differs": list(a) != list(b),
            "nullability_differs": [
                k for k in sorted(a.keys() & b.keys())
                if old.schema.field(k).nullable != live.schema.field(k).nullable
            ],
        }
        raise ValueError("Old/current schema differs; refuse coercion. "
                         + "Column-only delta: " + json.dumps(schema_delta, sort_keys=True))
    oi, ci = index(old, "backup"), index(live, "current")
    missing = set(oi) - set(ci)
    conflicts = null_old = current_new = 0
    for mid in set(oi) & set(ci):
        i, j = oi[mid], ci[mid]
        if any(old[k][i].as_py() != live[k][j].as_py()
               for k in ("player1_id", "player2_id", "scheduled_at")):
            raise ValueError("Old/current overlapping match identity conflict")
        old_stats = json.loads(old["stats_json"][i].as_py() or "{}")
        new_stats = json.loads(live["stats_json"][j].as_py() or "{}")
        if not isinstance(old_stats, dict) or not isinstance(new_stats, dict):
            raise ValueError("Malformed observed stats")
        for k, v in old_stats.items():
            if v is not None:
                if new_stats.get(k) is None:
                    null_old += 1
                elif new_stats[k] != v:
                    conflicts += 1
        current_new += sum(v is not None and old_stats.get(k) is None
                           for k, v in new_stats.items())
    additions = old.take(pa.array(
        [i for i in range(old.num_rows) if old["match_id"][i].as_py() in missing],
        type=pa.int64(),
    ))
    merged = pa.concat_tables([live, additions], promote_options="none")
    if merged.num_rows != len(set(oi) | set(ci)) or not _live_prefix_is_conserved(
            original_live, merged):
        raise ValueError("Merged canonical content not conserved")
    return merged, {
        "backup_2026": len(oi), "live_2026": len(ci),
        "old_only_restored": len(missing),
        "live_only_preserved": len(set(ci) - set(oi)),
        "overlap": len(set(oi) & set(ci)),
        "null_on_live_overlap_not_modified": null_old,
        "conflicts_quarantined_live_precedence": conflicts,
        "new_live_overlap_values_preserved": current_new,
        "merged_2026": merged.num_rows,
        "net_new_canonical_matches": len(missing),
        "enriched_existing_matches": 0,
        "existing_cells_overwritten": 0,
        "schema_alignment": "strict_best_of_int_and_null_rank_widening_only",
    }, set(oi) | set(ci)


def verify_cross_year(history, future_ids):
    import pyarrow.parquet as pq
    all_ids = set()
    paths = sorted(history.glob("history-*.parquet"))
    if len(paths) != 78:
        raise ValueError("Canonical annual inventory is incomplete")
    for path in paths:
        if path.name == "history-2026.parquet":
            continue
        for batch in pq.ParquetFile(path).iter_batches(
                batch_size=16000, columns=["match_id"]):
            for mid in batch.column(0).to_pylist():
                if not mid or mid in all_ids or mid in future_ids:
                    raise ValueError("Cross-year match ID conflict")
                all_ids.add(mid)
    return len(all_ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "write"), required=True)
    parser.add_argument("--expected-old-only", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true" or not os.getenv("GH_TOKEN"):
        raise RuntimeError("GitHub Actions private canonical context required")
    from cdb_global_writer_lock import verify
    from download_stable_cdb import download_stable
    from release_store import ReleaseStore
    from tbt.data.history_snapshot import update_year_manifest
    import pyarrow.parquet as pq

    if args.mode == "write":
        verify(REPO, Path(".cdb-global-writer-lock.json"))
    root = args.out
    root.mkdir(parents=True, exist_ok=False)
    frozen_assets = assets(release(BACKUP))
    if (frozen_assets[OLD_FILE]["digest"] != "sha256:" + OLD_SHA or
            frozen_assets[OLD_MANIFEST]["digest"] != "sha256:" + OLD_MANIFEST_SHA):
        raise RuntimeError("Pinned immutable source no longer matches")
    old_parquet = download(BACKUP, OLD_FILE, root / "frozen", frozen_assets[OLD_FILE])
    old_manifest = download(BACKUP, OLD_MANIFEST, root / "frozen", frozen_assets[OLD_MANIFEST])
    if json.loads(old_manifest.read_text())["years"]["2026"]["sha256"] != OLD_SHA:
        raise RuntimeError("Frozen year manifest is inconsistent")

    pre_stamp = stamp(release(TAG))
    snapshot = download_stable(REPO, TAG, root / "current")
    if snapshot.get("status") != "verified" or stamp(release(TAG)) != pre_stamp:
        raise RuntimeError("Live canonical source moved during download")
    history = root / "current"
    original_live = pq.read_table(history / "history-2026.parquet")
    merged, counts, ids = merge_preserving_live(pq.read_table(old_parquet), original_live)
    counts["other_year_unique_ids"] = verify_cross_year(history, ids)
    counts.update(schema=1, phase=args.mode, provider_requests=0,
                  model_changes=0, cdb_writes=0, state="STAGED_NOT_PUBLISHED",
                  source_manifest_sha256=snapshot["manifest_sha256"],
                  old_2026_sha256=OLD_SHA)
    if counts["old_only_restored"] != args.expected_old_only:
        raise RuntimeError("Live/backup identity count drift since approval")
    proposed = root / "proposed-2026.parquet"
    pq.write_table(merged, proposed, compression="snappy")
    if not pq.read_table(proposed).equals(merged, check_metadata=False):
        raise RuntimeError("Local full-Parquet candidate readback failed")

    if args.mode == "write":
        tag = f'blinq-cdb2026-lossless-prewrite-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
        backups = root / "backups"
        backups.mkdir()
        names = ("history-2026.parquet", "history_manifest.json", "_tbt_bundle_manifest.json")
        for name in names:
            shutil.copyfile(history / name, backups / name)
        with (backups / "SHA256SUMS").open("w") as output:
            for name in names:
                output.write(sha(backups / name) + "  " + name + "\n")
        command("release", "create", tag, *sorted(backups.glob("*")), "-R", REPO,
                "--title", "Immutable CDB 2026 prewrite backup",
                "--notes", "Live baseline before lossless 2026 backup-only row recovery")
        copied = root / "backup-readback"
        copied.mkdir()
        command("release", "download", tag, "-R", REPO, "-D", copied)
        for name in names:
            if sha(backups / name) != sha(copied / name):
                raise RuntimeError("Immutable prewrite restore download mismatch")
        if stamp(release(TAG)) != pre_stamp:
            raise RuntimeError("CAS failed: canonical CDB moved before publishing")
        shutil.copyfile(proposed, history / "history-2026.parquet")
        meta = {
            "sha256": sha(history / "history-2026.parquet"),
            "bytes": (history / "history-2026.parquet").stat().st_size,
            "rows": merged.num_rows,
        }
        update_year_manifest(history, 2026, meta, extra={
            "recovery": "lossless_union_preserving_live",
            "recovery_backup_tag": BACKUP,
        })
        verify(REPO, Path(".cdb-global-writer-lock.json"))
        store = ReleaseStore(REPO, TAG, history)
        if stamp(release(TAG)) != pre_stamp:
            raise RuntimeError("CAS failed: canonical CDB moved during publication setup")
        store.upload_bundle([history / "history-2026.parquet",
                             history / "history_manifest.json"])
        # Independent fresh download; the uploader's local Python objects do not
        # constitute proof of what production now serves.
        readback = download_stable(REPO, TAG, root / "persisted")
        persisted = pq.read_table(root / "persisted" / "history-2026.parquet")
        if not persisted.equals(merged, check_metadata=False):
            raise RuntimeError("Remote persisted 2026 content mismatch")
        if not _live_prefix_is_conserved(original_live, persisted):
            raise RuntimeError("Existing live canonical rows changed")
        for year in range(1949, 2026):
            filename = f"history-{year}.parquet"
            if sha(history / filename) != sha(root / "persisted" / filename):
                raise RuntimeError("Unrelated canonical annual partition changed")
        counts.update(cdb_writes=1, state="REMOTE_PERSISTED_READBACK_VERIFIED",
                      prewrite_backup_tag=tag,
                      persisted_manifest_sha256=readback["manifest_sha256"])
    (root / "report.json").write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
    print("CDB_2026_LOSSLESS", json.dumps(counts, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
