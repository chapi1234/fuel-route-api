"""Load the fuel price file into the database.

Cleaning rules, decided from the data:

* Only US states are kept (the file also lists 620 Canadian stations).
* A station (OPIS ID) can appear several times with different prices; the lowest
  price is kept, since the brief asks for the most cost-effective stops.
* City names are trimmed (many have trailing spaces) and located with
  ``data/station_cities.csv`` built by ``scripts/build_geodata.py``.
"""

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction

from geo.names import US_STATES, place_key


@dataclass(frozen=True)
class ImportReport:
    rows: int
    stations: int
    skipped_non_us: int
    skipped_unlocated: int


def load_city_coordinates(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row["state"], row["city_key"]): (float(row["lat"]), float(row["lon"]))
            for row in csv.DictReader(handle)
        }


def read_stations(prices_path: Path, cities_path: Path) -> tuple[list[dict], ImportReport]:
    coordinates = load_city_coordinates(cities_path)
    stations: dict[int, dict] = {}
    rows = non_us = unlocated = 0
    with prices_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows += 1
            state = row["State"].strip()
            if state not in US_STATES:
                non_us += 1
                continue
            city = row["City"].strip()
            location = coordinates.get((state, place_key(city)))
            if location is None:
                unlocated += 1
                continue
            opis_id = int(row["OPIS Truckstop ID"])
            price = Decimal(row["Retail Price"].strip())
            current = stations.get(opis_id)
            if current is None or price < current["price"]:
                stations[opis_id] = {
                    "opis_id": opis_id,
                    "name": " ".join(row["Truckstop Name"].split()),
                    "address": " ".join(row["Address"].split()),
                    "city": city,
                    "state": state,
                    "rack_id": int(row["Rack ID"]),
                    "price": price,
                    "latitude": location[0],
                    "longitude": location[1],
                }
    report = ImportReport(rows, len(stations), non_us, unlocated)
    return list(stations.values()), report


def import_stations(station_model, prices_path: Path | None = None) -> ImportReport:
    """Replace all stations with the contents of the price file. Idempotent."""
    data_dir = Path(settings.DATA_DIR)
    records, report = read_stations(
        prices_path or data_dir / "fuel-prices.csv", data_dir / "station_cities.csv"
    )
    with transaction.atomic():
        station_model.objects.all().delete()
        station_model.objects.bulk_create(
            [station_model(**record) for record in records], batch_size=1000
        )
    return report
