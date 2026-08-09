"""Pre-fit diagnostics: collinearity, correlation, dispersion.

The VIF computation here is the one that would have caught the geometry/roadside
confounding on M51 before it reached a result. It runs before anything is fitted.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor


class Family(StrEnum):
    """Count family indicated by the data."""

    POISSON = "poisson"
    NEGATIVE_BINOMIAL = "negative_binomial"


@dataclass(frozen=True)
class VIFReport:
    """Variance inflation factors across the active design."""

    values: dict[str, float]

    @property
    def max_vif(self) -> float:
        return max(self.values.values()) if self.values else 1.0

    @property
    def worst(self) -> str | None:
        """The term to drop first when collinearity forces a descent."""
        if not self.values:
            return None
        return max(self.values, key=lambda k: self.values[k])

    def above(self, threshold: float) -> list[str]:
        return sorted(
            (k for k, v in self.values.items() if v > threshold),
            key=lambda k: self.values[k],
            reverse=True,
        )


@dataclass(frozen=True)
class DispersionReport:
    """Whether the counts are overdispersed relative to Poisson."""

    mean: float
    variance: float
    ratio: float
    family: Family
    pearson_dispersion: float | None = None

    @property
    def overdispersed(self) -> bool:
        return self.family is Family.NEGATIVE_BINOMIAL


def compute_vif(design: pd.DataFrame) -> VIFReport:
    """Variance inflation factor per column, computed with an intercept present.

    A single-column design has no collinearity to measure and returns 1.0. Perfectly
    collinear columns return ``inf`` rather than raising — the gate decides what to do
    about it.
    """
    if design.shape[1] == 0:
        return VIFReport(values={})
    if design.shape[1] == 1:
        return VIFReport(values={design.columns[0]: 1.0})

    exog = sm.add_constant(design.astype(float), has_constant="add")
    columns = list(exog.columns)
    matrix = exog.to_numpy(dtype=float)

    values: dict[str, float] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with np.errstate(divide="ignore", invalid="ignore"):
            for position, name in enumerate(columns):
                if name == "const":
                    continue
                try:
                    vif = float(variance_inflation_factor(matrix, position))
                except Exception:  # noqa: BLE001 - singular design, reported not raised
                    vif = float("inf")
                values[name] = vif if np.isfinite(vif) else float("inf")

    return VIFReport(values=values)


def correlation_matrix(design: pd.DataFrame) -> pd.DataFrame:
    """Pearson correlation across the transformed design."""
    if design.shape[1] == 0:
        return pd.DataFrame()
    return design.astype(float).corr()


def correlated_partners(
    design: pd.DataFrame,
    factor: str,
    *,
    threshold: float = 0.3,
) -> list[tuple[str, float]]:
    """Factors correlated with ``factor`` above ``threshold``, strongest first.

    Used by the sign guard: when a coefficient contradicts its expected sign, these
    are the partners it is refitted alongside.
    """
    if factor not in design.columns or design.shape[1] < 2:
        return []
    correlations = design.astype(float).corr()[factor].drop(labels=[factor])
    partners = [
        (name, float(value))
        for name, value in correlations.items()
        if np.isfinite(value) and abs(value) >= threshold
    ]
    return sorted(partners, key=lambda item: abs(item[1]), reverse=True)


def compute_dispersion(
    counts: pd.Series,
    *,
    nb_threshold: float = 1.2,
    pearson_dispersion: float | None = None,
) -> DispersionReport:
    """Variance-to-mean ratio, and the family it implies.

    This sets the family, not the mode. An overdispersed panel still runs Mode A — it
    just runs it as negative binomial rather than Poisson.
    """
    values = counts.astype(float)
    mean = float(values.mean())
    variance = float(values.var(ddof=1)) if len(values) > 1 else 0.0
    ratio = variance / mean if mean > 0 else float("inf")

    indicated = pearson_dispersion if pearson_dispersion is not None else ratio
    family = (
        Family.NEGATIVE_BINOMIAL if indicated > nb_threshold else Family.POISSON
    )

    return DispersionReport(
        mean=mean,
        variance=variance,
        ratio=ratio,
        family=family,
        pearson_dispersion=pearson_dispersion,
    )


CONSTANT_RELATIVE_TOLERANCE = 1e-12


def zero_variance_columns(
    design: pd.DataFrame,
    *,
    relative_tolerance: float = CONSTANT_RELATIVE_TOLERANCE,
) -> list[str]:
    """Columns that are constant and therefore inestimable.

    A constant column makes the design singular. It is dropped before fitting and the
    drop is logged — never silently absorbed into the intercept.

    The comparison is relative and tolerant rather than an exact ``== 0``. Floating
    point summation leaves a genuinely constant column with a standard deviation
    around 1e-15 rather than zero, and an exact test misses it. This is not a
    theoretical case: a corridor with one posted speed limit along its whole length is
    ordinary, and ``maxspeed`` is frequently constant in exactly that way.
    """
    if design.shape[1] == 0:
        return []

    values = design.astype(float)
    stds = values.std(ddof=0)
    # Compare against the column's own magnitude, so the test means the same thing on
    # a column of proportions as on a column of log-metres.
    scales = values.abs().mean().clip(lower=1.0)

    return [
        str(name)
        for name in values.columns
        if not np.isfinite(stds[name])
        or stds[name] <= relative_tolerance * scales[name]
    ]


__all__ = [
    "DispersionReport",
    "Family",
    "VIFReport",
    "compute_dispersion",
    "compute_vif",
    "correlated_partners",
    "correlation_matrix",
    "zero_variance_columns",
]
