"""Rung 3 — the GAM spline diagnostic. It hunts the U-shape, and it never ships.

    a factor  →  penalised spline, everything else linear  →  a curve  →  a shape

The brief states the mechanism this exists to catch:

    A linear term forces geometry to be monotonic. Reality is plausibly a **U-shape**:
    dead-straight is dangerous (speed, fatigue), gentle curve is fine, sharp curve is
    dangerous. **A linear fit through a U-shape can return a negative coefficient —
    exactly the M51 symptom.**

That is the third of the three suspects behind ``ln(GF) = -0.730``, and it is the only
one a single plot can settle. Confounding needs a second corridor and a missing mediator
needs speed data; composite masking needs this module and nothing else.

**It is structurally incapable of becoming the assessment.** :class:`ShapeDiagnostic`
has no coefficient, no p-value, no predicted count and no interval — not by convention
but by type, the same guarantee :class:`~roadrisk.core.models.index.IndexResult` gives
in the other direction. The brief files the GAM under *reference only, never in the
client report*, and a type that cannot express a client number cannot leak into one.

**The band is a cluster bootstrap, not the model's own standard errors.** Step 3.1
established that this panel's rows are not independent — every factor is a property of
a segment repeated down every period — so a spline's nominal confidence band would be
too narrow for exactly the reason rung 1's intervals were. Resampling *units* with
replacement keeps the correction the project already paid for. The headline it produces
is better than a band anyway: how many resampled corridors still show the shape.

**The shape reported is the one that survives the smoothing grid, not the one at the
best-fitting penalty.** This was measured rather than assumed. On an ordinary panel
whose curvature effect is genuinely linear, the lowest-AIC penalty drew an inverted U —
a finding out of nothing, on the exact factor the M51 argument is about. Across the
grid it was the odd one out: every other penalty read the same data as monotonic. On a
panel with a *planted* U the U held at three penalties of five. So the headline is the
majority shape across the grid, the curve drawn is the best-fitting fit that agrees with
it, and every penalty's answer is reported either way.

Selecting by a cluster-aware information criterion was tried first and abandoned: the
effective-degrees-of-freedom differences between penalties are far smaller than the
deviance differences, so charging ``ln(units)`` per parameter instead of 2 changed the
chosen penalty on none of the test panels. The problem was never the accounting.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd
import statsmodels.api as sm

from roadrisk.core.registry import Sign
from roadrisk.core.runlog import RunLog

STAGE = "shape"

#: Basis dimension for the spline. Six cubic B-spline bases can express a straight
#: line, a single bend and a U, and cannot express the twelve-turn wiggle that would
#: let a reader find whatever they went looking for. The penalty does the rest.
DEFAULT_DF = 6
DEFAULT_DEGREE = 3

#: Smoothing penalties tried, chosen by AIC. Spans three orders of magnitude because
#: the interesting failure is at the top of it: at a heavy enough penalty every spline
#: is a straight line and the diagnostic silently agrees with the term it is checking.
PENALTY_GRID: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0, 1000.0)

#: Distinct values of the factor needed before a spline is worth fitting. Every factor
#: on a corridor panel is unit-constant, so this is a count of *units*, not of rows.
MIN_DISTINCT_X = 20

#: Curve range, in log crash rate, below which the factor is called flat. 0.10 is about
#: a 10% difference in rate between the safest and least safe value of the factor —
#: below that there is no shape to interpret whatever the spline drew.
FLAT_RANGE = 0.10

#: How much of the curve's total range each arm of a turning point must recover before
#: the turn is called real rather than a wobble.
ARM_SHARE = 0.25

#: Turning points inside this fraction of either end are not counted. Splines are least
#: constrained at the edges of the data, and an upturn in the last two percent of the x
#: range is the classic way to see a U that is not there.
EDGE_MARGIN = 0.15

#: Resampled corridors drawn to test whether the shape survives. Units, not rows.
DEFAULT_RESAMPLES = 40

#: Points the curve is evaluated on.
GRID_POINTS = 41

#: The x range is trimmed to these quantiles. The extreme few percent of any covariate
#: carry almost no data and all of the spline's freedom.
X_QUANTILES = (0.02, 0.98)


class Shape(StrEnum):
    """What the curve does across the range of the factor."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    U_SHAPED = "u_shaped"
    INVERTED_U = "inverted_u"
    WAVY = "wavy"
    FLAT = "flat"

    @property
    def is_monotonic(self) -> bool:
        return self in (Shape.INCREASING, Shape.DECREASING)

    @property
    def is_turning(self) -> bool:
        """A single interior turn — the shape a linear term cannot represent."""
        return self in (Shape.U_SHAPED, Shape.INVERTED_U)

    @property
    def as_sign(self) -> int:
        """The sign a linear term would report, where the curve implies one."""
        if self is Shape.INCREASING:
            return 1
        if self is Shape.DECREASING:
            return -1
        return 0

    def describe(self) -> str:
        return {
            Shape.INCREASING: "rises across the whole range",
            Shape.DECREASING: "falls across the whole range",
            Shape.U_SHAPED: "falls, turns and rises — a U",
            Shape.INVERTED_U: "rises, turns and falls — an inverted U",
            Shape.WAVY: "turns more than once",
            Shape.FLAT: "is flat",
        }[self]


