"""Strict candidate gates for CDB player identity reconciliation."""
from audit_cdb_identity_reconciliation import (
    abbreviation, full_initial, propose_candidates, compare_events, evaluate_pair,
)


def _row(pid, name, tour="atp"):
    return {"player_id": pid, "name": name, "tour": tour}


def _match(mid, opponent="Smith", day="2026-06-12", winner=True, surface="hard"):
    return {"match_id": mid, "date": day, "opponent": opponent.lower(),
            "opponent_id": "opponent-id", "tournament": "london",
            "round": "r32", "surface": surface, "won": winner}


def test_exact_full_name_provider_to_history_candidate():
    players = {"players": [_row("main-1", "Cameron Norrie"),
                           _row("hist-js:atp:N771", "Cameron Norrie")]}
    links, conflicts = propose_candidates(players)
    assert links[("atp", "hist-js:atp:N771")][0] == "main-1"
    assert not conflicts["nonunique_full_name_owner"]


def test_initial_requires_unique_target():
    players = {"players": [_row("p1", "Francisco Cerundolo"),
                           _row("p2", "Juan Manuel Cerundolo"),
                           _row("hist-js:atp:c", "Cerundolo F.")]}
    links, _ = propose_candidates(players)
    assert links[("atp", "hist-js:atp:c")][0] == "p1"
    players["players"].append(_row("p3", "Federico Cerundolo"))
    links, flags = propose_candidates(players)
    assert ("atp", "hist-js:atp:c") not in links
    assert flags["ambiguous_initial_surname"] >= 1


def test_two_identical_events_are_required_not_just_name_or_rank():
    primary = [_match("main-1"), _match("main-2", day="2026-06-14")]
    shadow = [_match("legacy-1"), _match("legacy-2", day="2026-06-14")]
    assert evaluate_pair(shadow, primary)["eligible"] is True
    assert evaluate_pair(shadow[:1], primary)["eligible"] is False
    assert evaluate_pair([_match("a")], [])["eligible"] is False


def test_conflicts_fail_closed_even_with_two_good_matches():
    primary = [_match("p1"), _match("p2", day="2026-06-14"),
               _match("p3", day="2026-06-15")]
    shadow = [_match("s1"), _match("s2", day="2026-06-14"),
              _match("s3", day="2026-06-15", winner=False)]
    result = evaluate_pair(shadow, primary)
    assert result["overlap"] == 2
    assert result["conflict"] == 1
    assert result["eligible"] is False


def test_same_day_name_opponent_is_not_sufficient():
    a = _match("a")
    b = _match("b", surface="clay")
    assert compare_events(a,b) == "conflict"
    assert compare_events(a,_match("c", opponent="Jones")) == "unrelated"


def test_cross_tour_ids_never_link():
    players = {"players": [_row("atp-player", "Alex One", "atp"),
                           _row("hist-js:wta:one", "Alex One", "wta")]}
    links,_ = propose_candidates(players)
    assert not links
