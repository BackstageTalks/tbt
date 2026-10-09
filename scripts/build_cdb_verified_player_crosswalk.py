"""Create an independently verified CDB identity crosswalk, never rewrite raw matches.

Requires a single-writer workflow. Official ATP IDs are corroborated against a
CC0 identity registry, exactly one provider full name, and the latest
checksum-verified canonical history. Ambiguous pairs are quarantined. The
result is a governed identity sidecar, not an activated model feature.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from audit_cdb_external_registry import DIRECTORY, registry, audit, normalize_player_name
from audit_cdb_identity_reconciliation import FIELDS, YEARS, release_download, match_token, evaluate_pair
import pandas as pd

REPO = "BackstageTalks/tbt-data"
SOURCE_TAG = "tbt-data-v1"
TARGET_TAG = "tbt-canonical-identity-links-v1"
OUTPUT = Path(".cache/tbt/player-identity-publish")


def build(directory: dict, registry_rows: list, observations: dict, names: dict):
    candidates = audit(directory, registry_rows)["candidates"]
    verified = []
    conflicts = []
    reasons = Counter()
    owners = defaultdict(set)
    for row in candidates:
        owners[(row["tour"], row["to_id"])].add(row["wikidata_qid"])
    for row in sorted(candidates, key=lambda p: (p["tour"], p["from_id"])):
        src = (row["tour"], row["from_id"])
        dst = (row["tour"], row["to_id"])
        src_matches = observations.get(src, [])
        dst_matches = observations.get(dst, [])
        src_names = names.get(src, set())
        dst_names = names.get(dst, set())
        canonical = normalize_player_name(row["name"])
        check = evaluate_pair(src_matches, dst_matches)
        reason = ""
        if len(owners[dst]) != 1:
            reason = "conflicting_external_identity_target"
        elif not src_matches or not dst_matches:
            reason = "missing_current_cdb_player_evidence"
        elif any(name != canonical for name in src_names | dst_names):
            reason = "inconsistent_canonical_source_player_name"
        elif check["conflict"]:
            reason = "canonical_event_overlap_conflict"
        if reason:
            reasons[reason] += 1
            conflicts.append({
                "from_id": row["from_id"], "to_id": row["to_id"],
                "name": row["name"], "reason": reason,
                "source_matches": len(src_matches), "target_matches": len(dst_matches),
                "collision_count": check["conflict"]
            })
            continue
        verified.append({
            "schema": 1, "tour": row["tour"],
            "source_player_id": row["from_id"], "canonical_player_id": row["to_id"],
            "canonical_name": row["name"], "wikidata_qid": row["wikidata_qid"],
            "atp_tour_id": row["verified_atp_tour_id"],
            "source": "BlinQ verified CDB plus Wikidata CC0",
            "evidence": "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb",
            "evidence_date": "2026-10-09",
            "source_matches_seen_2017_2026": len(src_matches),
            "target_matches_seen_2017_2026": len(dst_matches),
            "matching_event_duplicates_to_exclude": check["duplicate_event_pairs"],
            "model_changed": False,
            "raw_history_rewritten": False,
        })
        reasons["accepted"] += 1
    keys = [(r["tour"], r["source_player_id"]) for r in verified]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Non-deterministic player source key")
    return verified, conflicts, {"candidate_count": len(candidates), **dict(reasons)}


def load_canonical_observations(wanted):
    observations = defaultdict(list)
    names = defaultdict(set)
    partition_meta = {}
    with tempfile.TemporaryDirectory(prefix="blinq-identity-verified-history-") as root:
        folder = Path(root)
        manifest_file = release_download("history_manifest.json", folder)
        bundle_file = release_download("_tbt_bundle_manifest.json", folder)
        manifest_bytes = manifest_file.read_bytes()
        bundle_bytes = bundle_file.read_bytes()
        manifest = json.loads(manifest_bytes)
        bundle = json.loads(bundle_bytes)
        for year in YEARS:
            metadata = (manifest.get("years") or {}).get(str(year))
            if not isinstance(metadata, dict):
                raise RuntimeError("Missing canonical year " + str(year))
            asset = str(metadata.get("asset") or f"history-{year}.parquet")
            expected = ((bundle.get("files") or {}).get(asset) or {}).get("sha256")
            if not expected or len(expected) != 64:
                raise RuntimeError("Missing immutable canonical asset digest " + asset)
            file = release_download(asset, folder)
            actual = sha256(file.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError("Canonical checksum mismatch " + asset)
            frame = pd.read_parquet(file, columns=list(FIELDS))
            partition_meta[str(year)] = {"sha256": actual, "rows": len(frame)}
            for fields in frame.itertuples(index=False, name=None):
                row = dict(zip(FIELDS, fields))
                tour = str(row.get("tour") or "").lower()
                if tour != "atp":
                    continue
                left, right = str(row.get("player1_id")), str(row.get("player2_id"))
                for pid, name in ((left, row.get("player1_name")), (right, row.get("player2_name"))):
                    key = tour, pid
                    if key not in wanted:
                        continue
                    names[key].add(normalize_player_name(name))
                    tok = match_token(row, pid)
                    if tok is not None:
                        observations[key].append(tok)
            file.unlink()
        return observations, names, partition_meta, {
            "manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "bundle_manifest_sha256": sha256(bundle_bytes).hexdigest(),
        }


def main():
    if not DIRECTORY.is_file():
        raise SystemExit("Verified canonical serving directory not available")
    source_bytes = DIRECTORY.read_bytes()
    directory = json.loads(source_bytes)
    if len(directory.get("players") or []) < 25000:
        raise SystemExit("Comparator directory unexpectedly short")
    external, evidence = registry()
    candidates = audit(directory, external)["candidates"]
    wanted = {
        (row["tour"], id_)
        for row in candidates for id_ in (row["from_id"], row["to_id"])
    }
    observations, names, partitions, manifests = load_canonical_observations(wanted)
    safe, quarantined, counts = build(directory, external, observations, names)
    if len(candidates) < 200:
        raise RuntimeError("Source registry candidate coverage unexpectedly low")
    if not safe:
        raise RuntimeError("No safe crosswalk entries after current CDB read")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sidecar = OUTPUT / "player-identity-crosswalk.jsonl"
    with sidecar.open("w", encoding="utf-8") as file:
        for row in safe:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema": 1, "state": "ready_for_persistence",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_cdb_modified": False, "model_changed": False,
        "cdb_tag": SOURCE_TAG, "crosswalk_tag": TARGET_TAG,
        "comparator_directory_sha256": sha256(source_bytes).hexdigest(),
        "registry_source": evidence, "canonical_source": manifests,
        "verified_years": partitions,
        "counts": counts, "crosswalk_rows": len(safe),
        "quarantined": quarantined[:250], "quarantined_total": len(quarantined),
        "sidecar_sha256": sha256(sidecar.read_bytes()).hexdigest(),
    }
    (OUTPUT / "crosswalk-integrity-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("CDB_VERIFIED_IDENTITY_CROSSWALK " + json.dumps({
        "rows": len(safe), "counts": counts, "quarantine_count": len(quarantined),
        "bublik": [row for row in safe if "bublik" in normalize_player_name(row["canonical_name"])],
        "source_bundle": manifests["bundle_manifest_sha256"],
        "sidecar_sha256": report["sidecar_sha256"]
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
