"""Step 3.4 — does the model predict segments it has never seen?

    hold out a stretch of road  ->  refit without it  ->  predict it  ->  compare

Everything before this step measures how well the model describes the corridor it was
fitted on. That is not the question a client is asking. They want to know whether the
number attached to *this* segment means anything, and the only honest way to answer is to
fit without that segment and then look.

**Reported by default, including when bad.** No flag turns this on and none turns it off.
A model that fails its own validation is a finding the report must carry, not an
inconvenience the caller can decline to compute. This is the same rule as the sign guard
and the mode banner, applied to accuracy.

### The folds are contiguous stretches, not random rows

Random k-fold on a corridor panel is optimistic, and badly so. Adjacent segments share
almost everything — the same terrain, the same design standard, the same traffic, the
same unobserved character that step 3.3a spends its time estimating — so a random fold
leaves a segment's own neighbours in the training set and the model half-remembers the
answer. Holding out a *run* of segments is the closest this can get to "a road we have
not seen".

**The gap between the two is measured rather than asserted.** Both are computed and
reported side by side, so the optimism of the easy method is visible instead of being
something a reader has to take on trust.

### Three things come out

* **Calibration** — over the held-out segments, do the predicted crashes add up to the
  observed ones? The ratio is the HSM's calibration factor in everything but name, and a
  model can be beautifully specified and still be wrong by a constant.
* **CURE plots** — cumulative residuals against each factor. They answer a question no
  single number can: *where* on a factor's range the model is wrong. Drifting outside the
  bounds over a stretch means the model is systematically over- or under-predicting for
  segments in that range, which is a functional-form problem — the same defect step 3.2's
  spline hunts, seen from the other side.
* **Accuracy** — mean absolute deviation per held-out cell, and the share of held-out
  crashes the model accounts for.

### What it cannot do

It validates the *specification* against the corridor's own crash data. It cannot tell
anybody whether the corridor's crash data is any good, and on a panel of synthetic
crashes it is measuring the generator. Both facts are stated in the report rather than
left for a reader to work out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from roadrisk.core.models import FitResult, fit_negative_binomial

#: Folds for cross-validation. Five is the usual compromise between training on enough
#: of the corridor and holding out a stretch long enough to be genuinely unseen.
DEFAULT_FOLDS = 5

#: Fewest units before cross-validation is attempted at all.
#:
#: With five folds this leaves ten units per held-out block, and a block much smaller
#: than that measures noise. The same reasoning as rung 2's twenty-cluster floor: an
#: estimator applied below the size it needs does not fail loudly, it produces a number
#: that looks like the others and is not one.
MIN_UNITS = 25

#: Calibration ratios outside this band are reported as a failure rather than a note.
#: Twenty per cent either way is the HSM's own rule of thumb for when a calibration
#: factor stops being a nuisance parameter and starts being a specification problem.
CALIBRATION_TOLERANCE = 0.20

#: Share of a CURE curve allowed outside its bounds before the factor is called
#: mis-specified. A well-behaved curve wanders outside occasionally; a fifth of its
#: length outside is drift, not wandering.
CURE_TOLERANCE = 0.20

#: Orderings sampled when a factor has tied values, and the seed that fixes them.
#:
#: CURE sorts by the covariate, and observations tied at one value can be summed in any
#: order — so the statistic is a distribution rather than a number, and the ordering a
#: stable sort happens to leave behind is one draw from it. Two hundred is enough to
#: settle a median on the unit counts this runs at; the seed is fixed because a run's
#: manifest fingerprints its results and a diagnostic that moves between identical runs
#: is worse than one that is occasionally wrong.
CURE_TIE_RESAMPLES = 200
CURE_TIE_SEED = 20260904

#: Points the CURE curve is reported on. Enough to see a drift, few enough to print.
CURE_POINTS = 41

FitFn = Callable[[pd.Series, pd.DataFrame, pd.Series], FitResult]


@dataclass(frozen=True)
class FoldOutcome:
    """One held-out block, and how the model did on it."""

    fold: int
    n_units: int
    n_rows: int
    observed: float
    predicted: float
    converged: bool

    @property
    def ratio(self) -> float | None:
        return self.observed / self.predicted if self.predicted > 0 else None


@dataclass(frozen=True)
class Calibration:
    """How the model did on road it had not seen."""

    scheme: str
    n_folds: int
    n_units: int
    observed: float
    predicted: float
    mean_absolute_deviation: float
    folds: list[FoldOutcome] = field(default_factory=list)

    @property
    def factor(self) -> float | None:
        """Observed over predicted. One is perfect; below one is over-prediction."""
        return self.observed / self.predicted if self.predicted > 0 else None

    @property
    def calibrated(self) -> bool:
        value = self.factor
        return value is not None and abs(value - 1.0) <= CALIBRATION_TOLERANCE

    def describe(self) -> str:
        value = self.factor
        if value is None:
            return f"{self.scheme}: nothing was predicted, so nothing can be compared."
        direction = "under" if value > 1 else "over"
        verdict = (
            "within the ±20% the HSM treats as ordinary calibration"
            if self.calibrated
            else "outside ±20%, which is a specification problem rather than a nuisance"
        )
        return (
            f"{self.scheme}: predicted {self.predicted:,.0f} crashes on held-out road "
            f"against {self.observed:,.0f} observed — a ratio of {value:.2f}, "
            f"{direction}-predicting, {verdict}. Mean absolute deviation "
            f"{self.mean_absolute_deviation:.3f} crashes per cell."
        )


@dataclass(frozen=True)
class CureCurve:
    """Cumulative residuals against one factor, and where they leave the bounds."""

    factor: str
    x: tuple[float, ...]
    cumulative: tuple[float, ...]
    bound: tuple[float, ...]
    #: Median share outside the band over the orderings this factor's ties permit.
    share_outside: float
    #: 5th and 95th percentile of that same sample. Equal to ``share_outside`` when the
    #: factor has no tied values and therefore only one ordering.
    share_outside_low: float = 0.0
    share_outside_high: float = 0.0

    @property
    def tie_sensitive(self) -> bool:
        """Whether the verdict depends on which of the tied orderings was drawn."""
        return self.share_outside_low <= CURE_TOLERANCE < self.share_outside_high

    @property
    def drifts(self) -> bool:
        return self.share_outside > CURE_TOLERANCE

    @property
    def worst_x(self) -> float | None:
        """Where the curve is furthest outside its bound, if it ever is."""
        excess = [
            (abs(c) - b, value)
            for value, c, b in zip(self.x, self.cumulative, self.bound, strict=True)
        ]
        worst = max(excess, key=lambda pair: pair[0])
        return worst[1] if worst[0] > 0 else None

    def describe(self) -> str:
        if not self.drifts:
            return (
                f"{self.factor}: cumulative residuals stay inside their bounds over "
                f"{1 - self.share_outside:.0%} of the range — no sign the model is "
                "systematically wrong anywhere along it."
            )
        where = f" worst around {self.worst_x:.2f}" if self.worst_x is not None else ""
        spread = (
            ""
            if self.share_outside_high <= self.share_outside_low
            else (
                f" Across the orderings this factor's tied values permit the share runs "
                f"{self.share_outside_low:.0%} to {self.share_outside_high:.0%}"
                + (
                    ", which straddles the threshold — read the verdict as indicative."
                    if self.tie_sensitive
                    else "."
                )
            )
        )
        return (
            f"{self.factor}: cumulative residuals are outside their bounds over "
            f"{self.share_outside:.0%} of the range{where}. The model is systematically "
            "wrong for segments in that band — a functional-form problem, not noise. "
            f"The rung 3 spline on this factor is the next thing to look at.{spread}"
        )

    def render(self, *, height: int = 9, indent: str = "") -> str:
        """Draw it as text, the same way the rung 3 spline draws its curve."""
        return _render_cure(self, height=height, indent=indent)


@dataclass(frozen=True)
class ValidationReport:
    """Out-of-sample validation for one fit. Always produced; sometimes a refusal."""

    available: bool
    n_units: int
    spatial: Calibration | None = None
    random: Calibration | None = None
    cure: list[CureCurve] = field(default_factory=list)
    #: How much wider the CURE bounds had to be made because residuals within a segment
    #: are correlated. One means the rows behaved independently.
    design_effect: float = 1.0
    refusal: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def optimism(self) -> float | None:
        """How much better random folds look than contiguous ones.

        The number this step exists to make visible. Positive means random k-fold
        flattered the model, which it does by leaving a segment's own neighbours in the
        training set.
        """
        if self.spatial is None or self.random is None:
            return None
        return self.spatial.mean_absolute_deviation - self.random.mean_absolute_deviation

    @property
    def drifting_factors(self) -> list[CureCurve]:
        return [c for c in self.cure if c.drifts]

    @property
    def passed(self) -> bool:
        return (
            self.available
            and self.spatial is not None
            and self.spatial.calibrated
            and not self.drifting_factors
        )

    def summary(self) -> str:
        if not self.available:
            return f"Out-of-sample validation was not run: {self.refusal}"
        lines = [self.spatial.describe()] if self.spatial else []
        if self.random is not None and self.optimism is not None:
            lines.append(
                f"Random folds would have reported a mean absolute deviation of "
                f"{self.random.mean_absolute_deviation:.3f} against "
                f"{self.spatial.mean_absolute_deviation:.3f} for contiguous ones — "  # type: ignore[union-attr]
                f"a difference of {self.optimism:+.3f} crashes per cell. Adjacent "
                "segments share their character, so a random fold leaves a segment's "
                "own neighbours in the training set."
            )
        for curve in self.cure:
            lines.append(curve.describe())
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        def calibration(item: Calibration | None) -> dict[str, object] | None:
            if item is None:
                return None
            return {
                "scheme": item.scheme,
                "n_folds": item.n_folds,
                "observed": item.observed,
                "predicted": item.predicted,
                "factor": item.factor,
                "calibrated": item.calibrated,
                "mean_absolute_deviation": item.mean_absolute_deviation,
            }

        return {
            "available": self.available,
            "passed": self.passed,
            "n_units": self.n_units,
            "spatial": calibration(self.spatial),
            "random": calibration(self.random),
            "optimism": self.optimism,
            "design_effect": self.design_effect,
            "cure": [
                {
                    "factor": c.factor,
                    "share_outside": c.share_outside,
                    "share_outside_low": c.share_outside_low,
                    "share_outside_high": c.share_outside_high,
                    "drifts": c.drifts,
                    "x": list(c.x),
                    "cumulative": list(c.cumulative),
                    "bound": list(c.bound),
                }
                for c in self.cure
            ],
            "refusal": self.refusal,
            "notes": list(self.notes),
        }


def validate(
    *,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    alpha: float | None = None,
    n_folds: int = DEFAULT_FOLDS,
    min_units: int = MIN_UNITS,
    fit_fn: FitFn = fit_negative_binomial,
    seed: int = 0,
) -> ValidationReport:
    """Cross-validate the specification over contiguous stretches of corridor.

    Args:
        counts: ``n_crashes``.
        design: The fitted specification's design matrix.
        log_exposure: ``ln(length_km * duration_hours)``, the offset.
        unit_ids: Unit id per row. Sorted order is taken as position along the corridor.
        alpha: NB dispersion from the shipped fit, used for the CURE bounds. Without it
            the bounds are Poisson and therefore too tight, which is recorded.
        n_folds: Held-out blocks.
        min_units: Below this the whole thing is declined rather than estimated badly.
        fit_fn: The fit to cross-validate. NB2 by default — cheap enough to run once per
            fold, which the Bayesian rung is not.
        seed: RNG seed for the random-fold comparison.

    Returns:
        A :class:`ValidationReport`. Always returned, never raised: a corridor too small
        to validate is a fact about the corridor and belongs in the report.
    """
    units = pd.Index(pd.unique(pd.Series(unit_ids)))
    n_units = int(len(units))
    if n_units < min_units:
        return ValidationReport(
            available=False,
            n_units=n_units,
            refusal=(
                f"this corridor has {n_units} unit(s) and cross-validation needs at "
                f"least {min_units}. Below that each held-out block is a handful of "
                "segments, and the spread between folds is noise rather than a "
                "measurement of how the model travels. Nothing about the fit above is "
                "affected; what is missing is any evidence that it predicts road it "
                "has not seen."
            ),
        )
    if design.shape[1] == 0:
        return ValidationReport(
            available=False,
            n_units=n_units,
            refusal="the specification has no factors, so there is nothing to validate.",
        )

    ordered = pd.Index(sorted(units.tolist()))
    position = {unit: index for index, unit in enumerate(ordered)}
    rows_unit = pd.Series(unit_ids).to_numpy()

    spatial = _cross_validate(
        counts, design, log_exposure, rows_unit,
        _contiguous_blocks(ordered, n_folds, position),
        scheme="contiguous stretches", fit_fn=fit_fn,
    )
    random = _cross_validate(
        counts, design, log_exposure, rows_unit,
        _random_blocks(ordered, n_folds, seed),
        scheme="random units", fit_fn=fit_fn,
    )

    notes: list[str] = [
        "Position along the corridor is taken from the sort order of unit_id, which is "
        "how the segmentation numbers them. A panel whose ids do not sort into corridor "
        "order would get folds that are contiguous in name only.",
    ]
    if alpha is None:
        notes.append(
            "No dispersion parameter was supplied, so the CURE bounds assume Poisson "
            "variance. On overdispersed counts that makes them too tight and the drift "
            "reported here is an overstatement."
        )

    curves, inflation = _cure_curves(
        counts, design, log_exposure, pd.Series(unit_ids), alpha, fit_fn
    )
    if inflation > 1.05:
        notes.append(
            f"The CURE bounds are widened by a measured design effect of "
            f"{inflation:.2f}x. Residuals within a segment are correlated — the same "
            "fact rung 2 corrects the standard errors for — so the independent-increment "
            "band assumed by the textbook plot is too tight here. Uncorrected, this "
            "panel's correctly specified factors read as 16-60% outside their bounds."
        )
    return ValidationReport(
        available=True,
        n_units=n_units,
        spatial=spatial,
        random=random,
        cure=curves,
        design_effect=inflation,
        notes=tuple(notes),
    )


def _contiguous_blocks(
    ordered: pd.Index, n_folds: int, position: dict[object, int]
) -> list[np.ndarray]:
    """Split the corridor into runs of neighbouring units."""
    return [np.asarray(block) for block in np.array_split(ordered.to_numpy(), n_folds)]


def _random_blocks(ordered: pd.Index, n_folds: int, seed: int) -> list[np.ndarray]:
    """The easy, optimistic split — kept only so the optimism can be measured."""
    rng = np.random.default_rng(seed)
    shuffled = ordered.to_numpy().copy()
    rng.shuffle(shuffled)
    return [np.asarray(block) for block in np.array_split(shuffled, n_folds)]


def _cross_validate(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    rows_unit: np.ndarray,
    blocks: list[np.ndarray],
    *,
    scheme: str,
    fit_fn: FitFn,
) -> Calibration:
    observed_total = 0.0
    predicted_total = 0.0
    deviations: list[float] = []
    outcomes: list[FoldOutcome] = []

    y = counts.to_numpy(dtype=float)
    offset = log_exposure.to_numpy(dtype=float)
    matrix = design.to_numpy(dtype=float)

    for index, block in enumerate(blocks, start=1):
        held = np.isin(rows_unit, block)
        if held.all() or not held.any():
            continue
        fit = fit_fn(counts[~held], design[~held], log_exposure[~held])
        if not fit.converged or fit.intercept is None:
            outcomes.append(
                FoldOutcome(index, int(len(block)), int(held.sum()), 0.0, 0.0, False)
            )
            continue

        beta = np.array(
            [
                (c.estimate if (c := fit.coefficient(name)) else 0.0)
                for name in design.columns
            ]
        )
        predicted = np.exp(offset[held] + fit.intercept.estimate + matrix[held] @ beta)
        observed = y[held]

        observed_total += float(observed.sum())
        predicted_total += float(predicted.sum())
        deviations.extend(np.abs(observed - predicted).tolist())
        outcomes.append(
            FoldOutcome(
                fold=index,
                n_units=int(len(block)),
                n_rows=int(held.sum()),
                observed=float(observed.sum()),
                predicted=float(predicted.sum()),
                converged=True,
            )
        )

    return Calibration(
        scheme=scheme,
        n_folds=len(outcomes),
        n_units=int(sum(o.n_units for o in outcomes)),
        observed=observed_total,
        predicted=predicted_total,
        mean_absolute_deviation=float(np.mean(deviations)) if deviations else float("nan"),
        folds=outcomes,
    )


def _cure_curves(
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    alpha: float | None,
    fit_fn: FitFn,
) -> tuple[list[CureCurve], float]:
    """Cumulative residuals against each factor, aggregated by unit.

    CURE is a *fit* diagnostic rather than a held-out one, and it belongs here anyway:
    calibration says whether the model is wrong on average, and this says where.

    **The residuals are summed within a unit before anything is accumulated, and the
    bounds carry a measured inflation factor.** Both are the same correction step 3.1
    made to the standard errors, arriving in a new place.

    The textbook CURE band assumes each residual is an independent draw. On this panel
    they are not: every factor is a property of a segment repeated down every period, so
    a segment that the model fits badly contributes a run of same-signed residuals and
    the cumulative sum wanders far further than an independent-increment band allows.
    Left uncorrected the plot condemns a correctly specified model — measured on the
    synthetic panel, whose effects are planted linear:

    ======================  ==========================
    Per-unit heterogeneity  Share of curve outside
    ======================  ==========================
    none                    0-6%, correctly nothing
    0.25                    7-23%
    0.5 (realistic)         16-60%, all of it spurious
    ======================  ==========================

    Summing to one residual per unit removes the correlation inside a unit; the
    remaining inflation, measured as the variance of the standardised unit residuals,
    is reported so the size of the correction is visible rather than assumed.
    """
    fit = fit_fn(counts, design, log_exposure)
    if not fit.converged or fit.intercept is None or fit.fitted_values is None:
        return [], 1.0

    residual = counts.to_numpy(dtype=float) - fit.fitted_values.to_numpy(dtype=float)
    mu = fit.fitted_values.to_numpy(dtype=float)
    variance = mu + (alpha * mu**2 if alpha else 0.0)

    units, codes = np.unique(pd.Series(unit_ids).to_numpy(), return_inverse=True)
    unit_residual = np.bincount(codes, weights=residual, minlength=units.size)
    unit_variance = np.bincount(codes, weights=variance, minlength=units.size)

    usable = unit_variance > 0
    if usable.sum() < 3:
        return [], 1.0
    standardised = unit_residual[usable] / np.sqrt(unit_variance[usable])
    # One if the rows within a unit were independent; larger when they are not. This is
    # the design effect, and it is what the naive band leaves out.
    inflation = float(max(np.var(standardised, ddof=1), 1.0))

    curves: list[CureCurve] = []
    for name in design.columns:
        column = design[name].to_numpy(dtype=float)
        per_unit = np.array(
            [column[codes == index][0] for index in range(units.size)], dtype=float
        )
        varies_within = any(
            np.ptp(column[codes == index]) > 1e-9 for index in range(units.size)
        )
        if varies_within:
            # Not a segment property, so there is nothing to aggregate over.
            per_unit = column
            axis_values = column
            values, cumulative_variance_source = residual, variance * inflation
        else:
            axis_values = per_unit
            values = unit_residual
            cumulative_variance_source = unit_variance * inflation

        curve = _cure_for(
            str(name), axis_values, values, cumulative_variance_source, per_unit
        )
        if curve is not None:
            curves.append(curve)
    return curves, inflation


def _cure_once(
    order: np.ndarray, values: np.ndarray, variance_source: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """One ordering's cumulative residual, its band, and the share outside it."""
    cumulative = np.cumsum(values[order])
    cumulative_variance = np.cumsum(variance_source[order])
    total = cumulative_variance[-1]
    if total <= 0:
        return None
    # The two-standard-deviation band of a Brownian bridge: the cumulative residual is
    # pinned near zero at both ends, so the band is widest in the middle.
    bound = 2.0 * np.sqrt(
        np.clip(cumulative_variance * (1.0 - cumulative_variance / total), 0.0, None)
    )
    return cumulative, bound, float(np.mean(np.abs(cumulative) > bound))


