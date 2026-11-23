from datetime import date
import gzip
import json

import pytest

from itf_week_gapfill_stage import run
from test_itf_week_gapfill_stage import Fake
from test_market_selection import row
from tbt.services.market_selection import select_market_sections


@pytest.mark.parametrize("price,opponent,key", [(1.9, 2., "value_picks"), (1.4, 3., "prime_picks")])
def test_new_winner_requires_identity_and_quote_time(price, opponent, key):
    for missing in ("event", "side", "time"):
        item = row("A", .74, price, opponent)
        if missing == "event":
            del item["event_id"]
        elif missing == "side":
            item["betting"]["selection_id"] = "stranger"
        else:
            del item["betting"]["captured_at"]
        assert not select_market_sections([item])[key]


def test_value_limits_and_offer_day():
    item = row("A", .72, 1.90, 2.)
    assert select_market_sections([item], value_limit=0)["top_daily_picks"]
    assert select_market_sections([item], section_priority=("top_daily", "value", "prime"))["top_daily_picks"]
    assert select_market_sections([item], public_offer_day="2026-09-10")["market_selection"]["value_audit"]["qualified"] == 0


def test_winter_depth_isolated_to_graded_itf_top(monkeypatch):
    item = row("A", .80, 1.56, 2.5, depth=.30)
    item.update(competition="ITF M15", tournament="ITF M15 Antalya")
    monkeypatch.delenv("TBT_ITF_TOP_DEPTH_MODE", raising=False)
    assert not select_market_sections([item])["top_daily_picks"]
    monkeypatch.setenv("TBT_ITF_TOP_DEPTH_MODE", "sqrt_v1")
    top, = select_market_sections([item])["top_daily_picks"]
    assert top["probability"] == pytest.approx(.66431677)
    assert top["baseline_blinq_probability"] == pytest.approx(.59)
    for competition in ("ATP", "ITF", "ITF M150"):
        item.update(competition=competition, tournament="Example")
        assert not select_market_sections([item])["top_daily_picks"]


def test_itf_reverse_collision_timeout_and_empty_interval(tmp_path):
    day = date(2023, 5, 1)
    target = {"p1": "Alexander Kotzen", "p2": "Ishaan Ravichander", "match_id": "A"}
    result = run(Fake(), {day: [target, dict(target, match_id="B")]}, tmp_path, 200)
    assert result["linked"] == 0 and result["ambiguous"] == 2

    class Timeout(Fake):
        def event_statistics(self, eid):
            raise TimeoutError()

    result = run(Timeout(), {day: [target]}, tmp_path, 200, range_end=day)
    assert result["stopped"] == "retry" and "last_complete_week" not in result
    assert gzip.open(tmp_path / "staging.jsonl.gz", "rt").read() == ""
    assert run(Fake(), {}, tmp_path, 200, range_end=day)["last_complete_week"] == day.isoformat()
