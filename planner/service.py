"""Plan a trip: resolve places, get the route (one external call), choose fuel stops."""

import logging
import time
from dataclasses import dataclass, field

import httpx
import numpy as np
from django.conf import settings
from django.core.cache import cache

from geo.geometry import simplify
from geo.places import Place, geocode, resolve_offline
from planner.corridor import stations_along_route
from planner.optimizer import Candidate, plan_fuel_stops
from routing.providers import Route, Router, get_router
from stations.index import get_station_index
from stations.models import FuelStation

logger = logging.getLogger(__name__)

ROUTE_CACHE_SECONDS = 24 * 60 * 60
RESPONSE_TOLERANCE_MILES = 0.05  # geometry sent back to the client


@dataclass(frozen=True)
class TripRequest:
    start: str
    finish: str
    max_range_miles: float = 500.0
    mpg: float = 10.0
    corridor_miles: float = 10.0
    stop_cost: float = 5.0  # USD weighed against each stop; see planner/optimizer.py

    @property
    def tank_gallons(self) -> float:
        return self.max_range_miles / self.mpg


@dataclass
class CallCounter:
    routing: int = 0
    geocoding: int = 0
    cached_route: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)


class SamePlace(Exception):
    pass


_client: httpx.Client | None = None


def http_client() -> httpx.Client:
    """One shared client per process: building TLS context costs ~0.5 s on every new client."""
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
        )
    return _client


def plan_trip(request: TripRequest, router: Router | None = None) -> dict:
    """Build the full trip plan as a JSON-ready dict."""
    router = router or get_router()
    calls = CallCounter()
    started = time.perf_counter()
    client = http_client()
    start = _resolve(request.start, client, calls)
    finish = _resolve(request.finish, client, calls)
    if abs(start.lat - finish.lat) < 1e-4 and abs(start.lon - finish.lon) < 1e-4:
        raise SamePlace("Start and finish are the same place.")
    route = _route(router, start, finish, client, calls)
    calls.timings_ms["locate_and_route"] = (time.perf_counter() - started) * 1000

    computed = time.perf_counter()
    corridor = stations_along_route(
        route.coords, route.miles, get_station_index(), request.corridor_miles
    )
    candidates = [Candidate(s.mile, s.price) for s in corridor]
    fuel_plan = plan_fuel_stops(
        candidates,
        route.miles,
        tank_gallons=request.tank_gallons,
        mpg=request.mpg,
        stop_cost=request.stop_cost,
    )
    chosen = [corridor[p.index] for p in fuel_plan.purchases]
    stations = FuelStation.objects.in_bulk([s.station_id for s in chosen])
    calls.timings_ms["planning"] = (time.perf_counter() - computed) * 1000

    stops = []
    for number, (purchase, match) in enumerate(
        zip(fuel_plan.purchases, chosen, strict=True), start=1
    ):
        station = stations[match.station_id]
        stops.append(
            {
                "stop": number,
                "mile": round(purchase.mile, 1),
                "off_route_miles": round(match.off_route_miles, 1),
                "station": {
                    "opis_id": station.opis_id,
                    "name": station.name,
                    "address": station.address,
                    "city": station.city,
                    "state": station.state,
                },
                "location": {"lat": station.latitude, "lon": station.longitude},
                "price_per_gallon": round(purchase.price, 3),
                "gallons": round(purchase.gallons, 2),
                "cost": round(purchase.cost, 2),
                "fuel_on_arrival_gallons": round(purchase.fuel_on_arrival, 2),
            }
        )

    total_gallons = fuel_plan.total_gallons
    total_cost = fuel_plan.total_cost
    kept = simplify(route.coords, RESPONSE_TOLERANCE_MILES)
    return {
        "start": _place_json(start),
        "finish": _place_json(finish),
        "route": {
            "distance_miles": round(route.miles, 1),
            "duration_hours": round(route.duration_seconds / 3600, 2),
            "provider": route.provider,
            "profile": route.profile,
            "geometry": {
                "type": "LineString",
                "coordinates": np.round(route.coords[kept], 5).tolist(),
            },
        },
        "vehicle": {
            "max_range_miles": request.max_range_miles,
            "mpg": request.mpg,
            "tank_gallons": round(request.tank_gallons, 2),
            "starts_with_full_tank": True,
        },
        "fuel_stops": stops,
        "summary": {
            "total_fuel_cost": round(total_cost, 2),
            "gallons_purchased": round(total_gallons, 2),
            "number_of_stops": len(stops),
            "average_price_per_gallon": round(total_cost / total_gallons, 3)
            if total_gallons
            else None,
            "trip_gallons": round(fuel_plan.trip_gallons, 2),
            "starting_tank_gallons_used": round(fuel_plan.starting_gallons, 2),
            "stations_within_corridor": len(corridor),
            "corridor_miles": request.corridor_miles,
            "stop_cost": request.stop_cost,
        },
        "meta": {
            "external_api_calls": {"routing": calls.routing, "geocoding": calls.geocoding},
            "route_from_cache": calls.cached_route,
            "timings_ms": {k: round(v, 1) for k, v in calls.timings_ms.items()},
        },
    }


def _resolve(query: str, client: httpx.Client, calls: CallCounter) -> Place:
    place = resolve_offline(query)
    if place is not None:
        return place
    key = f"geocode:{query.strip().lower()}"
    cached = cache.get(key)
    if cached is not None:
        return Place(**cached)
    calls.geocoding += 1
    place = geocode(query, client)
    cache.set(key, place.__dict__, ROUTE_CACHE_SECONDS)
    return place


def _route(
    router: Router, start: Place, finish: Place, client: httpx.Client, calls: CallCounter
) -> Route:
    key = (
        f"route:{router.name}:{router.profile}:"
        f"{start.lat:.4f},{start.lon:.4f}:{finish.lat:.4f},{finish.lon:.4f}"
    )
    cached = cache.get(key)
    if cached is not None:
        calls.cached_route = True
        return Route(coords=np.asarray(cached.pop("coords")), **cached)
    calls.routing += 1
    route = router.route((start.lat, start.lon), (finish.lat, finish.lon), client)
    logger.info(
        "Routed %s -> %s: %.0f mi via %s", start.label, finish.label, route.miles, route.provider
    )
    cache.set(
        key,
        {
            "coords": route.coords.tolist(),
            "miles": route.miles,
            "duration_seconds": route.duration_seconds,
            "provider": route.provider,
            "profile": route.profile,
        },
        ROUTE_CACHE_SECONDS,
    )
    return route


def _place_json(place: Place) -> dict:
    return {
        "query": place.query,
        "label": place.label,
        "lat": round(place.lat, 5),
        "lon": round(place.lon, 5),
        "resolved_by": place.source,
    }