@dataclass(frozen=True)
class ShapeCurve:
    """The fitted partial effect, and the bootstrap band around it.

    ``y`` is on the log crash-rate scale and centred on its own mean, so it reads as
    *relative* risk across the factor's range and carries no baseline. There is
    deliberately nothing here that can be quoted as an effect size for a road.
    """

    factor: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    lower: tuple[float, ...] = ()
    upper: tuple[float, ...] = ()

    @property
    def span(self) -> float:
        """Highest minus lowest point on the curve, in log crash rate."""
        return float(max(self.y) - min(self.y)) if self.y else 0.0

    @property
    def has_band(self) -> bool:
        return len(self.lower) == len(self.y) and bool(self.lower)

    def render(self, *, height: int = 11, indent: str = "") -> str:
        """Draw the curve as text. This is the diagnostic plot."""
        return _render(self, height=height, indent=indent)


@dataclass(frozen=True)
class ResampleReport:
    """How often the shape survived a corridor resampled by unit."""

    n_resamples: int
    n_fitted: int
    n_agreeing: int
    shapes: dict[str, int] = field(default_factory=dict)

    @property
    def share(self) -> float:
        return self.n_agreeing / self.n_fitted if self.n_fitted else 0.0

    @property
    def stable(self) -> bool:
        """Two thirds is the bar. Below it the shape is a property of these units."""
        return self.n_fitted > 0 and self.share >= 2 / 3


@dataclass(frozen=True)
class ShapeDiagnostic:
    """What the spline found for one factor.

    **Read the field list.** There is no coefficient, no standard error, no p-value, no
    predicted count and no confidence interval on an effect. This type exists to answer
    one question — *is the linear term being forced through a bend?* — and it is built
    so that it cannot be made to answer any other. ``linear_estimate`` is the shipped
    fit's own number, carried here for comparison and never computed by this module.
    """

    factor: str
    available: bool
    n_units: int
    n_observations: int
    shape: Shape | None = None
    curve: ShapeCurve | None = None
    turning_point: float | None = None
    penalty: float | None = None
    edf: float | None = None
    penalty_shapes: tuple[tuple[float, Shape], ...] = ()
    resamples: ResampleReport | None = None
    linear_estimate: float | None = None
    expected_sign: Sign | None = None
    explains_contradiction: bool = False
    verdict: str = ""
    refusal: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def penalty_sensitive(self) -> bool:
        """True when smoothing choice alone changes the shape."""
        shapes = {shape for _, shape in self.penalty_shapes}
        return len(shapes) > 1

    def report(self, *, indent: str = "") -> str:
        """The diagnostic as it should be read: the plot, then what it means."""
        if not self.available:
            return f"{indent}{self.factor}: {self.refusal or 'not available'}"
        lines = [f"{indent}{self.factor} — the curve {self.shape.describe()}"]  # type: ignore[union-attr]
        if self.curve is not None:
            lines.append(self.curve.render(indent=indent))
        lines.append(f"{indent}{self.verdict}")
        lines.extend(f"{indent}{note}" for note in self.notes)
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        """Serialisable form, for the run record's reference appendix."""
        return {
            "factor": self.factor,
            "available": self.available,
            "shape": self.shape.value if self.shape else None,
            "turning_point": self.turning_point,
            "penalty": self.penalty,
            "edf": self.edf,
            "penalty_shapes": [[p, s.value] for p, s in self.penalty_shapes],
            "penalty_sensitive": self.penalty_sensitive,
            "n_units": self.n_units,
            "n_observations": self.n_observations,
            "curve": (
                {
                    "x": list(self.curve.x),
                    "y": list(self.curve.y),
                    "lower": list(self.curve.lower),
                    "upper": list(self.curve.upper),
                }
                if self.curve
                else None
            ),
            "resamples": (
                {
                    "drawn": self.resamples.n_resamples,
                    "fitted": self.resamples.n_fitted,
                    "agreeing": self.resamples.n_agreeing,
                    "share": round(self.resamples.share, 4),
                    "shapes": self.resamples.shapes,
                }
                if self.resamples
                else None
            ),
            "linear_estimate": self.linear_estimate,
            "expected_sign": self.expected_sign.value if self.expected_sign else None,
            "explains_contradiction": self.explains_contradiction,
            "verdict": self.verdict,
            "refusal": self.refusal,
            "notes": list(self.notes),
        }


