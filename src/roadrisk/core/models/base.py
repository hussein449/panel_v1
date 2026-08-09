"""Shared result types for the model layer.

Everything a fit produces is captured in plain dataclasses rather than a statsmodels
object, so that a result can be serialised into a run record and reproduced later. The
raw fit is kept alongside for diagnostics, but nothing downstream depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from roadrisk.core.diagnostics import Family


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
    raw: Any = field(default=None, repr=False, compare=False)

    @property
    def factor_names(self) -> list[str]:
        return [c.factor for c in self.coefficients]

    def coefficient(self, factor: str) -> Coefficient | None:
        return next((c for c in self.coefficients if c.factor == factor), None)


__all__ = ["Coefficient", "FitResult"]
