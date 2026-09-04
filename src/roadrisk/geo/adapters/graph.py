"""Tier B adapter — a traffic proxy from the shape of the road network.

No open global source of traffic volume exists. What does exist is the network itself,
and the observation that a road carrying shortest paths between many pairs of places
tends to carry traffic. Betweenness centrality measures exactly that, and it is free.

**It is a proxy and it is never AADT.** The registry says so in capitals, the column is
called ``traffic_proxy``, and the reason is not pedantry: the HSM's AADT exponent is
estimated on measured volumes and does not transfer to a unitless centrality score. A
number labelled ``aadt`` would be multiplied by a coefficient that means something else.

**The window is the trap this module exists to survive.** Betweenness is computed over
the graph you supply, so a graph shaped like a ribbon around the corridor produces a
parabola peaking in the middle of the ribbon — an artefact of the query, indistinguishable
at a glance from a town on the corridor. Two defences:

*Fetch a region, not a ribbon.* The network comes from a bounding box with a wide margin
rather than the corridor-following ``around`` filter the other OSM adapters use, because
through traffic routes through an area and a ribbon graph has nowhere else to go.

*Then test for the artefact anyway.* The finished proxy is correlated against a symmetric
parabola centred on the corridor. A real town peaks wherever the town is; the artefact
peaks dead centre by construction. Above :data:`ARTEFACT_WARN` the run says so, above
:data:`ARTEFACT_REFUSE` the factor is withheld — a column that is mostly a picture of the
box we asked for is worse than no column.

**Only the corridor is reported, though a whole region is computed.** Nodes near the edge
of any window have artificially low betweenness, because the paths that would have run
through them from outside were never in the graph. Reporting only the middle of a wide
window is the standard mitigation and the reason the margin is wide by default.

Measured on Cyprus B9:

===========  ============  =====================  ==================
Margin       Junctions     Artefact correlation   Peak unit (of 49)
===========  ============  =====================  ==================
5 km         114           0.38                   1
10 km        277           0.69                   26
20 km        592           0.41                   19
===========  ============  =====================  ==================

**Read that honestly: the along-corridor pattern is not stable under a change of
window.** It is not that the artefact decays with width — it does not, on this road —
but that an arbitrary analysis choice moves both the shape and where it peaks. Which is
the most useful thing this adapter can tell you about its own output, and the reason
the registry keeps ``traffic_proxy`` uncited and these notes as loud as they are.

The margin nevertheless defaults to the widest of the three, on the methodological
ground rather than the correlation: a wider window cuts off fewer of the through-routes
that betweenness is trying to count, and the corridor sits further from the edge where
the distortion is worst. It is the least-bad window, not a good one.
"""

from __future__ import annotations

import heapq
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import (
    AdapterResult,
    SkippedFactor,
    require_slots,
    resolve,
)
from roadrisk.geo.adapters.osm_tags import maxspeed_kmh
from roadrisk.geo.adapters.osmdata import NODE_PRECISION_M
from roadrisk.geo.cache import quantise_bbox
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError
from roadrisk.geo.osm import HttpOverpassClient, OverpassClient
from roadrisk.geo.segmentation import Segmentation

FACTOR = "traffic_proxy"
ADAPTER = "osm_graph_centrality"
SLOTS: tuple[tuple[str, str], ...] = ((FACTOR, ADAPTER),)

#: Classes that carry through traffic. Residential streets are excluded deliberately:
#: they multiply the node count several-fold and they are not where strategic paths go,
#: so including them costs a great deal of compute to add noise.
STRATEGIC_CLASSES: tuple[str, ...] = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
)

#: Margin around the corridor's bounding box. The widest window that is still a region
#: rather than a country: it cuts off fewer of the through-routes betweenness is trying
#: to count, and it keeps the corridor well away from the edge where the distortion is
#: worst. See the module docstring for what three margins actually produced on Cyprus
#: B9 — the answer is not flattering, and it is why the artefact gate exists.
DEFAULT_NETWORK_MARGIN_M = 20_000.0