def hunt_shape(
    *,
    factor: str,
    counts: pd.Series,
    design: pd.DataFrame,
    log_exposure: pd.Series,
    unit_ids: pd.Series,
    alpha: float | None = None,
    expected_sign: Sign | None = None,
    linear_estimate: float | None = None,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
    log: RunLog | None = None,
) -> ShapeDiagnostic:
    """Fit a penalised spline on one factor and say what shape it has.

    Every other factor in ``design`` stays linear, so the curve is the partial effect of
    ``factor`` holding the rest of the specification fixed — the same quantity the
    linear coefficient claims to summarise.

    Args:
        factor: Column in ``design`` to put the spline on.
        counts: ``n_crashes``.
        design: The transformed design matrix the shipped fit used.
        log_exposure: ``ln(length_km * duration_hours)``, the offset.
        unit_ids: Unit id per row. The resampling clusters.
        alpha: NB2 dispersion from the shipped fit. Without it the spline is fitted
            with a Poisson family, which biases nothing about the shape but makes the
            band optimistic — recorded as a note when it happens.
        expected_sign: The factor's declared direction, when there is one.
        linear_estimate: The shipped fit's coefficient, carried for comparison. Never
            recomputed here.
        n_resamples: Corridors resampled by unit to test the shape. Zero skips it.
        seed: RNG seed for that resampling.
        log: Run log, when the caller wants the finding recorded.

    Returns:
        A :class:`ShapeDiagnostic`. When the spline cannot be fitted it comes back with
        ``available = False`` and a reason, never an exception — a diagnostic that
        crashes the run it was meant to explain is worse than no diagnostic.
    """
    n_observations = int(len(counts))
    n_units = int(pd.Series(unit_ids).nunique())

    refusal = _why_not(factor, design)
    if refusal is not None:
        diagnostic = ShapeDiagnostic(
            factor=factor,
            available=False,
            n_units=n_units,
            n_observations=n_observations,
            linear_estimate=linear_estimate,
            expected_sign=expected_sign,
            refusal=refusal,
        )
        if log is not None:
            log.warning(STAGE, "shape_unavailable", f"'{factor}': {refusal}", factor=factor)
        return diagnostic

    x = design[factor].to_numpy(dtype=float)
    others = design.drop(columns=[factor])
    endog = counts.to_numpy(dtype=float)
    offset = log_exposure.to_numpy(dtype=float)
    exog = sm.add_constant(others.astype(float), has_constant="add").to_numpy(dtype=float)
    family = _family(alpha)
    grid = _grid(x)

    fitted = [
        (penalty, curve)
        for penalty in PENALTY_GRID
        if (curve := _fit_curve(endog, exog, x, offset, family, penalty, grid))
        is not None
    ]
    if not fitted:
        diagnostic = ShapeDiagnostic(
            factor=factor,
            available=False,
            n_units=n_units,
            n_observations=n_observations,
            linear_estimate=linear_estimate,
            expected_sign=expected_sign,
            refusal=(
                "the penalised spline did not converge at any smoothing penalty on the "
                "grid, so there is no curve to read."
            ),
        )
        if log is not None:
            log.warning(
                STAGE,
                "shape_unavailable",
                f"'{factor}': {diagnostic.refusal}",
                factor=factor,
            )
        return diagnostic

    penalty_shapes = tuple(
        (penalty, classify(curve.values)) for penalty, curve in fitted
    )
    penalty, chosen, shape = _choose(fitted, penalty_shapes)

    resamples = _resample(
        endog=endog,
        exog=exog,
        x=x,
        offset=offset,
        unit_ids=pd.Series(unit_ids).to_numpy(),
        family=family,
        penalty=penalty,
        grid=grid,
        shape=shape,
        n_resamples=n_resamples,
        seed=seed,
    )
    lower, upper = resamples[1] if resamples else ((), ())
    report = resamples[0] if resamples else None

    curve = ShapeCurve(
        factor=factor,
        x=tuple(float(v) for v in grid),
        y=tuple(float(v) for v in chosen.values),
        lower=lower,
        upper=upper,
    )
    turning = _turning_x(chosen.values, grid, shape)
    notes = _notes(alpha, n_units, penalty, penalty_shapes, shape)
    verdict = _verdict(
        factor=factor,
        shape=shape,
        linear_estimate=linear_estimate,
        expected_sign=expected_sign,
        turning_point=turning,
        curve=curve,
        resamples=report,
    )

    diagnostic = ShapeDiagnostic(
        factor=factor,
        available=True,
        n_units=n_units,
        n_observations=n_observations,
        shape=shape,
        curve=curve,
        turning_point=turning,
        penalty=penalty,
        edf=chosen.edf,
        penalty_shapes=penalty_shapes,
        resamples=report,
        linear_estimate=linear_estimate,
        expected_sign=expected_sign,
        explains_contradiction=_explains(
            shape, linear_estimate, expected_sign, report
        ),
        verdict=verdict,
        notes=notes,
    )

    if log is not None:
        log.info(
            STAGE,
            "shape_diagnostic",
            f"'{factor}': the spline {shape.describe()}. {verdict}",
            factor=factor,
            shape=shape.value,
            penalty=penalty,
            edf=round(chosen.edf, 3) if chosen.edf is not None else None,
            explains_contradiction=diagnostic.explains_contradiction,
        )
    return diagnostic


