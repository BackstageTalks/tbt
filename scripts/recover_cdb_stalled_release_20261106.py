#!/usr/bin/env python3
"""One-shot fail-closed repair of the pinned 2026-11-05 CDB release interruption.

No provider calls, model changes, row rewrites, schema changes or direct GitHub
release deletes. The ONLY writer is ReleaseStore.upload_bundle under the existing
cross-repository global lock. Unknown data or changed assets => no mutations.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

from audit_history_data import _duplicate_details, audit_partition
from cdb_global_writer_lock import verify
from release_store import ReleaseStore
from repair_missing_history_manifest import _partition_meta

REPOSITORY = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
YEAR_ASSET = "history-2022.parquet"
PINNED = {
    YEAR_ASSET: (713844992, "2bb7b19b3b42e68e4d5e337ad9101cb3e3b660a00166765467b647a01c2c7823", 16922453),
    "history_manifest.json": (713914514, "0723b483c904284bced960b44005be0df4ed50a463e0b953f7fa3f659065354d", 44377),
    "_tbt_bundle_manifest.json": (713914873, "71ab6c2f86193f2f02937a72221280ccd31cfff2a02360aede0adb6ee6e7fad9", 17949),
    "blinq-txn-b543ef19a71c41b58ecab5753d5b2ba6.json": (713986347, "8fddf297a495c6d0890c2816fec556c9b5410166acfe1854a6964cc05dff7d95", 120),
    "blinq-txn-426d57229ef145d29bd0cc2f3d8afd39.json": (713988199, "0f0ca43b71b228c9deb1850fd7da91282cca0874aec2766fa09c51a9ca009c98", 120),
    "blinq-candidate-426d57229ef145d29bd0cc2f3d8afd39-history-2022.parquet": (713988478, "8f6bea173af1c5c44ebfee6ce271fdcb86fba49a9b3d9eb01c89171bbd0607f9", 16922491),
}
TRANSIENT = tuple(sorted(n for n in PINNED if n.startswith(("blinq-txn-", "blinq-candidate-"))))


def snapshot(assets: dict) -> dict:
    return {name: (asset.get("id"), asset.get("digest"), asset.get("size"))
            for name, asset in assets.items()}


def assert_pinned(assets: dict) -> None:
    transients = {name for name in assets if name.startswith(
        ("blinq-txn-", "blinq-rollback-", "blinq-candidate-"))}
    if transients != set(TRANSIENT):
        raise RuntimeError(f"Unexpected CDB transactions; stop: {sorted(transients)}")
    for name, (ident, digest, size) in PINNED.items():
        actual = assets.get(name) or {}
        if (actual.get("id"), actual.get("digest"), actual.get("size")) != (
            ident, "sha256:" + digest, size
        ):
            raise RuntimeError(f"Release asset has changed since incident audit: {name}")


def verify_inventory_consistency(assets: dict, history: dict, bundle: dict,
                                 *, permitted_mismatch: frozenset[str]) -> tuple[int, int]:
    years = history.get("years")
    files = bundle.get("files")
    if not isinstance(years, dict) or not years or not isinstance(files, dict):
        raise ValueError("Invalid CDB history or bundle manifest")
    expected_history = set()
    year_mismatches = set()
    for year, meta in years.items():
        if not isinstance(meta, dict) or not re.fullmatch(r"\d{4}", str(year)):
            raise ValueError("Invalid CDB year entry")
        name = str(meta.get("asset") or f"history-{year}.parquet")
        if not re.fullmatch(r"history-\d{4}\.parquet", name):
            raise ValueError("Unsafe CDB year asset name")
        expected_history.add(name)
        actual = assets.get(name)
        if not actual:
            raise FileNotFoundError(f"CDB history partition absent: {name}")
        if (actual.get("digest"), actual.get("size")) != (
            "sha256:" + str(meta.get("sha256")), meta.get("bytes")
        ):
            year_mismatches.add(name)
    remote_history = {name for name in assets if re.fullmatch(r"history-\d{4}\.parquet", name)}
    if expected_history != remote_history:
        raise RuntimeError("History manifest omits or invents CDB year partitions")
    bundle_mismatches = set()
    for name, meta in files.items():
        if not isinstance(meta, dict) or name not in assets:
            raise FileNotFoundError(f"Committed CDB checksum asset missing: {name}")
        actual = assets[name]
        if (actual.get("digest"), actual.get("size")) != (
            "sha256:" + str(meta.get("sha256")), meta.get("bytes")
        ):
            bundle_mismatches.add(name)
    if year_mismatches != permitted_mismatch or bundle_mismatches != permitted_mismatch:
        raise RuntimeError("Unrecognized CDB checksum mismatch: " + json.dumps({
            "year": sorted(year_mismatches), "bundle": sorted(bundle_mismatches)
        }))
    if "history_manifest.json" not in files:
        raise RuntimeError("History manifest lacks committed checksum")
    return len(expected_history), len(files)


def _download_verified(store: ReleaseStore, assets: dict, name: str) -> Path:
    store._download_asset(name)
    path = store.directory / name
    if not store._verified_asset(assets, name, path):
        raise RuntimeError(f"Downloaded bytes do not match GitHub SHA-256/size: {name}")
    return path


def recover(store: ReleaseStore, *, apply: bool = False) -> dict:
    verify(REPOSITORY, Path(".cdb-global-writer-lock.json"))
    before = store._release_asset_inventory()
    assert_pinned(before)
    baseline = snapshot(before)
    for name in ("history_manifest.json", store.BUNDLE_MANIFEST, YEAR_ASSET, *TRANSIENT):
        _download_verified(store, before, name)
    for name in TRANSIENT:
        if not name.startswith("blinq-txn-"):
            continue
        obj = json.loads((store.directory / name).read_text(encoding="utf-8"))
        if (obj.get("schema") != 1 or obj.get("created") != []
                or not re.fullmatch(r"[0-9a-f]{64}", str(obj.get("target_bundle_sha256") or ""))):
            raise RuntimeError(f"Unrecognized interrupted CDB journal: {name}")

    history_path = store.directory / "history_manifest.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    bundle = json.loads((store.directory / store.BUNDLE_MANIFEST).read_text(encoding="utf-8"))
    years_count, checksums_count = verify_inventory_consistency(
        before, history, bundle, permitted_mismatch=frozenset({YEAR_ASSET})
    )

    summary, issues, identities = audit_partition(store.directory / YEAR_ASSET)
    if summary.get("fatal") or issues:
        raise RuntimeError("Canonical 2022 history has invalid rows/identity")
    if (_duplicate_details(identities, "match_id", "duplicate_match_id") or
            _duplicate_details(identities, "provider_event_id", "duplicate_provider_event_id")):
        raise RuntimeError("Duplicate canonical 2022 identity")
    actual_year = _partition_meta(store.directory / YEAR_ASSET, 2022)
    old = history["years"].get("2022")
    if not isinstance(old, dict) or type(old.get("rows")) is not int:
        raise RuntimeError("Missing authoritative 2022 history inventory")
    if actual_year["rows"] < old["rows"]:
        raise RuntimeError("2022 canonical history row regression")
    for field, sign in (("history_start", -1), ("history_end", 1)):
        previous = old.get(field)
        now = actual_year[field]
        if isinstance(previous, str) and ((sign < 0 and now > previous) or (sign > 0 and now < previous)):
            raise RuntimeError(f"2022 canonical history coverage regression: {field}")
    if (actual_year["sha256"], actual_year["bytes"]) != (
        PINNED[YEAR_ASSET][1], PINNED[YEAR_ASSET][2]
    ):
        raise RuntimeError("Audited 2022 parquet is not pinned canonical generation")
    # Preserve every pre-existing metadata field; only the audited year's
    # rows/range/hash/size can be synchronized to the unchanged current parquet.
    updated = dict(history)
    updated["years"] = dict(history["years"])
    updated["years"]["2022"] = {**old, **{
        key: actual_year[key] for key in (
            "rows", "history_start", "history_end", "sha256", "bytes"
        )
    }}
    report = {
        "status": "VALIDATED_NO_WRITES" if not apply else "PREPARED",
        "pin": "2026-11-05T16:15Z",
        "canonical_2022_sha256": actual_year["sha256"],
        "canonical_2022_rows": actual_year["rows"],
        "prior_2022_rows": old["rows"],
        "history_partitions_checked": years_count,
        "committed_asset_checksums_checked": checksums_count,
        "transactions_to_retire": len(TRANSIENT),
        "provider_calls": 0,
        "canonical_parquet_rewrites": 0,
    }
    if not apply:
        return report

    history_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    def still_same():
        verify(REPOSITORY, Path(".cdb-global-writer-lock.json"))
        if snapshot(store._release_asset_inventory()) != baseline:
            raise RuntimeError("Private CDB release changed after preflight")
    still_same()

    # Use the existing guarded journal, CAS-style asset ID/digest checks,
    # full rollback path and history-row monotonicity enforcement.
    store.upload_bundle([store.directory / YEAR_ASSET, history_path],
                        remove_names=TRANSIENT, before_upload=still_same)

    after = store._release_asset_inventory()
    if any(name in after for name in TRANSIENT):
        raise RuntimeError("Stale CDB transaction residue survived repair")
    if (after[YEAR_ASSET].get("id"), after[YEAR_ASSET].get("digest")) != (
        PINNED[YEAR_ASSET][0], "sha256:" + PINNED[YEAR_ASSET][1]
    ):
        raise RuntimeError("Canonical parquet bytes/asset were unexpectedly replaced")
    for name, state in baseline.items():
        if name in TRANSIENT or name in {"history_manifest.json", store.BUNDLE_MANIFEST}:
            continue
        if snapshot(after).get(name) != state:
            raise RuntimeError(f"Unrelated CDB release asset changed: {name}")

    # Independent normal reader proves release-byte SHA and history-year integrity.
    with tempfile.TemporaryDirectory(prefix="cdb-post-repair-") as tmp:
        reader = ReleaseStore(REPOSITORY, TAG, Path(tmp))
        selected = reader.download(require_bundle_manifest=True)
        verified_history = json.loads((reader.directory / "history_manifest.json").read_text())
        verified_bundle = json.loads((reader.directory / reader.BUNDLE_MANIFEST).read_text())
        verify_inventory_consistency(reader._release_asset_inventory(),
                                     verified_history, verified_bundle,
                                     permitted_mismatch=frozenset())
    report.update(status="CDB_REPAIRED_INDEPENDENT_READBACK_PASS",
                  downloaded_files_verified=len(selected),
                  transactions_remaining=0)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Explicit one-shot metadata repair")
    ap.add_argument("--work-dir", default=".cache/tbt/cdb-recovery-20261106")
    args = ap.parse_args()
    directory = Path(args.work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    store = ReleaseStore(REPOSITORY, TAG, directory)
    report = recover(store, apply=args.apply)
    (directory / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
