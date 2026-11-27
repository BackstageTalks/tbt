from datetime import date, datetime, timezone

from tbt.services.bracket import public_brackets, update_bracket_predictions


DAY = date(2026, 11, 25)


def test_tournament_accuracy_dedup_and_exclude_walkover_and_late_freeze():
    now = datetime(2026, 11, 25, 10, tzinfo=timezone.utc)
    start = "2026-11-25T11:00:00+00:00"
    matches = [
        {"event_id": str(i), "players": [{"id": "10"}, {"id": "20"}],
         "analysis_context": {"scheduled_at": start}} for i in range(1, 7)
    ]
    entry = {"id": "12:34", "name": "Test", "last_seen": DAY.isoformat(),
             "draws": [{"rounds": [{"name": "Final", "matches": matches}]}]}
    snapshot = {"tournaments": [entry]}
    events = {str(i): {"id": i, "homeTeam": {"id": 10}, "awayTeam": {"id": 20},
                       "tournament": {"uniqueTournament": {"id": 12}}, "season": {"id": 34},
                       "scheduled_at": start, "status": {"type": "notstarted"}} for i in (1, 2, 3, 4, 6)}
    def predict(pair, context):
        return {"predicted_winner_id": "10", "probability": .6, "quality": {"band": "medium"},
                "model_version": "fixture", "source": "comparator"}
    for _ in range(2):
        update_bracket_predictions(snapshot, {}, events, {}, predict, lambda: now, lambda: True)
    assert len(entry["predictions"]) == 5
    witness = {"provider_home_id": "10", "provider_away_id": "20", "actual_started_at": start}
    statuses = {
        "1": {**witness, "status": "win", "winner_id": "10"},
        "2": {**witness, "status": "loss", "winner_id": "20"},
        "4": {**witness, "status": "void"},
        "6": {**witness, "actual_started_at": now.isoformat(), "status": "win", "winner_id": "10"},
    }
    update_bracket_predictions(snapshot, {}, {}, statuses, predict, lambda: now, lambda: True)
    result = public_brackets(snapshot, DAY, analysis_allowed=True)["tournaments"][0]["tournament_stats"]
    assert result[0]["items"][0]["value"] == "50,0 %"
    assert result[0]["items"][0]["hint"] == "1 z 2 vyhodnotených"
    assert [item["value"] for item in result[1]["items"]] == [1, 1, 1]
    assert "tournament_stats" not in public_brackets(snapshot, DAY)["tournaments"][0]




def test_standalone_fixture_uses_confirmed_offer_before_local_comparator():
    now = datetime(2026, 11, 25, 10, tzinfo=timezone.utc)
    start = "2026-11-25T11:00:00+00:00"
    match = {"event_id": "7", "players": [{"id": "10"}, {"id": "20"}]}
    entry = {"id": "12:34", "name": "Test", "last_seen": DAY.isoformat(),
             "draws": [{"rounds": [{"name": "Final", "matches": [match]}]}]}
    snapshot = {"tournaments": [entry]}
    event = {"id": 7, "homeTeam": {"id": 10}, "awayTeam": {"id": 20},
             "tournament": {"uniqueTournament": {"id": 12}}, "season": {"id": 34},
             "scheduled_at": start, "status": {"type": "notstarted"}}
    samples = {"matches": 30, "surface_matches": 15}
    feed = {"top_daily_picks": [{
        "event_id": 7, "issued_at": now.isoformat(), "publication_status": "published",
        "player1": {"id": "20"}, "player2": {"id": "10"}, "winner_id": "20",
        "blinq_probability": .62, "model_version": "fixture", "odds": 1.85,
        "quality": {"player1": samples, "player2": samples},
    }]}

    def predict(*_):
        raise AssertionError("confirmed offer takes precedence")

    # A stale notstarted status plus a positive kickoff witness cannot freeze.
    update_bracket_predictions(snapshot, feed, {"7": {**event, "actual_started_at": now.isoformat()}},
                               {}, predict, lambda: now, lambda: True)
    assert not entry["predictions"]
    update_bracket_predictions(snapshot, feed, {"7": event}, {}, predict, lambda: now, lambda: True)
    frozen = entry["predictions"]["7:10:20"]
    assert (frozen["source"], frozen["predicted_winner_id"], frozen["odds"]) == ("offer", "20", 1.85)

    # A scheduled timestamp in a terminal payload is insufficient to score.
    finished = {**event, "status": {"type": "finished"}, "winnerCode": 2}
    ended = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    update_bracket_predictions(snapshot, feed, {"7": finished}, {}, predict, lambda: ended, lambda: True)
    assert frozen["outcome"] == "pending"
    finished["actual_started_at"] = start
    update_bracket_predictions(snapshot, feed, {"7": finished}, {}, predict, lambda: ended, lambda: True)
    assert frozen["outcome"] == "correct"
    visible = public_brackets(snapshot, DAY, analysis_allowed=True)["tournaments"][0]
    hidden = public_brackets(snapshot, DAY)["tournaments"][0]
    assert "odds" not in visible["draws"][0]["rounds"][0]["matches"][0]["prediction"]
    assert "prediction" not in hidden["draws"][0]["rounds"][0]["matches"][0]
