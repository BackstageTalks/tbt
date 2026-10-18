"""Prospective 7.1.1 TOP/VALUE blind contracts; no production writes."""
from datetime import datetime, timedelta, timezone
from blind_711_forward import capture, grade, metrics, CHAMPION, CANDIDATE

NOW = datetime(2026, 10, 18, 9, tzinfo=timezone.utc)
ISSUED = (NOW - timedelta(hours=1)).isoformat()
START = (NOW + timedelta(hours=3)).isoformat()
TAKEN = (NOW - timedelta(hours=2)).isoformat()


def offer(section="top_daily", odds=1.75, chosen="a"):
    return {"event_id": "e1", "match_id": "m1", "tour": "ATP", "scheduled_at": START,
            "player1": {"id": "a"}, "player2": {"id": "b"},
            "market_publications": [
                {"section": section, "market": "match_winner", "selection_id": chosen,
                 "issued_at": ISSUED, "odds": odds, "publication_status": "published",
                 "result": {"scheduled_at": START}}]}


def predictions():
    return {"event_id": "e1", "match_id": "m1", "tour": "ATP",
            "scheduled_at": START, "captured_at": TAKEN, "status": "pending",
            "player1_id": "a", "player2_id": "b", "target_player1_win": None,
            "result_winner_id": None, "production_model_version": CHAMPION,
            "challenger_model_version": CANDIDATE,
            "production_player1_probability": .66, "challenger_player1_probability": .81}


def test_frozen_never_contains_outcome():
    rows, errors = capture([offer()], [predictions()], NOW)
    assert len(rows) == 1
    assert rows[0]["candidate_probability"] == .81
    assert "correct" not in rows[0] and "target_player1_win" not in rows[0]
    assert rows[0]["timing"] == "before_issued"


def test_after_issue_but_before_match_separated():
    s = predictions()
    s["captured_at"] = (NOW - timedelta(minutes=5)).isoformat()
    f, _ = capture([offer()], [s], NOW)
    assert len(f) == 1 and f[0]["timing"] == "after_issued_before_start"


def test_reverse_selected_side_is_complement():
    f, _ = capture([offer(chosen="b")], [predictions()], NOW)
    assert len(f) == 1 and abs(f[0]["candidate_probability"] - .19) < 1e-10


def test_unverifiable_price_rejected():
    assert not capture([offer(odds=1.49)], [predictions()], NOW)[0]


def test_stale_model_pair_and_wrong_players_rejected():
    s = predictions()
    s["challenger_model_version"] = "v7.2.1"
    assert not capture([offer()], [s], NOW)[0]
    s = predictions()
    s["player1_id"] = "someone-else"
    assert not capture([offer()], [s], NOW)[0]


def test_outcomes_known_or_after_start_never_frozen():
    r = offer()
    r["market_publications"][0]["result"]["correct"] = True
    assert not capture([r], [predictions()], NOW)[0]
    assert not capture([offer()], [predictions()], NOW + timedelta(hours=4))[0]
    s = predictions()
    s["status"] = "settled"
    s["target_player1_win"] = 1
    assert not capture([offer()], [s], NOW)[0]


def test_future_capture_rejected():
    s = predictions()
    s["captured_at"] = (NOW + timedelta(hours=1)).isoformat()
    assert not capture([offer()], [s], NOW)[0]


def test_dedup_same_pick_across_top_and_value():
    r = offer()
    r["market_publications"].extend(offer("value")["market_publications"])
    f, _ = capture([r], [predictions()], NOW)
    assert len(f) == 1 and set(f[0]["sections"]) == {"top_daily", "value"}
    assert not capture([r], [predictions()], NOW, f)[0]


def test_score_only_after_fixture_and_verified_result():
    f, _ = capture([offer()], [predictions()], NOW)
    r = offer()
    r["market_publications"][0]["result"]["correct"] = True
    assert not grade(f, [r], NOW)[0]
    scored, rejected = grade(f, [r], NOW + timedelta(hours=4))
    assert len(scored) == 1 and scored[0]["correct"] is True
    assert "correct" not in f[0]
    assert abs(metrics(scored)["roi"] - .75) < 1e-10
    assert metrics(scored)["candidate"]["0.8"]["n"] == 1
    assert metrics(scored)["champion"]["0.8"]["n"] == 0


def test_do_not_grade_void_or_unsettled():
    f, _ = capture([offer()], [predictions()], NOW)
    assert not grade(f, [offer()], NOW + timedelta(hours=4))[0]
    r = offer()
    r["market_publications"][0]["result"].update({"correct": True, "status": "void"})
    assert not grade(f, [r], NOW + timedelta(hours=4))[0]


def test_empty_metrics_not_a_win():
    assert metrics([]) == {"n": 0, "roi": None}
