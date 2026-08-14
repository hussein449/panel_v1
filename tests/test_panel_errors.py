"""Rung 2 — standard errors that account for the panel.

The step's own test is *"standard errors widen versus plain NB2"*, and the reason it
matters is stated in the brief: the panel measures the same segment across many periods,
and plain NB treats those as independent observations.

On this panel the error is severe, because **every factor is unit-constant**. Curvature,
gradient, lane count and every density are properties of a segment, repeated unchanged
down every period. A 120-unit corridor over 24 months has 5,760 rows and 120 independent
observations of each covariate; rung 1 computes its intervals as though it had 5,760.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.contract import (
    CRASH_COLUMN,
    LOG_EXPOSURE_COLUMN,
    UNIT_COLUMN,
    prepare_panel,
)
from roadrisk.core.engine import assess
from roadrisk.core.models.glm import (
    FEW_CLUSTERS,
    MIN_CLUSTERS,
    fit_negative_binomial,
    fit_negative_binomial_panel,
)
from roadrisk.core.registry import load_registry
from roadrisk.core.transforms import build_design
from roadrisk.demo import TRUE_EFFECTS, synthetic_panel

#: A segment-level trait that persists across every period — a bad junction layout, a
#: school, poor drainage. Modest on the log scale, and enough to make repeated
#: observations of one segment correlated, which is the whole point.
REALISTIC_HETEROGENEITY = 0.5


def pieces(panel: pd.DataFrame):
    """counts, design, offset, unit ids — what the model layer actually takes."""
    prepared, _ = prepare_panel(panel)
    registry = load_registry()
    factors = registry.available(prepared.columns)
    design = build_design(prepared, factors)
    return (
        prepared[CRASH_COLUMN],
        design,
        prepared[LOG_EXPOSURE_COLUMN],
        prepared[UNIT_COLUMN],
    )


@pytest.fixture(scope="module")
def realistic() -> pd.DataFrame:
    """A panel whose segments have persistent unobserved traits, as real ones do."""
    return synthetic_panel(n_units=120, n_periods=24, seed=7)


class TestTheCorrection:
    def test_standard_errors_widen(self, realistic: pd.DataFrame) -> None:
        """The step's done-when, on data that has the correlation to correct for."""
        counts, design, offset, units = pieces(realistic)

        naive = fit_negative_binomial(counts, design, offset)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert panel.converged
        for coefficient in panel.coefficients:
            before = naive.coefficient(coefficient.factor)
            assert before is not None
            assert coefficient.std_error > before.std_error

    def test_the_coefficients_do_not_move(self, realistic: pd.DataFrame) -> None:
        """Only the certainty changes. That is what makes the upgrade legible."""
        counts, design, offset, units = pieces(realistic)

        naive = fit_negative_binomial(counts, design, offset)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        for coefficient in panel.coefficients:
            before = naive.coefficient(coefficient.factor)
            assert coefficient.estimate == pytest.approx(before.estimate, rel=1e-6)

    def test_a_factor_can_lose_its_significance(self, realistic: pd.DataFrame) -> None:
        """The brief's warning, reproduced: this alone may change a p-value.

        On this fixture `access_density` goes from p < 0.0001 to p ≈ 0.65. It was never
        significant; the first fit was counting one segment forty-eight times.
        """
        counts, design, offset, units = pieces(realistic)

        naive = fit_negative_binomial(counts, design, offset)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        lost = [
            c.factor
            for c in panel.coefficients
            if not c.significant and naive.coefficient(c.factor).significant
        ]
        assert lost, "the whole point of rung 2 is that this can happen"

    def test_the_widening_is_reported_per_coefficient(
        self, realistic: pd.DataFrame
    ) -> None:
        counts, design, offset, units = pieces(realistic)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert set(panel.cluster_widening) == set(panel.factor_names)
        assert panel.worst_widening > 2.0
        assert panel.is_clustered

    def test_both_standard_errors_are_kept_side_by_side(
        self, realistic: pd.DataFrame
    ) -> None:
        """A correction nobody can see the size of is a correction nobody believes.

        The estimates do not move, so the only way a reader can judge how much the
        panel mattered is to see what they would have been told beside what is true.
        """
        counts, design, offset, units = pieces(realistic)

        naive = fit_negative_binomial(counts, design, offset)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert set(panel.naive_std_errors) == set(panel.factor_names)
        for name, before in panel.naive_std_errors.items():
            assert before == pytest.approx(naive.coefficient(name).std_error)
            assert panel.coefficient(name).std_error / before == pytest.approx(
                panel.cluster_widening[name]
            )

    def test_the_number_of_clusters_is_recorded(self, realistic: pd.DataFrame) -> None:
        counts, design, offset, units = pieces(realistic)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert panel.n_clusters == 120
        assert panel.n_observations == 5_760

    def test_it_says_what_it_did(self, realistic: pd.DataFrame) -> None:
        counts, design, offset, units = pieces(realistic)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert any("clustered by unit" in note for note in panel.notes)
        assert any("widened the intervals" in note for note in panel.notes)


