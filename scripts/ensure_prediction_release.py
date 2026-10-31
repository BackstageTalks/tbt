#!/usr/bin/env python3
"""Restore incomplete private prediction publication before any paid refresh.

Only invoke inside the existing tbt-production-deploy serialized workflow.
This does not request provider data or change the production model.
"""
import argparse
import json
import os
from pathlib import Path

from release_store import ReleaseStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=os.environ.get(
        "TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--work-dir", default=".cache/tbt/prediction-release-preflight")
    args = parser.parse_args()
    store = ReleaseStore(args.data_repository, "tbt-predictions-v1", Path(args.work_dir))
    recovered = store.recover_interrupted_swaps()
    # Check all three live-serving invariants even when no rollback was found.
    # The strict reader validates SHA-256 against the committed bundle.
    selected = store.download(required_names=(
        "feed.json", "ledger.json", "daily_offer_snapshot.json",
    ))
    assets = store._release_asset_inventory()
    pending = [name for name in assets
               if name.startswith(("blinq-rollback-", "blinq-txn-", "blinq-candidate-"))]
    if pending:
        raise RuntimeError("Unresolved production release transaction: " + ", ".join(sorted(pending)))
    print(json.dumps({"prediction_release_preflight": recovered,
                      "verified_assets": selected,
                      "pending_transactions": 0}))


if __name__ == "__main__":
    main()
