"""06 Nov regression: pre-match extreme market/model contradictions must not be TOP.

Preserve odds sources, model probabilities, the immutable issued ledger, and
ordinary high-confidence TOP candidates.  The same rule must apply to a
new selector decision and to serving an already-issued daily snapshot.
"""
from tbt.services.entitlements import _daily_rows
from copy import deepcopy
from datetime import datetime, timezone

from tbt.services.market_selection import attach_match_winner_market, select_market_sections
from tbt.services.price_integrity import (
    extreme_winner_price_inversion,
    unsubstantiated_high_confidence_winner,
)


def winner(event_id, probability, odds, opponent_odds):
    market = {
        "player1_odds": odds,
        "player2_odds": opponent_odds,
    }
    total = 1 / odds + 1 / opponent_odds
    implied = (1 / odds) / total
    return {
        "event_id": event_id,
        "scheduled_at": "2026-11-06T14:00:00+00:00",
        "tour": "ATP", "surface": "hard",
        "player1": {"id": "p1", "name": event_id, "probability": probability},
        "player2": {"id": "p2", "name": "Opponent", "probability": 1 - probability},
        "winner_id": "p1",
        "confidence": probability,
        "data_depth": 1.0,
        "quality": {
            "player1": {"matches": 50, "surface_matches": 12},
            "player2": {"matches": 50, "surface_matches": 12},
            "surface_known": True,
        },
        "betting": {
            "market": "match_winner", "selection": event_id, "selection_id": "p1",
            "odds": odds, "model_probability": probability,
            "blinq_probability": probability, "fair_implied_probability": implied,
            "edge": probability - implied,
            "expected_value": probability * odds - 1,
            "provider_id": 1, "betting_day": "2026-11-06",
        },
        "match_winner_market": market,
    }


def test_extreme_inversion_detects_safonov_but_keeps_todays_other_top_prices():
    assert extreme_winner_price_inversion(.83, 3.70)
    assert not extreme_winner_price_inversion(.902, 2.18)
    assert not extreme_winner_price_inversion(.765, 1.77)
    assert not extreme_winner_price_inversion(.755, 1.65)
    assert not extreme_winner_price_inversion(.65, 3.70)  # not an odds ceiling
    assert not extreme_winner_price_inversion(float("nan"), 3.70)
    assert not extreme_winner_price_inversion(.83, float("inf"))


def test_selector_quarantines_extreme_inversion_without_filling_fake_top():
    rows = [winner("Safonov", .83, 3.70, 1.26),
            winner("Van Herck", .902, 2.18, 1.50),
            winner("Nakashima", .765, 1.77, 1.70),
            winner("Sahtali", .755, 1.65, 1.90)]
    sections = select_market_sections(rows)
    ids = {x["event_id"] for x in sections["top_daily_picks"]}
    assert "Safonov" not in ids
    assert "Van Herck" in ids
    assert sections["market_selection"]["selection_counts"]["extreme_price_inversion_quarantined"] == 1
    # The new integrity check never edits or reprices the caller's raw rows.
    assert rows[0]["betting"]["odds"] == 3.70
    assert rows[0]["betting"]["blinq_probability"] == .83


def test_existing_issued_daily_snapshot_is_non_actionable_if_extreme():
    entries = [winner("Safonov", .83, 3.70, 1.26),
               winner("Van Herck", .902, 2.18, 1.50),
               winner("Nakashima", .765, 1.77, 1.70),
               winner("Sahtali", .755, 1.65, 1.90)]
    snapshot = {"top_daily_picks": entries, "value_picks": [],
                "market_selection": {"top_daily_rule": {
                    "core_min_probability": .8, "fallback_only_if_core_count_below": 3,
                }}}
    offered = _daily_rows(snapshot)
    assert [x["event_id"] for x in offered] == ["Van Herck", "Nakashima", "Sahtali"]
    assert len(snapshot["top_daily_picks"]) == 4  # no mutation of issued evidence


def test_post_start_price_is_non_actionable_in_selector_and_issued_board():
    before = winner("Before", .83, 1.75, 2.10)
    late = winner("Late", .83, 1.75, 2.10)
    before["betting"]["captured_at"] = "2026-11-06T13:59:00+00:00"
    before["match_winner_market"]["captured_at"] = before["betting"]["captured_at"]
    late["betting"]["captured_at"] = "2026-11-06T14:01:00+00:00"
    late["match_winner_market"]["captured_at"] = late["betting"]["captured_at"]

    rows = [before, late]
    sections = select_market_sections(rows)
    assert [card["event_id"] for card in sections["top_daily_picks"]] == ["Before"]
    assert sections["market_selection"]["selection_counts"]["post_start_quote_quarantined"] == 1

    # The published snapshot remains immutable; only actionable serving differs.
    issued = {"top_daily_picks": rows, "value_picks": []}
    assert [card["event_id"] for card in _daily_rows(issued)] == ["Before"]
    assert len(issued["top_daily_picks"]) == 2
    assert late["betting"]["odds"] == 1.75


