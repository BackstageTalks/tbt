from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_atp_rank_history_request_is_safe_dry_run():
    request = json.loads((ROOT / ".github/atp-rank-history-request.json").read_text())
    assert request["mode"] == "dry-run"
    assert request["rapidapi_requests"] == 0
    assert request["production_mutated"] is False
    assert request["rank_points_policy"] == "sidecar_only_until_candidate_ablation"


def test_atp_rank_audit_has_conservative_point_in_time_policy():
    script = (ROOT / "scripts/audit_atp_weekly_rank_history.py").read_text()
    assert "bisect.bisect_right" in script
    assert "if weeks[idx] == match_day" in script
    assert '"strict_fill_candidate"' in script
    assert '"rapidapi_requests": 0' in script
    assert "rank-points-sidecar.jsonl" in script


def test_atp_rank_importer_never_overwrites_disagreeing_rank():
    script = (ROOT / "scripts/import_atp_weekly_rank_fill.py").read_text()
    assert 'counts["existing_rank_mismatch"]' in script
    assert "source_week.date() >= scheduled.date()" in script
    assert 'counts["stale_snapshot_rejected"]' in script
    assert '"_tbt_rank_provenance"' in script
    assert '"point_in_time": True' in script


def test_atp_rank_workflow_is_manual_or_pr_only():
    workflow = (ROOT / ".github/workflows/atp-rank-history.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
    assert "  schedule:" not in workflow
    assert "upload_bundle" not in workflow
    assert "audit_atp_weekly_rank_history.py" in workflow
