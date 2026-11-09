"""Read-only financial check of issued VIAC ES in a supplied Results snapshot.

This is a CLI wrapper around the shared, strict accounting implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tbt.services.most_aces_roi_accounting import _number, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.feed.read_bytes()
    report = audit(json.loads(raw))
    report["source_sha256"] = hashlib.sha256(raw).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    if report["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
