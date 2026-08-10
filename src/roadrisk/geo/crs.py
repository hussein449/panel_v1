"""Projection between WGS84 and a local metric coordinate system.

Every length, distance and radius in this package is in **metres**, computed in a
projected CRS. Doing geometry in degrees is the classic way to get a corridor whose
segments are the wrong length by a factor that varies with latitude, and it would
poison exposure — which is the offset the whole model hangs on.

Coordinates are always named ``latitude`` / ``longitude`` in public signatures. The
(lat, lon) versus (lon, lat) confusion is a genuine source of silent, plausible-looking
errors, and positional pairs invite it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from roadrisk.geo.errors import CorridorError

WGS84_EPSG = 4326


def utm_epsg_for(latitude: float, longitude: float) -> int:
    """EPSG code of the UTM zone containing this point.

    UTM is used rather than a single global projection because it keeps distance
    distortion under about 0.1% within a zone, which is far below the error in any
    other input here.
    """
    if not -90.0 <= latitude <= 90.0:
        raise CorridorError(f"latitude {latitude} is outside [-90, 90]")
    if not -180.0 <= longitude <= 180.0:
        raise CorridorError(f"longitude {longitude} is outside [-180, 180]")

    zone = int((longitude + 180.0) / 6.0) + 1
    zone = min(zone, 60)
    return (32600 if latitude >= 0 else 32700) + zone


@dataclass(frozen=True)
class Projector:
    """Converts geometry between WGS84 and one metric CRS.

    Transformers are built once and cached — constructing them is not free, and a
    corridor projects many thousands of points.
    """

    epsg: int

    @classmethod
    def for_point(cls, latitude: float, longitude: float) -> Projector:
        return cls(epsg=utm_epsg_for(latitude, longitude))

    @cached_property
    def _to_metric(self) -> Transformer:
        return Transformer.from_crs(
            f"EPSG:{WGS84_EPSG}", f"EPSG:{self.epsg}", always_xy=True
        )

    @cached_property
    def _to_wgs84(self) -> Transformer:
        return Transformer.from_crs(
            f"EPSG:{self.epsg}", f"EPSG:{WGS84_EPSG}", always_xy=True
        )

    def point_to_metric(self, latitude: float, longitude: float) -> tuple[float, float]:
        """Project a single lat/lon to metric easting/northing."""
        return self._to_metric.transform(longitude, latitude)

    def point_to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        """Unproject metric easting/northing back to (latitude, longitude)."""
        longitude, latitude = self._to_wgs84.transform(x, y)
        return latitude, longitude

    def to_metric(self, geometry: BaseGeometry) -> BaseGeometry:
        """Project a geometry given in (longitude, latitude) order."""
        return transform(self._to_metric.transform, geometry)

    def to_wgs84(self, geometry: BaseGeometry) -> BaseGeometry:
        """Unproject a metric geometry back to (longitude, latitude) order."""
        return transform(self._to_wgs84.transform, geometry)


__all__ = ["WGS84_EPSG", "Projector", "utm_epsg_for"]
