"""One Overpass fetch, everything OSM knows about the corridor's surroundings.

Every Tier A factor that comes out of OpenStreetMap — the road's own tags, junctions,
accesses, ramps, roadside POIs — is served from a single request. Fanning out one query
per factor would multiply the load on a volunteer-run service by six for data that
arrives in the same response.

**The query is bounded by the corridor, not by a bounding box.** Overpass ``around``
takes a polyline, so a 25 km road asks for a 100 m ribbon rather than the 25 x 15 km box
that encloses it. On a corridor through a city the difference between those two is the
difference between a few thousand elements and a few hundred thousand.

**Node identity comes from coordinates, not from node ids.** Junction detection needs to
know when two ways meet, which is a question about shared nodes. Reading the ``nodes``
array would work, but keying on the projected vertex position to a tenth of a metre is
equivalent — ways that share a node share its coordinates exactly — and it does not
depend on an Overpass output field that a caller's client, or a cache, might drop. It
also makes a test fixture a list of coordinates rather than a bookkeeping exercise in
node ids.

**The network is injectable**, exactly as in :mod:`roadrisk.geo.osm`: the client is a
protocol, and every test supplies a fake.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point

from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError
from roadrisk.geo.osm import HttpOverpassClient, OverpassClient

#: How far from the centreline a way must come to be fetched. Wide enough to catch a
#: side road, a driveway or a slip road as it approaches; narrow enough that a parallel
#: street two blocks away never enters the extract.
DEFAULT_ROAD_RADIUS_M = 100.0

#: The same for roadside points of interest. Larger than the road radius would start
#: counting the activity of the next street over as this road's roadside activity.
DEFAULT_POI_RADIUS_M = 60.0

#: The centreline is simplified before it goes into the query, because a 700-vertex
#: polyline repeated across clauses makes a query tens of kilobytes long for no gain.
#: Well below the road radius, so simplification cannot move the ribbon off the road.
QUERY_SIMPLIFY_TOLERANCE_M = 20.0

#: Hard ceiling on polyline vertices in the query. Reached only by a very long or very
#: windy corridor; the tolerance is relaxed until the count fits, and the relaxation is
#: reported rather than applied silently.
MAX_QUERY_VERTICES = 600

#: Highway classes that carry through traffic. These are what the corridor is made of,
#: and what forms a junction with it.
JUNCTION_CLASSES = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "living_street",
        "road",
    }
)

#: Slip roads. Deliberately excluded from the junction classes: a ramp joining a
#: motorway would otherwise be counted once as a junction and again as a ramp, and the
#: two columns would be collinear by construction rather than by accident.
LINK_CLASSES = frozenset(
    f"{name}_link"
    for name in ("motorway", "trunk", "primary", "secondary", "tertiary")
)

#: Driveways, service roads, farm and forestry tracks — the access points a survey
#: vehicle would count. Also excluded from the junction classes, for the same reason.
ACCESS_CLASSES = frozenset({"service", "track"})

#: Classes a corridor itself can be made of, used to decide which way carries a given
#: point of the centreline.
CARRIER_CLASSES = JUNCTION_CLASSES | LINK_CLASSES

#: Tag keys that mark a node as roadside activity.
POI_KEYS: tuple[str, ...] = ("amenity", "shop", "tourism", "office", "leisure")

#: Precision at which two vertices are the same node, in metres. OSM stores coordinates
#: at seven decimal places (about 1 cm), so a tenth of a metre is loose enough to
#: survive the projection round trip and tight enough never to merge distinct nodes.
NODE_PRECISION_M = 0.1


@dataclass(frozen=True)
class OsmWay:
    """One OSM way, projected into the corridor's metric CRS."""

    osm_id: int
    tags: Mapping[str, str]
    geometry: LineString

    @property
    def highway(self) -> str:
        return str(self.tags.get("highway", ""))

    @property
    def refs(self) -> frozenset[str]:
        """Every reference this way carries. OSM separates multiples with ';'."""
        raw = self.tags.get("ref", "")
        return frozenset(part.strip() for part in str(raw).split(";") if part.strip())

    @property
    def is_carrier(self) -> bool:
        return self.highway in CARRIER_CLASSES

    @property
    def is_link(self) -> bool:
        return self.highway in LINK_CLASSES

    @property
    def is_access(self) -> bool:
        return self.highway in ACCESS_CLASSES

    @property
    def is_building(self) -> bool:
        """A mapped building outline. ``building=no`` exists and means what it says."""
        value = str(self.tags.get("building", "")).strip().lower()
        return bool(value) and value != "no"

    @property
    def counts_towards_degree(self) -> bool:
        return self.highway in JUNCTION_CLASSES


