from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT
from tbt.config import settings
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.backtest_service import walk_forward_backtest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run leakage-safe yearly "
            "walk-forward backtest"
        )
    )

    parser.add_argument(
        "--first-test-year",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--report",
        default=str(
            ROOT
            / "reports"
            / "backtest.json"
        ),
    )

    args = parser.parse_args()

    repo = SupabaseRepository()

    matches = (
        repo.get_completed_matches()
    )

    report = (
        walk_forward_backtest(
            matches,
            first_test_year=(
                args.first_test_year
            ),
        )
    )

    path = Path(
        args.report
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    if settings.supabase_write_key:
        repo.save_backtest_run(
            {
                # This report evaluates fresh models fitted inside
                # each walk-forward fold. It must not be attributed
                # to the currently deployed/champion model version.
                "model_version": None,
                "report": report,
            }
        )

    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
