"""Read-only ATP/WTA source preflight for BlinQ Model Factory phase 1.

This intentionally does not freeze fit inputs, import CDB rows, retrain, or
alter a champion. The protected fitter owns the subsequent immutable freeze.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.services.data_quality import audit_history


REPO = "BackstageTalks/tbt-data"
ROOT_OUT = ROOT / ".cache/tbt/model-factory-preflight"
CANONICAL = "tbt-data-v1"
MINIMUM_ELIGIBLE_MATCHES = 500000


def inspect(matches, *, app_sha: str, source_manifest_digest: str) -> dict:
    """Count trustworthy source fields; never impute missing statistics."""
    accepted, quality = audit_history(matches)
    counts = Counter()
    dates: dict[str, list[str]] = {"atp": [], "wta": []}
    coverage = {
        tour: {"rank_pair": 0, "serve": 0, "return": 0,
               "break_points": 0, "stat_rows": 0}
        for tour in ("atp", "wta")
    }
    for m in accepted:
        tour = str(m.tour or "").lower()
        if tour not in coverage:
            counts["other_tour"] += 1
            continue
        counts[tour] += 1
        dates[tour].append(m.scheduled_at.astimezone(timezone.utc).date().isoformat())
        if m.player1_rank is not None and m.player2_rank is not None:
            coverage[tour]["rank_pair"] += 1
        values = {str(key).lower(): value for key, value in
                  (m.stats or {}).items() if value is not None}
        if values:
            coverage[tour]["stat_rows"] += 1
        for field, terms in (("serve", ("serve", "service", "first_")),
                             ("return", ("return", "receiv")),
                             ("break_points", ("break_point", "breakpoint"))):
            if any(any(term in key for term in terms) for key in values):
                coverage[tour][field] += 1
    total = counts["atp"] + counts["wta"]
    if total < MINIMUM_ELIGIBLE_MATCHES:
        raise ValueError("Canonical ATP/WTA dataset unexpectedly small")
    result = {
        "schema": 1,
        "status": "READ_ONLY_PREFLIGHT_COMPLETE_NOT_FROZEN",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_sha": app_sha,
        "canonical_source_release": CANONICAL,
        "canonical_manifest_sha256": source_manifest_digest,
        "raw_rows": len(matches),
        "eligible_rows": total,
        "excluded_rows": len(matches) - total,
        "quality_audit": quality,
        "tours": {
            t: {"eligible_matches": counts[t],
                "first_match_date": min(dates[t]) if dates[t] else None,
                "last_match_date": max(dates[t]) if dates[t] else None,
                "coverage_counts": coverage[t]}
            for t in ("atp", "wta")
        },
        "provider_requests": 0,
        "cdb_mutations": 0,
        "production_mutations": 0,
        "next": "Protected fit independently freezes and verifies full inputs; preflight is not a training certificate.",
    }
    return result


def main():
    if os.environ.get("GITHUB_REPOSITORY") != "BackstageTalks/tbt":
        raise RuntimeError("Unexpected repository")
    sha = str(os.environ.get("GITHUB_SHA") or "")
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise RuntimeError("Pinned application commit required")
    ROOT_OUT.mkdir(parents=True, exist_ok=False)
    source = ROOT_OUT / "source"
    ReleaseStore(REPO, CANONICAL, source).download(require_bundle_manifest=True)
    manifest = source / "history_manifest.json"
    if not manifest.is_file():
        raise RuntimeError("Canonical history manifest unavailable")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    raw = load_partitions(source)
    clean, safety = sanitize_history_identities(raw)
    if safety.get("unresolved", 0):
        raise RuntimeError("Unresolved canonical identities; preparation rejected")
    report = inspect(clean, app_sha=sha, source_manifest_digest=manifest_hash)
    report["identity_safety"] = safety
    path = ROOT_OUT / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                               indent=2, default=str) + "\n", encoding="utf-8")
    back = json.loads(path.read_text(encoding="utf-8"))
    if back["status"] != "READ_ONLY_PREFLIGHT_COMPLETE_NOT_FROZEN" or back["code_sha"] != sha:
        raise RuntimeError("Preflight report readback mismatch")
    print(json.dumps({
        "status": back["status"],
        "atp": back["tours"]["atp"],
        "wta": back["tours"]["wta"],
        "excluded": back["excluded_rows"],
        "manifest_sha256": manifest_hash,
    }, ensure_ascii=False), flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("### BlinQ Model Factory · 1. Pripraviť dáta\n")
            out.write("| Tour | Zápasy | Rank pair | Serve | Return | Break points |\n")
            out.write("|---|---:|---:|---:|---:|---:|\n")
            for t in ("atp", "wta"):
                item = back["tours"][t]
                c = item["coverage_counts"]
                out.write(f"| {t.upper()} | {item['eligible_matches']} | {c['rank_pair']} | {c['serve']} | {c['return']} | {c['break_points']} |\n")
            out.write("\nRead-only preflight; **inputs are NOT yet frozen** and no champion changes.\n")


if __name__ == "__main__":
    main()
