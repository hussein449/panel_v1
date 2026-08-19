"""Rung 2, done properly — a Bayesian NB GLMM with a random intercept per unit.

    Laplace  ->  importance check  ->  (only if it fails) MCMC  ->  credible intervals

**What this fixes that 3.1 could not.** Clustering corrects the *spread* of the
estimates and leaves the estimates alone. A random intercept models the unobserved
persistent character of each segment — the bad junction layout, the school, the
drainage — so it changes the estimates too, and it pools information between segments
instead of trusting each one on its own.

**Credible intervals, not p-values.** A p-value answers "how surprising would this data
be if the effect were exactly zero", which is not the question anybody asks. A credible
interval answers "where is the effect, given this data", and on the small counts this
product exists for, that distinction stops being academic. The result type carries no
p-value at all.

### Why the random intercepts are integrated out rather than sampled

A 120-unit corridor has 120 random intercepts, so treating them as parameters is a
130-dimensional problem. Integrating each unit's intercept out by Gauss-Hermite
quadrature — a one-dimensional integral per unit, all independent given the
hyperparameters — leaves **eight or so parameters**. That is the strategy INLA is built
on, and the brief names INLA as an acceptable engine for this rung.

### The inference ladder, and why there is one

The same shape as the mode ladder and the rung ladder: try the good cheap thing, test
whether it was good enough, descend if not, and say so.

======  =============================  ==============================================
Step    Method                         Descends when
======  =============================  ==============================================
1       Laplace + importance sampling  the importance weights say the approximation
                                       is not trustworthy (Pareto k-hat above 0.7)
2       MCMC, warm-started from 1      the chains do not mix
3       refuse                         — nothing is reported
======  =============================  ==============================================

**Step 1 costs seconds and almost always wins.** Find the posterior mode, take the
curvature there, and you have a Gaussian approximation to the posterior. Then draw from
that Gaussian and re-weight the draws by the true posterior: the re-weighted draws are
the answer, and **the weights themselves say whether the approximation deserved to be
trusted.** Even weights mean the Gaussian was a good fit; one weight carrying everything
means it was not. That is Pareto-smoothed importance sampling and its k-hat statistic
(Vehtari et al.), and it makes the honesty check part of the fit rather than a separate
ritual somebody has to remember to run.

**Step 2 exists because step 1 can fail.** An ensemble sampler was the first thing built
here and on its own it was marginal: R-hat stuck at 1.017 against a 1.01 threshold after
a QR rotation, a mean-corrected random effect and 4,500 iterations, because affine
ensemble moves mix poorly past about ten dimensions. Warm-started from the Laplace mode
*and its covariance*, it starts in the right place with the right step shape, which is
exactly what it was missing.

**The threshold is not negotiable to make a fit pass.** R-hat 1.01 is the Vehtari et al.
(2021) recommendation and k-hat 0.7 is the PSIS one. Relaxing either to get a green
light would make every downstream number a lie of a kind this package refuses
everywhere else.

### A wrong diagnosis, recorded because it nearly shipped

Step 1 was at first refused on every wide panel — k-hat 0.76 to 0.84 at eleven
parameters, against 0.58 at eight — and the obvious reading was dimension. Importance
sampling really does lose efficiency exponentially as dimension grows, the numbers lined
up with that story, and nine combinations of proposal degrees of freedom and scale
inflation failed to rescue the eleven-dimensional case. The boundary was about to be
written down as a property of the method.

It was **quadrature error**. Every one of those runs used twelve nodes. Fixing that
alone, at unchanged dimension:

======================  ======  ==============  ==============
Specification           Dims    k-hat, 12 nodes k-hat, laddered
======================  ======  ==============  ==============
A-reduced, 5 factors    8       0.58            0.24
A-full, 8 factors       11      0.76-0.84       0.07-0.32
======================  ======  ==============  ==============

Dimension was never the binding constraint. The lesson worth keeping is not about
splines or samplers: **a plausible mechanism that predicts the observed numbers is not
therefore the mechanism**, and the tell was that more data made things worse, which
dimension does not explain and accumulating per-unit error does.

Step 2 now almost never runs. It stays because "almost never" is not "never".

### The consequence of marginalising, stated plainly because it constrains 3.3c

Marginalising works **only because each unit's effect is independent of every other
unit's** once the hyperparameters are fixed. A spatial CAR/BYM field is the opposite:
neighbouring segments are coupled by construction, and the integral no longer
factorises into one-dimensional pieces. **The quadrature in this module cannot be
extended to spatial structure** — but the Laplace machinery can, because approximating a
coupled latent Gaussian field at its mode is precisely what it is for. See the note in
``STEPS.md`` under 3.3c.

### The dispersion parameter is in statsmodels' convention, end to end

``alpha`` here is always the NB2 parameter of ``var = mu + alpha * mu**2``, matching
:mod:`roadrisk.core.models.glm` and every number the rest of the package reports.
Several libraries use the reciprocal. Mixing the two silently produces a dispersion
wrong by a factor of ``alpha**2`` and nothing anywhere complains, so the convention is
asserted by a test rather than trusted to a comment.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd
from scipy.special import gammaln, logsumexp

from roadrisk.core.diagnostics import Family

#: Quadrature nodes tried for the per-unit integral, in order, until the importance
#: check passes.
#:
#: **This escalates because twelve nodes was not enough and that was measured, not
#: guessed.** The first version fixed it at twelve on the reasoning that the marginal
#: likelihood stops moving well before then, which is true and beside the point: the
#: likelihood settles to the eye long before it settles to the precision importance
#: weights need. A weight is a ratio of two log-posteriors, so quadrature error that is
#: invisible in the fit is not invisible in the weights, and it accumulates across
#: units. On a 60-unit panel:
#:
#: ===== ========= =================
#: Nodes k-hat     Effective draws
#: ===== ========= =================
#: 12    1.10      29 of 8,000
#: 20    0.87      277
#: 32    0.64      1,065
#: 48    0.11      5,829
#: ===== ========= =================
#:
#: Cost is linear in the node count and accuracy plainly is not, so it is cheaper to
#: start low, check, and add nodes than to pay for the worst case every time — and far
#: cheaper than descending to an MCMC run that takes minutes.
NODE_LADDER: tuple[int, ...] = (24, 48, 96)

#: Entry point of that ladder, and what a caller gets if they pass ``n_nodes``.
DEFAULT_NODES = NODE_LADDER[0]

#: Pareto k-hat above which the Laplace approximation is not trusted and the ladder
#: descends. 0.7 is the PSIS threshold: above it the importance-weight distribution has
#: infinite variance and the re-weighted estimate has no reliable error.
KHAT_THRESHOLD = 0.7

#: Draws taken from the Laplace approximation for the importance step. Enough for a
#: stable 95% interval and for k-hat itself to be estimated from a decent tail.
IS_DRAWS = 8000

#: Degrees of freedom for the multivariate-t proposal. Low enough that the tails are
#: comfortably heavier than the target's, high enough that the bulk still matches the
#: curvature at the mode. Seven is the usual choice and was not tuned to pass a test.
PROPOSAL_DF = 7

#: Rank-normalised split-R-hat above which chains have not mixed. 1.01 is the Vehtari
#: et al. (2021) recommendation, stricter than the older 1.1 which was shown to pass
#: visibly unconverged chains.
RHAT_THRESHOLD = 1.01

#: Effective sample size below which interval endpoints are too noisy to report.
ESS_THRESHOLD = 400

#: MCMC defaults, used only when the ladder descends to step 2.
#:
#: Measured rather than guessed, and they are large because they had to be: on a
#: five-factor panel this sampler needed 16,000 iterations to reach R-hat 1.003, and at
#: 4,500 it sat at 1.017 — over the threshold, having already been helped by a QR
#: rotation and a mean-corrected random effect. Ensemble moves are simply not efficient
#: here. Step 2 costs minutes, which is why step 1 exists.
DEFAULT_DRAWS = 12000
DEFAULT_TUNE = 4000
DEFAULT_WALKER_MULTIPLE = 4

#: Elements allowed in one working array of the log posterior, which is
#: ``walkers x rows x nodes``. The batch is split to respect this rather than split at a
#: fixed walker count, because the right number of walkers per call depends entirely on
#: the panel: a short corridor at 24 nodes fits its whole ensemble in one call, while a
#: long one at 96 nodes does not.
#:
#: A fixed chunk of 16 was the first version and it was quietly wasteful — an ensemble of
#: 24 walkers went through as 16 and then 8, and the second call paid nearly a full
#: call's overhead for half a call's work. Eight million elements is about 64 MB per
#: temporary, and there are a handful of them live at once.
ELEMENT_BUDGET = 8_000_000


class Method(StrEnum):
    """Which rung of the inference ladder produced the answer."""

    LAPLACE = "laplace+is"
    MCMC = "mcmc"
    NONE = "none"


@dataclass(frozen=True)
class PosteriorSummary:
    """One parameter's posterior. There is deliberately no p-value on this type."""

    name: str
    mean: float
    sd: float
    hdi_low: float
    hdi_high: float
    prob_positive: float
    #: MCMC only. ``None`` from the Laplace rung, which has no chains to compare.
    r_hat: float | None = None
    ess_bulk: float | None = None

    @property
    def excludes_zero(self) -> bool:
        """Whether the credible interval is entirely on one side of zero."""
        return (self.hdi_low > 0.0) or (self.hdi_high < 0.0)

    @property
    def prob_negative(self) -> float:
        return 1.0 - self.prob_positive

    @property
    def sign(self) -> int:
        if self.mean > 0:
            return 1
        if self.mean < 0:
            return -1
        return 0

    def probability_of_sign(self, expected: int) -> float:
        """Posterior mass in the declared direction.

        This is what replaces the p-value in the sign guard: not "could this be zero"
        but "how much of the posterior agrees with what we expected". A factor at 0.51
        is a coin toss whatever its interval looks like.
        """
        return self.prob_positive if expected > 0 else self.prob_negative


