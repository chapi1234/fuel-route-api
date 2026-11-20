import itertools
import random

import pytest

from planner.optimizer import Candidate, NoFuelInRange, plan_fuel_stops


def plan(stations, route_miles, **kwargs):
    candidates = [Candidate(mile, price) for mile, price in stations]
    return plan_fuel_stops(candidates, route_miles, **kwargs)


def stops(result):
    return [(p.mile, round(p.gallons, 6)) for p in result.purchases]


def test_short_trip_buys_exactly_the_fuel_it_needs_at_the_start():
    result = plan([(0, 3.00), (100, 3.50)], 300)
    assert stops(result) == [(0, 30)]
    assert result.total_cost == pytest.approx(90.0)


def test_buys_just_enough_to_reach_a_cheaper_station():
    result = plan([(0, 4.00), (200, 3.00)], 600)
    assert stops(result) == [(0, 20), (200, 40)]
    assert result.total_cost == pytest.approx(20 * 4 + 40 * 3)


def test_fills_up_when_the_current_station_is_the_cheapest_in_range():
    # Fill up at $3.00, then go to the cheapest station in range ($3.50 at mile 500)
    # and buy only what is left to reach the destination.
    result = plan([(0, 3.00), (450, 4.00), (500, 3.50)], 900)
    assert stops(result) == [(0, 50), (500, 40)]


def test_skips_an_expensive_station_it_can_drive_past():
    result = plan([(0, 3.00), (300, 5.00), (480, 3.10)], 700)
    assert [mile for mile, _ in stops(result)] == [0, 480]


def test_total_gallons_equal_trip_miles_over_mpg():
    result = plan([(5, 3.2), (240, 3.9), (410, 2.9), (700, 3.4), (880, 3.1)], 1100)
    assert result.total_gallons == pytest.approx(110.0)


def test_fuel_to_reach_the_first_station_is_bought_there():
    result = plan([(12, 3.0)], 112)
    assert result.purchases[0].gallons == pytest.approx(11.2)


def test_records_fuel_left_on_arrival():
    result = plan([(0, 3.00), (450, 4.00), (500, 3.50)], 900)
    assert result.purchases[1].fuel_on_arrival == pytest.approx(0.0)


def test_gap_longer_than_a_tank_is_reported():
    with pytest.raises(NoFuelInRange) as error:
        plan([(0, 3.0), (600, 3.0)], 800)
    assert (error.value.from_mile, error.value.to_mile) == (0, 600)


def test_first_station_out_of_range_is_reported():
    with pytest.raises(NoFuelInRange):
        plan([(510, 3.0)], 800)


def test_no_stations_at_all_is_reported():
    with pytest.raises(NoFuelInRange):
        plan([], 50)


def test_stations_past_the_destination_are_ignored():
    result = plan([(0, 3.5), (150, 1.0)], 100)
    assert [p.mile for p in result.purchases] == [0]


def brute_force_cost(stations, route_miles, tank, mpg):
    """Exact minimum by dynamic programming over whole gallons (the test oracle)."""
    miles = [m for m, _ in stations] + [route_miles]
    prices = [p for _, p in stations]
    states = {0: 0.0}  # gallons in the tank on arrival -> cheapest cost so far
    for i in range(len(stations)):
        leg = (miles[i + 1] - miles[i]) // mpg
        following: dict[int, float] = {}
        for fuel, cost in states.items():
            for buy in range(tank - fuel + 1):
                if fuel + buy >= leg:
                    left = fuel + buy - leg
                    total = cost + buy * prices[i]
                    following[left] = min(following.get(left, float("inf")), total)
        states = following
    origin_leg = miles[0] // mpg
    return states.get(0, float("inf")) + origin_leg * prices[0]


@pytest.mark.parametrize("seed", range(300))
def test_matches_brute_force_on_random_trips(seed):
    rng = random.Random(seed)
    tank, mpg = 12, 10  # a small tank keeps the oracle fast; distances are whole gallons
    miles = sorted(rng.sample(range(0, 300, 10), rng.randint(1, 8)))
    stations = [(m, round(rng.uniform(2.5, 4.5), 3)) for m in miles]
    route = rng.choice(range(miles[-1], miles[-1] + 130, 10))
    gaps = [b - a for a, b in itertools.pairwise([*miles, route])]
    if miles[0] > tank * mpg or any(gap > tank * mpg for gap in gaps):
        with pytest.raises(NoFuelInRange):
            plan(stations, route, tank_gallons=tank, mpg=mpg)
        return
    greedy = plan(stations, route, tank_gallons=tank, mpg=mpg)
    assert greedy.total_cost == pytest.approx(brute_force_cost(stations, route, tank, mpg))
    assert greedy.total_gallons == pytest.approx(route / mpg)
