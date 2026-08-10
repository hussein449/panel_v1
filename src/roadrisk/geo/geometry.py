"""Tier A adapter — horizontal alignment, computed from the centreline alone.

No network, no API key, no external data. Curvature is pure geometry, which makes it
the cheapest genuinely useful factor in the registry and the natural first adapter.

**Why the line is resampled first.** Curvature computed from a line's own vertices
measures how the line was *digitised*, not how the road bends. A corridor traced with
vertices every 2 m and the same corridor traced every 20 m would produce different
curvature, because dense vertices amplify GPS jitter into false bends. Resampling to a
fixed interval removes that dependence.

**What resampling cannot do is rescue an under-sampled line.** If the source polyline
is coarser than the resample interval, the bend information is already gone: the chords
have cut the corners, and resampling merely interpolates *along* those chords. The
result is a sequence of near-straight runs meeting at artificially sharp corners, which
reads as much tighter curvature than the real road has. That is a data problem, not a
computation problem, so this module measures the source spacing and says so rather than
returning a confident wrong answer.

Feeds ``curve_radius_min`` and ``curve_density`` in the factor registry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from roadrisk.geo.corridor import CENTRELINE_GUIDANCE
from roadrisk.geo.segmentation import Segmentation

#: Spacing the centreline is resampled to before curvature is measured. Short enough to
#: resolve a tight bend, long enough not to amplify GPS jitter into false curvature.
DEFAULT_RESAMPLE_INTERVAL_M = 20.0

#: Radius at or below which a sample counts as "in a curve". Taken from the iRAP
#: boundary between "straight or gently curving" (>900 m) and "moderate curvature",
#: so the frequency measure and the iRAP severity weight agree on what a curve is.
DEFAULT_CURVE_THRESHOLD_M = 900.0

#: Tangents have infinite radius, which no transform can consume. The registry's `ln`
#: transform rejects infinity by design, so the adapter caps it here and the cap is
#: reported rather than hidden.
DEFAULT_MAX_RADIUS_M = 5000.0

CURVE_RADIUS_COLUMN = "curve_radius_min"
CURVE_DENSITY_COLUMN = "curve_density"


@dataclass(frozen=True)
class CurvatureResult:
    """Per-unit curvature, plus what it took to compute it."""

    values: pd.DataFrame
    resample_interval_m: float
    curve_threshold_m: float
    max_radius_m: float
    n_samples: int
    n_units_capped: int
    source_spacing_m: float

    @property
    def columns(self) -> list[str]:
        return [CURVE_RADIUS_COLUMN, CURVE_DENSITY_COLUMN]

    @property
    def under_sampled(self) -> bool:
        """True when the source line is too coarse to describe its own bends."""
        return self.source_spacing_m > self.resample_interval_m

    @property
    def notes(self) -> list[str]:
        notes = [
            f"Curvature measured on the centreline resampled to "
            f"{self.resample_interval_m:.0f} m spacing ({self.n_samples:,} samples), "
            "so the result does not depend on how densely the line was digitised.",
            f"A curve is a run of samples with radius <= "
            f"{self.curve_threshold_m:.0f} m (the iRAP straight/moderate boundary). "
            "A curve spanning a unit boundary is counted in both units, so densities "
            "must not be summed across units.",
        ]
        if self.under_sampled:
            notes.append(
                f"WARNING: the source centreline has a median vertex spacing of "
                f"{self.source_spacing_m:.0f} m, coarser than the "
                f"{self.resample_interval_m:.0f} m measurement interval. Its chords "
                "have already cut the corners, so resampling interpolates along "
                "straight segments meeting at artificially sharp joints. Curvature "
                "here reads TIGHTER than the real road and must not be trusted. "
                "Obtain a finer centreline, or raise the resample interval above the "
                "source spacing and accept coarser curvature.\n\n"
                + CENTRELINE_GUIDANCE
            )
        if self.n_units_capped:
            notes.append(
                f"{self.n_units_capped} unit(s) are effectively straight and had "
                f"curve_radius_min capped at {self.max_radius_m:.0f} m. The cap is a "
                "modelling choice, not a measurement — it sets how much credit a "
                "dead-straight segment gets."
            )
        return notes


def compute_curvature(
    segmentation: Segmentation,
    *,
    resample_interval_m: float = DEFAULT_RESAMPLE_INTERVAL_M,
    curve_threshold_m: float = DEFAULT_CURVE_THRESHOLD_M,
    max_radius_m: float = DEFAULT_MAX_RADIUS_M,
) -> CurvatureResult:
    """Minimum curve radius and curve density for every unit.

    Args:
        segmentation: Units covering the corridor.
        resample_interval_m: Spacing to resample the centreline to before measuring.
        curve_threshold_m: Radius at or below which a sample is "in a curve".
        max_radius_m: Cap applied to straight sections.

    Returns:
        A :class:`CurvatureResult` whose ``values`` frame is keyed by ``unit_id``.
    """
    corridor = segmentation.corridor
    chainages, points = _resample(corridor.geometry, resample_interval_m)
    radii = _radii(points, max_radius_m)

    rows = []
    capped = 0
    for unit in segmentation:
        inside = (chainages >= unit.start_m) & (chainages <= unit.end_m)
        unit_radii = radii[inside]

        if unit_radii.size == 0:
            minimum = max_radius_m
            density = 0.0
        else:
            minimum = float(min(unit_radii.min(), max_radius_m))
            density = _curve_runs(unit_radii, curve_threshold_m) / unit.length_km

        if minimum >= max_radius_m:
            capped += 1

        rows.append(
            {
                "unit_id": unit.unit_id,
                CURVE_RADIUS_COLUMN: minimum,
                CURVE_DENSITY_COLUMN: density,
            }
        )

    return CurvatureResult(
        values=pd.DataFrame(rows),
        resample_interval_m=resample_interval_m,
        curve_threshold_m=curve_threshold_m,
        max_radius_m=max_radius_m,
        n_samples=int(len(chainages)),
        n_units_capped=capped,
        source_spacing_m=_median_vertex_spacing(corridor.geometry),
    )


def _median_vertex_spacing(line) -> float:
    """Typical distance between the source line's own vertices.

    Median rather than mean: a single long straight run between two vertices should
    not make an otherwise well-traced corridor look under-sampled.
    """
    coords = np.asarray(line.coords, dtype=float)
    if len(coords) < 2:  # pragma: no cover - corridors always have 2+ vertices
        return float("inf")
    spacing = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    return float(np.median(spacing))


def _resample(line, interval_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Sample the line at fixed chainage spacing, always including both ends."""
    total = float(line.length)
    count = max(int(math.floor(total / interval_m)) + 1, 2)
    chainages = np.linspace(0.0, total, count)
    points = np.array(
        [(p.x, p.y) for p in (line.interpolate(float(c)) for c in chainages)]
    )
    return chainages, points


