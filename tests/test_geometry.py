import numpy as np
import pytest

from geo.geometry import cumulative_miles, haversine_miles, project_points, simplify
from planner.corridor import stations_along_route
from stations.index import StationIndex


def test_haversine_one_degree_of_latitude():
    assert haversine_miles(-100.0, 40.0, -100.0, 41.0) == pytest.approx(69.09, abs=0.05)


def test_haversine_new_york_to_los_angeles():
    assert haversine_miles(-74.006, 40.7128, -118.2437, 34.0522) == pytest.approx(2445, rel=0.01)


def test_cumulative_miles_starts_at_zero_and_adds_legs():
    line = np.array([[-100.0, 40.0], [-100.0, 41.0], [-100.0, 42.0]])
    miles = cumulative_miles(line)
    assert miles[0] == 0
    assert miles[-1] == pytest.approx(2 * 69.09, abs=0.1)


def test_simplify_drops_collinear_points_and_keeps_corners():
    line = np.array([[0.0, 40.0], [0.5, 40.0], [1.0, 40.0], [1.0, 40.5], [1.0, 41.0]])
    assert simplify(line, 0.1).tolist() == [0, 2, 4]


def test_project_points_offset_and_position():
    line = np.array([[-100.0, 40.0], [-99.0, 40.0]])
    line_miles = cumulative_miles(line)
    # A point 0.1 degrees of latitude (~6.9 mi) north of the middle of the line.
    off, along = project_points(np.array([-99.5]), np.array([40.1]), line, line_miles)
    assert off[0] == pytest.approx(6.9, abs=0.05)
    assert along[0] == pytest.approx(line_miles[-1] / 2, rel=0.01)


def make_index(points):
    lon = np.array([p[0] for p in points], dtype=float)
    lat = np.array([p[1] for p in points], dtype=float)
    price = np.array([p[2] for p in points], dtype=float)
    return StationIndex(np.arange(1, len(points) + 1), lat, lon, price)


def test_stations_along_route_filters_by_corridor_and_orders_by_mile():
    line = np.array([[-100.0, 40.0], [-98.0, 40.0]])
    index = make_index(
        [
            (-98.5, 40.05, 3.0),  # ~3.5 mi off, near the end
            (-99.5, 40.0, 3.5),  # on the route, near the start
            (-99.0, 40.5, 2.0),  # ~35 mi off: outside a 10 mi corridor
        ]
    )
    found = stations_along_route(line, route_miles=110.0, index=index, corridor_miles=10)
    assert [s.station_id for s in found] == [2, 1]
    assert found[0].mile == pytest.approx(27.5, abs=0.5)  # positions scaled to route_miles
    assert found[1].off_route_miles == pytest.approx(3.45, abs=0.1)


def test_long_straight_segment_still_finds_stations_in_the_middle():
    line = np.array([[-110.0, 40.0], [-90.0, 40.0]])  # one ~1,060 mile segment
    index = make_index([(-100.0, 40.02, 3.0)])
    found = stations_along_route(line, route_miles=1060.0, index=index, corridor_miles=5)
    assert len(found) == 1


@pytest.mark.parametrize("seed", range(20))
def test_grid_prefilter_never_drops_a_station_inside_the_corridor(seed):
    rng = np.random.default_rng(seed)
    lat0 = rng.uniform(25, 48)
    lon = np.sort(rng.uniform(-120, -75, 6))
    line = np.column_stack([lon, lat0 + rng.uniform(-3, 3, 6)])
    stations = make_index([(rng.uniform(-121, -74), rng.uniform(22, 50), 3.0) for _ in range(3000)])
    corridor = float(rng.choice([5, 10, 25]))
    found = stations_along_route(line, 1000.0, stations, corridor)
    miles = cumulative_miles(line)
    off, _ = project_points(stations.lon, stations.lat, line, miles)
    expected = set(stations.ids[off <= corridor].tolist())
    assert {s.station_id for s in found} == expected
