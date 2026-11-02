"""Frozen Telegram ACE O/U issuance must settle the same contract on web."""
from copy import deepcopy

from prepare_feed import overlay_confirmed_telegram_aces_ou
from tbt.services.match_status import runtime_settled_results


def fixture():
    event = "17449526"
    hurkacz = "158896"
    match = {
        "event_id": event, "scheduled_at": "2026-11-02T10:00:00+00:00",
        "player1": {"id": "musetti", "name": "Lorenzo Musetti"},
        "player2": {"id": hurkacz, "name": "Hubert Hurkacz"},
        "selection_id": hurkacz, "market": "aces", "projection": 10.9,
        "market_publications": [{
            "section": "ace", "market": "aces", "selection_id": hurkacz,
            "price_contract": "player_superiority",
            "projection": 10.9, "publication_status": "published",
            "issued_at": "2026-11-02T05:37:35+00:00",
            "publication_key": f"ace:projection:aces:player:{event}:{hurkacz}",
            "price_status": "projection_only",
        }],
    }
    ref = {
        "channel": "aces", "market": "aces", "event_id": event,
        "selection_id": hurkacz, "name": "Hubert Hurkacz",
        "publication_key": f"local-aces-ou-v1:{event}:{hurkacz}:over:10.5",
        "market_line": 10.5, "projection_direction": "over",
        "scheduled_at": match["scheduled_at"],
        "odds": 1.80, "projection": 10.9,
        "price_basis": "local_aces_statistical_v1",
    }
    state = {"schema": 1, "reposts": {"2026-11-02:repost:aces-player-ou-20261102-v1": {
        "status": "sent", "supersedes_daily": True,
        "sent_at": "2026-11-02T09:27:02.743369+00:00",
        "message_ids": [100, 101], "rows": [ref],
    }}}
    status = {event: {
        "status": "win", "provider_home_id": "musetti",
        "provider_away_id": hurkacz, "projection_stats_p1_id": "musetti",
        "projection_stats_p2_id": hurkacz,
        "projection_stats": {"p1_aces": 5.0, "p2_aces": 9.0},
        "checked_at": "2026-11-02T12:00:00+00:00",
    }}
    return match, state, status


def test_frozen_telegram_over_10_5_is_web_loss_even_if_hurkacz_served_more():
    match, state, status = fixture()
    feed = {"ace_picks": [match], "results": []}
    frozen = deepcopy(feed)
    new_feed = overlay_confirmed_telegram_aces_ou(feed, state)
    assert feed == frozen  # no changes to private source
    pubs = new_feed["ace_picks"][0]["market_publications"]
    assert len(pubs) == 2
    assert pubs[0]["price_contract"] == "player_superiority"
    assert pubs[1]["market_line"] == 10.5
    assert pubs[1]["ou_side"] == "over" and pubs[1]["odds"] == 1.8
    rows = runtime_settled_results(new_feed, status)
    assert len(rows) == 1
    scored = rows[0]["market_publications"]
    assert len(scored) == 1
    result = scored[0]["result"]
    assert result["status"] == "miss" and result["correct"] is False
    assert result["actual_count"] == 9
    assert result["opponent_actual_count"] == 5
    assert result["staked_units"] == 1.0 and result["profit_units"] == -1.0
    assert overlay_confirmed_telegram_aces_ou(new_feed, state)["ace_picks"] == new_feed["ace_picks"]


def test_missing_or_late_reissue_never_invents_historical_ou():
    match, state, status = fixture()
    feed = {"ace_picks": [match], "results": []}
    unconfirmed = deepcopy(state)
    batch = next(iter(unconfirmed["reposts"].values()))
    batch["status"] = "reserved"
    assert overlay_confirmed_telegram_aces_ou(feed, unconfirmed) == feed
    after_start = deepcopy(state)
    next(iter(after_start["reposts"].values()))["sent_at"] = "2026-11-02T11:00:00+00:00"
    assert overlay_confirmed_telegram_aces_ou(feed, after_start) == feed
    wrong_player = deepcopy(state)
    next(iter(wrong_player["reposts"].values()))["rows"][0]["selection_id"] = "other"
    assert overlay_confirmed_telegram_aces_ou(feed, wrong_player) == feed
    assert runtime_settled_results(feed, status) == []
