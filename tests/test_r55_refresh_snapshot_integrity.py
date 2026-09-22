from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_projection_integrity_runs_before_daily_snapshot_carry_forward():
    source = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    restore = source.index("feed = restore_published_market_snapshots(feed, records)")
    integrity = source.index("integrity = _projection_presentation_integrity")
    carry = source.index("feed, daily_snapshot_report = carry_forward_betting_day_market_rows")
    final_validate = source.index("validate_market_publication_candidate(feed, records)", carry)

    assert restore < integrity < carry < final_validate
