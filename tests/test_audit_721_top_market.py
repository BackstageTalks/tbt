"""Synthetic tests of exact-time 7.2.1 TOP market evidence; no real ledger upload."""
from copy import deepcopy

import pytest

from audit_721_top_market import evaluate_721


ISSUED = "2026-10-21T09:00:00Z"
START = "2026-10-21T11:00:00Z"
SNAP = "2026-10-21T08:00:00Z"
PREPARED = "2026-10-21T08:30:00Z"


def frozen_evidence():
    return {"status": "EVALUATED_NOT_DEPLOYED",
            "candidate_remote_readback_verified": True,
            "backup_readback_verified": True,
            "champion_restore_verified": True,
            "champion_version": "v201", "candidate_version": "v7.2.1-v201",
            "candidate_release_tag": "blinq-candidate-frozen-1-1",
            "candidate_sha256": "a"*64}


def issued_row():
    prepared = {"schema": 2, "source": "pre_deploy_feed",
                "prepared_at": PREPARED, "market_captured_at": SNAP,
                "model_probability": .72,
                "two_way_match_winner": {"player1_odds": 1.8, "player2_odds": 2.1}}
    confirmed = {**prepared, "source": "pre_deploy_feed_confirmed",
                 "confirmed_at": ISSUED}
    return {"event_id": "e1", "match_id": "m1", "tour": "ATP",
            "scheduled_at": START,
            "player1": {"id": "p1"}, "player2": {"id": "p2"},
            "market_publications": [{
                "section": "top_daily", "market": "match_winner",
                "selection_id": "p1", "odds": 1.8, "issued_at": ISSUED,
                "model_probability": .72, "prepared_snapshot": prepared,
                "issued_snapshot": confirmed, "publication_status": "published",
                "result": {"status": "settled", "scheduled_at": START, "correct": True}}]}


def shadow():
    return {"event_id": "e1", "match_id": "m1", "tour": "ATP",
            "scheduled_at": START, "captured_at": SNAP,
            "player1_id": "p1", "player2_id": "p2", "status": "settled",
            "target_player1_win": 1, "production_model_version": "v201",
            "challenger_model_version": "v7.2.1-v201",
            "production_player1_probability": .66,
            "challenger_player1_probability": .74}


def test_exact_issued_721_pair_observational_not_promotion():
    from datetime import datetime, timezone
    report = evaluate_721([issued_row()], [shadow()], frozen_evidence(),
                          now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert report["matched_unique"] == 1
    assert report["status"] == "INSUFFICIENT_MATCHED_PUBLISHED_PICKS"
    assert report["groups"]["all"]["probability"]["candidate"]["mean_expected_value"] == pytest.approx(.74 * 1.8 - 1)
    assert report["groups"]["all"]["baseline_same_fixed_picks"]["roi"] == pytest.approx(.8)
    assert report["review_gate"]["ready_for_independent_market_review"] is False
    assert report["production_mutated"] is False and report["provider_requests"] == 0


def test_missing_forward_shadow_yields_no_invented_performance():
    from datetime import datetime, timezone
    result = evaluate_721([issued_row()], [], frozen_evidence(),
                          now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert result["matched_unique"] == 0
    assert result["groups"]["all"]["baseline_same_fixed_picks"]["roi"] is None


def test_wrong_quote_or_late_or_unverified_snapshot_excluded():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    row = issued_row()
    row["market_publications"][0]["odds"] = 2.50
    result = evaluate_721([row], [shadow()], frozen_evidence(), now=now)
    assert result["source_issued"] == 0
    assert result["quote_provenance_exclusions"]["unverified_selected_price"] == 1
    row = issued_row()
    row["market_publications"][0].pop("prepared_snapshot")
    result = evaluate_721([row], [shadow()], frozen_evidence(), now=now)
    assert result["source_issued"] == 0
    row = issued_row()
    row["market_publications"][0]["issued_at"] = "2026-10-21T12:00:00Z"
    result = evaluate_721([row], [shadow()], frozen_evidence(), now=now)
    assert result["matched_unique"] == 0


def test_unverified_candidate_never_counted():
    e = frozen_evidence()
    e["candidate_remote_readback_verified"] = False
    with pytest.raises(ValueError, match="immutable"):
        evaluate_721([issued_row()], [shadow()], e)
