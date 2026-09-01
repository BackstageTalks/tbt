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
        "startTimestamp": 1748868600,
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
        "startTimestamp": 1748868600,
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
        "startTimestamp": 1748868600,
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
