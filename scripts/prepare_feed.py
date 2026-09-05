"""Fetch the small private serving snapshot before an Azure deployment."""
import json
import os
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed, read_feed

target = ROOT / "api/data/feed.json"
target.parent.mkdir(parents=True, exist_ok=True)
repository = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
if os.getenv("GH_TOKEN"):
    store = ReleaseStore(repository, "tbt-predictions-v1", target.parent)
    store.download(extra_names=("feed.json",))
    payload = read_feed(target)
else:
    # Initial manual deployment can show an honest empty state without data access.
    payload = empty_feed()
target.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
print("Serving snapshot ready:", payload.get("ready", False))
