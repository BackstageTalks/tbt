from tbt.providers.rapidapi import RapidTennisClient


def test_historical_event_uses_winner_code():
    raw = {
        "id": 999,
        "startTimestamp": 1748844000,
        "homeTeam": {"id": 10, "name": "Winner", "ranking": 12},
        "awayTeam": {"id": 20, "name": "Loser", "ranking": 27},
        "winnerCode": 1,
        "status": {"type": "finished"},
        "roundInfo": {"name": "Round of 16"},
        "tournament": {
            "id": 77,
            "name": "Test",
            "groundType": "Hard",
            "category": {"name": "ATP"},
        },
    }

    match = RapidTennisClient.normalize_match(raw, "atp", historical=True)

    assert match.winner_id == "10"
    assert match.surface == "hard"
    assert match.player1_id == "10"
    assert match.player2_id == "20"

    # Historical ranking snapshots are not trusted unless the provider can
    # guarantee they represent the ranking at the event date.  Dropping them
    # prevents current-ranking leakage into historical training rows.
    assert match.player1_rank is None
    assert match.player2_rank is None


def test_historical_event_can_mark_away_player_as_winner():
    raw = {
        "id": 1000,
        "startTimestamp": 1748844000,
        "homeTeam": {"id": 10, "name": "Player A"},
        "awayTeam": {"id": 20, "name": "Player B"},
        "winnerCode": 2,
        "status": {"type": "finished"},
        "roundInfo": {"name": "Quarterfinal"},
        "tournament": {
            "id": 77,
            "name": "Test",
            "groundType": "Clay",
            "category": {"name": "ATP"},
        },
    }

    match = RapidTennisClient.normalize_match(raw, "atp", historical=True)

    assert match.winner_id == "20"
    assert match.surface == "clay"


def test_upcoming_event_has_no_winner():
    raw = {
        "id": "today-123",
        "startTimestamp": 1748868630,
        "homeTeam": {"id": 10, "name": "A", "ranking": 1},
        "awayTeam": {"id": 20, "name": "B", "ranking": 2},
        "status": {"type": "notstarted"},
        "roundInfo": {"name": "Round 3"},
        "tournament": {
            "id": 77,
            "name": "Test",
            "groundType": "Hard",
            "category": {"name": "ATP"},
        },
    }

    match = RapidTennisClient.normalize_match(raw, "atp", historical=False)

    assert match.winner_id is None
    assert match.player1_rank == 1
    assert match.player2_rank == 2


def test_canonical_id_survives_home_away_reordering():
    upcoming = {
        "id": "today-123",
        "startTimestamp": 1748868630,
        "homeTeam": {"id": 10, "name": "A"},
        "awayTeam": {"id": 20, "name": "B"},
        "status": {"type": "notstarted"},
        "roundInfo": {"name": "Round 3"},
        "tournament": {
            "id": 77,
            "name": "Test",
            "groundType": "Hard",
            "category": {"name": "ATP"},
        },
    }

    historical = {
        "id": "game-987",
        "startTimestamp": 1748868630,
        "homeTeam": {"id": 20, "name": "B"},
        "awayTeam": {"id": 10, "name": "A"},
        "winnerCode": 1,
        "status": {"type": "finished"},
        "roundInfo": {"name": "Round 3"},
        "tournament": {
            "id": 77,
            "name": "Test",
            "groundType": "Hard",
            "category": {"name": "ATP"},
        },
    }

    before = RapidTennisClient.normalize_match(upcoming, "atp", historical=False)
    after = RapidTennisClient.normalize_match(historical, "atp", historical=True)

    assert before.match_id == after.match_id
    assert before.winner_id is None
    assert after.winner_id == "20"



def test_provider_infers_missing_best_of_for_normal_atp_and_wta():
    base = {
        "id": "format-1",
        "startTimestamp": 1748868630,
        "homeTeam": {"id": 10, "name": "A"},
        "awayTeam": {"id": 20, "name": "B"},
        "status": {"type": "notstarted"},
        "roundInfo": {"name": "Quarterfinal"},
        "tournament": {"id": 77, "name": "Test Open", "groundType": "Hard"},
    }
    atp = RapidTennisClient.normalize_match(base, "atp", historical=False)
    wta = RapidTennisClient.normalize_match({**base, "id": "format-2"}, "wta", historical=False)
    assert atp.best_of == 3
    assert wta.best_of == 3


def test_provider_infers_atp_grand_slam_main_draw_bo5_but_qualifying_bo3():
    base = {
        "id": "slam-1",
        "startTimestamp": 1748868630,
        "homeTeam": {"id": 10, "name": "A"},
        "awayTeam": {"id": 20, "name": "B"},
        "status": {"type": "notstarted"},
        "tournament": {
            "id": 77, "name": "US Open", "groundType": "Hard",
            "category": {"name": "ATP"},
        },
    }
    main = RapidTennisClient.normalize_match(
        {**base, "roundInfo": {"name": "Round of 16"}}, "atp", historical=False
    )
    qualifying = RapidTennisClient.normalize_match(
        {**base, "id": "slam-q", "roundInfo": {"name": "Qualification round 2"}},
        "atp", historical=False,
    )
    assert main.best_of == 5
    assert qualifying.best_of == 3


