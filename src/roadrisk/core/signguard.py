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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from roadrisk.core.diagnostics import Family, correlated_partners, correlation_matrix
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


@dataclass(frozen=True)
class SignGuardReport:
    """Sign guard outcome for one fit."""

    findings: list[SignFinding]
    correlations: pd.DataFrame

    @property
    def contradictions(self) -> list[SignFinding]:
        return [f for f in self.findings if f.contradicts]

    @property
    def clean(self) -> bool:
        return not self.contradictions

    @property
    def significant_contradictions(self) -> list[SignFinding]:
        """The ones that matter most — a wrong sign that is also statistically firm."""
        return [f for f in self.contradictions if f.significant]


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
) -> SignGuardReport:
    """Compare every fitted coefficient against its declared ``expected_sign``.

    The follow-up diagnostics are expensive and only run for factors that actually
    contradict, which is rare by design.
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
        finding = SignFinding(
            factor=factor.name,
            label=factor.label,
            expected_sign=factor.expected_sign,
            estimate=coefficient.estimate,
            p_value=coefficient.p_value,
            significant=coefficient.significant,
            contradicts=True,
            verdict=_verdict(factor, coefficient.estimate, coefficient.significant),
            univariate_estimate=_univariate(
                fit_fn, counts, design, log_exposure, factor.name
            ),
            pairwise=_pairwise(
                fit_fn,
                counts,
                design,
                log_exposure,
                factor,
                partners,
                full_estimate=coefficient.estimate,
            ),
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
        )

    if not any(f.contradicts for f in findings):
        log.info(
            STAGE,
            "signs_agree",
            f"All {len(findings)} fitted coefficient(s) agree with their declared signs.",
        )

    return SignGuardReport(findings=findings, correlations=correlations)


def _verdict(factor: Factor, estimate: float, significant: bool) -> str:
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
