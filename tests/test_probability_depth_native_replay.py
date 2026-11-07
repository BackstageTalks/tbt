"""Local synthetic safety tests; no private source files or API calls."""
from collections import Counter

import pytest

from replay_selection_reliability import canonical_index, dt, prepare
from research.probability_depth_replay import (
    reconstructed_card, selection_ids, paired_day_ci, test_replay as replay_analysis,
)
from tbt.services.market_selection import select_market_sections


def row(event="event-a", raw=.85, depth=.95, selected="top_daily", *, odds=1.65):
    p = .5 + (raw-.5)*depth
    return {
        "event_id": event, "scheduled_at": "2026-11-02T12:00:00+00:00",
        "model_version": "model-test", "tour": "ATP", "surface": "hard",
        "winner_id": "a",
        "player1": {"id": "a", "name": "A", "rank": 1, "probability": raw},
        "player2": {"id": "b", "name": "B", "rank": 2, "probability": 1-raw},
        "raw_model_probability": raw, "blinq_probability": p, "data_depth": depth,
        "samples": {"player1_surface_matches": 8, "player2_surface_matches": 9,
                    "player1_matches": 20, "player2_matches": 20},
        "priced": True, "selected_section": selected,
        "betting": {"selection": "A", "selection_id": "a", "odds": odds, "betting_day": "2026-11-02",
                    "captured_at": "2026-11-02T06:58:00+00:00",
                    "edge": .0, "expected_value": -.05},
        "two_way_market": {"player1_odds": odds, "player2_odds": 2.4,
                           "captured_at": "2026-11-02T06:58:00+00:00"},
    }


def match(event="event-a", winner="a", status="finished"):
    return {"match_id": event, "player1_id": "a", "player2_id": "b",
            "winner_id": winner, "scheduled_at": "2026-11-02T12:00:00+00:00",
            "tour": "atp", "status": status}


def snapshot(rows):
    return {"generated_at": "2026-11-02T07:00:00+00:00", "rows": rows}


def test_native_selector_is_used_for_both_arms_and_raw_can_add_top():
    first = row("one", raw=.84, depth=.96)
    second = row("two", raw=.62, depth=.80, selected=None)
    index = canonical_index([match("one"), match("two")])
    pub, alternative = [], []
    for original in (first, second):
        p = prepare(original, dt("2026-11-02T07:00:00+00:00"), "2026-11-02", index, Counter())
        assert p["quote_ok"]
        pub.append(reconstructed_card(original, p, raw_instead_of_shrunk=False, day="2026-11-02"))
        alternative.append(reconstructed_card(original, p, raw_instead_of_shrunk=True, day="2026-11-02"))
    assert selection_ids(select_market_sections(pub))["top_daily"] == {"one"}
    assert selection_ids(select_market_sections(alternative))["top_daily"] == {"one", "two"}


def test_real_replay_does_not_equate_different_policy_denominators():
    first = row("one", raw=.84, depth=.96)
    second = row("two", raw=.62, depth=.80, selected=None)
    r = replay_analysis([snapshot([first, second])], [match("one"), match("two", winner="b")])
    x = r["models"]["model-test"]
    assert x["fixed_candidate_raw"]["settled"] == 2
    assert x["native_selector_replay"]["exact_reproduced_days"] == 1
    assert x["native_selector_replay"]["raw_changes"]["top_daily"]["entered"] == 1
    assert x["native_selector_replay"]["fully_settled_same_capacity_n"]["top_daily"] == 0
    assert not r["candidate_promoted"]


def test_mismatch_fails_closed_for_claim_of_exact_replay():
    first = row("one", raw=.84, depth=.96, selected="prime")
    r = replay_analysis([snapshot([first])], [match("one")])
    m = r["models"]["model-test"]["native_selector_replay"]
    assert m["exact_reproduced_days"] == 0
    assert m["baseline_mismatch_days"] == 1
    assert m["raw_changes"]["top_daily"]["entered"] == 0


def test_late_quotes_cannot_be_used_in_hindsight():
    original = row()
    original["betting"]["captured_at"] = "2026-11-02T10:00:00+00:00"
    r = replay_analysis([snapshot([original])], [match()])
    m = r["models"]["model-test"]["native_selector_replay"]
    assert m["priced_rows"] == 0
    assert m["baseline_missing_quoted_rows"] == 1
    assert m["exact_reproduced_days"] == 0


def test_reference_replay_crosscheck_rejects_change_in_canonical_outcomes():
    original = row()
    reference = {"model_quality_A": {"model-test": {
        "all_candidates_raw": {"settled": 1, "hit_rate": 0, "brier": 0.3, "log_loss": 0.7},
        "all_candidates_public": {"settled": 1, "hit_rate": 0, "brier": 0.3, "log_loss": 0.7},
    }}}
    with pytest.raises(ValueError, match="reference mismatch"):
        replay_analysis([snapshot([original])], [match()], reference)


def test_paired_day_bootstrap_is_zero_for_equal_scores():
    examples = [
        {"day": "2026-11-01", "correct": True, "raw": .7, "public": .7},
        {"day": "2026-11-02", "correct": False, "raw": .6, "public": .6},
    ]
    for metric in ("brier", "log_loss"):
        x = paired_day_ci(examples, metric=metric, repeats=200)
        assert x["n"] == 2
        assert abs(x["mean_public_minus_raw"]) < 1e-12
        assert x["day_bootstrap_ci95"] == [0, 0]


def test_void_outcomes_not_counted_as_settled():
    r = replay_analysis([snapshot([row()])], [match(status="scheduled")])
    x = r["models"]["model-test"]
    assert x["fixed_candidate_raw"]["settled"] == 0
    assert x["fixed_candidate_shrunk"]["settled"] == 0


def test_fixed_snapshot_assigned_sections_are_a_separate_denominator():
    original = row("one", raw=.84, depth=.95, selected="top_daily")
    unassigned = row("two", raw=.90, depth=.40, selected=None)
    result = replay_analysis([snapshot([original, unassigned])],
                             [match("one"), match("two")])
    model = result["models"]["model-test"]
    fixed = model["fixed_snapshot_assigned_sections"]
    assert fixed["top_daily"]["raw"]["settled"] == 1
    assert fixed["unassigned"]["raw"]["settled"] == 1
    assert model["fixed_depth_gte_80"]["raw"]["settled"] == 1
    assert model["fixed_candidate_raw"]["settled"] == 2
    assert model["fixed_verified_prestart_quoted"]["raw"]["settled"] == 2
    # Very poorly supported unassigned candidate cannot become TOP/PRIME merely
    # because the raw probability is high.
    assert model["native_selector_replay"]["raw_changes"]["top_daily"]["entered"] == 0
