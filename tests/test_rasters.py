"""Raster-backed Tier A adapters — gradient from the DEM, roadside land use.

**No rasterio and no network here.** Both adapters take a :class:`PointSampler`, so
these tests hand them analytic surfaces: a known constant slope, a known step, a known
strip of built-up land. That is the point of the seam — the measurement decisions are
testable exactly, and the only untested code is the HTTP window read, which is exercised
against the live buckets by ``tools/validate_rasters.py`` instead.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from roadrisk.core.registry import Licence, Registry, Tier
from roadrisk.geo import build_corridor_panel
from roadrisk.geo.adapters.grade import (
    BASELINE_M,
    compute_grade,
)
from roadrisk.geo.adapters.landcover import OFFSETS_M, compute_landcover
from roadrisk.geo.adapters.rasters import (
    WORLDCOVER_BUILT_UP,
    copernicus_dem_url,
    worldcover_url,
)
from roadrisk.geo.adapters.sampling import stations_along, to_latlon
from roadrisk.geo.corridor import Corridor
from roadrisk.geo.segmentation import segment

ORIGIN_LAT = 34.90
ORIGIN_LON = 32.85

LAT_PER_M = 1.0 / 111_320.0
LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))

CORRIDOR_M = 4000.0
UNIT_M = 500.0

#: Not-built-up, so a surface that returns this everywhere gives landuse_urban = 0.
GRASSLAND = 30.0

#: The fixtures lay points out with a flat-earth metres-per-degree, while the corridor
#: measures itself in UTM. The two differ by about 0.07% here, so a surface built on
#: "fixture metres" and a gradient measured in true metres agree to three figures and
#: not to six. Every tolerance below that looks loose is this, and only this.
SCALE_SLACK = 2e-3


def at(east_m: float, north_m: float = 0.0) -> tuple[float, float]:
    return (ORIGIN_LON + east_m * LON_PER_M, ORIGIN_LAT + north_m * LAT_PER_M)


def straight(length_m: float = CORRIDOR_M, step_m: float = 50.0) -> list:
    count = int(length_m / step_m) + 1
    return [at(index * step_m) for index in range(count)]


@pytest.fixture(scope="module")
def corridor() -> Corridor:
    return Corridor.from_latlon([(lat, lon) for lon, lat in straight()], name="B9")


@pytest.fixture(scope="module")
def units(corridor: Corridor):
    return segment(corridor, target_length_m=UNIT_M)


def easting_of(latitude: float, longitude: float) -> float:
    """Roughly how far east of the origin a point is, in metres."""
    return (longitude - ORIGIN_LON) / LON_PER_M


def northing_of(latitude: float, longitude: float) -> float:
    return (latitude - ORIGIN_LAT) / LAT_PER_M


def surface(height):
    """A sampler over an analytic surface, given as f(east_m, north_m) -> value."""

    def sample(points):
        return np.array(
            [
                height(easting_of(lat, lon), northing_of(lat, lon))
                for lat, lon in points
            ],
            dtype=float,
        )

    return sample


class TestTileAddressing:
    def test_a_dem_tile_is_named_for_its_south_west_corner(self) -> None:
        url = copernicus_dem_url(34.9, 32.85)
        assert "N34_00_E032_00" in url
        assert url.endswith(".tif")

    def test_negative_degrees_floor_rather_than_truncate(self) -> None:
        """int(-0.5) is 0 and would ask for the tile north of the point."""
        assert "S01_00" in copernicus_dem_url(-0.5, 10.0)
        assert "W001" in copernicus_dem_url(10.0, -0.5)

    def test_worldcover_tiles_are_three_degrees(self) -> None:
        assert "N33E030" in worldcover_url(34.9, 32.85)
        assert "N33E033" in worldcover_url(34.9, 33.10)

    def test_worldcover_south_of_the_equator(self) -> None:
        assert "S03E030" in worldcover_url(-1.0, 31.0)


class TestStations:
    def test_stations_span_the_whole_corridor(self, units) -> None:
        stations = stations_along(units, 50.0)

        assert stations.chainages[0] == 0.0
        assert stations.chainages[-1] == pytest.approx(units.corridor.length_m)
        assert stations.counts().sum() == len(stations)

    def test_offsets_land_perpendicular_to_the_corridor(self, units) -> None:
        """The corridor runs due east, so an offset must move purely north or south."""
        chainages = np.array([1000.0])
        left = to_latlon(units, chainages, offset_m=80.0)[0]
        right = to_latlon(units, chainages, offset_m=-80.0)[0]

        assert northing_of(*left) == pytest.approx(80.0, abs=2.0)
        assert northing_of(*right) == pytest.approx(-80.0, abs=2.0)
        assert easting_of(*left) == pytest.approx(easting_of(*right), abs=2.0)


class TestGrade:
    def test_a_known_constant_slope_is_recovered(
        self, units, shipped_registry: Registry
    ) -> None:
        """A 5% ramp must read 5%, or nothing else in this module can be trusted."""
        result = compute_grade(
            units, surface(lambda e, n: 0.05 * e), registry=shipped_registry
        )
        values = result.resolved[0].values

        assert values.min() == pytest.approx(5.0, rel=SCALE_SLACK)
        assert values.max() == pytest.approx(5.0, rel=SCALE_SLACK)

    def test_flat_ground_reads_zero(self, units, shipped_registry: Registry) -> None:
        result = compute_grade(
            units, surface(lambda e, n: 120.0), registry=shipped_registry
        )
        assert result.resolved[0].values.eq(0.0).all()

    def test_grade_is_absolute(self, units, shipped_registry: Registry) -> None:
        """The registry's weight does not distinguish up from down, so nor does this."""
        up = compute_grade(units, surface(lambda e, n: 0.04 * e), registry=shipped_registry)
        down = compute_grade(
            units, surface(lambda e, n: -0.04 * e), registry=shipped_registry
        )

        assert up.resolved[0].values.equals(down.resolved[0].values)

    def test_a_hill_shows_up_in_the_unit_it_is_in(
        self, units, shipped_registry: Registry
    ) -> None:
        def hill(east_m: float, north_m: float) -> float:
            return 60.0 if east_m >= 1500.0 else 0.0

        values = compute_grade(units, surface(hill), registry=shipped_registry).resolved[
            0
        ].values

        assert values.iloc[2] > values.iloc[0]
        assert values.iloc[0] == pytest.approx(0.0)
        assert values.iloc[-1] == pytest.approx(0.0)

    def test_the_baseline_is_what_stops_dem_noise_becoming_grade(
        self, units, shipped_registry: Registry
    ) -> None:
        """The reason the module exists in this shape.

        A flat road under 2 m of independent per-pixel error must not produce a
        double-digit gradient. Over a 200 m baseline the noise lands near the stated
        floor of about 1.4 points; over 30 m it would be about nine.
        """
        rng = np.random.default_rng(11)
        noisy = surface(lambda e, n: float(rng.normal(0.0, 2.0)))

        wide = compute_grade(
            units, noisy, registry=shipped_registry, baseline_m=BASELINE_M
        ).resolved[0].values
        narrow = compute_grade(
            units,
            noisy,
            registry=shipped_registry,
            station_interval_m=15.0,
            baseline_m=30.0,
            min_baseline_m=30.0,
        ).resolved[0].values

        assert wide.mean() < 4.0
        assert narrow.mean() > 3.0 * wide.mean()

    def test_the_noise_floor_is_stated_on_every_run(
        self, units, shipped_registry: Registry
    ) -> None:
        result = compute_grade(
            units, surface(lambda e, n: 0.03 * e), registry=shipped_registry
        )
        assert any("noise floor" in note for note in result.notes)
        assert any("SURFACE model" in note for note in result.notes)

    def test_attribution_travels_with_the_values(
        self, units, shipped_registry: Registry
    ) -> None:
        """Copernicus DEM is attribution-required, not public domain."""
        result = compute_grade(
            units, surface(lambda e, n: 0.03 * e), registry=shipped_registry
        )

        assert result.resolved[0].licence is Licence.CC_BY
        assert result.resolved[0].tier is Tier.A
        assert any("ATTRIBUTION REQUIRED" in note for note in result.notes)

    def test_no_elevation_anywhere_skips_rather_than_reporting_flat(
        self, units, shipped_registry: Registry
    ) -> None:
        """Zero gradient and no data are not the same claim about a road."""
        result = compute_grade(
            units, surface(lambda e, n: float("nan")), registry=shipped_registry
        )

        assert result.resolved == []
        assert "no elevation" in result.skipped[0].reason

    def test_a_unit_with_no_elevation_skips_the_whole_factor(
        self, units, shipped_registry: Registry
    ) -> None:
        def void(east_m: float, north_m: float) -> float:
            return float("nan") if 500.0 <= east_m < 1000.0 else 0.03 * east_m

        result = compute_grade(units, surface(void), registry=shipped_registry)

        assert result.resolved == []
        assert "unit(s) have no usable elevation" in result.skipped[0].reason


