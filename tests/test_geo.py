"""The geospatial pipeline: corridor, segmentation, curvature, panel, snapping."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.engine import assess
from roadrisk.core.gates import CheckStatus
from roadrisk.geo import (
    Corridor,
    CorridorError,
    GeoError,
    SegmentationError,
    SnapError,
    build_corridor_panel,
    build_skeleton,
    compute_curvature,
    segment,
)
from roadrisk.geo.crs import Projector, utm_epsg_for
from roadrisk.geo.demo import (
    monthly_periods,
    synthetic_centreline,
    synthetic_crashes,
)
from roadrisk.geo.geometry import _curve_runs, _radii
from roadrisk.geo.panel import attach_factor_values
from roadrisk.geo.snapping import apply_counts, snap_crashes


@pytest.fixture(scope="module")
def centreline() -> list[tuple[float, float]]:
    return synthetic_centreline(length_km=10.0)


@pytest.fixture(scope="module")
def corridor(centreline) -> Corridor:
    return Corridor.from_latlon(centreline, name="M1")


@pytest.fixture(scope="module")
def periods() -> list[str]:
    return monthly_periods(24)


class TestCRS:
    def test_utm_zone_selection(self) -> None:
        assert utm_epsg_for(34.9, 33.2) == 32636, "Cyprus, northern hemisphere zone 36"
        assert utm_epsg_for(-34.0, 18.4) == 32734, "Cape Town, southern hemisphere"

    def test_rejects_impossible_coordinates(self) -> None:
        with pytest.raises(CorridorError, match="latitude"):
            utm_epsg_for(120.0, 0.0)
        with pytest.raises(CorridorError, match="longitude"):
            utm_epsg_for(0.0, 200.0)

    def test_projection_round_trips(self) -> None:
        projector = Projector.for_point(34.9, 33.2)
        x, y = projector.point_to_metric(34.9, 33.2)
        latitude, longitude = projector.point_to_wgs84(x, y)

        assert latitude == pytest.approx(34.9, abs=1e-9)
        assert longitude == pytest.approx(33.2, abs=1e-9)


class TestCorridor:
    def test_length_matches_the_requested_corridor(self, corridor: Corridor) -> None:
        """A sinuous 10 km path is longer than 10 km, but not by much."""
        assert 10.0 < corridor.length_km < 12.0

    def test_chainage_runs_from_zero_to_length(self, corridor: Corridor) -> None:
        start = corridor.point_at(0.0)
        end = corridor.point_at(corridor.length_m)

        assert corridor.chainage_of(start.x, start.y) == pytest.approx(0.0, abs=0.5)
        assert corridor.chainage_of(end.x, end.y) == pytest.approx(
            corridor.length_m, abs=0.5
        )

    def test_rejects_a_single_point(self) -> None:
        with pytest.raises(CorridorError, match="at least 2 points"):
            Corridor.from_latlon([(34.9, 33.2)])

    def test_rejects_a_corridor_too_short_to_segment(self) -> None:
        with pytest.raises(CorridorError, match="below the"):
            Corridor.from_latlon([(34.9, 33.2), (34.9002, 33.2)])

    def test_rejects_points_that_collapse_to_one(self) -> None:
        repeated = [(34.9, 33.2)] * 5
        with pytest.raises(CorridorError, match="collapses to a single point"):
            Corridor.from_latlon(repeated)

    def test_chainage_outside_the_corridor_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(CorridorError, match="outside corridor"):
            corridor.point_at(corridor.length_m + 1.0)

    def test_self_intersection_is_warned_about_not_rejected(self) -> None:
        """A figure-of-eight is legal geometry but ambiguous linear referencing."""
        loop = [
            (34.900, 33.200),
            (34.910, 33.210),
            (34.900, 33.210),
            (34.910, 33.200),
        ]
        crossing = Corridor.from_latlon(loop, name="loop")

        assert crossing.self_intersecting
        assert any("crosses itself" in w for w in crossing.warnings)


class TestSegmentation:
    def test_chainage_is_continuous_and_exhaustive(self, corridor: Corridor) -> None:
        """No gaps, no overlaps — exposure depends on it."""
        units = segment(corridor, target_length_m=500.0).units

        assert units[0].start_m == 0.0
        assert units[-1].end_m == pytest.approx(corridor.length_m)
        for current, following in zip(units[:-1], units[1:], strict=True):
            assert current.end_m == pytest.approx(following.start_m)

    def test_unit_lengths_sum_to_the_corridor(self, corridor: Corridor) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        assert segmentation.total_length_km == pytest.approx(corridor.length_km)

    def test_trailing_runt_is_merged(self) -> None:
        """A 2 m final unit would carry near-zero exposure and an absurd rate."""
        line = Corridor.from_latlon(
            [(34.90, 33.20), (34.90 + 0.00904, 33.20)], name="straight"
        )
        units = segment(line, target_length_m=400.0).units

        assert all(unit.length_m >= 200.0 for unit in units)

    def test_unit_lookup_is_half_open(self, corridor: Corridor) -> None:
        """A boundary chainage must belong to exactly one unit, never two."""
        segmentation = segment(corridor, target_length_m=500.0)
        boundary = segmentation.units[0].end_m

        owner = segmentation.unit_for_chainage(boundary)
        assert owner is segmentation.units[1]
        assert not segmentation.units[0].contains_chainage(boundary)

    def test_corridor_end_still_resolves(self, corridor: Corridor) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        assert segmentation.unit_for_chainage(corridor.length_m) is segmentation.units[-1]

    def test_rejects_a_unit_longer_than_the_corridor(self, corridor: Corridor) -> None:
        with pytest.raises(SegmentationError, match="exceeds the whole corridor"):
            segment(corridor, target_length_m=corridor.length_m * 2)

    def test_rejects_a_non_positive_target(self, corridor: Corridor) -> None:
        with pytest.raises(SegmentationError, match="must be positive"):
            segment(corridor, target_length_m=0.0)

    def test_unit_ids_are_prefixed_and_ordered(self, corridor: Corridor) -> None:
        ids = segment(corridor, target_length_m=500.0).unit_ids
        assert ids[0] == "M1-0000"
        assert ids == sorted(ids)


class TestCurvatureMaths:
    """The circumradius is exact, so it can be checked against known shapes."""

    @pytest.mark.parametrize("radius", [100.0, 500.0, 900.0, 2000.0])
    def test_recovers_a_known_circle(self, radius: float) -> None:
        theta = np.linspace(0.0, np.pi / 2, 200)
        points = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])

        computed = _radii(points, max_radius_m=5000.0)

        assert computed.min() == pytest.approx(radius, rel=1e-6)
        assert computed.max() == pytest.approx(radius, rel=1e-6)

    def test_a_straight_line_caps(self) -> None:
        points = np.column_stack([np.arange(0.0, 1000.0, 20.0), np.zeros(50)])
        assert (_radii(points, max_radius_m=5000.0) >= 5000.0).all()

    def test_counts_curves_not_bendy_samples(self) -> None:
        """A long sweeping bend is one curve, not fifteen."""
        radii = np.array([2000.0] * 5 + [500.0] * 15 + [2000.0] * 5)
        assert _curve_runs(radii, 900.0) == 1

    def test_counts_separate_curves_separately(self) -> None:
        radii = np.array([2000.0, 500.0, 500.0, 2000.0, 500.0, 2000.0])
        assert _curve_runs(radii, 900.0) == 2

    def test_a_straight_has_no_curves(self) -> None:
        assert _curve_runs(np.full(20, 5000.0), 900.0) == 0


class TestCurvatureOnACorridor:
    def test_extra_vertices_do_not_change_the_answer(self) -> None:
        """The property resampling actually buys.

        Two traces of the same road, both at least as fine as the 20 m measurement
        interval, must agree. Without resampling the denser one would report tighter
        curvature purely because it has more vertices for jitter to live in.
        """
        fine = Corridor.from_latlon(
            synthetic_centreline(length_km=8.0, spacing_m=4.0), name="fine"
        )
        coarse = Corridor.from_latlon(
            synthetic_centreline(length_km=8.0, spacing_m=20.0), name="coarse"
        )

        fine_values = compute_curvature(segment(fine, target_length_m=1000.0)).values
        coarse_values = compute_curvature(segment(coarse, target_length_m=1000.0)).values

        n = min(len(fine_values), len(coarse_values))
        np.testing.assert_allclose(
            fine_values["curve_radius_min"].to_numpy()[:n],
            coarse_values["curve_radius_min"].to_numpy()[:n],
            rtol=0.15,
        )

    def test_an_under_sampled_centreline_is_detected_and_warned_about(self) -> None:
        """Resampling cannot recover bends the source never recorded.

        A line traced at 80 m through a bend has already cut the corners. Resampling
        interpolates along those chords, producing artificially sharp joints and
        curvature that reads much tighter than the real road. That must be reported,
        not silently returned.
        """
        under = Corridor.from_latlon(
            synthetic_centreline(length_km=8.0, spacing_m=80.0), name="under"
        )
        result = compute_curvature(segment(under, target_length_m=1000.0))

        assert result.under_sampled
        assert result.source_spacing_m > result.resample_interval_m
        assert any("reads TIGHTER" in note for note in result.notes)

    def test_a_well_sampled_centreline_raises_no_warning(self) -> None:
        good = Corridor.from_latlon(
            synthetic_centreline(length_km=8.0, spacing_m=10.0), name="good"
        )
        result = compute_curvature(segment(good, target_length_m=1000.0))

        assert not result.under_sampled
        assert not any("reads TIGHTER" in note for note in result.notes)

    def test_tightening_bends_show_as_falling_radius(self, corridor: Corridor) -> None:
        """The synthetic corridor's amplitude ramps, so bends tighten along it."""
        values = compute_curvature(segment(corridor, target_length_m=500.0)).values
        radii = values["curve_radius_min"].to_numpy()

        assert radii[:5].mean() > radii[-5:].mean()

    def test_capped_units_are_counted_and_explained(self) -> None:
        straight = Corridor.from_latlon(
            [(34.90, 33.20), (34.94, 33.20)], name="straight"
        )
        result = compute_curvature(segment(straight, target_length_m=500.0))

        assert result.n_units_capped == len(result.values)
        assert any("capped" in note for note in result.notes)

    def test_produces_exactly_the_registry_columns(self, corridor: Corridor) -> None:
        result = compute_curvature(segment(corridor, target_length_m=500.0))
        assert result.columns == ["curve_radius_min", "curve_density"]