# ---- the fit -----------------------------------------------------------------


@dataclass(frozen=True)
class _Curve:
    """One penalty's answer."""

    values: np.ndarray
    aic: float
    edf: float | None


def _choose(
    fitted: list[tuple[float, _Curve]],
    penalty_shapes: tuple[tuple[float, Shape], ...],
) -> tuple[float, _Curve, Shape]:
    """Pick the shape the grid agrees on, and a curve that shows it.

    The headline is the shape found at the most penalties. Ties go to the shape at the
    best-fitting penalty, and the curve drawn is the best-fitting fit *that agrees with
    the headline*, so the plot and the sentence above it can never disagree.

    Choosing the best-fitting fit outright is what produced a spurious inverted U on a
    panel whose effect was linear. One penalty out of five said so and AIC picked that
    one; the diagnostic would have reported a shape the data does not have, which is the
    one failure mode this module cannot be allowed to have.
    """
    tally: dict[Shape, int] = {}
    for _, shape in penalty_shapes:
        tally[shape] = tally.get(shape, 0) + 1

    ranked = sorted(fitted, key=lambda pair: pair[1].aic)
    best_shape = classify(ranked[0][1].values)
    top = max(tally.values())
    # `best_shape` first, so a tie resolves toward the fit the data likes most.
    winner = (
        best_shape
        if tally.get(best_shape, 0) == top
        else next(shape for shape, count in tally.items() if count == top)
    )

    for penalty, curve in ranked:
        if classify(curve.values) is winner:
            return penalty, curve, winner
    return ranked[0][0], ranked[0][1], best_shape


