"""Confirm prediction issuance only after a successful public deployment."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed
from tbt.services.publication import confirm_publication, validate_publication_candidate


PREDICTION_ASSETS = {"feed.json", "ledger.json"}


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def _prediction_asset_state(store: ReleaseStore) -> str:
    assets = store._asset_names()
    present = PREDICTION_ASSETS & assets
    if not present:
        return "absent"
    if present != PREDICTION_ASSETS:
        missing = sorted(PREDICTION_ASSETS - present)
        raise FileNotFoundError(
            "Prediction release is incomplete; missing assets: " + ", ".join(missing)
        )
    return "complete"


def _is_honest_empty_feed(value) -> bool:
    expected = empty_feed()
    return isinstance(value, dict) and all(value.get(key) == expected[key] for key in expected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--deployed-feed",
        default=None,
        help="Local feed file that was just deployed; must match the private candidate exactly.",
    )
    args = parser.parse_args(argv)

    deployed_feed = None
    if args.deployed_feed:
        deployed_feed = read_json(Path(args.deployed_feed), None)
        if not isinstance(deployed_feed, dict):
            raise ValueError("Invalid deployed feed")

    directory = ROOT / ".cache/tbt/predictions-confirm"
    store = ReleaseStore(args.data_repository, "tbt-predictions-v1", directory)
    state = _prediction_asset_state(store)

    if state == "absent":
        # A manual/bootstrap deployment can legitimately have no prediction
        # candidate yet. It must have deployed the honest empty feed; there is
        # then nothing to issue and confirmation is a successful no-op.
        if deployed_feed is not None and not _is_honest_empty_feed(deployed_feed):
            raise RuntimeError(
                "No private prediction candidate exists, but the deployed feed is not empty; "
                "refusing to confirm an unverifiable deployment"
            )
        print(json.dumps({"status": "no_candidate", "newly_confirmed": 0, "published_ids": 0}))
        return

    store.download(
        extra_names=("ledger.json", "feed.json"),
        required_names=("ledger.json", "feed.json"),
    )
    ledger = read_json(directory / "ledger.json", [])
    feed = read_json(directory / "feed.json", {})
    if not isinstance(ledger, list) or not isinstance(feed, dict):
        raise ValueError("Invalid prediction publication artifacts")

    if deployed_feed is None:
        deployed_feed = feed
    elif deployed_feed != feed:
        raise RuntimeError(
            "Deployed feed does not match the current private publication candidate; "
            "refusing to confirm issuance"
        )

    upcoming = deployed_feed.get("upcoming")
    if not isinstance(upcoming, list):
        raise ValueError("Invalid deployed feed")
    validate_publication_candidate(deployed_feed, ledger)
    published_rows = upcoming
    before = sum(1 for row in ledger if isinstance(row, dict) and row.get("issued_at"))
    confirmed = confirm_publication(ledger, published_rows, datetime.now(timezone.utc))
    after = sum(1 for row in confirmed if isinstance(row, dict) and row.get("issued_at"))
    write_json(directory / "ledger.json", confirmed)
    store.upload_bundle([directory / "ledger.json"])
    print(json.dumps({"status": "confirmed", "newly_confirmed": after - before, "published_ids": len(published_rows)}))


if __name__ == "__main__":
    main()
