"""An in-memory copy of all stations as NumPy arrays, built once per process.

There are ~6,600 stations, so holding them in memory is cheap (well under 1 MB) and
lets a route request find nearby stations with vectorised maths instead of a query
per route segment.
"""

from dataclasses import dataclass
from threading import Lock

import numpy as np


@dataclass(frozen=True)
class StationIndex:
    ids: np.ndarray  # database primary keys
    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray  # USD per gallon, float64

    def __len__(self) -> int:
        return len(self.ids)


_index: StationIndex | None = None
_lock = Lock()


def get_station_index() -> StationIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _build()
    return _index


def reset_station_index() -> None:
    global _index
    _index = None


def _build() -> StationIndex:
    from stations.models import FuelStation

    rows = list(FuelStation.objects.values_list("id", "latitude", "longitude", "price"))
    if not rows:
        empty = np.empty(0)
        return StationIndex(empty.astype(np.int64), empty, empty, empty)
    ids, lat, lon, price = zip(*rows, strict=True)
    return StationIndex(
        ids=np.asarray(ids, dtype=np.int64),
        lat=np.asarray(lat, dtype=np.float64),
        lon=np.asarray(lon, dtype=np.float64),
        price=np.asarray([float(p) for p in price], dtype=np.float64),
    )