def _why_not(factor: str, design: pd.DataFrame) -> str | None:
    """Reasons a spline is not worth fitting, stated before one is attempted."""
    if factor not in design.columns:
        return f"there is no column '{factor}' in the design matrix."
    values = design[factor].to_numpy(dtype=float)
    distinct = int(np.unique(values).size)
    if distinct < MIN_DISTINCT_X:
        return (
            f"the factor takes only {distinct} distinct value(s) on this panel, and a "
            f"spline needs at least {MIN_DISTINCT_X} to describe a shape rather than "
            "join up a handful of points. Every factor here is unit-constant, so this "
            "is a statement about how many units the corridor has."
        )
    return None


def _family(alpha: float | None) -> object:
    if alpha is not None and alpha > 0:
        return sm.families.NegativeBinomial(alpha=float(alpha))
    return sm.families.Poisson()


def _grid(x: np.ndarray) -> np.ndarray:
    low, high = np.quantile(x, X_QUANTILES)
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low, high = float(np.min(x)), float(np.max(x))
    return np.linspace(float(low), float(high), GRID_POINTS)


def _fit_curve(
    endog: np.ndarray,
    exog: np.ndarray,
    x: np.ndarray,
    offset: np.ndarray,
    family: object,
    penalty: float,
    grid: np.ndarray,
) -> _Curve | None:
    """Fit at one penalty and evaluate the smooth on the grid. None if it fails."""
    from statsmodels.gam.api import BSplines, GLMGam

    frame = pd.DataFrame({"x": x})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            splines = BSplines(frame, df=[DEFAULT_DF], degree=[DEFAULT_DEGREE])
            results = GLMGam(
                endog,
                exog=exog,
                smoother=splines,
                alpha=[penalty],
                family=family,
                offset=offset,
            ).fit()
            basis = np.asarray(
                splines.transform(np.clip(grid, x.min(), x.max()).reshape(-1, 1))
            )
    except Exception:  # noqa: BLE001 - a diagnostic never crashes the run it explains
        return None

    params = np.asarray(results.params, dtype=float)
    width = basis.shape[1]
    if width == 0 or width > params.size:
        return None
    values = basis @ params[-width:]
    if not np.all(np.isfinite(values)):
        return None

    aic = float(getattr(results, "aic", np.nan))
    if not np.isfinite(aic):
        return None
    edf = getattr(results, "edf", None)
    return _Curve(
        values=values - float(np.mean(values)),
        aic=aic,
        edf=float(np.sum(edf)) if edf is not None else None,
    )


def _resample(
    *,
    endog: np.ndarray,
    exog: np.ndarray,
    x: np.ndarray,
    offset: np.ndarray,
    unit_ids: np.ndarray,
    family: object,
    penalty: float,
    grid: np.ndarray,
    shape: Shape,
    n_resamples: int,
    seed: int,
) -> tuple[ResampleReport, tuple[tuple[float, ...], tuple[float, ...]]] | None:
    """Redraw the corridor's units with replacement and refit.

    Resampling *units* rather than rows is the whole point. Step 3.1 measured what
    happens when this panel's rows are treated as independent: rung 1's 95% intervals
    held the truth 70% of the time. A bootstrap over rows would repeat that mistake in
    a new place.
    """
    if n_resamples <= 0:
        return None

    rng = np.random.default_rng(seed)
    units = np.unique(unit_ids)
    rows_by_unit = {unit: np.flatnonzero(unit_ids == unit) for unit in units}

    curves: list[np.ndarray] = []
    counted: dict[str, int] = {}
    agreeing = 0

    for _ in range(n_resamples):
        drawn = rng.choice(units, size=units.size, replace=True)
        rows = np.concatenate([rows_by_unit[unit] for unit in drawn])
        curve = _fit_curve(
            endog[rows], exog[rows], x[rows], offset[rows], family, penalty, grid
        )
        if curve is None:
            continue
        curves.append(curve.values)
        drawn_shape = classify(curve.values)
        counted[drawn_shape.value] = counted.get(drawn_shape.value, 0) + 1
        if drawn_shape is shape:
            agreeing += 1

    if not curves:
        return None

    stacked = np.vstack(curves)
    lower = tuple(float(v) for v in np.percentile(stacked, 2.5, axis=0))
    upper = tuple(float(v) for v in np.percentile(stacked, 97.5, axis=0))
    return (
        ResampleReport(
            n_resamples=n_resamples,
            n_fitted=len(curves),
            n_agreeing=agreeing,
            shapes=counted,
        ),
        (lower, upper),
    )


