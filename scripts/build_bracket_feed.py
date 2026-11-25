"""Update a local draw snapshot using existing match-status evidence.

Run with PYTHONPATH=api:scripts. The evidence document contains events (raw
TennisAPI fixtures already seen by the collector) and statuses (verified
match-status rows keyed by native event ID). The match-status worker fetches draws.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
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
    parser.add_argument("--day", type=date.fromisoformat, default=datetime.now(BRATISLAVA).date())
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    previous = read(args.output) if args.output.is_file() else {}
    def offline_only(*_):
        raise AssertionError("Draws are fetched by the match-status worker")

    snapshot, report = build_feed(read(args.feed), read(args.evidence), previous, args.day, offline_only, 0)
    write_atomic(args.output, snapshot)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
