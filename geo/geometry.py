"""Small, vectorised geometry helpers for route lines given as (lon, lat) degrees."""

import numpy as np

EARTH_RADIUS_MILES = 3958.7613
MILES_PER_DEGREE_LAT = 69.055


def haversine_miles(lon1, lat1, lon2, lat2):
    """Great-circle distance in miles; accepts scalars or NumPy arrays."""
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def cumulative_miles(coords: np.ndarray) -> np.ndarray:
    """Distance from the first vertex to every vertex of a (n, 2) lon/lat line."""
    if len(coords) < 2:
        return np.zeros(len(coords))
    legs = haversine_miles(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    return np.concatenate([[0.0], np.cumsum(legs)])


def _local_xy(coords: np.ndarray) -> np.ndarray:
    """Project to miles with a per-vertex scale; accurate enough for small tolerances."""
    x = coords[:, 0] * np.cos(np.radians(coords[:, 1])) * MILES_PER_DEGREE_LAT
    y = coords[:, 1] * MILES_PER_DEGREE_LAT
    return np.column_stack([x, y])


def simplify(coords: np.ndarray, tolerance_miles: float) -> np.ndarray:
    """Ramer-Douglas-Peucker simplification. Returns the indices of the kept vertices."""
    n = len(coords)
    if n <= 2:
        return np.arange(n)
    xy = _local_xy(coords)
    keep = np.zeros(n, dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        a, b = xy[start], xy[end]
        points = xy[start + 1 : end]
        ab = b - a
        length = np.hypot(*ab)
        if length == 0:
            distances = np.hypot(*(points - a).T)
        else:
            distances = np.abs(ab[0] * (points[:, 1] - a[1]) - ab[1] * (points[:, 0] - a[0]))
            distances /= length
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance_miles:
            split = start + 1 + worst
            keep[split] = True
            stack.extend([(start, split), (split, end)])
    return np.flatnonzero(keep)


def project_points(
    lon: np.ndarray,
    lat: np.ndarray,
    line: np.ndarray,
    line_miles: np.ndarray,
    chunk: int = 256,
) -> tuple[np.ndarray, np.ndarray]:
    """Project points onto a polyline.

    Returns, for every point, its distance from the line (miles) and the distance
    along the line to its closest position (miles, using ``line_miles`` at vertices).
    Distances are measured in a flat frame centred on each point, which is accurate
    for the few-mile offsets that matter here.
    """
    if len(line) < 2:
        raise ValueError("A line needs at least two vertices.")
    off = np.empty(len(lon))
    along = np.empty(len(lon))
    start, end = line[:-1], line[1:]
    seg_miles = np.diff(line_miles)
    for i in range(0, len(lon), chunk):
        plon, plat = lon[i : i + chunk, None], lat[i : i + chunk, None]
        scale_x = np.cos(np.radians(plat)) * MILES_PER_DEGREE_LAT
        ax = (start[None, :, 0] - plon) * scale_x
        ay = (start[None, :, 1] - plat) * MILES_PER_DEGREE_LAT
        bx = (end[None, :, 0] - plon) * scale_x
        by = (end[None, :, 1] - plat) * MILES_PER_DEGREE_LAT
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.where(length2 > 0, -(ax * dx + ay * dy) / length2, 0.0)
        t = np.clip(t, 0.0, 1.0)
        distance = np.hypot(ax + t * dx, ay + t * dy)
        best = np.argmin(distance, axis=1)
        rows = np.arange(len(best))
        off[i : i + chunk] = distance[rows, best]
        along[i : i + chunk] = line_miles[best] + t[rows, best] * seg_miles[best]
    return off, along
