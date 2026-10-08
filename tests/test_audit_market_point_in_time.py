"""Regression tests for the read-only market timestamp audit."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_market_point_in_time.py"
spec = importlib.util.spec_from_file_location("market_pit_audit", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample(**overrides):
    row = {"event_id": "match-1", "scheduled_at": "2026-01-03T15:00:00Z",
           "observed_at": "2026-01-03T10:00:00Z", "market": "moneyline"}
    row.update(overrides)
    return row


def test_valid_moneyline_research_only():
    assert module.eligibility(sample()) == "eligible_research_only"


def test_missing_or_naive_timestamp_rejected():
    assert module.eligibility(sample(observed_at=None)) == "reject_unverified_timestamp"
    assert module.eligibility(sample(observed_at="2026-01-03T10:00:00")) == "reject_unverified_timestamp"


def test_after_start_rejected():
    assert module.eligibility(sample(observed_at="2026-01-03T15:00:00Z")) == "reject_not_prematch"


def test_missing_identity_rejected():
    assert module.eligibility(sample(event_id="")) == "reject_missing_identity"


def test_totals_line_needs_own_timestamp():
    assert module.eligibility(sample(market="totals", line=22.5)) == "reject_unverified_line_timestamp"
    assert module.eligibility(sample(market="totals", line=22.5, line_observed_at="2026-01-03T15:01:00Z")) == "reject_line_not_prematch"
    assert module.eligibility(sample(market="totals", line=22.5, line_observed_at="2026-01-03T09:00:00Z")) == "eligible_research_only"


def test_invalid_json_is_quarantined(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{broken json}\n', encoding="utf-8")
    result = module.audit(path)
    assert result["counts"]["reject_invalid_json"] == 1
    assert result["canonical_writes"] == 0
    assert result["production_eligible"] is False
