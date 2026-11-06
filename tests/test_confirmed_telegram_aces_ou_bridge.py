"""Frozen Telegram ACE O/U issuance must settle the same contract on web."""
from copy import deepcopy

from prepare_feed import overlay_confirmed_telegram_aces_ou
from tbt.services.match_status import runtime_settled_results, attach_confirmed_aces_ou_sidecar


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




def test_sidecar_preserves_canonical_feed_and_replays_exact_frozen_ou():
    match, state, status = fixture()
    canonical = {"ace_picks": [match], "results": []}
    presentation = overlay_confirmed_telegram_aces_ou(canonical, state)
    pub = presentation["ace_picks"][0]["market_publications"][-1]
    sidecar = {"schema": 1, "issued_aces_ou": [{
        "event_id": match["event_id"], "selection_id": match["selection_id"],
        "scheduled_at": match["scheduled_at"], "projection": match["projection"],
        "publication": pub,
    }]}
    initial = deepcopy(canonical)
    served = attach_confirmed_aces_ou_sidecar(canonical, sidecar)
    assert canonical == initial
    assert served == presentation
    settled = runtime_settled_results(served, status)
    assert settled[0]["market_publications"][0]["result"]["status"] == "miss"
    assert settled[0]["market_publications"][0]["result"]["profit_units"] == -1.0
    assert attach_confirmed_aces_ou_sidecar(served, sidecar) == served
    invalid = deepcopy(sidecar)
    invalid["issued_aces_ou"][0]["projection"] = 14.0
    assert attach_confirmed_aces_ou_sidecar(canonical, invalid) == canonical


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

def test_farjat_confirmed_over_4_5_reissue_wins_after_retirement():
    """Exact sent receipt is Over 4.5, NOT the 5.49 model projection shown as 5.5."""
    event, farjat, opponent = "17467964", "270414", "206594"
    canonical = {
        "generated_at": "2026-11-02T05:12:06Z",
        "results": [],
        "ace_picks": [{
            "event_id": event, "scheduled_at": "2026-11-02T13:00:00+00:00",
            "player1": {"id": farjat, "name": "Tomas Farjat"},
            "player2": {"id": opponent, "name": "Federico Aguilar Cardozo"},
            "selection_id": farjat, "winner_id": opponent, "market": "aces", "projection": 5.49,
            "market_publications": [{
                "section": "ace", "market": "aces", "selection_id": farjat,
                "price_contract": "player_superiority",
                "projection": 5.49, "publication_status": "published",
                "issued_at": "2026-11-02T05:37:35.400107+00:00",
                "publication_key": f"ace:projection:aces:player:{event}:{farjat}",
                "price_status": "projection_only",
            }],
        }],
    }
    receipt = {
        "schema": 1, "reposts": {
            "2026-11-02:repost:aces-player-ou-20261102-v1": {
                "status": "sent", "supersedes_daily": True,
                "message_ids": [727, 728],
                "sent_at": "2026-11-02T09:27:02.743369+00:00",
                "rows": [{
                    "event_id": event, "section": "ace", "channel": "aces",
                    "market": "aces", "selection_id": farjat, "name": "Tomas Farjat",
                    "publication_key": f"local-aces-ou-v1:{event}:{farjat}:over:4.5",
                    "market_line": 4.5, "projection_direction": "over",
                    "scheduled_at": "2026-11-02T13:00:00+00:00",
                    "odds": 1.79, "price_basis": "local_aces_statistical_v1",
                    "projection": 5.49,
                }],
            }
        },
    }
    archived_original = deepcopy(canonical)
    bridged = overlay_confirmed_telegram_aces_ou(canonical, receipt)
    assert canonical == archived_original
    expected = bridged["ace_picks"][0]["market_publications"][-1]
    assert expected["market_line"] == 4.5 and expected["ou_side"] == "over"
    assert expected["price_basis"] == "local_aces_statistical_v1"
    assert expected["odds"] == 1.79
    sidecar = {"schema": 1, "issued_aces_ou": [{
        "event_id": event, "selection_id": farjat,
        "scheduled_at": "2026-11-02T13:00:00+00:00",
        "projection": 5.49, "publication": expected,
    }]}
    restored = attach_confirmed_aces_ou_sidecar(canonical, sidecar)
    assert restored == bridged
    assert attach_confirmed_aces_ou_sidecar(restored, sidecar) == restored
    status = {event: {
        "status": "retired", "provider_status": "finished retired",
        "provider_home_id": farjat, "provider_away_id": opponent,
        "projection_stats_p1_id": farjat,
        "projection_stats_p2_id": opponent,
        "projection_stats": {"p1_aces": 7.0, "p2_aces": 0.0},
        "checked_at": "2026-11-02T17:45:41Z",
    }}
    results = runtime_settled_results(restored, status)
    assert len(results) == 1
    publications = results[0]["market_publications"]
    assert len(publications) == 1  # superseded old Aces bet must not create a second VOID
    verified = [p for p in publications if p.get("price_contract") == "player_total_ou"]
    assert len(verified) == 1
    outcome = verified[0]["result"]
    assert outcome["correct"] is True and outcome["void"] is False
    assert outcome["retirement_line_decided"] is True
    assert outcome["actual_count"] == 7
    assert outcome["profit_units"] == 0.79


