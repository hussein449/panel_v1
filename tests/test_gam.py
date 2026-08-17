"""Rung 3 — the spline must find a planted U, and must not invent one.

The second half of that sentence is the harder test and the reason most of this file
exists. A diagnostic that reports a bend whenever it is asked would "explain" every
sign reversal ever put to it, and it would be worse than having no diagnostic at all,
because its answer is the one that stops people looking.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.engine import assess
from roadrisk.core.gam import (
    ARM_SHARE,
    MIN_DISTINCT_X,
    PENALTY_GRID,
    Shape,
    ShapeCurve,
    ShapeDiagnostic,
    classify,
    hunt_shape,
)
from roadrisk.core.models.base import FitResult
from roadrisk.core.registry import Sign
from roadrisk.core.transforms import build_design
from roadrisk.demo import TRUE_EFFECTS, synthetic_panel

FACTORS = ("curve_density", "junction_density", "access_density", "speed_limit")


def _prepared(panel: pd.DataFrame, registry):
    """Everything `hunt_shape` needs, built the way the engine builds it."""
    frame, _ = prepare_panel(panel)
    factors = [f for f in registry.factors if f.column in FACTORS]
    design = build_design(frame, factors)
    return frame, design, {f.name: f for f in factors}


@pytest.fixture(scope="module")
def u_panel() -> pd.DataFrame:
    """Curvature is genuinely safest in the middle of its range here."""
    return synthetic_panel(n_units=120, n_periods=24, seed=7, u_shaped="curve_density")


@pytest.fixture(scope="module")
def u_diagnostic(u_panel: pd.DataFrame, shipped_registry):
    frame, design, factors = _prepared(u_panel, shipped_registry)
    return hunt_shape(
        factor="curve_density",
        counts=frame["n_crashes"],
        design=design,
        log_exposure=frame["log_exposure"],
        unit_ids=frame["unit_id"],
        alpha=0.6,
        expected_sign=factors["curve_density"].expected_sign,
        linear_estimate=-0.16,
        n_resamples=12,
        seed=3,
    )


@pytest.fixture(scope="module")
def linear_diagnostic(rich_panel: pd.DataFrame, shipped_registry):
    """The control: a panel whose curvature effect really is a straight line."""
    frame, design, factors = _prepared(rich_panel, shipped_registry)
    return hunt_shape(
        factor="curve_density",
        counts=frame["n_crashes"],
        design=design,
        log_exposure=frame["log_exposure"],
        unit_ids=frame["unit_id"],
        alpha=0.6,
        expected_sign=factors["curve_density"].expected_sign,
        linear_estimate=0.32,
        n_resamples=12,
        seed=3,
    )


class TestClassify:
    """The shape reader, on curves whose shape is not in question."""

    def test_a_rising_line_is_increasing(self) -> None:
        assert classify(np.linspace(-1.0, 1.0, 41)) is Shape.INCREASING

    def test_a_falling_line_is_decreasing(self) -> None:
        assert classify(np.linspace(1.0, -1.0, 41)) is Shape.DECREASING

    def test_a_bowl_is_a_u(self) -> None:
        x = np.linspace(-1.0, 1.0, 41)
        assert classify(x**2) is Shape.U_SHAPED

    def test_a_dome_is_an_inverted_u(self) -> None:
        x = np.linspace(-1.0, 1.0, 41)
        assert classify(-(x**2)) is Shape.INVERTED_U

    def test_a_flat_curve_is_flat(self) -> None:
        assert classify(np.zeros(41)) is Shape.FLAT

    def test_a_barely_sloping_curve_is_flat(self) -> None:
        """Below a tenth of a log point there is no shape worth interpreting."""
        assert classify(np.linspace(0.0, 0.05, 41)) is Shape.FLAT

    def test_two_turns_are_wavy(self) -> None:
        x = np.linspace(0.0, 2 * np.pi, 81)
        assert classify(np.sin(x)) is Shape.WAVY

    def test_a_wobble_is_not_a_turn(self) -> None:
        """A dip worth 5% of the range is noise; calling it a U manufactures findings."""
        x = np.linspace(-1.0, 1.0, 41)
        rising_with_a_dimple = x + 0.05 * np.sin(6 * x)
        assert classify(rising_with_a_dimple) is Shape.INCREASING

    def test_a_turn_against_the_very_edge_is_not_counted(self) -> None:
        """Splines are least constrained at the edges, and turn up there for free."""
        y = np.linspace(1.0, -1.0, 41)
        y[-2:] = [-0.4, 0.6]  # a sharp late upturn, inside the edge margin
        assert classify(y) is Shape.DECREASING

    def test_the_arm_share_is_what_decides(self) -> None:
        """A turn is real when both arms recover a real share of the range."""
        x = np.linspace(-1.0, 1.0, 41)
        shallow = -x + 0.5 * np.clip(x, 0, None) ** 2 * (ARM_SHARE * 0.5)
        assert classify(shallow) is not Shape.U_SHAPED


class TestFindingAPlantedU:
    """The panel's truth is known: curvature is safest in the middle."""

    def test_the_u_is_found(self, u_diagnostic: ShapeDiagnostic) -> None:
        assert u_diagnostic.available
        assert u_diagnostic.shape is Shape.U_SHAPED

    def test_the_turning_point_is_reported(self, u_diagnostic: ShapeDiagnostic) -> None:
        assert u_diagnostic.turning_point is not None
        curve = u_diagnostic.curve
        assert curve is not None
        assert curve.x[0] < u_diagnostic.turning_point < curve.x[-1]

    def test_it_explains_a_reversal(self, u_diagnostic: ShapeDiagnostic) -> None:
        """A U plus a negative coefficient against a '+' expectation is the M51 case."""
        assert u_diagnostic.explains_contradiction

    def test_the_verdict_names_the_suspect(self, u_diagnostic: ShapeDiagnostic) -> None:
        assert "composite masking" in u_diagnostic.verdict

    def test_the_shape_survives_resampling_by_unit(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        assert u_diagnostic.resamples is not None
        assert u_diagnostic.resamples.stable

    def test_every_penalty_on_the_grid_is_reported(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        assert len(u_diagnostic.penalty_shapes) == len(PENALTY_GRID)

    def test_the_drawn_curve_agrees_with_the_headline(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        """The plot and the sentence above it can never disagree."""
        assert u_diagnostic.curve is not None
        assert classify(np.asarray(u_diagnostic.curve.y)) is u_diagnostic.shape


class TestNotInventingAU:
    """The control, and the regression test for a defect this module actually had."""

    def test_a_linear_panel_reads_as_monotonic(
        self, linear_diagnostic: ShapeDiagnostic
    ) -> None:
        """Selecting the penalty by AIC alone reported an inverted U here.

        The truth is a planted linear effect of +0.25. One penalty of five drew a bend
        in the noise and AIC preferred it, so the headline is now the shape the whole
        grid agrees on. If this ever fails again, read the penalty_shapes.
        """
        assert linear_diagnostic.shape is Shape.INCREASING

    def test_it_claims_to_explain_nothing(
        self, linear_diagnostic: ShapeDiagnostic
    ) -> None:
        assert not linear_diagnostic.explains_contradiction

    def test_an_unstable_turn_is_not_offered_as_an_explanation(self) -> None:
        """Stability is required, not decorative — a turn 40% of corridors show is not
        an explanation for anything."""
        from roadrisk.core.gam import ResampleReport, _explains

        shaky = ResampleReport(n_resamples=40, n_fitted=40, n_agreeing=16)
        assert not _explains(Shape.U_SHAPED, -0.5, Sign.POSITIVE, shaky)
        firm = ResampleReport(n_resamples=40, n_fitted=40, n_agreeing=39)
        assert _explains(Shape.U_SHAPED, -0.5, Sign.POSITIVE, firm)

    def test_a_monotonic_curve_never_explains_a_reversal(self) -> None:
        from roadrisk.core.gam import _explains

        assert not _explains(Shape.DECREASING, -0.5, Sign.POSITIVE, None)


class TestRefusals:
    """It declines rather than drawing a shape it cannot support."""

    def test_a_factor_with_too_few_distinct_values_is_refused(
        self, rich_panel: pd.DataFrame, shipped_registry
    ) -> None:
        """speed_limit takes five values on this panel. Five points is not a curve."""
        frame, design, factors = _prepared(rich_panel, shipped_registry)
        result = hunt_shape(
            factor="speed_limit",
            counts=frame["n_crashes"],
            design=design,
            log_exposure=frame["log_exposure"],
            unit_ids=frame["unit_id"],
            n_resamples=0,
        )
        assert not result.available
        assert result.shape is None
        assert str(MIN_DISTINCT_X) in (result.refusal or "")

    def test_an_unknown_factor_is_refused_by_name(
        self, rich_panel: pd.DataFrame, shipped_registry
    ) -> None:
        frame, design, _ = _prepared(rich_panel, shipped_registry)
        result = hunt_shape(
            factor="not_a_column",
            counts=frame["n_crashes"],
            design=design,
            log_exposure=frame["log_exposure"],
            unit_ids=frame["unit_id"],
            n_resamples=0,
        )
        assert not result.available
        assert "not_a_column" in (result.refusal or "")

    def test_resampling_can_be_skipped(
        self, u_panel: pd.DataFrame, shipped_registry
    ) -> None:
        frame, design, factors = _prepared(u_panel, shipped_registry)
        result = hunt_shape(
            factor="curve_density",
            counts=frame["n_crashes"],
            design=design,
            log_exposure=frame["log_exposure"],
            unit_ids=frame["unit_id"],
            alpha=0.6,
            expected_sign=factors["curve_density"].expected_sign,
            linear_estimate=-0.16,
            n_resamples=0,
        )
        assert result.available
        assert result.resamples is None


class TestItCannotShipANumber:
    """The structural guarantee, asserted rather than trusted.

    The brief files the GAM as reference only, never in the client report. That is
    enforced by the type: there is nowhere on it to put a coefficient, an interval or a
    predicted count. This test fails the moment somebody adds one.
    """

    FORBIDDEN = (
        "coefficients",
        "coefficient",
        "predict",
        "predicted_counts",
        "fitted_values",
        "p_value",
        "p_values",
        "std_error",
        "ci_low",
        "ci_high",
        "confidence_interval",
    )

    def test_the_diagnostic_exposes_no_client_number(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        for name in self.FORBIDDEN:
            assert not hasattr(u_diagnostic, name), (
                f"ShapeDiagnostic grew a '{name}'. Rung 3 is a diagnostic; the moment "
                "it can express an effect size it can be quoted as one."
            )

    def test_the_serialised_form_exposes_no_client_number(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        payload = u_diagnostic.as_dict()
        for name in self.FORBIDDEN:
            assert name not in payload

    def test_it_is_not_a_fit_result(self, u_diagnostic: ShapeDiagnostic) -> None:
        assert not isinstance(u_diagnostic, FitResult)

    def test_the_linear_estimate_is_carried_not_computed(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        """It is the shipped fit's own number, passed in for comparison."""
        assert u_diagnostic.linear_estimate == -0.16


class TestThePlot:
    """The step's done-when: it produces the diagnostic plot."""

    def test_a_curve_renders(self, u_diagnostic: ShapeDiagnostic) -> None:
        assert u_diagnostic.curve is not None
        drawing = u_diagnostic.curve.render()
        assert "curve_density" in drawing
        assert "*" in drawing
        assert "partial effect" in drawing

    def test_the_plot_has_a_zero_reference(self, u_diagnostic: ShapeDiagnostic) -> None:
        assert "0.00" in u_diagnostic.curve.render()  # type: ignore[union-attr]

    def test_the_report_contains_the_plot_and_the_reading(
        self, u_diagnostic: ShapeDiagnostic
    ) -> None:
        report = u_diagnostic.report()
        assert "*" in report
        assert u_diagnostic.verdict in report

    def test_an_empty_curve_does_not_crash_the_renderer(self) -> None:
        assert "no curve" in ShapeCurve(factor="x", x=(), y=()).render()

    def test_a_curve_without_a_band_still_draws(self) -> None:
        curve = ShapeCurve(
            factor="x",
            x=tuple(np.linspace(0, 1, 21)),
            y=tuple(np.linspace(-1, 1, 21)),
        )
        assert "*" in curve.render()


@pytest.fixture(scope="module")
def reversed_result():
    """A reversal that is genuinely monotonic — the spline must not excuse it."""
    panel = synthetic_panel(
        n_units=80,
        n_periods=18,
        seed=17,
        effects={**TRUE_EFFECTS, "curve_density": -0.45},
    )
    return assess(panel, max_leave_one_out=3, shape_resamples=8)


class TestTheSignGuardRunsIt:
    """A contradiction gets the spline without anybody asking."""

    def test_a_contradiction_carries_a_shape(self, reversed_result) -> None:
        contradiction = reversed_result.sign_guard.contradictions[0]
        assert contradiction.shape is not None

    def test_a_genuinely_monotonic_reversal_is_not_blamed_on_shape(
        self, reversed_result
    ) -> None:
        """This panel's reversal is real and linear — the spline must not excuse it."""
        contradiction = reversed_result.sign_guard.contradictions[0]
        assert contradiction.shape.shape is Shape.DECREASING
        assert not contradiction.shape.explains_contradiction
        assert reversed_result.sign_guard.explained_by_shape == []

    def test_the_verdict_hands_the_question_back(self, reversed_result) -> None:
        verdict = reversed_result.sign_guard.contradictions[0].shape.verdict
        assert "Shape is not the explanation" in verdict

    def test_a_clean_run_fits_no_splines(self, rich_panel: pd.DataFrame) -> None:
        """The expensive diagnostics run only where there is something to explain."""
        result = assess(rich_panel)
        assert result.sign_guard.clean
        assert all(f.shape is None for f in result.sign_guard.findings)

    def test_the_shape_reaches_the_serialised_payload(self, reversed_result) -> None:
        findings = reversed_result.as_dict()["sign_guard"]["findings"]
        contradicting = [f for f in findings if f["contradicts"]]
        assert contradicting[0]["shape"]["shape"] == Shape.DECREASING.value


class TestAskingForItEarly:
    """The brief says run it early — before there is a reversal to explain."""

    def test_a_requested_factor_is_fitted(self, rich_panel: pd.DataFrame) -> None:
        result = assess(
            rich_panel, shape_factors=["curve_density"], shape_resamples=8
        )
        assert [s.factor for s in result.shapes] == ["curve_density"]
        assert result.shapes[0].available

    def test_a_factor_that_was_never_fitted_is_reported_not_ignored(
        self, rich_panel: pd.DataFrame
    ) -> None:
        result = assess(rich_panel, shape_factors=["nonsense"], shape_resamples=0)
        assert result.shapes == []
        assert any(e.code == "shape_factor_not_fitted" for e in result.log.events)

    def test_shapes_serialise_under_reference(self, rich_panel: pd.DataFrame) -> None:
        """Never under 'fit'. The payload says what it is before a consumer guesses."""
        result = assess(
            rich_panel, shape_factors=["curve_density"], shape_resamples=0
        )
        payload = result.as_dict()
        assert len(payload["reference"]["shapes"]) == 1
        assert "shapes" not in payload["fit"]

    def test_asking_for_a_contradicting_factor_reuses_the_guards_fit(self) -> None:
        """Two splines on one factor could disagree. There is only ever one."""
        panel = synthetic_panel(
            n_units=80,
            n_periods=18,
            seed=17,
            effects={**TRUE_EFFECTS, "curve_density": -0.45},
        )
        result = assess(
            panel,
            max_leave_one_out=3,
            shape_factors=["curve_density"],
            shape_resamples=8,
        )
        assert len(result.shapes) == 1
        assert result.shapes[0] is result.sign_guard.contradictions[0].shape


class TestTheFixture:
    """The planted U has to be genuinely there, or none of the above means anything."""

    def test_the_bowl_reverses_the_linear_coefficient(
        self, u_panel: pd.DataFrame
    ) -> None:
        """Curvature declares '+'; forced through a linear term it comes back '-'."""
        result = assess(u_panel, shape_resamples=8)
        coefficient = result.fit.coefficient("curve_density")
        assert coefficient is not None
        assert coefficient.estimate < 0

    def test_the_reversal_is_caught_without_needing_to_be_significant(
        self, u_panel: pd.DataFrame
    ) -> None:
        """Step 3.1 takes this reversal's significance away, and 3.2 still fires.

        Naively the coefficient is p < 0.001; clustered by unit it is p = 0.16. Both
        rungs are behaving: 120 units cannot resolve this effect, and saying so is what
        3.1 is for. The sign guard keys on the *sign*, not on significance, so the
        spline still runs — which is right. A wrong sign that cannot be dismissed as
        noise and cannot be confirmed either is exactly when knowing the shape helps.
        """
        result = assess(u_panel, shape_resamples=8)
        coefficient = result.fit.coefficient("curve_density")
        assert not coefficient.significant
        assert result.fit.cluster_widening["curve_density"] > 1.5
        assert [f.factor for f in result.sign_guard.contradictions] == ["curve_density"]

    def test_an_ordinary_panel_keeps_its_sign(self, rich_panel: pd.DataFrame) -> None:
        result = assess(rich_panel)
        assert result.fit.coefficient("curve_density").estimate > 0

    def test_planting_a_shape_on_an_unknown_factor_is_refused(self) -> None:
        with pytest.raises(KeyError, match="not one of the factors"):
            synthetic_panel(n_units=30, n_periods=6, u_shaped="no_such_factor")
