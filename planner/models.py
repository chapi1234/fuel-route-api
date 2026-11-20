import uuid

from django.db import models


class TripPlan(models.Model):
    """A computed plan, kept so its map can be opened later by id."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    start = models.CharField(max_length=200)
    finish = models.CharField(max_length=200)
    result = models.JSONField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.start} -> {self.finish}"
