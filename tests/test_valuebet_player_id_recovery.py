from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from link_valuebetennis_market_history import (
    _crosswalk_link,
    _strict_one_to_one_crosswalk,
)


def _source(**overrides):
    base = dict(
        tour="wta",
        player_a_id="va",
        player_b_id="vb",
        player_a="Alpha Alias",
        player_b="Beta Alias",
        winner="Alpha Alias",
        event_date=datetime(2026, 1, 2, tzinfo=timezone.utc).date(),
        surface="hard",
        tournament="Test Open",
        opening={
            "player1_odds": 1.8,
            "player2_odds": 2.1,
            "player1_implied_probability": 0.5384615384615384,
            "player2_implied_probability": 0.4615384615384615,
            "raw_overround": 1.0317460317460316,
        },
        closing=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _match(**overrides):
    base = dict(
        player1_id="ca",
        player2_id="cb",
        winner_id="ca",
        scheduled_at=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        surface="hard",
        tournament="Test Open",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_crosswalk_requires_one_to_one_mapping_both_directions():
    mapping = _strict_one_to_one_crosswalk(
        [
            ("wta", "va", "ca"),
            ("wta", "vb", "cb"),
            ("wta", "conflict", "ca"),
            ("wta", "unstable", "cx"),
            ("wta", "unstable", "cy"),
        ]
    )
    assert ("wta", "va") not in mapping
    assert mapping[("wta", "vb")] == "cb"
    assert ("wta", "unstable") not in mapping


def test_crosswalk_link_recovers_alias_only_on_exact_safe_identity():
    crosswalk = {("wta", "va"): "ca", ("wta", "vb"): "cb"}
    linked = _crosswalk_link(_source(), _match(), crosswalk)
    assert linked is not None
    assert linked["accepted"] is True
    assert linked["orientation"] == "direct"
    assert "player_id_crosswalk" in linked["evidence"]


def test_crosswalk_link_fails_closed_on_wrong_day_or_winner():
    crosswalk = {("wta", "va"): "ca", ("wta", "vb"): "cb"}
    wrong_day = _match(
        scheduled_at=datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
    )
    wrong_winner = _match(winner_id="cb")
    assert _crosswalk_link(_source(), wrong_day, crosswalk) is None
    assert _crosswalk_link(_source(), wrong_winner, crosswalk) is None
