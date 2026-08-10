"""Tier A source adapters — the contract, the OSM tag readers, the density counters.

Every test here uses a **fake Overpass client**, for the same reason the corridor tests
do: a suite that reaches the network is slow, flaky, and fails for reasons that have
nothing to do with the code.

The fixtures are built in metres from a fixed origin in Cyprus, so the UTM zone and the
metres-per-degree scaling are realistic rather than notional.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.registry import Licence, Registry, Tier
from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters import (
    count_densities,
    curvature_adapter,
    fetch_extract,
    fuse,
    match_carriers,
    provenance_frame,
    read_tags,
    resolve,
)
from roadrisk.geo.adapters.base import (
    AdapterResult,
    FactorValues,
    collect_notes,
    require_slots,
)
from roadrisk.geo.adapters.osm_density import SLOTS as DENSITY_SLOTS
from roadrisk.geo.adapters.osm_density import count_per_unit
from roadrisk.geo.adapters.osm_tags import SLOTS as TAG_SLOTS
from roadrisk.geo.adapters.osmdata import build_extract_query
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.errors import CorridorError, GeoError
from roadrisk.geo.geometry import compute_curvature
from roadrisk.geo.segmentation import segment

ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85

LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))

CORRIDOR_M = 3000.0
UNIT_M = 500.0


def at(east_m: float, north_m: float = 0.0) -> tuple[float, float]:
    """A (longitude, latitude) pair offset from the origin by metres."""
    return (ORIGIN_LON + east_m * LON_PER_M, ORIGIN_LAT + north_m * LAT_PER_M)


def run(start_m: float, end_m: float, north_m: float = 0.0, step_m: float = 50.0) -> list:
    """A straight run along the easting axis."""
    count = max(int(abs(end_m - start_m) / step_m) + 1, 2)
    return [
        at(start_m + i * (end_m - start_m) / (count - 1), north_m) for i in range(count)
    ]


def way(points: list[tuple[float, float]], **tags: str) -> dict:
    """One Overpass way element, in the shape `out geom;` returns."""
    return {
        "type": "way",
        "id": abs(hash((tuple(points), tuple(sorted(tags.items()))))) % 10**9,
        "tags": {"highway": "primary", **tags},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in points],
    }


def poi(east_m: float, north_m: float, **tags: str) -> dict:
    lon, lat = at(east_m, north_m)
    return {
        "type": "node",
        "id": abs(hash((east_m, north_m))) % 10**9,
        "lat": lat,
        "lon": lon,
        "tags": tags or {"amenity": "restaurant"},
    }


def client_returning(*elements: dict):
    """A fake Overpass client that records the query it was handed."""

    def fake(query: str) -> dict:
        fake.last_query = query  # type: ignore[attr-defined]
        return {"elements": list(elements)}

    fake.last_query = None  # type: ignore[attr-defined]
    return fake


@pytest.fixture(scope="module")
def corridor() -> Corridor:
    return Corridor.from_latlon(
        [(lat, lon) for lon, lat in run(0.0, CORRIDOR_M)], name="B9"
    )


@pytest.fixture(scope="module")
def units(corridor: Corridor):
    return segment(corridor, target_length_m=UNIT_M)


def extract_from(corridor: Corridor, *elements: dict, ref: str | None = None):
    return fetch_extract(corridor, client=client_returning(*elements), ref=ref)


def values_of(result: AdapterResult, factor: str) -> pd.Series:
    for resolved in result.resolved:
        if resolved.factor == factor:
            return resolved.values
    raise AssertionError(
        f"'{factor}' did not resolve; skipped: "
        + ", ".join(f"{s.factor} ({s.reason[:40]}…)" for s in result.skipped)
    )


def factor_of(result: AdapterResult, factor: str):
    for resolved in result.resolved:
        if resolved.factor == factor:
            return resolved
    raise AssertionError(f"'{factor}' did not resolve")


def skip_reason(result: AdapterResult, factor: str) -> str:
    for skipped in result.skipped:
        if skipped.factor == factor:
            return skipped.reason
    raise AssertionError(f"'{factor}' was not skipped; it resolved")


# ---- the contract ------------------------------------------------------------


class TestAdapterContract:
    """Value, source, tier and licence — and the tier is not the adapter's to choose."""

    def test_tier_and_licence_come_from_the_registry(
        self, shipped_registry: Registry
    ) -> None:
        value = resolve(
            shipped_registry,
            "speed_limit",
            "osm_maxspeed",
            source="a tag",
            values=pd.Series([80.0], index=["u-0"]),
        )

        assert value.tier is Tier.A
        assert value.licence is Licence.ODBL
        assert value.column == "speed_limit"

    def test_an_undeclared_adapter_cannot_contribute_a_value(
        self, shipped_registry: Registry
    ) -> None:
        """The registry is the source of truth for provenance, not the code.

        An adapter that could name its own slot could attach a tier and a licence the
        registry never agreed to, which is exactly the claim a client relies on.
        """
        with pytest.raises(GeoError, match="does not declare an adapter named"):
            resolve(
                shipped_registry,
                "speed_limit",
                "osm_maxspeed_v2",
                source="a tag",
                values=pd.Series([80.0], index=["u-0"]),
            )

    def test_an_unknown_factor_is_refused(self, shipped_registry: Registry) -> None:
        with pytest.raises(GeoError, match="not a factor in registry"):
            resolve(
                shipped_registry,
                "vibes",
                "osm_maxspeed",
                source="a tag",
                values=pd.Series([1.0], index=["u-0"]),
            )

    def test_slots_are_checked_before_any_work_is_done(
        self, shipped_registry: Registry
    ) -> None:
        require_slots(shipped_registry, TAG_SLOTS)
        require_slots(shipped_registry, DENSITY_SLOTS)

        with pytest.raises(GeoError, match="does not declare an adapter named"):
            require_slots(shipped_registry, [("lit", "osm_streetlight")])

    def test_a_column_with_a_gap_is_refused(self) -> None:
        """A partial column silently changes which rows the model sees."""
        with pytest.raises(GeoError, match="unresolved on unit"):
            FactorValues(
                factor="lit",
                column="lit",
                adapter="osm_lit",
                tier=Tier.A,
                licence=Licence.ODBL,
                source="a tag",
                values=pd.Series([1.0, float("nan")], index=["u-0", "u-1"]),
            )

    def test_repeated_unit_ids_are_refused(self) -> None:
        with pytest.raises(GeoError, match="repeated unit id"):
            FactorValues(
                factor="lit",
                column="lit",
                adapter="osm_lit",
                tier=Tier.A,
                licence=Licence.ODBL,
                source="a tag",
                values=pd.Series([1.0, 0.0], index=["u-0", "u-0"]),
            )

    def test_provenance_carries_all_four_things_the_brief_asks_for(
        self, shipped_registry: Registry
    ) -> None:
        result = AdapterResult(
            name="osm_tags",
            resolved=[
                resolve(
                    shipped_registry,
                    "lanes",
                    "osm_lanes",
                    source="OpenStreetMap `lanes`",
                    values=pd.Series([2.0], index=["u-0"]),
                    coverage=0.8,
                )
            ],
        )

        frame = provenance_frame(fuse([result], shipped_registry))
        row = frame.iloc[0]

        assert row["column"] == "lanes"
        assert row["tier"] == "A"
        assert row["licence"] == "ODbL"
        assert "lanes" in row["source"]
        assert row["coverage"] == pytest.approx(0.8)

    def test_skip_reasons_reach_the_report(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M)))
        result = read_tags(extract, units, registry=shipped_registry)

        notes = collect_notes([result])
        assert any("not resolved by osm_lit" in note for note in notes)


