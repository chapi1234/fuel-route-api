"""Build the coordinate files the API uses, so no geocoding happens at request time.

The fuel price file has truck stop addresses like "I-44, EXIT 283 & US-69" but no
coordinates. This script locates every station's city once, offline:

1. US Census Gazetteer (public domain): incorporated places and census-designated
   places first, then county subdivisions (New England towns, townships).
2. Anything still unmatched (small unincorporated communities) is looked up once on
   OpenStreetMap Nominatim, at most one request per second, and cached in
   ``data/geocode_cache.json`` so later runs are fully offline.

Outputs (committed to the repo):
    data/station_cities.csv  every (state, city) in the fuel file with coordinates
    data/us_places.csv       Census places, for resolving "City, ST" request inputs

Usage:
    uv run python scripts/build_geodata.py [--gazetteer-dir DIR] [--offline]
"""

import argparse
import csv
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geo.names import US_STATES, gazetteer_name_variants, place_key  # noqa: E402

DATA = ROOT / "data"
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/{name}.zip"
)
PLACES = "2024_Gaz_place_national"
COUNTY_SUBDIVISIONS = "2024_Gaz_cousubs_national"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "fuel-route-api-data-build/1.0 (github.com/chapi1234/fuel-route-api)"


def read_gazetteer(name: str, directory: Path | None) -> list[dict[str, str]]:
    if directory and (directory / f"{name}.txt").is_file():
        text = (directory / f"{name}.txt").read_text(encoding="latin-1")
    else:
        print(f"Downloading {name} ...")
        response = httpx.get(GAZETTEER_URL.format(name=name), timeout=120, follow_redirects=True)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            text = archive.read(f"{name}.txt").decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return [{key.strip(): value.strip() for key, value in row.items()} for row in reader]


def build_index(
    places: list[dict[str, str]], subdivisions: list[dict[str, str]]
) -> dict[tuple[str, str], tuple[float, float, str]]:
    """Map (state, place_key) to coordinates. Places win over county subdivisions,
    and among equals the larger land area wins (the town, not a same-named hamlet)."""
    best: dict[tuple[str, str], tuple[tuple[int, int, float], float, float, str]] = {}
    for priority, rows in ((2, places), (1, subdivisions)):
        for row in rows:
            state = row["USPS"]
            if state not in US_STATES:
                continue
            lat, lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
            area = float(row["ALAND"])
            for rank, variant in enumerate(reversed(gazetteer_name_variants(row["NAME"]))):
                key = (state, place_key(variant))
                score = (priority, rank, area)
                if key not in best or score > best[key][0]:
                    best[key] = (score, lat, lon, row["NAME"])
    return {key: (lat, lon, name) for key, (_, lat, lon, name) in best.items()}


def nominatim(city: str, state: str, client: httpx.Client) -> tuple[float, float] | None:
    params = {"city": city, "state": state, "country": "us", "format": "jsonv2", "limit": 1}
    response = client.get(NOMINATIM_URL, params=params)
    response.raise_for_status()
    results = response.json()
    time.sleep(1.1)  # Nominatim usage policy: at most one request per second
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gazetteer-dir", type=Path, help="folder with already unzipped files")
    parser.add_argument("--offline", action="store_true", help="never call Nominatim")
    args = parser.parse_args()

    places = read_gazetteer(PLACES, args.gazetteer_dir)
    subdivisions = read_gazetteer(COUNTY_SUBDIVISIONS, args.gazetteer_dir)
    index = build_index(places, subdivisions)

    with (DATA / "fuel-prices.csv").open(encoding="utf-8", newline="") as handle:
        cities = sorted(
            {
                (row["State"].strip(), row["City"].strip())
                for row in csv.DictReader(handle)
                if row["State"].strip() in US_STATES
            }
        )

    cache_path = DATA / "geocode_cache.json"
    cache: dict[str, list[float] | None] = (
        json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    )
    rows, unresolved = [], []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for state, city in cities:
            key = place_key(city)
            if (state, key) in index:
                lat, lon, _ = index[(state, key)]
                rows.append((state, key, city, lat, lon, "census"))
                continue
            cache_key = f"{state}|{city}"
            if cache_key not in cache and not args.offline:
                cache[cache_key] = list(nominatim(city, state, client) or []) or None
                cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
            if cache.get(cache_key):
                lat, lon = cache[cache_key]
                rows.append((state, key, city, lat, lon, "nominatim"))
            else:
                unresolved.append(f"{city}, {state}")

    with (DATA / "station_cities.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["state", "city_key", "city", "lat", "lon", "source"])
        for state, key, city, lat, lon, source in rows:
            writer.writerow([state, key, city, f"{lat:.6f}", f"{lon:.6f}", source])

    with (DATA / "us_places.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["state", "name", "lat", "lon"])
        # Larger places first, so a name shared by two places in a state resolves to the
        # bigger one (the request-time lookup keeps the first match).
        for row in sorted(places, key=lambda r: (r["USPS"], -float(r["ALAND"]))):
            if row["USPS"] in US_STATES:
                plain = gazetteer_name_variants(row["NAME"])[-1]
                writer.writerow(
                    [
                        row["USPS"],
                        plain,
                        f"{float(row['INTPTLAT']):.5f}",
                        f"{float(row['INTPTLONG']):.5f}",
                    ]
                )

    sources = {source: sum(1 for r in rows if r[5] == source) for source in ("census", "nominatim")}
    print(f"{len(cities)} station cities: {sources}, unresolved {len(unresolved)}")
    for name in unresolved:
        print("  unresolved:", name)


if __name__ == "__main__":
    main()
