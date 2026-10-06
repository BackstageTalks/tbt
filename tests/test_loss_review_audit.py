from datetime import datetime, timezone

from audit_loss_review import analyze_loss_review, evaluate_rule


NOW = datetime(2026, 10, 6, 7, 0, tzinfo=timezone.utc)


def _entry(correct, **overrides):
    row = {
        "correct": correct,
        "odds": 1.80,
        "probability": .74,
        "probability_market_gap": .10,
        "public_expected_value": .20,
        "data_depth": .95,
        "exact_issue_snapshot": True,
        "min_surface_matches_at_issue": 8,
        "same_event_primary_count": 1,
        "section": "top_daily",
        "competition": "ATP",
    }
    row.update(overrides)
    return row


def test_rule_reports_losses_prevented_and_wins_sacrificed():
    entries = [
        _entry(False, probability=.60),
        _entry(False, probability=.64),
        _entry(True, probability=.66),
        _entry(True, probability=.78),
        _entry(True, probability=.82),
    ]
    report = evaluate_rule(
        entries,
        "confidence_68",
        "Require 68%",
        lambda e: e["probability"] is not None and e["probability"] >= .68,
    )
    assert report["prevented_losses"] == 2
    assert report["sacrificed_wins"] == 1
    assert report["net_bad_removed"] == 1
    assert report["removed_picks"] == 3


def test_shadow_rule_never_changes_original_population():
    entries = [_entry(False), _entry(True), _entry(True)]
    original = [dict(e) for e in entries]
    evaluate_rule(entries, "noop", "Keep all", lambda _e: True)
    assert entries == original


def test_loss_review_uses_only_settled_pre_match_primary_publications():
    issued = "2026-10-04T08:00:00+00:00"
    scheduled = "2026-10-05T12:00:00+00:00"
    pub = {
        "publication_key": "top:e1",
        "section": "top_daily",
        "market": "match_winner",
        "selection_id": "a",
        "selection": "Alpha",
        "issued_at": issued,
        "publication_status": "published",
        "model_probability": .74,
        "odds": 1.80,
        "fair_implied_probability": .64,
        "result": {"correct": False, "scheduled_at": scheduled},
        "issued_snapshot": {
            "source": "deployed_feed_at_issuance",
            "captured_at": issued,
            "model_probability": .74,
            "blinq_probability": .72,
            "data_depth": .93,
            "model_version": "v-test",
            "quality": {
                "player1": {"surface_matches": 12},
                "player2": {"surface_matches": 9},
            },
        },
    }
    row = {
        "event_id": "e1",
        "scheduled_at": scheduled,
        "winner_id": "a",
        "tour": "ATP",
        "competition": "ATP",
        "player1": {"id": "a", "name": "Alpha"},
        "player2": {"id": "b", "name": "Beta"},
        "market_publications": [pub],
    }
    report = analyze_loss_review([row], now=NOW, window_days=10)
    assert report["overall"]["settled"] == 1
    assert report["overall"]["losses"] == 1
    assert report["losses"][0]["event_id"] == "e1"
    assert report["losses"][0]["exact_issue_snapshot"] is True
    assert report["losses"][0]["min_surface_matches_at_issue"] == 9


def test_late_and_unsettled_rows_are_excluded():
    issued = "2026-10-05T12:00:00+00:00"
    scheduled = "2026-10-05T12:00:00+00:00"
    row = {
        "event_id": "late",
        "scheduled_at": scheduled,
        "winner_id": "a",
        "tour": "ATP",
        "player1": {"id": "a", "name": "Alpha"},
        "player2": {"id": "b", "name": "Beta"},
        "market_publications": [{
            "publication_key": "top:late",
            "section": "top_daily",
            "market": "match_winner",
            "selection_id": "a",
            "issued_at": issued,
            "publication_status": "published",
            "model_probability": .80,
            "odds": 1.5,
            "result": {"correct": False, "scheduled_at": scheduled},
        }],
    }
    report = analyze_loss_review([row], now=NOW, window_days=10)
    assert report["overall"]["settled"] == 0
    assert report["diagnostics"]["excluded_or_late"] == 1