class TestCurvatureAdapter:
    def test_the_same_computation_carries_different_provenance(
        self, units, shipped_registry: Registry
    ) -> None:
        """Circumradius is circumradius. Where the line came from is not."""
        curvature = compute_curvature(units)

        from_osm = curvature_adapter(
            curvature, units, registry=shipped_registry, adapter="osm_geometry"
        )
        from_client = curvature_adapter(
            curvature, units, registry=shipped_registry, adapter="client_alignment"
        )

        assert from_osm.resolved[0].tier is Tier.A
        assert from_osm.resolved[0].licence is Licence.ODBL
        assert from_client.resolved[0].tier is Tier.D
        assert from_client.resolved[0].licence is Licence.CLIENT
        assert from_osm.resolved[0].values.equals(from_client.resolved[0].values)


# ---- the extract -------------------------------------------------------------


class TestExtractQuery:
    def test_the_query_follows_the_corridor_not_its_bounding_box(
        self, corridor: Corridor
    ) -> None:
        """`around` on a polyline asks for a ribbon; a bbox asks for everything in it."""
        client = client_returning(way(run(0.0, CORRIDOR_M)))
        fetch_extract(corridor, client=client)

        query = client.last_query
        assert "around:100" in query
        assert "around:60" in query
        assert '["highway"]' in query
        assert "out geom;" in query

    def test_roads_buildings_and_pois_arrive_in_one_request(
        self, corridor: Corridor
    ) -> None:
        """One fetch, not nine. Overpass is volunteer-run infrastructure."""
        client = client_returning()
        fetch_extract(corridor, client=client)

        query = client.last_query
        assert query.count("out geom;") == 1, "one request"
        assert query.count("around:") == 3, "roads, buildings, POIs"
        assert '["building"]' in query

    def test_a_polyline_needs_two_points(self) -> None:
        with pytest.raises(CorridorError, match="at least two coordinates"):
            build_extract_query([(34.9, 32.85)])

    def test_a_long_corridor_is_simplified_and_says_so(self) -> None:
        """A 700-vertex polyline repeated across clauses is a query, not a corridor."""
        zigzag = [
            (lat, lon)
            for lon, lat in (
                at(index * 40.0, 12.0 if index % 2 else -12.0) for index in range(900)
            )
        ]
        long_corridor = Corridor.from_latlon(zigzag, name="zigzag")

        client = client_returning()
        extract = fetch_extract(long_corridor, client=client, max_query_vertices=200)

        assert extract.query_vertices <= 200
        assert any("simplified at" in note for note in extract.warnings)


