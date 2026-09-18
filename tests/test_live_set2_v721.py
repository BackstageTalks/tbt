from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tbt.services.comeback_projection import annotate_live_second_set_projections
from tbt.services.live_comeback import extract_second_set_winner_odds, attach_second_set_odds, scan_comeback_radar


def _match(p1, p2, first_winner, second_winner, days=10, surface="hard"):
    p1_first = 1.0 if first_winner == p1 else 0.0
    p2_first = 1.0 - p1_first
    p1_second = 1.0 if second_winner == p1 else 0.0
    p2_second = 1.0 - p1_second
    return SimpleNamespace(
        scheduled_at=datetime.now(timezone.utc)-timedelta(days=days), status="finished",
        player1_id=p1, player2_id=p2, surface=surface,
        stats={
            "p1_first_set_won":p1_first,"p2_first_set_won":p2_first,
            "p1_second_set_won":p1_second,"p2_second_set_won":p2_second,
        },
    )


def test_conditional_projection_is_separate_from_match_probability():
    history=[]
    for i in range(16):
        history.append(_match("10", f"x{i}", f"x{i}", "10" if i < 12 else f"x{i}", days=i+2))
    for i in range(12):
        history.append(_match(f"y{i}", "20", "20", f"y{i}" if i < 7 else "20", days=i+3))
    feed={"prime_picks":[{
        "event_id":"123","surface":"hard",
        "player1":{"id":"10","probability":.88},"player2":{"id":"20","probability":.12},
        "betting":{"selection_id":"10","selection":"Favorite","odds":1.18,"blinq_probability":.88},
    }]}
    enriched,report=annotate_live_second_set_projections(feed,history,now=datetime.now(timezone.utc))
    proj=enriched["prime_picks"][0]["live_second_set_projection"]
    assert proj["model"] == "live-second-set-comeback-v1"
    assert 0.2 <= proj["probability"] <= 0.85
    assert proj["probability"] != .88
    assert proj["favorite_samples"] == 16
    assert report["history_matches_with_set2"] == 28


def test_extract_second_set_market_variants_and_devig():
    event={"homeTeam":{"name":"Favorite"},"awayTeam":{"name":"Opponent"}}
    payload={"markets":[{"marketName":"Winner - Set 2","choices":[
        {"choiceName":"Favorite","decimalOdds":1.80},
        {"choiceName":"Opponent","decimalOdds":2.10},
    ]}]}
    out=extract_second_set_winner_odds(payload,event)
    assert out and out["home_odds"] == 1.80 and out["away_odds"] == 2.10
    assert abs(out["home_fair_probability"]+out["away_fair_probability"]-1.0) < 1e-9


def test_attach_set2_odds_calculates_edge_and_ev_only_with_real_market():
    feed={"prime_picks":[{
        "event_id":"123","player1":{"id":"10","probability":.88},"player2":{"id":"20","probability":.12},
        "betting":{"selection_id":"10","selection":"Favorite","odds":1.18,"blinq_probability":.88},
        "live_second_set_projection":{"probability":.64,"model":"x","favorite_samples":10,"opponent_closeout_samples":8},
    }]}
    event={"id":"123","status":{"type":"inprogress"},"homeTeam":{"id":"10","name":"Favorite"},"awayTeam":{"id":"20","name":"Opponent"},"homeScore":{"period1":4,"period2":1},"awayScore":{"period1":6,"period2":1}}
    scan=scan_comeback_radar(feed,[event])
    payload={"markets":[{"marketName":"2nd Set Winner","choices":[{"choiceName":"Favorite","decimalOdds":1.75},{"choiceName":"Opponent","decimalOdds":2.15}]}]}
    out=attach_second_set_odds(scan,{"123":payload},[event])
    row=out["candidates"][0]
    assert row["second_set_odds"] == 1.75
    assert row["second_set_edge"] is not None
    assert abs(row["second_set_ev"]-(.64*1.75-1)) < 1e-9
