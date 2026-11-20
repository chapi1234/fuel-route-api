"""Turn a start/finish input into coordinates, offline whenever possible.

Accepted inputs, in the order they are tried:

1. ``"lat,lon"`` such as ``"39.7392,-104.9903"``: used as is.
2. ``"City, ST"`` or ``"City, State"`` such as ``"Denver, CO"``: looked up in the
   bundled Census places file, no network call.
3. Anything else (a street address, a landmark): one call to a geocoder, which
   counts against the external-call budget the API reports.
"""

import csv
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
from django.conf import settings

from geo.names import US_STATES, place_key

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}  # fmt: skip

_COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class PlaceNotFound(Exception):
    pass


class OutsideUSA(Exception):
    pass


@dataclass(frozen=True)
class Place:
    query: str
    label: str
    lat: float
    lon: float
    source: str  # "coordinates", "places" or "geocoder"


@lru_cache(maxsize=1)
def _us_rings() -> list[tuple[np.ndarray, tuple[float, float, float, float]]]:
    """US border rings (Census 1:20M cartographic boundary) with their bounding boxes."""
    path = Path(settings.DATA_DIR) / "us_boundary.json"
    rings = json.loads(path.read_text(encoding="utf-8"))["rings"]
    result = []
    for ring in rings:
        coords = np.asarray(ring, dtype=float)
        box = (coords[:, 0].min(), coords[:, 0].max(), coords[:, 1].min(), coords[:, 1].max())
        result.append((coords, box))
    return result


def in_usa(lat: float, lon: float) -> bool:
    """Point-in-polygon test against the US border (even-odd rule over all rings)."""
    inside = False
    for coords, (west, east, south, north) in _us_rings():
        if not (west <= lon <= east and south <= lat <= north):
            continue
        x1, y1 = coords[:-1, 0], coords[:-1, 1]
        x2, y2 = coords[1:, 0], coords[1:, 1]
        crosses = (y1 > lat) != (y2 > lat)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
        if np.count_nonzero(crosses & (lon < x_at)) % 2:
            inside = not inside
    return inside


@lru_cache(maxsize=1)
def _places_index() -> dict[tuple[str, str], tuple[str, float, float]]:
    path = Path(settings.DATA_DIR) / "us_places.csv"
    index: dict[tuple[str, str], tuple[str, float, float]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["state"], place_key(row["name"]))
            # The file lists larger places first within a name; keep the first one.
            index.setdefault(key, (row["name"], float(row["lat"]), float(row["lon"])))
    return index


def _split_city_state(text: str) -> tuple[str, str] | None:
    text = re.sub(r"[,\s]+(usa|u\.s\.a\.|us|united states(?: of america)?)$", "", text, flags=re.I)
    if "," not in text:
        return None
    city, state = (part.strip() for part in text.rsplit(",", 1))
    code = state.upper() if state.upper() in US_STATES else STATE_NAMES.get(state.lower())
    return (city, code) if city and code else None


def resolve_offline(query: str) -> Place | None:
    text = query.strip()
    if match := _COORDINATES.match(text):
        lat, lon = float(match[1]), float(match[2])
        if not in_usa(lat, lon):
            raise OutsideUSA(f"{text!r} is not inside the USA.")
        return Place(text, f"{lat:.5f}, {lon:.5f}", lat, lon, "coordinates")
    if parts := _split_city_state(text):
        city, state = parts
        found = _places_index().get((state, place_key(city)))
        if found:
            name, lat, lon = found
            return Place(text, f"{name}, {state}", lat, lon, "places")
    return None


def geocode(query: str, client: httpx.Client) -> Place:
    """Look a free-form US address up on Nominatim (one external call)."""
    response = client.get(
        settings.GEOCODER_URL,
        params={"q": query, "countrycodes": "us", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": settings.HTTP_USER_AGENT},
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise PlaceNotFound(f"Could not find {query!r} in the USA.")
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    if not in_usa(lat, lon):
        raise OutsideUSA(f"{query!r} is not inside the USA.")
    return Place(query, results[0].get("display_name", query), lat, lon, "geocoder")
