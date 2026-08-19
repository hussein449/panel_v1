"""Shared result types for the model layer.

Everything a fit produces is captured in plain dataclasses rather than a statsmodels
object, so that a result can be serialised into a run record and reproduced later. The
raw fit is kept alongside for diagnostics, but nothing downstream depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

from roadrisk.core.diagnostics import Family


class Estimator(StrEnum):
    """How Mode A's numbers are arrived at. **Not** which mode or rung is used.

    The distinction matters, because ``assess`` deliberately exposes no way to force a
    mode or a rung and a test asserts it never grows one. That rule is about *data
    adequacy*: whether a panel can support seven terms or three is the engine's call,
    never the caller's, because a caller who could overrule it would overrule it.

    This is a different question. The ladder still decides the mode, the rung and the
    terms, identically either way; this only decides how the coefficients on those
    terms are estimated. A test pins that: the same panel returns the same mode, rung
    and factor list under both estimators.
    """

    #: Negative binomial with unit-clustered standard errors. The shipped default and
    #: the comparison every reviewer expects to see cited.
    NB2 = "nb2"
    #: Bayesian NB GLMM with a random intercept per unit. Credible intervals rather
    #: than p-values, and it changes the estimates rather than only their spread.
    BAYES = "bayes"


@dataclass(frozen=True)
class Coefficient:
    """One estimated term."""

    factor: str
    estimate: float
    std_error: float
    z_value: float
    p_value: float
    ci_low: float
    ci_high: float

    @property
    def sign(self) -> int:
        """Direction of the point estimate. Zero only on an exact zero."""
        if self.estimate > 0:
            return 1
        if self.estimate < 0:
            return -1
        return 0

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05

    @property
    def ci_excludes_zero(self) -> bool:
        return (self.ci_low > 0) or (self.ci_high < 0)


@dataclass(frozen=True)
class FitResult:
    """A fitted Mode A model.

    A result with ``converged = False`` is never reported. It exists so the ladder can
    record *why* a rung was abandoned rather than discarding the attempt.
    """

    specification: str
    family: Family
    converged: bool
    n_observations: int
    n_parameters: int
    coefficients: list[Coefficient] = field(default_factory=list)
    intercept: Coefficient | None = None
    log_likelihood: float | None = None
    aic: float | None = None
    bic: float | None = None
    alpha: float | None = None
    pearson_dispersion: float | None = None
    fitted_values: pd.Series | None = None
    failure_reason: str | None = None

    #: Units the standard errors were clustered over, when they were. ``None`` means
    #: the fit treats every row as an independent observation.
    n_clusters: int | None = None
    #: Per coefficient, how much wider the clustered standard error is than the naive
    #: one. This is the number rung 2 exists to produce: how much too certain the
    #: independent-rows fit was.
    cluster_widening: dict[str, float] = field(default_factory=dict)
    #: The standard error rung 1 would have reported, per coefficient. Kept so the
    #: report can print what the reader would have been told beside what is true — a
    #: correction nobody can see the size of is a correction nobody believes.
    naive_std_errors: dict[str, float] = field(default_factory=dict)
    #: What the model layer needs the reader to know about this fit.
    notes: tuple[str, ...] = ()

    raw: Any = field(default=None, repr=False, compare=False)

    @property
    def factor_names(self) -> list[str]:
        return [c.factor for c in self.coefficients]

    @property
    def is_clustered(self) -> bool:
        return bool(self.cluster_widening)

    @property
    def worst_widening(self) -> float:
        """The most over-confident coefficient's inflation factor, or 1.0."""
        return max(self.cluster_widening.values(), default=1.0)

    def coefficient(self, factor: str) -> Coefficient | None:
        return next((c for c in self.coefficients if c.factor == factor), None)


__all__ = ["Coefficient", "Estimator", "FitResult"]
