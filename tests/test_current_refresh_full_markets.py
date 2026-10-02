from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")


def test_current_refresh_keeps_full_market_discovery():
    assert "projection_odds_cap = 0" not in PIPELINE
    assert "current_refresh_match_winner_priority" not in PIPELINE
    assert "if prop_key and args.propline_max_events:" in PIPELINE
    assert "if args.doubles_odds_max_events and doubles_predictions:" in PIPELINE


def test_current_refresh_merges_recent_completed_matches_in_memory():
    assert '"canonical_history": "read_only"' in PIPELINE
    assert '"recent_completed_refreshed_in_memory": recent_completed' in PIPELINE
    assert "reused_plus_recent_in_memory" in PIPELINE


def test_ace_df_settlement_statistics_are_targeted_before_new_market_discovery():
    assert "def _pending_ace_df_settlement_requirements(ledger):" in PIPELINE
    assert "provider.event_statistics(provider_event_id)" in PIPELINE
    assert '"ace_df_settlement_statistics": ace_df_settlement_stats_report' in PIPELINE
    call = "ace_df_settlement_stats_report = _enrich_pending_ace_df_settlement_stats("
    assert call in PIPELINE
    assert PIPELINE.index(call) < PIPELINE.index("projection_odds_cap = max(")
    assert "market not in {\"aces\", \"double_faults\"}" in PIPELINE
