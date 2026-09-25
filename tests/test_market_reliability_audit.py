"""Offline, synthetic contracts for the market quality audit."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from audit_market_reliability import analyze, _betting_day


NOW = datetime(2026, 9, 25, 23, tzinfo=timezone.utc)
ISSUED = "2026-09-24T08:00:00+00:00"
SCHEDULED = "2026-09-25T12:00:00+00:00"


def item(event, section, *, probability=.82, adjusted=.80, odds=1.5,
         fair=.66, correct=True, market="match_winner", result_status=None):
    pub = {
        "publication_key": f"{section}:{event}:{market}", "section": section,
        "market": market, "selection_id": "a", "selection": "Alpha",
        "issued_at": ISSUED, "publication_status": "published",
        "model_probability": probability, "odds": odds,
        "fair_implied_probability": fair, "betting_day": "2026-09-24",
        "result": {"correct": correct, "scheduled_at": SCHEDULED},
    }
    if result_status is not None:
        pub["result"]["status"] = result_status
    row = {
        "event_id": event, "scheduled_at": SCHEDULED, "winner_id": "a",
        "tour": "ATP", "competition": "ATP", "model_version": "old",
        "raw_model_confidence": probability, "blinq_probability": adjusted,
        "data_depth": .9,
        "player1": {"id": "a", "name": "Alpha"},
        "player2": {"id": "b", "name": "Beta"},
        "market_publications": [pub],
    }
    return row


def test_three_separate_sections_no_short_odds_roi_or_reconstructed_bets():
    top = item("t1", "top_daily", correct=False, probability=.84, adjusted=.82)
    value = item("v1", "value", correct=True, probability=.67, adjusted=.65, odds=1.90, fair=.54)
    doubles = item("d1", "doubles", correct=True, probability=.64, odds=1.80, fair=.55)
    prime = item("p1", "prime", correct=True, probability=.95, odds=1.04)
    report = analyze([top, value, doubles, prime], now=NOW)
    assert report["selection_scope"] == ["top_daily", "value", "doubles"]
    assert report["sections"]["top_daily"]["overall"]["losses"] == 1
    assert report["sections"]["value"]["overall"]["wins"] == 1
    assert report["sections"]["doubles"]["overall"]["wins"] == 1
    assert abs(report["sections"]["value"]["overall"]["yield_flat_stake"] - .9) < 1e-12
    assert abs(report["sections"]["top_daily"]["overall"]["yield_flat_stake"] + 1) < 1e-12
    assert report["sections"]["top_daily"]["overall"]["calibration_n"] == 1
    assert report["sections"]["doubles"]["overall"]["calibration_n"] == 1
    assert report["sections"]["doubles"]["by_model_version"] == {"unverified": report["sections"]["doubles"]["overall"]}
    assert report["same_event_exposure"]["events_with_multiple_non_short_odds_publications"] == 0


def test_same_match_exposure_includes_sets_and_games_but_not_short_odds():
    top = item("shared", "top_daily", correct=False)
    top["market_publications"].append({
        "publication_key": "sets:shared", "section": "sets",
        "market": "sets", "selection_id": "sets:under:2.5",
        "issued_at": ISSUED, "publication_status": "published",
        "result": {"status": "miss", "correct": False, "scheduled_at": SCHEDULED},
    })
    top["market_publications"].append({
        "publication_key": "games:shared", "section": "games",
        "market": "games", "selection_id": "games:high",
        "issued_at": ISSUED, "publication_status": "published",
        "result": {"status": "hit", "correct": True, "scheduled_at": SCHEDULED},
    })
    top["market_publications"].append({
        "publication_key": "prime:shared", "section": "prime",
        "market": "match_winner", "selection_id": "a", "odds": 1.05,
        "issued_at": ISSUED, "publication_status": "published",
        "result": {"correct": False, "scheduled_at": SCHEDULED},
    })
    report = analyze([top], now=NOW)
    exposure = report["same_event_exposure"]
    assert exposure["events_with_multiple_non_short_odds_publications"] == 1
    assert exposure["events_with_top_and_other_market"] == 1
    example = exposure["examples"][0]
    assert example["published_sections"] == ["games", "sets", "top_daily"]
    assert example["both_loss_pairs"] == 1
    assert report["sections"]["top_daily"]["overall"]["settled"] == 1
    assert report["sections"]["value"]["overall"]["settled"] == 0


def test_exact_published_snapshot_survives_changed_first_prediction():
    row = item("snapshot", "top_daily", probability=.73, adjusted=.69, correct=False)
    pub = row["market_publications"][0]
    pub["model_probability"] = .87
    pub["issued_snapshot"] = {
        "source": "deployed_feed_at_issuance",
        "captured_at": ISSUED, "model_probability": .87,
        "blinq_probability": .84, "model_version": "new",
        "data_depth": .83,
    }
    report = analyze([row], now=NOW)
    top = report["sections"]["top_daily"]
    assert top["overall"]["calibration_n"] == 1
    assert abs(top["overall"]["mean_confidence"] - .84) < 1e-12
    assert top["by_model_version"]["new"]["losses"] == 1
    assert top["by_data_depth"]["080_090"]["losses"] == 1
    assert report["high_confidence_top_losses"]["total"] == 1
    assert report["probability_market_discrepancies"]["total"] == 1
    assert top["exact_probability_snapshots"] == 1


def test_missing_snapshots_and_bad_odds_fail_conservatively():
    row = item("legacy", "top_daily", probability=.88, adjusted=.84, correct=False)
    pub = row["market_publications"][0]
    pub["model_probability"] = .72
    pub["odds"] = None
    report = analyze([row], now=NOW)
    overall = report["sections"]["top_daily"]["overall"]
    assert overall["settled"] == 1
    assert overall["priced"] == 0
    assert overall["yield_flat_stake"] is None
    assert overall["calibration_n"] == 0
    assert report["high_confidence_top_losses"]["total"] == 0
    assert report["sections"]["top_daily"]["by_model_version"]["unverified"]["losses"] == 1
    assert report["diagnostics"]["confidence_unavailable"] == 1
    assert report["diagnostics"]["primary_missing_real_odds"] == 1


def test_semantic_dedupe_void_late_unsettled_and_daily_boundaries():
    first = item("one", "top_daily")
    duplicate = deepcopy(first)
    duplicate["market_publications"][0]["publication_key"] = "legacy:other-schema"
    void = item("void", "value", correct=None, result_status="void")
    pending = item("pending", "doubles")
    pending["market_publications"][0]["result"] = None
    late = item("late", "top_daily")
    late["market_publications"][0]["issued_at"] = SCHEDULED
    report = analyze([first, duplicate, void, pending, late], now=NOW)
    assert report["diagnostics"]["duplicate_semantic_publication"] == 1
    assert report["diagnostics"]["excluded_or_late"] == 1
    assert report["sections"]["top_daily"]["overall"]["published"] == 1
    assert report["sections"]["value"]["overall"]["void_or_unsettled"] == 1
    assert report["sections"]["doubles"]["overall"]["void_or_unsettled"] == 1
    assert _betting_day(datetime(2026, 9, 25, 3, 59, tzinfo=timezone.utc)) == "2026-09-24"
    assert _betting_day(datetime(2026, 9, 25, 4, 0, tzinfo=timezone.utc)) == "2026-09-25"


def test_older_than_window_and_missing_evidence_do_not_become_zero_bet_days():
    old = item("old", "top_daily")
    old["scheduled_at"] = (NOW - timedelta(days=120)).isoformat()
    old["market_publications"][0]["result"]["scheduled_at"] = old["scheduled_at"]
    report = analyze([old], now=NOW)
    assert report["sections"]["top_daily"]["overall"]["published"] == 0
    assert report["sections"]["top_daily"]["active_days"] == 0
    assert report["sections"]["top_daily"]["mean_published_per_active_day"] is None
