from datetime import date
from types import SimpleNamespace
import httpx
from date_window import history_window
from tbt.services.weather_archive import ArchiveClient, explicit_location


def test_rolling_window_crosses_year_and_leap_day():
    assert history_window(lookback_days=365, today=date(2027, 1, 1)) == (date(2026, 1, 1), date(2026, 12, 31))
    assert history_window(lookback_days=2, today=date(2024, 3, 1)) == (date(2024, 2, 28), date(2024, 2, 29))


def test_weather_does_not_guess_venue_from_tournament_title():
    assert explicit_location(SimpleNamespace(provider_payload={'tournament': {'name': 'Paris Open'}})) is None


def test_ambiguous_geocoding_is_rejected():
    rows = [{'name': 'Paris', 'country_code': 'FR', 'latitude': 48, 'longitude': 2}] * 2
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'results': rows}))) as client:
        archive = ArchiveClient(1, client)
        assert archive.geocode('Paris', 'FR') is None
        assert archive.requests == 1
