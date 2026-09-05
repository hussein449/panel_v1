"""Step 3.4 — does the model predict road it has not seen, and where is it wrong?

The two tests that matter most are a matched pair: a correctly specified panel must come
back clean, and a panel with a planted defect must come back flagged. A diagnostic that
only ever fires is as useless as one that never does, and the first version of the CURE
bounds here failed the first half — it condemned a correctly specified model on 60% of
one factor's range because it assumed residuals within a segment were independent.
"""

from __future__ import annotations

import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.engine import assess
from roadrisk.core.models import fit_negative_binomial
from roadrisk.core.registry import load_registry
from roadrisk.core.transforms import build_design
from roadrisk.core.validation import (
    CALIBRATION_TOLERANCE,
    CURE_TOLERANCE,
    MIN_UNITS,
    CureCurve,
    validate,
)
from roadrisk.demo import synthetic_panel

FACTORS = ["speed_limit", "curve_density", "junction_density", "grade_pct"]


def _pieces(panel: pd.DataFrame):
    frame, _ = prepare_panel(panel)
    design = build_design(frame, load_registry().available(frame.columns))[FACTORS]
    fit = fit_negative_binomial(frame["n_crashes"], design, frame["log_exposure"])
    return frame, design, fit


def _validate(panel: pd.DataFrame):
    frame, design, fit = _pieces(panel)
    return validate(
        counts=frame["n_crashes"],
        design=design,
        log_exposure=frame["log_exposure"],
        unit_ids=frame["unit_id"],
        alpha=fit.alpha,
    )


@pytest.fixture(scope="module")
def clean_report():
    """A panel whose effects are planted linear — the model is correctly specified."""
    return _validate(synthetic_panel(n_units=80, n_periods=18, seed=7))


@pytest.fixture(scope="module")
def broken_report():
    """The same panel with a genuine U-shape the linear model cannot represent."""
    return _validate(
        synthetic_panel(n_units=80, n_periods=18, seed=7, u_shaped="curve_density")
    )


class TestItRunsAndCalibrates:
    def test_it_produces_both_schemes(self, clean_report) -> None:
        assert clean_report.available
        assert clean_report.spatial is not None
        assert clean_report.random is not None

    def test_held_out_predictions_are_calibrated(self, clean_report) -> None:
        """The corridor's own generator, so the model should land near the truth."""
        assert clean_report.spatial.calibrated
        assert abs(clean_report.spatial.factor - 1.0) <= CALIBRATION_TOLERANCE

    def test_the_folds_are_contiguous_stretches(self, clean_report) -> None:
        assert clean_report.spatial.scheme == "contiguous stretches"
        assert clean_report.spatial.n_folds >= 2

    def test_every_unit_is_held_out_exactly_once(self, clean_report) -> None:
        held = sum(f.n_units for f in clean_report.spatial.folds)
        assert held == clean_report.n_units

    def test_the_optimism_of_random_folds_is_measured(self, clean_report) -> None:
        """Reported rather than asserted — the point of computing both."""
        assert clean_report.optimism is not None


class TestCureFindsMisspecificationAndOnlyThat:
    """The matched pair. Both halves are load-bearing."""

    def test_a_correct_model_comes_back_clean(self, clean_report) -> None:
        """The regression that the design-effect correction exists for.

        Before it, this panel — whose effects are planted linear — reported 16-60% of
        several factors outside their bounds, because residuals within a segment are
        correlated and the textbook band assumes they are not.
        """
        assert not clean_report.drifting_factors, (
            "a correctly specified panel must not be condemned: "
            f"{[(c.factor, c.share_outside) for c in clean_report.drifting_factors]}"
        )
        assert clean_report.passed

    def test_a_planted_u_shape_is_caught(self, broken_report) -> None:
        drifting = {c.factor for c in broken_report.drifting_factors}
        assert "curve_density" in drifting
        assert not broken_report.passed

    def test_it_names_the_guilty_factor_and_not_the_others(self, broken_report) -> None:
        """A diagnostic that flags everything points at nothing."""
        drifting = {c.factor for c in broken_report.drifting_factors}
        assert drifting == {"curve_density"}

    def test_it_says_where_on_the_range(self, broken_report) -> None:
        curve = next(
            c for c in broken_report.cure if c.factor == "curve_density"
        )
        assert curve.worst_x is not None
        assert "rung 3 spline" in curve.describe()

    def test_the_plot_draws(self, broken_report) -> None:
        curve = next(c for c in broken_report.cure if c.factor == "curve_density")
        plot = curve.render()
        assert "cumulative residual" in plot
        assert "#" in plot, "the breach markers should appear on a drifting curve"