#: Grid the network box is snapped to before it is requested.
#:
#: Half a degree is roughly 55 km, chosen so two corridors anywhere in the same county
#: round to one box. A finer grid does not share: measured on Cyprus, B9 and E601 are a
#: few kilometres apart, and with a 20 km margin their padded boxes still differed by
#: more than a tenth of a degree — at 0.1 the second corridor missed the cache entirely.
#:
#: The cost is a larger fetch on a cold cache. That is the trade this step exists to
#: make: the brief's rule is "a second corridor in the same country is nearly free",
#: which is a claim about the second corridor, not the first.
NETWORK_GRID_DEG = 0.5

#: Free-flow speeds in km/h by highway class, used to weight the graph where OSM does
#: not state a limit. Shortest paths on travel time route the way drivers do; shortest
#: paths on distance send everyone down the lanes.
CLASS_SPEED_KMH: dict[str, float] = {
    "motorway": 110.0,
    "trunk": 90.0,
    "primary": 80.0,
    "secondary": 70.0,
    "tertiary": 60.0,
    "motorway_link": 60.0,
    "trunk_link": 55.0,
    "primary_link": 50.0,
    "secondary_link": 45.0,
    "tertiary_link": 40.0,
}
DEFAULT_SPEED_KMH = 50.0

#: Source nodes sampled for the approximate betweenness. Every source is a full
#: Dijkstra, so this is the run's cost dial. A proxy does not deserve exact
#: betweenness — that would be false precision on a quantity with no units.
DEFAULT_SOURCE_SAMPLE = 128

#: Fixed so two identical runs fingerprint identically. The manifest depends on it.
SOURCE_SEED = 20260810

#: Refuse to build a graph larger than this, counted in **contracted junctions** — the
#: quantity a Dijkstra actually costs. Reaching it means the margin is too wide for the
#: area, not that the corridor is unusual.
#:
#: **This used to be checked against raw OSM vertices, which is ten to twenty times
#: larger and is not what betweenness runs on.** Measured on the A3 through Paris at
#: the default window: 674,358 vertices, 37,935 contracted nodes, betweenness in 25
#: seconds. The guard refused a graph comfortably inside its own budget, and it refused
#: it hardest in exactly the places a traffic proxy is most worth having — dense urban
#: networks, where the whole question is which road carries the through traffic.
MAX_GRAPH_NODES = 60_000

#: Ceiling on raw OSM vertices, which bounds the contraction itself rather than the
#: Dijkstras that follow it. Contraction is linear and cheap; this exists so that a
#: pathological box cannot exhaust memory before :data:`MAX_GRAPH_NODES` is even
#: measurable. Paris at the widest window uses about a tenth of it.
MAX_GRAPH_VERTICES = 6_000_000

#: Correlation with a symmetric parabola centred on the corridor above which the proxy
#: is reported as suspect, and above which it is withheld entirely.
ARTEFACT_WARN = 0.7
ARTEFACT_REFUSE = 0.9

#: How far a corridor sample may sit from a graph edge and still be carried by it.
EDGE_TOLERANCE_M = 30.0

#: Spacing at which each unit is sampled onto the graph.
SAMPLE_INTERVAL_M = 25.0

_EPS = 1e-9


@dataclass(frozen=True)
class GraphEdge:
    """One run of road between two junctions."""

    u: int
    v: int
    seconds: float
    geometry: LineString


@dataclass(frozen=True)
class RoadGraph:
    """A routable graph contracted to its junctions."""

    points: list[tuple[float, float]]
    edges: list[GraphEdge]
    adjacency: list[list[tuple[int, int]]]
    n_ways: int
    margin_m: float
    warnings: list[str] = field(default_factory=list)

    @property
    def n_nodes(self) -> int:
        return len(self.points)

    @property
    def n_edges(self) -> int:
        return len(self.edges)

    def summary(self) -> str:
        return (
            f"{self.n_ways:,} strategic way(s) contracted to {self.n_nodes:,} junctions "
            f"and {self.n_edges:,} links"
        )


