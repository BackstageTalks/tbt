from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tbt.models.point_model import PointHistory, format_for
from tbt.models.point_simulation import simulate, tiebreak
from tbt.schemas import MatchRecord
from tbt.services import point_model_shadow


@pytest.mark.parametrize("best,deciding", [(3, 7), (3, 10), (5, 7), (5, 10)])
def test_simulation_normalizes_and_swaps(best, deciding):
    a = simulate(.68, .58, best, deciding)
    b = simulate(.58, .68, best, deciding)
    assert sum(a["winner"]) == pytest.approx(1)
    assert sum(a["first_set"]) == pytest.approx(1)
    assert len(a["set_score"]) == 2 * (best // 2 + 1)
    for key in ("set_score", "total_games", "game_margin_player1"):
        assert sum(a[key].values()) == pytest.approx(1)
    for key in ("winner", "breaks", "service_points", "first_set",
                "at_least_one_set", "comeback_given_first_set_loss"):
        assert a[key] == pytest.approx(b[key][::-1])
    for score, probability in a["set_score"].items():
        assert probability == pytest.approx(b["set_score"][":".join(score.split(":")[::-1])])
    for line, probs in a["handicap"].items():
        assert probs == pytest.approx(b["handicap"][line][::-1])
        assert probs[0] + a["handicap"][f"{-float(line):+g}"][1] == pytest.approx(1)
    assert a["total_games"] == pytest.approx(b["total_games"])
    for sides in a["totals"].values():
        assert sum(sides.values()) == pytest.approx(1)
    assert a["tiebreak"] == pytest.approx(b["tiebreak"])
    for item, reverse in zip(a["exact_match_top3"], b["exact_match_top3"]):
        assert item["probability"] == pytest.approx(reverse["probability"])
        assert item["scores"] == [":".join(x.split(":")[::-1]) for x in reverse["scores"]]
    a["set_score"].clear()
    assert sum(simulate(.68, .58, best, deciding)["set_score"].values()) == pytest.approx(1)


def test_tiebreak_to_seven_or_ten_and_deciding_rule():
    seven, service_seven = tiebreak((.62, .62), 0, 7)
    ten, service_ten = tiebreak((.62, .62), 0, 10)
    assert seven == pytest.approx(.5)
    assert ten == pytest.approx(.5)
    assert sum(service_ten) > sum(service_seven) > 7
    assert tiebreak((.69, .59), 0, 10)[0] > tiebreak((.69, .59), 0, 7)[0] > .5
    assert simulate(.69, .59, 5, 10)["winner"][0] > simulate(.69, .59, 5, 7)["winner"][0]
    assert format_for(fixture(tournament="Wimbledon", tournament_level="Grand Slam"))[:2] == (5, 10)
    assert format_for(fixture(tournament="Wimbledon", tournament_level="Grand Slam",
                              round_name="Qualification"))[0] == 3


NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def fixture(**changes):
    return replace(MatchRecord("target", "atp", NOW, "a", "A", "b", "B",
                               surface="hard", tournament_level="ATP"), **changes)


def past(match_id, at, *, winner="a", statistics=None, context=None):
    return fixture(match_id=match_id, scheduled_at=at, winner_id=winner,
                   status="completed", stats=statistics or {}, provider_payload=context or {})


def test_unknown_player_falls_back_to_elo_and_missing_values():
    replay = PointHistory([past("1", NOW - timedelta(days=14))])
    replay.advance(NOW - timedelta(microseconds=1))
    card = replay.card(fixture(player2_id="new"))
    assert card["data_quality"] == "elo_fallback" and card["low_data"]
    assert card["head_to_head"] == {"matches": 0, "value": "--"}
    assert card["serve_return"]["value"][1]["history"]["aces"]["value"] == "--"
    p = card["favorite"]["value"]["probabilities"][0]
    assert p > .5
    assert p == pytest.approx(card["form_vs_elo"]["value"]["elo_probability"][0], abs=.0006)


def test_no_target_future_same_day_or_late_available_stats():
    cutoff = NOW - timedelta(seconds=1)
    stats = {"p1_service_points_won": .89, "p2_service_points_won": .4,
             "p1_first_serve_in": .8, "p1_aces": 0, "p1_service_points_total": 60}
    delayed = past("delayed", NOW - timedelta(days=14), statistics=stats,
                   context={"_tbt_statistics": {"fetched_at": cutoff.isoformat()}})
    old = past("old", NOW - timedelta(days=10))
    controlling = PointHistory([old, replace(delayed, stats={})])
    dirty = PointHistory([old, delayed, past("target", NOW, statistics=stats),
                          past("future", NOW + timedelta(days=1), statistics=stats),
                          past("same_day", NOW - timedelta(hours=2), statistics=stats)])
    for replay in (controlling, dirty):
        replay.advance(cutoff)
    assert dirty.card(fixture()) == controlling.card(fixture())
    assert dirty.card(fixture(), {"b": {"as_of": NOW.isoformat(), "matches": 10, "value": "attacker"}})["opponent_style"]["value"][0] == "--"
    dirty.advance(cutoff + timedelta(microseconds=1))
    card = dirty.card(fixture())
    assert card["data_quality"] == "low"
    assert card["serve_return"]["value"][0]["history"]["first_serve_in"]["matches"] == 1
    assert card["predicted_stats"]["value"][0]["aces"]["matches"] == 1  # observed zero
    with pytest.raises(ValueError, match="precede"):
        dirty.card(fixture(scheduled_at=cutoff))


def test_cached_snapshot_rotates_and_missing_flag_is_off(tmp_path, monkeypatch):
    path = tmp_path / "point.json"
    monkeypatch.setenv(point_model_shadow.SNAPSHOT, str(path))
    monkeypatch.delenv(point_model_shadow.FLAG, raising=False)
    assert not point_model_shadow.enabled()
    monkeypatch.setenv(point_model_shadow.FLAG, "true")
    assert point_model_shadow.enabled()
    path.write_text(json.dumps({"schema": 3, "candidate": "blinq-candidate-frozen-45525499354-1", "cards": {"a": {"value": 1}}}))
    assert point_model_shadow.shadow_card("a") == {"value": 1}
    hits = point_model_shadow._read.cache_info().hits
    assert point_model_shadow.shadow_card("a") == {"value": 1}
    assert point_model_shadow._read.cache_info().hits == hits + 1
    new = path.with_suffix(".new")
    new.write_text(json.dumps({"schema": 3, "candidate": "blinq-candidate-frozen-45525499354-1", "cards": {"a": {"value": 200}}}))
    new.replace(path)
    assert point_model_shadow.shadow_card("a") == {"value": 200}
    assert point_model_shadow.shadow_card("unknown") is None


def test_route_is_flagged_and_checks_admin_first(monkeypatch):
    import function_app

    monkeypatch.setattr(function_app, "response", lambda body, status=200: (body, status))
    monkeypatch.setattr(function_app, "_admin_user", lambda req: (None, ("denied", 403)))
    monkeypatch.setattr(point_model_shadow, "shadow_card", lambda _: pytest.fail("Unauthorized read"))
    req = SimpleNamespace(params={"match_id": "m"})
    monkeypatch.delenv(point_model_shadow.FLAG, raising=False)
    assert function_app.admin_point_model_shadow(req)[1] == 403
    monkeypatch.setenv(point_model_shadow.FLAG, "1")
    assert function_app.admin_point_model_shadow(req)[1] == 403
    monkeypatch.setattr(function_app, "_admin_user", lambda req: ({}, None))
    monkeypatch.delenv(point_model_shadow.FLAG)
    assert function_app.admin_point_model_shadow(req)[1] == 404
    monkeypatch.setenv(point_model_shadow.FLAG, "1")
    monkeypatch.setattr(point_model_shadow, "shadow_card", lambda key: {"match_id": key})
    assert function_app.admin_point_model_shadow(req) == ({"analysis_v2": {"match_id": "m"}}, 200)

@pytest.mark.parametrize("best,deciding", [(3, 7), (3, 10), (5, 7), (5, 10)])
@pytest.mark.parametrize("target", [.015, .28, .5, .81, .985])
def test_calibrated_point_sum_and_candidate_winner(best, deciding, target):
    from tbt.models.point_anchor import anchored_rates, calibrated_mean

    mean = calibrated_mean(.63, -.045)
    rates = anchored_rates(mean, target, best, deciding)
    assert sum(rates) == pytest.approx(2 * mean)
    assert simulate(*rates, best, deciding)["winner"][0] == pytest.approx(target, abs=.005)

@pytest.mark.parametrize("decider,total,margin", [((10,8),21,1), ((14,12),21,1), ((1,0),21,1)])
def test_match_tiebreak_is_one_game(decider,total,margin):
    from tbt.models.point_rules import rules_for, score_audit
    a,b=decider
    stats={"p1_set1_games":6,"p2_set1_games":4,"p1_set2_games":4,"p2_set2_games":6,
           "total_sets":3,"p1_sets_won":2,"p2_sets_won":1,
           "p1_games_won":10+a,"p2_games_won":10+b,"total_games":20+a+b}
    m=fixture(tournament="ITF M15",tournament_level="ITF Men",round_name="Qualifications",
              status="finished",winner_id="a",stats=stats)
    reason, games=score_audit(m,3,rules_for(m))
    assert reason=="complete" and sum(games)==total and games[0]-games[1]==margin
    assert score_audit(replace(m,provider_payload={"_tbt_termination":{"reason":"retired"}}),3,rules_for(m))[1] is None
    explicit={**stats,"p1_set3_games":a,"p2_set3_games":b,"p1_games_won":11,
              "p2_games_won":10,"total_games":21}
    assert score_audit(replace(m,stats=explicit),3,rules_for(m))==("complete",(11,10))
    missing=dict(stats)
    missing.pop("p1_set1_games")
    assert score_audit(replace(m,stats=missing),3,rules_for(m))[0]=="incomplete"


def test_itf_qualifying_and_short_sets():
    from tbt.models.point_rules import Rules, rules_for
    from tbt.models.point_simulation import game
    from tbt.models.point_anchor import anchored_rates
    for tier, expected in (("W35",True),("W75",False)):
        m=fixture(tour="wta",tournament_level="ITF Women",tournament="ITF "+tier,round_name="Qualifications")
        assert rules_for(m).match_tiebreak is expected
        assert not rules_for(m).no_ad
    assert game(.5,True)[0]==pytest.approx(.5)
    assert game(.5,True)[1]<game(.5)[1]
    for best,rules,upper in ((3,Rules(match_tiebreak=True),27),(5,Rules(short=True,no_ad=True),35)):
        points=anchored_rates(.58,.72,best,7,rules)
        result=simulate(*points,best,7,rules)
        assert max(result["total_games"])==upper
        assert sum(result["total_games"].values())==pytest.approx(1)
        assert result["winner"][0]==pytest.approx(.72,abs=.0001)


def test_score_and_format_conflict_is_excluded():
    from tbt.models.point_rules import STANDARD, Rules, score_audit
    stats={"p1_set1_games":6,"p2_set1_games":4,"p1_set2_games":4,"p2_set2_games":6,
           "total_sets":3,"p1_sets_won":2,"p2_sets_won":1,
           "p1_games_won":16,"p2_games_won":14,"total_games":30}
    m=fixture(status="finished",winner_id="a",stats=stats)
    assert score_audit(m,3,STANDARD)==("complete",(16,14))
    assert score_audit(m,3,Rules(match_tiebreak=True))[0]=="decider_format_conflict"
    assert score_audit(replace(m,status="suspended"),3,STANDARD)[0]=="unfinished"
    assert score_audit(replace(m,stats={**stats,"total_games":29}),3,STANDARD)[0]=="inconsistent_summary"