def _radii(points: np.ndarray, max_radius_m: float) -> np.ndarray:
    """Circumradius of every consecutive vertex triple.

    The radius of the circle through three points is ``abc / 4A``. Collinear points
    give zero area and infinite radius — a straight — which is capped.
    """
    if len(points) < 3:
        return np.full(len(points), max_radius_m)

    first, middle, last = points[:-2], points[1:-1], points[2:]

    a = np.linalg.norm(middle - first, axis=1)
    b = np.linalg.norm(last - middle, axis=1)
    c = np.linalg.norm(last - first, axis=1)

    # Twice the triangle area, via the 2-D cross product.
    cross = np.abs(
        (middle[:, 0] - first[:, 0]) * (last[:, 1] - first[:, 1])
        - (middle[:, 1] - first[:, 1]) * (last[:, 0] - first[:, 0])
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        radii = (a * b * c) / (2.0 * cross)

    radii = np.nan_to_num(radii, nan=max_radius_m, posinf=max_radius_m)
    radii = np.clip(radii, 0.0, max_radius_m)

    # Endpoints have no triple of their own; they inherit their neighbour's radius.
    return np.concatenate([[radii[0]], radii, [radii[-1]]])


def _curve_runs(radii: np.ndarray, threshold_m: float) -> int:
    """Count *runs* of consecutive bendy samples, not bendy samples.

    A 300 m sweeping bend is one curve, not fifteen. Counting samples would make
    curve density a measure of sampling rate.
    """
    bendy = radii <= threshold_m
    if not bendy.any():
        return 0
    starts = np.diff(bendy.astype(np.int8), prepend=0) == 1
    return int(starts.sum())


__all__ = [
    "CURVE_DENSITY_COLUMN",
    "CURVE_RADIUS_COLUMN",
    "DEFAULT_CURVE_THRESHOLD_M",
    "DEFAULT_MAX_RADIUS_M",
    "DEFAULT_RESAMPLE_INTERVAL_M",
    "CurvatureResult",
    "compute_curvature",
]
