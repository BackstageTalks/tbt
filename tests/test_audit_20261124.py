"""Offline reproductions of audit findings. Strict xfail turns a fix into XPASS."""
import pytest
from tbt.services import market_selection as ms, offer_shadow as shadow


@pytest.mark.xfail(strict=True, reason="Admin FILL and runtime FLOOR disagree")
def test_admin_top_floor_reaches_selector(monkeypatch):
    monkeypatch.setenv("TBT_TOP_LOW_ODDS_FLOOR", "1.40")
    monkeypatch.setenv("TBT_TOP_LOW_ODDS_FILL", "1.45")
    assert ms._low_odds_fill_floor() == 1.45


@pytest.mark.xfail(strict=True, reason="Non-finite ace counts settle as wins")
def test_invalid_ace_count_stays_pending():
    from types import SimpleNamespace
    match = SimpleNamespace(player1_id="a", stats={"p1_aces": float("inf")})
    row = {"section": "aces_over", "market_line": 3.5, "selected_player_id": "a"}
    assert shadow._row_won(row, match) is None


@pytest.mark.xfail(strict=True, reason="Duplicate contracts within one capture count twice")
def test_one_virtual_stake_per_contract():
    from test_offer_shadow import _cap, _m, _row
    from datetime import datetime, timezone
    row = _row("1", "a", 1.8)
    report = shadow.settle_month(_cap([row, row]), [_m("1", "a")],
                                 asof=datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert report["variants"]["value_all_levels"]["WTA"]["staked"] == 1


@pytest.mark.xfail(strict=True, reason="Cache accepts changed frame bytes with intact manifest")
def test_changed_cached_values_do_not_change_training_rows(tmp_path):
    import pandas as pd
    from test_feature_checkpoints import _ck, _full, _history
    matches = _history(300)
    _ck(matches, tmp_path)
    path = sorted(tmp_path.glob("frame-*.pkl"))[0]
    frame = pd.read_pickle(path)
    col = next(key for key in frame.select_dtypes("number") if len(frame[key].dropna()))
    frame[col] = 123456
    frame.to_pickle(path)
    actual, _ = _ck(matches, tmp_path)
    pd.testing.assert_frame_equal(actual, _full(matches), check_exact=True)
