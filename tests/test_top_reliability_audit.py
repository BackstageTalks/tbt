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
