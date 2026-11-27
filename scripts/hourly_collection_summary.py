import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.services.hourly_collection import build_run, publish_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".cache/tbt/history", type=Path)
    args = parser.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    report = build_run(
        args.dir, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"],
        datetime.now(timezone.utc), os.getenv("FALLBACK_EXPECTED") == "true",
    )
    path = args.dir / "hourly_collection_summary.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    publish_run(report)


if __name__ == "__main__":
    main()
