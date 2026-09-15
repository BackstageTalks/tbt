from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
import time
import unicodedata
import re

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ENVIRONMENT_SCHEMA_VERSION = 2


class OpenMeteoBudgetExceeded(RuntimeError):
    pass


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


def _normal(value: Any) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value or "").casefold())
        if not unicodedata.combining(c)
    ).strip()


class OpenMeteoClient:
    def __init__(
        self,
        timeout_seconds: float = 25.0,
        *,
        request_limit: int | None = None,
        min_interval_seconds: float = 0.75,
        client: httpx.Client | None = None,
    ) -> None:
        if request_limit is not None and request_limit < 1:
            raise ValueError("request_limit must be positive when set")
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": "TBT environment-enrichment"},
        )
        self.request_limit = int(request_limit) if request_limit is not None else None
        self.request_count = 0
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.request_limit is not None and self.request_count >= self.request_limit:
            raise OpenMeteoBudgetExceeded("Open-Meteo request cap reached")
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()
        self.request_count += 1
        response = self.client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Invalid Open-Meteo response")
        return payload

    @lru_cache(maxsize=4096)
    def geocode(self, query: str) -> Venue | None:
        query = " ".join(str(query or "").split())
        if not query:
            return None

        parts = [p.strip() for p in query.split(",") if p.strip()]
        name = parts[0]
        qualifiers = parts[1:]
        country_hint = ""
        region_hint = ""
        if qualifiers:
            if len(qualifiers[-1]) == 2 and qualifiers[-1].isalpha():
                country_hint = qualifiers[-1]
                if len(qualifiers) >= 2:
                    region_hint = qualifiers[-2]
            elif len(qualifiers) == 1:
                country_hint = qualifiers[0]
            else:
                country_hint = qualifiers[-1]
                region_hint = qualifiers[-2]

        params: dict[str, Any] = {
            "name": name,
            "count": 20,
            "language": "en",
            "format": "json",
        }
        if len(country_hint) == 2 and country_hint.isalpha():
            params["countryCode"] = country_hint.upper()

        rows = self._get(GEOCODE_URL, params).get("results") or []
        if not isinstance(rows, list):
            return None

        exact = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _normal(row.get("name")) != _normal(name):
                continue
            if country_hint:
                country_values = {
                    _normal(row.get("country")),
                    _normal(row.get("country_code")),
                }
                if _normal(country_hint) not in country_values:
                    continue
            if region_hint:
                region_values = {
                    _normal(row.get("admin1")),
                    _normal(row.get("admin2")),
                    _normal(row.get("admin3")),
                }
                if _normal(region_hint) not in region_values:
                    continue
            exact.append(row)

        # Fail closed on ambiguity. We never pick "the first" city silently.
        if len(exact) != 1:
            return None
        row = exact[0]

        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Invalid geocoding coordinates")

        elevation = row.get("elevation")
        if elevation is None:
            elevation = self.elevation(latitude, longitude)

        return Venue(
            query=query,
            name=str(row.get("name") or name),
            latitude=latitude,
            longitude=longitude,
            elevation_m=float(elevation) if elevation is not None else None,
            timezone=row.get("timezone"),
            country=row.get("country"),
        )

    @lru_cache(maxsize=4096)
    def elevation(self, latitude: float, longitude: float) -> float | None:
        payload = self._get(
            ELEVATION_URL,
            {"latitude": latitude, "longitude": longitude},
        )
        values = payload.get("elevation")
        if isinstance(values, list) and values:
            try:
                return float(values[0])
            except (TypeError, ValueError):
                return None
        return None

    @lru_cache(maxsize=32768)
    def _weather_day(
        self,
        latitude: float,
        longitude: float,
        day_iso: str,
    ) -> dict[str, Any]:
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
        payload = self._get(
            ARCHIVE_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": day_iso,
                "end_date": day_iso,
                "hourly": hourly,
                "timezone": "UTC",
            },
        )
        data = payload.get("hourly") or {}
        times = data.get("time") or []
        if not isinstance(times, list) or not times:
            raise ValueError("Open-Meteo returned no hourly archive data")
        return data

    def weather_at(self, venue: Venue, scheduled_at: datetime) -> WeatherAtMatch:
        scheduled = scheduled_at.astimezone(timezone.utc)
        if scheduled.date() >= datetime.now(timezone.utc).date():
            raise ValueError("Historical enrichment only accepts completed archive dates")
        data = self._weather_day(
            round(venue.latitude, 5),
            round(venue.longitude, 5),
            scheduled.date().isoformat(),
        )
        times = data.get("time") or []
        target = scheduled.replace(minute=0, second=0, microsecond=0)
        candidates: list[tuple[float, int, datetime]] = []
        for idx, value in enumerate(times):
            try:
                parsed = datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            candidates.append((abs((parsed - target).total_seconds()), idx, parsed))
        if not candidates:
            return WeatherAtMatch(None, None, None, None, None, None, None, None)
        _, idx, source_time = min(candidates)

        def num(key: str) -> float | None:
            values = data.get(key) or []
            if idx >= len(values) or values[idx] is None:
                return None
            try:
                return float(values[idx])
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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


