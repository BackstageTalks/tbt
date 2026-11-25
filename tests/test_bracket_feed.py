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
