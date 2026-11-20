"""Choose where to buy fuel, and how much, so a trip costs as little as possible.

This is the fixed-route "gas station problem". Stations sit at known distances along
the route with known prices; the tank holds ``tank_gallons``; partial fills are allowed.
The greedy rule below is optimal for that problem (Khuller, Malekian & Mestre,
"To fill or not to fill", 2007):

* At a station, look ahead as far as a full tank reaches.
* If a cheaper station is in range, buy only enough to reach the first such station.
* Otherwise fill the tank here and drive to the cheapest station in range.

The destination is treated as a free station, so the truck arrives with an empty
tank and never buys fuel it does not use.

Assumption: the truck leaves the origin with an empty tank, so every gallon of the
trip is paid for. The fuel needed to reach the first station on the route is bought
at that station (it is usually a few miles from the origin).
"""

from collections.abc import Sequence
from dataclasses import dataclass

EPSILON = 1e-9


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
) -> FuelPlan:
    """Return the cheapest set of purchases for a trip of ``route_miles``.

    ``candidates`` must be sorted by ``mile``; ``Purchase.index`` refers back to it.
    """
    range_miles = tank_gallons * mpg
    usable = [i for i, c in enumerate(candidates) if 0 <= c.mile <= route_miles]
    if not usable:
        raise NoFuelInRange(0.0, route_miles, range_miles)

    # Stops are positions in ``usable``; ``destination`` stands for the end of the route.
    miles = [candidates[i].mile for i in usable] + [route_miles]
    prices = [candidates[i].price for i in usable] + [0.0]
    destination = len(usable)

    if miles[0] > range_miles + EPSILON:
        raise NoFuelInRange(0.0, miles[0], range_miles)

    purchases: list[Purchase] = []
    origin_leg = miles[0] / mpg  # bought at the first station, see the module docstring
    stop, fuel = 0, 0.0
    while stop != destination:
        reach = miles[stop] + range_miles
        in_range = [k for k in range(stop + 1, destination + 1) if miles[k] <= reach + EPSILON]
        if not in_range:
            raise NoFuelInRange(miles[stop], miles[stop + 1], range_miles)

        cheaper = next((k for k in in_range if prices[k] < prices[stop]), None)
        if cheaper is not None:
            target = cheaper
            buy = max(0.0, (miles[target] - miles[stop]) / mpg - fuel)
        else:
            # Nothing cheaper ahead: fill up, then go to the cheapest station in range
            # (the farthest one on a tie, which means fewer stops).
            target = min(in_range, key=lambda k: (prices[k], -miles[k]))
            buy = tank_gallons - fuel

        gallons = buy + (origin_leg if stop == 0 else 0.0)
        if gallons > EPSILON:
            purchases.append(
                Purchase(
                    index=usable[stop],
                    mile=miles[stop],
                    price=prices[stop],
                    gallons=gallons,
                    fuel_on_arrival=fuel,
                )
            )
        fuel = max(0.0, fuel + buy - (miles[target] - miles[stop]) / mpg)
        stop = target
    return FuelPlan(purchases)
