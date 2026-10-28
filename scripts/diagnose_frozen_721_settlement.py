"""Read-only diagnostics for unmatched frozen 7.2.1 pre-match pairs.

Require original immutable paired ledger and independently SHA-verified CDB
partition. Print only aggregate reason codes; never fuzzy-match, settle, or
publish anything. No provider credentials or canonical writer lock needed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from _bootstrap import ROOT
from settle_frozen_721_shadow import (
    DATA_REPO, SHADOW_TAG, LEDGER_ASSET, REPORT_ASSET, ReleaseStore,
    _utc, completed_matches_for_pending, download_verified_years,
    pending_schedule_diagnostics,
)
from tbt.services.frozen_721_research import (
    exclude_repeated_events, validate_frozen_evidence,
)


def diagnose(*, repo=DATA_REPO, workdir=None, now=None):
    if repo != DATA_REPO:
        raise ValueError("Unexpected canonical data repository")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Explicit timezone required")
    now = now.astimezone(timezone.utc)
    root = Path(workdir or ROOT / ".cache/tbt/721-identity-probe")
    store = ReleaseStore(repo, SHADOW_TAG, root / "shadow")
    store.download(
        extra_names=(LEDGER_ASSET, REPORT_ASSET),
        required_names=(LEDGER_ASSET, REPORT_ASSET),
        require_bundle_manifest=True,
    )
    payload = json.loads((store.directory / LEDGER_ASSET).read_text(encoding="utf-8"))
    source = payload.get("source") or {}
    rows, before = validate_frozen_evidence(
        payload, production_version=source.get("production_version")
    )
    rows = exclude_repeated_events(rows)
    pending = [r for r in rows if r.get("status") == "pending"]
    years = {_utc(r["scheduled_at"]).year for r in pending}
    canonical, provenance = download_verified_years(repo, root / "canonical", years)
    eligible, categories = completed_matches_for_pending(rows, canonical, now)
    pending_counts = pending_schedule_diagnostics(rows, canonical, now)
    # The accepted matches are counted only. No settlement of them is performed.
    safe = {k: v for k, v in categories.items() if k != "provider_alias_evidence"}
    return {
        "status": "READ_ONLY_IDENTITY_DIAGNOSTICS",
        "at_utc": now.isoformat(),
        "ledger_pending": before["pending"],
        "ledger_settled_unchanged": before["settled"],
        "eligible_for_separate_strict_settlement": len(eligible),
        "canonical_matching": safe,
        "pending_diagnostics": pending_counts,
        "canonical_provenance": provenance,
        "provider_requests": 0,
        "CDB_mutated": False,
        "shadow_mutated": False,
        "production_mutated": False,
        "model_promoted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".cache/tbt/721-identity-probe/report.json")
    args = parser.parse_args()
    report = diagnose()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False))


if __name__ == "__main__":
    main()