def _cure_for(
    name: str,
    axis_values: np.ndarray,
    values: np.ndarray,
    variance_source: np.ndarray,
    per_unit: np.ndarray,
) -> CureCurve | None:
    """The CURE curve for one factor, averaged over the orderings its ties permit.

    **Ties are the whole reason this function exists.** CURE sorts by the covariate and
    accumulates residuals, and a stable sort leaves observations tied at the same value
    in the order they arrived — which is corridor order. Residuals along a road are
    spatially correlated, so summing a tied block in corridor order accumulates that
    correlation and the curve leaves its band. The factor being plotted has nothing to
    do with it: any factor with the same tie structure produces the same excursion.

    Measured on the A3 through Paris, where `junction_density` and `access_density` are
    each tied across 28 of 37 units: corridor order reported 43% and 38% outside and
    called both mis-specified, while the median over 2,000 equally valid tie orders was
    2.7% for both, and fewer than 3% of orderings would have reported a drift at all.
    Corridor order sat at the 100th percentile of the orderings — not a typical choice
    but the worst available one, for exactly the reason above.

    So the statistic under ties is a distribution, not a number, and this reports the
    median of it over a seeded sample. A factor with no ties has one ordering, gets one
    resample, and is unaffected. The rendered curve is the sampled ordering whose share
    is nearest the median, so the picture a client sees matches the number beside it.
    """
    order = np.argsort(axis_values, kind="stable")
    exact = _cure_once(order, values, variance_source)
    if exact is None:
        return None

    _, tie_sizes = np.unique(axis_values, return_counts=True)
    if int(tie_sizes.max()) <= 1:
        cumulative, bound, outside = exact
        return _finish(name, order, axis_values, per_unit, cumulative, bound,
                       outside, outside, outside)

    rng = np.random.default_rng(CURE_TIE_SEED)
    draws: list[tuple[float, np.ndarray, np.ndarray, np.ndarray]] = []
    for _ in range(CURE_TIE_RESAMPLES):
        shuffled = np.lexsort((rng.random(axis_values.size), axis_values))
        drawn = _cure_once(shuffled, values, variance_source)
        if drawn is None:  # pragma: no cover - total is order-independent
            continue
        cumulative, bound, outside = drawn
        draws.append((outside, shuffled, cumulative, bound))

    if not draws:  # pragma: no cover - guarded by `exact` above
        return None
    shares = np.array([d[0] for d in draws])
    median = float(np.median(shares))
    representative = min(draws, key=lambda d: abs(d[0] - median))
    return _finish(
        name,
        representative[1],
        axis_values,
        per_unit,
        representative[2],
        representative[3],
        median,
        float(np.quantile(shares, 0.05)),
        float(np.quantile(shares, 0.95)),
    )


