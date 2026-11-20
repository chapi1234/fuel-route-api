"""Routing providers. Each request costs exactly one call to the provider.

* OpenRouteService (``ORS_API_KEY`` set): the ``driving-hgv`` (truck) profile.
* OSRM public server (default, no key): the car profile.

Both return the full route geometry and distance in that single call.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx
import numpy as np
from django.conf import settings

METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class Route:
    coords: np.ndarray  # (n, 2) lon/lat
    miles: float
    duration_seconds: float
    provider: str
    profile: str


class RoutingError(Exception):
    """The provider failed or returned no route."""


class NoRouteFound(RoutingError):
    """The provider answered, but there is no road route between the points."""


class Router(Protocol):
    name: str
    profile: str

    def route(
        self, start: tuple[float, float], finish: tuple[float, float], client: httpx.Client
    ) -> Route: ...


class OSRMRouter:
    name = "osrm"
    profile = "driving"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def route(self, start, finish, client):
        (lat1, lon1), (lat2, lon2) = start, finish
        url = f"{self.base_url}/route/v1/{self.profile}/{lon1},{lat1};{lon2},{lat2}"
        try:
            response = client.get(url, params={"overview": "full", "geometries": "geojson"})
        except httpx.HTTPError as error:
            raise RoutingError(f"OSRM request failed: {error}") from error
        payload = _json(response)
        if payload.get("code") == "NoRoute" or (response.is_success and not payload.get("routes")):
            raise NoRouteFound("No road route between these points.")
        if not response.is_success or payload.get("code") != "Ok":
            raise RoutingError(f"OSRM error: {payload.get('message') or response.status_code}")
        best = payload["routes"][0]
        return Route(
            coords=np.asarray(best["geometry"]["coordinates"], dtype=float),
            miles=best["distance"] / METERS_PER_MILE,
            duration_seconds=float(best["duration"]),
            provider=self.name,
            profile=self.profile,
        )


class OpenRouteServiceRouter:
    name = "openrouteservice"
    profile = "driving-hgv"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def route(self, start, finish, client):
        (lat1, lon1), (lat2, lon2) = start, finish
        try:
            response = client.post(
                f"{self.base_url}/v2/directions/{self.profile}/geojson",
                json={"coordinates": [[lon1, lat1], [lon2, lat2]]},
                headers={"Authorization": self.api_key},
            )
        except httpx.HTTPError as error:
            raise RoutingError(f"OpenRouteService request failed: {error}") from error
        payload = _json(response)
        if not response.is_success:
            message = (payload.get("error") or {}).get("message") or str(response.status_code)
            code = (payload.get("error") or {}).get("code")
            if code in {2009, 2010, 2099}:  # route not found / point not routable
                raise NoRouteFound(message)
            raise RoutingError(f"OpenRouteService error: {message}")
        feature = payload["features"][0]
        summary = feature["properties"]["summary"]
        return Route(
            coords=np.asarray(feature["geometry"]["coordinates"], dtype=float),
            miles=summary["distance"] / METERS_PER_MILE,
            duration_seconds=float(summary.get("duration", 0.0)),
            provider=self.name,
            profile=self.profile,
        )


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_router() -> Router:
    if settings.ORS_API_KEY:
        return OpenRouteServiceRouter(settings.ORS_API_KEY, settings.ORS_BASE_URL)
    return OSRMRouter(settings.OSRM_BASE_URL)
