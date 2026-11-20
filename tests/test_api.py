import numpy as np
import pytest
from django.core.cache import cache

from planner.models import TripPlan
from routing.providers import NoRouteFound, Route, RoutingError
from stations.index import reset_station_index
from stations.models import FuelStation

pytestmark = pytest.mark.django_db

URL = "/api/v1/trip-plans"


class FakeRouter:
    """Always returns the same straight road along latitude 40, lon -100 to -90 (~530 mi)."""

    name, profile = "fake", "driving"

    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def route(self, start, finish, client):
        self.calls += 1
        if self.error:
            raise self.error
        coords = np.column_stack([np.linspace(-100.0, -90.0, 50), np.full(50, 40.0)])
        return Route(coords, miles=530.0, duration_seconds=8 * 3600, provider="fake",
                     profile="driving")  # fmt: skip


@pytest.fixture
def router(monkeypatch):
    fake = FakeRouter()
    monkeypatch.setattr("planner.service.get_router", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def stations(db):
    """Replace the bundled stations with a few on the fake road."""
    cache.clear()
    FuelStation.objects.all().delete()
    rows = [
        (1, "WEST STOP", -99.95, 3.40),
        (2, "MIDDLE STOP", -95.0, 2.90),
        (3, "OFF ROAD", -95.0, 3.00, 41.0),  # ~69 mi north: outside the corridor
        (4, "EAST STOP", -91.0, 3.60),
    ]
    for opis_id, name, lon, price, *lat in rows:
        FuelStation.objects.create(
            opis_id=opis_id, name=name, address="I-80, EXIT 1", city="Town", state="NE",
            rack_id=1, price=price, latitude=lat[0] if lat else 40.0, longitude=lon,
        )  # fmt: skip
    reset_station_index()
    yield
    reset_station_index()


def plan(client, **body):
    return client.post(URL, {"start": "40,-100", "finish": "40,-90", **body},
                       content_type="application/json")  # fmt: skip


def test_plans_a_trip_with_one_routing_call(client, router):
    response = plan(client)
    assert response.status_code == 201
    body = response.json()
    assert router.calls == 1
    assert body["meta"]["external_api_calls"] == {"routing": 1, "geocoding": 0}
    assert [s["station"]["name"] for s in body["fuel_stops"]] == ["WEST STOP", "MIDDLE STOP"]
    assert body["summary"]["total_gallons"] == pytest.approx(53.0)
    expected = sum(s["gallons"] * s["price_per_gallon"] for s in body["fuel_stops"])
    assert body["summary"]["total_fuel_cost"] == pytest.approx(expected, abs=0.02)
    assert body["route"]["geometry"]["type"] == "LineString"
    assert body["map_url"].endswith(f"/api/v1/trip-plans/{body['id']}/map")


def test_repeated_trip_uses_the_cached_route(client, router):
    plan(client)
    body = plan(client).json()
    assert router.calls == 1
    assert body["meta"]["route_from_cache"] is True
    assert body["meta"]["external_api_calls"]["routing"] == 0


def test_saved_plan_and_map_can_be_fetched(client, router):
    body = plan(client).json()
    detail = client.get(f"{URL}/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["summary"] == body["summary"]
    page = client.get(f"{URL}/{body['id']}/map")
    assert page.status_code == 200
    assert b"leaflet" in page.content
    assert b"MIDDLE STOP" in page.content


def test_unknown_plan_is_404(client):
    assert client.get(f"{URL}/00000000-0000-0000-0000-000000000000").status_code == 404


def test_city_names_resolve_without_a_geocoding_call(client, router):
    body = client.post(URL, {"start": "Lincoln, NE", "finish": "Omaha, NE"},
                       content_type="application/json").json()  # fmt: skip
    assert body["start"]["resolved_by"] == "places"
    assert body["meta"]["external_api_calls"]["geocoding"] == 0


@pytest.mark.parametrize(
    ("body", "field"),
    [({"start": "40,-100"}, "finish"), ({"start": "", "finish": "x"}, "start"),
     ({"start": "a", "finish": "b", "corridor_miles": 500}, "corridor_miles")],
)  # fmt: skip
def test_invalid_requests_are_400(client, body, field):
    response = client.post(URL, body, content_type="application/json")
    assert response.status_code == 400
    assert field in response.json()["detail"]


def test_outside_the_usa_is_422(client, router):
    response = client.post(URL, {"start": "51.5,-0.12", "finish": "40,-90"},
                           content_type="application/json")  # fmt: skip
    assert response.status_code == 422
    assert response.json()["error"] == "outside_usa"
    assert router.calls == 0


def test_same_start_and_finish_is_422(client, router):
    response = client.post(URL, {"start": "40,-90", "finish": "40,-90"},
                           content_type="application/json")  # fmt: skip
    assert response.json()["error"] == "same_place"


def test_gap_without_fuel_is_422(client, router):
    FuelStation.objects.filter(opis_id__in=[2, 4]).delete()
    reset_station_index()
    response = plan(client)
    assert response.status_code == 422
    assert response.json()["error"] == "no_fuel_in_range"


def test_no_route_is_422(client, monkeypatch):
    monkeypatch.setattr("planner.service.get_router", lambda: FakeRouter(NoRouteFound("none")))
    assert plan(client).json()["error"] == "no_route"


def test_provider_failure_is_502(client, monkeypatch):
    monkeypatch.setattr("planner.service.get_router", lambda: FakeRouter(RoutingError("down")))
    response = plan(client)
    assert response.status_code == 502
    assert TripPlan.objects.count() == 0


def test_openapi_docs_are_served(client):
    assert client.get("/api/schema").status_code == 200
    assert client.get("/api/docs").status_code == 200
