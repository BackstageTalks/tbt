"""Offline fail-closed check of the approved morning TOP policy."""
import json
from _bootstrap import ROOT
from tbt.services.market_selection import _rank_full_slate_top, select_market_sections


def verify():
    rule = select_market_sections([])["market_selection"]["top_daily_rule"]
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))["market_rules"]["top_daily"]
    assert rule["policy"] == ui["policy"] == "priority_tours_top_v19"
    assert rule["core_min_probability"] == ui["min_probability"] == .70
    assert rule["probability_tiers"] == ui["confidence_tiers"] == [.70]
    assert rule["daily_minimum_target"] == ui["target_count"] == 3
    assert rule["min_odds"] == ui["min_odds"] == 1.50 and ui["max_odds"] is None
    assert ui["competition_priority"] == [["ATP", "WTA"], ["Challenger", "WTA 125"], ["ITF"]]
    def card(event, competition, probability):
        return dict(event_id=event, competition=competition,
                    tour="WTA" if competition.startswith("WTA") else "ATP",
                    probability=probability, odds=1.6)
    pool = [card("itf", "ITF", .95), card("secondary", "Challenger", .90),
            card("low", "ATP", .69), card("main-low", "ATP", .70),
            card("main-high", "WTA", .79)]
    selected, _, _ = _rank_full_slate_top(pool, [])
    assert [c["event_id"] for c in selected] == ["main-high", "main-low", "secondary"]
    selected, _, _ = _rank_full_slate_top([pool[0], pool[3]], [])
    assert [c["event_id"] for c in selected] == ["main-low", "itf"]
    return {"status": "PASS", "policy": rule["policy"], "provider_requests": 0}


if __name__ == "__main__":
    print(json.dumps(verify()))
