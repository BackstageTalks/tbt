"""Research-only reanalysis archive. Never used as a pre-match forecast feature."""
import time
import unicodedata

import httpx

VARIABLES = ('temperature_2m', 'relative_humidity_2m', 'precipitation',
             'wind_speed_10m', 'surface_pressure', 'weather_code')


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold())
                   if not unicodedata.combining(c)).strip()


def explicit_location(match):
    raw = match.provider_payload or {}
    tournament = raw.get('tournament') or {}
    for obj in (raw.get('venue') or {}, tournament, tournament.get('uniqueTournament') or {}, raw):
        city = obj.get('city') or obj.get('venueCity')
        country = obj.get('country') or tournament.get('country') or {}
        if isinstance(city, str) and isinstance(country, dict):
            code = str(country.get('alpha2') or '').upper()
            if city.strip() and len(code) == 2 and code.isalpha():
                return city.strip(), code
    return None


class WeatherBudgetExhausted(RuntimeError):
    pass


class ArchiveClient:
    def __init__(self, limit=100, client=None):
        self.client = client or httpx.Client(timeout=25)
        self.limit, self.requests = limit, 0
        self.last = 0.

    def get(self, url, params):
        if self.requests >= self.limit:
            raise WeatherBudgetExhausted('Weather request cap reached')
        time.sleep(max(0., .75 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.requests += 1
        response = self.client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get('error'):
            raise ValueError('Invalid weather response')
        return payload

    def geocode(self, city, country):
        payload = self.get('https://geocoding-api.open-meteo.com/v1/search',
                           {'name': city, 'countryCode': country, 'count': 100, 'language': 'en'})
        candidates = [r for r in payload.get('results', [])
                      if normalized(r.get('name')) == normalized(city)
                      and r.get('country_code') == country]
        if len(candidates) != 1:
            return None
        row = candidates[0]
        lat, lon = float(row['latitude']), float(row['longitude'])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError('Invalid coordinates')
        return {'latitude': lat, 'longitude': lon, 'city': city, 'country': country,
                'elevation_m': row.get('elevation'), 'precision': 'city'}

    def day(self, location, day):
        payload = self.get('https://archive-api.open-meteo.com/v1/archive', {
            'latitude': location['latitude'], 'longitude': location['longitude'],
            'start_date': day, 'end_date': day, 'hourly': ','.join(VARIABLES), 'timezone': 'UTC'})
        hourly = payload.get('hourly') or {}
        times = hourly.get('time') or []
        if len(times) != 24 or any(not str(t).startswith(day + 'T') for t in times):
            raise ValueError('Incomplete weather day; retry later')
        if any(len(hourly.get(v, [])) != len(times) for v in VARIABLES):
            raise ValueError('Weather variables do not align')
        return {'time': times, **{v: hourly[v] for v in VARIABLES}}