def test_entire_20261102_confirmed_aces_reissue_grades_only_played_verified_bets():
    """All issued O/U selections, with actual provider counts from 2 Nov snapshot.

    The fifth player, Barton, stays pending until terminal verified statistics
    exist. Match-winner TOP/VALUE/FREE picks are not changed.
    """
    player_cases = [
        # event, picked, other, threshold, odds, actual picked, actual other,
        # retired, expected settlement, profit (stake=1)
        ("17468525", "289146", "355096", 12.5, 1.75, 26, 7, False, True, .75),
        ("17449526", "158896", "261015", 10.5, 1.80, 9, 5, False, False, -1.0),
        ("17467964", "270414", "206594", 4.5, 1.79, 7, 0, True, True, .79),
        ("17457727", "341853", "407164", 7.5, 1.72, 7, 5, False, False, -1.0),
    ]
    feed = {"generated_at": "2026-11-02T05:12:06Z", "ace_picks": [], "results": [],
            "top_daily_picks": [{"event_id": "17467283", "pick": "Danka Kovinic"}]}
    sent_rows = []
    statuses = {}
    for event, selected, opponent, threshold, odds, count, other, retired, correct, profit in player_cases:
        publication_id = f"local-aces-ou-v1:{event}:{selected}:over:{threshold:.1f}"
        row = {
            "event_id": event, "scheduled_at": "2026-11-02T13:00:00+00:00",
            "player1": {"id": selected}, "player2": {"id": opponent},
            "selection_id": selected, "winner_id": opponent, "market": "aces",
            "projection": threshold + .4,
        }
        feed["ace_picks"].append(row)
        sent_rows.append({
            "event_id": event, "selection_id": selected, "section": "ace",
            "market": "aces", "channel": "aces",
            "publication_key": publication_id, "market_line": threshold,
            "projection_direction": "over", "odds": odds,
            "scheduled_at": row["scheduled_at"], "projection": row["projection"],
            "name": "Frozen Aces selection", "price_basis": "local_aces_statistical_v1",
        })
        statuses[event] = {
            "status": "retired" if retired else "win",
            "provider_status": "finished retired" if retired else "finished ended",
            "provider_home_id": selected, "provider_away_id": opponent,
            "projection_stats_p1_id": selected,
            "projection_stats_p2_id": opponent,
            "projection_stats": {"p1_aces": count, "p2_aces": other},
            "checked_at": "2026-11-02T17:45:41Z",
        }
    # The fifth issued pick has not finished and therefore cannot be graded.
    pending = {
        "event_id": "17456687", "scheduled_at": "2026-11-02T19:00:00Z",
        "player1": {"id": "372310"}, "player2": {"id": "other"},
        "market": "aces", "selection_id": "372310", "projection": 6.57,
    }
    feed["ace_picks"].append(pending)
    sent_rows.append({
        "event_id": "17456687", "selection_id": "372310", "section": "ace",
        "market": "aces", "channel": "aces",
        "publication_key": "local-aces-ou-v1:17456687:372310:over:6.5",
        "market_line": 6.5, "projection_direction": "over", "odds": 1.6,
        "scheduled_at": pending["scheduled_at"], "projection": 6.57,
        "name": "Hynek Barton", "price_basis": "local_aces_statistical_v1",
    })
    state = {
        "schema": 1, "reposts": {
            "2026-11-02:repost:aces-player-ou-20261102-v1": {
                "status": "sent", "supersedes_daily": True,
                "message_ids": [727, 728],
                "sent_at": "2026-11-02T09:27:02.743369+00:00",
                "rows": sent_rows,
            },
        },
    }
    frozen = deepcopy(feed)
    bridged = overlay_confirmed_telegram_aces_ou(feed, state)
    assert feed == frozen
    assert bridged["top_daily_picks"] == frozen["top_daily_picks"]
    sidecar = {"schema": 1, "issued_aces_ou": [
        {
            "event_id": row["event_id"], "selection_id": row["selection_id"],
            "scheduled_at": row["scheduled_at"], "projection": row["projection"],
            "publication": pub,
        }
        for row in bridged["ace_picks"]
        for pub in row.get("market_publications") or []
        if pub.get("source") == "confirmed_telegram_ou_reissue"
    ]}
    assert len(sidecar["issued_aces_ou"]) == 5
    served = attach_confirmed_aces_ou_sidecar(feed, sidecar)
    assert served == bridged
    results = runtime_settled_results(served, statuses)
    actual = {
        p["publication_key"]: p["result"]
        for row in results for p in row.get("market_publications") or []
        if p.get("price_contract") == "player_total_ou"
    }
    assert len(actual) == 4
    for event, selected, opponent, threshold, odds, count, other, retired, correct, profit in player_cases:
        pubkey = f"local-aces-ou-v1:{event}:{selected}:over:{threshold:.1f}"
        outcome = actual[pubkey]
        assert outcome["correct"] is correct and outcome["void"] is False
        assert outcome["actual_count"] == count
        assert outcome["staked_units"] == 1.0
        assert abs(outcome["profit_units"] - profit) < 1e-9
    assert "local-aces-ou-v1:17456687:372310:over:6.5" not in actual


