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


def _ace_hist(rows):
    cap = {"schema": 1, "public_offer_day": "2026-11-24",
           "captured_at": "2026-11-24T05:00:00+00:00",
           "variants": {"aces_all_levels": rows}}
    cap["sha256"] = osh._digest(cap)
    return {"snapshots": [{"offer_shadow": cap}]}


def test_aces_and_double_faults_graded_by_superiority():
    rows = [dict(_row("1", "a", None, cat="ITF-M"), section="most_aces"),
            dict(_row("2", "a", None, cat="ITF-M"), section="most_aces"),
            dict(_row("3", "b", None, cat="WTA 125"), section="double_faults"),
            dict(_row("4", "a", None, cat="ITF-M"), section="most_aces")]
    ms = [SimpleNamespace(**vars(_m("1", "a")), stats={"p1_aces": 7, "p2_aces": 3}),
          SimpleNamespace(**vars(_m("2", "b")), stats={"p1_aces": 2, "p2_aces": 5}),
          SimpleNamespace(**vars(_m("3", "a")), stats={"p1_double_faults": 1, "p2_double_faults": 4}),
          SimpleNamespace(**vars(_m("4", "a")), stats={"p1_aces": 4, "p2_aces": 4})]
    rep = osh.settle_month(_ace_hist(rows), ms, asof=datetime(2026, 11, 25, tzinfo=timezone.utc))
    v = rep["variants"]["aces_all_levels"]
    assert v["Viac es · ITF-M"]["issued"] == 3
    assert v["Viac es · ITF-M"]["settled"] == 2 and v["Viac es · ITF-M"]["correct"] == 1
    assert v["Dvojchyby · WTA 125"]["correct"] == 1


def test_calibrated_probability_slopes():
    assert osh.calibrated_probability(0.7, "ITF-M") == 0.7 or abs(osh.calibrated_probability(0.7, "ITF-M") - 0.7) < 1e-12
    assert osh.calibrated_probability(0.7, "Challenger") < 0.7
    assert osh.calibrated_probability(None, "UTR") is None
