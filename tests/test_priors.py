"""Step 3.3b — the registry's weights as priors, and the three-way comparison.

Most of this is exercised on constructed objects rather than on fits, deliberately: the
arithmetic of "how much of this answer is the literature" is the part that has to be
right, and it does not need a sampler to check. One end-to-end run covers the wiring.
"""

from __future__ import annotations

import pandas as pd
import pytest

from roadrisk.core.context import RunContext
from roadrisk.core.engine import assess
from roadrisk.core.evidence import (
    DATA_DOMINATES,
    PRIOR_DOMINATES,
    Answer,
    FactorEvidence,
    compare,
)
from roadrisk.core.models import Estimator
from roadrisk.core.models.bayes import PosteriorFit, PosteriorSummary
from roadrisk.core.priors import (
    DEFAULT_SD,
    MIN_SD,
    FactorPrior,
    PriorSet,
    build_priors,
)
from roadrisk.core.registry import load_registry
from roadrisk.core.registry.schema import CrashScope, FacilityType, Region, Severity
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
    "speed_limit",
]


@pytest.fixture(scope="module")
def context() -> RunContext:
    return RunContext(
        facility_type=FacilityType.RURAL_TWO_LANE,
        region=Region.EUROPE,
        severity=Severity.INJURY,
    )


@pytest.fixture(scope="module")
def registry_priors(context: RunContext) -> PriorSet:
    return build_priors(load_registry().factors, context)


class TestPriorsComeFromTheRegistry:
    def test_some_factors_are_cited_and_some_are_not(self, registry_priors) -> None:
        assert registry_priors.cited
        assert registry_priors.uncited
        assert registry_priors.is_informative

    def test_an_uncited_factor_gets_an_uninformative_prior(self, registry_priors) -> None:
        """Centred on no effect, so it says nothing about direction."""
        for prior in registry_priors.uncited:
            assert prior.mean == 0.0
            assert prior.sd == DEFAULT_SD

    def test_a_cited_prior_carries_its_citation(self, registry_priors) -> None:
        for prior in registry_priors.cited:
            assert prior.source
            assert prior.family
            assert prior.published_value is not None

    def test_no_prior_is_ever_unfalsifiable(self, registry_priors) -> None:
        """A prior a corridor cannot move is an assumption wearing a posterior's coat."""
        for prior in registry_priors.priors:
            assert prior.sd >= MIN_SD
            assert prior.sd <= DEFAULT_SD

    def test_priors_never_truncate_the_expected_sign(self, registry_priors) -> None:
        """The prior carries direction as an expectation, never as a constraint.

        A truncated prior would make P(wrong sign) identically zero and delete the sign
        guard by construction. Every prior here is a plain normal with support on both
        sides of zero, which is what keeps a contradiction reportable.
        """
        for prior in registry_priors.cited:
            assert prior.sd > 0
            # A normal centred within a few SDs of zero always admits the other sign.
            assert abs(prior.mean) / prior.sd < 10.0

    def test_a_concern_widens_the_prior(self, context: RunContext) -> None:
        """speed_limit's posted-versus-operating caveat should loosen its own prior."""
        priors = build_priors(load_registry().factors, context)
        speed = priors.prior("speed_limit")
        assert speed is not None
        assert speed.concerns
        assert speed.sd > MIN_SD


class TestScopeDilution:
    """A weight for one crash type cannot speak at full strength about all of them."""

    def test_a_total_scope_weight_is_not_diluted(self, registry_priors) -> None:
        for prior in registry_priors.cited:
            if prior.scope is CrashScope.TOTAL:
                assert prior.dilution == 1.0
                assert prior.mean == pytest.approx(prior.published_value)

    def test_a_scoped_weight_is_diluted_by_its_crash_share(self, registry_priors) -> None:
        scoped = [p for p in registry_priors.cited if p.is_scoped]
        assert scoped, "the registry should carry at least one crash-type-scoped weight"
        for prior in scoped:
            assert 0.0 < prior.dilution < 1.0
            assert prior.mean == pytest.approx(prior.published_value * prior.dilution)

    def test_dilution_only_ever_weakens_a_prior(self, registry_priors) -> None:
        """It must not amplify: a scoped weight says *less* about total crashes."""
        for prior in registry_priors.cited:
            assert abs(prior.mean) <= abs(prior.published_value) + 1e-12


