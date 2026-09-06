"""Confirm prediction issuance only after a successful public deployment."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from _bootstrap import ROOT
from download_tennis_history import read_json, write_json
from release_store import ReleaseStore
from tbt.services.engine import confirm_publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    args = parser.parse_args()

    directory = ROOT / ".cache/tbt/predictions-confirm"
    store = ReleaseStore(args.data_repository, "tbt-predictions-v1", directory)
    store.download(
        extra_names=("ledger.json", "feed.json"),
        required_names=("ledger.json", "feed.json"),
    )
    ledger = read_json(directory / "ledger.json", [])
    feed = read_json(directory / "feed.json", {})
    if not isinstance(ledger, list) or not isinstance(feed, dict):
        raise ValueError("Invalid prediction publication artifacts")
    upcoming = feed.get("upcoming")
    if not isinstance(upcoming, list):
        raise ValueError("Invalid deployed feed")
    published_ids = {
        str(row.get("event_id"))
        for row in upcoming
        if isinstance(row, dict) and row.get("event_id")
    }
    before = sum(1 for row in ledger if isinstance(row, dict) and row.get("issued_at"))
    confirmed = confirm_publication(ledger, published_ids, datetime.now(timezone.utc))
    after = sum(1 for row in confirmed if isinstance(row, dict) and row.get("issued_at"))
    write_json(directory / "ledger.json", confirmed)
    store.upload_bundle([directory / "ledger.json"])
    print(json.dumps({"newly_confirmed": after - before, "published_ids": len(published_ids)}))


if __name__ == "__main__":
    main()