# ---- reading the curve -------------------------------------------------------


def classify(
    values: np.ndarray,
    *,
    flat_range: float = FLAT_RANGE,
    arm_share: float = ARM_SHARE,
    edge_margin: float = EDGE_MARGIN,
) -> Shape:
    """Name the shape of a curve.

    A turning point counts only when it is away from the edges — splines are least
    constrained there — and when both of its arms recover a real share of the curve's
    total range. Everything else is a wobble, and calling a wobble a U is how a
    diagnostic starts manufacturing the finding it went looking for.
    """
    y = np.asarray(values, dtype=float)
    if y.size < 3:
        return Shape.FLAT
    span = float(y.max() - y.min())
    if span < flat_range:
        return Shape.FLAT

    threshold = arm_share * span
    turns = _turning_points(y, threshold, edge_margin)
    if len(turns) > 1:
        return Shape.WAVY
    if len(turns) == 1:
        return Shape.U_SHAPED if turns[0][1] == "min" else Shape.INVERTED_U
    return Shape.INCREASING if y[-1] >= y[0] else Shape.DECREASING


def _turning_points(
    y: np.ndarray, threshold: float, edge_margin: float
) -> list[tuple[int, str]]:
    """Interior points where the curve reverses by at least ``threshold``.

    A zigzag walk: hold the running extreme, and record a turn only once the curve has
    moved back from it by the threshold. That ignores small reversals without needing
    the curve to be smooth, and it counts a genuine wave as two turns rather than one.
    """
    points: list[tuple[int, str]] = []
    if y.size < 3:
        return points

    edge = int(round(edge_margin * (y.size - 1)))
    interior = range(edge, y.size - edge)

    extreme_index, extreme_value = 0, float(y[0])
    direction = 0  # +1 rising from the last turn, -1 falling, 0 not yet moved

    for index in range(1, y.size):
        value = float(y[index])
        if direction >= 0 and value >= extreme_value:
            extreme_index, extreme_value = index, value
            if direction == 0 and value - float(y[0]) >= threshold:
                direction = 1
            continue
        if direction <= 0 and value <= extreme_value:
            extreme_index, extreme_value = index, value
            if direction == 0 and float(y[0]) - value >= threshold:
                direction = -1
            continue
        if direction >= 0 and extreme_value - value >= threshold:
            if extreme_index in interior:
                points.append((extreme_index, "max"))
            direction, extreme_index, extreme_value = -1, index, value
        elif direction <= 0 and value - extreme_value >= threshold:
            if extreme_index in interior:
                points.append((extreme_index, "min"))
            direction, extreme_index, extreme_value = 1, index, value

    return points


def _turning_x(values: np.ndarray, grid: np.ndarray, shape: Shape) -> float | None:
    """Where on the factor's scale the curve turns."""
    if not shape.is_turning:
        return None
    index = int(np.argmin(values) if shape is Shape.U_SHAPED else np.argmax(values))
    return float(grid[index])


def _explains(
    shape: Shape,
    linear_estimate: float | None,
    expected_sign: Sign | None,
    resamples: ResampleReport | None,
) -> bool:
    """Does the shape account for a linear term pointing the wrong way?

    A turn that a majority of resampled corridors did not reproduce explains nothing.
    Being the reason a reviewer stops worrying about a wrong sign is a heavy claim, and
    it is refused unless the shape survived both the smoothing grid and the resampling.
    """
    if not shape.is_turning or linear_estimate is None or expected_sign is None:
        return False
    if resamples is not None and not resamples.stable:
        return False
    fitted_sign = 1 if linear_estimate > 0 else -1 if linear_estimate < 0 else 0
    return fitted_sign != 0 and fitted_sign != expected_sign.as_int


