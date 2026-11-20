from django.db import models


class FuelStation(models.Model):
    """A truck stop from the provided price file, located at its city's coordinates."""

    opis_id = models.PositiveIntegerField(unique=True, help_text="OPIS Truckstop ID")
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField()
    price = models.DecimalField(
        max_digits=10, decimal_places=8, help_text="Retail price per gallon, USD"
    )
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ["opis_id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.price:.3f}"