_GENERIC_TOURNAMENT_TOKENS = {
    "atp", "wta", "men", "women", "mens", "womens", "qualifying",
    "qualification", "singles", "doubles", "open", "grand slam",
    "challenger", "challengers", "itf", "final", "finals",
}

# High-confidence canonical tennis locations. These are deliberately venue/city
# mappings, not fuzzy guesses. They let historical provider label variants share
# the same static environment record (coordinates/elevation/timezone).
_LOCATION_ALIASES = {
    # United States / Canada
    "winston salem": "Winston-Salem, North Carolina, US",
    "winston-salem": "Winston-Salem, North Carolina, US",
    "miami": "Miami, Florida, US",
    "miami usa": "Miami, Florida, US",
    "miami united states": "Miami, Florida, US",
    "indian wells": "Indian Wells, California, US",
    "indian wells usa": "Indian Wells, California, US",
    "us open": "New York, New York, US",
    "flushing meadows": "New York, New York, US",
    "cincinnati": "Mason, Ohio, US",
    "cincinnati usa": "Mason, Ohio, US",
    "washington": "Washington, District of Columbia, US",
    "washington dc": "Washington, District of Columbia, US",
    "newport": "Newport, Rhode Island, US",
    "delray beach": "Delray Beach, Florida, US",
    "houston": "Houston, Texas, US",
    "charleston": "Charleston, South Carolina, US",
    "atlanta": "Atlanta, Georgia, US",
    "dallas": "Dallas, Texas, US",
    "san diego": "San Diego, California, US",
    "toronto": "Toronto, Ontario, CA",
    "toronto canada": "Toronto, Ontario, CA",
    "montreal": "Montreal, Quebec, CA",
    "montreal canada": "Montreal, Quebec, CA",
    "vancouver": "Vancouver, British Columbia, CA",

    # Great Britain / Europe
    "wimbledon": "London, England, GB",
    "nottingham": "Nottingham, England, GB",
    "nottingham great britain": "Nottingham, England, GB",
    "eastbourne": "Eastbourne, England, GB",
    "queens club": "London, England, GB",
    "queens": "London, England, GB",
    "birmingham": "Birmingham, England, GB",
    "rome": "Rome, IT",
    "roma": "Rome, IT",
    "milan": "Milan, IT",
    "milano": "Milan, IT",
    "turin": "Turin, IT",
    "torino": "Turin, IT",
    "madrid": "Madrid, ES",
    "barcelona": "Barcelona, ES",
    "valencia": "Valencia, ES",
    "seville": "Seville, ES",
    "sevilla": "Seville, ES",
    "paris": "Paris, FR",
    "roland garros": "Paris, FR",
    "lyon": "Lyon, FR",
    "marseille": "Marseille, FR",
    "metz": "Metz, FR",
    "montpellier": "Montpellier, FR",
    "monte carlo": "Monaco, MC",
    "monte-carlo": "Monaco, MC",
    "hamburg": "Hamburg, DE",
    "munich": "Munich, DE",
    "muenchen": "Munich, DE",
    "berlin": "Berlin, DE",
    "stuttgart": "Stuttgart, DE",
    "halle": "Halle, North Rhine-Westphalia, DE",
    "vienna": "Vienna, AT",
    "wien": "Vienna, AT",
    "basel": "Basel, CH",
    "geneva": "Geneva, CH",
    "gstaad": "Gstaad, CH",
    "rotterdam": "Rotterdam, NL",
    "s-hertogenbosch": "'s-Hertogenbosch, NL",
    "hertogenbosch": "'s-Hertogenbosch, NL",
    "antwerp": "Antwerp, BE",
    "brussels": "Brussels, BE",
    "stockholm": "Stockholm, SE",
    "bastad": "Båstad, SE",
    "oslo": "Oslo, NO",
    "copenhagen": "Copenhagen, DK",
    "helsinki": "Helsinki, FI",
    "warsaw": "Warsaw, PL",
    "warszawa": "Warsaw, PL",
    "prague": "Prague, CZ",
    "praha": "Prague, CZ",
    "budapest": "Budapest, HU",
    "bucharest": "Bucharest, RO",
    "iasi": "Iași, RO",
    "iasi romania": "Iași, RO",
    "cluj napoca": "Cluj-Napoca, RO",
    "belgrade": "Belgrade, RS",
    "kursumlijska banja": "Kuršumlijska Banja, RS",
    "zagreb": "Zagreb, HR",
    "umag": "Umag, HR",
    "ljubljana": "Ljubljana, SI",
    "bratislava": "Bratislava, SK",
    "sofia": "Sofia, BG",
    "athens": "Athens, GR",
    "istanbul": "Istanbul, TR",

    # Asia / Middle East / Oceania
    "dubai": "Dubai, AE",
    "abu dhabi": "Abu Dhabi, AE",
    "doha": "Doha, QA",
    "riyadh": "Riyadh, SA",
    "tel aviv": "Tel Aviv, IL",
    "beijing": "Beijing, CN",
    "shanghai": "Shanghai, CN",
    "shanghai china": "Shanghai, CN",
    "chengdu": "Chengdu, Sichuan, CN",
    "wuhan": "Wuhan, Hubei, CN",
    "zhuhai": "Zhuhai, Guangdong, CN",
    "hong kong": "Hong Kong, HK",
    "tokyo": "Tokyo, JP",
    "osaka": "Osaka, JP",
    "seoul": "Seoul, KR",
    "singapore": "Singapore, SG",
    "bangkok": "Bangkok, TH",
    "pune": "Pune, IN",
    "chennai": "Chennai, IN",
    "new delhi": "New Delhi, IN",
    "delhi": "New Delhi, IN",
    "melbourne": "Melbourne, Victoria, AU",
    "sydney": "Sydney, New South Wales, AU",
    "brisbane": "Brisbane, Queensland, AU",
    "adelaide 2": "Adelaide, South Australia, AU",
    "adelaide": "Adelaide, South Australia, AU",
    "perth": "Perth, Western Australia, AU",
    "auckland": "Auckland, NZ",

    # Latin America / Africa
    "bogota": "Bogotá, CO",
    "bogota colombia": "Bogotá, CO",
    "barranquilla": "Barranquilla, CO",
    "medellin": "Medellín, CO",
    "buenos aires": "Buenos Aires, AR",
    "cordoba": "Córdoba, AR",
    "sao paulo": "São Paulo, BR",
    "rio de janeiro": "Rio de Janeiro, BR",
    "florianopolis": "Florianópolis, BR",
    "santiago": "Santiago, CL",
    "lima": "Lima, PE",
    "acapulco": "Acapulco, MX",
    "guadalajara": "Guadalajara, MX",
    "cancun": "Cancún, MX",
    "mexico city": "Mexico City, MX",
    "marrakech": "Marrakesh, MA",
    "rabat": "Rabat, MA",
    "tunis": "Tunis, TN",
    "cairo": "Cairo, EG",
}

