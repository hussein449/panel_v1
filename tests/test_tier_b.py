"""Tier B adapters — the traffic proxy from graph centrality, Mapillary detections.

Betweenness is checked against graphs small enough to work out on paper: a path, a
bridge between two clusters, a fast detour beating a slow direct road. That is the only
way to know the Brandes accumulation is right, and it is why the graph is constructed
here rather than fetched.

Neither adapter touches the network in these tests. The traffic proxy is exercised
against the live OSM network by ``tools/validate_traffic_proxy.py``; Mapillary needs an
access token, so ``tools/validate_mapillary.py`` is there for whoever has one.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from roadrisk.core.registry import Licence, Registry, Tier, Transform
from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters.graph import (
    ARTEFACT_REFUSE,
    ARTEFACT_WARN,
    DEFAULT_NETWORK_MARGIN_M,
    GraphEdge,
    RoadGraph,
    _sample_resolution,
    build_network_query,
    compute_traffic_proxy,
    edge_betweenness,
    fetch_network,
)
from roadrisk.geo.adapters.mapillary import (
    HAZARD_OBJECTS,
    MAX_TILE_SPAN_DEG,
    OBJECT_TOLERANCE_M,
    TOKEN_ENV,
    HttpMapillaryClient,
    TooMuchData,
    bounding_box,
    compute_object_density,
    fetch_features,
    tile_boxes,
    tile_length_m,
)
from roadrisk.geo.adapters.osm_density import POI_TOLERANCE_M
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError
from roadrisk.geo.segmentation import segment

ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85
LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))

CORRIDOR_M = 3000.0
UNIT_M = 500.0


def at(east_m: float, north_m: float = 0.0) -> tuple[float, float]:
    return (ORIGIN_LON + east_m * LON_PER_M, ORIGIN_LAT + north_m * LAT_PER_M)


def straight(
    start_m: float = 0.0, end_m: float = CORRIDOR_M, north_m: float = 0.0, step_m: float = 50.0
) -> list:
    count = max(int(abs(end_m - start_m) / step_m) + 1, 2)
    return [
        at(start_m + i * (end_m - start_m) / (count - 1), north_m) for i in range(count)
    ]


def way(points: list[tuple[float, float]], osm_id: int = 0, **tags: str) -> dict:
    return {
        "type": "way",
        "id": osm_id or abs(hash(tuple(points))) % 10**9,
        "tags": {"highway": "primary", **tags},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in points],
    }


def client_returning(*elements: dict):
    def fake(query: str) -> dict:
        fake.last_query = query  # type: ignore[attr-defined]
        return {"elements": list(elements)}

    fake.last_query = None  # type: ignore[attr-defined]
    return fake


@pytest.fixture(scope="module")
def corridor() -> Corridor:
    return Corridor.from_latlon([(lat, lon) for lon, lat in straight()], name="B9")


@pytest.fixture(scope="module")
def units(corridor: Corridor):
    return segment(corridor, target_length_m=UNIT_M)


def ladder_ways() -> list[dict]:
    """A through road with a side street every 200 m.

    The stubs are what make the boundaries junctions: without them contraction quite
    correctly collapses the whole corridor to one link, and there is no along-corridor
    pattern to test the artefact gate against.
    """
    ways = [way(straight(0, CORRIDOR_M))]
    ways.extend(
        way([at(float(x), 0.0), at(float(x), 300.0)], highway="secondary")
        for x in range(200, int(CORRIDOR_M), 200)
    )
    return ways


def graph_from(points: list[tuple[float, float]], links: list[tuple[int, int, float]]):
    """A RoadGraph built by hand, so betweenness can be checked against paper."""
    edges = [
        GraphEdge(
            u=u,
            v=v,
            seconds=seconds,
            geometry=LineString([points[u], points[v]]),
        )
        for u, v, seconds in links
    ]
    adjacency: list[list[tuple[int, int]]] = [[] for _ in points]
    for index, edge in enumerate(edges):
        adjacency[edge.u].append((edge.v, index))
        adjacency[edge.v].append((edge.u, index))
    return RoadGraph(
        points=points,
        edges=edges,
        adjacency=adjacency,
        n_ways=len(edges),
        margin_m=DEFAULT_NETWORK_MARGIN_M,
    )


# ---- the graph ---------------------------------------------------------------


class TestNetworkQuery:
    def test_the_network_is_fetched_as_a_box_not_a_ribbon(
        self, corridor: Corridor
    ) -> None:
        """Through traffic routes through an area. A ribbon graph has nowhere else to go.

        This is the one OSM fetch in the package that deliberately does not use the
        corridor-following `around` filter.
        """
        query = build_network_query(corridor)

        assert "around" not in query
        assert "motorway|trunk|primary|secondary|tertiary" in query
        assert "out geom;" in query

    def test_residential_streets_are_left_out(self, corridor: Corridor) -> None:
        assert "residential" not in build_network_query(corridor)

    def test_the_box_is_padded_by_the_margin(self, corridor: Corridor) -> None:
        tight = build_network_query(corridor, margin_m=1000.0)
        wide = build_network_query(corridor, margin_m=40_000.0)

        assert tight != wide


class TestContraction:
    def test_a_plain_way_becomes_one_link(self, corridor: Corridor) -> None:
        """Sixty vertices, no junctions: one edge between two ends.

        Contraction is what makes betweenness affordable — every uncontracted vertex
        would be a node in a Dijkstra that runs once per sampled source.
        """
        graph = fetch_network(
            corridor, client=client_returning(way(straight(0, 3000))), margin_m=5000.0
        )

        assert graph.n_nodes == 2
        assert graph.n_edges == 1

    def test_the_size_refusal_counts_junctions_not_raw_vertices(
        self, corridor: Corridor
    ) -> None:
        """The A3 bug: Paris was refused on 674,358 vertices worth 37,935 junctions.

        A straight way of sixty vertices contracts to two nodes, so a ceiling of two
        must accept it. The quantity a Dijkstra costs is junctions, and measuring the
        refusal against vertices rejected the dense urban corridors this proxy is most
        worth having on.
        """
        graph = fetch_network(
            corridor,
            client=client_returning(way(straight(0, 3000))),
            margin_m=5000.0,
            max_nodes=2,
        )

        assert graph.n_nodes == 2

    def test_a_graph_of_too_many_junctions_is_still_refused(
        self, corridor: Corridor
    ) -> None:
        """The ceiling still exists; it is only measured on the right thing now."""
        crossings = [
            way([at(float(x), -400.0), at(float(x), 400.0)], highway="secondary")
            for x in range(200, 2800, 200)
        ]
        with pytest.raises(CorridorError, match="contracts to"):
            fetch_network(
                corridor,
                client=client_returning(way(straight(0, 3000)), *crossings),
                margin_m=5000.0,
                max_nodes=4,
            )

    def test_a_region_too_large_to_contract_is_refused_on_vertices(
        self, corridor: Corridor
    ) -> None:
        """The vertex ceiling survives, bounding contraction rather than the fit."""
        with pytest.raises(CorridorError, match="raw vertices"):
            fetch_network(
                corridor,
                client=client_returning(way(straight(0, 3000))),
                margin_m=5000.0,
                max_vertices=10,
            )

    def test_a_t_junction_splits_the_through_road(self, corridor: Corridor) -> None:
        graph = fetch_network(
            corridor,
            client=client_returning(
                way(straight(0, 3000)),
                way([at(1500.0, 0.0), at(1500.0, 800.0)], highway="secondary"),
            ),
            margin_m=5000.0,
        )

        assert graph.n_nodes == 4, "two ends, the junction, and the side road's far end"
        assert graph.n_edges == 3

    def test_the_graph_does_not_depend_on_the_order_the_mirror_returned_ways(
        self, corridor: Corridor
    ) -> None:
        """Two identical runs must fingerprint identically — the manifest depends on it."""
        ways = [
            way(straight(0, 1500), osm_id=11),
            way(straight(1500, 3000), osm_id=22),
            way([at(1500.0, 0.0), at(1500.0, 800.0)], osm_id=33, highway="secondary"),
        ]
        forward = fetch_network(
            corridor, client=client_returning(*ways), margin_m=5000.0
        )
        shuffled = fetch_network(
            corridor, client=client_returning(*reversed(ways)), margin_m=5000.0
        )

        assert forward.points == shuffled.points
        assert np.array_equal(edge_betweenness(forward), edge_betweenness(shuffled))

    def test_travel_time_uses_the_posted_limit_where_osm_states_one(
        self, corridor: Corridor
    ) -> None:
        slow = fetch_network(
            corridor,
            client=client_returning(way(straight(0, 3000), maxspeed="30")),
            margin_m=5000.0,
        )
        fast = fetch_network(
            corridor,
            client=client_returning(way(straight(0, 3000), maxspeed="100")),
            margin_m=5000.0,
        )

        assert slow.edges[0].seconds > fast.edges[0].seconds


class TestBetweenness:
    def test_the_middle_of_a_path_carries_the_most(self) -> None:
        """A-B-C-D-E: the two middle links are on more shortest paths than the ends."""
        points = [(float(i) * 100.0, 0.0) for i in range(5)]
        graph = graph_from(points, [(i, i + 1, 1.0) for i in range(4)])

        scores = edge_betweenness(graph)

        assert scores[1] > scores[0]
        assert scores[2] > scores[3]
        assert scores[1] == pytest.approx(scores[2])

    def test_a_bridge_between_two_clusters_carries_everything(self) -> None:
        """Every path from one side to the other must use it, and betweenness says so."""
        points = [(float(i) * 100.0, 0.0) for i in range(6)]
        graph = graph_from(
            points,
            [
                (0, 1, 1.0),
                (1, 2, 1.0),
                (0, 2, 1.0),
                (2, 3, 1.0),  # the bridge
                (3, 4, 1.0),
                (4, 5, 1.0),
                (3, 5, 1.0),
            ],
        )

        scores = edge_betweenness(graph)
        bridge = 3  # index of (2, 3)

        assert scores[bridge] == max(scores)

    def test_a_fast_detour_beats_a_slow_direct_road(self) -> None:
        """Shortest paths on travel time route the way drivers do."""
        points = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0), (50.0, -100.0)]
        graph = graph_from(
            points,
            [
                (0, 1, 100.0),  # direct but slow
                (0, 2, 1.0),  # fast detour, first leg
                (2, 1, 1.0),  # fast detour, second leg
                (0, 3, 50.0),
            ],
        )

        scores = edge_betweenness(graph)

        assert scores[1] > scores[0], "the detour carries the traffic"
        assert scores[2] > scores[0]

    def test_a_graph_too_small_to_have_paths_scores_zero(self) -> None:
        graph = graph_from([(0.0, 0.0), (1.0, 0.0)], [(0, 1, 1.0)])
        assert edge_betweenness(graph).tolist() == [0.0]

    def test_the_estimate_is_a_share_and_cannot_exceed_one(self) -> None:
        points = [(float(i) * 100.0, 0.0) for i in range(8)]
        graph = graph_from(points, [(i, i + 1, 1.0) for i in range(7)])

        scores = edge_betweenness(graph)

        assert scores.max() <= 1.0
        assert scores.min() >= 0.0

    def test_sampling_is_deterministic(self) -> None:
        points = [(float(i) * 100.0, 0.0) for i in range(40)]
        graph = graph_from(points, [(i, i + 1, 1.0) for i in range(39)])

        assert np.array_equal(
            edge_betweenness(graph, n_sources=8), edge_betweenness(graph, n_sources=8)
        )


class TestTrafficProxy:
    def test_it_resolves_along_the_corridor(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        graph = fetch_network(
            corridor,
            client=client_returning(
                way(straight(0, 3000)),
                way([at(1000.0, 0.0), at(1000.0, 2000.0)], highway="secondary"),
                way([at(2000.0, 0.0), at(2000.0, 2000.0)], highway="secondary"),
                way([at(1000.0, 2000.0), at(2000.0, 2000.0)], highway="secondary"),
            ),
            margin_m=5000.0,
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        assert result.resolved
        assert result.resolved[0].tier is Tier.B
        assert result.resolved[0].licence is Licence.ODBL
        assert len(result.resolved[0].values) == len(units)

    def test_it_is_never_labelled_aadt(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """The 'done when' of step 2.8, asserted rather than trusted."""
        graph = fetch_network(
            corridor, client=client_returning(way(straight(0, 3000))), margin_m=5000.0
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        assert result.resolved[0].column == "traffic_proxy"
        assert any("NEVER AADT" in note for note in result.resolved[0].notes)

    def test_no_unit_reads_exactly_zero(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Zero is a claim about the sample, and `ln` cannot take it either way.

        A unit no sampled shortest path happened to use has a true share somewhere
        below the estimator's resolution, not of zero, so it is floored at half of it.
        """
        graph = fetch_network(
            corridor,
            client=client_returning(
                way(straight(0, 3000)),
                way([at(1000.0, 0.0), at(1000.0, 2000.0)], highway="secondary"),
                way([at(2000.0, 0.0), at(2000.0, 2000.0)], highway="secondary"),
                way([at(1000.0, 2000.0), at(2000.0, 2000.0)], highway="secondary"),
            ),
            margin_m=5000.0,
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        values = list(result.resolved[0].values)
        assert values, "the adapter resolved nothing to check"
        assert all(v > 0.0 for v in values)

    def test_a_graph_too_small_to_route_leaves_a_constant_column(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Two nodes carry no shortest paths, so every unit reads the same.

        There is no resolution to floor against and nothing to learn either way. The
        column is constant, and the engine drops constant columns before any transform
        sees them — so `ln` is never asked to take the logarithm of zero.
        """
        graph = fetch_network(
            corridor, client=client_returning(way(straight(0, 3000))), margin_m=5000.0
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        values = list(result.resolved[0].values)
        assert len(set(values)) == 1

    def test_the_floor_is_the_estimator_resolution(self) -> None:
        """Half of what one path through one link contributes, not an arbitrary epsilon."""
        assert _sample_resolution(100, 128) == pytest.approx(
            (100 / 100) / 2.0 / (100 * 99 / 2.0)
        )
        # More sources than nodes cannot sample a node twice.
        assert _sample_resolution(10, 128) == _sample_resolution(10, 10)

    def test_flooring_is_reported_when_it_happens(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        graph = fetch_network(
            corridor, client=client_returning(way(straight(0, 3000))), margin_m=5000.0
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)
        notes = result.resolved[0].notes

        if any(note.startswith("0 of") for note in notes):  # pragma: no cover
            pytest.skip("this fixture floored nothing")
        floored = [n for n in notes if "floored to half the estimator" in n]
        if floored:
            assert "resolution" in floored[0]

    def test_the_registry_fits_it_on_a_multiplicative_scale(
        self, shipped_registry: Registry
    ) -> None:
        """ln1p on a share of order 1e-3 is the identity, and extrapolates linearly.

        Cross-validated on the A3, that failed contiguous-stretch calibration at 0.674;
        under `ln` the same corridor calibrates at 1.143. A lock, because the difference
        does not look like it matters and does.
        """
        factor = next(
            f for f in shipped_registry.factors if f.name == "traffic_proxy"
        )
        assert factor.transform is Transform.LN

    def test_a_corridor_off_the_strategic_network_is_refused(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Centrality is a property of the graph. It cannot be carried across a gap."""
        graph = fetch_network(
            corridor,
            client=client_returning(way(straight(0, 3000, north_m=5000.0))),
            margin_m=8000.0,
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        assert result.resolved == []
        assert "not part of the strategic network" in result.skipped[0].reason

    def test_an_empty_network_is_refused(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        graph = fetch_network(corridor, client=client_returning(), margin_m=5000.0)
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        assert result.resolved == []
        assert "came back empty" in result.skipped[0].reason

    def test_a_window_shaped_result_is_refused(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """The reason this module is more than twenty lines.

        A corridor with nothing in the graph but its own side streets produces
        betweenness that peaks dead centre — the exact shape a query window imposes, and
        indistinguishable at a glance from a town in the middle of the road.
        """
        graph = fetch_network(
            corridor, client=client_returning(*ladder_ways()), margin_m=5000.0
        )
        result = compute_traffic_proxy(units, graph, registry=shipped_registry)

        assert result.resolved == []
        assert "symmetric parabola" in result.skipped[0].reason

    def test_the_artefact_gate_can_be_relaxed_for_a_corridor_that_earns_it(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """The gate is a threshold, not a law — but the default refuses by design."""
        graph = fetch_network(
            corridor, client=client_returning(*ladder_ways()), margin_m=5000.0
        )
        relaxed = compute_traffic_proxy(
            units, graph, registry=shipped_registry, artefact_refuse=1.01
        )

        assert relaxed.resolved
        assert any("WARNING" in note for note in relaxed.resolved[0].notes)

    def test_the_widest_measured_margin_is_the_default(self) -> None:
        """5/10/20 km on Cyprus B9 gave artefact correlations 0.38/0.69/0.41.

        Not monotonic — the along-corridor pattern is simply unstable under a change of
        window, which is the honest finding. The widest is the default on the
        methodological ground that it cuts off fewest through-routes.
        """
        assert DEFAULT_NETWORK_MARGIN_M == 20_000.0
        assert ARTEFACT_REFUSE > ARTEFACT_WARN


# ---- mapillary ---------------------------------------------------------------


def feature(east_m: float, north_m: float, value: str) -> dict:
    lon, lat = at(east_m, north_m)
    return {
        "id": abs(hash((east_m, north_m))) % 10**9,
        "object_value": value,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def mapillary_returning(*features: dict):
    def fake(bbox):
        fake.last_bbox = bbox  # type: ignore[attr-defined]
        return {"data": list(features)}

    fake.last_bbox = None  # type: ignore[attr-defined]
    return fake


class TestMapillaryFetch:
    def test_the_bbox_is_west_south_east_north(self, corridor: Corridor) -> None:
        """Mapillary and Overpass disagree on the order. Getting it wrong returns Kenya."""
        west, south, east, north = bounding_box(corridor)

        assert west < east
        assert south < north
        assert 32.8 < west < 32.9
        assert 34.8 < south < 35.0

    def test_every_tile_stays_under_the_span_the_api_accepts(
        self, corridor: Corridor
    ) -> None:
        """Measured, not documented: a 0.053 x 0.137 box answers HTTP 500.

        The failure gives no hint that size is the problem — it says "an unknown error
        occurred" — so the limit is enforced here rather than discovered again.
        """
        for west, south, east, north in tile_boxes(corridor):
            assert east - west <= MAX_TILE_SPAN_DEG
            assert north - south <= MAX_TILE_SPAN_DEG

    def test_a_long_corridor_is_tiled_and_a_short_one_is_not(
        self, corridor: Corridor
    ) -> None:
        short = Corridor.from_latlon(
            [(lat, lon) for lon, lat in straight(0, 400)], name="short"
        )

        assert len(tile_boxes(short)) == 1
        assert len(tile_boxes(corridor)) > 1

    def test_the_tiles_cover_the_whole_corridor(self, corridor: Corridor) -> None:
        tiles = tile_boxes(corridor)
        whole = bounding_box(corridor)

        assert min(t[0] for t in tiles) == pytest.approx(whole[0], abs=1e-6)
        assert max(t[2] for t in tiles) == pytest.approx(whole[2], abs=1e-6)

    def test_tiles_shrink_towards_the_poles(self) -> None:
        """A degree of longitude is half a degree of latitude in metres at 60 north."""
        tropical = Corridor.from_latlon(
            [(5.0, 10.0), (5.0, 10.05)], name="tropical"
        )
        arctic = Corridor.from_latlon([(69.0, 20.0), (69.0, 20.05)], name="arctic")

        assert tile_length_m(arctic, 120.0) < tile_length_m(tropical, 120.0)

    def test_a_pole_seen_in_two_overlapping_tiles_is_counted_once(
        self, corridor: Corridor
    ) -> None:
        """Padded tiles overlap, so a boundary pole comes back twice.

        Counting it twice would inflate the density of exactly the units that sit on a
        tile edge — an artefact of our own tiling, not of the road.
        """
        duplicate = feature(100.0, 10.0, "object--street-light")

        def every_tile_returns_it(bbox):
            return {"data": [duplicate]}

        features = fetch_features(corridor, client=every_tile_returns_it)

        assert features.n_tiles > 1, "the fixture needs more than one tile to matter"
        assert features.n_returned == features.n_tiles
        assert features.n_counted == 1

    def test_a_tile_too_dense_to_answer_is_split_and_retried(
        self, corridor: Corridor
    ) -> None:
        """Mapillary refuses on the size of the ANSWER, not the size of the question.

        Its words, verbatim, as HTTP 500: "Please reduce the amount of data you're
        asking for, then retry your request". So a tile that is comfortable through
        farmland is refused in a city centre, and the remedy is automatic — ask for
        half of the same thing.
        """
        refused: list[tuple[float, float, float, float]] = []

        def dense_in_the_west(bbox):
            west, south, east, north = bbox
            if east - west > 0.004:
                refused.append(bbox)
                raise TooMuchData("Please reduce the amount of data you're asking for")
            return {"data": [feature(100.0, 10.0, "object--street-light")]}

        features = fetch_features(corridor, client=dense_in_the_west)

        assert refused, "the fixture must actually refuse something"
        assert features.n_counted == 1, "still deduplicated across the split pieces"
        assert any("was split into" in note for note in features.warnings)

    def test_a_tile_that_never_shrinks_enough_gives_up_and_says_why(
        self, corridor: Corridor
    ) -> None:
        """Halving forever is not a strategy. Three halvings, then the real error."""

        def always_too_much(bbox):
            raise TooMuchData("Please reduce the amount of data you're asking for")

        with pytest.raises(TooMuchData, match="reduce the amount of data"):
            fetch_features(corridor, client=always_too_much)

    def test_a_client_error_is_not_retried(self, corridor: Corridor) -> None:
        """A 4xx means we asked wrongly. Splitting the box would just ask wrongly twice."""
        calls = []

        def refuses(bbox):
            calls.append(bbox)
            raise CorridorError("Mapillary refused the request with HTTP 400.")

        with pytest.raises(CorridorError, match="HTTP 400"):
            fetch_features(corridor, client=refuses)

        assert len(calls) == 1

    def test_an_absurd_corridor_refuses_rather_than_flooding_a_free_api(self) -> None:
        long_road = Corridor.from_latlon([(0.0, 0.0), (0.0, 20.0)], name="very-long")

        with pytest.raises(CorridorError, match="over the"):
            tile_boxes(long_road)

    def test_only_roadside_objects_are_counted(self, corridor: Corridor) -> None:
        features = fetch_features(
            corridor,
            client=mapillary_returning(
                feature(100.0, 10.0, "object--support--utility-pole"),
                feature(200.0, 10.0, "object--bench"),
                feature(300.0, 10.0, "object--trash-can"),
                feature(400.0, 10.0, "object--street-light"),
            ),
        )

        # The fake answers every tile with the same four, so the raw count scales with
        # tiling; the counted total does not, because the four have stable ids.
        assert features.n_returned == 4 * features.n_tiles
        assert features.n_counted == 2

    def test_hitting_the_page_limit_is_reported(self, corridor: Corridor) -> None:
        many = [feature(float(i), 10.0, "object--street-light") for i in range(5)]
        features = fetch_features(
            corridor, client=mapillary_returning(*many), limit=5
        )

        assert features.limit_reached
        assert any("page limit" in note for note in features.warnings)

    def test_a_missing_token_names_the_environment_variable(self, monkeypatch) -> None:
        monkeypatch.delenv(TOKEN_ENV, raising=False)

        with pytest.raises(CorridorError, match=TOKEN_ENV):
            HttpMapillaryClient()((32.8, 34.8, 32.9, 34.9))

    def test_the_object_list_is_rigid_things_not_street_furniture(self) -> None:
        """Struck-object risk is about rigid things close to the carriageway."""
        assert "object--support--utility-pole" in HAZARD_OBJECTS
        assert "object--bench" not in HAZARD_OBJECTS
        assert "object--trash-can" not in HAZARD_OBJECTS

    def test_signage_is_excluded_so_this_is_not_a_second_poi_density(self) -> None:
        """Found by validating on central Amsterdam, not by reasoning about it.

        Shop, advertisement and information signs plus banners were 591 of 1,088
        detections there — 54% of the column. They hang on building facades rather than
        standing in the verge, so they are not struck-object hazards; what they measure
        is shopfront density. Counting them would have made roadside_object_density a
        noisier copy of poi_density, collinear with it by construction.
        """
        for signage in (
            "object--sign--store",
            "object--sign--advertisement",
            "object--sign--information",
            "object--banner",
        ):
            assert signage not in HAZARD_OBJECTS

    def test_the_hazard_radius_is_the_clear_zone_not_the_neighbourhood(self) -> None:
        """A struck object is one you could hit; a POI is one that generates trips.

        At 50 m in central Amsterdam this factor counted objects on parallel streets and
        reported a median of 136 per km — one every seven metres.
        """
        assert OBJECT_TOLERANCE_M < POI_TOLERANCE_M
        assert OBJECT_TOLERANCE_M >= 10.0, "must still clear the AASHTO clear zone"


class TestObjectDensity:
    def test_objects_are_counted_per_km_in_the_right_unit(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        features = fetch_features(
            corridor,
            client=mapillary_returning(
                feature(100.0, 10.0, "object--street-light"),
                feature(200.0, 10.0, "object--street-light"),
                feature(1700.0, 10.0, "object--support--pole"),
            ),
        )
        result = compute_object_density(units, features, registry=shipped_registry)
        values = result.resolved[0].values

        assert values.iloc[0] == pytest.approx(2.0 / units.units[0].length_km)
        assert values.iloc[3] == pytest.approx(1.0 / units.units[3].length_km)
        assert values.iloc[1] == 0.0

    def test_an_object_beyond_the_tolerance_is_not_roadside(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        features = fetch_features(
            corridor,
            client=mapillary_returning(
                feature(100.0, 400.0, "object--street-light"),
            ),
            margin_m=1000.0,
        )
        result = compute_object_density(units, features, registry=shipped_registry)

        assert result.resolved[0].values.sum() == 0.0

    def test_no_detections_means_absent_not_zero(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Mapillary coverage follows where somebody drove with a camera."""
        features = fetch_features(corridor, client=mapillary_returning())
        result = compute_object_density(units, features, registry=shipped_registry)

        assert result.resolved == []
        assert "absence of imagery" in result.skipped[0].reason

    def test_the_hazard_score_is_always_refused_with_its_reason(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """The registry declares this adapter against it. Deriving it would be fiction.

        roadside_hazard_score is measured on the HSM roadside hazard rating, an integer
        1 to 7 whose cited weight is meaningless on any other scale. Turning poles per
        km into an RHR needs a study, not an assumption.
        """
        features = fetch_features(
            corridor,
            client=mapillary_returning(feature(100.0, 10.0, "object--street-light")),
        )
        result = compute_object_density(units, features, registry=shipped_registry)

        refusal = next(
            skip for skip in result.skipped if skip.factor == "roadside_hazard_score"
        )
        assert "HSM roadside hazard rating" in refusal.reason
        assert "roadside_hazard_score" not in [v.factor for v in result.resolved]

    def test_the_note_corrects_the_registry_about_trees_and_walls(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        features = fetch_features(
            corridor,
            client=mapillary_returning(feature(100.0, 10.0, "object--street-light")),
        )
        result = compute_object_density(units, features, registry=shipped_registry)

        assert any("Trees and walls" in note for note in result.resolved[0].notes)


class TestPipelineIntegration:
    def test_tier_b_values_are_capped_at_medium_confidence(self, units) -> None:
        """Nobody stated it; a model inferred it. Fusion knows that from the tier."""
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
            mapillary_client=mapillary_returning(
                feature(100.0, 10.0, "object--street-light"),
                feature(1700.0, 10.0, "object--support--pole"),
            ),
        )

        confidence = built.confidence
        objects = confidence[confidence["factor"] == "roadside_object_density"]

        assert not objects.empty
        assert (objects["confidence"] == "medium").all()
        assert (objects["reason"] == "inferred").all()

    def test_a_failed_mapillary_fetch_costs_only_its_own_factor(self, units) -> None:
        def failing(bbox):
            raise CorridorError("token expired.")

        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
            mapillary_client=failing,
        )

        assert "curve_radius_min" in built.panel.columns
        assert "roadside_object_density" not in built.panel.columns
        assert any("Mapillary fetch failed" in note for note in built.warnings)

    def test_a_failed_network_fetch_costs_only_the_traffic_proxy(self, units) -> None:
        def failing(query: str):
            raise CorridorError("every Overpass mirror failed.")

        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
            network_client=failing,
        )

        assert "curve_radius_min" in built.panel.columns
        assert "traffic_proxy" not in built.panel.columns
        assert any("strategic network fetch failed" in note for note in built.warnings)

    def test_the_pipeline_stays_offline_unless_asked(self) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            target_length_m=UNIT_M,
        )

        assert "traffic_proxy" not in built.panel.columns
        assert "roadside_object_density" not in built.panel.columns


def test_count_per_unit_is_shared_with_the_osm_densities(units) -> None:
    """Mapillary reuses the OSM density counter rather than growing a second one."""
    from roadrisk.geo.adapters.osm_density import count_per_unit

    point = units.corridor.geometry.interpolate(700.0)
    counts = count_per_unit([Point(point.x, point.y + 10.0)], units, 50.0)

    assert counts.sum() == 1.0
    assert counts[1] == 1.0