class TestPanelSkeleton:
    def test_zero_crash_rows_exist_by_construction(
        self, corridor: Corridor, periods: list[str]
    ) -> None:
        """The whole point: the panel comes from geography, not from the crash table."""
        segmentation = segment(corridor, target_length_m=500.0)
        panel = build_skeleton(segmentation, periods=periods)

        assert (panel["n_crashes"] == 0).all()
        assert len(panel) == len(segmentation) * len(periods)

    def test_skeleton_satisfies_the_input_contract(
        self, corridor: Corridor, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        panel = build_skeleton(segmentation, periods=periods)

        _, report = prepare_panel(panel)
        assert report.zero_crash_rows == report.n_rows

    def test_time_slots_multiply_the_rows(
        self, corridor: Corridor, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        panel = build_skeleton(
            segmentation, periods=periods, time_slots={"day": 400.0, "night": 330.0}
        )

        assert len(panel) == len(segmentation) * len(periods) * 2
        assert set(panel["time_slot"]) == {"day", "night"}

    def test_rejects_repeated_period_labels(self, corridor: Corridor) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        with pytest.raises(GeoError, match="must be unique"):
            build_skeleton(segmentation, periods=["2024-01", "2024-01"])

    def test_rejects_zero_duration_slots(self, corridor: Corridor) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        with pytest.raises(GeoError, match="must be positive"):
            build_skeleton(segmentation, periods=["2024-01"], time_slots={"day": 0.0})

    def test_attaching_a_partial_factor_column_is_refused(
        self, corridor: Corridor, periods: list[str]
    ) -> None:
        """A gap would silently change which rows the model sees."""
        segmentation = segment(corridor, target_length_m=500.0)
        panel = build_skeleton(segmentation, periods=periods)
        partial = pd.DataFrame(
            {"unit_id": [segmentation.units[0].unit_id], "grade_pct": [3.0]}
        )

        with pytest.raises(GeoError, match="no value for some units"):
            attach_factor_values(panel, partial)


class TestSnapping:
    def test_reports_every_drop_with_a_reason(
        self, corridor: Corridor, centreline, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        crashes = synthetic_crashes(centreline, periods, n_crashes=400)

        outcome = snap_crashes(
            segmentation, crashes, periods=periods, time_slots=["all"]
        )

        assert outcome.report.n_supplied == 400
        assert outcome.report.n_dropped == sum(outcome.report.dropped_reasons.values())
        assert "beyond_tolerance" in outcome.report.dropped_reasons
        assert "missing_coordinates" in outcome.report.dropped_reasons
        assert "period_not_in_panel" in outcome.report.dropped_reasons

    def test_tolerance_controls_what_lands(
        self, corridor: Corridor, centreline, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        crashes = synthetic_crashes(centreline, periods, n_crashes=300)

        tight = snap_crashes(
            segmentation, crashes, periods=periods, time_slots=["all"], tolerance_m=5.0
        )
        loose = snap_crashes(
            segmentation, crashes, periods=periods, time_slots=["all"], tolerance_m=200.0
        )

        assert tight.n_snapped < loose.n_snapped

    def test_counts_never_exceed_what_was_supplied(
        self, corridor: Corridor, centreline, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        crashes = synthetic_crashes(centreline, periods, n_crashes=300)

        outcome = snap_crashes(
            segmentation, crashes, periods=periods, time_slots=["all"]
        )

        assert outcome.counts["n_crashes"].sum() == outcome.n_snapped
        assert outcome.n_snapped <= len(crashes)

    def test_applying_counts_preserves_the_skeleton_shape(
        self, corridor: Corridor, centreline, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        skeleton = build_skeleton(segmentation, periods=periods)
        crashes = synthetic_crashes(centreline, periods, n_crashes=300)
        outcome = snap_crashes(
            segmentation, crashes, periods=periods, time_slots=["all"]
        )

        panel = apply_counts(skeleton, outcome.counts)

        assert len(panel) == len(skeleton)
        assert panel["n_crashes"].sum() == outcome.n_snapped

    def test_missing_columns_are_named(
        self, corridor: Corridor, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        with pytest.raises(SnapError, match="latitude"):
            snap_crashes(
                segmentation,
                pd.DataFrame({"lon": [33.2], "period": ["2024-01"]}),
                periods=periods,
                time_slots=["all"],
            )

    def test_ambiguous_time_slot_is_refused(
        self, corridor: Corridor, centreline, periods: list[str]
    ) -> None:
        segmentation = segment(corridor, target_length_m=500.0)
        crashes = synthetic_crashes(centreline, periods, n_crashes=10)

        with pytest.raises(SnapError, match="must carry one"):
            snap_crashes(
                segmentation, crashes, periods=periods, time_slots=["day", "night"]
            )


@pytest.fixture(scope="module")
def built(centreline, periods):
    return build_corridor_panel(
        centreline,
        periods=periods,
        name="M1",
        crashes=synthetic_crashes(centreline, periods, n_crashes=900),
        target_length_m=500.0,
    )


class TestPipelineEndToEnd:
    def test_produces_a_contract_valid_panel(self, built) -> None:
        _, report = prepare_panel(built.panel)
        assert report.n_units == built.n_units
        assert report.zero_crash_rows > 0, "zero rows must survive to the contract"

    def test_carries_the_geometry_factors(self, built) -> None:
        assert sorted(built.factor_columns) == ["curve_density", "curve_radius_min"]
        for column in built.factor_columns:
            assert column in built.panel.columns

    def test_the_engine_accepts_it(self, built) -> None:
        result = assess(built.panel, snap=built.snap)
        assert result.has_result
        assert result.contract.n_units == built.n_units

    def test_the_snap_report_activates_check_six(self, built) -> None:
        """Check 6 is skipped when no snapping was done. Here it must actually run."""
        result = assess(built.panel, snap=built.snap)
        check = result.gates.by_number(6)

        assert check is not None
        assert check.status is not CheckStatus.SKIPPED
        assert f"{built.snap.n_snapped:,}" in check.message

    def test_curvature_reaches_the_model(self, built) -> None:
        result = assess(built.panel, snap=built.snap)
        assert "curve_radius_min" in [f.name for f in result.available_factors]

    def test_works_with_no_crash_data_at_all(self, centreline, periods) -> None:
        """Mode B needs geometry only — no crash table is a legitimate input."""
        built = build_corridor_panel(centreline, periods=periods, name="M1")

        assert built.total_crashes == 0
        assert built.snap is None
        assert built.zero_crash_rows == built.n_rows

    def test_summary_describes_the_build(self, built) -> None:
        summary = built.summary()
        assert "M1" in summary
        assert "units" in summary
        assert "zero-crash rows" in summary

    def test_the_pipeline_does_not_manufacture_signal(self, built) -> None:
        """Crashes with no true curvature effect must not produce a curvature effect.

        Found on the first real-road run. Crashes had been placed by vertex index,
        and because traced centrelines put vertices closer together through bends,
        that concentrated them in curves — producing `curve_radius_min` at p < 0.0001
        out of pure geometry. Placing crashes uniformly along distance instead, the
        coefficient collapsed to p = 0.69.

        A pipeline that invents a relationship from how a road was drawn would be
        worse than useless, so the property is pinned here.
        """
        result = assess(built.panel, snap=built.snap)

        assert result.fit is not None
        for coefficient in result.fit.coefficients:
            assert coefficient.p_value > 0.01, (
                f"{coefficient.factor} is significant at p={coefficient.p_value:.4g} "
                "on crashes that carry no curvature effect — the pipeline is "
                "manufacturing signal from geometry"
            )