@dataclass(frozen=True)
class OsmNode:
    """One tagged OSM node, projected into the corridor's metric CRS."""

    osm_id: int
    tags: Mapping[str, str]
    point: Point

    @property
    def is_poi(self) -> bool:
        return any(key in self.tags for key in POI_KEYS)


@dataclass(frozen=True)
class OsmExtract:
    """Everything one Overpass call returned, parsed and projected."""

    ways: tuple[OsmWay, ...]
    nodes: tuple[OsmNode, ...]
    road_radius_m: float
    poi_radius_m: float
    query_vertices: int
    ref: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.ways and not self.nodes

    @property
    def carriers(self) -> tuple[OsmWay, ...]:
        return tuple(way for way in self.ways if way.is_carrier)

    @property
    def poi_nodes(self) -> tuple[OsmNode, ...]:
        return tuple(node for node in self.nodes if node.is_poi)

    @property
    def buildings(self) -> tuple[OsmWay, ...]:
        return tuple(way for way in self.ways if way.is_building)

    def junction_points(self) -> list[Point]:
        """Vertices where three or more road edges meet.

        Graph degree, counted honestly: a vertex interior to a way contributes two
        incident edges, an endpoint contributes one. Two ways of the same road split at
        a vertex therefore give degree two and are not a junction, while a side road
        ending on that road gives three and is.
        """
        incident: dict[tuple[int, int], int] = {}
        position: dict[tuple[int, int], tuple[float, float]] = {}

        for way in self.ways:
            if not way.counts_towards_degree:
                continue
            coords = list(way.geometry.coords)
            for index, (x, y) in enumerate(coords):
                key = _node_key(x, y)
                interior = 0 < index < len(coords) - 1
                incident[key] = incident.get(key, 0) + (2 if interior else 1)
                position.setdefault(key, (x, y))

        return [Point(position[key]) for key, degree in incident.items() if degree >= 3]

    @property
    def road_ways(self) -> tuple[OsmWay, ...]:
        return tuple(way for way in self.ways if way.highway)

    def summary(self) -> str:
        return (
            f"{len(self.road_ways):,} road way(s) within {self.road_radius_m:.0f} m, "
            f"{len(self.buildings):,} building(s) and {len(self.poi_nodes):,} POI "
            f"node(s) within {self.poi_radius_m:.0f} m of the centreline"
        )


def build_extract_query(
    coordinates: Sequence[tuple[float, float]],
    *,
    road_radius_m: float = DEFAULT_ROAD_RADIUS_M,
    poi_radius_m: float = DEFAULT_POI_RADIUS_M,
    timeout_s: int = 180,
) -> str:
    """Overpass QL for every road and roadside POI along a polyline.

    Args:
        coordinates: Ordered (latitude, longitude) vertices of the simplified corridor.
        road_radius_m: Ribbon width for highway ways.
        poi_radius_m: Ribbon width for POI nodes.
        timeout_s: Server-side timeout. Generous — this query is larger than the
            corridor fetch and mirrors are slow under load.
    """
    if len(coordinates) < 2:
        raise CorridorError(
            "an Overpass 'around' filter needs at least two coordinates to describe a "
            f"corridor, got {len(coordinates)}"
        )

    polyline = ",".join(f"{lat:.6f},{lon:.6f}" for lat, lon in coordinates)
    poi_filter = "|".join(POI_KEYS)

    return (
        f"[out:json][timeout:{timeout_s}];"
        "("
        f'way["highway"](around:{road_radius_m:.0f},{polyline});'
        f'way["building"](around:{poi_radius_m:.0f},{polyline});'
        f'node[~"^({poi_filter})$"~"."](around:{poi_radius_m:.0f},{polyline});'
        ");"
        "out geom;"
    )


