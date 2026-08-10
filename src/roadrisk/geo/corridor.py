"""Step 1 of the pipeline — resolve the corridor and give it a linear reference.

A corridor is one continuous centreline plus chainage: every point on it has a single
distance-from-start in metres. That linear reference is what makes everything after it
possible — segmentation cuts on chainage, crashes snap to chainage, and factor values
attach to chainage ranges.

**Routing is not implemented yet.** This class takes a centreline that has already been
resolved. The OSM step that turns two coordinates into a centreline constrained to a
named road is Step 2.2b and is not built.

Until it is, the recommended source is an **export of the real road from OSM**, not a
hand-drawn line — see :data:`CENTRELINE_GUIDANCE`, which the CLI prints and which is
attached to the under-sampled-centreline warning. What *is* built here are the
structural gates: a corridor that cannot be linearly referenced is rejected rather than
producing a panel whose numbers are all wrong but plausible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

from shapely.geometry import LineString, Point
from shapely.ops import substring

from roadrisk.geo.crs import Projector
from roadrisk.geo.errors import CorridorError

#: Consecutive points closer than this are treated as duplicates. Below a metre is
#: noise in any GPS trace, and a zero-length span breaks linear referencing.
MIN_VERTEX_SPACING_M = 1.0

#: A corridor shorter than this cannot support meaningful segmentation.
MIN_CORRIDOR_LENGTH_M = 100.0

#: How to obtain a centreline good enough to measure curvature from.
#:
#: Surfaced by the CLI and attached to the under-sampled-centreline warning, because
#: that warning is exactly the moment somebody needs to know this. Exporting the road
#: from OSM beats hand-drawing it: mappers already placed vertices densely through the
#: bends, which is the only place curvature detail matters.
CENTRELINE_GUIDANCE = """\
Best source: export the real road from OpenStreetMap rather than drawing it.

  1. Open https://overpass-turbo.eu and zoom to the corridor.
  2. Run, with your road's ref in place of M51:

       [out:json];
       way["ref"="M51"]({{bbox}});
       (._;>;);
       out geom;

  3. Export -> GeoJSON.
  4. In QGIS: Vector > Geometry Tools > Merge Lines, to join the pieces OSM
     returns into one line. Then export the vertices as CSV with `latitude`
     and `longitude` columns.

Why: OSM's own vertices are already dense through bends, which is where curvature
detail matters. A hand-drawn line usually is not.

If you must draw it by hand:
  - Dense on the bends; sparse on the straights is fine, they cap anyway.
  - Never cut a corner - two clicks across a curve become a fake sharp bend.
  - Pick ONE carriageway on a divided road; do not zigzag between them.
  - Do not double back on yourself.\
"""


@dataclass(frozen=True)
class Corridor:
    """A linearly-referenced centreline in a metric CRS."""

    name: str
    geometry: LineString
    projector: Projector
    self_intersecting: bool = False

    @classmethod
    def from_latlon(
        cls,
        points: Sequence[tuple[float, float]],
        *,
        name: str = "corridor",
    ) -> Corridor:
        """Build a corridor from ordered (latitude, longitude) pairs.

        Args:
            points: Ordered centreline vertices as (latitude, longitude).
            name: Corridor identifier, used to prefix unit ids.

        Raises:
            CorridorError: Fewer than two distinct points, or the resulting line is
                too short to segment.
        """
        if len(points) < 2:
            raise CorridorError(
                f"corridor '{name}' needs at least 2 points, got {len(points)}"
            )

        projector = Projector.for_point(*points[0])
        projected = [projector.point_to_metric(lat, lon) for lat, lon in points]
        cleaned = _drop_duplicate_vertices(projected, name)

        line = LineString(cleaned)
        if line.length < MIN_CORRIDOR_LENGTH_M:
            raise CorridorError(
                f"corridor '{name}' is {line.length:.1f} m long, below the "
                f"{MIN_CORRIDOR_LENGTH_M:.0f} m minimum. A corridor this short cannot "
                "be segmented into units that carry meaningful exposure."
            )

        return cls(
            name=name,
            geometry=line,
            projector=projector,
            self_intersecting=not line.is_simple,
        )

    # ---- linear reference ---------------------------------------------------

    @property
    def length_m(self) -> float:
        return float(self.geometry.length)

    @property
    def length_km(self) -> float:
        return self.length_m / 1000.0

    @property
    def epsg(self) -> int:
        return self.projector.epsg

    def chainage_of(self, x: float, y: float) -> float:
        """Distance from the corridor start to the nearest point on it, in metres."""
        return float(self.geometry.project(Point(x, y)))

    def point_at(self, chainage_m: float) -> Point:
        """The point at a given chainage."""
        if not 0.0 <= chainage_m <= self.length_m:
            raise CorridorError(
                f"chainage {chainage_m:.1f} m is outside corridor '{self.name}' "
                f"(0 to {self.length_m:.1f} m)"
            )
        return self.geometry.interpolate(chainage_m)

    def between(self, start_m: float, end_m: float) -> LineString:
        """The sub-line between two chainages."""
        if end_m <= start_m:
            raise CorridorError(
                f"end chainage {end_m:.1f} must exceed start {start_m:.1f}"
            )
        return substring(self.geometry, start_m, end_m)

    def distance_to(self, x: float, y: float) -> float:
        """Perpendicular distance from a metric point to the centreline."""
        return float(self.geometry.distance(Point(x, y)))

    @cached_property
    def wgs84(self) -> LineString:
        """The centreline back in (longitude, latitude) order, for mapping."""
        return self.projector.to_wgs84(self.geometry)

    @property
    def warnings(self) -> list[str]:
        """Structural concerns that do not justify rejection but must be reported."""
        issues: list[str] = []
        if self.self_intersecting:
            issues.append(
                "Centreline crosses itself. Linear referencing is ambiguous near the "
                "crossing: a crash there can snap to either branch, and the chainage "
                "it receives is whichever branch happens to be marginally closer. "
                "Split the corridor at the crossing, or accept that units near it are "
                "unreliable."
            )
        return issues


def _drop_duplicate_vertices(
    points: Sequence[tuple[float, float]],
    name: str,
) -> list[tuple[float, float]]:
    """Remove consecutive near-identical vertices, which break linear referencing."""
    cleaned: list[tuple[float, float]] = [points[0]]
    for point in points[1:]:
        previous = cleaned[-1]
        spacing = ((point[0] - previous[0]) ** 2 + (point[1] - previous[1]) ** 2) ** 0.5
        if spacing >= MIN_VERTEX_SPACING_M:
            cleaned.append(point)

    if len(cleaned) < 2:
        raise CorridorError(
            f"corridor '{name}' collapses to a single point once duplicate vertices "
            f"are removed — all {len(points)} supplied points are within "
            f"{MIN_VERTEX_SPACING_M} m of each other."
        )
    return cleaned


__all__ = [
    "CENTRELINE_GUIDANCE",
    "MIN_CORRIDOR_LENGTH_M",
    "MIN_VERTEX_SPACING_M",
    "Corridor",
]