def test_regular_confirmed_daily_aces_ou_receipt_bridges_exact_contract():
    """Normal 06:20 daily Telegram picks must not stay ungradable."""
    match, reissue_state, statuses = fixture()
    feed = {"ace_picks": [match], "results": []}
    confirmed = deepcopy(next(iter(reissue_state["reposts"].values())))
    confirmed.pop("supersedes_daily")
    state = {"schema": 1, "attempts": {"2026-11-02:daily:0620": confirmed},
             "reposts": {}}
    before = deepcopy(feed)
    bridged = overlay_confirmed_telegram_aces_ou(feed, state)
    assert feed == before
    pub = bridged["ace_picks"][0]["market_publications"][-1]
    assert pub["publication_key"] == confirmed["rows"][0]["publication_key"]
    assert pub["price_contract"] == "player_total_ou"
    assert pub["market_line"] == 10.5 and pub["ou_side"] == "over"
    graded = runtime_settled_results(bridged, statuses)
    assert graded[0]["market_publications"][0]["result"]["correct"] is False
    assert graded[0]["market_publications"][0]["result"]["actual_count"] == 9


def test_superseding_aces_reissue_does_not_grade_original_daily_line():
    match, state, _ = fixture()
    feed = {"ace_picks": [match], "results": []}
    old = deepcopy(next(iter(state["reposts"].values())))
    old["sent_at"] = "2026-11-02T05:37:35+00:00"
    old.pop("supersedes_daily")
    old["rows"][0]["market_line"] = 11.5
    old["rows"][0]["publication_key"] = old["rows"][0]["publication_key"].replace(
        "over:10.5", "over:11.5"
    )
    state["attempts"] = {"2026-11-02:daily:0620": old}
    bridged = overlay_confirmed_telegram_aces_ou(feed, state)
    new_key = next(iter(state["reposts"].values()))["rows"][0]["publication_key"]
    pubs = [p for p in bridged["ace_picks"][0]["market_publications"]
            if p.get("price_contract") == "player_total_ou"]
    assert len(pubs) == 1
    assert pubs[0]["publication_key"] == new_key
    assert pubs[0]["market_line"] == 10.5


