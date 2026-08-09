"""Mode A rungs 0 and 1 — Poisson and negative binomial count models.

Rung 0, Poisson, is a **reference point, not an answer**. It measures overdispersion
and justifies the negative binomial. It is always run and it never reaches a client.

Rung 1, NB2, is the HSM standard and the Mode A baseline. Nothing else ships before it
works.

``ln(exposure)`` enters as an offset in both — a coefficient fixed at 1, not estimated.
Exposure is structural and the ladder may never drop it.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm

from roadrisk.core.diagnostics import Family
from roadrisk.core.models.base import Coefficient, FitResult

INTERCEPT = "const"
_ALPHA = "alpha"


def fit_poisson(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
) -> FitResult:
    """Rung 0 — Poisson GLM. Reference only; never reported as the assessment."""
    return _fit(
        counts,
        design,
        log_exposure,
        specification="Poisson GLM",
        family=Family.POISSON,
    )


def fit_negative_binomial(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
) -> FitResult:
    """Rung 1 — NB2 GLM with jointly estimated dispersion. The Mode A baseline."""
    return _fit(
        counts,
        design,
        log_exposure,
        specification="Negative binomial (NB2) GLM",
        family=Family.NEGATIVE_BINOMIAL,
    )


def _fit(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    *,
    specification: str,
    family: Family,
) -> FitResult:
    endog = counts.astype(float)
    exog = sm.add_constant(design.astype(float), has_constant="add")
    offset = log_exposure.astype(float).to_numpy()
    n_parameters = int(exog.shape[1]) + (1 if family is Family.NEGATIVE_BINOMIAL else 0)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if family is Family.POISSON:
                model = sm.GLM(
                    endog, exog, family=sm.families.Poisson(), offset=offset
                )
                results = model.fit()
            else:
                model = sm.NegativeBinomialP(endog, exog, p=2, offset=offset)
                results = model.fit(disp=0, maxiter=200)
    except Exception as exc:  # noqa: BLE001 - a failed fit descends, it does not crash
        return FitResult(
            specification=specification,
            family=family,
            converged=False,
            n_observations=int(len(endog)),
            n_parameters=n_parameters,
            failure_reason=f"{type(exc).__name__}: {exc}",
        )

    if not _converged(results):
        return FitResult(
            specification=specification,
            family=family,
            converged=False,
            n_observations=int(len(endog)),
            n_parameters=n_parameters,
            failure_reason="optimiser did not report convergence",
            raw=results,
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        coefficients, intercept, alpha = _extract(results, design.columns)
        fitted = pd.Series(np.asarray(results.predict()), index=design.index)
        log_likelihood = _safe_float(getattr(results, "llf", None))
        aic = _safe_float(getattr(results, "aic", None))
        # `bic_llf` is the log-likelihood form. Plain `bic` on a GLM is the deviance
        # form, which is on a different scale and not comparable across families.
        bic = _safe_float(
            getattr(results, "bic_llf", None) or getattr(results, "bic", None)
        )

    return FitResult(
        specification=specification,
        family=family,
        converged=True,
        n_observations=int(len(endog)),
        n_parameters=n_parameters,
        coefficients=coefficients,
        intercept=intercept,
        log_likelihood=log_likelihood,
        aic=aic,
        bic=bic,
        alpha=alpha,
        pearson_dispersion=_pearson_dispersion(endog, fitted, alpha, n_parameters),
        fitted_values=fitted,
        raw=results,
    )


def _extract(
    results: object,
    factor_columns: pd.Index,
) -> tuple[list[Coefficient], Coefficient | None, float | None]:
    params = results.params  # type: ignore[attr-defined]
    bse = results.bse  # type: ignore[attr-defined]
    pvalues = results.pvalues  # type: ignore[attr-defined]
    conf = results.conf_int()  # type: ignore[attr-defined]

    def build(name: str) -> Coefficient:
        estimate = float(params[name])
        std_error = float(bse[name])
        low, high = (float(conf.loc[name].iloc[0]), float(conf.loc[name].iloc[1]))
        return Coefficient(
            factor=name,
            estimate=estimate,
            std_error=std_error,
            z_value=estimate / std_error if std_error else float("nan"),
            p_value=float(pvalues[name]),
            ci_low=low,
            ci_high=high,
        )

    coefficients = [build(str(name)) for name in factor_columns if name in params.index]
    intercept = build(INTERCEPT) if INTERCEPT in params.index else None
    alpha = float(params[_ALPHA]) if _ALPHA in params.index else None
    return coefficients, intercept, alpha


def _converged(results: object) -> bool:
    retvals = getattr(results, "mle_retvals", None)
    if isinstance(retvals, dict) and "converged" in retvals:
        return bool(retvals["converged"])
    return bool(getattr(results, "converged", True))


def _pearson_dispersion(
    counts: pd.Series,
    fitted: pd.Series,
    alpha: float | None,
    n_parameters: int,
) -> float | None:
    """Pearson chi-squared per residual degree of freedom.

    For Poisson this is the overdispersion statistic that justifies moving to NB. For
    NB it should sit near 1 if the dispersion parameter is doing its job.
    """
    df_resid = len(counts) - n_parameters
    if df_resid <= 0:
        return None
    mu = fitted.to_numpy(dtype=float)
    variance = mu + (alpha * mu**2 if alpha else 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        contributions = (counts.to_numpy(dtype=float) - mu) ** 2 / variance
    contributions = contributions[np.isfinite(contributions)]
    if contributions.size == 0:
        return None
    return float(contributions.sum() / df_resid)


def _safe_float(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


__all__ = ["INTERCEPT", "fit_negative_binomial", "fit_poisson"]
