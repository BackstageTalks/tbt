"""Independently validate each recovered TennisApi native ID against published CDB.

The guarded history collector must already have acquired/released the CDB lock.
This script has no writer capability and makes zero provider requests.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile


def verify_rows(rows, expected):
    from tbt.services.statistics_gapfill import event_id
    seen = set()
    native_claims = set()
    for match in rows:
        mid = str(match.match_id)
        if mid not in expected:
            continue
        if mid in seen:
            raise ValueError("Repeated canonical match ID during identity readback")
        seen.add(mid)
        proof = expected[mid]
        payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        witness = payload.get("_tbt_event_identity")
        if (not isinstance(witness, dict) or witness.get("status") != "finished"
                or payload.get("_tbt_provider_event_id") != proof["event_id"]
                or event_id(match) != proof["event_id"]
                or {str(witness.get("home")), str(witness.get("away"))}
                   != {proof["home"], proof["away"]}
                or {str(match.player1_id), str(match.player2_id)}
                   != {proof["home"], proof["away"]}
                or str(match.winner_id) not in {proof["home"], proof["away"]}
                or str(match.tour).lower() != proof["tour"]
                or match.scheduled_at.year != proof["year"]):
            raise ValueError("Persisted provider identity differs from verified proposal")
        if (match.stats or {}) != proof["stats_before"]:
            raise ValueError("Native identity repair unexpectedly changed historical statistics")
        claim = (proof["tour"], proof["event_id"])
        if claim in native_claims:
            raise ValueError("Provider native event is claimed by multiple canonical matches")
        native_claims.add(claim)
    return seen


def main():
    from _bootstrap import ROOT  # noqa: F401
    from tbt.data.history_snapshot import load_snapshot
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", required=True)
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    args = ap.parse_args()
    local = Path(args.history_dir)
    expected = json.loads((local / "identity_expected.json").read_text())
    collection = json.loads((local / "download_report.json").read_text())
    proposals = expected["recovered"]
    years = expected["years"]
    if (expected.get("schema") != 1 or len(proposals) !=
            collection["identity_backfill"]["recovered_native_event_ids"] or
            sorted({int(v["year"]) for v in proposals.values()}) != years):
        raise ValueError("Identity collector report is inconsistent with proposed links")
    proof = {}
    found = set()
    if proposals:
        with tempfile.TemporaryDirectory() as temp:
            remote = Path(temp)
            names = [f"history-{int(y):04d}.parquet" for y in years]
            for name in [*names, "_tbt_bundle_manifest.json"]:
                subprocess.run(["gh", "release", "download", "tbt-data-v1",
                                "--repo", args.data_repository, "--pattern", name,
                                "--dir", str(remote)], check=True, timeout=150)
            manifest = json.loads((remote / "_tbt_bundle_manifest.json").read_text())["files"]
            for name in names:
                digest = sha256((remote / name).read_bytes()).hexdigest()
                if (digest != sha256((local / name).read_bytes()).hexdigest()
                        or digest != manifest[name]["sha256"]):
                    raise ValueError("Remote CDB partition SHA differs from produced history")
                subset = {mid: record for mid, record in proposals.items()
                          if int(record["year"]) == int(name[8:12])}
                observed = verify_rows(load_snapshot(remote / name), subset)
                if observed != set(subset):
                    raise ValueError("Published CDB is missing recovered event identity")
                if found & observed:
                    raise ValueError("Recovered match ID duplicated across CDB partitions")
                found |= observed
                proof[name] = digest
    if found != set(proposals):
        raise ValueError("Recovered identity count differs from remote canonical CDB")
    output = {
        "status": "VERIFIED" if found else "VERIFIED_NO_GAIN",
        "persisted_native_event_ids": len(found),
        "partition_sha256": proof,
        "source": "remote private release SHA and exact event/player IDs",
        "historical_statistics_unchanged": True,
        "cross_provider_guesses": 0,
    }
    (local / "identity_readback.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