# Provider suffixes that describe draw/category rather than geography. Removing
# these before alias matching catches variants like
# "Kursumlijska Banja, Singles Qualifying, M-ITF-SRB-01A" without fuzzy matching.
_TOURNAMENT_NOISE_RE = re.compile(
    r"\b(?:singles?|doubles?|qualifying|qualification|men(?:'s|s)?|women(?:'s|s)?|"
    r"atp|wta|challenger|challengers|grand\s+slam|round\s+of\s+\d+|"
    r"m-?itf-[a-z]{3}-?\w*|w-?itf-[a-z]{3}-?\w*|m\d{2,3}|w\d{2,3})\b",
    re.IGNORECASE,
)


def _alias_key(value: Any) -> str:
    text = _normal(_clean_location_token(value))
    text = _TOURNAMENT_NOISE_RE.sub(" ", text)
    text = " ".join(text.replace("/", " ").replace("-", " ").replace(",", " ").split())
    return text.strip()


def _tournament_alias(value: Any) -> str | None:
    """Resolve only high-confidence tennis tournament/location aliases.

    Provider tournament labels frequently add gender/qualifying/ITF suffixes.
    Matching remains conservative: only explicit known city/event names are used.
    """
    raw = _normal(_clean_location_token(value))
    cleaned = _alias_key(value)
    if not raw:
        return None
    for key in sorted(_LOCATION_ALIASES, key=len, reverse=True):
        normalized_key = _normal(key)
        if (
            raw == normalized_key
            or raw.startswith(normalized_key + ",")
            or raw.startswith(normalized_key + " ")
            or cleaned == normalized_key
            or cleaned.startswith(normalized_key + " ")
        ):
            return _LOCATION_ALIASES[key]
    return None


