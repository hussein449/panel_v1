"""Walking a corridor at fixed spacing, in the coordinates a raster wants.

The OSM adapters sample the centreline in metres because they compare against metric
geometry. The raster adapters need the same stations in degrees, because a global
GeoTIFF is indexed in EPSG:4326 — and the land-cover adapter needs them *beside* the
road rather than on it. Both live here so the two adapters agree on what a station is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from roadrisk.geo.segmentation import Segmentation

#: Half-length of the chord used to estimate the corridor's bearing at a station.
#: Short enough to follow a bend, long enough not to be dominated by one vertex.
TANGENT_HALF_M = 5.0


@dataclass(frozen=True)
class Stations:
    """Evenly spaced points along a corridor, each tied to the unit it falls in."""

    chainages: np.ndarray
    unit_index: np.ndarray
    n_units: int
    interval_m: float

    def __len__(self) -> int:
        return int(len(self.chainages))

    def counts(self) -> np.ndarray:
        """Stations per unit."""
        return np.bincount(self.unit_index, minlength=self.n_units).astype(float)


def stations_along(
    segmentation: Segmentation,
    interval_m: float,
) -> Stations:
    """Chainages at fixed spacing from 0 to the corridor end, inclusive of both.

    Both ends are included because a gradient needs elevation on either side of the
    stations it describes, and dropping the last one would leave the final unit short
    exactly where a corridor most often runs into terrain.
    """
    total = segmentation.corridor.length_m
    count = max(int(math.floor(total / interval_m)) + 1, 2)
    chainages = np.linspace(0.0, total, count)

    edges = np.array(
        [unit.start_m for unit in segmentation] + [segmentation.units[-1].end_m]
    )
    unit_index = np.clip(
        np.searchsorted(edges, chainages, side="right") - 1, 0, len(segmentation) - 1
    )

    return Stations(
        chainages=chainages,
        unit_index=unit_index,
        n_units=len(segmentation),
        interval_m=float(total / (count - 1)) if count > 1 else total,
    )


def to_latlon(
    segmentation: Segmentation,
    chainages: np.ndarray,
    *,
    offset_m: float = 0.0,
) -> list[tuple[float, float]]:
    """Station positions as (latitude, longitude), optionally offset sideways.

    A positive ``offset_m`` moves left of the direction of travel and a negative one
    right. Which side is which does not matter to any caller here — both sides are
    always sampled — but the sign has to be consistent or the two offsets would land on
    top of each other.
    """
    corridor = segmentation.corridor
    line = corridor.geometry
    total = line.length
    points: list[tuple[float, float]] = []

    for chainage in chainages:
        position = line.interpolate(float(chainage))
        x, y = position.x, position.y

        if offset_m:
            normal_x, normal_y = _normal(line, float(chainage), total)
            x += normal_x * offset_m
            y += normal_y * offset_m

        points.append(corridor.projector.point_to_wgs84(x, y))

    return points


def _normal(line, chainage: float, total: float) -> tuple[float, float]:
    """Unit vector perpendicular to the corridor at this chainage."""
    back = line.interpolate(max(chainage - TANGENT_HALF_M, 0.0))
    forward = line.interpolate(min(chainage + TANGENT_HALF_M, total))

    dx, dy = forward.x - back.x, forward.y - back.y
    length = math.hypot(dx, dy)
    if length == 0.0:  # pragma: no cover - duplicate vertices are removed upstream
        return (0.0, 0.0)
    return (-dy / length, dx / length)


__all__ = ["TANGENT_HALF_M", "Stations", "stations_along", "to_latlon"]