def test_unconfirmed_daily_aces_receipt_never_creates_published_contract():
    match, state, _ = fixture()
    feed = {"ace_picks": [match], "results": []}
    old = deepcopy(next(iter(state["reposts"].values())))
    old.pop("supersedes_daily")
    old["message_ids"] = []
    state = {"schema": 1, "attempts": {"2026-11-02:daily:0620": old}}
    assert overlay_confirmed_telegram_aces_ou(feed, state) == feed


def test_confirmed_telegram_ou_survives_later_model_projection_drift():
    """Only the frozen receipt/publication pair decides what was issued.

    A later model recalculation cannot erase the already-issued Over/Under.
    Tampered receipt/publication pairs still fail closed.
    """
    match, state, status = fixture()
    original = {"ace_picks": [match], "results": []}
    issued = overlay_confirmed_telegram_aces_ou(original, state)
    publication = issued["ace_picks"][0]["market_publications"][-1]
    sidecar = {"schema": 1, "issued_aces_ou": [{
        "event_id": match["event_id"], "selection_id": match["selection_id"],
        "scheduled_at": match["scheduled_at"],
        "projection": match["projection"], "publication": publication,
    }]}
    # Daily re-training after 06:20 changes the visible MODEL projection,
    # but it does not change the already-confirmed Telegram betting contract.
    updated = deepcopy(original)
    updated["ace_picks"][0]["projection"] = 12.74
    frozen = deepcopy(updated)
    # Preparation itself must link the original confirmed publication, without
    # mutating the newer model prediction or deriving a new market line.
    bridged = overlay_confirmed_telegram_aces_ou(updated, state)
    assert updated == frozen
    assert bridged["ace_picks"][0]["projection"] == 12.74
    assert bridged["ace_picks"][0]["market_publications"][-1] == publication
    assert publication["projection"] == match["projection"] == 10.9
    served = attach_confirmed_aces_ou_sidecar(updated, sidecar)
    assert updated == frozen
    assert served["ace_picks"][0]["market_publications"][-1] == publication
    assert len(served["ace_picks"][0]["market_publications"]) == 2
    scored = runtime_settled_results(served, status)
    assert scored[0]["market_publications"][0]["result"]["correct"] is False
    assert scored[0]["market_publications"][0]["result"]["actual_count"] == 9

    forged = deepcopy(sidecar)
    forged["issued_aces_ou"][0]["publication"]["projection"] = 12.74
    assert attach_confirmed_aces_ou_sidecar(updated, forged) == updated
    forged = deepcopy(sidecar)
    forged["issued_aces_ou"][0]["publication"]["publication_key"] = "unrelated-ou"
    assert attach_confirmed_aces_ou_sidecar(updated, forged) == updated
    # This cannot create a second conflicting issued O/U when an exact one exists.
    already_issued = attach_confirmed_aces_ou_sidecar(updated, sidecar)
    assert attach_confirmed_aces_ou_sidecar(already_issued, forged) == already_issued


def test_telegram_receipt_rejects_same_event_player_when_start_time_changed():
    match, state, _ = fixture()
    original = {"ace_picks": [match], "results": []}
    changed = deepcopy(original)
    changed["ace_picks"][0]["scheduled_at"] = "2026-11-02T11:00:00+00:00"
    assert overlay_confirmed_telegram_aces_ou(changed, state) == changed
    assert original["ace_picks"][0]["scheduled_at"] == "2026-11-02T10:00:00+00:00"
