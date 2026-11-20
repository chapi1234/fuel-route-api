"""Choose where to buy fuel, and how much, so a trip costs as little as possible.

This is the fixed-route "gas station problem": stations sit at known distances along
the route with known prices, the tank holds ``tank_gallons``, and partial fills are
allowed. Pure price-minimisation tends to pick many tiny top-ups to save a few cents
(a stop for 1.3 gallons to save $0.04), which no driver would make. So each stop is
also charged ``stop_cost`` dollars, standing for the time it takes, and the plan
minimises

    fuel cost + stop_cost x number of stops

``stop_cost=0`` gives the cheapest possible fuel bill. The reported total is always
the fuel actually bought; the stop cost only shapes the choice.

Assumptions: the truck leaves the origin with a full tank, which is what lets it go
up to ``tank_gallons x mpg`` miles before the first stop. The destination counts as a
free station, so the truck never buys fuel it does not burn before arriving.

The solver is exact. It uses the structure proved by Khuller, Malekian & Mestre
("To fill or not to fill", 2007): in some optimal plan, at every stop the truck
either fills the tank (when the next stop is dearer) or buys just enough to reach
the next stop empty (when the next stop is cheaper or equal). So the tank level on
arrival at a stop is either empty or "full at an earlier, cheaper stop k, minus the
drive from k", and a dynamic program over (stop, arrival level) is exact. The full
starting tank fits that model as a free station at mile 0.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

EPSILON = 1e-9
TIE_BREAK_PER_STOP = 1e-6  # among plans of equal cost, prefer fewer stops
EMPTY = -1  # arrival state: tank empty (otherwise: the stop where the tank was filled)
ORIGIN = 0  # position of the virtual "starting tank" station in the internal arrays


@dataclass(frozen=True)
class Candidate:
    """A station that can be used, at ``mile`` along the route."""

    mile: float
    price: float  # USD per gallon


@dataclass(frozen=True)
class Purchase:
    index: int  # position in the candidate list passed in
    mile: float
    price: float
    gallons: float
    fuel_on_arrival: float  # gallons in the tank on arrival, before buying

    @property
    def cost(self) -> float:
        return self.gallons * self.price


@dataclass(frozen=True)
class FuelPlan:
    purchases: list[Purchase]
    trip_gallons: float  # fuel burned over the whole trip
    starting_gallons: float  # of which came from the tank the truck left with

    @property
    def total_gallons(self) -> float:
        return sum(p.gallons for p in self.purchases)

    @property
    def total_cost(self) -> float:
        return sum(p.cost for p in self.purchases)


class NoFuelInRange(Exception):
    """A stretch of the route is longer than one tank can cover."""

    def __init__(self, from_mile: float, to_mile: float, range_miles: float):
        self.from_mile, self.to_mile, self.range_miles = from_mile, to_mile, range_miles
        super().__init__(
            f"No fuel station within {range_miles:.0f} miles after mile {from_mile:.0f} "
            f"(the next fuel or the destination is at mile {to_mile:.0f})."
        )


def plan_fuel_stops(
    candidates: Sequence[Candidate],
    route_miles: float,
    *,
    tank_gallons: float = 50.0,
    mpg: float = 10.0,
    stop_cost: float = 0.0,
) -> FuelPlan:
    """Return the plan minimising fuel cost plus ``stop_cost`` per stop.

    ``candidates`` must be sorted by ``mile``; ``Purchase.index`` refers back to it.
    """
    range_miles = tank_gallons * mpg
    usable = _usable(candidates, route_miles)
    _check_reachable([candidates[i].mile for i in usable], route_miles, range_miles)

    # Internal stops: 0 is the starting tank (free fuel at mile 0), then the stations,
    # then the destination at position n (also free, so nothing is bought for it).
    miles = np.array([0.0] + [candidates[i].mile for i in usable] + [route_miles])
    price = np.array([0.0] + [candidates[i].price for i in usable] + [0.0])
    gallons_at = miles / mpg  # fuel needed to get there from the origin
    n = len(miles) - 1
    tank = tank_gallons
    penalty = stop_cost + TIE_BREAK_PER_STOP

    # cost_to_go[i][source]: cheapest cost from stop i to the destination, arriving at i
    # with the tank empty (source EMPTY) or after filling it at stop ``source``.
    cost_to_go: list[dict[int, float]] = [{} for _ in range(n + 1)]
    choice: list[dict[int, int]] = [{} for _ in range(n)]
    cost_to_go[n][EMPTY] = 0.0

    for i in range(n - 1, -1, -1):
        ahead = np.arange(i + 1, n + 1)
        ahead = ahead[gallons_at[ahead] - gallons_at[i] <= tank + EPSILON]
        behind = [
            k for k in range(i)
            if price[k] < price[i] and gallons_at[i] - gallons_at[k] <= tank + EPSILON
        ]  # fmt: skip
        sources = [EMPTY, *behind]
        arrival = np.array([0.0] + [tank - (gallons_at[i] - gallons_at[k]) for k in behind])

        leg = gallons_at[ahead] - gallons_at[i]
        cheaper = price[ahead] <= price[i]  # buy just enough and arrive empty
        next_empty = np.array([cost_to_go[j].get(EMPTY, np.inf) for j in ahead])
        next_filled = np.array(
            [
                np.inf if is_cheaper else cost_to_go[j].get(i, np.inf)
                for j, is_cheaper in zip(ahead, cheaper, strict=True)
            ]
        )

        buy = np.where(cheaper[None, :], leg[None, :] - arrival[:, None], tank - arrival[:, None])
        fees = np.where(buy > EPSILON, penalty, 0.0) if i != ORIGIN else 0.0
        total = buy * price[i] + fees
        total = total + np.where(cheaper[None, :], next_empty[None, :], next_filled[None, :])
        total[buy < -EPSILON] = np.inf  # would arrive with fuel to spare: not a real stop

        best = np.argmin(total, axis=1)
        for row, source in enumerate(sources):
            cost_to_go[i][source] = float(total[row, best[row]])
            choice[i][source] = int(ahead[best[row]])

    purchases: list[Purchase] = []
    stop, source, fuel = ORIGIN, EMPTY, 0.0
    while stop != n:
        target = choice[stop][source]
        leg = gallons_at[target] - gallons_at[stop]
        if price[target] <= price[stop]:
            buy, source = leg - fuel, EMPTY
        else:
            buy, source = tank - fuel, stop
        if stop != ORIGIN and buy > EPSILON:
            purchases.append(
                Purchase(
                    index=usable[stop - 1],
                    mile=float(miles[stop]),
                    price=float(price[stop]),
                    gallons=float(buy),
                    fuel_on_arrival=float(fuel),
                )
            )
        fuel = max(0.0, fuel + buy - leg)
        stop = target

    trip_gallons = route_miles / mpg
    return FuelPlan(
        purchases=purchases,
        trip_gallons=trip_gallons,
        starting_gallons=min(tank, trip_gallons),
    )


def _usable(candidates: Sequence[Candidate], route_miles: float) -> list[int]:
    """Indices of stations on the route, keeping only the cheapest at any one position."""
    best: dict[float, int] = {}
    for i, c in enumerate(candidates):
        if 0 <= c.mile <= route_miles:
            key = round(c.mile, 6)
            if key not in best or c.price < candidates[best[key]].price:
                best[key] = i
    return sorted(best.values(), key=lambda i: candidates[i].mile)


def _check_reachable(miles: list[float], route_miles: float, range_miles: float) -> None:
    points = [0.0, *miles, route_miles]
    for a, b in zip(points, points[1:], strict=False):
        if b - a > range_miles + EPSILON:
            raise NoFuelInRange(a, b, range_miles)
