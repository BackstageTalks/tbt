from __future__ import annotations

"""Free environment/travel enrichment for TBT.

This module deliberately does NOT alter model probabilities by itself. It collects
real, timestamped external covariates that can be joined into the feature engine
and accepted only after chronological walk-forward validation.

Data source: Open-Meteo public APIs (geocoding, elevation, forecast/archive).
No API key is required.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx


GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


@dataclass(frozen=True)
class Venue:
    query: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float | None
    timezone: str | None
    country: str | None


@dataclass(frozen=True)
class WeatherAtMatch:
    temperature_c: float | None
    relative_humidity_pct: float | None
    precipitation_mm: float | None
    wind_speed_kmh: float | None
    wind_gusts_kmh: float | None
    surface_pressure_hpa: float | None
    weather_code: int | None
    source_time_utc: str | None


class OpenMeteoClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    @lru_cache(maxsize=512)
    def geocode(self, query: str) -> Venue | None:
        query = " ".join(str(query or "").split())
        if not query:
            return None
        response = self.client.get(
            GEOCODE_URL,
            params={"name": query, "count": 1, "language": "en", "format": "json"},
        )
        response.raise_for_status()
        rows = response.json().get("results") or []
        if not rows:
            # Tournament labels often start with the event name. Retry the
            # location-like suffix after the first comma.
            if "," in query:
                shorter = query.split(",", 1)[1].strip()
                if shorter and shorter != query:
                    return self.geocode(shorter)
            return None

        row = rows[0]
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        elevation = row.get("elevation")
        if elevation is None:
            elevation = self.elevation(lat, lon)

        return Venue(
            query=query,
            name=str(row.get("name") or query),
            latitude=lat,
            longitude=lon,
            elevation_m=float(elevation) if elevation is not None else None,
            timezone=row.get("timezone"),
            country=row.get("country"),
        )

    @lru_cache(maxsize=2048)
    def elevation(self, latitude: float, longitude: float) -> float | None:
        response = self.client.get(
            ELEVATION_URL, params={"latitude": latitude, "longitude": longitude}
        )
        response.raise_for_status()
        values = response.json().get("elevation")
        if isinstance(values, list) and values:
            try:
                return float(values[0])
            except (TypeError, ValueError):
                return None
        return None

    def weather_at(self, venue: Venue, scheduled_at: datetime) -> WeatherAtMatch:
        scheduled_at = scheduled_at.astimezone(timezone.utc)
        day = scheduled_at.date().isoformat()
        now_day = datetime.now(timezone.utc).date()
        base_url = ARCHIVE_URL if scheduled_at.date() < now_day else FORECAST_URL

        hourly = ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "wind_speed_10m",
                "wind_gusts_10m",
                "surface_pressure",
                "weather_code",
            ]
        )
        response = self.client.get(
            base_url,
            params={
                "latitude": venue.latitude,
                "longitude": venue.longitude,
                "start_date": day,
                "end_date": day,
                "hourly": hourly,
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        data = response.json().get("hourly") or {}
        times = data.get("time") or []
        if not times:
            return WeatherAtMatch(None, None, None, None, None, None, None, None)

        target = scheduled_at.replace(minute=0, second=0, microsecond=0)
        parsed = []
        for idx, value in enumerate(times):
            try:
                dt = datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
                parsed.append((abs((dt - target).total_seconds()), idx, dt))
            except ValueError:
                continue
        if not parsed:
            return WeatherAtMatch(None, None, None, None, None, None, None, None)

        _, idx, source_time = min(parsed)

        def num(key: str) -> float | None:
            arr = data.get(key) or []
            if idx >= len(arr) or arr[idx] is None:
                return None
            try:
                return float(arr[idx])
            except (TypeError, ValueError):
                return None

        code = num("weather_code")
        return WeatherAtMatch(
            temperature_c=num("temperature_2m"),
            relative_humidity_pct=num("relative_humidity_2m"),
            precipitation_mm=num("precipitation"),
            wind_speed_kmh=num("wind_speed_10m"),
            wind_gusts_kmh=num("wind_gusts_10m"),
            surface_pressure_hpa=num("surface_pressure"),
            weather_code=int(code) if code is not None else None,
            source_time_utc=source_time.isoformat(),
        )


def haversine_km(a: Venue, b: Venue) -> float:
    radius_km = 6371.0088
    lat1, lon1, lat2, lon2 = map(
        radians, [a.latitude, a.longitude, b.latitude, b.longitude]
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(h))


def environment_payload(
    client: OpenMeteoClient,
    tournament_location: str,
    scheduled_at: datetime,
) -> dict[str, Any]:
    venue = client.geocode(tournament_location)
    if venue is None:
        return {"venue_resolved": False, "query": tournament_location}

    weather = client.weather_at(venue, scheduled_at)
    return {
        "venue_resolved": True,
        "venue": asdict(venue),
        "weather": asdict(weather),
        "match_hour_utc": scheduled_at.astimezone(timezone.utc).hour,
    }
