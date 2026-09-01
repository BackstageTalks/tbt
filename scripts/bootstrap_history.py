from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from _bootstrap import ROOT  # noqa: F401
from tbt.config import settings
from tbt.services.sync import bootstrap_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap point-in-time tennis history into Supabase")
    parser.add_argument("--start-year", type=int, default=settings.history_start_year)
    parser.add_argument("--end-year", type=int, default=datetime.now(timezone.utc).year)
    args = parser.parse_args()
    if args.start_year > args.end_year:
        raise SystemExit("start-year must be <= end-year")
    report = bootstrap_history(args.start_year, args.end_year)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
