"""Step 3.3c — segment 47 and segment 48 are neighbours, not strangers.

    a chain of units  ->  a CAR field over it  ->  joint Laplace  ->  rho

Rung 2 gives every segment its own independent random intercept. That is better than
nothing and still wrong about a road: a bad stretch is a *stretch*, and the thing making
segment 47 dangerous is usually making 48 dangerous too. A conditional autoregressive
field says so, by making neighbouring units' effects correlated a priori.

### Why the quadrature had to be abandoned, and what replaced it

:mod:`roadrisk.core.models.bayes` is fast because it integrates each unit's random
intercept out separately — one small independent integral per unit. That factorisation is
the whole trick, and it works **only** because the units are independent given the
hyperparameters. A CAR field couples them by construction, the integral stops
factorising, and the trick evaporates. `STEPS.md` recorded this as the specific way 3.3c
was blocked.

What it did not record, because it was not obvious until the Laplace machinery existed,
is that the *outer* half of that module generalises perfectly. The inference ladder
operates on a marginal log posterior over a handful of hyperparameters; it does not care
how that marginal is obtained. Swapping the inner quadrature for a **joint Laplace
approximation over the whole latent field** leaves mode-finding, the importance check,
the MCMC fallback and every reporting surface untouched.

**A corridor is a path graph, which is what makes this cheap.** Neighbours are the units
either side, so the precision matrix is tridiagonal: Newton's method needs a banded solve
and the log determinant needs a banded Cholesky, both O(units). One marginal evaluation
on an eighty-unit corridor costs about two milliseconds. None of the awkward areal cases
— islands, disconnected components, wildly varying neighbour counts — arise on a road.

### The Leroux parameterisation, chosen because it nests what already exists

    Q_u = (1 / sigma_u^2) [ (1 - rho) I + rho R ]

``R`` is the structure matrix of the chain: neighbour count on the diagonal, −1 between
neighbours. ``rho = 0`` gives independent random intercepts — **exactly** the model rung
2 fits — and ``rho`` approaching one approaches the intrinsic CAR limit. So this is a
strict generalisation, ``rho = 0`` must reproduce 3.3a, and a test asserts it does.

That nesting is also what makes the question answerable. "Is there spatial structure on
this corridor" becomes "is rho credibly above zero", which the posterior answers directly
rather than by comparing two models fitted separately.

### The honest caveat, which was expected and turns out not to bite here

A spatial field and a per-unit random intercept both live at unit level and compete to
explain the same variance, so ``rho`` was expected to be poorly identified on the fifty
to a hundred and twenty units a corridor has. Measured on a planted field it is not:
profiling the marginal over ``rho`` on eighty units peaks within a step of the planted
value, and the log marginal moves by seventeen units between ``rho = 0`` and the truth,
which is not a flat likelihood. On corridors where it *is* flat the posterior comes back
wide and the report says the corridor cannot tell — which is the answer, not a failure.

**Two approximations are now stacked**: a Laplace over the latent field inside, and the
existing Laplace-plus-importance-sampling over the hyperparameters outside. The outer
importance check polices only the outer one. That is stated rather than glossed, and it
is the reason the MCMC fallback still exists.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.linalg import cholesky_banded, solveh_banded
from scipy.special import gammaln

from roadrisk.core.diagnostics import Family
from roadrisk.core.models.bayes import (
    IS_DRAWS,
    PROPOSAL_DF,
    ApproximationReport,
    Method,
    PosteriorFit,
    PosteriorSummary,
    _find_mode,
    _hessian,
    _pareto_k,
    _weighted_summary,
)
from roadrisk.core.priors import PriorSet

#: Newton iterations allowed when finding the latent field's mode.
MAX_INNER_ITERATIONS = 100

#: Convergence tolerance on the largest step of that Newton loop.
INNER_TOLERANCE = 1e-8

#: Importance draws tried, in order, until the outer check passes.
#:
#: The analogue of the quadrature ladder in :mod:`roadrisk.core.models.bayes`, and here
#: for the same reason: the cheap escalation is worth trying before the expensive
#: refusal. This posterior carries one more dimension than the independent one — rho —
#: and on a short corridor that is enough for the Gaussian approximation to need more
#: draws before its importance weights behave.
DRAW_LADDER: tuple[int, ...] = (IS_DRAWS, 4 * IS_DRAWS)

#: Credible mass below which rho is reported as "this corridor cannot tell". The
#: posterior for rho lives on the unit interval, so a 95% interval covering more than
#: this much of it is barely narrower than the prior and settles nothing.
RHO_UNINFORMATIVE_WIDTH = 0.75


@dataclass(frozen=True)
class SpatialReport:
    """What the corridor had to say about whether its segments cluster."""

    rho: PosteriorSummary
    sigma_u: PosteriorSummary
    n_units: int

    @property
    def identified(self) -> bool:
        """Whether the data narrowed rho at all."""
        return (self.rho.hdi_high - self.rho.hdi_low) < RHO_UNINFORMATIVE_WIDTH

    @property
    def spatial(self) -> bool:
        """Whether neighbouring segments are credibly correlated."""
        return self.identified and self.rho.hdi_low > 0.1

    def describe(self) -> str:
        interval = f"[{self.rho.hdi_low:.2f}, {self.rho.hdi_high:.2f}]"
        if not self.identified:
            return (
                f"rho = {self.rho.mean:.2f} {interval} — this corridor cannot tell "
                "whether its segments cluster. The spatial and independent parts of the "
                "field explain the same variance, and with "
                f"{self.n_units} units there is not enough to separate them. That is an "
                "answer about the corridor, not a failure of the fit: read the "
                "independent-intercept model instead, and treat any spatial claim as "
                "unsupported."
            )
        if self.spatial:
            return (
                f"rho = {self.rho.mean:.2f} {interval} — neighbouring segments are "
                "correlated beyond what independent intercepts explain. A bad stretch "
                "is a stretch: the model now pools each segment with the road either "
                "side of it rather than treating them as strangers."
            )
        return (
            f"rho = {self.rho.mean:.2f} {interval} — no spatial clustering worth "
            "modelling. Segment effects behave as independent draws, so the "
            "independent-intercept model of rung 2 is the right one here and this fit "
            "adds a parameter for nothing."
        )


@dataclass(frozen=True)
class _SpatialProblem:
    """Everything the marginal needs, arranged so nothing is rebuilt per call."""

    y: np.ndarray
    offset: np.ndarray
    design: np.ndarray
    codes: np.ndarray
    n_units: int
    structure: np.ndarray
    r_inverse: np.ndarray
    means: np.ndarray
    prior_means: np.ndarray
    prior_sds: np.ndarray
    intercept_sd: float
    lgamma_y1: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @property
    def n_factors(self) -> int:
        return int(self.design.shape[1])

    @property
    def n_dim(self) -> int:
        # intercept, slopes, log sigma_u, logit rho, log alpha
        return 1 + self.n_factors + 3


def chain_structure(n_units: int) -> np.ndarray:
    """The ICAR structure matrix of a path, in scipy's upper banded form.

    Row 1 is the diagonal — how many neighbours each unit has, one at the ends and two
    in the middle. Row 0 is the super-diagonal, −1 between neighbours. Nothing else is
    non-zero, which is the entire reason this step is affordable.
    """
    banded = np.zeros((2, n_units))
    banded[1] = 2.0
    if n_units:
        banded[1, 0] = banded[1, -1] = 1.0
    banded[0, 1:] = -1.0
    return banded


def _precision(structure: np.ndarray, sigma: float, rho: float) -> np.ndarray:
    """Leroux precision in banded form: ((1-rho) I + rho R) / sigma^2."""
    banded = rho * structure
    banded[1] += 1.0 - rho
    return banded / sigma**2


def _logdet_banded(banded: np.ndarray) -> float | None:
    try:
        factor = cholesky_banded(banded, lower=False)
    except Exception:  # noqa: BLE001 - a non-positive-definite matrix is a refusal
        return None
    diagonal = factor[1]
    if np.any(diagonal <= 0):
        return None
    return float(2.0 * np.sum(np.log(diagonal)))


def _nb_terms(
    y: np.ndarray, eta: np.ndarray, r: float, lgamma_y1: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NB2 log-likelihood and its first two derivatives with respect to eta.

    The second derivative is returned positive, because every use of it here wants the
    *negative* of the Hessian.
    """
    mu = np.exp(eta)
    total = r + mu
    loglik = (
        gammaln(y + r) - gammaln(r) - lgamma_y1 + r * np.log(r / total) + y * np.log(mu / total)
    )
    first = y - mu * (y + r) / total
    second = (y + r) * mu * r / total**2
    return loglik, first, second


