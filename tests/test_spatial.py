"""Step 3.3c — a CAR field over the corridor chain.

The pair that matters, again: a corridor whose segments genuinely cluster must be told
so, and one whose segments do not must not be told they do. A spatial model that always
finds spatial structure has found nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.engine import assess
from roadrisk.core.models import Estimator
from roadrisk.core.models.spatial import (
    RHO_UNINFORMATIVE_WIDTH,
    chain_structure,
    fit_spatial_glmm,
)
from roadrisk.core.registry import load_registry
from roadrisk.core.transforms import build_design
from roadrisk.demo import synthetic_panel

NARROW = [
    "unit_id",
    "period",
    "time_slot",
    "n_crashes",
    "length_km",
    "duration_hours",
    "curve_density",
    "junction_density",
]

PLANTED_RHO = 0.9


def _fit(panel: pd.DataFrame):
    frame, _ = prepare_panel(panel)
    design = build_design(frame, load_registry().available(frame.columns))
    return fit_spatial_glmm(
        frame["n_crashes"],
        design,
        frame["log_exposure"],
        frame["unit_id"],
        seed=3,
    )


@pytest.fixture(scope="module")
def clustered():
    """Neighbouring segments genuinely share their character."""
    return _fit(
        synthetic_panel(
            n_units=80, n_periods=12, seed=5, spatial_rho=PLANTED_RHO
        )[NARROW]
    )


@pytest.fixture(scope="module")
def scattered():
    """Segment character drawn independently — no spatial structure to find."""
    return _fit(
        synthetic_panel(n_units=80, n_periods=12, seed=5, spatial_rho=0.0)[NARROW]
    )


class TestTheChain:
    """A corridor is a path graph, and that is what makes this affordable."""

    def test_the_ends_have_one_neighbour_and_the_middle_two(self) -> None:
        banded = chain_structure(6)
        assert banded[1, 0] == 1.0
        assert banded[1, -1] == 1.0
        assert list(banded[1, 1:-1]) == [2.0, 2.0, 2.0, 2.0]

    def test_neighbours_are_linked_and_nothing_else_is(self) -> None:
        banded = chain_structure(6)
        assert list(banded[0, 1:]) == [-1.0] * 5
        assert banded.shape == (2, 6), "tridiagonal, which is why this is O(units)"

    def test_each_row_sums_to_zero(self) -> None:
        """The defining property of an ICAR structure matrix."""
        n = 7
        banded = chain_structure(n)
        dense = np.diag(banded[1]) + np.diag(banded[0, 1:], 1) + np.diag(banded[0, 1:], -1)
        assert np.allclose(dense.sum(axis=1), 0.0)


class TestItFindsClusteringOnlyWhenThereIsSome:
    def test_a_clustered_corridor_is_reported_as_clustered(self, clustered) -> None:
        fit, report = clustered
        assert fit.converged
        assert report is not None
        assert report.identified
        assert report.spatial, f"rho came back {report.rho.mean:.2f}"

    def test_the_planted_value_is_inside_the_interval(self, clustered) -> None:
        _, report = clustered
        assert report.rho.hdi_low <= PLANTED_RHO <= report.rho.hdi_high

    def test_a_scattered_corridor_is_not(self, scattered) -> None:
        """The half that stops this from being a machine for finding what it looks for."""
        fit, report = scattered
        assert fit.converged
        assert report is not None
        assert not report.spatial, (
            f"invented spatial structure where none was planted: rho "
            f"{report.rho.mean:.2f} [{report.rho.hdi_low:.2f}, {report.rho.hdi_high:.2f}]"
        )

    def test_the_verdicts_read_differently(self, clustered, scattered) -> None:
        assert "correlated beyond" in clustered[1].describe()
        assert "no spatial clustering" in scattered[1].describe()


class TestItNestsTheIndependentModel:
    """rho = 0 is rung 2 exactly, which is why the generalisation is safe."""

    def test_the_coefficients_agree_with_the_independent_fit(self, scattered) -> None:
        from roadrisk.core.models.bayes import fit_bayesian_glmm

        panel = synthetic_panel(n_units=80, n_periods=12, seed=5, spatial_rho=0.0)[NARROW]
        frame, _ = prepare_panel(panel)
        design = build_design(frame, load_registry().available(frame.columns))
        independent = fit_bayesian_glmm(
            frame["n_crashes"],
            design,
            frame["log_exposure"],
            frame["unit_id"],
            allow_mcmc=False,
            seed=3,
        )
        spatial_fit, _ = scattered
        assert independent.converged and spatial_fit.converged
        for coefficient in spatial_fit.coefficients:
            other = independent.coefficient(coefficient.name)
            assert other is not None
            # Same data, same model family, and rho near zero — the estimates should
            # sit comfortably inside each other's intervals.
            assert other.hdi_low - 0.2 <= coefficient.mean <= other.hdi_high + 0.2

    def test_it_still_reports_the_between_segment_spread(self, clustered) -> None:
        fit, _ = clustered
        assert fit.sigma_u is not None
        assert fit.sigma_u.mean > 0

    def test_it_carries_no_p_value(self, clustered) -> None:
        fit, _ = clustered
        assert "p_value" not in str(fit.as_dict())


class TestItRefusesRatherThanGuesses:
    def test_a_chain_too_short_for_neighbours_is_declined(self) -> None:
        panel = synthetic_panel(n_units=6, n_periods=12, seed=5)[NARROW]
        fit, report = _fit(panel)
        assert not fit.converged
        assert report is None
        assert "neighbours" in (fit.failure_reason or "")

    def test_an_unidentified_rho_says_the_corridor_cannot_tell(self) -> None:
        """Wide is an answer about the road, not a failure of the fit."""
        from roadrisk.core.models.bayes import PosteriorSummary
        from roadrisk.core.models.spatial import SpatialReport

        wide = PosteriorSummary(
            name="rho", mean=0.5, sd=0.3, hdi_low=0.02, hdi_high=0.98, prob_positive=1.0
        )
        report = SpatialReport(rho=wide, sigma_u=wide, n_units=40)
        assert not report.identified
        assert not report.spatial
        assert "cannot tell" in report.describe()
        assert (wide.hdi_high - wide.hdi_low) > RHO_UNINFORMATIVE_WIDTH


class TestTheEngineWiring:
    def test_it_is_off_by_default(self) -> None:
        panel = synthetic_panel(n_units=40, n_periods=12, seed=5)[NARROW]
        result = assess(panel, estimator=Estimator.BAYES)
        assert result.spatial is None
        assert result.posterior_spatial is None

    def test_asking_for_it_produces_a_report(self) -> None:
        panel = synthetic_panel(
            n_units=80, n_periods=12, seed=5, spatial_rho=PLANTED_RHO
        )[NARROW]
        result = assess(panel, estimator=Estimator.BAYES, use_spatial=True)
        assert result.posterior_spatial is not None
        assert result.spatial is not None
        payload = result.as_dict()
        assert payload["spatial"] is not None
        assert "rho" in payload["spatial"]  # type: ignore[operator]

    def test_a_short_corridor_admits_it_cannot_tell(self) -> None:
        """The caveat, measured rather than predicted.

        Forty units carrying a planted rho of 0.9 come back at 0.44 with an interval
        spanning most of the unit line. The spatial and independent parts of the field
        explain the same variance and there is not enough road to separate them — so the
        report says so instead of reporting 0.44 as a finding.
        """
        panel = synthetic_panel(
            n_units=40, n_periods=12, seed=5, spatial_rho=PLANTED_RHO
        )[NARROW]
        result = assess(panel, estimator=Estimator.BAYES, use_spatial=True)
        assert result.spatial is not None
        assert not result.spatial.identified
        assert not result.spatial.spatial
        assert "cannot tell" in result.spatial.describe()

    def test_it_does_not_disturb_the_mode_or_the_rung(self) -> None:
        panel = synthetic_panel(n_units=40, n_periods=12, seed=5)[NARROW]
        plain = assess(panel)
        spatial = assess(panel, estimator=Estimator.BAYES, use_spatial=True)
        assert plain.mode is spatial.mode
        assert plain.rung is spatial.rung
        assert plain.factor_names == spatial.factor_names
