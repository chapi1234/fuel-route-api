import httpx
import pytest
import respx

from routing.providers import (
    METERS_PER_MILE,
    NoRouteFound,
    OpenRouteServiceRouter,
    OSRMRouter,
    RoutingError,
    get_router,
)

START, FINISH = (39.74, -104.99), (39.10, -94.58)
OSRM_URL = "https://osrm.test/route/v1/driving/-104.99,39.74;-94.58,39.1"
ORS_URL = "https://ors.test/v2/directions/driving-hgv/geojson"


@respx.mock
def test_osrm_returns_geometry_and_distance_in_miles():
    respx.get(OSRM_URL).respond(
        json={
            "code": "Ok",
            "routes": [
                {
                    "distance": 100 * METERS_PER_MILE,
                    "duration": 5400,
                    "geometry": {"coordinates": [[-104.99, 39.74], [-94.58, 39.10]]},
                }
            ],
        }
    )
    with httpx.Client() as client:
        route = OSRMRouter("https://osrm.test").route(START, FINISH, client)
    assert route.miles == pytest.approx(100)
    assert route.coords.shape == (2, 2)
    assert (route.provider, route.profile) == ("osrm", "driving")


@respx.mock
def test_osrm_no_route():
    respx.get(OSRM_URL).respond(400, json={"code": "NoRoute", "message": "Impossible route"})
    with httpx.Client() as client, pytest.raises(NoRouteFound):
        OSRMRouter("https://osrm.test").route(START, FINISH, client)


@respx.mock
def test_osrm_server_error():
    respx.get(OSRM_URL).respond(503, text="busy")
    with httpx.Client() as client, pytest.raises(RoutingError):
        OSRMRouter("https://osrm.test").route(START, FINISH, client)


@respx.mock
def test_osrm_network_error():
    respx.get(OSRM_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))
    with httpx.Client() as client, pytest.raises(RoutingError):
        OSRMRouter("https://osrm.test").route(START, FINISH, client)


@respx.mock
def test_openrouteservice_uses_the_truck_profile_and_the_key():
    call = respx.post(ORS_URL).respond(
        json={
            "features": [
                {
                    "geometry": {"coordinates": [[-104.99, 39.74], [-94.58, 39.10]]},
                    "properties": {"summary": {"distance": 1609.344 * 600, "duration": 30000}},
                }
            ]
        }
    )
    with httpx.Client() as client:
        route = OpenRouteServiceRouter("secret", "https://ors.test").route(START, FINISH, client)
    assert call.calls.last.request.headers["Authorization"] == "secret"
    assert route.miles == pytest.approx(600)
    assert route.profile == "driving-hgv"


@respx.mock
def test_openrouteservice_route_not_found():
    respx.post(ORS_URL).respond(404, json={"error": {"code": 2009, "message": "Route not found"}})
    with httpx.Client() as client, pytest.raises(NoRouteFound):
        OpenRouteServiceRouter("k", "https://ors.test").route(START, FINISH, client)


def test_router_choice_follows_the_api_key(settings):
    settings.ORS_API_KEY = ""
    assert get_router().name == "osrm"
    settings.ORS_API_KEY = "abc"
    assert get_router().name == "openrouteservice"
