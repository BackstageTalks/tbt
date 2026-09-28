"""Value audit contracts: immutable issuance, fair-market gaps, no invented bets."""
from copy import deepcopy
from datetime import datetime, timezone

from audit_market_reliability import analyze

NOW = datetime(2026, 9, 27, 14, tzinfo=timezone.utc)
ISSUED = "2026-09-26T08:00:00+00:00"
SCHEDULED = "2026-09-26T15:00:00+00:00"


def value(event, public, raw, fair, odds, surfaces, correct, *, exact=True):
    publication = {
        "publication_key": f"value:{event}", "section": "value",
        "market": "match_winner", "selection_id": "p1",
        "selection": "Selected", "publication_status": "published",
        "issued_at": ISSUED, "model_probability": raw,
        "odds": odds, "expected_value": raw * odds - 1,
        "fair_implied_probability": fair,
        "result": {"correct": correct, "scheduled_at": SCHEDULED,
                   "status": "void" if correct is None else "settled"},
    }
    if exact:
        publication["issued_snapshot"] = {
            "source": "deployed_feed_at_issuance",
            "captured_at": ISSUED, "model_probability": raw,
            "blinq_probability": public, "model_version": "test-v1",
            "data_depth": .84,
            "quality": {
                "player1": {"surface_matches": surfaces[0]},
                "player2": {"surface_matches": surfaces[1]},
            },
        }
    return {
        "event_id": event, "winner_id": "p1", "scheduled_at": SCHEDULED,
        "tour": "ITF", "raw_model_confidence": raw,
        "blinq_probability": public, "data_depth": .84,
        "player1": {"id": "p1", "name": "Selected"},
        "player2": {"id": "p2", "name": "Opponent"},
        "market_publications": [publication],
    }


def test_value_shadow_cohorts_are_only_actual_issued_exacts():
    high_gap_loss = value("a", .73, .78, .55, 1.80, (4, 7), False)
    low_conf_win = value("b", .62, .67, .55, 1.80, (6, 6), True)
    combined_win = value("c", .65, .71, .54, 1.80, (7, 6), True)
    void = value("d", .66, .70, .55, 1.80, (7, 7), None)
    legacy = value("e", .61, .65, .55, 1.80, (6, 6), False, exact=False)
    ledger = [high_gap_loss, low_conf_win, combined_win, void, legacy]

    # Another legacy publication key for the same actual bet must not double count.
    duplicate = deepcopy(high_gap_loss)
    duplicate["market_publications"][0]["publication_key"] = "value:migrated-a"
    ledger.append(duplicate)

    audit = analyze(ledger, now=NOW, window_days=7)
    va = audit["value_audit"]
    assert audit["sections"]["value"]["overall"]["published"] == 5
    assert audit["sections"]["value"]["overall"]["settled"] == 4
    assert va["exact_issue_snapshots"] == 4
    assert va["comparable_published"] == 4
    assert va["comparable_settled"] == 3
    assert va["diagnostic_flags"]["no_vig_market_gap_15pp_plus"] == 1
    assert va["diagnostic_flags"]["exact_surface_history_below_5"] == 1
    assert va["diagnostic_flags"]["missing_exact_issued_evidence"] == 1
    shadows = va["shadow_on_same_issued_population"]
    assert shadows["exact_evidence_baseline"]["settled"] == 3
    assert shadows["surface_5_each"]["settled"] == 2
    assert shadows["public_probability_65_plus"]["settled"] == 2
    assert shadows["no_vig_gap_under_15pp"]["settled"] == 2
    assert shadows["combined_65_surface5_gap15"]["settled"] == 1
    assert shadows["combined_65_surface5_gap15"]["wins"] == 1
    assert shadows["combined_65_surface5_gap15"]["small_sample"] is True
    assert va["recent_losses"][0]["event_id"] in {"a", "e"}
    assert len(va["recent_losses"]) == 2
    assert audit["diagnostics"]["duplicate_semantic_publication"] == 1


def test_value_no_fair_side_no_quality_never_fabricated_for_shadows():
    missing_fair = value("no-fair", .66, .70, .55, 1.8, (8, 8), False)
    missing_fair["market_publications"][0].pop("fair_implied_probability")
    missing_quality = value("no-quality", .71, .73, .54, 1.8, (8, 8), True)
    missing_quality["market_publications"][0]["issued_snapshot"]["quality"] = None
    mismatched = value("wrong-snapshot", .75, .80, .55, 1.8, (8, 8), False)
    mismatched["market_publications"][0]["issued_snapshot"]["captured_at"] = "2026-09-26T09:00:00+00:00"
    late = value("late", .66, .72, .55, 1.8, (8, 8), True)
    late["market_publications"][0]["issued_at"] = SCHEDULED
    report = analyze([missing_fair, missing_quality, mismatched, late], now=NOW)
    va = report["value_audit"]
    assert report["sections"]["value"]["overall"]["published"] == 3
    assert va["comparable_published"] == 0
    assert va["diagnostic_flags"]["missing_two_sided_fair_probability"] == 1
    assert va["diagnostic_flags"]["missing_exact_issued_evidence"] == 1
    assert va["by_surface_samples_at_issue"]["unknown"]["published"] == 2
    assert va["shadow_on_same_issued_population"]["exact_evidence_baseline"]["yield_flat_stake"] is None


def test_value_raw_ev_vs_public_ev_flags_only_with_preserved_snapshot():
    # Historical edge case: a legacy Value offer using a weaker displayed
    # probability. An audit flag is not itself grounds to rewrite history.
    row = value("historical", .55, .65, .54, 1.80, (9, 9), False)
    report = analyze([row], now=NOW)
    flags = report["value_audit"]["diagnostic_flags"]
    assert flags["raw_ev_positive_public_ev_nonpositive"] == 1
    loss = report["value_audit"]["recent_losses"][0]
    assert loss["public_expected_value"] < 0
    assert loss["recorded_raw_expected_value"] > 0
