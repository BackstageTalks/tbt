from tbt.services.entitlements import filter_feed_for_access, effective_plan


def row(i):
    return {"event_id": str(i), "winner_id": "a", "signals": ["x"], "betting": {"odds": 2.0},
            "player1": {"id": "a", "name": "A", "probability": .7},
            "player2": {"id": "b", "name": "B", "probability": .3}}


def feed(n=8):
    keys = ["prime_picks", "top_daily_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks"]
    payload = {key: [row(i) for i in range(n)] for key in keys}
    payload["upcoming"] = [row(i) for i in range(n)]
    payload["results"] = []
    return payload


def test_suspended_is_denied():
    try:
        filter_feed_for_access(feed(), {"status": "suspended", "plan": "pro"})
    except PermissionError:
        pass
    else:
        raise AssertionError("suspended account must be denied")


def test_rookie_never_receives_hidden_rows():
    data, manifest = filter_feed_for_access(feed(), {"status": "active", "plan": "rookie"})
    assert len(data["prime_picks"]) == 3
    assert len(data["top_daily_picks"]) == 2
    assert len(data["value_picks"]) == 1
    assert manifest["sections"]["prime"]["locked_count"] == 5


def test_trial_inherits_rookie_server_side():
    assert effective_plan({"status": "trial", "plan": "rookie"}) == "rookie"


def test_expired_has_only_explicit_free_subset():
    data, _ = filter_feed_for_access(feed(), {"status": "expired", "plan": "expired"})
    assert len(data["prime_picks"]) == 1
    assert len(data["top_daily_picks"]) == 0
    assert len(data["ace_picks"]) == 0


def test_elite_gets_full_curated_feed():
    data, _ = filter_feed_for_access(feed(), {"status": "active", "plan": "elite"})
    assert len(data["prime_picks"]) == 8
    assert len(data["sg_picks"]) == 8
