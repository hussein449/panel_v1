"""Tier A adapter — vertical alignment, from the Copernicus DEM.

Elevation along the centreline, differenced into a gradient, averaged per unit. The
arithmetic is two lines. The measurement decision is the module.

**The baseline is the whole problem.** A DEM's vertical error does not cancel when you
difference two nearby pixels — it is amplified by the short distance you divide by. With
a local vertical error around 2 m, differencing over one 30 m pixel produces about *nine
percentage points* of pure noise, which is larger than any real highway grade. The same
error over 200 m produces about 1.4. So grade is measured over a **200 m baseline**, and
that number is chosen from the error budget rather than from the DEM's resolution:

    grade noise  ~  sqrt(2) * vertical_error / baseline

The HSM prices grade in bands at 3% and 6%, so the measurement has to separate 3 from 6.
A 1.4-point noise floor does; a 9-point one would produce a column of plausible-looking
numbers with no signal in it, on a factor that carries a cited weight.

The baseline is therefore part of the *definition* of the column, not an implementation
detail, and the registry says so. A grade measured over 30 m and a grade measured over
200 m are different quantities and must not be compared.

**GLO-30 is a surface model, not a terrain model.** Its elevation over a forested
cutting is the canopy, and a 30 m pixel is several times wider than a two-lane road. On
open ground along a road corridor that is usually harmless; through woodland it is not,
and the note says so on every run rather than only when someone asks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from roadrisk.core.contract import UNIT_COLUMN
from roadrisk.core.registry import Registry
from roadrisk.geo.adapters.base import (
    AdapterResult,
    SkippedFactor,
    require_slots,
    resolve,
)
from roadrisk.geo.adapters.rasters import COPERNICUS_DEM, PointSampler
from roadrisk.geo.adapters.sampling import stations_along, to_latlon
from roadrisk.geo.segmentation import Segmentation

FACTOR = "grade_pct"
ADAPTER = "copernicus_dem_glo30"
SLOTS: tuple[tuple[str, str], ...] = ((FACTOR, ADAPTER),)

#: Distance between elevation stations. A quarter of the baseline, so each gradient is
#: an independent-ish difference of stations two apart rather than a rolling average of
#: essentially the same two pixels.
STATION_INTERVAL_M = 50.0

#: Distance the elevation difference is taken over. See the module docstring — this is
#: an error-budget decision, not a resolution one.
BASELINE_M = 200.0

#: Local vertical error assumed when reporting the noise floor. Declared as a parameter
#: rather than buried, because every statement this module makes about how much of the
#: column is real depends on it.
ASSUMED_VERTICAL_ERROR_M = 2.0

#: Shortest baseline accepted near the corridor ends, where the full one does not fit.
MIN_BASELINE_M = 100.0


def compute_grade(
    segmentation: Segmentation,
    sampler: PointSampler,
    *,
    registry: Registry,
    station_interval_m: float = STATION_INTERVAL_M,
    baseline_m: float = BASELINE_M,
    assumed_vertical_error_m: float = ASSUMED_VERTICAL_ERROR_M,
    min_baseline_m: float = MIN_BASELINE_M,
) -> AdapterResult:
    """Absolute gradient per unit, in percent.

    Args:
        segmentation: Units covering the corridor.
        sampler: Anything that returns an elevation per (latitude, longitude). The
            default is :func:`~roadrisk.geo.adapters.rasters.elevation_sampler`; tests
            pass an analytic surface.
        registry: Supplies the tier and licence for the adapter slot.
        station_interval_m: Spacing of elevation stations along the centreline.
        baseline_m: Distance each gradient is measured over.
        assumed_vertical_error_m: Local DEM vertical error, used only to report the
            noise floor. It changes no value.
        min_baseline_m: Shortest baseline accepted near the corridor ends.

    Returns:
        An :class:`AdapterResult` carrying ``grade_pct``, or naming why it could not.
    """
    require_slots(registry, SLOTS)

    stations = stations_along(segmentation, station_interval_m)
    elevations = np.asarray(
        sampler(to_latlon(segmentation, stations.chainages)), dtype=float
    )

    grades, usable = _gradients(
        elevations, stations.chainages, baseline_m, min_baseline_m
    )
    coverage = float(usable.mean()) if len(usable) else 0.0
    noise_floor = _noise_floor(assumed_vertical_error_m, baseline_m)

    if not usable.any():
        return AdapterResult(
            name="grade",
            skipped=[
                SkippedFactor(
                    FACTOR,
                    ADAPTER,
                    f"{COPERNICUS_DEM.name} returned no elevation anywhere along this "
                    "centreline. The corridor is outside the DEM's coverage, or the "
                    "tiles it needs are not reachable",
                )
            ],
            notes=[
                f"No elevation was returned for any of {len(stations):,} stations. "
                "grade_pct is absent, not zero."
            ],
        )

    totals = np.bincount(
        stations.unit_index[usable], weights=grades[usable], minlength=stations.n_units
    ).astype(float)
    counted = np.bincount(
        stations.unit_index[usable], minlength=stations.n_units
    ).astype(float)

    blank = int((counted == 0).sum())
    if blank:
        return AdapterResult(
            name="grade",
            skipped=[
                SkippedFactor(
                    FACTOR,
                    ADAPTER,
                    f"{blank} of {stations.n_units} unit(s) have no usable elevation "
                    f"({coverage:.0%} of stations returned a value). Interpolating "
                    "across them would invent terrain, so the factor is absent rather "
                    "than partly guessed",
                )
            ],
            notes=[
                f"grade_pct: {coverage:.0%} of stations carried elevation, but "
                f"{blank} unit(s) had none at all."
            ],
        )

    unit_ids = pd.Index(segmentation.unit_ids, name=UNIT_COLUMN)
    values = pd.Series(totals / counted, index=unit_ids, dtype=float)

    source = (
        f"{COPERNICUS_DEM.name} sampled every {stations.interval_m:.0f} m along the "
        f"centreline and differenced over a {baseline_m:.0f} m baseline; each unit is "
        "the mean absolute gradient of its own stations. Read as COG windows over "
        "HTTPS range requests, never as whole tiles."
    )

    notes = [
        f"grade_pct is measured over a {baseline_m:.0f} m baseline. At an assumed "
        f"{assumed_vertical_error_m:.0f} m local vertical error that leaves a noise "
        f"floor of about {noise_floor:.1f} percentage points, which is why the baseline "
        f"is not the DEM's {COPERNICUS_DEM.resolution_m:.0f} m resolution: differencing "
        f"over one pixel would carry roughly "
        f"{_noise_floor(assumed_vertical_error_m, COPERNICUS_DEM.resolution_m):.0f} "
        "points of noise and swamp any real gradient. A grade measured over a different "
        "baseline is a different quantity and must not be compared with this one.",
        f"{COPERNICUS_DEM.name} is a DIGITAL SURFACE model: over woodland it returns the "
        "canopy, not the road, and its 30 m pixel is several times wider than a "
        "two-lane carriageway. Grades through cuttings and tree cover read less "
        "reliably than grades in the open.",
        f"ATTRIBUTION REQUIRED. {COPERNICUS_DEM.attribution}",
    ]
    if coverage < 1.0:
        notes.append(
            f"grade_pct: {1.0 - coverage:.0%} of stations had no usable elevation and "
            "were excluded. Every unit still carries at least one."
        )

    return AdapterResult(
        name="grade",
        resolved=[
            resolve(
                registry,
                FACTOR,
                ADAPTER,
                source=source,
                values=values,
                coverage=coverage,
                unit_coverage=pd.Series(
                    counted / np.maximum(stations.counts(), 1.0),
                    index=unit_ids,
                    dtype=float,
                ),
            )
        ],
        notes=notes,
    )


def _gradients(
    elevations: np.ndarray,
    chainages: np.ndarray,
    baseline_m: float,
    min_baseline_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Absolute percent gradient at every station, and which ones are usable.

    The lag is in stations rather than metres so the difference is always between two
    values that were actually sampled — interpolating the elevation profile first would
    smooth the very noise the baseline exists to control, and make the noise floor a
    claim rather than a bound.
    """
    count = len(elevations)
    interval = chainages[1] - chainages[0] if count > 1 else baseline_m
    lag = max(int(round(baseline_m / (2.0 * interval))), 1)

    grades = np.zeros(count, dtype=float)
    usable = np.zeros(count, dtype=bool)

    for index in range(count):
        low = max(index - lag, 0)
        high = min(index + lag, count - 1)
        span = chainages[high] - chainages[low]

        if span < min_baseline_m:
            continue
        if not (np.isfinite(elevations[low]) and np.isfinite(elevations[high])):
            continue

        grades[index] = abs(elevations[high] - elevations[low]) / span * 100.0
        usable[index] = True

    return grades, usable


def _noise_floor(vertical_error_m: float, baseline_m: float) -> float:
    """Grade noise in percentage points implied by independent errors at both ends."""
    return float(np.sqrt(2.0) * vertical_error_m / baseline_m * 100.0)


__all__ = [
    "ASSUMED_VERTICAL_ERROR_M",
    "BASELINE_M",
    "MIN_BASELINE_M",
    "SLOTS",
    "STATION_INTERVAL_M",
    "compute_grade",
]
