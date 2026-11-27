from datetime import date
from pathlib import Path

from build_bracket_feed import apply_settlement, build_feed, normalize_draws, write_atomic
from tbt.services.bracket import public_brackets


DAY = date(2026, 11, 25)
EVENT = {
    "id": 100, "roundInfo": {"name": "Semifinal"},
    "tournament": {"uniqueTournament": {"id": 12, "name": "Example Open"}},
    "season": {"id": 34},
    "homeTeam": {"id": 10}, "awayTeam": {"id": 20},
    "homeScore": {"period1": 4, "period2": 6},
    "awayScore": {"period1": 6, "period2": 7},
}
OFFER = {"daily_picks": [{"event_id": 100, "scheduled_at": "2026-11-25T11:00:00Z"}]}
CUP = {"cupTrees": [{"id": 9, "name": "Singles", "views": [[{
    "eventIds": [100], "round": {"description": "Semifinal"},
    "leftParticipant": {"team": {"id": 20, "name": "Away"}},
    "rightParticipant": {"team": {"id": 10, "name": "Home"}},
}]]}]}
SETTLED = {"status": "loss", "winner_id": "20", "provider_home_id": "10", "provider_away_id": "20"}


def test_analysis_context_requires_exact_native_participants_and_explicit_format():
    event = {
        **EVENT, "startTimestamp": 1795604400, "bestOf": 3, "groundType": "Hard",
        "tournament": {**EVENT["tournament"], "category": {"name": "ATP Challenger"}},
    }
    for raw, expected in (
        (event, "atp"),
        ({**event, "awayTeam": {"id": 99}}, None),
        ({**event, "bestOf": None}, None),
        ({**event, "tournament": {**event["tournament"], "category": {"name": "Challenger"}}}, None),
    ):
        snapshot, _ = build_feed(OFFER, {"events": [raw]}, {}, DAY, lambda *_: CUP, 1)
        node = snapshot["tournaments"][0]["draws"][0]["rounds"][0]["matches"][0]
        assert (node.get("analysis_context") or {}).get("tour") == expected
        if expected:
            assert node["analysis_context"]["best_of"] == 3
            assert node["analysis_context"]["surface"] == "hard"
            assert node["analysis_context"]["verified_at"]


def test_verified_context_rejects_conflicting_observations_and_other_editions():
    event = {
        **EVENT, "startTimestamp": 1795604400000, "bestOf": 5, "groundType": "Grass",
        "tournament": {**EVENT["tournament"], "category": {"name": "ATP"}},
    }

    def node(snapshot):
        return snapshot["tournaments"][0]["draws"][0]["rounds"][0]["matches"][0]

    first, _ = build_feed(OFFER, {"events": [event, event]}, {}, DAY, lambda *_: CUP, 1)
    context = node(first)["analysis_context"]
    assert context["best_of"] == 5
    assert context["surface"] == "grass"
    assert context["scheduled_at"].endswith("+00:00")
    unchanged, _ = build_feed(OFFER, {}, first, DAY, lambda *_: CUP, 0)
    assert node(unchanged)["analysis_context"] == context
    changed, _ = build_feed(
        OFFER, {"events": [event, {**event, "groundType": "Clay"}]}, first, DAY, lambda *_: CUP, 0,
    )
    assert "analysis_context" not in node(changed)
    changed, _ = build_feed(
        OFFER, {"events": [{**event, "season": {"id": 99}}]}, first, DAY, lambda *_: CUP, 0,
    )
    assert "analysis_context" not in node(changed)


def test_initial_and_new_round_only_with_no_pay_for_settlement():
    calls = []

    def fetch(tournament, season):
        calls.append((tournament, season))
        return CUP

    snapshot, _ = build_feed(OFFER, {"events": [EVENT]}, {}, DAY, fetch, 30)
    unchanged, _ = build_feed(OFFER, {"events": [EVENT], "statuses": {"100": SETTLED}}, snapshot, DAY, fetch, 30)
    assert calls == [("12", "34")]
    match = unchanged["tournaments"][0]["draws"][0]["rounds"][0]["matches"][0]
    assert match["event_id"] == "100"
    assert match["winner_id"] == "20"
    assert [player["score"] for player in match["players"]] == ["6 7", "4 6"]

    final = {**EVENT, "roundInfo": {"name": "Final"}}
    refreshed, _ = build_feed(OFFER, {"events": [final]}, unchanged, DAY, fetch, 30)
    assert calls == [("12", "34"), ("12", "34")]
    assert refreshed["tournaments"][0]["seen_rounds"] == ["final", "semifinal"]
    refreshed_match = refreshed["tournaments"][0]["draws"][0]["rounds"][0]["matches"][0]
    assert refreshed_match["winner_id"] == "20"
    assert refreshed_match["players"][0]["score"] == "6 7"


def test_scope_cap_and_empty_draw_attempt_deduplication():
    calls = []

    def empty(*args):
        calls.append(args)
        return {}

    unrelated = {**EVENT, "id": 200, "season": {"id": 99}}
    evidence = {"events": [EVENT, unrelated]}
    assert build_feed(OFFER, evidence, {}, DAY, empty, 0)[1]["cup_tree_attempts"] == 0
    snapshot, _ = build_feed(OFFER, evidence, {}, DAY, empty, 1)
    build_feed(OFFER, evidence, snapshot, DAY, empty, 1)
    assert calls == [("12", "34")]


