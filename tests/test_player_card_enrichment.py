from __future__ import annotations

import enrich_player_cards as enrichment


def test_ranking_row_parses_team_country_and_rank():
    row = {
        "team": {
            "id": 69208,
            "name": "Jasmine Paolini",
            "shortName": "J. Paolini",
            "country": {
                "alpha2": "IT",
                "alpha3": "ITA",
                "name": "Italy",
            },
        },
        "ranking": 21,
        "points": 2123,
        "previousRanking": 20,
        "bestRanking": 4,
    }
    profile = enrichment.profile_from_ranking_row(row, tour="wta")
    assert profile == {
        "id": "69208",
        "name": "Jasmine Paolini",
        "rank": 21,
        "country_code": "IT",
        "country_code3": "ITA",
        "country_name": "Italy",
        "tour": "WTA",
    }


def test_player_specific_ranking_can_use_known_id_when_history_row_omits_id():
    row = {
        "ranking": 21,
        "country": {"alpha2": "IT", "name": "Italy"},
    }
    profile = enrichment.profile_from_ranking_row(
        row, tour="wta", assumed_player_id="69208"
    )
    assert profile["id"] == "69208"
    assert profile["rank"] == 21
    assert profile["country_code"] == "IT"


def test_photo_extension_detects_provider_image_bytes():
    assert enrichment._photo_extension(b"\x89PNG\r\n\x1a\nrest", "image/png") == "png"
    assert enrichment._photo_extension(b"\xff\xd8\xffrest", "image/jpeg") == "jpg"
    assert enrichment._photo_extension(b"RIFFxxxxWEBPrest", "image/webp") == "webp"
    assert enrichment._photo_extension(b"not-an-image", "text/plain") is None


def test_current_players_are_unique_and_prioritised_by_confidence():
    feed = {
        "upcoming": [
            {
                "tour": "ATP",
                "confidence": 0.71,
                "player1": {"id": "10", "name": "Alpha"},
                "player2": {"id": "20", "name": "Beta"},
            },
            {
                "tour": "ATP",
                "confidence": 0.95,
                "player1": {"id": "10", "name": "Alpha"},
                "player2": {"id": "30", "name": "Gamma"},
            },
        ]
    }
    players = enrichment._current_players(feed)
    assert [row["id"] for row in players] == ["10", "30", "20"]
    assert players[0]["priority"] == 0.95
