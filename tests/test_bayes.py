"""The Bayesian rung: credible intervals, and gates that refuse rather than guess.

Every fit here is deliberately narrow and short. The inference ladder's first rung
costs seconds; its second costs minutes, and a test suite that waits for MCMC is a test
suite nobody runs. The slow path is exercised once, by
``tools/validate_posterior.py``, against a long reference run.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import prepare_panel
from roadrisk.core.engine import assess
from roadrisk.core.models import Estimator
from roadrisk.core.models.base import FitResult
from roadrisk.core.models.bayes import (
    ESS_THRESHOLD,
    KHAT_THRESHOLD,
    ApproximationReport,
    Method,
    PosteriorSummary,
    _pareto_k,
    effective_sample_size,
    fit_bayesian_glmm,
    split_r_hat,
)
from roadrisk.core.registry import load_registry
from roadrisk.core.transforms import build_design
from roadrisk.demo import synthetic_panel

#: Three factors, so the posterior is six-dimensional and the Laplace rung wins. The
#: measured boundary is around nine dimensions — see the module docstring.
NARROW = [
    "unit_id",
    "period",
    "time_slot",
    "n_crashes",
    "length_km",
    "duration_hours",
    "curve_density",
    "junction_density",
    "speed_limit",
]

PLANTED_SIGMA = 0.5


@pytest.fixture(scope="module")
def narrow_panel() -> pd.DataFrame:
    return synthetic_panel(
        n_units=40, n_periods=12, seed=7, unit_dispersion=PLANTED_SIGMA
    )[NARROW]


@pytest.fixture(scope="module")
def posterior(narrow_panel: pd.DataFrame):
    frame, _ = prepare_panel(narrow_panel)
    registry = load_registry()
    design = build_design(frame, registry.available(frame.columns))
    return fit_bayesian_glmm(
        frame["n_crashes"],
        design,
        frame["log_exposure"],
        frame["unit_id"],
        allow_mcmc=False,
        seed=3,
    )


class TestTheFastRungWins:
    """Step 1 should answer almost every real corridor, in seconds."""

    def test_it_converges(self, posterior) -> None:
        assert posterior.converged
        assert posterior.method is Method.LAPLACE

    def test_the_importance_check_passed_on_both_gates(self, posterior) -> None:
        report = posterior.approximation
        assert report is not None
        assert report.k_hat <= KHAT_THRESHOLD
        assert report.effective_draws >= ESS_THRESHOLD

    def test_the_descent_is_recorded(self, posterior) -> None:
        """The receipt pattern: a reader sees which rung answered and why."""
        assert len(posterior.descent) == 1
        assert "Laplace" in posterior.descent[0]

    def test_no_mcmc_diagnostics_are_invented(self, posterior) -> None:
        """R-hat is meaningless without chains, so it is absent rather than faked."""
        assert posterior.convergence is None
        assert all(c.r_hat is None for c in posterior.coefficients)


class TestItRecoversPlantedTruth:
    """The panel's parameters are planted, so the posterior has a right answer."""

    def test_the_between_segment_spread_is_recovered(self, posterior) -> None:
        """sigma_u is the quantity rungs 1 and 2 could not estimate at all."""
        assert posterior.sigma_u is not None
        assert posterior.sigma_u.hdi_low <= PLANTED_SIGMA <= posterior.sigma_u.hdi_high

    def test_the_dispersion_is_in_the_statsmodels_convention(self, posterior) -> None:
        """var = mu + alpha*mu^2, not the reciprocal several libraries use.

        The panel is generated with alpha = 0.6. Under the reciprocal convention the
        same fit would report about 1.67, so this test fails loudly if the two are ever
        mixed — which is the failure mode that produces a plausible-looking dispersion
        wrong by a factor of alpha squared.
        """
        assert posterior.alpha is not None
        assert 0.3 < posterior.alpha.mean < 1.2

    def test_every_interval_is_ordered(self, posterior) -> None:
        for summary in posterior.coefficients:
            assert summary.hdi_low < summary.mean < summary.hdi_high


class TestItCannotReportAPValue:
    """Credible intervals replace p-values. The type is where that is enforced."""

    FORBIDDEN = (
        "p_value",
        "p_values",
        "std_error",
        "z_value",
        "significant",
        "ci_low",
        "ci_high",
        "pvalue",
    )

    def test_the_summary_has_no_frequentist_field(self, posterior) -> None:
        for name in self.FORBIDDEN:
            assert not hasattr(posterior.coefficients[0], name), (
                f"PosteriorSummary grew a '{name}'. The whole point of this rung is "
                "that those quantities do not exist here."
            )

    def test_the_serialised_form_has_no_p_value(self, posterior) -> None:
        payload = posterior.as_dict()
        assert "p_value" not in str(payload)

    def test_it_is_not_a_frequentist_fit(self, posterior) -> None:
        assert not isinstance(posterior, FitResult)

    def test_probability_of_sign_replaces_significance(self) -> None:
        summary = PosteriorSummary(
            name="x", mean=0.4, sd=0.2, hdi_low=0.02, hdi_high=0.78, prob_positive=0.97
        )
        assert summary.probability_of_sign(1) == pytest.approx(0.97)
        assert summary.probability_of_sign(-1) == pytest.approx(0.03)
        assert summary.excludes_zero