def fetch_extract(
    corridor: Corridor,
    *,
    client: OverpassClient | None = None,
    ref: str | None = None,
    road_radius_m: float = DEFAULT_ROAD_RADIUS_M,
    poi_radius_m: float = DEFAULT_POI_RADIUS_M,
    simplify_tolerance_m: float = QUERY_SIMPLIFY_TOLERANCE_M,
    max_query_vertices: int = MAX_QUERY_VERTICES,
) -> OsmExtract:
    """Fetch and parse everything OSM has along a corridor.

    Args:
        corridor: The linearly-referenced centreline. Supplies the projection, so every
            geometry in the result is already metric and directly comparable to it.
        client: Overpass client. Defaults to the HTTP one; inject a fake to avoid the
            network.
        ref: Road reference, when known. Used later to break ties between candidate
            carrier ways, never to filter the fetch.
        road_radius_m, poi_radius_m: Ribbon widths.
        simplify_tolerance_m: Starting tolerance for simplifying the query polyline.
        max_query_vertices: Ceiling on polyline vertices in the query.

    Raises:
        CorridorError: Every Overpass mirror failed, or the response is not parseable.
    """
    active = client if client is not None else HttpOverpassClient()
    coordinates, vertices, relaxed = _query_polyline(
        corridor, simplify_tolerance_m, max_query_vertices
    )

    payload = active(
        build_extract_query(
            coordinates, road_radius_m=road_radius_m, poi_radius_m=poi_radius_m
        )
    )
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        raise CorridorError(
            "Overpass returned a payload with no element list. The mirror may have "
            "answered with an error page rather than JSON."
        )

    ways = tuple(
        way
        for way in (_parse_way(element, corridor) for element in elements)
        if way is not None
    )
    nodes = tuple(
        node
        for node in (_parse_node(element, corridor) for element in elements)
        if node is not None
    )

    warnings: list[str] = []
    if relaxed is not None:
        warnings.append(
            f"The query polyline was simplified at {relaxed:.0f} m rather than "
            f"{simplify_tolerance_m:.0f} m to stay under {max_query_vertices:,} "
            "vertices. The search ribbon is correspondingly looser on the bends; raise "
            "road_radius_m if the corridor is very windy."
        )
    if not any(way.highway for way in ways):
        warnings.append(
            f"OSM returned no highway ways within {road_radius_m:.0f} m of this "
            "centreline. Either the area is unmapped, or the centreline does not lie "
            "on the road it claims to — check it against a basemap before trusting "
            "anything derived from it."
        )

    return OsmExtract(
        ways=ways,
        nodes=nodes,
        road_radius_m=road_radius_m,
        poi_radius_m=poi_radius_m,
        query_vertices=vertices,
        ref=ref,
        warnings=warnings,
    )


# ---- internals ---------------------------------------------------------------


def _node_key(x: float, y: float) -> tuple[int, int]:
    return (round(x / NODE_PRECISION_M), round(y / NODE_PRECISION_M))


def _query_polyline(
    corridor: Corridor,
    tolerance_m: float,
    max_vertices: int,
) -> tuple[list[tuple[float, float]], int, float | None]:
    """Simplify the centreline enough to put it in a query, and say if that hurt."""
    tolerance = tolerance_m
    relaxed: float | None = None

    simplified = corridor.geometry.simplify(tolerance)
    while len(simplified.coords) > max_vertices and tolerance < 1000.0:
        tolerance *= 2.0
        relaxed = tolerance
        simplified = corridor.geometry.simplify(tolerance)

    coordinates = [
        corridor.projector.point_to_wgs84(x, y) for x, y in simplified.coords
    ]
    return coordinates, len(coordinates), relaxed


def _tags(element: Mapping[str, Any]) -> dict[str, str]:
    raw = element.get("tags") or {}
    return {str(key): str(value) for key, value in raw.items()}


def _parse_way(element: Mapping[str, Any], corridor: Corridor) -> OsmWay | None:
    if element.get("type") != "way":
        return None

    geometry = element.get("geometry") or []
    if len(geometry) < 2:
        # A way clipped to a single vertex carries no length and no direction; it
        # cannot carry a sample or contribute a junction edge.
        return None

    projected = [
        corridor.projector.point_to_metric(node["lat"], node["lon"])
        for node in geometry
    ]
    return OsmWay(
        osm_id=int(element.get("id", 0)),
        tags=_tags(element),
        geometry=LineString(projected),
    )


def _parse_node(element: Mapping[str, Any], corridor: Corridor) -> OsmNode | None:
    if element.get("type") != "node":
        return None
    if "lat" not in element or "lon" not in element:
        return None

    x, y = corridor.projector.point_to_metric(element["lat"], element["lon"])
    return OsmNode(
        osm_id=int(element.get("id", 0)),
        tags=_tags(element),
        point=Point(x, y),
    )


__all__ = [
    "ACCESS_CLASSES",
    "CARRIER_CLASSES",
    "DEFAULT_POI_RADIUS_M",
    "DEFAULT_ROAD_RADIUS_M",
    "JUNCTION_CLASSES",
    "LINK_CLASSES",
    "MAX_QUERY_VERTICES",
    "POI_KEYS",
    "QUERY_SIMPLIFY_TOLERANCE_M",
    "OsmExtract",
    "OsmNode",
    "OsmWay",
    "build_extract_query",
    "fetch_extract",
]
