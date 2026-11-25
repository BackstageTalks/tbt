"""Build the public draw sidecar from today's offer and existing match-status evidence.

Run with PYTHONPATH=api:scripts. The evidence document contains events (raw
TennisAPI fixtures already seen by the collector) and statuses (verified
match-status rows keyed by native event ID). No fixture lookups are made here.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from tbt.services.bracket import (  # re-exported for script callers
    BRATISLAVA, apply_settlement, build_feed, normalize_draws,
)


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    try:
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("api/data/bracket.json"))
    parser.add_argument("--budget-db", type=Path, default=Path(".cache/bracket-budget.sqlite3"))
    parser.add_argument("--day", type=date.fromisoformat, default=datetime.now(BRATISLAVA).date())
    parser.add_argument("--settlements-only", action="store_true")
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    previous = read(args.output) if args.output.is_file() else {}
    client = budget = None

    def fetch(tid, sid):
        nonlocal client, budget
        from history_download_budget import LocalRequestBudget, RequestBudgetExceeded
        from tbt.errors import ProviderError
        from tbt.providers.rapidapi import RapidTennisClient
        from tbt.providers.shared_budget import SharedBudgetExhausted, SharedBudgetUnavailable, from_environment
        if client is None:
            if from_environment() is None:
                raise SystemExit("Shared API budget configuration required for cup-trees")
            args.budget_db.parent.mkdir(parents=True, exist_ok=True)
            budget = LocalRequestBudget(args.budget_db, limit)
            client = RapidTennisClient(request_budget=budget)
            client.retry_attempts = 1
        try:
            return client.tournament_cup_trees(tid, sid)
        except (ProviderError, RequestBudgetExceeded, SharedBudgetExhausted, SharedBudgetUnavailable) as error:
            raise ValueError(type(error).__name__) from error

    limit = 0 if args.settlements_only else int(os.getenv("TBT_BRACKET_MAX_REQUESTS", "30"))
    if not 0 <= limit <= 14500:
        parser.error("TBT_BRACKET_MAX_REQUESTS must be in 0..14500")
    try:
        snapshot, report = build_feed(read(args.feed), read(args.evidence), previous, args.day, fetch, limit)
        write_atomic(args.output, snapshot)
        print(json.dumps(report))
    finally:
        if client is not None:
            client.close()
        if budget is not None:
            budget.close()


if __name__ == "__main__":
    main()
