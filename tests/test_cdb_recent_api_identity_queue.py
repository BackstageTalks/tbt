"""Private review queue: research candidates never become CDB-ready."""
from __future__ import annotations

import hashlib
import json

import pytest

from scripts.cdb_recent_api_identity_queue import build


def _case(tmp_path, *, duplicate=False, provenance="sackmann:atp_stats.csv"):
    link, stage, private = tmp_path / "link", tmp_path / "stage", tmp_path / "private"
    link.mkdir()
    stage.mkdir()
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "normalized": [{
            "path": "work/source/atp_stats.csv", "tour": "atp",
            "source_sha256": "b" * 64,
        }]
    }))
    (link / "report.json").write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "matching_strategy": "verified_ids",
    }))
    (stage / "report.json").write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "license_review_required": True,
        "eligible_matches": 0,
    }))
    (stage / "eligible.jsonl").write_text("")
    (link / "quarantine.jsonl").write_text("")
    row = {
        "match_id": "secret-canonical-id",
        "canonical": {"tour": "atp", "scheduled_date_utc": "2026-10-17"},
        "incoming_stats": {"p1_aces": 6, "p2_service_points_won": 0.64},
        "sources": [{"source": provenance,
                     "evidence": ["date_exact", "winner", "tournament_exact"]}],
    }
    rows = [row, row] if duplicate else [row]
    (link / "auto_linked.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    return link, source, stage, private


def test_private_source_only_api_review_queue_never_authorizes_import(tmp_path):
    link, source, stage, private = _case(tmp_path)
    report = build(link, source, stage, private)
    assert report["queued_unique_canonical_candidates"] == 1
    assert report["candidate_stat_fields_to_verify"] == 2
    assert report["api_requests"] == 0
    assert report["write_authorized"] is False
    assert report["canonical_matches_confirmed"] == 0
    payload = (private / "api-identity-review.jsonl").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == report["private_queue_sha256"]
    row = json.loads(payload)
    assert row["canonical_match_id"] == "secret-canonical-id"
    assert row["source_provenance"][0]["source_sha256"] == "b" * 64
    assert row["source_reuse_rights_verified"] is False
    assert row["cdb_import_ready"] is False
    assert row["provider_api_requests_made"] == 0
    public = (private / "aggregate-only.json").read_text()
    assert "secret-canonical-id" not in public
    assert "atp_stats.csv" not in public
    assert "b" * 64 not in public


def test_exclude_conflicted_and_already_eligible_candidates(tmp_path):
    link, source, stage, private = _case(tmp_path)
    (link / "quarantine.jsonl").write_text(json.dumps({"match_id": "secret-canonical-id"}) + "\n")
    report = build(link, source, stage, private)
    assert report["queued_unique_canonical_candidates"] == 0
    assert report["reason_counts"] == {"canonical_conflict_quarantined": 1}

    (link / "quarantine.jsonl").write_text("")
    (stage / "eligible.jsonl").write_text(json.dumps({"match_id": "secret-canonical-id"}) + "\n")
    (stage / "report.json").write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "license_review_required": True, "eligible_matches": 1,
    }))
    report = build(link, source, stage, tmp_path / "eligible-case")
    assert report["reason_counts"] == {"already_strictly_eligible": 1}
    assert report["queued_unique_canonical_candidates"] == 0


def test_unverified_provenance_duplicate_or_bad_contract_fails_closed(tmp_path):
    link, source, stage, private = _case(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="Duplicate/missing"):
        build(link, source, stage, private)
    (link / "auto_linked.jsonl").write_text(
        (link / "auto_linked.jsonl").read_text().splitlines()[0] + "\n")
    row = json.loads((link / "auto_linked.jsonl").read_text())
    row["sources"][0]["source"] = "sackmann:unverified.csv"
    (link / "auto_linked.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="unaudited source"):
        build(link, source, stage, tmp_path / "bad-source")
    row["sources"][0]["source"] = "sackmann:atp_stats.csv"
    (link / "auto_linked.jsonl").write_text(json.dumps(row) + "\n")
    (link / "report.json").write_text(json.dumps({
        "production_mutated": True, "api_requests": 0,
        "matching_strategy": "verified_ids",
    }))
    with pytest.raises(ValueError, match="strictly read-only"):
        build(link, source, stage, tmp_path / "mutated")


def test_refuses_public_overwrite_and_invalid_statistics(tmp_path):
    link, source, stage, private = _case(tmp_path)
    private.mkdir()
    (private / "old.jsonl").write_text("untouched")
    with pytest.raises(ValueError, match="must be empty"):
        build(link, source, stage, private)
    assert (private / "old.jsonl").read_text() == "untouched"
    row = json.loads((link / "auto_linked.jsonl").read_text())
    row["incoming_stats"]["p1_aces"] = float("nan")
    (link / "auto_linked.jsonl").write_text(
        json.dumps(row, allow_nan=True) + "\n")
    report = build(link, source, stage, tmp_path / "invalid-stats")
    assert report["queued_unique_canonical_candidates"] == 0
    assert report["reason_counts"]["missing_or_invalid_candidate_stats"] == 1
