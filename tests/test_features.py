from tbt.models.feature_builder import FeatureBuilder


def test_same_day_results_are_not_used_as_features(match_factory):
    matches = [
        match_factory("m1", "A", "B", "A", day=1),
        match_factory("m2", "A", "C", "A", day=1),
        match_factory("m3", "A", "D", "A", day=2),
    ]
    frame = FeatureBuilder().build_training_frame(matches)
    assert frame.loc[0, "elo_diff"] == 0
    assert frame.loc[1, "elo_diff"] == 0
    assert abs(frame.loc[2, "elo_diff"]) > 0


def test_winner_first_provider_order_does_not_become_target_leakage(match_factory):
    matches = [
        match_factory(f"winner-first-{i}", f"A{i}", f"B{i}", f"A{i}", day=(i % 28) + 1)
        for i in range(800)
    ]
    frame = FeatureBuilder().build_training_frame(matches)
    rate = float(frame["target"].mean())
    assert 0.44 < rate < 0.56


def test_h2h_is_shrunk_for_tiny_samples(match_factory):
    builder = FeatureBuilder()
    first = match_factory("h1", "A", "B", "A", day=1)
    builder.update(first)
    next_match = match_factory("h2", "A", "B", None, day=2)
    advantage = builder.snapshot(next_match)["h2h_advantage"]
    assert 0 < advantage < 0.5


def test_posthoc_historical_weather_is_not_training_eligible(match_factory):
    match = match_factory("weather-posthoc", "A", "B", None, day=3)
    match.provider_payload = {
        "_tbt_environment": {
            "venue_resolved": True,
            "training_eligible_weather": False,
            "venue": {"latitude": 48.1, "longitude": 17.1, "elevation_m": 150.0},
            "weather": {
                "temperature_c": 33.0,
                "relative_humidity_pct": 80.0,
                "wind_speed_kmh": 45.0,
                "wind_gusts_kmh": 70.0,
                "surface_pressure_hpa": 995.0,
            },
        }
    }
    assert FeatureBuilder._weather_values(match) == {}


def test_explicitly_training_eligible_weather_can_be_read(match_factory):
    match = match_factory("weather-eligible", "A", "B", None, day=3)
    match.provider_payload = {
        "_tbt_environment": {
            "training_eligible_weather": True,
            "weather": {
                "temperature_c": 20.0,
                "relative_humidity_pct": 50.0,
                "wind_speed_kmh": 10.0,
                "wind_gusts_kmh": 20.0,
                "surface_pressure_hpa": 1010.0,
            },
        }
    }
    values = FeatureBuilder._weather_values(match)
    assert values["temperature_c"] == 20.0
    assert values["wind_speed_kmh"] == 10.0
