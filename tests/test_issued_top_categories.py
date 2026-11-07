"""Synthetic tests: issued ledger (NOT candidate) settlement and category integrity."""
from audit_issued_top_categories import audit, category


def entry(event="e1", *, section="top_daily", quote=1.65, correct=True,
          winner="a", level="ITF M15", tour="ATP", issued=True,
          captured="2026-11-06T12:59:00+00:00"):
    publication = {
        "section": section, "market": "match_winner", "selection_id": "a",
        "odds": quote, "captured_at": captured,
        "issued_at": "2026-11-06T13:00:00+00:00" if issued else None,
        "publication_status": "published" if issued else "pending",
        "issued_snapshot": {"model_version": "v7.2.1",
                            "blinq_probability": .84, "data_depth": .91},
        "result": {"correct": correct, "winner_id": winner},
    }
    return {
        "event_id": event, "winner_id": "a", "tour": tour,
        "scheduled_at": "2026-11-06T14:00:00+00:00",
        "competition": level, "tournament": "Original Frozen Tournament",
        "player1": {"id": "a"}, "player2": {"id": "b"},
        "market_publications": [publication],
    }


def finished(event="e1", *, winner="a", tour="ATP"):
    return {
        "match_id": event, "player1_id": "a", "player2_id": "b",
        "winner_id": winner, "status": "finished", "tour": tour,
        "scheduled_at": "2026-11-06T14:00:00+00:00",
        "provider_context_json": {},
    }


def test_actual_issued_top_not_all_candidates_and_no_future_odds():
    ledger = [
        entry("w1", quote=1.7, correct=True),
        entry("l1", quote=1.8, correct=False, winner="b", level="ITF M25"),
        entry("unissued", issued=False, level="ATP250"),
    ]
    results = [finished("w1"), finished("l1", winner="b"), finished("unissued")]
    report = audit(ledger, results)
    score = report["pit_quote_proven"]["overall"]
    assert score == {"n": 2, "wins": 1, "losses": 1, "hit_rate": .5,
                     "profit_1u": -.3, "roi_1u": -.15}
    groups = report["canonical_verified"]["by_category"]
    assert groups["ITF_M15"]["wins"] == 1
    assert groups["ITF_M25"]["losses"] == 1
    assert "ATP_MAIN" not in groups
    assert report["rejected_or_unverified_counts_nonexclusive"]["not_issued"] == 1


def test_canonical_grade_conflict_quarantined():
    mismatch = entry("fraud", correct=True, winner="a")
    observed = finished("fraud", winner="b")
    report = audit([mismatch], [observed])
    assert report["canonical_verified"]["overall"]["n"] == 0
    assert report["rejected_or_unverified_counts_nonexclusive"]["settlement_conflict"] == 1


def test_missing_quote_capture_never_claims_verified_prestart_price():
    x = entry("legacy", captured=None)
    report = audit([x], [finished("legacy")])
    assert report["canonical_verified"]["overall"]["n"] == 1
    assert report["pit_quote_proven"]["overall"]["n"] == 0
    assert report["rejected_or_unverified_counts_nonexclusive"]["no_verified_price_timestamp"] == 1


def test_poststart_capture_never_passes_price_proven():
    x = entry("late", captured="2026-11-06T14:01:00+00:00")
    report = audit([x], [finished("late")])
    assert report["canonical_verified"]["overall"]["n"] == 1
    assert report["pit_quote_proven"]["overall"]["n"] == 0


def test_duplicate_same_event_not_double_counted_and_conflict_quarantined():
    first = entry()
    same = entry()
    report = audit([first, same], [finished()])
    assert report["canonical_verified"]["overall"]["n"] == 1
    assert report["rejected_or_unverified_counts_nonexclusive"]["semantic_duplicate"] == 1
    conflict = entry()
    conflict["market_publications"][0]["odds"] = 2.2
    report = audit([first, conflict], [finished()])
    assert report["canonical_verified"]["overall"]["n"] == 0
    assert report["rejected_or_unverified_counts_nonexclusive"]["duplicate_conflict"] == 1
    after_conflict = audit([first, conflict, entry()], [finished()])
    assert after_conflict["canonical_verified"]["overall"]["n"] == 0
    assert after_conflict["rejected_or_unverified_counts_nonexclusive"]["conflicting_key_additional_record"] == 1


def test_unknown_main_tour_never_inferred_from_atp_only():
    x = entry(level="ATP", tour="ATP")
    assert category(x) == "UNKNOWN"
    x["competition"] = "ATP 250"
    assert category(x) == "ATP_MAIN"
    x["competition"] = "WTA 125"
    x["tour"] = "WTA"
    assert category(x) == "WTA125"
    x["competition"] = "ITF W35"
    assert category(x) == "ITF_W35"


def test_issued_after_start_is_not_a_published_top_grade():
    x = entry()
    x["market_publications"][0]["issued_at"] = "2026-11-06T13:59:59+00:00"
    result = audit([x], [finished()])
    assert result["canonical_verified"]["overall"]["n"] == 0
    assert result["rejected_or_unverified_counts_nonexclusive"]["issued_inside_15_min_cutoff"] == 1


def test_ambiguous_provider_player_id_is_never_scored_as_correct():
    x = entry()
    mismatched = finished()
    mismatched["player2_id"] = "other"
    result = audit([x], [mismatched])
    assert result["canonical_verified"]["overall"]["n"] == 0
    assert result["rejected_or_unverified_counts_nonexclusive"]["canonical_player_conflict"] == 1