def test_invalid_explicit_quote_timestamp_fails_closed_without_repricing():
    row = winner("Unverified", .83, 1.75, 2.10)
    row["betting"]["captured_at"] = "not-a-timestamp"
    sections = select_market_sections([row])
    assert sections["top_daily_picks"] == []
    assert sections["market_selection"]["selection_counts"]["post_start_quote_quarantined"] == 1


def test_selected_local_quote_capture_wins_over_later_provider_market_refresh():
    # Do not subordinate the user's selected local quote to an unrelated
    # later provider refresh when judging whether that chosen bet was pre-start.
    local = winner("LocalPrestart", .83, 1.75, 2.10)
    local["betting"]["captured_at"] = "2026-11-06T13:55:00+00:00"
    local["match_winner_market"]["captured_at"] = "2026-11-06T14:02:00+00:00"
    selected = select_market_sections([local])
    assert [pick["event_id"] for pick in selected["top_daily_picks"]] == ["LocalPrestart"]
    assert selected["market_selection"]["selection_counts"]["post_start_quote_quarantined"] == 0



def test_severe_price_conflict_with_missing_frozen_rank_evidence_requires_review():
    # Frozen 6 Nov counterexample: 90.2% at 2.18 (44.3 percentage-point gap)
    # with *both* ranks absent at prediction time. The >50pp guard misses it.
    base = winner("Van Herck", .902, 2.18, 1.50)
    base["player1"]["rank"] = None
    base["player2"]["rank"] = None
    total = 1 / 2.18 + 1 / 1.50
    market = {
        "player1_odds": 2.18, "player2_odds": 1.50,
        "player1_implied_probability": (1 / 2.18) / total,
        "player2_implied_probability": (1 / 1.50) / total,
    }
    priced = attach_match_winner_market(
        base, market, captured_at=datetime(2026, 11, 6, 13, 59, tzinfo=timezone.utc)
    )
    assert priced["betting"]["model_time_ranks"] == {"player1": None, "player2": None}
    assert priced["betting"]["odds"] == 2.18
    assert not extreme_winner_price_inversion(.902, 2.18)
    assert unsubstantiated_high_confidence_winner(priced)
    before = deepcopy(priced)
    picks = select_market_sections([priced])
    assert picks["top_daily_picks"] == []
    assert picks["market_selection"]["selection_counts"]["market_conflict_missing_rank_quarantined"] == 1
    assert priced == before  # no mutation or repricing

    # Presentation may add a rank later; only the model-time frozen evidence
    # may authorize this selection, not the post-model feed enrichment.
    shown = deepcopy(priced)
    shown["player1"]["rank"], shown["player2"]["rank"] = 10, 12
    assert unsubstantiated_high_confidence_winner(shown)
    assert _daily_rows({"top_daily_picks": [shown], "value_picks": []}) == []


def test_review_guard_preserves_ordinary_top_and_any_rank_evidence():
    normal = winner("Normal", .83, 1.75, 2.10)
    ranked = winner("Ranked", .902, 2.18, 1.50)
    weak = winner("Weak", .76, 2.18, 1.50)
    for row in (normal, ranked, weak):
        row["betting"]["model_time_ranks"] = {"player1": None, "player2": None}
    ranked["betting"]["model_time_ranks"]["player1"] = 120
    assert not any(unsubstantiated_high_confidence_winner(r) for r in (normal, ranked, weak))
    cards = select_market_sections([normal, ranked, weak])
    assert {r["event_id"] for r in cards["top_daily_picks"]} == {
        "Normal", "Ranked", "Weak",
    }
    assert cards["market_selection"]["selection_counts"]["market_conflict_missing_rank_quarantined"] == 0


def test_review_guard_respects_local_odds_and_does_not_reconstruct_legacy_ranks():
    local = winner("Local", .92, 2.25, 1.44)
    local["betting"]["model_time_ranks"] = {"player1": None, "player2": None}
    local["betting"]["odds_source"] = "local"
    # A later/different source's market pair is irrelevant; the selected local
    # odds and original model-time ranks drive this evidence-integrity check.
    local["match_winner_market"]["player1_odds"] = 1.10
    assert unsubstantiated_high_confidence_winner(local)
    assert select_market_sections([local])["top_daily_picks"] == []
    assert local["betting"]["odds"] == 2.25

    old = winner("Legacy", .92, 2.25, 1.44)
    old["player1"]["rank"] = None
    old["player2"]["rank"] = None
    assert not unsubstantiated_high_confidence_winner(old)
    assert [r["event_id"] for r in _daily_rows({
        "top_daily_picks": [old], "value_picks": [],
    })] == ["Legacy"]


def test_price_guard_requires_explicit_complete_original_rank_marker():
    row = winner("InvalidEvidence", .902, 2.18, 1.50)
    for evidence in (None, {}, {"player1": None}, [], "missing"):
        row["betting"]["model_time_ranks"] = evidence
        assert not unsubstantiated_high_confidence_winner(row)
    row["betting"]["model_time_ranks"] = {"player1": 0, "player2": None}
    assert unsubstantiated_high_confidence_winner(row)