class TestExtractParsing:
    def test_geometry_is_projected_into_the_corridor_crs(
        self, corridor: Corridor
    ) -> None:
        """Everything downstream compares distances; degrees would be meaningless."""
        extract = extract_from(corridor, way(run(0.0, 1000.0)))
        line = extract.ways[0].geometry

        assert line.length == pytest.approx(1000.0, abs=2.0)
        assert corridor.geometry.distance(line) < 1.0

    def test_geometry_free_ways_are_dropped(self, corridor: Corridor) -> None:
        extract = extract_from(
            corridor,
            {"type": "way", "id": 1, "tags": {"highway": "primary"}, "geometry": []},
        )
        assert extract.ways == ()

    def test_an_empty_extract_is_reported_not_assumed_away(
        self, corridor: Corridor
    ) -> None:
        extract = extract_from(corridor)

        assert extract.is_empty
        assert any("no highway ways" in note for note in extract.warnings)

    def test_a_road_split_into_two_ways_is_not_a_junction(
        self, corridor: Corridor
    ) -> None:
        """Editors split ways constantly. Degree 2 is a continuation, not a junction."""
        extract = extract_from(
            corridor, way(run(0.0, 1500.0)), way(run(1500.0, CORRIDOR_M))
        )
        assert extract.junction_points() == []

    def test_a_side_road_ending_on_the_corridor_is_a_junction(
        self, corridor: Corridor
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            way([at(700.0, 0.0), at(700.0, 200.0)], highway="residential"),
        )
        points = extract.junction_points()

        assert len(points) == 1
        assert corridor.geometry.project(points[0]) == pytest.approx(700.0, abs=5.0)

    def test_a_driveway_join_is_not_counted_as_a_junction(
        self, corridor: Corridor
    ) -> None:
        """Otherwise access_density and junction_density are collinear by construction."""
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            way([at(700.0, 0.0), at(700.0, 40.0)], highway="service", service="driveway"),
        )
        assert extract.junction_points() == []

    def test_a_slip_road_join_is_not_counted_as_a_junction(
        self, corridor: Corridor
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            way([at(700.0, 0.0), at(760.0, 60.0)], highway="primary_link"),
        )
        assert extract.junction_points() == []

    def test_poi_nodes_are_recognised_by_any_of_their_keys(
        self, corridor: Corridor
    ) -> None:
        extract = extract_from(
            corridor,
            poi(100.0, 10.0, shop="bakery"),
            poi(200.0, 10.0, leisure="pitch"),
            poi(300.0, 10.0, barrier="gate"),
        )
        assert len(extract.poi_nodes) == 2


# ---- tags --------------------------------------------------------------------


