from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
import time
import unicodedata
import re

import httpx

from tbt.services.countries import normalize_country_code

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ENVIRONMENT_SCHEMA_VERSION = 2
ENVIRONMENT_RESOLVER_VERSION = 6


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


# Only documented equivalent city spellings. Never guess arbitrary cities.
_CITY_CANONICAL = {
    "sharm elsheikh": "sharm el sheikh",
    "sharm el-sheikh": "sharm el sheikh",
    "s. margherita di pula": "santa margherita di pula",
    "s margherita di pula": "santa margherita di pula",
    # Open-Meteo and tennis feeds disagree about the Dutch city's apostrophe.
    "'s-hertogenbosch": "s-hertogenbosch",
    "'s hertogenbosch": "s-hertogenbosch",
    "s hertogenbosch": "s-hertogenbosch",
    "den bosch": "s-hertogenbosch",
}


def _normal(value: Any) -> str:
    normalized = "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value or "").casefold())
        if not unicodedata.combining(c)
    ).strip()
    return _CITY_CANONICAL.get(normalized, normalized)


_COUNTRY_HINT_ALIASES = {
    "usa": "us",
    "united states": "us",
    "united states of america": "us",
    "great britain": "gb",
    "united kingdom": "gb",
    "uk": "gb",
    "england": "gb",
    "scotland": "gb",
    "wales": "gb",
    "uae": "ae",
    "united arab emirates": "ae",
    "south korea": "kr",
    "korea republic": "kr",
    "czech republic": "cz",
}


def _country_hint(value: Any) -> str:
    text = _normal(value)
    if not text:
        return ""
    return _COUNTRY_HINT_ALIASES.get(text, text)


