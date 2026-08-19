"""Model layer.

Only two models ever reach a client:

* **Mode A** — negative binomial, fitted from the client's own crash data.
* **Mode B** — a weighted index from cited published weights. Ranking only.

Poisson is a reference model. It measures overdispersion and justifies the negative
binomial, and it lives in the run log and the internal appendix. It is never the
assessment.
"""

from roadrisk.core.models.base import Coefficient, Estimator, FitResult
from roadrisk.core.models.bayes import (
    ApproximationReport,
    ConvergenceReport,
    Method,
    PosteriorFit,
    PosteriorSummary,
    fit_bayesian_glmm,
)
from roadrisk.core.models.glm import INTERCEPT, fit_negative_binomial, fit_poisson
from roadrisk.core.models.index import IndexResult, IndexTerm, score_index
from roadrisk.core.models.spatial import SpatialReport, fit_spatial_glmm

__all__ = [
    "INTERCEPT",
    "ApproximationReport",
    "Coefficient",
    "ConvergenceReport",
    "Estimator",
    "FitResult",
    "IndexResult",
    "IndexTerm",
    "Method",
    "PosteriorFit",
    "PosteriorSummary",
    "SpatialReport",
    "fit_bayesian_glmm",
    "fit_spatial_glmm",
    "fit_negative_binomial",
    "fit_poisson",
    "score_index",
]