def build_network_query(
    corridor: Corridor,
    *,
    margin_m: float = DEFAULT_NETWORK_MARGIN_M,
    grid_deg: float = NETWORK_GRID_DEG,
    timeout_s: int = 180,
) -> str:
    """Overpass QL for the strategic network in a grid-aligned box around the corridor.

    A box, not the ``around`` ribbon the other OSM adapters use. Through traffic routes
    through an *area*; a ribbon-shaped graph has nowhere else to go and manufactures the
    very centrality peak this adapter has to be trusted not to invent.

    **Snapped to a grid, which is what makes it cacheable across corridors.** Two roads
    through the same county have different bounding boxes and would otherwise ask two
    different questions; rounded out to a half-degree cell they ask one, and the second
    corridor never leaves the disk. The snapping lives here rather than in the cache so
    that a run with a cache and a run without fetch exactly the same region — a cache
    that changes the answer is not a cache.

    The rounding only ever grows the box, and for this measure a wider region is mildly
    *better*: it cuts off fewer of the through-routes betweenness is trying to count.
    """
    south, west, north, east = _padded_box(corridor, margin_m)
    west, south, east, north = quantise_bbox((west, south, east, north), grid_deg)
    classes = "|".join(STRATEGIC_CLASSES)
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["highway"~"^({classes})(_link)?$"]'
        f"({south:.5f},{west:.5f},{north:.5f},{east:.5f});"
        "out geom;"
    )


def fetch_network(
    corridor: Corridor,
    *,
    client: OverpassClient | None = None,
    margin_m: float = DEFAULT_NETWORK_MARGIN_M,
    grid_deg: float = NETWORK_GRID_DEG,
    max_nodes: int = MAX_GRAPH_NODES,
    max_vertices: int = MAX_GRAPH_VERTICES,
) -> RoadGraph:
    """Fetch the surrounding strategic network and contract it to a routable graph.

    Raises:
        CorridorError: Overpass failed, the region holds more than ``max_vertices`` raw
            vertices to contract, or it contracts to more than ``max_nodes`` junctions.
    """
    active = client if client is not None else HttpOverpassClient(timeout_s=180.0)
    payload = active(
        build_network_query(corridor, margin_m=margin_m, grid_deg=grid_deg)
    )

    elements = payload.get("elements", [])
    # Sorted by OSM id so node numbering — and therefore the sampled sources — does not
    # depend on the order a mirror happened to return the ways in. The run manifest
    # fingerprints the result, so this is correctness, not tidiness.
    ways = sorted(
        (e for e in elements if e.get("type") == "way" and len(e.get("geometry", [])) >= 2),
        key=lambda way: int(way.get("id", 0)),
    )
    return _contract(ways, corridor, margin_m, max_nodes, max_vertices)


def edge_betweenness(
    graph: RoadGraph,
    *,
    n_sources: int = DEFAULT_SOURCE_SAMPLE,
    seed: int = SOURCE_SEED,
) -> np.ndarray:
    """Approximate edge betweenness: the share of shortest paths using each link.

    Brandes' algorithm over a sample of source nodes, scaled to the whole graph. The
    result is the estimated fraction of all node pairs whose fastest route runs along
    that link, which is unitless, bounded by one, and comparable between corridors
    computed with the same margin.
    """
    n = graph.n_nodes
    if n < 3 or not graph.edges:
        return np.zeros(graph.n_edges, dtype=float)

    sources = _sample_sources(n, n_sources, seed)
    totals = np.zeros(graph.n_edges, dtype=float)

    for source in sources:
        _accumulate(graph, source, totals)

    # Each pair is reached once from each end when every node is a source, so the sum
    # double counts; the sample estimator scales by n/k; and dividing by the number of
    # pairs turns a count into a share.
    pairs = n * (n - 1) / 2.0
    scale = (n / len(sources)) / 2.0 / pairs
    return totals * scale


