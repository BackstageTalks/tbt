from datetime import datetime, timezone
from types import SimpleNamespace

from tbt.services import offer_shadow as osh


def _cap(rows):
    cap = {"schema": 1, "public_offer_day": "2026-11-24",
           "captured_at": "2026-11-24T05:00:00+00:00",
           "variants": {"value_all_levels": rows}}
    cap["sha256"] = osh._digest(cap)
    return {"snapshots": [{"offer_shadow": cap}, {"offer_shadow": dict(cap)}]}


def _row(mid, sel, odds, cat="WTA", published=False):
    return {"section": "value", "category": cat, "event_id": mid, "match_id": mid,
            "selected_player_id": sel, "player1_id": "a", "player2_id": "b",
            "scheduled_at": "2026-11-24T10:00:00+00:00", "odds": odds,
            "published": published}


def _m(mid, winner):
    return SimpleNamespace(is_completed=True, match_id=mid, player1_id="a",
                           player2_id="b", winner_id=winner)


def test_settle_counts_only_unpublished_and_dedupes_days():
    hist = _cap([_row("1", "a", 2.0), _row("2", "a", 2.5), _row("3", "a", 1.8, published=True),
                 _row("4", "a", 2.0)])
    rep = osh.settle_month(hist, [_m("1", "a"), _m("2", "b"), _m("3", "a")],
                           asof=datetime(2026, 11, 25, tzinfo=timezone.utc))
    d = rep["variants"]["value_all_levels"]["WTA"]
    assert rep["days"] == 1
    assert (d["issued"], d["settled"], d["correct"], d["staked"]) == (3, 2, 1, 2)
    s = osh.summarize({"2026-11": rep})["rows"][0]
    assert s["hit_rate"] == 0.5 and abs(s["roi"] - 0.0) < 1e-9 and s["profit_units"] == 0.0


def test_tampered_capture_is_ignored():
    hist = _cap([_row("1", "a", 2.0)])
    hist["snapshots"][0]["offer_shadow"]["variants"]["value_all_levels"][0]["odds"] = 9.0
    hist["snapshots"] = hist["snapshots"][:1]
    rep = osh.settle_month(hist, [_m("1", "a")], asof=datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert rep["days"] == 0


def test_not_settled_before_start():
    rep = osh.settle_month(_cap([_row("1", "a", 2.0)]), [_m("1", "a")],
                           asof=datetime(2026, 11, 24, 9, tzinfo=timezone.utc))
    assert rep["variants"]["value_all_levels"]["WTA"]["settled"] == 0


def test_category_splits_itf_by_tour():
    assert osh.category({"competition": "ITF", "tour": "ATP"}) == "ITF-M"
    assert osh.category({"competition": "ITF", "tour": "WTA"}) == "ITF-W"