@dataclass(frozen=True)
class ApproximationReport:
    """How far the Laplace approximation could be trusted."""

    k_hat: float
    n_draws: int
    effective_draws: float
    log_evidence: float

    @property
    def tails_behaved(self) -> bool:
        return math.isfinite(self.k_hat) and self.k_hat <= KHAT_THRESHOLD

    @property
    def enough_draws(self) -> bool:
        """Two gates, not one, for the same reason the MCMC rung has two.

        k-hat says the *shape* was right. It says nothing about whether enough draws
        survived re-weighting to place an interval endpoint. At k-hat 0.67 — passing —
        this fit kept 256 draws of 4,000, and its 2.5% endpoints visibly disagreed with
        a long MCMC run whose means it matched to 0.02. A mean is easy; a tail is what
        the draws are for.
        """
        return self.effective_draws >= ESS_THRESHOLD

    @property
    def trustworthy(self) -> bool:
        return self.tails_behaved and self.enough_draws

    def describe(self) -> str:
        if self.trustworthy:
            return (
                f"The Gaussian approximation held: Pareto k-hat {self.k_hat:.2f} "
                f"(threshold {KHAT_THRESHOLD}), {self.effective_draws:,.0f} effective "
                f"draws of {self.n_draws:,}. The importance weights are even enough "
                "that the re-weighted posterior can be believed."
            )
        problems = []
        if not self.tails_behaved:
            problems.append(
                f"Pareto k-hat {self.k_hat:.2f} is above {KHAT_THRESHOLD}, so a few "
                "draws carry most of the weight and the re-weighted estimate has no "
                "reliable error"
            )
        if not self.enough_draws:
            problems.append(
                f"only {self.effective_draws:,.0f} of {self.n_draws:,} draws survived "
                f"re-weighting, against the {ESS_THRESHOLD:,} needed to place an "
                "interval endpoint rather than just a mean"
            )
        return (
            "The Gaussian approximation did NOT hold: "
            + ", and ".join(problems)
            + ". The posterior is not shaped like the curvature at its mode suggests — "
            "usually skew in the variance parameters. Descending to MCMC."
        )


@dataclass(frozen=True)
class ConvergenceReport:
    """Whether the sampler can be believed. Only produced by the MCMC rung."""

    n_draws: int
    n_walkers: int
    n_tune: int
    max_r_hat: float
    min_ess_bulk: float
    acceptance: float
    worst_r_hat_parameter: str
    worst_ess_parameter: str

    @property
    def mixed(self) -> bool:
        return self.max_r_hat <= RHAT_THRESHOLD

    @property
    def enough_draws(self) -> bool:
        return self.min_ess_bulk >= ESS_THRESHOLD

    @property
    def converged(self) -> bool:
        return self.mixed and self.enough_draws

    def describe(self) -> str:
        if self.converged:
            return (
                f"Converged — R-hat at most {self.max_r_hat:.3f} and at least "
                f"{self.min_ess_bulk:,.0f} effective draws over {self.n_walkers} "
                "walkers."
            )
        problems = []
        if not self.mixed:
            problems.append(
                f"the chains have not mixed (R-hat {self.max_r_hat:.3f} on "
                f"'{self.worst_r_hat_parameter}', needs {RHAT_THRESHOLD})"
            )
        if not self.enough_draws:
            problems.append(
                f"there are too few effective draws ({self.min_ess_bulk:,.0f} on "
                f"'{self.worst_ess_parameter}', needs {ESS_THRESHOLD:,})"
            )
        return (
            "NOT converged — " + " and ".join(problems) + ". Nothing from this fit is "
            "reported: an interval from chains that have not mixed is not an interval, "
            "it is a picture of where the sampler happened to be. Raising `draws` is "
            "the first thing to try."
        )