def compute_traffic_proxy(
    segmentation: Segmentation,
    graph: RoadGraph,
    *,
    registry: Registry,
    n_sources: int = DEFAULT_SOURCE_SAMPLE,
    seed: int = SOURCE_SEED,
    interval_m: float = SAMPLE_INTERVAL_M,
    tolerance_m: float = EDGE_TOLERANCE_M,
    artefact_warn: float = ARTEFACT_WARN,
    artefact_refuse: float = ARTEFACT_REFUSE,
) -> AdapterResult:
    """Per-unit traffic proxy, or a refusal explaining why it would have been fiction.

    Args:
        segmentation: Units covering the corridor.
        graph: The surrounding network, from :func:`fetch_network`.
        registry: Supplies the tier and licence for the adapter slot.
        n_sources: Source nodes sampled for the betweenness estimate.
        seed: Fixed so two identical runs fingerprint identically.
        interval_m: Spacing at which each unit is sampled onto the graph.
        tolerance_m: How far a sample may sit from a graph edge.
        artefact_warn, artefact_refuse: Correlation with a window-shaped parabola above
            which the result is flagged, and above which it is withheld.
    """
    require_slots(registry, SLOTS)

    if graph.n_edges == 0:
        return _refuse(
            "the strategic network around this corridor came back empty, so there is no "
            "graph to measure centrality on"
        )

    betweenness = edge_betweenness(graph, n_sources=n_sources, seed=seed)
    values, matched = _project_onto_units(
        segmentation, graph, betweenness, interval_m, tolerance_m
    )

    if not matched.any():
        return _refuse(
            f"no unit of this corridor lies within {tolerance_m:.0f} m of a "
            f"{'/'.join(STRATEGIC_CLASSES)} way. The corridor is not part of the "
            "strategic network the proxy was computed over, so its centrality in that "
            "network is not defined"
        )

    blank = int((~matched).sum())
    if blank:
        return _refuse(
            f"{blank} of {len(segmentation)} unit(s) lie more than {tolerance_m:.0f} m "
            "from any strategic way. Centrality cannot be carried across a gap the way "
            "a tag can — it is a property of the graph, not of the road"
        )

    artefact = _artefact_correlation(segmentation, values)
    if artefact is not None and artefact >= artefact_refuse:
        return _refuse(
            f"the result correlates {artefact:.2f} with a symmetric parabola centred on "
            "the corridor, which is the exact shape a query window imposes on "
            "betweenness. At that correlation the column is a picture of the area we "
            f"asked for rather than of the road. Widen the margin beyond "
            f"{graph.margin_m / 1000:.0f} km and see whether the pattern survives"
        )

    unit_ids = pd.Index(segmentation.unit_ids, name=UNIT_COLUMN)
    source = (
        f"Approximate edge betweenness over the OpenStreetMap "
        f"{'/'.join(STRATEGIC_CLASSES)} network within "
        f"{graph.margin_m / 1000:.0f} km of the corridor "
        f"({graph.n_nodes:,} junctions, {graph.n_edges:,} links), from {n_sources} "
        "sampled sources on travel time. The value is the estimated share of all "
        "shortest paths in that network that use the unit."
    )

    notes = [
        "traffic_proxy is a RELATIVE RANKING QUANTITY AND NEVER AADT. No global open "
        "source of traffic volume exists. The HSM's AADT exponent is estimated on "
        "measured volumes and does not transfer to a unitless centrality score, which "
        "is why this factor is uncited and stays uncited.",
        f"Computed over a {graph.margin_m / 1000:.0f} km margin, so the magnitudes are "
        "only comparable with other corridors computed at the same margin. Only the "
        "corridor is reported although the whole region was computed: betweenness near "
        "the edge of any window is depressed by the paths the window cut off.",
        f"Betweenness is approximated from {n_sources} sampled sources rather than all "
        f"{graph.n_nodes:,}. Exact betweenness would be false precision on a quantity "
        "with no units, and the sample is seeded so two identical runs agree.",
    ]
    if artefact is not None and artefact >= artefact_warn:
        notes.append(
            f"WARNING: the result correlates {artefact:.2f} with a symmetric parabola "
            "centred on the corridor. That is the shape a query window imposes on "
            "betweenness, and it is indistinguishable here from a genuine town in the "
            "middle of the road. Treat the along-corridor pattern as unproven until it "
            "survives a wider margin."
        )
    notes.extend(graph.warnings)

    return AdapterResult(
        name="traffic_proxy",
        resolved=[
            resolve(
                registry,
                FACTOR,
                ADAPTER,
                source=source,
                values=pd.Series(values, index=unit_ids, dtype=float),
                coverage=1.0,
                notes=notes,
            )
        ],
        notes=[f"traffic_proxy: {graph.summary()}."],
    )