def _summary(name: str, mean: float, sd: float) -> PosteriorSummary:
    return PosteriorSummary(
        name=name,
        mean=mean,
        sd=sd,
        hdi_low=mean - 1.96 * sd,
        hdi_high=mean + 1.96 * sd,
        prob_positive=1.0 if mean > 0 else 0.0,
    )


def _fit(summaries: list[PosteriorSummary]) -> PosteriorFit:
    from roadrisk.core.diagnostics import Family
    from roadrisk.core.models.bayes import Method

    return PosteriorFit(
        specification="test",
        family=Family.NEGATIVE_BINOMIAL,
        converged=True,
        method=Method.LAPLACE,
        n_observations=100,
        n_units=40,
        n_parameters=5,
        coefficients=summaries,
    )


class TestTheShare:
    """How much of the answer came from the literature, as a percentage."""

    def test_a_confident_corridor_owns_its_answer(self) -> None:
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.5, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 0.05)]),
            mix_fit=_fit([_summary("x", 0.41, 0.05)]),
        )
        # prior precision 4, data precision 400 -> share about 1%
        assert report.factors[0].prior_share == pytest.approx(4 / 404, abs=1e-6)
        assert not report.factors[0].prior_dominates

    def test_a_silent_corridor_is_told_the_answer(self) -> None:
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.2, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 0.8)]),
            mix_fit=_fit([_summary("x", 0.49, 0.19)]),
        )
        assert report.factors[0].prior_share > PRIOR_DOMINATES
        assert report.factors[0].prior_dominates
        assert "MOSTLY TEXTBOOK" in report.factors[0].label()

    def test_an_uncited_factor_has_no_share(self) -> None:
        priors = PriorSet(priors=[FactorPrior("x", mean=0.0, sd=1.0, is_cited=False)])
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 0.1)]),
            mix_fit=_fit([_summary("x", 0.4, 0.1)]),
        )
        assert report.factors[0].prior_share is None


class TestContradiction:
    """The road disagreeing with the literature is a finding, not an error."""

    def test_it_is_judged_on_the_corridor_alone(self) -> None:
        """Never on the mix, which the prior has already pulled toward the textbook."""
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.3, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", -0.6, 0.15)]),
            mix_fit=_fit([_summary("x", -0.1, 0.14)]),
        )
        found = report.factors[0]
        assert found.contradicts_textbook
        assert found.label() == "CONTRADICTS"
        assert report.contradictions

    def test_agreeing_is_not_a_contradiction(self) -> None:
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.3, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.45, 0.10)]),
            mix_fit=_fit([_summary("x", 0.47, 0.09)]),
        )
        assert not report.factors[0].contradicts_textbook

    def test_a_wide_interval_containing_the_weight_is_not_a_contradiction(self) -> None:
        """Disagreeing by being uncertain is not disagreeing."""
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.3, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", -0.2, 0.9)]),
            mix_fit=_fit([_summary("x", 0.3, 0.3)]),
        )
        assert not report.factors[0].contradicts_textbook


class TestIndirectShift:
    """A factor with no prior of its own is not insulated from everyone else's."""

    def test_an_uncited_factor_moved_by_a_neighbour_is_reported(self) -> None:
        priors = PriorSet(priors=[FactorPrior("x", mean=0.0, sd=1.0, is_cited=False)])
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.40, 0.20)]),
            mix_fit=_fit([_summary("x", 0.25, 0.20)]),
        )
        found = report.factors[0]
        assert found.indirectly_shifted
        assert found.moved_by_others == pytest.approx(0.75, abs=1e-6)
        assert "another prior" in found.label()
        assert report.indirectly_shifted

    def test_an_untouched_factor_says_so(self) -> None:
        priors = PriorSet(priors=[FactorPrior("x", mean=0.0, sd=1.0, is_cited=False)])
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.40, 0.20)]),
            mix_fit=_fit([_summary("x", 0.401, 0.20)]),
        )
        assert not report.factors[0].indirectly_shifted
        assert report.factors[0].label() == "data alone"