class TestTiedValues:
    """CURE sorts by the covariate, and tied values can be summed in any order.

    A stable sort leaves them in the order they arrived — corridor order — so a block of
    tied units accumulates the *spatial* correlation of the residuals and the curve
    leaves its band for a reason that has nothing to do with the factor being plotted.
    On the A3 through Paris that reported 43% and 38% outside for two factors tied
    across 28 of 37 units, and called the model mis-specified; the median over 2,000
    equally valid tie orders was 2.7% for both.
    """

    def tied_panel(self, share: float) -> pd.DataFrame:
        """A correctly specified panel, with `junction_density` tied across `share`."""
        panel = synthetic_panel(n_units=80, n_periods=18, seed=7, unit_dispersion=0.5)
        units = sorted(panel["unit_id"].unique())
        flat = set(units[: int(len(units) * share)])
        panel.loc[panel["unit_id"].isin(flat), "junction_density"] = 0.0
        return panel

    def curve(self, report, factor: str):
        return next(c for c in report.cure if c.factor == factor)

    def test_an_untied_factor_has_a_single_ordering(self, clean_report) -> None:
        """No ties, no sample: the statistic is exact and the interval collapses."""
        curve = self.curve(clean_report, "grade_pct")

        assert curve.share_outside_low == curve.share_outside
        assert curve.share_outside_high == curve.share_outside
        assert not curve.tie_sensitive

    def test_a_tied_factor_reports_the_spread_it_has(self) -> None:
        report = _validate(self.tied_panel(0.75))
        curve = self.curve(report, "junction_density")

        assert curve.share_outside_low < curve.share_outside_high
        assert curve.share_outside_low <= curve.share_outside <= curve.share_outside_high

    def test_heavy_ties_do_not_condemn_a_correctly_specified_model(self) -> None:
        """The A3 regression. The panel below has no defect planted in it at all."""
        report = _validate(self.tied_panel(0.75))

        assert not self.curve(report, "junction_density").drifts

    def test_a_planted_defect_still_survives_the_tie_sample(self, broken_report) -> None:
        """Averaging over orderings must not blunt the diagnostic into uselessness."""
        assert self.curve(broken_report, "curve_density").drifts

    def test_the_same_panel_gives_the_same_answer_twice(self) -> None:
        """The seed is fixed because a run's manifest fingerprints its results."""
        panel = self.tied_panel(0.75)
        first = self.curve(_validate(panel.copy()), "junction_density")
        second = self.curve(_validate(panel.copy()), "junction_density")

        assert first.share_outside == second.share_outside
        assert first.share_outside_high == second.share_outside_high

    def test_a_straddling_interval_is_called_out(self) -> None:
        curve = CureCurve(
            factor="speed_limit",
            x=(0.0, 1.0),
            cumulative=(0.0, 0.0),
            bound=(1.0, 1.0),
            share_outside=0.08,
            share_outside_low=0.05,
            share_outside_high=CURE_TOLERANCE + 0.02,
        )
        assert curve.tie_sensitive

    def test_the_spread_reaches_the_description(self) -> None:
        curve = CureCurve(
            factor="junction_density",
            x=(0.0, 1.0),
            cumulative=(9.0, 9.0),
            bound=(1.0, 1.0),
            share_outside=0.5,
            share_outside_low=0.1,
            share_outside_high=0.6,
        )
        assert "tied values permit" in curve.describe()

    def test_the_spread_reaches_the_payload(self) -> None:
        payload = _validate(self.tied_panel(0.75)).as_dict()
        entry = next(
            c for c in payload["cure"] if c["factor"] == "junction_density"
        )

        assert "share_outside_low" in entry
        assert "share_outside_high" in entry


