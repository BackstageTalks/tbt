from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_wta_rank_audit_is_read_only_and_pinned():
    request=json.loads((ROOT/".github/wta-rank-gapfill-request.json").read_text())
    assert request["mode"] == "dry-run"
    assert request["expected_sha256"] == "cedbf748e111e1f14317a09f561f267bc4861e60dbbafa5500f2826c6d5a4c72"
    assert request["zero_provider_api_requests"] is True
    assert request["production_mutated"] is False

    workflow=(ROOT/".github/workflows/wta-rank-gapfill.yml").read_text()
    assert "audit_offline_wta_rank_points.py" in workflow
    assert "upload_bundle" in workflow
    assert "  schedule:" not in workflow
    assert "research/rank_points/wta-rank-points-2006-2026.jsonl.gz" in workflow


def test_wta_rank_audit_stages_only_safe_exact_day_missing_ranks():
    script=(ROOT/"scripts/audit_offline_wta_rank_points.py").read_text()
    assert 'counts["canonical_both_rank_missing"]' in script
    assert 'counts["strict_fill_candidate"]' in script
    assert 'counts["strict_fill_candidate_one_missing"]' in script
    assert "present_rank_matches" in script
    assert "if exact_day:" in script
    assert "rank-fill-candidates.jsonl" in script
    assert "canonical_rank1=None" in script
    assert "canonical_rank2=None" in script


def test_wta_rank_importer_preserves_point_in_time_provenance_contract():
    script=(ROOT/"scripts/import_offline_wta_rank_fill.py").read_text()
    assert '"point_in_time": True' in script
    assert '"_tbt_rank_provenance"' in script
    assert "source_date.date() != scheduled.date()" in script
    assert 'counts["existing_rank_mismatch"]' in script
    assert 'counts["player1_rank_filled"]' in script
    assert 'counts["player2_rank_filled"]' in script