class OpenMeteoClient:
    def __init__(
        self,
        timeout_seconds: float = 25.0,
        *,
        request_limit: int | None = None,
        min_interval_seconds: float = 0.75,
        transient_retries: int = 2,
        retry_backoff_seconds: float = 0.75,
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
        self.transient_retries = max(0, int(transient_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.transient_retries + 1):
            if self.request_limit is not None and self.request_count >= self.request_limit:
                raise OpenMeteoBudgetExceeded("Open-Meteo request cap reached")
            delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()
            self.request_count += 1
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("error"):
                    raise ValueError("Invalid Open-Meteo response")
                return payload
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt >= self.transient_retries:
                    raise
                backoff = self.retry_backoff_seconds * (2 ** attempt)
                if backoff > 0:
                    time.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    # Retain positive AND negative queries throughout a full history pass.
    # 4k evicted common ITF city misses and repeated paid geocodes.
    @lru_cache(maxsize=65536)
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

        normalized_country_hint = _country_hint(country_hint)

        params: dict[str, Any] = {
            "name": name,
            "count": 20,
            "language": "en",
            "format": "json",
        }
        if len(normalized_country_hint) == 2 and normalized_country_hint.isalpha():
            params["countryCode"] = normalized_country_hint.upper()

        rows = self._get(GEOCODE_URL, params).get("results") or []
        if not isinstance(rows, list):
            return None

        exact = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _normal(row.get("name")) != _normal(name):
                continue
            if normalized_country_hint:
                country_values = {
                    _country_hint(row.get("country")),
                    _country_hint(row.get("country_code")),
                }
                if normalized_country_hint not in country_values:
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

        # Open-Meteo can return BOTH a populated city and an administrative
        # region with the same name (e.g. Antalya). Prefer the populated place
        # only when the response identifies one unambiguous settlement. Two
        # different settlements with the same name remain unresolved.
        if len(exact) != 1:
            populated = [
                item for item in exact
                if str(item.get("feature_code") or "").upper().startswith("PPL")
            ]
            if len(populated) == 1:
                exact = populated
            else:
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
            # Some Open-Meteo entries (e.g. Hong Kong) omit the display
            # country but retain the authoritative GeoNames country_code.
            # Never infer country from the requested query alone.
            country=row.get("country") or (
                row.get("country_code")
                if normalize_country_code(row.get("country_code"))
                else None
            ),
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
    "pozoblanco": "Pozoblanco, ES",
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
    "little rock": "Little Rock, Arkansas, US",
    "s-hertogenbosch": "'s-Hertogenbosch, NL",
    "'s-hertogenbosch": "'s-Hertogenbosch, NL",
    "'s hertogenbosch": "'s-Hertogenbosch, NL",
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
    "kutaisi": "Kutaisi, GE",
    "maringa": "Maringá, BR",
    "hurghada": "Hurghada, EG",
    "monastir": "Monastir, TN",
    "antalya": "Antalya, TR",
    "sharm el sheikh": "Sharm El Sheikh, EG",
    "heraklion": "Heraklion, GR",
    "oeiras": "Oeiras, PT",
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
    r"atp|wta|itf|challenger|challengers|grand\s+slam|round\s+of\s+\d+|"
    r"m-?itf-[a-z]{3}-?\w*|w-?itf-[a-z]{3}-?\w*|m\d{2,3}|w\d{2,3})\b",
    re.IGNORECASE,
)

_LEADING_UTR_RE = re.compile(r"^(?:utr\s+)?(?:ptt\s+|pro\s+tennis\s+tour\s+)+", re.IGNORECASE)
_LEADING_TOUR_CLASS_RE = re.compile(
    r"^(?:(?:itf|atp|wta)\s+)?(?:m|w)\s*\d{2,3}\b[\s:,-]*",
    re.IGNORECASE,
)
_TRAILING_EVENT_NUMBER_RE = re.compile(r"(?:\s+|\s*[-#]\s*)\d{1,3}$")
_TRAILING_DRAW_RE = re.compile(
    r"(?:[,\s-]+(?:men(?:'s|s)?|women(?:'s|s)?|singles?|doubles?|qualifying|qualification|finals?))+$",
    re.IGNORECASE,
)
_ITF_COUNTRY_CODE_RE = re.compile(r"\b[MW]-?ITF-([A-Z]{3})(?:[-_A-Z0-9]*|$)", re.IGNORECASE)


def _country_from_tournament_label(value: Any) -> str:
    """Extract an explicit provider/ITF country token when present.

    Example: ``M-ITF-SRB-01A`` -> ``RS``.  We only normalize explicit codes;
    no country is guessed from a tournament or player name.
    """
    match = _ITF_COUNTRY_CODE_RE.search(str(value or ""))
    return normalize_country_code(match.group(1)) if match else ""


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


def _clean_tournament_location_part(value: Any) -> str:
    """Conservatively strip provider draw/tour decorations from a location.

    Examples:
    ``ITF M15 Monastir 30`` -> ``Monastir``
    ``ITF M25 Kutaisi Men`` -> ``Kutaisi``
    ``Maringa Women`` -> ``Maringa``

    The raw provider label remains a later fallback, so this helper never
    destroys the only candidate.
    """
    text = _clean_location_token(value)
    text = _ITF_COUNTRY_CODE_RE.sub(" ", text)
    text = _LEADING_UTR_RE.sub("", text).strip()
    text = _LEADING_TOUR_CLASS_RE.sub("", text).strip()
    previous = None
    while text and text != previous:
        previous = text
        text = _TRAILING_DRAW_RE.sub("", text).strip(" ,-")
        text = _TRAILING_EVENT_NUMBER_RE.sub("", text).strip(" ,-")
    return " ".join(text.split())


def _location_from_tournament_name(name: Any) -> list[str]:
    text = _clean_location_token(name)
    if not text:
        return []
    explicit_country = _country_from_tournament_label(text)

    if "," not in text:
        cleaned = _clean_tournament_location_part(text)
        if not cleaned or cleaned == text:
            return []
        # A leftover tour/draw token means the label is still an event title,
        # not a trustworthy city; do not send it verbatim to the geocoder.
        if any(re.search(rf"\b{re.escape(token)}\b", _normal(cleaned))
               for token in ("atp", "wta", "itf", "utr", "ptt", "challenger", "open", "masters", "qualifying", "unknown")):
            return []
        out = []
        if explicit_country:
            out.append(f"{cleaned}, {explicit_country}")
        out.append(cleaned)
        return out

    parts = [_clean_location_token(p) for p in text.split(",")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return []

    usable: list[str] = []
    country_hint = explicit_country
    for idx, part in enumerate(parts):
        low = _normal(part)
        if not country_hint:
            country_hint = normalize_country_code(part)
        if _ITF_COUNTRY_CODE_RE.search(part):
            continue
        if idx == 0 and ("open" in low or low in _GENERIC_TOURNAMENT_TOKENS):
            continue
        if low in _GENERIC_TOURNAMENT_TOKENS or "qualif" in low:
            continue
        cleaned_part = _clean_tournament_location_part(part)
        if cleaned_part:
            usable.append(cleaned_part)
    if not usable:
        return []

    out: list[str] = []
    city = usable[0]
    if country_hint:
        out.append(f"{city}, {country_hint}")
    elif len(usable) >= 2:
        out.append(f"{city}, {usable[1]}")
    out.append(city)
    return list(dict.fromkeys(out))


def explicit_country_hints(
    provider_payload: dict[str, Any],
    tournament: str = "",
) -> set[str]:
    """Return only explicit/provider-backed country hints for a match."""
    raw = _as_dict(provider_payload)
    tournament_obj = _as_dict(raw.get("tournament"))
    unique = _as_dict(tournament_obj.get("uniqueTournament"))
    venue = _as_dict(raw.get("venue"))
    country = _as_dict(tournament_obj.get("country"))
    unique_country = _as_dict(unique.get("country"))
    raw_country = _as_dict(raw.get("country"))
    venue_country = _as_dict(venue.get("country"))

    hints: set[str] = set()

    def add(value: Any) -> None:
        code = normalize_country_code(value)
        if code:
            hints.add(code)

    for value in (
        venue_country.get("alpha2"),
        venue_country.get("name"),
        venue.get("countryName"),
        country.get("alpha2"),
        country.get("name"),
        unique_country.get("alpha2"),
        unique_country.get("name"),
        raw_country.get("alpha2"),
        raw_country.get("name"),
        raw.get("countryName"),
    ):
        add(value)

    for source_name in (
        tournament_obj.get("name"),
        tournament,
        unique.get("name"),
    ):
        add(_country_from_tournament_label(source_name))
        alias = _tournament_alias(source_name)
        if alias:
            alias_parts = [part.strip() for part in alias.split(",") if part.strip()]
            if alias_parts:
                add(alias_parts[-1])
    return hints


def strong_location_name_hints(
    provider_payload: dict[str, Any],
    tournament: str = "",
) -> set[str]:
    """Return conservative city/location names that a cached venue must respect.

    Direct provider city fields are authoritative.  Tournament labels are used
    only when they carry an explicit ITF country code or map through a curated
    tennis-location alias; this avoids treating arbitrary tournament names as
    geography.
    """
    raw = _as_dict(provider_payload)
    tournament_obj = _as_dict(raw.get("tournament"))
    unique = _as_dict(tournament_obj.get("uniqueTournament"))
    venue = _as_dict(raw.get("venue"))
    hints: set[str] = set()

    def add(value: Any) -> None:
        text = _normal(value)
        if text:
            hints.add(text)

    for value in (
        venue.get("city"),
        tournament_obj.get("city"),
        unique.get("city"),
        raw.get("city"),
        raw.get("venueCity"),
    ):
        add(value)

    for source_name in (
        tournament_obj.get("name"),
        tournament,
        unique.get("name"),
    ):
        alias = _tournament_alias(source_name)
        if alias:
            add(alias.split(",", 1)[0])
            continue
        explicit_country = _country_from_tournament_label(source_name)
        if not explicit_country:
            continue
        for parsed in _location_from_tournament_name(source_name):
            parts = [part.strip() for part in parsed.split(",") if part.strip()]
            if len(parts) >= 2 and normalize_country_code(parts[-1]) == explicit_country:
                add(parts[0])
                break
    return hints


def venue_context_compatible(
    provider_payload: dict[str, Any],
    tournament: str,
    venue: dict[str, Any],
) -> tuple[bool, str]:
    """Validate a resolved/cached venue against explicit match geography.

    A history-cache hit is rejected when it conflicts with an explicit country
    or with a strong provider-derived city hint.  Missing hints fail open; known
    contradictions fail closed.
    """
    venue_country = normalize_country_code(venue.get("country"))
    country_hints = explicit_country_hints(provider_payload, tournament)
    if country_hints and venue_country not in country_hints:
        return False, "country_mismatch"

    venue_names = {
        _normal(venue.get("name")),
        _normal(str(venue.get("query") or "").split(",", 1)[0]),
    }
    venue_names.discard("")
    raw = _as_dict(provider_payload)
    tournament_obj = _as_dict(raw.get("tournament"))
    direct_cities = {
        _normal(value) for value in (
            _as_dict(raw.get("venue")).get("city"),
            tournament_obj.get("city"),
            _as_dict(tournament_obj.get("uniqueTournament")).get("city"),
            raw.get("city"), raw.get("venueCity"),
        ) if _normal(value)
    }
    # Provider-supplied city is authoritative even when a broader tournament
    # alias names a nearby but different place (Antalya vs Belek).
    if direct_cities:
        if not venue_names.intersection(direct_cities):
            return False, "provider_city_mismatch"
    else:
        city_hints = strong_location_name_hints(provider_payload, tournament)
        if city_hints and not venue_names.intersection(city_hints):
            return False, "city_mismatch"
    return True, "compatible"


def _query_variants(query: str) -> list[str]:
    variants = [query]
    alias = _tournament_alias(query) or _LOCATION_ALIASES.get(_normal(query))
    if alias and alias.lower() != query.lower():
        variants.insert(0, alias)
    cleaned = _clean_tournament_location_part(query)
    if cleaned and cleaned.casefold() != query.casefold() and cleaned.casefold() not in {v.casefold() for v in variants}:
        variants.append(cleaned)
    return variants


def location_candidates(
    provider_payload: dict[str, Any],
    tournament: str = "",
) -> list[str]:
    """Prefer explicit geography; never send decorated event labels to geocoding.

    Country-scoped candidates are preferred over bare city names. A conflicting
    provider country is not guessed away, and unparseable tournament labels are
    reported unresolved without spending Open-Meteo requests.
    """
    raw = _as_dict(provider_payload)
    tournament_obj = _as_dict(raw.get("tournament"))
    unique = _as_dict(tournament_obj.get("uniqueTournament"))
    venue = _as_dict(raw.get("venue"))
    hints = explicit_country_hints(raw, tournament)
    only_country = next(iter(hints)) if len(hints) == 1 else ""
    candidates: list[str] = []

    def add(value: Any, *, city: bool = False) -> None:
        text = _clean_location_token(value)
        if not text:
            return
        # Normalize only explicit, proven alternative city spellings.
        city_part, separator, qualifier = text.partition(",")
        canonical = _normal(city_part)
        if canonical in {"sharm el sheikh", "santa margherita di pula"}:
            text = canonical + (separator + qualifier if separator else "")
        # Never fall back to a countryless query when the provider supplied
        # an unambiguous country; this prevents homonymous-city mismatches.
        if city and only_country and "," not in text:
            text = f"{text}, {only_country.upper()}"
        if text.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(text)

    def add_city(value: Any, country: Any = None) -> None:
        city = _clean_location_token(value)
        if not city:
            return
        # Canonical aliases preserve the original explicit country restriction.
        if _normal(city) in {"sharm el sheikh", "santa margherita di pula"}:
            city = _normal(city)
        explicit = normalize_country_code(country)
        if explicit:
            add(f"{city}, {explicit}")
        else:
            add(city, city=True)

    venue_country = (
        _as_dict(venue.get("country")).get("alpha2")
        or _as_dict(venue.get("country")).get("name")
        or venue.get("countryName")
    )
    add_city(venue.get("city"), venue_country)

    country = _as_dict(tournament_obj.get("country")) or _as_dict(unique.get("country"))
    country_name = (
        country.get("alpha2") or country.get("name")
        or raw.get("countryName")
        or _as_dict(raw.get("country")).get("alpha2")
        or _as_dict(raw.get("country")).get("name")
    )
    for city in (tournament_obj.get("city"), unique.get("city"), raw.get("city"), raw.get("venueCity")):
        add_city(city, country_name)

    for name in (tournament_obj.get("name"), tournament, unique.get("name")):
        alias = _tournament_alias(name)
        if alias:
            add(alias)
        for parsed in _location_from_tournament_name(name):
            # Explicit country hints are applied to names parsed from labels.
            add(parsed, city=True)

    # A genuinely plain location label (e.g. "Saitama") is useful; tournament
    # descriptions such as "UTR PTT Saitama Men 06" are never sent verbatim.
    if not candidates:
        for name in (tournament_obj.get("name"), tournament, unique.get("name")):
            text = _clean_location_token(name)
            lowered = _normal(text)
            if (
                text and 1 <= len(text.split()) <= 2
                and not re.search(r"\d", text)
                and not any(re.search(rf"\b{re.escape(token)}\b", lowered)
                            for token in ("open", "final", "masters", "challenger", "itf", "atp", "wta", "utr", "ptt", "men", "women"))
            ):
                add(text, city=True)
    return candidates


def venue_learning_keys(
    provider_payload: dict[str, Any],
    tournament: str = "",
    *,
    tour: str = "",
    tournament_id: Any = None,
) -> list[str]:
    """Stable high-confidence keys used to reuse already-resolved venues.

    The enrichment job rebuilds this cache from the private history release on
    every run, so no extra database or cache artifact is required.  A key is
    only used when the historical observations for that key agree on one venue.
    """
    raw = _as_dict(provider_payload)
    tournament_obj = _as_dict(raw.get("tournament"))
    unique = _as_dict(tournament_obj.get("uniqueTournament"))
    keys: list[str] = []

    def add(prefix: str, value: Any) -> None:
        text = _normal(value)
        text = " ".join(text.replace("/", " ").replace("-", " ").replace(",", " ").split())
        if text:
            key = f"{prefix}:{text}"
            if key not in keys:
                keys.append(key)

    tour_key = _normal(tour) or "unknown"
    for value in (
        tournament_id,
        tournament_obj.get("id"),
        unique.get("id"),
        raw.get("tournamentId"),
        raw.get("uniqueTournamentId"),
    ):
        if value not in (None, ""):
            add(f"tournament-id:{tour_key}", value)

    # The cleaned tournament label is useful for recurring ITF/Challenger labels
    # while the tour prefix prevents accidental ATP/WTA cross-linking.
    for value in (tournament, tournament_obj.get("name"), unique.get("name")):
        cleaned = _alias_key(value)
        if cleaned and cleaned not in _GENERIC_TOURNAMENT_TOKENS:
            add(f"tournament-name:{tour_key}", cleaned)

    # Reuse exact provider-derived location candidates when they already resolved
    # elsewhere in history.  These are deliberately more specific than a bare city.
    for candidate in location_candidates(raw, tournament):
        normalized_candidate = _normal(candidate)
        if normalized_candidate in _GENERIC_TOURNAMENT_TOKENS:
            continue
        add("location", candidate)
    return keys


def resolve_match_venue(
    client: OpenMeteoClient,
    provider_payload: dict[str, Any],
    tournament: str,
) -> tuple[Venue | None, str | None]:
    for raw_query in location_candidates(provider_payload, tournament):
        for query in _query_variants(raw_query):
            venue = client.geocode(query)
            if venue is None:
                continue
            compatible, _ = venue_context_compatible(
                provider_payload,
                tournament,
                asdict(venue),
            )
            if compatible:
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
        "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
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