# ---- internals ---------------------------------------------------------------


def _refuse(reason: str) -> AdapterResult:
    return AdapterResult(
        name="traffic_proxy",
        skipped=[SkippedFactor(FACTOR, ADAPTER, reason)],
        notes=[f"traffic_proxy: not resolved — {reason}."],
    )


def _padded_box(corridor: Corridor, margin_m: float) -> tuple[float, float, float, float]:
    """The corridor's bounding box, grown by a margin, in degrees."""
    min_x, min_y, max_x, max_y = corridor.geometry.bounds
    south, west = corridor.projector.point_to_wgs84(min_x - margin_m, min_y - margin_m)
    north, east = corridor.projector.point_to_wgs84(max_x + margin_m, max_y + margin_m)
    return south, west, north, east


def _speed_kmh(tags: dict[str, str]) -> float:
    """Posted limit where OSM states one, otherwise the class default."""
    posted = maxspeed_kmh(tags)
    if posted is not None:
        return posted
    return CLASS_SPEED_KMH.get(str(tags.get("highway", "")), DEFAULT_SPEED_KMH)


def _key(x: float, y: float) -> tuple[int, int]:
    return (round(x / NODE_PRECISION_M), round(y / NODE_PRECISION_M))


def _contract(
    ways: Sequence[dict[str, Any]],
    corridor: Corridor,
    margin_m: float,
    max_nodes: int,
    max_vertices: int = MAX_GRAPH_VERTICES,
) -> RoadGraph:
    """Turn raw ways into a graph whose nodes are junctions and ends, not vertices.

    Contraction is what makes betweenness affordable: a corridor's worth of OSM carries
    ten to fifteen vertices per junction, and every one of them would otherwise be a
    node in a Dijkstra that runs once per sampled source.

    **It has to contract across ways, not within them.** OSM splits a road at arbitrary
    points — a change of surface, a bridge, an editor's convenience — so a single road
    arrives as a chain of ways whose shared ends are not junctions at all. Walking each
    way independently and closing a run at its last vertex looks like contraction and
    achieves almost none of it: measured on the Cyprus B9 region, 483 ways came back as
    506 links, one per way. So the vertex graph is built first and the chains of
    degree-two vertices are collapsed afterwards, wherever they happen to run.
    """
    vertices: dict[tuple[int, int], int] = {}
    points: list[tuple[float, float]] = []
    # Vertex-level segments, then adjacency into them. Segments are held separately so
    # a walk can consume each exactly once and parallel roads between the same pair of
    # junctions stay distinct.
    segments: list[tuple[int, int, float]] = []
    adjacency_v: list[list[tuple[int, int]]] = []

    def vertex_for(x: float, y: float) -> int:
        key = _key(x, y)
        index = vertices.get(key)
        if index is None:
            index = len(points)
            vertices[key] = index
            points.append((x, y))
            adjacency_v.append([])
        return index

    for way in ways:
        coords = [
            corridor.projector.point_to_metric(node["lat"], node["lon"])
            for node in way["geometry"]
        ]
        tags = {str(k): str(v) for k, v in (way.get("tags") or {}).items()}
        metres_per_second = _speed_kmh(tags) / 3.6

        previous = vertex_for(*coords[0])
        for index in range(1, len(coords)):
            current = vertex_for(*coords[index])
            length = math.dist(coords[index - 1], coords[index])
            if current == previous or length <= 0.0:
                continue
            segment = len(segments)
            segments.append((previous, current, length / metres_per_second))
            adjacency_v[previous].append((current, segment))
            adjacency_v[current].append((previous, segment))
            previous = current

        # Bounds the contraction, not the Dijkstras. The graph-size refusal is below,
        # once the vertices have been collapsed into the junctions it is about.
        if len(points) > max_vertices:
            raise CorridorError(
                f"the strategic network within {margin_m / 1000:.0f} km of this "
                f"corridor holds more than {max_vertices:,} raw vertices, which is too "
                "much to contract. Reduce the margin — the traffic proxy needs a region "
                "wide enough to route through, not the whole country."
            )

    junction = [len(adjacency_v[v]) != 2 for v in range(len(points))]
    consumed = [False] * len(segments)

    node_index: dict[int, int] = {}
    node_points: list[tuple[float, float]] = []

    def node_for(vertex: int) -> int:
        index = node_index.get(vertex)
        if index is None:
            index = len(node_points)
            node_index[vertex] = index
            node_points.append(points[vertex])
        return index

    edges: list[GraphEdge] = []

    def walk(start: int, first_neighbour: int, first_segment: int) -> None:
        """Follow a chain of degree-two vertices until the next real junction."""
        consumed[first_segment] = True
        seconds = segments[first_segment][2]
        run = [points[start], points[first_neighbour]]

        # Marking each segment consumed as it is walked is also what stops the walk
        # turning round: the way back is already used, so the only unconsumed segment
        # at a degree-two vertex is the way forward.
        current = first_neighbour
        while not junction[current]:
            step = next(
                (
                    (neighbour, segment)
                    for neighbour, segment in adjacency_v[current]
                    if not consumed[segment]
                ),
                None,
            )
            if step is None:
                break
            neighbour, segment = step
            consumed[segment] = True
            seconds += segments[segment][2]
            run.append(points[neighbour])
            current = neighbour

        u, v = node_for(start), node_for(current)
        # A chain that returns to where it started is a self-loop. It carries no
        # shortest path between two distinct junctions, so it is dropped rather than
        # added as an edge Dijkstra would have to keep stepping over.
        if u != v and seconds > 0.0 and len(run) >= 2:
            edges.append(
                GraphEdge(u=u, v=v, seconds=seconds, geometry=LineString(run))
            )

    for vertex in range(len(points)):
        if not junction[vertex]:
            continue
        for neighbour, segment in adjacency_v[vertex]:
            if not consumed[segment]:
                walk(vertex, neighbour, segment)

    # Anything left is a ring of degree-two vertices with no junction on it. Break it
    # at an arbitrary point so the loop still exists in the graph.
    for segment, (u, v, _) in enumerate(segments):
        if not consumed[segment]:
            junction[u] = True
            walk(u, v, segment)

    # The refusal that matters, on the quantity that costs: one Dijkstra per sampled
    # source over the contracted graph. Raw vertices are ten to twenty times more
    # numerous and were what this used to be measured against.
    if len(node_points) > max_nodes:
        raise CorridorError(
            f"the strategic network within {margin_m / 1000:.0f} km of this corridor "
            f"contracts to {len(node_points):,} junctions, above the {max_nodes:,} this "
            "proxy will route over. Reduce the margin — the traffic proxy needs a "
            "region wide enough to route through, not the whole country."
        )

    adjacency: list[list[tuple[int, int]]] = [[] for _ in node_points]
    for index, edge in enumerate(edges):
        adjacency[edge.u].append((edge.v, index))
        adjacency[edge.v].append((edge.u, index))

    warnings: list[str] = []
    if node_points and not edges:  # pragma: no cover - a graph of isolated points
        warnings.append(
            "The strategic network contracted to junctions with no links between them, "
            "which means the ways returned do not connect to each other."
        )

    return RoadGraph(
        points=node_points,
        edges=edges,
        adjacency=adjacency,
        n_ways=len(ways),
        margin_m=margin_m,
        warnings=warnings,
    )