@dataclass(frozen=True)
class PosteriorFit:
    """A fitted Bayesian GLMM.

    Carries no p-value, no z statistic and no standard error on a coefficient — the
    quantities a frequentist report is built from do not exist here, and the type is
    the place to say so.
    """

    specification: str
    family: Family
    converged: bool
    method: Method
    n_observations: int
    n_units: int
    n_parameters: int
    coefficients: list[PosteriorSummary] = field(default_factory=list)
    intercept: PosteriorSummary | None = None
    #: Between-segment standard deviation on the log rate. The quantity rungs 1 and 2
    #: could not estimate at all: how much persistent character segments carry.
    sigma_u: PosteriorSummary | None = None
    alpha: PosteriorSummary | None = None
    approximation: ApproximationReport | None = None
    convergence: ConvergenceReport | None = None
    hdi_probability: float = 0.95
    #: Quadrature nodes the answer was produced at. Exposed rather than left in the
    #: descent prose because anything comparing two fits has to put them on the same
    #: target: a different node count is a slightly different marginal posterior, so a
    #: reference run that does not match this one is not a reference for it.
    n_nodes: int = DEFAULT_NODES
    #: One line per rung attempted, in order — the receipt pattern the rest of the
    #: engine uses. A reader can see that the cheap method was tried and why it lost.
    descent: tuple[str, ...] = ()
    failure_reason: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def factor_names(self) -> list[str]:
        return [c.name for c in self.coefficients]

    def coefficient(self, factor: str) -> PosteriorSummary | None:
        return next((c for c in self.coefficients if c.name == factor), None)

    def as_dict(self) -> dict[str, object]:
        def summary(item: PosteriorSummary | None) -> dict[str, float | None] | None:
            if item is None:
                return None
            return {
                "mean": item.mean,
                "sd": item.sd,
                "hdi_low": item.hdi_low,
                "hdi_high": item.hdi_high,
                "prob_positive": item.prob_positive,
                "r_hat": item.r_hat,
                "ess_bulk": item.ess_bulk,
            }

        return {
            "specification": self.specification,
            "method": self.method.value,
            "converged": self.converged,
            "n_observations": self.n_observations,
            "n_units": self.n_units,
            "n_nodes": self.n_nodes,
            "hdi_probability": self.hdi_probability,
            "coefficients": {c.name: summary(c) for c in self.coefficients},
            "intercept": summary(self.intercept),
            "sigma_u": summary(self.sigma_u),
            "alpha": summary(self.alpha),
            "approximation": (
                {
                    "k_hat": self.approximation.k_hat,
                    "effective_draws": self.approximation.effective_draws,
                    "trustworthy": self.approximation.trustworthy,
                    "message": self.approximation.describe(),
                }
                if self.approximation
                else None
            ),
            "convergence": (
                {
                    "converged": self.convergence.converged,
                    "max_r_hat": self.convergence.max_r_hat,
                    "min_ess_bulk": self.convergence.min_ess_bulk,
                    "acceptance": self.convergence.acceptance,
                    "message": self.convergence.describe(),
                }
                if self.convergence
                else None
            ),
            "descent": list(self.descent),
            "failure_reason": self.failure_reason,
            "notes": list(self.notes),
        }


# ---- the model ---------------------------------------------------------------


@dataclass(frozen=True)
class _Problem:
    """Everything the log posterior needs, arranged so it never re-sorts per call.

    ``design`` here is **not** the caller's design matrix. It is centred and then
    QR-decomposed, and inference works on the orthonormal ``Q``. Two reasons, both
    measured rather than assumed:

    * The factors on a corridor are correlated with each other — junction density with
      access density, curvature with gradient — so the posterior over their coefficients
      is a long thin ridge. Both a Gaussian approximation and an ensemble sampler do
      badly on that; the first version of this module failed its own convergence gate at
      R-hat 1.09 because of it. On ``Q`` the ridge is a ball.
    * Centring separates the intercept from the slopes, which is the other half of the
      same correlation problem.

    ``r_inverse`` and ``means`` carry the transform back, so every reported number is on
    the caller's scale and nothing downstream knows this happened.
    """

    y: np.ndarray
    offset: np.ndarray
    design: np.ndarray
    boundaries: np.ndarray
    lgamma_y1: np.ndarray
    nodes: np.ndarray
    log_weights: np.ndarray
    n_units: int
    r_inverse: np.ndarray
    means: np.ndarray

    @property
    def n_factors(self) -> int:
        return int(self.design.shape[1])

    @property
    def n_dim(self) -> int:
        return 1 + self.n_factors + 2


def _prepare(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    n_nodes: int,
) -> _Problem:
    """Sort rows by unit so each unit's rows are contiguous.

    ``np.add.reduceat`` then sums within a unit without building an indicator matrix,
    which matters because that sum runs once per quadrature node per parameter vector.
    """
    frame = pd.DataFrame(
        {
            "y": np.asarray(counts, dtype=float),
            "offset": np.asarray(log_exposure, dtype=float),
            "unit": pd.Series(unit_ids).to_numpy(),
        }
    )
    order = np.argsort(frame["unit"].to_numpy(), kind="stable")
    ordered = frame.iloc[order]
    codes = pd.factorize(ordered["unit"])[0]
    boundaries = np.flatnonzero(np.r_[True, np.diff(codes) != 0])

    raw = np.asarray(design, dtype=float)[order]
    means = raw.mean(axis=0)
    centred = raw - means
    # Scaled so Q's columns stay order-one whatever the panel length, which keeps step
    # sizes comparable between a 7-unit corridor and a 700-unit one.
    q, r = np.linalg.qr(centred)
    scale = math.sqrt(max(len(raw) - 1, 1))
    q, r = q * scale, r / scale

    nodes, weights = np.polynomial.hermite_e.hermegauss(n_nodes)
    return _Problem(
        y=ordered["y"].to_numpy(),
        offset=ordered["offset"].to_numpy(),
        design=q,
        boundaries=boundaries,
        lgamma_y1=gammaln(ordered["y"].to_numpy() + 1.0),
        nodes=nodes,
        log_weights=np.log(weights) - 0.5 * math.log(2.0 * math.pi),
        n_units=int(len(boundaries)),
        r_inverse=np.linalg.inv(r),
        means=means,
    )