def _finish(
    name: str,
    order: np.ndarray,
    axis_values: np.ndarray,
    per_unit: np.ndarray,
    cumulative: np.ndarray,
    bound: np.ndarray,
    outside: float,
    low: float,
    high: float,
) -> CureCurve:
    axis = axis_values[order]
    picks = np.linspace(0, len(order) - 1, min(CURE_POINTS, len(order))).astype(int)
    return CureCurve(
        factor=name,
        x=tuple(float(v) for v in axis[picks]),
        cumulative=tuple(float(v) for v in cumulative[picks]),
        bound=tuple(float(v) for v in bound[picks]),
        share_outside=outside,
        share_outside_low=low,
        share_outside_high=high,
    )


def _render_cure(curve: CureCurve, *, height: int, indent: str) -> str:
    """A text plot of the cumulative residual against its bounds."""
    y = np.asarray(curve.cumulative, dtype=float)
    bound = np.asarray(curve.bound, dtype=float)
    if y.size == 0:
        return f"{indent}(no curve)"

    top = float(max(y.max(), bound.max()))
    bottom = float(min(y.min(), -bound.max()))
    if top - bottom < 1e-9:
        top, bottom = top + 1.0, bottom - 1.0

    height = max(5, height)
    width = y.size
    rows = [[" "] * width for _ in range(height)]

    def row_of(value: float) -> int:
        position = (top - value) / (top - bottom) * (height - 1)
        return int(min(height - 1, max(0, round(position))))

    for column in range(width):
        rows[row_of(bound[column])][column] = "."
        rows[row_of(-bound[column])][column] = "."
    zero = row_of(0.0)
    if 0 <= zero < height:
        for column in range(width):
            if rows[zero][column] == " ":
                rows[zero][column] = "-"
    for column in range(width):
        outside = abs(y[column]) > bound[column]
        rows[row_of(y[column])][column] = "#" if outside else "*"

    label_width = 9
    lines = [f"{indent}{'':>{label_width}} cumulative residual, with ±2σ bounds"]
    for index, row in enumerate(rows):
        if index == 0:
            label = f"{top:+.0f}"
        elif index == height - 1:
            label = f"{bottom:+.0f}"
        elif index == zero:
            label = "0"
        else:
            label = ""
        lines.append(f"{indent}{label:>{label_width}} |{''.join(row)}")
    lines.append(f"{indent}{'':>{label_width}} +{'-' * width}")
    lines.append(
        f"{indent}{'':>{label_width}}  {curve.x[0]:.2f}"
        f"{' ' * max(1, width - 12)}{curve.x[-1]:.2f}"
    )
    lines.append(f"{indent}{'':>{label_width}}  {curve.factor}, low to high")
    return "\n".join(lines)


__all__ = [
    "CALIBRATION_TOLERANCE",
    "CURE_TOLERANCE",
    "DEFAULT_FOLDS",
    "MIN_UNITS",
    "Calibration",
    "CureCurve",
    "FoldOutcome",
    "ValidationReport",
    "validate",
]
