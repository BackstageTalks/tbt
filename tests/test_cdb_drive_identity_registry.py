"""Fail-closed contract for private Drive source-ID candidate registry."""
import csv
import hashlib
import json

import pytest

from scripts.cdb_drive_identity_registry import build


def fixture(tmp_path):
    raw = tmp_path / "input" / "atp_matches.csv"
    raw.parent.mkdir()
    raw.write_bytes(b"Original source bytes")
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    normalized = tmp_path / "source" / "normalized" / ("atp_" + sha[:16] + "_0.csv")
    normalized.parent.mkdir(parents=True)
    with normalized.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "league", "winner_name", "loser_name", "source_winner_id", "source_loser_id"
        ])
        writer.writeheader()
        writer.writerow({"league": "atp", "winner_name": "Alpha One",
                         "loser_name": "Beta Two", "source_winner_id": "foreign-1",
                         "source_loser_id": "foreign-2"})
        writer.writerow({"league": "atp", "winner_name": "Alpha One",
                         "loser_name": "Gamma Three", "source_winner_id": "foreign-1",
                         "source_loser_id": "foreign-3"})
    report = tmp_path / "source" / "report.json"
    report.write_text(json.dumps({
        "schema": 1, "state": "SOURCE_ONLY", "production_mutated": False,
        "api_requests": 0,
        "normalized": [{"path": str(normalized), "tour": "atp", "source_sha256": sha}]
    }))
    stage = tmp_path / "stage"
    (stage / "link").mkdir(parents=True)
    (stage / "report.json").write_text(json.dumps({
        "schema": 1, "state": "READ_ONLY_STAGE",
        "production_mutated": False, "api_requests": 0
    }))
    (stage / "eligible.jsonl").write_text("")
    manifest = tmp_path / "drive_manifest.json"
    manifest.write_text(json.dumps({
        "schema": 2, "state": "DRIVE_SOURCE_FETCH_ONLY", "production_mutated": False,
        "files": [{"status": "fetched", "id": "drive-1",
                   "sha256": sha, "local_file": str(raw)}]
    }))
    return raw, sha, normalized, report, stage, manifest


def linked(ref, a="foreign-1", b="foreign-2",
           cid_a="canonical-A", cid_b="canonical-B", mid="match-1"):
    return {
        "match_id": mid,
        "canonical": {"player1_id": cid_a, "player2_id": cid_b},
        "sources": [{
            "source": ref, "source_player_a_id": a, "source_player_b_id": b,
            "source_id_namespace": "drive-unverified",
            "mapping": {"a": "p1", "b": "p2"},
            "evidence": ["winner", "tournament_exact", "surface"]
        }]
    }


def test_conflicting_candidate_ids_are_quarantined_and_nothing_verified(tmp_path):
    _, sha, normalized, report, stage, manifest = fixture(tmp_path)
    ref = "sackmann:" + normalized.name
    (stage / "link" / "auto_linked.jsonl").write_text(
        json.dumps(linked(ref)) + "\n" +
        json.dumps(linked(ref, b="foreign-3", cid_a="DIFFERENT",
                          cid_b="canonical-C", mid="match-2")) + "\n"
    )
    result = build(report, stage, manifest, tmp_path / "private-review.json")
    assert result["source_ids_count"] == 3
    assert result["candidate_match_count"] == 2
    assert result["canonical_write_authorized"] is False
    assert result["crosswalk_promotion_authorized"] is False
    ids = {x["source_player_id"]: x for x in result["players"]}
    assert ids["foreign-1"]["status"] == "QUARANTINE_CONFLICTING_CANONICAL_CANDIDATES"
    assert ids["foreign-2"]["status"] == "METADATA_CANDIDATE_NOT_INDEPENDENTLY_VERIFIED"
    assert ids["foreign-2"]["candidate_canonical_player_ids"] == ["canonical-B"]
    assert ids["foreign-3"]["source_id_namespace"] == "drive-file-sha256:" + sha
    assert all(x["independently_verified"] is False and
               x["write_authorized"] is False for x in result["players"])


def test_namespace_mismatch_and_raw_source_tampering_fail_closed(tmp_path):
    raw, _, normalized, report, stage, manifest = fixture(tmp_path)
    item = linked("sackmann:" + normalized.name)
    item["sources"][0]["source_id_namespace"] = "sackmann"
    (stage / "link" / "auto_linked.jsonl").write_text(json.dumps(item) + "\n")
    with pytest.raises(ValueError, match="wrong namespace"):
        build(report, stage, manifest, tmp_path / "out.json")
    (stage / "link" / "auto_linked.jsonl").write_text("")
    raw.write_bytes(b"Tampered raw bytes")
    with pytest.raises(ValueError, match="raw Drive provenance"):
        build(report, stage, manifest, tmp_path / "out.json")