class TestLandCover:
    def test_open_country_is_not_urban(self, units, shipped_registry: Registry) -> None:
        result = compute_landcover(
            units, surface(lambda e, n: GRASSLAND), registry=shipped_registry
        )
        assert result.resolved[0].values.eq(0.0).all()

    def test_built_up_roadside_is_urban(self, units, shipped_registry: Registry) -> None:
        result = compute_landcover(
            units,
            surface(lambda e, n: float(WORLDCOVER_BUILT_UP)),
            registry=shipped_registry,
        )
        assert result.resolved[0].values.eq(1.0).all()

    def test_the_centreline_itself_is_never_sampled(
        self, units, shipped_registry: Registry
    ) -> None:
        """WorldCover calls a sealed road built-up.

        Sampling the centreline would report every paved corridor as urban, so the
        adapter must read only the offsets. A surface that is built-up on the line and
        grassland beside it must therefore score zero.
        """
        def road_is_built_up(east_m: float, north_m: float) -> float:
            return float(WORLDCOVER_BUILT_UP) if abs(north_m) < 10.0 else GRASSLAND

        result = compute_landcover(
            units, surface(road_is_built_up), registry=shipped_registry
        )

        assert result.resolved[0].values.eq(0.0).all()

    def test_development_on_one_side_only_is_a_half(
        self, units, shipped_registry: Registry
    ) -> None:
        def north_side(east_m: float, north_m: float) -> float:
            return float(WORLDCOVER_BUILT_UP) if north_m > 0 else GRASSLAND

        result = compute_landcover(
            units, surface(north_side), registry=shipped_registry
        )
        assert result.resolved[0].values.eq(0.5).all()

    def test_a_town_shows_up_in_the_units_it_covers(
        self, units, shipped_registry: Registry
    ) -> None:
        """Units 4 and 5 lie wholly inside the town; unit 0 is a kilometre clear of it.

        The town edges sit at 1900 and 3100 rather than on the unit boundaries so that
        no station lands within a metre of them — see SCALE_SLACK.
        """
        def town(east_m: float, north_m: float) -> float:
            return (
                float(WORLDCOVER_BUILT_UP) if 1900.0 <= east_m < 3100.0 else GRASSLAND
            )

        values = compute_landcover(
            units, surface(town), registry=shipped_registry
        ).resolved[0].values

        assert values.iloc[0] == pytest.approx(0.0)
        assert values.iloc[4] == pytest.approx(1.0)
        assert values.iloc[5] == pytest.approx(1.0)

    def test_unclassified_pixels_leave_the_denominator_rather_than_scoring_zero(
        self, units, shipped_registry: Registry
    ) -> None:
        """WorldCover leaves permanent water blank. Water is not 'not urban'."""
        def half_missing(east_m: float, north_m: float) -> float:
            if north_m > 0:
                return float("nan")
            return float(WORLDCOVER_BUILT_UP)

        result = compute_landcover(
            units, surface(half_missing), registry=shipped_registry
        )

        assert result.resolved[0].values.eq(1.0).all()
        assert result.resolved[0].coverage == pytest.approx(0.5)

    def test_no_coverage_at_all_skips_the_factor(
        self, units, shipped_registry: Registry
    ) -> None:
        result = compute_landcover(
            units, surface(lambda e, n: float("nan")), registry=shipped_registry
        )

        assert result.resolved == []
        assert "no class anywhere" in result.skipped[0].reason

    def test_attribution_travels_with_the_values(
        self, units, shipped_registry: Registry
    ) -> None:
        result = compute_landcover(
            units, surface(lambda e, n: GRASSLAND), registry=shipped_registry
        )

        assert result.resolved[0].licence is Licence.CC_BY
        assert any("ATTRIBUTION REQUIRED" in note for note in result.notes)

    def test_both_sides_are_sampled(self) -> None:
        assert sum(1 for offset in OFFSETS_M if offset > 0) == sum(
            1 for offset in OFFSETS_M if offset < 0
        )
        assert 0.0 not in OFFSETS_M


