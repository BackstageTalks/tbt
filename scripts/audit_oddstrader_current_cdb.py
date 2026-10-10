"""Independent, read-only current canonical audit for historic OddsTrader markers.

Full private ReleaseStore bundle digest check occurs before running this script.
An audit is not a fresh source-to-cell linker and never confers write permission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest

YEARS = tuple(range(2015, 2027))
FIELDS = ("_tbt_market_history", "_tbt_match_winner_odds")
PRIOR_VERIFIED_MARKERS = {"_tbt_market_history": 11935, "_tbt_match_winner_odds": 283}
PRIOR_RUN_ID = "37906147697"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_markers(ids: pd.Series, contexts: pd.Series) -> dict[str, int]:
    if len(ids) != len(contexts):
        raise ValueError("Mismatched canonical IDs and contexts")
    if ids.isna().any() or ids.astype(str).eq("").any() or ids.astype(str).duplicated().any():
        raise ValueError("Missing or duplicate canonical match IDs")
    counts = Counter()
    for mid, raw in zip(ids, contexts):
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            context = {}
        elif isinstance(raw, str):
            try:
                context = json.loads(raw)
            except (TypeError, ValueError) as e:
                raise ValueError("Malformed JSON canonical context for match: " + str(mid)) from e
        else:
            raise ValueError("Unexpected canonical context type for match: " + str(mid))
        if not isinstance(context, dict):
            raise ValueError("Canonical context is not object for match: " + str(mid))
        for field in FIELDS:
            if field in context and context[field] is not None:
                counts[field] += 1
        counts["checked"] += 1
    return dict(counts)


def audit(history_dir: Path, report: Path, minimum_previous: bool = True) -> dict:
    manifest = load_manifest(history_dir)
    year_meta = manifest.get("years") or {}
    totals = Counter()
    by_year = {}
    for year in YEARS:
        file = history_dir / f"history-{year}.parquet"
        meta = year_meta.get(str(year)) or {}
        if not file.is_file() or meta.get("asset") != file.name:
            raise ValueError("Missing canonical year partition: " + str(year))
        digest = sha256(file)
        if meta.get("sha256") != digest:
            raise ValueError("Canonical year digest disagrees with pinned manifest: " + str(year))
        frame = pd.read_parquet(file, engine="pyarrow",
                                columns=["match_id", "provider_context_json"])
        if int(meta.get("rows", -1)) != len(frame):
            raise ValueError("Canonical year row-count mismatch: " + str(year))
        counts = count_markers(frame["match_id"], frame["provider_context_json"])
        totals.update(counts)
        by_year[str(year)] = {
            "rows": len(frame),
            "sha256": digest,
            "market_markers": counts.get(FIELDS[0], 0),
            "match_winner_markers": counts.get(FIELDS[1], 0),
            "release_asset": file.name,
        }
    regressions = {
        field: {"previous": floor, "current": totals[field]}
        for field, floor in PRIOR_VERIFIED_MARKERS.items()
        if totals[field] < floor
    }
    result = {
        "schema": 1,
        "status": ("BLOCKED_PRIOR_MARKERS_NOT_PRESENT" if regressions
                   else "VERIFIED_CURRENT_CDB_MARKERS_READ_ONLY"),
        "previous_verified_import_run": PRIOR_RUN_ID,
        "previous_import_report": "audit/oddstrader-current-canonical-37906147697.json",
        "affected_years": list(YEARS),
        "prior_verified_marker_floor": PRIOR_VERIFIED_MARKERS,
        "current_markers": {field: totals[field] for field in FIELDS},
        "canonical_rows_checked": totals["checked"],
        "year_partitions": by_year,
        "regressions": regressions,
        "no_open_or_close_time_inferred": True,
        "current_source_to_cell_net_new_delta": None,
        "current_source_to_cell_full_overlap_proven": False,
        "verified_source_rights_and_quote_time_for_CLV": False,
        "production_cdb_mutated": False,
        "provider_api_requests": 0,
        "model_training_performed": False,
        "model_promoted": False,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if minimum_previous and regressions:
        raise ValueError("Historical independently verified market markers regressed: " + str(regressions))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(audit(a.history_dir, a.report), sort_keys=True))


if __name__ == "__main__":
    main()
