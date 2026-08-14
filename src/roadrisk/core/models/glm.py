"""Mode A rungs 0, 1 and 2 — Poisson, negative binomial, and the panel correction.

Rung 0, Poisson, is a **reference point, not an answer**. It measures overdispersion
and justifies the negative binomial. It is always run and it never reaches a client.

Rung 1, NB2, is the HSM standard and the Mode A baseline. Nothing else ships before it
works.

Rung 2 fixes the thing rung 1 gets wrong about a *panel*. The brief puts it plainly:
*the panel measures the same segment across many periods; plain NB treats those as
independent observations, and they are not.*

**On this panel that error is severe, because every factor is unit-constant.** Curvature,
gradient, lane count, every density — they are properties of a segment, repeated
unchanged down every period of that segment. A 50-unit corridor over 24 months has 1,200
rows and **50 independent observations of every covariate**. Rung 1 computes its standard
errors as though it had 1,200, so it reports a certainty it has not earned, and the
report says a factor is significant when the data cannot support that.

``ln(exposure)`` enters as an offset in all three — a coefficient fixed at 1, not
estimated. Exposure is structural and the ladder may never drop it.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import replace

import numpy as np
import pandas as pd
import statsmodels.api as sm

from roadrisk.core.diagnostics import Family
from roadrisk.core.models.base import Coefficient, FitResult

INTERCEPT = "const"
_ALPHA = "alpha"

#: Fewest units the clustered estimator will be applied to.
#:
#: The sandwich estimator is consistent as the number of *clusters* grows, not as the
#: number of rows grows. Below a couple of dozen units it is biased downwards — it would
#: report standard errors that are still too small while looking like it had fixed them,
#: which is worse than not applying it, because the caveat would be invisible.
#: Cameron and Miller's survey puts the danger zone here. The M51 corridor, with seven
#: units, sits squarely inside it.
MIN_CLUSTERS = 20

#: Below this the correction is applied but declared unreliable. Between twenty and
#: forty clusters the finite-sample adjustment is doing real work and the result should
#: be read as indicative.
FEW_CLUSTERS = 40


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


def fit_negative_binomial_panel(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    groups: pd.Series,
    *,
    min_clusters: int = MIN_CLUSTERS,
    few_clusters: int = FEW_CLUSTERS,
) -> FitResult:
    """Rung 2 — NB2 with standard errors clustered by unit.

    **The coefficients do not move.** This is the same NB2 fit rung 1 produces; only the
    covariance changes. That is deliberate, and it is what makes the upgrade legible: the
    report can put the two standard errors side by side and say exactly how much too
    certain the independent-rows fit was, without anybody having to trust a second set of
    estimates to find out.

    It is not the random-intercept GLMM the step names. A random intercept models the
    unobserved heterogeneity between segments and changes the estimates as well as their
    spread; this corrects the spread only. It is the cheap upgrade the brief asks for,
    and the module docstring records where the full version belongs.

    Args:
        counts: ``n_crashes``.
        design: Transformed design matrix.
        log_exposure: ``ln(length_km * duration_hours)``, the offset.
        groups: Unit id per row. The clusters.
        min_clusters: Below this the correction is declined, not silently applied.
        few_clusters: Below this it is applied and declared unreliable.

    Returns:
        A :class:`FitResult`. When the correction is declined the naive fit comes back
        instead, carrying a note that says so and estimates how wrong it is.
    """
    naive = _fit(
        counts,
        design,
        log_exposure,
        specification="Negative binomial (NB2) GLM",
        family=Family.NEGATIVE_BINOMIAL,
    )
    if not naive.converged or naive.raw is None:
        return naive

    aligned = pd.Series(groups).reset_index(drop=True)
    n_clusters = int(aligned.nunique())
    rows_per_cluster = len(counts) / n_clusters if n_clusters else 0.0

    if n_clusters < min_clusters:
        return replace(
            naive,
            n_clusters=n_clusters,
            notes=(
                f"Standard errors are NOT corrected for the panel. This corridor has "
                f"{n_clusters} unit(s) over {len(counts):,} rows, and clustering needs "
                f"at least {min_clusters} units before the estimator is trustworthy — "
                "below that it produces standard errors that are still too small while "
                "appearing to have fixed them. Every factor here is unit-constant, so "
                f"the effective sample size is {n_clusters}, not {len(counts):,}, and "
                "the intervals below are narrower than the data can support by "
                f"something of the order of {math.sqrt(rows_per_cluster):.1f}x. Treat "
                "significance on this corridor as unproven.",
            ),
        )

    # Refitting rather than re-covariancing an existing fit: statsmodels' discrete
    # results classes carry no `get_robustcov_results`, unlike its GLM ones, so the
    # covariance has to be chosen when the optimiser runs. The estimates are identical
    # either way — only the covariance differs — and a second NB2 optimisation on a
    # corridor panel costs a fraction of a second.
    clustered = _fit(
        counts,
        design,
        log_exposure,
        specification="Negative binomial (NB2) GLM, unit-clustered SEs",
        family=Family.NEGATIVE_BINOMIAL,
        cov_type="cluster",
        cov_kwds={"groups": aligned.to_numpy(), "use_correction": True},
    )
    if not clustered.converged:
        return replace(
            naive,
            n_clusters=n_clusters,
            notes=(
                "The clustered standard errors could not be computed "
                f"({clustered.failure_reason}), so the reported intervals are the naive "
                "ones and are too narrow for a panel.",
            ),
        )

    widening = _widening(naive, clustered.coefficients)
    before = {
        c.factor: float(c.std_error)
        for c in naive.coefficients
        if c.factor in widening
    }

    notes = [
        f"Standard errors are clustered by unit over {n_clusters} unit(s) and "
        f"{len(counts):,} rows. Every factor on this panel is a property of the segment "
        "repeated down every period, so the independent-rows fit was treating "
        f"{rows_per_cluster:.0f} copies of each observation as {rows_per_cluster:.0f} "
        "observations. The coefficients are unchanged; only the certainty is.",
    ]
    if widening:
        worst = max(widening, key=lambda name: widening[name])
        notes.append(
            f"The correction widened the intervals by up to {widening[worst]:.2f}x "
            f"({worst}). A factor that was significant before and is not now was never "
            "significant — the first fit was counting the same segment many times."
        )
    if n_clusters < few_clusters:
        notes.append(
            f"Only {n_clusters} clusters. The sandwich estimator is consistent in the "
            f"number of clusters, and below about {few_clusters} it is still biased "
            "downwards even after the finite-sample correction applied here. These "
            "intervals are wider than rung 1's and probably still too narrow."
        )

    return replace(
        clustered,
        n_clusters=n_clusters,
        cluster_widening=widening,
        naive_std_errors=before,
        notes=tuple(notes),
    )


def _widening(naive: FitResult, clustered: list[Coefficient]) -> dict[str, float]:
    """How much wider each clustered standard error is than the naive one."""
    widening: dict[str, float] = {}
    for coefficient in clustered:
        before = naive.coefficient(coefficient.factor)
        if before is None or before.std_error <= 0:
            continue
        widening[coefficient.factor] = float(
            coefficient.std_error / before.std_error
        )
    return widening


def _fit(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    *,
    specification: str,
    family: Family,
    cov_type: str | None = None,
    cov_kwds: dict[str, object] | None = None,
) -> FitResult:
    endog = counts.astype(float)
    exog = sm.add_constant(design.astype(float), has_constant="add")
    offset = log_exposure.astype(float).to_numpy()
    n_parameters = int(exog.shape[1]) + (1 if family is Family.NEGATIVE_BINOMIAL else 0)
    covariance = (
        {} if cov_type is None else {"cov_type": cov_type, "cov_kwds": cov_kwds or {}}
    )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if family is Family.POISSON:
                model = sm.GLM(
                    endog, exog, family=sm.families.Poisson(), offset=offset
                )
                results = model.fit(**covariance)
            else:
                model = sm.NegativeBinomialP(endog, exog, p=2, offset=offset)
                results = model.fit(disp=0, maxiter=200, **covariance)
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


__all__ = [
    "FEW_CLUSTERS",
    "INTERCEPT",
    "MIN_CLUSTERS",
    "fit_negative_binomial",
    "fit_negative_binomial_panel",
    "fit_poisson",
]
