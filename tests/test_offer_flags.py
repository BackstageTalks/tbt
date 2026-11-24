import pytest

from tbt.services import offer_flags
from tbt.services.market_selection import _low_odds_fill_floor, value_level_ok


def test_value_level_filter(monkeypatch):
    atp = {"tournament_level": "ATP 250", "tour": "ATP"}
    itf_m = {"tournament_level": "ITF Men", "tour": "ATP"}
    itf_w = {"tournament_level": "ITF Women", "tour": "WTA"}
    monkeypatch.delenv("TBT_VALUE_LEVELS", raising=False)
    assert value_level_ok(itf_w)  # empty = unchanged behaviour
    monkeypatch.setenv("TBT_VALUE_LEVELS", "ATP,ITF-M")
    assert value_level_ok(atp) and value_level_ok(itf_m)
    assert not value_level_ok(itf_w)


def test_low_odds_floor_bounds(monkeypatch):
    monkeypatch.delenv("TBT_TOP_LOW_ODDS_FLOOR", raising=False)
    assert _low_odds_fill_floor() is None
    monkeypatch.setenv("TBT_TOP_LOW_ODDS_FLOOR", "1.40")
    assert _low_odds_fill_floor() == 1.40
    monkeypatch.setenv("TBT_TOP_LOW_ODDS_FLOOR", "1.55")
    assert _low_odds_fill_floor() is None


def test_offer_flag_validation_and_env():
    assert offer_flags._validate("TBT_VALUE_LEVELS", "ATP,ITF-M") == "ATP,ITF-M"
    with pytest.raises(ValueError):
        offer_flags._validate("TBT_VALUE_LEVELS", "NHL")
    with pytest.raises(ValueError):
        offer_flags._validate("TBT_TOP_LOW_ODDS_FLOOR", 1.6)
    with pytest.raises(ValueError):
        offer_flags._validate("TBT_UNKNOWN", True)
    env = offer_flags.as_env({"TBT_VALUE_SERVE_RETURN": {"value": True},
                              "TBT_TOP_LOW_ODDS_FLOOR": {"value": 1.4},
                              "TBT_VALUE_LEVELS": {"value": "ATP"}})
    assert env == {"TBT_VALUE_SERVE_RETURN": "true", "TBT_TOP_LOW_ODDS_FLOOR": "1.4",
                   "TBT_VALUE_LEVELS": "ATP"}


def test_zero_means_code_default():
    env = offer_flags.as_env({"TBT_TOP_MIN_PICKS": {"value": 0.0}, "TBT_ACES_MIN_GAP": {"value": 0.0}})
    assert env == {"TBT_TOP_MIN_PICKS": "", "TBT_ACES_MIN_GAP": ""}
