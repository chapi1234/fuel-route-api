"""Find the stations near a route and where along the route each one is."""

from dataclasses import dataclass

import numpy as np

from geo.geometry import MILES_PER_DEGREE_LAT, cumulative_miles, project_points, simplify
from stations.index import StationIndex

# Tolerance for the line used to measure station offsets; 0.1 mi keeps the matching
# exact for practical purposes while cutting a cross-country line to ~2k vertices.
MATCH_TOLERANCE_MILES = 0.1


@dataclass(frozen=True)
class CorridorStation:
    station_id: int
    mile: float  # distance along the route from the origin
    off_route_miles: float
    price: float


def stations_along_route(
    coords: np.ndarray,
    route_miles: float,
    index: StationIndex,
    corridor_miles: float,
) -> list[CorridorStation]:
    """Stations within ``corridor_miles`` of the route, sorted by position along it.

    ``coords`` is the route as an (n, 2) lon/lat array. Positions are scaled so that
    the end of the line is at ``route_miles`` (the router's own distance).
    """
    if len(index) == 0 or len(coords) < 2:
        return []

    vertex_miles = cumulative_miles(coords)
    if vertex_miles[-1] > 0:
        vertex_miles *= route_miles / vertex_miles[-1]
    kept = simplify(coords, MATCH_TOLERANCE_MILES)
    line, line_miles = coords[kept], vertex_miles[kept]

    candidates = _near_line(index, line, corridor_miles)
    if candidates.size == 0:
        return []
    off, along = project_points(index.lon[candidates], index.lat[candidates], line, line_miles)
    inside = off <= corridor_miles
    order = np.lexsort((index.price[candidates][inside], along[inside]))
    chosen = candidates[inside][order]
    return [
        CorridorStation(
            station_id=int(index.ids[i]),
            mile=float(m),
            off_route_miles=float(o),
            price=float(index.price[i]),
        )
        for i, m, o in zip(chosen, along[inside][order], off[inside][order], strict=True)
    ]


def _near_line(index: StationIndex, line: np.ndarray, corridor_miles: float) -> np.ndarray:
    """Cheap pre-filter: stations in grid cells the line passes through, plus neighbours.

    Cells are at least ``corridor_miles`` tall and wide, so any station within the
    corridor is in the same or an adjacent cell to some point on the line. The line is
    densified first so a long straight segment marks every cell it crosses.
    """
    cell = max(corridor_miles, 5.0) / MILES_PER_DEGREE_LAT  # degrees of latitude
    # A degree of longitude shrinks towards the poles, so longitude cells are widened
    # for the most northern latitude the corridor reaches.
    max_lat = min(np.max(np.abs(line[:, 1])) + 2 * cell, 89.0)
    cell_lon = cell / np.cos(np.radians(max_lat))
    dense = _densify(line, cell / 2)
    rows = np.floor(dense[:, 1] / cell).astype(np.int64)
    cols = np.floor(dense[:, 0] / cell_lon).astype(np.int64)
    marked = {
        (r + dr, c + dc)
        for r, c in zip(rows, cols, strict=True)
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
    }
    station_rows = np.floor(index.lat / cell).astype(np.int64)
    station_cols = np.floor(index.lon / cell_lon).astype(np.int64)
    hit = np.fromiter(
        ((r, c) in marked for r, c in zip(station_rows, station_cols, strict=True)),
        dtype=bool,
        count=len(index),
    )
    return np.flatnonzero(hit)


def _densify(line: np.ndarray, step_degrees: float) -> np.ndarray:
    """Insert points so no two consecutive vertices are more than ``step_degrees`` apart."""
    pieces = [line[:1]]
    for a, b in zip(line[:-1], line[1:], strict=True):
        steps = max(1, int(np.ceil(np.max(np.abs(b - a)) / step_degrees)))
        t = np.linspace(0, 1, steps + 1)[1:, None]
        pieces.append(a + t * (b - a))
    return np.concatenate(pieces)
