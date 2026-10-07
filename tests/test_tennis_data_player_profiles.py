from scripts.link_tennis_data_player_profiles import clean_profile


def test_profile_validation_keeps_plausible_values():
    row = {
        "pl1_flag": "ESP",
        "pl1_year_pro": "2018",
        "pl1_weight": "72",
        "pl1_height": "185",
        "pl1_hand": "Right-Handed",
    }
    assert clean_profile(row, "pl1", match_year=2022) == {
        "country_alpha3": "ESP",
        "year_pro": 2018,
        "weight_kg": 72,
        "height_cm": 185,
        "hand": "right",
    }


def test_profile_validation_drops_implausible_values_field_by_field():
    row = {
        "pl1_flag": "E",
        "pl1_year_pro": "0",
        "pl1_weight": "7",
        "pl1_height": "70",
        "pl1_hand": "Unknown",
    }
    assert clean_profile(row, "pl1", match_year=2022) == {
        "country_alpha3": None,
        "year_pro": None,
        "weight_kg": None,
        "height_cm": None,
        "hand": None,
    }


def test_future_year_pro_is_rejected():
    row = {
        "pl2_flag": "USA",
        "pl2_year_pro": "2025",
        "pl2_weight": "80",
        "pl2_height": "190",
        "pl2_hand": "Left-Handed",
    }
    result = clean_profile(row, "pl2", match_year=2022)
    assert result["year_pro"] is None
    assert result["hand"] == "left"
