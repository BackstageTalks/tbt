"""Today’s live ESÁ balls must not leave the new VIAC ES offer empty.

A source O/U is already issued. Its leader marker may be shown as a *signal*,
not a second published bet. No changing ledger, Results or arbitrary tiers.
"""
from copy import deepcopy

from tbt.services.ace_winner_bridge import with_issued_ace_leader_signals
from tbt.services.entitlements import filter_feed_for_access, _published_daily_pick_count


NAMES = ("Alexander Donski", "Lorenzo Sonego", "Colin Sinclair", "Sebastian Dominko")


def _aces(event: str, leader: str, *, gap: float = 3.2):
    return {
        "event_id": event, "scheduled_at": "2026-11-08T16:00:00+00:00",
        "surface": "hard", "market": "aces",
        "player1": {"id": f"{event}-p1", "name": "Opponent"},
        "player2": {"id": f"{event}-p2", "name": leader},
        "selection_id": f"{event}-p2", "pick": leader,
        "selection": leader, "aces_superiority_hint": leader,
        "projection_model": "ace-count-projection-v4",
        "projection_subject": leader,
        "projection": 7.2, "opponent_projection": 7.2 - gap,
        "projection_confidence": .835,
        "price_contract": "player_total_ou", "price_status": "priced_projection",
        "market_line": 5.5, "ou_side": "over",
        "odds": 1.7, "betting": {"selection": leader, "market": "aces"},
        "market_publications": [{
            "section": "ace", "market": "aces", "selection_id": f"{event}-p2",
            "selection": leader, "publication_key": f"ace:issued:{event}",
            "price_contract": "player_total_ou", "odds": 1.7,
            "publication_status": "published",
            "issued_at": "2026-11-08T07:00:00+00:00",
        }],
    }


def _fixture():
    return {
        "ace_picks": [_aces(str(i), name) for i, name in enumerate(NAMES)],
        "daily_picks": [], "top_daily_picks": [], "prime_picks": [],
        "value_picks": [], "doubles_picks": [], "sg_picks": [], "results": [],
    }


def test_four_existing_issued_balls_are_visible_in_more_aces_without_extra_bets():
    source = _fixture()
    before = deepcopy(source)
    bridged = with_issued_ace_leader_signals(source)
    assert source == before  # no mutation of the issued source
    assert len(bridged["ace_picks"]) == 8
    assert [x["pick"] for x in bridged["ace_picks"] if x["market"] == "most_aces"] == list(NAMES)
    for row in bridged["ace_picks"][4:]:
        assert row["projection"] > row["opponent_projection"]
        assert row["price_contract"] == "player_superiority"
        assert row["price_status"] == "projection_only"
        assert row["ace_winner_issued"] is False
        assert row["ace_winner_source_publication"].startswith("ace:issued:")
        assert row["odds"] is None and row["market_line"] is None
        assert row["market_publications"] == [] and row["result"] is None
    assert bridged["results"] == source["results"]
    assert _published_daily_pick_count(bridged) == _published_daily_pick_count(source) == 4


def test_existing_independently_issued_winner_does_not_mix_with_fallback():
    payload = _fixture()
    payload["ace_picks"].append({"market": "most_aces", "event_id": "new"})
    assert with_issued_ace_leader_signals(payload) is payload


def test_unissued_stale_ambiguous_or_wrong_player_sources_are_never_promoted():
    rows = [
        _aces("valid", "Leader"),
        _aces("pending", "Pending"),
        _aces("after", "Late"),
        _aces("wrong", "Not leader"),
        _aces("tie", "Tie", gap=0),
        _aces("duplicate", "Duplicate"),
        _aces("duplicate", "Duplicate"),
    ]
    rows[1]["market_publications"][0]["publication_status"] = "pending"
    rows[2]["market_publications"][0]["issued_at"] = "2026-11-08T17:00:00Z"
    rows[3]["aces_superiority_hint"] = "Opponent"
    payload = {"ace_picks": rows}
    derived = with_issued_ace_leader_signals(payload)["ace_picks"][len(rows):]
    assert [row["event_id"] for row in derived] == ["valid"]


def test_both_plans_are_checked_by_normal_server_entitlement_filter():
    source = with_issued_ace_leader_signals(_fixture())
    cfg = {"dashboard": {"daily_hub": {"tabs": {
        "ace": {"plans": {
            "pro": {"visible_rows": "ALL", "display_state": "active"},
            "elite": {"visible_rows": "ALL", "display_state": "active"},
        }},
        "ace_winner": {"enabled": True, "plans": {
            "pro": {"visible_rows": 0, "display_state": "active"},
            "elite": {"visible_rows": "ALL", "display_state": "active"},
        }},
    }}}}
    pro, pro_access = filter_feed_for_access(source, {"plan": "pro", "status": "active"}, cfg)
    elite, elite_access = filter_feed_for_access(source, {"plan": "elite", "status": "active"}, cfg)
    assert not any(r.get("market") == "most_aces" for r in pro["ace_picks"])
    assert len([r for r in elite["ace_picks"] if r.get("market") == "most_aces"]) == 4
    assert pro_access["sections"]["ace_winner"]["returned"] == 0
    assert elite_access["sections"]["ace_winner"]["returned"] == 4
    assert pro["results"] == elite["results"] == []


def test_deployed_legacy_feed_can_have_pending_nested_publications_but_issued_authority():
    # Actual serving flow: asset is generated first, then the exact row is
    # confirmed after deployment. Its embedded candidate is still pending.
    src = _fixture()
    src["generated_at"] = "2026-11-08T05:07:24Z"
    src["publication_authority_status"] = "confirmed"
    src["ace_picks"][0]["market_publications"][0]["publication_status"] = "pending"
    src["ace_picks"][0]["market_publications"][0]["issued_at"] = None
    src["ace_picks"][1]["market_publications"] = []
    converted = with_issued_ace_leader_signals(src)
    assert len([r for r in converted["ace_picks"] if r["market"] == "most_aces"]) == 4
    assert converted["ace_picks"][4]["ace_winner_issued"] is False
    assert converted["ace_picks"][5]["ace_winner_source_publication"] == ""

    # Authority missing or created after the match => fail closed.
    without_authority = deepcopy(src)
    without_authority["publication_authority_status"] = "unavailable"
    rows = with_issued_ace_leader_signals(without_authority)["ace_picks"]
    assert len([r for r in rows if r["market"] == "most_aces"]) == 2

    after_start = deepcopy(src)
    after_start["generated_at"] = "2026-11-08T17:00:00Z"
    rows = with_issued_ace_leader_signals(after_start)["ace_picks"]
    assert len([r for r in rows if r["market"] == "most_aces"]) == 2
