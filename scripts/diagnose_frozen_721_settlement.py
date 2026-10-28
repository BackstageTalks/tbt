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


def verified_schedule_shift_distribution(pending, canonical):
    """Only count independently witnessed, uniquely identified native events.

    Descriptive timing histogram; this does NOT promote a match to settlement.
    """
    from collections import Counter, defaultdict

    by_event = defaultdict(list)
    for match in canonical:
        raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        evidence = raw.get("_tbt_event_identity")
        if not isinstance(evidence, dict):
            continue
        event = str(raw.get("_tbt_provider_event_id") or "")
        if event and str(evidence.get("event_id") or "") == event:
            by_event[event].append(match)

    shifts = Counter()
    before_real_start = after_real_start = 0
    min_abs_hours = max_abs_hours = None
    for row in pending:
        event = str(row.get("event_id") or "")
        matches = by_event.get(event, [])
        if len(matches) != 1:
            continue
        match = matches[0]
        raw = match.provider_payload or {}
        witness = raw.get("_tbt_event_identity") or {}
        canonical_players = {str(match.player1_id), str(match.player2_id)}
        if (witness.get("status") != "finished"
                or {str(witness.get("home") or ""), str(witness.get("away") or "")} != canonical_players
                or {str(row.get("player1_id") or ""), str(row.get("player2_id") or "")} != canonical_players
                or str(row.get("tour") or "").upper() != str(match.tour or "").upper()):
            continue
        delta_h = (match.scheduled_at - _utc(row["scheduled_at"])).total_seconds() / 3600
        abs_h = abs(delta_h)
        if abs_h <= 24:
            continue
        direction = "later" if delta_h > 0 else "earlier"
        band = ("24_48h" if abs_h <= 48 else
                "2_7d" if abs_h <= 168 else
                "7_30d" if abs_h <= 720 else "over_30d")
        shifts[f"{direction}_{band}"] += 1
        if _utc(row["captured_at"]) < match.scheduled_at:
            before_real_start += 1
        else:
            after_real_start += 1
        min_abs_hours = abs_h if min_abs_hours is None else min(min_abs_hours, abs_h)
        max_abs_hours = abs_h if max_abs_hours is None else max(max_abs_hours, abs_h)
    return {
        "strict_witnessed_shift_over_24h": sum(shifts.values()),
        "direction_and_duration": dict(sorted(shifts.items())),
        "capture_before_canonical_start": before_real_start,
        "capture_at_or_after_canonical_start": after_real_start,
        "smallest_abs_hours": round(min_abs_hours, 2) if min_abs_hours is not None else None,
        "largest_abs_hours": round(max_abs_hours, 2) if max_abs_hours is not None else None,
        "settlement_automatically_authorized": False,
    }


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
    shift_distribution = verified_schedule_shift_distribution(pending, canonical)
    # The accepted matches are counted only. No settlement of them is performed.
    safe = {k: v for k, v in categories.items() if k != "provider_alias_evidence"}
    return {
        "status": "READ_ONLY_IDENTITY_DIAGNOSTICS",
        "at_utc": now.isoformat(),
        "ledger_pending": before["pending"],
        "ledger_settled_unchanged": before["settled"],
        "eligible_for_separate_strict_settlement": len(eligible),
        "canonical_matching": safe,
        "verified_schedule_shift_distribution": shift_distribution,
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
