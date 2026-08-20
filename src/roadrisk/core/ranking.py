"""Step 4.2 — which segments, in what order, and which ones sit together.

Two modes produce two different quantities. Mode A produces an expected crash rate
from a fitted model; Mode B produces a weighted index score from published weights.
They are not the same kind of number and never will be — but *"which bit of road do I
look at first"* is one question, and a report that answers it twice in two shapes has
made the reader do the joining.

So there is one ranked table. Both modes fill in ``unit_id``, ``rank``, ``percentile``
and ``score``, worst first. Mode A additionally fills in what it actually estimated —
observed, expected, an interval, exposure, rate. Mode B fills in none of those, and
they are **absent from its rows rather than present and null**, because a null count is
still a count-shaped hole that invites a reader to fill it.

**Blackspots are runs, not points.** A single bad segment is usually a bad segment; six
bad segments in a row is a length of road with a problem. Runs are built along the
corridor, and a run breaks wherever the road does — a missing unit, or a gap in
chainage between one unit's end and the next one's start. That is the difference
between "these eight units are one blackspot" and "these are two blackspots either side
of a junction the panel does not cover".

**On the interval.** It is a confidence interval on the *expected* count — where the
model's estimate of the mean sits — obtained by the delta method from the fit's own
parameter covariance. It is not a prediction interval for next year's actual count,
which would be wider and is a different question. When the fit clustered its standard
errors by unit, the covariance this reads is the clustered one, so the panel correction
from 3.1 travels into the ranking without being re-derived here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

#: Worst-quintile default. A blackspot list that flags half the corridor is a list
#: nobody acts on.
DEFAULT_THRESHOLD_PERCENTILE = 0.80

#: Two unit ends closer than this are treated as touching. Segmentation produces
#: contiguous units by construction, so this absorbs floating-point noise in the
#: chainage arithmetic and nothing else.
CHAINAGE_TOLERANCE_M = 0.5

#: 95%, matching the intervals everywhere else in the engine.
Z_95 = 1.959963984540054

MODE_A_BASIS = "expected crashes per unit of exposure, from the fitted model"
MODE_B_BASIS = "weighted index score from published weights — a ranking, not a rate"

ASSUMED_ORDER_NOTE = (
    "No corridor order was supplied, so units were taken in sorted id order and "
    "assumed adjacent. Segmentation numbers units along the chainage, so this holds "
    "for a panel this tool built — a panel assembled elsewhere may group units that "
    "are neighbours in name only."
)
NO_INTERVAL_NOTE = (
    "The fit did not expose a parameter covariance, so the ranking carries expected "
    "counts without an interval. The order is unaffected; the uncertainty around it "
    "is simply not reported rather than being guessed at."
)


@dataclass(frozen=True)
class UnitRisk:
    """One segment's place in the order, and what was actually estimated for it."""

    unit_id: str
    rank: int
    percentile: float
    score: float
    observed: int | None = None
    expected: float | None = None
    expected_low: float | None = None
    expected_high: float | None = None
    exposure: float | None = None
    rate: float | None = None
    #: Mode B's per-crash-type scores. A unit that ranks badly can be read for *why*.
    components: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialised form. Count-shaped fields are omitted, not nulled.

        Mode B has no predicted count and no interval. Emitting ``"expected": null``
        would put a count-shaped hole in the payload for a renderer to fill in with a
        dash, which reads as *"not available"* rather than *"this mode does not produce
        one"*. The keys are simply not there.
        """
        payload: dict[str, Any] = {
            "unit_id": self.unit_id,
            "rank": self.rank,
            "percentile": round(self.percentile, 6),
            "score": round(self.score, 9),
        }
        for name in (
            "observed",
            "expected",
            "expected_low",
            "expected_high",
            "exposure",
            "rate",
        ):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value if name == "observed" else round(value, 9)
        if self.components:
            payload["components"] = {
                key: round(value, 9) for key, value in self.components.items()
            }
        return payload


@dataclass(frozen=True)
class Blackspot:
    """A contiguous run of units that all rank in the worst band."""

    rank: int
    unit_ids: tuple[str, ...]
    worst_unit: str
    worst_rank: int
    score: float
    start_m: float | None = None
    end_m: float | None = None
    observed: int | None = None
    expected: float | None = None

    @property
    def n_units(self) -> int:
        return len(self.unit_ids)

    @property
    def length_m(self) -> float | None:
        if self.start_m is None or self.end_m is None:
            return None
        return round(self.end_m - self.start_m, 3)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rank": self.rank,
            "unit_ids": list(self.unit_ids),
            "n_units": self.n_units,
            "worst_unit": self.worst_unit,
            "worst_rank": self.worst_rank,
            "score": round(self.score, 9),
        }
        if self.start_m is not None and self.end_m is not None:
            payload["start_m"] = round(self.start_m, 3)
            payload["end_m"] = round(self.end_m, 3)
            payload["length_m"] = self.length_m
        if self.observed is not None:
            payload["observed"] = self.observed
        if self.expected is not None:
            payload["expected"] = round(self.expected, 9)
        return payload


@dataclass(frozen=True)
class Ranking:
    """One ranked table, whatever produced the numbers in it."""

    mode: str
    basis: str
    units: tuple[UnitRisk, ...] = ()
    blackspots: tuple[Blackspot, ...] = ()
    threshold_percentile: float = DEFAULT_THRESHOLD_PERCENTILE
    has_intervals: bool = False
    notes: tuple[str, ...] = ()

    @property
    def n_units(self) -> int:
        return len(self.units)

    def worst(self, n: int = 10) -> tuple[UnitRisk, ...]:
        return self.units[:n]

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame([unit.as_dict() for unit in self.units])

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "basis": self.basis,
            "threshold_percentile": self.threshold_percentile,
            "has_intervals": self.has_intervals,
            "n_units": self.n_units,
            "units": [unit.as_dict() for unit in self.units],
            "blackspots": [spot.as_dict() for spot in self.blackspots],
            "notes": list(self.notes),
        }


def rank_mode_a(
    predictions: pd.DataFrame,
    *,
    fit: Any = None,
    corridor_units: Sequence[tuple[str, float, float]] | None = None,
    threshold_percentile: float = DEFAULT_THRESHOLD_PERCENTILE,
) -> Ranking:
    """Rank segments by the rate the model expects of them.

    Args:
        predictions: One row per panel row — ``unit_id``, ``observed``, ``expected``,
            ``exposure``. The frame :func:`roadrisk.core.engine.assess` puts on the
            assessment.
        fit: The :class:`~roadrisk.core.models.base.FitResult`. Used only for its
            parameter covariance, and only to put an interval around the expected
            count. Ranking works without it.
        corridor_units: ``(unit_id, start_m, end_m)`` in corridor order, when the
            caller knows the geography. Supplies the run order, the chainage extents,
            and the gaps that break a run.
        threshold_percentile: Units at or above this percentile are blackspot
            candidates. The default flags the worst fifth.

    Returns:
        A :class:`Ranking`, worst first.
    """
    grouped = (
        predictions.groupby("unit_id", sort=False)[["observed", "expected", "exposure"]]
        .sum()
        .reset_index()
    )
    grouped["rate"] = grouped["expected"] / grouped["exposure"]

    bounds = _interval_by_unit(predictions, fit)
    notes: list[str] = [] if bounds else [NO_INTERVAL_NOTE]

    ordered = grouped.sort_values("rate", ascending=False, kind="mergesort")
    percentiles = ordered["rate"].rank(pct=True)

    units: list[UnitRisk] = []
    for position, (index, row) in enumerate(ordered.iterrows(), start=1):
        unit_id = str(row["unit_id"])
        low, high = bounds.get(unit_id, (None, None))
        units.append(
            UnitRisk(
                unit_id=unit_id,
                rank=position,
                percentile=float(percentiles.loc[index]),
                score=float(row["rate"]),
                observed=int(row["observed"]),
                expected=float(row["expected"]),
                expected_low=low,
                expected_high=high,
                exposure=float(row["exposure"]),
                rate=float(row["rate"]),
            )
        )

    return _assemble(
        mode="A",
        basis=MODE_A_BASIS,
        units=units,
        corridor_units=corridor_units,
        threshold_percentile=threshold_percentile,
        has_intervals=bool(bounds),
        notes=notes,
    )


def rank_mode_b(
    unit_ranking: pd.DataFrame,
    *,
    corridor_units: Sequence[tuple[str, float, float]] | None = None,
    threshold_percentile: float = DEFAULT_THRESHOLD_PERCENTILE,
) -> Ranking:
    """Put Mode B's index scores into the same table, and nothing else into it.

    Args:
        unit_ranking: :attr:`~roadrisk.core.models.index.IndexResult.unit_ranking` —
            one row per unit with ``score`` and any ``score_<crash type>`` columns.
        corridor_units: As :func:`rank_mode_a`.
        threshold_percentile: As :func:`rank_mode_a`.

    Returns:
        A :class:`Ranking` carrying scores and crash-type components. No count, no
        interval, no exposure — Mode B estimates none of them, and the row shape says
        so by leaving them out.
    """
    components = [c for c in unit_ranking.columns if c.startswith("score_")]
    ordered = unit_ranking.sort_values("score", ascending=False, kind="mergesort")
    percentiles = ordered["score"].rank(pct=True)

    units = [
        UnitRisk(
            unit_id=str(row["unit_id"]),
            rank=position,
            percentile=float(percentiles.loc[index]),
            score=float(row["score"]),
            components={
                name.removeprefix("score_"): float(row[name])
                for name in components
                if pd.notna(row[name])
            },
        )
        for position, (index, row) in enumerate(ordered.iterrows(), start=1)
    ]

    return _assemble(
        mode="B",
        basis=MODE_B_BASIS,
        units=units,
        corridor_units=corridor_units,
        threshold_percentile=threshold_percentile,
        has_intervals=False,
        notes=[],
    )


def find_blackspots(
    units: Sequence[UnitRisk],
    *,
    corridor_units: Sequence[tuple[str, float, float]] | None = None,
    threshold_percentile: float = DEFAULT_THRESHOLD_PERCENTILE,
) -> tuple[Blackspot, ...]:
    """Group flagged units into contiguous runs along the road.

    A run continues only while the next unit is both flagged and physically adjacent.
    Adjacency is decided by chainage when ``corridor_units`` supplies it: a unit whose
    start does not meet the previous unit's end is the far side of a gap, and a
    blackspot that spanned it would be describing road the panel does not cover.

    Without ``corridor_units`` the order is the sorted unit ids and adjacency is
    positional — the same assumption the spatial field makes, recorded in the
    ranking's notes rather than left implicit.
    """
    flagged = {u.unit_id: u for u in units if u.percentile >= threshold_percentile}
    if not flagged:
        return ()

    runs: list[list[UnitRisk]] = []
    current: list[UnitRisk] = []
    previous_end: float | None = None

    for unit_id, start_m, end_m in _walk_order(units, corridor_units):
        risk = flagged.get(unit_id)
        broken = risk is None or (
            previous_end is not None
            and start_m is not None
            and abs(start_m - previous_end) > CHAINAGE_TOLERANCE_M
        )
        if broken and current:
            runs.append(current)
            current = []
        if risk is not None:
            current.append(risk)
            previous_end = end_m
        else:
            previous_end = None
    if current:
        runs.append(current)

    spots = [_blackspot(run, corridor_units) for run in runs]
    spots.sort(key=lambda spot: spot.worst_rank)
    return tuple(
        Blackspot(**{**spot.__dict__, "rank": position})
        for position, spot in enumerate(spots, start=1)
    )


# ---- internals ---------------------------------------------------------------


def _assemble(
    *,
    mode: str,
    basis: str,
    units: list[UnitRisk],
    corridor_units: Sequence[tuple[str, float, float]] | None,
    threshold_percentile: float,
    has_intervals: bool,
    notes: list[str],
) -> Ranking:
    if corridor_units is None:
        notes = [*notes, ASSUMED_ORDER_NOTE]
    return Ranking(
        mode=mode,
        basis=basis,
        units=tuple(units),
        blackspots=find_blackspots(
            units,
            corridor_units=corridor_units,
            threshold_percentile=threshold_percentile,
        ),
        threshold_percentile=threshold_percentile,
        has_intervals=has_intervals,
        notes=tuple(notes),
    )


def _walk_order(
    units: Sequence[UnitRisk],
    corridor_units: Sequence[tuple[str, float, float]] | None,
) -> list[tuple[str, float | None, float | None]]:
    """The order to walk the corridor in, with chainage when it is known."""
    if corridor_units is not None:
        return [(str(u), float(s), float(e)) for u, s, e in corridor_units]
    return [(unit_id, None, None) for unit_id in sorted(u.unit_id for u in units)]


def _blackspot(
    run: list[UnitRisk],
    corridor_units: Sequence[tuple[str, float, float]] | None,
) -> Blackspot:
    extents = (
        {str(u): (float(s), float(e)) for u, s, e in corridor_units}
        if corridor_units is not None
        else {}
    )
    ids = [risk.unit_id for risk in run]
    worst = min(run, key=lambda risk: risk.rank)
    starts = [extents[i][0] for i in ids if i in extents]
    ends = [extents[i][1] for i in ids if i in extents]
    observed = [risk.observed for risk in run if risk.observed is not None]
    expected = [risk.expected for risk in run if risk.expected is not None]

    return Blackspot(
        rank=0,  # replaced once the runs are ordered against each other
        unit_ids=tuple(ids),
        worst_unit=worst.unit_id,
        worst_rank=worst.rank,
        score=float(np.mean([risk.score for risk in run])),
        start_m=min(starts) if starts else None,
        end_m=max(ends) if ends else None,
        observed=int(sum(observed)) if len(observed) == len(run) else None,
        expected=float(sum(expected)) if len(expected) == len(run) else None,
    )


def _interval_by_unit(
    predictions: pd.DataFrame, fit: Any
) -> Mapping[str, tuple[float, float]]:
    """Delta-method interval on each unit's expected count.

    The expected count for a unit is the sum of its rows' fitted means. Its gradient
    with respect to the coefficients is ``sum(mu_r * x_r)``, because a log link makes
    ``d(mu)/d(beta) = mu * x``. The variance is then that gradient through the fit's
    own parameter covariance — clustered, when the fit clustered it.

    Returns an empty mapping when the fit cannot supply a covariance, which is a
    reason to report no interval rather than to invent one.
    """
    raw = getattr(fit, "raw", None)
    model = getattr(raw, "model", None)
    exog = getattr(model, "exog", None)
    if raw is None or exog is None:
        return {}

    try:
        exog = np.asarray(exog, dtype=float)
        n_mean_params = exog.shape[1]
        covariance = np.asarray(raw.cov_params(), dtype=float)[
            :n_mean_params, :n_mean_params
        ]
    except (AttributeError, ValueError, IndexError, TypeError):  # pragma: no cover
        return {}

    mu = predictions["expected"].to_numpy(dtype=float)
    if len(mu) != len(exog):  # pragma: no cover - alignment already guaranteed
        return {}

    bounds: dict[str, tuple[float, float]] = {}
    weighted = exog * mu[:, None]
    for unit_id, positions in _positions_by_unit(predictions).items():
        total = float(mu[positions].sum())
        if total <= 0:  # pragma: no cover - exposure is strictly positive
            continue
        gradient = weighted[positions].sum(axis=0)
        variance = float(gradient @ covariance @ gradient)
        if not math.isfinite(variance) or variance < 0:  # pragma: no cover
            continue
        spread = Z_95 * math.sqrt(variance) / total
        bounds[unit_id] = (total * math.exp(-spread), total * math.exp(spread))
    return bounds


def _positions_by_unit(predictions: pd.DataFrame) -> dict[str, np.ndarray]:
    units = predictions["unit_id"].to_numpy()
    return {
        str(unit_id): np.flatnonzero(units == unit_id) for unit_id in pd.unique(units)
    }


__all__ = [
    "DEFAULT_THRESHOLD_PERCENTILE",
    "Blackspot",
    "Ranking",
    "UnitRisk",
    "find_blackspots",
    "rank_mode_a",
    "rank_mode_b",
]
