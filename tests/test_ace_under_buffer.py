"""Guard the production Aces UNDER selection against too-tight real lines.

All inputs below are deterministic *test fixtures*, not historical ROI claims.
"""
import pytest

from tbt.services.ace_under_buffer import (
    ace_under_eligible, ace_under_margins, ace_under_preferred,
)
from tbt.services.projection_odds import _attach_ace


@pytest.mark.parametrize("mean,minimum,preferred", [
    (2.1, 1.0, 2.0),
    (3.99, 1.0, 2.0),
    (4.0, 1.5, 2.0),
    (8.0, 1.5, 2.0),
    (9.5, 2.0, 3.0),
])
def test_configured_cushions(mean, minimum, preferred):
    assert ace_under_margins(mean) == (minimum, preferred)


@pytest.mark.parametrize("mean,line,allowed,preferred", [
    (2.1, 2.5, False, False),
    (2.1, 3.5, True, False),
    (2.1, 4.5, True, True),
    (9.5, 10.5, False, False),
    (9.5, 11.5, True, False),
    (9.5, 12.5, True, True),
    (float("nan"), 12.5, False, False),
    (9.5, float("nan"), False, False),
    (-1, 2.5, False, False),
])
def test_under_market_line_is_real_and_has_enough_space(mean, line, allowed, preferred):
    assert ace_under_eligible(mean, line) is allowed
    assert ace_under_preferred(mean, line) is preferred


def _card(mean=2.1, metric="aces"):
    return {
        "market": metric, "event_id": "event-1", "projection": mean,
        "player1": {"id": "1", "name": "Player A"},
        "player2": {"id": "2", "name": "Player B"},
        "selection_id": "1", "selection": "Player A",
        "price_status": "projection_only",
    }


def _payload(offers, metric="Aces"):
    markets = []
    for line, under_odds, over_odds in offers:
        for side, odds in (("Under", under_odds), ("Over", over_odds)):
            markets.append({
                "marketName": f"Player A Total {metric}",
                "choiceName": side, "choiceGroup": f"{line:.1f}",
                "decimalOdds": odds,
            })
    return {"markets": markets}


def _pick(mean, offers, metric="aces"):
    return _attach_ace(
        _card(mean, metric),
        _payload(offers, "Aces" if metric == "aces" else "Double Faults"),
        "2026-11-01T11:00:00+00:00", 1,
    )


def test_under_2_5_with_2_1_projection_is_blocked():
    card, ok, reason = _pick(2.1, [(2.5, 1.8, 1.1)])
    assert not ok and reason == "ace_under_buffer_not_qualified"
    assert card["price_status"] == "projection_only"
    assert "market_line" not in card
    assert card["projection"] == 2.1


def test_under_3_5_with_2_1_projection_is_allowed():
    card, ok, reason = _pick(2.1, [(3.5, 1.85, 1.1)])
    assert ok and reason == "priced_player_total_ou"
    assert card["ou_side"] == "under" and card["market_line"] == 3.5
    assert card["projection"] == 2.1 and card["odds"] == 1.85


def test_high_projection_prefers_12_5_if_positive_ev_even_when_11_5_has_higher_ev():
    card, ok, _ = _pick(9.5, [(11.5, 2.2, 1.1), (12.5, 1.65, 1.1)])
    assert ok
    assert card["ou_side"] == "under" and card["market_line"] == 12.5
    assert card["odds"] == 1.65


def test_falls_back_to_11_5_when_12_5_quote_has_no_ev():
    card, ok, _ = _pick(9.5, [(11.5, 2.2, 1.1), (12.5, 1.08, 1.1)])
    assert ok and card["market_line"] == 11.5
    assert card["odds"] == 2.2


def test_aces_over_not_changed():
    card, ok, _ = _pick(7.2, [(5.5, 1.15, 1.92)])
    assert ok and card["ou_side"] == "over"
    assert card["market_line"] == 5.5


def test_double_faults_under_is_not_subject_to_ace_buffer():
    card, ok, _ = _pick(2.1, [(2.5, 2.5, 1.1)], "double_faults")
    assert ok and card["ou_side"] == "under"
    assert card["market_line"] == 2.5


def test_rejected_real_line_is_flagged_for_strict_mode():
    card, ok, _ = _pick(2.1, [(2.5, 1.8, 1.1)])
    assert not ok and card["real_ou_market_rejected"] is True
    assert card["real_ou_lines_seen"] == [2.5]


def test_no_real_market_is_not_flagged():
    card, ok, _ = _pick(2.1, [])
    assert not ok and "real_ou_market_rejected" not in card


def test_dfs_books_rank_after_sportsbooks():
    from tbt.services.projection_odds import _is_dfs_book
    assert _is_dfs_book("PrizePicks") and _is_dfs_book("Underdog Fantasy")
    assert not _is_dfs_book("DraftKings") and not _is_dfs_book("bet365")


def test_cushion_rule_over_and_under_from_offer(monkeypatch):
    from tbt.services import projection_odds as po
    monkeypatch.setenv("TBT_ACES_CUSHION_RULE", "true")
    # projection 5.0: Over 3.5 qualifies (cushion 1.5), Over 4.5 does not
    card, ok, reason = _pick(5.0, [(3.5, 2.6, 1.55), (4.5, 2.0, 1.9)])
    assert ok and card["ou_side"] == "over" and card["market_line"] == 3.5
    assert card["selection_rule"] == "blinq_cushion_v1"
    # projection 10.4: Under 17.5 qualifies (big cushion)
    card, ok, _ = _pick(10.4, [(17.5, 1.6, 2.2)])
    assert ok and card["ou_side"] == "under" and card["market_line"] == 17.5


def test_cushion_rule_accepts_one_sided_over(monkeypatch):
    monkeypatch.setenv("TBT_ACES_CUSHION_RULE", "true")
    payload = {"markets": [{"marketName": "Player A Total Aces", "choiceName": "Over",
                            "choiceGroup": "3.5", "decimalOdds": 1.7}]}
    card, ok, _ = _attach_ace(_card(5.2), payload, "2026-11-01T11:00:00+00:00", 2)
    assert ok and card["ou_side"] == "over" and card["market_line"] == 3.5


def test_cushion_rule_off_keeps_ev_logic(monkeypatch):
    monkeypatch.delenv("TBT_ACES_CUSHION_RULE", raising=False)
    payload = {"markets": [{"marketName": "Player A Total Aces", "choiceName": "Over",
                            "choiceGroup": "3.5", "decimalOdds": 1.7}]}
    card, ok, _ = _attach_ace(_card(5.2), payload, "2026-11-01T11:00:00+00:00", 2)
    assert not ok


def test_cushion_rule_under_symmetric_1_5(monkeypatch):
    monkeypatch.setenv("TBT_ACES_CUSHION_RULE", "true")
    card, ok, _ = _pick(10.4, [(11.5, 1.9, 1.9)])
    assert not ok
    card, ok, _ = _pick(10.4, [(12.5, 1.6, 2.2)])
    assert ok and card["ou_side"] == "under" and card["market_line"] == 12.5