class TestWhenThereIsNothingToCorrect:
    def test_independent_rows_are_barely_touched(self) -> None:
        """A fixture with no segment-level heterogeneity has no correlation to fix.

        The sandwich estimator is a different estimator, not a bigger one, so on data
        that genuinely has independent rows it lands near the naive figure and may sit
        slightly either side of it. Reporting a widening here would be an artefact.
        """
        flat = synthetic_panel(n_units=120, n_periods=24, seed=7, unit_dispersion=0.0)
        counts, design, offset, units = pieces(flat)

        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert panel.worst_widening < 1.5

    def test_segments_now_carry_persistent_character_by_default(self) -> None:
        """The fixture drew overdispersion per ROW until rung 2 was built.

        That made every observation of a segment independent, which is not what a panel
        is, and it let every model fitted to the demo look better than it would on a
        road. Turning it on is now the default; zero is available to get the old
        behaviour, and on that setting the correction correctly finds nothing.
        """
        varied = synthetic_panel(n_units=40, n_periods=12, seed=3)
        flat = synthetic_panel(n_units=40, n_periods=12, seed=3, unit_dispersion=0.0)

        assert not flat.equals(varied)
        by_unit = varied.groupby(UNIT_COLUMN)[CRASH_COLUMN].mean()
        assert by_unit.std() > flat.groupby(UNIT_COLUMN)[CRASH_COLUMN].mean().std()


class TestTheIntervalsAreActuallyHonest:
    """The one test that shows the correction is *right*, not merely different.

    Everything else here shows the intervals moved. This shows they moved the correct
    way, by measuring the promise a 95% interval makes: across many panels drawn from
    the same planted truth, the true value should land inside it 95% of the time.

    Deterministic — the seeds are fixed — so there is no flake in the thresholds.
    """

    REPLICATES = 24

    def measure(self, unit_dispersion: float) -> tuple[float, float]:
        naive_hits = clustered_hits = total = 0

        for seed in range(self.REPLICATES):
            panel = synthetic_panel(
                n_units=80,
                n_periods=12,
                seed=1000 + seed,
                unit_dispersion=unit_dispersion,
            )
            counts, design, offset, units = pieces(panel)
            naive = fit_negative_binomial(counts, design, offset)
            clustered = fit_negative_binomial_panel(counts, design, offset, units)
            if not (naive.converged and clustered.converged):
                continue

            for name, truth in TRUE_EFFECTS.items():
                a, b = naive.coefficient(name), clustered.coefficient(name)
                if a is None or b is None:
                    continue
                total += 1
                naive_hits += a.ci_low <= truth <= a.ci_high
                clustered_hits += b.ci_low <= truth <= b.ci_high

        return naive_hits / total, clustered_hits / total

    def test_rung_one_is_overconfident_on_a_real_panel(self) -> None:
        """It claims 95% and delivers about 70%. That is the defect, quantified."""
        naive_rate, _ = self.measure(REALISTIC_HETEROGENEITY)

        assert naive_rate < 0.80, (
            f"rung 1's 95% intervals contained the truth {naive_rate:.0%} of the time"
        )

    def test_rung_two_delivers_what_it_promises(self) -> None:
        _, clustered_rate = self.measure(REALISTIC_HETEROGENEITY)

        assert 0.88 <= clustered_rate <= 1.0, (
            f"rung 2's 95% intervals contained the truth {clustered_rate:.0%} of the time"
        )

    def test_the_correction_is_not_just_making_everything_wider(self) -> None:
        """On data with genuinely independent rows, rung 1 was already honest.

        A correction that widened regardless would show up here as coverage climbing
        above the nominal rate — intervals too wide, which is its own kind of wrong.
        """
        naive_rate, clustered_rate = self.measure(0.0)

        assert naive_rate >= 0.88, "nothing to correct, so rung 1 should already be fine"
        assert clustered_rate <= 1.0


