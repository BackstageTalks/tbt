from datetime import date

from scripts.link_livetennisapi_player_profiles import clean_profile


def test_clean_profile_keeps_valid_public_metadata():
    row = {
        "player_id": "123",
        "country": "SVK",
        "birthday": "2000-01-02",
        "hand": "R",
        "sackmann_id": "104925",
    }
    assert clean_profile(row, event_date=date(2026, 1, 1)) == {
        "country_alpha3": "SVK",
        "birth_date": "2000-01-02",
        "hand": "right",
        "sackmann_id": "104925",
        "livetennisapi_player_id": "123",
    }


def test_clean_profile_drops_invalid_fields():
    row = {
        "player_id": "",
        "country": "SK",
        "birthday": "2030-01-01",
        "hand": "X",
        "sackmann_id": "abc",
    }
    assert clean_profile(row, event_date=date(2026, 1, 1)) == {
        "country_alpha3": None,
        "birth_date": None,
        "hand": None,
        "sackmann_id": None,
        "livetennisapi_player_id": None,
    }