def _notes(
    alpha: float | None,
    n_units: int,
    penalty: float,
    penalty_shapes: tuple[tuple[float, Shape], ...],
    shape: Shape,
) -> tuple[str, ...]:
    notes: list[str] = []

    shapes = {found for _, found in penalty_shapes}
    if len(shapes) > 1:
        held = [f"{p:g}" for p, found in penalty_shapes if found is shape]
        lost = [
            f"{p:g}: {found.value}" for p, found in penalty_shapes if found is not shape
        ]
        notes.append(
            f"Smoothing changes the answer. This shape holds at {len(held)} of "
            f"{len(penalty_shapes)} penalties on the grid — {', '.join(held)}, drawn at "
            f"{penalty:g} — and elsewhere reads {'; '.join(lost)}. Both directions of "
            "that disagreement matter: a heavy penalty flattens any curve into the "
            "straight line the linear term already assumed, and a light one will find a "
            "bend in noise."
        )
    else:
        notes.append(
            f"The shape is the same at every penalty on the grid "
            f"({', '.join(f'{p:g}' for p, _ in penalty_shapes)}), so it is not an "
            "artefact of how hard the spline was smoothed."
        )

    if alpha is None:
        notes.append(
            "Fitted with a Poisson family because no dispersion parameter was supplied. "
            "The shape is unaffected; the resampled band is narrower than it should be."
        )

    notes.append(
        f"Reference only. This curve is a diagnostic on {n_units:,} units and must not "
        "be quoted as an effect size, a crash prediction or a countermeasure "
        "justification. It says what the linear term is hiding, not what the road does."
    )
    return tuple(notes)


def _verdict(
    *,
    factor: str,
    shape: Shape,
    linear_estimate: float | None,
    expected_sign: Sign | None,
    turning_point: float | None,
    curve: ShapeCurve,
    resamples: ResampleReport | None,
) -> str:
    """What the shape means for the coefficient the model is reporting."""
    stability = ""
    if resamples is not None and resamples.n_fitted:
        stability = (
            f" The same shape came back on {resamples.n_agreeing} of "
            f"{resamples.n_fitted} corridors resampled by unit"
            + ("" if resamples.stable else ", which is not a stable majority")
            + "."
        )

    if shape is Shape.FLAT:
        return (
            f"'{factor}' is flat once the rest of the specification is held fixed — the "
            f"whole curve spans {curve.span:.2f} in log crash rate. There is no shape "
            "here for a linear term to have got wrong, and no shape to report."
            + stability
        )

    if shape is Shape.WAVY:
        return (
            f"'{factor}' turns more than once. A road safety mechanism that reverses "
            "twice across one factor is unlikely; an under-penalised spline that does "
            "so is ordinary. Read this as 'the spline found no interpretable shape' "
            "rather than as a finding." + stability
        )

    if shape.is_turning:
        where = f" around {turning_point:.2f} on the transformed scale" if turning_point else ""
        head = (
            f"'{factor}' is not monotonic: the curve {shape.describe()}{where}. "
            "A straight line through this returns the average slope, which is a number "
            "no part of the road actually has."
        )
        if linear_estimate is not None and expected_sign is not None:
            fitted_sign = 1 if linear_estimate > 0 else -1
            if fitted_sign != expected_sign.as_int:
                if resamples is not None and not resamples.stable:
                    return (
                        head
                        + f" The shipped fit reports {linear_estimate:+.3f} against a "
                        f"declared expectation of '{expected_sign.value}', and a turn "
                        "would explain that — but this one did not survive resampling, "
                        "so it is not offered as the explanation. Treat the reversal as "
                        "unexplained." + stability
                    )
                return (
                    head
                    + f" The shipped fit reports {linear_estimate:+.3f} against a "
                    f"declared expectation of '{expected_sign.value}', and this is a "
                    "sufficient explanation for that reversal — the third of the "
                    "brief's three suspects, composite masking, rather than confounding "
                    "or a missing mediator. The term must not be interpreted as causal "
                    "in either direction. The fix is a specification that can bend: "
                    "split the factor at the turning point, or carry it as two terms."
                    + stability
                )
        return (
            head
            + " The linear term for this factor is reporting an average of two opposite "
            "regimes and should not be read as one effect." + stability
        )

    direction = "rises" if shape is Shape.INCREASING else "falls"
    head = (
        f"'{factor}' {direction} monotonically across its range, so the linear term is "
        "not being forced through a bend."
    )
    if linear_estimate is not None and expected_sign is not None:
        fitted_sign = 1 if linear_estimate > 0 else -1
        if fitted_sign != expected_sign.as_int:
            return (
                head
                + f" The shipped fit reports {linear_estimate:+.3f} against a declared "
                f"expectation of '{expected_sign.value}', and the curve agrees with the "
                "coefficient rather than with the expectation. **Shape is not the "
                "explanation.** That leaves the brief's other two suspects — "
                "confounding with a correlated or omitted variable, which needs a "
                "second corridor, and a missing mediator such as operating speed, which "
                "needs speed data. Neither is answerable from this panel." + stability
            )
    return head + stability


