from types import SimpleNamespace

from scripts.finalize_shadow_promotion import (
    _build_gate_report,
    _fingerprint,
)


def _row(i, tour, target, candidate, production, elo):
    return {
        "match_id": f"m{i}",
        "scheduled_at": f"2026-10-{6 + (i % 3):02d}T12:00:00+00:00",
        "tour": tour,
        "target_player1_win": target,
        "challenger_player1_probability": candidate,
        "production_player1_probability": production,
        "elo_player1_probability": elo,
    }


def test_shadow_fingerprint_is_order_independent():
    rows = [_row(1, "atp", 1, .7, .6, .55), _row(2, "wta", 0, .3, .4, .45)]
    a = _fingerprint(rows, "prod", "cand")
    b = _fingerprint(list(reversed(rows)), "prod", "cand")
    assert a == b


def test_gate_report_contains_same_cohort_metrics():
    rows = []
    for i in range(240):
        target = i % 2
        good = .75 if target else .25
        weaker = .62 if target else .38
        elo = .58 if target else .42
        rows.append(_row(i, "atp" if i % 2 else "wta", target, good, weaker, elo))
    report = _build_gate_report(rows, "prod-v1", "cand-v2")
    assert report["holdout"]["n"] == 240
    assert report["production_holdout"]["n"] == 240
    assert report["elo_baseline_holdout"]["n"] == 240
    assert report["shadow"]["settled_utc_days"] == 3
    assert report["shadow"]["by_tour"] == {"atp": 120, "wta": 120}
    assert report["evaluation_governance"]["eligibility_reason"] is None
