"""Conservative GeoNames gazetteer fallback for unresolved Open-Meteo places.

GeoNames cities500.zip: https://download.geonames.org/export/dump/cities500.zip
GeoNames data © GeoNames, CC BY 4.0: https://www.geonames.org/about.html
A single archive download replaces repeated public geocoding API calls.
Never resolve a countryless or homonymous place automatically.
"""
from __future__ import annotations

from collections import defaultdict
from io import BytesIO, TextIOWrapper
from zipfile import BadZipFile, ZipFile
import logging

import httpx

from tbt.services.countries import normalize_country_code
from tbt.services.environment import Venue, _normal

LOG = logging.getLogger(__name__)
CITIES500_URL = "https://download.geonames.org/export/dump/cities500.zip"

# GeoNames explicitly lists this small Serbian spa (feature S.SPA); it is
# smaller than the cities500 population cutoff and absent from the city dump.
# https://www.geonames.org/advanced-search.html?featureClass=S&q=serbia
_CURATED_SMALL_FEATURES = {
    ("kursumlijska banja", "RS"): (
        "Kuršumlijska Banja", 43.057862, 21.252555, None, "Europe/Belgrade"
    ),
}


class GeoNamesFallback:
    """Lazy, one-download, country-scoped, exact-name offline geocoder.

    The archive is only needed after Open-Meteo returns no acceptable match.
    Read only rows relevant to outstanding missing names to bound memory.
    """

    def __init__(self, *, wanted_names: set[str] | None = None,
                 archive_bytes: bytes | None = None,
                 timeout_seconds: float = 40.0) -> None:
        self.wanted_names = (
            {_normal(name.split(",", 1)[0]).strip() for name in wanted_names}
            if wanted_names is not None else None
        )
        self.archive_bytes = archive_bytes
        self.timeout_seconds = timeout_seconds
        self._loaded = False
        self._index: dict[tuple[str, str], list[tuple]] = {}
        self.load_error: str | None = None
        self.archive_downloads = 0
        self.resolved = 0

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            archive = self.archive_bytes
            if archive is None:
                self.archive_downloads += 1
                with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True,
                                  headers={"User-Agent": "BlinQ research venue enrichment (GeoNames CC BY 4.0)"}) as client:
                    response = client.get(CITIES500_URL)
                    response.raise_for_status()
                    archive = response.content
            if len(archive) > 40_000_000:
                raise ValueError("GeoNames archive exceeds 40MB safety limit")
            index: dict[tuple[str, str], dict[str, tuple]] = defaultdict(dict)
            with ZipFile(BytesIO(archive)) as zip_file:
                info = zip_file.getinfo("cities500.txt")
                if info.file_size > 110_000_000:
                    raise ValueError("GeoNames text exceeds 110MB safety limit")
                with zip_file.open(info) as raw, TextIOWrapper(raw, encoding="utf-8") as data:
                    for line in data:
                        fields = line.rstrip("\n").split("\t")
                        if len(fields) < 19 or fields[6] != "P":
                            continue
                        country = normalize_country_code(fields[8])
                        if not country:
                            continue
                        try:
                            latitude, longitude = float(fields[4]), float(fields[5])
                            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                                continue
                        except ValueError:
                            continue
                        names = [fields[1], fields[2]]
                        # GeoNames-supplied aliases, not inferred spellings.
                        # Index only requested aliases to avoid a huge memory map.
                        if self.wanted_names is not None:
                            names.extend(fields[3].split(","))
                        elif fields[3]:
                            names.extend(fields[3].split(",")[:24])
                        elevation = fields[15] or fields[16]
                        try:
                            altitude = float(elevation) if elevation else None
                        except ValueError:
                            altitude = None
                        record = (fields[0], fields[1], latitude, longitude,
                                  altitude, fields[17] or None)
                        for name in names:
                            normal = _normal(name).strip()
                            if normal and (
                                self.wanted_names is None or normal in self.wanted_names
                            ):
                                index[(normal, country)][fields[0]] = record
            self._index = {key: list(records.values()) for key, records in index.items()}
        except (httpx.HTTPError, BadZipFile, KeyError, OSError, ValueError) as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            LOG.warning("GeoNames fallback archive unavailable: %s", self.load_error)

    def resolve(self, query: str, country_code: str) -> Venue | None:
        """Exact requested city + verified ISO country + unique GeoNames ID."""
        code = normalize_country_code(country_code)
        name = str(query).split(",", 1)[0].strip()
        key = (_normal(name), code)
        if not code or not name:
            return None

        curated = _CURATED_SMALL_FEATURES.get(key)
        if curated:
            _name, lat, lon, elevation, timezone = curated
            self.resolved += 1
            return Venue(query=query, name=_name, latitude=lat, longitude=lon,
                         elevation_m=elevation, timezone=timezone, country=code)

        self._load()
        matches = self._index.get(key, [])
        # Two different GeoNames IDs for the same alias/country are ambiguous.
        if len(matches) != 1:
            return None
        _id, geoname, lat, lon, elevation, timezone = matches[0]
        self.resolved += 1
        # The requested label is a GeoNames-verified synonym of this place;
        # keep it for strict comparison against the provider's city.
        return Venue(query=query, name=name, latitude=lat, longitude=lon,
                     elevation_m=elevation, timezone=timezone, country=code)
