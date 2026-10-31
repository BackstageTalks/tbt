"""Read-only TOP reliability audit contracts; no private data or provider required."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from audit_top_reliability import analyze, confidence, model_freshness


NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def fixture(event, *, section="top_daily", result=True, odds=1.60, adjusted=.82,
            raw=.88, level="atp", pick_rank=250, rival_rank=500, stats=True):
    scheduled = (NOW - timedelta(days=2)).isoformat()
    issued = (NOW - timedelta(days=3)).isoformat()
    pub = {
        "publication_key": event, "section": section, "market": "match_winner",
        "selection_id": "a", "issued_at": issued, "publication_status": "published",
        "model_probability": raw, "odds": odds,
        "result": {"correct": result, "scheduled_at": scheduled},
    }
    return {
        "event_id": event, "tour": "atp", "competition": level,
        "scheduled_at": scheduled, "winner_id": "a", "raw_model_confidence": raw,
        "blinq_probability": adjusted, "data_depth": 1.0,
        "stats_available": stats,
        "player1": {"id": "a", "rank": pick_rank},
        "player2": {"id": "b", "rank": rival_rank},
        "quality": {"player1": {"surface_matches": 12},
                    "player2": {"surface_matches": 9}},
        "market_publications": [pub],
    }


def test_exact_published_top_only_and_segment_calibration():
    win = fixture("win")
    loss = fixture("loss", result=False, odds=1.50, adjusted=.80, level="challenger",
                   pick_rank=1100, rival_rank=1350, stats=False)
    void = fixture("void", result=None, level="itf", stats=False)
    void["market_publications"][0]["result"]["status"] = "void"
    wrong_section = fixture("prime", section="prime")
    late = fixture("late")
    late["market_publications"][0]["issued_at"] = NOW.isoformat()
    old = fixture("old")
    old["scheduled_at"] = (NOW - timedelta(days=100)).isoformat()
    old["market_publications"][0]["result"]["scheduled_at"] = old["scheduled_at"]
    copy = deepcopy(win)
    audit = analyze([win, loss, void, wrong_section, late, old, copy], now=NOW)
    assert audit["overall"]["published"] == 3
    assert audit["overall"]["settled"] == 2
    assert audit["overall"]["wins"] == 1
    assert audit["overall"]["losses"] == 1
    assert audit["overall"]["void_or_unsettled"] == 1
    assert audit["overall"]["average_odds"] == 1.55
    assert abs(audit["overall"]["yield_flat_stake"] + .20) < 1e-12
    assert audit["overall"]["calibration_n"] == 2
    assert abs(audit["overall"]["mean_confidence"] - .81) < 1e-12
    assert set(audit["subgroups"]["competition"]) == {"ATP", "Challenger", "ITF"}
    assert audit["subgroups"]["ranking"]["both_800_plus"]["losses"] == 1
    assert audit["subgroups"]["ranking_500"]["both_500_plus"]["losses"] == 1
    assert audit["subgroups"]["ranking_1000"]["both_1000_plus"]["losses"] == 1
    assert audit["subgroups"]["picked_rank"]["pick_1000_plus"]["losses"] == 1
    assert audit["subgroups"]["stats"]["yes"]["wins"] == 1
    assert audit["diagnostics"]["duplicate_publication_skipped"] == 1
    assert audit["diagnostics"]["invalid_or_excluded_publication"] == 1
    assert audit["overall"]["small_sample"] is True


def test_calibration_does_not_invent_confidence_when_publication_model_changed():
    row = fixture("newer", adjusted=.83, raw=.90)
    pub = row["market_publications"][0]
    pub["model_probability"] = .75
    assert confidence(row, pub) is None
    audit = analyze([row], now=NOW)
    assert audit["overall"]["settled"] == 1
    assert audit["overall"]["calibration_n"] == 0
    assert audit["diagnostics"]["confidence_not_reconstructable"] == 1


def test_ranking_unknown_is_separate_not_grouped_with_800_plus():
    row = fixture("unknown", pick_rank=None)
    audit = analyze([row], now=NOW)
    assert "rank_unknown" in audit["subgroups"]["ranking"]
    assert "both_800_plus" not in audit["subgroups"]["ranking"]


def test_model_history_gap_and_backfill_limit():
    train = {"data": {"end": "2026-09-06T00:00:00+00:00"},
             "rank_provenance": {"stripped_rows": 120}}
    history = {"generated_at": "2026-09-25T12:00:00Z", "years": {
        "2026": {"history_end": "2026-09-24T08:00:00Z"}}}
    report = model_freshness(train, history)
    assert report["history_ahead_of_training"] is True
    assert report["rank_provenance"]["stripped_rows"] == 120
    assert "backfilled" in report["warning"]


def test_no_missing_training_date_claim():
    report = model_freshness({"data": {}}, {"years": {}})
    assert report["history_ahead_of_training"] is None


def test_ranking_cohorts_do_not_exclude_outside_top_1000():
    matches = [
        fixture("both500", pick_rank=250, rival_rank=420, stats=True),
        fixture("pick500", pick_rank=490, rival_rank=1250, result=False, stats=False),
        fixture("pick800", pick_rank=800, rival_rank=1100, stats=True),
        fixture("rival600", pick_rank=1100, rival_rank=600, stats=False),
        fixture("bothoutside", pick_rank=1400, rival_rank=1600, result=False),
        fixture("missing", pick_rank=None, rival_rank=200),
    ]
    report = analyze(matches, now=NOW)
    assert report["overall"]["settled"] == 6
    assert report["subgroups"]["ranking_500"]["both_top_500"]["settled"] == 1
    assert report["subgroups"]["ranking_500"]["pick_top_500_opponent_500_plus"]["settled"] == 1
    assert report["subgroups"]["ranking_500"]["both_500_plus"]["settled"] == 3
    assert report["subgroups"]["ranking_1000"]["both_top_1000"]["settled"] == 1
    assert report["subgroups"]["ranking_1000"]["pick_top_1000_opponent_1000_plus"]["settled"] == 2
    assert report["subgroups"]["ranking_1000"]["pick_1000_plus_opponent_top_1000"]["settled"] == 1
    assert report["subgroups"]["ranking_1000"]["both_1000_plus"]["settled"] == 1
    assert report["subgroups"]["picked_rank"]["pick_top_500"]["settled"] == 2
    assert report["subgroups"]["picked_rank"]["pick_501_1000"]["settled"] == 1
    assert report["subgroups"]["picked_rank"]["pick_1000_plus"]["settled"] == 2
    assert report["subgroups"]["picked_rank"]["rank_unknown"]["settled"] == 1
    assert report["subgroups"]["rank_and_stats"]["pick_top_500/no"]["losses"] == 1
    assert report["coverage"]["active_betting_days"] == 1
    assert report["coverage"]["days_with_5_plus_published"] == 1


def test_ranking_audit_reports_active_day_coverage_without_invented_zero_days():
    recent = fixture("recent")
    earlier = fixture("earlier", result=False)
    earlier["scheduled_at"] = (NOW - timedelta(days=5)).isoformat()
    earlier["market_publications"][0]["result"]["scheduled_at"] = earlier["scheduled_at"]
    earlier["market_publications"][0]["issued_at"] = (NOW - timedelta(days=6)).isoformat()
    report = analyze([recent, earlier], now=NOW)
    coverage = report["coverage"]
    assert coverage["active_betting_days"] == 2
    assert coverage["days_with_5_plus_published"] == 0
    assert coverage["days_with_below_5_published"] == 2
    assert coverage["mean_published_per_active_day"] == 1
    assert len(coverage["betting_day_counts"]) == 2
    empty = analyze([], now=NOW)
    assert empty["coverage"]["active_betting_days"] == 0
    assert empty["coverage"]["mean_published_per_active_day"] is None


def test_issuance_snapshot_recovers_calibration_and_ranking_after_model_drift():
    row = fixture("issued", raw=.90, adjusted=.82, pick_rank=50, rival_rank=100)
    pub = row["market_publications"][0]
    pub["model_probability"] = .75  # different from frozen first prediction
    pub["issued_snapshot"] = {
        "schema": 1, "source": "deployed_feed_at_issuance",
        "captured_at": pub["issued_at"], "model_probability": .75,
        "blinq_probability": .71,
        "rank_provenance": "public_card_snapshot_not_verified_historical_rank",
        "ranks": {"player1": {"id": "a", "rank": 820},
                  "player2": {"id": "b", "rank": 1150}},
        "stats_available": False,
        "quality": {"player1": {"surface_matches": 6},
                    "player2": {"surface_matches": 5}},
    }
    audit = analyze([row], now=NOW)
    assert audit["overall"]["calibration_n"] == 1
    assert abs(audit["overall"]["mean_confidence"] - .71) < 1e-12
    assert audit["subgroups"]["picked_rank"]["pick_501_1000"]["wins"] == 1
    assert audit["subgroups"]["ranking_1000"]["pick_top_1000_opponent_1000_plus"]["wins"] == 1
    assert audit["subgroups"]["stats"]["no"]["wins"] == 1
    assert audit["subgroups"]["surface_evidence"]["both_5_plus"]["wins"] == 1
    assert audit["diagnostics"]["exact_issued_evidence"] == 1
    assert audit["diagnostics"]["issued_rank_available"] == 1


def test_issuance_snapshot_refuses_rewritten_or_mismatched_public_evidence():
    row = fixture("changed")
    pub = row["market_publications"][0]
    pub["issued_snapshot"] = {
        "source": "deployed_feed_at_issuance", "captured_at": NOW.isoformat(),
        "model_probability": .88, "blinq_probability": .99,
        "ranks": {"player1": {"id": "a", "rank": 1},
                  "player2": {"id": "b", "rank": 2}},
    }
    audit = analyze([row], now=NOW)
    assert audit["diagnostics"].get("exact_issued_evidence", 0) == 0
    assert abs(audit["overall"]["mean_confidence"] - .82) < 1e-12
    assert audit["subgroups"]["picked_rank"]["pick_top_500"]["wins"] == 1


def _with_confirmed_model_quote(row, version="v7.2.1-test"):
    """Real two-way bookmaker and model version frozen before issuance."""
    row = deepcopy(row)
    pub = row["market_publications"][0]
    issued = datetime.fromisoformat(pub["issued_at"])
    prepared = {
        "schema": 2, "source": "pre_deploy_feed",
        "model_version": version,
        "model_probability": pub["model_probability"],
        "blinq_probability": row["blinq_probability"],
        "players": {"player1": deepcopy(row["player1"]),
                    "player2": deepcopy(row["player2"])},
        "prepared_at": pub["issued_at"],
        "market_captured_at": (issued - timedelta(minutes=5)).isoformat(),
        "two_way_match_winner": {"player1_odds": pub["odds"],
                                "player2_odds": 2.50},
    }
    pub["model_version"] = version
    pub["prepared_snapshot"] = prepared
    pub["issued_snapshot"] = {
        **prepared, "source": "pre_deploy_feed_confirmed",
        "confirmed_at": pub["issued_at"],
    }
    return row


def test_current_model_top_audit_uses_only_exact_binary_version_and_quoted_price():
    current = _with_confirmed_model_quote(fixture("current"))
    previous = _with_confirmed_model_quote(fixture("previous"), "v201-previous")
    absent = fixture("unverified-legacy")
    report = analyze([current, previous, absent], now=NOW, model_version="v7.2.1-test")
    assert report["model_version_scope"] == "v7.2.1-test"
    assert report["overall"]["published"] == 1
    assert report["overall"]["settled"] == 1
    assert report["overall"]["wins"] == 1
    assert report["diagnostics"]["missing_or_other_model_issued_proof"] == 2
    assert report["diagnostics"]["other_model_issued_proof"] == 1
    assert report["diagnostics"]["missing_or_inconsistent_model_issued_proof"] == 1
    assert report["overall"]["average_odds"] == 1.6


def test_pending_publications_count_as_published_without_changing_scores():
    for section in ("top_daily", "value"):
        win = _with_confirmed_model_quote(fixture("win", section=section))
        pending = _with_confirmed_model_quote(fixture("pending", section=section))
        pending["market_publications"][0]["result"] = None
        report = analyze([win, pending], now=NOW, model_version="v7.2.1-test", section=section)
        assert report["overall"]["published"] == 2
        assert report["overall"]["settled"] == 1
        assert report["overall"]["void_or_unsettled"] == 1
        assert report["overall"]["hit_rate"] == 1
        assert report["overall"]["calibration_n"] == 1
        assert report["diagnostics"]["unsettled"] == 1
        assert sum(report["coverage"]["betting_day_counts"].values()) == 2


def test_outside_window_publications_do_not_inflate_model_proof_diagnostics():
    old = fixture("old")
    old["market_publications"][0]["result"]["scheduled_at"] = (NOW - timedelta(days=31)).isoformat()
    future = fixture("future")
    future["market_publications"][0]["result"]["scheduled_at"] = (NOW + timedelta(days=1)).isoformat()
    report = analyze([old, future], now=NOW, window_days=30, model_version="v7.2.1-test")
    assert report["overall"]["published"] == 0
    assert report["diagnostics"].get("missing_or_other_model_issued_proof", 0) == 0

def test_current_model_rejects_forged_price_identity_and_version():
    current = _with_confirmed_model_quote(fixture("current"))
    forged_quote = deepcopy(current)
    forged_quote["market_publications"][0]["odds"] = 1.70
    report = analyze([forged_quote], now=NOW, model_version="v7.2.1-test")
    assert report["overall"]["published"] == 0
    assert report["diagnostics"]["unverified_current_model_selected_price"] == 1

    drifted_player = deepcopy(current)
    drifted_player["player1"]["id"] = "foreign-player"
    report = analyze([drifted_player], now=NOW, model_version="v7.2.1-test")
    assert report["overall"]["published"] == 0
    assert report["diagnostics"]["unverified_current_model_selected_price"] == 1

    forged_version = deepcopy(current)
    forged_version["market_publications"][0]["issued_snapshot"]["model_version"] = "new-label"
    report = analyze([forged_version], now=NOW, model_version="v7.2.1-test")
    assert report["overall"]["published"] == 0
    assert report["diagnostics"]["missing_or_other_model_issued_proof"] == 1


def test_current_model_scope_rejects_blank_version_and_does_not_change_legacy_audit():
    row = fixture("legacy")
    assert analyze([row], now=NOW)["overall"]["published"] == 1
    import pytest
    with pytest.raises(ValueError, match="nonempty"):
        analyze([row], now=NOW, model_version="")
    assert analyze([row], now=NOW, model_version="v7.2.1-test")["overall"]["published"] == 0


def test_value_exact_issued_scope_is_independent_of_top_and_old_versions():
    top = _with_confirmed_model_quote(fixture("top-current"))
    active_value = _with_confirmed_model_quote(
        fixture("value-current", section="value", result=False)
    )
    old_value = _with_confirmed_model_quote(
        fixture("value-legacy", section="value", result=True), "older"
    )
    missing_value = fixture("value-missing", section="value")
    rows = [top, active_value, old_value, missing_value]
    scoped_value = analyze(rows, now=NOW, model_version="v7.2.1-test", section="value")
    scoped_top = analyze(rows, now=NOW, model_version="v7.2.1-test")
    assert scoped_value["section"] == "value"
    assert scoped_value["overall"]["published"] == 1
    assert scoped_value["overall"]["settled"] == 1
    assert scoped_value["overall"]["wins"] == 0
    assert scoped_value["overall"]["losses"] == 1
    assert scoped_value["diagnostics"]["missing_or_other_model_issued_proof"] == 2
    assert scoped_top["section"] == "top_daily"
    assert scoped_top["overall"]["published"] == 1
    assert scoped_top["overall"]["wins"] == 1

    forged_value = deepcopy(active_value)
    forged_value["market_publications"][0]["issued_snapshot"]["two_way_match_winner"]["player1_odds"] = 4.50
    result = analyze([forged_value], now=NOW, model_version="v7.2.1-test", section="value")
    assert result["overall"]["published"] == 0
    assert result["diagnostics"]["unverified_current_model_selected_price"] == 1

    import pytest
    with pytest.raises(ValueError, match="TOP and VALUE"):
        analyze(rows, now=NOW, section="prime")
