from pathlib import Path

from django.core.management.base import BaseCommand

from stations.importer import import_stations
from stations.index import reset_station_index
from stations.models import FuelStation


class Command(BaseCommand):
    help = "Load (or reload) fuel stations from the fuel price CSV."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, help="CSV path (default: data/fuel-prices.csv)")

    def handle(self, *args, **options):
        report = import_stations(FuelStation, options["file"])
        reset_station_index()
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {report.stations} stations from {report.rows} rows "
                f"(skipped {report.skipped_non_us} outside the US, "
                f"{report.skipped_unlocated} without coordinates)."
            )
        )