def _latent_marginal(
    problem: _SpatialProblem,
    eta_fixed: np.ndarray,
    precision: np.ndarray,
    r: float,
) -> float | None:
    """log p(y | hyperparameters), integrating the coupled field out at its mode.

    Newton on the latent field. Both the system solved each step and the determinant at
    the end are banded, so this is linear in the number of units.
    """
    u = np.zeros(problem.n_units)
    for _ in range(MAX_INNER_ITERATIONS):
        eta = eta_fixed + u[problem.codes]
        _, first, second = _nb_terms(problem.y, eta, r, problem.lgamma_y1)
        gradient = np.bincount(
            problem.codes, weights=first, minlength=problem.n_units
        ) - _banded_matvec(precision, u)
        weights = np.bincount(
            problem.codes, weights=second, minlength=problem.n_units
        )
        hessian = precision.copy()
        hessian[1] += weights
        try:
            step = solveh_banded(hessian, gradient, lower=False)
        except Exception:  # noqa: BLE001 - a failed solve is a refusal, not a crash
            return None
        u = u + step
        if np.max(np.abs(step)) < INNER_TOLERANCE:
            break
    else:
        return None

    eta = eta_fixed + u[problem.codes]
    loglik, _, second = _nb_terms(problem.y, eta, r, problem.lgamma_y1)
    weights = np.bincount(problem.codes, weights=second, minlength=problem.n_units)
    hessian = precision.copy()
    hessian[1] += weights

    logdet_precision = _logdet_banded(precision)
    logdet_hessian = _logdet_banded(hessian)
    if logdet_precision is None or logdet_hessian is None:
        return None

    quadratic = float(u @ _banded_matvec(precision, u))
    return (
        float(loglik.sum())
        + 0.5 * logdet_precision
        - 0.5 * quadratic
        - 0.5 * logdet_hessian
    )