class TestTheDesignEffect:
    """Residuals within one segment are correlated. The bounds have to know."""

    def test_independent_rows_need_little_correction(self) -> None:
        report = _validate(
            synthetic_panel(n_units=80, n_periods=18, seed=7, unit_dispersion=0.0)
        )
        assert report.design_effect < 2.5

    def test_persistent_segment_character_needs_a_lot(self) -> None:
        report = _validate(
            synthetic_panel(n_units=80, n_periods=18, seed=7, unit_dispersion=0.5)
        )
        assert report.design_effect > 3.0

    def test_the_correction_is_reported_not_silent(self) -> None:
        report = _validate(
            synthetic_panel(n_units=80, n_periods=18, seed=7, unit_dispersion=0.5)
        )
        assert any("design effect" in note for note in report.notes)

    def test_it_never_narrows_the_bounds(self) -> None:
        """Only ever a widening. A design effect below one would be a bug."""
        for dispersion in (0.0, 0.5):
            report = _validate(
                synthetic_panel(
                    n_units=80, n_periods=18, seed=7, unit_dispersion=dispersion
                )
            )
            assert report.design_effect >= 1.0


class TestItRefusesRatherThanGuesses:
    def test_a_short_corridor_is_declined_with_a_reason(self) -> None:
        report = _validate(synthetic_panel(n_units=12, n_periods=18, seed=7))
        assert not report.available
        assert report.refusal
        assert str(MIN_UNITS) in report.refusal
        assert "predicts road it has not seen" in report.refusal

    def test_refusing_does_not_retract_the_fit(self) -> None:
        """The absence of validation is not a failure of the model above it."""
        report = _validate(synthetic_panel(n_units=12, n_periods=18, seed=7))
        assert "Nothing above is retracted" not in (report.refusal or "")
        assert not report.passed

    def test_the_thresholds_are_sane(self) -> None:
        assert 0.0 < CURE_TOLERANCE < 1.0
        assert 0.0 < CALIBRATION_TOLERANCE < 1.0


class TestReportedByDefault:
    """No flag turns this on. That is the step's own done-when."""

    @staticmethod
    def _assessment():
        return assess(synthetic_panel(n_units=80, n_periods=18, seed=7))

    def test_it_runs_without_being_asked(self) -> None:
        result = self._assessment()
        assert result.validation is not None
        assert result.validation.available

    def test_there_is_no_flag_to_disable_it(self) -> None:
        import inspect

        parameters = inspect.signature(assess).parameters
        assert not {"validate", "skip_validation", "no_validation"} & set(parameters)

    def test_it_reaches_the_serialised_payload(self) -> None:
        payload = self._assessment().as_dict()
        assert payload["validation"] is not None
        assert payload["validation"]["spatial"] is not None  # type: ignore[index]
        assert "design_effect" in payload["validation"]  # type: ignore[operator]

    def test_a_failure_is_logged_as_a_flag_not_a_note(self) -> None:
        """Reported by default *including when bad* — so it cannot be scrolled past."""
        result = assess(
            synthetic_panel(
                n_units=80, n_periods=18, seed=7, u_shaped="curve_density"
            )
        )
        assert result.validation is not None
        assert not result.validation.passed
        assert any(e.code == "cure_drift" for e in result.log.events)

    def test_a_small_corridor_says_so_in_the_log(self) -> None:
        result = assess(synthetic_panel(n_units=12, n_periods=18, seed=7))
        assert result.validation is not None
        assert not result.validation.available
        assert any(e.code == "not_validated" for e in result.log.events)