def _sample_sources(n: int, n_sources: int, seed: int) -> list[int]:
    """Source nodes for the betweenness estimate, chosen deterministically."""
    if n_sources >= n:
        return list(range(n))
    return sorted(random.Random(seed).sample(range(n), n_sources))


def _accumulate(graph: RoadGraph, source: int, totals: np.ndarray) -> None:
    """One source's contribution to edge betweenness — Brandes, on travel time."""
    n = graph.n_nodes
    distance = [math.inf] * n
    sigma = [0.0] * n
    predecessors: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    settled = [False] * n
    order: list[int] = []

    distance[source] = 0.0
    sigma[source] = 1.0
    queue: list[tuple[float, int]] = [(0.0, source)]

    while queue:
        d, v = heapq.heappop(queue)
        if settled[v]:
            continue
        settled[v] = True
        order.append(v)

        for w, edge in graph.adjacency[v]:
            if settled[w]:
                continue
            candidate = d + graph.edges[edge].seconds
            if candidate < distance[w] - _EPS:
                distance[w] = candidate
                sigma[w] = sigma[v]
                predecessors[w] = [(v, edge)]
                heapq.heappush(queue, (candidate, w))
            elif abs(candidate - distance[w]) <= _EPS:
                sigma[w] += sigma[v]
                predecessors[w].append((v, edge))

    delta = [0.0] * n
    for w in reversed(order):
        for v, edge in predecessors[w]:
            contribution = (sigma[v] / sigma[w]) * (1.0 + delta[w])
            totals[edge] += contribution
            delta[v] += contribution


