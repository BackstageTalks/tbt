"""Offline fail-closed check of the approved morning TOP policy."""
import json
from _bootstrap import ROOT
from tbt.services.market_selection import _rank_full_slate_top, select_market_sections


def verify():
    from tbt.services.top_policy import rejection_reasons
    rule = select_market_sections([])["market_selection"]["top_daily_rule"]
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))["market_rules"]["top_daily"]
    assert rule["policy"] == ui["policy"] == "priority_tours_top_v20"
    assert rule["core_min_probability"] == ui["min_probability"] == .65
    assert rule["probability_tiers"] == ui["confidence_tiers"] == [.65]
    assert rule["daily_minimum_target"] == ui["target_count"] == 3
    assert rule["min_odds"] == ui["min_odds"] == 1.50 and ui["max_odds"] is None
    assert ui["competition_priority"] == [["ATP", "WTA"], ["Challenger"], ["ITF"]]
    def card(event, competition, probability):
        return dict(event_id=event, competition=competition,
                    tour="WTA" if competition.startswith("WTA") else "ATP",
                    probability=probability, odds=1.6)
    pool = [card("w35", "ITF W35", .95), card("secondary", "Challenger", .90),
            card("main-65", "ATP", .65), card("main-68", "ATP", .69),
            card("main-70", "WTA", .79), card("excluded", "WTA 125", .99)]
    selected, _, details = _rank_full_slate_top(pool, [])
    assert [c["event_id"] for c in selected] == ["main-70", "main-68", "main-65"]
    assert all(c["selection_tier"] == "main_0.65" for c in selected)
    assert details["shortfall"] == 0
    selected, _, details = _rank_full_slate_top([pool[0], pool[1], pool[4]], [])
    assert [c["event_id"] for c in selected] == ["main-70", "secondary", "w35"]
    assert details["shortfall"] == 0
    selected, _, details = _rank_full_slate_top([card("none", "ATP", .64)], [])
    assert selected == [] and details["shortfall"] == 3

    male = card("itf-m", "ITF Men", .98)
    male["tournament"] = "M25 Challenger"
    assert "itf_top_requires_verified_w35plus" in rejection_reasons(male)
    unknown = card("unknown-itf", "ITF Women", .97)
    assert "itf_top_requires_verified_w35plus" in rejection_reasons(unknown)
    verified = card("verified", "ITF Women", .65)
    verified["tournament"] = "ITF W35 Heraklion"
    verified["quality"] = {"feature_evidence": {
        "serve_return_known_both": True,
        "surface_serve_return_known_both": True,
    }}
    assert "itf_top_requires_verified_w35plus" not in rejection_reasons(verified)
    return {"status": "PASS", "policy": rule["policy"], "provider_requests": 0}


if __name__ == "__main__":
    print(json.dumps(verify()))