def test_provider_explicit_best_of_overrides_inference():
    raw = {
        "id": "explicit-format",
        "startTimestamp": 1748868630,
        "homeTeam": {"id": 10, "name": "A"},
        "awayTeam": {"id": 20, "name": "B"},
        "status": {"type": "notstarted"},
        "bestOf": 3,
        "roundInfo": {"name": "Round of 16"},
        "tournament": {"id": 77, "name": "Wimbledon", "groundType": "Grass"},
    }
    match = RapidTennisClient.normalize_match(raw, "atp", historical=False)
    assert match.best_of == 3

def test_current_ranking_and_market_enrichment_endpoints(monkeypatch):
    client = object.__new__(RapidTennisClient)
    calls = []

    def fake_get(path, params=None, *, enrichment=False):
        calls.append((path, enrichment))
        if path == "/api/tennis/rankings/atp/":
            return {"rankings": [{"team": {"id": 10}, "ranking": 1}]}
        if path.endswith("/rankings"):
            return {"rankings": [{"ranking": 7}]}
        if "/odds/1/all" in path:
            return {"markets": []}
        if path.endswith("/statistics"):
            return {"statistics": []}
        return {}

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.rankings("atp")[0]["ranking"] == 1
    assert client.player_rankings(10)["rankings"][0]["ranking"] == 7
    assert client.event_odds(99, 1) == {"markets": []}
    assert client.event_statistics(99) == {"statistics": []}
    assert calls == [
        ("/api/tennis/rankings/atp/", True),
        ("/api/tennis/player/10/rankings", True),
        ("/api/tennis/event/99/odds/1/all", True),
        ("/api/tennis/event/99/statistics", True),
    ]


def test_data_unwraps_rankings_list():
    rows = RapidTennisClient._data({"rankings": [{"ranking": 1}, {"ranking": 2}]})
    assert [row["ranking"] for row in rows] == [1, 2]


def test_tournament_logo_prefers_dark_and_falls_back_to_regular(monkeypatch):
    client = object.__new__(RapidTennisClient)
    calls = []

    def fake_bytes(path, *, enrichment=False):
        calls.append((path, enrichment))
        if path.endswith('/image/dark'):
            return None
        return (b'logo', 'image/png')

    monkeypatch.setattr(client, '_get_bytes', fake_bytes)
    assert client.tournament_logo(2371) == (b'logo', 'image/png')
    assert calls == [
        ('/api/tennis/tournament/2371/image/dark', True),
        ('/api/tennis/tournament/2371/image', True),
    ]


def test_tournament_logo_stops_after_dark_variant(monkeypatch):
    client = object.__new__(RapidTennisClient)
    calls = []

    def fake_bytes(path, *, enrichment=False):
        calls.append((path, enrichment))
        return (b'dark-logo', 'image/webp')

    monkeypatch.setattr(client, '_get_bytes', fake_bytes)
    assert client.tournament_logo(2368) == (b'dark-logo', 'image/webp')
    assert calls == [('/api/tennis/tournament/2368/image/dark', True)]


def test_provider_monthly_calendar_batch_caches_only_complete_valid_days(monkeypatch):
    from datetime import date
    client = object.__new__(RapidTennisClient)
    client._category_cache = {}
    days = [date(2026, 11, n) for n in range(1, 6)]
    calls = []

    def fake_get(path, params=None, *, enrichment=False):
        calls.append((path, params))
        assert path == "/api/tennis/calendar/11/2026/categories"
        assert params == {"days": "1,2,3,4,5"}
        return {day.isoformat(): {"categories": [
            {"category": {"id": 3, "name": "ATP"}}
        ]} for day in days}
    monkeypatch.setattr(client, "_get", fake_get)
    assert client.prefetch_calendar_categories(days[::-1]) == 5
    for day in days:
        assert client.calendar_categories(day)[0]["category"]["id"] == 3
    assert len(calls) == 1
    assert client.calendar_batch_metrics["days_cached"] == 5


def test_provider_monthly_batch_missing_date_or_duplicate_id_falls_back(monkeypatch):
    from datetime import date
    client = object.__new__(RapidTennisClient)
    client._category_cache = {}
    days = [date(2026, 11, 1), date(2026, 11, 2)]
    payloads = [
        {days[0].isoformat(): {"categories": [{"id": 3}]}},
        {d.isoformat(): {"categories": [{"id": 3}, {"id": 3}]}
         for d in days},
        {},
    ]
    def fake_get(path, params=None, *, enrichment=False):
        if "/calendar/11/2026/" in path:
            return payloads.pop(0)
        assert path == "/api/tennis/calendar/1/11/2026/categories"
        return {"categories": [{"id": 6}]}
    monkeypatch.setattr(client, "_get", fake_get)
    for _ in range(3):
        assert client.prefetch_calendar_categories(days) == 0
        assert client._category_cache == {}
    assert client.calendar_categories(days[0]) == [{"id": 6}]
    assert client.calendar_batch_metrics["invalid_responses"] == 3


def test_provider_monthly_batch_preserves_shared_quota_stop(monkeypatch):
    from datetime import date
    import pytest
    from tbt.providers.budget import RequestBudgetExceeded
    client = object.__new__(RapidTennisClient)
    client._category_cache = {}
    def fail(*args, **kwargs):
        raise RequestBudgetExceeded("provider reserve reached")
    monkeypatch.setattr(client, "_get", fail)
    days = [date(2026, 11, 1), date(2026, 11, 2)]
    with pytest.raises(RequestBudgetExceeded):
        client.prefetch_calendar_categories(days)
    assert client._category_cache == {}
    with pytest.raises(ValueError):
        client.prefetch_calendar_categories([date(2026, 10, 31), days[0]])
