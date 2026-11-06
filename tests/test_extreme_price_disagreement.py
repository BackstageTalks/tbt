"""06 Nov regression: pre-match extreme market/model contradictions must not be TOP.

Preserve odds sources, model probabilities, the immutable issued ledger, and
ordinary high-confidence TOP candidates.  The same rule must apply to a
new selector decision and to serving an already-issued daily snapshot.
"""
from tbt.services.entitlements import _daily_rows
from tbt.services.market_selection import select_market_sections
from tbt.services.price_integrity import extreme_winner_price_inversion


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