class TestCarrierMatching:
    def test_every_sample_finds_the_road_it_sits_on(
        self, corridor: Corridor, units
    ) -> None:
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M)))
        match = match_carriers(extract, units)

        assert match.match_rate == pytest.approx(1.0)
        assert match.n_samples == pytest.approx(corridor.length_m / 10.0, rel=0.05)

    def test_a_reference_beats_proximity(self, corridor: Corridor, units) -> None:
        """A frontage road 8 m away must not lend the corridor its 30 km/h limit."""
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M), ref="B9", maxspeed="80"),
            way(run(0.0, CORRIDOR_M, north_m=8.0), highway="residential", maxspeed="30"),
        )
        match = match_carriers(extract, units, ref="B9")

        assert len(match.ways) == 1
        assert {match.ways[i].tags["maxspeed"] for i in match.way_index} == {"80"}

    def test_without_a_reference_the_nearest_road_wins(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Stated plainly because it is the failure mode of an unlabelled centreline."""
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M, north_m=15.0), maxspeed="80"),
            way(run(0.0, CORRIDOR_M, north_m=3.0), highway="residential", maxspeed="30"),
        )
        result = read_tags(extract, units, registry=shipped_registry)

        assert values_of(result, "speed_limit").eq(30.0).all()

    def test_a_centreline_off_the_road_is_called_out(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, 900.0), maxspeed="80"),
        )
        result = read_tags(extract, units, registry=shipped_registry)

        assert any("of the centreline sits within" in note for note in result.notes)


class TestTagReading:
    def test_speed_limit_is_length_weighted_along_the_unit(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Half the unit at 80 and half at 40 is 60, not whichever way came first."""
        extract = extract_from(
            corridor,
            way(run(0.0, 250.0), maxspeed="80"),
            way(run(250.0, CORRIDOR_M), maxspeed="40"),
        )
        speeds = values_of(
            read_tags(extract, units, registry=shipped_registry), "speed_limit"
        )

        assert speeds.iloc[0] == pytest.approx(60.0, abs=1.5)
        assert speeds.iloc[1] == pytest.approx(40.0)

    def test_mph_is_converted(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M), maxspeed="50 mph"))
        speeds = values_of(
            read_tags(extract, units, registry=shipped_registry), "speed_limit"
        )

        assert speeds.iloc[0] == pytest.approx(80.47, abs=0.01)

    def test_an_implicit_national_limit_reads_as_untagged(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """`maxspeed=CY:rural` is a country's default, not a sign on this road."""
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M), maxspeed="CY:rural"))
        result = read_tags(extract, units, registry=shipped_registry)

        assert "states the tag anywhere" in skip_reason(result, "speed_limit")

    def test_a_short_untagged_gap_is_carried_across_and_declared(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Six units, one untagged, five hundred metres from a tagged one.

        The first version of this module discarded the factor here. On the real
        Cyprus B9 that behaviour threw away `maxspeed` at 92% coverage and `lanes` at
        84%, and the registry's own note says losing speed_limit biases the terms that
        remain. Carrying a value 500 m and saying so is the smaller error.
        """
        extract = extract_from(
            corridor,
            way(run(0.0, 2400.0), maxspeed="80"),
            way(run(2400.0, CORRIDOR_M)),
        )
        resolved = factor_of(
            read_tags(extract, units, registry=shipped_registry), "speed_limit"
        )

        assert resolved.values.eq(80.0).all()
        assert resolved.unit_coverage.iloc[-1] == 0.0, "carried, so no coverage of its own"
        assert any("carried, not measured" in note for note in resolved.notes)

    def test_a_gap_too_wide_to_carry_drops_the_factor(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Past the fill distance a road has changed character, not just lost a tag."""
        extract = extract_from(
            corridor,
            way(run(0.0, 2400.0), maxspeed="80"),
            way(run(2400.0, CORRIDOR_M)),
        )
        result = read_tags(
            extract, units, registry=shipped_registry, max_gap_fill_m=200.0
        )

        reason = skip_reason(result, "speed_limit")
        assert "more than 200 m from any unit that does" in reason

    def test_thin_coverage_across_the_corridor_is_refused(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Every unit has some evidence, but the column would be mostly hearsay."""
        tagged = [way(run(start, start + 100.0), maxspeed="80") for start in range(0, 3000, 500)]
        untagged = [way(run(start + 100.0, start + 500.0)) for start in range(0, 3000, 500)]
        extract = extract_from(corridor, *tagged, *untagged)

        result = read_tags(extract, units, registry=shipped_registry)

        reason = skip_reason(result, "speed_limit")
        assert "below the 50% floor" in reason

    def test_an_untagged_road_is_not_an_unlit_road(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """The single most tempting wrong answer in this module.

        Reading absent `lit` as unlit manufactures a lighting effect out of how much
        attention a mapper paid, and the effect would point the way the registry
        expects, which is exactly what makes it dangerous.
        """
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M)))
        result = read_tags(extract, units, registry=shipped_registry)

        assert "lit" not in [value.factor for value in result.resolved]
        assert "nothing to measure and nothing to carry" in skip_reason(result, "lit")

    def test_lit_is_the_lit_share_of_the_tagged_part(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, 1500.0), lit="yes"),
            way(run(1500.0, CORRIDOR_M), lit="no"),
        )
        lit = values_of(read_tags(extract, units, registry=shipped_registry), "lit")

        assert lit.iloc[0] == pytest.approx(1.0)
        assert lit.iloc[-1] == pytest.approx(0.0)

    def test_paved_by_default_is_not_applied(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Routers assume an untagged primary is sealed. The iRAP weight is -1.0986.

        Being usually right is not good enough at that magnitude, so an untagged
        surface is unknown and the factor does not enter the model.
        """
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M), highway="primary"))
        result = read_tags(extract, units, registry=shipped_registry)

        assert "surface_paved" not in [value.factor for value in result.resolved]

    def test_surface_reads_the_explicit_tag(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M), surface="gravel"))
        paved = values_of(
            read_tags(extract, units, registry=shipped_registry), "surface_paved"
        )

        assert paved.eq(0.0).all()

    def test_sidewalk_reads_the_sided_tags_too(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(
            corridor, way(run(0.0, CORRIDOR_M), **{"sidewalk:left": "yes"})
        )
        values = values_of(
            read_tags(extract, units, registry=shipped_registry), "sidewalk_present"
        )

        assert values.eq(1.0).all()

    def test_lanes_outside_a_plausible_range_are_not_believed(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M), lanes="40"))
        result = read_tags(extract, units, registry=shipped_registry)

        assert "lanes" not in [value.factor for value in result.resolved]

    def test_a_corridor_with_no_road_beside_it_resolves_nothing(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor, poi(100.0, 10.0))
        result = read_tags(extract, units, registry=shipped_registry)

        assert result.resolved == []
        assert len(result.skipped) == len(TAG_SLOTS)

    def test_resolved_values_carry_the_registry_tier_and_licence(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M), maxspeed="80"))
        result = read_tags(extract, units, registry=shipped_registry)

        assert all(value.tier is Tier.A for value in result.resolved)
        assert all(value.licence is Licence.ODBL for value in result.resolved)
        assert all(value.source for value in result.resolved)