# ---- the plot ----------------------------------------------------------------

_CURVE_MARK = "*"
_BAND_MARK = "."
_ZERO_MARK = "-"


def _render(curve: ShapeCurve, *, height: int, indent: str) -> str:
    """Draw the curve as a text plot.

    Text rather than an image on purpose: ``core`` depends on pandas and statsmodels and
    nothing else, the CLI is the only surface this project has today, and a plot nobody
    can see without installing a plotting stack is not a plot. The curve travels as data
    on :class:`ShapeCurve`, which is the seam the HTML report in stage 4 will draw from.
    """
    y = np.asarray(curve.y, dtype=float)
    if y.size == 0:
        return f"{indent}(no curve)"

    lower = np.asarray(curve.lower, dtype=float) if curve.has_band else y
    upper = np.asarray(curve.upper, dtype=float) if curve.has_band else y
    top = float(max(y.max(), upper.max()))
    bottom = float(min(y.min(), lower.min()))
    if top - bottom < 1e-9:
        top, bottom = top + 0.05, bottom - 0.05

    height = max(5, height)
    width = y.size
    rows = [[" "] * width for _ in range(height)]

    def row_of(value: float) -> int:
        position = (top - value) / (top - bottom) * (height - 1)
        return int(min(height - 1, max(0, round(position))))

    if curve.has_band:
        for column in range(width):
            for row in range(row_of(upper[column]), row_of(lower[column]) + 1):
                rows[row][column] = _BAND_MARK

    # After the band, not before: zero is the reference the reader measures against,
    # and a band wide enough to swallow it is exactly when that matters most.
    zero_row = row_of(0.0) if bottom <= 0.0 <= top else None
    if zero_row is not None:
        rows[zero_row] = [_ZERO_MARK] * width

    for column in range(width):
        rows[row_of(y[column])][column] = _CURVE_MARK

    label_width = 7
    lines = [
        f"{indent}{'':>{label_width}} partial effect on ln(crash rate), centred",
    ]
    for index, row in enumerate(rows):
        if index == 0:
            label = f"{top:+.2f}"
        elif index == height - 1:
            label = f"{bottom:+.2f}"
        elif index == zero_row:
            label = "0.00"
        else:
            label = ""
        lines.append(f"{indent}{label:>{label_width}} |{''.join(row)}")

    axis = "-" * width
    lines.append(f"{indent}{'':>{label_width}} +{axis}")
    left = f"{curve.x[0]:.2f}"
    right = f"{curve.x[-1]:.2f}"
    middle = f"{curve.x[width // 2]:.2f}"
    pad = max(1, width - len(left) - len(right) - len(middle))
    gap_left = " " * (pad // 2)
    gap_right = " " * (pad - pad // 2)
    lines.append(
        f"{indent}{'':>{label_width}}  {left}{gap_left}{middle}{gap_right}{right}"
    )
    lines.append(f"{indent}{'':>{label_width}}  {curve.factor}, transformed scale")
    return "\n".join(lines)


__all__ = [
    "ARM_SHARE",
    "DEFAULT_DF",
    "DEFAULT_RESAMPLES",
    "EDGE_MARGIN",
    "FLAT_RANGE",
    "MIN_DISTINCT_X",
    "PENALTY_GRID",
    "ResampleReport",
    "Shape",
    "ShapeCurve",
    "ShapeDiagnostic",
    "classify",
    "hunt_shape",
]
