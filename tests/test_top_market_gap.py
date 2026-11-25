from tbt.services import market_anchored_rank as m


def _card(p, fair, monkeypatch):
    monkeypatch.setattr(m, "valid_prestart_fair", lambda c: fair)
    return {"probability": p}


def test_gap_off_by_default(monkeypatch):
    monkeypatch.delenv("TBT_TOP_MAX_MARKET_GAP", raising=False)
    monkeypatch.delenv("TBT_TOP_REQUIRE_MARKET_SIDE", raising=False)
    assert not m.top_market_side_violation(_card(0.90, 0.55, monkeypatch))


def test_gap_cap_vetoes_overconfident(monkeypatch):
    monkeypatch.setenv("TBT_TOP_MAX_MARKET_GAP", "0,15")
    assert m.top_market_side_violation(_card(0.76, 0.58, monkeypatch))
    assert not m.top_market_side_violation(_card(0.72, 0.58, monkeypatch))


def test_zero_or_missing_fair_never_vetoes(monkeypatch):
    monkeypatch.setenv("TBT_TOP_MAX_MARKET_GAP", "0")
    assert not m.top_market_side_violation(_card(0.95, 0.55, monkeypatch))
    monkeypatch.setenv("TBT_TOP_MAX_MARKET_GAP", "0.15")
    assert not m.top_market_side_violation(_card(0.95, None, monkeypatch))


def test_market_side_still_works(monkeypatch):
    monkeypatch.delenv("TBT_TOP_MAX_MARKET_GAP", raising=False)
    monkeypatch.setenv("TBT_TOP_REQUIRE_MARKET_SIDE", "true")
    assert m.top_market_side_violation(_card(0.70, 0.45, monkeypatch))