# ---- densities ---------------------------------------------------------------


class TestDensities:
    def test_a_junction_lands_in_the_unit_it_sits_in(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            way([at(700.0, 0.0), at(700.0, 200.0)], highway="residential"),
        )
        density = values_of(
            count_densities(extract, units, registry=shipped_registry),
            "junction_density",
        )

        assert density.iloc[1] == pytest.approx(1.0 / units.units[1].length_km)
        assert density.drop(density.index[1]).eq(0.0).all()

    def test_a_driveway_is_an_access_and_only_an_access(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """The double-counting trap: one feature must not raise two columns."""
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            way([at(300.0, 0.0), at(300.0, 40.0)], highway="service", service="driveway"),
        )
        result = count_densities(extract, units, registry=shipped_registry)

        assert values_of(result, "access_density").iloc[0] > 0
        assert values_of(result, "junction_density").eq(0.0).all()
        assert values_of(result, "ramp_density").eq(0.0).all()

    def test_a_slip_road_is_a_ramp_and_only_a_ramp(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M), highway="trunk"),
            way([at(2600.0, 2.0), at(2700.0, 80.0)], highway="trunk_link"),
        )
        result = count_densities(extract, units, registry=shipped_registry)

        assert values_of(result, "ramp_density").iloc[5] > 0
        assert values_of(result, "junction_density").eq(0.0).all()
        assert values_of(result, "access_density").eq(0.0).all()

    def test_a_poi_beyond_the_tolerance_is_not_roadside(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            poi(100.0, 20.0),
            poi(200.0, 400.0),
        )
        density = values_of(
            count_densities(extract, units, registry=shipped_registry), "poi_density"
        )

        assert density.iloc[0] == pytest.approx(1.0 / units.units[0].length_km)
        assert density.sum() == pytest.approx(density.iloc[0])

    def test_a_track_running_alongside_is_one_access_not_one_per_unit(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Counted at its closest approach. It is one access, however long it is."""
        extract = extract_from(
            corridor,
            way(run(0.0, CORRIDOR_M)),
            way(run(0.0, CORRIDOR_M, north_m=20.0), highway="track"),
        )
        counts = values_of(
            count_densities(extract, units, registry=shipped_registry), "access_density"
        ) * np.array([unit.length_km for unit in units])

        assert counts.sum() == pytest.approx(1.0)

    def test_nothing_mapped_is_reported_as_nothing_mapped(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        """Zero driveways per km is a claim about OSM, not about the road."""
        extract = extract_from(corridor, way(run(0.0, CORRIDOR_M)))
        result = count_densities(extract, units, registry=shipped_registry)

        access = next(v for v in result.resolved if v.factor == "access_density")
        assert access.values.eq(0.0).all()
        assert any("statement about what OSM has mapped" in note for note in access.notes)

    def test_an_empty_extract_scores_nothing_rather_than_zero(
        self, corridor: Corridor, units, shipped_registry: Registry
    ) -> None:
        extract = extract_from(corridor)
        result = count_densities(extract, units, registry=shipped_registry)

        assert result.resolved == []
        assert len(result.skipped) == len(DENSITY_SLOTS)

    def test_a_feature_beyond_tolerance_is_not_counted(self, units) -> None:
        from shapely.geometry import Point

        far = units.corridor.geometry.interpolate(1000.0)
        counts = count_per_unit(
            [Point(far.x, far.y + 90.0)], units, tolerance_m=50.0
        )
        assert counts.sum() == 0


# ---- the pipeline ------------------------------------------------------------


class TestPipelineIntegration:
    def test_the_adapters_widen_the_panel(self, shipped_registry: Registry) -> None:
        elements = [
            way(run(0.0, CORRIDOR_M), ref="B9", maxspeed="80", lanes="2", surface="asphalt"),
            way([at(700.0, 0.0), at(700.0, 200.0)], highway="residential"),
            way([at(300.0, 0.0), at(300.0, 40.0)], highway="service", service="driveway"),
            poi(320.0, 15.0),
        ]
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in run(0.0, CORRIDOR_M)],
            periods=["2024-01", "2024-02"],
            name="B9",
            ref="B9",
            osm_client=client_returning(*elements),
        )

        for column in (
            "curve_radius_min",
            "speed_limit",
            "lanes",
            "surface_paved",
            "junction_density",
            "access_density",
            "ramp_density",
            "poi_density",
        ):
            assert column in built.panel.columns

        _, report = prepare_panel(built.panel)
        assert report.n_rows == len(built.panel)

    def test_the_pipeline_stays_offline_unless_asked(self) -> None:
        """No client, no network. The whole suite depends on this being true."""
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in run(0.0, CORRIDOR_M)],
            periods=["2024-01"],
            name="B9",
        )

        assert sorted(built.factor_columns) == ["curve_density", "curve_radius_min"]
        assert built.provenance["adapter"].unique().tolist() == ["osm_geometry"]

    def test_a_failed_fetch_loses_the_osm_factors_and_nothing_else(self) -> None:
        """A busy Overpass mirror must not cost the client their crash data."""

        def failing(query: str) -> dict:
            raise CorridorError("every Overpass mirror failed — 504.")

        built = build_corridor_panel(
            [(lat, lon) for lon, lat in run(0.0, CORRIDOR_M)],
            periods=["2024-01"],
            name="B9",
            osm_client=failing,
        )

        assert "curve_radius_min" in built.panel.columns
        assert "speed_limit" not in built.panel.columns
        assert any("OSM attribute fetch failed" in note for note in built.warnings)

    def test_provenance_reaches_the_corridor_panel(self) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in run(0.0, CORRIDOR_M)],
            periods=["2024-01"],
            name="B9",
            ref="B9",
            osm_client=client_returning(
                way(run(0.0, CORRIDOR_M), ref="B9", maxspeed="80")
            ),
        )

        provenance = built.provenance
        speed = provenance.loc[provenance["column"] == "speed_limit"].iloc[0]

        assert speed["adapter"] == "osm_maxspeed"
        assert speed["tier"] == "A"
        assert speed["licence"] == "ODbL"
        assert ("median_present", "osm_divided") in [
            (factor, adapter) for factor, adapter, _ in built.skipped
        ]
