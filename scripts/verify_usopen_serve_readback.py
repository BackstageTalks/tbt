"""Compare backed-up and committed 2024 canonical snapshots after serve enrichment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_snapshot
from import_usopen_serve_metadata import MARKER_KEY


def _dump(match):
    return match.model_dump(mode="json") if hasattr(match, "model_dump") else match.dict()


def verify(before, after, stage):
    expected = {}
    for item in stage:
        if not isinstance(item, dict) or item.get("schema") != 1 or item.get("import_ready") is not True:
            raise ValueError("Invalid staged record")
        mid = str(item.get("match_id") or "")
        if not mid or mid in expected:
            raise ValueError("Duplicate staged match identity")
        expected[mid] = item["marker"]
    old = {str(row.match_id): _dump(row) for row in before}
    current = {str(row.match_id): _dump(row) for row in after}
    if len(old) != len(before) or len(current) != len(after) or old.keys() != current.keys():
        raise ValueError("Canonical match count / identity changed")
    changed = set()
    for mid, original in old.items():
        persisted = current[mid]
        if mid not in expected:
            if persisted != original:
                raise ValueError(f"Unstaged canonical record modified: {mid}")
            continue
        if original.get("provider_payload", {}).get(MARKER_KEY) is not None:
            raise ValueError("Backed-up marker already existed")
        previous = dict(original)
        updated = dict(persisted)
        before_payload = dict(previous.pop("provider_payload") or {})
        after_payload = dict(updated.pop("provider_payload") or {})
        if previous != updated:
            raise ValueError(f"Non-provider canonical fields changed: {mid}")
        recorded = after_payload.pop(MARKER_KEY, None)
        if recorded != expected[mid] or after_payload != before_payload:
            raise ValueError(f"Persisted serve marker or other provider context differs: {mid}")
        changed.add(mid)
    if changed != set(expected):
        raise ValueError("Unverified stage/readback match set mismatch")
    return {"schema": 1, "canonical_rows_before": len(old),
            "canonical_rows_after": len(current), "enriched_matches": len(changed),
            "stats_overwrites": 0, "identity_changes": 0, "unstaged_changes": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", type=Path, required=True)
    ap.add_argument("--persisted", type=Path, required=True)
    ap.add_argument("--stage", type=Path, required=True)
    args = ap.parse_args()
    with args.stage.open(encoding="utf-8") as fh:
        stage = [json.loads(line) for line in fh if line.strip()]
    result = verify(load_snapshot(args.backup), load_snapshot(args.persisted), stage)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
