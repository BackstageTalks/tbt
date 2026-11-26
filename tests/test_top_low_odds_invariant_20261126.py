"""26.11. morning crash: owner 1.40 TOP fill tripped the 1.50 odds invariant."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "api/tbt/services/market_selection.py").read_text(encoding="utf-8")


def test_invariant_exempts_only_low_odds_fill_tier_above_its_floor():
    block = SRC[SRC.index("_fill_floor = _low_odds_fill_floor()"):SRC.index('raise ValueError("Top odds floor invariant failed")')]
    assert 'card.get("selection_tier") == "low_odds_fill"' in block
    assert ">= _fill_floor" in block and "_fill_floor is not None" in block
