#!/usr/bin/env python3
"""Repair only provable interrupted CDB publication before paid API work.

Run under the existing cross-repository single-writer lock. No provider calls,
new writer, schema changes, or speculative CDB mutations.
"""
import argparse
import json
import os
import re
from pathlib import Path

from cdb_global_writer_lock import verify
from release_store import ReleaseStore
from repair_missing_history_manifest import repair_missing_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=os.environ.get(
        "TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--release-tag", default="tbt-data-v1")
    parser.add_argument("--work-dir", default=".cache/tbt/history-release-preflight")
    args = parser.parse_args()
    verify(args.data_repository, Path(".cdb-global-writer-lock.json"))
    store = ReleaseStore(args.data_repository, args.release_tag, Path(args.work_dir))
    recovered = store.recover_interrupted_swaps()
    assets = store._asset_names()
    if "history_manifest.json" not in assets and any(
        re.fullmatch(r"history-\\d{4}\\.parquet", name) for name in assets
    ):
        # The original 2026-10-30 outage predates the staged-swap protocol.
        # Reuse the existing audited identity/schema/dedup recovery, and verify
        # through the normal downloader before allowing paid API calls.
        repaired = repair_missing_manifest(store)
        print(json.dumps({"release_preflight": recovered, "legacy_manifest_repair": repaired}))
        return
    print(json.dumps({"release_preflight": recovered, "manifest_present": "history_manifest.json" in assets}))


if __name__ == "__main__":
    main()