def _project_onto_units(
    segmentation: Segmentation,
    graph: RoadGraph,
    betweenness: np.ndarray,
    interval_m: float,
    tolerance_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Average the betweenness of the graph links each unit runs along."""
    tree = STRtree([edge.geometry for edge in graph.edges])

    values = np.zeros(len(segmentation), dtype=float)
    matched = np.zeros(len(segmentation), dtype=bool)

    for position, unit in enumerate(segmentation):
        count = max(int(math.ceil(unit.length_m / interval_m)), 1)
        step = unit.length_m / count
        found: list[float] = []

        for index in range(count):
            point = unit.geometry.interpolate(float((index + 0.5) * step))
            hits = tree.query_nearest(point, max_distance=tolerance_m)
            if len(hits):
                found.append(float(betweenness[int(hits[0])]))

        if found:
            values[position] = float(np.mean(found))
            matched[position] = True

    return values, matched


def _artefact_correlation(
    segmentation: Segmentation, values: np.ndarray
) -> float | None:
    """How much the result looks like the parabola a query window would impose.

    A real peak sits wherever the town sits. The window artefact peaks dead centre by
    construction, so correlating against a symmetric parabola centred on the corridor
    separates the two better than looking at the shape by eye.
    """
    if len(values) < 4 or float(np.std(values)) == 0.0:
        return None

    midpoints = np.array([unit.midpoint_m for unit in segmentation], dtype=float)
    centre = (midpoints[0] + midpoints[-1]) / 2.0
    template = -((midpoints - centre) ** 2)

    if float(np.std(template)) == 0.0:  # pragma: no cover - needs a zero-length corridor
        return None
    return float(abs(np.corrcoef(values, template)[0, 1]))


__all__ = [
    "ARTEFACT_REFUSE",
    "ARTEFACT_WARN",
    "CLASS_SPEED_KMH",
    "DEFAULT_NETWORK_MARGIN_M",
    "DEFAULT_SOURCE_SAMPLE",
    "MAX_GRAPH_NODES",
    "MAX_GRAPH_VERTICES",
    "NETWORK_GRID_DEG",
    "SLOTS",
    "SOURCE_SEED",
    "STRATEGIC_CLASSES",
    "GraphEdge",
    "RoadGraph",
    "build_network_query",
    "compute_traffic_proxy",
    "edge_betweenness",
    "fetch_network",
]