def _clean_location_token(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip(" ,-()")


def _location_from_tournament_name(name: Any) -> list[str]:
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
    """Build only location strings present in provider/history data."""
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
    venue_country = (
        _as_dict(venue.get("country")).get("name")
        or _as_dict(venue.get("country")).get("alpha2")
        or venue.get("countryName")
    )
    if venue_city and venue_country:
        add(f"{venue_city}, {venue_country}")
    add(venue_city)
    if venue_name and venue_country and venue_name != venue_city:
        add(f"{venue_name}, {venue_country}")

    city = (
        tournament_obj.get("city")
        or unique.get("city")
        or raw.get("city")
        or raw.get("venueCity")
    )
    country_name = (
        country.get("name")
        or country.get("alpha2")
        or raw.get("countryName")
        or _as_dict(raw.get("country")).get("name")
        or _as_dict(raw.get("country")).get("alpha2")
    )
    if city and country_name:
        add(f"{city}, {country_name}")
    add(city)

    for source_name in (
        tournament_obj.get("name"),
        tournament,
        unique.get("name"),
    ):
        alias = _tournament_alias(source_name)
        if alias:
            add(alias)
        for parsed in _location_from_tournament_name(source_name):
            add(parsed)

    # Bare names are last resort and still require an exact, unique geocoder match.
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
    *,
    include_weather: bool = True,
) -> dict[str, Any]:
    venue, query = resolve_match_venue(client, provider_payload, tournament)
    base = {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "venue_resolved": venue is not None,
        "location_query": query,
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "open-meteo",
        "weather_provenance": "historical_archive_posthoc",
        "training_eligible_weather": False,
    }
    if venue is None:
        return base

    base["venue"] = asdict(venue)
    if include_weather:
        base["weather"] = asdict(client.weather_at(venue, scheduled_at))
        base["match_hour_utc"] = scheduled_at.astimezone(timezone.utc).hour
    return base
