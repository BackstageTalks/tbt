from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
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
        self.client = httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": "TBT environment-enrichment"},
        )

    def close(self) -> None:
        self.client.close()

    @lru_cache(maxsize=2048)
    def geocode(self, query: str) -> Venue | None:
        query = " ".join(str(query or "").split())
        if not query:
            return None

        response = self.client.get(
            GEOCODE_URL,
            params={"name": query, "count": 5, "language": "en", "format": "json"},
        )
        response.raise_for_status()
        rows = response.json().get("results") or []
        if not rows:
            return None

        row = rows[0]
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        elevation = row.get("elevation")
        if elevation is None:
            elevation = self.elevation(latitude, longitude)

        return Venue(
            query=query,
            name=str(row.get("name") or query),
            latitude=latitude,
            longitude=longitude,
            elevation_m=float(elevation) if elevation is not None else None,
            timezone=row.get("timezone"),
            country=row.get("country"),
        )

    @lru_cache(maxsize=4096)
    def elevation(self, latitude: float, longitude: float) -> float | None:
        response = self.client.get(
            ELEVATION_URL,
            params={"latitude": latitude, "longitude": longitude},
        )
        response.raise_for_status()
        values = response.json().get("elevation")
        if isinstance(values, list) and values:
            try:
                return float(values[0])
            except (TypeError, ValueError):
                return None
        return None

    @lru_cache(maxsize=32768)
    def _weather_hour(
        self,
        latitude: float,
        longitude: float,
        hour_utc_iso: str,
    ) -> WeatherAtMatch:
        scheduled = datetime.fromisoformat(hour_utc_iso).astimezone(timezone.utc)
        day = scheduled.date().isoformat()
        base_url = (
            ARCHIVE_URL
            if scheduled.date() < datetime.now(timezone.utc).date()
            else FORECAST_URL
        )

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
                "latitude": latitude,
                "longitude": longitude,
                "start_date": day,
                "end_date": day,
                "hourly": hourly,
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        data = response.json().get("hourly") or {}
        times = data.get("time") or []
        target = scheduled.replace(minute=0, second=0, microsecond=0)

        candidates: list[tuple[float, int, datetime]] = []
        for idx, value in enumerate(times):
            try:
                dt = datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
                candidates.append((abs((dt - target).total_seconds()), idx, dt))
            except ValueError:
                continue

        if not candidates:
            return WeatherAtMatch(None, None, None, None, None, None, None, None)

        _, idx, source_time = min(candidates)

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

    def weather_at(self, venue: Venue, scheduled_at: datetime) -> WeatherAtMatch:
        hour = scheduled_at.astimezone(timezone.utc).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        return self._weather_hour(
            round(venue.latitude, 5),
            round(venue.longitude, 5),
            hour.isoformat(),
        )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}



_GENERIC_TOURNAMENT_TOKENS = {
    "atp", "wta", "men", "women", "mens", "womens", "qualifying", "qualification",
    "singles", "doubles", "open", "grand slam",
}

# Aliases are only added after they are observed in real provider data and fail the
# geocoder in their provider spelling. Keep this intentionally small and auditable.
_LOCATION_ALIASES = {
    "winston salem": "Winston-Salem",
}


def _clean_location_token(value: Any) -> str:
    text = " ".join(str(value or "").replace("_", " ").split()).strip(" ,-()")
    return text


def _location_from_tournament_name(name: Any) -> list[str]:
    """Extract explicit city/country text embedded in a tournament label.

    Example: ``US Open, New York, USA, Qualifying`` -> ``New York, USA``.
    This does not infer a venue; it only reuses location words present in provider data.
    """
    text = _clean_location_token(name)
    if not text or "," not in text:
        return []

    parts = [_clean_location_token(p) for p in text.split(",")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return []

    usable: list[str] = []
    for idx, part in enumerate(parts):
        low = part.lower()
        if idx == 0 and ("open" in low or low in _GENERIC_TOURNAMENT_TOKENS):
            continue
        if low in _GENERIC_TOURNAMENT_TOKENS or "qualif" in low:
            continue
        usable.append(part)

    if not usable:
        return []

    out: list[str] = []
    # Prefer city + country when both are explicitly present.
    if len(usable) >= 2:
        out.append(f"{usable[0]}, {usable[1]}")
    out.append(usable[0])
    return out


def _query_variants(query: str) -> list[str]:
    variants = [query]
    alias = _LOCATION_ALIASES.get(query.lower())
    if alias and alias.lower() != query.lower():
        variants.insert(0, alias)
    return variants

def location_candidates(
    provider_payload: dict[str, Any],
    tournament: str = "",
) -> list[str]:
    """Build factual venue queries from provider data; never invent a city."""

    raw = _as_dict(provider_payload)
    tournament_obj = _as_dict(raw.get("tournament"))
    unique = _as_dict(tournament_obj.get("uniqueTournament"))
    venue = _as_dict(raw.get("venue"))
    country = _as_dict(tournament_obj.get("country")) or _as_dict(unique.get("country"))

    candidates: list[str] = []

    def add(value: Any) -> None:
        text = _clean_location_token(value)
        if text and text.lower() not in {item.lower() for item in candidates}:
            candidates.append(text)

    venue_name = venue.get("name") or venue.get("city")
    venue_city = venue.get("city")
    venue_country = _as_dict(venue.get("country")).get("name") or venue.get("countryName")
    if venue_city and venue_country:
        add(f"{venue_city}, {venue_country}")
    if venue_name and venue_country:
        add(f"{venue_name}, {venue_country}")
    add(venue_name)

    city = (
        tournament_obj.get("city")
        or unique.get("city")
        or raw.get("city")
        or raw.get("venueCity")
    )
    country_name = (
        country.get("name")
        or raw.get("countryName")
        or _as_dict(raw.get("country")).get("name")
    )
    if city and country_name:
        add(f"{city}, {country_name}")
    add(city)

    # Many TennisApi rows omit venue/city fields but embed a real location in the
    # tournament label. Extract only those explicit tokens before trying competition
    # names such as "US Open, Men" which are not geocodable places.
    for source_name in (
        tournament_obj.get("name"),
        tournament,
        unique.get("name"),
    ):
        for parsed in _location_from_tournament_name(source_name):
            add(parsed)

    # Raw labels remain last-resort queries for place-named tournaments like Monterrey.
    add(unique.get("name"))
    add(tournament_obj.get("name"))
    add(tournament)
    return candidates


def resolve_match_venue(
    client: OpenMeteoClient,
    provider_payload: dict[str, Any],
    tournament: str,
) -> tuple[Venue | None, str | None]:
    for raw_query in location_candidates(provider_payload, tournament):
        for query in _query_variants(raw_query):
            venue = client.geocode(query)
            if venue is not None:
                return venue, query
    return None, None


def environment_payload(
    client: OpenMeteoClient,
    provider_payload: dict[str, Any],
    tournament: str,
    scheduled_at: datetime,
) -> dict[str, Any]:
    venue, query = resolve_match_venue(client, provider_payload, tournament)
    if venue is None:
        return {
            "venue_resolved": False,
            "location_query": None,
            "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "open-meteo",
        }

    weather = client.weather_at(venue, scheduled_at)
    return {
        "venue_resolved": True,
        "location_query": query,
        "venue": asdict(venue),
        "weather": asdict(weather),
        "match_hour_utc": scheduled_at.astimezone(timezone.utc).hour,
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "open-meteo",
    }