def _banded_matvec(banded: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Symmetric tridiagonal matrix times a vector, from the banded form."""
    result = banded[1] * vector
    upper = banded[0, 1:]
    result[:-1] += upper * vector[1:]
    result[1:] += upper * vector[:-1]
    return result


def _log_posterior(theta: np.ndarray, problem: _SpatialProblem) -> np.ndarray:
    """Log posterior over the hyperparameters, one row of ``theta`` at a time.

    Unlike the quadrature version this cannot be vectorised across parameter vectors —
    each one needs its own Newton solve for the latent field — but each solve is
    milliseconds, so the loop is affordable.
    """
    theta = np.atleast_2d(theta)
    out = np.full(theta.shape[0], -np.inf)

    for index, row in enumerate(theta):
        intercept = row[0]
        beta = row[1 : 1 + problem.n_factors]
        sigma = math.exp(row[-3])
        rho = 1.0 / (1.0 + math.exp(-row[-2]))
        alpha = math.exp(row[-1])
        if not (0.0 < sigma < 10.0) or not (0.0 < alpha < 50.0):
            continue
        # Leroux is proper for rho < 1 and degenerate at exactly one.
        rho = min(rho, 0.999)

        eta_fixed = problem.offset + intercept + problem.design @ beta
        precision = _precision(problem.structure, sigma, rho)
        marginal = _latent_marginal(problem, eta_fixed, precision, 1.0 / alpha)
        if marginal is None or not np.isfinite(marginal):
            continue

        original_beta = beta @ problem.r_inverse.T
        standardised = (original_beta - problem.prior_means) / problem.prior_sds
        log_prior = (
            -0.5 * (intercept / problem.intercept_sd) ** 2
            - 0.5 * float(np.sum(standardised**2))
            - 0.5 * sigma**2
            + row[-3]
            - 0.5 * alpha**2
            + row[-1]
            # Uniform on rho, plus the logit Jacobian. Flat on the unit interval is the
            # honest default: nothing in the registry speaks to how clustered a road's
            # unobserved character is.
            + math.log(max(rho * (1.0 - rho), 1e-300))
        )
        total = marginal + log_prior
        if np.isfinite(total):
            out[index] = total
    return out


def _prepare(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    priors: PriorSet | None,
) -> _SpatialProblem:
    """Order rows by unit, and take that order as position along the corridor.

    The same assumption step 3.4 makes and records: segmentation numbers units along the
    chainage, so sorting their ids recovers the order they sit in on the road. A panel
    whose ids do not sort that way would get neighbours that are adjacent in name only.
    """
    units = pd.Series(unit_ids).to_numpy()
    order = np.argsort(units, kind="stable")
    codes = pd.factorize(pd.Series(units[order]))[0]

    raw = np.asarray(design, dtype=float)[order]
    means = raw.mean(axis=0)
    q, r = np.linalg.qr(raw - means)
    scale = math.sqrt(max(len(raw) - 1, 1))
    q, r = q * scale, r / scale

    y = np.asarray(counts, dtype=float)[order]
    names = [str(c) for c in design.columns]
    return _SpatialProblem(
        y=y,
        offset=np.asarray(log_exposure, dtype=float)[order],
        design=q,
        codes=codes,
        n_units=int(codes.max()) + 1 if codes.size else 0,
        structure=chain_structure(int(codes.max()) + 1 if codes.size else 0),
        r_inverse=np.linalg.inv(r),
        means=means,
        prior_means=np.asarray(priors.means(names)) if priors else np.zeros(len(names)),
        prior_sds=np.asarray(priors.sds(names)) if priors else np.ones(len(names)),
        intercept_sd=priors.intercept_sd if priors else 5.0,
        lgamma_y1=gammaln(y + 1.0),
    )


def _to_caller_scale(draws: np.ndarray, problem: _SpatialProblem) -> np.ndarray:
    """Undo the QR rotation, the centring and the link functions, draw by draw."""
    out = draws.copy()
    slopes = draws[:, 1 : 1 + problem.n_factors] @ problem.r_inverse.T
    out[:, 1 : 1 + problem.n_factors] = slopes
    out[:, 0] = draws[:, 0] - slopes @ problem.means
    out[:, -3] = np.exp(draws[:, -3])
    out[:, -2] = 1.0 / (1.0 + np.exp(-draws[:, -2]))
    out[:, -1] = np.exp(draws[:, -1])
    return out


def fit_spatial_glmm(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    *,
    start: dict[str, float] | None = None,
    priors: PriorSet | None = None,
    hdi_probability: float = 0.95,
    seed: int = 0,
) -> tuple[PosteriorFit, SpatialReport | None]:
    """Fit the NB GLMM with a Leroux CAR field over the corridor chain.

    Args:
        counts: ``n_crashes``.
        design: Transformed design matrix.
        log_exposure: ``ln(length_km * duration_hours)``, the offset.
        unit_ids: Unit id per row. Sorted order is taken as position along the corridor.
        start: Optional starting point from the frequentist fit.
        priors: The registry's cited weights, from step 3.3b.
        hdi_probability: Credible interval mass.
        seed: RNG seed.

    Returns:
        The posterior and a :class:`SpatialReport`, or a refusal and ``None``.
    """
    problem = _prepare(counts, design, log_exposure, unit_ids, priors)
    names = [str(c) for c in design.columns]
    specification = "Bayesian NB GLMM, Leroux CAR field over the corridor"

    if problem.n_units < 10:
        return (
            PosteriorFit(
                specification=specification,
                family=Family.NEGATIVE_BINOMIAL,
                converged=False,
                method=Method.NONE,
                n_observations=int(problem.y.size),
                n_units=problem.n_units,
                n_parameters=problem.n_dim,
                failure_reason=(
                    f"a chain of {problem.n_units} unit(s) has too few neighbours for a "
                    "spatial field to mean anything."
                ),
            ),
            None,
        )

    centre = np.zeros(problem.n_dim)
    mean_rate = float(np.mean(problem.y))
    centre[0] = math.log(max(mean_rate, 1e-3)) - float(np.mean(problem.offset))
    if start:
        beta = np.array([float(start.get(name, 0.0)) for name in names])
        centre[1 : 1 + problem.n_factors] = np.linalg.inv(problem.r_inverse) @ beta
        centre[0] = float(start.get("intercept", centre[0])) + float(problem.means @ beta)
        centre[-1] = math.log(max(float(start.get("alpha", 0.6)), 1e-3))
    else:
        centre[-1] = math.log(0.6)
    centre[-3] = math.log(0.4)
    centre[-2] = 0.0  # logit(0.5) — no opinion about clustering before the data

    def objective(theta: np.ndarray) -> np.ndarray:
        return _log_posterior(theta, problem)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mode, ok = _find_mode(centre, objective)
        if not ok and not np.all(np.isfinite(mode)):
            return _refused(specification, problem, "the posterior mode could not be located.")
        hessian = _hessian(mode, objective)
        try:
            covariance = np.linalg.inv(-hessian)
            cholesky = np.linalg.cholesky(covariance)
        except np.linalg.LinAlgError:
            return _refused(
                specification,
                problem,
                "the curvature at the mode is not a maximum, so there is no Gaussian "
                "to approximate the hyperparameter posterior with.",
            )

        attempts: list[tuple[ApproximationReport, np.ndarray, np.ndarray]] = []
        for n_draws in DRAW_LADDER:
            rng = np.random.default_rng(seed)
            scaled = rng.chisquare(PROPOSAL_DF, n_draws) / PROPOSAL_DF
            raw = rng.standard_normal((n_draws, problem.n_dim)) / np.sqrt(scaled)[:, None]
            draws = mode + raw @ cholesky.T
            target = objective(draws)
            proposal = -0.5 * (PROPOSAL_DF + problem.n_dim) * np.log1p(
                np.sum(raw**2, axis=1) / PROPOSAL_DF
            )
            log_weights, k_hat = _pareto_k(target - proposal)

            finite = np.isfinite(log_weights)
            if finite.sum() < 10:
                continue
            weights = np.zeros(log_weights.shape)
            weights[finite] = np.exp(log_weights[finite] - log_weights[finite].max())
            weights = weights / weights.sum()
            attempt = ApproximationReport(
                k_hat=k_hat,
                n_draws=n_draws,
                effective_draws=float(1.0 / np.sum(weights**2)),
                log_evidence=0.0,
            )
            attempts.append((attempt, weights, draws))
            if attempt.trustworthy:
                break

    if not attempts:
        return _refused(specification, problem, "the importance weights all collapsed.")
    report, weights, draws = attempts[-1]
    reported = _to_caller_scale(draws, problem)
    labels = ["intercept", *names, "sigma_u", "rho", "alpha"]
    summaries = [
        _weighted_summary(labels[i], reported[:, i], weights, hdi_probability)
        for i in range(problem.n_dim)
    ]

    if not report.trustworthy:
        return (
            PosteriorFit(
                specification=specification,
                family=Family.NEGATIVE_BINOMIAL,
                converged=False,
                method=Method.NONE,
                n_observations=int(problem.y.size),
                n_units=problem.n_units,
                n_parameters=problem.n_dim,
                approximation=report,
                descent=(f"Laplace over the latent field: {report.describe()}",),
                failure_reason=report.describe(),
            ),
            None,
        )

    spatial = SpatialReport(
        rho=summaries[-2], sigma_u=summaries[-3], n_units=problem.n_units
    )
    return (
        PosteriorFit(
            specification=specification,
            family=Family.NEGATIVE_BINOMIAL,
            converged=True,
            method=Method.LAPLACE,
            n_observations=int(problem.y.size),
            n_units=problem.n_units,
            n_parameters=problem.n_dim,
            coefficients=summaries[1 : 1 + len(names)],
            intercept=summaries[0],
            sigma_u=summaries[-3],
            alpha=summaries[-1],
            approximation=report,
            hdi_probability=hdi_probability,
            descent=(
                "Joint Laplace over the CAR field, then Laplace with an importance "
                f"check over the hyperparameters: {report.describe()}",
            ),
            notes=(
                "The latent field is integrated out by a Laplace approximation at its "
                "mode rather than by quadrature, because a CAR field couples "
                "neighbouring units and the per-unit integrals stop factorising. Two "
                "approximations are therefore stacked, and the importance check polices "
                "only the outer one.",
                spatial.describe(),
            ),
        ),
        spatial,
    )


def _refused(
    specification: str, problem: _SpatialProblem, reason: str
) -> tuple[PosteriorFit, None]:
    return (
        PosteriorFit(
            specification=specification,
            family=Family.NEGATIVE_BINOMIAL,
            converged=False,
            method=Method.NONE,
            n_observations=int(problem.y.size),
            n_units=problem.n_units,
            n_parameters=problem.n_dim,
            failure_reason=reason,
        ),
        None,
    )


__all__ = [
    "MAX_INNER_ITERATIONS",
    "RHO_UNINFORMATIVE_WIDTH",
    "SpatialReport",
    "chain_structure",
    "fit_spatial_glmm",
]