class TestPipelineIntegration:
    def test_rasters_widen_the_panel(self) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            elevation=surface(lambda e, n: 0.04 * e),
            landcover=surface(lambda e, n: GRASSLAND),
        )

        assert "grade_pct" in built.panel.columns
        assert "landuse_urban" in built.panel.columns
        assert built.panel["grade_pct"].max() == pytest.approx(4.0, rel=SCALE_SLACK)
        assert built.panel["landuse_urban"].eq(0.0).all()

    def test_the_pipeline_stays_offline_unless_asked(self) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()], periods=["2024-01"], name="B9"
        )

        assert "grade_pct" not in built.panel.columns
        assert "landuse_urban" not in built.panel.columns

    def test_provenance_names_the_products_and_their_licences(self) -> None:
        built = build_corridor_panel(
            [(lat, lon) for lon, lat in straight()],
            periods=["2024-01"],
            name="B9",
            elevation=surface(lambda e, n: 0.04 * e),
            landcover=surface(lambda e, n: GRASSLAND),
        )
        provenance = built.provenance.set_index("column")

        assert provenance.loc["grade_pct", "adapter"] == "copernicus_dem_glo30"
        assert provenance.loc["grade_pct", "licence"] == "CC-BY-4.0"
        assert provenance.loc["landuse_urban", "adapter"] == "esa_worldcover"
        assert provenance.loc["landuse_urban", "licence"] == "CC-BY-4.0"
