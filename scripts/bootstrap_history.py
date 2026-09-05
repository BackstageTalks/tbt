from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from _bootstrap import ROOT  # noqa: F401
from tbt.config import settings
from tbt.services.sync import bootstrap_history

HOT_TIER_START_YEAR = 2025


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap HOT tennis history into Supabase. V20.4 stores 2024 and older "
            "directly in the private GitHub Release snapshot."
        )
    )
    parser.add_argument("--start-year", type=int, default=max(settings.history_start_year, HOT_TIER_START_YEAR))
    parser.add_argument("--end-year", type=int, default=datetime.now(timezone.utc).year)
    args = parser.parse_args()

    if args.start_year > args.end_year:
        raise SystemExit("start-year must be <= end-year")
    if args.start_year < HOT_TIER_START_YEAR:
        raise SystemExit(
            "V20.4 safety stop: refusing to write pre-2025 history into Supabase. "
            "Use scripts/bootstrap_history_release.py / the Bootstrap tennis history workflow instead."
        )

    report = bootstrap_history(args.start_year, args.end_year)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