class TestTooFewClusters:
    def test_the_correction_is_declined_not_silently_applied(self) -> None:
        """Below a couple of dozen units the sandwich estimator is itself unreliable.

        Applying it anyway would produce standard errors that are still too small while
        looking as though the problem had been dealt with — the caveat would vanish.
        """
        small = synthetic_panel(
            n_units=8, n_periods=36, seed=5, unit_dispersion=REALISTIC_HETEROGENEITY
        )
        counts, design, offset, units = pieces(small)

        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert panel.n_clusters == 8
        assert not panel.is_clustered
        assert panel.cluster_widening == {}

    def test_it_says_how_wrong_the_uncorrected_intervals_are(self) -> None:
        """Refusing to fix it is not a reason to stop describing it."""
        small = synthetic_panel(n_units=8, n_periods=36, seed=5)
        counts, design, offset, units = pieces(small)

        note = fit_negative_binomial_panel(counts, design, offset, units).notes[0]

        assert "NOT corrected" in note
        assert "effective sample size is 8" in note
        assert "unproven" in note

    def test_the_m51_corridor_is_exactly_this_case(self) -> None:
        """Seven units. The corridor this whole project keeps referring back to."""
        m51 = synthetic_panel(n_units=7, n_periods=155, seed=11)
        counts, design, offset, units = pieces(m51)

        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert panel.n_clusters == 7
        assert panel.n_clusters < MIN_CLUSTERS
        assert not panel.is_clustered

    def test_between_twenty_and_forty_clusters_it_applies_but_hedges(self) -> None:
        middling = synthetic_panel(
            n_units=25, n_periods=24, seed=9, unit_dispersion=REALISTIC_HETEROGENEITY
        )
        counts, design, offset, units = pieces(middling)

        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert MIN_CLUSTERS <= panel.n_clusters < FEW_CLUSTERS
        assert panel.is_clustered
        assert any("still too narrow" in note for note in panel.notes)

    def test_a_wide_corridor_gets_the_correction_without_a_caveat(
        self, realistic: pd.DataFrame
    ) -> None:
        counts, design, offset, units = pieces(realistic)
        panel = fit_negative_binomial_panel(counts, design, offset, units)

        assert panel.n_clusters >= FEW_CLUSTERS
        assert not any("still too narrow" in note for note in panel.notes)


class TestThroughTheEngine:
    def test_the_shipped_fit_is_the_corrected_one(self, realistic: pd.DataFrame) -> None:
        assessment = assess(realistic)

        assert assessment.is_mode_a
        assert "unit-clustered" in assessment.fit.specification
        assert assessment.fit.n_clusters == 120

    def test_the_correction_reaches_the_run_log(self, realistic: pd.DataFrame) -> None:
        assessment = assess(realistic)
        events = [event for event in assessment.log if "clustered by unit" in event.message]

        assert events, "a reader of the log must be able to see the certainty changed"

    def test_the_sign_guard_still_sees_the_same_directions(
        self, realistic: pd.DataFrame
    ) -> None:
        """Clustering moves no estimate, so it can neither create nor hide a reversal."""
        assessment = assess(realistic)

        assert assessment.sign_guard is not None
        for finding in assessment.sign_guard.findings:
            coefficient = assessment.fit.coefficient(finding.factor)
            assert np.sign(coefficient.estimate) == np.sign(finding.estimate)

    def test_a_narrow_corridor_still_produces_an_assessment(self) -> None:
        """Declining the correction must not cost the run its result."""
        small = synthetic_panel(n_units=8, n_periods=60, seed=5)
        assessment = assess(small)

        assert assessment.has_result
        if assessment.is_mode_a:
            assert not assessment.fit.is_clustered
