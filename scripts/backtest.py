from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT
from tbt.config import settings
from tbt.data.history_source import default_history_dir, load_training_history
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.backtest import walk_forward_backtest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run leakage-safe walk-forward backtest from private GitHub history partitions"
    )
    parser.add_argument("--first-test-year", type=int, default=None)
    parser.add_argument("--report", default=str(ROOT / "reports" / "backtest.json"))
    parser.add_argument("--history-dir", default=str(default_history_dir(ROOT)))
    args = parser.parse_args()

    matches = load_training_history(args.history_dir, root=ROOT)
    report = walk_forward_backtest(matches, first_test_year=args.first_test_year)
    report["history_source"] = "private GitHub Release yearly Parquet partitions"
    report["history_rows_loaded"] = len(matches)

    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if settings.supabase_write_key:
        repo = SupabaseRepository()
        repo.save_backtest_run({"model_version": None, "report": report})

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
