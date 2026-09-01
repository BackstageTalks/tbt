from tbt.providers.rapidapi import RapidTennisClient


def test_historical_archive_marks_player1_as_winner():
    raw = {
        "id": 999,
        "date": "2025-06-02",
        "player1": {"id": 10, "name": "Winner"},
        "player2": {"id": 20, "name": "Loser"},
        "result": "6-4 6-3",
        "roundId": 4,
        "tournament": {"id": 77, "name": "Test", "court": {"name": "Hard"}},
    }
    match = RapidTennisClient.normalize_match(raw, "atp", historical=True)
    assert match.winner_id == "10"
    assert match.surface == "hard"


def test_canonical_id_survives_winner_first_reordering():
    upcoming = {
        "id": "today-123",
        "date": "2025-06-02T15:30:00Z",
        "player1": {"id": 10, "name": "A"},
        "player2": {"id": 20, "name": "B"},
        "roundId": 4,
        "tournament": {"id": 77, "name": "Test"},
    }
    historical = {
        "id": "game-987",
        "date": "2025-06-02",
        "player1": {"id": 20, "name": "B"},
        "player2": {"id": 10, "name": "A"},
        "roundId": 4,
        "result": "6-4 6-4",
        "tournament": {"id": 77, "name": "Test"},
    }
    before = RapidTennisClient.normalize_match(upcoming, "atp", historical=False)
    after = RapidTennisClient.normalize_match(historical, "atp", historical=True)
    assert before.match_id == after.match_id
    assert before.winner_id is None
    assert after.winner_id == "20"