def test_rejects_live_or_mismatched_evidence_and_ambiguous_event_ids():
    match = normalize_draws(CUP)[0]["rounds"][0]["matches"][0]
    apply_settlement(match, {**SETTLED, "status": "live"}, EVENT)
    apply_settlement(match, {**SETTLED, "provider_home_id": "30"}, EVENT)
    assert not match["winner_id"]
    apply_settlement(match, SETTLED, {**EVENT, "homeScore": {"period1": 4}})
    assert match["winner_id"] == "20"
    assert not any(player["score"] for player in match["players"])

    node = CUP["cupTrees"][0]["views"][0][0]
    team_cup = {"cupTrees": [{"id": 9, "views": [[{**node, "eventIds": [100, 101]}]]}]}
    assert normalize_draws(team_cup)[0]["rounds"][0]["matches"][0]["event_id"] == ""


def test_atomic_output_creates_static_sidecar(tmp_path: Path):
    output = tmp_path / "api" / "data" / "bracket.json"
    write_atomic(output, {"schema": 1})
    write_atomic(output, {"schema": 2})
    assert output.read_text() == '{"schema":2}'
    assert list(output.parent.iterdir()) == [output]


def test_deferred_tournament_is_loaded_on_a_later_tick_without_new_evidence():
    snapshot, report = build_feed(OFFER, {"events": [EVENT]}, {}, DAY, lambda *_: CUP, 0)
    assert report["cup_tree_attempts"] == 0
    assert public_brackets(snapshot, DAY)["tournaments"] == [
        {"id": "12:34", "name": "Example Open", "draws": []}
    ]

    snapshot, report = build_feed(OFFER, {}, snapshot, DAY, lambda *_: CUP, 1)
    assert report["cup_tree_attempts"] == 1
    assert public_brackets(snapshot, DAY)["tournaments"][0]["draws"]
    assert not public_brackets(snapshot, date(2026, 11, 26))["tournaments"]


def test_match_connections_follow_the_provider_tree():
    final = {
        "round": {"description": "Final"},
        "left": {"round": {"description": "Semifinal"}, "eventIds": [100]},
        "right": {"round": {"description": "Semifinal"}, "eventIds": [200]},
    }
    draw, = normalize_draws({"cupTrees": [{"id": 9, "views": [[final]]}]})
    semis, finals = draw["rounds"]
    final_match, = finals["matches"]
    assert {match["parent_id"] for match in semis["matches"]} == {final_match["id"]}
    assert len({match["id"] for match in semis["matches"]}) == 2
    assert not final_match["parent_id"]

def test_brackets_endpoint_requires_auth_and_only_reads_snapshot(monkeypatch):
    import json
    import azure.functions as func
    import function_app as app

    reads = []

    def read_snapshot():
        reads.append(True)
        today = app.datetime.now(app.BRATISLAVA).date().isoformat()
        return {"tournaments": [{
            "id": "12:34", "name": "Example Open", "last_seen": today,
            "draws": normalize_draws(CUP), "predictions": ["private"],
        }]}

    def provider_call(*args, **kwargs):
        raise AssertionError("The brackets endpoint cannot call TennisAPI")

    monkeypatch.setattr(app, "load_bracket_snapshot", read_snapshot)
    monkeypatch.setattr(app, "RapidTennisClient", provider_call)
    request = func.HttpRequest(method="GET", url="http://localhost/api/v1/brackets", body=b"")
    endpoint = app.tournament_brackets.build().get_user_function()
    monkeypatch.setattr(app, "_verified_user", lambda req: None)
    assert endpoint(request).status_code == 401
    assert not reads

    monkeypatch.setattr(app, "_verified_user", lambda req: {"id": "account"})
    result = endpoint(request)
    assert result.status_code == 200
    assert reads == [True]
    assert json.loads(result.get_body())["tournaments"] == [
        {"id": "12:34", "name": "Example Open", "draws": normalize_draws(CUP)},
    ]

def test_empty_cup_tree_displays_observed_players_and_progression():
    def fixture(event_id, players, round_name, winner=0, tournament_id=200):
        return {
            **EVENT, "id": event_id, "roundInfo": {"name": round_name},
            "tournament": {**EVENT["tournament"], "id": tournament_id, "name": "Example Singles"},
            "homeTeam": {"id": players[0], "name": f"Player {players[0]}"},
            "awayTeam": {"id": players[1], "name": f"Player {players[1]}"},
            "status": {"type": "finished" if winner else "notstarted"},
            "winnerCode": winner,
        }

    first = fixture(100, (10, 20), "Semifinals", 2)
    second = fixture(101, (30, 40), "Semifinal", 2)
    different_draw = fixture(102, (50, 60), "Final", tournament_id=202)
    snapshot, _ = build_feed(OFFER, {"events": [first, second, different_draw]}, {}, DAY, lambda *_: {}, 1)
    singles, other = public_brackets(snapshot, DAY)["tournaments"][0]["draws"]
    assert singles["partial"]
    semi, final = singles["rounds"]
    assert {match["parent_id"] for match in semi["matches"]} == {"final-slot"}
    assert semi["matches"][0]["players"][1]["score"] == "6 7"
    pending, = final["matches"]
    assert pending["pending_slot"] and not pending["event_id"]
    assert [player["id"] for player in pending["players"]] == ["20", "40"]
    assert other["rounds"][0]["matches"][0]["event_id"] == "102"

    published = fixture(103, (20, 40), "Final")
    snapshot, _ = build_feed(OFFER, {"events": [published]}, snapshot, DAY, lambda *_: {}, 0)
    singles = public_brackets(snapshot, DAY)["tournaments"][0]["draws"][0]
    semi, final = singles["rounds"]
    assert {match["parent_id"] for match in semi["matches"]} == {"103"}
    assert final["matches"][0]["event_id"] == "103"
    assert "pending_slot" not in final["matches"][0]
