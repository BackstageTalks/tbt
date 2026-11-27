from datetime import datetime, timedelta, timezone

from tbt.data.court_speed import court_speed_display_prior
from tbt.schemas import MatchRecord
from tbt.services.comparator_card import match_card_context


NOW = datetime(2026, 11, 27, tzinfo=timezone.utc)


def test_fixture_context_only_exposes_exact_future_authorized_predictions():
    result = {"player1": {"player_id": "11"}, "player2": {"player_id": "22"},
              "tour": "atp", "surface": "hard",
              "_court_speed_display": {"as_of": NOW.isoformat(), "venues": {
                  "atp|fixture open|hard": {"value": 104.2, "matches": 7, "scope": "venue_history"}
              }}}
    row = {"event_id": "1", "player1": {"id": "22"}, "player2": {"id": "11"},
           "tour": "ATP", "surface": "hard", "indoor": False, "tournament": "Fixture Open",
           "scheduled_at": (NOW + timedelta(hours=1)).isoformat(),
           "issued_at": NOW.isoformat(), "publication_status": "published", "selection_id": "11",
           "blinq_probability": 0.67, "odds": 1.82}
    context = match_card_context(result, feed={"daily_picks": [row], "upcoming": [row]}, event_id="1", now=NOW)
    assert context["setting"] == "outdoor"
    assert context["court_speed"]["value"] == 104.2
    assert (context["blinq_probability"], context["odds"], context["selection_id"]) == (.67, 1.82, "11")
    for feed, event_id, now in (
        ({"upcoming": [row]}, "1", NOW),
        ({"daily_picks": [row]}, "2", NOW),
        ({"daily_picks": [row]}, "1", NOW + timedelta(hours=1)),
        ({"daily_picks": [{**row, "player1": {"id": "33"}}]}, "1", NOW),
        ({"daily_picks": [row, {**row, "odds": 1.97}]}, "1", NOW),
        ({"daily_picks": [{**row, "issued_at": (NOW + timedelta(minutes=1)).isoformat()}]}, "1", NOW),
    ):
        hidden = match_card_context(result, feed=feed, event_id=event_id, now=now)
        assert hidden["odds"] is None and hidden["blinq_probability"] is None


def test_venue_prior_ignores_target_and_requires_minimum_sample():
    rows = [MatchRecord(
        match_id=str(i), tour="atp", scheduled_at=NOW - timedelta(days=i),
        player1_id="11", player1_name="A", player2_id="22", player2_name="B",
        surface="hard", tournament="Fixture Open" if i < 6 else "Other",
        winner_id="11", status="completed", stats={"p1_service_points_won": 0.7},
    ) for i in range(21)]
    rows[0].stats["p1_service_points_won"] = 100.0
    prior = court_speed_display_prior(rows, NOW)["venues"]["atp|fixture open|hard"]
    assert prior == {"value": 100.0, "matches": 5, "scope": "venue_history"}
    assert "atp|fixture open|hard" not in court_speed_display_prior(rows[2:], NOW)["venues"]


def test_offer_visibility_is_rechecked_per_caller_on_shared_pair_cache(monkeypatch):
    from types import SimpleNamespace
    import function_app as api

    now = datetime.now(timezone.utc)
    row = {"event_id": "123", "player1": {"id": "11"}, "player2": {"id": "22"},
           "surface": "hard", "tour": "ATP",
           "scheduled_at": (now + timedelta(hours=2)).isoformat(),
           "issued_at": (now - timedelta(minutes=2)).isoformat(), "publication_status": "published",
           "winner_id": "11", "blinq_probability": .72, "odds": 1.8}
    compared = {"player1": {"player_id": "11"}, "player2": {"player_id": "22"},
                "surface": "hard", "tour": "atp", "match_context": {}}
    calls = []
    monkeypatch.setattr(api, "_comparator_user", lambda req, feature: ({}, None))
    monkeypatch.setattr(api, "_COMPARATOR_RESULT_CACHE", {})
    monkeypatch.setattr(api, "_load_comparator_players", lambda: {"generated_at": "test", "model_version": "v"})
    monkeypatch.setattr(api, "load_pair_artifact", lambda *a, **kw: {"court_speed_display": {"venues": {}}})
    monkeypatch.setattr(api, "compare_from_artifact", lambda *a, **kw: (calls.append(1) or dict(compared)))
    monkeypatch.setattr(api, "_authorized_feed_payload",
                        lambda req: {"daily_picks": [row]} if req.account == "allowed" else {"upcoming": [row]})
    monkeypatch.setattr(api, "response", lambda body, status=200: body)
    payload = {"player1_id": "11", "player2_id": "22", "event_id": "123",
               "tour": "atp", "surface": "hard"}

    def make_request(account):
        return SimpleNamespace(params={}, get_json=lambda: payload, account=account)

    first = api.comparator_compare(make_request("allowed"))
    second = api.comparator_compare(make_request("hidden"))
    assert first["cache"] == "miss" and first["match_context"]["odds"] == 1.8
    assert second["cache"] == "hit" and second["match_context"]["odds"] is None
    assert second["match_context"]["blinq_probability"] is None
    assert "_court_speed_display" not in first and "_court_speed_display" not in second
    assert calls == [1]