class TestDesignation:
    """Three numbers are shown. One is named as the answer."""

    def test_a_rich_corridor_is_designated_its_own_data(self) -> None:
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.5, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 0.05)]),
            mix_fit=_fit([_summary("x", 0.41, 0.05)]),
        )
        assert report.answer is Answer.DATA
        assert "outweighs the literature" in report.reason

    def test_a_thin_corridor_is_designated_the_mix(self) -> None:
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.3, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 0.5)]),
            mix_fit=_fit([_summary("x", 0.47, 0.26)]),
        )
        assert report.answer is Answer.MIX

    def test_a_prior_dominated_answer_forbids_a_crash_count(self) -> None:
        """Mode B refuses to produce a count from published weights alone. So does this."""
        priors = PriorSet(
            priors=[FactorPrior("x", mean=0.5, sd=0.15, is_cited=True, published_value=0.5)]
        )
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 1.0)]),
            mix_fit=_fit([_summary("x", 0.49, 0.15)]),
        )
        assert report.answer is Answer.MIX
        assert report.prior_dominated
        assert "No crash count may be derived" in report.reason

    def test_without_any_cited_weight_the_data_is_the_answer(self) -> None:
        priors = PriorSet(priors=[FactorPrior("x", mean=0.0, sd=1.0, is_cited=False)])
        report = compare(
            priors=priors,
            data_fit=_fit([_summary("x", 0.4, 0.2)]),
            mix_fit=_fit([_summary("x", 0.4, 0.2)]),
        )
        assert report.answer is Answer.DATA

    def test_the_thresholds_are_ordered(self) -> None:
        assert DATA_DOMINATES < PRIOR_DOMINATES


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return synthetic_panel(n_units=40, n_periods=12, seed=7)[NARROW]


class TestTheEngineWiring:
    """One end-to-end run, because the plumbing needs checking once."""

    def test_priors_are_off_by_default(self, panel, context) -> None:
        """Today's numbers must not move because a new feature exists."""
        result = assess(panel, context=context, estimator=Estimator.BAYES)
        assert result.evidence is None
        assert result.posterior_data_only is None

    def test_asking_for_them_produces_the_comparison(self, panel, context) -> None:
        result = assess(
            panel,
            context=context,
            estimator=Estimator.BAYES,
            use_registry_priors=True,
        )
        assert result.evidence is not None
        assert result.posterior is not None
        assert result.posterior_data_only is not None
        assert result.evidence.cited, "the registry should price at least one fitted factor"

    def test_the_comparison_reaches_the_serialised_payload(self, panel, context) -> None:
        result = assess(
            panel,
            context=context,
            estimator=Estimator.BAYES,
            use_registry_priors=True,
        )
        payload = result.as_dict()
        assert payload["evidence"] is not None
        assert payload["posterior_data_only"] is not None
        first = payload["evidence"]["factors"][0]  # type: ignore[index]
        assert {"textbook", "data", "mix", "prior_share", "label"} <= set(first)


class TestFactorEvidenceEdges:
    def test_a_missing_fit_does_not_crash_the_comparison(self) -> None:
        priors = PriorSet(priors=[FactorPrior("x", mean=0.2, sd=0.4, is_cited=True)])
        report = compare(priors=priors, data_fit=None, mix_fit=None)
        assert report.factors[0].data_mean is None
        assert report.answer is Answer.DATA

    def test_zero_width_data_is_not_divided_by(self) -> None:
        item = FactorEvidence(factor="x", data_mean=0.1, mix_mean=0.2, data_sd=0.0)
        assert item.moved_by_others is None
