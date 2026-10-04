from __future__ import annotations

from datetime import datetime, timezone
import unittest
from types import SimpleNamespace

from enrich_environment_snapshot import VenueKnowledge, _needs_work
from tbt.services.environment import ARCHIVE_URL, ENVIRONMENT_SCHEMA_VERSION, OpenMeteoClient, Venue


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _ArchiveHTTP:
    def __init__(self):
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        if url != ARCHIVE_URL:
            raise AssertionError(f"unexpected URL: {url}")
        return _Response({
            "hourly": {
                "time": ["2025-06-01T12:00"],
                "temperature_2m": [30.0],
                "relative_humidity_2m": [40.0],
                "dew_point_2m": [14.9],
                "apparent_temperature": [29.5],
                "precipitation": [0.0],
                "cloud_cover": [20.0],
                "sunshine_duration": [3600.0],
                "wind_speed_10m": [18.0],
                "wind_direction_10m": [225.0],
                "wind_gusts_10m": [30.0],
                "surface_pressure": [900.0],
                "weather_code": [1],
            }
        })

    def close(self):
        pass


class ExtendedEnvironmentWeatherTests(unittest.TestCase):
    def test_era5_seamless_and_extended_weather_are_persistable(self):
        http = _ArchiveHTTP()
        client = OpenMeteoClient(
            request_limit=1,
            min_interval_seconds=0,
            client=http,
        )
        venue = Venue(
            query="Madrid, ES",
            name="Madrid",
            latitude=40.4168,
            longitude=-3.7038,
            elevation_m=667.0,
            timezone="Europe/Madrid",
            country="ES",
        )
        weather = client.weather_at(
            venue,
            datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(http.calls), 1)
        _, params = http.calls[0]
        self.assertEqual(params["models"], "era5_seamless")
        requested = set(params["hourly"].split(","))
        for key in (
            "dew_point_2m", "apparent_temperature", "cloud_cover",
            "sunshine_duration", "wind_direction_10m",
        ):
            self.assertIn(key, requested)
        self.assertEqual(weather.dew_point_c, 14.9)
        self.assertEqual(weather.cloud_cover_pct, 20.0)
        self.assertEqual(weather.wind_direction_deg, 225.0)
        self.assertIsNotNone(weather.air_density_kg_m3)
        self.assertIsNotNone(weather.density_altitude_m)
        self.assertGreater(weather.density_altitude_m, 0)

    def test_density_features_fail_closed_when_pressure_missing(self):
        class MissingPressureHTTP(_ArchiveHTTP):
            def get(self, url, params):
                response = super().get(url, params)
                response._payload["hourly"]["surface_pressure"] = [None]
                return response

        client = OpenMeteoClient(
            request_limit=1,
            min_interval_seconds=0,
            client=MissingPressureHTTP(),
        )
        venue = Venue("x", "x", 0.0, 0.0, 0.0, "UTC", "GB")
        weather = client.weather_at(
            venue,
            datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(weather.air_density_kg_m3)
        self.assertIsNone(weather.density_altitude_m)


class WeatherSchemaResumeTests(unittest.TestCase):
    def test_old_resolved_weather_is_selected_for_additive_upgrade(self):
        match = SimpleNamespace(
            tournament="Madrid",
            tournament_id=1,
            tour="ATP",
            indoor=False,
        )
        payload = {
            "_tbt_environment": {
                "schema_version": ENVIRONMENT_SCHEMA_VERSION - 1,
                "venue_resolved": True,
                "venue": {
                    "name": "Madrid",
                    "query": "Madrid, ES",
                    "latitude": 40.4168,
                    "longitude": -3.7038,
                    "country": "ES",
                },
                "weather": {
                    "temperature_c": 25.0,
                    "relative_humidity_pct": 40.0,
                    "wind_speed_kmh": 10.0,
                },
            }
        }
        selected, reason = _needs_work(
            match=match,
            payload=payload,
            knowledge=VenueKnowledge(),
            force=False,
            complete_static=False,
            retry_unresolved=True,
        )
        self.assertTrue(selected)
        self.assertEqual(reason, "weather_schema_upgrade")

    def test_current_extended_weather_does_not_repeat(self):
        match = SimpleNamespace(
            tournament="Madrid",
            tournament_id=1,
            tour="ATP",
            indoor=False,
        )
        payload = {
            "_tbt_environment": {
                "schema_version": ENVIRONMENT_SCHEMA_VERSION,
                "venue_resolved": True,
                "venue": {
                    "name": "Madrid",
                    "query": "Madrid, ES",
                    "latitude": 40.4168,
                    "longitude": -3.7038,
                    "country": "ES",
                },
                "weather": {
                    "dew_point_c": 10.0,
                    "apparent_temperature_c": 25.0,
                    "cloud_cover_pct": 10.0,
                    "wind_direction_deg": 180.0,
                    "air_density_kg_m3": 1.1,
                    "density_altitude_m": 900.0,
                },
            }
        }
        selected, reason = _needs_work(
            match=match,
            payload=payload,
            knowledge=VenueKnowledge(),
            force=False,
            complete_static=False,
            retry_unresolved=True,
        )
        self.assertFalse(selected)
        self.assertEqual(reason, "not_unresolved")


if __name__ == "__main__":
    unittest.main()
