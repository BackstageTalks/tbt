from build_launch_gate import build


def test_launch_gate_allows_projection_launch_without_set2_odds():
    mega = {
        "history_audit": {"invalid_rows": 0, "duplicate_match_id_groups": 0, "duplicate_provider_event_id_groups": 0, "total_rows": 100},
        "sg_summary": {"target_players": 10, "players_ready": 9, "target_samples": 24},
        "ace_summary": {"target_players": 10, "players_ready": 8, "target_samples": 18},
        "provider_live_probe": {"live_events": 3, "live_odds_samples": [{"event_id": "1", "second_set_rows": []}]},
    }
    report = build(mega, {"status": "ready_with_warnings"}, sample_gate=0.8)
    assert report["status"] == "ready_with_warnings"
    assert report["sets_games"]["publication_mode"] == "model_projection"
    assert report["esa"]["publication_mode"] == "model_projection"
    assert report["live_set2"]["value_mode"] == "projection_only"


def test_launch_gate_blocks_dirty_history_or_weak_samples():
    mega = {
        "history_audit": {"invalid_rows": 1, "duplicate_match_id_groups": 0, "duplicate_provider_event_id_groups": 0},
        "sg_summary": {"target_players": 10, "players_ready": 5},
        "ace_summary": {"target_players": 10, "players_ready": 10},
        "provider_live_probe": {"live_events": 0, "live_odds_samples": []},
    }
    report = build(mega, {}, sample_gate=0.8)
    assert report["status"] == "blocked"
    assert "history_integrity_not_clean_or_missing" in report["blockers"]
    assert "sets_games_sample_gate_not_met" in report["blockers"]
