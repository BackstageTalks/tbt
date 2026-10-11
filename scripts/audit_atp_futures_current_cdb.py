"""Strict read-only fresh CDB overlap for SHA-proven operator ATP Futures source.

Results are aggregate-only; no ambiguous IDs are asserted or published.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from _bootstrap import ROOT  # noqa
from audit_atp_futures_source_sha import FOLDER, fetch_private, reconstruct
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_manifest, load_partitions
from tbt.data.history_safety import sanitize_history_identities

REPO = "BackstageTalks/tbt-data"


def summarized(linker, safety, history, original_sha):
    counts = linker.get("counts") or {}
    field_counts = linker.get("staged_field_counts") or {}
    if not isinstance(counts, dict) or not isinstance(field_counts, dict):
        raise ValueError("Link report invalid")
    if linker.get("production_mutated") is not False or linker.get("api_requests") != 0:
        raise ValueError("Linker must be read-only")
    if safety.get("quarantined_rows") or len(history) < 994096:
        raise ValueError("Canonical identity/floor changed")
    if linker.get("canonical_rows") != len(history):
        raise ValueError("Linker used a different canonical input")
    verified_links = int(counts.get("verified_id_linked") or 0)
    name_links = int(counts.get("name_linked") or 0)
    if verified_links < 0 or name_links < 0:
        raise ValueError("Invalid linker identity attribution")
    if verified_links + name_links != int(counts.get("identity_linked") or 0):
        raise ValueError("Incomplete linker identity attribution")
    attested_crosswalk = linker.get("verified_crosswalk_sha256")
    if verified_links and not attested_crosswalk:
        raise ValueError("Claimed verified-ID matches without SHA-pinned crosswalk")
    identity_provenance = (
        "VERIFIED_IDS_PINNED_CROSSWALK" if verified_links
        else "NAME_MATCHED_CANDIDATES_ONLY_NO_VERIFIED_ID_CROSSWALK"
    )
    return {
        "schema": 1, "status": "READ_ONLY_SOURCE_TO_CDB_FIELD_DELTA_NOT_WRITE_APPROVED",
        "source_filename": "blinq_atp_futures_quali_2018_2026.csv",
        "source_sha256": original_sha, "source_license_approved": False,
        "canonical_rows": len(history),
        "canonical_identity_quarantined": safety.get("quarantined_rows"),
        "source_rows_with_stats_compared": linker.get("source_rows"),
        "link_counts": counts,
        "link_staged_field_counts": field_counts,
        "link_staged_fields_total": sum(int(v) for v in field_counts.values()),
        "verified_id_linked_source_rows": verified_links,
        "name_only_linked_source_rows": name_links,
        "verified_player_crosswalk_sha256": attested_crosswalk,
        "identity_provenance": identity_provenance,
        "write_approved_statistic_values": 0,
        "identity_verified_candidate_fields": 0 if not verified_links else None,
        "quality_ready_projected_added": linker.get("quality_ready_projected_added"),
        "matching_strategy": linker.get("matching_strategy"),
        "source_to_current_cdb_write_authorized": False,
        "immutable_backup_created": False,
        "production_cdb_mutated": False, "provider_requests": 0,
        "model_trained": False, "cron_created": False,
        "note": "Link candidates are not ID-verified without a SHA-pinned, independently attested player crosswalk. Source license is uncleared. Zero fields authorized for write; require fresh identity, source-rights, writer lease/backup/CAS/remote proof.",
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True, type=Path)
    args=p.parse_args()
    root=args.out_dir
    root.mkdir(parents=True, exist_ok=True)
    manifest=json.loads(fetch_private(FOLDER + "/manifest.json"))
    original, _=reconstruct(manifest,lambda name:fetch_private(FOLDER+"/"+name))
    source=root/"blinq_atp_futures_quali_2018_2026.csv"
    source.write_bytes(original)
    history=root/"history"
    ReleaseStore(REPO,"tbt-data-v1",history).download(require_bundle_manifest=True)
    matches,safety=sanitize_history_identities(load_partitions(history))
    years=load_manifest(history)["years"]
    if len(years)!=78 or sum(int(v["rows"]) for v in years.values())!=len(matches):
        raise RuntimeError("Incomplete canonical partition manifest")
    linked=root/"linked"
    subprocess.run([sys.executable,"scripts/link_offline_serve_return.py",
                    "--history-dir",str(history),"--source-csv",str(source),
                    "--out-dir",str(linked), "--matching-strategy","verified_ids"],check=True,
                   stdout=subprocess.DEVNULL)
    report=json.loads((linked/"report.json").read_text())
    result=summarized(report,safety,matches,hashlib.sha256(original).hexdigest())
    result["canonical_manifest_sha256"]=hashlib.sha256(
        (history/"history_manifest.json").read_bytes()).hexdigest()
    result["canonical_bundle_sha256"]=hashlib.sha256(
        (history/"_tbt_bundle_manifest.json").read_bytes()).hexdigest()
    (root/"source-cdb-delta-report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    source.unlink()  # no redistribution; no archived raw beyond transient runner
    print("ATP_FUTURES_CURRENT_CDB_READ_ONLY_DELTA",
          json.dumps({"counts":result["link_counts"],
                      "field_counts":result["link_staged_field_counts"],
                      "canonical_rows":result["canonical_rows"],
                      "source_rows_with_stats":result["source_rows_with_stats_compared"],
                      "approved_for_write":False},sort_keys=True))


if __name__ == "__main__":
    main()
