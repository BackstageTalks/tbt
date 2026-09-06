"""Fetch the small private serving snapshot before an Azure deployment."""
from __future__ import annotations

import json
import os
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed, read_feed


PREDICTION_ASSETS = {"feed.json", "ledger.json"}


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


def main() -> None:
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    repository = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")

    payload = empty_feed()
    if os.getenv("GH_TOKEN"):
        # Verify/download the complete private prediction candidate in cache.
        # Never download ledger.json into api/data, where it could be packaged
        # with the public serving API.
        cache = ROOT / ".cache/tbt/deploy-predictions"
        store = ReleaseStore(repository, "tbt-predictions-v1", cache)
        state = _prediction_asset_state(store)
        if state == "complete":
            store.download(
                extra_names=("feed.json", "ledger.json"),
                required_names=("feed.json", "ledger.json"),
            )
            payload = read_feed(cache / "feed.json")

    # If no private prediction candidate exists, overwrite any checked-in stale
    # snapshot with an honest empty feed instead of silently deploying it.
    target.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print("Serving snapshot ready:", payload.get("ready", False))


if __name__ == "__main__":
    main()
