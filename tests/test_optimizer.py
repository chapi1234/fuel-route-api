import itertools
import random

import pytest

from planner.optimizer import Candidate, NoFuelInRange, plan_fuel_stops


def plan(stations, route_miles, **kwargs):
    candidates = [Candidate(mile, price) for mile, price in stations]
    return plan_fuel_stops(candidates, route_miles, **kwargs)


def stops(result):
    return [(p.mile, round(p.gallons, 6)) for p in result.purchases]


def test_trip_within_one_tank_needs_no_stops():
    result = plan([(100, 3.00), (300, 2.50)], 450)
    assert result.purchases == []
    assert result.total_cost == 0
    assert (result.trip_gallons, result.starting_gallons) == (45, 45)


def test_buys_only_what_the_starting_tank_does_not_cover():
    result = plan([(400, 3.00)], 700)
    assert stops(result) == [(400, 20)]  # arrives with 10 gal, needs 30 for the last 300 mi
    assert result.total_cost == pytest.approx(60.0)


def test_waits_for_the_cheaper_station_when_the_tank_allows():
    result = plan([(300, 4.00), (450, 3.00)], 800)
    assert stops(result) == [(450, 30)]


def test_buys_just_enough_to_reach_a_cheaper_station():
    result = plan([(450, 4.00), (600, 3.00)], 1100)
    # Arrives at mile 450 with 5 gal; buys 10 to reach mile 600, then 50 there.
    assert stops(result) == [(450, 10), (600, 50)]


def test_fills_up_when_the_current_station_is_the_cheapest_in_range():
    result = plan([(400, 3.00), (850, 4.00), (900, 3.50)], 1300)
    # Fill at $3.00 (40 gal), then at mile 900 buy only what is left to arrive empty.
    assert stops(result) == [(400, 40), (900, 40)]


def test_gallons_bought_plus_starting_tank_cover_the_trip():
    result = plan([(240, 3.9), (410, 2.9), (700, 3.4), (880, 3.1), (1150, 3.3)], 1400)
    assert result.total_gallons + result.starting_gallons == pytest.approx(140.0)


def test_records_fuel_left_on_arrival():
    result = plan([(400, 3.00)], 700)
    assert result.purchases[0].fuel_on_arrival == pytest.approx(10.0)


def test_the_cheapest_of_stations_at_the_same_place_is_used():
    result = plan([(400, 3.50), (400, 3.10)], 700)
    assert [p.price for p in result.purchases] == [3.10]


def test_gap_longer_than_a_tank_is_reported():
    with pytest.raises(NoFuelInRange) as error:
        plan([(100, 3.0), (700, 3.0)], 800)
    assert (error.value.from_mile, error.value.to_mile) == (100, 700)


def test_first_station_out_of_range_is_reported():
    with pytest.raises(NoFuelInRange):
        plan([(510, 3.0)], 800)


def test_long_trip_without_stations_is_reported():
    with pytest.raises(NoFuelInRange):
        plan([], 501)


def test_stations_past_the_destination_are_ignored():
    result = plan([(450, 3.5), (650, 1.0)], 600)
    assert [p.mile for p in result.purchases] == [450]


def test_stop_cost_avoids_tiny_top_ups():
    # Prices fall slowly along the route: the cheapest bill tops up at every station.
    stations = [(500, 3.20), (600, 3.19), (700, 3.18), (800, 3.17), (900, 3.16)]
    cheapest = plan(stations, 1000)
    sensible = plan(stations, 1000, stop_cost=10)
    assert len(cheapest.purchases) == 5
    assert len(sensible.purchases) == 1
    assert sensible.total_cost - cheapest.total_cost == pytest.approx(1.0)  # $1 for 4 stops


def brute_force(stations, route_miles, tank, mpg, stop_cost=0.0):
    """Exact minimum of fuel cost + stop_cost per stop, by dynamic programming over
    whole gallons (the test oracle). The truck starts with a full tank.

    Returns (objective, fuel cost).
    """
    miles = [m for m, _ in stations] + [route_miles]
    prices = [p for _, p in stations]
    first_leg = miles[0] // mpg
    if first_leg > tank:
        return float("inf"), float("inf")
    states = {tank - first_leg: (0.0, 0.0)}  # gallons on arrival -> (objective, cost)
    for i in range(len(stations)):
        leg = (miles[i + 1] - miles[i]) // mpg
        following: dict[int, tuple[float, float]] = {}
        for fuel, (objective, cost) in states.items():
            for buy in range(tank - fuel + 1):
                if fuel + buy < leg:
                    continue
                option = (objective + buy * prices[i] + stop_cost * (buy > 0),
                          cost + buy * prices[i])  # fmt: skip
                left = fuel + buy - leg
                if left not in following or option < following[left]:
                    following[left] = option
        states = following
    # Fuel left at the destination is never needed; the cheapest plan leaves none
    # unless the starting tank alone covers the trip.
    return min(states.values(), default=(float("inf"), float("inf")))


def random_trip(seed):
    rng = random.Random(seed)
    miles = sorted(rng.sample(range(10, 400, 10), rng.randint(1, 9)))
    stations = [(m, round(rng.uniform(2.5, 4.5), 3)) for m in miles]
    route = rng.choice(range(miles[-1], miles[-1] + 130, 10))
    return stations, route


def feasible(stations, route, range_miles):
    miles = [m for m, _ in stations]
    return all(b - a <= range_miles for a, b in itertools.pairwise([0, *miles, route]))


@pytest.mark.parametrize("seed", range(300))
def test_matches_brute_force_on_random_trips(seed):
    tank, mpg = 12, 10  # a small tank keeps the oracle fast; distances are whole gallons
    stations, route = random_trip(seed)
    if not feasible(stations, route, tank * mpg):
        with pytest.raises(NoFuelInRange):
            plan(stations, route, tank_gallons=tank, mpg=mpg)
        return
    result = plan(stations, route, tank_gallons=tank, mpg=mpg)
    assert result.total_cost == pytest.approx(brute_force(stations, route, tank, mpg)[1])
    assert result.total_gallons + result.starting_gallons == pytest.approx(route / mpg)


@pytest.mark.parametrize("seed", range(300))
def test_stop_cost_matches_brute_force_on_random_trips(seed):
    tank, mpg, stop_cost = 12, 10, 1.5
    stations, route = random_trip(seed)
    if not feasible(stations, route, tank * mpg):
        return
    result = plan(stations, route, tank_gallons=tank, mpg=mpg, stop_cost=stop_cost)
    objective = result.total_cost + stop_cost * len(result.purchases)
    expected, _ = brute_force(stations, route, tank, mpg, stop_cost)
    assert objective == pytest.approx(expected, abs=1e-4)
