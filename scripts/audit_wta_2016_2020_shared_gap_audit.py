"""Read-only, single-download 2016-2020 WTA canonical-ID and PIT ranking NULL audit.

Reuse the proven 2021-2024 exact-identity audit core and download the source,
crosswalk and complete canonical CDB only once for all years. Never writes CDB.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import audit_wta_2023_2024_verified_rank_gaps as core


YEARS = (2016, 2017, 2018, 2019, 2020)


def two_null_only(report, rows):
    """Safely preserve complete two-null rank stages accepted by guarded writer."""
    eligible = [row for row in rows if set(row.get("add_only_null_fields") or ()) ==
                {"player1_rank", "player2_rank"} and
                row.get("expected_player1_rank") is None and
                row.get("expected_player2_rank") is None]
    excluded = len(rows) - len(eligible)
    counts = report["counts"]
    counts["unfiltered_audit_candidate_matches"] = counts.get("candidate_matches", 0)
    counts["unfiltered_audit_candidate_cells"] = counts.get("candidate_rank_cells", 0)
    counts["candidate_matches"] = len(eligible)
    counts["candidate_rank_cells"] = 2 * len(eligible)
    report["quarantined"]["partial_null_not_stageable_by_strict_writer"] = excluded
    report["stage_policy"] = "complete_two_null_ranks_only__no_existing_rank_changed"
    if excluded < 0 or counts["candidate_matches"] != len(eligible):
        raise ValueError("WTA candidate filter inconsistent")
    return eligible


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for piece in iter(lambda: f.read(1024*1024), b""):
            h.update(piece)
    return h.hexdigest()


def main():
    from _bootstrap import ROOT  # noqa: F401
    from release_store import ReleaseStore
    from rank_feature_inputs import load_rank_feature_inputs
    from tbt.data.history_snapshot import load_manifest, load_partitions
    from tbt.data.history_safety import sanitize_history_identities
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default="BackstageTalks/tbt-data")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    history = args.out / "history"
    ReleaseStore(args.repo, "tbt-data-v1", history).download(require_bundle_manifest=True)
    matches, safety = sanitize_history_identities(load_partitions(history))
    if safety.get("quarantined_rows") or len(matches) < 994101:
        raise ValueError("Canonical full release incomplete or identity unsafe")
    ranking = load_rank_feature_inputs(args.repo, args.out/"rank-inputs", matches)
    manifest = load_manifest(history)["years"]
    source_sha = {key: value["sha256"] for key, value in ranking.report["sources"].items()}
    overview = []
    for year in YEARS:
        entry = manifest[str(year)]
        partition = history / f"history-{year}.parquet"
        year_sha = sha(partition)
        if entry.get("sha256") != year_sha:
            raise ValueError(f"Year {year} manifest SHA mismatch")
        core.YEAR = year
        report, candidates = core.audit_rows(matches, ranking.wta, year_sha, source_sha)
        stage = two_null_only(report, candidates)
        report["canonical_rows"] = len(matches)
        report["wta_crosswalk"] = ranking.report["wta_crosswalk"]
        report["shared_download_multi_year"] = True
        report["canonical_mutated"] = False
        report["write_authorized"] = False
        report["provider_api_requests"] = 0
        report["model_trained"] = False
        folder = args.out / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        stagefile = folder / f"wta{year}-rank-null-candidates.jsonl.gz"
        with stagefile.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as z:
                for row in stage:
                    z.write((json.dumps(row, sort_keys=True, ensure_ascii=False)+"\n").encode())
        report["stage_sha256"] = sha(stagefile)
        (folder/"report.json").write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
        overview.append({"year":year, "counts":report["counts"],
                         "quarantined":report["quarantined"],
                         "canonical_year_sha256":year_sha,
                         "stage_sha256":report["stage_sha256"]})
    (args.out/"overview.json").write_text(json.dumps(overview, indent=2, sort_keys=True)+"\n")
    print("WTA_2016_2020_SHARED_DOWNLOAD_READONLY", json.dumps(overview, sort_keys=True))


if __name__ == "__main__":
    main()
