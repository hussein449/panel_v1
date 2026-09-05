"""The sign guard — the feature born from the M51 failure.

M51 produced ``ln(GF) = -0.730, p = 0.007``: worse geometry predicting fewer crashes.
Significant, and physically impossible. Orthogonalisation returned the identical
coefficient, because by Frisch-Waugh-Lovell it must — that was mathematically
guaranteed, not diagnostic.

A tool that catches its own nonsense is more trustworthy than one that never reports
any. iRAP cannot do this, because its weights are fixed. The HSM assumes a correctly
specified SPF. So this runs on every fit, and a contradiction is flagged prominently
rather than quietly reported.

On contradiction the guard automatically runs the diagnostics that found the original
problem: the factor alone, the factor alongside each correlated partner, the correlation
matrix, and leave-one-unit-out.

Since step 3.2 it also runs the rung 3 spline. The first four diagnostics all hunt the
brief's *first* suspect, confounding — they ask which other term the sign lives with.
None of them can see the third suspect, because a linear term forced through a U-shape
has no correlated partner to blame; it is the specification itself that is wrong. The
spline is the only diagnostic here that can return "the shape is why", and it is also
the only one that can rule that out and hand the question back to the other two.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from roadrisk.core.diagnostics import Family, correlated_partners, correlation_matrix
from roadrisk.core.gam import DEFAULT_RESAMPLES, ShapeDiagnostic, hunt_shape
from roadrisk.core.models import FitResult, fit_negative_binomial, fit_poisson
from roadrisk.core.registry import Factor, Sign
from roadrisk.core.runlog import RunLog

STAGE = "sign_guard"

DEFAULT_CORRELATION_THRESHOLD = 0.3
DEFAULT_MAX_LEAVE_ONE_OUT = 25

FitFn = Callable[[pd.Series, pd.DataFrame, pd.Series], FitResult]


@dataclass(frozen=True)
class PairwiseRefit:
    """The suspect factor refitted alongside one correlated partner."""

    partner: str
    correlation: float
    estimate: float | None
    agrees_with_expected: bool
    differs_from_full_fit: bool


@dataclass(frozen=True)
class LeaveOneOutReport:
    """Coefficient stability when single units are withheld."""

    n_units: int
    n_refits: int
    capped: bool
    estimate_min: float | None
    estimate_max: float | None
    n_sign_flips: int

    @property
    def unstable(self) -> bool:
        return self.n_sign_flips > 0


@dataclass(frozen=True)
class SignFinding:
    """One factor, checked against its declared expectation."""

    factor: str
    label: str
    expected_sign: Sign
    estimate: float
    p_value: float
    significant: bool
    contradicts: bool
    verdict: str
    univariate_estimate: float | None = None
    pairwise: list[PairwiseRefit] = field(default_factory=list)
    correlations: list[tuple[str, float]] = field(default_factory=list)
    leave_one_out: LeaveOneOutReport | None = None
    #: The rung 3 spline on this factor. Reference only — it carries a shape and a
    #: plot, and by construction no number that could reach a client report.
    shape: ShapeDiagnostic | None = None
    #: The correlated factor that, fitted alongside this one and nothing else, puts the
    #: sign back the way the registry declares it. ``None`` when no single partner does.
    #:
    #: **This is the difference between a mechanism and a mystery.** Drivers slow for
    #: bends, so on a corridor carrying both, speed absorbs the curvature signal and
    #: curvature comes out backwards — a textbook suppressor, and the pairwise refit
    #: shows it directly. A contradiction no partner explains is a different animal and
    #: has to stay flagged as one.
    suppressed_by: str | None = None

    @property
    def suppressed(self) -> bool:
        """A contradiction whose mechanism has been identified, not merely suspected."""
        return self.contradicts and self.suppressed_by is not None


@dataclass(frozen=True)
class SignGuardReport:
    """Sign guard outcome for one fit."""

    findings: list[SignFinding]
    correlations: pd.DataFrame

    @property
    def contradictions(self) -> list[SignFinding]:
        return [f for f in self.findings if f.contradicts]

    @property
    def suppressed(self) -> list[SignFinding]:
        """Contradictions a single correlated partner accounts for."""
        return [f for f in self.contradictions if f.suppressed]

    @property
    def unexplained(self) -> list[SignFinding]:
        """Contradictions no single partner accounts for. The ones worth worrying at."""
        return [f for f in self.contradictions if not f.suppressed]

    @property
    def clean(self) -> bool:
        return not self.contradictions

    @property
    def significant_contradictions(self) -> list[SignFinding]:
        """The ones that matter most — a wrong sign that is also statistically firm."""
        return [f for f in self.contradictions if f.significant]

    @property
    def explained_by_shape(self) -> list[SignFinding]:
        """Contradictions the spline accounts for: a straight line through a bend."""
        return [
            f
            for f in self.contradictions
            if f.shape is not None and f.shape.explains_contradiction
        ]


def run_sign_guard(
    *,
    fit: FitResult,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    factors: list[Factor],
    log: RunLog,
    correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
    max_leave_one_out: int = DEFAULT_MAX_LEAVE_ONE_OUT,
    shape_resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> SignGuardReport:
    """Compare every fitted coefficient against its declared ``expected_sign``.

    The follow-up diagnostics are expensive and only run for factors that actually
    contradict, which is rare by design. ``shape_resamples = 0`` skips the resampling
    inside the spline diagnostic, which is the bulk of that cost.
    """
    by_name = {f.name: f for f in factors}
    fit_fn = _fit_fn_for(fit.family)
    correlations = correlation_matrix(design)
    findings: list[SignFinding] = []

    for coefficient in fit.coefficients:
        factor = by_name.get(coefficient.factor)
        if factor is None:
            continue

        contradicts = (
            coefficient.sign != 0 and coefficient.sign != factor.expected_sign.as_int
        )

        if not contradicts:
            findings.append(
                SignFinding(
                    factor=factor.name,
                    label=factor.label,
                    expected_sign=factor.expected_sign,
                    estimate=coefficient.estimate,
                    p_value=coefficient.p_value,
                    significant=coefficient.significant,
                    contradicts=False,
                    verdict=(
                        f"Sign agrees with the declared expectation "
                        f"('{factor.expected_sign.value}')."
                    ),
                )
            )
            continue

        partners = correlated_partners(
            design, factor.name, threshold=correlation_threshold
        )
        univariate = _univariate(fit_fn, counts, design, log_exposure, factor.name)
        pairwise = _pairwise(
            fit_fn,
            counts,
            design,
            log_exposure,
            factor,
            partners,
            full_estimate=coefficient.estimate,
        )
        suppressed_by = _suppressor(factor, univariate, pairwise)
        finding = SignFinding(
            factor=factor.name,
            label=factor.label,
            expected_sign=factor.expected_sign,
            estimate=coefficient.estimate,
            p_value=coefficient.p_value,
            significant=coefficient.significant,
            contradicts=True,
            verdict=_verdict(
                factor,
                coefficient.estimate,
                coefficient.significant,
                suppressed_by=suppressed_by,
            ),
            univariate_estimate=univariate,
            pairwise=pairwise,
            suppressed_by=suppressed_by,
            correlations=partners,
            leave_one_out=_leave_one_out(
                fit_fn,
                counts,
                design,
                log_exposure,
                unit_ids,
                factor.name,
                cap=max_leave_one_out,
            ),
            shape=hunt_shape(
                factor=factor.name,
                counts=counts,
                design=design,
                log_exposure=log_exposure,
                unit_ids=unit_ids,
                alpha=fit.alpha,
                expected_sign=factor.expected_sign,
                linear_estimate=coefficient.estimate,
                n_resamples=shape_resamples,
                seed=seed,
                log=log,
            ),
        )
        findings.append(finding)

        log.flag(
            STAGE,
            "sign_contradiction",
            (
                f"'{factor.name}' fitted {coefficient.estimate:+.3f} "
                f"(p = {coefficient.p_value:.3f}) but declares expected sign "
                f"'{factor.expected_sign.value}'. {finding.verdict}"
            ),
            factor=factor.name,
            estimate=round(coefficient.estimate, 6),
            p_value=round(coefficient.p_value, 6),
            expected_sign=factor.expected_sign.value,
            univariate_estimate=finding.univariate_estimate,
            correlated_with=[name for name, _ in partners],
            shape=(
                finding.shape.shape.value
                if finding.shape is not None and finding.shape.shape is not None
                else None
            ),
            explained_by_shape=(
                finding.shape is not None and finding.shape.explains_contradiction
            ),
        )

    if not any(f.contradicts for f in findings):
        log.info(
            STAGE,
            "signs_agree",
            f"All {len(findings)} fitted coefficient(s) agree with their declared signs.",
        )

    return SignGuardReport(findings=findings, correlations=correlations)


def _suppressor(
    factor: Factor, univariate: float | None, pairwise: list[PairwiseRefit]
) -> str | None:
    """The single partner that puts the sign back, if one does.

    Two conditions, and both are needed. The factor must point the declared way **on its
    own** — otherwise there is no correct sign for a partner to have suppressed, and the
    disagreement is with the data rather than with the specification. And adding exactly
    one correlated partner must put it back — which identifies that partner as the
    absorber rather than leaving the cause somewhere among the other five terms.

    Where both hold the mechanism is named, not guessed: curvature comes out backwards
    beside speed because drivers slow for bends, and the pairwise refit shows precisely
    that. Where they do not, nothing has been explained and the finding stays open.
    """
    expected = factor.expected_sign.as_int
    if univariate is None or univariate == 0.0:
        return None
    if (univariate > 0) != (expected > 0):
        return None
    restored = [
        refit
        for refit in pairwise
        if refit.agrees_with_expected and refit.estimate is not None
    ]
    if not restored:
        return None
    # The most correlated partner, which is the one with the most to absorb.
    return max(restored, key=lambda refit: abs(refit.correlation)).partner


def _verdict(
    factor: Factor,
    estimate: float,
    significant: bool,
    *,
    suppressed_by: str | None = None,
) -> str:
    if suppressed_by is not None:
        return (
            f"Fitted {estimate:+.3f} against a declared expectation of "
            f"'{factor.expected_sign.value}', but this is suppression rather than a "
            f"contradiction and the suppressor is identified: on its own the factor "
            f"points the declared way, and it still does beside '{suppressed_by}' "
            "alone. The two move together on this corridor and the partner absorbs the "
            "signal, which is ordinary behaviour for correlated terms and not evidence "
            "that the literature is wrong here. The coefficient still must not be read "
            f"on its own — what it measures is this factor net of '{suppressed_by}', "
            "which is not the quantity the registry's expectation is about."
        )
    firmness = (
        "It is also statistically significant, which makes it a specification problem "
        "rather than noise."
        if significant
        else "It is not statistically significant, so noise cannot be excluded."
    )
    return (
        f"Fitted {estimate:+.3f} against a declared expectation of "
        f"'{factor.expected_sign.value}'. {firmness} This term is NOT interpretable as "
        "causal and must not be used to justify a countermeasure. The usual causes are "
        "confounding with an omitted or correlated variable, a missing mediator, or a "
        "non-monotonic relationship forced through a linear term."
    )


def _fit_fn_for(family: Family) -> FitFn:
    return (
        fit_negative_binomial if family is Family.NEGATIVE_BINOMIAL else fit_poisson
    )


def _estimate(result: FitResult, factor: str) -> float | None:
    if not result.converged:
        return None
    coefficient = result.coefficient(factor)
    return coefficient.estimate if coefficient else None


def _univariate(
    fit_fn: FitFn,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    factor: str,
) -> float | None:
    """The factor on its own. If the sign is right here, the problem is specification."""
    return _estimate(fit_fn(counts, design[[factor]], log_exposure), factor)


def _pairwise(
    fit_fn: FitFn,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    factor: Factor,
    partners: list[tuple[str, float]],
    *,
    full_estimate: float,
) -> list[PairwiseRefit]:
    """The factor alongside each correlated partner, one at a time.

    This is what isolates the culprit: on M51 the negative sign lived in the ramp
    component and appeared only alongside the roadside activity term. A partner that
    flips the sign back to its expected direction is the one to investigate.
    """
    expected = factor.expected_sign.as_int
    full_sign = _sign_of(full_estimate)
    refits: list[PairwiseRefit] = []

    for partner, correlation in partners:
        estimate = _estimate(
            fit_fn(counts, design[[factor.name, partner]], log_exposure), factor.name
        )
        sign = _sign_of(estimate) if estimate is not None else 0
        refits.append(
            PairwiseRefit(
                partner=partner,
                correlation=correlation,
                estimate=estimate,
                agrees_with_expected=estimate is not None and sign == expected,
                differs_from_full_fit=estimate is not None and sign != full_sign,
            )
        )
    return refits


def _sign_of(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _leave_one_out(
    fit_fn: FitFn,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    factor: str,
    *,
    cap: int,
) -> LeaveOneOutReport | None:
    """Refit with single units withheld, to see whether one unit carries the result.

    Capped, because a refit is not cheap. With many units this test is weak by
    construction — dropping 1 of 3,800 segments moves nothing — and the cap is reported
    so the weakness is visible rather than implied.
    """
    units = pd.unique(unit_ids)
    if len(units) < 3:
        return None

    capped = len(units) > cap
    if capped:
        stride = max(1, len(units) // cap)
        sampled = list(units[::stride])[:cap]
    else:
        sampled = list(units)

    estimates: list[float] = []
    for unit in sampled:
        keep = (unit_ids != unit).to_numpy()
        if keep.sum() < len(design.columns) + 2:
            continue
        estimate = _estimate(
            fit_fn(counts[keep], design[keep], log_exposure[keep]), factor
        )
        if estimate is not None and np.isfinite(estimate):
            estimates.append(estimate)

    if not estimates:
        return LeaveOneOutReport(
            n_units=int(len(units)),
            n_refits=0,
            capped=capped,
            estimate_min=None,
            estimate_max=None,
            n_sign_flips=0,
        )

    positives = sum(1 for e in estimates if e > 0)
    negatives = len(estimates) - positives
    return LeaveOneOutReport(
        n_units=int(len(units)),
        n_refits=len(estimates),
        capped=capped,
        estimate_min=float(min(estimates)),
        estimate_max=float(max(estimates)),
        n_sign_flips=min(positives, negatives),
    )


__all__ = [
    "DEFAULT_CORRELATION_THRESHOLD",
    "DEFAULT_MAX_LEAVE_ONE_OUT",
    "LeaveOneOutReport",
    "PairwiseRefit",
    "SignFinding",
    "SignGuardReport",
    "run_sign_guard",
]
