from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_wta_rank_audit_is_read_only_and_pinned():
    request=json.loads((ROOT/".github/wta-rank-gapfill-request.json").read_text())
    assert request["mode"] == "audit"
    assert request["expected_sha256"] == "cedbf748e111e1f14317a09f561f267bc4861e60dbbafa5500f2826c6d5a4c72"
    assert request["zero_provider_api_requests"] is True
    assert request["production_mutated"] is False

    workflow=(ROOT/".github/workflows/wta-rank-gapfill.yml").read_text()
    assert "audit_offline_wta_rank_points.py" in workflow
    assert "write_year_partition" not in workflow
    assert "upload_bundle" not in workflow
    assert "  schedule:" not in workflow
    assert "research/rank_points/wta-rank-points-2006-2026.jsonl.gz" in workflow


def test_wta_rank_audit_only_stages_exact_day_both_missing_pairs():
    script=(ROOT/"scripts/audit_offline_wta_rank_points.py").read_text()
    assert 'counts["canonical_both_rank_missing"]' in script
    assert 'counts["strict_fill_candidate"]' in script
    assert "if exact_day:" in script
    assert "rank-fill-candidates.jsonl" in script
    assert "canonical_rank1=None" in script
    assert "canonical_rank2=None" in script