def _log_posterior(theta: np.ndarray, problem: _Problem) -> np.ndarray:
    """Log posterior for a batch of parameter vectors.

    ``theta`` is ``(batch, 1 + n_factors + 2)``: centred intercept, **Q-space** slopes,
    log sigma_u, log alpha. The two scale parameters are handled on the log scale so
    inference is unconstrained; the Jacobians are added back below.

    The priors are declared on the caller's coefficients, not on the Q-space ones, so
    the slopes are rotated back before the prior is applied. The Jacobian of that
    rotation is constant and cannot affect anything, so it is omitted.
    """
    theta = np.atleast_2d(theta)
    batch = theta.shape[0]
    intercept = theta[:, 0]
    beta = theta[:, 1 : 1 + problem.n_factors]
    sigma = np.exp(theta[:, -2])
    alpha = np.exp(theta[:, -1])

    out = np.full(batch, -np.inf)
    usable = np.isfinite(sigma) & np.isfinite(alpha) & (sigma < 10.0) & (alpha < 50.0)
    if not usable.any():
        return out

    index = np.flatnonzero(usable)
    r = 1.0 / alpha[index]
    # (batch, rows): the fixed part of the linear predictor, exposure offset included.
    eta = problem.offset[None, :] + intercept[index, None] + beta[index] @ problem.design.T
    # (batch, rows, nodes): plus each quadrature node's value of the random intercept.
    #
    # The random effect is mean-corrected by -sigma^2/2 so exp(u) averages to one.
    # Without it the intercept and sigma_u are coupled — a lognormal with a wider spread
    # has a larger mean, so one can rise and the other fall and land in the same place.
    # It also gives the intercept an interpretation worth having: the log rate at a
    # segment of average character, not at a hypothetical zero-effect segment.
    offsets = sigma[index, None] * problem.nodes[None, :] - 0.5 * sigma[index, None] ** 2

    # Everything below is written to touch the (batch, rows, nodes) array with as few
    # transcendental functions as possible, because that array is the whole cost of this
    # package's slowest path. The obvious spelling needs three of them — one exp for mu
    # and two logs for the negative binomial terms. This needs one.
    #
    #   exp(eta + offset)  ==  exp(eta) * exp(offset)
    #
    # so the exponential runs over (batch, rows) and (batch, nodes) separately and their
    # product is a multiply. And log(mu) never has to be recovered from mu, because
    # eta + offset *is* log(mu) and it is already in hand.
    log_mu = eta[:, :, None] + offsets[:, None, :]
    mu = np.exp(eta)[:, :, None] * np.exp(offsets)[:, None, :]

    y = problem.y[None, :, None]
    r_b = r[:, None, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        # The one remaining transcendental over the big array. Both NB terms are
        # differences against it: log(mu/(r+mu)) = log_mu - log(r+mu), and
        # log(r/(r+mu)) = log(r) - log(r+mu).
        log_r_plus_mu = np.log(r_b + mu)
        loglik = (
            gammaln(y + r_b)
            - gammaln(r_b)
            - problem.lgamma_y1[None, :, None]
            + r_b * (np.log(r_b) - log_r_plus_mu)
            + y * (log_mu - log_r_plus_mu)
        )
    loglik = np.where(np.isfinite(loglik), loglik, -np.inf)

    per_unit = np.add.reduceat(loglik, problem.boundaries, axis=1)
    marginal = logsumexp(per_unit + problem.log_weights[None, None, :], axis=2).sum(axis=1)

    # Weakly informative priors on the log-rate scale. Normal(0, 1) on a coefficient
    # admits effects up to about sevenfold per unit of the transformed factor, generous
    # for road safety and still ruling out the numerical nonsense an improper prior
    # lets an optimiser or a sampler wander into.
    #
    # Step 3.3b replaces these with the registry's own cited weights, which is the
    # brief's unifying idea: Mode B weights ARE the priors.
    original_beta = beta[index] @ problem.r_inverse.T
    log_prior = (
        -0.5 * (intercept[index] / 5.0) ** 2
        - 0.5 * np.sum(original_beta**2, axis=1)
        - 0.5 * sigma[index] ** 2
        + theta[index, -2]
        - 0.5 * alpha[index] ** 2
        + theta[index, -1]
    )

    total = marginal + log_prior
    out[index] = np.where(np.isfinite(total), total, -np.inf)
    return out


def _batched_log_posterior(theta: np.ndarray, problem: _Problem) -> np.ndarray:
    """Chunked so peak memory stays bounded, in as few calls as that allows."""
    theta = np.atleast_2d(theta)
    per_walker = max(1, problem.y.size * problem.nodes.size)
    chunk = max(1, ELEMENT_BUDGET // per_walker)
    if theta.shape[0] <= chunk:
        return _log_posterior(theta, problem)
    return np.concatenate(
        [
            _log_posterior(theta[start : start + chunk], problem)
            for start in range(0, theta.shape[0], chunk)
        ]
    )


# ---- step 1: Laplace, and the importance check that polices it ----------------


def _step_sizes(theta: np.ndarray) -> np.ndarray:
    return 1e-4 * np.maximum(1.0, np.abs(theta))


def _gradient(theta: np.ndarray, problem: _Problem) -> np.ndarray:
    """Central-difference gradient, every perturbation in one batched call."""
    n = theta.size
    h = _step_sizes(theta)
    steps = np.eye(n) * h
    batch = np.vstack([theta + steps, theta - steps])
    values = _batched_log_posterior(batch, problem)
    return (values[:n] - values[n:]) / (2.0 * h)


def _hessian(theta: np.ndarray, problem: _Problem) -> np.ndarray:
    """Central-difference Hessian of the log posterior.

    Batched the same way: an eleven-parameter model needs a few hundred evaluations and
    they all go through one vectorised call, which is why this costs a second rather
    than a minute.
    """
    n = theta.size
    h = _step_sizes(theta)
    eye = np.eye(n) * h

    points: list[np.ndarray] = []
    for i in range(n):
        for j in range(i, n):
            points.extend(
                [
                    theta + eye[i] + eye[j],
                    theta + eye[i] - eye[j],
                    theta - eye[i] + eye[j],
                    theta - eye[i] - eye[j],
                ]
            )
    values = _batched_log_posterior(np.vstack(points), problem)

    hessian = np.zeros((n, n))
    at = 0
    for i in range(n):
        for j in range(i, n):
            pp, pm, mp, mm = values[at : at + 4]
            at += 4
            entry = (pp - pm - mp + mm) / (4.0 * h[i] * h[j])
            hessian[i, j] = hessian[j, i] = entry
    return hessian


def _find_mode(
    start: np.ndarray, problem: _Problem
) -> tuple[np.ndarray, bool]:
    """Maximise the log posterior. Returns the mode and whether the optimiser liked it."""
    from scipy.optimize import minimize

    def objective(theta: np.ndarray) -> float:
        value = float(_batched_log_posterior(theta[None, :], problem)[0])
        return -value if np.isfinite(value) else 1e12

    def jacobian(theta: np.ndarray) -> np.ndarray:
        return -_gradient(theta, problem)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = minimize(objective, start, jac=jacobian, method="L-BFGS-B")
    return np.asarray(result.x, dtype=float), bool(result.success)


def _pareto_k(log_weights: np.ndarray) -> tuple[np.ndarray, float]:
    """Pareto-smooth the importance weights and return them with k-hat.

    The largest weights are the dangerous ones: if the proposal has lighter tails than
    the target, a handful of draws end up carrying the whole estimate. Fitting a
    generalised Pareto to that tail both stabilises the weights and measures how bad the
    problem is — k-hat is the fitted shape, and above 0.7 the weight distribution has
    infinite variance.
    """
    weights = np.asarray(log_weights, dtype=float)
    finite = np.isfinite(weights)
    if finite.sum() < 10:
        return np.full(weights.shape, -np.inf), float("inf")

    weights = weights - weights[finite].max()
    n = weights.size
    tail_size = int(min(n / 5.0, 3.0 * math.sqrt(n)))
    if tail_size < 5:
        return weights, float("inf")

    order = np.argsort(weights)
    tail_index = order[-tail_size:]
    cutoff = weights[order[-tail_size - 1]]
    excess = np.exp(weights[tail_index]) - np.exp(cutoff)
    excess = excess[excess > 0]
    if excess.size < 5:
        return weights, float("inf")

    k, sigma = _fit_generalised_pareto(np.sort(excess))
    if not math.isfinite(k):
        return weights, float("inf")

    # Replace the tail with the fitted quantiles, which is the "smoothing" half.
    ranks = (np.arange(excess.size) + 0.5) / excess.size
    if abs(k) > 1e-8:
        smoothed = sigma * ((1.0 - ranks) ** (-k) - 1.0) / k
    else:
        smoothed = -sigma * np.log1p(-ranks)
    replacement = np.log(smoothed + np.exp(cutoff))

    out = weights.copy()
    keep = tail_index[np.argsort(weights[tail_index])][-replacement.size :]
    out[keep] = np.minimum(replacement, weights[order[-1]])
    return out, float(k)


def _fit_generalised_pareto(excess: np.ndarray) -> tuple[float, float]:
    """Zhang and Stephens (2009) estimator for the generalised Pareto tail."""
    n = excess.size
    m = 30 + int(math.sqrt(n))
    prior = 3.0 / (4.0 * excess[max(int(n / 4 + 0.5) - 1, 0)])
    grid = 1.0 / excess[-1] + (
        1.0 - np.sqrt(m / (np.arange(1, m + 1) - 0.5))
    ) * prior

    with np.errstate(divide="ignore", invalid="ignore"):
        k_grid = np.mean(np.log1p(-grid[:, None] * excess[None, :]), axis=1)
        profile = n * (np.log(-grid / k_grid) - k_grid - 1.0)

    finite = np.isfinite(profile)
    if not finite.any():
        return float("nan"), float("nan")
    weights = np.exp(profile[finite] - profile[finite].max())
    weights = weights / weights.sum()
    theta = float(np.sum(weights * grid[finite]))

    k = float(np.mean(np.log1p(-theta * excess)))
    sigma = float(-k / theta) if theta != 0 else float("nan")
    # Small-sample correction, as in the reference implementation.
    k = k * n / (n + 10.0) + 0.5 * 10.0 / (n + 10.0)
    return k, sigma


def _weighted_summary(
    name: str, draws: np.ndarray, weights: np.ndarray, hdi_probability: float
) -> PosteriorSummary:
    """Summarise one parameter from importance-weighted draws."""
    order = np.argsort(draws)
    ordered_draws, ordered_weights = draws[order], weights[order]
    cumulative = np.cumsum(ordered_weights)
    cumulative = cumulative / cumulative[-1]

    tail = (1.0 - hdi_probability) / 2.0
    low = float(np.interp(tail, cumulative, ordered_draws))
    high = float(np.interp(1.0 - tail, cumulative, ordered_draws))
    mean = float(np.sum(weights * draws))
    variance = float(np.sum(weights * (draws - mean) ** 2))
    return PosteriorSummary(
        name=name,
        mean=mean,
        sd=math.sqrt(max(variance, 0.0)),
        hdi_low=low,
        hdi_high=high,
        prob_positive=float(np.sum(weights[draws > 0.0])),
    )


def _fit_laplace(
    problem: _Problem,
    names: list[str],
    centre: np.ndarray,
    hdi_probability: float,
    seed: int,
) -> tuple[list[PosteriorSummary], ApproximationReport | None, np.ndarray | None,
           np.ndarray | None]:
    """Step 1. Returns summaries, the honesty report, the mode and its covariance."""
    mode, ok = _find_mode(centre, problem)
    if not ok and not np.all(np.isfinite(mode)):
        return [], None, None, None

    hessian = _hessian(mode, problem)
    precision = -hessian
    try:
        covariance = np.linalg.inv(precision)
        cholesky = np.linalg.cholesky(covariance)
    except np.linalg.LinAlgError:
        # Not negative definite: the optimiser stopped somewhere that is not a maximum.
        return [], None, mode, None

    rng = np.random.default_rng(seed)
    n_dim = problem.n_dim
    # A multivariate t rather than the Gaussian the curvature literally implies.
    #
    # Importance sampling needs the proposal's tails to be at least as heavy as the
    # target's, or a few far-out draws end up carrying the whole estimate. A Gaussian
    # proposal against this posterior measured k-hat 0.80 — over the threshold, so the
    # ladder descended to a twelve-minute MCMC to say the same thing. Same mode, same
    # covariance, heavier tails: the approximation is no less faithful and importance
    # sampling can now correct what it gets wrong.
    scaled = rng.chisquare(PROPOSAL_DF, IS_DRAWS) / PROPOSAL_DF
    raw = rng.standard_normal((IS_DRAWS, n_dim)) / np.sqrt(scaled)[:, None]
    draws = mode + raw @ cholesky.T

    target = _batched_log_posterior(draws, problem)
    # log q, up to a constant that cancels when the weights are normalised.
    mahalanobis = np.sum(raw**2, axis=1)
    proposal = -0.5 * (PROPOSAL_DF + n_dim) * np.log1p(mahalanobis / PROPOSAL_DF)
    log_weights, k_hat = _pareto_k(target - proposal)

    finite = np.isfinite(log_weights)
    if finite.sum() < 10:
        return [], None, mode, covariance
    weights = np.zeros(log_weights.shape)
    weights[finite] = np.exp(log_weights[finite] - log_weights[finite].max())
    total = weights.sum()
    if total <= 0:
        return [], None, mode, covariance
    weights = weights / total

    report = ApproximationReport(
        k_hat=k_hat,
        n_draws=IS_DRAWS,
        effective_draws=float(1.0 / np.sum(weights**2)),
        log_evidence=float(logsumexp(target - proposal) - math.log(IS_DRAWS)),
    )

    reported = _to_caller_scale(draws[:, None, :], problem)[:, 0, :]
    labels = ["intercept", *names, "sigma_u", "alpha"]
    summaries = [
        _weighted_summary(labels[i], reported[:, i], weights, hdi_probability)
        for i in range(n_dim)
    ]
    return summaries, report, mode, covariance


# ---- step 2: MCMC, warm-started from step 1 -----------------------------------


def _fit_mcmc(
    problem: _Problem,
    names: list[str],
    centre: np.ndarray,
    covariance: np.ndarray | None,
    draws: int,
    tune: int,
    walkers: int | None,
    hdi_probability: float,
    seed: int,
) -> tuple[list[PosteriorSummary], ConvergenceReport] | None:
    """Step 2. Returns None when emcee is not installed."""
    try:
        import emcee
    except ModuleNotFoundError:
        return None

    n_dim = problem.n_dim
    n_walkers = walkers if walkers is not None else DEFAULT_WALKER_MULTIPLE * n_dim
    n_walkers = max(n_walkers, 2 * n_dim + 2)

    rng = np.random.default_rng(seed)
    if covariance is not None:
        # Start the ensemble spread along the posterior's own shape rather than as a
        # small isotropic ball. This is the whole benefit of running Laplace first: the
        # sampler's hardest problem was the correlation between coefficients, and the
        # curvature at the mode describes exactly that correlation.
        try:
            spread = np.linalg.cholesky(covariance)
            initial = centre + rng.standard_normal((n_walkers, n_dim)) @ spread.T
        except np.linalg.LinAlgError:
            initial = centre + rng.normal(0.0, 0.05, (n_walkers, n_dim))
    else:
        initial = centre + rng.normal(0.0, 0.05, (n_walkers, n_dim))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sampler = emcee.EnsembleSampler(
            n_walkers,
            n_dim,
            _batched_log_posterior,
            args=(problem,),
            vectorize=True,
            # The default stretch move assumes a roughly isotropic target and degrades
            # past a handful of dimensions. Differential evolution proposes along the
            # ensemble's own covariance, which is what a correlated posterior needs.
            moves=[(emcee.moves.DEMove(), 0.8), (emcee.moves.DESnookerMove(), 0.2)],
        )
        sampler.run_mcmc(initial, tune + draws, progress=False)
        chain = sampler.get_chain(discard=tune)  # (draw, walker, dim)
        acceptance = float(np.mean(sampler.acceptance_fraction))

    labels = ["intercept", *names, "sigma_u", "alpha"]
    reported = _to_caller_scale(chain, problem)
    summaries = [
        _summarise(labels[i], reported[:, :, i], hdi_probability) for i in range(n_dim)
    ]

    worst_r_hat = max(summaries, key=lambda s: s.r_hat or 0.0)
    worst_ess = min(summaries, key=lambda s: s.ess_bulk or 0.0)
    convergence = ConvergenceReport(
        n_draws=int(chain.shape[0]),
        n_walkers=n_walkers,
        n_tune=tune,
        max_r_hat=worst_r_hat.r_hat or float("inf"),
        min_ess_bulk=worst_ess.ess_bulk or 0.0,
        acceptance=acceptance,
        worst_r_hat_parameter=worst_r_hat.name,
        worst_ess_parameter=worst_ess.name,
    )
    return summaries, convergence


# ---- the ladder ---------------------------------------------------------------


def fit_bayesian_glmm(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    *,
    start: dict[str, float] | None = None,
    draws: int = DEFAULT_DRAWS,
    tune: int = DEFAULT_TUNE,
    walkers: int | None = None,
    n_nodes: int = DEFAULT_NODES,
    hdi_probability: float = 0.95,
    allow_mcmc: bool = True,
    seed: int = 0,
) -> PosteriorFit:
    """Fit the random-intercept NB GLMM and return its posterior.

    Walks the inference ladder: Laplace with an importance check first, MCMC only if
    that check fails, and a refusal if neither can be believed. Every rung attempted is
    recorded on ``descent``.

    Args:
        counts: ``n_crashes``.
        design: Transformed design matrix.
        log_exposure: ``ln(length_km * duration_hours)``, entering as an offset — a
            coefficient fixed at one, never estimated.
        unit_ids: Unit id per row. The grouping for the random intercept.
        start: Optional starting point keyed by factor name plus ``intercept`` and
            ``alpha``. The engine passes rung 1's estimates, which costs nothing.
        draws: MCMC iterations kept per walker, if the ladder descends that far.
        tune: MCMC iterations discarded as burn-in.
        walkers: Ensemble size. Defaults to four per dimension.
        n_nodes: Gauss-Hermite nodes for the per-unit integral.
        hdi_probability: Credible interval mass. 0.95 by convention here.
        allow_mcmc: Set False to stop at step 1 and refuse rather than descend. Used by
            tests that must stay fast, and by callers who would rather have nothing
            than wait.
        seed: RNG seed. The same seed reproduces the same posterior.

    Returns:
        A :class:`PosteriorFit`. When no rung can be believed it comes back with
        ``converged = False`` and empty summaries — the numbers exist but are not handed
        out, because an interval nobody can vouch for is not an interval.
    """
    names = [str(c) for c in design.columns]
    specification = "Bayesian NB GLMM, random intercept per unit"
    descent: list[str] = []

    # Quadrature accuracy is the first thing to escalate, because it is by far the
    # cheapest: adding nodes costs seconds, descending to MCMC costs minutes.
    schedule = [n for n in NODE_LADDER if n >= n_nodes] or [n_nodes]
    problem = _prepare(counts, design, log_exposure, unit_ids, schedule[0])
    centre = _starting_point(start, names, problem)
    summaries: list[PosteriorSummary] = []
    approximation: ApproximationReport | None = None
    mode: np.ndarray | None = None
    covariance: np.ndarray | None = None

    for nodes in schedule:
        problem = _prepare(counts, design, log_exposure, unit_ids, nodes)
        summaries, approximation, mode, covariance = _fit_laplace(
            problem, names, centre, hdi_probability, seed
        )
        if approximation is not None and approximation.trustworthy and summaries:
            descent.append(
                f"Laplace + importance sampling at {nodes} quadrature nodes: "
                f"{approximation.describe()}"
            )
            return _assemble(
                specification=specification,
                method=Method.LAPLACE,
                problem=problem,
                names=names,
                summaries=summaries,
                approximation=approximation,
                convergence=None,
                hdi_probability=hdi_probability,
                descent=tuple(descent),
                notes=_notes(problem, nodes),
                n_nodes=nodes,
            )
        descent.append(
            f"Laplace + importance sampling at {nodes} quadrature nodes: "
            + (
                approximation.describe()
                if approximation is not None
                else "the posterior mode could not be located, or the curvature there "
                "was not a maximum, so there was no Gaussian to approximate with."
            )
        )

    notes = _notes(problem, schedule[-1])

    if not allow_mcmc:
        return _refused(
            specification, problem, approximation, tuple(descent), notes,
            "The Laplace approximation was not trustworthy and MCMC was not permitted.",
        )

    outcome = _fit_mcmc(
        problem,
        names,
        mode if mode is not None else centre,
        covariance,
        draws,
        tune,
        walkers,
        hdi_probability,
        seed,
    )
    if outcome is None:
        return _refused(
            specification, problem, approximation, tuple(descent), notes,
            "The Laplace approximation was not trustworthy and the MCMC fallback needs "
            'the "bayes" extra: pip install "roadrisk-panel[bayes]"',
        )

    mcmc_summaries, convergence = outcome
    descent.append(f"MCMC, warm-started from the Laplace mode: {convergence.describe()}")
    if not convergence.converged:
        return _refused(
            specification, problem, approximation, tuple(descent), notes,
            convergence.describe(), convergence=convergence,
        )

    return _assemble(
        specification=specification,
        method=Method.MCMC,
        problem=problem,
        names=names,
        summaries=mcmc_summaries,
        approximation=approximation,
        convergence=convergence,
        hdi_probability=hdi_probability,
        descent=tuple(descent),
        notes=notes,
    )


def fit_mcmc_reference(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    *,
    start: dict[str, float] | None = None,
    draws: int = DEFAULT_DRAWS,
    tune: int = DEFAULT_TUNE,
    walkers: int | None = None,
    n_nodes: int = 48,
    hdi_probability: float = 0.95,
    seed: int = 0,
) -> PosteriorFit:
    """Run the MCMC rung directly, skipping the approximation. **Validation only.**

    Now that the node ladder makes step 1 succeed on everything tried, the ordinary
    entry point never reaches step 2 — so checking the approximation against a sampler
    needs a way to ask for the sampler on purpose. That is all this is for, and it is
    why it is not wired into the engine: a caller who wanted slower, noisier answers
    with the same intervals would be choosing badly, and the engine does not offer
    choices like that.

    It is warm-started from the Laplace mode, which changes how long the chains take to
    settle and not where they settle. The posterior explored is the true one, arrived at
    by a method that fails in completely different ways from a Gaussian approximation —
    which is the entire point of comparing them.

    See ``tools/validate_posterior.py``.
    """
    problem = _prepare(counts, design, log_exposure, unit_ids, n_nodes)
    names = [str(c) for c in design.columns]
    centre = _starting_point(start, names, problem)

    mode, ok = _find_mode(centre, problem)
    covariance: np.ndarray | None = None
    if ok and np.all(np.isfinite(mode)):
        try:
            covariance = np.linalg.inv(-_hessian(mode, problem))
            np.linalg.cholesky(covariance)
        except np.linalg.LinAlgError:
            covariance = None
    else:
        mode = centre

    outcome = _fit_mcmc(
        problem, names, mode, covariance, draws, tune, walkers, hdi_probability, seed
    )
    specification = "Bayesian NB GLMM, random intercept per unit (MCMC reference)"
    notes = _notes(problem, n_nodes)
    if outcome is None:
        return _refused(
            specification,
            problem,
            None,
            ("MCMC reference requested.",),
            notes,
            'The MCMC reference needs the "bayes" extra: '
            'pip install "roadrisk-panel[bayes]"',
        )

    summaries, convergence = outcome
    descent = (f"MCMC reference at {n_nodes} nodes: {convergence.describe()}",)
    if not convergence.converged:
        return _refused(
            specification, problem, None, descent, notes,
            convergence.describe(), convergence=convergence,
        )
    return _assemble(
        specification=specification,
        method=Method.MCMC,
        problem=problem,
        names=names,
        summaries=summaries,
        approximation=None,
        convergence=convergence,
        hdi_probability=hdi_probability,
        descent=descent,
        notes=notes,
        n_nodes=n_nodes,
    )


def _notes(problem: _Problem, n_nodes: int) -> tuple[str, ...]:
    return (
        f"The {problem.n_units:,} random intercepts are integrated out by {n_nodes}-node "
        f"Gauss-Hermite quadrature rather than estimated, leaving {problem.n_dim} "
        "parameters. Per-segment effects are therefore not available from this fit, and "
        "neither is spatial structure — see 3.3c.",
        "alpha is the NB2 dispersion of var = mu + alpha * mu^2, the same convention the "
        "frequentist rungs report.",
        "Priors are weakly informative and are NOT the registry's cited weights yet. "
        "Step 3.3b makes Mode B's weights the prior means, which is the brief's "
        "unifying idea and changes what this fit means.",
    )


def _assemble(
    *,
    specification: str,
    method: Method,
    problem: _Problem,
    names: list[str],
    summaries: list[PosteriorSummary],
    approximation: ApproximationReport | None,
    convergence: ConvergenceReport | None,
    hdi_probability: float,
    descent: tuple[str, ...],
    notes: tuple[str, ...],
    n_nodes: int,
) -> PosteriorFit:
    return PosteriorFit(
        specification=specification,
        family=Family.NEGATIVE_BINOMIAL,
        converged=True,
        method=method,
        n_observations=int(len(problem.y)),
        n_units=problem.n_units,
        n_parameters=problem.n_dim,
        coefficients=summaries[1 : 1 + len(names)],
        intercept=summaries[0],
        sigma_u=summaries[-2],
        alpha=summaries[-1],
        approximation=approximation,
        convergence=convergence,
        hdi_probability=hdi_probability,
        n_nodes=n_nodes,
        descent=descent,
        notes=notes,
    )


def _refused(
    specification: str,
    problem: _Problem,
    approximation: ApproximationReport | None,
    descent: tuple[str, ...],
    notes: tuple[str, ...],
    reason: str,
    convergence: ConvergenceReport | None = None,
) -> PosteriorFit:
    return PosteriorFit(
        specification=specification,
        family=Family.NEGATIVE_BINOMIAL,
        converged=False,
        method=Method.NONE,
        n_observations=int(len(problem.y)),
        n_units=problem.n_units,
        n_parameters=problem.n_dim,
        approximation=approximation,
        convergence=convergence,
        descent=descent,
        failure_reason=reason,
        notes=notes,
    )


def _to_caller_scale(chain: np.ndarray, problem: _Problem) -> np.ndarray:
    """Undo the QR rotation, the centring and the log scales, draw by draw.

    Done on the draws rather than on the summaries because a posterior is not a point:
    the intercept correction is nonlinear in the slopes, so transforming a mean is not
    the mean of the transform.
    """
    out = chain.copy()
    slopes = chain[:, :, 1 : 1 + problem.n_factors] @ problem.r_inverse.T
    out[:, :, 1 : 1 + problem.n_factors] = slopes
    out[:, :, 0] = chain[:, :, 0] - slopes @ problem.means
    out[:, :, -2] = np.exp(chain[:, :, -2])
    out[:, :, -1] = np.exp(chain[:, :, -1])
    return out


def _starting_point(
    start: dict[str, float] | None, names: list[str], problem: _Problem
) -> np.ndarray:
    """Start at rung 1's answer, rotated into the working space.

    The engine already has an NB2 fit by the time this runs, so handing over its
    estimates costs nothing and saves the optimiser hunting for the right neighbourhood.
    The posterior found is the same either way — only how long it takes changes.
    """
    mean_rate = float(np.mean(problem.y))
    fallback_intercept = math.log(max(mean_rate, 1e-3)) - float(np.mean(problem.offset))
    centre = np.zeros(problem.n_dim)
    centre[0] = fallback_intercept
    centre[-2] = math.log(0.4)
    centre[-1] = math.log(0.6)
    if not start:
        return centre

    beta = np.array([float(start.get(name, 0.0)) for name in names])
    r = np.linalg.inv(problem.r_inverse)
    centre[1 : 1 + problem.n_factors] = r @ beta
    centre[0] = float(start.get("intercept", fallback_intercept)) + float(
        problem.means @ beta
    )
    alpha = float(start.get("alpha", 0.6))
    centre[-1] = math.log(alpha if alpha > 0 else 0.6)
    return centre


def _summarise(
    name: str, draws: np.ndarray, hdi_probability: float
) -> PosteriorSummary:
    """One parameter, summarised from its (draw, chain) array."""
    flat = draws.reshape(-1)
    tail = (1.0 - hdi_probability) / 2.0
    low, high = np.percentile(flat, [100 * tail, 100 * (1.0 - tail)])
    return PosteriorSummary(
        name=name,
        mean=float(np.mean(flat)),
        sd=float(np.std(flat, ddof=1)),
        hdi_low=float(low),
        hdi_high=float(high),
        prob_positive=float(np.mean(flat > 0.0)),
        r_hat=split_r_hat(draws),
        ess_bulk=effective_sample_size(draws),
    )


# ---- convergence diagnostics -------------------------------------------------
#
# Implemented here rather than taken from ArviZ deliberately: ArviZ pulls in xarray and
# a large dependency tree, and this package's whole shape is that `core` needs pandas
# and statsmodels and nothing else. Both functions are checked against ArviZ in the
# test suite, which is skipped when ArviZ is absent.


def _rank_normalise(draws: np.ndarray) -> np.ndarray:
    """Rank-normalise pooled draws, so the diagnostics do not assume normality.

    Vehtari et al. (2021). Plain R-hat is computed from means and variances, which a
    heavy-tailed or badly skewed posterior can satisfy while being nowhere near
    converged. Ranking first removes that failure mode.
    """
    from scipy.stats import norm

    flat = draws.reshape(-1)
    order = flat.argsort(kind="stable")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, flat.size + 1, dtype=float)
    scaled = (ranks - 3.0 / 8.0) / (flat.size + 0.25)
    return norm.ppf(scaled).reshape(draws.shape)


def split_r_hat(draws: np.ndarray) -> float:
    """Rank-normalised split-R-hat for a ``(draw, chain)`` array.

    Splitting each chain in half is what catches a chain that is drifting: the two
    halves of one slowly-moving walker disagree with each other even though the walkers
    agree with one another.
    """
    values = np.asarray(draws, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    n_draws, _ = values.shape
    if n_draws < 4:
        return float("inf")

    half = n_draws // 2
    split = np.concatenate([values[:half], values[half : 2 * half]], axis=1)
    normalised = _rank_normalise(split)

    n, _ = normalised.shape
    chain_means = normalised.mean(axis=0)
    chain_vars = normalised.var(axis=0, ddof=1)
    within = chain_vars.mean()
    between = n * chain_means.var(ddof=1)
    if within <= 0:
        return float("inf")
    var_hat = ((n - 1) / n) * within + between / n
    return float(math.sqrt(var_hat / within))


def effective_sample_size(draws: np.ndarray) -> float:
    """Bulk effective sample size for a ``(draw, chain)`` array.

    Geyer's initial positive sequence: sum the autocorrelations in adjacent pairs and
    stop at the first pair that goes negative, which is where the estimate stops being
    information and starts being noise.
    """
    values = np.asarray(draws, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    n_draws, n_chains = values.shape
    if n_draws < 8:
        return 0.0

    normalised = _rank_normalise(values)
    total = n_draws * n_chains

    acov = np.zeros((n_draws, n_chains))
    for chain in range(n_chains):
        series = normalised[:, chain] - normalised[:, chain].mean()
        padded = int(2 ** math.ceil(math.log2(2 * n_draws)))
        spectrum = np.fft.rfft(series, n=padded)
        acov[:, chain] = np.fft.irfft(spectrum * np.conjugate(spectrum), n=padded)[
            :n_draws
        ] / n_draws

    chain_means = normalised.mean(axis=0)
    chain_var = acov[0] * n_draws / (n_draws - 1.0)
    var_plus = chain_var.mean()
    if n_chains > 1:
        var_plus = var_plus * (n_draws - 1.0) / n_draws + chain_means.var(ddof=1)
    if var_plus <= 0:
        return 0.0

    rho = np.zeros(n_draws)
    for lag in range(n_draws):
        rho[lag] = 1.0 - (chain_var.mean() - acov[lag].mean()) / var_plus

    total_rho = 0.0
    pair = 1
    while pair + 1 < n_draws:
        combined = rho[pair] + rho[pair + 1]
        if combined < 0:
            break
        total_rho += combined
        pair += 2

    tau = -1.0 + 2.0 * total_rho
    if tau <= 0:
        return float(total)
    return float(min(total, total / tau))


__all__ = [
    "DEFAULT_DRAWS",
    "DEFAULT_NODES",
    "NODE_LADDER",
    "DEFAULT_TUNE",
    "ESS_THRESHOLD",
    "ELEMENT_BUDGET",
    "IS_DRAWS",
    "KHAT_THRESHOLD",
    "RHAT_THRESHOLD",
    "ApproximationReport",
    "ConvergenceReport",
    "Method",
    "PosteriorFit",
    "PosteriorSummary",
    "effective_sample_size",
    "fit_bayesian_glmm",
    "fit_mcmc_reference",
    "split_r_hat",
]
