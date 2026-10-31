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
    print(json.dumps({"prediction_release_preflight": store.recover_interrupted_swaps()}))


if __name__ == "__main__":
    main()