class TestTheGatesRefuse:
    """A number nobody can vouch for is not reported."""

    def test_both_gates_are_required(self) -> None:
        """k-hat says the shape was right; effective draws say the tail was measured."""
        thin_tail = ApproximationReport(
            k_hat=0.95, n_draws=8000, effective_draws=5000, log_evidence=0.0
        )
        too_few = ApproximationReport(
            k_hat=0.2, n_draws=8000, effective_draws=12, log_evidence=0.0
        )
        good = ApproximationReport(
            k_hat=0.2, n_draws=8000, effective_draws=5000, log_evidence=0.0
        )
        assert not thin_tail.trustworthy
        assert not too_few.trustworthy
        assert good.trustworthy

    def test_a_refusal_names_the_gate_that_failed(self) -> None:
        report = ApproximationReport(
            k_hat=0.2, n_draws=8000, effective_draws=12, log_evidence=0.0
        )
        assert "survived re-weighting" in report.describe()

    def test_refusing_reports_nothing(self, narrow_panel: pd.DataFrame) -> None:
        """When no rung can be believed, the summaries are empty, not approximate."""
        frame, _ = prepare_panel(narrow_panel)
        design = build_design(frame, load_registry().available(frame.columns))
        # One draw cannot support any interval, so both gates must fail.
        from roadrisk.core.models import bayes

        original = bayes.IS_DRAWS
        bayes.IS_DRAWS = 12
        try:
            result = fit_bayesian_glmm(
                frame["n_crashes"],
                design,
                frame["log_exposure"],
                frame["unit_id"],
                allow_mcmc=False,
                seed=3,
            )
        finally:
            bayes.IS_DRAWS = original

        assert not result.converged
        assert result.method is Method.NONE
        assert result.coefficients == []
        assert result.failure_reason


class TestParetoK:
    """The honesty meter itself."""

    def test_a_matched_proposal_scores_low(self) -> None:
        rng = np.random.default_rng(0)
        _, k = _pareto_k(rng.normal(0.0, 0.05, 4000))
        assert k < KHAT_THRESHOLD

    def test_a_badly_mismatched_proposal_scores_high(self) -> None:
        """A few draws carrying everything is exactly what k-hat exists to catch."""
        rng = np.random.default_rng(0)
        heavy = rng.standard_t(1, 4000) * 4.0
        _, k = _pareto_k(heavy)
        assert k > KHAT_THRESHOLD


class TestDiagnostics:
    """Hand-rolled so `core` keeps its two dependencies. Checked against ArviZ."""

    def test_r_hat_is_one_for_well_mixed_chains(self) -> None:
        rng = np.random.default_rng(0)
        assert split_r_hat(rng.normal(size=(2000, 6))) == pytest.approx(1.0, abs=0.01)

    def test_r_hat_catches_chains_that_disagree(self) -> None:
        rng = np.random.default_rng(0)
        offset = rng.normal(size=(2000, 6)) + np.arange(6) * 2.0
        assert split_r_hat(offset) > 1.5

    def test_ess_is_near_the_draw_count_when_independent(self) -> None:
        rng = np.random.default_rng(0)
        draws = rng.normal(size=(2000, 6))
        assert effective_sample_size(draws) > 0.8 * draws.size

    def test_ess_collapses_when_autocorrelated(self) -> None:
        rng = np.random.default_rng(0)
        walk = np.cumsum(rng.normal(size=(2000, 6)) * 0.1, axis=0)
        assert effective_sample_size(walk) < 100

    def test_they_agree_with_arviz(self) -> None:
        """The reference implementation, where it is available."""
        arviz = pytest.importorskip("arviz")
        rng = np.random.default_rng(0)
        draws = rng.normal(size=(2000, 6))
        dataset = arviz.convert_to_dataset(draws.T[None, :, :].reshape(6, 2000))
        assert split_r_hat(draws) == pytest.approx(
            float(arviz.rhat(dataset).x.values), abs=1e-6
        )
        assert effective_sample_size(draws) == pytest.approx(
            float(arviz.ess(dataset).x.values), rel=0.1
        )


@pytest.fixture(scope="module")
def both(narrow_panel: pd.DataFrame):
    """The same panel through both estimators, so they can be compared directly."""
    return (
        assess(narrow_panel),
        assess(narrow_panel, estimator=Estimator.BAYES),
    )


class TestTheEngineOptsIn:
    """`estimator` chooses how, never what. The ladder still decides mode and rung."""

    def test_the_default_fits_no_posterior(self, both) -> None:
        frequentist, _ = both
        assert frequentist.posterior is None

    def test_opting_in_adds_one(self, both) -> None:
        _, bayesian = both
        assert bayesian.posterior is not None
        assert bayesian.posterior.converged

    def test_nb2_survives_alongside_it(self, both) -> None:
        """The comparison every reviewer expects to see cited is still there."""
        _, bayesian = both
        assert bayesian.fit is not None
        assert bayesian.fit.coefficients

    def test_the_estimator_cannot_change_the_mode_or_the_rung(self, both) -> None:
        """The carve-out from the no-override rule, asserted rather than promised.

        `assess` exposes no way to force a mode or a rung, because that is a question
        about whether the data can support one. Choosing an estimator is a different
        question, and this test is what keeps it a different question.
        """
        frequentist, bayesian = both
        assert frequentist.mode is bayesian.mode
        assert frequentist.rung is bayesian.rung
        assert frequentist.factor_names == bayesian.factor_names

    def test_there_is_still_no_mode_override(self) -> None:
        import inspect

        parameters = inspect.signature(assess).parameters
        assert not {"mode", "force_mode", "rung"} & set(parameters)
        assert "estimator" in parameters

    def test_the_posterior_reaches_the_serialised_payload(self, both) -> None:
        _, bayesian = both
        payload = bayesian.as_dict()
        assert payload["posterior"] is not None
        assert payload["posterior"]["method"] == Method.LAPLACE.value
        assert payload["posterior"]["sigma_u"] is not None

    def test_the_inference_steps_are_logged(self, both) -> None:
        _, bayesian = both
        assert any(e.code == "inference_step" for e in bayesian.log.events)
