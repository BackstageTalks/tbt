"""Offline v7.2.1 calibration audit from a private, source-pinned paired ledger.

No network, provider API, training, model release change or promotion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401 - adds api/ and scripts/ to sys.path
from tbt.services.frozen_721_research import research_frozen_721


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True,
                        help="Local PRIVATE paired-v7.2.1 evidence JSON; not legacy shadow")
    parser.add_argument("--production-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Input must not be overwritten")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = research_frozen_721(payload, production_version=args.production_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({"status": report["status"], "reason": report.get("reason"),
                      "fit_rows": report["fit_rows"], "evaluation_rows": report["evaluation_rows"],
                      "provider_requests": 0, "automatic_promotion": False}))


if __name__ == "__main__":
    main()
